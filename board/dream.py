#!/usr/bin/env python3
"""dream: the nightly memory consolidation run (spec 2026-11-12-memory-consolidation-design.md, plan G1-G12).

For a project key P it copies the shared context core and archive into a run dir, lets `claude -p` condense them there,
checks the result (dream_check) and commits it under the context lock, with backups. A failed run changes no context file.

  dream.py run <project>|--all [--dry-run] [--force] [--root DIR]
  dream.py report <project>          the last run's out/run.json and report

Tests: board/tests/test_dream.py (fake model: board/tests/fixtures/dream/claude)."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context  # noqa: E402
import dream_actions  # noqa: E402
import dream_check  # noqa: E402
import dream_discord  # noqa: E402
import dream_paths as P  # noqa: E402
import metrics  # noqa: E402
import paneclass  # noqa: E402
import relay  # noqa: E402
import tc_env  # noqa: E402,F401
import usage  # noqa: E402

REPO = Path(__file__).resolve().parents[1]   # the agent-board checkout that holds this file (F5)
TIMEOUT = 900
GRACE = 3    # seconds between TERM and KILL of the model's process group
REAP = 5     # seconds to collect the killed child's pipes
WEEKLY_MAX = 85
KEEP_DAYS = 14
FIRST_RUN_DAYS = 30
SCRUB = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_MESSAGING_SOCKET",
         "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_CHILD_SESSION", "TMUX", "TMUX_PANE")
FILES_RE = dream_check.FILES_RE


def projects():
    d = context.context_dir()
    out = []
    for f in sorted(d.glob("*.md")):
        stem = f.name[:-3]
        if stem.endswith(".archive") or not context.PROJECT_RE.fullmatch(stem):
            continue
        out.append(stem)
    return out


def live_session_root(project):
    """The repo of the live tmux session whose group or name is `project` (not a background one), else None."""
    try:
        # paneclass.tmux_cmd(): under launchd $TMUX is unset, so this resolves to agent-board's own server (-L agent-board)
        out = subprocess.run(paneclass.tmux_cmd() + ["list-sessions", "-F", "#{session_name}\t#{session_group}\t#{session_path}\t#{@tc_bg}"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for ln in out.stdout.splitlines():
        f = ln.split("\t") + [""] * 4
        name, group, path, bg = f[:4]
        if bg or (group or name) != project or not path:
            continue
        r = relay.root_for(path)
        if r and (Path(r) / ".git").exists():
            return str(Path(r).resolve())
    return None


def resolve_root(project, state, root_arg):
    """S6, in order: the live session, the root remembered in dream.json, --root; else None."""
    r = live_session_root(project)
    if r:
        return r
    for cand in (state.get("root"), root_arg):
        if cand and Path(cand).is_dir():
            return str(Path(cand).resolve())
    return None


def weekly_pct(now):
    """Weekly plan usage in percent from the statusLine tap, or None when unknown (no tap, or its window already reset)."""
    try:
        pl = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
        sd = (pl or {}).get("seven_day")
        pct = sd.get("used_percentage")
        resets = sd.get("resets_at")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            return None
        if isinstance(resets, (int, float)) and resets < now:
            return None
        return pct
    except Exception:
        return None


def _head(root):
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def observer_dir():
    return Path(os.environ.get("TASK_OBSERVER_WORKSPACE") or Path.home() / ".task-observer") / "skill-observations" / "observation-log"


def _rd(p):
    return p.read_bytes() if p.is_file() else b""


def _sources(root):
    r = Path(root) / "docs" / "superpowers"
    return sorted(r.glob("ledgers/*/progress.md")) + sorted(r.glob("reports/*.md"))


def digest(project, root):
    """sha1 over the core, the archive, each ledger progress.md and top-level report (path and bytes, sorted), the byte
    total of the observer log dir and the repo's HEAD sha."""
    h = hashlib.sha1()
    h.update(_rd(context.context_path(project)) + b"\0" + _rd(context.archive_path(project)) + b"\0")
    for f in _sources(root):
        h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes() + b"\0")
    od = observer_dir()
    total = sum(f.stat().st_size for f in od.glob("*.md") if f.is_file()) if od.is_dir() else 0
    h.update(f"observer:{total}\0head:{_head(root)}".encode())
    return h.hexdigest()


