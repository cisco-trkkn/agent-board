# Discord files: reports, logs and board snapshots out; images in

Date: 2026-11-11 · Decided with the user over Discord, 2026-11-11 (ideas 6, 7 of the Discord round)
Needs merged: `2026-11-11-discord-bridge-visibility-design.md` (outbox `post` with `files`, spec threads).

## Design

### 1. Files out

- The outbox `post` op already carries `files: [abs paths]` (bridge spec). The bridge attaches them (max 10, 25 MB
  each, as Discord allows; a bigger file is replaced by a line `<name> too large (<size>)`).
- Automatic, by `board/discord_feed.py`:
  - the morning report (`docs/superpowers/reports/YYYY-MM-DD-queue.md`) attached to the channel post when it is
    committed;
  - a failed spec: the last 200 lines of its failing test run (the run record's output file) attached to the spec
    thread's `failed — …` post, as `<run id>.log`.
- On request, a new `tmux-ctl discord send [--thread <key>] <file>… [-m <text>]` writes a `post` op (paths made
  absolute, each must exist and be readable). The lead uses it to send a spec, plan, diff or log when the user asks;
  the plugin's own `reply files:` stays usable in the conversation.
- Board snapshot: `tmux-ctl discord snap [<project>]` renders the board's overview page to PNG with headless Chrome
  (`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=<tmp>.png
  --window-size=1200,1600 <board url with token>`), then sends it like `send`. No Chrome: exit 1 with
  `snap: Chrome not found`. The temporary PNG is deleted after the bridge sent it. The board URL with its token is
  never posted.
- Lead rule: "When the user asks for a file, a report, a log or a picture of the board from Discord, use `tmux-ctl
  discord send` or `snap`."

### 2. Images in

The plugin already delivers attachments (`attachment_count` and names in the channel tag; `download_attachment`).
Lead rule in § Remote: Discord: an image the user sends is downloaded with `download_attachment` and Read before
answering; for a bug report it goes to `systematic-debugging` like any other bug, and the downloaded path is cited in
the reply. Files are kept in the plugin's inbox dir; nothing is copied into the repo unless the user asks.

## Testing

- `send`: op written with absolute paths; missing file → exit 1, no op; `--thread` key passed through.
- `snap`: fake Chrome on PATH writes a PNG; op written; temp file cleanup after a fake bridge ack; URL with the token
  never in the op text.
- Feed: morning report and failed-run log attachments from fixtures.
- Bridge: files attached; oversize replaced by the line.
- One real run (user gate): `snap` arrives on the phone; the user sends a photo and the lead describes it.

## Out of scope

- Voice notes (dropped by the user).
