#!/usr/bin/env python3
"""improve_pick: the improve tick's pick step (spec 2026-11-16 §2; plan Task 9). Fills the free trial slots (at most MAX_TRIALS
at once) with the top proposals of one mechanical-tier ranking call. A ranking failure picks nothing and writes one
`improve_rank_failed` event. The tick calls pick(store, runs, tick_id) through improve_eval.HOOK_MODULES.
Protected (docs/superpowers/improve/protected.txt). Test: tests/test_improve_pick.py."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ROUTING = REPO / "docs" / "superpowers" / "model-routing.json"
RANK_TIMEOUT = 300
MAX_TRIALS = 2
MAX_OUTPUT_TOKENS = 2000


def _parse_result(text):
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines[1:]).strip()
    return json.loads(t)


def _candidates(rows):
    running = {r["target"] for r in rows if r["state"] == "trial"}
    return [r for r in rows if r["state"] == "proposed" and r["class"] in ("low", "high") and r["patch"] is not None
            and r["target"] not in running]


def _prompt(cands, outcomes):
    by_id = {o.get("id"): o for o in outcomes}
    items = []
    for r in cands:
        try:
            ev = json.loads(r["evidence"]) if r["evidence"] else []
        except ValueError:
            ev = r["evidence"]
        items.append({"id": r["id"], "kind": r["kind"], "target": r["target"], "evidence": ev,
                      "outcome": by_id.get(r["outcome"], r["outcome"])})
    active = [o for o in outcomes if o.get("state") == "active"]
    return ((REPO / "claude" / "improve-rank.md").read_text() + "\n\nCandidates:\n" + json.dumps(items, indent=1, default=str)
            + "\n\nActive outcomes:\n" + json.dumps(active, indent=1, default=str) + "\n")


def _rank(prompt, ids):
    """(failure text or None, ordered ids or None)."""
    try:
        model = json.loads(ROUTING.read_text())["mechanical"]
        # The prompt carries adapter-fed targets and evidence and the reply is a list of ids: the call gets no tool, no
        # MCP server, no skill and leaves no session (as dream.run_model, minus its file tools).
        argv = [os.environ.get("TC_IMPROVE_CLAUDE") or "claude", "-p", "--model", model, "--effort", "low", "--restricted",
                "--tools", "", "--permission-mode", "dontAsk", "--strict-mcp-config", "--disable-slash-commands",
                "--no-session-persistence", "--output-format", "json"]
    except (OSError, ValueError, KeyError):
        return "no mechanical model", None
    env = {k: v for k, v in os.environ.items() if k not in dream.SCRUB}
    try:
        proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    except OSError:
        return "model error", None
    try:
        out, _err = proc.communicate(prompt, timeout=RANK_TIMEOUT)
    except subprocess.TimeoutExpired:
        dream._kill_group(proc)
        return "model timeout", None
    if proc.returncode != 0:
        return f"model exit {proc.returncode}", None
    res = None
    for cand in (out, *reversed(out.strip().splitlines())):
        try:
            res = json.loads(cand)
            break
        except ValueError:
            continue
    if not isinstance(res, dict) or res.get("is_error") is not False or not isinstance(res.get("result"), str):
        return "model error", None
    u = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    toks = u.get("output_tokens")
    if not isinstance(toks, int) or isinstance(toks, bool) or toks > MAX_OUTPUT_TOKENS:
        return "output tokens over limit", None
    try:
        parsed = _parse_result(res["result"])
    except ValueError:
        return "bad reply", None
    if not isinstance(parsed, list) or not all(isinstance(i, str) and i in ids for i in parsed) or len(set(parsed)) != len(parsed):
        return "bad reply", None
    return None, parsed


def _failed(store, why, tick_id):
    c = store._conn()
    try:
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, NULL, NULL, 'improve_rank_failed', ?)",
                  (store.now(), json.dumps({"reason": why, "tick": tick_id})))
    finally:
        c.close()


def pick(store, runs, tick_id, outcomes=None):
    """Start the top proposals of one ranking call, up to the free trial slots. Returns the ids started."""
    rows = store.list()
    free = MAX_TRIALS - sum(1 for r in rows if r["state"] == "trial")
    cands = _candidates(rows)
    if free <= 0 or not cands:
        return []
    if outcomes is None:
        import improve
        outcomes = improve.load_outcomes()
    why, ranked = _rank(_prompt(cands, outcomes), {r["id"] for r in cands})
    if why:
        _failed(store, why, tick_id)
        return []
    started = []
    for pid in ranked[:free]:
        store.transition(pid, "trial", "ranked", trial_started_at=store.now())
        started.append(pid)
    return started
