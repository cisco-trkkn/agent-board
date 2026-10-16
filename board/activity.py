"""activity: agent test/build runs recorded by `tmux-ctl run`, their logs, and the command feed."""
import os
import re
from pathlib import Path

from artifacts import jsonl, state_dir

HEAD_RE = re.compile(r"^── (\d\d:\d\d:\d\d) · (.*?) · (.*) · exit (-?\d+)(?: · @(\d+))?$")


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


def feed(project, limit=200):
    out = []
    for wi, win in enumerate(("tests", "shell")):
        p = state_dir() / f"feed-{project}-{win}.log"
        if not p.exists():
            continue
        cur = None
        for line in p.read_text(errors="replace").splitlines():
            m = HEAD_RE.match(line)
            if m:
                cur = {"win": win, "time": m[1], "agent": m[2], "cwd": m[3], "exit": int(m[4]), "cmd": "", "tail": "",
                       "epoch": int(m[5]) if m[5] else 0, "_pos": (len(out), wi)}
                out.append(cur)
            elif cur is not None and line.startswith("$ ") and not cur["cmd"]:
                cur["cmd"] = line[2:]
            elif cur is not None and line.strip():
                cur["tail"] = f"{cur['tail']}\n{line}" if cur["tail"] else line
    # merge by epoch; lines from before the epoch was written (epoch 0) keep each file's append order
    out.sort(key=lambda b: (b["epoch"], b["_pos"][1], b["_pos"][0]) if b["epoch"] else (0, b["_pos"][1], b["_pos"][0]))
    for b in out:
        del b["_pos"]
    return out[-limit:]
