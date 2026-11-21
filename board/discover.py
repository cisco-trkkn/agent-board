#!/usr/bin/env python3
"""discover: opportunity discovery. `collect` merges every signal into one JSON, `rank` has the model pick the
few worth reporting and keeps only valid items. See docs/superpowers/specs/2026-11-12-opportunity-discovery-design.md."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream  # noqa: E402
import discover_post  # noqa: E402
import discover_repo  # noqa: E402
import discover_tests  # noqa: E402
import discord_feed  # noqa: E402
import metrics  # noqa: E402
import tc_env  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RANK_TIMEOUT = 600
FAIL_POST_AT = 3
KEEP_RUNS = 14
MAX_ITEMS = 5
VALUES = ("high", "medium", "low")
EFFORTS = ("S", "M", "L")


def _git_head(root):
    try:
        p = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def collect(project, root, now):
    """Run every collector; one that raises is listed in sources_skipped and the others still run."""
    base = tc_env.agent_base()
    history_path = base / "tests" / "history.jsonl"
    runs_path = tc_env.state_dir() / f"runs-{project}.jsonl"
    ledgers = Path(root) / "docs" / "superpowers" / "ledgers"
    cands, skipped = [], []

    def run(signal, fn, missing=None):
        if missing:
            skipped.append({"signal": signal, "why": missing})
            return
        try:
            cands.extend(fn())
        except Exception as e:   # noqa: BLE001 - a broken collector must not stop the night
            skipped.append({"signal": signal, "why": f"error: {type(e).__name__}: {e}"})

    no_hist = None if history_path.is_file() else "no test history"
    hist = []
    if not no_hist:
        try:
            hist = discover_tests.load_history(history_path, now)
        except Exception as e:   # noqa: BLE001
            no_hist = f"error: {type(e).__name__}: {e}"
    mine = discover_tests.for_root(hist, root)
    run("flaky_test", lambda: discover_tests.flaky_tests(mine, now), no_hist)
    run("slow_test", lambda: discover_tests.slow_tests(mine, now), no_hist)
    run("failed_run", lambda: discover_tests.failed_runs(runs_path, root, now),
        None if runs_path.is_file() else "no run records")
    no_led = None if ledgers.is_dir() else "no ledgers"
    run("repeated_ruling", lambda: discover_repo.repeated_rulings(root, now), no_led)
    run("deferred_minor", lambda: discover_repo.deferred_minors(root), no_led)
    run("todo", lambda: discover_repo.todos(root, now))
    try:
        dc, ds = discover_repo.dependencies(root)
        cands.extend(dc)
        skipped.extend(ds)
    except Exception as e:   # noqa: BLE001
        skipped.append({"signal": "dependency", "why": f"error: {type(e).__name__}: {e}"})
    ideas_file = _ideas_file(project)
    run("stale_idea", lambda: discover_repo.stale_ideas(project, now), None if ideas_file else "no ideas file")
    return {"project": project, "root": str(root), "at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "head": _git_head(root), "candidates": cands, "sources_skipped": skipped}


def _ideas_file(project):
    """True when the project's ideas file exists (the pre-refactor file counts, as ideas.load reads it)."""
    import ideas
    try:
        paths = [ideas.ideas_path(project), ideas._legacy_path(project)]
    except ValueError:
        return False
    return any(p is not None and p.is_file() for p in paths)


def validate(items, candidates):
    """Keep only items with a known key, in-range int evidence_refs, valid enums and text fields; at most 5."""
    by_key = {c["key"]: c for c in candidates}
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("key"), str) or it["key"] not in by_key or it["key"] in seen:
            continue
        if it.get("expected_value") not in VALUES or it.get("effort") not in EFFORTS:
            continue
        if not all(isinstance(it.get(k), str) and it[k].strip() for k in ("title", "why", "risk")):
            continue
        refs = it.get("evidence_refs")
        n = len(by_key[it["key"]].get("evidence") or [])
        if not isinstance(refs, list) or not all(type(r) is int and 0 <= r < n for r in refs):
            continue
        seen.add(it["key"])
        out.append({k: it[k] for k in ("key", "title", "why", "expected_value", "effort", "risk", "evidence_refs")})
    return out[:MAX_ITEMS]


def _parse_result(text):
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines[1:]).strip()
    return json.loads(t)


