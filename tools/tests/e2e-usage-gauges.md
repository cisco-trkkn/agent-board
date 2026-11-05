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
    S=$S
    TMP=$TMP

    $ claude --version
    2.1.318 (Claude Code)

    $ ls $TMPDIR/tmux-ctl-$(id -u)/statusline | wc -l
         208

    $ T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP

    $ T show-environment -g TC_STATE
    TC_STATE=$TMP

    $ WT=$(git rev-parse --show-toplevel); print $WT
    /Users/<user>/agent-board/.claude/worktrees/mod-usage-gauges

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

Redactions, applied by script after the runs (the script is in the task-3 report): the real foreign tap file's session id is `<foreign-session-id>` and its `received_at` is dropped (only its rate_limits, context_window and cost fields are shown); the scratch sessions' own ids are `<sid-1>` (first run) and `<sid-2>` (the run in the last section); the temp dirs under the system temp dir are `$TMP` (the state dir), `$S` (the driver dir) and `$PROBE_DIR` (the probe plugin dir); the account name is `<user>`. Nothing else was edited.

Helper scripts the driver calls (`$S/show.py` prints the fields the mod reads; `$S/rewrite.py` sets `received_at`):

    $ cat $S/show.py
    import json, sys
    p = json.load(open(sys.argv[1]))
    print("session_id", p["session_id"])
    print("five_hour", p["rate_limits"]["five_hour"]["used_percentage"], "seven_day", p["rate_limits"]["seven_day"]["used_percentage"], "ctx", p["context_window"]["used_percentage"], "cost", p["cost"]["total_cost_usd"], "received_at", p["received_at"])

    $ cat $S/rewrite.py
    import json, sys, time
    path, age = sys.argv[1], int(sys.argv[2])
    p = json.load(open(path)); p["received_at"] = time.time() - age
    json.dump(p, open(path, "w"))
    print("received_at set to now -", age, "=", p["received_at"])

## Gauge line

