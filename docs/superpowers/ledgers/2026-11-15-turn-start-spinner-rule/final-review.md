# Final review: spec #2, turn-start spinner rule (d0009d3..684a57b)

Reviewer: spin-final (session level), read-only, one pass over the code diff plus the plan, the ledger and the note.
Worktree HEAD at review time: 684a57b. The worktree has one uncommitted change I did not make:
`docs/superpowers/plans/2026-11-15-turn-start-spinner-rule.md.tasks.json` (+22/-4), which is task state.

Evidence I ran in this session:
- `python3 -m unittest board.tests.test_paneclass` gave `Ran 56 tests … OK`.
- `python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'` gave `Ran 65 tests … OK`.
- Old against new on all 15 `.txt` fixtures in `tools/tests/fixtures/telegram-watch/` (uncapped listing). I loaded d0009d3's
  `paneclass.py` from a scratch copy and rebuilt the old `_spinner_above_input`:
  - The 4 new live fixtures and `working.txt` flip from `ready` to `working`.
  - The other 10 keep `ready` and `spinner_live` False.
  - On no fixture did the old watchdog check see a spinner that the new rule misses.
- Synthetic probes of the false-positive and false-negative shapes (listed under Issues).
- Watchdog probes on the real fixtures:
  - `idle_at_prompt` is False for all 5 live fixtures, with mod `None` and with mod `ready`.
  - `idle-with-teammates.txt` with its input line emptied (`❯\xa0`) gives `idle_at_prompt` True with mod `None` and with mod `ready`. So a lead with teammates still gets its reconnect.
- I did not re-run the mutation checks. The ledger records them (T1, T2, T4 ×3, T5 ×2).

### Strengths
- One source of truth. `idle_at_prompt` now calls `paneclass.spinner_live(rows[-30:])` (tools/telegram_watch.py:177), which is the same call and window `classify` uses (board/paneclass.py:156). `_spinner_above_input` is gone.
- The real-shape coverage is strong:
  - There are 5 real-capture fixtures: `working.txt`, the two task-label frames and the two wrapped hook-suffix frames.
  - Each has a provenance line in the README with its epoch and the tmux command.
  - Each has a direct `classify` test (board/tests/test_paneclass.py:134-160).
  - The agreement test covers every `.txt` fixture, with mod `None` and mod `ready` (tools/tests/test_telegram_watch.py:218-232).
- The false-positive guards are explicit:
  - The glyph set is anchored at column 0 (paneclass.py:25,28).
  - The wrap join only fires for a glyph row that has an unclosed `(` or matches no spinner regex, followed by a non-empty column-0 row that does not start with a glyph or box character (paneclass.py:106-107). The joined row must still match a spinner regex.
  - Each guard has a negative test (test_paneclass.py:177-216).
- The real-state note is unusually thorough:
  - Three runs, with frame counts and gaps.
  - The `-J` question was settled by a real capture: 24 of 24 hook-suffix frames stay wrapped.
  - The run3 classification is stated with totals: 195 working, 196 ready, 0 disagreements out of 391.
- `send_remove` is now the deployed function at module level. Its argv is pinned, and one test runs it against a real scratch tmux server started with `-f /dev/null` (test_telegram_watch.py:235-269).

### Issues

#### Critical (Must Fix)
None.

#### Important (Should Fix)
None.

#### Minor (Nice to Have)
1. **A user-prompt row can complete a join** (board/paneclass.py:26).
   - What's wrong: `WRAP_TAIL_STOP_RE` does not exclude `❯`, `>` or `›`. A column-0 glyph row that is not a spinner, followed directly by a user-prompt echo ending in `…`, joins into a first-frame spinner.
   - Probe: `["✻ Worked for 5s", "❯ do the thing…", "", RULE, "❯ "]` gives `spinner_live` True and `classify` `working`.
   - Why it is minor: in practice a blank row usually separates the two, and `⏺` output follows a prompt.
   - Fix: add `❯>›` to the stop class, with a one-line negative test.
