# Remote UX: lead liveness on Discord, remote across handoffs, /ideas per project

Status: approved by the user on Discord, 2026-11-23 (D-Q1 1, D-Q2 1, design "Ok"). Source: the regroup of the ideas
inbox, group D "Discord / remote UX" (ideas 2026-11-19 18:46, 18:54, 2026-11-20 08:51). Parked from the group: natural-
language ops commands turned into engine policies (2026-11-12 01:27), until PCEE engine part 2 has its policy table.

## Goal

From the phone, the user can tell at a glance whether the lead got, read and answered a message, never has to ask
"update?", never lands on a successor lead that asks at the terminal, and sees in a project's own channel only that
project's ideas.

## Decisions (user, Discord, 2026-11-23)

1. Scope: a (lead liveness), b (remote across handoffs), c (/ideas per project bot). d parked.
2. Liveness is one state reaction on the user's latest message, swapped as the state changes, plus ❓ on demand.
3. The board computes lead state and hands it to the bridge as a file; no model in the path.

## 1. Lead state file (board)

On every overview (`board/overview.py`, about once a minute, and on each refresh the page asks for), the board writes,
for each project with a Discord bridge (`$TC_STATE/discord/<project>/bridge.json` present),
`$TC_STATE/discord/<project>/lead-state.json`, atomically (temp file + rename):

```json
{"at": "<ISO>", "state": "busy|ready|needs_you|down", "since": "<ISO>", "tool": "<running tool or null>",
 "queued": <int>, "last_read_text": "<first 200 chars of the newest Discord channel message in the lead's transcript, or null>",
 "holder": true|false}
```

- `state` from what the overview already knows about the lead pane: `needs_you` when a dialog or permission prompt
  waits in the lead pane; `down` when the lead window or pane is gone, the pane is dead, no claude process runs in it,
  or nobody holds the project's bot (`holder` false); otherwise `busy` or `ready` as agent-status reports it.
- `since`: when `state` last changed (kept across writes).
- `queued`: channel messages delivered to the lead and not yet in its transcript, when the transcript shows the
  plugin's queue; else 0.
- `last_read_text`: from the lead's transcript, the newest user row whose origin is the Discord channel.

The overview builder must not slow down: the transcript read is the tail the usage index already parses.

## 2. Reactions (bridge)

`tools/discord-bridge` (new `lib/liveness.js`, wired in `bridge.js`) reads `lead-state.json` every 10 s and keeps one
liveness reaction (the bot's own) on the newest message from an allowlisted user in the project's home channel:

| Reaction | When |
| --- | --- |
| 📨 | the message was posted and `state` is not `down` |
| ⏳ | `state` is `busy` and the message's text is not yet in `last_read_text` |
| 👀 | the message's first 200 chars equal `last_read_text` (read by the lead) |
| ✅ | the bot posted a message in the channel after it (the lead answered) |
| 🙋 | `state` is `needs_you` |
| ⚠️ | `state` is `down`, or `at` is more than 180 s old |

Order of precedence when several hold: ⚠️, 🙋, ✅, 👀, ⏳, 📨. A swap removes the bot's previous liveness reaction
and adds the new one; no swap when the reaction would not change. When the user posts a newer message, the older one
loses its liveness reaction. The plugin's own ackReaction (👀 on receipt, configured per project) is unaffected; when
both would show 👀 on the same message the bridge does not add a second one. Reaction calls go through the bridge's
existing rate-limited outbox.

**❓ on demand:** an allowlisted user reacting ❓ on any message in the home channel gets one reply line built from
`lead-state.json`, no model involved:
`busy 6m26s: <tool>; <n> message(s) queued` · `ready since 21:40` · `needs you: a dialog is waiting in <window>` ·
`down: <reason> since <time>` · `no lead state (board not running?)` when the file is missing or older than 180 s.
The bridge removes the user's ❓ after replying.

## 3. Remote carries across handoffs

- `board/relay.py` (the relay that starts a successor lead) and `tmux-ctl lead-restart` copy
  `$TC_STATE/remote/<old session id>` to `$TC_STATE/remote/<new session id>` as soon as the new session id is known
  (from its SessionStart record), when the old marker exists.
- `claude/plugin/scripts/remote-ask-guard.sh` gains one rule for a lead (`AGENT_BOARD_LEAD=1`) with no marker of its
  own: remote when the project's bridge recorded a message from an allowlisted user in the home channel within
  43200 s (12 h) and no terminal prompt from the user is newer (the newest user prompt in the lead's own transcript is
  not from a channel). The bridge, which sees every home-channel message for §2, writes the newest allowlisted
  user message's time to `$TC_STATE/discord/<project>/last-user-message.json` (`{"ts": <ISO>, "message_id": …}`);
  the guard reads that file.

## 4. /ideas per project bot

- `tools/discord-bridge/lib/commands.js`: project bots register `/ideas` too; on a project bot it covers only its own
  project (a `project` option naming another project is refused with one line), and its Park / Brainstorm / Drop
  buttons act on that project. The ops bot keeps `/ideas` across every project in #command-center, unchanged.

## 5. Parts

- `board/overview.py` (or a new `board/lead_state.py` called from it): the state file.
- `tools/discord-bridge/lib/liveness.js` (new), `bridge.js` (timer, ❓ handler, last-user-message.json), `lib/commands.js` (/ideas).
- `board/relay.py`, the `lead-restart` code in `bin/tmux-ctl`: the marker copy.
- `claude/plugin/scripts/remote-ask-guard.sh`: the 12 h rule.
- `docs/ARCHITECTURE.md`: lead-state.json and the reaction table.

## 6. Testing

- Board unit tests: each `state` from fixed overview inputs; `since` kept across writes and reset on change;
  `last_read_text` from a fixture transcript; atomic write; no file for a project without bridge.json; `TC_STATE` temp.
- Bridge node tests (fake Discord client, fake state file, fake clock): each reaction from the table, precedence,
  no-op when unchanged, the older message losing its reaction, stale file → ⚠️, ❓ reply lines including the missing-file
  line, ❓ from a non-allowlisted user ignored.
- Hook tests (`claude/hooks/tests/` style, temp state): marker copied on relay; guard remote by the 12 h rule; not
  remote when a newer terminal prompt exists; not remote after 12 h.
- Bridge test: a project bot's `/ideas` lists only its project and refuses another; the ops bot's lists all.
- One live check after merge (user gate, from the phone): send a message to the agent-board lead and watch
  📨 → ⏳/👀 → ✅; react ❓ once.

## Out of scope

Natural-language ops commands (parked); reactions in threads or on bot messages; liveness for teammates or peer
sessions; changing the plugin's ackReaction.
