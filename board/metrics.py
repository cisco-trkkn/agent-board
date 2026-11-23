#!/usr/bin/env python3
"""metrics: the queue run log (docs/superpowers/metrics/runs.jsonl) and its commands.

Run log: one JSON object per line, kind in batch|start|run|defect|error|dream|analytics|discover|scout|analysis (readers ignore unknown
kinds). Append-only; readers take the last `run` per (batch, spec); a malformed line is skipped and counted.
Nothing private goes in a line: no session ids, prompts, agent names, absolute paths.

Task log (docs/superpowers/metrics/tasks.jsonl, same rules): one line per plan task, written by `record` and by
`backfill-tasks`; readers take the last line per (batch, spec, task_id).

CLI: metrics.py [--repo DIR] <batch start|start|record|defect|append|has|runs|report|compare|backfill|backfill-tasks|analyze|recommend|weekly|gate|status> ...
A failing command prints one line `metrics: <sub>: <reason>` to stderr and exits 1. `tmux-ctl metrics` calls this.
"""
import argparse
import calendar
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import metrics_lead  # noqa: E402
import metrics_tasks  # noqa: E402
import tc_env  # noqa: E402
import usage  # noqa: E402

METRICS_DIR = Path("docs/superpowers/metrics")
SUBS = ("batch start", "start", "record", "defect", "report", "compare", "backfill", "backfill-tasks", "analyze", "recommend", "weekly", "gate", "status", "append", "has", "runs")
STAGE1_KINDS = ("batch", "start", "run", "defect")   # written by their own commands, never by `append`


class MetricsError(Exception):
    pass


class UsageError(MetricsError):
    """A bad argument value: exit 2."""
    code = 2


def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise MetricsError((p.stderr.strip().splitlines() or ["git failed"])[-1])
    return p.stdout.strip()


def repo_root(repo_arg=None):
    return Path(_git(repo_arg or ".", "rev-parse", "--show-toplevel"))


LOG_OVERRIDE = None   # `backfill --log PATH` (tests, dry runs): read and write this file instead of the repo's run log


TASKS_OVERRIDE = None   # `backfill-tasks --log PATH`: read and write this file instead of the repo's tasks.jsonl


def mdir(repo):
    """The metrics directory of the MAIN checkout: every worktree of the repo shares its run log, configs, gates and roadmap."""
    return Path(main_root(repo)) / METRICS_DIR


def log_path(repo):
    return Path(LOG_OVERRIDE) if LOG_OVERRIDE else mdir(repo) / "runs.jsonl"


def tasks_path(repo):
    return Path(TASKS_OVERRIDE) if TASKS_OVERRIDE else mdir(repo) / "tasks.jsonl"


def _read_jsonl(p):
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


def read_log(repo):
    """(lines, malformed_count): every parsed JSON object (unknown kinds kept), bad lines counted."""
    return _read_jsonl(log_path(repo))


def read_tasks(repo):
    """(lines, malformed_count) of tasks.jsonl, like read_log."""
    return _read_jsonl(tasks_path(repo))


