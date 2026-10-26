---
name: "gitlab-ci-loop"
description: Autonomous GitLab CI iteration loop. Use when working in a GitLab-hosted repo and the user wants the agent to push changes, run/watch GitLab pipelines, read failed job logs and fix them until green, or when asked to "set up the gitlab ci loop / agent ci" in a new or blank repository, or to diagnose a failed pipeline on staging/main after an MR was merged. Provides the `agent-ci` CLI (start, check, cycle, watch, failures, status, finish, postmerge) built on glab.
---

# GitLab CI loop

Lets you (the agent) close the edit → CI → fix loop without the user copying pipeline logs back and forth.
Scripts live in this skill folder: `~/.claude/skills/gitlab-ci-loop/scripts/`.
Each repo only has `.agent-ci.yml` (config), a managed block in `AGENTS.md` and `.agent-ci/` in `.gitignore`.

## 1. Setup (once per repo)

Run this if `.agent-ci.yml` is missing or the user asks to set up the loop:

1. Ask the user which branch agent MRs should target (the integration branch) if it isn't obviously the default branch.
2. Run:
   ```bash
   bash ~/.claude/skills/gitlab-ci-loop/scripts/bootstrap.sh --integration <branch> [--install-glab] [--starter-ci]
   ```
   - `--install-glab` installs glab (Homebrew, or the checksum-verified release binary into `~/.local/bin`).
   - `--starter-ci` adds a minimal `.gitlab-ci.yml` **only** when the repo has none.
3. If glab isn't authenticated, ask the user to run `glab auth login` themselves. Never handle their token.
4. Review the generated `.agent-ci.yml` (it's derived from the validation-stage jobs in `.gitlab-ci.yml` and its includes):
   - fix `# TODO` entries
   - make sure `paths` globs and `run` commands work locally
   - use `skip_local` for jobs that need CI-only services
   - run `agent-ci check --list`, then `agent-ci check --all` to confirm
5. Tell the user which files to commit (`.agent-ci.yml`, `AGENTS.md`, `.gitignore`). Don't commit on your own unless they ask.

If `agent-ci` isn't on PATH, call `~/.claude/skills/gitlab-ci-loop/scripts/agent-ci.py` directly.

**Auth notes**
- API calls go through glab's token, so MRs are authored by whoever owns that token. A project access token shows up as a bot.
- Git push and fetch use the user's own git credentials. If `origin` is HTTPS (which can't prompt from an agent shell) and `ssh -T git@<host>` works, `agent-ci` routes git over SSH per command. The remote and global config are left untouched. Set `AGENT_CI_GIT_TRANSPORT=https` to disable this.

## 2. The loop

```bash
agent-ci start <topic>          # branch <prefix><topic> from origin/<integration>
# …edit…
agent-ci check                  # only the checks matching changed files; fix until green
git add -A && git commit -m "…"
agent-ci cycle                  # check → push → MR → watch → failed-job log tails
# red → read the printed logs, fix the root cause, commit, cycle again
agent-ci finish -m "feat: …"    # green → squash, set the final MR title, then follow the merge
```

- When the work is green, run `finish` **as a background command**: it marks the MR ready, then keeps
  watching (read-only) until the user merges, and runs `postmerge` on the branch the MR merged into
  (section 2b). Report the MR URL from its early output right away. The user reviews and merges. When the
  background command completes, report the post-merge result; if it's red, continue with 2b.
  A branch containing a merge commit (e.g. syncing `staging` into the integration branch) is not squashed,
  so the merge stays in history; `--no-squash` keeps commits on any branch.
  `--no-follow` returns right after marking ready; `postmerge.follow: false` turns following off for a repo;
  `agent-ci follow [--mr IID]` follows an MR that is already open.
  If the user merges while `finish` is still running, `finish` finds the merged MR and goes to `postmerge`.
  It does not try to open a new MR, and a merge is never an error exit.
