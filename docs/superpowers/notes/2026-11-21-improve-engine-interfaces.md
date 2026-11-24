# Improve-loop: engine interfaces on main (Task 1)

> **Superseded (plan refresh 2026-11-24, main 0af42b5).** This first run predates the engine: parts 1 and 2 merged as 064a029, so `engine/lib/engine/`, `engine/bin/engine.js` and the `tmux-ctl engine` wrapper (`bin/tmux-ctl`, `engine)` ~796) now exist, and the line numbers and "absent" findings below are out of date. Task 1 re-runs against main and rewrites this note whole; the plan's Task 1 lists the starting points. Engine §13 (holds) and §14 (schedules) were still absent at 0af42b5.

Checked on branch `supervised-improvement-loop` (rebased on main d4ded08; no code differs from main). The PCEE engine spec (`docs/superpowers/specs/2026-11-10-pcee-engine-design.md`) parts 1 and 2 failed entry gate K1 and were never built. `engine/` holds only the registry (`engine/bin/registry.js`, `engine/lib/registry/*`, a different spec). Result: the engine is absent, so every row is MISSING.

Checks run (all from the worktree root):
- `ls engine/bin` → `registry.js`
- `grep -rIlE 'sqlite|TC_ENGINE|inbox|schedule|hold' engine --exclude-dir=node_modules` → no output (no match)
- `bin/tmux-ctl engine` → `tmux-ctl: unknown command 'engine' (tmux-ctl help)`
- `ls engine/bin/hold.js claude/hooks/engine-hold.sh` → `ls: claude/hooks/engine-hold.sh: No such file or directory` (and hold.js absent)

| Interface | Engine spec § | Where on main (file:line) | Check run | Result |
|---|---|---|---|---|
| 1 engine DB path, `TC_ENGINE_DIR`, `events` table columns | §1 | none | `grep -rIn TC_ENGINE_DIR engine bin board claude tools` → no output | MISSING |
| 2 `engine rebuild --check` with scratch `proposals` table and `improve` event | §10.6 | none; no engine DB and no `rebuild`, so neither `ignored` nor `needs registration` can be decided | `grep -rIn 'engine rebuild' engine bin board claude tools` → no output | MISSING |
| 3 `inbox` table and `schedule` source (`<name>@<due_at>`) | §12 | none (only the unrelated ideas inbox, `board/ideas.py:2`) | `grep -rIn source_id engine bin board claude tools` → no output | MISSING |
| 4 brief builder for an engine-run spec's jobs; `<worktree>/.superpowers/engine/` | §1, §3 step 2 | none | `grep -rn '\.superpowers/engine' engine bin board` → no output | MISSING |
| 5 tier-to-model map the engine uses for a spec's jobs | §2 | none in the engine; `model-routing.json` is read only by `board/taskwin.py:298`, `board/metrics.py:883`, `board/scout_draft.py:63` | `grep -rn model-routing board engine` → those three, none under `engine/` | MISSING |
| 6 `metrics start`/`record` calls from the engine; run records carry `runner` | §3 step 7, §7 | `metrics start` exists (`board/metrics.py:218`, `cmd_start`) but no engine calls it; no `runner` field | `grep -rn metrics engine` → no output; `grep -c runner board/metrics.py` → `0` | MISSING |
| 7 merge step: `steps` kind `merge`, `Engine-Step: <key>` trailer, live-checkout check | §3 step 7, §10.4 | none | `grep -rIn Engine-Step engine bin board claude tools` → no output | MISSING |
| 8 morning report writer, and the point after the report is committed | §7 | none (engine `report.js` is the registry report, not the morning report) | `grep -rIn morning engine` → no output | MISSING |
| 9 event forms for architect `ruling`, review finding, "tests red after the merge" | §3, §4 | none (`board/metrics.py:245` `rulings` is a ledger count, not an engine event) | `grep -rIn ruling engine` → no output | MISSING |
| 10 `engine.json` key `holds`, default hold list, `engine/bin/hold.js`, `claude/hooks/engine-hold.sh` | §13 | none | `ls engine/bin/hold.js claude/hooks/engine-hold.sh` → both `No such file or directory` | MISSING |
| 11 `tmux-ctl engine schedule add\|list\|rm\|run-now`, `engine wake` | §14 | none | `bin/tmux-ctl engine` → `unknown command 'engine'` | MISSING |
| 12 `tmux-ctl engine` wrapper running `node engine/bin/engine.js` | §5 | none; `bin/tmux-ctl:776` wraps only `engine/bin/registry.js` (`registry` command) | `bin/tmux-ctl engine` → `tmux-ctl: unknown command 'engine'`; `ls engine/bin` → `registry.js` | MISSING |

Row 2 verdict: undecided. There is no engine DB or `rebuild`, so Task 3 cannot go `ignored` or `needs registration` until the engine exists.

## Files the later tasks change

- Task 3: undetermined: engine absent (the replay file does not exist).
- Task 5: undetermined: engine absent.
- Task 7: undetermined: engine absent.
- Task 10: undetermined: engine absent.
- Task 11: undetermined: engine absent.
