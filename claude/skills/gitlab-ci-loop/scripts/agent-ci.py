#!/usr/bin/env python3
"""agent-ci: drive the GitLab MR pipeline loop from the terminal.

  check [...]      run local checks for changed files (args passed to local-check.py)
  start <topic>    create <prefix><topic> from origin/<integration_branch>
                   (--base REF branches from REF and opens the MR against it; REF must be in mr_targets)
  follow           read-only: wait for the MR to merge, then postmerge its target (finish does this by default)
  postmerge        read-only: watch the pipeline on the merged ref (default: staging), follow pipelines
                   referenced by failed job logs, group failures by root-cause signature, keep an
                   attempt log (.agent-ci/incidents.json), stop after postmerge.max_rounds repeats
  cycle            local-check -> push -> MR -> watch -> failures   (the one-liner loop)
  push             local-check, push branch, create/reuse MR (ready for review; mr_draft: true for drafts)
  watch            wait for the pipeline of HEAD; print failures if red
  failures         failed jobs (incl. child pipelines) with trimmed log tails
  status           branch, MR and latest pipeline summary
  finish -m MSG    squash into one commit, force-push (agent branches only), set the final MR title,
                   then follow the merge (--no-follow to return)
  stage0-plan      dry-run by default; --execute triggers a plan-only main-ref stage-0 pipeline
  watch --pipeline ID --stage0  watch that specific plan and verify stage-0 job ran

Exit codes: 0 ok/green, 1 failed, 2 usage/guard error, 3 no pipeline / only manual jobs, 4 timeout, 5 max rounds reached.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from agentci_config import STATE_DIR, load_config, repo_root  # noqa: E402

TTY = sys.stdout.isatty()
if not TTY:
    # Piped (agents, Remote Control): flush every line so progress shows as it happens.
    sys.stdout.reconfigure(line_buffering=True)
C = {k: (v if TTY else "") for k, v in dict(g="\033[32m", r="\033[31m", y="\033[33m", d="\033[2m", b="\033[1m", x="\033[0m").items()}
GLAB_ENV = {**os.environ, "GLAB_NO_PROMPT": "1", "NO_COLOR": "1"}
GLAB_ENV.pop("NO_PROMPT", None)
TRANSPORT = os.environ.get("AGENT_CI_GIT_TRANSPORT", "auto")  # auto | https
os.environ["GIT_TERMINAL_PROMPT"] = "0"
TERMINAL = {"success", "failed", "canceled", "skipped", "manual"}
STAGE0_JOB = "landing-zone-deploy-stage0"
STAGE0_VARIABLES = {
    "PIPELINE_TYPE": "landing-zone",
    "LANDING_ZONE_STAGE": "0-org-setup",
    "APPLY_MODE": "plan",
}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|section_(start|end):\d+:[^\r\n]*?\r|\r")


def say(msg: str) -> None:
    print(f"{C['d']}[agent-ci]{C['x']} {msg}", flush=True)


def fail(msg: str, code: int = 2) -> None:
    print(f"{C['r']}[agent-ci] {msg}{C['x']}", file=sys.stderr)
    sys.exit(code)


def sh(*args: str, check: bool = True, capture: bool = True) -> str:
    res = subprocess.run(args, capture_output=capture, text=True)
    if check and res.returncode != 0:
        fail(f"command failed: {' '.join(args)}\n{(res.stderr or res.stdout or '').strip()}", 1)
    return (res.stdout or "").strip()


def glab_bin() -> str:
    path = shutil.which("glab") or os.path.expanduser("~/.local/bin/glab")
    if not os.path.exists(path):
        fail("glab not found. Run the skill's scripts/install-glab.sh, then `glab auth login`.")
    return path


def api(endpoint: str, method: str = "GET", raw: bool = False, fields: dict | None = None):
    cmd = [glab_bin(), "api", "-X", method, endpoint]
    for k, v in (fields or {}).items():
        cmd += (["-F", f"{k}={json.dumps(v)}"] if isinstance(v, (list, dict))
                else ["-f", f"{k}={v}"])
    res = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=GLAB_ENV)
    if res.returncode != 0:
        if endpoint == "projects/:id/pipeline" and "permission to run a pipeline" in res.stderr:
            fail("this glab account cannot run pipelines on protected main. "
                 "Use an authorized GitLab account, or have an operator trigger the plan "
                 "and pass its pipeline ID to `agent-ci watch --pipeline ID --stage0`.")
        fail(f"GitLab API {method} {endpoint} failed: {res.stderr.strip() or res.stdout.strip()}", 1)
    return res.stdout if raw else json.loads(res.stdout or "null")


def api_read_with_permission_check(endpoint: str):
    """A 403 is expected for pipeline variables on Developer-scoped tokens."""
    res = subprocess.run([glab_bin(), "api", endpoint], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, env=GLAB_ENV)
    if res.returncode == 0:
        return json.loads(res.stdout)
    if "403 Forbidden" in res.stderr:
        say("GitLab denied pipeline-variable access (403); plan mode must be verified in the job trace.")
        return None
    fail(f"GitLab API {endpoint} failed: {res.stderr.strip()}", 1)


def ensure_auth() -> None:
    if not sh("git", "remote", "get-url", "origin", check=False):
        fail("no 'origin' remote — add the GitLab remote first (git remote add origin <url>).")
    res = subprocess.run([glab_bin(), "auth", "status"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, env=GLAB_ENV)
    if res.returncode != 0:
        fail("glab is not authenticated for this host. Ask the user to run: glab auth login")


# ── git helpers ──────────────────────────────────────────────────────────────

_NET: list[str] | None = None


def git_net(*args: str) -> list[str]:
    """git command for network ops. If origin is https (can't prompt here) and SSH works, route over SSH
    via a per-command insteadOf — the user's remote and global config are untouched."""
    global _NET
    if _NET is None:
        _NET = []
        url = sh("git", "remote", "get-url", "origin", check=False)
        m = re.match(r"^https://(?:[^@/]+@)?([^/]+)/", url)
        if m and TRANSPORT != "https":
            host = m.group(1)
            probe = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-T", f"git@{host}"],
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if "welcome" in (probe.stdout + probe.stderr).lower():
                _NET = ["-c", f"url.git@{host}:.insteadOf=https://{host}/"]
    return ["git", *_NET, *args]


def branch() -> str:
    return sh("git", "rev-parse", "--abbrev-ref", "HEAD")


def head_sha() -> str:
    return sh("git", "rev-parse", "HEAD")


def base_ref(cfg: dict, target: str | None = None) -> str:
    target = target or cfg["integration_branch"]
    sh(*git_net("fetch", "--quiet", "origin", target), check=False)
    return f"origin/{target}"


def allowed_targets(cfg: dict) -> list[str]:
    return [cfg["integration_branch"], *[t for t in (cfg.get("mr_targets") or []) if t != cfg["integration_branch"]]]


def target_path(b: str) -> str:
    return os.path.join(repo_root(), STATE_DIR, "targets", b.replace("/", "__"))


def target_for(cfg: dict, b: str) -> str:
    """MR target for an agent branch: recorded by `start --base`, else the integration branch."""
    try:
        t = Path(target_path(b)).read_text().strip()
    except OSError:
        return cfg["integration_branch"]
    if t in allowed_targets(cfg):
        return t
    # A branch cut from another target carries that target's .agent-ci.yml, which may predate
    # mr_targets. `start --base` already validated the record; an explicit mr_targets still wins.
    if "mr_targets" not in cfg and t in (cfg.get("protected_branches") or []):
        return t
    return cfg["integration_branch"]


def guard_branch(cfg: dict) -> str:
    b = branch()
    if b in cfg["protected_branches"] or b == cfg["integration_branch"]:
        fail(f"refusing to operate on protected branch '{b}'. Use: agent-ci start <topic>")
    if not b.startswith(cfg["branch_prefix"]):
        fail(f"branch '{b}' does not start with '{cfg['branch_prefix']}'. Use: agent-ci start <topic>")
    return b


def ensure_clean() -> None:
    if sh("git", "status", "--porcelain", "--untracked-files=no"):
        fail("working tree has uncommitted changes — commit them first (only committed work is pushed).")


def rounds_file(b: str) -> str:
    return os.path.join(repo_root(), STATE_DIR, "rounds", b.replace("/", "__"))


def bump_rounds(b: str, reset: bool = False) -> int:
    path = rounds_file(b)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0 if reset else (int(open(path).read() or 0) if os.path.exists(path) else 0) + 1
    with open(path, "w") as fh:
        fh.write(str(n))
    return n


def stage0_round(cfg: dict, pid: int, success: bool = False) -> int:
    """Only count each failed stage-0 pipeline once, even if watched again."""
    key = "stage0-main"
    if success:
        bump_rounds(key, reset=True)
        return 0
    marker = os.path.join(repo_root(), STATE_DIR, "rounds", f"{key}-{pid}")
    if os.path.exists(marker):
        return int(Path(rounds_file(key)).read_text())
    n = bump_rounds(key)
    with open(marker, "w") as fh:
        fh.write(str(pid))
    say(f"stage-0 red round {n}/{cfg['max_ci_rounds']}")
    if n >= int(cfg["max_ci_rounds"]):
        say("STOP: five failed stage-0 rounds. Report the blockers; do not trigger another plan.")
    return n


# ── MR / pipeline helpers ────────────────────────────────────────────────────

def find_mr(b: str) -> dict | None:
    mrs = api(f"projects/:id/merge_requests?state=opened&source_branch={urllib.parse.quote(b, safe='')}")
    return mrs[0] if mrs else None


CONVENTIONAL_RE = re.compile(r"^\[?([a-z]+(?:\([^)\]]*\))?!?)\]?:\s*(.+)$")
BRACKETED_TITLE_RE = re.compile(r"^\[[^\]]+\]:\s")


def mr_title_style(cfg: dict, target: str) -> str:
    """bracketed → "[fix(scope)]: subject", plain → "fix(scope): subject".
    auto (default) follows the majority of recent merged MRs into the same target."""
    style = cfg.get("mr_title_style", "auto")
    if style in ("bracketed", "plain"):
        return style
    mrs = api_optional(f"projects/:id/merge_requests?state=merged&target_branch="
                       f"{urllib.parse.quote(target, safe='')}&order_by=updated_at&per_page=20") or []
    titles = [m.get("title", "") for m in mrs if isinstance(m, dict)]
    bracketed = sum(1 for t in titles if BRACKETED_TITLE_RE.match(t))
    return "bracketed" if titles and bracketed * 2 > len(titles) else "plain"


def format_mr_title(subject: str, style: str) -> str:
    m = CONVENTIONAL_RE.match(subject.strip())
    if not m:
        return subject.strip()
    return f"[{m[1]}]: {m[2]}" if style == "bracketed" else f"{m[1]}: {m[2]}"


def ensure_mr(cfg: dict, b: str) -> dict:
    mr = find_mr(b)
    if mr:
        return mr
    target = target_for(cfg, b)
    base = base_ref(cfg, target)
    # first-parent: a merged-in branch's own commits (e.g. staging's, when syncing it) aren't this MR's subjects
    subjects = sh("git", "log", "--first-parent", "--reverse", "--format=%s", f"{base}..HEAD").splitlines()
    title = subjects[0] if subjects else b.split("/", 1)[-1].replace("-", " ")
    title = format_mr_title(title, mr_title_style(cfg, target))
    desc = "\n".join(f"- {s}" for s in subjects) or title
    mr = api("projects/:id/merge_requests", "POST", fields={
        "source_branch": b, "target_branch": target,
        "title": f"Draft: {title}" if cfg.get("mr_draft") else title,
        "description": desc, "remove_source_branch": "true",
    })
    say(f"opened {'draft ' if cfg.get('mr_draft') else ''}MR !{mr['iid']}")
    return mr


def settle_commit_pipelines(sha: str, pl: dict, deadline: float, interval: int) -> dict | None:
    """Push and merge-request pipelines can both run for one commit; wait for all, return the worst."""
    while True:
        pls = api(f"projects/:id/pipelines?sha={sha}&order_by=id&sort=desc&per_page=20")
        if not [p for p in pls if p["status"] not in TERMINAL]:
            break
        if time.time() > deadline:
            return None
        time.sleep(interval)
    failed = [p for p in pls if p["status"] == "failed"]
    if failed and failed[0]["id"] != pl["id"]:
        say(f"pipeline {failed[0]['id']} ({failed[0].get('source')}) for this commit failed: {failed[0]['web_url']}")
        return api(f"projects/:id/pipelines/{failed[0]['id']}")
    return pl


DISPATCH_JOB_RE = re.compile(r"^dispatch-([0-9a-f]+)-(\d+)$")
TREE_SYM = {"success": "✓", "failed": "✗", "running": "▶", "pending": "…", "created": "·", "skipped": "-",
            "manual": "⏸", "canceled": "⊘", "waiting_for_resource": "…", "preparing": "…", "scheduled": "…"}


class PipelineTree:
    """Read-only live view of a pipeline and what it started: bridge children, plus the API pipelines that
    `dispatch-<plan hash>-<target id>` jobs create (matched on their RELEASE_PLAN_ID/RELEASE_TARGET_ID)."""

    def __init__(self, root: dict, api_vars: dict | None = None, project: str = ":id"):
        self.root, self.project = root, project
        self.api_vars = {} if api_vars is None else api_vars   # API pipeline id → variables (fetched once)

    def _dispatch_children(self) -> dict[tuple[str, str], list[dict]]:
        pls = api_optional(f"projects/{self.project}/pipelines?ref={urllib.parse.quote(self.root['ref'], safe='')}"
                           f"&source=api&updated_after={urllib.parse.quote(self.root['created_at'], safe='')}"
                           f"&per_page=50") or []
        out: dict[tuple[str, str], list[dict]] = {}
        for pl in pls:
            if pl["id"] not in self.api_vars:
                vs = api_optional(f"projects/{self.project}/pipelines/{pl['id']}/variables") or []
                self.api_vars[pl["id"]] = {v["key"]: v.get("value", "") for v in vs if isinstance(v, dict)}
            v = self.api_vars[pl["id"]]
            plan, target = v.get("RELEASE_PLAN_ID", ""), v.get("RELEASE_TARGET_ID", "")
            if plan and target:
                out.setdefault((plan.rsplit("-", 1)[-1], target), []).append(pl)
        return out

    def render(self) -> str:
        lines: list[str] = []
        dispatched = None

        def walk(pl: dict, label: str, depth: int) -> None:
            nonlocal dispatched
            jobs = jobs_of(pl["id"], self.project)
            lines.append(f"{'   ' * depth}{label} {pl['id']} {TREE_SYM.get(pl['status'], pl['status'])} "
                         f"{pl['status']}  {job_counts(jobs)}")
            if depth >= 3:
                return
            for j in jobs:
                m = DISPATCH_JOB_RE.match(j["name"])
                if not m:
                    continue
                if dispatched is None:
                    dispatched = self._dispatch_children()
                for child in dispatched.get((m[1], m[2]), []):
                    walk(child, f"{j['name']} →", depth + 1)
            for br in api_optional(f"projects/{self.project}/pipelines/{pl['id']}/bridges?per_page=100") or []:
                ds = br.get("downstream_pipeline")
                if ds:
                    walk(ds, f"{br['name']} →", depth + 1)

        walk(self.root, "pipeline", 0)
        return "\n".join(lines)


def print_tree_if_changed(tree: PipelineTree, last: str) -> str:
    text = tree.render()
    if text != last:
        say(time.strftime("%H:%M:%S"))
        print(text, flush=True)
    return text


def pipeline_for(sha: str) -> dict | None:
    pls = api(f"projects/:id/pipelines?sha={sha}&order_by=id&sort=desc&per_page=5")
    return pls[0] if pls else None


def jobs_of(pid: int, project: str = ":id") -> list[dict]:
    jobs = []
    page = 1
    while True:
        batch = api(f"projects/{project}/pipelines/{pid}/jobs?per_page=100&include_retried=false&page={page}")
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def job_counts(jobs: list[dict]) -> str:
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"], 0) + 1
    sym = {"success": "✓", "failed": "✗", "running": "▶", "pending": "…", "created": "·", "skipped": "-", "manual": "⏸", "canceled": "⊘"}
    return " ".join(f"{sym.get(k, k)}{v}" for k, v in sorted(counts.items()))


TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z [0-9A-F]{2}[OE]\+? ?")
NOISE_RE = re.compile(
    r"^(section_(start|end):|Running with gitlab-runner|Preparing the |Using (docker|effective pull|Docker executor)|"
    r"Pulling docker image|Resolving secrets|Getting source from|Gitaly correlation|Fetching changes|"
    r"Initialized empty Git|Created fresh repository|Reinitialized existing|Checking out [0-9a-f]+ as|"
    r"Skipping Git submodules|\$ git remote set-url|Executing \"step_|Running on runner-|Cleaning up |"
    r"Uploading artifacts|Downloading artifacts|WARNING: .*artifacts|Saving cache|Restoring cache|Job succeeded)")


def clean_log(text: str) -> list[str]:
    out = []
    for ln in ANSI_RE.sub("", text.replace("\r\n", "\n")).split("\n"):
        ln = TS_RE.sub("", ln).rstrip()
        if ln.strip() and not NOISE_RE.match(ln.strip()):
            out.append(ln)
    # runner/environment preamble ends where the job's own commands start
    first_cmd = next((i for i, ln in enumerate(out) if ln.startswith("$ ")), 0)
    return out[first_cmd:]


PIPELINE_REF_RE = re.compile(r"\bpipeline[ #:/]+(\d{7,})\b", re.I)
ERR_RE = re.compile(r"\bERROR\b|\bError\b|\bFailed\b|denied|Traceback|unsupported|not found", re.I)
GENERIC_ERR_RE = re.compile(r"^ERROR: Job failed")
PLACEHOLDER_RE = re.compile(r"""['"](\$\{?[A-Z_][A-Z0-9_]*\}?)['"]""")
INFRA_RE = re.compile(r"PERMISSION_DENIED|permission denied|\b403\b|workload.?identity|invalid_grant|"
                      r"state file|no outputs|quota|iam\.", re.I)


def api_optional(endpoint: str):
    """GET that returns None instead of exiting on failure (used when following log-referenced pipelines)."""
    res = subprocess.run([glab_bin(), "api", endpoint], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, env=GLAB_ENV)
    if res.returncode != 0:
        return None
    try:
        return json.loads(res.stdout or "null")
    except ValueError:
        return None


def root_error_line(lines: list[str]) -> str:
    """The last real error line of a job log (not a `$ cmd` echo or the runner's generic 'Job failed')."""
    real = [ln for ln in lines if ERR_RE.search(ln) and not ln.startswith("$ ") and not GENERIC_ERR_RE.match(ln)]
    return real[-1] if real else (lines[-1] if lines else "")


def failure_hint(lines: list[str]) -> str | None:
    """Classify by the root error line only; earlier warnings (e.g. terraform's) are not the cause."""
    err = root_error_line(lines)
    if PLACEHOLDER_RE.search(err):
        return "unexpanded"
    return "infra" if INFRA_RE.search(err) else None


def error_signature(job_name: str, lines: list[str]) -> str:
    """Stable key for 'the same failure': job name + last real error line, with ids/numbers normalized."""
    name = re.sub(r"dispatch-[0-9a-f]+-\d+", "dispatch-<h>", job_name)
    err = root_error_line(lines)
    err = re.sub(r"^\d{4}-\d\d-\d\d[ T][\d:.,]+Z?\s*", "", err)
    err = re.sub(r"\b[0-9a-f]{8,}\b", "<h>", err)
    err = re.sub(r"\b\d+\b", "N", err)  # standalone numbers only, so names like ga4 survive
    return f"{name} :: {err.strip()[:160]}"


def incidents_path() -> str:
    return os.path.join(repo_root(), STATE_DIR, "incidents.json")


def load_incidents() -> dict:
    try:
        with open(incidents_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_incidents(data: dict) -> None:
    os.makedirs(os.path.dirname(incidents_path()), exist_ok=True)
    with open(incidents_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def record_incident(sig: str, pipeline_id: int) -> dict:
    """Count distinct failed pipelines per signature (re-watching one pipeline never double counts)."""
    data = load_incidents()
    entry = data.setdefault(sig, {"count": 0, "pipelines": [], "attempts": []})
    if pipeline_id not in entry["pipelines"]:
        entry["pipelines"].append(pipeline_id)
    entry["count"] = len(entry["pipelines"])
    save_incidents(data)
    return entry


def add_attempt(sig_part: str, note: str) -> str:
    data = load_incidents()
    hits = [s for s in data if sig_part in s]
    if len(hits) != 1:
        fail(f"{len(hits)} incidents match {sig_part!r}; use a more specific part of the signature "
             f"(see `agent-ci postmerge` output / .agent-ci/incidents.json)")
    data[hits[0]]["attempts"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note})
    save_incidents(data)
    return hits[0]


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_start(cfg: dict, args) -> int:
    topic = re.sub(r"[^a-zA-Z0-9._-]+", "-", args.topic).strip("-").lower()
    name = cfg["branch_prefix"] + topic
    target = args.base or cfg["integration_branch"]
    if target not in allowed_targets(cfg):
        fail(f"--base {target} is not an allowed MR target. Allowed: {', '.join(allowed_targets(cfg))} "
             f"(add it to mr_targets in .agent-ci.yml if intended).", 2)
    base = base_ref(cfg, target)
    sh("git", "switch", "-c", name, base, capture=False)
    path = target_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if target != cfg["integration_branch"]:
        Path(path).write_text(target)
    elif os.path.exists(path):
        os.remove(path)
    say(f"on {name} (from {base}; MR will target {target})")
    return 0


def run_local_check(extra: list[str] | None = None, cfg: dict | None = None) -> bool:
    extra = list(extra or [])
    if cfg and "--base" not in extra and not any(a.startswith("--base=") for a in extra):
        b = branch()
        if b.startswith(cfg["branch_prefix"]):
            # diff against the branch's MR target (e.g. staging after `start --base staging`)
            extra = ["--base", target_for(cfg, b), *extra]
    cmd = [sys.executable, os.path.join(HERE, "local-check.py"), *extra]
    return subprocess.run(cmd).returncode == 0


# Errors a standalone include fragment produces only because its context lives in the root file.
LINT_UNRESOLVED_INCLUDE_RE = re.compile(r"Local file `[^`]+` does not exist|chosen stage \S+ does not exist")


def lint_ci_if_changed(cfg: dict) -> None:
    changed = sh("git", "diff", "--name-only", f"{base_ref(cfg, target_for(cfg, branch()))}...HEAD").splitlines()
    ci_files = [f for f in changed if re.search(r"(^|/)\.?gitlab-ci[^/]*\.ya?ml$", f) and os.path.exists(f)]
    for f in ci_files:
        # Each changed file is linted on its own. GitLab resolves `include: local` against the
        # project's default branch, and fragments rely on the root file's `stages:`, so those
        # errors can't be settled before the push; they're warnings, the pipeline validates them.
        say(f"CI config changed → glab ci lint {f}")
        res = subprocess.run([glab_bin(), "ci", "lint", f], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, env=GLAB_ENV)
        out = (res.stdout + res.stderr).strip()
        if res.returncode == 0:
            continue
        errors = [ln for ln in out.splitlines() if re.match(r"^\s*\d+\s", ln)]
        if errors and all(LINT_UNRESOLVED_INCLUDE_RE.search(ln) for ln in errors):
            say(f"{C['y']}lint needs the root config's context (includes/stages) for {f}; "
                f"the pipeline validates it:{C['x']}\n{out}")
            continue
        fail(f"CI lint failed for {f}:\n{out}", 1)


def cmd_push(cfg: dict, args) -> int:
    b = guard_branch(cfg)
    ensure_auth()
    ensure_clean()
    if not args.no_check and not run_local_check(cfg=cfg):
        fail("local checks failed — fix before pushing (or --no-check to skip).", 1)
    lint_ci_if_changed(cfg)
    push = git_net("push", "--quiet", "-u", "origin", "HEAD")
    if args.force:
        push.insert(push.index("push") + 1, "--force-with-lease")
    sh(*push, capture=False)
    mr = ensure_mr(cfg, b)
    say(f"pushed {head_sha()[:8]} → {mr['web_url']}")
    return 0


def cmd_watch(cfg: dict, args) -> int:
    is_stage0 = getattr(args, "stage0", False)
    pipeline_id = getattr(args, "pipeline", None)
    if is_stage0 and not pipeline_id:
        fail("--stage0 requires --pipeline ID; never select a stage-0 run by HEAD.")
    if is_stage0:
        verified_vars = validate_stage0_pipeline(cfg, pipeline_id)
    else:
        verified_vars = False
    sha = head_sha() if not pipeline_id else ""
    deadline = time.time() + args.timeout
    pl, waited = (api(f"projects/:id/pipelines/{pipeline_id}") if pipeline_id else None), 0
    while pl is None:
        pl = pipeline_for(sha)
        if pl:
            break
        if waited >= args.appear_timeout:
            say(f"{C['y']}no pipeline for {sha[:8]} after {waited}s — no CI jobs matched this change.{C['x']}")
            return 3
        time.sleep(5)
        waited += 5
    say(f"pipeline {pl['id']} {pl['web_url']}")
    last, tree_cache = "", {}
    while True:
        pl = api(f"projects/:id/pipelines/{pl['id']}")
        if is_stage0:
            line = f"{pl['status']:<9} {job_counts(jobs_of(pl['id']))}"
            if line != last:
                say(f"{time.strftime('%H:%M:%S')} {line}")
                last = line
        else:
            last = print_tree_if_changed(PipelineTree(pl, tree_cache), last)
        if pl["status"] in TERMINAL:
            break
        if time.time() > deadline:
            say(f"{C['y']}timed out after {args.timeout}s (pipeline still {pl['status']}){C['x']}")
            return 4
        time.sleep(args.interval)
    if not pipeline_id and not is_stage0:
        settled = settle_commit_pipelines(sha, pl, deadline, args.interval)
        if settled is None:
            say(f"{C['y']}timed out after {args.timeout}s waiting for the other pipelines on {sha[:8]}{C['x']}")
            return 4
        pl = settled

    b = branch()
    stage0_jobs = [j for j in jobs_of(pl["id"]) if j["name"] == STAGE0_JOB] if is_stage0 else []
    if is_stage0 and (len(stage0_jobs) != 1 or stage0_jobs[0]["status"] == "skipped"):
        say(f"{C['r']}Stage-0 job was not executed; pipeline status is not a stage-0 result.{C['x']}")
        return 3
    if pl["status"] in ("skipped", "manual"):
        manual = [j["name"] for j in jobs_of(pl["id"]) if j["status"] == "manual"]
        say(f"{C['y']}no automatic jobs ran (pipeline {pl['status']})"
            + (f"; manual jobs available: {', '.join(manual)}" if manual else "") + f"{C['x']}")
        say("local checks are the only signal for this change; do not start manual jobs unless the user asks.")
        return 3
    if pl["status"] == "success":
        if is_stage0 and stage0_jobs[0]["status"] != "success":
            say(f"{C['r']}Stage-0 job did not succeed ({stage0_jobs[0]['status']}).{C['x']}")
            return 1
        say(f"{C['g']}{C['b']}pipeline green{C['x']} ✓" if is_stage0
            else f"{C['g']}{C['b']}green{C['x']} ✓")
        if b.startswith(cfg["branch_prefix"]) and not is_stage0:
            bump_rounds(b, reset=True)
        if is_stage0:
            if not summarize_stage0_plan(stage0_jobs[0], verified_vars):
                say("Plan artifact review incomplete; do not apply.")
                return 3
            stage0_round(cfg, pl["id"], success=True)
        return 0
    say(f"{C['r']}{C['b']}{pl['status']}{C['x']}")
    print_failures(pl["id"], ":id", args.tail)
    if is_stage0 and stage0_round(cfg, pl["id"]) >= int(cfg["max_ci_rounds"]):
        return 5
    if b.startswith(cfg["branch_prefix"]) and not is_stage0:
        n = bump_rounds(b)
        say(f"red round {n}/{cfg['max_ci_rounds']}")
        if n >= int(cfg["max_ci_rounds"]):
            say(f"{C['y']}STOP: max CI rounds reached — summarize the failures for the user instead of retrying.{C['x']}")
            return 5
    return 1


def stage0_config(cfg: dict) -> tuple[str, str]:
    preset = cfg.get("stage0_plan")
    if not isinstance(preset, dict) or set(preset) != {"project_path", "ref"}:
        fail("stage0-plan requires stage0_plan: {project_path: ..., ref: main} in .agent-ci.yml")
    path, ref = preset["project_path"], preset["ref"]
    if not isinstance(path, str) or not path.strip() or ref != "main":
        fail("stage0-plan requires a nonempty project_path and ref: main")
    return path, ref


def validate_stage0_pipeline(cfg: dict, pid: int) -> bool:
    path, ref = stage0_config(cfg)
    project = api("projects/:id")
    if project["path_with_namespace"] != path:
        fail(f"project mismatch: preset is {path}, glab points to {project['path_with_namespace']}")
    pl = api(f"projects/:id/pipelines/{pid}")
    if pl["ref"] != ref or pl["source"] != "api":
        fail(f"pipeline {pid} is not an API run on {ref}")
    variables = api_read_with_permission_check(f"projects/:id/pipelines/{pid}/variables")
    if variables is None:
        return False
    actual = {v["key"]: v.get("value") for v in variables if v.get("key") in STAGE0_VARIABLES}
    if actual != STAGE0_VARIABLES:
        fail(f"pipeline {pid} is not a plan-only stage-0 run (expected fixed variable set)")
    return True


def cmd_stage0_plan(cfg: dict, args) -> int:
    path, ref = stage0_config(cfg)
    ensure_auth()
    project = api("projects/:id")
    if project["path_with_namespace"] != path:
        fail(f"project mismatch: preset is {path}, glab points to {project['path_with_namespace']}")
    branch_data = api(f"projects/:id/repository/branches/{ref}")
    if not branch_data["protected"]:
        fail(f"{ref} is not protected; stage-0 plans require protected main")
    sha = branch_data["commit"]["id"]
    say(f"POST projects/{project['id']}/pipeline ref={ref} @ {sha[:12]} "
        f"variables={STAGE0_VARIABLES}")
    if not args.execute:
        say("dry run only; pass --execute to trigger exactly this plan-only request")
        return 0
    rounds = rounds_file("stage0-main")
    if os.path.exists(rounds) and int(Path(rounds).read_text()) >= int(cfg["max_ci_rounds"]):
        fail("maximum failed stage-0 rounds reached; ask the user before another trigger")
    pl = api("projects/:id/pipeline", "POST", fields={
        "ref": ref,
        "variables": [{"key": key, "value": value} for key, value in STAGE0_VARIABLES.items()],
    })
    if pl["ref"] != ref or pl["sha"] != sha or pl["source"] != "api":
        fail(f"pipeline {pl['id']} created but its ref/SHA/source differs from preflight; "
             f"inspect {pl['web_url']} before any retry", 1)
    validate_stage0_pipeline(cfg, pl["id"])
    say(f"created plan-only pipeline {pl['id']} → {pl['web_url']}")
    say(f"watch with: agent-ci watch --pipeline {pl['id']} --stage0")
    return 0


def summarize_stage0_plan(job: dict, variables_verified: bool) -> bool:
    """Report nonsecret Terraform counts; do not print Terraform state or values."""
    trace = api(f"projects/:id/jobs/{job['id']}/trace", raw=True)
    if not re.search(r"Running FAST stage '0-org-setup' in mode: plan", trace):
        say("Stage-0 job trace does not confirm APPLY_MODE=plan; do not treat this as a safe plan.")
        return False
    if "Plan-only mode complete for 0-org-setup." not in trace:
        say("Stage-0 job trace does not confirm the plan-only path completed.")
        return False
    if not variables_verified:
        say("Variables API is inaccessible, but the stage-0 script confirms plan-only execution.")
    summaries = re.findall(r"(?:Plan: \d+ to add, \d+ to change, \d+ to destroy\.|No changes\.[^\n]*|Plan-only mode complete for 0-org-setup\.)", trace)
    if summaries:
        for line in dict.fromkeys(summaries):
            say(f"stage-0: {line}")
    else:
        say("stage-0 completed, but no plan totals found in job trace; inspect restricted plan artifacts manually")
    if not summaries:
        return False
    archives = [a for a in job.get("artifacts", []) if a.get("file_type") == "archive" and a.get("size", 0) > 0]
    if not archives:
        say("No saved plan artifact on the stage-0 job; cannot review resource actions. "
            "Fix artifact paths or upload before calling this plan reviewable.")
        return False
    plan_json = None
    for path in ("tmp/tf-results/0-org-setup_plan.json", "tf-results/0-org-setup_plan.json"):
        result = subprocess.run(
            [glab_bin(), "api", f"projects/:id/jobs/{job['id']}/artifacts/{path}"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=GLAB_ENV,
        )
        if result.returncode == 0:
            plan_json = json.loads(result.stdout)
            break
        if "404" not in result.stderr and "404" not in result.stdout:
            fail(f"cannot inspect stage-0 artifact: {result.stderr.strip()}", 1)
    if plan_json is None:
        say("Stage-0 plan JSON artifact not found in expected paths; review in GitLab before calling this complete.")
        return False
    actions: dict[str, int] = {}
    for resource in plan_json.get("resource_changes", []):
        for action in resource.get("change", {}).get("actions", []):
            actions[action] = actions.get(action, 0) + 1
    say(f"Terraform resource actions: {actions or {'no-op': 0}} (values deliberately omitted)")
    if actions.get("delete"):
        say(f"{C['r']}destructive change or replacement in plan: STOP; requires explicit operator review.{C['x']}")
        return False
    say("Inspect restricted plan artifact and org/IAM changes; apply requires separate approval.")
    return True


def print_failures(pid: int, project, tail: int, depth: int = 0, seen: set | None = None,
                   records: list | None = None) -> int:
    """Print failed jobs with log tails. Follows (a) failed child pipelines via bridges and (b) failed
    pipelines whose id appears in a failed job's log (API-triggered fanouts are not bridges).
    If `records` is given, appends one dict per failed job (wrapper=True when a followed pipeline holds the cause)."""
    seen = set() if seen is None else seen
    seen.add((str(project), int(pid)))
    count = 0
    for job in jobs_of(pid, project):
        if job["status"] != "failed":
            continue
        count += 1
        note = " (allowed to fail)" if job.get("allow_failure") else ""
        print(f"\n{C['r']}{C['b']}✗ {job['stage']} / {job['name']}{note}{C['x']}  {C['d']}{job['web_url']}{C['x']}")
        lines = clean_log(api(f"projects/{project}/jobs/{job['id']}/trace", raw=True))
        print("\n".join(lines[-tail:]))
        followed = False
        if depth < 3:
            for ref_id in dict.fromkeys(PIPELINE_REF_RE.findall("\n".join(lines))):
                if (str(project), int(ref_id)) in seen:
                    continue
                ref = api_optional(f"projects/{project}/pipelines/{ref_id}")
                if not ref or ref.get("status") != "failed":
                    continue
                print(f"\n{C['y']}↳ pipeline {ref_id} (referenced by {job['name']}){C['x']}")
                n = print_failures(int(ref_id), project, tail, depth + 1, seen, records)
                count += n
                followed = followed or n > 0
        if records is not None:
            records.append({"pipeline": int(pid), "job": job["name"], "stage": job["stage"],
                            "url": job["web_url"], "wrapper": followed,
                            "signature": error_signature(job["name"], lines),
                            "hint": failure_hint(lines)})
    if depth < 3:
        for br in api(f"projects/{project}/pipelines/{pid}/bridges?per_page=100"):
            ds = br.get("downstream_pipeline")
            if br["status"] == "failed" and ds and (str(ds["project_id"]), int(ds["id"])) not in seen:
                print(f"\n{C['y']}↳ child pipeline via {br['name']}{C['x']}")
                count += print_failures(ds["id"], ds["project_id"], tail, depth + 1, seen, records)
    return count


def cmd_failures(cfg: dict, args) -> int:
    ensure_auth()
    pid = args.pipeline or (pipeline_for(head_sha()) or {}).get("id")
    if not pid:
        fail("no pipeline found for HEAD; pass --pipeline ID", 1)
    n = print_failures(int(pid), ":id", args.tail)
    if not n:
        say("no failed jobs")
    return 1 if n else 0


def cmd_status(cfg: dict, args) -> int:
    ensure_auth()
    b = branch()
    say(f"branch {b} @ {head_sha()[:8]}")
    mr = find_mr(b)
    say(f"MR !{mr['iid']} {'(draft) ' if mr.get('draft') else ''}{mr['web_url']}" if mr else "no open MR")
    pl = pipeline_for(head_sha())
    if pl:
        say(f"pipeline {pl['id']} {pl['status']} {job_counts(jobs_of(pl['id']))}  {pl['web_url']}")
    else:
        say("no pipeline for HEAD")
    return 0


def cmd_cycle(cfg: dict, args) -> int:
    rc = cmd_push(cfg, args)
    return rc or cmd_watch(cfg, args)


def merged_mr_for_head(b: str) -> dict | None:
    """An MR for this branch that was already merged at the current HEAD (branch names get reused, so match the sha)."""
    if find_mr(b):
        return None
    mrs = api(f"projects/:id/merge_requests?state=merged&source_branch={urllib.parse.quote(b, safe='')}"
              f"&order_by=updated_at&per_page=5")
    sha = head_sha()
    return next((m for m in mrs if m.get("sha") == sha), None)


def cmd_finish(cfg: dict, args) -> int:
    b = guard_branch(cfg)
    ensure_auth()
    merged = merged_mr_for_head(b)
    if merged:
        # The user merged before finish ran: nothing left to squash, push or retitle.
        say(f"MR !{merged['iid']} was already merged into {merged['target_branch']}; skipping squash and title")
        if args.no_follow or not (cfg.get("postmerge") or {}).get("follow", True):
            return 0
        return cmd_follow(cfg, argparse.Namespace(mr=merged["iid"], merge_timeout=args.merge_timeout,
                                                  merge_interval=args.merge_interval, timeout=3600,
                                                  interval=20, tail=40))
    ensure_clean()
    pl = pipeline_for(head_sha())
    if not args.force and (not pl or pl["status"] != "success"):
        fail(f"HEAD pipeline is {pl['status'] if pl else 'missing'}; finish only after green (or --force).", 1)
    base = base_ref(cfg, target_for(cfg, b))
    mb = sh("git", "merge-base", base, "HEAD")
    commits = sh("git", "rev-list", f"{mb}..HEAD").split()
    # A branch that merges another branch (e.g. syncing staging into dev3) must keep its merge commit:
    # squashing it would flatten the history and make the next sync conflict again.
    keep_history = args.no_squash or bool(sh("git", "rev-list", "--merges", f"{mb}..HEAD").split())
    if keep_history and len(commits) > 1:
        say(f"keeping {len(commits)} commits (branch contains a merge commit or --no-squash); not squashing")
        sh(*git_net("push", "--quiet", "origin", "HEAD"), check=False)
    elif len(commits) > 1:
        bodies = sh("git", "log", "--format=%B", f"{mb}..HEAD")
        trailers = sorted({ln.strip() for ln in bodies.splitlines() if re.match(r"^\s*Co-authored-by:", ln, re.I)})
        msg = args.message + ("\n\n" + "\n".join(trailers) if trailers else "")
        sh("git", "reset", "--soft", mb)
        sh("git", "commit", "--quiet", "-m", msg)
        say(f"squashed {len(commits)} commits → {head_sha()[:8]}")
        sh(*git_net("push", "--quiet", "--force-with-lease", "origin", "HEAD"), capture=False)
    elif commits:
        sh(*git_net("push", "--quiet", "origin", "HEAD"), check=False)
    mr = ensure_mr(cfg, b)
    title = format_mr_title(args.message.splitlines()[0], mr_title_style(cfg, target_for(cfg, b)))
    api(f"projects/:id/merge_requests/{mr['iid']}", "PUT",
        fields={"title": title})  # also drops a "Draft:" prefix (mr_draft: true, or older MRs)
    bump_rounds(b, reset=True)
    say(f"{C['g']}ready for review{C['x']} → {mr['web_url']}")
    if len(commits) > 1 and not keep_history:
        say("squash push started a fresh pipeline; run `agent-ci watch` to confirm it stays green.")
    if args.no_follow or not (cfg.get("postmerge") or {}).get("follow", True):
        return 0
    return cmd_follow(cfg, argparse.Namespace(mr=mr["iid"], merge_timeout=args.merge_timeout,
                                              merge_interval=args.merge_interval, timeout=3600,
                                              interval=20, tail=40))


def resolve_postmerge_pipeline(args, ref: str) -> int:
    if args.pipeline:
        return int(args.pipeline)
    if args.mr:
        mr = api(f"projects/:id/merge_requests/{args.mr}")
        if mr.get("state") != "merged":
            fail(f"MR !{args.mr} is {mr.get('state')}, not merged yet.", 1)
        sha = mr.get("merge_commit_sha") or mr.get("squash_commit_sha")
        # source=push: dispatch jobs create API pipelines on the same sha/ref, which aren't the merge's pipeline
        pls = api(f"projects/:id/pipelines?sha={sha}&ref={urllib.parse.quote(ref, safe='')}&source=push"
                  f"&order_by=id&sort=desc&per_page=5") if sha else []
    else:
        pls = api(f"projects/:id/pipelines?ref={urllib.parse.quote(ref, safe='')}&source=push&order_by=id&sort=desc&per_page=1")
    if not pls:
        fail(f"no pipeline found on {ref}; pass --pipeline ID.", 3)
    return int(pls[0]["id"])


def merged_pipeline(mr: dict, appear_timeout: int = 600) -> int | None:
    """The push pipeline GitLab starts on the target branch for a merged MR's commit (waits for it to appear)."""
    sha = mr.get("merge_commit_sha") or mr.get("squash_commit_sha") or mr.get("sha")
    ref = urllib.parse.quote(mr["target_branch"], safe="")
    deadline = time.time() + appear_timeout
    while True:
        pls = api(f"projects/:id/pipelines?sha={sha}&ref={ref}&source=push&order_by=id&sort=desc&per_page=5")
        if pls:
            return int(pls[0]["id"])
        if time.time() > deadline:
            return None
        time.sleep(10)


def cmd_follow(cfg: dict, args) -> int:
    """Read-only. Wait until the MR is merged, then run postmerge on the branch it merged into."""
    ensure_auth()
    iid = args.mr
    if not iid:
        mr = find_mr(branch())
        if not mr:
            fail("no open MR for this branch; pass --mr IID.", 3)
        iid = mr["iid"]
    say(f"following MR !{iid}: waiting for it to be merged (read-only; Ctrl-C stops only the watch)")
    deadline = time.time() + args.merge_timeout
    while True:
        mr = api(f"projects/:id/merge_requests/{iid}")
        if mr["state"] == "merged":
            break
        if mr["state"] == "closed":
            say(f"{C['y']}MR !{iid} was closed without merging; nothing to follow.{C['x']}")
            return 3
        if time.time() > deadline:
            say(f"{C['y']}MR !{iid} not merged after {args.merge_timeout}s; run `agent-ci follow --mr {iid}` "
                f"later.{C['x']}")
            return 4
        time.sleep(args.merge_interval)
    target = mr["target_branch"]
    say(f"MR !{iid} merged into {target}; locating its pipeline")
    pid = merged_pipeline(mr)
    if pid is None:
        say(f"{C['y']}no push pipeline appeared on {target} for the merge commit; nothing to diagnose.{C['x']}")
        return 3
    return cmd_postmerge(cfg, argparse.Namespace(ref=target, pipeline=pid, mr=None, note=None,
                                                 timeout=args.timeout, interval=args.interval, tail=args.tail))


def cmd_postmerge(cfg: dict, args) -> int:
    """Read-only. Never creates, retries or plays anything: only GETs pipelines, jobs and traces."""
    ensure_auth()
    pm = cfg.get("postmerge") or {}
    ref = args.ref or pm.get("ref", "staging")
    limit = int(pm.get("max_rounds", 3))
    if args.note:
        sig = add_attempt(args.note[0], args.note[1])
        say(f"logged attempt for: {sig}")
        return 0
    pid = resolve_postmerge_pipeline(args, ref)
    pl = api(f"projects/:id/pipelines/{pid}")
    if pl["ref"] != ref:
        fail(f"pipeline {pid} is on {pl['ref']}, not {ref}; refusing (pass --ref {pl['ref']} if intended).")
    say(f"post-merge pipeline {pid} on {ref} @ {pl['sha'][:8]} {pl['web_url']}")
    tree_cache: dict[int, dict] = {}
    deadline, last = time.time() + args.timeout, ""
    while True:
        pl = api(f"projects/:id/pipelines/{pid}")
        last = print_tree_if_changed(PipelineTree(pl, tree_cache), last)
        if pl["status"] in TERMINAL:
            break
        if time.time() > deadline:
            say(f"{C['y']}timed out after {args.timeout}s (pipeline still {pl['status']}){C['x']}")
            return 4
        time.sleep(args.interval)
    if pl["status"] == "success":
        save_incidents({})
        say(f"{C['g']}{C['b']}{ref} pipeline green{C['x']} ✓ (open incidents cleared)")
        return 0
    if pl["status"] != "failed":
        say(f"{C['y']}pipeline ended {pl['status']}; nothing to diagnose.{C['x']}")
        return 3
    say(f"{C['r']}{C['b']}failed{C['x']}")
    records: list[dict] = []
    print_failures(pid, ":id", args.tail, records=records)
    roots = [r for r in records if not r["wrapper"]] or records
    over = False
    print(f"\n{C['b']}Root-cause incidents{C['x']}")
    for sig in dict.fromkeys(r["signature"] for r in roots):
        entry = record_incident(sig, pid)
        hints = {r.get("hint") for r in roots if r["signature"] == sig}
        label = ("   (CI variable reached the job unexpanded)" if "unexpanded" in hints
                 else "   (looks like infra/IAM/state)" if "infra" in hints else "")
        print(f"- [{entry['count']}/{limit}] {sig}{label}")
        for a in entry["attempts"]:
            print(f"    tried {a['ts']}: {a['note']}")
        if "unexpanded" in hints:
            print("    → a literal `$NAME` means the variable was unset where it was forwarded: check trigger "
                  "`variables: X: $X` entries and the caller that creates the pipeline (it must set X).")
        elif "infra" in hints:
            print("    → gather READ-ONLY GCP context (IAM bindings, service-account policy, Cloud Run/Cloud Build logs, "
                  "terraform state/outputs) before proposing a change; never apply.")
        if entry["count"] >= limit:
            over = True
            print(f"    {C['y']}STOP: this signature has failed in {entry['count']} {ref} pipelines. "
                  f"Summarize for the user; don't open another fix MR for it unasked.{C['x']}")
    if not over:
        base = args.ref or pm.get("ref", "staging")
        print(f"\nnext: agent-ci start <topic> --base {base}  → fix → agent-ci cycle → agent-ci finish; "
              f"then: agent-ci postmerge --note \"<signature part>\" \"<what you changed>\"")
    return 5 if over else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="agent-ci", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("topic")
    s.add_argument("--base", help="branch from and open the MR against this branch (must be in mr_targets)")
    for name in ("push", "cycle"):
        p = sub.add_parser(name)
        p.add_argument("--no-check", action="store_true", help="skip local-check")
        p.add_argument("--force", action="store_true", help="force-with-lease push (agent branches only)")
    for name in ("watch", "cycle"):
        p = sub.choices[name] if name in sub.choices else sub.add_parser(name)
        p.add_argument("--timeout", type=int, default=1800)
        p.add_argument("--interval", type=int, default=15)
        p.add_argument("--appear-timeout", type=int, default=90, help="seconds to wait for a pipeline to be created")
        p.add_argument("--tail", type=int, default=60)
        if name == "watch":
            p.add_argument("--pipeline", type=int, help="watch this exact pipeline ID")
            p.add_argument("--stage0", action="store_true", help="require a plan-only stage-0 job")
    f = sub.add_parser("failures"); f.add_argument("--pipeline", type=int); f.add_argument("--tail", type=int, default=60)
    sub.add_parser("status")
    pm = sub.add_parser("postmerge", help="read-only: diagnose the pipeline on the merged ref (default staging)")
    pm.add_argument("--ref")
    pm.add_argument("--pipeline", type=int, help="specific pipeline id on the ref")
    pm.add_argument("--mr", type=int, help="use the pipeline for this merged MR's merge commit")
    pm.add_argument("--note", nargs=2, metavar=("SIG_PART", "TEXT"), help="log what you tried for an incident")
    pm.add_argument("--timeout", type=int, default=3600)
    pm.add_argument("--interval", type=int, default=20)
    pm.add_argument("--tail", type=int, default=40)
    fin = sub.add_parser("finish"); fin.add_argument("-m", "--message", required=True); fin.add_argument("--force", action="store_true")
    fin.add_argument("--no-follow", action="store_true", help="return after marking ready instead of following the merge")
    fin.add_argument("--no-squash", action="store_true",
                     help="keep the branch's commits (automatic when the branch contains a merge commit)")
    fol = sub.add_parser("follow", help="read-only: wait for the MR to merge, then run postmerge on its target")
    fol.add_argument("--mr", type=int, help="MR iid (default: this branch's open MR)")
    fol.add_argument("--timeout", type=int, default=3600, help="seconds to wait for the merged pipeline")
    fol.add_argument("--interval", type=int, default=20)
    fol.add_argument("--tail", type=int, default=40)
    for p in (fin, fol):
        p.add_argument("--merge-timeout", type=int, default=7 * 24 * 3600, help="seconds to wait for the merge")
        p.add_argument("--merge-interval", type=int, default=60)
    stage0 = sub.add_parser("stage0-plan", help="preview or trigger a protected-main stage-0 Terraform plan")
    stage0.add_argument("--execute", action="store_true", help="trigger exactly one plan-only pipeline")
    sub.add_parser("check", add_help=False)
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        return 0 if run_local_check(sys.argv[2:], load_config()) else 1
    args = ap.parse_args()

    os.chdir(repo_root())
    cfg = load_config()
    if args.cmd != "start" and subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode:
        fail("repository has no commits yet — make an initial commit on the default branch first.")
    return {"start": cmd_start, "push": cmd_push, "cycle": cmd_cycle, "watch": cmd_watch,
            "failures": cmd_failures, "status": cmd_status, "finish": cmd_finish,
            "stage0-plan": cmd_stage0_plan, "postmerge": cmd_postmerge, "follow": cmd_follow}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
