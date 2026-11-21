#!/usr/bin/env python3
"""scout: the trend scout's CLI and its Sunday pass (`tmux-ctl scout …`; launchd runs it, so nothing here needs tmux).

  scout poll | source add|list|remove|test …         the daily poll and the sources (scout_sources)
  scout weekly [--dry-run] [--force] [--retry] [--root <dir>]
  scout approve|reject|revise <id> [--note <text>] [--root <dir>]
  scout redraft <id> [--root <dir>]                  redraft a `revise` draft now
  scout pack [--root <dir>]                          print the context pack

weekly: off switch, the retry rule, one pass per week (unless --force), the 85% usage guard (unless --force), then: the
week's new items, context pack, evaluate, validate, pick, redraft the waiting revisions, draft each pick, expire, publish,
cleanup. State is weekly.json in scout_dir(); each event is one weekly.log line. A model step that fails (evaluate, or every
draft) posts no digest and counts a failed week; the second in a row posts one critical line.

--dry-run runs the same pass against a copy of scout_dir() in a temp dir and drafts in a `git clone --shared` of the repo,
so it writes no scout state and makes no ref in the real repo. It calls nothing that writes the outbox (no publish, redraft,
expire or cleanup), appends no metrics record, and prints the digest instead. The state copy is kept and its path printed;
the clone is removed. Test: tests/test_scout_weekly.py. Spec: docs/superpowers/specs/2026-11-13-trend-scout-design.md §3."""
import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_feed  # noqa: E402
import dream  # noqa: E402
import findings  # noqa: E402
import metrics  # noqa: E402
import scout_decisions  # noqa: E402
import scout_draft  # noqa: E402
import scout_eval  # noqa: E402
import scout_pack  # noqa: E402
import scout_post  # noqa: E402
import scout_sources  # noqa: E402
import tc_env  # noqa: E402

PROJECT = "agent-board"
REPO = Path(__file__).resolve().parents[1]
RUNS_KEEP = 8
FIRST_RUN_DAYS = 7
FAIL_POST_AT = 2
WEEKLY_DEFAULTS = {"last_run_at": None, "last_week": None, "skipped_week": None, "failed_weeks": 0}
_RUN = re.compile(r"^\d{8}-\d{4}$")        # runs/<YYYYMMDD-HHMM>: one pass
_WEEK = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # runs/<week>: the digest's file copies (scout_post._copy_files)
_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_GIT_ENV = scout_draft._GIT_ENV
USAGE = "usage: scout poll | source … | weekly [--dry-run] [--force] [--retry] | approve|reject|revise <id> [--note <text>] | redraft <id> | pack"


def scout_dir():
    return scout_sources.scout_dir()


def week_of(now):
    """The local date of the most recent Sunday on or before now."""
    lt = time.localtime(now)
    back = (lt.tm_wday + 1) % 7            # tm_wday: Monday is 0, Sunday is 6
    return time.strftime("%Y-%m-%d", time.localtime(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - back, 12, 0, 0, 0, 0, -1))))


def _off():
    return scout_sources._off()


def _weekly():
    st = scout_sources._read(scout_dir() / "weekly.json", {})
    out = dict(WEEKLY_DEFAULTS)
    out.update({k: st[k] for k in WEEKLY_DEFAULTS if k in st})
    if not isinstance(out["failed_weeks"], int) or isinstance(out["failed_weeks"], bool):
        out["failed_weeks"] = 0
    return out


def _set_weekly(**kw):
    st = _weekly()
    st.update(kw)
    scout_sources._atomic(scout_dir() / "weekly.json", st)
    return st


def _log(text, now):
    scout_draft._log(text, now)


@contextlib.contextmanager
def _one_pass():
    """Yields False when another weekly pass holds scout_dir()/weekly.lock."""
    d = scout_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "weekly.lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


def _root(arg):
    """The repo: --root, else the live session's, else the checkout this file is in (the launchd run has no session)."""
    r = str(Path(arg).resolve()) if arg and Path(arg).is_dir() else None
    r = r or (None if arg else dream.resolve_root(PROJECT, {"root": str(REPO)}, None))
    if not r:
        print(f"scout: no repo for {PROJECT}", file=sys.stderr)
    return r


