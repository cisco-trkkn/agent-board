# Parallel-safety audit of the test jobs (2026-11-11 fast-test-suite)

Spec section 2: every job must be safe to run concurrently with every other under `tools/tests/all.zsh`. The runner gives each job its own `TMPDIR` and `TC_STATE` under one run dir.

**Checks (grep over the test sources, then a run of every job alone):** fixed `/tmp/...` paths; writes under `~/.claude`, `~/.local/state` or `$HOME`; fixed ports (`TMUX_DASH_PORT`, literal ports); fixed tmux socket names (`-L <literal>`); env read at import that another module supplies (the Task 2 pattern); the real `~/.claude/projects` or usage index.

**Findings in short:** no fixed port, `/tmp` write or literal tmux socket in a non-zsh job (sockets are `<name>-<pid>`, ports come from `bind(("127.0.0.1", 0))`). Two defects found and fixed: the import-order `TMUX_DASH_TOKEN` (Task 2) and the sleep counter in the no-wait stop test (this task, ad973bd). Read-only touches of real state are listed per row.

**Part A scope (this version):** every job except `zsh/*`; the 54 `zsh/*` rows are placeholders for part B.

**Alone check:** all 65 non-zsh jobs run one at a time (4 concurrent processes, plain environment, from the checkout) with the exact `all.zsh --list` command: 65 of 65 exit 0.

**Test-count method:** for each job log, the sum of `Ran N tests` lines, or, for a bash/zsh file with none, the count of lines starting `PASS` or `ok`. Non-zsh total from the alone run: **1345** over 65 jobs. Parallel and `--serial` runs of `all.zsh` print job counts only, so the equality of test counts is argued from "same job list, every job exit 0".

