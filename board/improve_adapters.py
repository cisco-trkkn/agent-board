"""improve_adapters: feeds the proposals store (improve_store) from dream, scout, discovery and the task-observer workspace.
run_all(project) runs each adapter; one that cannot read its source writes one `improve_adapter_error` event and is skipped.
Idempotence comes from Store.insert's dedupe key. drafted rows carry reason 'adapter draft' (bookkeeping only: the scout's
and discovery's own approval flows own them). Spec 2026-11-16 §4. Test: tests/test_improve_adapters.py."""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover_post  # noqa: E402
import dream_paths  # noqa: E402
import improve_class  # noqa: E402
import improve_store  # noqa: E402
import scout_post  # noqa: E402

DRAFT_REASON = "adapter draft"
_HEAD = re.compile(r"^##\s+(\S+).*awaiting install", re.M)
_HDR = re.compile(r"^(?:---|\+\+\+) (.+)$", re.M)
_SUFFIX = re.compile(r"\.(new|next|changed)$")
LOOKUP_DIRS = ("claude", "bin", "docs")


class Skip(Exception):
    """One item of a source is skipped; the adapter goes on."""


def observer_dir():
    return Path(os.environ.get("TC_OBSERVER_DIR") or Path.home() / ".task-observer")


def _clean(raw):
    """One ---/+++ header value -> a path guess: no timestamp, no a/ b/, no .new/.next/.changed, no checkout prefix."""
    name = raw.split("\t")[0].strip()
    if name == "/dev/null":
        return None
    name = _SUFFIX.sub("", name)
    if name.startswith(("a/", "b/")):
        name = name[2:]
    if name.startswith("/"):
        name = name.rsplit("/agent-board/", 1)[1] if "/agent-board/" in name else name
    return name


def rule_target(patch):
    """The repo-relative file an observer `_target-files` patch changes, or the bare name when it cannot be resolved to
    exactly one repo file (observer() then skips the patch)."""
    names = [n for n in (_clean(m) for m in _HDR.findall(patch)[:2]) if n]
    repo = improve_class.REPO
    for n in names:
        if not n.startswith("/") and (repo / n).is_file():
            return n
    for n in names:
        base = n.rsplit("/", 1)[-1]
        hits = sorted({str(f.relative_to(repo)) for d in LOOKUP_DIRS if (repo / d).is_dir() for f in (repo / d).rglob(base)
                       if f.is_file() and "node_modules" not in f.parts})
        if len(hits) == 1:
            return hits[0]
    return names[-1] if names else None


def _o1(*texts):
    return "O1" if any("O1" in str(t or "") for t in texts) else None


def _draft(store, target, ref, outcome=None, title=None):
    return store.insert("adapter", "spec", target, None, [{"type": "report", "ref": ref}], outcome=outcome, title=title,
                        state="drafted", reason=DRAFT_REASON)


def dream(store, project, errors):
    d = dream_paths.project_dir(project)
    runs = sorted((r for r in d.iterdir() if (r / "out" / "report.json").is_file()), key=lambda r: r.name) if d.is_dir() else []
    if not runs:
        return 0
    rep = runs[-1] / "out" / "report.json"
    props = json.loads(rep.read_text()).get("proposals") or []
    n = 0
    for i, it in enumerate(props):
        text = str(it.get("text") or "").strip()
        title = text.splitlines()[0][:120] if text else None
        ev = [{"type": "report", "ref": f"{rep}#proposals[{i}]"}] + [{"type": "note", "ref": str(e)} for e in it.get("evidence") or []]
        target = it.get("target") or f"dream:{runs[-1].name}:{i}"
        if it.get("kind") == "observer":
            store.insert("dream", "procedure", target, None, ev, title=title)
        elif it.get("kind") == "idea":
            store.insert("dream", "spec", target, None, ev, title=title, state="drafted", reason=DRAFT_REASON)
        else:
            continue
        n += 1
    return n


def scout(store, project, errors):
    p = scout_post.scout_dir() / "drafts.json"
    if p.exists():
        json.loads(p.read_text())          # a present but unparsable file is an error, not an empty source
    n = 0
    for did, d in (scout_post._drafts().read()["drafts"] or {}).items():
        if isinstance(d, dict) and d.get("path"):
            _draft(store, d["path"], f"scout drafts.json#{d.get('id') or did}", _o1(d.get("title"), d.get("text")), d.get("title"))
            n += 1
    return n


