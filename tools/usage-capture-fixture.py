#!/usr/bin/env python3
"""Capture a content-stripped usage fixture from a Claude Code transcript.

usage: usage-capture-fixture.py <src.jsonl> <dst.jsonl>

Reads the source read-only. Writes a header line naming the source, keeps `cost-state`
lines whole, and reduces every usage-bearing line to the fields the usage indexer reads.
Everything else (prompts, replies, tool results) is dropped. /Users/<name> in cwd becomes /home/u.
"""
import json
import re
import sys
from datetime import date

KEEP = ("type", "requestId", "timestamp", "cwd", "sessionId", "gitBranch", "effort",
        "isSidechain", "agentName", "teamName")


def strip(d):
    out = {k: d[k] for k in KEEP if k in d}
    if "cwd" in out:
        out["cwd"] = re.sub(r"^/Users/[^/]+", "/home/u", out["cwd"])
    m = d["message"]
    out["message"] = {k: m[k] for k in ("model", "usage") if k in m}
    return out


def capture(src, dst):
    n = 0
    with open(src, encoding="utf-8", errors="replace") as fi, open(dst, "w", encoding="utf-8") as fo:
        fo.write(json.dumps({"_fixture_source": src, "_captured": date.today().isoformat()}) + "\n")
        for raw in fi:
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("type") == "cost-state":
                fo.write(json.dumps(d) + "\n")
            elif isinstance(d.get("message"), dict) and d["message"].get("usage"):
                fo.write(json.dumps(strip(d)) + "\n")
            else:
                continue
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(capture(sys.argv[1], sys.argv[2]))
