# Discord ticker: a live status line on the bots

Status: approved on Discord 2026-11-17. Depends on `2026-11-12-discord-ops-bot-design.md`; the ops-bot part needs its ops bridge.

## Goal

A glance at Discord's member list shows the user, without opening a channel, how much of the plan is left, how fast it's being used, how full each lead's context is, what the day has cost, and what is running. Every project bot and the ops bot each show one line as their custom status.

## User decisions (made on Discord, 2026-11-17)

- Where: the bot's own status line (Discord custom status). Not a pinned message, and not lines on the cards.
- Content: the default line, plus the running spec's progress, plus a ⚠ prefix.
- Which bots: both. Each project bot shows its own project, and the ops bot shows one line for everything.
- ⚠ on context: at **40% or more**.

## The line

Project bot, `<project>`:

    [⚠ ]wk <w>% ▲<pace>× · 5h <f>% · ctx <c>% · $<spend> · <spec> <k>/<n>

Ops bot:

    [⚠ ]wk <w>% ▲<pace>× · 5h <f>% · ctx max <c>% <project> · $<spend all> · <r> running

| Field | Source | Notes |
| --- | --- | --- |
| `w`, `f` | `usage.plan_limits(taps)`: `seven_day.used_percentage` and `five_hour.used_percentage` | Account-wide, so the same on every bot. |
| `pace` | `w / 100 ÷ elapsed`, where `elapsed = 1 − (seven_day.resets_at − now) / 604800` | One decimal. `—` while `elapsed < 12 h / 7 d`, or when there is no reset time. |
| `c` | the project lead's `context_pct` from `usage.live_sessions` (the `role == "lead"` row whose cwd is in the project) | Ops bot: the highest `c` across projects, with the project's name. `—` when no lead is live. |
| `spend` | overview record `spend_today` (the board's spend since local midnight) | Two decimals. The ops bot uses the sum across projects. |
| `spec k/n` | the running `Plan & run:` spec's short name (`discord_feed._spec_name`) and its own tasks: done/total of the tasks with a numeric id above the floor the status card already uses (`render_card`'s floor) | `idle` when no spec is running. Ops bot: `<r> running` = how many projects have a running spec. |

- **⚠** goes first when any of these holds: pace > 1.2, `f` ≥ 80, `c` ≥ 40 (on the ops bot, the max `c`).
- **Stale usage**: when the freshest tap with rate limits is older than 10 min (`received_at`), `w`, `pace` and `f` show `?`, and they never trigger ⚠.
- **Length**: at most 128 characters (Discord's custom-status limit). The spec name is trimmed first, with `…`.
- The line has no clock time, so a bridge that is down does not leave a misleading time behind.

## Flow

1. The board's feed tick (`server.feed_tick`, per project with a bridge) builds the project line with a pure function, `ticker.project_line(record, live, limits, lead_tasks, now)`, in a new `board/ticker.py`. The ops tick (`discord_ops.tick`) calls `ticker.ops_line(records, live, limits, tasks_by_project, now)`.
2. When the text differs from the last one sent and at least 60 s have passed since that send, the board writes the outbox op `{"op": "presence", "text": "<line>"}`. The last text and its time are kept in `feed-state.json` (project) or the ops state (ops bot). The op is validated in `discord_feed._check`: `text` is a non-empty string of at most 128 characters.
3. The bridge (`tools/discord-bridge/bridge.js`), in both modes, applies the op with `client.user.setPresence({ activities: [{ type: ActivityType.Custom, name: "custom", state: text }], status: "online" })`. It keeps the last text and re-applies it after a reconnect (`ready` / `shardResume`). A failure is logged to `bridge.log`, and the op is consumed rather than retried, because the next tick sends a fresh line.
4. Nothing is posted, so nothing notifies the user.

## Delivery semantics (presence op)

- **Repeated**: setting the same status twice is harmless.
- **Out of order**: the bridge applies outbox files in name (time) order, as it does for the other ops, so the newest line wins.
- **Concurrent**: one bridge per bot, and the board writes under the feed-state flock.

## Errors

- No taps with rate limits: `w`, `pace` and `f` are `?`.
- The ops bridge isn't configured: no ops line is built (`discord_ops.configured()`).
- A Discord rate limit or error on `setPresence`: logged, and the next change retries.

## Testing

- `board/tests/test_ticker.py`: the line builders against fixture records. Cover pace (normal, under 12 h, no reset time), each ⚠ trigger including ctx at 39% (no ⚠) and 40% (⚠), stale taps, the 128-character trim, idle, and the ops max-ctx pick and running count.
- Feed tick: a `presence` op is written on change, not on the same text, and not twice within 60 s. `_check` rejects text over 128 characters or empty text.
- Bridge: the op calls `setPresence` with the custom activity on a fake client, re-applies after `shardResume`, and logs and consumes a thrown error.
- Real-state check (read-only): build both lines from the live board's `api/overview` and `api/usage` and print them. The `k/n` must match the running plan's own task count, not the whole list.
- User gate: the user confirms on the phone that both the agent-board bot and the ops bot show the line in the member list, and that it changes within about 2 min of a change (for example a task completing).