def discovery(store, project, errors):
    p = discover_post._store(project).path
    if p.exists():
        json.loads(p.read_text())
    n = 0
    for night, post in sorted(discover_post.load_state(project)["posts"].items()):
        for it in post.get("items") or []:
            path = it.get("path") or it.get("spec_path")
            if path:
                _draft(store, path, f"discover state#{night}/{it.get('kid') or it.get('key')}", _o1(it.get("title"), it.get("why")), it.get("title"))
                n += 1
    return n


def _repo_file(target):
    return bool(target) and not target.startswith("/") and ".." not in Path(target).parts and (improve_class.REPO / target).is_file()


def _rehead(patch, rel):
    """The patch with its one ---/+++ header pair rewritten to a/<rel> and b/<rel> (what a trial and git apply on main
    read), or None when it is not a one-file patch. A header pair is a --- line, a +++ line, then a hunk line: a removed
    line that starts with `-- ` is not one."""
    lines = patch.split("\n")
    at = [i for i in range(len(lines) - 2)
          if lines[i].startswith("--- ") and lines[i + 1].startswith("+++ ") and lines[i + 2].startswith("@@ ")
          and (i == 0 or not lines[i - 1].startswith("@@ "))]
    if len(at) != 1:
        return None
    return "\n".join(lines[:at[0]] + [f"--- a/{rel}", f"+++ b/{rel}"] + lines[at[0] + 2:])


def observer(store, project, errors):
    """Every stored patch names its target as a/<rel> and b/<rel>, <rel> a file of this repo: the form improve_trials and
    improve_apply read. An item that has no such file (a skill that lives only in ~/.claude/skills, a rule patch whose
    name is no single repo file) is one error line and no proposal."""
    pend = observer_dir() / "skill-updates" / "PENDING.md"
    if not pend.is_file():
        return 0                          # no workspace or no PENDING.md: an absent source, not an error
    rounds = _HEAD.findall(pend.read_text())
    n = 0
    for rnd in rounds:
        base = pend.parent / rnd
        ev = [{"type": "report", "ref": f"{pend}#{rnd}"}]
        for staged in sorted(base.glob("*/SKILL.md")):
            skill = staged.parent.name
            rel = f"claude/skills/{skill}/SKILL.md"
            live = improve_class.REPO / rel
            if not live.is_file():
                outside = (Path.home() / ".claude" / "skills" / skill / "SKILL.md").is_file()
                errors.append(f"skill {skill} lives outside the repo (round {rnd})" if outside
                              else f"no live SKILL.md for {skill} (round {rnd})")
                continue
            patch = "".join(difflib.unified_diff(live.read_text().splitlines(True), staged.read_text().splitlines(True),
                                                 f"a/{rel}", f"b/{rel}"))
            if not patch:
                continue
            store.insert("observer", "skill", rel, patch, ev)
            n += 1
        for pf in sorted((base / "_target-files").glob("*.patch")):
            raw = pf.read_text()
            target = rule_target(raw)
            if not target:
                errors.append(f"no ---/+++ header in {pf}")
                continue
            if not _repo_file(target):
                errors.append(f"no single repo file for {pf} ({target})")
                continue
            patch = _rehead(raw, target)
            if patch is None:
                errors.append(f"not a one-file patch: {pf}")
                continue
            store.insert("observer", "rule", target, patch, ev)
            n += 1
    return n


ADAPTERS = (("dream", dream), ("scout", scout), ("discovery", discovery), ("observer", observer))


def _error(store, source, reason):
    c = store._conn()
    try:
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, NULL, NULL, 'improve_adapter_error', ?)",
                  (store.now(), json.dumps({"source": source, "reason": reason})))
    finally:
        c.close()


def run_all(project, store=None, only=None):
    """Run every adapter (or the one named by `only`). Returns {source: items read}; failed sources map to None."""
    store = store or improve_store.Store(project)
    out = {}
    for name, fn in ADAPTERS:
        if only and name != only:
            continue
        errors = []
        try:
            out[name] = fn(store, project, errors)
        except Exception as e:  # noqa: BLE001 -- one unreadable source never stops the others
            out[name] = None
            errors.append(f"{type(e).__name__}: {e}")
        for reason in errors:
            _error(store, name, reason)
    return out
