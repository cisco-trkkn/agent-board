# Code Mode hooks probe (2026-11-20)

Question: do PreToolUse and PostToolUse hooks fire for tool calls made from Code Mode code? The answer decides E5 of the efficiency-now plan.

## Setup

Claude Code 2.1.330. Model `haiku`. Placeholders: `<scratch>` is the scratch directory, `<repo>` this worktree.

Scratch project and `<scratch>/proj/.claude/settings.json` (the probe hook has no matcher; bash-mirror runs on PostToolUse `Bash` with `TC_STATE` in the scratch):

```json
{"hooks":{
"PreToolUse":[{"hooks":[{"type":"command","command":"jq -c '{e: .hook_event_name, t: .tool_name, at: now}' >> <scratch>/events.jsonl"}]}],
"PostToolUse":[{"hooks":[{"type":"command","command":"jq -c '{e: .hook_event_name, t: .tool_name, at: now}' >> <scratch>/events.jsonl"}]},
 {"matcher":"Bash","hooks":[{"type":"command","command":"TC_STATE=<scratch>/state <repo>/claude/plugin/scripts/bash-mirror.sh --scoped"}]}]}}
```

Commands (every tmux call had `TMUX=` cleared; socket `en9`):

```
echo 'hello probe' > <scratch>/proj/probe.txt; git init -q <scratch>/proj
tmux -L en9 -f /dev/null new-session -d -s p -x 200 -y 50 -c <scratch>/proj "claude --model haiku"
tmux -L en9 send-keys -t p Down Enter          # trust prompt: "Yes, trust this folder"
tmux -L en9 new-window -d -n cm -e CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 -c <scratch>/proj "claude --model haiku"
tmux -L en9 send-keys -t cm Down Enter         # Code Mode dialog: "Yes, turn on Code Mode"
tmux -L en9 new-window -d -n shell -c <scratch>/proj   # bash-mirror writes only if the session has a window named shell
```

Prompt, identical in both runs: `Run the shell command `echo probe-ok` with the Bash tool, then read the file probe.txt with the Read tool, then reply with one line.` Run 1 (control) went to window 0 (no variable), run 2 (Code Mode) to window `cm`. A first pass of both runs had no `shell` window, so bash-mirror wrote nothing (its rule, not a hook failure); the table is from the second pass, after `events.jsonl` was emptied. The first Code Mode pass logged the same six events.

Code Mode was active in the `cm` window: it showed the dialog "Code Mode (experimental)" at start and, after accepting it, the banner "Code Mode (experimental) is on". The control window showed neither. Both runs used the same prompt and both answered it.

Deny pair (second round, new server on the same socket and a fresh `state` directory). A script `<scratch>/deny.sh` was added as a second PreToolUse hook with matcher `Bash` (added with `jq` to the same settings file):

```
c="$(jq -r '.tool_input.command // empty')"
if [[ "$c" == *probe-deny* ]]; then print -u2 "DENIED-BY-PROBE-HOOK: commands containing probe-deny are blocked"; exit 2; fi
exit 0
```

Deny mechanism: exit code 2 with the reason on stderr (the JSON `permissionDecision` form was not tried). Same start commands as above (windows `=p:0` control, `shell`, `cm` Code Mode, both with the trust and Code Mode dialogs answered with Down, Enter). Prompt in both runs: `Run the shell command `echo probe-deny` with the Bash tool. Then reply with one line that quotes any error or block message you received verbatim, or says it ran.`

Cleanup: `tmux -L en9 kill-server`; `ps` showed no process of the socket afterwards. No `pkill` or `killall`.

## Observed events

Events in log order. Tool calls were Bash and Read in both runs; the Code Mode run also logged a `REPL` call, the wrapper that runs the model's JavaScript.

| Run | Tool call | PreToolUse logged | PostToolUse logged | bash-mirror line written |
|---|---|---|---|---|
| control | Bash `echo probe-ok` | yes | yes | yes |
| control | Read `probe.txt` | yes | yes | n/a (Bash only) |
| Code Mode | REPL (wrapper) | yes | yes | n/a (Bash only) |
| Code Mode | Bash `echo probe-ok` (called from the code) | yes | yes | yes |
| Code Mode | Read `probe.txt` (called from the code) | yes | yes | n/a (Bash only) |

Deny pair (hook `deny.sh` exit 2 on `probe-deny`):

| Run | Tool call | PreToolUse logged | PostToolUse logged | bash-mirror line written | Blocked | Reason reached the model |
|---|---|---|---|---|---|---|
| control | Bash `echo probe-deny` | yes | no | no | yes | yes (quoted verbatim) |
| Code Mode | REPL (wrapper) | yes | yes | n/a | n/a | n/a |
| Code Mode | Bash `echo probe-deny` (called from the code) | yes | no | no | yes | yes (quoted verbatim) |

In both runs the screen showed "Did not run 1 call" with "Reason: PreToolUse:Bash hook error: DENIED-BY-PROBE-HOOK: commands containing probe-deny are blocked", and the model's reply quoted that text. `echo probe-deny` never ran: no PostToolUse for Bash and no mirror entry (the mirror file was not created). Raw order, Code Mode deny run: Pre REPL, Pre Bash, Post REPL. Control deny run: Pre Bash.

Raw order, Code Mode: Pre REPL, Pre Bash, Post Bash, Pre Read, Post Read, Post REPL. Control: Pre Bash, Pre Read, Post Bash, Post Read. The mirror file `feed-p-shell.log` held one entry per run, each with `$ echo probe-ok` and `probe-ok`, exit 0.

## What fires and what does not

- Under Code Mode both PreToolUse and PostToolUse fire for every tool call the code makes (Bash and Read), each with its own `tool_name`, and the PostToolUse `Bash` hook ran (bash-mirror wrote its entry).
- Code Mode adds a `REPL` tool call that wraps the others: Pre REPL comes first, Post REPL last. A gate matching all tools or a specific tool name sees both the wrapper and the inner calls.
- The control run fires the same events without the wrapper.
- A PreToolUse hook that exits 2 blocked the inner Bash call under Code Mode exactly as in the control run, and its stderr reason reached the model in both. The wrapper REPL call still completed (Post REPL logged) with the inner call reported as not run.
- Not tested: the JSON `permissionDecision` deny form, PermissionRequest hooks, and a deny on the REPL wrapper itself. The Code Mode dialog says auto mode's safety check reads the JavaScript once, not each inner call; hooks are a separate layer and did run per inner call. One run per condition, one model.

## Verdict for E5

go: PreToolUse and PostToolUse fired for every tool call made from Code Mode code (Bash and Read), and a PreToolUse Bash hook that exits 2 blocked the inner call with its reason reaching the model, as in the control; the JSON permissionDecision form was not tried.