- `finish`/`follow` exit codes after the merge are `postmerge`'s (below); 3 also means the MR was closed
  without merging, and 4 means it wasn't merged within `--merge-timeout` (default 7 days).
- `cycle` exit codes:

| Code | Meaning | What to do |
|---|---|---|
| 0 | green | finish |
| 1 | red | fix and cycle again |
| 2 | precondition refused: uncommitted changes, a protected or unprefixed branch, no `origin`, or glab not authenticated | read the message; for a dirty tree see below |
| 3 | no pipeline, or only manual jobs (no automatic job rules matched) | tell the user; local checks are the only signal; never start manual jobs unasked |
| 4 | timeout | run `agent-ci watch` again or report |
| 5 | max red rounds reached | **stop** and summarize the failures for the user |

- **Red only on the runner, and the log says nothing.** The process is silent, or the error doesn't name a
  cause. The next push adds instrumentation so the failure describes itself, not a guessed fix. For example,
  a stack dump on timeout (`PYTHONFAULTHANDLER=1`, and the harness sends SIGABRT), or the child's stderr in
  the assertion message. Each remote round costs a full pipeline, so spend it on evidence.
- **`agent-ci check` runs only the checks whose `paths` match the changed files.** A changed file that no
  check maps, or a new test directory with no check, is not run locally. When you cite `agent-ci check` as
  evidence for a change that adds a test or edits CI files, confirm that its output lists the check covering
  that file. Otherwise run the test directly, or add the mapping.
- Read the exit code from `agent-ci` itself. Piping it through `| tail` reports `tail`'s 0, so a refusal looks
  like a finished run; use `set -o pipefail` or read the output.
- **Dirty tree the user wants left alone.** `cycle` pushes only committed work and refuses (code 2) while
  tracked files are modified. If the user has decided not to commit those edits, don't commit or stash them.
  Run the cycle from a clean worktree of the same branch, then remove it:
  ```bash
  git worktree add -f .claude/worktrees/ci-<topic> <branch>
  (cd .claude/worktrees/ci-<topic> && agent-ci cycle)
  git worktree remove .claude/worktrees/ci-<topic>
  ```
- Keep it lean:
  - batch related fixes into one commit per round
  - don't push to "see what happens" when `agent-ci check` can tell you locally
  - use `agent-ci failures --tail 200` only when 60 lines isn't enough
- Other commands: `agent-ci status` gives an overview, and `agent-ci watch` resumes watching an existing pipeline.

## 2a. Protected-main FAST stage-0 plan (opt-in per repo)

This separate path is available only if `.agent-ci.yml` has:

```yaml
stage0_plan:
  project_path: "group/project"
  ref: "main"
```

Use only after the operator verifies the FAST bootstrap, remote-state migration,
GitLab WIF and bounded-auth prerequisites in the stage-0 runbook. The CLI
requires protected main and checks that the GitLab project matches the preset.
The API request always sends **exactly** `ref=main` and
`PIPELINE_TYPE=landing-zone`, `LANDING_ZONE_STAGE=0-org-setup`,
`APPLY_MODE=plan`; there is no flag for apply. `glab` reads auth from its
keyring, not CLI args. Creating a pipeline on protected main requires a
GitLab account permitted to run pipelines there; a Developer-scoped project
token may read logs but will be rejected at creation. Do not weaken main
protection to bypass this: use an authorized account, or have that operator
create the exact plan-only pipeline and share its ID.

```bash
agent-ci stage0-plan                  # preview ref, current remote SHA and vars
agent-ci stage0-plan --execute        # trigger one plan-only API pipeline
agent-ci watch --pipeline <ID> --stage0  # wait on that exact run and verify the stage-0 job
agent-ci failures --pipeline <ID>     # failed job log tails when needed
```