| job | shared state found | fix | serial? |
| --- | --- | --- | --- |
| board/test_activity | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_agent_controls | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_agent_spawn | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_artifacts_switch | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_artifacts | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_context | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_dirs | reads ~ (list_dirs("~")), read-only | none needed | no |
| board/test_gitlab_sync | asserts conf_path() under Path.home(), no write | none needed | no |
| board/test_ideas_actions | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas_dropped_ui | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas_gitlab_ui | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas_issue | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas_kick | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas_switch | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_ideas | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_backfill | reads the real usage snapshot ~/.local/state/agent-board/metrics/usage-snapshot-*.sqlite and copies it first (read-only; skips if absent); PrivacySweep reads $HOME only to assert it is absent from output | none needed | no |
| board/test_metrics_decide | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_fixwave | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_log | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_record_git | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_record_usage | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_metrics_report | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_notify | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_orchestrator_path | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_overseer | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_overview_api | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_overview_home_ui | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_overview | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_paneclass | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_planview | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_poll_efficiency | tmux socket poll-<pid>, free port, TC_STATE under its tmp | none needed | no |
| board/test_relay | tmux socket relay-root-<pid>; lineage dir is a tmp dir | none needed | no |
| board/test_reload | tmux socket reload-<pid>, free ports for board and ttyd, TC_STATE under its tmp | none needed | no |
| board/test_restart_orchestrator | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_server_bind | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_session_path | TMUX_DASH_TOKEN at import (Task 2); socket sesspath-<pid> | fixed in Task 2 (os.environ.setdefault in the module) | no |
| board/test_session_root_path | TMUX_DASH_TOKEN at import (Task 2) | fixed in Task 2 | no |
| board/test_taskwin_cli | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_taskwin_state | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_taskwin | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_tc_env | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_telegram_badge | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_terminal_session | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_usage | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_board_remove | StopWaitsForExit counted every time.sleep call, including subprocess internals (sleep(0.001)) under parallel load: failed in two parallel runs | test counts only sleeps called from server.py (commit ad973bd) | no |
| board/test_worktree_board | real git/sleep subprocesses in tmp dirs only | none needed | no |
| board/test_worktree_lock | known flake under load: test_live_non_claude_pid_is_stale races real pids (sleep/ps); no shared files | Task 6 part B watches the parallel runs; marked only if it repeats | no |
| board/test_worktree_safety_classify | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_ignored | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_recent | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_squash | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_sweep | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| zsh/test_agent_cleanup.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_agent_env.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_agent_launch.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_agent_model.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_agent_name_guard.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_all_runner.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_artifact_hook.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_bg_fresh.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_bg_interrupt.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_bg_lock.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_bg_parallel.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_bg.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_claude_config_link.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_claude_orchestrator_tg.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_context_inject.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_approve.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_artifact.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_awake.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_busy.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_context.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_interrupt.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_lanes.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_opts.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_panes.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_relay.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_ctl_telegram.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_dedicated_server.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_e2e_isolation.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_e2e.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_fresh_path.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_grouped.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_harness.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_hook_gate.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_hook_resolve.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_install.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_kill_guard.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_layout.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_mirror.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_overseer.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_plan_handoff_guard.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_plugin.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_prompt_argv.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_repo_paths.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_run_long_line.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_run_summary.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_sdd_call_guard.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_session_closed.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_superpowers_hook.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_tasks_window.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_tc_tmux_cwd.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_teammate_window.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_telegram_always_on.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_telegram_launcher.zsh | pending (part B) | pending (part B) | pending (part B) |
| zsh/test_worktree_hook.zsh | pending (part B) | pending (part B) | pending (part B) |
| tools/test_install_lib.py | strings mention ~/.claude, ~/.local/bin; operates on tmp files only | none needed | no |
| tools/test_telegram_watch.py | reads (never writes) ~/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist and asserts its mtime is unchanged by the test | none needed; the real plist only changes if the user installs the watcher mid-run | no |
| skill/docs-architecture | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| skill/docs-compose | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| skill/docs-report | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| statusline | tmp dirs only | none needed | no |
| hooks/test-context-size-guard.sh | reads $HOME/.claude/projects/*/48822fd2*.jsonl (read-only, skips if absent); leak check counts files in the real ~/.local/state/agent-board/context-guard before/after, so a live Claude session writing there during the run would fail it | left as is: a live session writes there only on its own context events; noted as the one real-state dependency | no |
| hooks/test-revise-claude-md-nudge.sh | runs $HOME/.claude/hooks/revise-claude-md-nudge.py (read-only) | none needed | no |
| hooks/test-spawn-record.sh | leak check on the real ~/.local/state/agent-board/spawns.jsonl: skipped when it already existed, so a live spawn cannot fail it | none needed | no |
| hooks/test-superpowers-hook.sh | mktemp -d; state env pointed into it | none needed | no |
| hooks/test-task-observer-review.sh | mktemp -d; state env pointed into it | none needed | no |
| hooks/test-task-observer-session-start.sh | reads the real task-observer workspace README (read-only) | none needed | no |
| hooks/test-telegram-env-scrub.sh | mktemp -d; state env pointed into it | none needed | no |

## Part A runs (non-zsh suites: board, tools, skills, statusline, hooks; 65 jobs)

| run | verdict | wall |
| --- | --- | --- |
| `--serial` | ALL PASS 65 jobs | 12m6s (rc=4, over the 5 min budget) |
| parallel 1 (after ad973bd) | ALL PASS 65 jobs | 5m35s (rc=4) |
| parallel 2 | ALL PASS 65 jobs | 6m57s (rc=4) |
| parallel, before ad973bd (twice) | FAIL 1/65: board/test_worktree_board_remove | n/a |

The machine was loaded by other work during every run (load average 5-8), so the wall times are upper bounds. Slowest jobs: `board/test_metrics_backfill` (157 s serial), `board/test_metrics_record_git` (49 s), `board/test_metrics_record_usage` (48 s), `board/test_metrics_decide` (35 s), `board/test_metrics_report` (about 160 s under parallel load); none is covered by Tasks 4-5.
