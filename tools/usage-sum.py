#!/usr/bin/env python3
"""Independent API-equivalent cost sum over Claude Code transcripts, to cross-check the board's Usage tab.

usage: usage-sum.py --repo <path> [--days 30] [--root ~/.claude/projects] [--prices board/prices.json]

Deliberately shares no code with board/usage.py (only board/prices.json is read, as data), so a bug in
the indexer cannot hide in this check. Prints: month=<dollars, 2dp> calls=<n> unpriced=<n>
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta

RATE_KEYS = (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_input_tokens"))


def model_id(name):
    name = name or ""
    if name.endswith("[1m]"):
        name = name[:-4]
    return re.sub(r"-[0-9]{8}$", "", name)


def window_start(days):
    today = datetime.now().date()
    return datetime.combine(today - timedelta(days=days - 1), datetime.min.time()).timestamp()   # local midnight


def in_repo(cwd, repo):
    repo = repo.rstrip("/")
    return cwd == repo or cwd.startswith(repo + "/.claude/worktrees/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--prices", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board", "prices.json"))
    a = ap.parse_args()
    with open(a.prices) as fh:
        rates = json.load(fh)["models"]
    start = window_start(a.days)
    calls = {}   # request id -> latest line seen for it
    files = glob.glob(os.path.join(a.root, "**", "*.jsonl"), recursive=True)
    for path in sorted(files, key=os.path.getmtime):   # older files first, so a newer line wins
        with open(path, "rb") as fh:
            pos = 0
            for raw in fh:
                at, pos = pos, pos + len(raw)
                if not raw.endswith(b"\n"):
                    continue   # a line still being written
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict) or msg.get("model") in (None, "<synthetic>"):
                    continue
                calls[d.get("requestId") or f"{path}:{at}"] = d
    total, n, unpriced = 0.0, 0, 0
    for d in calls.values():
        if not in_repo(d.get("cwd") or "", a.repo):
            continue
        try:
            when = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError, AttributeError):
            continue
        if when < start:
            continue
        n += 1
        use, rate = d["message"]["usage"], rates.get(model_id(d["message"]["model"]))
        if rate is None:
            unpriced += 1
            continue
        split = use.get("cache_creation") or {}
        w5, w1 = split.get("ephemeral_5m_input_tokens"), split.get("ephemeral_1h_input_tokens")
        if w5 is None and w1 is None:
            w5, w1 = use.get("cache_creation_input_tokens") or 0, 0
        cost = sum((use.get(field) or 0) * (rate[k] or 0) for k, field in RATE_KEYS)
        cost += (w5 or 0) * (rate["cache_write_5m"] or 0) + (w1 or 0) * (rate["cache_write_1h"] or 0)
        total += cost / 1e6
    print(f"month={total:.2f} calls={n} unpriced={unpriced}")


if __name__ == "__main__":
    sys.exit(main())