def _cited_paths(*texts):
    out = set()
    for t in texts:
        for _, line in dream_check.parse(t)[0]:
            out |= dream_check.files_of(line)
    return out


def prepare(run_dir, project, root, state, core, archive, now):
    """Build the run dir the prompt reads (the `inputs/ contract` of Task 3's report). core and archive are the texts."""
    run_dir = Path(run_dir)
    (run_dir / "out").mkdir(parents=True, exist_ok=True)
    (run_dir / "core.md").write_text(core)
    (run_dir / "archive.md").write_text(archive)
    last = P.parse_iso(state.get("last_run"))
    since = last if last is not None else None
    inp = run_dir / "inputs"
    inp.mkdir(exist_ok=True)
    docs = Path(root) / "docs" / "superpowers"
    for f in sorted(docs.glob("ledgers/*/progress.md")):
        if since is None or f.stat().st_mtime > since:
            dst = inp / "ledgers" / f.parent.name / "progress.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
    for f in sorted(docs.glob("reports/*.md")):
        if since is None or f.stat().st_mtime > since:
            (inp / "reports").mkdir(exist_ok=True)
            shutil.copyfile(f, inp / "reports" / f.name)
    od = observer_dir()
    cutoff = since if since is not None else now - FIRST_RUN_DAYS * 86400
    if od.is_dir():
        for f in sorted(od.glob("*.md")):
            try:
                if f.stat().st_mtime > cutoff and project in f.read_text(errors="replace"):
                    (inp / "observer").mkdir(exist_ok=True)
                    shutil.copyfile(f, inp / "observer" / f.name)
            except OSError:
                pass
    after = P.iso_utc(since) if since is not None else f"{FIRST_RUN_DAYS}.days.ago"
    g = subprocess.run(["git", "-C", str(root), "log", "--name-status", f"--since={after}"], capture_output=True, text=True)
    (inp / "gitlog.txt").write_text(g.stdout if g.returncode == 0 else "")
    missing = sorted(p for p in _cited_paths(core, archive)
                     if p != "none" and not p.startswith(("~/", "/")) and not (Path(root) / p).exists())
    (inp / "missing-files.txt").write_text("".join(m + "\n" for m in missing))


def _kill_group(proc):
    """TERM the child's process group, give the leader a short grace, then KILL the group whether or not the leader
    is still alive (a grandchild may ignore TERM and hold the pipes), and reap with a bound: never hangs the night."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(GRACE)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.communicate(timeout=REAP)
    except subprocess.TimeoutExpired:
        proc.kill()
        for f in (proc.stdout, proc.stderr, proc.stdin):
            try:
                f and f.close()
            except OSError:
                pass


def _save_model_output(run_dir, out, err):
    """The model's stdout and stderr, kept in out/ so a night that failed (`model error`, `model exit N`) can be diagnosed."""
    try:
        o = Path(run_dir) / "out"
        o.mkdir(parents=True, exist_ok=True)
        (o / "model.stdout").write_text(out or "")
        (o / "model.stderr").write_text(err or "")
    except OSError:
        pass


