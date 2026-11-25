"""improve_apply: how a proposal reaches `main` (spec 2026-11-16 §5, §6; plan Task 10). Protected (docs/superpowers/improve/protected.txt).

The loop never commits in the main checkout. It builds one commit on a branch `improve/<id>` in a worktree of its own under
`<TC_STATE>/improve/<project>/wt/`, then asks the engine to land it: `tmux-ctl engine merge-branch <branch> --key <key>
--proposal <id> --project <p>` (exit 0 merged, 2 refused, 3 the live checkout is mid-change, 1 failed). The engine rebases
and fast-forwards, so the commit with the trailers `Proposal: <id>` and `Engine-Step: <key>` is the one commit on main.

  apply(store, pid)          a kept or promoted proposal -> its commit on main; the tick's hook (improve_eval.HOOK_MODULES)
  revert(store, pid)         `improve revert <id>`: one revert commit, state `reverted`
  draft(store, pid)          a `proposed` proposal of class `protected` -> a drafted spec on `improve/<id>` only, state `drafted`
  approve_draft(store, pid)  the Approve click (Task 12): merges that branch, state `promoted`, the ideas line, the lead line
  applies / reject_if_stale  whether the patch still applies on main; a stale one goes to `rejected`
  sweep_apply / sweep_drafts what `improve tick` runs around the tick: retry waiting commits, draft protected proposals

A patch that no longer applies on main moves the proposal to `rejected` with the reason `stale patch`, from any state
(kept and promoted included: `reverted` is kept for a commit that landed and was undone).
Test: tests/test_improve_apply.py (scratch repo through TC_IMPROVE_REPO; the engine's side: engine/test/improve_merge.test.js)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_class  # noqa: E402
import improve_store  # noqa: E402
import tc_env  # noqa: E402

TARGET = "main"
RETIRED = ".superpowers/improve/retired"
DRAFTS = "docs/superpowers/specs/drafts"
ADAPTER_DRAFT = "adapter draft"
MERGED, REFUSED, WAITING = 0, 2, 3   # exit codes of `engine merge-branch`
MERGE_TIMEOUT = 300


class ApplyError(Exception):
    pass


class _Stale(Exception):
    pass


# ---- git and the engine ---------------------------------------------------------------------------------------------

def _git(cwd, *args, data=None, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], input=data, capture_output=True, env=env)


def _out(cwd, *args):
    r = _git(cwd, *args)
    if r.returncode:
        raise ApplyError(f"git {args[0]} failed: {(r.stderr.decode(errors='replace').strip().splitlines() or [''])[-1]}")
    return r.stdout.decode(errors="replace").strip()


def repo_root():
    """The main checkout the loop lands commits in: the one of this code, or of TC_IMPROVE_REPO (tests)."""
    base = os.environ.get("TC_IMPROVE_REPO") or str(improve_class.REPO)
    common = Path(_out(base, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.parent if common.name == ".git" else Path(base)


def _tmux_ctl():
    return os.environ.get("TC_TMUX_CTL") or str(improve_class.REPO / "bin" / "tmux-ctl")


def _merge(repo, project, branch, key, pid):
    """(exit code, sha or the engine's reason) of `engine merge-branch`."""
    try:
        r = subprocess.run([_tmux_ctl(), "engine", "merge-branch", branch, "--key", key, "--proposal", pid, "--project", project],
                           cwd=str(repo), capture_output=True, text=True, timeout=MERGE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"engine merge-branch: {type(e).__name__}"
    if r.returncode == MERGED:
        return MERGED, r.stdout.strip().rsplit(" ", 1)[-1]
    pre = "engine: merge-branch: "
    why = [l[len(pre):] for l in r.stderr.splitlines() if l.startswith(pre)]
    return r.returncode, (why[-1] if why else f"exit {r.returncode}").removeprefix("waiting: ")


def _messages(repo, ref):
    r = _git(repo, "log", ref, "--format=%H%n%B%x00")
    if r.returncode:
        return []
    out = []
    for rec in r.stdout.decode(errors="replace").split("\0"):
        lines = [l.strip() for l in rec.strip().splitlines()]
        if lines:
            out.append((lines[0], lines[1:]))
    return out


def _step_key(lines, pid, prefix):
    """The Engine-Step key of a commit message that carries `Proposal: <pid>` and a key starting with `prefix`, or None."""
    if f"Proposal: {pid}" not in lines:
        return None
    return next((l[len("Engine-Step: "):] for l in lines if l.startswith(f"Engine-Step: {prefix}")), None)


def _landed(repo, pid, prefix):
    """The sha of the commit already on main for this proposal and key prefix (a crash after the merge), or None."""
    return next((sha for sha, lines in _messages(repo, TARGET) if _step_key(lines, pid, prefix)), None)


def _branch_key(repo, branch, pid, prefix):
    """The key of a branch built earlier (a commit that waited for the checkout), or None when there is no usable branch."""
    if _git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}").returncode:
        return None
    base = _git(repo, "merge-base", TARGET, branch).stdout.decode().strip()
    msgs = _messages(repo, f"{base}..{branch}") if base else []
    return _step_key(msgs[0][1], pid, prefix) if len(msgs) == 1 else None


def _wt_dir(project, name):
    return tc_env.state_dir() / "improve" / project / "wt" / name


def _drop_worktree(repo, wt):
    _git(repo, "worktree", "remove", "--force", str(wt))
    shutil.rmtree(wt, ignore_errors=True)
    _git(repo, "worktree", "prune")


def _drop_branch(repo, branch):
    _git(repo, "branch", "-D", branch)


def _build(repo, project, branch, make):
    """One commit on a new `branch` from main, in a worktree that is removed again. make(wt, main_sha) -> the message.
    Returns main's sha at the time. A failure leaves no branch behind."""
    wt = _wt_dir(project, branch.split("/", 1)[1])
    _drop_worktree(repo, wt)
    _drop_branch(repo, branch)
    main = _out(repo, "rev-parse", TARGET)
    wt.parent.mkdir(parents=True, exist_ok=True)
    _out(repo, "worktree", "add", "-q", "-b", branch, str(wt), TARGET)
    ok = False
    try:
        msg = make(wt, main)
        _out(wt, "commit", "-q", "-m", msg)
        ok = True
    finally:
        _drop_worktree(repo, wt)
        if not ok:
            _drop_branch(repo, branch)
    return main


def _trailers(pid, key):
    return f"\n\nProposal: {pid}\nEngine-Step: {key}"


def _title(row):
    return " ".join(str(row["title"] or f"{row['kind']} {row['target']}").split())


def _subject(row):
    return f"improve({row['kind']}): {row['id']} {_title(row)}"


def _event(store, kind, detail):
    c = store._conn()
    try:
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, NULL, NULL, ?, ?)", (store.now(), kind, json.dumps(detail)))
    finally:
        c.close()


