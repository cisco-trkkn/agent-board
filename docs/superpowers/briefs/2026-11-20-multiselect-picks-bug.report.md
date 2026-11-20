# Report: multi-select from Discord pressed "Apple, Pear" (runbook #30 item 5)

Outcome: no code bug found in the board or the bridge's pick path, and I could not reproduce it, so there is no fix and no
failing test. The cause is undetermined. The logs pin down one fact: the bridge's submit event carried picks [1, 2].

## Evidence
- Audit `03:11:36Z ab:dlg:p179-c54827ea39058af7:submit pressed: Apple, Pear`. The label is built in `board/discord_dialogs.py`
  `click()` from `ev["picks"]` (`", ".join(_label(ok[p]) for p in picks)`) before any key is sent. So the event already said
  picks = [1, 2]; the press and the "Review your answers" screen (`→ Apple, Pear`) agree with it. Hypothesis (a), press mapping
  to wrong rows, is ruled out: the wrong set exists before press runs.
- Hypothesis (b), board maps picks to wrong labels: ruled out. I parsed the brief's 80-column pane (with description lines) with
  `_dlg_parse | _dlg_json`: options are n=1 Apple, 2 Pear, 3 Plum, 4 Type something, 5 Chat about this. `discord_dialogs.message()`
  on that show gives toggle buttons `:t1 "1. Apple"`, `:t2 "2. Pear"`, `:t3 "3. Plum"`, then Submit and Reply.
  The existing `test_submit_presses_the_final_set_of_picks` shows picks [1, 3] press `--option 1 --option 3` with label "Apple, Plum".
- Hypothesis (c), stale older message with the same id: not supported by the logs. `_finish` deletes the key and writes an
  `edit` op without `rows`, which sets the message's components to [] (`bridge.js` `opEdit`), so the 03:10 message had no buttons
  when the 03:11:16 message was posted (`bridge.log` 447-452: dialog 03:10:00, event 03:10:07, dialog 03:11:16, event 03:11:26;
  `bridge-state.json` maps the key to the new message id 1573173860445192315). I could not read the old message back from Discord,
  so "the edit was applied" is inferred from code, not observed.
- Bridge path: `onDialogInteraction` flips style 2<->3 on the clicked custom_id and builds picks from style-3 `:t<n>` buttons.
  I ran real discord.js 14.28.1 `Message` objects through the same `toJSON` and spread code (`rowsOf`): styles and custom_ids
  survive intact. `i.message` is patched from each interaction payload (`Message._patch`, `CachedManager._add`), so the state is
  fresh per click. The bridge unit tests (`bridge.test.js` toggle and submit) use inputs of this shape.
- Not observable: toggles write no log line (only submit does) and the event files were consumed, so the actual button states at
  Submit are recorded nowhere. That is why this cannot be settled from the logs.

## What would explain it (untested)
Only a state where Pear was green at Submit. A fast-tap race on stale payloads would leave Plum alone or Apple alone, not add
Pear, so I do not think it is that. A mis-tap on Pear is possible, though the user reports Apple and Plum green.

## Suggested follow-up (not done; the brief says stop when it is not a code bug)
Make it diagnosable next time: in `bridge.js`, `say()` the toggled id and new style on each toggle, and the picks on submit.
Then ask the user to retry once.

## Follow-up done (lead's ruling): diagnostic log lines in the bridge
`tools/discord-bridge/bridge.js` `onDialogInteraction` now logs one line per toggle (`toggle <custom_id> "<label>" -> <new style>`) and one per submit
(`submit <key> picks [..] buttons t1 "<label>" <style>, …` for every `:t<n>` button of the clicked message). No behaviour change.
Tests first in `test/bridge.test.js`: `toggle logs the custom id, the label and the new style` and
`submit logs the picks and the label and style of every t<n> button`; RED run showed exactly those two failing (151 pass, 2 fail),
GREEN `npm test` 153 pass, 0 fail. Commit `f886cb6` (`fix(bridge): log each dialog toggle and the button states at submit`).
Full suite in the worktree: `ALL PASS 172 jobs in 8m9s` (rc=4 = the time budget only; `grep -c FAIL` on the output = 0).
The bridge is not restarted; the lead does that and the merge.

## Files, commits, suite
Only this report is added on branch `fix/multiselect-picks`. No code changed, so I did not run `zsh tools/tests/all.zsh`.
The parse, `message()` and discord.js probes ran as one-off scripts in the scratchpad and are not committed.

Context learned:
- Gotchas: `_dlg_parse` prints nothing on raw pane text with blank rows; feed it `sed 's/ *$//' | grep -v '^$'` first, as `_dlg_screen` does (files: tools/lib/dialog.zsh)
- Gotchas: bridge toggles log nothing and click events are consumed, so the button state at Submit is unrecoverable afterwards (files: tools/discord-bridge/bridge.js)
- Map: the audit "pressed: <labels>" is computed from the event's picks before any key is sent, so it separates click-side from press-side bugs (files: board/discord_dialogs.py)