def run_model(run_dir, project, now):
    """(failure text or None, info). G6: argv, cwd, scrubbed environment, the prompt on stdin."""
    argv = [os.environ.get("TC_DREAM_CLAUDE") or "claude", "-p", "--model", "sonnet", "--effort", "medium", "--restricted",
            "--tools", "Read,Grep,Glob,Write,Edit", "--permission-mode", "dontAsk",
            "--settings", str(REPO / "claude" / "dream-settings.json"), "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "json"]
    prompt = (REPO / "claude" / "dream.md").read_text() \
        + f"\n\nProject: {project}\nToday: {time.strftime('%Y-%m-%d', time.localtime(now))}\nCore cap: {context.CAP} bytes\n"
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    try:
        proc = subprocess.Popen(argv, cwd=str(run_dir), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError:
        return "model error", {}
    try:
        out, err = proc.communicate(prompt, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return "model timeout", {}
    _save_model_output(run_dir, out, err)
    if proc.returncode != 0:
        return f"model exit {proc.returncode}", {}
    res = None
    for cand in (out, *reversed(out.strip().splitlines())):
        try:
            res = json.loads(cand)
            break
        except ValueError:
            continue
    if not isinstance(res, dict) or res.get("is_error") is not False:
        return "model error", {}
    u = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    info = {"cost_usd": res.get("total_cost_usd"),
            "tokens": {k: u.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
            "model_s": (res.get("duration_ms") or 0) / 1000}
    return None, info


def _restore(project, run, core_before, had_archive):
    """Put both live files back from the backups; plain writes, never os.replace (that is what may have failed)."""
    context.context_path(project).write_bytes(P.backup_core(project, run).read_bytes())
    ap = context.archive_path(project)
    b = P.backup_archive(project, run).read_bytes()
    if b:
        ap.write_bytes(b)
    else:
        ap.unlink(missing_ok=True)


def commit(project, snapshot, new_core, new_archive, run, run_dir):
    """G8. snapshot = (core text, archive text or None) taken at the start. -> (failure text or None, final core, notice)."""
    snap_core, snap_arch = snapshot
    cp, ap = context.context_path(project), context.archive_path(project)
    try:
        lock = context.locked(project, wait=30)
        lock.__enter__()
    except ValueError as e:
        return f"write failed: {e}", None, None
    try:
        live_core = cp.read_text() if cp.is_file() else ""
        live_arch = ap.read_text() if ap.is_file() else None
        if live_arch != snap_arch:
            return "files changed during the run", None, None
        if live_core != snap_core:
            snap_lines = {l for _, l in context.entries(snap_core)}
            rows = context.entries(live_core)
            if not snap_lines <= {l for _, l in rows}:
                return "files changed during the run", None, None
            extra = [(s, l) for s, l in rows if l not in snap_lines]
            if not extra:
                return "files changed during the run", None, None
            new_core = context.append_missing(new_core, extra)
        P.backups_dir().mkdir(parents=True, exist_ok=True)
        P.backup_core(project, run).write_text(live_core)
        P.backup_archive(project, run).write_text(live_arch or "")
        try:
            for path, text in ((ap, new_archive), (cp, new_core)):
                tmp = path.with_name(f".{path.name}.tmp")
                tmp.write_text(text)
                os.replace(tmp, path)
        except Exception as e:
            for path in (ap, cp):
                path.with_name(f".{path.name}.tmp").unlink(missing_ok=True)
            _restore(project, run, live_core, live_arch is not None)
            return f"write failed: {e}", None, None
        out = Path(run_dir) / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "core.after.md").write_text(new_core)
        size = len(new_core.encode())
        notice = f"context: core over 8 KB ({size}), the nightly run will condense it" if size > context.CAP else None
        return None, new_core, notice
    finally:
        lock.__exit__(None, None, None)


def prune(project, now):
    cutoff = now - KEEP_DAYS * 86400
    for f in P.backups_dir().glob(f"{project}.*") if P.backups_dir().is_dir() else []:
        rid = f.name.rsplit(".", 1)[-1]
        if f.name in (f"{project}.md.{rid}", f"{project}.archive.md.{rid}"):
            t = P.id_time(rid)
            if t is not None and t < cutoff:
                f.unlink(missing_ok=True)
    pd = P.project_dir(project)
    for d in pd.iterdir() if pd.is_dir() else []:
        t = P.id_time(d.name)
        if d.is_dir() and t is not None and t < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def record_metrics(root, rec):
    p = metrics.mdir(root) / "runs.jsonl"
    if p.is_file():
        metrics.append(root, rec)


def notify(result):
    """Post the night to the project's Discord channel (G11); `posted` is set on result for run.json."""
    dream_discord.notify(result)


def _json_safe_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str))


def run_project(project, now, dry_run=False, force=False, root=None):
    """Run one project. -> result dict; outcome is ok | unchanged | failed | skipped."""
    t0 = time.monotonic()
    run = P.run_id(now)
    res = {"project": project, "run": run, "outcome": "skipped", "dry_run": dry_run, "failures": 0, "at": P.iso_utc(now),
           "check": None, "counts": None, "cost_usd": None, "tokens": None, "duration_s": 0, "proposals": [],
           "contradictions": [], "posted": False, "message": None, "diff": "", "notice": None, "summary": ""}
    state = P.load(project)
    res["failures"] = state.get("failures", 0) if isinstance(state.get("failures"), int) else 0
    root = resolve_root(project, state, root)
    if root is None:
        res["message"] = f"dream: {project} skipped, no repo root"
        return res
    lock_fd = None
    if not dry_run:
        pd = P.project_dir(project)
        pd.mkdir(parents=True, exist_ok=True)
        lock_fd = open(pd / "run.lock", "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_fd.close()
            res["message"] = f"dream: {project} already running"
            return res
    run_dir = None
    try:
        before = digest(project, root)
        if not force and state.get("sources_digest") == before:
            res["message"] = f"dream: {project} skipped, unchanged sources"
            return res
        if dry_run:
            run_dir = Path(tempfile.mkdtemp(prefix="dream-dry."))
        else:
            run_dir = P.run_dir(project, run)
            if run_dir.exists():
                res["message"] = f"dream: {project} already ran this minute"
                return res
            run_dir.mkdir(parents=True)
        res["run_dir"] = str(run_dir)
        check = _attempt(res, project, now, root, state, run_dir, run, dry_run)
        res["check"] = check
        if check:
            res["outcome"] = "failed"
        res["duration_s"] = round(time.monotonic() - t0, 3)
        if not dry_run:
            _finish(res, project, state, root, now, run_dir, run)
        return res
    except Exception as e:   # one project's surprise (git missing, an OSError copying an input) is a failed night, not a crash
        res["check"] = f"error: {type(e).__name__}: {e}"
        res["outcome"] = "failed"
        res["duration_s"] = round(time.monotonic() - t0, 3)
        if not dry_run:
            try:
                _finish(res, project, state, root, now, run_dir, run)
            except Exception as e2:
                print(f"dream: bookkeeping failed: {e2}", file=sys.stderr)
        return res
    finally:
        if dry_run and run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)
        if lock_fd:
            lock_fd.close()


def _attempt(res, project, now, root, state, run_dir, run, dry_run):
    """Everything between the skips and the bookkeeping; -> failure text or None. Fills res."""
    cp, ap = context.context_path(project), context.archive_path(project)
    old_core = cp.read_text() if cp.is_file() else ""
    old_arch = ap.read_text() if ap.is_file() else None
    arch_work = old_arch if old_arch is not None else f"# {project}: archived agent context\n\n{dream_check.SKELETON}"
    for name, text in (("core", old_core), ("archive", arch_work)):
        problems = dream_check.parse(text)[1]
        if problems:
            return f"{name} invalid: {problems[0]}"
    prepare(run_dir, project, root, state, old_core, arch_work, now)
    fail, info = run_model(run_dir, project, now)
    res.update({k: v for k, v in info.items() if k in ("cost_usd", "tokens")})
    if fail:
        return fail
    rp = Path(run_dir) / "out" / "report.json"
    if not rp.is_file():
        return "report missing"
    try:
        report = json.loads(rp.read_text())
    except ValueError:
        return "report invalid: not valid JSON"
    try:
        new_core = (Path(run_dir) / "core.md").read_text()
        new_arch = (Path(run_dir) / "archive.md").read_text()
    except OSError:
        return "core invalid: core.md or archive.md is missing"
    bad = dream_check.check(old_core, arch_work, new_core, new_arch, report, root)
    if bad:
        return bad
    res["counts"] = dream_check.counts(old_core, old_arch or "", new_core, new_arch, report)
    res["proposals"] = report["proposals"]
    res["contradictions"] = report["contradictions"]
    res["summary"] = report["summary"]
    if new_core == old_core and new_arch == arch_work:
        res["outcome"] = "unchanged"
        return None
    res["outcome"] = "ok"
    res["diff"] = dream_check.diff(old_core, arch_work, new_core, new_arch, project)
    if dry_run:
        return None
    err, final_core, notice = commit(project, (old_core, old_arch), new_core, new_arch, run, run_dir)
    if err:
        return err
    res["notice"] = notice
    res["diff"] = dream_check.diff(old_core, arch_work, final_core, (ap.read_text()), project)
    return None


def _write_run_json(out, res):
    keys = ("project", "run", "outcome", "check", "counts", "cost_usd", "tokens", "duration_s", "proposals", "contradictions", "posted")
    _json_safe_write(out / "run.json", {k: res[k] for k in keys})


def _finish(res, project, state, root, now, run_dir, run):
    """Bookkeeping of a real run: dream.json, out/ files, metrics, prune, notify. Errors here never fail the run."""
    out = Path(run_dir) / "out" if run_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    ok = res["outcome"] in ("ok", "unchanged")
    sd = digest(project, root) if ok else None
    try:
        lock = context.locked(project, wait=30)
        lock.__enter__()
    except ValueError:
        lock = None   # bookkeeping still runs; the merge below re-reads dream.json either way
    try:
        d = dict(P.load(project))   # fresh: only this run's own fields are merged, so a concurrent Revert is never overwritten
        d["root"] = root
        if ok:
            d.update({"last_run": res["at"], "sources_digest": sd, "failures": 0})
            if res["outcome"] == "ok":   # `run`, `reverted` and `last_report` follow the last run that committed: an unchanged night keeps Revert possible
                d.update({"last_report": str(out / "report.json"), "run": run, "reverted": None})
        else:
            n = d.get("failures")
            d["failures"] = res["failures"] = (n if isinstance(n, int) else 0) + 1
            d.setdefault("reverted", None)
        if ok:
            res["failures"] = 0
        P.save(project, d)
    finally:
        if lock:
            lock.__exit__(None, None, None)
    try:
        if out and res["diff"] is not None:
            (out / "diff.txt").write_text(res["diff"])
        if out:
            _write_run_json(out, res)
    except OSError as e:
        print(f"dream: could not write run files: {e}", file=sys.stderr)
    try:
        record_metrics(root, {"kind": "dream", "at": res["at"], "project": project, "run": run, "outcome": res["outcome"],
                              "cost_usd": res["cost_usd"], "tokens": res["tokens"], "duration_s": res["duration_s"], "model": "sonnet"})
    except Exception as e:
        print(f"dream: metrics line failed: {e}", file=sys.stderr)
    if ok:
        try:
            prune(project, now)
        except Exception as e:
            print(f"dream: prune failed: {e}", file=sys.stderr)
    try:
        notify(res)
        if res["posted"] and out:
            _write_run_json(out, res)
    except Exception as e:
        print(f"dream: notify failed: {e}", file=sys.stderr)


def render(res):
    if res["outcome"] == "skipped":
        return res["message"] + "\n"
    p = res["project"]
    if res["outcome"] == "failed":
        return f"dream: {p} failed — {res['check']}\n"
    word = "dry run" if res["dry_run"] else "ok"
    if res["outcome"] == "unchanged":
        s = f"dream: {p} {word} — no changes\n"
    else:
        c = res["counts"]
        s = (f"dream: {p} {word} — merged {c['merged']}, archived {c['archived']}, stale {c['stale']}, added {c['added']}; "
             f"{len(res['proposals'])} proposals; {len(res['contradictions'])} contradictions\n")
    if res["dry_run"] and res["diff"]:
        s += res["diff"] if res["diff"].endswith("\n") else res["diff"] + "\n"
    if res.get("notice"):
        s += res["notice"] + "\n"
    return s


def report(project):
    pd = P.project_dir(project)
    runs = sorted(d for d in (pd.iterdir() if pd.is_dir() else []) if d.is_dir() and (d / "out" / "run.json").is_file())
    if not runs:
        print(f"dream: {project} has no run yet")
        return 0
    out = runs[-1] / "out"
    try:
        for k, v in json.loads((out / "run.json").read_text()).items():
            if k not in ("proposals", "contradictions"):
                print(f"{k}: {v}")
        rep = json.loads((out / "report.json").read_text()) if (out / "report.json").is_file() else {}
        if rep.get("summary"):
            print(f"summary: {rep['summary']}")
        for k in ("proposals", "contradictions"):
            print(f"{k}:")
            for item in rep.get(k, []):
                print("  - " + json.dumps(item, ensure_ascii=False))
    except (OSError, ValueError) as e:
        print(f"dream: {project}: unreadable run record ({e})", file=sys.stderr)
        return 1
    return 0


def _empty_core(project):
    """True when the project's core has no '- ' entry lines (only title, Last curated and headings)."""
    try:
        return not context.entries(context.context_path(project).read_text())
    except OSError:
        return False


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(prog="dream")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("project", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--force", action="store_true")
    r.add_argument("--root")
    rp = sub.add_parser("report")
    rp.add_argument("project")
    fp = sub.add_parser("file")
    fp.add_argument("project")
    fp.add_argument("run", nargs="?")
    rv = sub.add_parser("revert")
    rv.add_argument("project")
    rv.add_argument("run")
    a = ap.parse_args(argv)
    if a.cmd in ("file", "revert"):
        try:
            context.context_path(a.project)
        except ValueError as e:
            print(f"dream: {e}", file=sys.stderr)
            return 2
        result = dream_actions.file_proposals(a.project, a.run) if a.cmd == "file" else dream_actions.revert(a.project, a.run)
        print(result)
        return 1 if result == "busy" or result == "unknown" or result.startswith("stale") else 0
    if a.cmd == "report":
        try:
            context.context_path(a.project)
        except ValueError as e:
            print(f"dream: {e}", file=sys.stderr)
            return 2
        return report(a.project)
    if bool(a.project) == bool(a.all):
        ap.error("give a project or --all")
    now = time.time() if now is None else now
    if os.environ.get("TC_DREAM") == "0" or (context.context_dir() / "dream.off").exists():
        print("dream: off")
        return 0
    if not a.force:
        pct = weekly_pct(now)
        if pct is not None and pct >= WEEKLY_MAX:
            print(f"dream: skipped, weekly {pct:g}%")
            return 0
    try:
        names = projects() if a.all else [a.project]
        for n in names:
            context.context_path(n)
    except ValueError as e:
        print(f"dream: {e}", file=sys.stderr)
        return 2
    rc = 0
    for n in names:
        if a.all and _empty_core(n):
            continue
        try:
            res = run_project(n, now, a.dry_run, a.force, a.root)
        except Exception as e:   # before the project's own guard (root lookup, lock file): still a failed night, and --all goes on
            res = {"outcome": "failed", "project": n, "check": f"error: {type(e).__name__}: {e}"}
        sys.stdout.write(render(res))
        sys.stdout.flush()
        if res["outcome"] == "failed":
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
