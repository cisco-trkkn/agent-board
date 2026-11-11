#!/usr/bin/env python3
"""metrics: the queue run log (docs/superpowers/metrics/runs.jsonl) and its commands.

Run log: one JSON object per line, kind in batch|start|run|defect (analysis is reserved; readers ignore unknown
kinds). Append-only; readers take the last `run` per (batch, spec); a malformed line is skipped and counted.
Nothing private goes in a line: no session ids, prompts, agent names, absolute paths.

CLI: metrics.py [--repo DIR] <batch start|start|record|defect|report|compare|backfill|gate|status> ...
A failing command prints one line `metrics: <sub>: <reason>` to stderr and exits 1. `tmux-ctl metrics` calls this.
"""
import argparse
import calendar
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import tc_env  # noqa: E402
import usage  # noqa: E402

METRICS_DIR = Path("docs/superpowers/metrics")
SUBS = ("batch start", "start", "record", "defect", "report", "compare", "backfill", "gate", "status")


class MetricsError(Exception):
    pass


def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise MetricsError((p.stderr.strip().splitlines() or ["git failed"])[-1])
    return p.stdout.strip()


def repo_root(repo_arg=None):
    return Path(_git(repo_arg or ".", "rev-parse", "--show-toplevel"))


def log_path(repo):
    return Path(repo) / METRICS_DIR / "runs.jsonl"


def read_log(repo):
    """(lines, malformed_count): every parsed JSON object (unknown kinds kept), bad lines counted."""
    p = log_path(repo)
    if not p.exists():
        return [], 0
    out, bad = [], 0
    for raw in p.read_text().splitlines():
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if isinstance(d, dict):
            out.append(d)
        else:
            bad += 1
    return out, bad


def append(repo, obj):
    p = log_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def last_runs(lines):
    """{(batch, spec): last `run` line}; other kinds are ignored."""
    out = {}
    for d in lines:
        if d.get("kind") == "run":
            out[(d.get("batch"), d.get("spec"))] = d
    return out


