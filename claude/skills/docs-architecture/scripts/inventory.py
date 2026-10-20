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

def resolve(repo, ref):
    """Full commit sha for <ref>, or None."""
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None

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
        inv = build(d)
    inv["meta"]["repo"], inv["meta"]["sha"] = os.path.abspath(repo), sha   # the archive is not a git repo
    return inv

SAME = ("kind", "name", "project", "env")

def diff(old, new, since):
    oc, nc = {c["id"]: c for c in old["components"]}, {c["id"]: c for c in new["components"]}
    ek = lambda e: (e["from"], e["to"], e["kind"], e["label"])
    oe, ne = {ek(e): e for e in old["edges"]}, {ek(e): e for e in new["edges"]}
    # same identity on both sides, any field but `source` differs (line numbers move on any edit)
    echg = lambda k: {f: oe[k].get(f) for f in (oe[k].keys() | ne[k].keys()) - {"source"} if oe[k].get(f) != ne[k].get(f)}
    return {"since": since, "head": new["meta"]["sha"],
            "components": {"added": [nc[i] for i in sorted(nc.keys() - oc.keys())],
                           "removed": [oc[i] for i in sorted(oc.keys() - nc.keys())],
                           "changed": [nc[i] for i in sorted(nc.keys() & oc.keys())
                                       if any(nc[i][k] != oc[i][k] for k in SAME)]},
            "edges": {"added": [ne[k] for k in sorted(ne.keys() - oe.keys())],
                      "removed": [oe[k] for k in sorted(oe.keys() - ne.keys())],
                      "changed": [{**ne[k], "was": w} for k in sorted(ne.keys() & oe.keys()) if (w := echg(k))]}}

def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventory.py", description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    ap.add_argument("--since", help="emit the diff between <sha> and HEAD (both from git archive) instead")
    ap.add_argument("-o", "--output", help="write JSON here instead of stdout")
    a = ap.parse_args(argv)
    if a.since:
        since, head = resolve(a.repo, a.since), resolve(a.repo, "HEAD")
        old = build_at(a.repo, since) if since else None
        if old is None or head is None:
            print(f"inventory: unknown --since sha {a.since}", file=sys.stderr)
            return 2
        inv = build_at(a.repo, head)        # both sides from `git archive`: same semantics, exact `head`
    else:
        inv = build(a.repo)
    if not inv["components"]:
        counts = ", ".join(f"{k}={v}" for k, v in inv["meta"]["extractors"].items())
        print(f"inventory: 0 components — discovery is broken, not an empty system ({counts}; repo {a.repo})",
              file=sys.stderr)
        return 2
    if a.since:
        inv = diff(old, inv, since)
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.output:
        with open(a.output, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