def run_model(run_dir, prompt):
    """(failure text or None, items-or-None, info)."""
    argv = [os.environ.get("TC_DISCOVER_CLAUDE") or "claude", "-p", "--model", "sonnet", "--effort", "medium", "--restricted",
            "--tools", "Read", "--permission-mode", "dontAsk", "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "json"]
    env = {k: v for k, v in os.environ.items() if k not in dream.SCRUB}
    try:
        proc = subprocess.Popen(argv, cwd=str(run_dir), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError:
        return "model error", None, {}
    try:
        out, err = proc.communicate(prompt, timeout=RANK_TIMEOUT)
    except subprocess.TimeoutExpired:
        dream._kill_group(proc)
        return "model timeout", None, {}
    try:
        (Path(run_dir) / "model-output.txt").write_text(out or "")
    except OSError:
        pass
    if proc.returncode != 0:
        return f"model exit {proc.returncode}", None, {}
    res = None
    for cand in (out, *reversed(out.strip().splitlines())):
        try:
            res = json.loads(cand)
            break
        except ValueError:
            continue
    if not isinstance(res, dict) or res.get("is_error") is not False or not isinstance(res.get("result"), str):
        return "model error", None, {}
    try:
        parsed = _parse_result(res["result"])
    except ValueError:
        return "model error", None, {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        return "model error", None, {}
    u = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    info = {"cost_usd": res.get("total_cost_usd"), "usage": u, "model_s": (res.get("duration_ms") or 0) / 1000}
    return None, parsed["items"], info


def runs_base(project):
    return tc_env.agent_base() / "discover" / "runs" / project


def new_run_dir(project, now):
    d = runs_base(project) / time.strftime("%Y%m%d-%H%M", time.localtime(now))
    d.mkdir(parents=True, exist_ok=True)
    return d


def prune_runs(project, keep=KEEP_RUNS):
    base = runs_base(project)
    if not base.is_dir():
        return
    for d in sorted(x for x in base.iterdir() if x.is_dir())[:-keep]:
        shutil.rmtree(d, ignore_errors=True)


def rank(project, root, now, run_dir):
    """-> (failure text or None, items, info). Writes collected.json, and rank.json only on success."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "rank.json").unlink(missing_ok=True)   # a failed run must not leave an earlier run's answer
    coll = collect(project, root, now)
    (run_dir / "collected.json").write_text(json.dumps(coll, indent=1))
    prompt = (REPO / "claude" / "discover.md").read_text() + f"\n\nProject: {project}\nCandidates: collected.json in the current directory\n"
    fail, items, info = run_model(run_dir, prompt)
    if fail:
        return fail, None, info
    kept = validate(items, coll["candidates"])
    (run_dir / "rank.json").write_text(json.dumps({"items": kept}, indent=1))
    return None, kept, info


def _state_root(project):
    try:
        d = json.loads((tc_env.agent_base() / "discover" / f"{project}.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _resolve(project, root_arg):
    r = dream.resolve_root(project, _state_root(project), root_arg)
    if not r:
        print(f"discover: no repo for {project}", file=sys.stderr)
    return r


def _iso_local(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _log(now, project, text):
    """discover.log, one line per night: `<ISO time> <project> failed: <reason>` or `<ISO time> <project> <outcome>`."""
    p = tc_env.agent_base() / "discover" / "discover.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(f"{_iso_local(now)} {project} {' '.join(str(text).split())}\n")


def _record(root, now, t0, project, outcome, ncand, nrank, nnew, skipped, info):
    """One kind=discover line in the project's runs.jsonl, only when that file exists."""
    if not metrics.log_path(root).is_file():
        return
    u = (info or {}).get("usage") or {}
    metrics.append(root, {"kind": "discover", "at": _iso_local(now), "project": project, "outcome": outcome,
                          "candidates": ncand, "ranked": nrank, "new": nnew, "sources_skipped": skipped,
                          "cost_usd": (info or {}).get("cost_usd"), "tokens": u, "duration_s": int(time.time() - t0),
                          "model": "sonnet"})


def _fail(project, root, now, t0, night, why, ncand, skipped, info, dry):
    print(f"discover: {project}: failed: {why}")
    if dry:
        return True
    def bump(st):
        st["failures"] += 1
        st["root"] = str(root)
    st = discover_post.update(project, bump)
    _log(now, project, f"failed: {why}")
    if st["failures"] == FAIL_POST_AT:
        text = f"🔎 discover: {project} failed {FAIL_POST_AT} nights running — {discover_post.escape(' '.join(why.split()))}"
        discord_feed.outbox_write(tc_env.discord_dir(project), {"op": "post", "text": text[:1900], "tier": "critical",
                                                                 "mention_user": True, "key": f"discover-{project}-fail-{night}"})
    _record(root, now, t0, project, "failed", ncand, 0, 0, skipped, info)
    return True


def _night(project, root, now, dry):
    """True when the night failed (model, collect or post)."""
    t0 = time.time()
    night = time.strftime("%Y%m%d", time.localtime(now))
    if not dry and night in discover_post.load_state(project)["posts"]:
        # a second run on the same night would replace the posted items' buttons (same post key): publish nothing
        print(f"discover: {project}: already posted {night}")
        _log(now, project, "nothing-new")
        _record(root, now, t0, project, "nothing-new", 0, 0, 0, [], {})
        return
    run_dir = new_run_dir(project, now)
    if dry:
        print(f"run dir: {run_dir}")
    try:
        try:
            fail, items, info = rank(project, root, now, run_dir)
        except Exception as e:   # noqa: BLE001 - a collect or rank error is a failed night
            return _fail(project, root, now, t0, night, f"{type(e).__name__}: {e}", 0, [], {}, dry)
        try:
            coll = json.loads((run_dir / "collected.json").read_text())
        except (OSError, ValueError):
            coll = {"candidates": [], "sources_skipped": []}
        cands = {c["key"]: c for c in coll["candidates"]}
        skipped = [s.get("signal") for s in coll["sources_skipped"]]
        ncand = len(cands)
        if fail:
            return _fail(project, root, now, t0, night, fail, ncand, skipped, info, dry)
        st = discover_post.load_state(project)
        sel = discover_post.select(items, cands, st, discover_post.memory_dirs(project))
        new, still, also = sel["new"], sel["still_open"], sel["also_memory"]
        try:
            op = discover_post.build_op(project, night, new, still, also, cands) if new else None
        except ValueError as e:
            return _fail(project, root, now, t0, night, f"post: {e}", ncand, skipped, info, dry)
        outcome = "posted" if new else "nothing-new"
        print(f"discover: {project}: {ncand} candidates, {len(items)} ranked, {len(new)} new, {('would post' if dry else 'posted') if new else 'nothing new'}")
        if dry:
            if op:
                print(op["text"])
                print("buttons: " + " | ".join(b["label"] for row in op["rows"] for b in row))
            return
        if new:
            try:
                discover_post.publish(project, night, new, still, also, cands, now)
            except ValueError as e:
                return _fail(project, root, now, t0, night, f"post: {e}", ncand, skipped, info, dry)
        def good(st):
            st["failures"], st["root"] = 0, str(root)
        discover_post.update(project, good)
        _log(now, project, outcome)
        _record(root, now, t0, project, outcome, ncand, len(items), len(new), skipped, info)
    finally:
        prune_runs(project)


def nightly(argv, now=None):
    ap = argparse.ArgumentParser(prog="discover nightly")
    ap.add_argument("--project")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    now = time.time() if now is None else now
    if os.environ.get("TC_DISCOVER") == "0" or (tc_env.agent_base() / "discover.off").exists():
        print("discover: off")
        return 0
    if not a.force:
        pct = dream.weekly_pct(now)
        if pct is not None and pct >= dream.WEEKLY_MAX:
            print(f"discover: skipped, weekly {pct:g}%")
            return 0
    names = [a.project] if a.project else dream.projects()
    rc = 0
    for n in names:
        try:
            root = dream.resolve_root(n, _state_root(n), None)
            if not root:
                print(f"discover: {n}: no repo")
                continue
            if _night(n, root, now, a.dry_run):
                rc = 1
        except Exception as e:   # noqa: BLE001 - one project must not stop the others
            print(f"discover: {n}: error: {type(e).__name__}: {e}", file=sys.stderr)
            rc = 1
    return rc


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(prog="discover")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("project")
    c.add_argument("--root")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("rank")
    r.add_argument("project")
    r.add_argument("--root")
    sub.add_parser("nightly").add_argument("rest", nargs="*")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "nightly":
        return nightly(argv[1:], now)
    a, extra = ap.parse_known_args(argv)
    if extra:
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    now = now if now is not None else time.time()
    root = _resolve(a.project, a.root)
    if not root:
        return 2
    if a.cmd == "collect":
        d = collect(a.project, root, now)
        if a.json:
            print(json.dumps(d, indent=1))
        else:
            for x in d["candidates"]:
                print(f"{x['signal']}\t{x['count']}\t{x['key']}\t{x['title']}")
            for s in d["sources_skipped"]:
                print(f"skipped: {s['signal']} ({s['why']})")
        return 0
    run_dir = new_run_dir(a.project, now)
    fail, items, _ = rank(a.project, root, now, run_dir)
    prune_runs(a.project)
    if fail:
        print(f"discover: {fail}", file=sys.stderr)
        return 1
    print(run_dir / "rank.json")
    for i in items:
        print(f"{i['expected_value']}\t{i['effort']}\t{i['key']}\t{i['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
