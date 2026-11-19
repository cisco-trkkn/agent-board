# Discord bridge and ops fixes, and /queue spec summaries (regroup group A)

Date: 2026-11-19 · Decided with the user over Discord, 2026-11-19 (regroup group A; ideas c902b57ed2, 713ac51c4d, 975b45d801, d54b5fc664, c1bdd9cc11, 5ccc50792e, 43e509dc4d)

## Problem

Six small defects in the Discord bridge and the ops bot, found while running the queue, plus one missing view:

1. `dc token` treats `"ackReaction": null` as "the user turned it off", so no 👀 is set (`tools/lib/discord.zsh:100`).
2. A card whose pin failed with 403 is never pinned later: only `createCard` pins (`tools/discord-bridge/bridge.js:86-105`), and the hint says "Manage Messages" where Discord needs "Pin Messages" (`docs/INSTALL.md:240`).
3. A presence op a bridge rejected is still recorded as sent (`board/discord_feed.py:591`, `board/discord_ops.py:307`), so an idle project never resends its status line.
4. `/pause` and `/resume` do not touch `paused_by_ops` (`board/discord_ops.py:358-363`), so a project paused by `/pause` whose task list still reads running is skipped by Resume all.
5. `/ideas` Park, Brainstorm next and Drop replace the message with the header plus one line, so the idea list disappears and the tap looks like nothing happened (`board/discord_ideas.py:253`).
6. `/ideas` run from the agent-board bot's copy of the command posts and edits its groups in #agent-board instead of #command-center: the slash event carries the receiving bridge (`tools/discord-bridge/lib/commands.js:55,98`) and `board/discord_ops.py:354` passes it on to `discord_ideas.request`. Each group's actions already reach its own project (`discord_ideas.click`).
7. Missing view: from the phone, the user cannot see each lead's queue at once, nor what a queued spec is about.

## Decisions (user, Discord, 2026-11-19)

- D1. The five small fixes take the scout's recommended fix (below), and Park gets a separate "parked ✓" reply as well (answer "2").
- D2. `/queue` with no project posts one card per lead in #command-center, each with a dropdown of that lead's specs; picking one shows a private summary: title, the spec's Problem section cut to about 600 characters, status and outcome, branch (answer "Yes as above").
- D3. The branch comes from a new `metadata.worktree` and `metadata.branch` that the lead writes on every `Plan & run:` task. The same field later narrows the failed-run log (group B idea e3ce28f853), which is not in this spec.
- D4. `/ideas` always posts and edits through the ops bridge; the project bots stop offering `/ideas`.
- D5. The frozen-dialog ideas (d8293803c6, 15f9db31fc) belong to spec C, not here.

## Design

### 1. `ackReaction: null` (`tools/lib/discord.zsh`)

The `dc token` filter becomes `if (.ackReaction // null) == null then .ackReaction = "👀" else . end`. Missing and `null` both get 👀; only `""` stays off. `_dc_status` keeps showing `off` for `""`.

### 2. Card pin retry (`tools/discord-bridge/bridge.js`, `docs/INSTALL.md`)

- `createCard` catches a pin error: it keeps the card (the send succeeded), sets `st.card_pinned = false`, saves, and logs `pin failed: grant Pin Messages (<reason>)`. On success it sets `st.card_pinned = true`.
- `doCard`, after a successful edit, retries `msg.pin()` while `st.card_pinned !== true`. A failed retry logs the same line once per process (not every tick) and leaves the op successful: the edit is what the op asked for.
- A state with no `card_pinned` key (a bridge that pinned before this change) counts as pinned.
- `docs/INSTALL.md:240` says "Pin Messages", matching line 248.

### 3. Presence resend (`board/discord_feed.py`, `board/discord_ops.py`)

