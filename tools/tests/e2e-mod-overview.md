# E2E: mod overview, real run (2026-11-09, mod 45258e3 + board of this branch)

Spec 8 task 4. One real scratch lead shows the agent line during a Bash call and the reason during an AskUserQuestion; then a
read-only check of the branch's `/api/overview` against the live board. Ids, pane ids of the user's sessions and home paths
are redacted (`$TMP`, `<sid>`, `~`). `claude --version`: 2.1.319.

## Setup (scratch tmux, test board, lead loading this worktree's plugin)

    T() { ~/.local/bin/tmux -L mod-overview-e2e -f /dev/null "$@"; }
    WT=<this worktree>; TMP=$(mktemp -d)
    T new-session -d -s e2e -x 200 -y 50 && T set-environment -g TC_STATE $TMP     # before any claude
    TMUX_DASH_PORT=7710 TMUX_DASH_TOKEN=x TMUX_DASH_TMUX_ARGS='-L mod-overview-e2e' TC_OVERSEER=0 TC_NOTIFY=0 TC_STATE=$TMP python3 board/server.py &
    T send-keys -t %0 "cd $WT && TC_STATE=$TMP claude --model haiku --permission-mode auto --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %0 Enter

(The first launch from the temp dir stopped at the "trust this folder" dialog; I answered "No, exit" and started the lead in the
worktree, which is already trusted. The lead's window is named by Claude (`2.1.319`), not `claude`, so the board shows "No lead"
for this scratch project; `agents[]` lists every claude pane regardless.)

Prompts: `T send-keys -t %0 "text"; sleep 1; T send-keys -t %0 Enter`. Status file idle, after start:

    {"session_id":"<sid>","pane":"%0","state":"ready","since":1794250690,"updatedAt":1794250705,"tool":null,"turnStartedAt":null,"waiting":null,"failStreak":0,"lastToolAt":null}

## Bash call: `sleep 20; echo done`

Prompt: "Run this exact Bash command and report its output: sleep 20; echo done". 5 s and 10 s into the call:

    date=1794250720   status file:
    {"session_id":"<sid>","pane":"%0","state":"busy","since":1794250710,"updatedAt":1794250720,"tool":{"name":"Bash","arg":"sleep 20; echo done","startedAt":1794250712},"turnStartedAt":1794250710,"waiting":null,"failStreak":0,"lastToolAt":null}
    GET :7710/x/api/overview  ->  projects[0].agents
    [{"window": "2.1.319", "pane": "%0", "state": "working", "state_s": 9, "turn_s": 9, "tool": "Bash: sleep 20; echo done"}]

(The arg is the whole first line, `sleep 20; echo done`, so the tool text is `Bash: sleep 20; echo done`, which starts with
`Bash: sleep 20`.) The first sample, 5 s in, was still the board's cached state (`ready`, tool null): the overview is cached
10 s (`OVERVIEW_EVERY`). After the call: `"lastToolAt":1794250734`, `tool` null, `failStreak` 0.

Page route: no jsdom, playwright or puppeteer is installed here (`node -e "require('jsdom')"` fails), so the page was rendered
by loading the real `ovRow` and its helper functions out of `board/index.html` into node with a minimal DOM shim
(`render-ovrow.js`, createElement/append/className/textContent only) and feeding it the `/api/overview` JSON captured above.
It prints the node tree:

PROJECT e2e
<div class="ov-row">
  <div class="ov-top">
    <span class="ov-mark nolead"> ◌
    <a class="ov-name"> e2e
    <span class="ov-status nolead"> No lead
    <span class="ov-right"> $0.00 today
  <div class="ov-sub">
    <div class="ov-agent ov-muted"> 2.1.319 · busy 9s · Bash: sleep 20; echo done

## AskUserQuestion