2. **Bare task-list rows keep a transcript first-frame row live** (board/paneclass.py:30).
   - What's wrong: `TASKLIST_RE` also accepts bare indented `◼/◻` rows. Those rows are also how the idle task list is drawn (idle-with-teammates.txt:31-36).
   - Probe: a transcript `✻ Thinking…` row directly above the idle task list reads live if the `N tasks (…)` header row is missing. With the real header present (the fixture), it reads ready.
   - Why it is minor: it is synthetic. Every real idle capture has the header.
   - Fix (optional): require a `⎿` task row to come first, before bare rows are accepted.
3. **The `_do_reconnect` wiring has no test** (tools/telegram_watch.py:470).
   - What's wrong: no test covers `remove=lambda back, count: send_remove(t, pane, back, count)`. A swapped argument order would pass every test.
   - Why it is minor: it is one line, and `_remove_command` passes `(len(after), len(COMMAND))`.
   - Fix (optional): build the `PaneCtl` through a factory and assert its `remove` forwards in order.
4. **The spec wording is out of date** (docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md, Design).
   - What's wrong: the spec says "The elapsed-form spinner rule is unchanged". Tasks 4 and 5 changed it (column-0 anchor, fixed glyph set, multi-word labels, hook brackets).
   - Why it is minor: ledger rulings justify both changes and the plan records them, but a later reader of the spec gets the wrong rule.
   - Fix: a one-line amendment in the spec that points at plan Tasks 4 and 5.
5. **The README's working.txt line is out of date** (tools/tests/fixtures/telegram-watch/README.md:4).
   - What's wrong: the `working.txt` line does not say it is a real 2.1.322 capture. The spec and the test comment both say it is.
   - Fix: a cosmetic edit to that line.

### Evidence checks (1-8, one line per item)
1. **Fixture origin:**
   - The 5 positive real-shape tests load real captures. The README names the pane, the version, `capture-pane -p` without `-J`, and the epochs (README.md:7-8). The ledger says Task 3's review found them cmp-identical to the captures.
   - The synthetic rows in test_paneclass.py:162-221 are hand-written. They are negatives, or variants of a real shape whose real form is also tested, so that is fine.
   - `test_joined_hook_suffix_spinners_are_working` pins a joined shape that run3 showed tmux never produces. It is harmless and labelled as such in the ledger.
2. **Artefact under test:**
   - Tests call the deployed `paneclass.spinner_live`/`classify`, `telegram_watch.idle_at_prompt` and `telegram_watch.send_remove`. There is no copy.
   - tmux, the external command, is run for real in `test_real_pane`. It runs against bash readline, not Claude's input box; a ledger ruling records why `cat` cannot work.
   - The `_do_reconnect` lambda is untested (Minor 3).
3. **User-experienced check:**
   - The real-state note measures what the board serves: `/api/state` from an ephemeral board, plus the pane capture.
   - It also states that mod states hid the gap live, and that the watchdog reads pane text.
   - No probe gave a result the note could not explain.
4. **State:**
   - Real checks ran on the long-lived live lead pane `%8`, with teammates, an active task list and hooks, at 111 columns. Fresh scratch state was not used.
   - Conditions never met:
     - another terminal width or font (wrap points)
     - a non-macOS glyph set (the open Linux gate)
     - a lead with no task list during a hook-suffix frame
   - `test_real_pane` falls back to `/opt/homebrew/bin/tmux` and errors rather than skips without tmux (test_telegram_watch.py:248). That fallback is a host-specific path; see the deferred-minor triage.
5. **Universal claims:**
   - The note's "0 of 391" and "195/196" counts state their totals over all frames.
   - The agreement test asserts `len(names) >= 10` and `live >= 3` over the uncapped glob.
   - My own "no fixture regresses" claim rests on the full 15-row listing above.
   - The "16/16 real wraps break after `·`" claim in the ledger is a count with its total.
