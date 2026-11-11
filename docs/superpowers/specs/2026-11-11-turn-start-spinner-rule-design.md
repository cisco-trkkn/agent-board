# One spinner rule for the board and the Telegram watchdog; the real remove() under test

Date: 2026-11-11

## Problem

1. **The board shows a turn's first frame as ready.**
   - `board/paneclass.py` `spinner_live` treats a first-frame spinner (`✽ Actioning…`, with no `(elapsed …)` part yet) as live only when blank rows follow it.
   - A real turn starts with a tip row under it, as in this Claude Code 2.1.322 capture, `tools/tests/fixtures/telegram-watch/working.txt:43-44`:
     ```
     ✽ Actioning…
       ⎿  Tip: Name your conversations with /rename to find them easily in /resume later
     ```
   - So `classify` returns `ready` for a lead that is working.
   - `board/tests/test_paneclass.py:128-132` pins the old rule with a hand-built `"  some indented output"` row.
   - `tools/telegram_watch.py` `_spinner_above_input` works around this with its own, stricter check (its docstring says so). That leaves two rules that can drift apart.
2. **Tests exercise a copy of `remove()`.** `tools/telegram_watch.py` `_do_reconnect` defines `remove(back, count)` inside itself: `End`, then `Left`×back, then `BSpace`×count, sent with send-keys. Tests and live proofs therefore use a copy, not the function the watchdog runs.

## Design

**paneclass: a tip row keeps a first-frame spinner live.**
- Add `TIP_RE = re.compile(r"^\s*⎿\s+Tip:")`.
- In `spinner_live`, a first-frame spinner stays live when the rows between it and the input rule are tip rows, a tip's wrapped continuation lines (indented, directly after a tip row), or blank rows.
- Any other indented row after a first-frame spinner still means the spinner is transcript. The existing `"  some indented output"` case stays `ready`.
- The elapsed-form spinner rule is unchanged.

**The watchdog reuses the shared rule.**
- `telegram_watch._spinner_above_input(rows)` becomes `paneclass.spinner_live(rows[-30:])`, or `idle_at_prompt` calls `paneclass.spinner_live` directly, and `_spinner_above_input` is removed.
- Every existing watchdog fixture keeps its verdict: `working.txt` is not idle; `idle.txt`, `real-idle-1.txt`, `real-idle-2.txt` and `after-turn.txt` are idle; the typed-text fixtures keep theirs.
- If a fixture flips, the shared rule is wrong, and it gets fixed in paneclass, not worked around in the watchdog.

**`remove()` moves to module level.**
- New function `send_remove(t, pane, back, count)` sends `["End"] + ["Left"] * back + ["BSpace"] * count` through `t("send-keys", "-t", pane, *keys)`.
- `_do_reconnect` passes `remove=lambda back, count: send_remove(t, pane, back, count)`.
- Tests call `send_remove` with a recording `t` and assert the exact argv. One test runs it against a scratch tmux pane (`-L` server with `-f /dev/null`): type text into a `cat` pane, call `send_remove`, and check the remaining text from a capture.

## Error handling

No new error paths. `send_remove` raises whatever `t` raises, the same as today.

## Testing

- **paneclass, new test:** load `tools/tests/fixtures/telegram-watch/working.txt` (real capture), and `classify` must return `("claude", "working")`. It is RED on the current code. Mutation: drop the TIP_RE branch, and the test fails.
- **paneclass, kept:** `test_first_frame_shaped_line_in_transcript_is_not_working` still passes unchanged.
- **paneclass, new case:** a tip row followed by `⏺ done` at column 0 before the rule is `ready`.
- **telegram_watch:** every existing fixture test passes with `_spinner_above_input` gone. Add one test that the watchdog and the board agree on every fixture in `tools/tests/fixtures/telegram-watch/`: `idle_at_prompt` is false wherever `spinner_live` is true.
- **send_remove:** the argv test, plus the scratch-pane test above.

## Acceptance

- `python3 -m unittest discover -s board/tests -p 'test_paneclass*.py'` and the telegram_watch tests pass. Once the fast-test-suite spec is merged, use `zsh tools/tests/all.zsh --suite board` and the watchdog's own suite.
- Real-state check, read-only: capture a working lead pane in the live `dev` session in the first second of a turn (`tmux capture-pane -p`). The board's `/api/state` shows it as `working`. Paste the capture into the test fixtures if it differs from `working.txt`.
