"""artifacts: the session artifact manifest written by ~/.claude/hooks/artifact-register.sh.

summary() for the board's panel, read() of allowlisted files only, save() with a hash check,
and CommentQueue: plan comments typed into the lead's pane, never while it shows a prompt.
"""
import hashlib
import re
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

HOOK = Path.home() / ".claude" / "hooks" / "artifact-register.sh"


def state_dir():
    return Path(os.environ.get("TC_STATE") or f"{os.environ.get('TMPDIR', '/tmp').rstrip('/')}/tmux-ctl-{os.getuid()}")


def jsonl(path):
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def entries(project):
    return jsonl(state_dir() / f"artifacts-{project}.jsonl")


def lineage(project):
    return jsonl(state_dir() / f"lineage-{project}.jsonl")


def summary(project):
    by = {}
    for e in entries(project):
        key = e.get("url") or e.get("path")
        if not key:
            continue
        it = by.setdefault(key, {"path": e.get("path", ""), "kind": e.get("kind", "other"), "url": e.get("url", ""), "history": []})
        it["history"].append({k: e.get(k) for k in ("ts", "agent", "hash", "epoch")})
    items = []
    for it in by.values():
        it["latest"] = it["history"][-1]
        items.append(it)
    items.sort(key=lambda i: i["latest"]["ts"] or 0, reverse=True)
    lin = lineage(project)
    epoch = len(lin)
    plans = [i for i in items if i["kind"] == "plan"]
    # a worker's plan in its own worktree must not take the pin: prefer the lead's plans, then this epoch, then the newest
    lead = [i for i in plans if i["latest"].get("agent") in ("claude", "you") or "/.claude/worktrees/" not in i["path"]]
    plans = [i for i in lead if (i["latest"].get("epoch") or 0) == epoch] or lead   # no lead plan: no pin
    return {"epoch": len(lin), "lineage": lin, "items": items,
            "active_plan": plans[0]["path"] if plans else None,
            "started_from": lin[-1].get("doc") if lin else None}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def read(project, path):
    if not any(e.get("path") == path and not e.get("url") for e in entries(project)):
        raise FileNotFoundError(path)
    data = Path(path).read_bytes()
    return {"path": path, "text": data.decode("utf-8", "replace"), "hash": _sha(data)}


class Conflict(Exception):
    def __init__(self, current):
        super().__init__("the file changed since you loaded it")
        self.current = current


def save(project, path, base_hash, text):
    cur = read(project, path)  # also the allowlist check
    if cur["hash"] != base_hash:
        raise Conflict(cur)
    p = Path(path)
    tmp = p.with_name(f".{p.name}.tmux-dash.tmp")
    tmp.write_text(text)
    os.replace(tmp, p)
    subprocess.run([str(HOOK), "--path", path, "--agent", "you", "--project", project],
                   capture_output=True, timeout=10, env={**os.environ, "TC_STATE": str(state_dir())})
    return read(project, path)


def _flat(s, limit):
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(s or "")).split())[:limit]


class CommentQueue:
    """Plan comments waiting for the lead, per session. Delivered by typing one line into the claude pane."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}

    def add(self, sess, path, anchor, quote, note):
        note = _flat(note, 2000)
        if not note:
            raise ValueError("write a note")
        c = {"id": uuid.uuid4().hex[:8], "path": path, "anchor": _flat(anchor, 80), "quote": _flat(quote, 200),
             "note": note, "ts": time.time()}
        with self._lock:
            self._items.setdefault(sess, []).append(c)
        return c

    def add_line(self, sess, text):
        """Queue one literal line for the lead (board requests). A line already waiting is not queued twice."""
        text = _flat(text, 2000)
        if not text:
            raise ValueError("empty line")
        with self._lock:
            items = self._items.setdefault(sess, [])
            for c in items:
                if c.get("text") == text:
                    return c
            c = {"id": uuid.uuid4().hex[:8], "text": text, "ts": time.time()}
            items.append(c)
        return c

    def pending(self, sess):
        with self._lock:
            return list(self._items.get(sess, []))

    @staticmethod
    def line(c):
        if "text" in c:
            return c["text"]
        where = f" § {c['anchor']}" if c["anchor"] else ""
        quote = f' "{c["quote"]}"' if c["quote"] else ""
        return f"[Plan comment] {_flat(Path(c['path']).name, 120)}{where}:{quote} — {c['note']}"

    def deliver(self, sess, pane, kind, status, send, input_has_text=None):
        """send(pane, text) types text + Enter. Holds everything while the lead shows a prompt or is not running."""
        if kind != "claude" or status == "waiting":
            return 0
        if input_has_text and input_has_text(pane):   # never glue a comment onto what the user is typing
            return 0
        with self._lock:
            items = self._items.pop(sess, [])
        for n, c in enumerate(items):
            try:
                send(pane, self.line(c))
            except Exception:
                with self._lock:
                    self._items[sess] = items[n:] + self._items.get(sess, [])
                return n
        return len(items)
