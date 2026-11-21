#!/usr/bin/env python3
"""scout_draft: the trend scout's draft step. draft() writes one pick as a spec on branch scout/<week>, in the worktree
<root>/.claude/worktrees/scout-<week> made from main, checks it and commits it there with the Scout-Item trailer.

Isolation: every git call names the worktree with -C and runs only after the worktree is proven to be its own checkout on
scout/<week> (a plain directory at that path would make `git -C` act on the main checkout). Whatever the model changed
besides the spec is reverted before the checks, so a file it created cannot satisfy the citation check and nothing but the
spec is committed. Nothing is pushed. See docs/superpowers/specs/2026-11-13-trend-scout-design.md §3 step 4.
Test: tests/test_scout_draft.py."""
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream  # noqa: E402
import findings  # noqa: E402
import scout_post  # noqa: E402
import scout_sources  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DRAFT_TIMEOUT = 1200
GIT_TIMEOUT = 120
FALLBACK_MODEL = "opus"
SPECS = "docs/superpowers/specs"
PROTECTED = ("claude/orchestrator.md", "claude/worker.md", "claude/scout-*.md", "board/scout*.py", "bin/tmux-ctl")
LIMIT_RE = re.compile(r"(?i)usage limit|rate limit|limit reached|overloaded")
_WEEK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FENCE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```[ \t]*$")
_SPAN = re.compile(r"`([^`\n]+)`")
_FILE = re.compile(r"^[\w./-]+\.(py|zsh|js|md|sh|json|plist)$")
_DIRS = ("board/", "bin/", "claude/", "tools/", "docs/")
_LINE = re.compile(r":\d+(-\d+)?$")
_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_PREFIX")


def _git(cwd, *args):
    """(exit code, stdout) of one git call in cwd. The GIT_* location variables are dropped: one inherited from a hook
    would point the call at another repo."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV}
    try:
        p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return p.returncode, p.stdout


def _log(line, now=None):
    d = scout_sources.scout_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or time.time()))
    with open(d / "weekly.log", "a", encoding="utf-8") as f:
        f.write(f"{ts} {' '.join(str(line).split())}\n")


def frontier_model(root):
    try:
        m = json.loads((Path(root) / "docs" / "superpowers" / "model-routing.json").read_text()).get("frontier")
    except (OSError, ValueError, AttributeError):
        m = None
    return m if isinstance(m, str) and m.strip() and m != "inherit" else FALLBACK_MODEL


# ---- the worktree ----------------------------------------------------------------------------------------------------

def _worktree(root, week):
    """The week's worktree path, created from main or reused; None when it is not its own checkout on scout/<week>."""
    wt = Path(root) / ".claude" / "worktrees" / f"scout-{week}"
    branch = f"scout/{week}"
    if not wt.exists():
        have = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0
        _git(root, "worktree", "add", *(() if have else ("-b", branch)), str(wt), branch if have else "main")
    rc, top = _git(wt, "rev-parse", "--show-toplevel") if wt.is_dir() else (1, "")
    if rc or not top.strip() or Path(top.strip()).resolve() != wt.resolve():
        return None
    rc, head = _git(wt, "symbolic-ref", "--short", "HEAD")
    return wt if rc == 0 and head.strip() == branch else None


def _changes(wt):
    """[(status, path)] of everything that differs from HEAD in the worktree, untracked files one by one."""
    rc, out = _git(wt, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    return [(e[:2], e[3:]) for e in out.split("\0") if len(e) > 3] if rc == 0 else []


def _revert(wt, keep=None):
    """Put the worktree back to HEAD, except the path `keep`: untracked files are removed, tracked ones restored."""
    for st, rel in _changes(wt):
        if rel == keep:
            continue
        if st != "??":
            _git(wt, "reset", "-q", "HEAD", "--", rel)
        if _git(wt, "cat-file", "-e", f"HEAD:{rel}")[0] == 0:
            _git(wt, "checkout", "-q", "HEAD", "--", rel)
        else:
            try:
                (wt / rel).unlink()
            except OSError:
                pass


def _week_specs(wt, week):
    d = wt / SPECS
    return {f.name: hashlib.sha1(f.read_bytes()).hexdigest() for f in sorted(d.glob(f"{week}-*-design.md")) if f.is_file()} if d.is_dir() else {}


def _written(wt, week, before, prev_name):
    """The spec file name this run wrote: the previous draft when it was rewritten, else the first new one by name."""
    after = _week_specs(wt, week)
    if prev_name and prev_name in after and after[prev_name] != before.get(prev_name):
        return prev_name
    return next((n for n in sorted(after) if n not in before), None)


# ---- the checks ------------------------------------------------------------------------------------------------------

def _spans(text):
    return [m.group(1).strip() for m in _SPAN.finditer(_FENCE.sub("", text))]


def missing_citation(text, wt):
    """The first backticked repo path in the spec that does not exist under wt, or None. A path is a whole span that looks
    like a file (`x/y.py`), or a span whose first word starts with board/, bin/, claude/, tools/ or docs/. A `:line` suffix
    is ignored, a `*` is matched as a glob, and a span with a <placeholder> is not a path."""
    wt = Path(wt)
    for span in _spans(text):
        if _FILE.match(span):
            p = span
        elif span.startswith(_DIRS):
            p = _LINE.sub("", span.split()[0])
        else:
            continue
        if any(c in p for c in "<>{}"):
            continue
        if p.startswith("/") or ".." in Path(p).parts:
            return p
        if not (any(wt.glob(p.rstrip("/"))) if "*" in p else (wt / p).exists()):
            return p
    return None


def is_protected(text, protected=None):
    """True when a backticked span of the spec names a protected path (as a word of the span, a `:line` suffix ignored)."""
    pats = PROTECTED if protected is None else protected
    for span in _spans(text):
        for word in span.split():
            w = _LINE.sub("", word).rstrip(".,;:)")
            if any(w == p or fnmatch.fnmatchcase(w, p) for p in pats):
                return True
    return False


def _title(text):
    for line in text.splitlines():
        if line.startswith("# "):
            # only a dashed suffix (" — design", " - design") goes: "Hook redesign" and "By design" are whole titles
            return re.sub(r"(?i)^(.*\S)\s+[—–-]\s+design$", r"\1", " ".join(line[2:].split()))
    return ""


# ---- the model -------------------------------------------------------------------------------------------------------

def _prompt(week, pick, note, prev, prev_text):
    finding = {k: pick.get(k) for k in ("component", "what_it_enables", "value", "effort", "risk", "overlaps", "evidence", "url", "published")}
    out = [(REPO / "claude" / "scout-draft.md").read_text().rstrip(), "",
           f"Write the spec to: {SPECS}/{week}-<slug>-design.md (pick a short lowercase slug with dashes)",
           f"Its header line: Proposed by: scout · Source: {pick.get('url')} ({pick.get('published') or 'no date'})", "",
           "The finding:", json.dumps(finding, indent=1, ensure_ascii=False)]
    if prev is not None:
        out += ["", "## Revision", "The user read an earlier draft of this spec and asked for a revision.",
                "Their note: " + (" ".join(str(note).split()) if note else "(they gave no note: improve the draft where it is weakest)"),
                f"The earlier draft was `{prev}`. If that file is in this worktree, rewrite it in place; if it is not, write the "
                "revised spec to the path above."]
        if prev_text:
            out += ["Its text:", "", "<<<EARLIER DRAFT", prev_text.rstrip(), "EARLIER DRAFT>>>"]
    return "\n".join(out) + "\n"


def _run_model(wt, model, prompt):
    """(failure text or None, info). The failure is "model limit" when the model hit a usage or rate limit."""
    argv = [os.environ.get("TC_SCOUT_CLAUDE") or "claude", "-p", "--model", model, "--permission-mode", "acceptEdits",
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--output-format", "json",
            "--allowedTools", "Read,Grep,Glob,Write,Edit"]
    env = {k: v for k, v in os.environ.items() if k not in dream.SCRUB}
    try:
        proc = subprocess.Popen(argv, cwd=str(wt), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError:
        return "model error", {}
    try:
        out, err = proc.communicate(prompt, timeout=DRAFT_TIMEOUT)
    except subprocess.TimeoutExpired:
        dream._kill_group(proc)
        return "model timeout", {}
    res = None
    for cand in (out, *reversed(out.strip().splitlines())):
        try:
            res = json.loads(cand)
            break
        except ValueError:
            continue
    res = res if isinstance(res, dict) else {}
    if res.get("is_error") is True and LIMIT_RE.search(str(res.get("result") or "")):
        return "model limit", {}
    if proc.returncode != 0:
        return ("model limit" if LIMIT_RE.search(err or "") else f"model exit {proc.returncode}"), {}
    if res.get("is_error") is not False:
        return "model error", {}
    u = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    return None, {"cost_usd": res.get("total_cost_usd"), "usage": u, "model_s": (res.get("duration_ms") or 0) / 1000, "model": model}


# ---- draft -----------------------------------------------------------------------------------------------------------

def _new_id(pick, revision):
    old = str(pick.get("id") or scout_post.draft_id(pick["key"]))
    if not revision:
        return scout_post.draft_id(pick["key"])
    m = re.match(r"^(.*?)(?:-r(\d+))?$", old)
    return f"{m.group(1)}-r{int(m.group(2) or 0) + 1}"


def _prev_text(wt, pick, prev):
    """The earlier draft's text: from this worktree, else from the worktree its Draft record names."""
    p = Path(str(prev))
    for cand in ([p] if p.is_absolute() else [wt / p] + ([Path(str(pick["worktree"])) / p] if pick.get("worktree") else [])):
        try:
            return cand.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return ""


def draft(root, week, pick, note=None, prev=None, info=None):
    """Draft one pick (an evaluate entry with key, url, published; for a revision the earlier Draft record, with `prev` its
    spec path and `note` the user's note). Returns the Draft record, or the dropped form {"id", "title", "why"}.
    `info`, when given, receives the successful model run's cost_usd, usage, model_s and model."""
    if not _WEEK.match(str(week)):
        raise ValueError(f"bad week: {week!r}")
    root = Path(root)
    did = _new_id(pick, prev is not None)
    name = str(pick.get("title") or pick.get("what_it_enables") or "")

    def dropped(why, title=None):
        return {"id": did, "title": title or name, "why": why}

    wt = _worktree(root, week)
    if wt is None:
        return dropped(f"worktree not on scout/{week}")
    _revert(wt)                                        # leftovers of a run that died must not count as this run's spec
    before = _week_specs(wt, week)
    prev_name = Path(str(prev)).name if prev is not None else None
    prompt = _prompt(week, pick, note, prev, _prev_text(wt, pick, prev) if prev is not None else "")
    model = frontier_model(root)
    fail, run = _run_model(wt, model, prompt)
    if fail == "model limit" and model != FALLBACK_MODEL:
        _revert(wt)
        _log(f"draft {did}: {model} limit, retried on {FALLBACK_MODEL}")
        fail, run = _run_model(wt, FALLBACK_MODEL, prompt)
    if fail:
        _revert(wt)
        return dropped(fail)
    spec_name = _written(wt, week, before, prev_name)
    rel = f"{SPECS}/{spec_name}" if spec_name else None
    _revert(wt, keep=rel)                              # only the spec stays: extra specs and stray edits go
    if not rel:
        return dropped("no spec written")
    try:
        text = (wt / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _revert(wt)
        return dropped("no spec written")
    slug = spec_name[len(week) + 1:-len("-design.md")]
    title = _title(text) or slug
    missing = missing_citation(text, wt)
    if missing:
        _revert(wt)
        return dropped(f"cites missing {missing}", title)
    if _git(wt, "add", "--", rel)[0] or _git(wt, "commit", "-q", "-m", f"docs(spec): {title} (scout draft)",
                                              "-m", f"Scout-Item: {pick['key']}", "--", rel)[0]:
        _revert(wt)
        return dropped("commit failed", title)
    if info is not None:
        info.update(run)
    rec = {k: pick.get(k) for k in ("key", "value", "effort", "risk", "url", "published", "evidence", "what_it_enables")}
    rec.update(id=did, title=title, slug=slug, path=rel, branch=f"scout/{week}", worktree=str(wt), week=week, status="pending",
               why=pick.get("what_it_enables"), protected=is_protected(text), post_key=f"scout-agent-board-{week}",
               note=None, reason=None, created_at=findings.iso(), decided_at=None, decided_by=None)
    return rec
