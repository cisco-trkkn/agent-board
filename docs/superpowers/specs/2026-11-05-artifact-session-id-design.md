# Manual artifact registrations record the session id

Date: 2026-11-05 · Status: approved design
Group 4 of the ideas (ideas file, 2026-11-05 00:33 "tmux-ctl artifact writes plan manifest lines with
session_id ''").

## Root cause

`tmux-ctl artifact <path>` calls `claude/hooks/artifact-register.sh --path <p> … --project <key>`
(`bin/tmux-ctl`, the `artifact)` case). With `--path` the script runs in manual mode: it feeds `{}` instead of
hook JSON (`payload='{}'`), and the Python block only reads `session_id` from hook JSON
(`sid = d.get("session_id") or ""`, inside `if not manual:`). So every manual line has `session_id: ""`.
Claude Code exports `CLAUDE_CODE_SESSION_ID` to the Bash tool's environment (seen in this session's `env`),
so a `tmux-ctl artifact` run by an agent can pass its real id.

## Design

- `claude/hooks/artifact-register.sh`, manual mode: `sid` = `$CLAUDE_CODE_SESSION_ID` when set, else `""`
  (a user typing `tmux-ctl artifact` in a plain shell has none; the line stays blank as today).
  Also accept an explicit `--session <id>` flag, which wins over the environment.
- `claude/plugin/scripts/artifact-register.sh` is the plugin copy: apply the same change if it is a separate
  file (`ls -l` first; if it is a link to the hooks copy, change only the target).
- `bin/tmux-ctl artifact`: no change needed (the environment passes through); its usage line gains
  `[--session ID]` only if the flag is forwarded.
- `board/planview.py` `plan_entry`: keep the blank-session_id fallback (lines already written stay blank),
  and state in its docstring that it covers lines written before this fix and plain-shell registrations.
  A line with a non-blank session_id is matched only by that id, as now.

## Files

- Modify: `claude/hooks/artifact-register.sh` (and the plugin copy if separate), `board/planview.py`
  (docstring only), `bin/tmux-ctl` (only if the flag is forwarded).
- Tests: the existing artifact-register shell test (`claude/hooks/tests/test-*.sh` or
  `tools/tests/*.zsh`, whichever covers `--path`): a manual registration with `CLAUDE_CODE_SESSION_ID=abc`
  writes `"session_id": "abc"`; without it writes `""`; `--session x` wins. Each seen failing first.

## Testing

Targeted only: the covering shell test, and `python3 -m unittest` on the planview test file
(`board/tests/test_planview*.py`) to show the fallback still passes. One real run: `tmux-ctl artifact` of a
scratch file from an agent's Bash tool, then the new manifest line's `session_id` equals the session's id
(read with `jq`). Scratch file and its manifest line are removed afterwards (the manifest is append-only:
use a temp `TC_STATE` for the run instead of the live one).