def _record(store, pid, reason, extra=None, **fields):
    """Set columns without a state change, as one `improve` event in the same transaction (replayable, like a transition)."""
    c = store._conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            old = c.execute("SELECT state FROM proposals WHERE id = ?", (pid,)).fetchone()
            sets = {**fields, "updated_at": store.now()}
            c.execute(f"UPDATE proposals SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), pid))
            new = c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
            store._append_event(c, new, old["state"], reason, extra)
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
    finally:
        c.close()


def _row(store, pid):
    row = store.get(pid)
    if not row:
        raise ApplyError(f"no proposal {pid}")
    return row


# ---- building the change --------------------------------------------------------------------------------------------

def _staged(wt):
    return set(_out(wt, "diff", "--cached", "--name-only", "--no-renames").splitlines())


def _split(target):
    file, _, heading = (target or "").partition("#")
    return file, heading


def _section(lines, heading):
    """(first, end) line indexes of the markdown section under `heading` (to the next heading of its level or above)."""
    fence, start, level = False, None, 0
    for i, l in enumerate(lines):
        if l.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence or not l.startswith("#"):
            continue
        n = len(l) - len(l.lstrip("#"))
        if start is None:
            if l[n:].strip() == heading.strip():
                start, level = i, n
        elif n <= level:
            return start, i
    return (start, len(lines)) if start is not None else None


def _retire(wt, row):
    """The soft delete (R5): the target moves under RETIRED/<id>/ (deleted when that folder is git-ignored; the copy is
    then kept in the main checkout after the merge), or its section is commented out with a `retired: <id>` marker."""
    file, heading = _split(row["target"])
    src = wt / file
    if not file or Path(file).is_absolute() or ".." in Path(file).parts or not src.exists():
        raise _Stale(f"no {file}")
    if heading:
        try:
            lines = src.read_bytes().decode().split("\n")
        except UnicodeDecodeError:
            raise _Stale(f"{file} is not UTF-8")
        span = _section(lines, heading)
        if not span:
            raise _Stale(f"no heading {heading}")
        a, b = span
        src.write_bytes("\n".join(lines[:a] + [f"<!-- retired: {row['id']}"] + lines[a:b] + ["-->"] + lines[b:]).encode())
        _out(wt, "add", "--", file)
        return {file}
    dest = f"{RETIRED}/{row['id']}/{file}"
    if _git(wt, "check-ignore", "-q", dest).returncode == 0:
        _out(wt, "rm", "-r", "-q", "--", file)
        return {file}
    (wt / dest).parent.mkdir(parents=True, exist_ok=True)
    _out(wt, "mv", "--", file, dest)
    return {file, dest}


def _change(wt, row):
    """Stage the proposal's change in the worktree; raise _Stale when it does not apply or leaves its target."""
    if row["kind"] == "retire":
        allowed = _retire(wt, row)
    else:
        if not row["patch"]:
            raise _Stale("no patch")
        if _git(wt, "apply", "--index", "-", data=row["patch"].encode()).returncode:
            raise _Stale("patch does not apply")
        allowed = {_split(row["target"])[0]}
    staged = _staged(wt)
    if not staged or not all(any(p == a or p.startswith(a + "/") for a in allowed) for p in staged):
        raise _Stale("the change is not its target alone")


def applies(store, pid, repo=None):
    """Whether the proposal's change still applies on main. Reads only: the patch is checked against a scratch index."""
    repo = repo or repo_root()
    row = _row(store, pid)
    file, heading = _split(row["target"])
    if row["kind"] == "retire":
        r = _git(repo, "show", f"{TARGET}:{file}")
        if not heading:
            return _git(repo, "cat-file", "-e", f"{TARGET}:{file}").returncode == 0
        return r.returncode == 0 and _section(r.stdout.decode(errors="replace").split("\n"), heading) is not None
    if not row["patch"]:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if _git(repo, "read-tree", TARGET, env=env).returncode:
            return False
        if _git(repo, "apply", "--cached", "--check", "-", data=row["patch"].encode(), env=env).returncode:
            return False
        if _git(repo, "apply", "--cached", "-", data=row["patch"].encode(), env=env).returncode:
            return False
        names = _git(repo, "diff", "--cached", "--name-only", "--no-renames", TARGET, env=env).stdout.decode().split()
        return bool(names) and all(n == file for n in names)


def _stale(store, row):
    store.transition(row["id"], "rejected", "stale patch")


def reject_if_stale(store, pid, repo=None):
    """True when the patch no longer applies on main; the proposal is then moved out (`stale patch`)."""
    if applies(store, pid, repo):
        return False
    _stale(store, _row(store, pid))
    return True


def _waiting(store, pid, key, why):
    _event(store, "improve_waiting", {"proposal": pid, "key": key, "reason": why})


# ---- apply ----------------------------------------------------------------------------------------------------------

def _keep_retired_copy(repo, row, sha):
    """A retire whose RETIRED folder is git-ignored deleted the target in the commit: keep its bytes in the main checkout."""
    file, heading = _split(row["target"])
    if heading or _git(repo, "check-ignore", "-q", f"{RETIRED}/{row['id']}/{file}").returncode:
        return
    for name in _git(repo, "ls-tree", "-r", "--name-only", "-z", f"{sha}^", "--", file).stdout.decode().split("\0"):
        blob = _git(repo, "show", f"{sha}^:{name}") if name else None
        if blob is not None and blob.returncode == 0:
            dest = repo / RETIRED / row["id"] / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob.stdout)


