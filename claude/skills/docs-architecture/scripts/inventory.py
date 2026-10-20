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

def build_at(repo, sha):
    """Inventory of <repo> at <sha>, from `git archive` into a temp dir (offline, read-only on the repo)."""
    import tarfile, tempfile, io
    try:
        blob = subprocess.run(["git", "-C", repo, "archive", "--format=tar", sha], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    with tempfile.TemporaryDirectory() as d:
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            t.extractall(d, filter="data")
        return build(d)

SAME = ("kind", "name", "project", "env")

def diff(old, new, since):
    oc, nc = {c["id"]: c for c in old["components"]}, {c["id"]: c for c in new["components"]}
    ek = lambda e: (e["from"], e["to"], e["kind"], e["label"])
    oe, ne = {ek(e): e for e in old["edges"]}, {ek(e): e for e in new["edges"]}
    return {"since": since, "head": new["meta"]["sha"],
            "components": {"added": [nc[i] for i in sorted(nc.keys() - oc.keys())],
                           "removed": [oc[i] for i in sorted(oc.keys() - nc.keys())],
                           "changed": [nc[i] for i in sorted(nc.keys() & oc.keys())
                                       if any(nc[i][k] != oc[i][k] for k in SAME)]},
            "edges": {"added": [ne[k] for k in sorted(ne.keys() - oe.keys())],
                      "removed": [oe[k] for k in sorted(oe.keys() - ne.keys())]}}

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
    if a.since:
        old = build_at(a.repo, a.since)
        if old is None:
            print(f"inventory: unknown --since sha {a.since}", file=sys.stderr)
            return 2
        inv = diff(old, inv, a.since)
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.output:
        with open(a.output, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
