# Fable First Run — Efficiency, Agent Board, DevOps Security Review

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spend one Claude Fable 5.1 run on three outcomes: (1) measurably cheaper, faster, less-interrupted Claude Code sessions; (2) a faster, version-controlled, more reliable Agent Board; (3) an evidence-backed security review of the master-gcp-repo DevOps posture with a ranked remediation roadmap and the first fixes on branches.

**Architecture:** An Opus lead session (started in `~/agent-board` via `dev` / `claude-orchestrator`, which pins `--model opus`) orchestrates three workstreams. Frontier tasks (threat model, triage, design, final synthesis) are dispatched to Fable teammates/subagents; mechanical and standard work goes to Haiku/Sonnet, all per the user-level routing file `~/.claude/superpowers/model-routing.json` (`mechanical→haiku`, `standard→sonnet`, `frontier→fable`, `enforceEffort: true`). A frontier dispatch must pass `model: "fable"` (or the task's `model` pin) or the routing gate blocks it. Every workstream starts by measuring a baseline and ends by re-measuring it, so "improved" is a number, not a claim.

**Tech Stack:** Claude Code (hooks, settings, skills, subagents), zsh + Python stdlib (tmux-ctl, tmux-dash), GitLab CI + glab, Terraform (Cloud Foundation Fabric FAST), GCP WIF/IAM, Python services on Cloud Run.

**Spec:** this document. Inputs are the three read-only inventories gathered 2026-10-16 by the planning session (summarised in "Ground truth" below). No separate spec file exists.

## Global Constraints

- **Nothing reaches GCP or GitLab state.** No `terraform apply/destroy`, no `gcloud ... create|update|delete|add-iam-policy-binding`, no `glab` writes (MR create, variable set, settings change), no `git push`. Read-only `gcloud ... list|describe|get-iam-policy` and `glab api` GETs only, and only in Task 16, which is a user gate.
- **Branches, not pushes.** master-gcp-repo changes go on local branches named `agent/fable-<topic>` cut from `dev3` (repo flow: `agent/*` → MR into `dev3` → `staging` → `main`, see `~/master-gcp-repo/CLAUDE.md` "Branches and commits"). The user pushes and opens MRs. agent-board changes go on local branches (`feat/fable-<topic>`, `fix/fable-<topic>`) built in a git worktree, never on the live `main` checkout; agent-board has no remote, and merging into `main` is a Task 18 decision for the user.
- **No superpowers material in master-gcp-repo.** Plans, hook runners and other superpowers files live in `~/agent-board` (user decision, MR !287 removed them from master-gcp-repo). Repo-level Claude config in master-gcp-repo is limited to `CLAUDE.md` and `.claude/settings*.json`.
- **Snapshot before you edit anything outside a git repo.** The Agent Board, the `dev` toolkit, `orchestrator.md`, `worker.md` and four hooks already live in `~/agent-board` (symlinked live). `~/.claude/{CLAUDE.md,settings.json,agents/,skills/<own>}` and the non-symlinked hooks are still unversioned; Task 1 puts them under git *before* any other task edits them.
- **Never kill processes by name or pattern** (`pkill`/`killall`); stop the board with `tmux-dash stop` or by a PID you looked up.
- **The user's own decisions stay the user's.** The task-observer mandate in `~/.claude/CLAUDE.md` and the superpowers plugin are deliberate choices. Measure their cost and write a decision memo (Task 6); do not remove them.
- **Security findings stay private.** The findings report lives in `~/.claude/fable-run/2026-10-16/security/` and is published only as a private Artifact. It is never committed to the repo. Fix branches reference finding IDs, not exploit detail.
- **Worktree isolation.** A session started with `claude -w` cannot run git outside its worktree. agent-board and `~/.claude` work runs in sessions started in `~/agent-board` (or a worktree of it); master-gcp-repo work runs in master-gcp-repo worktrees (see Session topology).
- **The checked-out agent-board branch is what runs live.** `~/.local/bin/*`, `~/.local/share/{tmux-dash,tmux-tools}` and the linked `~/.claude` files point into `~/agent-board`. Keep `~/agent-board` on `main`; test board changes from the worktree (ephemeral port / scratch tmux server per `~/.claude/CLAUDE.md`), and restart the live board only for the explicit real-state checks.
- **Evidence over assertion.** Every "improved/fixed/vulnerable" claim cites a command output or file:line captured in this run.

**User decisions (already made):**
- "use fable for the first time specifically to improve efficiency in my usage of claude code, optimize agent board and perform a deep security review of master gcp repo dev ops posture"
- "I need a very indepth plan for it to execute"
- 2026-10-16 re-scope: plan and tasks live in `~/agent-board/docs/superpowers/plans/` ("there shouldn't be any superpowers code in master-gcp-repo; all of this should live in the agent-board repo").
- 2026-10-16 re-scope: Opus lead, Fable for frontier tasks (not a Fable lead).
- 2026-10-16 re-scope: Task 1 covers only what is still unversioned under `~/.claude`.
- Security work reads master-gcp-repo from `dev3`; fix branches are local `agent/fable-<topic>` from `dev3`; the user pushes.

---

## Why the plan is shaped this way (read once, then work)

**What Fable is good at, and where it isn't the right tool.** Claude Fable 5.1 costs $10/$50 per MTok (2.5× Opus 5.5, 5× Sonnet 5.5). Its biggest gains are long autonomous runs, code review/debugging, repo-history search, ambiguity, and parallel delegation. Anthropic's notes say two things that shape this plan:
1. **Over-prescriptive prompts reduce Fable's output quality.** The tasks below fix the *goal, constraints, files, acceptance criteria and verification*. They deliberately do not script every step for frontier tasks. Mechanical tasks are fully scripted because a Haiku worker will run them.
2. **Security-focused bug finding is not among Fable's measured gains, and cyber classifiers can decline security requests** (`stop_reason: refusal`). So the vulnerability *sweep* runs on Opus (claude-security plugin, Task 13). Fable does threat modelling, adversarial verification and the remediation design, where judgment matters most. If Fable declines a request, route that sub-task to Opus and note it in the run log. Don't rephrase to get around the classifier.

**Effort.** The lead is Opus at the session's effort. Frontier dispatches use `subagent_type: "general-purpose"`, `model: "fable"` and inherit the session effort (routing map `frontier → inherit`); Fable at moderate effort often beats older models at `xhigh`. Standard → `effort-medium` + `sonnet`; mechanical → `effort-low` + `haiku`.

**Cost control.** Fable's spend comes from its frontier tasks (the lead is Opus). Haiku (mechanical) and Sonnet (standard) do the reading-heavy work and return conclusions, not file dumps. Cap the run at roughly 6–8 hours of lead wall-clock; if the budget is tight, Tasks 10, 11 and 16 are the first to defer.

## Ground truth (from the 2026-10-16 inventories — re-verify before acting on any line)

**Changed since the inventories (verified 2026-10-16 afternoon):**
- `superpowers-hook.sh` now lives at `~/agent-board/claude/hooks/superpowers-hook.sh` and is registered at user level in `~/.claude/settings.json` (Stop ×2: `stop-revalidate-user-gates.sh`, `stop-wait-guard.sh`; PostToolUse `TaskUpdate`: `post-task-complete-revalidate.sh`). It still walks with `find` (line 26). master-gcp-repo has no `.claude/hooks/` any more; its `.claude/settings.json` holds only `env` and `permissions`.
- master-gcp-repo (`dev3`) has a root `CLAUDE.md` (43 lines, commit `b42cf24e`), and its project memory dir holds `MEMORY.md` + `master-gcp-repo-monorepo-only.md`.
- Board code: `~/agent-board/board/` (= `~/.local/share/tmux-dash`), toolkit tests `~/agent-board/tools/tests/` (= `~/.local/share/tmux-tools/tests`), CLI scripts `~/agent-board/bin/` (= `~/.local/bin/<script>` symlinks). Pre-repo copies kept as `~/.local/share/{tmux-dash,tmux-tools}.pre-repo-20261016`.
- `skillOverrides` is still only in master-gcp-repo's `.claude/settings.local.json`; `autoMode.environment` "Trusted repo" still names `~/.claude/jobs/318c9a50/tmp/teamtest`; the global allowlist is still `Bash(tmux-ctl:*)` only.
- Lines below that contradict these bullets are superseded by them.

**Claude Code setup**
- SessionStart injects ≈8.4K chars: superpowers `using-superpowers` ≈7,965 chars, re-injected after every `/compact`; task-observer hook ≈430 chars.
- task-observer is mandated three times: `~/.claude/CLAUDE.md`, the SessionStart hook, and its own skill description. Its SKILL.md is 44,715 chars (≈11K tokens) and loads in nearly every session.
- Project hooks call `.claude/hooks/superpowers-hook.sh`, which runs `find ~/.claude/plugins` and `find ~/Library/Application Support/Claude` on every Stop (×2 hooks) and every TaskUpdate.
- Three Stop hooks run per turn: `revise-claude-md-nudge.py` reads transcripts up to 33 MB and can block Stop once; `stop-revalidate-user-gates.sh`; `stop-wait-guard.sh`.
- The permission allowlist is effectively empty: global `Bash(tmux-ctl:*)` only.
- `skillOverrides` trims 16 synced skills, but only in master-gcp-repo's `settings.local.json`.
- GitLab MCP is configured twice: the plugin server and the claude.ai connector.
- `autoMode.environment` "Trusted repo" points at a stale test directory.
- master-gcp-repo has no CLAUDE.md, and its project memory directory is empty.
- Workers spawned by `tmux-ctl agent` set no model/effort, so they inherit `opus`.
- Usage: 75 transcripts, 230 MB; 11 files over 5 MB, all in master-gcp-repo.

**Agent Board**
- Code: `~/agent-board/board/` (server.py, index.html, activity/artifacts/relay/ideas/paneclass/dirs) and the CLI scripts in `~/agent-board/bin/`.
- In git (`~/agent-board`, no remote) since 2026-10-16.
- The running server (pid from `~/.local/state/tmux-dash/server.pid`) predates the Oct 16 code, so the `/api/runs|feed|log` routes probably 404, and `pollActivity` hides that.
- The page polls a chained loop every 2 s and rebuilds every card with `replaceChildren`. Artifacts are refetched in full and diffed with an O(n·m) LCS in the browser.
- Each tmux exec costs ≈0.5 s on this Mac (server.py:42 comment); every state build runs one `capture-pane` per pane.
- `summarize()` only parses pytest output, so unittest runs record empty summaries. `| tail` pipes hide exit codes because there is no pipefail.
- `runs-*.jsonl` is never trimmed and is re-read on every poll.
- Duplicated logic: the STATE path is computed in 4 places; shell/prompt regexes are duplicated across tmux-ctl and paneclass.py; a tmux.conf "New agent" binding bypasses `tmux-ctl agent`.
- Tests:
  - Python: `cd <agent-board checkout> && python3 -W error::ResourceWarning -m unittest discover -s board/tests`
  - zsh: `cd <agent-board checkout> && zsh tools/tests/run-all.zsh`
- Open items in `~/.claude/handoffs/2026-10-15-team-reliability.md`.

**DevOps security hotspots** (leads, not findings)
- `landing-zone/fast-bootstrap/identity.tf:67-71`: the planner SA's `workloadIdentityUser` is bound to `attribute.ref_type/branch`, i.e. any branch of the project.
- `ci/scripts/auth/gcp-wif-auth-org.sh:14` chooses the SA from `ORG_WIF_AUTH_REF`, which `ci/actions/validate/.gitlab-ci-branch-policy.yml:118` sets to the MR source branch.
- `DOCKER_TLS_CERTDIR: ""` (dind over plain tcp:2375) in `ci/actions/release/.gitlab-ci-release.yml:113`, `ci/actions/mlops/generators/mlops-generator.py:150` and `ci/actions/release/stage_enrollment_pipeline.py:114`.
- Images are unpinned (`python:3.11` ×34, `google/cloud-sdk:slim` ×14, `hashicorp/terraform:latest`). Terraform is curl-installed without a checksum. `.terraform.lock.hcl` is gitignored. FAST stages have no provider version pins.
- `requirements.txt` files are unpinned in bq-to-{ads,gsc,yt} and all 4 `tools/cloudrun-*`. No hash pinning anywhere.
- `GITLAB_TOKEN` is embedded via `git config url.insteadOf` in `ci/scripts/tf-utils/tf-plan.sh:6` (and apply/destroy). The tenant WIF script writes token/creds files into the job directory with no cleanup.
- `roles/owner` is granted to users in `landing-zone/fast/stages/2-project-factory-shared/datasets/config/projects/mougii-{prod,staging}-0.yaml`.
- `fast-bootstrap` uses local state. 7 `terraform.tfvars` files are committed.
- No security scanners exist in CI (no SAST, secret detection, IaC or dependency scanning). Locally only `glab` is installed.
- CODEOWNERS has a single owner for every path, which raises bus-factor and self-approval questions.
- Cloud Run routes that handle secrets: `tools/cloudrun-ingest-layer/routes/{secret_update,onboarding}.py`, `tools/cloudrun-ledger-layer/routes/config.py`.
- No `tags:` on any CI job, so everything runs on shared/default runners.

## Session topology

| Session | Start it in | Model / effort | Owns |
|---|---|---|---|
| **Lead** | `~/agent-board` (main checkout, *not* `-w`) via `dev` / `claude-orchestrator` | Opus 5.5 | Coordinates; runs Task 0 and the final whole-plan review; dispatches every other task by its `modelTier` |
| **Frontier teammates** | `~/agent-board` or a master-gcp-repo worktree, per task | Fable 5.1 (`model: "fable"`), effort inherited | Tasks 6, 7, 10 (design), 12, 15, 17, 18 |
| **Board** | a git worktree of `~/agent-board` on `feat/fable-board` | Sonnet 5.5 `medium`; Fable for Task 10 design only | Tasks 8–11 |
| **Security sweep / lenses** | master-gcp-repo worktree from `dev3` via `tmux-ctl agent fable-sec-sweep` | Opus 5.5 (task `model` pin), claude-security orchestrator | Tasks 13, 14 |
| **Repo fixes** | master-gcp-repo worktrees from `dev3` via `tmux-ctl agent fable-fix-<topic>` | Sonnet 5.5 `medium` | Task 17 fix branches |

All run notes go to `~/.claude/fable-run/2026-10-16/` (created in Task 0), which is the memory surface for this run: `run-log.md`, `metrics/`, `security/`, `decisions/`. It is never committed (security findings stay private).

---

### Task 0: Run kickoff, baselines and run log

**Goal:** Create the run directory and capture the baseline numbers every later task is measured against.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/run-log.md`
- Create: `~/.claude/fable-run/2026-10-16/metrics/baseline.json`
- Create: `~/.claude/fable-run/2026-10-16/metrics/measure.sh`

**Acceptance Criteria:**
- [ ] `baseline.json` holds:
  - `session_start_injection_chars`: sum of SessionStart hook stdout, measured by running each hook command.
  - `stop_hook_ms`: median of 5 timed runs of each Stop hook.
  - `taskupdate_hook_ms`
  - `bash_pretool_hook_ms`: kill-guard on a harmless command.
  - `permission_prompts_per_session`: count of `"type":"permission"`-style prompt events (or the closest marker present) in the 10 most recent master-gcp-repo transcripts, divided by 10. State the marker used.
  - `board_state_ms`: median of 10 `curl -s -o /dev/null -w '%{time_total}' http://127.0.0.1:7700/api/state` calls with the token.
  - `board_api_runs_status`: HTTP code of `/api/runs`.
  - `tmux_execs_per_state_build`: count of `capture-pane` lines in one build (instrument with `TMUX_DASH_DEBUG=1` or count panes).
- [ ] `measure.sh` regenerates the same JSON shape, so Task 18 can diff it.
- [ ] `run-log.md` lists the session topology, today's date and the task-observer review offer outcome.

**Verify:** `bash ~/.claude/fable-run/2026-10-16/metrics/measure.sh | python3 -m json.tool` → valid JSON with every key above non-null.

**Steps:**
- [ ] Record the lead's task-observer Session Start outcome in the run log (the lead already ran it; last review 2026-10-16, so no review is due).
- [ ] Read the board token from `~/.local/state/tmux-dash/` (see how `~/agent-board/bin/tmux-dash url` builds the URL) before curling.
- [ ] Write `measure.sh` so it times each hook command registered in `~/.claude/settings.json` (this now includes the three `superpowers-hook.sh` entries) and in `~/master-gcp-repo/.claude/settings.json` if it registers any. Parse the commands from the JSON; don't hardcode them. Hooks read JSON on stdin: feed `{"session_id":"measure","transcript_path":"/dev/null","cwd":"'"$HOME"'/master-gcp-repo"}`.
- [ ] Commit nothing: the run dir stays outside every repo.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/run-log.md", "~/.claude/fable-run/2026-10-16/metrics/baseline.json", "~/.claude/fable-run/2026-10-16/metrics/measure.sh"], "verifyCommand": "bash ~/.claude/fable-run/2026-10-16/metrics/measure.sh | python3 -m json.tool", "acceptanceCriteria": ["baseline.json has every listed key non-null", "measure.sh reproduces the JSON shape", "run-log.md records topology and review offer"], "modelTier": "standard"}
```

### Task 1: Put the remaining unversioned `~/.claude` config under git

**Goal:** Every `~/.claude` file this run will edit is tracked in `~/agent-board` with a clean baseline commit, so each change is a reviewable diff and can be reverted. (The board, the `dev` toolkit, `orchestrator.md`, `worker.md` and four hooks are already there.)

**Files:**
- Create (in a worktree of `~/agent-board`, branch `feat/claude-config-home`): `claude/CLAUDE.md`, `claude/settings.json`, `claude/agents/`, `claude/hooks/<each regular, non-backup file in ~/.claude/hooks>` (today: `revise-claude-md-nudge.py`, `context-size-guard.sh`, `task-observer-review.sh`, `task-observer-session-start.sh`, `claude-md-monthly-report.sh`, `tests/`), `claude/skills/<own skills>` (`gitlab-ci-loop`, `tmux-orchestrator`, `requesting-code-review-extras`, `test-driven-development-extras`, `writing-plans-extras`, `writing-for-agents`, `fix-merge-conflicts`, `context-canary`, `retro`)
- Create: `bin/claude-config-link` (symlinks live paths into the repo, `--dry-run` prints actions) and `bin/claude-config-sync` (copies live `settings.json` → repo, for files that must stay regular files)
- Modify: `README.md` (path-mapping table)
- Do **not** track: `~/.claude/skills/synced/` (harness-managed), the `handoff` skill symlink (points into `~/.agents`), `*.bak*` / `*.pre-repo-*` files, or anything else under `~/.claude` (sessions, caches, secrets).

**Acceptance Criteria:**
- [ ] `git -C ~/agent-board log --oneline main..feat/claude-config-home` shows the baseline commit(s); `.bak*`/`.pre-repo-*` are untracked (add them to `.gitignore`).
- [ ] `diff -r` between each tracked copy and its live original is empty at commit time.
- [ ] No credential is committed: `git -C <worktree> grep -InE '(token|secret|password|api[_-]?key)\s*[:=]'` reviewed by hand, hits excluded and noted in the run log.
- [ ] `settings.json` decision recorded in the run log with evidence: test in a scratch `CLAUDE_CONFIG_DIR` whether Claude Code keeps a symlinked `settings.json` a symlink after it writes the file (e.g. a `/config` change via `claude -p`). If it replaces the link, settings.json stays a regular file tracked through `claude-config-sync`; otherwise it is linked like the rest.
- [ ] `claude-config-link --dry-run` prints one action per tracked path. The live swap (backups `F.bak-YYYYMMDD` first, per `~/.claude/CLAUDE.md`) runs only after the branch is merged into `main`; both are Task 18 decisions, except that the lead may ask the user for an early merge+link so Tasks 2–5 edit tracked files.
- [ ] `zsh tools/tests/run-all.zsh` and the board suite pass in the worktree.

**Verify:** `git -C <worktree> status --short | wc -l` → `0`; `<worktree>/bin/claude-config-link --dry-run | wc -l` → ≥ number of tracked top-level paths; `for f in CLAUDE.md agents hooks/revise-claude-md-nudge.py; do diff -r ~/.claude/$f <worktree>/claude/$f && echo same; done` → `same` ×3.

**Steps:**
- [ ] Create the worktree: `git -C ~/agent-board worktree add ~/agent-board/.claude/worktrees/claude-config-home -b feat/claude-config-home main`.
- [ ] Copy (don't move) each listed path; commit `chore(claude): track remaining ~/.claude config` ending with the attribution trailer your harness specifies.
- [ ] Write `claude-config-link` after the pattern used for the existing links (README table): for each path, refuse if live is already a link elsewhere, back up, `ln -s`. Add a zsh test under `tools/tests/` that runs it with `HOME` pointed at a scratch dir.
- [ ] Do not run the live swap.

```json:metadata
{"files": ["~/agent-board/claude/", "~/agent-board/bin/claude-config-link", "~/agent-board/bin/claude-config-sync", "~/agent-board/README.md", "~/agent-board/.gitignore"], "verifyCommand": "git -C ~/agent-board/.claude/worktrees/claude-config-home status --short | wc -l", "acceptanceCriteria": ["baseline commit on feat/claude-config-home", ".bak files untracked", "tracked copies identical to live", "no credentials committed", "settings.json symlink behaviour tested and decided", "link script dry-run only", "both suites pass"], "modelTier": "standard"}
```

---

## Workstream A — Claude Code efficiency

### Task 2: Remove hook filesystem walks and measure Stop-hook overhead

**Goal:** The user-level superpowers hook runner resolves the plugin path without `find`, and Stop/TaskUpdate hook latency drops measurably.

**Files:**
- Modify: `~/agent-board/claude/hooks/superpowers-hook.sh` (in an agent-board worktree, branch `fix/fable-hook-find`)
- Modify: `~/.claude/settings.json` (`env` block) — tracked by Task 1
- Test: `~/agent-board/tools/tests/test_superpowers_hook.zsh`

**Acceptance Criteria:**
- [ ] `superpowers-hook.sh` uses `$SUPERPOWERS_PLUGIN_ROOT` when it is set and the script exists there. It falls back to the current `find` otherwise, so plugin upgrades don't break it.
- [ ] Choose how `SUPERPOWERS_PLUGIN_ROOT` is set: either by a resolution step that globs `~/.claude/plugins/cache/superpowers-extended-cc-marketplace/superpowers-extended-cc/*/` and takes the highest version, or by `CLAUDE_PLUGIN_ROOT` if the harness exposes it to user-level hooks. Check that by echoing env in a test hook. Don't hardcode `6.5.3-dev`.
- [ ] `stop_hook_ms` and `taskupdate_hook_ms` from `measure.sh` drop versus baseline. Record both numbers in the run log.

**Verify:** `bash ~/.claude/fable-run/2026-10-16/metrics/measure.sh | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["stop_hook_ms"], d["taskupdate_hook_ms"])'` → both lower than in `baseline.json`.

**Steps:**
- [ ] Write the zsh test first (`tools/tests/test_superpowers_hook.zsh`, picked up by `run-all.zsh`) that asserts: with the env var set, no `find` runs (shim `find` on `PATH` to exit 99); without it, the fallback still works. Watch it fail, implement, watch it pass.
- [ ] Commit on `fix/fable-hook-find` (`fix(hooks): …`, attribution trailer per your harness). The latency AC is measured against the worktree copy by pointing `measure.sh` at it, since live runs `main`.

```json:metadata
{"files": ["~/agent-board/claude/hooks/superpowers-hook.sh", "~/.claude/settings.json", "~/agent-board/tools/tests/test_superpowers_hook.zsh"], "verifyCommand": "zsh tools/tests/run-all.zsh && bash ~/.claude/fable-run/2026-10-16/metrics/measure.sh", "acceptanceCriteria": ["env var path skips find", "fallback preserved", "no hardcoded plugin version", "hook latency below baseline"], "modelTier": "standard"}
```

### Task 3: Read-only permission allowlist

**Goal:** Cut permission prompts for read-only commands without allowing anything that mutates state.

**Files:**
- Modify: `~/.claude/settings.json` (`permissions.allow`/`deny`), tracked by Task 1
- Modify: `~/master-gcp-repo/.claude/settings.json` (repo-specific read-only commands; branch `agent/fable-claude-efficiency` from `dev3`)

**Acceptance Criteria:**
- [ ] Run the `fewer-permission-prompts` skill first and use its transcript-derived ranking as the input list.
- [ ] Global allow list: read-only git (`status`, `log`, `diff`, `show`, `branch --list`, `rev-parse`, `worktree list`), `ls`, `rg`, `grep`, `find` without `-delete`/`-exec`, `wc`, `jq`, `python3 -m json.tool`, `glab api` GETs only (if the matcher can't express "GET only", leave `glab api` out), `glab mr view|list`, `glab ci status|view|list`, `agent-ci check|status|failures`.
- [ ] Project allow list: `terraform fmt -check`, `terraform validate`, `ruff check`, `pytest` (scoped to `tests/`, `pipelines/*/tests`, `ci/**/tests`), `shellcheck`.
- [ ] **Deny** list, added in the same edit: `Bash(gcloud * create*)`, `Bash(gcloud * delete*)`, `Bash(gcloud * update*)`, `Bash(gcloud * add-iam-policy-binding*)`, `Bash(gcloud * set-iam-policy*)`, `Bash(terraform apply*)`, `Bash(terraform destroy*)`, `Bash(git push*)`, `Bash(glab mr create*)`, `Bash(glab variable*)`.
- [ ] Every entry is checked against the documented matcher syntax. Use the `claude-code-guide` agent and confirm the exact pattern format; don't guess wildcards.

**Verify:** `python3 -c 'import json; s=json.load(open("'$HOME'/.claude/settings.json")); print(len(s["permissions"]["allow"]), len(s["permissions"].get("deny",[])))'` → allow ≥ 15, deny ≥ 10; plus a manual spot check in a fresh session: `git log -1` runs without a prompt, `git push --dry-run` prompts or is denied.

**Steps:**
- [ ] Back up the current file (`settings.json.bak-YYYYMMDD`) and make sure Task 1's tracked copy matches it before editing.
- [ ] Also fix the stale `autoMode.environment` trusted repo (today `~/.claude/jobs/318c9a50/tmp/teamtest`) so it names `~/master-gcp-repo` and `~/agent-board`. Same file, same commit, own line in the commit message.

```json:metadata
{"files": ["~/.claude/settings.json", ".claude/settings.json"], "verifyCommand": "python3 -c 'import json,os; s=json.load(open(os.path.expanduser(\"~/.claude/settings.json\"))); print(len(s[\"permissions\"][\"allow\"]), len(s[\"permissions\"].get(\"deny\",[])))'", "acceptanceCriteria": ["allowlist derived from fewer-permission-prompts", "deny list blocks GCP/TF/push mutations", "patterns verified against docs", "stale trusted repo fixed"], "modelTier": "standard"}
```

### Task 4: Listing and MCP hygiene

**Goal:** Every session loads a smaller skill listing and one GitLab MCP instead of two.

**Files:**
- Modify: `~/.claude/settings.json` (move `skillOverrides` from `~/master-gcp-repo/.claude/settings.local.json` to user scope)
- Modify: `~/master-gcp-repo/.claude/settings.local.json` (remove the moved block)

**Acceptance Criteria:**
- [ ] `skillOverrides` lives at user scope with the same 16 entries; the project-local copy is gone.
- [ ] The run log records which GitLab MCP to keep, with the reason (both are unauthenticated today). It also records a one-line instruction for the user to disconnect the other in claude.ai → Settings → Connectors (a user-side action, not something the run can do).
- [ ] A fresh `claude -p "list your available skills by name only"` run in `/tmp` shows the trimmed set. Record the count before and after.

**Verify:** `cd /tmp && claude -p "Print only the names of the skills available to you, one per line." | wc -l` → count lower than the baseline recorded first.

```json:metadata
{"files": ["~/.claude/settings.json", ".claude/settings.local.json"], "verifyCommand": "cd /tmp && claude -p 'Print only the names of the skills available to you, one per line.' | wc -l", "acceptanceCriteria": ["skillOverrides at user scope", "project copy removed", "GitLab MCP decision logged", "skill count reduced"], "modelTier": "mechanical"}
```

### Task 5: Worker sessions stop asking an absent user

**Goal:** Workers spawned by `tmux-ctl agent` never get blocked by end-of-session nudges that ask questions.

**Files:**
- Modify: `~/agent-board/bin/tmux-ctl` (the `agent` subcommand; find it with `grep -n 'agent)' bin/tmux-ctl`)
- Modify: `~/agent-board/claude/hooks/revise-claude-md-nudge.py` (tracked by Task 1; honour an env opt-out if it doesn't already)
- Test: `~/agent-board/tools/tests/test_agent_env.zsh`
- Work in an agent-board worktree, branch `fix/fable-worker-nudge`.

**Acceptance Criteria:**
- [ ] `tmux-ctl agent` launches workers with `CLAUDE_MD_REVISE_HOOK=0` (confirm the exact variable name the hook reads) and `TC_ROLE=worker` exported.
- [ ] The nudge hook exits 0 without blocking when `CLAUDE_MD_REVISE_HOOK=0`.
- [ ] The new zsh test, using the existing `lib.zsh` isolated tmux server, asserts the typed launch line contains both env assignments.
- [ ] The full zsh suite passes.

**Verify:** `zsh tools/tests/run-all.zsh` (in the worktree) → all PASS, including `test_agent_env`.

```json:metadata
{"files": ["~/agent-board/bin/tmux-ctl", "~/agent-board/claude/hooks/revise-claude-md-nudge.py", "~/agent-board/tools/tests/test_agent_env.zsh"], "verifyCommand": "zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["workers launched with opt-out env", "nudge honours opt-out", "new test passes", "suite green"], "modelTier": "standard"}
```

### Task 6: Decision memo — the session-start tax

**Goal:** Give the user a one-page, numbers-first decision on the ≈19K chars every session spends before doing work: task-observer ≈45K-char skill plus three mandates, and the superpowers ≈8K-char injection that repeats after compact.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/decisions/session-start-tax.md`

**Acceptance Criteria:**
- [ ] Measured cost per session in tokens. Use `claude -p` with `--output-format json` in an empty dir, comparing with and without each component disabled via a temporary `--settings` override; report `usage.input_tokens` / cache numbers.
- [ ] Counts how often each mandate actually produced value in the last 50 master-gcp-repo sessions: observations written, plans gated. Derive this from transcripts and the observation log, read-only.
- [ ] 2–3 options, each stating what changes, what is lost and the token saving. Example: "keep task-observer, drop the CLAUDE.md duplicate since the hook already covers it"; "lazy-load: hook injects a 2-line pointer, skill loads at first plan".
- [ ] One recommendation. No edits to `~/.claude/CLAUDE.md` or plugin files: the user decides.

**Verify:** `test -s ~/.claude/fable-run/2026-10-16/decisions/session-start-tax.md && grep -c '^## Option' ~/.claude/fable-run/2026-10-16/decisions/session-start-tax.md` → ≥ 2.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/decisions/session-start-tax.md"], "verifyCommand": "grep -c '^## Option' ~/.claude/fable-run/2026-10-16/decisions/session-start-tax.md", "acceptanceCriteria": ["measured token cost per component", "value evidence from last 50 sessions", "2-3 options with tradeoffs", "single recommendation, no edits made"], "modelTier": "frontier"}
```

### Task 7: master-gcp-repo CLAUDE.md review, memory seed, and Fable-ready prompts

**Goal:** Sessions in this repo stop spending their first turns rediscovering the repo layout, and the worker/orchestrator prompts suit Fable.

**Files:**
- Modify: `~/master-gcp-repo/CLAUDE.md` (exists since `b42cf24e`, 43 lines; changes on `agent/fable-claude-efficiency` from `dev3`)
- Modify: `~/.claude/projects/-Users-francisco-ruiz-master-gcp-repo/memory/MEMORY.md` + add 2–5 memory files (one exists: `master-gcp-repo-monorepo-only.md`)
- Modify: `~/agent-board/claude/worker.md`, `~/agent-board/claude/orchestrator.md` (agent-board worktree, branch `feat/fable-prompts`)

**Acceptance Criteria:**
- [ ] CLAUDE.md is scored with the `claude-md-management:claude-md-improver` rubric first; only gaps are added. It stays ≤ 120 lines, contains no superpowers material, and covers only what isn't derivable from a quick `ls`:
  - the branch flow (`agent/*` → dev3 → staging → main; `hotfix-*` and `ci-vars/*` rules);
  - how to run tests per area (exact commands);
  - `agent-ci` usage;
  - "never apply/push" rules;
  - where runbooks live;
  - the `tmux-ctl run tests` convention.
- [ ] Memory files follow the frontmatter format in the system prompt. They seed durable non-derivable facts only: the user's pinned workspace conventions, the stale-server gotcha, the worktree-isolation constraint.
- [ ] Run `/claude-api prompt-audit` against `worker.md` (target: Fable and Sonnet workers) and `orchestrator.md` (target: the Opus lead). Apply its de-prescription diff where it reduces step-by-step scaffolding. Keep the safety rules: no pkill, commit-don't-push, ask only before destructive actions. Add Fable's "ground progress claims" and "re-grounding final summary" lines.
- [ ] A worker started with the new `worker.md` completes a toy task ("add a docstring to lib/…/x.py and run its tests"). Its final report leads with the outcome and cites the command output.

**Verify:** `git -C <mgr worktree> show agent/fable-claude-efficiency:CLAUDE.md | wc -l` → ≤ 120; `ls ~/.claude/projects/-Users-francisco-ruiz-master-gcp-repo/memory/ | wc -l` → ≥ 4; the toy-worker transcript is saved to the run dir.

```json:metadata
{"files": ["~/master-gcp-repo/CLAUDE.md", "~/.claude/projects/-Users-francisco-ruiz-master-gcp-repo/memory/MEMORY.md", "~/agent-board/claude/worker.md", "~/agent-board/claude/orchestrator.md"], "verifyCommand": "git -C ~/master-gcp-repo show agent/fable-claude-efficiency:CLAUDE.md | wc -l && ls ~/.claude/projects/-Users-francisco-ruiz-master-gcp-repo/memory/ | wc -l", "acceptanceCriteria": ["CLAUDE.md <=120 lines, scored by improver rubric", "memory seeded with non-derivable facts", "prompt-audit applied to worker/orchestrator with safety rules kept", "toy worker run verifies new prompt"], "modelTier": "frontier"}
```

---

## Workstream B — Agent Board

All tasks in this workstream run in the Board session, in one agent-board worktree on branch `feat/fable-board` (one commit or more per task, `feat(board): …` / `fix(tmux-ctl): …`). Paths below are relative to that worktree (`board/` = live `~/.local/share/tmux-dash`, `tools/` = live `~/.local/share/tmux-tools`, `bin/` = live `~/.local/bin`). TDD applies: write the failing test first. Python suite: `python3 -W error::ResourceWarning -m unittest discover -s board/tests`; zsh suite: `zsh tools/tests/run-all.zsh`. Re-verify each Ground-truth item before fixing it: today's board batches (`fix/board-batch` etc.) may already have closed some.

### Task 8: Stale-server fix and self-reload

**Goal:** The Activity drawer works again, and code edits can never silently run against an old server process.

**Files:**
- Modify: `board/server.py` (startup mtime snapshot + `/api/version` + re-exec when a module's mtime changes, checked at most every 5 s on request)
- Modify: `board/index.html` (`pollActivity`: show a visible "server out of date / restart" banner on 404 instead of silently returning)
- Test: `board/tests/test_reload.py`

**Acceptance Criteria:**
- [ ] Before any code change, check the live board (real state): `/api/runs` status. If it is not 200, restart with `tmux-dash stop && tmux-dash start` and confirm 200. Record this in the run log as the quick win (or that it was already fixed).
- [ ] Test: start the server on an ephemeral port, touch `activity.py`, issue a request, and assert `/api/version` reports a new start time within 10 s.
- [ ] A 404 from `/api/runs` renders a banner. Check it by pointing the page at a stub server returning 404 (in the test, or manually via the Chrome tools).

**Verify:** `python3 -W error::ResourceWarning -m unittest discover -s board/tests -p 'test_reload.py' -v` → OK.

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_reload.py"], "verifyCommand": "python3 -W error::ResourceWarning -m unittest discover -s board/tests -p 'test_reload.py' -v", "acceptanceCriteria": ["restart restores /api/runs 200", "server self-reloads on module mtime change", "404 shows visible banner"], "modelTier": "standard"}
```

### Task 9: Correct run records

**Goal:** Every `tmux-ctl run` record has a truthful exit code and a non-empty summary for pytest, unittest and zsh suites.

**Files:**
- Modify: `bin/tmux-ctl` (`run`: wrap in `set -o pipefail` for the typed subshell; `summarize()`)
- Test: `tools/tests/test_run_summary.zsh`

**Acceptance Criteria:**
- [ ] `tmux-ctl run tests "false | tail -1"` records `rc` ≠ 0.
- [ ] `summarize()` parses:
  - unittest: `Ran N tests` + `OK` / `FAILED (failures=F, errors=E)`
  - pytest: as today
  - the zsh suite's own pass line (read `run-all.zsh` for its exact format)
- [ ] Records are bounded: on append, if `runs-<p>.jsonl` exceeds 500 records, keep the newest 500 (atomic rewrite via temp + `mv`).

**Verify:** `zsh tools/tests/run-all.zsh` → all PASS, including `test_run_summary`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_run_summary.zsh"], "verifyCommand": "zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["pipefail gives true rc", "unittest and zsh summaries parsed", "runs file capped at 500"], "modelTier": "standard"}
```

### Task 10: Polling and tmux-exec efficiency

**Goal:** Cut the board's per-poll cost (tmux execs, bytes, DOM work) without the UI going stale.

**Files:**
- Modify: `board/server.py`, `board/activity.py`, `board/artifacts.py`, `board/index.html`
- Test: `board/tests/test_poll_efficiency.py`

**Acceptance Criteria:**
- [ ] **Design first (Fable, frontier):** a ≤1-page note in the run log choosing among:
  - (a) skip `capture-pane` for panes whose `#{pane_activity}`/`#{window_activity}` is unchanged since the last build (reuse the cached classification);
  - (b) one `tmux` invocation that chains several `capture-pane -p` commands with `\;` and splits output on markers;
  - (c) a combined `/api/poll` with ETag/304;
  - (d) DOM keyed updates instead of `replaceChildren`;
  - (e) incremental `runs` reads by byte offset;
  - (f) artifact diff computed only when the artifact panel is open.
  Pick by measured cost. The exec cost (≈0.5 s each) dominates, so (a)+(b) are likely first.
- [ ] Test counts tmux execs per state build via a shim `tmux` on `PATH` that logs calls. Assert the count for an idle 6-pane layout is ≤ 2 on the second build (was ≈7+).
- [ ] `board_state_ms` median drops ≥ 50 % against baseline (from `measure.sh`).
- [ ] The UI behaves the same. Use Chrome automation (`claude-in-chrome`) to load the board, start a `tmux-ctl run tests "sleep 3; echo ok"`, and confirm the card goes working → ready and the Runs tab shows the record. Record a GIF `agent-board-poll.gif`.

**Verify:** `python3 -W error::ResourceWarning -m unittest discover -s board/tests -v` → OK, and `measure.sh` shows `board_state_ms` ≤ 0.5 × baseline.

```json:metadata
{"files": ["board/server.py", "board/activity.py", "board/artifacts.py", "board/index.html", "board/tests/test_poll_efficiency.py"], "verifyCommand": "python3 -W error::ResourceWarning -m unittest discover -s board/tests -v", "acceptanceCriteria": ["design note picks measured options", "<=2 tmux execs on idle rebuild", "board_state_ms halved", "UI verified via browser with GIF"], "modelTier": "frontier"}
```

### Task 11: Single source of truth, plus model/effort for workers

**Goal:** One definition each of the state path and the pane-state regexes, and worker spawns that choose a model and effort.

**Files:**
- Create: `tools/lib/tc-env.zsh` (STATE path, SHELLS regex, prompt regex), with a matching `board/tc_env.py` the board imports
- Modify: `bin/tmux-ctl`, `claude/hooks/{bash-mirror,artifact-register}.sh`, `board/{artifacts,relay,paneclass}.py`
- Modify: `bin/tmux-ctl agent` to accept (if not already: check `d563d64` frontier→fable routing first) `--model <haiku|sonnet|opus|fable>` and `--effort <low|medium|high|xhigh>`, mapping to the `claude` CLI flags (check exact flag names with `claude --help`). Defaults: `sonnet` / `medium`.
- Modify: `board/index.html` "+ New agent" adds a model/effort select defaulting to sonnet/medium
- Modify: `~/.tmux.conf` / `menu.conf` "New Claude agent" binding to call `tmux-ctl agent` (find the binding with `grep -n "New Claude agent" ~/.tmux.conf ~/.config/tmux/*`)

**Acceptance Criteria:**
- [ ] `grep -rn 'tmux-ctl-\$UID\|TMPDIR/tmux-ctl' board bin tools claude/hooks` returns only the two `tc-env` files.
- [ ] A Python test asserts `paneclass` and `tc_env` agree on the regexes (`tc_env.py` parses `tc-env.zsh`, or both are generated from one JSON).
- [ ] `tmux-ctl agent --model haiku --effort low demo "echo hi"` types a launch line containing the model and effort flags. Verify this in the isolated test server.
- [ ] Both suites pass.

**Verify:** `zsh tools/tests/run-all.zsh && python3 -W error::ResourceWarning -m unittest discover -s board/tests` → all pass.

```json:metadata
{"files": ["tools/lib/tc-env.zsh", "board/tc_env.py", "bin/tmux-ctl", "board/index.html"], "verifyCommand": "zsh tools/tests/run-all.zsh && python3 -W error::ResourceWarning -m unittest discover -s board/tests", "acceptanceCriteria": ["state path defined once", "regexes shared and tested", "agent spawn takes model/effort", "menu binding uses tmux-ctl agent", "suites green"], "modelTier": "standard"}
```

---

## Workstream C — DevOps security review (master-gcp-repo)

Read-only until Task 17. Read the repo at `dev3` (checked out in `~/master-gcp-repo`; analysis runs in worktrees cut from `dev3`). All notes go in `~/.claude/fable-run/2026-10-16/security/`. Finding IDs are `SEC-NNN`.

### Task 12: Threat model and review scope

**Goal:** A threat model that tells the sweep and the deep-dives what matters most, so the review covers attacker paths, not just a checklist.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/threat-model.md`

**Acceptance Criteria:**
- [ ] **Assets:** org-level and FAST deployer SAs, tenant deploy SAs, Secret Manager tenant secrets (Ads/GA4/GSC/YT OAuth refresh tokens, developer tokens), Terraform state buckets, ledger Cloud SQL, the GitLab CI variable set, release images in Artifact Registry.
- [ ] **Trust boundaries:** a diagram (mermaid) of GitLab project → runner → OIDC token → WIF pool attribute conditions → SA impersonation → GCP resources. It shows which branch/protection attributes gate each SA.
- [ ] **Attacker models, each with an entry point:**
  - developer with push to a non-protected branch;
  - a malicious MR (including from `agent/*`);
  - a compromised upstream image or PyPI package;
  - a compromised shared runner / co-tenant job;
  - a tenant-facing Cloud Run caller;
  - a stolen GitLab PAT.
- [ ] **Ranked list of the 10 most valuable attack paths to test.** The Ground-truth hotspots must each appear or be explicitly dismissed with a reason.
- [ ] Every claim about current configuration cites `file:line`.

**Verify:** `grep -c 'file:\|\.tf:\|\.yml:\|\.sh:\|\.py:' ~/.claude/fable-run/2026-10-16/security/threat-model.md` → ≥ 20 citations; the mermaid block renders (paste into an Artifact preview).

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/threat-model.md"], "verifyCommand": "grep -cE '\\.(tf|yml|yaml|sh|py):[0-9]+' ~/.claude/fable-run/2026-10-16/security/threat-model.md", "acceptanceCriteria": ["assets enumerated", "trust-boundary diagram with WIF conditions", "6 attacker models with entry points", "top-10 attack paths ranked, hotspots covered", ">=20 file:line citations"], "modelTier": "frontier"}
```

### Task 13: Automated sweep — claude-security scan plus deterministic scanners

**Goal:** Broad, reproducible coverage: an LLM vulnerability sweep plus standard scanners, with raw outputs saved.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/sweep/` (scanner JSON outputs + `claude-security` report)

**Acceptance Criteria:**
- [ ] Run the claude-security orchestrator on **Opus 5.5** (not Fable, see "Why the plan is shaped this way") from worktree `fable-sec-sweep` (cut from `dev3`), scope = whole repo, with `threat-model.md` as context. Save its verified report.
- [ ] Run the deterministic scanners against the worktree, with versions pinned and recorded. None are installed today, so run them as pinned container images (`docker run --rm -v "$PWD":/src:ro <image>@sha256:…`) when Docker is available; otherwise ask the user once to approve `pipx install` of each:
  - `gitleaks detect --source . --log-opts="--all"` (full history; report rule + file + commit only, and redact matches in the saved output)
  - `checkov -d . --framework terraform,gitlab_ci,dockerfile,secrets -o json`
  - `trivy config .` and `trivy fs --scanners vuln .`
  - `pip-audit -r <each requirements.txt>`
  - `bandit -r pipelines tools lib -f json`
  - `semgrep --config p/ci --config p/python --config p/terraform --json`
- [ ] A `sweep/summary.md` table: tool, version, findings by severity, and the top 5 per tool that are not obvious false positives.
- [ ] No secret value appears in any saved file. Check with `grep -rE '[A-Za-z0-9_\-]{32,}' sweep/ | grep -vi sha256 | wc -l` and review hits by hand.

**Verify:** `ls ~/.claude/fable-run/2026-10-16/security/sweep/` → one output per tool + `claude-security` report + `summary.md`.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/sweep/summary.md"], "verifyCommand": "ls ~/.claude/fable-run/2026-10-16/security/sweep/", "acceptanceCriteria": ["claude-security run on Opus with threat model", "6 scanners run pinned with raw outputs", "summary table per tool", "no secret values saved"], "modelTier": "standard", "model": "opus"}
```

### Task 14: Deep-dive reviews — five parallel lenses

**Goal:** Expert-depth review of the attack paths from Task 12, done by parallel sub-agents, each producing candidate findings with exploit narratives.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/lenses/{identity-wif,supply-chain,terraform-iam,runtime-services,gitlab-governance}.md`

**Acceptance Criteria:**
- [ ] Five subagents run in parallel, dispatched by the Opus lead; lens agents are Opus 5.5 (security analysis, see the classifier note). Each receives `threat-model.md`, the sweep summary and its lens brief:
  1. **identity-wif:**
     - Can a non-protected branch or MR pipeline obtain the planner/deployer/org/tenant SA? Trace `identity.tf` attribute conditions → `auth-fast-wif.sh` / `gcp-wif-auth-org.sh` / `gcp-wif-auth-tenant.sh` → which jobs run on MR pipelines.
     - What can the planner SA read? (tfstate holds secrets.)
     - Is `ORG_WIF_AUTH_REF` user-controllable via pipeline variables? Check project "who can run pipelines with variables".
     - Token files are left in the job dir: are they in `artifacts:` paths?
  2. **supply-chain:**
     - unpinned images; dind without TLS on shared runners;
     - terraform curl with no checksum;
     - gitignored lock file and unpinned providers;
     - unpinned requirements and no hashes;
     - `constraints.txt` not applied in Docker builds;
     - Fabric module pin integrity.
  3. **terraform-iam:**
     - `roles/owner` user grants;
     - `roles/viewer` in identity.tf;
     - fast-bootstrap local state;
     - committed tfvars contents;
     - KMS key IAM, logging sink destinations, org-policy gaps against the hardening baseline;
     - VPC/firewall egress policy correctness;
     - whether VPC-SC is absent.
  4. **runtime-services:**
     - Cloud Run ingress/auth settings (`--allow-unauthenticated`? `--ingress`?) in `deploy-common.sh` and the env yamls;
     - authn/authz on `secret_update`, `onboarding` and ledger `config` routes;
     - input validation;
     - SSRF/injection in the ingest layer;
     - SA least privilege per service;
     - secrets in logs.
  5. **gitlab-governance:**
     - branch-policy scripts vs real protected-branch settings;
     - CODEOWNERS single owner + whether "prevent approval by author" is on;
     - CI variable protection/masking flags (`infra/gitlab-ci-variables/variables.yaml`) vs which jobs read them on unprotected refs;
     - `GITLAB_TOKEN` scope and its `insteadOf` embedding;
     - runner tagging;
     - `agent/*` → staging bypasses.
- [ ] Each candidate finding has:
  - an ID;
  - the attacker model;
  - preconditions;
  - a step-by-step path;
  - impact;
  - evidence `file:line`;
  - what would disprove it.
- [ ] Lenses don't propose fixes yet.

**Verify:** `grep -c '^### SEC-' ~/.claude/fable-run/2026-10-16/security/lenses/*.md` → every file ≥ 1 or an explicit "no findings, here is what I checked" section.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/lenses/identity-wif.md", "~/.claude/fable-run/2026-10-16/security/lenses/supply-chain.md", "~/.claude/fable-run/2026-10-16/security/lenses/terraform-iam.md", "~/.claude/fable-run/2026-10-16/security/lenses/runtime-services.md", "~/.claude/fable-run/2026-10-16/security/lenses/gitlab-governance.md"], "verifyCommand": "grep -c '^### SEC-' ~/.claude/fable-run/2026-10-16/security/lenses/*.md", "acceptanceCriteria": ["5 lenses run in parallel", "each finding has attacker/preconditions/path/impact/evidence/falsifier", "no-findings sections list what was checked"], "modelTier": "frontier", "model": "opus"}
```

### Task 15: Adversarial verification and dedup

**Goal:** Only real findings survive. Each candidate is attacked by a fresh-context verifier whose job is to disprove it.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/verified.md`

**Acceptance Criteria:**
- [ ] Merge sweep results and lens candidates, dedup by root cause, and keep the source list per finding.
- [ ] One fresh verifier per finding (Sonnet 5.5 `medium` for scanner hits, Opus 5.5 `high` for lens findings). It is told to *refute* the finding: check the falsifier, look for compensating controls (org policies, protected-branch settings, VPC-SC, IAM conditions) and re-read the cited lines.
- [ ] Verdicts: `CONFIRMED`, `PLAUSIBLE (needs live check: <what>)` or `REFUTED (<why>)`. PLAUSIBLE items list the exact read-only command that would settle them; these feed Task 16.
- [ ] Severity uses one rubric: CVSS-like impact × likelihood given the attacker model. The rubric is written at the top of the file.

**Verify:** `grep -cE 'CONFIRMED|PLAUSIBLE|REFUTED' ~/.claude/fable-run/2026-10-16/security/verified.md` → equals the number of deduped candidates (stated in the file header).

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/verified.md"], "verifyCommand": "grep -cE 'CONFIRMED|PLAUSIBLE|REFUTED' ~/.claude/fable-run/2026-10-16/security/verified.md", "acceptanceCriteria": ["dedup by root cause", "fresh verifier per finding tasked to refute", "every candidate has a verdict", "PLAUSIBLE items carry settling read-only command", "severity rubric stated"], "modelTier": "frontier"}
```

### Task 16: Live read-only posture check (user gate)

**Goal:** Settle the PLAUSIBLE findings against the real GitLab and GCP configuration, using read-only calls the user has approved.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task touches live systems under the user's credentials. It MUST NOT run until the user approves the exact command list. It MUST NOT be closed by substituting reasoning for the live check. Close only after every command's output is captured or the user declines, and record that.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/live-checks.md` (the command list, then captured outputs with secrets redacted)

**Acceptance Criteria:**
- [ ] The command list is presented to the user in one message, grouped GitLab / GCP. Every command is a GET/list/describe. Examples:
  - `glab api projects/:id/protected_branches`
  - `glab api projects/:id` (fields: `only_allow_merge_if_pipeline_succeeds`, `merge_requests_author_approval`, `ci_pipeline_variables_minimum_override_role`)
  - `glab api projects/:id/variables` (keys + protected/masked flags only; pipe through `jq 'map({key,protected,masked,environment_scope})'` so values never print)
  - `gcloud iam workload-identity-pools providers describe …`
  - `gcloud asset search-all-iam-policies --scope=organizations/<id> --query='policy:roles/owner'`
  - `gcloud run services describe … --format='value(spec.template.metadata.annotations,metadata.annotations."run.googleapis.com/ingress")'`
  - `gcloud resource-manager org-policies list --organization=<id>`
- [ ] The user approves, edits or declines. Run only approved commands and update each PLAUSIBLE verdict.
- [ ] If declined, the findings stay PLAUSIBLE and the report says so.

**Verify:** `grep -c '^- \[x\]' ~/.claude/fable-run/2026-10-16/security/live-checks.md` → equals the number of approved commands; `grep -cE '"value"|refresh_token' live-checks.md` → 0.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/live-checks.md"], "verifyCommand": "grep -c '^- \\[x\\]' ~/.claude/fable-run/2026-10-16/security/live-checks.md", "acceptanceCriteria": ["user approved exact read-only command list", "only approved commands run", "outputs captured with secrets redacted", "PLAUSIBLE verdicts updated or left with reason"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

### Task 17: Report, remediation roadmap, and first fixes on branches

**Goal:** A decision-ready security report, plus the highest-value low-risk fixes ready as local branches.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/security/report.html`, published as a **private** Artifact
- Create branches in master-gcp-repo worktrees cut from `dev3` (one per fix topic, not pushed):
  - `agent/fable-sec-ci-scanners`: adds GitLab `Secret-Detection`, `SAST` and `Dependency-Scanning` templates (or gitleaks/checkov/pip-audit jobs) as `allow_failure: true` in a new `ci/actions/security/.gitlab-ci-security.yml`, included from `.gitlab-ci.yml`
  - `agent/fable-sec-pin-images`: digest-pins the CI images and Dockerfile bases, adds a terraform download checksum check, and un-ignores `.terraform.lock.hcl` for `infra/` and `landing-zone/`
  - one branch per CONFIRMED high/critical finding where the fix is code-only and reversible (e.g. narrowing `planner_wif` to MR/protected attributes)
  - IAM/Terraform changes that alter live access are written as branches **with a plan-impact note**. They are never applied.

**Acceptance Criteria:**
- [ ] The report leads with a 5-line executive summary: overall posture and the top 3 risks in plain language. Then:
  - the findings table (ID, severity, verdict, attacker model, evidence, fix, effort S/M/L, owner action);
  - a 30/60/90-day roadmap;
  - what was *not* covered;
  - the methodology (models, tools, versions).
- [ ] Each fix branch:
  - passes `agent-ci check` locally (or the relevant `pytest`/`terraform validate`/`ruff` subset);
  - has a commit message referencing `SEC-NNN` without exploit detail;
  - gets a `superpowers-extended-cc:requesting-code-review` pass with findings addressed.
- [ ] Changes that need a `terraform plan` to judge get a `README-plan-impact.md` in the branch, stating the expected plan diff and the rollback.
- [ ] Nothing pushed; the branch list goes in the run log.

**Verify:** for each branch, `git log --oneline dev3..<branch>` shows ≥ 1 commit, plus the branch's check command output saved to `security/fixes/<branch>.log` with a passing result.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/security/report.html", "ci/actions/security/.gitlab-ci-security.yml", ".gitlab-ci.yml", ".gitignore"], "verifyCommand": "for b in $(git branch --list 'agent/fable-sec-*' --format='%(refname:short)'); do git log --oneline dev3..$b | head -1; done", "acceptanceCriteria": ["private artifact report with exec summary, table, roadmap, gaps, methodology", "scanner jobs branch non-blocking", "image/provider pinning branch", "fix branch per confirmed high/critical code-only finding", "each branch checked and reviewed, not pushed"], "modelTier": "frontier"}
```

---

### Task 18: Close-out — measure, report, remember

**Goal:** Prove what changed, hand the user one page of decisions, and leave lessons where the next session will find them.

**Files:**
- Create: `~/.claude/fable-run/2026-10-16/metrics/after.json`, `~/.claude/fable-run/2026-10-16/summary.html` (private Artifact)
- Modify: project memory files (lessons learned); all agent-board branches committed (no merges into `main` without the user)

**Acceptance Criteria:**
- [ ] `measure.sh` is re-run and `after.json` diffed against `baseline.json`. The summary shows before/after per metric, with no rounding that hides regressions.
- [ ] Fable run cost: tokens and $ per workstream, taken from `/cost` or the session usage, and compared with what a Sonnet/Opus-only run would plausibly have cost. Say which tasks earned Fable and which didn't, as advice for the next run.
- [ ] A **Decisions for you** section lists:
  - the session-start-tax memo (Task 6);
  - the GitLab MCP choice;
  - merging the agent-board branches (`feat/claude-config-home`, `fix/fable-hook-find`, `fix/fable-worker-nudge`, `feat/fable-prompts`, `feat/fable-board`) into `main` and running `claude-config-link`;
  - pushing `agent/fable-claude-efficiency` (master-gcp-repo CLAUDE.md + settings) as an MR into `dev3`;
  - whether to delete the old master-gcp-repo worktree branch `worktree-want-use-fable-first`;
  - the security fix branches to push and their order;
  - deleting the `.bak-*` files;
  - the pending task-observer review.
- [ ] Memory: one file per lesson, e.g. "Fable for X was / wasn't worth it", "board server must be restarted after edits".
- [ ] Fable drafts the summary; the Opus lead runs the final whole-plan review at session level and `superpowers-extended-cc:verification-before-completion` before the final message. The final message leads with the outcome in plain sentences.

**Verify:** `python3 - <<'EOF'
import json,os
b=json.load(open(os.path.expanduser("~/.claude/fable-run/2026-10-16/metrics/baseline.json")))
a=json.load(open(os.path.expanduser("~/.claude/fable-run/2026-10-16/metrics/after.json")))
for k in b: print(k, b[k], "->", a.get(k))
EOF` → prints every metric with both values.

```json:metadata
{"files": ["~/.claude/fable-run/2026-10-16/metrics/after.json", "~/.claude/fable-run/2026-10-16/summary.html"], "verifyCommand": "python3 -c 'import json,os;p=os.path.expanduser(\"~/.claude/fable-run/2026-10-16/metrics/\");b=json.load(open(p+\"baseline.json\"));a=json.load(open(p+\"after.json\"));[print(k,b[k],a.get(k)) for k in b]'", "acceptanceCriteria": ["before/after metrics diffed", "Fable cost per workstream with advice", "decisions-for-you list", "lessons in memory", "verification-before-completion run"], "modelTier": "frontier"}
```

## Dependencies and parallelism

- **Task 0 → Task 1 → everything else.**
- **Workstream A:** 2, 3 and 4 run in parallel (2 and 3 both touch `~/.claude/settings.json`: different keys, but serialize the writes); 5 needs Task 1's tracked hook copy; 6 and 7 run in parallel after 2–4.
- **Workstream B:** 8 → 9 → 10 → 11, sequential because they touch the same files.
- **Workstream C:** 12 → 13 ∥ 14 (14 reads 13's summary when it is ready, but may start lenses on the threat model alone) → 15 → 16 (gate) → 17.
- **Running streams concurrently:** A, B and C can run at the same time once Task 1 is done (C does not depend on Task 1 and may start right after Task 0). The lead coordinates; the Board session and the security worktrees run in their own tmux windows.
- **Task 18** runs after everything else.

## Kickoff prompt (paste into the Opus lead session in `~/agent-board`)

```text
Execute ~/agent-board/docs/superpowers/plans/2026-10-16-fable-first-run.md with superpowers-extended-cc:subagent-driven-development. It is my first run with Claude Fable: (1) cut the token, latency and permission-prompt cost of my Claude Code setup, (2) make my Agent Board faster and more reliable, (3) do a deep security review of master-gcp-repo's DevOps posture (from dev3). You are the Opus lead; route each task by its modelTier via ~/.claude/superpowers/model-routing.json (frontier → model "fable"), and honour a task's "model" pin (Tasks 13 and 14 run on Opus).

The plan fixes goals, constraints and acceptance criteria; frontier executors choose their own method. For reversible actions that follow from the plan, proceed without asking. Stop only for the user gate in Task 16, for anything the Global Constraints forbid, and for genuine scope changes.

Before reporting progress, audit each claim against a tool result from this session. Keep ~/.claude/fable-run/2026-10-16/run-log.md current. The final message leads with the outcome in plain sentences, then the decisions you need from me.
```

The lead runs on Opus (`claude-orchestrator` pins `--model opus`); Fable is used only through frontier dispatches.