def apply(store, pid, repo=None):
    """Land a kept or promoted proposal on main as one `improve(<kind>): <id> <title>` commit.
    -> "applied" | "waiting" (the live checkout is mid-change: state unchanged, one improve_waiting event; the next tick
    retries) | "stale" | "skipped" (not kept or promoted, or class protected) | "refused: <why>" (the engine's refusal,
    or any error here).
    It never raises: the tick calls it right after the `kept` transition, and an exception there would end the tick
    before its other trials, the outcomes, the pick and the digest. An error is `refused: <ErrorType>: <text>` with one
    improve_refused event; the row is left as it is, so the next tick's sweep tries again."""
    try:
        return _apply(store, pid, repo)
    except Exception as e:  # noqa: BLE001
        why = f"{type(e).__name__}: {e}"
        try:
            _event(store, "improve_refused", {"proposal": pid, "why": why})
        except Exception:  # noqa: BLE001
            pass
        return f"refused: {why}"


def _apply(store, pid, repo=None):
    repo = repo or repo_root()
    row = _row(store, pid)
    if row["state"] not in ("kept", "promoted") or row["class"] == "protected":
        return "skipped"
    if row["commit_sha"]:
        return "applied"
    branch, prefix = f"improve/{pid}", f"improve:{pid}@"
    extra = {"undo": f"tmux-ctl improve revert {pid}"} if row["kind"] == "retire" else None
    sha = _landed(repo, pid, prefix)
    if not sha:
        key = _branch_key(repo, branch, pid, prefix)
        if not key:
            try:
                main = _build(repo, store.project, branch,
                              lambda wt, m: (_change(wt, row), _subject(row) + _trailers(pid, f"{prefix}{m}"))[1])
            except _Stale:
                _stale(store, row)
                return "stale"
            key = f"{prefix}{main}"
        rc, res = _merge(repo, store.project, branch, key, pid)
        if rc == WAITING:
            _waiting(store, pid, key, res)
            return "waiting"
        if rc != MERGED:
            if "rebase conflict" in res:
                _drop_branch(repo, branch)
                _stale(store, row)
                return "stale"
            _event(store, "improve_refused", {"proposal": pid, "key": key, "why": res})
            return f"refused: {res}"
        sha = res
    _record(store, pid, "applied", extra, commit_sha=sha)
    if row["kind"] == "retire":
        _keep_retired_copy(repo, row, sha)
    _drop_branch(repo, branch)
    return "applied"


