# Discord ops bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second Discord app ("agent-board ops") that shows every project in one pinned card, gathers every open decision in #approvals with tap buttons (including phone merge approvals with evidence), posts a daily digest, answers slash commands and forms, and routes chat to the read-only overseer.

**Architecture:** The same `tools/discord-bridge/bridge.js` runs a second time with `--ops` on the state dir `<agent_base>/discord/_ops/`. The board stays the source of truth: a new `board/discord_ops.py` renders the card, mirrors decisions, writes a read-model file `views.json` that the bridge answers ephemeral reads from, and consumes the ops bridge's events (actions go to leads as `[Discord] …` lines). Merge evidence comes from `board/discord_merge.py`, called by a new `tmux-ctl discord merge-request`. The digest is `board/discord_digest.py`. The overseer gets the ops bot's chat via `--channels`.

**Tech Stack:** zsh (`tools/lib/discord.zsh`, `bin/claude-overseer`), Node + discord.js (`tools/discord-bridge`), Python 3 stdlib (`board/`), unittest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-12-discord-ops-bot-design.md`

## Global Constraints

- **Discord is never the source of truth.** Every action goes through the board (events → `board/discord_ops.py`), is checked against `access.json` `allowFrom` (re-read per event), and is audited with `discord_feed.audit_append(<_ops dir>, user, action, target, result)`.
- **Ops state dir:** `tc_env.agent_base() / "discord" / "_ops"` (zsh: `$(_dc_root)/_ops`). Name it once: `tc_env.ops_dir()` (new, Task 4) and `_dc_ops_dir` (new, Task 1). `_ops` is never a valid project name (project regex `^[A-Za-z0-9][A-Za-z0-9._-]*$` already rejects it).
- **`<_ops>/bridge.json`:** `{"command_center": "<id>", "approvals": "<id>", "user": "<allowFrom[0]>"}`. Project `bridge.json` stays `{"channel", "user"}`.
- **No command runs a shell command or takes a free-form command line** from Discord. Form text only reaches `ideas.add(...)` or a `[Discord] …` lead line, never argv of a shell.
- **Ops outbox op shapes** (validated by `discord_feed._check`, extended in Task 4; the bridge handles them in Task 2):
  - `card {op, text}` — in ops mode posted/edited in #command-center with one button row: `Pause all` `ab:ops:pause-all`, `Resume all` `ab:ops:resume-all`, `Inbox` `ab:ops:inbox`. Same 30 s throttle as today.
  - `post {op, text, tier, mention_user, [key], [thread_key], …}` — ops mode posts in #command-center. New optional `key` (both modes): the bridge stores `st.posts[key] = message id` so a later `edit` with that key finds it.
  - `approval {op, key, kind, text, mention_user, [link]}` — ops mode only, posted in #approvals; `kind` ∈ `perm|question|merge|other`. Buttons by kind: perm → `Allow once` `ab:ops:allow:<key>` (style 3) + `Deny` `ab:ops:deny:<key>` (style 4); merge → `Merge` `ab:ops:merge:<key>`, `Keep branch` `ab:ops:keep:<key>`, `Show files` `ab:ops:files:<key>:0`, and a second row with a string select `ab:ops:diff:<key>` whose options are the first 25 changed files from `views.json` evidence; question/other → a link button (style 5, `url` = `link`) labelled `Reply in <project>` when `link` is set, else no components. Message id kept in `st.approvals[key]` (newest 500 kept).
  - `edit {op, key, text}` — unchanged shape; the bridge now looks the key up in `st.prompts`, then `st.posts`, then `st.approvals`, edits the text and removes all components.
  - Ops keys are `sha1(project + "\0" + source key)[:12]` hex — 12 chars, so every customId stays under Discord's 100-char limit.
- **`<_ops>/views.json`** (board writes atomically, every ops tick; the bridge only reads it):
  `{"ts": <epoch>, "projects": ["a", …], "status": {"_all": "<card text>", "<project>": "<that project's line block>"}, "queue": {"<project>": "<queue_text output>"}, "approvals": [{"key", "project", "kind", "title", "link"}], "evidence": {"<key>": {"files": [{"path", "add", "del"}], "diffs": {"<path>": "<≤1800 chars>"}}}}`.
  A diff longer than 1800 characters is cut to 1800 and followed by `\n… too long, see board`.
- **Bridge → board events** (`<dir>/events/*.json`, written as today): existing `perm`, `click`, `react`, plus
  - `click` gains optional `values` (select menus) — not used for actions in this plan;
  - `{"type": "slash", "command": "pause"|"resume", "project", "user", "ts"}`;
  - `{"type": "modal", "form": "idea"|"new-spec", "project", "fields": {"title","text"}|{"what","why"}, "user", "ts"}`;
  - `{"type": "read", "what": "<customId or /command>", "user", "ts"}` — read-only answers the bridge gave from `views.json`, audited `answered`;
  - `{"type": "rejected", "what", "user", "ts"}` — a non-allowlisted user's click/command (the bridge already replied "Not authorized."), audited `rejected`.
- **Lead lines** (all through `COMMENTS.add_line(project, text)`, as the controls spec does): pause `[Discord] 🛑 pause the queue`, resume `[Discord] ▶️ resume the queue` (reuse `discord_controls.EMOJI_LINES`), `[Discord] merge approved for <spec>`, `[Discord] keep branch for <spec>`, `[Discord] new spec request: <what> — <why>`.
- **Queue state of a project** = `discord_feed._queue(lead_tasks)` (`queue: running <spec> (k/n)` / `queue: paused` / `queue: idle`). "Running queue" = starts with `queue: running`; "paused queue" = `queue: paused`.
- Ephemeral replies use `flags: 64`. Every reply text ≤ 2000 chars.
- Commit steps end with the attribution trailer your harness specifies. Conventional commits with scope (`feat(discord): …`, `feat(board): …`, `docs(orchestrator): …`).
- Node suite: `cd tools/discord-bridge && npm test` (not part of all.zsh). Whole repo: `zsh tools/tests/all.zsh` (its verdict line).
- Teammates share the worktree `.claude/worktrees/discord-ops-bot`: stage only your own paths.

**User decisions (already made):**
- A separate ops bot (its own Discord app), state dir `${TC_STATE}/discord/_ops/`, same token/pairing/access rules, `tmux-ctl discord token|pair|policy|status --ops` (spec, Decisions).
- Discord is never the source of truth (spec, Decisions).
- Ops chat goes to the overseer, which has no authority; actions only from structured controls (spec, Decisions).
- Queue item integration for this spec: merge locally, no push (queue metadata).

## Rulings made while planning (the queue runs unattended; recorded for the morning report)

- **Ephemeral reads are answered by the bridge from `views.json`**, not by a round trip to the board: Discord needs an answer within 3 s and the board ticks every 10 s. Cost if wrong: answers can be ≤ 10 s stale.
- **Lead questions in #approvals come from the overview record** (`needs_you` entries with window `claude`), not from the notifier's `needs_you` feed events (those also cover teammate prompts, which the controls mirror already posts). The project-channel notifier post of a lead question is not edited on resolution (it has no key; its ✅/❌ flow is the controls one); perm prompts and merge approvals are edited in both channels. Cost if wrong: one stale-looking post per lead question in the project channel.
- **Project bridges register the same slash commands** with `project` optional, defaulting to their own project; they read `../_ops/views.json` for read-only answers ("ops bot not set up" when absent). Cost if wrong: duplicated command names in the picker (Discord shows the app name next to each).
- **`/queue` text is rendered by `discord_ops.queue_text(lead_tasks)`**, not `taskwin.py render --view queue --plain`: that CLI has no `--view`/`--plain` flags (`board/taskwin.py:788-797`), and the board already holds the lead tasks. Cost if wrong: the phone's queue view is plainer than the tasks window.
- **"Fake lead transcript check"** for `integration: ask` is a doc test that the Queue mode rule text is present and consistent (Task 6) plus the board-side test that a `merge_approval` feed event becomes an approval post (Task 4). A lead's real behaviour is checked by the user gate (Task 10).

---

### Task 1: `tmux-ctl discord --ops`, `ops-channels`, ops bridge start

**Goal:** The ops bot's state dir is managed by the same subcommands with `--ops`, `ops-channels <cc> <approvals>` writes its config, and `bridge start|stop --ops` runs `bridge.js <_ops dir> --ops`.

**Files:**
- Modify: `tools/lib/discord.zsh` (argument parsing in `discord_cmd`, `_dc_status`, `_dc_bridge`, new `_dc_ops_channels`, `_dc_usage`)
- Modify: `bin/tmux-ctl` (help lines 44–47, and bump the `sed -n '2,NNp'` help range if you add a line — `tmux-ctl help` must still print its last line)
- Modify: `docs/INSTALL.md` (an "Ops bot" section: create a second Discord app, `tmux-ctl discord token --ops`, `pair --ops`, `ops-channels`, Message Content intent not needed, the bot needs `applications.commands` scope)
- Test: `tools/tests/test_ctl_discord_ops.zsh` (new; use `tools/tests/lib.zsh` like `test_ctl_discord_channel.zsh`)

**Acceptance Criteria:**
- [ ] `--ops` selects `$(_dc_root)/_ops` for `token|pair|deny|policy|allow|remove|forget|status|audit|bridge`; `--ops` with `--project` → usage error, rc 2.
- [ ] `tmux-ctl discord ops-channels <cc> <ap>` (both all digits, else usage rc 2; needs an allowlisted user, else "pair or allow a user first" rc 1) writes `<_ops>/bridge.json` `{"command_center","approvals","user"}` mode 600 and adds both ids to `access.json` `groups` with `{"requireMention": false, "allowFrom": [...]}`; a second identical call prints `(unchanged)` and changes no mtime.
- [ ] `status --ops` prints `command center: <id>`, `approvals: <id>` (or `none`), and the bridge line; it does not print `channel:`.
- [ ] `bridge start --ops` starts window `discord-ops` in hidden session `_ops-bg` running `exec node …/bridge.js <_ops dir> --ops`; `--keeper` and `bridge.stopped` behave as for projects; it refuses without a token or without both channel ids.
- [ ] The tokenish-argument guard still applies to every new argument.
- [ ] `tmux-ctl help` output's last line is unchanged (help range bumped if needed).
- [ ] Existing discord zsh suites stay green.

**Verify:** `zsh tools/tests/test_ctl_discord_ops.zsh && zsh tools/tests/test_ctl_discord.zsh && zsh tools/tests/test_ctl_discord_channel.zsh` → each ends with its ok/ALL PASS summary, rc 0

**Steps:**
- [ ] Write the test first (scratch `TC_STATE`, a fake `node` on PATH that records argv, scratch tmux server via `lib.zsh`); run it RED.
- [ ] Parse `--ops` in `discord_cmd`; set `dir=$(_dc_ops_dir)` and `project=_ops` (skip the project-name regex only on this path); add `ops-channels` (two positionals: extend the `pos` count check for this subcommand only).
- [ ] `_dc_bridge`: for ops, `BG=_ops-bg`, window `discord-ops`, append ` --ops` to the node command; check `.command_center` and `.approvals` instead of `.channel`.
- [ ] `_dc_status`: ops branch for the channel lines.
- [ ] INSTALL section; help lines.
- [ ] GREEN; commit `feat(discord): ops bot state dir, ops-channels and ops bridge start`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "bin/tmux-ctl", "docs/INSTALL.md", "tools/tests/test_ctl_discord_ops.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord_ops.zsh && zsh tools/tests/test_ctl_discord.zsh && zsh tools/tests/test_ctl_discord_channel.zsh", "acceptanceCriteria": ["--ops selects _ops dir for every subcommand; --ops with --project is rc 2", "ops-channels writes bridge.json {command_center, approvals, user} 600 and groups; idempotent", "status --ops prints command center/approvals lines", "bridge start --ops runs window discord-ops in _ops-bg with bridge.js <dir> --ops; keeper/stopped as projects", "tokenish guard on new args", "tmux-ctl help last line intact", "existing discord zsh suites green"], "modelTier": "standard"}
```

### Task 2: bridge ops mode: card buttons, approvals channel, keyed posts and edits, ops clicks

**Goal:** `bridge.js <dir> --ops` posts the card with its buttons in #command-center, approval posts with their buttons in #approvals, edits any keyed message, answers read-only buttons from `views.json`, runs the pause-all confirm step, and writes action events.

**Files:**
- Modify: `tools/discord-bridge/bridge.js`
- Modify: `tools/discord-bridge/lib/state.js` (defaults gain `posts: {}`, `approvals: {}`)
- Modify: `tools/discord-bridge/test/fake-client.js` (multiple channels, `reply`/`followUp`/`update` on interactions, components captured)
- Test: `tools/discord-bridge/test/ops.test.js` (new); existing `bridge.test.js` stays green

**Acceptance Criteria:**
- [ ] `createBridge({dir, client, ops: true})`; `main()` sets `ops` from `--ops` in argv. Project mode behaviour is unchanged (existing tests green).
- [ ] Ops `home()` is `bridge.json.command_center`; `approval` ops go to `bridge.json.approvals`. Card ops in ops mode carry the three-button row (customIds exactly `ab:ops:pause-all`, `ab:ops:resume-all`, `ab:ops:inbox`); the 30 s throttle still applies.
- [ ] `approval` builds the components per kind exactly as in Global Constraints (merge: 3 buttons + a select of ≤ 25 options from `views.json` `evidence[key].files`, option value = path cut to 100 chars; no files → no select row).
- [ ] `post` with `key` records `st.posts[key]`; `edit` finds the key in prompts, posts or approvals, edits the text, sets `components: []`; unknown key logs `edit <key>: no message` and the op is removed.
- [ ] Clicks (allowlisted users only; others get ephemeral `Not authorized.` and a `rejected` event):
  - `ab:ops:inbox` → ephemeral list from `views.json.approvals` (`<project> · <title>` + link per line, `No open decisions.` when empty) and a `read` event;
  - `ab:ops:files:<key>:<page>` → ephemeral (or `update` when clicked from the ephemeral) page of 10 files `path +add -del`, with `Prev`/`Next` buttons (`ab:ops:files:<key>:<n±1>`, omitted at the ends) and `page k/n`; `read` event;
  - `ab:ops:diff:<key>` select → ephemeral reply with `evidence[key].diffs[value]` in a ```diff block (≤ 1800 chars, as written by the board); `read` event;
  - `ab:ops:pause-all` → ephemeral `Pause every running queue?` with one button `Confirm pause all` `ab:ops:pause-all-confirm:<ms now>`; no event besides `read`;
  - `ab:ops:pause-all-confirm:*`, `ab:ops:resume-all`, `ab:ops:allow:*`, `ab:ops:deny:*`, `ab:ops:merge:*`, `ab:ops:keep:*` → `deferUpdate` (or ephemeral `Sent.` for the confirm) and a `click` event with `custom_id`.
  - a missing or unreadable `views.json` → ephemeral `Board data not available yet.`
- [ ] Every reply ≤ 2000 chars, `allowedMentions: {parse: []}`.

**Verify:** `cd tools/discord-bridge && npm test` → `# fail 0`

**Steps:**
- [ ] Extend the fake client first; write `ops.test.js` with one test per criterion above (fixtures: a `views.json` with 2 projects, 2 approvals, one merge evidence of 23 files); RED.
- [ ] Implement in `bridge.js`: `ops` option, `chan(name)` helper for `command_center`/`approvals`, `opApproval`, keyed `post`, widened `opEdit`, an `onOpsInteraction` branch before the generic click path, `views()` reader (`readJson(path.join(dir,'views.json'), null)`).
- [ ] GREEN; commit `feat(discord-bridge): ops mode card buttons, approvals and ephemeral reads`.

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/lib/state.js", "tools/discord-bridge/test/fake-client.js", "tools/discord-bridge/test/ops.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["ops option; project mode unchanged", "card in command_center with 3 exact button ids; approvals in approvals channel", "approval components per kind; merge select <=25 from views evidence", "keyed post/edit across prompts/posts/approvals; components removed", "inbox/files paging/diff select/pause-all confirm/action clicks as specified; rejected and read events", "replies <=2000 chars, no mentions"], "modelTier": "standard"}
```

### Task 3: slash commands and forms (both bridge modes)

**Goal:** The ops bridge registers `/status /queue /pause /resume /idea /new-spec /approvals` as guild commands in its server and answers them; project bridges register the same set with `project` defaulting to their own project.

**Files:**
- Modify: `tools/discord-bridge/bridge.js`
- Create: `tools/discord-bridge/lib/commands.js` (the registration payload and the per-command handlers, pure where possible)
- Test: `tools/discord-bridge/test/commands.test.js` (new)

**Acceptance Criteria:**
- [ ] On ready, `client.application.commands.set(payload, guildId)` once per connection with guildId = the guild of `command_center` (ops) or of the home channel (project). Payload: 7 chat-input commands; `project` is a string option, required for `queue pause resume idea new-spec` in ops mode, optional in project mode and for `status`. A registration failure is logged and does not stop the bridge.
- [ ] Each command checks `allowFrom` first (else ephemeral `Not authorized.` + `rejected` event).
- [ ] `/status [project]` → `views.status._all` or `views.status[project]`; `/queue <project>` → `views.queue[project]` in a code block; `/approvals` → the same list as the Inbox button. Each writes a `read` event. Unknown project → ephemeral `Unknown project: <name>` (no event besides `read`).
- [ ] `/pause` `/resume` → ephemeral `Sent to <project>.` and a `slash` event `{command, project}`.
- [ ] `/idea` → `showModal` custom_id `ab:modal:idea:<project>`, inputs `title` (short, ≤ 100) and `text` (paragraph, ≤ 1000); `/new-spec` → `ab:modal:new-spec:<project>`, inputs `what` (short) and `why` (paragraph). Submit → `modal` event with the trimmed fields and ephemeral `💡 noted for <project>` (idea) / `Sent to <project>'s lead.` (new-spec).
- [ ] Project mode reads `views.json` from `path.join(path.dirname(dir), '_ops', 'views.json')`; when absent, read commands answer `Ops bot not set up (tmux-ctl discord ops-channels).`; action commands still work (they go to the project's own events dir).
- [ ] No command takes or runs a command line (no free-form option besides the form fields, which are only written into the event).

**Verify:** `cd tools/discord-bridge && npm test` → `# fail 0`

**Steps:**
- [ ] Tests first against the fake client (interaction type `isChatInputCommand()`, `isModalSubmit()`, `options.getString`, `fields.getTextInputValue`); RED.
- [ ] `lib/commands.js`: `payload(ops)`, `handle(i, ctx)`; wire into `attach()`/`onReady()`.
- [ ] GREEN; commit `feat(discord-bridge): slash commands and idea/new-spec forms`.

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/lib/commands.js", "tools/discord-bridge/test/commands.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["guild registration of 7 commands on ready; project option rules; failure logged", "allowlist check first; rejected event", "status/queue/approvals answered from views.json with read events; unknown project message", "pause/resume -> slash event", "idea/new-spec modals -> modal event and ephemeral ack", "project mode reads ../_ops/views.json; absent -> setup message", "no free-form command line"], "modelTier": "standard"}
```

### Task 4: `board/discord_ops.py`: card, views, decision mirror, critical alerts, ops events

**Goal:** One module that, given the overview records and each project's lead tasks, renders the command-center card, writes `views.json`, mirrors decisions into #approvals and critical events into #command-center, edits both copies on resolution, and consumes the ops (and forwarded project) events.

**Files:**
- Create: `board/discord_ops.py`
- Modify: `board/tc_env.py` (`ops_dir()`)
- Modify: `board/discord_feed.py` (`_check`: `approval` op, `post.key`; `ops_for_events`: decision-tier posts get `key = "dec:" + sha1(ts|text)[:12]`, `merge_approval` posts get `key = "merge:<task>"`)
- Modify: `board/discord_controls.py` (`scan_prompts`: when `discord_ops.configured()`, also `discord_ops.mirror_prompt(project, key, window, tool, lines)`; `_edit`: also `discord_ops.resolve(project, key, text)`; `consume_events`: `slash`/`modal`/`read`/`rejected` events go to `discord_ops.handle_event(project, d, ev, add_line, allow)`)
- Test: `board/tests/test_discord_ops.py` (new); `test_discord_feed.py`, `test_discord_controls.py` stay green

**Acceptance Criteria:**
- [ ] `render_card(records, tasks_by_project, links, limits, now)` → ≤ 1900 chars, plain text (no code block, so links render): header `usage: 5h <p>% · week <p>% · today $<sum of spend_today>` (`—` for unknown parts); one line per project `**<project>** · <queue state> · <done>/<total> · blockers: <alert labels or none> · waiting on you: <n> · <<link>>` (link from the project's `bridge.json.channel` + `bridge-state.json.guild_id`; omitted when unknown); `updated HH:MM` last; overflow cut with `… <n> more`. Fixture test with two projects + one 40-project overflow test.
- [ ] `tick(records, tasks_by_project, limits, now, add_line)` under `flock(<_ops>/ops-state.lock)` (non-blocking; returns None when held): writes the card op when due (`discord_feed.card_op_due`), writes `views.json` atomically (shape in Global Constraints; `queue[p]` = `queue_text(lead_tasks)`: the `discord_feed._queue` line, then one line per `Plan & run:` task in id order, `✓`/`▶`/`·` + `discord_feed._spec_name(subject)` + ` — <metadata.outcome>` when set, cut to 1800 chars), reads each project's feed from its own offset in `ops-state.json` (first sight: offset = file size, no replay), and per event: tier `decision` → one `approval` op (kind `merge` for `merge_approval`, else `other`, with the project-channel link), tier `critical` → one ops `post` with `mention_user: true` prefixed `<project>: `.
- [ ] Lead questions: a project whose record `needs_you` holds window `claude` gets one `approval` (kind `question`, text `<project>: the lead is waiting on you`, link to the project channel); when it leaves `needs_you`, `edit` → `<project>: answered`. Not re-posted while it stays.
- [ ] `mirror_prompt` posts kind `perm` (`🔐 <project> · <window> wants to run <tool>` + the first 15 lines in a code block); `resolve(project, src_key, text)` edits the ops copy with `<project>: <text>` and drops it from `views.approvals`. Both no-ops when ops is not configured.
- [ ] Ops events (`consume(add_line, run, now)`), allowlist re-read per event; each audited in `<_ops>/audit.jsonl`:
  - `ab:ops:allow|deny:<k>` → a `perm` event `{key: <src key>, choice: allow|deny, user, ts}` written into that project's `events/` (the controls step presses and edits both copies) — audited `forwarded`;
  - `ab:ops:pause-all-confirm:<ms>` → within 60 s of `<ms>`: the pause line to every project whose queue state is running (audited `queued <n>`), else `expired`; `ab:ops:resume-all` → the resume line to every paused project;
  - `ab:ops:merge:<k>` / `ab:ops:keep:<k>` → `discord_merge.on_merge(...)` / keep line (Task 5 provides `on_merge`; until then the test injects a stub);
  - `slash` pause/resume → that project's line; `modal` idea → `ideas.add(project, title, detail=text)`, new-spec → `[Discord] new spec request: <what> — <why>` (whitespace collapsed, each ≤ 300 chars); `read` → audited `answered`; `rejected` → audited `rejected`; unknown project → audited `unknown project`.
  - The same `handle_event` serves events forwarded from a project's `consume_events` (project defaulted to that project).
- [ ] Delivery semantics (tests for each): a repeated event file (same content twice) presses/sends once per file only — pause-all lines are idempotent for the lead; a duplicated `ab:ops:allow` after the first is answered by the controls' existing `unknown` path (no second press); events are processed in filename order; a decision already mirrored is never posted twice (keys in `ops-state.json.mirrored`, newest 2000).
- [ ] Ops not configured (`<_ops>/bridge.json` missing) → `tick` and `consume` return without writing anything; project behaviour unchanged.

**Verify:** `python3 -m unittest board.tests.test_discord_ops board.tests.test_discord_feed board.tests.test_discord_controls` → `OK`

**Steps:**
- [ ] Tests first with a scratch `TC_STATE` (patch env), fixture records for two projects, fixture feed lines, a recording `add_line` and a fake `run`; each guard test names its mutation in a comment (e.g. "drop the 60 s check → `test_confirm_expired` fails"); RED.
- [ ] Implement; keep I/O at the edges (`_load`, atomic writes like `discord_controls.step`).
- [ ] GREEN; commit `feat(board): discord ops card, views, decision mirror and ops events`.

```json:metadata
{"files": ["board/discord_ops.py", "board/tc_env.py", "board/discord_feed.py", "board/discord_controls.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_ops board.tests.test_discord_feed board.tests.test_discord_controls", "acceptanceCriteria": ["render_card format and <=1900 cap with overflow", "tick: card when due, views.json atomic, per-project feed offsets without replay, decision->approval, critical->ops post", "lead question approval posted once and edited answered", "mirror_prompt/resolve edit ops copy; no-op unconfigured", "ops events: allow/deny forwarded, pause-all confirm 60s, resume-all, merge/keep, slash, modal idea/new-spec, read, rejected, all audited", "delivery: repeats, order, no double mirror", "unconfigured -> nothing written"], "modelTier": "standard"}
```

### Task 5: merge evidence and `tmux-ctl discord merge-request`

**Goal:** A lead in queue mode with `integration: ask` runs one command that computes the merge evidence, posts the decision, and a later Merge tap re-checks the branch tip before telling the lead to merge.

**Files:**
- Create: `board/discord_merge.py` (`evidence(repo, branch, target) -> dict`, `request(project, repo, task, spec, branch, target, tests, verdict, findings, now)`, `on_merge(project, ev_key, state, add_line, now)`, CLI `main()` for the zsh wrapper)
- Modify: `tools/lib/discord.zsh` (`merge-request` subcommand → `python3 -I board/discord_merge.py request …`)
- Modify: `bin/tmux-ctl` (one help line; bump the help `sed` range)
- Modify: `board/discord_ops.py` (call `discord_merge.on_merge` for `ab:ops:merge:*`; views evidence from `<_ops>/evidence/*.json`)
- Test: `board/tests/test_discord_merge.py` (new, with a fixture git repo built in a temp dir); `tools/tests/test_ctl_discord_ops.zsh` gains the CLI case

**Acceptance Criteria:**
- [ ] `tmux-ctl discord merge-request --project <p> --task <id> --spec <spec> --branch <b> [--target main] --tests "<verdict line>" --verdict "<final review verdict>" [--finding "<line>"]…` (repo = the caller's git toplevel; `--repo` overrides) writes `<_ops>/evidence/<p>-<task>.json` and appends one feed event `{kind: "merge_approval", tier: "decision", spec, text, refs: {task, evidence, sha}}` to the project's feed; prints `merge-request: posted <spec>`; rc 0. Without ops configured it still posts in the project channel (the feed event) and says `(ops bot not set up: project channel only)`.
- [ ] Evidence: `sha` = `git rev-parse <branch>`; `files` from `git diff --numstat <target>...<branch>` (binary `-` counts as 0); post text = `merge approval: <spec>` / `<branch> → <target> @ <sha[:8]>` / `git diff --stat` lines, first 25 files then `… <n> more` / `tests: <line>` / `final review: <verdict>` / one line per finding (each cut to 200 chars) / `diff: <files> files, +<adds> −<dels>`; text cut to 1900. `diffs[path]` = `git diff <target>...<branch> -- <path>` cut to 1800 + `\n… too long, see board`.
- [ ] Fixture test: a repo with 30 changed files → 25 stat lines + `… 5 more`; a binary file; a diff of > 1800 chars carries the note.
- [ ] `on_merge`: re-runs `git rev-parse <branch>`; equal to evidence `sha` → `[Discord] merge approved for <spec>` to the lead and edits both copies to `merge approved — sent to the lead`; different or branch gone → edits both copies to `branch changed since this was posted`, then calls `request(...)` again with the stored fields (fresh evidence, fresh post). Keep → `[Discord] keep branch for <spec>`, edits `kept: <branch>`. A second tap on a resolved key → audited `unknown`, nothing sent.
- [ ] No branch/target/spec value reaches a shell string: every git call is an argv list with `--` before paths; branch and target must match `^[A-Za-z0-9._/-]+$` and not start with `-` (else rc 2, nothing written).

**Verify:** `python3 -m unittest board.tests.test_discord_merge board.tests.test_discord_ops && zsh tools/tests/test_ctl_discord_ops.zsh` → `OK` and the zsh suite's pass line

**Steps:**
- [ ] Fixture repo helper in the test (`git init`, commits on `main` and a branch); tests for each criterion, including the SHA-mismatch path (advance the branch after `request`); RED.
- [ ] Implement `discord_merge.py`; wire the zsh subcommand and the ops click.
- [ ] GREEN; commit `feat(discord): merge approval evidence and merge-request`.

```json:metadata
{"files": ["board/discord_merge.py", "tools/lib/discord.zsh", "bin/tmux-ctl", "board/discord_ops.py", "board/tests/test_discord_merge.py", "tools/tests/test_ctl_discord_ops.zsh"], "verifyCommand": "python3 -m unittest board.tests.test_discord_merge board.tests.test_discord_ops && zsh tools/tests/test_ctl_discord_ops.zsh", "acceptanceCriteria": ["merge-request writes evidence json and one merge_approval decision feed event; project-only note without ops", "evidence text format, 25-file cut, binary, diff 1800 cut", "on_merge sha equal -> lead line + both edited; mismatch -> branch changed + fresh request; keep; second tap unknown", "argv-only git, branch/target shape check"], "modelTier": "standard"}
```

### Task 6: Queue mode `integration: ask` in the lead rules

**Goal:** The lead rules know the new `ask` integration: finish up to the merge, keep the branch, post the decision with `tmux-ctl discord merge-request`, move on; merge or keep later when the `[Discord]` line arrives.

**Files:**
- Modify: `claude/orchestrator.md` (§ Queue mode: step 1's integration list and `metadata.queue.integration` values gain `ask`, "approve from the phone"; step 2 gains one sentence for `ask`; a new bullet for the two `[Discord] merge approved for <spec>` / `[Discord] keep branch for <spec>` lines)
- Test: `tools/tests/test_orchestrator_rules.zsh` if it exists, else `tools/tests/test_queue_ask_rule.zsh` (new): greps that the three texts are present

**Acceptance Criteria:**
- [ ] `claude/orchestrator.md` names `"ask"` in the `metadata.queue.integration` value list, and step 2 says, verbatim in substance: with `ask`, run `finishing-a-development-branch` up to the integration step with the option "keep the branch", then `tmux-ctl discord merge-request --project <p> --task <id> --spec <spec> --branch <b> --tests "<verdict line>" --verdict "<final review verdict>" [--finding …]`, record `metadata.outcome = "awaiting merge approval <branch>"`, and start the next spec.
- [ ] On `[Discord] merge approved for <spec>`: run `finishing-a-development-branch` with `merge` for that spec's branch (its pre-merge tests and live-checkout checks run), update the task's outcome to `merged <sha>`; on `[Discord] keep branch for <spec>`: outcome `kept <branch>`. Neither line is ever a push.
- [ ] The sentence fits the file's style (no new headings); the test greps for `"ask"`, `merge-request`, and `merge approved for`.

**Verify:** `zsh tools/tests/test_queue_ask_rule.zsh` → `ok` lines, rc 0

**Steps:**
- [ ] Write the grep test; RED.
- [ ] Edit `claude/orchestrator.md` (keep the text short; follow `writing-for-agents` style).
- [ ] GREEN; commit `docs(orchestrator): queue integration ask approves merges from Discord`.

```json:metadata
{"files": ["claude/orchestrator.md", "tools/tests/test_queue_ask_rule.zsh"], "verifyCommand": "zsh tools/tests/test_queue_ask_rule.zsh", "acceptanceCriteria": ["ask in integration values; step 2 ask flow with merge-request and outcome awaiting merge approval", "merge approved -> finishing with merge, outcome merged; keep -> kept; never a push", "grep test for ask, merge-request, merge approved for"], "modelTier": "mechanical"}
```

### Task 7: board wiring: ops tick, ops bridge keeper, real-state check

**Goal:** The board runs the ops tick and the ops event consumer on every overview build and keeps the ops bridge running, without slowing the overview or breaking project feeds.

**Files:**
- Modify: `board/server.py` (`feed_tick`: collect `tasks_by_project`, then one `discord_ops.tick(...)` and `discord_ops.consume(...)` call wrapped like the project calls; `ensure_discord_bridges`: also `bridge start --keeper --ops` when `<_ops>/.env` and both channel ids exist, same 60 s recheck)
- Modify: `board/tests/test_discord_wiring.py`
- Test: as above

**Acceptance Criteria:**
- [ ] With ops configured, one overview build calls `discord_ops.tick` once and `discord_ops.consume` once after every project's feed+controls step; an exception in either is logged `tmux-dash: discord ops failed: …` and the overview still returns.
- [ ] `limits` = `usage.plan_limits(usage.tap_entries(now, 10 ** 9))` (as `board/metrics.py:202` does), failures → `None`.
- [ ] `ensure_discord_bridges` starts the ops bridge at most once per 60 s; `TC_DISCORD_BRIDGE=0` disables it too.
- [ ] Real state (read-only): `python3 board/overview.py --json > <scratch>/ov.json` from the live board, then a one-off `python3 -c` that loads it and calls `discord_ops.render_card(...)` with the real records (no writes; `links` from the real `bridge.json`/`bridge-state.json` files, read only) prints a card ≤ 1900 chars naming every project in the live overview; paste the output in the report.
- [ ] `zsh tools/tests/all.zsh` verdict line ALL PASS (or only the known flaky pair, rerun alone green).

**Verify:** `python3 -m unittest board.tests.test_discord_wiring board.tests.test_discord_ops` → `OK`

**Steps:**
- [ ] Wiring tests first (monkeypatch `discord_ops.tick/consume`, `run_script`); RED.
- [ ] Implement; real-state check; all.zsh.
- [ ] Commit `feat(board): run the discord ops tick and keep the ops bridge`.

```json:metadata
{"files": ["board/server.py", "board/tests/test_discord_wiring.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_wiring board.tests.test_discord_ops", "acceptanceCriteria": ["one ops tick + consume per overview build, failures logged, overview returns", "limits from usage.plan_limits", "ops bridge keeper 60s, TC_DISCORD_BRIDGE=0", "real-state read-only card render <=1900 naming every live project", "all.zsh ALL PASS"], "modelTier": "standard"}
```

### Task 8: daily digest

**Goal:** At `TC_DISCORD_DIGEST_AT` (default `08:00` local, `off` disables) the board posts one digest in #command-center covering everything since the last digest.

**Files:**
- Create: `board/discord_digest.py` (`due(state, now, at)`, `build(projects, feeds, approvals, records, limits, since, now) -> str`, `tick(records, limits, now)`)
- Modify: `board/server.py` (call `discord_digest.tick` next to the ops tick, same error wrapping)
- Test: `board/tests/test_discord_digest.py` (new)

**Acceptance Criteria:**
- [ ] `due`: true once per local day at or after `at` (`HH:MM`); state `<_ops>/digest-state.json {"last_ts", "last_day"}`; first ever run uses `since = now - 86400`; `off` → never; an unparsable value → default `08:00` and one stderr line.
- [ ] Content: header `digest <YYYY-MM-DD> · 5h <p>% · week <p>% · spend $<x>`; per project with activity: `<project>: merged <n> (<specs>) · failed <n> (<specs>) · running <spec or none> · decisions <n> · test runs failed <n>`, specs cut to 3 names + `…`; decisions with links as following lines; a project with nothing new → `<project>: quiet`. Sources: feed events since `since` (`spec_outcome` text `merged…`/`failed…`, `spec_started`, kind `test_failed`), open approvals from `ops-state.json`, `spend_today` from records. ≤ 1900 chars, cut with `… <n> more projects`.
- [ ] One ops `post` op (tier `progress`, no mention) per digest; never posts twice the same day (test with two ticks); a feed spanning midnight counts events from both days (aged fixture: events dated yesterday 23:50 and today 00:10 with `since` yesterday 08:00).
- [ ] Critical events are not held: the digest never suppresses Task 4's critical posts (test: a critical event before the digest is still posted by `discord_ops.tick`).
- [ ] Ops not configured → nothing.

**Verify:** `python3 -m unittest board.tests.test_discord_digest` → `OK`

**Steps:**
- [ ] Tests first (fixed `now`, `TZ` set in the test, fixture feeds); RED.
- [ ] Implement; wire; GREEN.
- [ ] Commit `feat(board): daily discord ops digest`.

```json:metadata
{"files": ["board/discord_digest.py", "board/server.py", "board/tests/test_discord_digest.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_digest", "acceptanceCriteria": ["due once per local day at TC_DISCORD_DIGEST_AT; off; bad value default", "content lines, quiet, cut <=1900", "one post per day; midnight-spanning feed counted", "critical not held", "unconfigured nothing"], "modelTier": "standard"}
```

### Task 9: ops chat goes to the overseer

**Goal:** When the ops token exists, the overseer Claude starts with the Discord channel on and `DISCORD_STATE_DIR=<_ops dir>`, so the user can chat with it in #command-center; it keeps its read-only rules.

**Files:**
- Modify: `bin/claude-overseer`
- Modify: `claude/overseer.md` (two lines: messages from Discord arrive as channel tags; answer with the discord `reply` tool; it still has no authority and points to the buttons/slash commands for actions)
- Modify: `claude/overseer-settings.json` only if the probe shows the discord plugin's tools need an allow entry (read-only reply/fetch only; never access tools)
- Test: `tools/tests/test_overseer_channel.zsh` (new; fake `claude` on PATH records argv and env)

**Acceptance Criteria:**
- [ ] `<_ops>/.env` holds a token (check with `claude/plugin/scripts/discord-mcp-launch --has-token <dir>`): `claude-overseer` execs claude with `--channels plugin:discord@claude-plugins-official` added and `DISCORD_STATE_DIR=<_ops dir>` exported; no token: argv and env exactly as today (test both).
- [ ] Probe (one real run, recorded in the report with its output): with `--setting-sources project,local`, does the discord plugin load in the overseer? Run `claude-overseer` in a scratch tmux window with a real `_ops` token present (or, without one, check `claude --setting-sources project,local --channels plugin:discord@claude-plugins-official -p 'say ok' --debug` output for the plugin's MCP server start). If it does not load, add the smallest settings change that makes it load (`--plugin-dir` of the installed discord plugin, or an `enabledPlugins` entry in `claude/overseer-settings.json`) and say which in the report.
- [ ] `tmux-ctl discord status --ops` names the overseer as holder when it runs with the channel (`held by: overseer:claude pid …`) — checked in the probe if a real token exists; otherwise noted as a user-gate item.
- [ ] The overseer's permissions stay read-only: `claude/overseer-settings.json` gains no write, Bash or access-skill allow.

**Verify:** `zsh tools/tests/test_overseer_channel.zsh` → its pass line, rc 0

**Steps:**
- [ ] Test first; RED. Probe. Implement. GREEN.
- [ ] Commit `feat(overseer): ops bot chat reaches the overseer`.

```json:metadata
{"files": ["bin/claude-overseer", "claude/overseer.md", "claude/overseer-settings.json", "tools/tests/test_overseer_channel.zsh"], "verifyCommand": "zsh tools/tests/test_overseer_channel.zsh", "acceptanceCriteria": ["token -> --channels + DISCORD_STATE_DIR; no token -> unchanged", "probe recorded: plugin loads under setting-sources project,local or the minimal fix", "status --ops holder overseer when real token, else user-gate note", "overseer stays read-only"], "modelTier": "standard"}
```

### Task 10: User gate — the real run from the phone

**Goal:** The user, from the phone only, checks status, files an idea with `/idea`, approves a merge with evidence, and pauses and resumes all.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- none (setup by the user: create the ops Discord app, `tmux-ctl discord token --ops`, pair, `ops-channels`)

**Acceptance Criteria:**
- [ ] Setup: `tmux-ctl discord status --ops` shows `token: set`, `paired: 1 allowlisted`, both channel ids, `bridge: running`.
- [ ] `/status` from the phone answers with every project; the pinned card in #command-center shows every project and an `updated` time within the last minute.
- [ ] `/idea agent-board` form submitted → a new `- [ ]` line in the ideas file and `tmux-ctl discord audit --ops` shows the `modal` line `ok`.
- [ ] A merge approval for a throwaway branch (lead runs `tmux-ctl discord merge-request` on a one-commit branch) shows evidence in #approvals; Show files and the diff select answer; Merge → the lead receives `[Discord] merge approved for <spec>` and both copies read `merge approved — sent to the lead`.
- [ ] Pause all → Confirm → each lead with a running queue receives `[Discord] 🛑 pause the queue`; Resume all → `[Discord] ▶️ resume the queue`; both in the ops audit.

**Verify:** `tmux-ctl discord audit --ops --since <gate start ISO>` → lines for read, modal, merge, pause-all-confirm and resume-all, each with a non-rejected result

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl discord audit --ops --since <gate start ISO>", "acceptanceCriteria": ["status --ops shows token, paired, both channels, bridge running", "/status lists every project; card pinned and fresh", "/idea adds an ideas line; audit modal ok", "merge approval evidence, files, diff, Merge -> lead line and both copies edited", "pause all confirm and resume all reach the leads; audited"], "userGate": true, "tags": ["user-gate"], "modelTier": "standard"}
```
