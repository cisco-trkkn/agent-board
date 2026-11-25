#!/usr/bin/env python3
"""metrics_lead: the lead fields of a run record, from the lineage file and the lead transcripts.

Pure and read-only: imports ctxsize and the standard library only. Never raises; what cannot be computed is None
and its name goes in "missing". The returned dict holds numbers only (no session id, path or file name).
Definitions (lead session, successor, read set...): docs/superpowers/plans/2026-11-20-efficiency-now.md, Metric definitions."""
import glob
import json
import os
import re
import shlex

import ctxsize

PHRASE = "continue from where the previous session left off"
HEAD_LINES = 200
FIRST_TURNS = 10
READERS = {"cat", "sed", "head", "tail", "grep"}
SEGMENT = re.compile(r"\|\||&&|[|;\n]")


def _lines(path, limit=None):
    """Parsed dict lines of a file (bad lines skipped), at most `limit` raw lines read. [] when unreadable."""
    out = []
    try:
        with open(path, "rb") as f:
            for i, raw in enumerate(f):
                if limit is not None and i >= limit:
                    break
                try:
                    d = json.loads(raw.decode("utf-8", "replace"))
                except (ValueError, RecursionError):
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        return []
    return out


def lineage(lineage_file):
    """The valid lineage lines (dicts with a numeric ts), sorted by ts."""
    out = []
    for d in _lines(lineage_file):
        try:
            d["ts"] = float(d["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(d)
    out.sort(key=lambda d: d["ts"])
    return out


def _text(d):
    m = d.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


_open = open          # seam: tests count file opens
_loads = json.loads   # seam: tests count JSON parses
_HEADS = {}           # tdir -> {path: ((mtime_ns, size), phrase_dicts, first_epoch)}
_RESULTS = {}         # (tdir, doc basename, old session id) -> (dir signature, path or None)
_PHRASE_B = PHRASE.encode()


def cache_clear():
    _HEADS.clear()
    _RESULTS.clear()


def _head_entry(p):
    """(phrase_dicts, first_epoch) of a transcript head. Only lines whose raw bytes hold PHRASE are parsed for
    matching; the first epoch (base rule: first timestamp of any head line) is read only when such a line exists."""
    raws = []
    try:
        with _open(p, "rb") as f:
            for i, raw in enumerate(f):
                if i >= HEAD_LINES:
                    break
                raws.append(raw)
    except OSError:
        return [], float("inf")

    def parse(raw):
        try:
            d = _loads(raw.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            return None
        return d if isinstance(d, dict) else None
    hits = [d for d in (parse(r) for r in raws if _PHRASE_B in r) if d is not None]
    if not hits:
        return [], float("inf")
    first = float("inf")
    for raw in raws:
        d = parse(raw)
        e = ctxsize._epoch(d.get("timestamp")) if d is not None else None
        if e is not None:
            first = e
            break
    return hits, first


def _heads(tdir):
    """The dir's cached heads, refreshed for new or changed files, removed files dropped. Returns (heads, signature)."""
    cache = _HEADS.setdefault(tdir, {})
    seen, sig = set(), []
    for p in sorted(glob.glob(os.path.join(glob.escape(tdir), "*.jsonl"))):
        try:
            st = os.stat(p)
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        seen.add(p)
        sig.append((p, key))
        if p not in cache or cache[p][0] != key:
            hits, first = _head_entry(p)
            cache[p] = (key, hits, first)
    for p in [p for p in cache if p not in seen]:
        del cache[p]
    return cache, tuple(sig)


def successor(tdir, line):
    """Path of the line's successor transcript, or None (Metric definitions: successor)."""
    try:
        base = os.path.basename(str(line.get("doc") or ""))
        old = str(line.get("old_session_id") or "")
        if not base:
            return None
        tdir = str(tdir)
        heads, sig = _heads(tdir)
        rkey = (tdir, base, old)
        got = _RESULTS.get(rkey)
        if got and got[0] == sig:
            return got[1]
        best = None
        for p in sorted(heads):
            if os.path.basename(p)[:-6] == old:
                continue
            _, hits, first = heads[p]
            if not any(d.get("type") == "user" and "agentName" not in d and base in (t := _text(d)) and PHRASE in t
                       for d in hits):
                continue
            if best is None or first < best[0]:
                best = (first, p)
        out = best[1] if best else None
        _RESULTS[rkey] = (sig, out)
        return out
    except Exception:
        return None


def _first_n_requests(lines, n):
    """Lines of main-thread assistant turns (usage present) restricted to the first n distinct requestIds."""
    seen, out = {}, []
    for d in lines:
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        m = d.get("message")
        if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
            continue
        rid = d.get("requestId") or id(d)
        if rid not in seen:
            seen[rid] = len(seen)
        if n is None or seen[rid] < n:
            out.append(d)
    return out


def _abs(tok, cwd):
    return os.path.normpath(tok if os.path.isabs(tok) else os.path.join(cwd or "", tok))


def read_set(transcript, first_turns=None):
    """Normalised paths of existing files the session read (Metric definitions: read set)."""
    out = set()
    try:
        for d in _first_n_requests(_lines(transcript), first_turns):
            cwd = d.get("cwd") if isinstance(d.get("cwd"), str) else ""
            content = d["message"].get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict) or b.get("type") != "tool_use" or not isinstance(b.get("input"), dict):
                    continue
                inp = b["input"]
                if b.get("name") == "Read" and isinstance(inp.get("file_path"), str):
                    cands = [inp["file_path"]]
                elif b.get("name") == "Bash" and isinstance(inp.get("command"), str):
                    cands = []
                    for seg in SEGMENT.split(inp["command"]):
                        try:
                            toks = shlex.split(seg)
                        except ValueError:
                            continue
                        if toks and os.path.basename(toks[0]) in READERS:
                            cands += [t for t in toks[1:] if not t.startswith("-")]
                else:
                    continue
                for c in cands:
                    p = _abs(c, cwd)
                    if os.path.isfile(p):
                        out.add(p)
    except Exception:
        pass
    return out


def _lead_sessions(tdir, lines, lo, hi):
    paths = []
    inside = [l for l in lines if lo <= l["ts"] <= hi]
    before = [l for l in lines if l["ts"] < lo]
    for l in inside:
        paths.append(os.path.join(tdir, str(l.get("old_session_id")) + ".jsonl"))
        paths.append(successor(tdir, l))
    if before:
        paths.append(successor(tdir, before[-1]))
    return {p for p in paths if p and os.path.isfile(p)}


def lead_session_ids(tdir, lineage_file, lo, hi):
    """Session ids of the lead sessions of [lo, hi] (old sessions and successors of the lineage lines); set() on error."""
    try:
        return {os.path.basename(p)[:-6] for p in _lead_sessions(str(tdir), lineage(lineage_file), float(lo), float(hi))}
    except Exception:
        return set()


def _fields(tdir, lineage_file, lo, hi, prev_end):
    lines = lineage(lineage_file)
    peak = None
    for p in _lead_sessions(tdir, lines, lo, hi):
        n = ctxsize.peak(p, lo, hi)
        if n is not None and (peak is None or n > peak):
            peak = n
    counted = [l for l in lines if (lo <= l["ts"] <= hi if prev_end is None else prev_end < l["ts"] <= hi)]
    post, rer = [], []
    for l in counted:
        succ = successor(tdir, l)
        old = os.path.join(tdir, str(l.get("old_session_id")) + ".jsonl")
        post.append(ctxsize.first_turns_tokens(succ, FIRST_TURNS) if succ else None)
        rer.append(len(read_set(succ, FIRST_TURNS) & read_set(old)) if succ and os.path.isfile(old) else None)
    return peak, len(counted), post, rer


def lead_fields(tdir, lineage_file, lo, hi, prev_end=None):
    try:
        peak, n, post, rer = _fields(str(tdir), lineage_file, float(lo), float(hi),
                                     None if prev_end is None else float(prev_end))
    except Exception:
        peak, n, post, rer = None, 0, [], []
    missing = []
    if peak is None:
        missing.append("lead_context_peak")
    if any(x is None for x in post):
        missing.append("post_handoff_tokens")
    if any(x is None for x in rer):
        missing.append("rereads")
    return {"lead_context_peak": peak, "lead_handoffs": n, "post_handoff_tokens": post, "rereads": rer,
            "missing": missing}
