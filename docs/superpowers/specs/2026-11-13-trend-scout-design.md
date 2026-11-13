# Trend scout: watch what's new outside, draft specs for what would improve agent-board

Date: 2026-11-13 · Decided with the user over Discord, 2026-11-13 (from Anthropic's "Superfans" idea: the user cannot
follow every AI trend or spot every improvement, and wants the system to find them)
Needs merged: `2026-11-11-discord-bridge-visibility-design.md` (outbox `post` with `files`, tiers, audit log),
`2026-11-11-discord-controls-design.md` (buttons, audit), `2026-11-12-opportunity-discovery-design.md` (the shared
findings core, §1 below).
Related: `2026-11-12-memory-consolidation-design.md` (the weekly-usage skip), ideas filed 2026-11-13: component
superfans, finding-to-work pipeline, guardrails on self-change (not part of this spec).

## Problem

New capabilities reach agent-board only when the user happens to notice them: Claude Code mods, agent teams, new
hooks, new models and prices, plugin releases, engineering posts such as Superfans. Nothing watches those sources, and
nothing turns "this release adds X" into "agent-board could use X here".

## Decisions (user, 2026-11-13)

- **The scout drafts specs.** It finds, judges and writes a spec for its best findings; the user only approves,
  rejects or asks for a revision. An approved spec joins the queue without another question.
- **Sources:** Claude Code releases; Anthropic news, engineering blog and docs release notes; the installed plugins;
  models and pricing; links the user posts in `#scout`. The user can add sources by hand. Community sources (Hacker
  News, GitHub trending) are not defaults.
- **Weekly:** one evaluate-and-draft pass on Sunday, at most 3 drafted specs, skipped at ≥ 85% weekly usage. The
  source poll runs daily and uses no model.
- **A headless pipeline on launchd**, not a lead task and not a long-lived agent.
- **Two specs, one core:** the scout builds on opportunity discovery's findings store, dismissal rules, digest
  renderer and button handlers, and keeps #11's own report-only behaviour unchanged.

## Design

### 1. The shared findings core (from opportunity discovery)

The scout uses these parts of the discovery implementation, by whatever names its plan gave them:

- a per-project findings state with stable keys, `reported`, `dismissed` (with an evidence count) and `filed`, and the
  rule that a dismissed key comes back only when its evidence grows ≥ 50%;
- the digest renderer (a numbered list with why / value / effort / risk / evidence links) and the outbox `post`;
- the `File as idea` and `Dismiss` button handlers and their audit lines.

Where one of these is not a reusable function in the merged discovery code, this spec's plan extracts it in place
(a refactor with discovery's tests still green, its behaviour unchanged) before using it. The scout's state is its own
file; it never writes discovery's.

### 2. Sources and the daily poll (code only)

- State directory: `~/.local/state/agent-board/scout/` (`TC_SCOUT_DIR` overrides; tests use it). Not `TC_STATE`'s
  temporary default: the seen-items list must survive a reboot.
- **Source kinds**, each a fetcher in the Python standard library, with the User-Agent `agent-board-scout` and no
  personal data in requests:

  | kind | reads | one item is |
  | --- | --- | --- |
  | `changelog_md` | a raw CHANGELOG.md | one version section |
  | `github_releases` | `https://api.github.com/repos/<o>/<r>/releases` (unauthenticated; `gh` token if `gh auth status` passes) | one release |
  | `rss` | an RSS or Atom feed | one entry |
  | `html_links` | an index page | one new article link (same host, path under the index) |
  | `html_diff` | a page | a change of the sha256 of its main text (the `<main>` element, else `<body>` minus nav/header/footer) |
  | `npm` | `https://registry.npmjs.org/<package>` | a new `dist-tags.latest` |
  | `plugin` | each installed plugin's marketplace source (`~/.claude/plugins` metadata) | a version newer than the installed one |
  | `discord_channel` | `#scout` messages through the Discord REST API with the project bot's token (read from the bot's `.env`, never printed or logged) | a message: each URL in it is fetched as a page item; a message `source: <url> <why>` is a source request (below) |

- **Default sources** (`scout.py` `DEFAULT_SOURCES`, written to `sources.json` on first run; the plan checks each URL
  answers and picks the right kind):
  1. Claude Code: its CHANGELOG.md (`changelog_md`) and the npm package `@anthropic-ai/claude-code` (`npm`); each item
     carries the installed version (`claude --version`).
  2. Anthropic news and engineering pages and the claude.com blog (`rss` where a feed exists, else `html_links`); the
     Claude Code and API docs release-notes pages (`html_diff`).
  3. Every installed plugin (`plugin`).
  4. The models overview and pricing pages (`html_diff`).
  5. `#scout` (`discord_channel`): the channel is created by the user and its id set with
     `tmux-ctl scout source add scout --kind discord_channel --url <channel id>`; without it the source is skipped and
     the digest says so.