After one short turn (no tools) the capture shows `⚠ agent-board: 5h 32% · 7d 92% · ctx 4% · $0.01`; the tap file's
fields (printed with a python3 one-liner, only the fields the mod reads) are 5h 32, 7d 92, ctx 4, cost 0.00888
(`$0.01`), and `grep -c "agent-board: 5h "` is 1.

    $ ls $TMP/statusline/
    <sid-1>.json

    $ T send-keys -t %0 "Reply with the single word: pong"; sleep 1; T send-keys -t %0 Enter

    $ sleep 30

    $ ls -l $TMP/statusline/
    total 8
    -rw-------  1 <user>  staff  2039 Nov  5 12:51 <sid-1>.json

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
    session_id <sid-1>
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
    <foreign-session-id>.json

    $ cp $FOREIGN_SRC $TMP/statusline/

    $ ls -l $TMP/statusline/
    total 16
    -rw-------  1 <user>  staff  2039 Nov  5 12:51 <sid-1>.json
    -rw-------  1 <user>  staff  1984 Nov  5 12:51 <foreign-session-id>.json

    $ python3 -I $S/show.py $TMP/statusline/$(basename $FOREIGN_SRC)
    session_id <foreign-session-id>
    five_hour 32 seven_day 92 ctx 27 cost 8.014046300000002

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
**`$.ui.status('')` leaves an empty `⚠ agent-board:` prefix row on screen** (found in this first run; the sections after Cleanup probe the alternatives and rerun this step with the fix) (count of `agent-board:` stays 1, count of
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
    session_id <sid-1>
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
    session_id <sid-1>
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
    session_id <sid-1>
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
    $S
    lib.zsh
    log
    rewrite.py
    s1.zsh
    s2.zsh
    s3.zsh
    s4.zsh
    s5.zsh
    show.py

## Clearing the status line

The first run showed that `$.ui.status('')` leaves an empty `⚠ agent-board:` row. The docs list no clear call, so a
throwaway probe mod (a scratch plugin dir under a mktemp dir, never in the repo; plugin name `agent-board` so the prefix
reads the same) alternates every 6 s between showing a text and applying the next variant: `undefined`, `null`, no
argument, `' '`, `''`. Each call is wrapped in try/catch and its outcome is written with `$.ui.log` (the `⏺ agent-board:
probe step N` rows in the transcript; a `THREW` entry would show an error, there is none). The row count uses
`grep -c '⚠ agent-board:'`, with the `⚠`, because the `$.ui.log` transcript rows also contain `agent-board:`.
Same scratch-server rules; one full capture at the start and one at the end, and between them a `grep -n` / `grep -c` of
the status row every 3 s.

Reading the log: texts 0 to 7 are shown at the odd/even steps. After `status(undefined)`, `status(null)` and
`status()` the row count is 0 (no row at all); after `status(' ')` and `status('')` the row is still there, empty
(`⚠ agent-board:`), count 1. None throws. The usage-gauges mod therefore clears with `$.ui.status(undefined)`.

    $ print "PROBE=$PROBE"; cat $PROBE/mods/probe.js
    PROBE=$PROBE_DIR/probe
    // scratch probe: every 6 s alternates between showing a text and applying the next clear variant
    let step = 0
    export function register(on) {
      on('session.start', async ($, e, next) => {
        $.clock.every(6000, async () => {
          const n = step++
          const k = Math.floor(n / 2)
          if (n % 2 === 0) {
            await $.ui.status('PROBE text ' + k)
            await $.ui.log('probe step ' + n + ': showed text ' + k)
            return
          }
          const names = ['undefined', 'null', 'no argument', 'single space', 'empty string']
          try {
            if (k === 0) await $.ui.status(undefined)
            else if (k === 1) await $.ui.status(null)
            else if (k === 2) await $.ui.status()
            else if (k === 3) await $.ui.status(' ')
            else await $.ui.status('')
            await $.ui.log('probe step ' + n + ': status(' + names[k] + ') returned without throwing')
          } catch (x) {
            await $.ui.log('probe step ' + n + ': status(' + names[k] + ') THREW ' + String(x && x.message ? x.message : x))
          }
        })
        return next(e)
      })
    }

    $ claude --version
    2.1.318 (Claude Code)

    $ T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP

    $ T send-keys -t %0 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $PROBE"; sleep 1; T send-keys -t %0 Enter

    $ sleep 20

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ⏺ agent-board: probe step 0: showed text 0
    
    ⏺ agent-board: probe step 1: status(undefined) returned without throwing
    
    ⏺ agent-board: probe step 2: showed text 1
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
                                                                                                      tmux focus-events off · add 'set -g focus-events on' to ~/.tmux.conf and reattach for focus tracking
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix lint errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: PROBE text 1
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ sleep 3

    $ date +%s
    1793901488

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 1
    1

    $ sleep 3

    $ date +%s
    1793901491

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ sleep 3

    $ date +%s
    1793901494

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ sleep 3

    $ date +%s
    1793901497

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 2
    1

    $ sleep 3

    $ date +%s
    1793901500

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 2
    1

    $ sleep 3

    $ date +%s
    1793901503

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ sleep 3

    $ date +%s
    1793901506

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ sleep 3

    $ date +%s
    1793901510

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 3
    1

    $ sleep 3

    $ date +%s
    1793901513

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 3
    1

    $ sleep 3

    $ date +%s
    1793901516

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901519

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901522

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 4
    1

    $ sleep 3

    $ date +%s
    1793901525

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 4
    1

    $ sleep 3

    $ date +%s
    1793901528

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901531

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 5
    1

    $ sleep 3

    $ date +%s
    1793901535

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 5
    1

    $ sleep 3

    $ date +%s
    1793901538

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901541

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901544

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 6
    1

    $ sleep 3

    $ date +%s
    1793901547

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 6
    1

    $ sleep 3

    $ date +%s
    1793901550

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901553

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board:
    1

    $ sleep 3

    $ date +%s
    1793901557

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 7
    1

    $ sleep 3

    $ date +%s
    1793901560

    $ T capture-pane -p -t %0 | grep -n '⚠ agent-board:'; T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    48:  ⚠ agent-board: PROBE text 7
    1

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ⏺ agent-board: probe step 0: showed text 0
    
    ⏺ agent-board: probe step 1: status(undefined) returned without throwing
    
    ⏺ agent-board: probe step 2: showed text 1
    
    ⏺ agent-board: probe step 3: status(null) returned without throwing
    
    ⏺ agent-board: probe step 4: showed text 2
    
    ⏺ agent-board: probe step 5: status(no argument) returned without throwing
    
    ⏺ agent-board: probe step 6: showed text 3
    
    ⏺ agent-board: probe step 7: status(single space) returned without throwing
    
    ⏺ agent-board: probe step 8: showed text 4
    
    ⏺ agent-board: probe step 9: status(empty string) returned without throwing
    
    ⏺ agent-board: probe step 10: showed text 5
    
    ⏺ agent-board: probe step 11: status(undefined) returned without throwing
    
    ⏺ agent-board: probe step 12: showed text 6
    
    ⏺ agent-board: probe step 13: status(undefined) returned without throwing
    
    ⏺ agent-board: probe step 14: showed text 7
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯ Try "fix lint errors"
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: PROBE text 7
      Haiku 5.5 · ctx –
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T kill-server; sleep 1; T list-sessions
    no server running on /private/tmp/tmux-503/usage-gauges-e2e

## Stale file, with the fixed mod

The fix (`$.ui.status(text === '' ? undefined : text)` in `usage-gauges.js`, line 49 below) was in the worktree when this
run started (`git status` shows it modified, not yet committed). Same steps as the stale part above: one turn, then
`received_at` is rewritten to now − 400 (the idle tap does not rewrite it; `show.py` shows `received_at` unchanged at
every capture). At +4 s (1793901758) the line is still there (count of `⚠ agent-board:` 1, of `5h .*7d ` 1). At +8 s
(1793901762) and +12 s (1793901766) both counts are 0: the row is gone, not empty. The `ps` count of 1 right after the
kill below was a transient (the processes were exiting); the re-check after the log shows 0 for the socket and 0 for
scratch claudes, and no server.

    $ git log --oneline -1; git status --short claude/plugin/mods/usage-gauges.js
    597f7aa test(plugin): usage-gauges real run
     M claude/plugin/mods/usage-gauges.js

    $ grep -n "ui.status" claude/plugin/mods/usage-gauges.js
    1:// usage-gauges: shows `5h <n>% · 7d <n>% · ctx <n>% · $<x.xx>` under the prompt ($.ui.status) from this session's own
    49:  await $.ui.status(text === '' ? undefined : text)

    $ T new-session -d -s e2e -n claude -x 200 -y 50 && T set-environment -g TC_STATE $TMP

    $ T send-keys -t %0 "TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin"; sleep 1; T send-keys -t %0 Enter

    $ sleep 15

    $ T send-keys -t %0 "Reply with the single word: pong"; sleep 1; T send-keys -t %0 Enter

    $ sleep 30

    $ ls -l $TMP/statusline/
    total 8
    -rw-------  1 <user>  staff  2072 Nov  5 13:02 <sid-2>.json

    $ python3 -I $S/show.py $OWN
    session_id <sid-2>
    five_hour 35 seven_day 92 ctx 4 cost 0.003877190000000001 received_at 1793901726.4823081

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Brewed for 2s · done 1:02 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 35% · 7d 92% · ctx 4% · $0.00
      Haiku 5.5 · ctx 4% · 5h 35%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    1

    $ date +%s
    1793901753

    $ python3 -I $S/rewrite.py $OWN 400
    received_at set to now - 400 = 1793901353.9915981

    $ sleep 4

    $ date +%s
    1793901758

    $ python3 -I $S/show.py $OWN
    session_id <sid-2>
    five_hour 35 seven_day 92 ctx 4 cost 0.003877190000000001 received_at 1793901353.9915981

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Brewed for 2s · done 1:02 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      ⚠ agent-board: 5h 35% · 7d 92% · ctx 4% · $0.00
      Haiku 5.5 · ctx 4% · 5h 35%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    1

    $ T capture-pane -p -t %0 | grep -c '5h .*7d '
    1

    $ sleep 4

    $ date +%s
    1793901762

    $ python3 -I $S/show.py $OWN
    session_id <sid-2>
    five_hour 35 seven_day 92 ctx 4 cost 0.003877190000000001 received_at 1793901353.9915981

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Brewed for 2s · done 1:02 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx 4% · 5h 35%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ T capture-pane -p -t %0 | grep -c '5h .*7d '
    0

    $ sleep 4

    $ date +%s
    1793901766

    $ python3 -I $S/show.py $OWN
    session_id <sid-2>
    five_hour 35 seven_day 92 ctx 4 cost 0.003877190000000001 received_at 1793901353.9915981

    $ T capture-pane -p -t %0
    
     ▐▛███▛█   Claude Code v2.1.318
    ▝▜██████▀  Haiku 5.5 · Claude Max
     ▝▝   ▝▝   ~/agent-board/.claude/worktrees/mod-usage-gauges
    
    
    ❯ Reply with the single word: pong
    
    ⏺ pong
    
    ✻ Brewed for 2s · done 1:02 PM
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ❯
    ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
      Haiku 5.5 · ctx 4% · 5h 35%
      ⏵⏵ auto mode on (shift+tab to cycle)

    $ T capture-pane -p -t %0 | grep -c '⚠ agent-board:'
    0

    $ T capture-pane -p -t %0 | grep -c '5h .*7d '
    0

    $ T send-keys -t %0 /exit; sleep 1; T send-keys -t %0 Enter; sleep 3

    $ T kill-server; sleep 1; T list-sessions
    no server running on /private/tmp/tmux-503/usage-gauges-e2e

    $ ps -axo pid,command | grep -c "[u]sage-gauges-e2e"
    1

    $ ps -axo pid,command | grep "[p]lugin-dir .*mod-usage-gauges" | grep -c -v grep
    0

    $ sleep 2; ps -axo pid,command | grep -c "[u]sage-gauges-e2e"
    0

    $ ps -axo pid,command | grep "[p]lugin-dir .*mod-usage-gauges" | grep -c -v grep
    0

    $ T list-sessions
    no server running on /private/tmp/tmux-503/usage-gauges-e2e

    $ sleep 2; ps -axo pid,command | grep -c "[u]sage-gauges-e2e"
    0

    $ ps -axo pid,command | grep "[p]lugin-dir .*mod-usage-gauges" | grep -c -v grep
    0

    $ T list-sessions
    no server running on /private/tmp/tmux-503/usage-gauges-e2e

