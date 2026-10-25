# Local CI pre-flight spike (ci-scout, 2026-10-25)

## Recommendation

- **Lint-only, not full local runs.** Add `actionlint` (GitHub repos) and `glab ci lint` (GitLab repos) as a pre-push step. Both are free to run: actionlint takes 0.16 s, `glab ci lint` about 1.9 s.
- **Be honest about the payoff.** Measured against 2026-10-20, lint would have caught 0 of the 10 failed runs. Every failure was runner-environment or test logic, none was workflow syntax. Lint is a cheap safety net, not the fix for the "6 pushes" problem.
- **Do not adopt `act` or `gitlab-ci-local`.** `act` cannot run the macOS half of the matrix, and 5 of the 10 failed runs hit macOS. For Linux, it uses a different image from `ubuntu-latest`, which is where most of the day's failures came from.
- **Home:** the `gitlab-ci-loop` skill. `agent-ci check` already runs the repo's own validation jobs locally without Docker, so add `glab ci lint` as its first step. For agent-board, which has no `agent-ci`, put `actionlint .github/workflows/*.yml` in the project's test runner.
- **Untested idea for the Linux-only failures:** replay the workflow's `run:` steps in the `ubuntu:24.04` image that is already on this Mac under colima. It needs no `act`, but I did not run it (see Cost).

## Replay of 2026-10-20

The day has 10 failed runs by local time: 9 created on 2026-10-20 UTC, plus 39520793187, which was created at 00:21Z on 10-21 (20:21 local). Causes come from `gh run view <id> --log-failed`. Where the log shows only symptoms, the cause comes from the fix commit that followed, and the row says so.

Verdict columns: yes / no / partly. For actionlint, "no" means it cannot see the problem. All 6 versions of `test.yml` committed that day lint clean with actionlint 1.7.12 (measured, exit 0 for each).

| Run id | Failure cause | actionlint | act | gitlab-ci-local | glab ci lint |
|---|---|---|---|---|---|
| 39435145945 (macOS + Linux; first matrix run) | tmux/hook tests: `summary parsed`, `zsh summary`, `parallel runs stay clean` on macOS; the same on Linux plus `orchestrator started` and `lineage written`. Fix commits `92db341` (BSD `date -j`) and `eb0ba1b` (`TMPDIR` unset). | no | partly: the Linux job only, and only if the image has the same TMPDIR/HOME. The macOS job is impossible. | n/a (GitLab only) | n/a |
| 39443434548 | tmux/hook tests, both OS: `run goes to bg`, `log written`, `lane ran the command`. A typed line was lost in the pane shell (cause confirmed in the fix `39f2407`: zsh first-run menu on the runner HOME). | no | partly: Linux only, and only if the container HOME is empty like the runner's. macOS impossible. | n/a | n/a |
| 39444737717 | Same failures as the previous run (a diagnostics-only push). | no | partly (as above) | n/a | n/a |
| 39449513549 (Linux only failed) | Same failures on Ubuntu after the ZDOTDIR fix. Real cause from `15eed79`: `/etc/zsh/zshrc` runs compinit, which asks "Ignore insecure directories" and swallows the typed line. | no | partly: `act` medium images may not have `/etc/zsh/zshrc` at all, so it could pass locally and still fail on the runner. | n/a | n/a |
| 39450849482 (Linux only) | Board tests died with exit code 139 (segfault) after about 150 tests; no stack in the log. Root cause not found in the log; `5eaa97c` added `PYTHONFAULTHANDLER`. | no | no: runner-specific crash, cannot be reproduced reliably | n/a | n/a |
| 39455457130 (Linux only) | The same compinit failures as 39449513549; the log still failed after `ALL PASS`. Fixed by `15eed79`. | no | partly (as 39449513549) | n/a | n/a |
| 39483823167 (after merging main) | Linux: 18 errors, `FileNotFoundError: /home/runner/.local/bin/tmux`. macOS: `test_poll_efficiency` ExecCountTest errors. Tests hard-coded a tmux path; fix `2a40ed0`. | no | partly: Linux only. The hard-coded `~/.local/bin/tmux` would probably also fail in a container, so the Linux half is likely a yes. | n/a | n/a |
| 39487699360 (macOS only) | `test_reload`: "server did not come up", 3 failures (slow macOS runner; fix `fa8633d` allows 30 s). | no | no: macOS only, and timing is runner-specific | n/a | n/a |
| 39490928438 (Linux only) | `test_poll_efficiency`: `tmux new-session` raised CalledProcessError. Later fixes `9df7dc4` (server bind without `getfqdn`), `f6ed319` (fresh socket per test). | no | partly: Linux only; `getfqdn` slowness depends on runner DNS | n/a | n/a |
| 39520793187 (Linux only; created 00:21Z on 10-21) | `test_poll_efficiency` errors again (`RuntimeError: ... exited <rc>: <stderr>`); fixed by `a179d94` (socket file removed). | no | partly | n/a | n/a |

Takeaway: 0 of 10 caught by lint. `act` could at best partly reproduce the Linux side: 5 runs failed on Linux only and 4 more failed on Linux and macOS together, with no guarantee for any of them. It cannot run the macOS job of those 4, and it cannot run the one macOS-only run (39487699360) at all. The first success after the failures was 39462019666 (12:57 local); runs 39522124772 and later were green.

## Cost on this Mac

Machine: Apple silicon (arm64), 12 cores, 19 GB RAM, colima 0.10.3 already running as aarch64 with 4 CPUs, 6 GiB, 40 GiB disk. docker 29.8.2 is already installed (not by me). `~/.colima` is 8.0 GB. Load average was about 10 at measurement time, so wall times below are noisy.

