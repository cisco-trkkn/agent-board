# Artifact session id: real run from an agent's Bash tool (2026-11-05)

Run by the implementer (`sid`) from its own Claude Code Bash tool, inside its tmux pane, in the worktree
`feat/artifact-session-id` at commit `32df331` (Task 1). The session id is recorded as MATCH/MISMATCH and
its length only; the id itself is not written here.

## 1. Registration with the id set

Environment check (value not printed): `CLAUDE_CODE_SESSION_ID` set, length 36; `TMUX_PANE` set.

Command (the scratch state dir from `mktemp -d`, a scratch plan under `…/docs/superpowers/plans/`):

```zsh
S=$(mktemp -d); F=$(mktemp -d)/docs/superpowers/plans; mkdir -p "$F"; print '# scratch' > "$F/2099-01-01-scratch.md"
TC_STATE="$S" bin/tmux-ctl artifact "$F/2099-01-01-scratch.md"
got=$(jq -r .session_id "$S"/artifacts-*.jsonl | tail -1)
[ -n "$CLAUDE_CODE_SESSION_ID" ] && [ "$got" = "$CLAUDE_CODE_SESSION_ID" ] && echo "MATCH len=${#got}" || echo "MISMATCH len=${#got}"
```

Output:

```
registered …/docs/superpowers/plans/2099-01-01-scratch.md (plan)
artifact rc=0
artifacts-agent-board.jsonl
MATCH len=36
```

The new manifest line's `session_id` equals `$CLAUDE_CODE_SESSION_ID`.

## 2. Same command with the variable unset

```zsh
TC_STATE="$S" env -u CLAUDE_CODE_SESSION_ID bin/tmux-ctl artifact "$F/2099-01-01-scratch.md"
jq -r '.session_id|length' "$S"/artifacts-*.jsonl | tail -1
```

Output:

```
registered …/docs/superpowers/plans/2099-01-01-scratch.md (plan)
unset rc=0
blank-run session_id length: 0
```

The new line's `session_id` is `""`. The scratch manifest held 2 lines after both runs.

## 3. Live manifest, read-only

Live state dir, resolved with `TC_STATE` unset:
`env -u TC_STATE python3 -c 'import sys; sys.path.insert(0,"board"); import tc_env; print(tc_env.state_dir())'`
→ `/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmux-ctl-503`

File: `artifacts-agent-board.jsonl`, 47 lines, cksum `2092496670 15781`.

Uncapped count of `kind == "plan"` lines, by the type and length of `session_id` (missing or null counted as blank):

```
   4 string len=0
   9 string len=36
blank=4
nonblank=9
```

13 plan lines in total: 4 blank, 9 non-blank. The blank lines are the ones written before manual
registrations recorded the id, and `plan_entry` still resolves them (see its docstring in `board/planview.py`).

Nothing was written to the live manifest: the cksum and line count were the same after both scratch runs.

## 4. Cleanup

```
ls -d "$S" "$F"
ls: …/tmp.S9wItsvPKl: No such file or directory
ls: …/tmp.vDbXsf6JvH: No such file or directory
```

Both scratch directories are gone.

## Verdict

MATCH: the `tmux-ctl artifact` registration from an agent's Bash tool writes the session's real id (length 36),
and the unset run writes an empty id.