- **Manual sources:** `tmux-ctl scout source add <name> --kind <kind> --url <url> --why "<text>"`,
  `scout source list`, `scout source remove <name>`, `scout source test <name>` (one fetch, prints the items it would
  collect, stores nothing). A `#scout` message `source: <url> <why>` adds a source after the bot replies with the
  parsed name and kind and the user reacts ✅ (audited); the kind is guessed (`rss` when the URL serves a feed, else
  `html_links`).
- **`tmux-ctl scout poll`**, launchd `com.user.agent-board-scout-poll`, daily 06:00 local: every source is fetched;
  new items (key: sha256 of source name + url + version or content hash) are appended to `items.jsonl` as
  `{key, source, kind, title, url, published, fetched_at, excerpt}` with the excerpt at most 4 KB of text. Seen keys
  are kept in `seen.json`. A source that fails is logged in `poll.log` and skipped; its failure count is kept, and
  three failures in a row put it in the next digest's source-health section. No model, no post.

### 3. The Sunday pass, `tmux-ctl scout weekly [--dry-run]`

launchd `com.user.agent-board-scout-weekly`, Sunday 07:00 local. Skipped (logged `scout: skipped, weekly <n>%`) when
weekly usage is at or over 85%, by the same numbers the memory job reads; a skipped Sunday is retried once on Monday
07:00. Skipped with no post when the week has no new items.

1. **Context pack (code)**, `context-pack.md`, at most 30 KB: the shared project context file; the README's layout
   section; every spec under `docs/superpowers/specs/` with its title and state (queued, merged, superseded: from the
   Status lines and git history); the ideas file's open titles; the installed Claude Code version and plugin versions;
   the Claude Code features in use (from `claude/plugin/hooks/hooks.json`, the mods index, `claude/session-settings.json`).
2. **Evaluate:** `claude -p --model sonnet --effort medium`, prompt `claude/scout-evaluate.md`, tools Read, Grep, Glob
   on the repo and WebFetch limited to the week's item URLs. Input: the week's items and the context pack. Output
   `evaluate.json`: per relevant item `{item, component, what_it_enables, value: high|medium|low, effort: S|M|L, risk,
   overlaps: [spec path or idea text], evidence: [{url, quote}]}`. Code drops an entry whose `item` is not one of the
   week's keys or that has no evidence quote. The finding key is `item key + component`; a key the findings state has
   as reported or dismissed (§1 rules) is dropped.
3. **Pick:** at most 3, by value (high first), then effort (S first); an entry with an overlap on a queued or
   unmerged spec is not drafted: it becomes an overlap note (`<spec>: could use <what_it_enables> (<url>)`).
4. **Draft:** for each pick, `claude -p` on the frontier tier's model (`docs/superpowers/model-routing.json`; on a
   model-limit error, once on Opus with a log line), prompt `claude/scout-draft.md`, in a worktree
   `.claude/worktrees/scout-<date>` on branch `scout/<date>` from `main`, 20-minute cap. The prompt asks for this
   repo's spec form: the header line `Proposed by: scout · Source: <url> (<published date>)`, Problem, Decisions
   (each marked *proposed, not approved*), Design, Error handling, Testing, Out of scope; every file it cites must
   have been read. Code checks after the run: the spec file exists at `docs/superpowers/specs/<date>-<slug>-design.md`,
   every repo path it cites in backticks exists (else the draft is dropped and listed as `dropped: cites missing
   <path>`), and whether it proposes changes to a **protected path**: `claude/orchestrator.md`, `claude/worker.md`,
   `claude/scout-*.md`, the scout's own code (`board/scout.py`, its CLI). Each draft is committed on the scout branch
   with the trailer `Scout-Item: <finding key>`.
5. **Digest:** one outbox `post` to the project's home channel, tier `progress`, rendered by the shared renderer:
   - **Drafted specs:** title, why in one line, value / effort / risk, source link, the spec file in `files`, and
     `⚠ touches protected files` when flagged. Buttons: `Approve` (`ab:scout:approve:<project>:<id>`), `Reject`
     (`ab:scout:reject:<project>:<id>`, an optional reason as the next message in the thread), `Revise`
     (`ab:scout:revise:<project>:<id>`, the note as the next message).
   - **Other findings** (up to 10, not drafted), each with `File as idea` and `Dismiss` from the shared core.
   - **Overlaps** (notes only), **dropped drafts**, **source health**, and the run's tokens.
   The post is edited to show each decision.
