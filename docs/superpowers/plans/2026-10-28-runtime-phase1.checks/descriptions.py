#!/usr/bin/env python3
"""descriptions.py — every repo skill description <= 300 chars; -extras keep their trigger."""
import pathlib, re, sys
root = pathlib.Path(__file__).resolve().parents[4]
files = sorted(root.glob("claude/skills/*/SKILL.md")) + sorted(root.glob("claude/plugin/skills/*/SKILL.md"))
bad = 0
for f in files:
    fm = f.read_text().split("---")[1]
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|\Z)", fm, re.M | re.S)
    d = " ".join((m.group(1) if m else "").split()).strip("\"'")
    if len(d) > 300:
        print(f"{len(d)} {f.relative_to(root)}"); bad = 1
    if f.parent.name.endswith("-extras") and not ("Use together with" in d and "every time it runs" in d):
        print(f"trigger lost: {f.relative_to(root)}"); bad = 1
print(f"descriptions {'ok' if not bad else 'FAIL'} ({len(files)} checked)")
sys.exit(bad)