Review the Terraform plan totals, raw plan artifact (in GitLab's restricted
UI, not chat) and IAM/org changes. A green CI run is **not** apply approval.
If the stage-0 job does not exist or is skipped, don't call the result green.
If GitLab returns 403 for pipeline variables, the watcher requires the job
trace to confirm it entered and completed `mode: plan` before reporting a
reviewable plan. If the plan JSON artifact is missing, the watcher reports
incomplete review rather than success. Never run a manual job or apply to
troubleshoot it.

If a code fix is needed, create a **new** `fix/stage0-<cause>` branch for
each distinct failure, in a separate worktree based on current remote `main`.
Leave the patch for the user to inspect, commit, push and promote. A main-ref
pipeline cannot test local or unmerged fixes: wait for the user to confirm
promotion before rerunning the plan. Stop for destructive changes or IAM
failures that need operator action, and after five unsuccessful rounds.

## 2b. After the merge: diagnose staging (read-only)

Fanout stages (stage-cohort, transform, mlops, rollout …) only run on the merged ref, so an MR can be green
and `staging` still go red. This runs **automatically** at the end of `finish` (via `follow`), on whatever
branch the MR merged into. Run it by hand when the user says an MR was merged outside that flow, or asks
why staging failed:

```bash
agent-ci postmerge --mr <iid>            # the MR's target branch; no flag: latest push pipeline on postmerge.ref (default staging)
```

- It only does GETs. It never creates, retries or plays pipelines or jobs.
- It waits for the pipeline, then prints failed job logs, **following pipelines whose id appears in a failed
  job's log** (the `dispatch-*`/`trigger-tenant-*` scripts create API pipelines, which are not bridges).
- Failures are grouped by **root-cause signature** (job name + last real error line, ids and numbers
  normalized). Wrapper jobs that only say "fanout pipeline N failed" are not counted as causes.
- Read the printed **attempt log** for the signature before changing anything. Do not repeat a variant that is
  already listed.
- Exit codes: 0 green · 1 red (fix it) · 3 nothing to diagnose · 4 timeout ·
  5 a signature has failed in `postmerge.max_rounds` staging pipelines → **stop and summarize for the user**.

Fixing it:

```bash
agent-ci start <topic> --base staging    # branch from origin/staging; the MR targets staging
# …fix, agent-ci check, commit…
agent-ci cycle                           # same loop as before; the MR is opened against staging
agent-ci finish -m "fix: …"              # user reviews and merges
agent-ci postmerge --note "<signature part>" "<what you changed and why>"   # log the attempt
```

- `--base` only accepts branches listed in `mr_targets` (config). The agent never pushes to `staging`/`main`.
  The branch records its target, so `check`, `cycle` and the MR all use it, even when the target's committed
  `.agent-ci.yml` predates `mr_targets`. If the repo's merge policy rejects the source branch name (an
  `enforce-branch-policy`-style job), say so and ask; don't rename branches to slip past it.
- **Unexpanded-variable signatures** (marked "CI variable reached the job unexpanded"; a literal `'$NAME'` in
  the error): the variable was unset where a trigger forwarded it as `X: $X`. Fix the caller that creates the
  pipeline, or the bridge's forwarding, not the consumer.
- **Red on unchanged code right after CI variables were created or changed.** First compare the new keys
  with the failing test's environment. Test fixtures that copy `os.environ` inherit every project variable.
- **Infra signatures** (marked "looks like infra/IAM/state"; permission denied, WIF, state/outputs):
  gather read-only GCP context first (`gcloud … describe/list/get-iam-policy`, `gcloud logging read`,
  `terraform state list/show`, `terraform output`) and propose the change. **Do not apply** IAM, Terraform or
  deploy changes, even though the credentials may allow it, unless the user explicitly asks.
- Config:

```yaml
mr_targets: [staging]            # extra branches agent MRs may target (add main only if intended)
postmerge: {ref: staging, max_rounds: 3, follow: true}   # follow: finish waits for the merge, then postmerge
```

