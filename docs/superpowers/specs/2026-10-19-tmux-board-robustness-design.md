# tmux and board robustness (Group C) — design

Date: 2026-10-19 · Ideas group C (from `~/.claude/ideas/agent-board.md`):
- the board's 2s poll logs an unhandled "TypeError: Failed to fetch" on every tick while the server is down;
- `test_bg.zsh` "parallel runs stay clean" fails about 2 runs in 8 under load;
- `tmux-teammate-window` should act only on the new pane (`#{pane_id}`);
- each agent window should show its role, model and effort, not the window number;
- `tmux-ctl run` reports a `tests` window running a zsh script as idle;
- `tmux-ctl artifact` registers plans and specs as kind `other`;
- a doc from project A open in its Changes view shows "Loading…" while viewing project B.

## Decisions

- **Agent labels:** shown in both places, the tmux window tabs and the board cards.
- **Label source:** the board server keeps `@tc_label` up to date from the usage index. Labels update only while the board runs, and appear after an agent's first API call.
- **Window number:** the window number (`#I`) is dropped from the tmux tab format.
- **`~/.tmux.conf`:** this file is not in the repo. Its changes are staged as a generated patch for the user to install; nothing edits it directly.

## 1. Board poll while the server is down — `board/index.html`

- `refresh()` returns `true` when `api/state` answered and `false` otherwise.
- `poll()` runs `pollArtifacts`, `pollIdeas` and `pollActivity` only after a `true`.
- A single banner element `#offline-banner` reads "Board server unreachable — retrying". It is shown while `refresh()` returns `false` and hidden on the next `true`.
- No `console.error` while offline. Other errors are still logged, once per distinct message.

## 2. `tmux-ctl` busy check, and the `test_bg` flake — `bin/tmux-ctl`

- **Busy check:** a pane is **busy** when its shell process has at least one child: `pgrep -P <#{pane_pid}>` finds a process. A pane is **idle** otherwise. The test replaces the shell-name comparison in `is_idle`, in `settle_win` and in `list`'s idle/busy column. `SHELLS` stays only where the code needs to know whether the pane runs a shell at all.
- **Effect:** a `tests` window running `zsh tools/tests/run-all.zsh` is busy, so a second `tmux-ctl run tests …` goes to a lane.
- **The flake:** it is debugged with `superpowers-extended-cc:systematic-debugging`, not with a fix guessed in advance.
  1. Reproduce the 8-iteration loop under load with the new busy check in place.
  2. If it still fails, find the interleaving with evidence. The candidate is `lock_win` reclaiming a lock whose `pid` file is not yet written.
  3. Fix only what the evidence shows.
  4. Done when the loop passes 20 runs in a row under load (for example with a parallel `run-all.zsh`).

## 3. Teammate hook acts on the new pane — `bin/tmux-teammate-window`, `~/.tmux.conf`

- **Hook mode with a pane:** `tmux-teammate-window --hook <pane_id>` checks only that pane: its start command (a `--agent-name` start command, or `cat`), its window's pane count, and `@tc_teammate`. Moving the pane and naming it work as today.
- **Hook mode without a pane:** keeps today's full scan, so an old hook line still works.
- **Staged `~/.tmux.conf` change:** the hook line becomes `set-hook -g after-split-window 'run-shell -b "~/.local/bin/tmux-teammate-window --hook #{pane_id}"'`.

## 4. Agent labels — `board/usage.py`, `board/server.py`, `board/index.html`, `~/.tmux.conf`

- **Matching:** `usage.card_labels(sessions, live)` matches panes to live sessions with the same project-scoped rules as `card_alerts`:
  - a teammate window `✦ <name>` matches `agent_name`;
  - a worker pane's path matches the `cwd` of a live session with no `agent_name`;
  - the `claude` window matches the newest live session with no `agent_name` in the repo.

  It returns `{pane_id: {"role", "model", "effort", "label"}}`.
- **Model family:** the second dash-separated token of the model id (`claude-sonnet-5-5` → `sonnet`).
- **Effort:** abbreviated as `low`, `med`, `high` or `max`. An unknown value is shown as is.
- **Label text:**

  | Window | Label |
  | --- | --- |
  | Teammate | `✦ <name> · <family>·<effort>` |
  | Lead (`claude` window) | `claude · <family>·<effort>` |
  | Worker | `<window name> · <family>·<effort>` |

  Without an effort, the label drops `·<effort>`.
- **Writer (`server.py`):** after each indexer snapshot, `sync_labels()` builds the state and computes `card_labels`.
  - For every agent window whose wanted label differs from its current `@tc_label`, it runs `set-option -w -t <window> @tc_label <label>`.
  - On an agent window with no match, it unsets `@tc_label` (`set-option -wu`).
  - It writes only on change. It runs in the indexer thread, never on the `api/state` request path.
- **Board cards:** `api/state` carries `usage_labels` per session. The card's `window N` text becomes `role · model · effort` when there is a label, else `window N` stays.
- **Staged `~/.tmux.conf` change:** `window-status-format` and `window-status-current-format` drop the leading `#I `, giving `#{?@tc_label,#{@tc_label},#W}`.

## 5. Artifact kind — `bin/tmux-ctl`

`tmux-ctl artifact <path>` passes `--kind <k>` to `artifact-register.sh` only when the user gave `--kind`. Otherwise the hook's `kind_of()` decides (plan, spec), and falls back to `other` in manual mode.

## 6. Doc pane across projects — `board/index.html`

`renderDoc` looks up versions under `docSess`, the doc's own project, not `session()`. While the viewed project is not `docSess`, `pollArtifacts` does not re-render the doc pane.

## Staged `~/.tmux.conf` patch

- **Output:** `~/.claude/staged/tmux.conf.patch`, generated with `diff -u` from a copy of the live file with both edits applied.
- **Check:** it passes `patch --dry-run` against the live file before being reported.
- **Who installs it:** the user. Install command: `cp ~/.tmux.conf ~/.tmux.conf.bak-YYYYMMDD && patch ~/.tmux.conf < ~/.claude/staged/tmux.conf.patch && tmux source-file ~/.tmux.conf`.

## Testing

**zsh harness** (scratch tmux servers with `-f /dev/null`, never the live server):
- **Busy check:**
  - a pane running `zsh -c 'sleep 5'` is busy, and `run` goes to a lane;
  - an idle shell is idle.
- **Flake:** the `test_bg` parallel loop passes 20 times in a row under load. The evidence goes in the report.
- **Hook:**
  - `--hook <pane>` moves a flagged teammate pane;
  - it leaves a plain split alone;
  - it ignores other windows' unflagged teammate panes;
  - the no-argument mode still works.
- **Artifact kind:** a manual `tmux-ctl artifact docs/superpowers/plans/x.md` registers kind `plan`; an explicit `--kind other` still wins.

**Python:**
- `card_labels`: one test per window rule, a project-scoping test, and the effort abbreviations.
- `sync_labels`: the tmux seam is mocked; it writes only on change and unsets an unmatched window's label.

**Live check** (scratch board on its own port, with real `~/.claude/projects` read-only):
- the offline banner appears when the server stops and clears when it restarts;
- the labels on the scratch tmux server's windows match their sessions;
- a doc left in Changes view in project A doesn't show "Loading…" in project B.

Every probe must be able to fail.

## Out of scope

Labels for non-agent windows; a label without the board running; changing `#W` automatic renaming.