# ---- revert ---------------------------------------------------------------------------------------------------------

def revert(store, pid, reason="reverted by hand", repo=None):
    """`improve revert <id>`: one `git revert` commit of the proposal's commit, landed the same way. Returns its sha.
    Raises ApplyError: `protected`, `no commit`, or why it could not land (a busy checkout: run it again)."""
    repo = repo or repo_root()
    row = _row(store, pid)
    if row["class"] == "protected" or improve_class.is_protected(_split(row["target"])[0]):
        raise ApplyError("protected")
    if not row["commit_sha"]:
        raise ApplyError("no commit")
    if row["state"] not in ("kept", "promoted"):
        raise ApplyError(f"{pid} is {row['state']}, not kept or promoted")
    branch, prefix = f"improve/{pid}-revert", f"improve:{pid}:revert@"
    sha = _landed(repo, pid, prefix)
    if not sha:
        key = _branch_key(repo, branch, pid, prefix)
        if not key:
            def make(wt, main):
                if _git(wt, "revert", "--no-edit", row["commit_sha"]).returncode:
                    _git(wt, "revert", "--abort")
                    raise ApplyError("revert conflict: main changed the same lines since")
                msg = _out(wt, "log", "-1", "--format=%B") + _trailers(pid, f"{prefix}{main}")
                _out(wt, "reset", "-q", "--soft", "HEAD^")   # _build commits once, with the trailers
                return msg
            key = f"{prefix}{_build(repo, store.project, branch, make)}"
        rc, res = _merge(repo, store.project, branch, key, pid)
        if rc == WAITING:
            _waiting(store, pid, key, res)
            raise ApplyError(f"{res}: run it again when the checkout is clean")
        if rc != MERGED:
            raise ApplyError(res)
        sha = res
    store.transition(pid, "reverted", reason)
    _drop_branch(repo, branch)
    return sha


# ---- drafted specs for protected proposals ----------------------------------------------------------------------------

def _draft_text(row):
    patch = row["patch"] if row["patch"] is not None else "(none)\n"
    fence = "```"
    while fence in patch:
        fence += "`"
    try:
        evidence = json.loads(row["evidence"] or "[]")
    except ValueError:
        evidence = [row["evidence"]]
    lines = [f"# Improve {row['id']}: {_title(row)}", "",
             "**Status:** draft. This proposal targets a protected file, so the improve loop never trials or applies it:",
             "approving this draft merges the draft only; the change itself is yours to make.", "",
             "## Proposal", "",
             f"- id: {row['id']}", f"- kind: {row['kind']}", f"- target: `{row['target']}`", f"- source: {row['source']}",
             f"- class: {row['class']}", f"- outcome: {row['outcome'] or '-'}", "",
             "## Evidence", ""]
    lines += [f"- `{json.dumps(e)}`" for e in evidence] or ["- (none)"]
    lines += ["", "## Patch", "", f"{fence}diff", patch.rstrip("\n"), fence, ""]
    return "\n".join(lines)


