# Parallel-safety audit of the test jobs (2026-11-11 fast-test-suite)

Spec section 2: every job must be safe to run concurrently with every other under `tools/tests/all.zsh`. The runner gives each job its own `TMPDIR` and `TC_STATE` under one run dir.

**Checks (grep over the test sources, then a run of every job alone):** fixed `/tmp/...` paths; writes under `~/.claude`, `~/.local/state` or `$HOME`; fixed ports (`TMUX_DASH_PORT`, literal ports); fixed tmux socket names (`-L <literal>`); env read at import that another module supplies (the Task 2 pattern); the real `~/.claude/projects` or usage index.

**Findings in short:** no fixed `/tmp` write, literal tmux socket or shared port survives; sockets are `<name>-<pid>` or tt_setup's `tctest-<pid>-<rand>`, ports now come from `bind(("127.0.0.1", 0))`. Defects found and fixed:
- import-order `TMUX_DASH_TOKEN` (Task 2) and the sleep counter in the no-wait stop test (part A);
- `tt_wait <s> test "$(cmd)" = x` evaluates the substitution once, so it was a blind wait of the full cap and failed on a loaded machine (ctl_lanes, ctl_panes, ctl_relay, e2e, layout, run_long_line, tasks_window, teammate_window): the waits now poll (new `tt_pane_is` in lib.zsh, small `have…` functions);
- `random 20000 + RANDOM % 20000` ports in test_dedicated_server and test_repo_paths: now `tt_free_port` (bind to port 0, new lib.zsh helper);
- test_fresh_path: under all.zsh the tmux socket path under the per-job TMPDIR exceeded macOS's 104-byte unix socket limit, so `dev` never started (failed in every parallel run, green alone): short mktemp TMUX_TMPDIR, and all.zsh now names per-job TMPDIRs `<rundir>/tmp/<n>`;
- test_ctl_busy: a pane script that slept 8 s was over before the check under load (now 90 s, interrupted with C-c) and `run -t 5` timed out (now 60);
- test_telegram_always_on (the ghost-check flake): four fixed `sleep 1.5` waits are `tt_wait 20 drawn`;
- test_bg_lock: `# serial` (its "send returns fast" check is a 2 s latency bound; it failed at 1.3-3 s whenever other jobs loaded the machine);
- all.zsh: the verdict line broke with two or more failed jobs (`J_name[$failed]` is arithmetic); fixed and covered by a test (M3 and M4 of Task 3 are also fixed: see the test_all_runner row).

**Part B (zsh) scope:** the 57 `zsh/*` jobs, including the files Tasks 4b/5 split (`test_bg*`, `test_ctl_approve*`, `bg_common.zsh` and `approve_common.zsh` are sourced helpers, not jobs).

