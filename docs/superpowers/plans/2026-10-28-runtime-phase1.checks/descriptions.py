#!/usr/bin/env python3
"""descriptions.py — every repo skill description <= 300 chars; -extras keep their trigger."""
import pathlib, re, sys
try:
    import yaml
except ImportError:
    yaml = None
root = pathlib.Path(__file__).resolve().parents[4]
files = sorted(root.glob("claude/skills/*/SKILL.md")) + sorted(root.glob("claude/plugin/skills/*/SKILL.md"))
bad = 0
print("frontmatter check: " + ("yaml.safe_load" if yaml else "bare ': ' scan (PyYAML missing)"))
for f in files:
    fm = f.read_text().split("---")[1]
    if yaml:
        try:
            yaml.safe_load(fm)
        except yaml.YAMLError as e:
            print(f"yaml invalid: {f.relative_to(root)}: {str(e).splitlines()[-1] if str(e) else e}"); bad = 1
    else:
        for line in fm.splitlines():
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v and v[0] not in "\"'|>[{" and ": " in v:
                print(f"bare ': ' in unquoted scalar: {f.relative_to(root)}: {line[:60]}"); bad = 1
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|\Z)", fm, re.M | re.S)
    d = " ".join((m.group(1) if m else "").split()).strip("\"'")
    if len(d) > 300:
        print(f"{len(d)} {f.relative_to(root)}"); bad = 1
    if f.parent.name.endswith("-extras") and not ("Use together with" in d and "every time it runs" in d):
        print(f"trigger lost: {f.relative_to(root)}"); bad = 1
print(f"descriptions {'ok' if not bad else 'FAIL'} ({len(files)} checked)")
sys.exit(bad)