6. **Metrics:** each run is recorded with `tmux-ctl metrics` as kind `scout`: tokens per step, items, findings,
   drafts, dropped.

`--dry-run` runs every step but writes no state, makes no commit and prints the post instead of sending it.

### 4. Approve, reject, revise, expire

Each has a command equivalent: `tmux-ctl scout approve|reject|revise <id> [--note "<text>"]`; every action is
audited (controls spec).

- **Approve:**
  1. Copy the spec file from the scout branch onto `main` as one path-scoped commit
     `docs(spec): <title> (scout)` with the `Scout-Item` trailer. When the live checkout is mid-change (another
     session's uncommitted edits in that path, a merge or rebase in progress), wait and retry every 10 minutes, at
     most 24 hours, then post a `decision` line.
  2. Add the ideas line `- [x] <date> · scout: <title> → <spec path>` (a new `tmux-ctl idea --done "<text>" --spec
     <path>`, which appends the line already marked).
  3. Tell the lead: append `{spec, approved_at}` to `scout/approved.jsonl` and, when a lead runs for the project,
     type `[Scout] approved: <spec path>` into its window. The lead rule (`claude/orchestrator.md`, Ideas inbox): on
     that line, or at the Next-steps round for each unconsumed line of `approved.jsonl`, create a pending
     `Plan & run: <spec path>` task blocked by the last queued one, with `metadata.queue = {"integration": "merge",
     "push": false, "answeredAt": <approved_at>}` (and the running batch id when Queue mode has one), mark the line
     consumed, and ask nothing: the Approve is the user's queue answer. When the spec is flagged protected, the lead
     posts one `decision` line before it runs: `scout spec <title> changes protected files; approved by you at
     <time>`. No extra question.
- **Reject:** the finding key is recorded as dismissed (shared core rules) with the reason; the draft is not copied.
- **Revise:** the note is stored; the pick is redrafted at the next Sunday pass ahead of new picks (it counts toward
  the 3), or now with `tmux-ctl scout redraft <id>`; the revised draft replaces the old one in a new digest entry.
- **Expire:** a draft with no decision after 4 weeks is rejected with reason `expired`.
- A `scout/<date>` branch whose drafts are all decided is deleted, and its worktree removed.

## Error handling

- A model step fails or passes its cap: no digest that Sunday, the reason in `weekly.log`; two failed Sundays in a
  row post a `critical` line.
- A draft that fails the citation check is dropped and listed; the others are still posted.
- A fetch error never fails the poll; a source with an invalid kind or URL is refused at `source add`.
- `TC_SCOUT=0` or the file `scout/off` turns both launchd jobs into no-ops.
- The scout never writes `main` except through Approve, never pushes, and never edits the lead's rules or its own
  prompts by itself.

## Testing

- **Fetchers:** each kind against recorded fixture responses served by a local HTTP server: new, unchanged and
  broken responses; `html_diff` hashing ignores nav, header and footer; `plugin` compares versions; the Discord
  fetcher reads a fixture channel and never prints the token (a leak check greps logs and output for it).
- **Poll:** dedupe by key, `seen.json`, failure counts and the three-failures rule.
- **Sources CLI:** add, list, remove, test; refusal of a bad kind or URL; the `#scout` `source:` request with and
  without the ✅.
- **Weekly pass** with a fake `claude`: the context pack's size cap; evaluate output validation (unknown item, no
  quote, already reported, dismissed and regrown); pick order and the overlap rule; a draft citing a missing path
  dropped; the protected-path flag; the 85% skip and Monday retry; the no-new-items skip; `--dry-run` writes nothing.
- **Decisions** on a scratch repo with a fake lead window: approve copies one file path-scoped with the trailer and
  waits on a mid-change checkout; the ideas `--done` line; `approved.jsonl` and the `[Scout] approved:` line; reject,
  revise (redraft ahead of new picks), expiry after 4 weeks; branch and worktree cleanup.
- **Buttons** and audit lines through the controls spec's handler test harness.
- **Shared core:** discovery's tests still pass after any extraction.
- **Isolation:** `TC_SCOUT_DIR` in a temporary directory, a scratch git repo and a fake outbox; a leak check confirms
  the real state directory, repo, ideas file and Discord are untouched.
- **User gate:** one real `tmux-ctl scout weekly --dry-run` on this repo with real sources, its printed digest shown
  to the user.

## Out of scope

- Community sources as defaults (the user can add them by hand).
- Component superfans, the finding-to-work pipeline for inward findings, and guardrails on self-change in general
  (filed as ideas 2026-11-13).
- Building or merging anything a scout spec proposes; that runs through the queue like any approved spec.
- Scouting for projects other than agent-board.