**Alone check:** all 66 non-zsh jobs and all 57 zsh jobs run one at a time with the exact `all.zsh --list` command. The zsh jobs were first run 4 at a time while the machine was at load average 15-27 (other agents): 49 passed and 8 failed on timing (fresh_path, ctl_interrupt, e2e, bg_lock, ctl_busy, run_long_line, teammate_window, ctl_lanes); those 8 were then run strictly one at a time and all 8 pass (see the rows for what was hardened).

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
| board/test_metrics_backfill_privacy | runs the other test_metrics_* files (one subprocess each, all at once) with their own `TMPDIR`-based scratch dirs and a tmp sink; reads the committed docs/superpowers/metrics/runs.jsonl read-only; solo 46-51 s under load 5-9 (inherent: it re-runs six sibling files, ~90 s of CPU) | none needed; sweeps print `checked 14 lines` and `checked 509 lines`, equal before and after the split | no |
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
| board/test_worktree_lock | was a flake in test_live_non_claude_pid_is_stale (1 failure in 72 runs at 24 concurrent): the `listed()` helper searched `git worktree list` output for "w1", and the random temp dir in the repo path can contain "w1", so the removed worktree still looked listed. No shared state | `listed()` matches worktree dir names from `--porcelain` output; verified red with TMPDIR containing `w1` (2 failures) and green after, plus 3 clean solo runs | no |
| board/test_worktree_safety_classify | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_ignored | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_recent | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_squash | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| board/test_worktree_safety_sweep | tmp dirs (tempfile), env patched with mock.patch.dict, no fixed port/socket/path found by grep | none needed | no |
| tools/test_install_lib.py | strings mention ~/.claude, ~/.local/bin; operates on tmp files only | none needed | no |
| tools/test_telegram_watch.py | reads (never writes) ~/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist and asserts its mtime is unchanged by the test | none needed; the real plist only changes if the user installs the watcher mid-run | no |
| skill/docs-architecture | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| skill/docs-compose | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| skill/docs-report | tests/ read fixtures in the skill dir, tmp dirs only | none needed | no |
| statusline | tmp dirs only | none needed | no |
| hooks/test-context-size-guard.sh | reads $HOME/.claude/projects/*/48822fd2*.jsonl (read-only, skips if absent); its leak check counted files in the real ~/.local/state/agent-board/context-guard, which a live Claude session writing there mid-run would change | every hook run now has HOME pointed at a temp dir and the leak check counts that dir's default state root (the hook already honours CLAUDE_CONTEXT_GUARD_STATE, which the test sets); 36 checks before and after | no |
| hooks/test-revise-claude-md-nudge.sh | runs $HOME/.claude/hooks/revise-claude-md-nudge.py (read-only) | none needed | no |
| hooks/test-spawn-record.sh | leak check on the real ~/.local/state/agent-board/spawns.jsonl: skipped when it already existed, so a live spawn cannot fail it | none needed | no |
| hooks/test-superpowers-hook.sh | mktemp -d; state env pointed into it | none needed | no |
| hooks/test-task-observer-review.sh | mktemp -d; state env pointed into it | none needed | no |
| hooks/test-task-observer-session-start.sh | reads the real task-observer workspace README (read-only) | none needed | no |
| hooks/test-telegram-env-scrub.sh | mktemp -d; state env pointed into it | none needed | no |
| zsh/test_agent_cleanup.zsh | mktemp scratch repos and worktrees; AW_STATE_DIR under the scratch dir (the sweep log never goes to ~/.local/state); fzf stub | none needed | no |
| zsh/test_agent_env.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); HOME set to a scratch dir for the hook | none needed | no |
| zsh/test_agent_launch.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); task text carries $HOME/`id` only as quoted data | none needed | no |
| zsh/test_agent_model.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_agent_name_guard.zsh | mktemp scratch; the JSON payload's cwd "/tmp" is data, never opened | none needed | no |
| zsh/test_all_runner.zsh | own mktemp root (SCR) with fake layouts; nested all.zsh runs get TMPDIR/TC_STATE pointed at it; TERM and dead-job cases kill only the PIDs the stubs recorded; ~49 s solo; its concurrency check (M3) flaked under load | M3: the -j 2 cap check now uses 6 one-second jobs so two overlap at any load; M4: python stubs log TMPDIR/TC_STATE/cwd too (env check covers 12 jobs, was 6); verdict with two failures fixed (J_name[$failed]) and tested | no |
| zsh/test_artifact_hook.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); HOME=$TT_DIR/home scratch with its own ~/.local/state/agent-board/handoffs and ~/.claude/handoffs | none needed | no |
| zsh/test_bg_fresh.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp) | none needed | no |
| zsh/test_bg_interrupt.zsh | private server via bg_common.zsh -> lib.zsh tt_setup; the hidden tt-bg session and run records live on that server's TC_STATE; 6 tight 0.01 s polls (CPU only) | none needed | no |
| zsh/test_bg_lock.zsh | private server via bg_common.zsh; run lock under its TC_STATE. "send returns fast" asserts a 2 s latency bound, which failed at 1.3-3 s when other jobs loaded the machine | `# serial` in the first 5 lines (latency bound, would fail under -j load); the lock and prompt checks are unaffected | yes (latency bound) |
| zsh/test_bg_parallel.zsh | private server via bg_common.zsh; the concurrent run pairs are inside its own tt-bg session (20 s solo) | none needed | no |
| zsh/test_bg.zsh | private server via bg_common.zsh; run records under its TC_STATE | none needed | no |
| zsh/test_claude_config_link.zsh | HOME=<mktemp scratch> for every run; reads the real ~/.claude/CLAUDE.md and settings.json (ls -l before/after) to assert they are untouched: read-only, fails only if the user edits them mid-run | none needed | no |
| zsh/test_claude_orchestrator_tg.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); HOME=$RT scratch; the telegram launcher heals a .mcp.json under CLAUDE_CONFIG_DIR (scratch) | none needed | no |
| zsh/test_context_inject.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); payload paths /tmp/none.jsonl and cwd /tmp are nonexistent/unused data | none needed | no |
| zsh/test_ctl_approve_expect.zsh | private server via approve_common.zsh; windows and fixtures under S=mktemp ttap.*; fixtures read-only | none needed | no |
| zsh/test_ctl_approve_misc.zsh | private server via approve_common.zsh; windows and fixtures under S=mktemp ttap.* | none needed | no |
| zsh/test_ctl_approve_spoof.zsh | private server via approve_common.zsh; windows and fixtures under S=mktemp ttap.* | none needed | no |
| zsh/test_ctl_approve.zsh | private server via approve_common.zsh; windows and fixtures under S=mktemp ttap.* | none needed | no |
| zsh/test_ctl_artifact.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_ctl_awake.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); caffeinate/pmset/sudo are stubs on a temp PATH; stub processes are found with pgrep -f "$S/real/" (a unique mktemp path) and cleanup kills only those; 27 s solo | none needed | no |
| zsh/test_ctl_busy.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup). Failed under 4 parallel jobs: the pane script slept 8 s and was over before `run` looked, `run -t 5` timed out, and `tt_wait 3` waits were too short | script now sleeps 90 s and is interrupted with C-c; `run -t 60`; waits 20 s | no |
| zsh/test_ctl_context.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp) | none needed | no |
| zsh/test_ctl_interrupt.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp). Failed once at 4 parallel jobs ("log has the output so far") | fixed `sleep 5` before "no stale .rc after a late _done" became a wait for the command's end marker (it failed in a parallel run: the late command had not finished) | no |
| zsh/test_ctl_lanes.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup). `tt_wait 3 test "$(tt display …)" = sleep` evaluated its substitution once, so it was a blind 3 s wait: "both busy -> exit 2" failed under load | 6 waits now poll tt_pane_is (new lib.zsh helper, 20 s); the busy `sleep 30` panes are `sleep 120` (30 s was over before the check under load: "both busy -> exit 2" failed), still interrupted with C-c | no |
| zsh/test_ctl_opts.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_ctl_panes.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup). Same once-evaluated `tt_wait 3 test "$(…)"` | polls tt_pane_is | no |
| zsh/test_ctl_relay.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp); TC_LINEAGE under the scratch dir. Same once-evaluated `tt_wait 10 test -n "$(…)"`; 33 s solo | polls a has_sleep function (20 s) | no |
| zsh/test_ctl_telegram.zsh | HOME=<mktemp scratch>; `claude` is a stub on a temp PATH; the stub poller is `exec -a "bun server.ts" sleep 600`, found by `pgrep -f '^bun server.ts'` (a fixed name, started by this file only: no other job starts one); reads nothing under the real HOME | none needed | no |
| zsh/test_dedicated_server.zsh | three scratch sockets named with $$; HOME=<scratch>; board on TMUX_DASH_PORT=20000+RANDOM%20000 (two jobs could draw the same port) | port from tt_free_port (bind 127.0.0.1:0, new lib.zsh helper) | no |
| zsh/test_e2e_isolation.zsh | own scratch servers and HOME/TMPDIR; reads the real -L agent-board server's session count and sha256 of the real ~/.claude/settings.json and ~/.tmux.conf before and after (read-only leak check: fails only if the user's board or those files change mid-run) | none needed | no |
| zsh/test_e2e.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); fixture ok.json with the real $HOME substituted as text only | the busy pane sleeps 120 s (was 30) and the wait polls tt_pane_is | no |
| zsh/test_fresh_path.zsh | scratch HOME, scratch socket name fp-<pid>-<rand>; TMUX_TMPDIR was $SCR/tmpdir: under all.zsh that path put the tmux socket past the 104-byte unix socket limit, so `dev` never started (failed in every parallel run, passes alone) | TMUX_TMPDIR is a short mktemp dir under /tmp (unique, removed in cleanup); the dev wait is 30 s; all.zsh also uses short per-job TMPDIRs ($rundir/tmp/<n>) | no |
| zsh/test_grouped.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_harness.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_hook_gate.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); kill-guard payload uses a pattern with $$ | none needed | no |
| zsh/test_hook_resolve.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); TMPDIR set to $TT_DIR/tmp so the hook-error log is scratch | none needed | no |
| zsh/test_install.zsh | mktemp scratch HOME for every install/migrate run (30 s solo) | none needed | no |
| zsh/test_kill_guard.zsh | mktemp scratch; fake claude processes carry GUARDPAT-$$/DECOYPAT-$$/NPMPAT-$$; its last case writes a marker to the real default state dir /tmp/tmux-ctl-<uid>/mods-active under a unique sid (kgtest-$$) and rmdirs the dirs only if empty: concurrent jobs cannot see that sid; at most a benign mkdir race | none needed | no |
| zsh/test_layout.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | the busy window sleeps 120 s (was 30); the wait polls tt_pane_is | no |
| zsh/test_mirror.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (twice); payload cwd "/tmp" is data | none needed | no |
| zsh/test_overseer.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); XDG_STATE_HOME=$TT_DIR/xdg; its sleeper is found with pgrep -f 'sleep [6]007' (only this file runs one) | none needed | no |
| zsh/test_plan_handoff_guard.zsh | mktemp scratch; synthetic transcripts only | none needed | no |
| zsh/test_plugin.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); reads repo files only (greps the rules and plugin manifest) | none needed | no |
| zsh/test_prompt_argv.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp); PATH-independent since Task 2 | fixed in Task 2 | no |
| zsh/test_repo_paths.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) + HOME=$RP_HOME scratch; board and ttyd ports were 20000+RANDOM%20000 and 40000+RANDOM%20000 | ports from tt_free_port | no |
| zsh/test_run_long_line.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp); `-C /tmp` / `cd /tmp` only set the cwd of a pane; `tt_wait 3 test "$(…)"` once-evaluated | polls tt_pane_is (20 s); "base window untouched" first waits for the base pane to stop drawing (two equal captures 0.5 s apart) | no |
| zsh/test_run_summary.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) | none needed | no |
| zsh/test_sdd_call_guard.zsh | mktemp scratch; synthetic transcripts; payload cwd "/tmp" is data | none needed | no |
| zsh/test_session_closed.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup) (+ mktemp) | none needed | no |
| zsh/test_superpowers_hook.zsh | mktemp scratch; HOME set to a scratch dir | none needed | no |
| zsh/test_tasks_window.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); once-evaluated `tt_wait 12 test -n "$(idx …)"` | polls a have_idx function (20 s) | no |
| zsh/test_tc_tmux_cwd.zsh | mktemp scratch; HOME set to a scratch dir | none needed | no |
| zsh/test_teammate_window.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); waits were once-evaluated (Task 5), 12 s caps failed at load | caps 30 s | no |
| zsh/test_telegram_always_on.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); scratch HOME and fake launchctl; its fake leads/servers carry MARK=tgfake-$$-$RANDOM (pgrep/kill by that mark); lists the real ~/Library/LaunchAgents read-only. Known flake: the ghost / refresh checks read the pane after a fixed `sleep 1.5` | 4 `sleep 1.5` replaced by `tt_wait 20 drawn` (the fake TUI has painted its input line); 31 s solo; "typed in the gap" types after 4 s into an 8 s gap (it typed at 1 s of a 3 s gap, before the watch's first capture on a loaded machine) | no |
| zsh/test_telegram_launcher.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); fake plugin roots, scratch CLAUDE_CONFIG_DIR and HOME | none needed | no |
| zsh/test_worktree_hook.zsh | private tmux server (tctest-<pid>-<rand>), TT_DIR/TC_STATE/CLAUDE_CONFIG_DIR/TC_LINEAGE under mktemp (lib.zsh tt_setup); git repos under $W; leak check uses pgrep -f "$W/aw-" (unique path) | none needed | no |

## Part A runs (non-zsh suites: board, tools, skills, statusline, hooks; 65 jobs)

- `--serial`: ALL PASS 65 jobs, 12m6s (rc=4, over the 5 min budget).
- parallel 1 (after ad973bd): ALL PASS 65 jobs, 5m35s (rc=4).
- parallel 2: ALL PASS 65 jobs, 6m57s (rc=4).
- parallel, before ad973bd (twice): FAIL 1/65, board/test_worktree_board_remove.

(These runs predate the split of the backfill privacy sweep, so they count 65 non-zsh jobs; `--list` now shows 66.)

The machine was loaded by other work during every run (load average 5-8), so the wall times are upper bounds. Slowest jobs: `board/test_metrics_backfill` (157 s serial), `board/test_metrics_record_git` (49 s), `board/test_metrics_record_usage` (48 s), `board/test_metrics_decide` (35 s), `board/test_metrics_report` (about 160 s under parallel load); none is covered by Tasks 4-5.
