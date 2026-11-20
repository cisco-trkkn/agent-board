# Lead recovery and the /lead, /tasks, /gauth commands: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a lead without a terminal: relay works from an idle lead in any lead window, `tmux-ctl lead-restart` restarts a lead pane, the Discord bot is handed over between leads, and the phone gets `/lead`, `/tasks` and `/gauth`.

**Architecture:** Shell side: `bin/tmux-ctl` (relay, `lead-restart`, `gauth`), `bin/claude-orchestrator` (bot wait), with the logic in Python (`board/relay.py`, `board/gauth.py`). Watch side: `tools/discord_watch.py` gains a project-keyed repair. Discord side: the bridge answers `/tasks` and `/lead status` from `views.json` (as `/queue` today); `/lead restart|handoff` and `/gauth` go through slash/click/modal events to `board/discord_ops.py`, which answers through a new `ireply` outbox op that edits the private interaction reply the bridge holds in memory.

**Tech Stack:** zsh, Python 3 (stdlib, unittest), Node (discord.js, `node --test`), tmux.

**Spec:** `docs/superpowers/specs/2026-11-19-lead-recovery-discord-commands-design.md`

## Global Constraints

- The spec's decisions D1-D5 stand. Lead rulings below (R1-R7) settle what the spec left open or what the code does not allow; they were sent to the user on Discord on 2026-11-20 with an "object N" option.
- Nothing from Discord text becomes a command-line flag or a shell word: `/gauth` builds its command from `<agent_base>/gauth/<project>.json` only; the code is typed with `send-keys -l`.
- Every Discord command checks `allowFrom` first and writes an audit line (`discord_feed.audit_append`).
- Never print or log a token: the gauth token check reports `token ok` or the error text only.
- zsh rules: never name a variable `path`; brace variables before `:`; quote `=name` tmux targets; scratch tmux servers start with `-f /dev/null` (tests use `tools/tests/lib.zsh` `tt_setup`).
- `bin/tmux-ctl` `help` prints a fixed line range (`sed -n '2,70p'`): every new help line raises that range, and its tests stay green.
- Commits: conventional with scope; end with the attribution trailer your harness specifies.
- The live install runs from the main checkout: work only in the worktree `.claude/worktrees/lead-recovery-discord-commands`.

