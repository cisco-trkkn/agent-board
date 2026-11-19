# Final whole-branch review: Discord /ideas (feat/discord-ideas-command)

Reviewer: id-final. Range 9246e05..7ac12e5 (6 commits, 18 files, +1261 −15). Read-only: no repo file changed; `git status` shows only the `plans/…tasks.json` change that was already there.

## Verdict

**Ready to merge: with fixes.** One Important finding must be fixed before the merge (the board's hot path), and one Important item goes into the user gate's precondition text. Nothing is Critical. Counts: 0 Critical, 2 Important, 13 Minor.

The feature itself works: I ran the whole chain in scratch state through the real `bridge.js`, the real board consumers and the real `tmux-ctl` CLI, and the formats match at every hop.

## What I ran (all in this session)

| Check | Command | Result |
|---|---|---|
| Every suite | `tmux-ctl run -t 900 -C <worktree> tests "zsh tools/tests/all.zsh; echo rc=$?"` | `ALL PASS 155 jobs in 6m53s`, 3777 tests, 0 `FAIL` lines (uncapped `grep -c`); `rc=4` is the runner's `SLOW: 6m53s over the 5 min budget`, not a failure (the Task 3 run had the same rc 4). My measurement and seam runs loaded the machine during this run |
| Bridge tests | `node --test test/*.test.js` in `tools/discord-bridge` | 132 pass, 0 fail, rc 0 |
| Cross-task seam run | a scratch script that drives the real `createBridge` (with the repo's `FakeClient`), `discord_ops.consume`, `discord_controls.consume_events`, `discord_ideas.expire` and `bin/tmux-ctl discord ideas-list/ideas-post`, on a temp `TC_STATE`, `TC_IDEAS_DIR` and `HOME` | rc 0; details under "Seams" |
| Hot path | `server.build_state()` 3 × 40 runs each way on a scratch tmux server (`-L perfsock -f /dev/null`, sessions `proj` and `overseer`) | 2 tmux execs per build against 1; details under Important 1 |
| Real-state check (read-only) | `bin/tmux-ctl discord ideas-list` on the live ideas dir; `ideas-post <doc> --dry-run` with a scratch `TC_STATE` and the live ideas dir | 44 rows (31 + 11 + 2), equal to `grep -c '^- \[ \] '` per file (31, 11, 2, 0, 0); dry-run `would post 3 groups, skipped 0`, rc 0; the scratch state holds only the request file and the lock |
| Failure probes | a scratch Python run of `post`/`click` with long titles, 12 groups, a failing `set_status` and a failing edit write | results cited in the findings |

Nothing was written under the live `~/.local/state/agent-board`, and nothing was posted to Discord.

## Strengths

- `discord_ideas.py` is one small module with one lock. `post` validates everything, persists the state and marks the request `answered` before it writes any op, so a retry cannot duplicate posts (discord_ideas.py:186-198).
- R3 holds: `click` never takes the ops-state lock, and the ideas lock is never held across a call back into `discord_ops`.
- The `/ideas` branch in `handle_event` sits after the allowlist check and before `_known` (discord_ops.py:349-356), so a null project works and a stranger is rejected without a request.
- The permission widening for the overseer was probed against the real CLI by two agents (task-4-report, task-4-review): compounds, substitutions and redirects are denied.
- Tests isolate state (`TC_STATE`, `TC_IDEAS_DIR`, `HOME`, `_kick` patched) and the CLI test checks for leaks under the scratch `HOME`.

## Seams (checked with the real code on both sides)

1. **Slash to groups.** `/ideas` in the alpha project channel wrote `{"type":"slash","command":"ideas","project":null,"bridge":"alpha",…}`. `consume_events` turned it into `req-<id>.json` with `"bridge": "alpha"` and the line `[Discord] /ideas <id>: group the open ideas of all projects, then run tmux-ctl discord ideas-post with the groups JSON` for `overseer`. `ideas-post -` on stdin answered `posted 2 groups, skipped 1`. The ops outbox stayed empty and the alpha bridge sent three messages to `C1`: two groups, each with one action row of three buttons (`style` 1/2/4, `custom_id` `ab:ideas:<act>:<req>:<g>`), and `skipped: 1 ids`. The same run through the ops bridge (`/ideas alpha` in #command-center, `bridge: "_ops"`) posted to `CC`.
2. **Click to edit (R1).** A click on the bridge wrote `{"type":"click","custom_id":"ab:ideas:next:<req>:0","user":"U1",…}`. The project consumer audited `queued`, queued `regroup: Alpha things — ideas: <id>, <id>` for `alpha`, and wrote the edit; the bridge's `opEdit` sent `{"content": "<header>\n→ sent to alpha's lead to brainstorm", "components": []}`. Through the ops consumer, Drop audited `dropped 3`, marked the three lines `- [-]`, and the edit read `<header>\ndropped 3` with `components: []`. A second tap was audited `unknown` and changed nothing. A stranger got `Not authorized.` and no event was written.
3. **Expire.** `expire` returned 0 at +170 s and 1 at +181 s; the bridge posted `overseer didn't answer /ideas`; a late `ideas-post` was refused with `request is closed`, rc 1.
4. **Delivery to the overseer.** `build_state` runs every 10 s from the notifier thread (`overview_loop`, server.py:589-600, through `build_overview` → `state()`), so the line reaches the overseer with no browser open. `regroup` is an existing lead rule (claude/orchestrator.md:64), so the lead knows the line.

## Findings

### Critical

None.

### Important

**1. The board runs a second tmux exec on every state build, whether or not an overseer line is waiting.** board/server.py:338-345, called at server.py:399.
- The overseer's pane is left out of `ids` (server.py:361), so it is never in `rows_by`, and `capture_panes([f[7]])` runs on every `build_state`. The overseer session exists by default (`ensure_overseer`), so this is every poll on every machine.
- Measured on a scratch tmux server, 3 rounds of 40 builds each way, with no line pending for the overseer: 2 tmux execs per build against 1; median 104.3 / 94.5 / 102.7 ms against 46.1 / 46.3 / 45.1 ms, so about +50 ms per build. Load average was 5.3 to 5.8 (the test suite was running), so read the ratio, not the absolute numbers.
- It breaks the rule written above `_last` (server.py:181-184: "One tmux exec per build"). The wiring test cannot see it, because it patches `capture_panes` (test_discord_ideas_wiring.py:142).
- Fix: return `[]` at the top of `_overseer_sessions` when `COMMENTS.pending(OVERSEER_SESSION)` is empty. The capture then runs only on the builds that have a line to deliver. Add a test that counts `server.tmux` calls for a build with an overseer session and nothing pending (expected: 1).
- **Must fix before merge.**

**2. The user gate's preconditions omit the board restart and name no command for the overseer restart.** docs/superpowers/plans/2026-11-19-discord-ideas-command.md:197.
- The line names the two bridge restarts with their commands, and "the overseer restarted" with none. It does not mention the board, which is a long-running process that loaded the old modules.
- Without the board restart, the old `handle_event` audits `/ideas` as `unknown project` (a null project fails `_known`), and the user sees the ack and then nothing: no groups and no time-out post.
- Commands to add: `agent-board dash stop && agent-board dash start` (README.md:56), and `bin/tmux-overseer stop --force` (bin/tmux-overseer:53-62: without `--force` it does nothing while a project session exists; the board's `ensure` on each overview build brings the overseer back, bin/tmux-overseer:6-7). The overseer needs the restart for both the new `overseer.md` and the new allow rules.
- This is a text fix in the plan or in the gate's task description. It does not block the merge commit, but the gate will fail without it. **Fix before the user gate runs.**

### Minor

1. **`error: edit failed` hides what the click did.** board/discord_ideas.py:254-257 (and :233-235). Probed: a Drop that marked 2 ideas `- [-]` and then failed to write the edit returned `error: edit failed`; the audit line says nothing about the drop. The same string is also returned by the pre-check, where nothing ran. It needs a failed outbox write (disk), so it is rare, but it is exactly the case where Discord shows no feedback and the audit is the only record. Fix: return `f"{result} (edit failed)"` after the action, and keep `error: edit failed` for the pre-check only. **Can defer; two lines, so take it in the fix wave.**
2. **Title and emoji are unconstrained.** board/discord_ideas.py:159, :177, :237. Probed: a title with a newline goes into the header as two lines; a 2500-character title makes a 2529-character `regroup:` line, which `CommentQueue._flat` cuts to 2000, so the ids are lost, and a 2555-character edit, which the bridge cuts to 2000, so the result line is lost. The title is written by the overseer (a model that reads idea text and Discord chat) and is typed into a lead's prompt when the user presses Brainstorm next. The user sees the title before pressing, which limits the risk. Fix: collapse whitespace and cap the title (80) and the emoji in `post`. **Can defer; cheap, take it in the fix wave.**
3. **The project consumer writes no audit line when `click` raises.** board/discord_controls.py:162-164, inside a `try/finally` with no `except` (:145-171). Probed with `set_status` raising `OSError`: the exception left `consume_events`, the event file was deleted, and `audit.jsonl` was not written. The ops consumer audits `error: …` in the same case (discord_ops.py:489-493). The constraint says every click is audited by its consumer. Can defer.
4. **`expire` runs only when the ops bot is configured.** board/server.py:533-534 gates `ops_tick`, which holds the call (:555-558). With project bots only, `/ideas` in a project channel is accepted and asked, but an unanswered request never gets `overseer didn't answer /ideas`. Can defer.
5. **A rejected request is silent on Discord.** tools/discord-bridge/lib/commands.js:59-60 and :75-79. With no `views.json` (no ops bot), `/ideas typo` is acked `asked the overseer, about 1 min`; the board audits `unknown project` and posts nothing. `invalid bridge` is silent in the same way. Can defer.
6. **The 10-group cap counts the document's index, not the valid groups.** board/discord_ideas.py:156. Probed: 3 empty groups followed by 9 valid ones posted 7 and skipped 2. Can defer.
7. **`no open ideas` is also the answer to an empty `groups` list while ideas are open.** board/discord_ideas.py:182-183. Ideas the overseer leaves out of every group are not reported either. Can defer; a line `<n> not grouped` would tell the user.
8. **Request and post files are never removed.** board/discord_ideas.py:202-216 reads every `req-*.json` on each tick (every 10 s). Growth is one or two small files per `/ideas`, so it is slow. Can defer.
9. **A corrupt `ts` or a missing `id` in one request file stops every time-out.** board/discord_ideas.py:207, :210, and :149 in `post`. The files are written only by this module. Can defer.
10. **A CLI test pins two checks to a branch commit.** tools/tests/test_discord_ideas_cli.zsh:49-50 compare the deny list and the other allows to `git show a773c48:…`. The checks fail in a clone without that object (a squash merge, a shallow clone) and on the next legitimate change to the overseer's allow list. Fix: literal expected lists. Line :51 counts matching lines (`-ge 2`), so two `ideas-list` lines pass without the here-string form. Can defer; the repo merges with merge commits, so it holds today.
11. **The answer goes to the bot's home channel, not to the channel where the command was typed.** The spec's request file carries `channel`; the constraints replace it with `bridge`, and `opPost` sends to `home()` (bridge.js:172). The ops bot's `/ideas` typed in another channel of the guild is answered in #command-center. This is the convention of the other commands. No change needed; noted as a deviation from the spec's wording.
12. **Bridge hardening.** tools/discord-bridge/bridge.js:186: a missing label becomes the text `undefined`, and `custom_id` is not cut to 100. The board's `_check` (discord_feed.py:76-81) already requires both as strings, and the ids are about 25 characters. bridge.js:189 keeps the newest 200 keyed posts, so the edit for a click on a much older group finds no message and the buttons stay. Can defer.
13. **Test and style notes from the task reviews.** `PROJECT_RE` copied (discord_ideas.py:25); the `or` assert (test_discord_ideas.py:138); the precedence trap (:166); dead `raw = None` (:293); `TestClickEditFailure(TestClick)` reruns the parent's tests (:310); the file-path form is untested in `main` (:348; the CLI test does cover it); the dense click line (discord_controls.py:164); allow patterns without a word boundary (claude/overseer-settings.json:9); the filter in test_overseer_channel.zsh:52 is not end-anchored. Can defer.

## Ledger triage

| Ledger line | Decision |
|---|---|
| Task 3: extra `capture_panes` call on every `build_state` poll | **Must fix before merge** (Important 1, measured) |
| Task 1 re-review: `error: edit failed` replaces the real audit result | Can defer; recommended in the fix wave (Minor 1) |
| Task 1: title newline and length unconstrained | Can defer; recommended in the fix wave (Minor 2) |
| Task 1: corrupt request `ts` raises in `expire` and `post` | Can defer (Minor 9) |
| Task 1: `PROJECT_RE` copied; `ANSWER_WINDOW` comment; vacuous `or` assert; precedence trap; dead code; file-path form untested; untested branches; `list <bad project>` rc 0 | Can defer (Minor 13) |
| Task 1 re-review: partial outbox leaves unclickable groups; state-file `OSError` traceback; duplicated test runs; probe checks the header only | Can defer |
| Task 2: missing label → `undefined`; `custom_id` not cut to 100 | Can defer (Minor 12) |
| Task 2: `/ideas bogus` with no `views.json` is acked and forwarded | Can defer (Minor 5). The board does reject it (`request` returns `unknown project`, pinned by `test_unknown_project_writes_nothing`), but the user is told nothing |
| Task 2: unknown-project test lacks the `flags: 64` check; no project-mode `/ideas <given>` test | Can defer |
| Task 3: dense click line; obscure `addCleanup` drain; hardcoded `claude` window name | Can defer |
| Task 4: allow patterns lack a word boundary; exclusion not end-anchored; `grep -c ≥2` loose; "no `'` in titles" conservative | Can defer |
| Task 4: CLI test pins the deny list to `git show a773c48` | Can defer (Minor 10); replace with literals when the file is next touched |
| Ruling R1 (buttons removed on edit, no ephemeral `already done`) | Holds. Seam run: the edit sends `components: []` and a second tap is audited `unknown` |
| Ruling R2 (`/ideas` never defaults to the channel's project) | Holds. Seam run: the project channel wrote `project: null` and the request covers all projects |
| Ruling R3 (own `state.lock`) | Holds. No path takes the ops-state lock inside `discord_ideas`; the ops consumer ran a click under `_state(True)` with no deadlock |
| Ruling: Task 1 and Task 2 in parallel | No conflict found in the merged result |

## Evidence checks

1. **Fixture origin.**
   - test_discord_ideas.py: ideas files are hand-written in the format `ideas.py` writes, and are read by the real `ideas.load`. Acceptable.
   - test_discord_ideas_wiring.py: slash and click events are hand-written (`{"type":"click","custom_id":…,"user":"U1"}`), and `discord_ideas` is mocked. The bridge tests pin the bridge's event shape separately. No test in the diff passes the bridge's real output to the board. My seam run did that and the shapes match, so this is a gap in the suite, not a defect. Recommendation: keep one cross-language test.
   - bridge tests: ops are hand-written in the shape `discord_ideas.post` emits (same keys, same button fields); the seam run confirmed the real ops render.
   - `row()` in the wiring test is a hand-written `list-panes` line with 17 fields, matching `fmt` at server.py:349-354.
2. **Artefact under test.** The CLI test runs the real `bin/tmux-ctl` and the real `discord_ideas.py`. The wiring test loads the real `server`, `discord_ops` and `discord_controls`. The bridge tests load the real `bridge.js` with a fake client. The overseer permission rules were probed with the real `claude -p` and the real settings file (task-4-report, task-4-review); I did not repeat that probe. The tmux call in `_overseer_sessions` is patched in its only test; see Important 1.
3. **User-experienced check.** No layout or visibility check is in the diff. What the user sees on Discord (the groups, the buttons, the edit) is covered only by the user gate (Task 5).
4. **State.** Every test runs on fresh scratch state. Long-lived conditions never met: a board that was not restarted (Important 2), a request older than the bridge's 200 keyed posts, many old request files, a GitLab-mapped project whose idea line gains ` · gl#<n>` between the post and the click (the key no longer matches, and the idea is counted `already changed`, as the spec says). The CLI test sets a scratch `HOME`; no test in the diff hard-codes a path under the real `HOME`.
5. **Universal claims.** "Every open idea is listed" rests on uncapped counts: 44 rows against 31 + 11 + 2 open lines, counted per file with `grep -c`. "Nothing written to live state" rests on the scratch `TC_STATE` and `HOME` of each run and on the file listing of the scratch state, not on a diff of the live directory, which the live bridges change all the time.

## Other checks

6. **Inputs agents cannot read.** The Discord side (the slash command registered in the guild, the buttons on the phone, the overseer answering within the 180 s) cannot be checked by an agent. It is the user gate, Task 5. Merge-gate items for it:
   - [ ] After the merge: `agent-board dash stop && agent-board dash start`; `tmux-ctl discord bridge stop && tmux-ctl discord bridge start`, the same with `--ops`; `bin/tmux-overseer stop --force`.
   - [ ] `/ideas` in #command-center, then `tail -5 ~/.local/state/agent-board/discord/_ops/audit.jsonl` shows `ideas:all` → `asked` and the three clicks.
7. **Runbook preconditions.** See Important 2. docs/INSTALL.md does not list the slash commands, so it needs no change.
8. **Endpoint trust.** No configurable endpoint is added.

## Recommendations

- Fix wave: Important 1 with its test, then Minor 1 and Minor 2 in the same commit series (about 10 lines in all). Re-run `zsh tools/tests/all.zsh`.
- Correct the Task 5 precondition text before the gate.
- Later: one cross-language seam test (bridge output into the board consumers), pruning of old request files, and a `<n> not grouped` line.

## Context learned

- `Gotchas`: a scratch tmux socket cannot live under the session scratchpad: the path exceeds the 104-byte unix socket limit and tmux fails with `File name too long`; use `mktemp -d /tmp/x.XXXXXX` for `TMUX_TMPDIR` (files: tools/tests/all.zsh).
- `How to run`: `build_state` can be timed against a scratch server with `env -u TMUX TMUX_DASH_TMUX_ARGS="-L <sock>" TC_STATE=<tmp> TC_NOTIFY=0 python3` and a wrapper that counts `server.tmux` calls (files: board/server.py, board/paneclass.py).
- `Map`: `ops_tick`, and with it `discord_ideas.expire`, runs only when `discord_ops.configured()` (files: board/server.py).
- `Map`: the repo's `FakeClient` plus `createBridge` can be driven from a script outside the test runner to pass real bridge events to the Python consumers (files: tools/discord-bridge/test/fake-client.js, tools/discord-bridge/bridge.js).
