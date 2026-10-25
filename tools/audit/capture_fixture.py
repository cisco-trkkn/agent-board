#!/usr/bin/env python3
"""Cut a redacted fixture from a real transcript.

usage: capture_fixture.py <src.jsonl|src_dir> <dst.jsonl|dst_dir> [--max-lines N]

A file is rewritten line by line, keeping only structural keys (type, subtype, requestId, timestamp, cwd,
sessionId, isSidechain, isMeta, agentName, teamName, message.model, message.usage, attachment.type,
hookInfos, hookAdditionalContext) plus message.content with all free text replaced by "x" * min(len, 50)
and a "_len" key holding the original length. tool_use blocks keep name, id and input; input strings become
"<redacted:len=N>" except file_path / path / command, which keep their value with /Users/<name> -> /home/u
and secret-shaped tokens masked. First output line is a fixture-header. A directory is captured recursively
(*.jsonl redacted; *.meta.json reduced to non-descriptive keys).
"""
import argparse
import json
import os
import re
import sys
from datetime import date

KEEP = ("type", "subtype", "requestId", "timestamp", "cwd", "sessionId", "isSidechain", "isMeta", "agentName", "teamName")
KEEP_PATH = ("file_path", "path", "command")
_HOME = re.compile(r"/Users/[^/\s\"']+")
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,}|AIza[0-9A-Za-z_-]{20,}|"
                     r"xox[abprs]-[A-Za-z0-9-]{8,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+|[A-Za-z0-9+/=_-]{32,}|"
                     r"(?i:(?:token|secret|password|passwd|api[_-]?key|authorization)\s*[=:]\s*\S+))")


def _x(s):
    return "x" * min(len(s), 50)


def _path_value(s):
    if re.search(r"(?i)password|passwd|glpat|sk-ant|AKIA|BEGIN [A-Z ]*KEY|ghp_|api[_-]?key|secret|token", s):
        return "<redacted-command:secret-words>"   # a command that names secrets is dropped whole
    s = _SECRET.sub("<secret>", _HOME.sub("/home/u", s))
    return re.sub(r"(?i)francisco[.\w-]*", "u", s)[:200]


def _input(v, key=None):
    if isinstance(v, str):
        return _path_value(v) if key in KEEP_PATH else "<redacted:len=%d>" % len(v)
    if isinstance(v, dict):
        return {k: _input(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_input(x, key) for x in v]
    return v


def _text(s):
    return {"text": _x(s), "_len": len(s)}


def _block(b):
    if not isinstance(b, dict):
        return {"type": "unknown"}
    t = b.get("type")
    if t == "tool_use":
        return {"type": t, "id": b.get("id"), "name": b.get("name"), "input": _input(b.get("input"))}
    if t == "tool_result":
        c = b.get("content")
        out = {"type": t, "tool_use_id": b.get("tool_use_id"), "is_error": bool(b.get("is_error"))}
        if isinstance(c, str):
            out["content"] = _x(c); out["_len"] = len(c)
        else:
            n = len(json.dumps(c)) if c is not None else 0
            out["content"] = _x("x" * n); out["_len"] = n
        return out
    if t in ("text", "thinking"):
        return dict({"type": t}, **_text(b.get("text") or b.get("thinking") or ""))
    return {"type": t}


def _list_redacted(v):
    return [_x(i) if isinstance(i, str) else {"type": "redacted"} for i in v]


def redact_line(d):
    out = {k: d[k] for k in KEEP if k in d}
    if isinstance(out.get("cwd"), str):
        out["cwd"] = _HOME.sub("/home/u", out["cwd"])
    m = d.get("message")
    if isinstance(m, dict):
        mo = {}
        for k in ("model", "usage", "role"):
            if k in m:
                mo[k] = m[k]
        c = m.get("content")
        if isinstance(c, str):
            mo["content"] = _x(c); mo["_len"] = len(c)
        elif isinstance(c, list):
            mo["content"] = [_block(b) for b in c]
        out["message"] = mo
    a = d.get("attachment")
    if isinstance(a, dict):
        out["attachment"] = {k: a[k] for k in ("type", "hookEvent") if k in a}
        out["attachment"]["_len"] = len(json.dumps(a))
    if isinstance(d.get("hookInfos"), list):
        out["hookInfos"] = [{"command": "<redacted>", "durationMs": h.get("durationMs")} for h in d["hookInfos"] if isinstance(h, dict)]
    if isinstance(d.get("hookAdditionalContext"), list):
        out["hookAdditionalContext"] = _list_redacted(d["hookAdditionalContext"])
    return out


def capture_file(src, dst, max_lines=None):
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    n = 0
    with open(src, "rb") as fi, open(dst, "w") as fo:
        fo.write(json.dumps({"type": "fixture-header", "source": os.path.basename(src), "captured": date.today().isoformat()}) + "\n")
        for raw in fi:
            if max_lines is not None and n >= max_lines:
                break
            if not raw.endswith(b"\n"):
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if isinstance(d, dict):
                fo.write(json.dumps(redact_line(d)) + "\n")
                n += 1
    return n


def capture_meta(src, dst):
    with open(src) as fh:
        d = json.load(fh)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with open(dst, "w") as fo:
        json.dump({k: d[k] for k in ("agentType", "spawnDepth", "requestShape", "model") if k in d}, fo)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--max-lines", type=int, default=None)
    a = ap.parse_args(argv)
    if os.path.isdir(a.src):
        for dp, _, fs in os.walk(a.src):
            for f in sorted(fs):
                rel = os.path.relpath(os.path.join(dp, f), a.src)
                s, t = os.path.join(dp, f), os.path.join(a.dst, rel)
                if f.endswith(".meta.json"):
                    capture_meta(s, t)
                elif f.endswith(".jsonl"):
                    capture_file(s, t, a.max_lines)
    else:
        capture_file(a.src, a.dst, a.max_lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