def _append_to(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p) + ".lock", "a") as lk:   # one writer at a time: a long line is not atomic under O_APPEND alone
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(p, "a") as f:
                f.write(json.dumps(obj, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def append(repo, obj):
    _append_to(log_path(repo), obj)


def append_task(repo, obj):
    _append_to(tasks_path(repo), obj)


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
    p = mdir(repo) / sub / (name + ".md")
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


REASON_BACKFILL = "backfilled run: no tap reading exists for a past window"
REASON_RECORD = "no statusline tap with rate_limits at record time"
REASON_START = "no statusline tap with rate_limits at start"
LEAD_FIELDS = ("lead_context_peak", "lead_handoffs", "post_handoff_tokens", "rereads")


def cmd_start(repo, args):
    wt = rel_worktree(repo, args.worktree) if args.worktree else None
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
        rec["missing_reason"] = {"limits": REASON_START}
    if wt:
        rec["worktree"] = wt
    append(repo, rec)


def cmd_defect(repo, args):
    append(repo, {"kind": "defect", "spec": args.spec, "what": args.what, "date": time.strftime("%Y-%m-%d", time.gmtime())})


# ---- record: the git- and file-derived half of a run line -------------------------------------------------------

EXCLUDED = "docs/superpowers/"
OUTCOMES = ("merged", "mr", "kept", "failed")
RESERVED = ("lock_wait_s", "lock_wait_cause", "repair_runs", "integration_s", "integration_tokens")
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


def _worktree_branch(start):
    """The branch name a run's worktree stands for: the basename of the `start` record's worktree path."""
    wt = (start or {}).get("worktree")
    return Path(wt).name if wt else None


def _fast_forward_range(repo, plan_path, plan_commit, start):
    """(head, base, True) of a run that was fast-forwarded onto main, else None. Such a run leaves no merge commit and
    no branch, so the range comes from what remains on main: head is the last commit that touched the plan's ledger
    directory (the ledger is the last thing a run commits), base is the main tip the run started from when the plan
    already existed then, else the parent of the plan's first commit."""
    ldir = "docs/superpowers/ledgers/" + Path(plan_path).name[:-3]
    rc, out = _git_try(repo, "log", "-1", "--format=%H", "main", "--", ldir)
    head = out.strip() if rc == 0 else ""
    if not head or _git_try(repo, "merge-base", "--is-ancestor", plan_commit, head)[0] != 0:
        return None
    rc, fp = _git_try(repo, "rev-list", "--first-parent", "main")   # a fast-forwarded run sits on main's own line; a merged branch does not
    if rc != 0 or not {plan_commit, head} <= set(fp.split()):
        return None
    smain = (start or {}).get("main")
    if smain and _git_try(repo, "merge-base", "--is-ancestor", plan_commit, smain)[0] == 0 \
            and _git_try(repo, "merge-base", "--is-ancestor", smain, head)[0] == 0:
        return head, smain, True
    rc, par = _git_try(repo, "rev-parse", "--verify", "-q", plan_commit + "^")
    return (head, par.strip(), True) if rc == 0 and par.strip() else None


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


def _registry_facts_cmd():
    env = os.environ.get("TC_REGISTRY_FACTS_CMD")
    if env:
        return shlex.split(env)
    return ["zsh", str(Path(__file__).resolve().parent.parent / "bin/tmux-ctl"), "registry"]


def _registry_facts(repo, spec, base, head):
    """(facts dict | None, error line | None). None with no error: the plan has no manifest (facts exit 3)."""
    try:
        p = subprocess.run([*_registry_facts_cmd(), "facts", spec, "--base", base, "--head", head], cwd=str(repo),
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e).splitlines()[0] if str(e) else type(e).__name__
    if p.returncode == 3:
        return None, None
    if p.returncode != 0:
        return None, ((p.stderr or p.stdout).strip().splitlines() or [f"exit {p.returncode}"])[0]
    try:
        facts = json.loads(p.stdout.strip().splitlines()[-1])
        if not isinstance(facts, dict):
            raise ValueError
    except (ValueError, IndexError):
        return None, "unreadable output"
    return facts, None


def build_record_static(repo, spec, batch, outcome, now, branch=None, plan=None, merge=None, batch_base=None):
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

    plan = plan or find_plan(repo, spec)
    plan_path = plan_ref = None
    if plan:
        plan_path, _, plan_ref = plan
    rec["plan"] = plan_path
    if not plan:
        missing.append("plan")
    plan_commit, plan_ts = _first_commit(repo, plan_path) if plan else (None, None)

    if merge is None and plan_commit:
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
    ff = False
    if not merge and not head and plan_commit:
        ffr = _fast_forward_range(repo, plan_path, plan_commit, start)
        if ffr:
            head, base, ff = ffr
            branch = branch or _worktree_branch(start)
    rec["branch"], rec["head"], rec["base"] = branch, head, base
    for k in ("branch", "head", "base"):
        if rec[k] is None:
            missing.append(k)
    rec["ended_at"] = utc(merge["ct"]) if merge else utc(now)

    word = (outcome or "").split()[0].lower() if (outcome or "").strip() else None
    if word is None:
        rec["outcome"] = "merged" if rec["merge"] or ff else "kept"
    else:
        rec["outcome"] = word
        if word not in OUTCOMES:
            missing.append("outcome")
    if rec["merge"] is None and not ff and rec["outcome"] in ("merged", "mr"):
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
    facts = None
    if plan and base and head and _fence(plan[1], "json:manifest"):
        facts, ferr = _registry_facts(repo, spec, base, head)
        if ferr:
            print(f"metrics: record: registry facts failed: {ferr}", file=sys.stderr)
            missing.append("manifest_facts")
    if facts:
        both, nt = facts.get("both"), facts.get("touched")
        r4 = lambda v: round(v, 4) if isinstance(v, (int, float)) else None
        rec["manifest"] = {"declared": facts.get("declared"), "touched": nt, "both": both,
                           "precision": r4(facts.get("precision")),
                           "recall": round(both / nt, 4) if nt and both is not None else None,
                           "recall_existing": r4(facts.get("recall_existing")), "recall_created": r4(facts.get("recall_created")),
                           "append_violations": facts.get("append_violations") or [], "source": "manifest"}
        rec["refreshes"], rec["stale_paths"] = facts.get("refreshes", 0), facts.get("stale_paths", 0)
    elif info and touched is not None:
        both = len(info["declared"] & touched)
        rec["manifest"] = {"declared": len(info["declared"]), "touched": len(touched), "both": both,
                           "precision": round(both / len(info["declared"]), 4) if info["declared"] else None,
                           "recall": round(both / len(touched), 4) if touched else None, "source": "tasks"}
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

    bb = batch_base or (batch_line or {}).get("base")
    sb = stale_base(repo, base, bb, head) if base and head and bb else None
    rec["stale_base"] = sb
    if sb is None:
        missing.append("stale_base")
    for k in RESERVED:
        rec[k] = None
    rec["manifest_tokens"] = None   # build_record fills it from the usage index
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

    Branch and worktree rows weigh 1. A row (lead or agent) with cwd == the repo root weighs 1/k, k = this spec plus the other
    specs whose window contains the row."""
    lo, hi = window
    out = []
    for r in usage._rows(conn, "select * from calls where ts>=? and ts<=?", (lo, hi)):
        cwd = r["cwd"] or ""
        by_branch = branch is not None and r["git_branch"] == branch
        by_dir = any(cwd == d or cwd.startswith(d + "/") for d in wt_dirs)
        if by_branch or by_dir:
            out.append((r, 1.0))
        elif cwd == root:   # any role: named agents working in the main checkout belong to the window too
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


def _lead_part(lines, batch, spec, root, project, lo, hi, missing):
    """The four lead fields; any failure gives null/0/[]/[] with every name in `missing` and one stderr line."""
    try:
        ends = []
        for (b, sp), run in last_runs(lines).items():
            if b == batch and sp != spec and run.get("ended_at"):
                try:
                    e = _epoch(run["ended_at"])
                except ValueError:
                    continue
                if e < lo:
                    ends.append(e)
        prev_end = max(ends) if ends else None
        got = metrics_lead.lead_fields(usage.root() / slug_of(root), tc_env.lineage_dir() / f"{project or Path(root).name}.jsonl",
                                       lo, hi, prev_end)
        out = {k: got[k] for k in LEAD_FIELDS}
        names = list(got.get("missing") or [])
    except Exception as e:
        print(f"metrics: record: lead fields skipped: {type(e).__name__}", file=sys.stderr)
        out = {"lead_context_peak": None, "lead_handoffs": 0, "post_handoff_tokens": [], "rereads": []}
        names = list(LEAD_FIELDS)
    missing.extend(k for k in names if k not in missing)
    return out


def _spec_slug(spec):
    name = Path(spec.split("#")[0]).name
    name = name[:-3] if name.endswith(".md") else name
    name = re.sub(r"^\d{4}-\d\d-\d\d-", "", name)
    return name[:-len("-design")] if name.endswith("-design") else name


def manifest_tokens(conn, spec, batch, batch_line, lo, hi):
    """Tokens of the `refresh-<slug>` rows in the run window plus this spec's share of the `crossplan-<batch>` rows
    (batch line `at` to the run's end); None without a batch line."""
    if not batch_line:
        return None
    cols = "+".join(f"coalesce({c},0)" for c in LEAD_KEYS)
    q = f"select coalesce(sum({cols}),0) from calls where agent_name=? and ts>=? and ts<=?"
    refresh = conn.execute(q, ("refresh-" + _spec_slug(spec), lo, hi)).fetchone()[0]
    cross = conn.execute(q, ("crossplan-" + batch, _epoch(batch_line["at"]), hi)).fetchone()[0]
    n = len(batch_line.get("assignment") or batch_line.get("specs") or [])
    return refresh + (cross / n if n else 0)


def build_record(repo, spec, batch, outcome, now, branch=None, conn=None, project=None, window=None, plan=None, merge=None,
                 batch_base=None, backfilled=False):
    """The whole `run` line: build_record_static plus the usage half. `window` = (start_ts, end_ts, kind) overrides
    the stamped window (backfill)."""
    repo = Path(repo)
    lines, _ = read_log(repo)
    batch_line = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == batch), None)
    start = next((d for d in reversed(lines) if d.get("kind") == "start" and d.get("batch") == batch and d.get("spec") == spec), None)
    rec = build_record_static(repo, spec, batch, outcome, now, branch=branch, plan=plan, merge=merge, batch_base=batch_base)
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
    rec["window"], rec["backfilled"] = kind, bool(backfilled)
    rec["manifest_tokens"] = manifest_tokens(conn, spec, batch, batch_line, lo, hi)
    if rec["manifest_tokens"] is None:
        missing.append("manifest_tokens")
    assign_cfg = (batch_line or {}).get("assignment") or {}
    rec["config"] = "seq-sdd" if batch == "backfill" else assign_cfg.get(spec)
    if rec["config"] is None and batch != "backfill":
        # a spec that joined the batch late is not in its assignment
        cfgs = (batch_line or {}).get("configs") or []
        if len(cfgs) == 1:
            rec["config"] = cfgs[0]
        else:
            missing.append("config")
    root = main_root(repo)
    others = _other_windows(lines, batch, spec, now) if start and kind == "stamped" else []
    wt = worktree_dirs(repo, root, rec["branch"], conn)
    if start and start.get("worktree"):
        wt = set(wt) | {os.path.join(root, start["worktree"])}   # rows of a worktree removed before record still count
    weighted = attributed_rows(conn, root, rec["branch"], wt, (lo, hi), others)
    rec.update(budget(weighted, usage.load_prices()))
    rec.update(time_fields((batch_line or {}).get("at"), lo, hi, weighted))
    if backfilled:
        # today's tap reading says nothing about a run that ended days ago; ready_at/wait_s have no batch line either
        rec["limits"] = {"start": None, "record": None}
        missing.extend(k for k in ("limits", "ready_at", "wait_s") if k not in missing)
        rec["missing_reason"] = {"limits": REASON_BACKFILL}
    else:
        pl = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
        rec["limits"] = {"start": (start or {}).get("limits"),
                         "record": {"five_hour": pl.get("five_hour"), "seven_day": pl.get("seven_day")} if pl else None}
        if not pl:
            missing.append("limits")
            rec["missing_reason"] = {"limits": REASON_RECORD}
    rec.update(_lead_part(lines, batch, spec, root, project, lo, hi, missing))
    rec["questions"] = count_questions(root, (lo, hi))
    if rec["questions"] is None:
        missing.append("questions")
    rec["handoffs"] = count_handoffs(project or Path(root).name, (lo, hi))
    return rec


def _commit_time(repo):
    """sha -> committer time (epoch int) or None for an unknown sha; one git call per sha."""
    seen = {}

    def ct(sha):
        if sha not in seen:
            rc, out = _git_try(repo, "show", "-s", "--format=%ct", sha)
            seen[sha] = int(out.strip()) if rc == 0 and out.strip().isdigit() else None
        return seen[sha]
    return ct


def task_lines_for_run(repo, run, conn):
    """The task lines of one `run` line, from its plan's .tasks.json, its ledger and the agent rows in its window that
    belong to the spec (cwd under the spec's worktrees or the main root). No plan: no lines. Raises MetricsError when the
    plan has no .tasks.json or the run has no window. A live ledger (.superpowers/sdd/<plan>/progress.md in the spec's worktree) wins over the archived one;
    with neither, the lines carry no ledger facts."""
    repo = Path(repo)
    spec, batch = run["spec"], run["batch"]
    plan = find_plan(repo, spec)
    if not plan:
        return []   # the run line already names the plan in `missing`
    plan_path, plan_text, plan_ref = plan
    tasks_text = _read(repo, plan_ref, plan_path + ".tasks.json")
    if tasks_text is None:
        raise MetricsError("plan has no .tasks.json")
    if not run.get("started_at") or not run.get("ended_at"):
        raise MetricsError("run has no window")
    lo, hi = _epoch(run["started_at"]), _epoch(run["ended_at"])
    base = Path(plan_path).name[:-3]
    root = main_root(repo)
    wt = worktree_dirs(repo, root, run.get("branch"), conn)
    progress = None
    for d in sorted(wt):
        f = Path(d) / ".superpowers/sdd" / base / "progress.md"
        if f.is_file():
            progress = f.read_text()
            break
    if progress is None:
        progress = _read(repo, plan_ref, f"docs/superpowers/ledgers/{base}/progress.md")
    try:
        routing = json.loads((Path(root) / "docs/superpowers/model-routing.json").read_text())
    except (OSError, ValueError):
        routing = {}
    # worker rows carry git_branch 'main' as often as the queue branch, and the worktree is gone by `record` time:
    # select by cwd (main root or any worktree under it); build_task_lines keeps only the ledger's owners/reviewers
    wt_root = root + "/.claude/worktrees/"
    rows = [r for r in usage._rows(conn, "select * from calls where ts>=? and ts<=? and agent_name is not null", (lo, hi))
            if (r["cwd"] or "") == root or (r["cwd"] or "").startswith(wt_root)
            or any((r["cwd"] or "") == d or (r["cwd"] or "").startswith(d + "/") for d in wt)]
    return metrics_tasks.build_task_lines(spec, batch, tasks_text, progress or "", routing, rows, _commit_time(repo), hi,
                                          plan_text=plan_text)


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
        append(repo, rec)
        try:   # the task half never fails the run record
            for t in task_lines_for_run(repo, rec, conn):
                append_task(repo, t)
        except Exception as e:
            print(f"metrics: record: task lines skipped: {clean_reason(e, repo)}", file=sys.stderr)
    finally:
        conn.close()
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


REREADS_SCOPE = ("Re-reads count files read with Read, cat, sed, head, tail or grep in the new lead's first 10 turns "
                 "that the previous lead also read; Grep and Glob calls are not counted.")


def _lead_lines(runs):
    """One line per run record with the key lead_context_peak. Sources, all fields of that record: lead_context_peak
    (peak, divided by 1000, rounded down), lead_handoffs (handoffs), rereads (sum of the non-null entries)."""
    out, scoped = [], False
    for r in runs:
        if "lead_context_peak" not in r:
            continue
        peak = r.get("lead_context_peak")
        n = r.get("lead_handoffs")
        shown = f"{int(peak) // 1000}K" if isinstance(peak, (int, float)) and not isinstance(peak, bool) else "-"
        line = f"{r['spec']}: Lead: peak {shown} tokens"
        line += f", {_cell(n)} handoffs"
        nums = [x for x in (r.get("rereads") or []) if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if isinstance(n, (int, float)) and n > 0 and nums:
            line += f", {sum(nums)} re-reads after handoff"
            scoped = True
        out.append(line)
    if scoped:
        out.append(REREADS_SCOPE)
    return out


def _limits_missing_lines(runs, starts):
    out = []
    for r in runs:
        why = (r.get("missing_reason") or {}).get("limits")
        if why:
            out.append(f"Limits missing: {r['spec']}: {why}")
    for d in starts:
        why = (d.get("missing_reason") or {}).get("limits")
        if why:
            out.append(f"Limits missing: start {d.get('spec')}: {why}")
    return out


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


def _pair_usable(r):
    """A run line can take part in a pair: a stale_base conflict, or a clean result with base and head."""
    res = (r.get("stale_base") or {}).get("result")
    return res == "conflict" or (res == "clean" and bool(r.get("base")) and bool(r.get("head")))


def pair_results(repo, batch, runs):
    """[(a, b, clean, paths)] for every usable pair, or None when git merge-tree failed. Pair order and the usable
    rule are those of the report's parallel-buildable pairs: stale_base conflict or (clean with base and head)."""
    by = {r["spec"]: r for r in runs}
    cand = sorted(by)

    usable = [(a, b) for i, a in enumerate(cand) for b in cand[i + 1:] if _pair_usable(by[a]) and _pair_usable(by[b])]
    out, trees = [], {}
    if usable and not batch.get("base"):
        raise MetricsError("batch line has no base")
    for a, b in usable:
        sa, sb = by[a]["stale_base"], by[b]["stale_base"]
        if sa["result"] == "conflict" or sb["result"] == "conflict":
            out.append((a, b, False, sorted(set(sa.get("paths") or []) | set(sb.get("paths") or []))))
            continue
        for s in (a, b):
            if s not in trees:
                trees[s] = _spec_tree(repo, by[s], batch["base"])
        if trees[a] is None or trees[b] is None:
            return None
        r = _merge_trees(repo, batch["base"], trees[a], trees[b])
        if r is None:
            return None
        out.append((a, b, True, []) if r[1] else (a, b, False, r[2]))
    return out


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
    if overlap and not usage_db and Path(usage.db_path()).exists():
        usage_db = usage.db_path()
    active = None
    if overlap and usage_db:
        active = _union_active(repo, runs, usage_db)
        if active == 0:   # the index exists but holds nothing for these windows: a 0 would read as "no activity"
            active = None
            note = " (sum, index lacks the window)"
    if active is None or not (overlap and usage_db):
        active = sum(r.get("active_min") or 0 for r in runs)
        if not note:
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
    usable = [(a, b) for a, b in cpairs if _pair_usable(by[a]) and _pair_usable(by[b])]
    res = pair_results(repo, batch, runs)
    failed = res is None
    clean = sum(1 for r in res if r[2]) if res else 0
    bad = [(a, b, paths) for a, b, c, paths in res if not c] if res else []
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
    last = max(runs, key=lambda r: r.get("at") or "") if runs else None
    out.append(_limits_line("Limits at start", (first or {}).get("limits")))
    out.append(_limits_line("Limits at end", ((last or {}).get("limits") or {}).get("record")))
    out += _lead_lines(runs)
    out += _limits_missing_lines(runs, starts)
    out.append("")
    out.append("Excluded: " + ("; ".join(excluded) if excluded else "none"))
    out.append(f"Malformed log lines: {malformed}")
    out.append("Missing: " + (", ".join(missing) if missing else "none"))
    span_lo = _epoch(batch["at"])
    # a failed record writes no run line, so the span runs to the next batch line (or now), not to the last run
    later = [_epoch(d["at"]) for d in lines if d.get("kind") == "batch" and d.get("at") and _epoch(d["at"]) > span_lo]
    span_hi = min(later) if later else time.time()
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
            try:
                out += ["", fn(repo, c)]
            except MetricsError as e:
                out += ["", f"compare {c}: {e}"]
    fn = getattr(me, "status_line", None)
    if fn and (mdir(repo) / "roadmap").exists():
        try:
            line = fn(repo)
        except MetricsError as e:
            line = f"status: {e}"
        if line:
            out += ["", line]
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
    ap_ = sp.add_parser("append", parents=[common])
    ap_.add_argument("kind")
    ap_.add_argument("--json", required=True)
    ap_.add_argument("--batch")
    ap_.add_argument("--log")
    hs = sp.add_parser("has", parents=[common])
    hs.add_argument("kind")
    hs.add_argument("--spec")
    hs.add_argument("--batch")
    hs.add_argument("--log")
    rn = sp.add_parser("runs", parents=[common])
    rn.add_argument("batch")
    rn.add_argument("--json", action="store_true")
    rn.add_argument("--log")
    st = sp.add_parser("start", parents=[common])
    st.add_argument("spec")
    st.add_argument("--batch", required=True)
    st.add_argument("--worktree")
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
    cp = sp.add_parser("compare", parents=[common])
    cp.add_argument("config")
    gp = sp.add_parser("gate", parents=[common])
    gp.add_argument("id")
    gp.add_argument("--log")
    sp.add_parser("status", parents=[common])
    bt = sp.add_parser("backfill-tasks", parents=[common])
    bt.add_argument("--log", dest="tasks_log")
    bt.add_argument("--usage-db")
    bt.add_argument("--no-ingest", action="store_true")
    an = sp.add_parser("analyze", parents=[common])
    an.add_argument("--since", default="7d")
    an.add_argument("--json", action="store_true")
    an.add_argument("--out")
    an.add_argument("--projects", nargs="+")
    an.add_argument("--tasks-log")
    rm = sp.add_parser("recommend", parents=[common])
    rm.add_argument("--since", default="7d")
    rm.add_argument("--stats")
    wk = sp.add_parser("weekly", parents=[common])
    wk.add_argument("--dry-run", action="store_true")
    wk.add_argument("--json", action="store_true")
    wk.add_argument("--force", action="store_true")   # re-post a week already posted to a destination
    wk.add_argument("--since", default="7d")
    wk.add_argument("--tasks-log")
    bf = sp.add_parser("backfill", parents=[common])
    bf.add_argument("--since")
    bf.add_argument("--until")
    bf.add_argument("--log")
    bf.add_argument("--project")
    bf.add_argument("--usage-db")
    bf.add_argument("--no-ingest", action="store_true")
    return ap


class _ArgError(Exception):
    pass


# ---- compare, gates, status --------------------------------------------------------------------------------------

import itertools
import math
import random
import statistics

LIMIT_SENTENCE = ("With this spread, a 2x effect shows after about 4 specs per configuration, 1.5x after about 9, and 20% needs "
                  "about 30; differences under about 1.5x are not decidable this way.")
PER_SPEC = ("tokens_per_task", "active_min_per_task")
EXACT_MAX = 200000
SAMPLES = 20000


def permutation_p(ch, base, direction):
    """One-sided permutation test on log values: statistic = mean(log ch) - mean(log base); p = share of splits with a
    statistic <= observed (direction "max": lower is better) or >= observed ("min"). Exact enumeration when
    comb(n+m, m) <= 200000, else 20,000 random splits from random.Random(0). Returns (p, "exact"|"sampled")."""
    lg = [math.log(v) for v in list(ch) + list(base)]
    m, n = len(ch), len(base)
    total = sum(lg)
    obs = sum(lg[:m]) / m - sum(lg[m:]) / n

    def stat(idx):
        s = sum(lg[i] for i in idx)
        return s / m - (total - s) / n

    def hit(v):
        return v <= obs + 1e-12 if direction == "max" else v >= obs - 1e-12

    if math.comb(m + n, m) <= EXACT_MAX:
        hits = splits = 0
        for idx in itertools.combinations(range(m + n), m):
            splits += 1
            hits += hit(stat(idx))
        return hits / splits, "exact"
    rng = random.Random(0)
    hits = sum(hit(stat(rng.sample(range(m + n), m))) for _ in range(SAMPLES))
    return hits / SAMPLES, "sampled"


def _norm(r, key):
    tasks, tot, act = r.get("tasks"), (r.get("tokens") or {}).get("total"), r.get("active_min")
    if not tasks or not tot or not act:
        return None
    return tot / tasks if key == "tokens_per_task" else act / tasks


def _exclusion(r):
    if r.get("outcome") in ("failed", "kept"):
        return f"outcome {r['outcome']}"
    if _norm(r, "tokens_per_task") is None:
        return "tokens, active_min or tasks missing or zero"
    return None


def _day(iso):
    return calendar.timegm(time.strptime(iso[:10], "%Y-%m-%d")) // 86400


def quality_veto(chal, base, defects):
    """(holds, lines). For failed specs, escaped defects (within 14 days of the spec's end) and fix waves: the
    challenger's count is above the baseline's rate times the challenger's spec count, plus one."""
    def counts(runs):
        failed = sum(1 for r in runs if r.get("outcome") == "failed")
        waves = sum(1 for r in runs if r.get("fix_wave"))
        esc = 0
        for r in runs:
            if not r.get("ended_at"):
                continue
            end = _day(r["ended_at"])
            esc += sum(1 for d in defects if d.get("spec") == r["spec"] and d.get("date")
                       and 0 <= _day(d["date"]) - end <= 14)
        return {"failed specs": failed, "escaped defects": esc, "fix waves": waves}
    c, b = counts(chal), counts(base)
    holds, lines = False, []
    for k in c:
        rate = b[k] / len(base) if base else 0.0
        limit = rate * len(chal) + 1
        over = c[k] > limit
        holds = holds or over
        lines.append(f"{k} {c[k]} (baseline rate {rate:.2f} x {len(chal)} + 1 = {limit:.2f}) {'over' if over else 'ok'}")
    return holds, lines


def _config_of(repo, cache, name):
    if name not in cache:
        cache[name] = load_config(repo, name) if name else None
    return cache[name]


def _throughput(runs):
    tasks = sum(r.get("tasks") or 0 for r in runs if r.get("outcome") in ("merged", "mr"))
    act = sum(r.get("active_min") or 0 for r in runs)
    return tasks / (act / 60) if act else None


def compare_data(repo, config):
    lines, _ = read_log(repo)
    conf = load_config(repo, config)
    if conf is None:
        raise MetricsError(f"unknown config {config}")
    cache = {}
    last = list(last_runs(lines).values())
    base = [r for r in last if (_config_of(repo, cache, r.get("config")) or {}).get("baseline") is True]
    chal = [r for r in last if r.get("config") == config]
    if not base:
        raise MetricsError("no baseline records")
    defects = [d for d in lines if d.get("kind") == "defect"]
    inc_c = [r for r in chal if _exclusion(r) is None]
    inc_b = [r for r in base if _exclusion(r) is None]
    veto, veto_lines = quality_veto(chal, base, defects)
    out = {"config": config, "conf": conf, "base": base, "chal": chal, "inc_c": inc_c, "inc_b": inc_b,
           "veto": veto, "veto_lines": veto_lines, "targets": []}
    for t in conf.get("targets") or []:
        m = t.get("metric")
        direction = "max" if "max" in t else "min"
        thr = t.get(direction)
        row = {"metric": m, "dir": direction, "thr": thr, "index": None, "met": False, "wrong": False, "p": None, "mode": None,
               "batch_met": None}
        if m in PER_SPEC:
            cv, bv = [_norm(r, m) for r in inc_c], [_norm(r, m) for r in inc_b]
            if cv and bv:
                row["index"] = statistics.median(cv) / statistics.median(bv)
                if thr is not None:
                    row["met"] = row["index"] <= thr if direction == "max" else row["index"] >= thr
                row["p"], row["mode"] = permutation_p(cv, bv, direction)
        elif m == "throughput":
            bt = _throughput(base)
            per_batch = {}
            for r in chal:
                per_batch.setdefault(r.get("batch"), []).append(r)
            ratios = {b: (_throughput(rs) / bt if bt and _throughput(rs) is not None else None) for b, rs in per_batch.items()}
            pooled = _throughput(chal)
            if bt and pooled is not None:
                row["index"] = pooled / bt
            row["batch_met"] = bool(ratios) and all(v is not None and (v <= thr if direction == "max" else v >= thr)
                                                    for v in ratios.values()) if thr is not None else bool(ratios)
            row["met"] = row["batch_met"]
        if row["index"] is not None:
            row["wrong"] = row["index"] > 1.0 if direction == "max" else row["index"] < 1.0
        out["targets"].append(row)
    n = len(chal)
    batches = len({r.get("batch") for r in chal})
    tg = out["targets"]
    wrong = any(t["wrong"] for t in tg)
    sig = all((t["p"] is not None and t["p"] < 0.10) for t in tg if t["metric"] in PER_SPEC)
    # rule 3 counts only the specs that enter the index: excluded (failed, kept, zero) ones do not count toward 8 and 2
    inc_batches = len({r.get("batch") for r in out["inc_c"]})
    replace = (len(out["inc_c"]) >= 8 and inc_batches >= 2 and bool(tg) and all(t["met"] for t in tg) and sig and not veto)
    if n < 4:
        verdict = "too early"
    elif n >= 8 and (wrong or veto):
        verdict = "kill or adjust"
    elif replace:
        verdict = "replace"
    elif n >= 16:
        verdict = "weak evidence"
    else:
        verdict = "continue"
    out.update({"verdict": verdict, "n": n, "batches": batches})
    return out


def compare_text(repo, config):
    d = compare_data(repo, config)
    cache = {}
    bases = sorted({r.get("config") for r in d["base"]})
    out = [f"compare {config} (baseline: {', '.join(str(b) for b in bases)})", f"Verdict: {d['verdict']}", LIMIT_SENTENCE, ""]
    out.append(f"Challenger specs: {d['n']} over {d['batches']} batches; {len(d['inc_c'])} in the index")
    out.append(f"Baseline specs: {len(d['base'])}; {len(d['inc_b'])} in the index")
    exc = [f"{r['spec']} ({_exclusion(r)})" for r in d["chal"] + d["base"] if _exclusion(r)]
    out.append(f"Excluded: {len(exc)}" + (" - " + "; ".join(exc) if exc else ""))
    for t in d["targets"]:
        idx = "-" if t["index"] is None else f"{t['index']:.3f}"
        side = "wrong side" if t["wrong"] else "right side"
        line = f"Target {t['metric']} ({t['dir']} {t['thr']}): index {idx}, {side}, {'met' if t['met'] else 'not met'}"
        if t["p"] is not None:
            line += f", p {t['p']:.4f} ({t['mode']})"
        if t["batch_met"] is not None:
            line += f", every challenger batch {'met' if t['batch_met'] else 'not met'}"
        out.append(line)
    out.append("Quality veto: " + ("holds" if d["veto"] else "does not hold"))
    out += ["  " + l for l in d["veto_lines"]]
    if d["verdict"] == "weak evidence":
        out.append("The evidence is weak: " + "; ".join(f"{t['metric']} index is on the {'wrong' if t['wrong'] else 'right'} side of 1.0"
                                                        for t in d["targets"]) + ". The user decides.")
    out.append("Per spec (tokens, tokens per task, tokens per declared file, active min per task):")
    for tag, rs in (("challenger", d["inc_c"]), ("baseline", d["inc_b"])):
        for r in rs:
            tot, df = r["tokens"]["total"], r.get("declared_files")
            per_file = f"{tot / df:.0f}" if df else "-"
            out.append(f"- {tag} {r['spec']}: {tot}, {_norm(r, 'tokens_per_task'):.0f}, {per_file}, {_norm(r, 'active_min_per_task'):.1f}")
    return "\n".join(out)


def cmd_compare(repo, args):
    print(compare_text(repo, args.config))


# ---- gates ----

def _dig(d, path):
    for k in path.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _fmt(v):
    return "-" if v is None else repr(round(v, 4)) if isinstance(v, float) else str(v)


def _where_ok(rec, where):
    for k, v in (where or {}).items():
        if k == "has":
            if _dig(rec, v) is None:
                return False
        elif _dig(rec, k) != v:
            return False
    return True


def _thr(c):
    parts = [f"{k} {c[k]}" for k in ("min", "max") if k in c]
    return "(" + ", ".join(parts) + ")"


def gate_eval(repo, gate_id):
    """(result, summary, lines): result is pass|fail|too early; summary is the conditions without verdicts."""
    gate = load_gate(repo, gate_id)
    if gate is None:
        raise MetricsError(f"no gate file {gate_id}")
    if "compare" in gate:
        v = compare_data(repo, gate["compare"])["verdict"]
        res = "pass" if v == "replace" else "fail" if v == "kill or adjust" else "too early"
        return res, f"compare {gate['compare']} {v}", [f"compare {gate['compare']}: {v}"]
    lines, _ = read_log(repo)
    runs = [r for r in last_runs(lines).values() if _where_ok(r, gate.get("where"))]
    analyses = [d for d in lines if d.get("kind") == "analysis"]
    verdicts, text, summ = [], [], []
    for c in gate.get("conditions") or []:
        m, agg = c["metric"], c.get("agg", "median")
        val, early, waves = None, False, None
        if agg == "last":
            last = analyses[-1] if analyses else None
            if last is None or not _where_ok(last, c.get("where")):
                early = True
            else:
                val = _dig(last, m)
                if val is None and m.startswith("analysis."):
                    val = _dig(last, m[len("analysis."):])   # the registry writes the analysis line flat
                early = val is None
                if m.startswith("analysis."):
                    waves = _dig(last, "analysis.waves.append")
                    if waves is None:
                        waves = _dig(last, "waves.append")
        elif agg == "ratio_of_sums" or "/" in m:
            num, _, den = m.partition("/")
            if agg == "ratio_of_sums":
                ns = [_dig(r, num) for r in runs]
                ds = [_dig(r, den) for r in runs]
                pairs = [(a, b) for a, b in zip(ns, ds) if a is not None and b is not None]
                val = sum(a for a, _ in pairs) / sum(b for _, b in pairs) if pairs and sum(b for _, b in pairs) else None
            else:
                vals = [(_dig(r, num) / _dig(r, den)) for r in runs if _dig(r, num) is not None and _dig(r, den)]
                val = statistics.median(vals) if vals else None
            early = val is None
        else:
            vals = [_dig(r, m) for r in runs if isinstance(_dig(r, m), (int, float))]
            val = statistics.median(vals) if vals else None
            early = val is None
        if early:
            res = "too early"
        else:
            ok = (("min" not in c or val >= c["min"]) and ("max" not in c or val <= c["max"]))
            res = "pass" if ok else "fail"
        verdicts.append(res)
        summ.append(f"{m} {_fmt(val)} {_thr(c)}")
        suffix = f" (append waves {waves})" if waves is not None and val is not None else ""
        text.append(f"{m} {_fmt(val)} {_thr(c)}{suffix} {res}")
    if len(runs) < int(gate.get("min_specs") or 0) or "too early" in verdicts:
        result = "too early"
    elif all(v == "pass" for v in verdicts):
        result = "pass"
    else:
        result = "fail"
    return result, ", ".join(summ), text


GATE_RC = {"pass": 0, "fail": 1, "too early": 3}


def cmd_gate(repo, args):
    def go():
        result, _, lines = gate_eval(repo, args.id)
        print(f"gate {args.id}: {result}")
        for l in lines:
            print(l)
        return GATE_RC[result]
    return _with_log(args, go)


# ---- status ----

def _cell_text(c):
    return re.sub(r"[`*]", "", c).strip()


def _status_rows(doc):
    m = re.search(r"^##\s+Status\s*$", doc, re.M)
    if not m:
        return []
    rows = []
    for l in doc[m.end():].splitlines():
        if l.startswith("## "):
            break
        if l.strip().startswith("|"):
            rows.append([_cell_text(c) for c in l.strip().strip("|").split("|")])
    if len(rows) < 2:
        return []
    head = [h.lower() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if all(re.fullmatch(r":?-+:?", c) for c in r if c):
            continue
        out.append({h: (r[i] if i < len(r) else "") for i, h in enumerate(head)})
    return out


def status_line(repo):
    ro = mdir(repo) / "roadmap"
    if not ro.exists():
        return ""
    first = next((l.strip() for l in ro.read_text().splitlines() if l.strip()), "")
    label, _, path = first.partition(" ")
    path = path.strip()
    if not label or not path:
        raise MetricsError("roadmap needs `<label> <path>`")
    doc = Path(repo) / path
    if not doc.is_file():
        raise MetricsError(f"cannot read {path}")
    rows = _status_rows(doc.read_text())
    if not rows:
        raise MetricsError(f"no Status table in {path}")
    idx = next((i for i, r in enumerate(rows) if r.get("state", "").lower() != "passed"), None)
    if idx is None:
        return f"{label}: all stages passed"
    row = rows[idx]
    head = f"{label}: stage {row.get('stage', '?')} {row.get('state', '')}".rstrip()
    gate = next((r.get("gate", "") for r in rows[idx:] if r.get("gate", "").lower() not in ("", "-", "—", "none", "n/a")), None)
    if gate is None:
        return head + ", no gate"
    if load_gate(repo, gate) is None:
        return f"{head}, next gate {gate}: no gate file"
    result, summary, _ = gate_eval(repo, gate)
    return f"{head}, next gate {gate}: {summary} {result}"


def cmd_status(repo, args):
    line = status_line(repo)
    if line:
        print(line)


# ---- backfill ----------------------------------------------------------------------------------------------------

SPEC_LINE = re.compile(r"\*\*Spec:\*\*\s*`?([^\s`]+\.md(?:#part-\d+)?)`?")


def _plan_for_merge(repo, m):
    """The plan .md of a merge: one a branch commit added, else (plan already on main) one whose basename without its
    date prefix the merge's branch name ends with. None when neither."""
    rc, out = _git_try(repo, "log", "--diff-filter=A", "--name-only", "--format=", f"{m['first']}..{m['second']}",
                       "--", "docs/superpowers/plans/")
    added = sorted({l for l in out.splitlines() if l.endswith(".md")}) if rc == 0 else []
    if added:
        return added[0]
    mt = re.match(r"Merge branch '([^']+)'", m["subject"])
    if not mt:
        return None
    rc, names = _git_try(repo, "ls-tree", "--name-only", m["first"], "docs/superpowers/plans/")
    for n in sorted(names.split()) if rc == 0 else []:
        slug = re.sub(r"^\d{4}-\d\d-\d\d-", "", Path(n).name[:-3]) if n.endswith(".md") else None
        if slug and mt.group(1).endswith(slug):
            return n
    return None


def _spec_of_plan(repo, m, plan_path):
    """The plan's `**Spec:**` path; the plan path itself when the plan names none."""
    for ref in (m["second"], m["first"]):
        rc, text = _git_try(repo, "show", f"{ref}:{plan_path}")
        if rc == 0:
            for line in text.splitlines()[:40]:
                hit = SPEC_LINE.search(line)
                if hit:
                    return hit.group(1)
            break
    return plan_path


def _parse_when(text, end=False):
    if re.fullmatch(r"\d{4}-\d\d-\d\d", text):
        return _epoch(text + "T00:00:00Z") + (86400 if end else 0)
    return _epoch(text)


def backfill_runs(repo, since, until, conn, project=None, now=None):
    """Run lines for every first-parent merge on main in [since, until] whose branch has a plan, with derived windows:
    from the later of the previous such merge and the last merge of any kind before the plan's first commit (the first: the
    plan's first commit) to the merge. A spec that already has a run line
    in any batch is skipped (it still anchors the next window)."""
    repo = Path(repo)
    now = now or time.time()
    have = {d.get("spec") for d in read_log(repo)[0] if d.get("kind") == "run"}
    rc, out = _git_try(repo, "log", "--first-parent", "--merges", "--reverse", "main", "--format=%H%x09%P%x09%ct%x09%s")
    merges, all_cts = [], []
    for line in out.splitlines() if rc == 0 else []:
        sha, parents, ct, subject = (line.split("\t", 3) + [""])[:4]
        ps = parents.split()
        if len(ps) >= 2:
            all_cts.append(int(ct))
        if len(ps) >= 2 and since <= int(ct) <= (until if until is not None else float("inf")):
            merges.append({"sha": sha, "first": ps[0], "second": ps[1], "ct": int(ct), "subject": subject})
    written, prev_ct = [], None
    for m in merges:
        plan_path = _plan_for_merge(repo, m)
        if not plan_path:
            continue
        spec = _spec_of_plan(repo, m, plan_path)
        _, first_ts = _first_commit(repo, plan_path)
        start_ts = prev_ct
        if start_ts is None:
            start_ts = first_ts
        elif first_ts is not None:
            # the window starts at the later of the previous plan merge and the last merge of any kind before the plan's
            # first commit: plan-less merges (fixes) in between are not this spec's time
            before = [c for c in all_cts if c < first_ts]
            if before and max(before) > start_ts:
                start_ts = max(before)
        prev_ct = m["ct"]
        if spec in have:
            continue
        rec = build_record(repo, spec, "backfill", "merged", now, conn=conn, project=project,
                           window=(start_ts if start_ts is not None else m["ct"], m["ct"], "derived"),
                           plan=(plan_path, "", m["second"]), merge=m, batch_base=m["first"], backfilled=True)
        append(repo, rec)
        have.add(spec)
        written.append(rec)
    return written


def cmd_backfill(repo, args):
    global LOG_OVERRIDE
    LOG_OVERRIDE = args.log
    try:
        conn = usage.connect(args.usage_db or usage.db_path())
        try:
            if not args.no_ingest:
                ingest_project(conn, main_root(repo))
            since = _parse_when(args.since or "2026-11-04")
            until = _parse_when(args.until, end=True) if args.until else None
            recs = backfill_runs(repo, since, until, conn, project=args.project)
        finally:
            conn.close()
        for r in recs:
            print(f"backfilled {r['spec']}: {r['tasks'] if r['tasks'] is not None else '?'} tasks, "
                  f"{r['tokens']['total'] / 1e6:.2f}M tokens, {r['active_min']} active min, {r['handoffs']} handoffs")
        print(f"backfilled {len(recs)} specs")
    finally:
        LOG_OVERRIDE = None


def _with_log(args, fn):
    """Run fn with `--log PATH` (when given) as the run log; LOG_OVERRIDE is restored afterwards."""
    global LOG_OVERRIDE
    saved = LOG_OVERRIDE
    if getattr(args, "log", None):
        LOG_OVERRIDE = args.log
    try:
        return fn()
    finally:
        LOG_OVERRIDE = saved


def cmd_append(repo, args):
    def go():
        if args.kind in STAGE1_KINDS:
            raise MetricsError(f"kind {args.kind} has its own command")
        try:
            obj = json.loads(args.json)
        except ValueError:
            raise MetricsError("--json is not valid JSON")
        if not isinstance(obj, dict):
            raise MetricsError("--json must be a JSON object")
        obj["kind"] = args.kind
        if args.batch:
            obj["batch"] = args.batch
        append(repo, obj)
    _with_log(args, go)


def cmd_has(repo, args):
    def go():
        for d in read_log(repo)[0]:
            if d.get("kind") == args.kind and (not args.spec or d.get("spec") == args.spec) \
                    and (not args.batch or d.get("batch") == args.batch):
                return 0
        return 1
    return _with_log(args, go)


def cmd_runs(repo, args):
    def go():
        lines = read_log(repo)[0]
        batch = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == args.batch), None)
        if batch is None:
            raise MetricsError(f"unknown batch {args.batch}")
        by = last_runs(lines)
        specs = sorted(batch.get("specs") or batch.get("assignment") or {})
        specs += sorted({k[1] for k in by if k[0] == args.batch and k[1] not in specs})
        runs = {s: by.get((args.batch, s)) for s in specs}
        res = pair_results(repo, batch, [r for r in runs.values() if r])
        pairs = None if res is None else [{"a": a, "b": b, "clean": c, "paths": p} for a, b, c, p in res]
        print(json.dumps({"batch": args.batch, "base": batch.get("base"), "at": batch.get("at"), "specs": specs,
                          "runs": runs, "pairs": pairs}, sort_keys=True))
    _with_log(args, go)


def cmd_backfill_tasks(repo, args):
    """Task lines for every run line whose (batch, spec) has none yet. A run whose lines cannot be built is named on stderr."""
    global TASKS_OVERRIDE
    TASKS_OVERRIDE = args.tasks_log
    try:
        have = {(d.get("batch"), d.get("spec")) for d in read_tasks(repo)[0]}
        conn = usage.connect(args.usage_db or usage.db_path())
        specs = tasks = partial = 0
        try:
            if not args.no_ingest:
                ingest_project(conn, main_root(repo))
            for key, run in last_runs(read_log(repo)[0]).items():
                if key in have:
                    continue
                try:
                    lines = task_lines_for_run(repo, run, conn)
                except Exception as e:
                    print(f"metrics: backfill-tasks: skipped {run.get('spec')}: {clean_reason(e, repo)}", file=sys.stderr)
                    continue
                if not lines:
                    continue
                for t in lines:
                    append_task(repo, t)
                specs += 1
                tasks += len(lines)
                partial += sum(1 for t in lines if t["partial"])
        finally:
            conn.close()
        print(f"backfilled tasks for {specs} specs ({tasks} tasks, {partial} partial)")
    finally:
        TASKS_OVERRIDE = None


def write_stats(repo, since_text, projects=None, tasks_log=None, out=None):
    """Compute stats.json and write it (R5: `out`, else $TC_STATE/analytics/stats.json). Projects (R4): `projects`, else
    `overview --json`, else this repo alone. Returns (stats, path)."""
    import metrics_analyze   # lazy: metrics_analyze imports nothing from here
    now = int(time.time())
    m = re.fullmatch(r"(\d+)d", since_text)
    try:
        since = now - int(m.group(1)) * 86400 if m else _parse_when(since_text)
    except ValueError:
        raise MetricsError(f"bad --since {since_text}: use 7d, 30d, an ISO date or datetime")
    here = main_root(repo)
    if projects:
        projects, source = list(projects), "args"
    else:
        try:
            projects, source = metrics_analyze.overview_projects(), "overview"
            if here in projects:
                projects.remove(here)
                projects.insert(0, here)
        except Exception:
            projects, source = [here], "repo-only"
    stats = metrics_analyze.analyze(projects, since, now, tasks_log=tasks_log, source=source)
    path = Path(out) if out else tc_env.state_dir() / "analytics" / "stats.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=1) + "\n")
    return stats, path


def cmd_analyze(repo, args):
    stats, out = write_stats(repo, args.since, args.projects, args.tasks_log, args.out)
    if args.json:
        print(json.dumps(stats, indent=1))
    else:
        print(f"analyzed {stats['trends']['specs_run']['current']} specs, {stats['coverage']['tasks']} tasks "
              f"across {len(stats['projects'])} projects → {out}")


def _recommend_to_file(stats_path):
    import metrics_recommend
    res = metrics_recommend.recommend(stats_path)
    (Path(stats_path).resolve().parent / "recommend.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def _analytics_off():
    return os.environ.get("TC_ANALYTICS") == "0" or (tc_env.agent_base() / "analytics.off").exists()


def _destinations(repo):
    """[(dir, idea project, projects or None, stats out or None, multi_project)]: the ops dir when the ops bot is
    configured, else each project with a Discord home channel."""
    import discord_feed, discord_ops, metrics_analyze
    if discord_ops.configured():
        return [(tc_env.ops_dir(), Path(main_root(repo)).name, None, None, True)]
    try:
        paths = metrics_analyze.overview_projects()
    except Exception:
        paths = [main_root(repo)]
    out = []
    for p in paths:
        name = Path(p).name
        if discord_feed.channel_of(name):
            out.append((tc_env.discord_dir(name), name, [p], tc_env.state_dir() / "analytics" / name / "stats.json", False))
    return out


def _sum_usage(usages):
    """(cost_usd or None, tokens dict or None): per-field sums over the non-None values."""
    costs = [u["cost_usd"] for u in usages if u.get("cost_usd") is not None]
    toks = [u["tokens"] for u in usages if u.get("tokens")]
    tokens = {k: sum(t.get(k) or 0 for t in toks) for k in ("input", "output", "cache_read", "cache_write")} if toks else None
    return (round(sum(costs), 4) if costs else None), tokens


def cmd_weekly(repo, args):
    """`weekly`: analyze, recommend and post to Discord per destination, then record one kind:analytics line.
    `--dry-run` prints the report text (or, with --json, the ops) and writes nothing."""
    import metrics_recommend, analytics_post
    if args.json and not args.dry_run:
        raise MetricsError("--json needs --dry-run")
    if args.dry_run and not args.json:
        stats, path = write_stats(repo, args.since, tasks_log=args.tasks_log)
        if stats["trends"]["specs_run"]["current"] == 0:
            print("no runs in the window; nothing to post")
            return
        print(metrics_recommend.weekly_text(stats, _recommend_to_file(path), path), end="")
        return
    if not args.dry_run and _analytics_off():
        print("analytics: off")
        return
    t0 = time.time()
    posts, dests, usages, week, partial, err, skipped = 0, [], [], None, False, None, 0
    try:
        for d, name, projects, out, multi in _destinations(repo):
            stats, path = write_stats(repo, args.since, projects, args.tasks_log, out)
            week = week or analytics_post.week_id(stats["window"]["until"])
            if stats["trends"]["specs_run"]["current"] == 0:
                continue
            rec = _recommend_to_file(path)
            usages.append(rec.get("usage") or {})
            partial = partial or "unavailable" in rec
            if args.dry_run:
                week = analytics_post.week_id(stats["window"]["until"])
                for op in analytics_post.build_ops(stats, rec, week, path, multi):
                    print(json.dumps(op, sort_keys=True))
                continue
            n = analytics_post.publish(d, name, stats, rec, path, multi, force=args.force)
            if not n:
                skipped += 1
                print(f"already posted {analytics_post.week_id(stats['window']['until'])} to {Path(d).name}")
                continue
            posts += n
            dests.append(Path(d).name)
        if not args.dry_run and not posts and not skipped:
            print("no runs in the window; nothing to post")
    except Exception as e:
        err = (str(e).splitlines() or [type(e).__name__])[0]
        raise
    finally:
        if not args.dry_run and (err is None or dests):   # a failure before anything posted leaves no record
            _weekly_record(repo, posts, dests, usages, week, partial, err, skipped, t0)


def _weekly_record(repo, posts, dests, usages, week, partial, err, skipped, t0):
    import analytics_post
    cost, tokens = _sum_usage(usages)
    if log_path(repo).is_file():
        rec = {"kind": "analytics", "at": utc(), "week": week or analytics_post.week_id(utc()),
               "outcome": "partial" if err else ("already-posted" if skipped else "no-runs") if not posts else "partial" if partial else "posted",
               "posts": posts, "destinations": dests, "cost_usd": cost, "tokens": tokens,
               "duration_s": int(time.time() - t0), "model": "sonnet"}
        if err:
            rec["error"] = err
        append(repo, rec)


def cmd_recommend(repo, args):
    """Ask the model for three recommendations over stats.json (computed first unless --stats), keep the ones whose
    evidence matches, write recommend.json beside the stats file."""
    import metrics_recommend   # lazy: it imports metrics_analyze, never metrics
    if args.stats:
        stats_path = Path(args.stats).resolve()
        if not stats_path.is_file():
            raise MetricsError(f"stats file not found: {stats_path.name}")
    else:
        stats_path = write_stats(repo, args.since)[1]
    res = _recommend_to_file(stats_path)
    if "unavailable" in res:
        print(f"recommendations unavailable: {res['unavailable']}")
        return
    for d in res["dropped"]:
        print(f"metrics: recommend: dropped \"{d['title']}\": {d['reason']}", file=sys.stderr)
    for it in res["items"]:
        print(f"- {it['title']}")
    print(f"({res['passed']} of {res['asked']} passed the evidence check)")


def _log_error(repo, sub, exc, log=None):
    """Append a kind:error line: to `log` when the command was given one, else to the run log, but only when the
    repo already has a metrics directory (a repo without metrics files stays clean)."""
    global LOG_OVERRIDE
    if repo is None:
        return
    saved = LOG_OVERRIDE
    try:
        if log:
            LOG_OVERRIDE = log
        elif not mdir(repo).is_dir():
            return
        append(repo, {"kind": "error", "sub": sub, "reason": clean_reason(exc, repo), "at": utc()})
    except Exception:
        pass
    finally:
        LOG_OVERRIDE = saved


def rel_spec(repo, spec):
    """A spec argument as a repo-relative path: absolute paths inside the repo (or its main checkout) are made relative,
    a leading ./ is dropped, anything outside is an error naming only the basename."""
    roots = {os.path.realpath(str(repo)), os.path.realpath(main_root(repo))}
    p = spec if os.path.isabs(spec) else os.path.join(main_root(repo), spec)
    p = os.path.normpath(p)
    rp = os.path.realpath(p) if os.path.exists(p) else os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
    for r in sorted(roots, key=len, reverse=True):
        if rp == r or rp.startswith(r + os.sep):
            return os.path.relpath(rp, r)
    raise MetricsError(f"spec outside the repo: {os.path.basename(spec)}")


def rel_worktree(repo, path):
    """--worktree as `.claude/worktrees/<name>[/…]` relative to the main checkout; anything else is a UsageError."""
    root = os.path.realpath(main_root(repo))
    p = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    rp = os.path.realpath(p) if os.path.exists(p) else os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
    rel = os.path.relpath(rp, root)
    parts = rel.split(os.sep)
    if len(parts) < 3 or parts[:2] != [".claude", "worktrees"] or ".." in parts:
        raise UsageError("--worktree must be under .claude/worktrees/")
    return rel


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = "metrics"
    repo = None
    args = None
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
        repo = None
        repo = repo_root(getattr(args, "repo", None))
        if args.sub == "batch":
            args.specs = [rel_spec(repo, s) for s in args.specs]
            args.group = [",".join(rel_spec(repo, x.strip()) for x in g.split(",") if x.strip()) for g in args.group]
        elif getattr(args, "spec", None) is not None:
            args.spec = rel_spec(repo, args.spec)
        rc = {"batch": cmd_batch_start, "start": cmd_start, "defect": cmd_defect, "record": cmd_record, "report": cmd_report,
              "compare": cmd_compare, "gate": cmd_gate, "status": cmd_status, "backfill": cmd_backfill,
              "backfill-tasks": cmd_backfill_tasks, "append": cmd_append, "has": cmd_has, "runs": cmd_runs, "analyze": cmd_analyze, "recommend": cmd_recommend, "weekly": cmd_weekly}[args.sub](repo, args)
        return rc or 0
    except Exception as e:  # MetricsError or anything else: one line, never a traceback
        print(f"metrics: {sub}: {e}", file=sys.stderr)
        if sub != "weekly":   # the weekly job reports to stderr (the launchd log) only
            _log_error(repo, sub, e, getattr(args, "log", None) or getattr(args, "tasks_log", None))
        return getattr(e, "code", 1)


if __name__ == "__main__":
    sys.exit(main())