def new_items(last_run_at, now):
    """The week's new items: fetched after the last run; with no last run, in the last 7 days."""
    cutoff = last_run_at if isinstance(last_run_at, str) and last_run_at else findings.iso(now - FIRST_RUN_DAYS * 86400)
    out = []
    try:
        lines = (scout_dir() / "items.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            it = json.loads(line)
        except ValueError:
            continue
        if isinstance(it, dict) and isinstance(it.get("key"), str) and isinstance(it.get("fetched_at"), str) and it["fetched_at"] > cutoff:
            out.append(it)
    return out


def _prune_runs():
    d = scout_dir() / "runs"
    if not d.is_dir():
        return
    for pat in (_RUN, _WEEK):
        for old in sorted(p for p in d.iterdir() if p.is_dir() and pat.match(p.name))[:-RUNS_KEEP]:
            shutil.rmtree(old, ignore_errors=True)


def _tokens(usages):
    n = 0
    for u in usages:
        for k in _TOKEN_KEYS:
            v = (u or {}).get(k)
            n += v if isinstance(v, int) and not isinstance(v, bool) else 0
    return n


class _Pass:
    """One weekly pass. `dry` holds the dry-run's temp dir (None on a real run); the clone is made at the first draft."""

    def __init__(self, root, now, week, dry):
        self.root, self.now, self.week, self.dry = root, now, week, dry
        self.t0 = time.time()
        self.clone = None
        self.items, self.valid, self.drafts, self.dropped = [], [], [], []
        self.eval_info, self.draft_infos = {}, []

    # ---- the record and the failure path ----
    def record(self, outcome):
        """One kind=scout line in the repo's runs.jsonl, only when that file exists; never on a dry run."""
        if self.dry or not metrics.log_path(self.root).is_file():
            return
        costs = [i.get("cost_usd") for i in [self.eval_info] + self.draft_infos if isinstance(i.get("cost_usd"), (int, float))]
        metrics.append(self.root, {
            "kind": "scout", "at": datetime.fromtimestamp(self.now).isoformat(timespec="seconds"), "outcome": outcome,
            "items": len(self.items), "findings": len(self.valid), "drafts": len(self.drafts), "dropped": len(self.dropped),
            "tokens": {"evaluate": self.eval_info.get("usage") or {}, "draft": [i.get("usage") or {} for i in self.draft_infos]},
            "cost_usd": round(sum(costs), 4) if costs else None, "duration_s": int(time.time() - self.t0)})

    def fail(self, why):
        why = " ".join(str(why).split())
        print(f"scout: failed: {why}")
        _log(f"failed: {why}", self.now)
        st = _set_weekly(failed_weeks=_weekly()["failed_weeks"] + 1)
        if st["failed_weeks"] == FAIL_POST_AT and not self.dry:
            discord_feed.outbox_write(tc_env.discord_dir(PROJECT), {
                "op": "post", "tier": "critical", "mention_user": True,
                "text": f"🛰 scout: two Sundays failed — {findings.escape(why)}"[:scout_post.LIMIT],
                "key": f"scout-{PROJECT}-fail-{self.week}"})
        self.record("failed")
        return 1

    # ---- the draft root ----
    def draft_root(self):
        """Where drafts are made: the repo, or on a dry run a `git clone --shared` of it (made once), so the scout branch,
        its worktree and its commits never exist in the real repo."""
        if not self.dry:
            return self.root
        if self.clone is None:
            clone = self.dry / "repo"
            env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV}
            p = subprocess.run(["git", "clone", "-q", "--shared", "--branch", "main", str(self.root), str(clone)],
                               capture_output=True, text=True, env=env, timeout=600)
            if p.returncode:
                raise RuntimeError("dry-run clone failed: " + " ".join((p.stderr or "").split())[:200])
            for key in ("user.name", "user.email"):     # the clone must be able to commit as the repo does
                rc, val = scout_draft._git(self.root, "config", "--local", "--get", key)
                if rc == 0 and val.strip():
                    scout_draft._git(clone, "config", key, val.strip())
            self.clone = clone
        return self.clone

    # ---- the pass ----
    def run(self):
        now, week, dry = self.now, self.week, self.dry
        self.items = new_items(_weekly()["last_run_at"], now)
        if not self.items:
            print("scout: no new items")
            _log("no new items", now)
            _set_weekly(last_week=week, last_run_at=findings.iso(now))
            self.record("no-new-items")
            return 0
        run_dir = scout_dir() / "runs" / time.strftime("%Y%m%d-%H%M", time.localtime(now))
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "items.json").write_text(json.dumps(self.items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            (run_dir / "context-pack.md").write_text(scout_pack.build(self.root, now), encoding="utf-8")
            fail, entries, info = scout_eval.run_evaluate(run_dir, self.root)
            self.eval_info = info or {}
            if fail:
                return self.fail(fail)
            vinfo = {}
            self.valid = scout_eval.validate(entries, self.items, scout_post._findings().read(), vinfo)
            queued = [p for p, s in scout_pack.spec_states(self.root).items() if s == "queued"]
            sel = scout_eval.pick(self.valid, scout_decisions.pending_revisions(), queued)
            for old in sel["revisions"]:
                if dry:                                  # redraft posts the revision: a dry run only names it
                    print(f"would redraft: {old.get('id')} {old.get('title')}")
                    continue
                new = scout_decisions.redraft(old["id"], self.root, now)
                _log(f"redraft {old['id']}: " + (f"now {new}" if new else "not redrafted, stays in revise"), now)
            for p in sel["picks"]:
                info = {}
                res = scout_draft.draft(self.draft_root(), week, p, info=info)
                if isinstance(res, dict) and "path" in res:
                    self.drafts.append(res)
                    self.draft_infos.append(info)
                else:
                    self.dropped.append(res)
                    _log(f"draft {res.get('id')}: dropped: {res.get('why')}", now)
            if sel["picks"] and not self.drafts and all(str(d.get("why") or "").startswith("model ") for d in self.dropped):
                return self.fail(self.dropped[0]["why"])
            if not dry:
                scout_decisions.expire(now)
            titles = {i["key"]: i.get("title") for i in self.items}
            others = [dict(o, title=titles.get(o.get("item")) or o["component"], why=o["what_it_enables"]) for o in sel["others"]]
            dropped = [f"{d.get('title') or d.get('id')} ({d.get('why')})" for d in self.dropped]
            health = scout_sources.load(create=False)
            tokens = _tokens([self.eval_info.get("usage")] + [i.get("usage") for i in self.draft_infos])
            args = (week, self.drafts, others, sel["notes"], dropped, health, tokens)
            try:
                if dry:
                    op = scout_post.build_op(*args)
                    print(op["text"])
                    print("buttons: " + " | ".join(b["label"] for row in op["rows"] for b in row))
                    for f in op.get("files") or []:
                        print(f"file: {f}")
                else:
                    scout_post.publish(*args, now)
            except ValueError as e:
                return self.fail(f"post: {e}")
            if not dry:
                scout_decisions.cleanup(self.root)
            _set_weekly(last_week=week, last_run_at=findings.iso(now), failed_weeks=0)
            dropped_counts = ", ".join(f"{n} {why}" for why, n in sorted((vinfo.get("dropped") or {}).items()))
            line = (f"{'would post' if dry else 'posted'}: {len(self.items)} items, {len(self.valid)} findings, {len(self.drafts)} drafted, "
                    f"{len(self.dropped)} dropped, {len(others)} other, {len(sel['notes'])} overlaps"
                    + (f"; entries dropped: {dropped_counts}" if dropped_counts else ""))
            print(f"scout: {line}")
            _log(line, now)
            self.record("posted")
            return 0
        finally:
            _prune_runs()


def _dry_setup():
    """A temp dir holding a copy of scout_dir() (locks and half-written files left out). Returns (temp dir, copy)."""
    tmp = Path(tempfile.mkdtemp(prefix="scout-dry-")).resolve()
    real, copy = scout_dir(), tmp / "scout"
    if real.is_dir():
        shutil.copytree(real, copy, ignore=shutil.ignore_patterns("*.lock", "*.tmp"))
    else:
        copy.mkdir()
    return tmp, copy


def weekly(argv, now=None):
    ap = argparse.ArgumentParser(prog="scout weekly")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--root")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    now = time.time() if now is None else now
    if _off():
        print("scout: off")
        return 0
    root = _root(a.root)
    if not root:
        return 2
    if not a.dry_run:
        return _guarded(a, root, now, None)
    tmp, copy = _dry_setup()
    old = os.environ.get("TC_SCOUT_DIR")
    os.environ["TC_SCOUT_DIR"] = str(copy)      # every scout module reads the dir from here: the whole pass runs on the copy
    try:
        return _guarded(a, root, now, tmp)
    finally:
        if old is None:
            os.environ.pop("TC_SCOUT_DIR", None)
        else:
            os.environ["TC_SCOUT_DIR"] = old
        shutil.rmtree(tmp / "repo", ignore_errors=True)
        print(f"dry-run dir: {copy}")


def _guarded(a, root, now, dry):
    """The skip rules, then the pass under the one-pass lock."""
    week = week_of(now)
    w = _weekly()
    if a.retry:
        if w["skipped_week"] != week or w["last_week"] == week:
            print("scout: nothing to retry")
            return 0
    elif w["last_week"] == week and not a.force:
        print(f"scout: already ran for {week}")
        return 0
    ps = _Pass(root, now, week, dry)
    if not a.force:
        pct = dream.weekly_pct(now)
        if pct is not None and pct >= dream.WEEKLY_MAX:
            print(f"scout: skipped, weekly {pct:g}%")
            _log(f"skipped, weekly {pct:g}%", now)
            _set_weekly(skipped_week=week)
            ps.record("skipped")
            return 0
    with _one_pass() as mine:
        if not mine:
            print("scout: a weekly pass is already running")
            return 0
        try:
            return ps.run()
        except Exception as e:  # noqa: BLE001 -- launchd gets a line and an exit code, never a traceback; not a model failure
            print(f"scout: error: {type(e).__name__}: {e}", file=sys.stderr)
            _log(f"error: {type(e).__name__}: {e}", now)
            return 1


# ---- decisions from the shell ----------------------------------------------------------------------------------------

def decide(act, argv, now=None):
    """approve|reject|revise <id> [--note]: the same path as the button (scout_post.click), as user `cli`. An approval from the
    shell tells no lead window: the lead reads approved.jsonl at its next round."""
    ap = argparse.ArgumentParser(prog=f"scout {act}")
    ap.add_argument("id")
    ap.add_argument("--note")
    ap.add_argument("--root")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    now = time.time() if now is None else now
    root = _root(a.root) if act == "approve" else None
    if act == "approve" and not root:
        return 2
    got = {}

    def approve_fn(draft, _add_line):
        got["res"] = scout_decisions.approve(draft, root, now, None)

    res = scout_post.click("cli", f"ab:scout:{act}:{PROJECT}:{a.id}", now, approve_fn=approve_fn)
    if act == "approve" and res == "already approved":
        # stored as approved but maybe not yet on main (it waited, or the retry gave up): copy it now
        rec = scout_post._drafts().read()["drafts"].get(a.id)
        res = scout_decisions.approve(rec, root, now, None) if rec else res
    elif act == "approve" and res == "approved":
        res = got.get("res") or res
    if res == "unknown" or res.startswith("error"):
        print(f"scout: {res}", file=sys.stderr)
        return 1
    if a.note and act in ("reject", "revise") and not res.startswith("already"):
        scout_post.reply("cli", f"ab:scout:{act}:{PROJECT}:{a.id}", a.note, now)
    print(res)
    return 0


def redraft(argv, now=None):
    ap = argparse.ArgumentParser(prog="scout redraft")
    ap.add_argument("id")
    ap.add_argument("--root")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    root = _root(a.root)
    if not root:
        return 2
    new = scout_decisions.redraft(a.id, root, time.time() if now is None else now)
    if not new:
        print(f"scout: {a.id} not redrafted", file=sys.stderr)   # no such draft in `revise`, or the model dropped it
        return 1
    print(f"redrafted {a.id} as {new}")
    return 0


def pack(argv, now=None):
    ap = argparse.ArgumentParser(prog="scout pack")
    ap.add_argument("--root")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    root = _root(a.root)
    if not root:
        return 2
    print(scout_pack.build(root, time.time() if now is None else now), end="")
    return 0


def main(argv=None, now=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    cmd = argv[0] if argv else ""
    if cmd in ("poll", "source"):
        return scout_sources.main(argv)
    if cmd == "weekly":
        return weekly(argv[1:], now)
    if cmd in ("approve", "reject", "revise"):
        return decide(cmd, argv[1:], now)
    if cmd == "redraft":
        return redraft(argv[1:], now)
    if cmd == "pack":
        return pack(argv[1:], now)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