First attempt with the mod at 8f02522 FAILED the criterion: the status file had
`"waiting":{"kind":"permission","detail":"AskUserQuestion: "}` and `needs_you[0].reason` was
`permission: AskUserQuestion: ` (a real AskUserQuestion also raises classic.PermissionRequest, which overwrote the question form;
the unit tests' stub never fired it). Fixed in 45258e3 (task-1-report.md, "Fix round 1"). Re-run with the fixed mod, a fresh
lead, prompt "Use AskUserQuestion to ask me to pick red or blue (header: Color), then reply with my pick.", dialog open:

    date=1794250995   status file:
    {"session_id":"<sid>","pane":"%0","state":"needs-you","since":1794250976,"updatedAt":1794250984,"tool":{"name":"AskUserQuestion","arg":"","startedAt":1794250976},"turnStartedAt":1794250968,"waiting":{"kind":"question","detail":"Color"},"failStreak":0,"lastToolAt":null}
    GET :7710/x/api/overview  ->  projects[0].needs_you
    [{"window": "2.1.319", "pane": "%0", "kind": "claude", "reason": "question: Color"}]
    projects[0].agents
    [{"window": "2.1.319", "pane": "%0", "state": "waiting", "state_s": 19, "turn_s": 27, "tool": "AskUserQuestion"}]

Rendered page:

PROJECT e2e
<div class="ov-row needs">
  <div class="ov-top">
    <span class="ov-mark needs"> ●
    <a class="ov-name"> e2e
    <span class="ov-status needs"> Needs you
    <span class="ov-right"> $0.00 today
  <div class="ov-sub">
    <div class="ov-needs"> 2.1.319 needs you — question: Color
    <div class="ov-agent ov-muted"> 2.1.319 · needs you 19s · AskUserQuestion

After one `Enter` (option 1) the status file went back to
`"state":"ready","tool":null,"turnStartedAt":null,"waiting":null,"failStreak":0,"lastToolAt":1794251004`.
`board/tests/fixtures/agent-status/real-new-fields.json` is the Bash-call file above (ids replaced); a test in
`board/tests/test_overview.py` loads it.

## Real-state check (read-only)

A board of this branch on :7711 (`TMUX_DASH_TOKEN=x TC_OVERSEER=0 TC_NOTIFY=0 TMUX_DASH_STATE=<temp dir>`, `TC_STATE` unset,
the same tmux server the live board reads), and the live board on :7700 (token from `~/.local/state/tmux-dash/token`). Nothing
was sent to or started in the user's tmux sessions. `diffpaths.py` lists every JSON key path (arrays as `[]`) with its type:

live paths: 53 new paths: 53
live paths missing in new: ['.events[]', '.events[].id', '.events[].ts', '.events[].project', '.events[].kind', '.events[].key', '.events[].title', '.events[].text']
same-path type changes: []
added paths: ['.projects[].agents', '.projects[].agents[]', '.projects[].agents[].pane', '.projects[].agents[].state', '.projects[].agents[].state_s', '.projects[].agents[].tool', '.projects[].agents[].turn_s', '.projects[].agents[].window']
projects live/new: 2 2

Reading: 53 paths on each side, 2 projects on each side (more than one real project). No live path changed type. The only live
paths absent from the new response are the `.events[]` item paths: events are history the live board accumulated over its
uptime (8 events), the new board had been up seconds with the notifier off, so it has none; that is runtime state, not schema.
The only added paths are `.projects[].agents…`. `needs_you[].reason` and alert `fail_streak`/`turn_s` did not appear because no
real session was waiting or failing at that moment; they are covered by the unit tests and the scratch run above. The real
sessions' fresh status files come from the installed (old) mod, so their agents show `state_s` with `turn_s` and `tool` null:
the old-file case reads as null, as intended.

## Cleanup

Boards killed by pid, scratch lead ended with `/exit` (status dir empty after), scratch server by `T kill-server`:

    $ T ls
    no server running on /private/tmp/tmux-503/mod-overview-e2e
    $ lsof -iTCP:7710 -iTCP:7711 -sTCP:LISTEN | wc -l
    0
    $ ps -axo pid,command | grep -E 'mod-overview-e2e|TMUX_DASH_PORT=771' | grep -v grep
    (nothing)

The remaining `board/server.py` (the live board on :7700) and the other `claude` processes in `ps` are not from this run.
