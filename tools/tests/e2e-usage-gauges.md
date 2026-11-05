# E2E: usage-gauges mod, real session with the statusLine tap (2026-11-05, branch feat/mod-usage-gauges)

A real Claude Code session in a scratch tmux server (`-L usage-gauges-e2e -f /dev/null`) shows the gauge line under its
prompt, read from the tap file that the user's own statusLine setting (`~/.claude/settings.json`,
`agent-board-statusline` in the main checkout, unedited) writes into `$TC_STATE/statusline/`. Every block is a literal
command line (`$ cmd`) followed by its untouched output, from one driver (`r 'cmd'` prints the line, runs it, strips
trailing spaces). Two display artifacts of the driver: `print` eats backslashes in the echoed command line (so
`grep -c '5h \|ctx '` shows as `'5h |ctx '`; the command that ran has the `\|`), and `T` is
`~/.local/bin/tmux -L usage-gauges-e2e -f /dev/null "$@"`. `S` and `TMP` are printed by the first command. The
statusLine tap itself prints a second row (`Haiku 5.5 · ctx 4% · 5h 32%`), so a bare `grep -c '5h \|ctx '` counts that
row too; the mod's row is the one starting `⚠ agent-board:`, and the counts below use `agent-board:` and `5h .*7d `
(the mod's row is the only one with both 5h and 7d).

## Setup

Preconditions: `WT=$(git rev-parse --show-toplevel)`; `T` uses any tmux 3.x. `claude --version` is below. The scratch
state dir `$TMP` is empty; the foreign file comes later from the real live dir (`wc -l` below shows its size only).

    $ print "S=$S"; print "TMP=$TMP"
    S=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.TP1Ak4oa7D
    TMP=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.TP1Ak4oa7D/state

    $ claude --version
    2.1.318 (Claude Code)

    $ ls $TMPDIR/tmux-ctl-$(id -u)/statusline | wc -l
         208

    $ T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP

    $ T show-environment -g TC_STATE
    TC_STATE=/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.TP1Ak4oa7D/state

    $ WT=$(git rev-parse --show-toplevel); print $WT
    /Users/francisco.ruiz/agent-board/.claude/worktrees/mod-usage-gauges

    $ T send-keys -t %0 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %0 Enter

    $ sleep 15

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
                                                                                                                             You've used 92% of your weekly limit · resets Nov 7 at 1pm (America/New_York)
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "edit tmux-ctl to..."
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: $0.00
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

`ls $TMP/statusline/` (first command of the next section) shows the tap created exactly one file, named by the session's own id.
The first capture (before any turn) already shows `⚠ agent-board: $0.00`: the first tap payload holds only the cost.

## Gauge line

After one short turn (no tools) the capture shows `⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01`; the tap file's
fields (printed with a python3 one-liner, only the fields the mod reads) are 5h 32, 7d 92, ctx 4, cost 0.00888
(`$0.01`), and `grep -c "agent-board: 5h "` is 1.

    $ ls $TMP/statusline/
    2ded8cca-858b-444f-8bac-464d69b5ab92.json

    $ T send-keys -t %0 "Reply with the single word: pong"; sleep 1; T send-keys -t %0 Enter

    $ sleep 30

    $ ls -l $TMP/statusline/
    total 8
    -rw-------  1 francisco.ruiz  staff  2039 Nov  5 12:51 2ded8cca-858b-444f-8bac-464d69b5ab92.json

    $ T capture-pane -p -t %0 | grep -v "^ *$"
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    ❯ Reply with the single word: pong
    ⏺ pong
    ✻ Churned for 3s · done 12:51 PM
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Churned for 3s · done 12:51 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ python3 -I $S/show.py $OWN
    session_id 2ded8cca-858b-444f-8bac-464d69b5ab92
    five_hour 32 seven_day 92 ctx 4 cost 0.00888 received_at 1793901065.979667

    $ T capture-pane -p -t %0 | grep -c "agent-board: 5h "
    1

## Foreign and stale files

A second real tap file (the third newest in the user's live `$TMPDIR/tmux-ctl-$(id -u)/statusline/`, another session's) is
copied read-only under its own name into `$TMP/statusline/`; only its `rate_limits`, `context_window` and `cost` fields
are printed (ctx 27, cost 8.01 against the own file's ctx 4, cost 0.01; its `5h`/`7d` happen to be equal because both
sessions share the plan). After 22 s (two polls) the capture still shows the own numbers (ctx 4%, $0.01), and the count
of the own `5h 32%` line is 1.

    $ basename $FOREIGN_SRC
    8be10495-6764-4145-abc1-b3e46006143a.json

    $ cp $FOREIGN_SRC $TMP/statusline/

    $ ls -l $TMP/statusline/
    total 16
    -rw-------  1 francisco.ruiz  staff  2039 Nov  5 12:51 2ded8cca-858b-444f-8bac-464d69b5ab92.json
    -rw-------  1 francisco.ruiz  staff  1984 Nov  5 12:51 8be10495-6764-4145-abc1-b3e46006143a.json

    $ python3 -I $S/show.py $TMP/statusline/$(basename $FOREIGN_SRC)
    session_id 8be10495-6764-4145-abc1-b3e46006143a
    five_hour 32 seven_day 92 ctx 27 cost 8.014046300000002 received_at 1793901022.772365

    $ sleep 22

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Churned for 3s · done 12:51 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "agent-board: 5h $(python3 -I -c "import json,sys; p=json.load(open(sys.argv[1])); print(round(p["rate_limits"]["five_hour"]["used_percentage"]))" $OWN)%"
    1

Stale: the own file's `received_at` is rewritten to now − 400 (the session is idle, so the tap does not rewrite it;
each `show.py` below proves `received_at` unchanged at every capture). Captures at +4, +8 and +12 s: at +4 s (1793901138)
the old line is still there (the poll runs every 10 s), at +8 s (1793901142) the row is cleared.
**`$.ui.status('')` leaves an empty `⚠ agent-board:` prefix row on screen** (count of `agent-board:` stays 1, count of
`5h .*7d ` is 0). The line text is gone, the prefix remains: this is the concern to report.

    $ date +%s
    1793901134

    $ python3 -I $S/rewrite.py $OWN 400
    received_at set to now - 400 = 1793900734.4258828

    $ date +%s
    1793901134

    $ sleep 4

    $ date +%s
    1793901138

    $ python3 -I $S/show.py $OWN
    session_id 2ded8cca-858b-444f-8bac-464d69b5ab92
    five_hour 32 seven_day 92 ctx 4 cost 0.00888 received_at 1793900734.4258828

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Churned for 3s · done 12:51 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "agent-board:"
    1

    $ T capture-pane -p -t %0 | grep -c "5h .*7d "
    1

    $ sleep 4

    $ date +%s
    1793901142

    $ python3 -I $S/show.py $OWN
    session_id 2ded8cca-858b-444f-8bac-464d69b5ab92
    five_hour 32 seven_day 92 ctx 4 cost 0.00888 received_at 1793900734.4258828

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Churned for 3s · done 12:51 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board:
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "agent-board:"
    1

    $ T capture-pane -p -t %0 | grep -c "5h .*7d "
    0

    $ sleep 4

    $ date +%s
    1793901147

    $ python3 -I $S/show.py $OWN
    session_id 2ded8cca-858b-444f-8bac-464d69b5ab92
    five_hour 32 seven_day 92 ctx 4 cost 0.00888 received_at 1793900734.4258828

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Churned for 3s · done 12:51 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board:
      Haiku 5.5 · ctx 4% · 5h 32%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c "agent-board:"
    1

    $ T capture-pane -p -t %0 | grep -c "5h .*7d "
    0

Literal brief grep over the last capture: the 1 hit is the tap's own row `Haiku 5.5 · ctx 4% · 5h 32%` (line 49), not the mod's.

    $ T capture-pane -p -t %0 | grep -c '5h |ctx '
    1

    $ T capture-pane -p -t %0 | grep -n '5h |ctx '
    49:  Haiku 5.5 · ctx 4% · 5h 32%

## Cleanup

The session was exited with `/exit`, the scratch server killed; no scratch `claude` remains, and the scratch state dir
was removed (the foreign copy with it).

    $ T send-keys -t %0 /exit; sleep 1; T send-keys -t %0 Enter; sleep 3

    $ T kill-server; sleep 1; T list-sessions
    no server running on /private/tmp/tmux-503/usage-gauges-e2e

    $ ps -axo pid,command | grep -c "[u]sage-gauges-e2e"
    0

    $ ps -axo pid,command | grep "[p]lugin-dir .*mod-usage-gauges" | grep -c -v grep
    0

    $ ls -d $S; rm -rf $S/state; ls $S
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmp.TP1Ak4oa7D
    lib.zsh
    log
    rewrite.py
    s1.zsh
    s2.zsh
    s3.zsh
    s4.zsh
    s5.zsh
    show.py
