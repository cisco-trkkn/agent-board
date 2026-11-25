#!/usr/bin/env python3
"""lead_state: <discord dir>/lead-state.json for each project with a Discord bridge (spec 2026-11-23-remote-lead-liveness §1).

tick(records, now, *, holder_of, sid_of, home) is called after each overview build. `records` are overview.build()'s
project records; holder_of(project) -> bool (the lead pane holds the project's bot); sid_of(project) -> the lead's session
id or "". No LLM, no network. A failing project is logged and skipped. The file:
  {"at", "state": busy|ready|needs_you|down, "since", "tool", "queued", "last_read_text", "last_read_message_id",
   "holder", "reason", "window"}
`last_read_message_id`, `reason` (why down) and `window` are additions to the spec's schema (plan assumption A2).
"""
import argparse
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import tc_env  # noqa: E402

TAIL = 1024 * 1024   # bytes of the lead transcript read from its end
READ_MAX = 200
CHANNEL = "plugin:discord:discord"
_TAG = re.compile(r'<channel source="plugin:discord:discord"([^>]*)>(.*?)</channel>', re.S)
_MID = re.compile(r'\bmessage_id="([^"]+)"')
_cache = {}   # transcript path -> ((size, mtime_ns), info)
_paths = {}   # session id -> transcript path
_lock = threading.Lock()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def classify(rec, holder):
    """(state, reason): down when the lead is missing or nobody holds the bot, needs_you when the lead pane waits on a
    dialog or permission prompt, busy while it works, else ready."""
    status = (rec.get("lead") or {}).get("status")
    if status in (None, "missing"):
        return "down", "no claude in the lead window"
    if not holder:
        return "down", "bot not held"
    if status == "waiting":
        return "needs_you", None
    if status == "working":
        return "busy", None
    return "ready", None


def lead_tool(rec):
    return next((a.get("tool") for a in rec.get("agents") or [] if a.get("window") == "claude"), None)


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, size - TAIL)
        f.seek(start)
        data = f.read().decode("utf-8", "replace")
    lines = data.splitlines()
    return lines[1:] if start > 0 else lines   # the first line of a mid-file read is partial


def transcript_info(path):
    """(last_read_text, last_read_message_id, queued) from the transcript's tail; (None, None, 0) when unreadable.
    Cached by (size, mtime): an unchanged file is not read again."""
    if not path:
        return None, None, 0
    try:
        stt = os.stat(path)
    except OSError:
        return None, None, 0
    key = (stt.st_size, stt.st_mtime_ns)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    carried = hit[1][:2] if hit else (None, None)   # the last read of an earlier tail of this same file
    text = mid = None
    pending = []   # queued prompt contents, FIFO
    try:
        lines = _tail_lines(path)
    except OSError:
        return None, None, 0
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        if r.get("type") == "queue-operation":
            op, c = r.get("operation"), r.get("content")
            if op == "enqueue":
                pending.append(c if isinstance(c, str) else "")
            elif op == "dequeue" and pending:
                pending.pop(0)
            elif op == "remove" and c in pending:
                pending.remove(c)
            elif op == "popAll":
                pending.clear()
            continue
        o = r.get("origin") or {}
        if r.get("type") == "user" and not r.get("isSidechain") and o.get("kind") == "channel" and o.get("server") == CHANNEL:
            ms = list(_TAG.finditer(_text((r.get("message") or {}).get("content"))))
            if ms:
                m = ms[-1]   # a row can hold several tags: the newest is the last
                text = m.group(2).strip()[:READ_MAX]
                mm = _MID.search(m.group(1))
                mid = mm.group(1) if mm else None
    if text is None:   # no channel row in this tail (the read slid out of the window): carry the earlier one forward
        text, mid = carried
    info = (text, mid, sum(1 for c in pending if f'<channel source="{CHANNEL}"' in c))
    _cache[path] = (key, info)
    return info


def transcript_path(home, sid):
    """<home>/projects/*/<sid>.jsonl, or None. The hit is cached per session id."""
    if not sid or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        return None
    p = _paths.get(sid)
    if p and os.path.isfile(p):
        return p
    hits = sorted(Path(home).glob(f"projects/*/{sid}.jsonl"))
    if not hits:
        return None
    _paths[sid] = str(hits[0])
    return _paths[sid]


def read(path):
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def compute(rec, holder, info, prev, now):
    state, reason = classify(rec, holder)
    since = prev.get("since") if prev and prev.get("state") == state and isinstance(prev.get("since"), str) else iso(now)
    text, mid, queued = info
    if text is None and prev:   # no cache entry (board restart) and none in the tail: the file's own last read
        text, mid = prev.get("last_read_text"), prev.get("last_read_message_id")
    return {"at": iso(now), "state": state, "since": since, "tool": lead_tool(rec) if state == "busy" else None,
            "queued": queued, "last_read_text": text, "last_read_message_id": mid, "holder": bool(holder),
            "reason": reason, "window": "claude"}


def write(path, obj):
    """Atomic: a temp file unique to this process and thread, then rename."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def tick(records, now, *, holder_of, sid_of, home):
    for r in records:
        p = r.get("project")
        try:
            d = tc_env.discord_dir(p)
            if not (d / "bridge.json").is_file():
                continue
            holder = bool(holder_of(p))
            info = transcript_info(transcript_path(home, sid_of(p) or ""))
            with _lock:   # read-modify-write of `since`: one writer at a time in this process
                f = d / "lead-state.json"
                write(f, compute(r, holder, info, read(f), now))
        except Exception as e:   # noqa: BLE001 - one project's failure never breaks the overview or the next project
            print(f"lead_state: {p}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _holder_and_sid(project):
    """(holder, session id) for `project`, the way server.lead_state_tick looks them up (imports server: heavy, CLI only)."""
    os.environ.setdefault("TMUX_DASH_TOKEN", "local")
    import server  # noqa: PLC0415
    import planview  # noqa: PLC0415
    raw = server.tmux("display", "-p", "-t", f"={project}:claude", "#{pane_id}\t#{pane_pid}").strip()
    holder = False
    if raw:
        pane, ppid = raw.split("\t")
        holder = pane in server.discord_leads([(pane, int(ppid))])
    return holder, planview.lead_entry(project, Path.home() / ".claude", server.tmux)[0]


def main(argv=None):
    """--dry-run [--project P]: print what tick would write for each bridged project; write nothing."""
    import time  # noqa: PLC0415
    ap = argparse.ArgumentParser(prog="lead_state")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project")
    a = ap.parse_args(argv)
    if not a.dry_run:
        ap.print_usage(sys.stderr)
        return 2
    import overview  # noqa: PLC0415
    ov = overview.board_overview() or overview.local_overview()
    now = time.time()
    for r in ov["projects"]:
        p = r.get("project")
        if a.project and p != a.project:
            continue
        d = tc_env.discord_dir(p)
        if not (d / "bridge.json").is_file():
            continue
        holder, sid = _holder_and_sid(p)
        info = transcript_info(transcript_path(Path.home() / ".claude", sid))
        f = d / "lead-state.json"
        print(json.dumps({"project": p, "file": str(f), "would_write": compute(r, holder, info, read(f), now)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
