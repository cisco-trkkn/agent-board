#!/usr/bin/env python3
"""scout_eval: the trend scout's evaluate step. run_evaluate asks the model, validate keeps only sound entries, pick
chooses the drafts. See docs/superpowers/specs/2026-11-13-trend-scout-design.md §3."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream  # noqa: E402
import findings  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EVAL_TIMEOUT = 900
MAX_PICKS = 3
MAX_OTHERS = 10
VALUES = ("high", "medium", "low")
EFFORTS = ("S", "M", "L")


def _parse_result(text):
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines[1:]).strip()
    return json.loads(t)


def run_evaluate(run_dir, root):
    """(failure text or None, entries or None, info). Writes evaluate.json only on success."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evaluate.json").unlink(missing_ok=True)   # a failed run must not leave an earlier answer
    prompt = (REPO / "claude" / "scout-evaluate.md").read_text() + "\n\nItems: items.json in the current directory\nContext: context-pack.md in the current directory\n"
    argv = [os.environ.get("TC_SCOUT_CLAUDE") or "claude", "-p", "--model", "sonnet", "--effort", "medium", "--permission-mode", "dontAsk",
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--output-format", "json",
            "--allowedTools", "Read,Grep,Glob,WebFetch", "--add-dir", str(root)]
    env = {k: v for k, v in os.environ.items() if k not in dream.SCRUB}
    try:
        proc = subprocess.Popen(argv, cwd=str(run_dir), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError:
        return "model error", None, {}
    try:
        out, _err = proc.communicate(prompt, timeout=EVAL_TIMEOUT)
    except subprocess.TimeoutExpired:
        dream._kill_group(proc)
        return "model timeout", None, {}
    try:
        (run_dir / "model-output-evaluate.txt").write_text(out or "")
    except OSError:
        pass
    if proc.returncode != 0:
        return f"model exit {proc.returncode}", None, {}
    res = None
    for cand in (out, *reversed(out.strip().splitlines())):
        try:
            res = json.loads(cand)
            break
        except ValueError:
            continue
    if not isinstance(res, dict) or res.get("is_error") is not False or not isinstance(res.get("result"), str):
        return "model error", None, {}
    try:
        parsed = _parse_result(res["result"])
    except ValueError:
        return "model error", None, {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("entries"), list):
        return "model error", None, {}
    u = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    info = {"cost_usd": res.get("total_cost_usd"), "usage": u, "model_s": (res.get("duration_ms") or 0) / 1000}
    (run_dir / "evaluate.json").write_text(json.dumps({"entries": parsed["entries"]}, indent=1))
    return None, parsed["entries"], info


def finding_key(item_key, component):
    return f"{item_key}:{'-'.join(str(component).lower().split())}"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def validate(entries, items, st, info=None):
    """Valid entries, each with `key` (finding key), item `url` and `published` added. Counts each drop reason in info["dropped"]."""
    info = info if info is not None else {}
    dropped = info.setdefault("dropped", {})
    by_key = {i["key"]: i for i in items if isinstance(i, dict) and "key" in i}
    urls = {i.get("url") for i in by_key.values()}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    out = []
    for e in entries:
        if not isinstance(e, dict):
            drop("malformed")
            continue
        if e.get("item") not in by_key:
            drop("unknown item")
            continue
        ev = e.get("evidence")
        ev = [x for x in ev if isinstance(x, dict)] if isinstance(ev, list) else []
        if not any(isinstance(x.get("quote"), str) and x["quote"].strip() for x in ev):
            drop("no quote")
            continue
        if e.get("value") not in VALUES or e.get("effort") not in EFFORTS:
            drop("bad value or effort")
            continue
        if not all(x.get("url") in urls for x in ev):
            drop("url not an item url")
            continue
        comp = e.get("component")
        if not isinstance(comp, str) or not comp.strip():
            drop("malformed")
            continue
        key = finding_key(e["item"], comp)
        count = len(ev)
        if key in st["filed"]:
            drop("filed")
            continue
        if findings.dismissed_blocks(st, key, count):
            drop("dismissed")
            continue
        rep = st["reported"].get(key)
        if rep:
            last = _num(rep.get("last_evidence_count"))
            if not (count > last and count >= findings.REGROWTH * last):
                drop("reported")
                continue
        it = by_key[e["item"]]
        out.append(dict(e, key=key, url=it.get("url"), published=it.get("published")))
    return out


def pick(valid, revise_first, queued_specs):
    """{"revisions", "picks", "notes", "others"}: revisions first, then by value, effort, newest item; at most 3 together."""
    queued = set(queued_specs)
    rank = sorted(valid, key=lambda e: (VALUES.index(e["value"]), EFFORTS.index(e["effort"]), -_ts(e.get("published"))))
    revisions = list(revise_first)[:MAX_PICKS]
    picks, notes, others = [], [], []
    for e in rank:
        spec = next((o for o in e.get("overlaps") or [] if o in queued), None)
        if spec:
            notes.append(f"{spec}: could use {e['what_it_enables']} ({e.get('url') or e['evidence'][0].get('url')})")
        elif len(revisions) + len(picks) < MAX_PICKS:
            picks.append(e)
        else:
            others.append(e)
    return {"revisions": revisions, "picks": picks, "notes": notes, "others": others[:MAX_OTHERS]}


def _ts(published):
    """Sortable number for an ISO date or datetime; a missing or odd date sorts oldest."""
    if not isinstance(published, str):
        return 0
    digits = "".join(c for c in published[:19] if c.isdigit())
    return int(digits.ljust(14, "0")) if digits else 0
