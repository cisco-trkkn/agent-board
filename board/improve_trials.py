"""improve_trials: which `trial` proposals apply to a spec, and what the engine needs to build its trial briefs
(spec 2026-11-16 §4, `tmux-ctl improve variants <spec> --json`). Patches are applied only in a temp copy: the champion
files are never written. Protected (docs/superpowers/improve/protected.txt).
Test: tests/test_improve_trials.py."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_class  # noqa: E402
import improve_store  # noqa: E402

CODE_MODE_ENV = {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "1"}
HEADING = re.compile(r"^(#{1,6})\s")


def in_trial(spec_id, pid):
    """True when the spec is in proposal pid's trial half (the control half is the rest)."""
    return int(hashlib.sha256((spec_id + pid).encode()).hexdigest(), 16) % 2 == 0


def _paths(patch):
    out = []
    for line in patch.splitlines():
        if line.startswith("--- a/"):
            out.append(line[6:].split("\t")[0])
    return out


def _unsafe(rel):
    p = Path(rel)
    return p.is_absolute() or ".." in p.parts or not p.parts


def _apply(repo, patch, target):
    """Apply patch to a copy of the files it names. Returns (tempdir, error); the caller removes the dir.
    Any path that is absolute or climbs out (`..`) is an error before anything is written."""
    d = tempfile.mkdtemp(prefix="improve-trial-")
    named = [l.split(None, 1)[1].split("\t")[0] for l in patch.splitlines() if l.startswith(("--- ", "+++ "))]
    named = [n[2:] if n[:2] in ("a/", "b/") else n for n in named if n != "/dev/null"]
    if any(_unsafe(n) for n in named + [target or ""]):
        return d, "unsafe path"
    if "--- /dev/null" in patch.splitlines() or not (Path(repo) / target).is_file():
        return d, "creates or lacks its target"   # a variant changes an existing champion file
    for rel in _paths(patch):
        src = Path(repo) / rel
        if src.is_file():
            (Path(d) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(d) / rel).write_bytes(src.read_bytes())
    r = subprocess.run(["git", "apply", "-"], input=patch, cwd=d, capture_output=True, text=True)
    return d, (r.stderr.strip() or "git apply failed") if r.returncode else None


def _first_change(patch):
    """The new-file line number of the first added or removed line of the patch (1 when there is none)."""
    n = None
    for line in patch.splitlines():
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
        if m:
            n = int(m.group(1))
        elif n is not None and line[:1] in "+-" and not line.startswith(("+++", "---")):
            return n
        elif n is not None and line[:1] == " ":
            n += 1
    return 1


def _section(text, patch):
    """(heading, section text) of the patched file: nearest heading at or above the first hunk's new start line."""
    lines = text.splitlines()
    at = min(_first_change(patch), max(len(lines), 1)) - 1
    start = next((i for i in range(at, -1, -1) if HEADING.match(lines[i])), None) if lines else None
    if start is None:
        return "(top of file)", "\n".join(lines)
    level = len(HEADING.match(lines[start]).group(1))
    end = next((i for i in range(start + 1, len(lines))
                if (h := HEADING.match(lines[i])) and len(h.group(1)) <= level), len(lines))
    return lines[start], "\n".join(lines[start:end]).rstrip("\n")


def _code_mode(patch, routing):
    if not re.search(r'^\+.*"codeMode"\s*:\s*true', patch, re.M):
        return False
    mech = routing.get("mechanical")
    return routing.get("codeMode") is True or (isinstance(mech, dict) and mech.get("codeMode") is True)


def _build(row, d, patch, target, kind, store):
    base = {"id": row["id"], "kind": kind, "target": target}
    if kind == "skill":
        skill = Path(target).parts[Path(target).parts.index("skills") + 1]
        base["skill_copy"] = {"from": f"claude/skills/{skill}", "to": f".superpowers/improve/skills/{skill}@{row['id']}",
                              "patch": str(improve_store.patches_dir(store.project) / f"{row['id']}.diff")}
    elif kind == "routing":
        routing = json.loads((Path(d) / target).read_text())
        base["routing"] = routing
        if _code_mode(patch, routing):
            base["env"] = dict(CODE_MODE_ENV)
            base["applies_to"] = {"tier": "mechanical", "kind": "implement"}
    else:
        heading, text = _section((Path(d) / target).read_text(), patch)
        base["overlay"] = f"## Trial {row['id']}\n{text}\n(This replaces the section {heading} of {target}.)"
    return base


def _variant(row, repo, store):
    """The variant entry for one trial proposal, or None when its patch no longer applies."""
    patch, target, kind = row["patch"] or "", row["target"], row["kind"]
    d, err = _apply(repo, patch, target)
    try:
        if err:
            return None
        try:
            return _build(row, d, patch, target, kind, store)
        except (OSError, ValueError, KeyError, IndexError, AttributeError):
            return None
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def variants(spec, store, repo=None):
    repo = Path(repo or improve_class.REPO)
    out = []
    for row in store.list("trial"):
        if not in_trial(spec, row["id"]):
            continue
        v = _variant(row, repo, store)
        if v is None:
            store.transition(row["id"], "rejected", "stale patch")
            continue
        out.append(v)
    return {"spec": spec, "variants": out}