`presence_op_due(st, text, now, bridge_state)` gains the bridge's own state (`bridge-state.json`, already written by the bridge with `presence` at `bridge.js:307`). It returns the op when:
- the text changed (today's rule), or
- `bridge_state.presence != text` and the last send is at least 60 s old (the existing throttle).

An old bridge that never writes `presence` therefore gets one resend a minute, not one per tick; a restarted bridge that lost the text gets it back within a minute. A missing or unreadable `bridge-state.json` counts as `presence` absent. Both callers (the project ticker and the ops ticker) pass the bridge state they read.

### 4. `/pause`, `/resume` share `paused_by_ops` (`board/discord_ops.py`, `board/discord_controls.py`)

`handle_event(st, d, ev, add_line, allow)` already receives `st` as a parameter slot; the slash branch now uses it: `/pause <p>` sets `st["paused_by_ops"][p] = now`, `/resume <p>` pops it, both before `add_line`. `consume` passes its `st`. The reaction-controls path (`discord_controls.py:161`, `_ops(...)`) loads the ops state under the same lock `consume` uses, passes it, and saves it, so a 🛑 / ▶️ on a project's message updates the record too. Resume all then resumes every project paused by either route.

### 5. `/ideas` keeps the list and replies (`board/discord_ideas.py`, `tools/discord-bridge/bridge.js`)

- `post` stores the rendered body as `g["body"]`. `click` edits to `f"{g['body']}\n{second}"`, where `second` is today's `→ parked` / `→ sent to <project>'s lead` / `→ dropped <n>` line. `_check` validates the full edit text against the 2000 limit, cutting the body (not the status line) when needed. A post state without `body` (made before this change) falls back to today's header-only edit.
- The edit op gains an optional `reply` field. The bridge, after a successful edit, sends `reply` as a reply to that message. `click` sets it to `parked ✓`, `sent to <project> ✓` or `dropped <n> ✓`. A second tap on a group already `done` changes nothing and sends no reply (today's idempotence holds).
- An old bridge ignores the unknown field, so the edit still lands.

### 6. `/ideas` routed to the ops bridge (`board/discord_ops.py`, `tools/discord-bridge/lib/commands.js`)

- `discord_ops.py:354` passes `"_ops"` to `discord_ideas.request`, whatever bridge the slash came from. The groups, their edits and the expiry post all go to #command-center.
- `payload(ops)` lists `ideas` only when `ops` is true, so the project bots stop registering it. Until a project bridge restarts, its old `/ideas` still works and its posts now land in #command-center too.
- The receiving bot's ephemeral "asked the overseer" ack stays as it is.

### 7. `/queue` cards with spec summaries

**Data (board).** On each ops tick, for each project with a lead, `discord_ops` builds:
- `views.json["queue"][p]` as today (`queue_text`), and
- `views.json["specs"][p]`: a list, in task-id order, of the lead's `Plan & run:` tasks, each `{"key": <task id>, "label": <spec name, 100 max>, "summary": <text, 1900 max>}`.

`summary` is built by a new `discord_ops.spec_summary(root, task)`:
- line 1: `**<spec title>**`, from the spec file's first `# ` line (the path is the subject after `Plan & run: `, without its `#part-n` or `(…)` suffix, resolved under the lead's repo root);
- the spec's `## Problem` section up to the next `## `, whitespace collapsed, cut at a word boundary to 600 characters with `…`;
- `Status: <pending|in progress|completed>` plus ` — <metadata.outcome>` when set;
- `Branch: <metadata.branch>` (and `· worktree <metadata.worktree>`) when set, else `Branch: not started`.

A missing or unreadable spec gives `**<spec name>**` and `(spec file not found)` in place of the Problem text; the status and branch lines stay. The summary is cached per `(path, mtime)` so a tick reads each spec once.

**Command (bridge).** `/queue` in ops mode takes `project` as optional:
- with a project: today's private text reply, unchanged;
- without: the bridge answers privately `posting <n> queue cards`, and the board posts one message per project with a lead to #command-center: the `queue_text` block, and under it one select menu, custom id `ab:ops:spec:<project>`, options = `views.json["specs"][p]` (label, value = key), the first 25 in id order, with a final line `… <k> more` in the card text when cut. A project with no `Plan & run:` tasks gets its card with no menu.

  The board posts the cards because the bridge has no per-project queue loop of its own; the slash writes a `slash` event (`/queue` with no project), and `discord_ops.handle_event` answers it with one `post` op per project. A second `/queue` posts new cards; old ones stay as they were (no edit tracking).

**Picking a spec.** `onOpsInteraction` handles `ab:ops:spec:<project>` like `ab:ops:diff:<key>`: it reads `i.values[0]`, looks up `views.json["specs"][project]`, and replies privately with that entry's `summary`, or `that spec is no longer in the queue` when the key is gone. The id passes the same `allowFrom` check as every `ab:` id.

**Post op.** `opPost` accepts an optional `select: {custom_id, options:[{label, value}], placeholder}` (at most 25 options, labels and values 100 max, custom id 100 max), rendered as its own action row under the buttons row. `discord_feed._check` validates the same limits for the board side.

**Lead rule (`claude/orchestrator.md`, Queue mode step 2).** When the lead branches for a `Plan & run:` task, it writes `metadata.worktree = ".claude/worktrees/<name>"` and `metadata.branch = "<branch>"` with TaskUpdate, alongside `metadata.plan`. The handoff skill's State of the work lists both fields with `metadata.queue`.

## Error handling

- Every new bridge path that fails (pin retry, the edit's `reply`, a select reply) logs one line to `bridge.log` and never fails the op that carried it, except a malformed `select` field, which fails the post op into `failed/` like any invalid op.
- `spec_summary` never raises: any read or parse error yields the not-found summary.
- `views.json` grows by the specs list; the existing writer (atomic rename) is unchanged.

## Testing

- `tools/tests/test_ctl_discord.zsh`: `ackReaction: null` → 👀; `""` kept; missing → 👀.
- `tools/discord-bridge/test/bridge.test.js`: pin fails with 403 on create, the next card op pins (fake client `failNext('pin', …)`); a pinned card is not re-pinned; a legacy state without `card_pinned` is not re-pinned; edit with `reply` sends one reply; post with `select` renders a type-3 row; a malformed `select` fails the op; `ab:ops:spec:<p>` replies with the summary, and with the not-in-queue text for an unknown key; `/queue` with no project in ops mode writes a slash event; project-mode `payload` has no `ideas`.
- `board/tests/test_discord_feed.py`: `presence_op_due` resends when `bridge_state.presence` differs and 60 s passed, not before; no resend when it matches; missing bridge state treated as absent.
- `board/tests/test_discord_ops.py`: slash `/pause` then Resume all resumes the project; controls-path pause updates `paused_by_ops`; the `/ideas` slash from a project bridge is stored with bridge `_ops`; `/queue` slash without project posts one card per lead with the select and cut-off line; `spec_summary` on a real spec file from `docs/superpowers/specs/`, on a missing file, and with outcome and branch metadata.
- `board/tests/test_discord_ideas.py`: click keeps the first idea's text in the edit, adds the reply, a repeat tap sends nothing; a long body is cut, the status line kept; legacy post state without `body` falls back.
- One real check after the merge (user gate): `/queue` on the phone shows a card per lead, picking a spec shows its summary; `/ideas` from the agent-board bot lands in #command-center; Park shows the kept list and the `parked ✓` reply.

## Out of scope

- Frozen dialogs while remote (spec C).
- Narrowing the failed-run log by `metadata.worktree` (group B, e3ce28f853), though this spec adds the field.
- Editing old `/queue` cards in place, or a live-updating queue card.
- A rendered picture of the queue.
