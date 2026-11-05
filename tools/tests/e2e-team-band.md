# E2E: team-band mod, real lead (2026-11-05, branch feat/mod-team-band)

A real Claude Code lead in a scratch tmux server (`-L team-band-e2e -f /dev/null`) draws the band from real status files.
Every block is a literal command line (`$ cmd`) followed by its untouched output; the commands came from one driver script
(`$S/run.zsh`) that printed each line before running it, and the output is its log. Two things the driver changed: it
stripped trailing spaces from output lines, and `T` is `~/.local/bin/tmux -L team-band-e2e -f /dev/null "$@"`. The `S` and
`TMP` paths are printed by the first command; all pane ids are the scratch server's (`%0` lead `claude`, `%1` `✦ qrev`,
`%2` `✦ old`, `%3` `✦ peer`). Absence is proved by the full capture plus a `grep -c` count over the whole capture
(`grep -cE "Needs you|busy |ready |\? [0-9]"` counts 1 on the band line when a band is drawn and 0 when none is).

## Setup

Fixtures: `qrev.json` is `needs-you` and rewritten every 10 s by `refresh.zsh` (reads `$S/qstate`); `old.json` has `updatedAt` now − 90000; `ghost.json` names `%99`, which is not in the session; `x.json.tmp` is a half-written leftover. The real state dir is only `ls`ed. The lead's own file appears once it is up.

    $ print "S=$S"; print "TMP=$TMP"
    S=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0
    TMP=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state

    $ claude --version
    2.1.318 (Claude Code)

    $ ls $TMPDIR/tmux-ctl-$(id -u)/agent-status
    25701080-d3e9-4528-ab40-85bb44b614ac.json
    7c5be853-197c-4526-960c-16861ba9f4a0.json
    8be10495-6764-4145-abc1-b3e46006143a.json

    $ T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP

    $ T show-environment -g TC_STATE
    TC_STATE=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state

    $ T new-window -d -t e2e: -n "✦ qrev" "sleep 9999"

    $ T new-window -d -t e2e: -n "✦ old" "sleep 9999"

    $ T list-panes -a -F "#{pane_id} #{session_name} #{window_name}"
    %0 e2e claude
    %1 e2e ✦ qrev
    %2 e2e ✦ old

    $ cat $S/mkfx.py
    import json, sys, time
    path, sid, pane, state, age = sys.argv[1:6]
    n = int(time.time()) - int(age)
    json.dump({"session_id": sid, "pane": pane, "state": state, "since": n, "updatedAt": n}, open(path, "w"))

    $ cat $S/refresh.zsh
    S=$1
    while true; do python3 $S/mkfx.py $S/state/agent-status/qrev.json qrev-sid %1 $(cat $S/qstate) 0; sleep 10; done

    $ python3 $S/mkfx.py $TMP/agent-status/qrev.json qrev-sid %1 needs-you 0

    $ nohup zsh $S/refresh.zsh $S >/dev/null 2>&1 &

    $ cat $S/refresher.pid
    25985

    $ python3 $S/mkfx.py $TMP/agent-status/old.json old-sid %2 busy 90000

    $ python3 $S/mkfx.py $TMP/agent-status/ghost.json ghost %99 needs-you 0

    $ print "{\"partial" > $TMP/agent-status/x.json.tmp

    $ ls -l $TMP/agent-status/
    total 32
    -rw-r--r--  1 francisco.ruiz  staff  106 Nov  5 12:22 ghost.json
    -rw-r--r--  1 francisco.ruiz  staff  102 Nov  5 12:22 old.json
    -rw-r--r--  1 francisco.ruiz  staff  108 Nov  5 12:22 qrev.json
    -rw-r--r--  1 francisco.ruiz  staff   10 Nov  5 12:22 x.json.tmp

    $ date +%s
    1793899350

    $ for f in $TMP/agent-status/*; do print $f; cat $f; print; done
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/ghost.json
    {"session_id": "ghost", "pane": "%99", "state": "needs-you", "since": 1793899350, "updatedAt": 1793899350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/old.json
    {"session_id": "old-sid", "pane": "%2", "state": "busy", "since": 1793809350, "updatedAt": 1793809350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/qrev.json
    {"session_id": "qrev-sid", "pane": "%1", "state": "needs-you", "since": 1793899350, "updatedAt": 1793899350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/x.json.tmp
    {"partial


## Band with needs-you

The lead runs in window `claude` (`%0`). Its own file (`pane` `%0`, state `ready`) is in the directory next to the fixtures, yet the band does not count it: the capture is `Needs you: ✦ qrev · ? 1` (`? 1` is `✦ old`; the ghost-pane file and `x.json.tmp` add nothing), the band line appears once, and `ready` is absent from the capture.

    $ T send-keys -t %0 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %0 Enter

    $ sleep 25

    $ date +%s
    1793899376

    $ ls -l $TMP/agent-status/
    total 40
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:22 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    -rw-r--r--  1 francisco.ruiz  staff  106 Nov  5 12:22 ghost.json
    -rw-r--r--  1 francisco.ruiz  staff  102 Nov  5 12:22 old.json
    -rw-r--r--  1 francisco.ruiz  staff  108 Nov  5 12:22 qrev.json
    -rw-r--r--  1 francisco.ruiz  staff   10 Nov  5 12:22 x.json.tmp

    $ for f in $TMP/agent-status/*; do print $f; cat $f; print; done
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    {"session_id":"a631ca1f-5eb1-4d2a-8b83-92dd243270f2","pane":"%0","state":"ready","since":1793899353,"updatedAt":1793899368}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/ghost.json
    {"session_id": "ghost", "pane": "%99", "state": "needs-you", "since": 1793899350, "updatedAt": 1793899350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/old.json
    {"session_id": "old-sid", "pane": "%2", "state": "busy", "since": 1793809350, "updatedAt": 1793809350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/qrev.json
    {"session_id": "qrev-sid", "pane": "%1", "state": "needs-you", "since": 1793899370, "updatedAt": 1793899370}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/x.json.tmp
    {"partial


    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    Needs you: ✦ qrev · ? 1                                                                                                                                                                             [-]
                                                                                                      tmux focus-events off · add 'set -g focus-events on' to ~/.tmux.conf and reattach for focus tracking
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "Needs you"
    1

    $ T capture-pane -p -t %0 | grep -c "Needs you: ✦ qrev · ? 1 "
    1

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    1

## State change

`qstate` is set to `busy` and `qrev.json` rewritten at the first `date` below; the band is `busy 1 · ? 1` at the first sample, 2 s later, with no `Needs you`, and stays so at +4 s and +6 s. The lead's file is still present in the directory and still not counted.

    $ echo busy > $S/qstate

    $ python3 $S/mkfx.py $TMP/agent-status/qrev.json qrev-sid %1 busy 0

    $ date +%s
    1793899377

    $ sleep 2

    $ date +%s
    1793899379

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    busy 1 · ? 1                                                                                                                                                                                        [-]

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "Needs you"
    0

    $ T capture-pane -p -t %0 | grep -c "busy 1 · ? 1 "
    1

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    1

    $ sleep 2

    $ date +%s
    1793899381

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    busy 1 · ? 1                                                                                                                                                                                        [-]

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "Needs you"
    0

    $ T capture-pane -p -t %0 | grep -c "busy 1 · ? 1 "
    1

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    1

    $ sleep 2

    $ date +%s
    1793899383

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    busy 1 · ? 1                                                                                                                                                                                        [-]

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "Needs you"
    0

    $ T capture-pane -p -t %0 | grep -c "busy 1 · ? 1 "
    1

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    1

    $ ls -l $TMP/agent-status/
    total 40
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    -rw-r--r--  1 francisco.ruiz  staff  106 Nov  5 12:22 ghost.json
    -rw-r--r--  1 francisco.ruiz  staff  102 Nov  5 12:22 old.json
    -rw-r--r--  1 francisco.ruiz  staff  103 Nov  5 12:23 qrev.json
    -rw-r--r--  1 francisco.ruiz  staff   10 Nov  5 12:22 x.json.tmp

    $ for f in $TMP/agent-status/*; do print $f; cat $f; print; done
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    {"session_id":"a631ca1f-5eb1-4d2a-8b83-92dd243270f2","pane":"%0","state":"ready","since":1793899353,"updatedAt":1793899383}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/ghost.json
    {"session_id": "ghost", "pane": "%99", "state": "needs-you", "since": 1793899350, "updatedAt": 1793899350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/old.json
    {"session_id": "old-sid", "pane": "%2", "state": "busy", "since": 1793809350, "updatedAt": 1793809350}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/qrev.json
    {"session_id": "qrev-sid", "pane": "%1", "state": "busy", "since": 1793899380, "updatedAt": 1793899380}
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/x.json.tmp
    {"partial


## No agents and non-lead

First the non-lead: a second claude, same flags, in window `✦ peer` (`%3`). Its own capture has no band (count 0) and the lead then counts it as `ready 1`. Then `/exit` in the peer (the `session.end` catch-all matcher): its process is gone and the lead still draws. Then the refresher is killed, the three `✦` windows are killed and the four fixtures removed, leaving only the lead's own file; the lead's capture has no band line at +4 s, +8 s and +12 s (count 0 each time).

    $ T new-window -d -t e2e: -n "✦ peer"

    $ T list-panes -a -F "#{pane_id} #{window_name}"
    %0 claude
    %1 ✦ qrev
    %2 ✦ old
    %3 ✦ peer

    $ T send-keys -t %3 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %3 Enter

    $ sleep 30

    $ date +%s
    1793899415

    $ T capture-pane -p -t %3

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band









































    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix lint errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %3 | grep -cE "Needs you|busy |ready |\? [0-9]"
    0

    $ ls -l $TMP/agent-status/
    total 48
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 16d3a2e7-e4c7-48a8-9334-1d488c2afb18.json
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    -rw-r--r--  1 francisco.ruiz  staff  106 Nov  5 12:22 ghost.json
    -rw-r--r--  1 francisco.ruiz  staff  102 Nov  5 12:22 old.json
    -rw-r--r--  1 francisco.ruiz  staff  103 Nov  5 12:23 qrev.json
    -rw-r--r--  1 francisco.ruiz  staff   10 Nov  5 12:22 x.json.tmp

    $ pgrep -P $(T display -p -t %3 "#{pane_pid}") -l
    26902 2.1.318

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    busy 1 · ready 1 · ? 1                                                                                                                                                                              [-]

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

### Peer status file on /exit

The peer's status file is `16d3a2e7-e4c7-48a8-9334-1d488c2afb18.json`, the one new name in the `ls` above next to the lead's `a631ca1f-…` (its content was not cat'ed in this run; the earlier rerun, commit 4ee4e40, showed a peer file with `"pane":"%1"`). It is gone from the `ls` below, 5 s after `/exit`, while the lead's file stays. agent-status's `session.end` still deletes it behind `index.js`. The `? 2` in the lead's capture is `✦ old` plus the `✦ peer` window, which has no file.

    $ T send-keys -t %3 "/exit"; sleep 1; T send-keys -t %3 Enter; sleep 5

    $ pgrep -P $(T display -p -t %3 "#{pane_pid}") -l; echo rc=$?
    rc=1

    $ ls -l $TMP/agent-status/
    total 40
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    -rw-r--r--  1 francisco.ruiz  staff  106 Nov  5 12:22 ghost.json
    -rw-r--r--  1 francisco.ruiz  staff  102 Nov  5 12:22 old.json
    -rw-r--r--  1 francisco.ruiz  staff  103 Nov  5 12:23 qrev.json
    -rw-r--r--  1 francisco.ruiz  staff   10 Nov  5 12:22 x.json.tmp

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band







































    busy 1 · ? 2                                                                                                                                                                                        [-]

    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ kill $(cat $S/refresher.pid); sleep 1; ps -p $(cat $S/refresher.pid); echo rc=$?
      PID TTY           TIME CMD
    rc=1

    $ T kill-window -t "e2e:✦ qrev"; T kill-window -t "e2e:✦ old"; T kill-window -t "e2e:✦ peer"

    $ rm $TMP/agent-status/qrev.json $TMP/agent-status/old.json $TMP/agent-status/ghost.json $TMP/agent-status/x.json.tmp

    $ T list-panes -a -F "#{pane_id} #{window_name}"
    %0 claude

    $ date +%s
    1793899422

    $ ls -l $TMP/agent-status/
    total 8
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json

    $ sleep 4

    $ date +%s
    1793899426

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band









































    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    0

    $ sleep 4

    $ date +%s
    1793899431

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band









































    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    0

    $ sleep 4

    $ date +%s
    1793899435

    $ T capture-pane -p -t %0

     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-team-band









































    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix typecheck errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -cE "Needs you|busy |ready |\? [0-9]"
    0

    $ ls -l $TMP/agent-status/
    total 8
    -rw-r--r--  1 francisco.ruiz  staff  123 Nov  5 12:23 a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json

    $ for f in $TMP/agent-status/*; do print $f; cat $f; print; done
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.WaJTllpVX0/state/agent-status/a631ca1f-5eb1-4d2a-8b83-92dd243270f2.json
    {"session_id":"a631ca1f-5eb1-4d2a-8b83-92dd243270f2","pane":"%0","state":"ready","since":1793899353,"updatedAt":1793899428}

## Cleanup

`/exit` in the lead, then the scratch server is killed. The last `ps` finds no `sleep 9999`, refresher or scratch server, and the lead's own file was removed by its `session.end`.

    $ T send-keys -t %0 "/exit"; sleep 1; T send-keys -t %0 Enter; sleep 4

    $ pgrep -P $(T display -p -t %0 "#{pane_pid}") -l; echo rc=$?
    rc=1

    $ ls -l $TMP/agent-status/
    total 0

    $ T kill-server; echo rc=$?
    rc=0

    $ T ls
    no server running on /private/tmp/tmux-503/team-band-e2e

    $ ps -axo pid,command | grep -E "sleep 9999|refresh.zsh|team-band-e2e" | grep -v grep; echo rc=$?
    rc=1

