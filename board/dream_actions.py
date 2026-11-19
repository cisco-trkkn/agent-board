#!/usr/bin/env python3
"""dream_actions: Revert and File proposals of the nightly memory run (Task 5, G8-G9, S10).

Both take the context lock for at most 3 s (`busy` when it stays held: the board's overview tick must not wait longer) and
return the result text the Discord click audits and the CLI prints. Path helpers come from dream_paths, never dream.py.
Nothing inside `context.locked` calls `context.add` (lockf is per process: a nested add would drop the lock)."""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context  # noqa: E402
import dream_paths as P  # noqa: E402

WAIT = 3
MAX_FILE = 20
OBSERVER_TIMEOUT = 10


def _atomic(path, text):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _append_missing(text, rows):
    have = {l for _, l in context.entries(text)}
    for section, line in rows:
        if line not in have:
            text = context._insert(text, section, line)
            have.add(line)
    return text


def revert(project, run):
    try:
        lock = context.locked(project, wait=WAIT)
        lock.__enter__()
    except ValueError as e:
        return "busy" if "locked by another writer" in str(e) else "unknown"
    try:
        state = P.load(project)
        if state.get("reverted") == run:
            return "already reverted"
        bc, ba = P.backup_core(project, run), P.backup_archive(project, run)
        after = P.run_dir(project, run) / "out" / "core.after.md"
        if not P.RUN_ID_RE.match(run or "") or not (bc.is_file() and ba.is_file() and after.is_file()):
            return "unknown"
        newer = state.get("run")
        if not newer:
            return "unknown"
        if newer != run:
            return f"stale: newer run {newer}"
        cp, ap = context.context_path(project), context.archive_path(project)
        live_core = cp.read_text() if cp.is_file() else ""
        live_arch = ap.read_text() if ap.is_file() else None
        kept = {l for _, l in context.entries(after.read_text())}
        extra = [(s, l) for s, l in context.entries(live_core) if l not in kept]
        new_core = _append_missing(bc.read_text(), extra)
        arch_before = ba.read_text()
        for path, text in ((P.backups_dir() / f"{project}.md.{run}.pre-revert", live_core),
                           (P.backups_dir() / f"{project}.archive.md.{run}.pre-revert", live_arch or "")):
            if not path.exists():   # a crashed first attempt already saved the real pre-revert state
                path.write_text(text)
        if arch_before:
            _atomic(ap, arch_before)
        else:
            ap.unlink(missing_ok=True)
        _atomic(cp, new_core)
        state["reverted"] = run
        state.pop("sources_digest", None)
        P.save(project, state)
        return "reverted"
    finally:
        lock.__exit__(None, None, None)


def pid(kind, text):
    return hashlib.sha1((kind + "\0" + text).encode()).hexdigest()[:12]


def _glob_observer():
    found = glob.glob(str(Path.home() / ".claude" / "plugins" / "**" / "task-observer" / "scripts" / "new-observation.sh"), recursive=True)
    return max(found, key=os.path.getmtime) if found else None


def _observer_script():
    s = os.environ.get("TC_OBSERVER_SCRIPT")
    if s:
        return s if os.path.isfile(s) else None
    return _glob_observer()


def _slug(text, ident):
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return f"dream-{words}-{ident[:6]}" if words else f"dream-{ident}"


def _file_observer(script, p):
    """-> None when written, else the reason the proposal stays unfiled."""
    ws = os.environ.get("TASK_OBSERVER_WORKSPACE") or str(Path.home() / ".task-observer")
    try:
        r = subprocess.run(["bash", script, _slug(p["text"], pid("observer", p["text"])), ws],
                           capture_output=True, text=True, timeout=OBSERVER_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return "script failed"
    out = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode != 0 or not out.startswith("/"):
        return "script failed"
    ev = "\n".join(f"- {e}" for e in p.get("evidence", []))
    with open(out, "a") as f:
        f.write(f"{p['text']}\n\nEvidence (nightly memory run):\n{ev}\n")
    return None


def _filed_path(project):
    return P.project_dir(project) / "filed.json"


def _filed(project):
    try:
        v = json.loads(_filed_path(project).read_text())
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def file_proposals(project, run=None):
    import ideas
    try:
        lock = context.locked(project, wait=WAIT)
        lock.__enter__()
    except ValueError as e:
        return "busy" if "locked by another writer" in str(e) else "unknown"
    try:
        run = run or P.load(project).get("run")
        if not P.RUN_ID_RE.match(run or ""):
            return "unknown"
        rp = P.run_dir(project, run) / "out" / "report.json"
        try:
            props = json.loads(rp.read_text()).get("proposals")
        except (OSError, ValueError, AttributeError):
            return "unknown"
        props = [p for p in props or [] if isinstance(p, dict) and p.get("kind") in ("idea", "observer") and p.get("text")]
        if not props:
            return "no proposals"
        done = _filed(project)
        todo = [p for p in props if pid(p["kind"], p["text"]) not in done]
        if not todo:
            return "already filed"
        n = skipped = 0
        script = None
        for p in todo[:MAX_FILE]:
            ident = pid(p["kind"], p["text"])
            if p["kind"] == "idea":
                ideas.add(project, p["text"], detail="evidence: " + "; ".join(str(e) for e in p.get("evidence", [])))
            else:
                script = script or _observer_script()
                if not script:
                    skipped += 1
                    reason = "no task-observer script"
                    continue
                why = _file_observer(script, p)
                if why:
                    skipped += 1
                    reason = why
                    continue
            done.append(ident)
            P.project_dir(project).mkdir(parents=True, exist_ok=True)
            _atomic(_filed_path(project), json.dumps(done))
            n += 1
        return f"filed {n}" + (f", skipped {skipped} observer ({reason})" if skipped else "")
    finally:
        lock.__exit__(None, None, None)
