"""GitLab CI extractor: top-level jobs → ci_job components; a script line that runs a Terraform directory
(`-chdir=<dir>` or `cd <dir>`) → call edge to that directory's project boundaries.

A line scanner, not a YAML parser: GitLab's `!reference` and anchors break yaml.safe_load.
"""
import fnmatch, os, re
from . import terraform

RESERVED = {"stages", "variables", "include", "default", "workflow", "image", "services",
            "before_script", "after_script", "cache"}
JOB_RE = re.compile(r'^([A-Za-z0-9][^:#]*):\s*$')
CHDIR_RE = re.compile(r'-chdir=(\S+)|\bcd\s+(\S+)')
CI_GLOBS = (".gitlab-ci.yml", "*.gitlab-ci*.yml", ".gitlab-ci-*.yml")

def ci_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in terraform.SKIP_DIRS)
        for f in sorted(files):
            if any(fnmatch.fnmatch(f, g) for g in CI_GLOBS):
                yield os.path.join(d, f)

def jobs(text):
    """Yield (name, line, [(lineno, text)]) for each top-level job; lines are the job's block."""
    cur = None
    for n, raw in enumerate(text.splitlines(), 1):
        m = JOB_RE.match(raw)
        if m and not raw.startswith((" ", "\t")):
            if cur:
                yield cur
            name = m.group(1).strip()
            cur = (name, n, []) if name not in RESERVED else None
        elif cur is not None and (raw.startswith((" ", "\t")) or not raw.strip() or raw.startswith("#")):
            cur[2].append((n, raw))
        elif cur is not None:               # another column-0 line that is not a job header
            yield cur
            cur = None
    if cur:
        yield cur

def field(lines, key):
    """Inline value of `key:` in a job block, or the `name:` on the lines under `key:`."""
    for i, (_, raw) in enumerate(lines):
        m = re.match(r'^\s+' + key + r':\s*(.*?)\s*$', raw)
        if not m:
            continue
        if m.group(1):
            return m.group(1).strip("'\"")
        for _, nxt in lines[i + 1:]:
            n = re.match(r'^\s+name:\s*(.+?)\s*$', nxt)
            if n:
                return n.group(1).strip("'\"")
            if nxt.strip() and not nxt.startswith("    "):
                break
    return None

def extract(root):
    out = {"components": [], "edges": [], "boundaries": [], "unknowns": [], "confidence": "high"}
    boundaries = [b["id"] for b in terraform.extract(root)["boundaries"] if b["kind"] == "project"]
    for path in ci_files(root):
        rel = os.path.relpath(path, root)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for name, line, body in jobs(text):
            cid = f"ci/{name}"
            env, stage = field(body, "environment"), field(body, "stage")
            norm = terraform.env_of(env) if env else None
            if env and not norm:
                out["unknowns"].append({"what": cid, "source": f"{rel}:{line}",
                                        "why": f"environment '{env}' is not one of dev/stage/prod"})
            out["components"].append({
                "id": cid, "kind": "ci_job", "name": f"{name} [{stage}]" if stage else name, "project": None,
                "env": norm or env, "source": f"{rel}:{line}"})
            for n, raw in body:
                m = CHDIR_RE.search(raw)
                if not m or raw.lstrip().startswith("#"):
                    continue
                d = os.path.normpath((m.group(1) or m.group(2)).strip("'\";"))
                full = os.path.join(root, d)
                if not (os.path.isdir(full) and any(f.endswith(".tf") for f in os.listdir(full))):
                    continue
                targets = [b for b in boundaries if b.startswith(d + "/project:")]
                for t in targets:
                    out["edges"].append({"from": cid, "to": t, "kind": "call", "label": "terraform",
                                         "source": f"{rel}:{n}"})
                if not targets:
                    out["unknowns"].append({"what": f"{cid} → {d}", "source": f"{rel}:{n}",
                                            "why": "job runs Terraform here but the directory declares no project boundary"})
    return out
