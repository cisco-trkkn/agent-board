#!/usr/bin/env python3
"""inventory.py — read a repo and emit the architecture inventory the docs-architecture skill draws from.

Read-only and offline: it never runs terraform, gcloud, glab or any network call (local git only).
Usage: inventory.py <repo> [--since <sha>] [-o inventory.json]
"""
import argparse, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extractors import EXTRACTORS  # noqa: E402

def git_sha(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None

def build(repo):
    inv = {"components": [], "edges": [], "boundaries": [], "unknowns": [],
           "meta": {"repo": os.path.abspath(repo), "sha": git_sha(repo), "extractors": {}, "confidence": "high"}}
    for name, mod in EXTRACTORS:
        part = mod.extract(repo)
        for key in ("components", "edges", "boundaries", "unknowns"):
            inv[key].extend(part[key])
        inv["meta"]["extractors"][name] = len(part["components"])
        if part["confidence"] == "low":
            inv["meta"]["confidence"] = "low"
    return inv

def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventory.py", description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    ap.add_argument("--since", help="emit the diff between <sha> and the working tree instead")
    ap.add_argument("-o", "--output", help="write JSON here instead of stdout")
    a = ap.parse_args(argv)
    inv = build(a.repo)
    if not inv["components"]:
        counts = ", ".join(f"{k}={v}" for k, v in inv["meta"]["extractors"].items())
        print(f"inventory: 0 components — discovery is broken, not an empty system ({counts}; repo {a.repo})",
              file=sys.stderr)
        return 2
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.output:
        with open(a.output, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