def _draft_path(repo, pid):
    names = _out(repo, "diff", "--name-only", f"{TARGET}...improve/{pid}").splitlines()
    return next((n for n in names if n.startswith(DRAFTS + "/")), None)


def draft(store, pid, repo=None):
    """Write a protected proposal as a drafted spec, committed on `improve/<id>` only; state `drafted`. Returns its path."""
    repo = repo or repo_root()
    row = _row(store, pid)
    branch, prefix = f"improve/{pid}", f"improve:{pid}@"
    if row["class"] != "protected" or row["reason"] == ADAPTER_DRAFT or row["state"] not in ("proposed", "drafted"):
        raise ApplyError("not a protected proposal")
    if not _branch_key(repo, branch, pid, prefix):
        if row["state"] == "drafted":
            raise ApplyError(f"no branch {branch}")
        rel = f"{DRAFTS}/{time.strftime('%Y-%m-%d', time.localtime(store.now()))}-improve-{pid}.md"

        def make(wt, main):
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (wt / rel).write_text(_draft_text(row))
            _out(wt, "add", "--", rel)
            return _subject(row) + _trailers(pid, f"{prefix}{main}")
        _build(repo, store.project, branch, make)
    if row["state"] == "proposed":
        store.transition(pid, "drafted", "protected")
    return _draft_path(repo, pid)


def approve_draft(store, pid, add_line=None, add_done=None, repo=None):
    """The Approve click on a protected draft: merge `improve/<id>` through the engine, state `promoted`, then the ideas
    line and `[Improve] approved: <draft path>` for the lead (each on its own: one failing never stops the other).
    -> "approved" | "waiting". Raises ApplyError for a row that is not a protected draft, or when the merge is refused."""
    repo = repo or repo_root()
    row = _row(store, pid)
    if row["state"] != "drafted" or row["class"] != "protected" or row["reason"] == ADAPTER_DRAFT:
        raise ApplyError("not a protected draft")
    branch, prefix = f"improve/{pid}", f"improve:{pid}@"
    sha = _landed(repo, pid, prefix)
    if not sha:
        key = _branch_key(repo, branch, pid, prefix)
        if not key:
            raise ApplyError(f"no branch {branch}")
        rc, res = _merge(repo, store.project, branch, key, pid)
        if rc == WAITING:
            _waiting(store, pid, key, res)
            return "waiting"
        if rc != MERGED:
            raise ApplyError(res)
        sha = res
    rel = next((n for n in _out(repo, "diff", "--name-only", f"{sha}^", sha).splitlines() if n.startswith(DRAFTS + "/")), None)
    store.transition(pid, "promoted", "approved", commit_sha=sha)
    _drop_branch(repo, branch)
    if add_done is None:
        import ideas
        add_done = ideas.add_done
    steps = [lambda: add_done(store.project, f"improve: {_title(row)}", rel)]
    if add_line:
        steps.append(lambda: add_line(f"[Improve] approved: {rel}"))
    for fn in steps:
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass
    return "approved"


# ---- what `improve tick` runs around the tick -------------------------------------------------------------------------

def _count(counts, key):
    counts[key] = counts.get(key, 0) + 1


def sweep_apply(store, repo=None):
    """Apply every kept or promoted proposal that has no commit yet (one that waited for the checkout). Returns counts."""
    counts = {}
    for row in store.list("kept") + store.list("promoted"):
        if row["commit_sha"] or row["class"] == "protected" or (row["patch"] is None and row["kind"] != "retire"):
            continue
        try:
            _count(counts, apply(store, row["id"], repo).split(":")[0])
        except Exception:  # noqa: BLE001  (apply itself never raises)
            _count(counts, "error")
    return counts


def sweep_drafts(store, repo=None):
    """Draft every `proposed` proposal of class `protected`. Returns counts."""
    counts = {}
    for row in store.list("proposed"):
        if row["class"] != "protected":
            continue
        try:
            draft(store, row["id"], repo)
            _count(counts, "drafted")
            import improve_discord   # the drafted card (never raises); a late import: improve_discord imports this module
            improve_discord.card("drafted", {"id": row["id"], "project": store.project})
        except Exception:  # noqa: BLE001  (one bad row never ends the tick's sweep)
            _count(counts, "error")
    return counts