6. **Inputs agents cannot read:** none. The one human-only input is the Linux spinner glyph, already an open user gate (Task 4).
   - Merge-gate item for the description: [ ] On a Linux host, run `tmux capture-pane -p -t <claude pane>` mid-turn and confirm the spinner glyph is in `·✢✳✶✻✽*`. This is not a merge blocker, per the lead.
7. **Runbook preconditions:** the note is not a runbook. Its method names the board command (`TMUX_DASH_TOKEN=… TMUX_DASH_PORT=7710 python3 board/server.py`) and the capture commands. Nothing is left as an unresolved "must exist".
8. **Endpoint trust:** not applicable. No configurable endpoints.

### Deferred-minor triage (one line per ledger minor: fix before merge | stays deferred, why)
- T1, Ctrl+Y row accepted only as a tip continuation, with no synthetic test: **stays deferred**. The real `working.txt` pins it through the tip-continuation branch.
- T1, RED run name and exit code missing from the report: **stays deferred**. It is a process record; later mutations cover the rule.
- T2, `test_real_pane` uses the `/opt/homebrew/bin/tmux` fallback and errors instead of skipping (test_telegram_watch.py:248): **stays deferred**. There is no CI map (`.agent-ci.yml` is absent), and every host this suite runs on has tmux. It is a cheap follow-up: `skipUnless(shutil.which("tmux"))`.
- T2, a capture-pane failure in the poll loop raises CalledProcessError: **stays deferred**. The test still fails loudly, just with a less clear message.
- T2, stale `tw-remove-*` socket files: **stays deferred**. `kill-server` runs in `finally`, the cause is unexplained, and nothing reproduces it.
- T4, `fixture_rows` duplicates the loader (test_paneclass.py:134-147): **stays deferred**. It is test-only duplication.
- T4, the round-1 column-0 anchor mutation was not re-run after round 2: **stays deferred**. `test_indented_glyph_prose_is_not_a_spinner` guards the anchor, and it passes at HEAD.
- T5, no test puts a team row or indented row between a wrapped head and tail: **stays deferred**. Claude draws the wrap itself, so no row can sit between a head and its tail. A probe shows both shapes read `spinner_live` False: no join, and a head with no elapsed part matches nothing. That fails toward ready only for a shape that cannot be drawn. The probes: a team row between head and tail, and `  ⎿  ◼ a` between them.
- T5, joined tests hand-concatenate real rows: **stays deferred**. Run3 settled that `-J` does not join, and the wrapped real fixtures are tested.
- T5, a wrap right before `· 2s` reads ready (paneclass.py:26,107): **stays deferred**. My probe confirms it still reads ready. Real data has 0 of 391 run3 frames and 0 of 16 run2 frames in this shape, and the board's mod state covers it mid-turn. Only the watchdog is exposed, and only with a stale or absent mod.
- T5, a column-0 `*`/`·` prose row plus an unindented continuation ending `…` reads working: **stays deferred**. Assistant prose is indented under `⏺`, so a column-0 glyph prose row is rare. My probe shows that a column-0 `* Next steps…` above the rule also reads working, which is the same accepted risk.
- T3, the note's headline and run2 "Gap found" read as current: **stays deferred**. The "After Task 4" paragraph says what is fixed at ae58ae1. A one-line status under the title would help, but nothing is wrong.
- T3, criterion 3's literal command and output are not pasted: **stays deferred**. The note gives the call and the per-epoch results.
- T3, run1's median gap was 0.28 s against a 0.25 s target: **stays deferred**. Run2 (0.19 s) and run3 meet it, and the turn-start frames were captured.
- T3, no real `·`-led wrap tail: **stays deferred**. This is the same item as the T5 `· 2s` minor.

### Assessment
**Ready to merge?** Yes

**Reasoning:** Every planned change is present, and the Task 4 and 5 deviations carry ledger rulings. The board and the watchdog read one rule, and the agreement test checks that over every fixture. Both touched suites pass at 684a57b (56 and 65 OK). No fixture changes verdict except the five that now correctly read working. The remaining gaps are rare synthetic shapes or the known Linux-glyph user gate.
