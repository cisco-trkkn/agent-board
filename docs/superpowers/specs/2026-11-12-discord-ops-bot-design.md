# Discord ops bot: command center, approvals inbox, daily digest, slash commands

Date: 2026-11-12 · Decided with the user over Discord, 2026-11-12, from the review of an outside architecture write-up
("Discord as the mobile interface to PCEE": hybrid interaction, autonomous execution with decision gates,
exception-driven notifications).
Needs merged: `2026-11-11-discord-bridge-visibility-design.md` (bridge, outbox/events spool, feed events §11, tiers
§8, deep links §9, audit §10) and `2026-11-11-discord-controls-design.md`.

## Problem

Each project has its own bot and channel, but nothing shows all projects at once on the phone, decisions are spread
over project channels, and every action needs typing or a reaction. The goal is to run the projects from the phone
without opening the laptop: see everything in one place, decide in one place, act with taps.

## Decisions (user, 2026-11-12)

- **A separate ops bot** (its own Discord app, "agent-board ops"), not a project bot. State dir
  `${TC_STATE}/discord/_ops/` (`_ops` cannot collide with a project name: project names must start with a letter or
  digit). Same token, pairing and access rules as a project bot; `tmux-ctl discord token|pair|policy|status --ops`.
- **Discord is never the source of truth.** The board owns state; the ops bridge renders and forwards.
- **Ops chat goes to the overseer**, the existing read-only session (`claude/overseer.md`), started with
  `--channels plugin:discord@…` and `DISCORD_STATE_DIR=<_ops dir>` by `bin/tmux-overseer` when the ops token exists.
  It answers questions across projects and has no authority, as today. Actions come only from the structured controls
  below, never from the overseer.

## Design

### 1. Channels

In the user's private server, set with `tmux-ctl discord ops-channels <command-center id> <approvals id>`
(writes `<_ops>/bridge.json` and adds both to `<_ops>/access.json` `groups` with `requireMention: false`):

- **#command-center**: one pinned card across all projects, critical alerts, the daily digest, and chat with the
  overseer.
- **#approvals**: one post per open decision from any project, each with its buttons; resolved posts are edited to
  their outcome and stay as history.

The ops bridge is the same `tools/discord-bridge/bridge.js` started with `--ops`; the board starts it like a project
bridge (`ensure_discord_bridges`).

### 2. Command-center card

Rendered by the board from `overview.build` (the overseer's data), edited at most every 30 s, ≤ 1900 characters:
per project one line `<project> · <queue state> · <running spec> k/n · <blockers> · <waiting on you n>` with a deep
link to that project's channel; a header with weekly and 5-hour usage and today's spend; buttons:

| Button | customId | Effect (through the board, audited) |
| --- | --- | --- |
| Pause all | `ab:ops:pause-all` | confirm step (second button "Confirm pause all", 60 s), then `[Discord] 🛑 pause the queue` to every lead with a running queue |
| Resume all | `ab:ops:resume-all` | `[Discord] ▶️ resume the queue` to every lead with a paused queue |
| Inbox | `ab:ops:inbox` | ephemeral list of open approvals with links |

### 3. Approvals inbox

- Every `decision`-tier feed event from any project is also posted in #approvals (the project channel keeps its
  copy; both posts are edited when it resolves).
- Kinds and their buttons:
  - teammate permission prompt (controls spec): Allow once / Deny, same flow;
  - a lead's question to the user: the question text and a "Reply in <project channel>" deep link; ✅/❌ reactions
    work as in the controls spec;
  - **merge approval**, for a queued spec whose stored integration is `ask` (a new value of `metadata.queue.integration`
    added by this spec, for specs the user wants to approve from the phone): the post shows the evidence: branch,
    target, changed files with +/- counts (`git diff --stat`, first 25 files, then `… <n> more`), test verdict line,
    final-review verdict and its Important/Critical findings (one line each), and a diff summary. Buttons: Merge
    (`ab:ops:merge:<task id>`), Keep branch, Show files (paged ephemeral file list, 10 per page, Next/Prev), Show diff
    of a file (select menu of the changed files, ephemeral reply with up to 1800 characters of that file's diff and
    a "too long, see board" note past that). Merge writes `[Discord] merge approved for <spec>` to the lead, which runs
    `finishing-a-development-branch` with `merge`.
- Queue mode reads `ask`: the lead finishes the spec up to the merge, keeps the branch, posts the decision, and moves
  on to the next spec; the approval later merges it. One line in `claude/orchestrator.md` § Queue mode.

### 4. Daily digest

At 08:00 local (configurable `TC_DISCORD_DIGEST_AT`, `off` disables), one post in #command-center: per project specs
merged / failed / still running since the last digest, open decisions with links, test runs failed, spend and usage.
Built from the feed files and metrics; a project with nothing new is one line `<project>: quiet`. Critical alerts are
never held for the digest.

### 5. Slash commands and forms

Registered by the ops bridge as guild commands in the user's server; project bridges register the same set scoped
to their channel where it applies. Every command answers ephemerally, checks the user is in `allowFrom`, and is
audited.

| Command | Effect |
| --- | --- |
| `/status [project]` | the card text for all projects or one, ephemeral |
| `/queue <project>` | the queue view (`taskwin.py render --view queue --plain`), ephemeral |
| `/pause <project>` · `/resume <project>` | the reaction-control lines to that lead |
| `/idea <project>` | opens a form (title, text); submits through `tmux-ctl idea` for that project; 💡 reply |
| `/new-spec <project>` | form (what, why); posts it to the lead as `[Discord] new spec request: <what> — <why>`; the lead starts `brainstorming` with the user in that project's channel |
| `/approvals` | ephemeral list of open decisions with links |

No command runs a shell command or takes a free-form command line.

## Error handling

- Ops bridge down: project bridges keep working; the card in #command-center goes stale and shows its `updated` time.
- A merge approval clicked after the branch moved: the board re-checks the branch tip against the evidence's SHA; on a
  mismatch the post is edited to `branch changed since this was posted` with a fresh evidence post.
- Command from a non-allowlisted user: ephemeral "Not authorized.", audited as rejected.

## Testing

- Card rendering across fixture overviews of two projects, length cap, button ids.
- Pause-all needs the confirm within 60 s; lines go only to leads with a running queue.
- Approvals: one post per decision mirrored in both channels; both edited on resolution; merge evidence from a fixture
  repo (diff stat cut at 25, review findings lines); paging and the file select; SHA mismatch path.
- Queue mode with `integration: ask`: branch kept, decision posted, next spec started (fake lead transcript check).
- Digest from fixture feed files; `quiet` lines; `off`.
- Slash commands: registration payload, allowlist check, each command's effect through a fake board, audit lines.
- One real run (user gate): from the phone only, the user checks status, files an idea with `/idea`, approves a merge
  with evidence, and pauses and resumes all.

## Out of scope (parked as ideas)

Lead-to-lead negotiation, a task marketplace, multi-project federation, continuous architecture scanning, natural
language orchestration commands ("start every plan with no blockers"): later PCEE stages.
