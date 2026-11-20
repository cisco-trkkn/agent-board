#!/usr/bin/env python3
"""check.py: structure check of the dialog fixtures. Run: python3 -I tools/tests/fixtures/dialogs/check.py
Every *.txt here needs expect/<name>.json (the oracle `dialog show` is tested against) and a row in README.md."""
import json
import sys
from pathlib import Path

D = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
REQUIRED = ["trust", "question-single", "question-multi", "question-two", "question-handoff", "plan"]
KINDS = {"permission", "question", "trust", "resume", "login", "unknown"}
bad = []
readme = (D / "README.md").read_text(encoding="utf-8") if (D / "README.md").is_file() else ""
# not dialogs: a teammate's own "Waiting for team lead approval" box (a pane-class fixture), no oracle
NOT_DIALOGS = {"team-waiting"}
names = sorted(p.stem for p in D.glob("*.txt"))
for want in REQUIRED:
    if want not in names:
        bad.append(f"missing fixture {want}.txt")
for sec in ("## Commands used", "## Key probes", "## Not captured", "## Redaction", "## Cleanup evidence"):
    if sec not in readme:
        bad.append(f"README.md lacks the section {sec!r}")
for n in names:
    text = (D / f"{n}.txt").read_text(encoding="utf-8")
    if "/Users/" in text:
        bad.append(f"{n}.txt holds a /Users/ path")
    if f"`{n}.txt`" not in readme:
        bad.append(f"README.md has no row for `{n}.txt`")
    if n in NOT_DIALOGS:
        continue
    try:
        e = json.loads((D / "expect" / f"{n}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as x:
        bad.append(f"expect/{n}.json: {type(x).__name__}")
        continue
    if set(e) - {"from"} != {"kind", "question", "options", "multi", "other"} or ("from" in e and not (isinstance(e["from"], str) and e["from"])):
        bad.append(f"expect/{n}.json keys are {sorted(e)}")
        continue
    if e["kind"] not in KINDS or not isinstance(e["question"], str) or type(e["multi"]) is not bool or type(e["other"]) is not bool:
        bad.append(f"expect/{n}.json has a bad kind, question, multi or other")
    opts = e["options"]
    if not (isinstance(opts, list) and opts and all(
            isinstance(o, dict) and set(o) == {"n", "label", "permanent"} and type(o["n"]) is int
            and isinstance(o["label"], str) and o["label"] and type(o["permanent"]) is bool for o in opts)):
        bad.append(f"expect/{n}.json options are not a non-empty list of {{n, label, permanent}}")
        continue
    rows = [" ".join(l.split()) for l in text.splitlines()]
    for o in opts:
        if not any(" ".join(o["label"].split()) in r for r in rows):
            bad.append(f"expect/{n}.json label {o['label']!r} is not on the screen in {n}.txt")
for b in bad:
    print("FAIL - " + b)
print(f"fixtures: {len(names)} checked, {len(bad)} problems")
sys.exit(1 if bad else 0)
