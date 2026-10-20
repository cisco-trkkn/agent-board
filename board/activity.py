"""activity: agent test/build runs recorded by `tmux-ctl run`, their logs."""
import os
from pathlib import Path

from artifacts import jsonl, state_dir

def runs(project, limit=100):
    latest = {}
    for r in jsonl(state_dir() / f"runs-{project}.jsonl"):
        if r.get("id"):
            latest[r["id"]] = r  # the final record replaces the start record
    return sorted(latest.values(), key=lambda r: r.get("ts") or 0, reverse=True)[:limit]


def log_text(project, run_id, max_bytes=512_000):
    root = (state_dir() / "logs" / project).resolve()
    for r in reversed(jsonl(state_dir() / f"runs-{project}.jsonl")):
        if r.get("id") == run_id:
            p = Path(r.get("log") or "").resolve()
            if not str(p).startswith(str(root) + os.sep):
                raise FileNotFoundError(run_id)
            return p.read_bytes()[-max_bytes:].decode("utf-8", "replace")
    raise FileNotFoundError(run_id)