def _fence(text, tag):
    m = re.search(r"```" + re.escape(tag) + r"[ \t]*\n(.*?)\n```", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _load(repo, sub, name, tag):
    p = Path(repo) / METRICS_DIR / sub / (name + ".md")
    if not p.exists():
        return None
    return _fence(p.read_text(), tag)


def load_config(repo, id):
    return _load(repo, "configs", id, "json:config")


def load_gate(repo, id):
    return _load(repo, "gates", id, "json:gate")


def utc(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def new_batch_id(repo, today):
    n = sum(1 for d in read_log(repo)[0] if d.get("kind") == "batch" and str(d.get("batch", "")).startswith(today + "-"))
    return f"{today}-{n + 1}"


def unit_key(batch_id, first_spec):
    return hashlib.sha256((batch_id + first_spec).encode()).hexdigest()


def assign(batch_id, specs, groups, configs, baseline):
    """{spec: config}. Units (a group, or a lone spec) sorted by hash, configs alternate starting with the baseline."""
    if len(configs) == 1:
        return {s: configs[0] for s in specs}
    grouped = {s for g in groups for s in g}
    units = [list(g) for g in groups] + [[s] for s in specs if s not in grouped]
    units.sort(key=lambda u: unit_key(batch_id, u[0]))
    cyc = [baseline] + [c for c in configs if c != baseline]
    out = {}
    for i, u in enumerate(units):
        for s in u:
            out[s] = cyc[i % len(cyc)]
    return out


def _baseline(repo, configs):
    flagged = [c for c in configs if (load_config(repo, c) or {}).get("baseline") is True]
    return flagged[0] if len(flagged) == 1 else configs[0]


def cmd_batch_start(repo, args):
    configs = args.config
    for c in configs:
        if load_config(repo, c) is None:
            raise MetricsError(f"unknown config {c}")
    groups = [[s.strip() for s in g.split(",") if s.strip()] for g in args.group]
    specs = args.specs
    for g in groups:
        for s in g:
            if s not in specs:
                raise MetricsError(f"group member {s} is not a listed spec")
    bid = new_batch_id(repo, time.strftime("%Y-%m-%d", time.gmtime()))
    asg = assign(bid, specs, groups, configs, _baseline(repo, configs))
    append(repo, {"kind": "batch", "batch": bid, "base": _git(repo, "rev-parse", "main"), "configs": configs,
                  "assignment": asg, "groups": groups, "at": utc()})
    print(bid)
    for s in specs:
        print(f"{s} {asg[s]}")


def cmd_start(repo, args):
    if not any(d.get("kind") == "batch" and d.get("batch") == args.batch for d in read_log(repo)[0]):
        raise MetricsError(f"unknown batch {args.batch}")
    now = time.time()
    pl = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
    rec = {"kind": "start", "batch": args.batch, "spec": args.spec, "at": utc(now), "main": _git(repo, "rev-parse", "main")}
    if pl:
        rec["limits"] = {"five_hour": pl.get("five_hour"), "seven_day": pl.get("seven_day")}
    else:
        rec["limits"] = None
        rec["missing"] = ["limits"]
    append(repo, rec)


def cmd_defect(repo, args):
    append(repo, {"kind": "defect", "spec": args.spec, "what": args.what, "date": time.strftime("%Y-%m-%d", time.gmtime())})


# ---- record: the git- and file-derived half of a run line -------------------------------------------------------

EXCLUDED = "docs/superpowers/"
OUTCOMES = ("merged", "mr", "kept", "failed")
RESERVED = ("manifest_tokens", "lock_wait_s", "lock_wait_cause", "repair_runs", "integration_s", "integration_tokens")
LEDGER_KEYS = ("bounces", "fix_rounds", "final_findings", "fix_wave", "rulings", "parked")


def _git_try(repo, *args):
    """(rc, stdout) without raising."""
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def _epoch(iso):
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def _read(repo, ref, rel):
    """File text from the working tree, else from `ref`'s tree; None when neither has it."""
    p = Path(repo) / rel
    if p.is_file():
        return p.read_text()
    if ref:
        rc, out = _git_try(repo, "show", f"{ref}:{rel}")
        if rc == 0:
            return out
    return None


def _spec_core(spec):
    return re.sub(r"#part-\d+$", "", spec)


def find_plan(repo, spec):
    """(plan path, text, ref) of the plan whose header names the spec, else None. Working tree first, then branches."""
    core = _spec_core(spec)
    sources = []
    for f in sorted((Path(repo) / "docs/superpowers/plans").glob("*.md")):
        sources.append(("", str(f.relative_to(repo)), f.read_text()))
    rc, refs = _git_try(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    for ref in refs.split() if rc == 0 else []:
        rc, names = _git_try(repo, "ls-tree", "--name-only", ref, "docs/superpowers/plans/")
        for n in names.split() if rc == 0 else []:
            if n.endswith(".md"):
                rc, text = _git_try(repo, "show", f"{ref}:{n}")
                if rc == 0:
                    sources.append((ref, n, text))
    hits = []
    for ref, path, text in sources:
        for line in text.splitlines()[:40]:
            if "**Spec:**" in line and core in line:
                hits.append((ref, path, text, spec in line))
                break
    if not hits:
        return None
    hits.sort(key=lambda h: (not h[3], h[0] != ""))  # a line carrying the #part-N suffix first, working tree first
    ref, path, text, _ = hits[0]
    return path, text, ref or None


def parse_tasks(text):
    """{"tasks": n, "tiers": {tier: n}, "declared": set of repo-relative files minus docs/superpowers/}."""
    d = json.loads(text)
    tiers, declared, n = {}, set(), 0
    for t in d.get("tasks", []):
        n += 1
        meta = _fence(t.get("description") or "", "json:metadata") or {}
        tier = meta.get("modelTier") or "unspecified"
        tiers[tier] = tiers.get(tier, 0) + 1
        declared.update(f for f in meta.get("files", []) if isinstance(f, str) and not f.startswith(EXCLUDED))
    return {"tasks": n, "tiers": tiers, "declared": declared}


def ledger_fields(progress, final_review):
    """M-ledger counters from the progress text and (optional) final-review text."""
    lines = progress.splitlines()
    out = {
        "bounces": sum(1 for l in lines if re.search(r"review.*❌|quality ❌", l)),
        "fix_rounds": sum(1 for l in lines if "fix round" in l),
        "fix_wave": any("fix wave" in l.lower() for l in lines),
        "rulings": sum(1 for l in lines if l.startswith("Ruling:")),
        "parked": sum(1 for l in lines if "minor (deferred)" in l or "parked" in l),
    }
    n, active = 0, False
    for l in (final_review or "").splitlines():
        if l.startswith("#"):
            active = "Important" in l or "Critical" in l
        elif active and l.startswith("- "):
            n += 1
    out["final_findings"] = n
    return out


def _first_commit(repo, path):
    rc, out = _git_try(repo, "log", "--all", "--reverse", "--format=%H %ct", "--", path)
    first = out.splitlines()[0].split() if rc == 0 and out.strip() else None
    return (first[0], int(first[1])) if first else (None, None)


def find_merge(repo, plan_commit, since_ts, slug):
    """The first-parent merge on main (at/after since_ts) that brought the plan's work in.

    1. the first merge whose second parent contains the plan's first commit and whose first parent does not;
    2. else, when the plan commit was already on main, the first merge whose subject branch ends with `slug`
       (the plan basename without its date prefix);
    3. else None."""
    rc, out = _git_try(repo, "log", "--first-parent", "--merges", "--reverse", "main", "--format=%H%x09%P%x09%ct%x09%s")
    if rc != 0:
        return None
    cands = []
    for line in out.splitlines():
        sha, parents, ct, subject = (line.split("\t", 3) + [""])[:4]
        ps = parents.split()
        if len(ps) >= 2 and int(ct) >= since_ts:
            cands.append({"sha": sha, "first": ps[0], "second": ps[1], "ct": int(ct), "subject": subject})

    def has(commit):
        return _git_try(repo, "merge-base", "--is-ancestor", plan_commit, commit)[0] == 0

    for c in cands:
        if has(c["second"]) and not has(c["first"]):
            return c
    for c in cands:
        m = re.match(r"Merge branch '([^']+)'", c["subject"])
        if m and slug and m.group(1).endswith(slug):
            return c
    return None


def _numstat(repo, base, head):
    rc, out = _git_try(repo, "diff", "--numstat", "--no-renames", f"{base}..{head}")
    if rc != 0:
        return None
    touched, lines = set(), 0
    for l in out.splitlines():
        a, b, path = l.split("\t", 2)
        if path.startswith(EXCLUDED):
            continue
        touched.add(path)
        lines += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
    return touched, lines


def stale_base(repo, base, batch_base, head):
    """merge-tree probe. Layout of `git merge-tree --write-tree --name-only --merge-base=B X Y`:
    line 1 the result tree OID; on conflict (rc 1) the conflicted paths follow, one per line, then a blank line and
    the informational messages; rc 0 prints only the OID; any other rc (128: bad object) is a failure."""
    p = subprocess.run(["git", "-C", str(repo), "merge-tree", "--write-tree", "--name-only", f"--merge-base={base}",
                        batch_base, head], capture_output=True, text=True)
    if p.returncode == 0:
        return {"result": "clean", "paths": []}
    if p.returncode == 1:
        paths = []
        for l in p.stdout.splitlines()[1:]:
            if not l.strip():
                break
            paths.append(l)
        return {"result": "conflict", "paths": paths}
    return None


def build_record_static(repo, spec, batch, outcome, now, branch=None):
    """The `run` line fields that come from git, the plan and the ledger. Missing sources are null and named in `missing`."""
    repo = Path(repo)
    lines, _ = read_log(repo)
    batch_line = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == batch), None)
    start = next((d for d in reversed(lines) if d.get("kind") == "start" and d.get("batch") == batch and d.get("spec") == spec), None)
    missing = []
    rec = {"kind": "run", "batch": batch, "spec": spec, "at": utc(now)}

    def null(*keys):
        for k in keys:
            rec[k] = None
            missing.append(k)

    rec["started_at"] = start["at"] if start else None
    if not start:
        missing.append("started_at")

    plan = find_plan(repo, spec)
    plan_path = plan_ref = None
    if plan:
        plan_path, _, plan_ref = plan
    rec["plan"] = plan_path
    if not plan:
        missing.append("plan")
    plan_commit, plan_ts = _first_commit(repo, plan_path) if plan else (None, None)

    merge = None
    if plan_commit:
        since = _epoch(start["at"]) if start else plan_ts
        slug = re.sub(r"^\d{4}-\d\d-\d\d-", "", Path(plan_path).name[:-3])
        merge = find_merge(repo, plan_commit, since, slug)
    head = base = None
    if merge:
        m = re.match(r"Merge branch '([^']+)'", merge["subject"])
        branch = m.group(1) if m else branch
        head = merge["second"]
        rc, mb = _git_try(repo, "merge-base", merge["first"], head)
        base = mb.strip() if rc == 0 and mb.strip() else None
        rec["merge"] = merge["sha"]
    else:
        rec["merge"] = None
        # the plan commit already on main makes `--contains` list every later branch: no guess then, only --branch
        on_main = plan_commit and _git_try(repo, "merge-base", "--is-ancestor", plan_commit, "main")[0] == 0
        if not branch and plan_commit and not on_main:
            rc, out = _git_try(repo, "branch", "--contains", plan_commit, "--format=%(refname:short)")
            branch = next((b for b in out.split() if b != "main"), None) if rc == 0 else None
        if branch:
            rc, tip = _git_try(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
            head = tip.strip() if rc == 0 and tip.strip() else None
            if head:
                rc, mb = _git_try(repo, "merge-base", "main", head)
                base = mb.strip() if rc == 0 and mb.strip() else None
    rec["branch"], rec["head"], rec["base"] = branch, head, base
    for k in ("branch", "head", "base"):
        if rec[k] is None:
            missing.append(k)
    rec["ended_at"] = utc(merge["ct"]) if merge else utc(now)

    word = (outcome or "").split()[0].lower() if (outcome or "").strip() else None
    if word is None:
        rec["outcome"] = "merged" if rec["merge"] else "kept"
    else:
        rec["outcome"] = word
        if word not in OUTCOMES:
            missing.append("outcome")
    if rec["merge"] is None and rec["outcome"] in ("merged", "mr"):
        missing.append("merge")

    info = None
    tasks_text = _read(repo, plan_ref, plan_path + ".tasks.json") if plan_path else None
    if tasks_text:
        try:
            info = parse_tasks(tasks_text)
        except (ValueError, AttributeError, TypeError):
            info = None
    if info:
        rec["tasks"], rec["tiers"], rec["declared_files"] = info["tasks"], info["tiers"], len(info["declared"])
        rec["declared_list"] = sorted(info["declared"])
    else:
        null("tasks", "tiers", "declared_files", "declared_list")

    ns = _numstat(repo, base, head) if base and head else None
    if ns:
        touched, rec["diff_lines"] = ns
        rec["touched_files"] = len(touched)
        rec["touched_list"] = sorted(touched)
    else:
        touched = None
        null("touched_files", "diff_lines", "touched_list")
    if info and touched is not None:
        both = len(info["declared"] & touched)
        rec["manifest"] = {"declared": len(info["declared"]), "touched": len(touched), "both": both,
                           "precision": round(both / len(info["declared"]), 4) if info["declared"] else None,
                           "recall": round(both / len(touched), 4) if touched else None}
    else:
        null("manifest")

    progress = None
    if plan_path:
        ldir = "docs/superpowers/ledgers/" + Path(plan_path).name[:-3]
        progress = _read(repo, plan_ref, ldir + "/progress.md")
    if progress is not None:
        rec.update(ledger_fields(progress, _read(repo, plan_ref, ldir + "/final-review.md")))
    else:
        null(*LEDGER_KEYS)

    sb = stale_base(repo, base, batch_line["base"], head) if base and head and batch_line and batch_line.get("base") else None
    rec["stale_base"] = sb
    if sb is None:
        missing.append("stale_base")
    for k in RESERVED:
        rec[k] = None
    rec["missing"] = missing
    return rec


# ---- record: the usage-index half and the command ----------------------------------------------------------------

LEAD_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def main_root(repo):
    """The main checkout's root: transcripts and lead rows are keyed by it even when the cwd is a worktree."""
    rc, out = _git_try(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = Path(out.strip()) if rc == 0 and out.strip() else None
    if common and common.name == ".git":
        return str(common.parent)
    return str(Path(repo))


def slug_of(path):
    return str(path).replace("/", "-").replace(".", "-")


def worktree_dirs(repo, root, branch, conn):
    """Directories of worktrees on `branch`: from `git worktree list`, plus names seen in rows with that git_branch."""
    dirs = set()
    if branch:
        rc, out = _git_try(repo, "worktree", "list", "--porcelain")
        cur = None
        for l in out.splitlines() if rc == 0 else []:
            if l.startswith("worktree "):
                cur = l[9:]
            elif l == f"branch refs/heads/{branch}" and cur:
                dirs.add(cur)
        for (cwd,) in conn.execute("select distinct cwd from calls where git_branch=?", (branch,)):
            m = re.match(re.escape(root) + r"/\.claude/worktrees/[^/]+", cwd or "")
            if m:
                dirs.add(m.group(0))
    return dirs


def is_lead(r):
    return not r["agent_name"] and not r["sidechain"] and not r["subagent_file"]


def attributed_rows(conn, root, branch, wt_dirs, window, others):
    """[(row, weight)] per M-attr. window = (start_ts, end_ts); others = windows of the batch's other started specs.

    Branch and worktree rows weigh 1. A lead row with cwd == the repo root weighs 1/k, k = this spec plus the other
    specs whose window contains the row."""
    lo, hi = window
    out = []
    for r in usage._rows(conn, "select * from calls where ts>=? and ts<=?", (lo, hi)):
        cwd = r["cwd"] or ""
        by_branch = branch is not None and r["git_branch"] == branch
        by_dir = any(cwd == d or cwd.startswith(d + "/") for d in wt_dirs)
        if by_branch or by_dir:
            out.append((r, 1.0))
        elif is_lead(r) and cwd == root:
            k = 1 + sum(1 for a, b in others if a <= r["ts"] <= b)
            out.append((r, 1.0 / k))
    return out


def budget(weighted, prices):
    tot = {k: 0.0 for k in LEAD_KEYS}
    usd = unpriced = 0
    by_role = {"lead": [0.0, 0.0], "agents": [0.0, 0.0]}
    by_model, shared = {}, False
    for r, w in weighted:
        t = sum(r[k] for k in LEAD_KEYS) * w
        c = usage.call_cost(r, prices)
        if c is None:
            unpriced += 1
        role = by_role["lead" if is_lead(r) else "agents"]
        role[0] += t
        role[1] += (c or 0.0) * w
        usd += (c or 0.0) * w
        for k in LEAD_KEYS:
            tot[k] += r[k] * w
        by_model[r["model"]] = by_model.get(r["model"], 0.0) + t
        shared = shared or w < 1.0
    total = round(sum(tot.values()))
    return {"tokens": {"input": round(tot["input"]), "output": round(tot["output"]), "cache_read": round(tot["cache_read"]),
                       "cache_write": round(tot["cache_write_5m"] + tot["cache_write_1h"]), "total": total},
            "usd": round(usd, 6), "unpriced_calls": unpriced,
            "by_role": {k: {"tokens": round(v[0]), "usd": round(v[1], 6)} for k, v in by_role.items()},
            "lead_share": round(by_role["lead"][0] / sum(v[0] for v in by_role.values()), 4) if total else None,
            "by_model": {m: round(v) for m, v in by_model.items()}, "lead_shared": shared}


def time_fields(batch_at, start_ts, end_ts, weighted):
    """M-active and the time numbers; ready_at is the batch time."""
    minutes, agents = set(), {}
    for r, _ in weighted:
        m = int(r["ts"] // 60)
        minutes.add(m)
        if not is_lead(r):
            agents.setdefault(m, set()).add(r["session_id"])
    buckets = {"0": 0, "1": 0, "2+": 0}
    for m in minutes:
        n = len(agents.get(m, ()))
        buckets["2+" if n >= 2 else str(n)] += 1
    ready = _epoch(batch_at) if batch_at else None
    return {"ready_at": batch_at, "wait_s": int(start_ts - ready) if ready is not None else None,
            "elapsed_s": int(end_ts - start_ts), "active_min": len(minutes), "agents_active_min": buckets}


def transcript_dirs(root):
    base = usage.root()
    slug = slug_of(root)
    dirs = [base / slug] + sorted(base.glob(slug + "--claude-worktrees-*"))
    return [d for d in dirs if d.is_dir()]


def count_questions(root, window):
    """AskUserQuestion tool_use blocks in lead transcript lines inside the window; None when no transcripts dir."""
    dirs = transcript_dirs(root)
    if not dirs:
        return None
    lo, hi = window
    n = 0
    for d in dirs:
        for f in d.rglob("*.jsonl"):
            if "subagents" in f.parts:
                continue
            try:
                if f.stat().st_mtime < lo:
                    continue
                text = f.read_text()
            except OSError:
                continue
            for raw in text.splitlines():
                if "AskUserQuestion" not in raw:
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get("agentName") or not lo <= usage._epoch(d.get("timestamp")) <= hi:
                    continue
                content = (d.get("message") or {}).get("content")
                if isinstance(content, list):
                    n += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion")
    return n


def count_handoffs(project, window):
    p = tc_env.lineage_dir() / f"{project}.jsonl"
    if not p.exists():
        return 0
    lo, hi = window
    n = 0
    for raw in p.read_text().splitlines():
        try:
            ts = float(json.loads(raw)["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if lo <= ts <= hi:
            n += 1
    return n


def _other_windows(lines, batch, spec, now):
    """Windows of the batch's other specs that have a start line; an unrecorded one runs to now."""
    runs = last_runs(lines)
    out = []
    for d in lines:
        if d.get("kind") == "start" and d.get("batch") == batch and d.get("spec") != spec:
            later = [x for x in lines if x.get("kind") == "start" and x.get("batch") == batch and x.get("spec") == d["spec"]]
            if later[-1] is not d:
                continue
            run = runs.get((batch, d["spec"]))
            end = _epoch(run["ended_at"]) if run and run.get("ended_at") else now
            out.append((_epoch(d["at"]), end))
    return out


def build_record(repo, spec, batch, outcome, now, branch=None, conn=None, project=None, window=None):
    """The whole `run` line: build_record_static plus the usage half. `window` = (start_ts, end_ts, kind) overrides
    the stamped window (backfill)."""
    repo = Path(repo)
    lines, _ = read_log(repo)
    batch_line = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == batch), None)
    start = next((d for d in reversed(lines) if d.get("kind") == "start" and d.get("batch") == batch and d.get("spec") == spec), None)
    rec = build_record_static(repo, spec, batch, outcome, now, branch=branch)
    missing = rec["missing"]
    if window:
        lo, hi, kind = window
        rec["started_at"], rec["ended_at"] = utc(lo), utc(hi)
        if "started_at" in missing:
            missing.remove("started_at")
    elif start:
        lo, hi, kind = _epoch(start["at"]), _epoch(rec["ended_at"]), "stamped"
    else:
        lo, hi, kind = _epoch(batch_line["at"]) if batch_line else now, _epoch(rec["ended_at"]), "derived"
        if batch_line:
            rec["started_at"] = batch_line["at"]
    rec["window"], rec["backfilled"] = kind, False
    assign_cfg = (batch_line or {}).get("assignment") or {}
    rec["config"] = "seq-sdd" if batch == "backfill" else assign_cfg.get(spec)
    root = main_root(repo)
    others = _other_windows(lines, batch, spec, now) if start and kind == "stamped" else []
    wt = worktree_dirs(repo, root, rec["branch"], conn)
    weighted = attributed_rows(conn, root, rec["branch"], wt, (lo, hi), others)
    rec.update(budget(weighted, usage.load_prices()))
    rec.update(time_fields((batch_line or {}).get("at"), lo, hi, weighted))
    pl = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
    rec["limits"] = {"start": (start or {}).get("limits"),
                     "record": {"five_hour": pl.get("five_hour"), "seven_day": pl.get("seven_day")} if pl else None}
    if not pl:
        missing.append("limits")
    rec["questions"] = count_questions(root, (lo, hi))
    if rec["questions"] is None:
        missing.append("questions")
    rec["handoffs"] = count_handoffs(project or Path(root).name, (lo, hi))
    return rec


def ingest_project(conn, root):
    for d in transcript_dirs(root):
        for f in sorted(d.rglob("*.jsonl")):
            try:
                usage.ingest(conn, f)
            except OSError:
                pass


def cmd_record(repo, args):
    if not any(d.get("kind") == "batch" and d.get("batch") == args.batch for d in read_log(repo)[0]):
        raise MetricsError(f"unknown batch {args.batch}")
    conn = usage.connect(args.usage_db or usage.db_path())
    try:
        if not args.no_ingest:
            ingest_project(conn, main_root(repo))
        rec = build_record(repo, args.spec, args.batch, args.outcome, time.time(), branch=args.branch, conn=conn, project=args.project)
    finally:
        conn.close()
    append(repo, rec)
    tasks = rec["tasks"] if rec["tasks"] is not None else "?"
    print(f"recorded {args.spec} {args.batch}: {tasks} tasks, {rec['tokens']['total'] / 1e6:.2f}M tokens, {rec['active_min']} active min")


# ---- report ------------------------------------------------------------------------------------------------------

BASELINE_SENTENCE = "These numbers see textual conflicts only. Two specs that merge cleanly can still be wrong together."


def clean_reason(reason, repo):
    """No absolute paths in a stored reason: the repo root becomes `.`, $HOME `~`, any other absolute path `<path>`."""
    import os
    text = str(reason)
    roots = sorted({str(repo), str(Path(repo).resolve())}, key=len, reverse=True)
    for r in roots:
        text = text.replace(r, ".")
    home = os.environ.get("HOME")
    if home and home != "/":
        text = text.replace(home, "~")
    return re.sub(r"(?<![\w.~])/(?:[\w.@+-]+/)*[\w.@+-]+", "<path>", text)


def _merge_trees(repo, base, x, y):
    """`git merge-tree --write-tree --merge-base=<commit> <x> <y>`: x and y may be trees. Probe (git 2.54): tree OIDs are
    accepted as the two sides with a commit as the merge base (rc 0 clean, rc 1 conflict, the OID first, then the paths
    with --name-only). Returns (tree, conflicted paths or []) for rc 0/1, None for any other failure."""
    p = subprocess.run(["git", "-C", str(repo), "merge-tree", "--write-tree", "--name-only", f"--merge-base={base}", x, y],
                       capture_output=True, text=True)
    if p.returncode not in (0, 1):
        return None
    out = p.stdout.splitlines()
    if not out:
        return None
    paths = []
    if p.returncode == 1:
        for l in out[1:]:
            if not l.strip():
                break
            paths.append(l)
    return out[0], p.returncode == 0, paths


def _spec_tree(repo, run, batch_base):
    r = _merge_trees(repo, run["base"], batch_base, run["head"])
    return r[0] if r and r[1] else None


def greedy_waves(lists):
    """Greedy colouring of the file-sharing graph: {spec: color}; vertices by degree desc, then spec path."""
    specs = sorted(lists)
    adj = {s: {t for t in specs if t != s and set(lists[s]) & set(lists[t])} for s in specs}
    order = sorted(specs, key=lambda s: (-len(adj[s]), s))
    color = {}
    for s in order:
        used = {color[t] for t in adj[s] if t in color}
        c = 0
        while c in used:
            c += 1
        color[s] = c
    return color


def _pct(d):
    if isinstance(d, dict):
        v = d.get("used_percentage")
        return json.dumps(d, sort_keys=True) if v is None else str(v)
    return "-" if d is None else str(d)


def _limits_line(label, lim):
    if not isinstance(lim, dict):
        return f"{label}: -"
    return f"{label}: five_hour {_pct(lim.get('five_hour'))}, seven_day {_pct(lim.get('seven_day'))}"


def _cell(v):
    return "-" if v is None else str(v)


def _union_active(repo, runs, usage_db):
    conn = usage.connect(usage_db)
    try:
        root = main_root(repo)
        minutes = set()
        for r in runs:
            if not (r.get("started_at") and r.get("ended_at")):
                continue
            wt = worktree_dirs(repo, root, r.get("branch"), conn)
            for row, _ in attributed_rows(conn, root, r.get("branch"), wt, (_epoch(r["started_at"]), _epoch(r["ended_at"])), []):
                minutes.add(int(row["ts"] // 60))
        return len(minutes)
    finally:
        conn.close()


def report_text(repo, batch_id, usage_db=None):
    repo = Path(repo)
    lines, malformed = read_log(repo)
    batch = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == batch_id), None)
    if batch is None:
        raise MetricsError(f"unknown batch {batch_id}")
    runs_by = last_runs(lines)
    runs = [runs_by[k] for k in sorted(runs_by, key=lambda k: str(k[1])) if k[0] == batch_id]
    starts = [d for d in lines if d.get("kind") == "start" and d.get("batch") == batch_id]
    out, missing, excluded = [f"## Metrics: batch {batch_id}", ""], [], []
    for s in sorted((batch.get("assignment") or {})):
        if not any(r["spec"] == s for r in runs):
            excluded.append(f"{s} (no run line)")

    out.append("| spec | outcome | tasks | tokens | tokens/task | active min | lead share | fix rounds | manifest recall | stale base |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        tot = (r.get("tokens") or {}).get("total")
        tasks = r.get("tasks")
        per = round(tot / tasks) if tot is not None and tasks else None
        cells = [r["spec"], r.get("outcome"), tasks, tot, per, r.get("active_min"), r.get("lead_share"), r.get("fix_rounds"),
                 (r.get("manifest") or {}).get("recall"), (r.get("stale_base") or {}).get("result")]
        out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    out += ["", BASELINE_SENTENCE, ""]

    # throughput
    accepted = [r for r in runs if r.get("outcome") in ("merged", "mr")]
    a_tasks = sum(r.get("tasks") or 0 for r in accepted)
    wins = sorted((_epoch(r["started_at"]), _epoch(r["ended_at"])) for r in runs if r.get("started_at") and r.get("ended_at"))
    overlap = any(wins[i][1] > wins[i + 1][0] for i in range(len(wins) - 1)) if wins else False
    note = ""
    if overlap and usage_db:
        active = _union_active(repo, runs, usage_db)
    else:
        active = sum(r.get("active_min") or 0 for r in runs)
        note = " (sum, windows overlap)" if overlap else ""
    out.append(f"Accepted: {len(accepted)} specs, {a_tasks} tasks; batch active {active} min{note}")
    if active:
        h = active / 60
        out.append(f"Throughput per active hour: {len(accepted) / h:.2f} specs, {a_tasks / h:.2f} tasks")
    else:
        out.append("Throughput per active hour: -")
    out.append("")

    # overlap and waves
    def lists_of(key):
        got = {r["spec"]: r[key] for r in runs if isinstance(r.get(key), list)}
        for r in runs:
            if r["spec"] not in got:
                reason = f"{r['spec']} (no {key})"
                if reason not in excluded:
                    excluded.append(reason)
        return got
    touched, declared = lists_of("touched_list"), lists_of("declared_list")
    specs = sorted(set(touched) | set(declared))
    pairs = [(a, b) for i, a in enumerate(specs) for b in specs[i + 1:]]
    n_over = 0
    out.append("Overlap per pair:")
    for a, b in pairs:
        sd = sorted(set(declared.get(a, [])) & set(declared.get(b, [])))
        st = sorted(set(touched.get(a, [])) & set(touched.get(b, [])))
        if st:
            n_over += 1
        if sd or st:
            out.append(f"- {a} <-> {b}: declared {len(sd)} ({', '.join(sd)}), touched {len(st)} ({', '.join(st)})")
    out.append(f"Pairs overlapping: {n_over} of {len(pairs)}")
    counts = {}
    for fl in touched.values():
        for f in fl:
            counts[f] = counts.get(f, 0) + 1
    hot = sorted((f for f, n in counts.items() if n >= 3), key=lambda f: (-counts[f], f))
    out.append("Hot files (touched by 3+ specs): " + (", ".join(f"{f} ({counts[f]})" for f in hot) if hot else "none"))
    for label, lists in (("touched", touched), ("declared", declared)):
        col = greedy_waves(lists)
        w = max(col.values()) + 1 if col else 0
        out.append(f"Waves ({label} files): {w}, {len(col)} specs / {w} waves = {len(col) / w:.2f}" if w else f"Waves ({label} files): 0")
    out.append("")

    # parallel-buildable pairs
    by = {r["spec"]: r for r in runs}
    cand = [s for s in sorted(by)]
    cpairs = [(a, b) for i, a in enumerate(cand) for b in cand[i + 1:]]
    def ok(r):
        res = (r.get("stale_base") or {}).get("result")
        return res == "conflict" or (res == "clean" and bool(r.get("base")) and bool(r.get("head")))
    usable = [(a, b) for a, b in cpairs if ok(by[a]) and ok(by[b])]
    clean, bad, failed = 0, [], False
    trees = {}
    for a, b in usable:
        sa, sb = by[a]["stale_base"], by[b]["stale_base"]
        if sa["result"] == "conflict" or sb["result"] == "conflict":
            paths = sorted(set(sa.get("paths") or []) | set(sb.get("paths") or []))
            bad.append((a, b, paths))
            continue
        for s in (a, b):
            if s not in trees:
                trees[s] = _spec_tree(repo, by[s], batch["base"])
        if trees[a] is None or trees[b] is None:
            failed = True
            break
        r = _merge_trees(repo, batch["base"], trees[a], trees[b])
        if r is None:
            failed = True
            break
        if r[1]:
            clean += 1
        else:
            bad.append((a, b, r[2]))
    if failed:
        out.append("Parallel-buildable pairs: unavailable (git merge-tree failed)")
        missing.append("parallel_pairs")
    else:
        pct = f" ({100 * clean / len(usable):.0f}%)" if usable else ""
        out.append(f"Parallel-buildable pairs: {clean} of {len(usable)}{pct}")
        for a, b, paths in bad:
            out.append(f"- {a} <-> {b}: {', '.join(paths)}")
    for a, b in cpairs:
        if (a, b) not in usable:
            reason = f"{a} <-> {b} (no usable stale_base, base or head)"
            if reason not in excluded:
                excluded.append(reason)
    out.append("")

    # limits
    first = starts[0] if starts else None
    last = runs[-1] if runs else None
    out.append(_limits_line("Limits at start", (first or {}).get("limits")))
    out.append(_limits_line("Limits at end", ((last or {}).get("limits") or {}).get("record")))
    out.append("")
    out.append("Excluded: " + ("; ".join(excluded) if excluded else "none"))
    out.append(f"Malformed log lines: {malformed}")
    out.append("Missing: " + (", ".join(missing) if missing else "none"))
    span_lo = _epoch(batch["at"])
    span_hi = max([_epoch(r["ended_at"]) for r in runs if r.get("ended_at")] + [span_lo])
    errs = []
    for d in lines:
        if d.get("kind") == "error" and d.get("at"):
            try:
                if span_lo <= _epoch(d["at"]) <= span_hi:
                    errs.append(f"{d.get('sub')}: {d.get('reason')}")
            except ValueError:
                pass
    out.append("Failed commands: " + ("; ".join(errs) if errs else "none"))

    me = sys.modules[__name__]
    base_cfg = _baseline(repo, batch.get("configs") or [""]) if batch.get("configs") else None
    for c in batch.get("configs") or []:
        fn = getattr(me, "compare_text", None)
        if c != base_cfg and fn:
            out += ["", fn(repo, c)]
    fn = getattr(me, "status_line", None)
    if fn and (repo / METRICS_DIR / "roadmap").exists():
        out += ["", fn(repo)]
    return "\n".join(out) + "\n"


def cmd_report(repo, args):
    sys.stdout.write(report_text(repo, args.batch, args.usage_db))


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="metrics", parents=[common])
    sp = ap.add_subparsers(dest="sub")
    b = sp.add_parser("batch", parents=[common]).add_subparsers(dest="bsub")
    bs = b.add_parser("start", parents=[common])
    bs.add_argument("--config", action="append", required=True)
    bs.add_argument("--group", action="append", default=[])
    bs.add_argument("specs", nargs="+")
    st = sp.add_parser("start", parents=[common])
    st.add_argument("spec")
    st.add_argument("--batch", required=True)
    df = sp.add_parser("defect", parents=[common])
    df.add_argument("spec")
    df.add_argument("what")
    rc = sp.add_parser("record", parents=[common])
    rc.add_argument("spec")
    rc.add_argument("--batch", required=True)
    rc.add_argument("--outcome")
    rc.add_argument("--branch")
    rc.add_argument("--project")
    rc.add_argument("--usage-db")
    rc.add_argument("--no-ingest", action="store_true")
    rp = sp.add_parser("report", parents=[common])
    rp.add_argument("batch")
    rp.add_argument("--usage-db")
    for name in ("compare", "backfill", "gate", "status"):
        sp.add_parser(name, parents=[common], add_help=False).add_argument("rest", nargs="*")
    return ap


class _ArgError(Exception):
    pass


def _log_error(repo, sub, exc):
    """Append a kind:error line when the repo resolved (a failing repo lookup has nowhere to write)."""
    if repo is None:
        return
    try:
        append(repo, {"kind": "error", "sub": sub, "reason": clean_reason(exc, repo), "at": utc()})
    except Exception:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = "metrics"
    repo = None
    try:
        ap = _parser()
        ap.error = lambda msg: (_ for _ in ()).throw(_ArgError(msg))
        for a in ap._subparsers._group_actions[0].choices.values():
            a.error = ap.error
        try:
            args = ap.parse_args(argv)
        except _ArgError as e:
            first = next((a for a in argv if not a.startswith("-") and a in [s.split()[0] for s in SUBS]), "metrics")
            sub = first
            raise MetricsError(str(e).splitlines()[0])
        sub = args.sub or "metrics"
        if args.sub == "batch":
            sub = "batch start"
            if args.bsub != "start":
                raise MetricsError("usage: metrics batch start --config C [--group a,b] <spec>...")
        if not args.sub:
            raise MetricsError("usage: metrics <" + "|".join(SUBS) + "> ...")
        if args.sub in ("compare", "backfill", "gate", "status"):
            raise MetricsError("not implemented")
        repo = None
        repo = repo_root(getattr(args, "repo", None))
        {"batch": cmd_batch_start, "start": cmd_start, "defect": cmd_defect, "record": cmd_record, "report": cmd_report}[args.sub](repo, args)
        return 0
    except Exception as e:  # MetricsError or anything else: one line, never a traceback
        print(f"metrics: {sub}: {e}", file=sys.stderr)
        _log_error(repo, sub, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
