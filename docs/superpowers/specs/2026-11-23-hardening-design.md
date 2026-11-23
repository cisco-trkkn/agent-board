# Hardening: SHA-pinned merge approval, scout sources (safe and easy), context recall for teammates

Status: approved by the user on Discord, 2026-11-23 (E-Q1 1, E-Q2 1, design "Ok"). Source: the regroup of the ideas
inbox, group E (ideas 2026-11-20 09:44, 2026-11-21 13:26, 2026-11-20 08:46). Three independent parts in one spec;
each has its own tests and none depends on another.

## Decisions (user, Discord, 2026-11-23)

1. One spec, three parts.
2. Adding a scout source must be easy: `source: <url>` or `/source <url>` detects the kind, and ✅ adds it at once
   with a test fetch whose result is shown.

## a. Merge approval pinned to a commit SHA

Today (`board/discord_merge.py`): the merge-request card carries the branch tip SHA; the Merge button (`on_merge`)
re-checks the tip and, when it moved, re-posts fresh evidence instead of approving; when it matches it sends the lead
`[Discord] merge approved for <spec>`. The gap is between that line and the lead's merge: the branch can move.

- `on_merge` sends `[Discord] merge approved for <spec> @ <full sha>` (the SHA it just checked).
- `claude/orchestrator.md` (Queue mode step 2, the `ask` branch): on that line the lead runs
  `finishing-a-development-branch` with `merge` **of that SHA**: it first checks `git rev-parse <branch>` equals the SHA;
  if not, it does not merge, runs `tmux-ctl discord merge-request` again (fresh evidence) and keeps the outcome
  `awaiting merge approval <branch>`. The merge merges the SHA, not the branch name. The outcome records
  `merged <merge sha>`. The rule text stays on continuation lines (Queue mode step-line tests,
  `tools/tests/test_plugin.zsh`, `tools/tests/test_queue_ask_rule.zsh`).
- A line without `@ <sha>` (an old card) is treated as not pinned: the lead re-requests instead of merging.
- Tests: `board/tests/test_discord_merge.py`: the approved line carries the full SHA; a moved tip still re-posts.
  `tools/tests/test_queue_ask_rule.zsh`: the rule names the SHA check and the re-request.

## b. Scout sources: one safe URL check, kind detection, instant add

### b1. One URL check

`board/scout_sources.py` gets `check_url_safe(url)` used by every source add, every #scout `source:` request and
every fetch in `board/scout_fetch.py` (the existing `_check_request_url` and the loopback check at
`scout_fetch.py` ~560 call it):

- scheme https, except the existing `_HTTP_OK_HOSTS` exemptions;
- the host resolves (`socket.getaddrinfo`), and every resolved address is global: not private, loopback, link-local,
  multicast, reserved or unspecified (`ipaddress`, IPv4 and IPv6, including IPv4-mapped IPv6), so 169.254.169.254,
  10/8, 172.16/12, 192.168/16, 127/8, ::1, fc00::/7, fe80::/10 are refused; a literal IP host gets the same test;
- each redirect hop is checked again before it is followed (the fetcher follows redirects by hand, at most 5).

A refusal raises `Refusal("<reason>")` with a one-line reason (`private address 10.0.0.5`, `link-local`, …).

### b2. Kind detection

`detect(url) -> {kind, url, name, prefix?}` in `board/scout_sources.py`, first match wins:

| URL | kind | url used |
| --- | --- | --- |
| `https://github.com/<o>/<r>` (optionally `/releases`) | `github_releases` | as the existing kind expects |
| `https://www.npmjs.com/package/<p>` | `npm` | the package name |
| a raw URL ending in `CHANGELOG.md` | `changelog_md` | as given |
| a page whose HTML has `<link rel="alternate" type="application/rss+xml|application/atom+xml">` | `rss` | the feed URL (absolute) |
| a URL that is itself RSS/Atom (content type or root element) | `rss` | as given |
| anything else | `html_links` | as given, prefix = its path |

Name default: host without `www.` plus the first path segment, lowercased, cut to fit `NAME_RE`, with `-2`, `-3`… on a
duplicate. Detection fetches at most one page (through the b1 check) and has a 10 s timeout; a failed fetch falls back
to `html_links`.

### b3. Adding from Discord

- `source: <url> [name]` in #scout (today's request) and a new `/source <url> [name]` slash command on the agent-board
  bot (`tools/discord-bridge/lib/commands.js`, allowlisted users only) both run `detect` and reply with what would be
  added: `<name> · <kind> · <url>`, react ✅ to add.
- On ✅ from an allowFrom user the source is added **at once** (not at the next daily poll) and fetched once; the reply
  is edited to show `added: <name> (<kind>)` and the first 3 item titles, or `added, first fetch failed: <reason>`
  (the source stays; failures show in the health report as today). A refused URL (b1) gets `refused: <reason>` and
  no ✅ prompt.
- The add path is one function used by the CLI, the #scout request and `/source`; `tmux-ctl scout source add <name> --kind <k> --url <u>`
  keeps working; `--kind` becomes optional and, when left out, `detect` picks it. The tmux-ctl help header line for it
  is edited in place (the header range is pinned by suites; add no line).

Tests (`board/tests/test_scout_sources.py`, `test_scout_fetch.py`, bridge node test for `/source`): each refused
address class with a fake resolver; one real resolution of `localhost` refused; redirect to a private address refused;
each detection row from fixture HTML; name defaults and duplicates; ✅ adds and fetches once with a fake fetcher;
refused URL gets no prompt.

## c. Context recall for teammates

Today `claude/plugin/scripts/context-recall.sh` runs on UserPromptSubmit at a session's first prompt and injects
archived context entries whose `files:` paths the prompt names. A teammate's spawn prompt fires no UserPromptSubmit,
so a teammate gets nothing.

- A new PostToolUse hook (`claude/plugin/scripts/context-recall-file.sh`, registered in the plugin's `hooks.json` for
  `Read|Edit|Write|Grep|Glob`) takes the tool's path argument (repo-relative after resolving against the repo top
  level), and once per (session, path), injects as `additionalContext` the archive entries whose `files:` cite that path,
  at most 4096 bytes per call, newest own date first, entries already injected in this session skipped. Marker:
  `<state>/context-recall/<session_id>.paths`. Same project resolution, kill switch (`TC_CONTEXT=0`) and silent
  failure as `context-recall.sh`.
- The first-prompt recall stays as is.
- Tests (`claude/hooks/tests/` style, temp state and context dir, a scratch tmux pane as the existing recall tests
  use): a Read of a cited path injects its entry once; a second Read of the same path injects nothing; a path no entry
  cites injects nothing; `TC_CONTEXT=0` silent; the 4 KB cap.

## Parts

- a: `board/discord_merge.py`, `claude/orchestrator.md`, their tests.
- b: `board/scout_sources.py`, `board/scout_fetch.py`, `tools/discord-bridge/lib/commands.js` (+ bridge wiring),
  `bin/tmux-ctl` (`--kind` optional), their tests.
- c: `claude/plugin/scripts/context-recall-file.sh` (new), `claude/plugin/hooks/hooks.json`, tests.

## Out of scope

Other scout fetch kinds; changing how sources are polled; recall for peer sessions outside the project.
