# Agent Board: agent controls (right-click menu, shut down workers and teammates)

Date: 2026-10-16. The ideas inbox (group A) covers two ideas: a UI button to shut down one-off agents, and moving "Restart orchestrator" off its visible button into a right-click action on the orchestrator's card.

Code: `~/.local/share/tmux-dash` (`index.html`, `server.py`, `artifacts.py`, `tests/`) and `~/.claude/orchestrator.md`. None of these are under git: back up each one as `F.bak-YYYYMMDD-agentctl` before editing it.

## Goals

- **Shut down a worker from the board:** a worker started with `tmux-ctl agent` (or the board's `+ New agent`) can be shut down without a terminal.
- **Shut down a teammate from the board:** the board asks the lead to shut a teammate down, so the lead's team bookkeeping stays correct.
- **Fewer visible risky buttons:** restart, shutdown and ask-to-shut-down live in a right-click menu on the agent's card. The visible "Restart orchestrator" button is removed.

Non-goals:
- shutting down plain Claude windows that are neither worker nor teammate (they keep the browser's own menu);
- removing worktrees or branches as part of a shutdown (the Worktrees panel already does that);
- a `⋯` button on cards;
- editing ideas (group D) and the usage dashboard (group C).

## 1. Agent menu (`index.html`)

- **Opening:** right-click (`contextmenu`) on an agent card opens a menu at the pointer, with `preventDefault` so the browser's menu doesn't show. A 500ms long press (pointerdown without a move of more than 10px and without pointerup) opens it too, for touch. The menu is clamped to the viewport.
- **Closing:** Escape, a click outside the menu, scrolling the main column, or choosing an item. Only one menu is open at a time.
- **Keyboard:** focus moves to the first item when the menu opens; Up/Down move between items, Enter or Space chooses, Escape closes and returns focus to the card.
- **Items by role** (the role is the existing `role(s, w, p)` plus the orchestrator check):

  | Card | Item | What it does |
  | --- | --- | --- |
  | Orchestrator (`w.name === "claude"`, Claude pane) | Restart orchestrator… | The existing confirmation text, then `restart_orchestrator` with `confirm: true` (unchanged behaviour) |
  | Worker (`w.worker`) | Shut down worker… | Confirmation, then `stop_agent` (section 2) |
  | Teammate (`w.teammate`) | Ask lead to shut down… | No confirmation (it only sends a request), then `ask_shutdown` (section 3) |
  | Any other card | none | The browser's own menu shows |

- The menu uses the board's existing tokens and the danger colour for destructive items. Results show through the existing `action()` toast.
- The card's visible "Restart orchestrator" button is removed. Open terminal and Message stay.

## 2. Worker shutdown: `stop_agent` (`server.py`)

- **Confirmation (client):** `Shut down <name>? Its window closes. Its worktree and branch stay in Worktrees for cleanup.`
- **Request:** `{action: "stop_agent", session, window: <window name>}`.
- **Server:**
  - `session` must pass `NAME_RE` and must not start with `_web-`.
  - Look for windows named exactly `window` in the project session and in `<session>-bg` when that session is tagged `@tc_bg` (a worker can live in either). Use `list-windows -F` with `#{window_id}`, `#{window_name}`, `#{@tc_agent}`, `#{@tc_teammate}`.
  - Refuse unless exactly one match exists and it has `@tc_agent == 1`. Errors: `no worker window named <name>`, `<name> is not a worker` (lead, teammate, shell, any untagged window), `more than one window named <name>; close it from its terminal`.
  - Kill it with `kill-window -t <window_id>` (the id, never the name, so a rename between check and kill can't hit another window).
  - Returns `shut down worker <name>; its worktree and branch are still in Worktrees`.

## 3. Teammate shutdown: `ask_shutdown` (`server.py`, `artifacts.py`, `orchestrator.md`)

- **Request:** `{action: "ask_shutdown", session, window: <window name>}`.
- **Server:** `session` must pass `NAME_RE`. Exactly one window in the project session must have that exact name and `@tc_teammate == 1`, or the request is refused (`<name> is not a teammate`). The teammate's name is the window name without the leading `✦ ` (and whitespace).
- **Queue:** `CommentQueue` gains `add_line(sess, text)`. It stores an item with a `text` field, and `line(c)` returns `c["text"]` for such items, so it goes through the same delivery path as Plan comments: held while the lead shows a prompt (`status == "waiting"`), while its input line has text, or while it isn't running, and delivered in order with the Plan comments. Queued text: `[Board] Please shut down teammate <name>.` A second request for the same teammate while one is still queued is not added twice.
- **Reply:** `asked the lead to shut down <name>`; the client shows it as a toast.
- **Lead rule:** one line in `~/.claude/orchestrator.md`, in "Controlling other agents in the project": a line `[Board] Please shut down teammate <name>.` was sent by the user from the board; send that teammate a `shutdown_request` (with the usual SendMessage note in its reason) and confirm in one line.

## 4. Errors

- Every refusal comes back through the existing `_act` error path and shows as an error toast; nothing is killed or queued on a refusal.
- `tmux` failures in `stop_agent` surface their stderr in the toast.
- A worker that already exited (its window back at a shell prompt) is still a worker window: shutting it down just closes the window.

## 5. Tests

- **Unit (`tests/test_agent_controls.py`, fake tmux runner like `test_restart_orchestrator.py`):**
  - `stop_agent` kills only a window with `@tc_agent == 1`, by window id, found by exact name in the project or tagged `-bg` session;
  - it refuses the lead (`claude`), a teammate, a shell, an untagged Claude window, a name that only matches as a prefix, an ambiguous name, a missing name, and a `_web-` session;
  - `ask_shutdown` queues exactly one `[Board] Please shut down teammate <name>.` line, refuses a non-teammate, and does not queue a duplicate;
  - `CommentQueue` holds an `add_line` item while the lead is waiting or its input has text, and delivers it once it is idle, in order with Plan comments.
- **Live in Chrome, on the real board with its accumulated state** (use `elementFromPoint`, not `getBoundingClientRect`, for visibility):
  - right-click opens the right menu for the orchestrator, a worker and a teammate, and nothing for a plain window or shell;
  - keyboard navigation and Escape work; the visible Restart button is gone;
  - shut down a scratch worker started from the board's `+ New agent`; its window disappears and its worktree stays listed;
  - "Ask lead to shut down…" shows the toast and the line arrives in the lead's pane (scratch session with a scratch teammate window, or a dry check against the queue if no team is running).

## 6. Files

- `~/.local/share/tmux-dash/index.html`: agent menu; remove the Restart button.
- `~/.local/share/tmux-dash/server.py`: `stop_agent`, `ask_shutdown` in `_act`.
- `~/.local/share/tmux-dash/artifacts.py`: `CommentQueue.add_line` and `line()` for text items.
- `~/.local/share/tmux-dash/tests/test_agent_controls.py`: new.
- `~/.claude/orchestrator.md`: the one lead rule.

Restart the board with `tmux-dash stop && tmux-dash start` after the server changes.
