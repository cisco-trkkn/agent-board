"""Normalised event stream over Claude Code transcripts (the only module that knows the format).

iter_events(root, repos, days) yields dicts with kind in usage | tool_use | tool_result | injection |
system | prompt, plus session, agent, ts, file (schema: .superpowers/sdd/.../context.md).
repos=None / days=None disable the scope / window filters.

Semantics aligned with the independent tools/usage-sum.py (no code shared):
  * usage = any complete line whose message has a usage dict and a model other than None/"<synthetic>",
    whatever the line type; the latest line per requestId wins (the same request repeats once per content
    block, `apiBlockIndex`); a line without requestId is keyed by file:offset.
  * dedupe is global across files (older mtime first); scope and window are judged on the winning line.
  * scope: cwd == repo or under repo/.claude/worktrees/; window: line timestamp >= local midnight
    (days - 1) days back.
  * a final line not ending in "\\n" is skipped; undecodable lines are skipped.
Non-usage events are emitted per line as read, with the same scope/window test; a line without cwd
inherits the last cwd seen in its file (for non-usage events only: usage-sum does not inherit).
"""
import glob
import hashlib
import json
import os
import re
from datetime import datetime, timedelta

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_SUB = re.compile(r"[/\\]subagents[/\\]agent-([^/\\]+)\.jsonl$")


def window_start(days):
    today = datetime.now().date()
    return datetime.combine(today - timedelta(days=days - 1), datetime.min.time()).timestamp()


def in_repo(cwd, repos):
    for repo in repos:
        repo = repo.rstrip("/")
        if cwd == repo or cwd.startswith(repo + "/.claude/worktrees/"):
            return True
    return False


def _ts(v):
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError, TypeError):
        return None


def _agent(path, d):
    m = _SUB.search(path)
    if m:
        return "sub:" + m.group(1)
    if d.get("agentName"):
        return "team:" + str(d["agentName"])
    return "main"


def _session(path, d):
    return d.get("sessionId") or os.path.splitext(os.path.basename(path))[0]


def load_session_meta(path):
    """Meta of a subagent file (<agent>.meta.json beside the jsonl), or {}."""
    meta = os.path.splitext(path)[0] + ".meta.json"
    try:
        with open(meta) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _target(inp):
    if isinstance(inp, dict):
        for k in ("file_path", "path", "command", "pattern"):
            if isinstance(inp.get(k), str):
                return inp[k]
    return None


def _size(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text", "")) if isinstance(b, dict) and isinstance(b.get("text"), str)
                   else len(json.dumps(b)) for b in content)
    return 0 if content is None else len(json.dumps(content))


def _line_events(d, path, ts, agent, session):
    base = {"session": session, "agent": agent, "ts": ts, "file": path}
    t = d.get("type")
    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
    content = msg.get("content")
    if t == "assistant" and isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                inp = b.get("input")
                yield dict(base, kind="tool_use", tool=b.get("name"), tool_use_id=b.get("id"),
                           args_key=hashlib.sha1(json.dumps(inp, sort_keys=True).encode()).hexdigest()[:12],
                           target=_target(inp))
    elif t == "user":
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    yield dict(base, kind="tool_result", tool_use_id=b.get("tool_use_id"),
                               size=_size(b.get("content")), is_error=bool(b.get("is_error")))
        text = _text_of(content)
        spans = _REMINDER.findall(text)
        for s in spans:
            yield dict(base, kind="injection", source="system-reminder", size=len(s))
        human = _REMINDER.sub("", text).strip()
        if human and not d.get("isMeta") and not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in (content if isinstance(content, list) else [])):
            yield dict(base, kind="prompt", size=len(human), text_head=human[:200])
    elif t == "attachment":
        a = d.get("attachment") if isinstance(d.get("attachment"), dict) else {}
        ev = dict(base, kind="injection", source="attachment:%s" % a.get("type"), size=len(json.dumps(a)))
        if a.get("type") == "hook_additional_context":
            ev["hook_event"] = a.get("hookEvent")   # None when the attachment has no hookEvent
        yield ev
    elif t == "system":
        yield dict(base, kind="system", subtype=d.get("subtype"), raw_keys=sorted(d.keys()))
        if d.get("hookAdditionalContext"):
            infos = d.get("hookInfos")
            ev = "unknown"
            if isinstance(infos, list) and infos and isinstance(infos[0], dict):
                ev = infos[0].get("event") or infos[0].get("hookEvent") or "unknown"
            yield dict(base, kind="injection", source="hook:%s" % ev, size=len(json.dumps(d["hookAdditionalContext"])))


def iter_events(root, repos, days):
    start = window_start(days) if days is not None else None
    files = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
    files = [f for f in files if start is None or os.path.getmtime(f) >= start]
    usage = {}
    for path in sorted(files, key=os.path.getmtime):
        last_cwd = ""
        with open(path, "rb") as fh:
            pos = 0
            for raw in fh:
                at, pos = pos, pos + len(raw)
                if not raw.endswith(b"\n"):
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                if d.get("cwd"):
                    last_cwd = d["cwd"]
                msg = d.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("usage"), dict) and msg.get("model") not in (None, "<synthetic>"):
                    usage[d.get("requestId") or "%s:%d" % (path, at)] = (path, d)
                ts = _ts(d.get("timestamp"))
                if repos is not None and not in_repo(d.get("cwd") or last_cwd, repos):
                    continue
                if start is not None and (ts is None or ts < start):
                    continue
                for ev in _line_events(d, path, ts, _agent(path, d), _session(path, d)):
                    yield ev
    for key, (path, d) in usage.items():
        ts = _ts(d.get("timestamp"))
        if repos is not None and not in_repo(d.get("cwd") or "", repos):
            continue
        if start is not None and (ts is None or ts < start):
            continue
        u = d["message"]["usage"]
        yield {"kind": "usage", "session": _session(path, d), "agent": _agent(path, d), "ts": ts, "file": path,
               "request_id": d.get("requestId") or key, "model": d["message"]["model"],
               "input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
               "cache_read": u.get("cache_read_input_tokens") or 0,
               "cache_creation": u.get("cache_creation_input_tokens") or 0}