| Tool | Install size | Image size | amd64 emulation | Wall time of one run | Failure modes |
|---|---|---|---|---|---|
| actionlint 1.7.12 | 5.8 MB static binary (2.2 MB tarball); measured, run from the scratchpad, **not installed permanently** (there is no brew on this Mac; the binary came from the GitHub release via `gh release download`) | none | no | measured: 0.16 s warm, 1.64 s first run (3 runs) | Static only: finds syntax, expression and shellcheck problems. Finds nothing at runtime. Needs shellcheck/pyflakes on PATH for deeper checks. |
| act | about 20 MB Go binary (estimated, from its release page) | estimated from the act README: the medium image is about 0.5–1 GB, the large one over 15 GB, and the image differs from `ubuntu-latest` | no for arm64 Linux images; `--container-architecture linux/amd64` forces emulation (slow, qemu/rosetta via colima) | not measured (not installed). The workflow does `apt-get update/install` plus the full suites, so I'd expect 5–10 min, estimated from the 4–6 min CI runtime. | Linux containers only (no macOS jobs); `ubuntu-latest` mismatch; `actions/setup-python` and hosted toolcache differ; bind mounts of the repo; tmux/zsh behaviour inside a container differs from a runner (the same class of failures as the day's). |
| gitlab-ci-local | npm package, about 30–60 MB with node (estimated) | pulls each job's image (python:3.11 etc.; `python:3.11` is already local at 1.62 GB, `python:3.9` and `ubuntu:24.04` too) | no (arm64 images) unless a job pins amd64 | not measured, not installed | Shell-executor vs docker-executor differences; `include:` with remote/project files and CI-only variables or services; cannot run deploy jobs that need cloud credentials. |
| glab ci lint | already installed | none | no | measured: 1.9 s total against gitlab.com for master-gcp-repo's `.gitlab-ci.yml` (output: "CI/CD YAML is valid!") | Needs network and auth; checks YAML/rules/includes only, not scripts. |

## GitLab side

- **`glab ci lint`:** works against gitlab.com for master-gcp-repo. `glab ci lint .gitlab-ci.yml` returned "✓ CI/CD YAML is valid!" in 1.9 s (the file is 57 lines and includes 21 local files, which the server resolves). I ran it read-only.
- **`.agent-ci.yml` already exists** in master-gcp-repo with checks derived from the validation jobs (for example `landing-zone-validate`, python 3.11 venv, no Docker). That is the existing "local run" and `gitlab-ci-loop` already prefers it over pushing to see what happens.
- **Last 12 failed pipelines, by job and cause** (`glab api projects/:fullpath/pipelines?status=failed`, then each pipeline's failed jobs and traces):

| Pipelines | Failing job | Cause (from log) | Caught locally? |
|---|---|---|---|
| 2956049692 | `ruff-lint` | "2 files would be reformatted" | yes: `agent-ci check` / ruff |
| 2963766629, 2968737991, 2969917713 | `test-offboard-cleanup`, `test-branch-policy`, `test-archive-ledger` | pytest failures (4, 1, 1 failed) | yes: same tests run by `agent-ci check` |
| 2977686181, 2956393861 | `prod-promotion-gate` | "No shared release workload is mapped for this candidate" (deterministic policy gate) | probably, if the gate script is runnable locally; not verified |
| 2956234011 | `enforce-branch-policy` | `fatal: expected 'packfile'` while fetching sources (infrastructure flake) | no |
| 2970486669, 2970504029 | `landing-zone-deploy-stage2-project-factory-stage` | script failure at deploy time (cloud state) | no |
| 2970454024, 2952643380 | `update-ingestion-layer`, `update-transformation-layer` | script failure on staging after merge | no (post-merge cloud state) |
| 2973550304 | none listed | failed on staging with no failed job returned | n/a |

So about 4–6 of 12 are locally catchable, and none are lint failures. `glab ci lint` would have caught none of them either; its value is guarding edits to `.gitlab-ci.yml` or its includes.

## Method

- `command -v actionlint act gitlab-ci-local docker colima glab gh` showed docker, colima, glab and gh present; actionlint, act and gitlab-ci-local absent.
- `git log --since=2026-10-19 --until=2026-10-21`
- `gh run list --created 2026-10-20 --limit 50`, and `--created 2026-10-21` for the late-evening runs
- `gh run view <id> --log-failed` and `gh run view <id> --json jobs --jq ...` for each failed run
- `git log -1 --format=%b <commit>` for the fix commits' reasons
- actionlint: `gh release download v1.7.12 -R rhysd/actionlint -p '*darwin_arm64.tar.gz'` into the scratchpad, `actionlint --version`, `actionlint .github/workflows/test.yml` three times with `time -p`; then `git show <commit>:.github/workflows/test.yml | actionlint` for all 6 commits that touched the file that day (all exit 0)
- `docker images`, `colima list`, `du -sh ~/.colima`, `uname -m`, `sysctl hw.ncpu hw.memsize`, `uptime`
- GitLab: `glab auth status`, `time glab ci lint .gitlab-ci.yml`, `glab api "projects/:fullpath/pipelines?status=failed&per_page=12"`, per-pipeline `.../jobs?scope[]=failed` and `.../jobs/<id>/trace` (via a small `python3 -I` script)
- Read `~/.claude/skills/gitlab-ci-loop/SKILL.md` (first 120 lines) and the head of master-gcp-repo's `.agent-ci.yml`.

Not measured: act and gitlab-ci-local sizes and times (not installed, per the brief; the figures above are estimates from memory of their docs and release pages, not fetched in this session). The 39450849482 segfault cause and the `prod-promotion-gate` local reproducibility were not established.
