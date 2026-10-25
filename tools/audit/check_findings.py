#!/usr/bin/env python3
"""Validate the runtime-audit findings format. usage: check_findings.py FILE [--require-heading T]... [--min-findings N]"""
import argparse, re, sys

LABELS = {"Verified", "Measured", "Hypothesis"}

def blocks(text):
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("### F-"):
            cur = [line]; out.append(cur)
        elif line.startswith("### ") or line.startswith("## "):
            cur = None
        elif cur is not None:
            cur.append(line)
    return out

def problems(block):
    title = block[0][4:].split(":")[0]
    fields = {}
    for l in block[1:]:
        m = re.match(r"(Label|Evidence|Confidence):\s*(.*)", l)
        if m: fields[m.group(1)] = m.group(2).strip()
    errs = [f"{title}: missing {k}:" for k in ("Label", "Evidence", "Confidence") if k not in fields]
    label = fields.get("Label", "").split()[0] if fields.get("Label") else ""
    if "Label" in fields and label not in LABELS:
        errs.append(f"{title}: Label {label!r} not in {sorted(LABELS)}")
    if label in ("Verified", "Measured") and fields.get("Evidence", "").lower() in ("", "none", "n/a"):
        errs.append(f"{title}: {label} finding without evidence")
    return errs

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file")
    ap.add_argument("--require-heading", action="append", default=[])
    ap.add_argument("--min-findings", type=int, default=0)
    a = ap.parse_args()
    text = open(a.file, encoding="utf-8").read()
    bs = blocks(text); errs = [e for b in bs for e in problems(b)]
    heads = [l.lstrip("#").strip() for l in text.splitlines() if l.startswith("#")]
    errs += [f"missing heading containing {h!r}" for h in a.require_heading if not any(h in x for x in heads)]
    if len(bs) < a.min_findings:
        errs.append(f"{len(bs)} findings, need at least {a.min_findings}")
    for e in errs: print(e)
    if errs: return 1
    print(f"OK {len(bs)} findings"); return 0

if __name__ == "__main__":
    sys.exit(main())
