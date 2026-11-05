# E2E: team-band mod, real lead (2026-11-05, branch feat/mod-team-band, 3b5f104)

A real Claude Code lead in a scratch tmux server draws the band from real status files. Every result below is raw output
pasted under the command that produced it. `$TMP` is `/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.L39x1oHh7T/state`
in the raw output; `$S` is its parent (scratch files). `claude --version`:

    $ claude --version
    2.1.318 (Claude Code)

## Setup

    T() { ~/.local/bin/tmux -L team-band-e2e -f /dev/null "$@"; }
    WT=/Users/francisco.ruiz/agent-board/.claude/worktrees/mod-team-band
    LIVE=$TMPDIR/tmux-ctl-$(id -u)/agent-status     # read-only ls only; the real dir
    snap() { T capture-pane -p -t $1 | grep -v '^$' | tail -12; }
    T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP   # before any claude
    T list-panes -a -F '#{pane_id} #{session_name} #{window_name}'
    T show-environment -g TC_STATE
    T new-window -d -t e2e: -n '✦ qrev' 'sleep 9999'
    T new-window -d -t e2e: -n '✦ old' 'sleep 9999'
    T list-panes -a -F '#{pane_id} #{window_name}'

    %0 e2e claude
    TC_STATE=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.L39x1oHh7T/state
    %0 claude
    %1 ✦ qrev
    %2 ✦ old

Fixtures in `$TMP/agent-status/` (`qrev.json` is rewritten every 10 s by a background loop, `refresh.zsh`, PID 12848, killed in
Cleanup; `old.json` is now − 90000; `ghost.json` names `%99`, not in the session; `x.json.tmp` is a half-written leftover):

    /…/state/agent-status/ghost.json
    {"session_id": "ghost", "pane": "%99", "state": "needs-you", "since": 1793898795, "updatedAt": 1793898795}
    /…/state/agent-status/old.json
    {"session_id": "old-sid", "pane": "%2", "state": "busy", "since": 1793808794, "updatedAt": 1793808794}
    /…/state/agent-status/qrev.json
    {"session_id": "qrev-sid", "pane": "%1", "state": "needs-you", "since": 1793898795, "updatedAt": 1793898795}
    /…/state/agent-status/x.json.tmp
    {"partial

    date +%s  ->  1793898796

Read-only `ls` of the real state dir before the run (two live sessions' files; none touched):

    7c5be853-197c-4526-960c-16861ba9f4a0.json
    8be10495-6764-4145-abc1-b3e46006143a.json

The lead (its own real status file is written by agent-status as `ready` for `%0`):

    T send-keys -t %0 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %0 Enter

## Band with needs-you

`sleep 25; date +%s; snap %0` (25 s after launch):

    1793898827
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band
    Needs you: ✦ qrev · ? 1                                                                                                                                                                             [-]
                                                                                                  tmux focus-events off · add 'set -g focus-events on' to ~/.tmux.conf and reattach for focus tracking
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "edit tmux-ctl to..."
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

`? 1` is `✦ old` (file 90000 s old). The ghost-pane file and `x.json.tmp` add nothing. The lead's own file is excluded.
(The `[-]` at the right edge is Claude Code's own chrome.)

Check (b), band text appears once and cleanly: `T capture-pane -p -t %0 | grep -c 'Needs you'`, then the line itself:

    count of band text:
    1

The `Needs you: ✦ qrev · ? 1` line in the capture above is the whole line, with no doubled or stray characters (the `cat -A`
I tried to show raw bytes is not supported by macOS `cat`, so there is no byte dump).

## State change

Switch `qrev` to `busy` (the refresher reads `$S/qstate`, so it keeps writing `busy`); polls run every 2 s:

    date +%s: 1793898834
    +2s
    busy 1 · ? 1                                                                                                                                                                                        [-]
    +4s
    busy 1 · ? 1                                                                                                                                                                                        [-]
    +6s
    busy 1 · ? 1                                                                                                                                                                                        [-]
    {"session_id": "qrev-sid", "pane": "%1", "state": "busy", "since": 1793898835, "updatedAt": 1793898835}

No `Needs you` in the grep output. The band changed within the first 2 s sample.

## No agents and non-lead

Non-lead: a second claude in a new window `✦ peer` (`%3`), same flags. `sleep 30; snap %3` (its own capture):

    %0 claude
    %1 ✦ qrev
    %2 ✦ old
    %3 ✦ peer
    peer=%3
    1793898878
    --- peer capture
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix lint errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)
    --- peer proc
     2854  2738 ttys005  claude --model haiku --effort low -n overseer …   (the user's real overseer, not ours)
    13051 12586 ttys030  claude --model haiku --settings /Users/francisco.ruiz/agent-board/.claude/worktrees/mod-team-band/claude/session-settin…   (lead)
    14009 13933 ttys037  claude --model haiku --settings /Users/francisco.ruiz/agent-board/.claude/worktrees/mod-team-band/claude/session-settin…   (peer)
    --- lead capture
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band
    busy 1 · ready 1 · ? 1                                                                                                                                                                              [-]
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

The peer's capture has no band line. The lead now counts the peer as `ready 1` (its own agent-status file).

Check (a), `session.end` catch-all matcher: `/exit` in the peer, then its process and the lead:

    T send-keys -t %3 "/exit"; sleep 1; T send-keys -t %3 Enter; sleep 5

    %0 pane_pid=12586 tty=/dev/ttys030
    %3 pane_pid=13933 tty=/dev/ttys037
    children of peer shell:
    14009 2.1.318
    --- peer pane after /exit
    …francisco.ruiz@US5TKNM0JCWGW mod-team-band %
    --- children of peer shell
    pgrep rc=1
    --- ps for peer pid
      PID COMMAND
    1793898898
    --- lead
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band
    busy 1 · ? 2                                                                                                                                                                                        [-]
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

(Before `/exit` the peer shell had child 14009; after, `pgrep -P` finds none (rc=1) and `ps -p 14009` lists only the header, so
the peer claude is gone. The lead still draws, with the peer's file now aging into `? 2`.) The peer's `session.end` stops only
the peer's own record (it never had one), so the lead is unaffected.

No agents: kill the refresher and all three `✦` windows, remove all fixtures, sample the lead every 4 s:

    refresher-gone
           0                       # files left in agent-status/
    %0 claude
    1793898905
    +4s
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "edit tmux-ctl to..."
    +8s
     (same: no band line)
    +12s
     (same: no band line)

(The +8 s and +12 s captures are abbreviated here to "same"; the raw output was identical to +4 s, no line between the logo and the rule.) The band was already gone at the first sample, +4 s; the lead's own file is excluded and no window remains, so the line is empty.

## Cleanup

    T send-keys -t %0 "/exit"; sleep 1; T send-keys -t %0 Enter; sleep 4
    T kill-server
    kill-server rc=0
    --- ps sleep/scratch claude/refresher       # ps -axo pid,command | grep -E 'sleep 9999|team-band-e2e|refresh.zsh|tmp.L39x1oHh7T'
    matches rc=1
    no server running on /private/tmp/tmux-503/team-band-e2e
    claude matches done                         # ps | grep 'claude --model haiku --settings .*mod-team-band': no lines

No `sleep 9999`, no scratch claude and no refresher remain. The real tmux server and the real agent-status dir were not touched.
