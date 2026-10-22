#!/usr/bin/env python3
"""Validate a docs-compose Sources block: python3 sources_check.py <file|->"""
import json, re, sys

TYPES = ("architecture", "runbook", "report", "explainer")
KINDS = [r"file:[^:\s]+:\d+(-\d+)?", r"inventory:\S+", r"interview:\d+", r"cloud:\d+",
         r"mr:[\w./-]+!\d+", r"commit:[0-9a-f]{7,40}", r"artefact:[^:\s]+(:\d+)?", r"section:.+@rev\d+"]
KIND = re.compile("^(" + "|".join(KINDS) + ")$")
FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

def source_ok(s):
    return isinstance(s, str) and bool(KIND.match(s))

def problems(doc):
    if not isinstance(doc, dict):
        return ["<top>: not an object"]
    out = []
    for name, sec in doc.items():
        sec = sec if isinstance(sec, dict) else {}
        if sec.get("type") not in TYPES:
            out.append(f"{name}: unknown type {sec.get('type')!r}")
        stamp = sec.get("stamp")
        if not (isinstance(stamp, str) and stamp.strip()):
            out.append(f"{name}: empty stamp")
        srcs = sec.get("sources")
        if not srcs:
            out.append(f"{name}: no sources")
        elif not isinstance(srcs, list):
            out.append(f"{name}: sources not a list")
        else:
            out += [f"{name}: source {s!r} matches no kind" for s in srcs if not source_ok(s)]
    return out

def main(text):
    m = FENCE.search(text)
    try:
        doc = json.loads(m.group(1) if m else text)
    except ValueError as e:
        print(f"unparseable: {e}")
        return 2
    found = problems(doc)
    for p in found:
        print(p)
    if found:
        return 1
    print(f"ok {len(doc)} sections")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: sources_check.py <file|->")
    sys.exit(main(sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read()))
