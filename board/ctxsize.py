#!/usr/bin/env python3
"""ctxsize: the one reader of a transcript's context size.

Context size of a turn = input_tokens + cache_read_input_tokens + cache_creation_input_tokens of a main-thread
(isSidechain false) assistant line with usage. Lines sharing a requestId are one turn; the last line wins.
CLI: ctxsize.py last <transcript> | peak <transcript> [--since ISO] [--until ISO] | doc <handoff doc>. Prints the number
(or the doc line), or nothing; always exits 0."""
import json
import sys
from datetime import datetime

BLOCK = 1 << 20


def _size(d):
    """Context size of one parsed line, or None when it is not a main-thread assistant turn with usage."""
    if not isinstance(d, dict) or d.get("type") != "assistant" or d.get("isSidechain"):
        return None
    u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
    if not isinstance(u, dict):
        return None
    try:
        return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    except (TypeError, ValueError):
        return None


def _output(d):
    try:
        return int(d["message"]["usage"].get("output_tokens") or 0)
    except (TypeError, ValueError, KeyError, AttributeError):
        return 0


def _parse(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None


def _epoch(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def context_tokens(transcript_path):
    """Context size at the last main-thread assistant turn, or None. Reads the file from its end, a block at a time."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            pos, tail = f.tell(), b""
            while pos > 0:
                step = min(BLOCK, pos)
                pos -= step
                f.seek(pos)
                lines = (f.read(step) + tail).split(b"\n")
                tail = lines[0] if pos > 0 else b""
                for raw in reversed(lines[1:] if pos > 0 else lines):
                    if b'"assistant"' in raw:
                        n = _size(_parse(raw))
                        if n is not None:
                            return n
    except OSError:
        return None
    return None


def peak(transcript_path, since=None, until=None):
    """Largest context size over the main-thread assistant turns with since <= timestamp <= until (epoch seconds;
    None = open), or None when no turn is in the window."""
    best = None
    try:
        with open(transcript_path, "rb") as f:
            for raw in f:
                if b'"assistant"' not in raw:
                    continue
                d = _parse(raw)
                n = _size(d)
                if n is None:
                    continue
                if since is not None or until is not None:
                    ts = _epoch(d.get("timestamp"))
                    if ts is None or (since is not None and ts < since) or (until is not None and ts > until):
                        continue
                if best is None or n > best:
                    best = n
    except OSError:
        return None
    return best


def turns(transcript_path):
    """One dict per main-thread turn in file order: {"ts", "context", "total"}; lines sharing a requestId collapse to
    the last one. [] for an unreadable file."""
    out, at = [], {}
    try:
        with open(transcript_path, "rb") as f:
            for raw in f:
                if b'"assistant"' not in raw:
                    continue
                d = _parse(raw)
                n = _size(d)
                if n is None:
                    continue
                t = {"ts": _epoch(d.get("timestamp")), "context": n, "total": n + _output(d)}
                rid = d.get("requestId")
                if rid is not None and rid in at:
                    out[at[rid]] = t
                else:
                    if rid is not None:
                        at[rid] = len(out)
                    out.append(t)
    except OSError:
        return []
    return out


def first_turns_tokens(transcript_path, n=10):
    """Sum of total over the first n turns, or None when there are none."""
    t = turns(transcript_path)[:n]
    return sum(x["total"] for x in t) if t else None


DOC_BUDGET = 3000


def doc_estimate(path, budget=DOC_BUDGET):
    """(line, over) for a handoff doc: tokens = characters / 4; a section starts at a line beginning "## " and the text
    before the first one is "(top)". None when the file cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    sections, name = {}, "(top)"
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            name = line[3:].strip() or "(untitled)"
        sections[name] = sections.get(name, 0) + len(line)
    total = len(text) // 4
    over = total > budget
    line = f"handoff doc: {total} tokens (budget {budget}): {'over' if over else 'ok'}"
    if over and sections:
        big = max(sections, key=sections.get)
        line += f"; largest section: {big} ({sections[big] // 4} tokens)"
    return line, over


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(a) == 2 and a[0] == "last":
            n = context_tokens(a[1])
        elif len(a) >= 2 and a[0] == "peak":
            opt = dict(zip(a[2::2], a[3::2]))
            n = peak(a[1], _epoch(opt.get("--since")) if "--since" in opt else None,
                     _epoch(opt.get("--until")) if "--until" in opt else None)
        elif len(a) == 2 and a[0] == "doc":
            got = doc_estimate(a[1])
            if got:
                print(got[0])
            return 0
        else:
            n = None
    except Exception:
        n = None
    if n is not None:
        print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