**Watching and linting.** `cycle`/`watch` wait for every pipeline on the commit (push *and* merge-request
pipelines) and report the worst one. While waiting, `watch` and `postmerge` print a live tree whenever it
changes: bridge children, plus the API pipelines that `dispatch-<plan hash>-<target id>` jobs start (matched on
their `RELEASE_PLAN_ID`/`RELEASE_TARGET_ID`), up to 3 levels deep. Only GET requests. Changed CI files are linted one by one. Errors that a standalone
include fragment can't avoid (an unresolved `include: local`, or a stage defined in the root file) are only
warnings, because the pipeline validates them.

**Guards that read a job trace.** A guard that watches a job trace for a line (for example, cancel an apply
when the replan differs) must strip GitLab's per-line timestamp and stream prefix, and ANSI colour codes,
before matching. Test it on a real captured trace line. A real line looks like
`2026-10-20T19:36:01.296042Z 01O \e[1mPlan:\e[0m 52 to add, 0 to change, 0 to destroy.`
A plan-then-apply job leaves only seconds to cancel, so a check inside the pipeline is safer than an outside watcher.

**MR titles.** `mr_title_style: auto | bracketed | plain` (default `auto`). Conventional subjects become
`[type(scope)]: subject` (bracketed) or `type(scope): subject` (plain). `auto` follows the majority of the
last 20 merged MRs into the same target. Write commit subjects and `finish -m` as plain conventional
messages; the title is formatted for you.

## 3. Guardrails (non-negotiable)

- Never push to protected branches or the integration branch. Only force-push `<prefix>*` branches, and only through `agent-ci` (`--force-with-lease`).
- Never trigger deploy/apply/rollout/onboard/offboard pipelines, `terraform apply`, or anything that changes cloud resources, unless the user explicitly asks. Plans and dry-runs are fine.
- `agent-ci postmerge` is read-only. Fix MRs for staging/main are opened only via `start --base <branch>` with the branch in `mr_targets`.
- Never merge MRs. Never commit secrets or `.agent-ci/`.
- Don't weaken CI rules or tests to get a green pipeline. Fix the code, or explain why a check is wrong.

## `.agent-ci.yml` reference

```yaml
integration_branch: dev3
branch_prefix: agent/
protected_branches: [main, staging, dev3]
max_ci_rounds: 5
mr_title_style: auto         # auto | bracketed ("[fix(x)]: …") | plain ("fix(x): …")
mr_draft: false              # MRs open ready for review; true opens them as drafts until finish
python_venv: true            # checks run inside .agent-ci/venv-<version> (setup pip installs land there)
python_version: "3.11"       # match the CI image; uv fetches it if missing
setup: []                    # global one-time setup (cached; the key is listed below the block)
checks:
  - name: pytest-foo
    paths: ["pipelines/foo/src/**"]   # or `always: true`
    env: {PIPELINE_DIR: pipelines/foo}
    setup: ["cd pipelines/foo && pip install -r src/requirements.txt pytest"]
    run: ["cd $PIPELINE_DIR", "python -m pytest tests -q"]
    skip_local: "needs postgres service"   # optional: listed but only runs in CI
    venv: own                # optional: isolated venv (e.g. jobs on apache/airflow images)
```

Setup is cached per check, and first runs of heavy stacks (Airflow) take a few minutes.
The cache key covers the setup commands, the venv path, the values of the check's `env` keys,
and the content of every file a pip command reads with `-r`, `--requirement`, `-c` or `--constraint`.
A leading `cd <dir> &&` sets where such a file is looked up, and files that a requirements file includes count too.
A missing file counts as "missing", so creating it later re-runs setup.
Other inputs are not in the key (for example `pyproject.toml` read by `pip install .`, or a lock file read by another tool).
When one of those changes, run `agent-ci check --resetup`. It passes through to `local-check.py` and forces setup to re-run.
Failed setups re-run next time.
If a check fails locally on a version conflict, compare with the CI image before blaming the code.
The same conflict usually fails in CI too.

Re-running `bootstrap.sh` is safe. `--force-config` regenerates the config after big CI changes.
