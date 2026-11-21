"""scout_decisions: carries out the trend scout's decisions. approve() copies the approved spec from scout/<week> onto main,
path-scoped (waiting while the live checkout is mid-change), adds the ideas line, appends approved.jsonl and tells the lead;
retry_copies() retries the waiting ones; redraft() redrafts a `revise` draft; expire() rejects 28-day-old pending drafts;
cleanup() removes a scout/<week> branch and worktree once every draft of the week is decided.

approve() runs after scout_post.click released its locks (flock is not re-entrant) and takes the drafts lock itself. Its
idempotency key is the Draft field copied_at (set after the main commit), not status: click has stored "approved" already.
Test: tests/test_scout_decisions.py."""
import calendar
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_feed  # noqa: E402
import findings  # noqa: E402
import ideas  # noqa: E402
import scout_post  # noqa: E402
import scout_sources  # noqa: E402
import tc_env  # noqa: E402

PROJECT = scout_post.PROJECT
GIVE_UP = 24 * 3600
EXPIRE_AFTER = 28 * 86400
DECIDED = ("approved", "rejected", "expired", "superseded")
WAITING = "approved, waiting for main"
_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_PREFIX")


def _git(root, *args):
    """(exit code, stdout) of one git call in root; the GIT_* location variables are dropped."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV}
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return p.returncode, p.stdout or ""


def _ts(s):
    try:
        return calendar.timegm(time.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def _busy(root, path):
    """True while the live checkout must not take a commit: a merge or rebase in progress, HEAD not on main, or the spec path dirty."""
    for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply"):
        rc, p = _git(root, "rev-parse", "--git-path", name)
        if rc or not p.strip():
            return True
        q = Path(p.strip())
        if os.path.lexists(q if q.is_absolute() else Path(root) / q):
            return True
    rc, head = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    if rc or head.strip() != "main":
        return True
    rc, st = _git(root, "status", "--porcelain", "--", path)
    return rc != 0 or bool(st.strip())


def _copy(root, rec):
    """show scout/<week>:<path> into the checkout, then add and commit that one path. True on success."""
    path, root = rec["path"], Path(root)
    rc, text = _git(root, "show", f"{rec.get('branch') or 'scout/' + str(rec['week'])}:{path}")
    if rc:
        return False
    dst = root / path
    tracked = _git(root, "ls-files", "--error-unmatch", "--", path)[0] == 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    if _git(root, "add", "--", path)[0] or _git(root, "commit", "-q", "-m", f"docs(spec): {rec['title']} (scout)",
                                                "-m", f"Scout-Item: {rec['key']}", "--", path)[0]:
        # leave the checkout as it was: a leftover file would make the path dirty and pin every retry in _busy
        _git(root, "reset", "-q", "HEAD", "--", path)
        try:
            if tracked:   # rewrite HEAD's bytes by hand: `git checkout` needs the index lock whose absence just failed us
                rc, old = _git(root, "show", f"HEAD:{path}")
                if rc == 0:
                    dst.write_text(old, encoding="utf-8")
            else:
                dst.unlink()
        except OSError:
            pass
        return False
    return True


def _follow(rec, now, add_line):
    """The steps after the main commit, each on its own: one failing is logged to weekly.log and never stops the others."""
    def jsonl():
        d = scout_sources.scout_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "approved.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"spec": rec["path"], "approved_at": findings.iso(now), "title": rec["title"],
                                "protected": bool(rec.get("protected")), "consumed": False}, ensure_ascii=False) + "\n")
    steps = [("add_done", lambda: ideas.add_done(PROJECT, f"scout: {rec['title']}", rec["path"])), ("approved.jsonl", jsonl)]
    if add_line:
        steps.append(("add_line", lambda: add_line(f"[Scout] approved: {rec['path']}")))
    for name, fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            try:
                import scout_draft
                scout_draft._log(f"approve {rec['id']}: {name} failed: {type(e).__name__}: {e}", now)
            except Exception:  # noqa: BLE001
                pass


def approve(draft, root, now, add_line=None):
    """"approved", "approved, waiting for main" or "already approved" (copied_at set: no second commit)."""
    ds = scout_post._drafts()
    with ds.locked():
        st = ds.read()
        rec = st["drafts"].get(draft.get("id")) or draft
        if rec.get("copied_at"):
            return "already approved"
        if _busy(root, rec["path"]):
            if rec["id"] not in st["pending_copies"]:
                st["pending_copies"].append(rec["id"])
                ds.write(st)
            return WAITING
        if not _copy(root, rec):
            if rec["id"] not in st["pending_copies"]:
                st["pending_copies"].append(rec["id"])
                ds.write(st)
            return WAITING
        rec["copied_at"] = findings.iso(now)
        st["drafts"][rec["id"]] = rec
        st["pending_copies"] = [i for i in st["pending_copies"] if i != rec["id"]]
        ds.write(st)
        _follow(rec, now, add_line)
    return "approved"


def retry_copies(root, now, add_line=None):
    """Retry each waiting approval; after 24 h of a busy main drop it with a `decision` post."""
    if not root:
        return
    ds = scout_post._drafts()
    with ds.locked():
        st = ds.read()
        ids = list(st["pending_copies"])
    for i in ids:
        rec = st["drafts"].get(i)
        if not rec or rec.get("copied_at"):
            _drop(i)
            continue
        since = _ts(rec.get("decided_at")) or _ts(rec.get("created_at")) or now
        if now - since > GIVE_UP:
            _drop(i)
            discord_feed.outbox_write(tc_env.discord_dir(PROJECT), {
                "op": "post", "tier": "decision", "mention_user": True,
                "text": f"scout: {findings.escape(rec['title'])} approved but main stayed busy for 24 h — run tmux-ctl scout approve {i}"})
            continue
        if approve(rec, root, now, add_line) == "approved":
            _drop(i)


def _drop(i):
    ds = scout_post._drafts()
    with ds.locked():
        st = ds.read()
        st["pending_copies"] = [x for x in st["pending_copies"] if x != i]
        ds.write(st)


def pending_revisions():
    """The drafts waiting in `revise`, for the Sunday pick."""
    return [d for d in scout_post._drafts().read()["drafts"].values() if d.get("status") == "revise"]


def redraft(draft_id, root, now=None):
    """Redraft a `revise` draft now. Returns the new id, or None (no such draft, or the model dropped it: the draft stays `revise`)."""
    import scout_draft
    ds = scout_post._drafts()
    old = ds.read()["drafts"].get(draft_id)
    if not old or old.get("status") != "revise":
        return None
    pick = {k: old.get(k) for k in ("key", "what_it_enables", "value", "effort", "risk", "url", "published", "evidence")}
    pick["component"] = str(old["key"]).rsplit(":", 1)[-1]
    pick["id"] = old["id"]
    pick["worktree"] = old.get("worktree")
    new = scout_draft.draft(root, old["week"], pick, note=old.get("note"), prev=old["path"])
    if not isinstance(new, dict) or "path" not in new:
        return None
    week = old["week"]
    with scout_post._both() as (d, f):
        dst, fst = d.read(), f.read()
        cur = dst["drafts"].get(draft_id)
        if cur:
            cur["status"] = "superseded"
            cur["decided_at"] = findings.iso(now)
        rec = dict(new)
        rec.update(status="pending", post_key=f"{scout_post._post_key(week)}-{rec['id']}", week=week)
        dst["drafts"][rec["id"]] = rec
        # the revision is its own post: key scout-agent-board-<week>-<id>, kept in posts["<week>-<id>"] (scout_post._edit edits
        # every post of the week)
        op, post = scout_post._built(week, [rec], [], [], [], {}, 0)
        op["key"] = post["key"] = rec["post_key"]
        discord_feed.outbox_write(tc_env.discord_dir(PROJECT), op)
        fst["posts"][f"{week}-{rec['id']}"] = post
        d.write(dst)
        f.write(fst)
    scout_post.refresh(week)
    return rec["id"]


def expire(now):
    """pending drafts older than 28 days: rejected, reason expired, dismissed in findings, post edited. Returns the ids."""
    gone, weeks = [], set()
    with scout_post._both() as (d, f):
        dst, fst = d.read(), f.read()
        for rec in dst["drafts"].values():
            made = _ts(rec.get("created_at"))
            if rec.get("status") == "pending" and made is not None and now - made > EXPIRE_AFTER:
                rec.update(status="rejected", reason="expired", decided_at=findings.iso(now), decided_by="expiry")
                fst["dismissed"][rec["key"]] = {"at": findings.iso(now), "evidence_count": len(rec.get("evidence") or [])}
                gone.append(rec["id"])
                weeks.add(rec.get("week"))
        if gone:
            d.write(dst)
            f.write(fst)
    for w in sorted(w for w in weeks if w):
        scout_post.refresh(w)
    return gone


def cleanup(root):
    """Remove worktree and branch of every scout/<week> whose drafts are all decided. Never touches another branch."""
    st = scout_post._drafts().read()
    by_week = {}
    for rec in st["drafts"].values():
        # an approved draft is decided only once its spec is on main: until then the retry still needs scout/<week>
        waiting = rec.get("status") == "approved" and (not rec.get("copied_at") or rec.get("id") in st["pending_copies"])
        by_week.setdefault(rec.get("week"), []).append("waiting" if waiting else rec.get("status"))
    removed = []
    for week, sts in sorted(by_week.items(), key=lambda kv: str(kv[0])):
        if not week or not all(s in DECIDED for s in sts):
            continue
        branch = f"scout/{week}"
        rc, _ = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if rc:
            continue
        wt = Path(root) / ".claude" / "worktrees" / f"scout-{week}"
        if wt.exists():
            _git(root, "worktree", "remove", "--force", str(wt))
        _git(root, "worktree", "prune")
        if _git(root, "branch", "-D", branch)[0] == 0:
            removed.append(branch)
    return removed