**Lead rulings (R):**
- R1 (/gauth code): Discord cannot reply to an ephemeral message, so the code arrives through a private modal: the private `/gauth` reply carries the sign-in URL and an `Enter code` button (`ab:gauth:code:<project>`); the button opens a modal (`ab:modal:gauth:<project>`, one short text input). Only the user who ran `/gauth`, within 10 min of the URL post, is accepted. Nothing to delete.
- R2 (answers from Python): a new outbox op `ireply {iid, content, components?}`. The bridge keeps each deferred `/lead` Confirm click and `/gauth` interaction in memory by interaction id for 14 min; `ireply` calls `editReply` on it. Unknown or expired iid (bridge restarted): the bridge posts `content` as a normal channel message instead and logs `ireply <iid> fell back to post`.
- R3 (lead pane): `claude` window, else `claude-next` window, in the project's (non-bg) session. The spec's "project's lead mark" does not exist: dropped.
- R4 (lead-restart command): `respawn-pane -k -t <pane> -c <root> "<orch> <args>; exec <login shell> -l"`, so the window survives Claude's exit; nothing is typed.
- R5 (allow rule): `Bash(tmux-ctl:*)` already in `claude/settings.json` covers `lead-restart`: no new rule. The task checks it is still there.
- R6 (session id for `--resume`): from `~/.claude/sessions/*.json` whose `tmux` field ends with the pane id (newest `updatedAt`), else a fresh `<state>/agent-status/*.json` whose `pane` is the pane. None: exit 1.
- R7 (relay from a lead's own pane): accepted when `$AGENT_BOARD_LEAD == 1`, `$TMUX_PANE`'s window is named `claude` or `claude-next`, is in session `$FEEDKEY`, and is not flagged `@tc_teammate`. A `claude-next` window is renamed to `claude` before the detached relay starts.

**User decisions (already made):** D1-D5 of the spec (one spec; fixed gauth command from config; status at once, restart/handoff with Confirm; 60 s wait then watch repair with `--resume`, idle only; design approved as sent).

---

### Task 1: Relay busy bug: reproduce on a real capture and fix

**Goal:** `relay.wait_turn_end` reads an idle lead (task list under its input box, status rows below) as ended.

**Files:**
- Create: `board/tests/fixtures/relay/idle-lead-tasklist.txt` (+ a working-lead capture `working-lead.txt`)
- Modify: `board/paneclass.py` or `board/relay.py` (whichever owns the misread)
- Test: `board/tests/test_relay.py`, `board/tests/test_paneclass.py`

**Acceptance Criteria:**
- [ ] Both fixtures are real captures (`capture-pane -p -J -S -40` of a live lead pane, read-only; the lead's own pane `%138` shows a task list under its input box), not hand-written
- [ ] The cause is named in the report with evidence (which branch of `classify` or `wait_turn_end` misread it; a candidate is a fresh agent-status `busy` record winning over an idle screen, `paneclass.classify` ~187-191)
- [ ] `wait_turn_end` on the idle fixture returns True; on the working fixture it keeps waiting (False at cap with a fake clock)
- [ ] If the capture already reads as ended on main, the report says so and the fixture is kept as a regression test
- [ ] Each new test of a guard names the mutation that makes it fail

**Verify:** `python3 -m unittest board.tests.test_relay board.tests.test_paneclass` → `OK`

**Steps:**
- [ ] `superpowers-extended-cc:systematic-debugging`: capture, run `paneclass.pane_status`'s `classify` on the capture (with and without a `mod` record), find the misread.
- [ ] RED test from the captures, fix, GREEN, full `python3 -m unittest discover -s board/tests`.
- [ ] Commit `fix(relay): an idle lead with a task list reads as ended`.

```json:metadata
{"files": ["board/paneclass.py", "board/relay.py", "board/tests/test_relay.py", "board/tests/test_paneclass.py", "board/tests/fixtures/relay/"], "verifyCommand": "python3 -m unittest board.tests.test_relay board.tests.test_paneclass", "acceptanceCriteria": ["fixtures are real captures", "cause named with evidence", "idle fixture ends the wait; working fixture does not", "no-bug case recorded as regression test", "guard tests name their mutation"], "modelTier": "standard"}
```

### Task 2: Relay from the lead's own pane in a `claude-next` window

**Goal:** `tmux-ctl relay` run by the lead in a window named `claude-next` renames it to `claude` and relays; a non-lead caller is still refused.

**Files:**
- Modify: `bin/tmux-ctl` (relay case, ~651-676; help lines)
- Modify: `claude/skills/tmux-orchestrator/SKILL.md` (~39), `claude/plugin/skills/tmux-orchestrator/SKILL.md` (~40): the relay row says "the lead's own window (`claude` or `claude-next`)"
- Test: `tools/tests/test_ctl_relay.zsh`

**Acceptance Criteria:**
- [ ] R7's rule is implemented exactly: `AGENT_BOARD_LEAD=1`, window `claude` or `claude-next`, session `$FEEDKEY`, not `@tc_teammate`
- [ ] A lead in `claude-next`: the window is renamed `claude` before the detached `relay.py` runs, and the stub orchestrator is started with the doc
- [ ] A worker pane, a teammate-flagged `claude-next` window, and a `claude-next` caller without `AGENT_BOARD_LEAD=1` are each refused with exit 2 and the window keeps its name
- [ ] `tmux-ctl help` still passes its tests

**Verify:** `zsh tools/tests/test_ctl_relay.zsh` → last line `ALL PASS`

**Steps:**
- [ ] RED cases in `test_ctl_relay.zsh` (model: its existing refusal and lead cases; `tt_setup claude worker`, then `tt rename-window` to `claude-next`).
- [ ] Implement in the relay case; rename with `t rename-window -t "$TMUX_PANE" claude`.
- [ ] Commit `feat(tmux-ctl): relay from the lead's own claude-next window`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_relay.zsh", "claude/skills/tmux-orchestrator/SKILL.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md"], "verifyCommand": "zsh tools/tests/test_ctl_relay.zsh", "acceptanceCriteria": ["R7 rule exact", "claude-next lead renamed then relayed", "worker / teammate / non-lead refused, name unchanged", "help tests green"], "modelTier": "standard"}
```

### Task 3: `tmux-ctl lead-restart <project> [--resume | --doc <handoff>]`

**Goal:** Restart a project's lead pane with the command as the pane command, per spec §2 and R3, R4, R6.

**Files:**
- Modify: `board/relay.py` (new: `lead_pane(tmux, project)`, `session_for_pane(pane, home, state)`, `newest_handoff(root, dir)`, `restart_lead(...)`, a `lead-restart` CLI mode in `main`)
- Modify: `bin/tmux-ctl` (new `lead-restart)` case after `relay`; line-107 exemption so it runs outside tmux with the project as `$1`; help lines)
- Create: `tools/tests/test_ctl_lead_restart.zsh`
- Test: `board/tests/test_relay.py`

**Acceptance Criteria:**
- [ ] Pane: `claude`, else `claude-next` (R3); none → exit 1 `lead-restart: no lead pane for <project>`, nothing changed
- [ ] `--resume`: argv is `--resume <id>` with R6's id; no id → exit 1, nothing renamed or respawned
- [ ] No flag or `--doc`: prompt `Read <doc> and continue from where the previous session left off.`; default doc = newest `handoffs/*.md` (not `drafts/`) whose first line is `Project: <root>`; another project's newer doc is ignored; none → exit 1
- [ ] The respawn is `respawn-pane -k -t <pane> -c <root> "<orch> <args>; exec <login shell> -l"` (R4); no `send-keys` is issued (the stub records its argv; the test asserts the pane's `#{pane_start_command}` contains the orchestrator path)
- [ ] `claude-next` is renamed to `claude` before the respawn
- [ ] Waits up to 60 s with `relay.wait_started(..., cap=60)`, then prints `lead-restart: <project> restarted (<resume <id>|doc <name>>); bot: held by the new lead | not held | no bot` (bot via `tools/lib/discord.zsh` `dc_holder`; `no bot` when the project has no token); exit 0 when started even if the bot is not held
- [ ] Runs outside tmux (`env -u TMUX`), with `TMUX_DASH_TMUX_ARGS`/socket as tests need
- [ ] `claude/settings.json` still allows `Bash(tmux-ctl:*)` (R5): asserted by a test line

**Verify:** `zsh tools/tests/test_ctl_lead_restart.zsh && python3 -m unittest board.tests.test_relay` → `ALL PASS` then `OK`

**Steps:**
- [ ] RED: unit tests for the four helpers (fake tmux recorder, temp handoff dir with two projects' docs aged with `os.utime`, temp `sessions/*.json`); zsh test with a stub `claude-orchestrator` that records argv then `exec sleep 600` (model: `test_ctl_relay.zsh`).
- [ ] Implement; GREEN; `zsh tools/tests/test_ctl_relay.zsh` still green.
- [ ] Commit `feat(tmux-ctl): lead-restart restarts a project's lead pane`.

```json:metadata
{"files": ["board/relay.py", "bin/tmux-ctl", "tools/tests/test_ctl_lead_restart.zsh", "board/tests/test_relay.py"], "verifyCommand": "zsh tools/tests/test_ctl_lead_restart.zsh && python3 -m unittest board.tests.test_relay", "acceptanceCriteria": ["pane lookup R3, none exits 1 unchanged", "--resume uses R6 id, none exits 1 unchanged", "newest matching handoff, other project ignored", "command is the respawn command, nothing typed", "claude-next renamed first", "prints result line, exit 0 when started", "runs outside tmux", "Bash(tmux-ctl:*) still allowed"], "modelTier": "standard"}
```

### Task 4: `claude-orchestrator` waits for the old lead to release the bot

**Goal:** A new lead whose bot is held by the same project's lead in another pane polls for up to 60 s and then takes the bot (spec §3 first bullet).

**Files:**
- Modify: `bin/claude-orchestrator` (~47-58)
- Test: `tools/tests/test_claude_orchestrator_dc.zsh` (holder fakes: model `tools/tests/test_discord_holder.zsh`)

**Acceptance Criteria:**
- [ ] Wait only when the holder pane is in the same project (session or group, `-bg` stripped) and its window is `claude` or `claude-next`; poll `dc_holder` every `${TC_DC_POLL:-2}` s up to `${TC_DC_WAIT:-60}` s
- [ ] Holder releases within the wait → the lead starts with `--channels plugin:discord…` and `DISCORD_STATE_DIR`
- [ ] Holder never releases → starts without the channel after the wait, with today's message
- [ ] Holder in another project or another process → no wait at all (test asserts elapsed < 1 s with `TC_DC_WAIT=5`)

**Verify:** `zsh tools/tests/test_claude_orchestrator_dc.zsh` → last line `ALL PASS`

**Steps:**
- [ ] RED cases with a fake holder process (`DISCORD_STATE_DIR=<dir>` in its env, killed after N s for the release case), `TC_DC_WAIT=4 TC_DC_POLL=1`.
- [ ] Implement; GREEN; commit `feat(orchestrator): wait for the same project's old lead to release the bot`.

```json:metadata
{"files": ["bin/claude-orchestrator", "tools/tests/test_claude_orchestrator_dc.zsh"], "verifyCommand": "zsh tools/tests/test_claude_orchestrator_dc.zsh", "acceptanceCriteria": ["waits only for same-project lead window", "release within wait takes the bot", "no release starts without it after the wait", "other project/process not waited on"], "modelTier": "standard"}
```

### Task 5: discord-watch restarts a bot-less idle lead

**Goal:** Spec §3 watch repair: for each project with a bot token, nobody holding the bot, and a lead pane running Claude without the discord channel that is idle on two runs in a row, run `tmux-ctl lead-restart <project> --resume`; at most once per project per 15 min.

**Files:**
- Modify: `tools/discord_watch.py` (new pass in `watch_once`, new kwargs seams `projects=`, `holder=`, `restart=`; project-keyed state keys `idle_seen`, `restarted` that `prune` keeps)
- Test: `tools/tests/test_discord_watch.py`

**Acceptance Criteria:**
- [ ] Restart on the second idle run, not the first
- [ ] Busy lead, held bot, a pane already running with `--channels plugin:discord`, a teammate window (only `claude`/`claude-next` windows count): no restart
- [ ] 15-minute cap per project holds (fake `now`)
- [ ] After success, posts `<project> lead reconnected to Discord` through the bridge (outbox `post` via `discord_feed`), and logs it; a failure is logged and bannered (`notify`)
- [ ] Old reconnect path and its tests unchanged

**Verify:** `python3 -m unittest discover -s tools/tests -p 'test_discord_watch.py'` → `OK`

**Steps:**
- [ ] RED tests in class `Once` style (inject `projects`, `holder`, `restart`, `pane_idle`); implement; GREEN; commit `feat(discord-watch): restart a bot-less idle lead with --resume`.

```json:metadata
{"files": ["tools/discord_watch.py", "tools/tests/test_discord_watch.py"], "verifyCommand": "python3 -m unittest discover -s tools/tests -p 'test_discord_watch.py'", "acceptanceCriteria": ["second idle run restarts, first does not", "busy/held/has-channel/teammate not restarted", "15-min cap per project", "success posts and logs; failure logs and banners", "old reconnect unchanged"], "modelTier": "standard"}
```

### Task 6: views.json gains `tasks` and `leads`

**Goal:** `discord_ops.tick` writes per-project plan tasks and lead status into `views.json` so the bridge can answer `/tasks` and `/lead status` at once.

**Files:**
- Modify: `board/discord_ops.py` (`tick`, new `tasks_text`, `lead_view`), `board/server.py` (pass what `tick` needs: lead entries per project)
- Test: `board/tests/test_discord_ops.py` (update `test_views_json_shape_and_atomic`)

**Acceptance Criteria:**
- [ ] `views.json["tasks"][project]`: the running `Plan & run:` task's own tasks (`discord_feed.spec_floor` + `spec_progress` rule), one line each `#id status owner tier subject[:60]`, total ≤ 1800 chars, only for projects with a non-empty list
- [ ] `views.json["leads"][project]`: `{window, pane, pid, state (idle|busy|waiting), holds_bot, context_pct|null, session_id|null, doc|null, doc_age_s|null}`; context % from the statusLine tap (`usage.tap_entries`), doc = newest matching handoff (reuse Task 3's `relay.newest_handoff`)
- [ ] Holder lookups are cached so `tick` runs `ps` at most once per tick
- [ ] Existing views keys unchanged

**Verify:** `python3 -m unittest board.tests.test_discord_ops` → `OK`

**Steps:**
- [ ] RED tests with fake records/tasks; implement; GREEN; full `python3 -m unittest discover -s board/tests`; commit `feat(discord-ops): views carry plan tasks and lead status`.

```json:metadata
{"files": ["board/discord_ops.py", "board/server.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_ops", "acceptanceCriteria": ["tasks view per project, plan tasks only, capped", "leads view fields", "holder lookup once per tick", "existing keys unchanged"], "modelTier": "standard"}
```

### Task 7: Bridge: `/lead`, `/tasks`, `/gauth`, select menu, `ireply`

**Goal:** The bridge side of spec §4-6 with R1, R2.

**Files:**
- Modify: `tools/discord-bridge/lib/commands.js` (ACTIONS, NEEDS_PROJECT, DESCRIPTIONS, payload options: `/lead` with a required `action` string choice status|restart|handoff), `tools/discord-bridge/bridge.js` (routing for `ab:lead:*`, `ab:tasks:pick`, `ab:gauth:code:*`, `ab:modal:gauth:*`; interaction memory; `ireply` op), `board/discord_feed.py` (op kind `ireply` accepted by the outbox writer)
- Test: `tools/discord-bridge/test/commands.test.js`, `bridge.test.js` or `ops.test.js`, `test/fake-client.js` (select-menu interaction, `editReply`)

**Acceptance Criteria:**
- [ ] Strangers are refused (`Not authorized.`, `rejected` event) for every new command and component
- [ ] `/tasks <p>`: private fenced reply from `views.tasks[p]` (or `no task list for <p>`); `/tasks` alone: private reply with a string select of projects that have tasks; picking one gives the same reply
- [ ] `/lead status <p>`: private reply from `views.leads[p]`
- [ ] `/lead restart|handoff <p>`: private preview (`restart the <p> lead in window claude with --resume <id>; it is busy right now` / `start a fresh lead from <doc>, written N min ago`) with Confirm (`ab:lead:<action>:<p>:<ms>`) and Cancel; Cancel → `cancelled`; Confirm older than 5 min → `expired; run /lead again`, no event; Confirm in time → `deferUpdate`, interaction kept, event `{type:'slash', command:'lead', action, project, user, iid, ts}`
- [ ] `/gauth <p>`: `deferReply` private, interaction kept, event `{type:'slash', command:'gauth', project, user, iid, ts}`; `Enter code` button opens the modal; modal submit → event `{type:'modal', form:'gauth', project, user, text, ts}` and a private `Code sent.`
- [ ] `ireply` op edits the kept interaction; unknown/expired iid (> 14 min) falls back to a channel post and logs `ireply <iid> fell back to post`
- [ ] The command-name list test is updated to the new set

**Verify:** `cd tools/discord-bridge && npm test` → `# fail 0`

**Steps:**
- [ ] (fresh worktree: `npm ci` first). RED tests with the fake client; implement; GREEN; commit `feat(bridge): /lead, /tasks, /gauth and the ireply op`.

```json:metadata
{"files": ["tools/discord-bridge/lib/commands.js", "tools/discord-bridge/bridge.js", "board/discord_feed.py", "tools/discord-bridge/test/commands.test.js", "tools/discord-bridge/test/fake-client.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["strangers refused", "/tasks with and without project", "/lead status", "/lead restart|handoff preview, cancel, 5-min expiry, confirm event", "/gauth defer, code button, modal event", "ireply edit and fallback", "command list test updated"], "modelTier": "standard"}
```

### Task 8: `board/gauth.py` and `tmux-ctl gauth`

**Goal:** Spec §6 config, run, code, result, as a Python module with a zsh front end.

**Files:**
- Create: `board/gauth.py` (`load_config(project)`, `build_argv(cfg)`, `start(project)`, `read_url(project)`, `send_code(project, code)`, `result(project)`, `token_check(cfg)`, `close(project)`; state under `tc_env.agent_base()/gauth/`)
- Modify: `bin/tmux-ctl` (`gauth config <project> [--adc|--no-adc] [--impersonate <sa>] [--account <email>]` and `gauth start|status|close <project>`; tmux-free branch like `discord` for `config`; help lines)
- Create: `board/tests/test_gauth.py`

**Acceptance Criteria:**
- [ ] `build_argv` comes from the config only: `gcloud auth application-default login --no-launch-browser` (adc) or `gcloud auth login --no-launch-browser`, plus `--impersonate-service-account=<sa>`, plus `--account=<email>` for non-adc when set; fake `gcloud` on PATH records its argv
- [ ] No config → `no gauth config for <p>; set it at the terminal: tmux-ctl gauth config <p> …`
- [ ] `start` opens bg window `gauth-<p>` in `<p>-bg` (pattern `tools/lib/discord.zsh` `_dc_bridge`); a second `start` while one waits → `a /gauth for <p> is already waiting for its code`
- [ ] `read_url` returns the `https://accounts.google.com/…` URL from the window (fake gcloud prints a fixed URL then reads a line)
- [ ] `send_code` types with `send-keys -l -- <code>` then `Enter`; a code with spaces or `;` arrives as one literal line (fake gcloud echoes it)
- [ ] `result` returns the `Credentials saved` line or the error; `token_check` runs `print-access-token` with stdout discarded and returns `token ok` or the error; its output never contains the fake token
- [ ] `close` kills the window

**Verify:** `python3 -m unittest board.tests.test_gauth` → `OK`

**Steps:**
- [ ] RED tests (scratch tmux via `-L` + `-f /dev/null`, fake gcloud script in a temp dir on PATH); implement; GREEN; commit `feat(gauth): fixed-command Google re-auth in a bg window`.

```json:metadata
{"files": ["board/gauth.py", "bin/tmux-ctl", "board/tests/test_gauth.py"], "verifyCommand": "python3 -m unittest board.tests.test_gauth", "acceptanceCriteria": ["argv from config only", "no-config hint", "bg window; second start refused", "URL read", "code typed literally", "result and token check never print the token", "close kills window"], "modelTier": "standard"}
```

### Task 9: discord_ops handles `/lead` and `/gauth` events

**Goal:** Python side of the Confirm and gauth flows, answering with `ireply`.

**Files:**
- Modify: `board/discord_ops.py` (`handle_event`: `lead` and `gauth` slash before the unknown-project check where needed; `modal` form `gauth`; pending-gauth record `{project, user, iid, url_ts}` under the ops state dir)
- Test: `board/tests/test_discord_ops.py`

**Acceptance Criteria:**
- [ ] `lead` Confirm runs `tmux-ctl lead-restart <p> --resume` (restart) or `--doc <newest>` (handoff) via the injected `run`, and sends `ireply` with its printed line (or its error); audited
- [ ] `gauth` slash: no config → `ireply` with the hint; already waiting → `ireply` refusal; else `gauth.start`, poll `read_url` up to 30 s, `ireply` with the URL, the 10-min note and the `Enter code` button
- [ ] `gauth` modal: accepted only from the same user within 10 min of the URL; another user or late → ignored and audited (late also closes the window and says `timed out`); accepted → `send_code`, wait for `result`, `token_check`, `ireply`/post the outcome, `close`
- [ ] The code never appears in audit lines, logs or posts (test greps the audit file for the code)
- [ ] A timed-out waiting gauth is closed by `tick` (10 min)

**Verify:** `python3 -m unittest board.tests.test_discord_ops` → `OK`

**Steps:**
- [ ] RED tests with fake `run`, fake gauth module (`mock.patch`), fake clock; implement; GREEN; full board suite; commit `feat(discord-ops): /lead confirm and /gauth flows`.

```json:metadata
{"files": ["board/discord_ops.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_ops", "acceptanceCriteria": ["lead confirm runs lead-restart and ireplies", "gauth slash: hint / refusal / URL with button", "modal: same user within 10 min only", "code never logged", "tick closes timed-out gauth"], "modelTier": "standard"}
```

### Task 10: Agent rules for re-auth

**Goal:** Workers stop and tell the lead on Google auth errors; a remote lead points the user at `/gauth`.

**Files:**
- Modify: `claude/worker.md` (end of `## Processes`), `claude/orchestrator.md` (`## Remote: Discord`, "While remote:" list)

**Acceptance Criteria:**
- [ ] worker.md: one bullet: on `invalid_rapt`, `Reauthentication failed` or missing Google credentials, stop that step and message the lead
- [ ] orchestrator.md: one bullet: the lead posts `🔑 <project> needs Google re-auth: run /gauth <project>` and does not ask for the terminal while the user is remote
- [ ] One bullet in each tmux-orchestrator SKILL.md table: `tmux-ctl lead-restart <project> [--resume|--doc <d>]`

**Verify:** `grep -c 'invalid_rapt' claude/worker.md && grep -c '/gauth' claude/orchestrator.md && grep -c 'lead-restart' claude/skills/tmux-orchestrator/SKILL.md claude/plugin/skills/tmux-orchestrator/SKILL.md` → each ≥ 1

**Steps:**
- [ ] Edit the four files with the exact bullets above; run Verify; commit `docs(rules): re-auth goes through /gauth; lead-restart in the skill table`.

```json:metadata
{"files": ["claude/worker.md", "claude/orchestrator.md", "claude/skills/tmux-orchestrator/SKILL.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md"], "verifyCommand": "grep -c 'invalid_rapt' claude/worker.md && grep -c '/gauth' claude/orchestrator.md && grep -c 'lead-restart' claude/skills/tmux-orchestrator/SKILL.md claude/plugin/skills/tmux-orchestrator/SKILL.md", "acceptanceCriteria": ["worker bullet", "orchestrator bullet", "skill table rows"], "modelTier": "mechanical"}
```

### Task 11: Full suite and the gate runbook

**Goal:** Every suite green on the branch, and a runbook for the user gate.

**Files:**
- Create: `docs/superpowers/e2e/2026-11-20-lead-recovery-runbook.md`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` verdict line and rc (rc 4 = time budget only, stated); `cd tools/discord-bridge && npm test` `# fail 0`
- [ ] A read-only real-state check: `python3 -c` printing `relay.lead_pane` and `relay.session_for_pane` for the live `agent-board` session, and `discord_ops` lead view for it, matches `tmux display -p -t %<pane> '#{window_name}'`
- [ ] Runbook items, each with its command or phone action and the expected result: `/lead status agent-board`; `/lead restart` of an idle lead (bot held afterwards: `tmux-ctl discord status` `held by: <session>:claude`); `/tasks`; one real `/gauth signal-hub-gcp` (precondition: `tmux-ctl gauth config signal-hub-gcp --adc --impersonate cox-agent@trk-cox-data-dev.iam.gserviceaccount.com`, a human gate: the user must confirm the values)

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → verdict line `ALL PASS`, rc 0 or 4

**Steps:**
- [ ] Run suites; write the runbook; commit `docs(e2e): lead recovery runbook`.

```json:metadata
{"files": ["docs/superpowers/e2e/2026-11-20-lead-recovery-runbook.md"], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh and npm test green", "read-only real-state check matches tmux", "runbook items with commands and expected results"], "modelTier": "standard"}
```

### Task 12: User gate: lead recovery on the phone

**Goal:** The user runs the runbook's items on the phone after the merge.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none

**Acceptance Criteria:**
- [ ] `/lead status agent-board` answers privately with the lead's window, state and context %
- [ ] `/lead restart` of an idle lead restarts it and `tmux-ctl discord status` shows the new lead holding the bot
- [ ] `/tasks` lists a plan's tasks
- [ ] One real `/gauth signal-hub-gcp` ends with `token ok`

**Verify:** the runbook `docs/superpowers/e2e/2026-11-20-lead-recovery-runbook.md`, evidence captured in the task metadata

```json:metadata
{"files": [], "verifyCommand": "docs/superpowers/e2e/2026-11-20-lead-recovery-runbook.md", "acceptanceCriteria": ["/lead status answers privately", "/lead restart restarts and holds the bot", "/tasks lists tasks", "/gauth ends with token ok"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

## Order

1 → 2 → 3; 4 independent; 5 after 3; 6 after 3; 7 independent; 8 independent; 9 after 6, 7, 8; 10 independent; 11 after all; 12 after merge.
