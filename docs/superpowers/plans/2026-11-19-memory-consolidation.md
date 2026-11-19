# Memory Consolidation ("dreaming") and Targeted Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nightly headless run condenses each project's shared context file to a core of at most 8192 bytes and moves the rest to an archive (nothing deleted, checked by the script, revertible from Discord); archived entries come back to an agent by the files its first prompt names, and by `tmux-ctl context search`.

**Architecture:** `board/dream.py` is the script around the model: it copies the core, the archive and the inputs into a run directory, runs one `claude -p` confined to that directory, checks the result with the pure functions of `board/dream_check.py`, and only then commits both files under the context lock, with backups. `board/dream_actions.py` (revert, file proposals) and `board/dream_discord.py` (post, clicks) sit on top; `discord_controls.consume_events` routes `ab:dream:` clicks. Recall is a self-contained `UserPromptSubmit` hook script in the plugin plus `context.py search`.

**Tech Stack:** Python 3 standard library (board modules, `unittest`), zsh (`bin/tmux-ctl`, `tools/tests` on a scratch tmux server via `tools/tests/lib.zsh`), bash + inline `python3 -I` (plugin hook script), Claude Code CLI 2.1.328 (`claude -p`), launchd.

**Spec:** `docs/superpowers/specs/2026-11-12-memory-consolidation-design.md` (binding; read it with this plan)

## Global Constraints

Every task and every reviewer works from these. `D` is the context dir, `context.context_dir()` (`${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}`); `<p>` is a project key matching `context.PROJECT_RE`.

**G1. Files.**
- `D/<p>.md`: the core. `D/<p>.archive.md`: the archive, first line `# <p>: archived agent context`, then a blank line and the four headings; no size cap. `D/<p>.dream.json`: `{"last_run": <ISO UTC of the last successful run>, "sources_digest": <sha1 hex>, "last_report": <abs path of that run's out/report.json>, "run": <run id>, "root": <repo main checkout>, "failures": <consecutive failed runs>, "reverted": <run id or null>}`.
- Run id: local time `YYYYMMDD-HHMM`. Backups: `D/backups/<p>.md.<run id>` and `D/backups/<p>.archive.md.<run id>`. Run dir: `D/dream/<p>/<run id>/` holding `core.md`, `archive.md` (the model's working copies), `inputs/`, `out/report.json` (model), and, written by the script, `out/diff.txt`, `out/run.json`, `out/core.after.md`. A `--dry-run` uses a `tempfile.mkdtemp()` run dir instead and removes it. Backups and run dirs older than 14 days (by run id) are pruned after each successful run. `D/dream/<p>/run.lock`, `D/dream/<p>/filed.json`.
- Projects for `--all`: stems of `D/*.md` that match `PROJECT_RE` and do not end in `.archive`.
- `CAP = 8192` (bytes of the core file), defined once in `board/context.py`; `board/dream_check.py` imports nothing from the board and repeats the number with a comment naming `context.CAP` and a test that asserts they are equal.

**G2. Entry lines.** A file is: optional `# …` title and `Last curated: …` lines before the first heading, the four headings `## Map`, `## How to run`, `## Gotchas`, `## Decisions` in that order, each once, blank lines, and entry lines. An entry line matches `^- .+ · (\d{4}-\d{2}-\d{2})( · archived \d{4}-\d{2}-\d{2})?( · stale: .+ gone)?$`. Any other non-blank line makes the file invalid. Core entries carry neither suffix. `base(line)` is the line with both suffixes removed; `files_of(line)` is the comma-split content of its `(files: …)` group (empty set when it has none). On 2026-11-18 all four real files parse with zero problems (agent-board 211 entries / 52652 bytes, interiors 165 / 45632).

**G3. No entry lost.** Every entry line `o` of the old core and old archive passes when some new entry (core or archive) has `base == base(o)`, or when `report.changed.merged` has an item whose `from` list contains `o[:60]` and whose `into` equals `t[:60]` for a new entry `t` with `files_of(t) ⊇ files_of(o)` and date `≥` the date of `o`. Anything else is `entry lost`.

**G4. Report.** `out/report.json`, written by the model: `{"changed": {"merged": [{"into": str, "from": [str, …]}], "archived": int, "stale": int, "added": int}, "contradictions": [{"a": str, "b": str, "note": str}], "proposals": [{"kind": "idea"|"observer", "text": str, "evidence": [str, …]}], "summary": str}`. The script recomputes the four counts from the files and uses its own numbers everywhere: merged = old entries accepted through a merge item; archived = old core entries whose base is in the new archive; stale = new archive entries with a stale suffix whose base had none before; added = new entries whose base is not an old base and whose first 60 characters are not an `into`.

**G5. Checks** (run in this order; the first failure is the `<check>` text): `model timeout` | `model exit <rc>` | `model error` (result JSON has `is_error` true or does not parse) | `report missing` | `report invalid: <why>` | `core invalid: <first problem>` | `core over 8192 bytes (<n>)` | `archive invalid: <first problem>` | `entry lost: <first 60 chars>` | `stale claim: <path> exists` (an entry newly marked stale must cite at least one path and none may exist under the repo root) | `files changed during the run` | `write failed: <error>`.

**G6. The model step** (probed on Claude Code 2.1.328, 2026-11-18; see "Probes"). Exact argv, cwd = the run dir, prompt on stdin, timeout 900 s:
`claude -p --model sonnet --effort medium --restricted --tools Read,Grep,Glob,Write,Edit --permission-mode dontAsk --settings <repo>/claude/dream-settings.json --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json`
The binary is `$TC_DREAM_CLAUDE` when set, else `claude` on PATH. The child environment drops `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_SSE_PORT`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CLAUDE_CODE_CHILD_SESSION`, `TMUX`, `TMUX_PANE` (the same list `bin/claude-overseer` unsets, plus tmux). The stdin prompt is the text of `claude/dream.md` followed by a trailer `\n\nProject: <p>\nToday: <YYYY-MM-DD>\nCore cap: 8192 bytes\n`. The result JSON on stdout gives `is_error`, `total_cost_usd`, `duration_ms`, `usage.{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}`.

**G7. The permission gate** (`claude/dream-settings.json`), stated as what it accepts. Accepted: `Read`, `Grep`, `Glob` on paths inside the run dir (after symlink resolution); `Write` and `Edit` on exactly `core.md`, `archive.md` and any path under `out/` of the run dir. Everything else is refused: `--restricted` removes Bash and the other code-running tools and WebFetch and confines every file tool to the working directory; `dontAsk` refuses any call no allow rule matches. The file's exact content: `{"permissions": {"defaultMode": "dontAsk", "allow": ["Read", "Grep", "Glob", "Edit(core.md)", "Edit(archive.md)", "Edit(out/**)"], "deny": ["Bash", "WebFetch", "WebSearch", "Agent", "Skill", "NotebookEdit"]}}`. No allow entry is matched by a deny entry (checked: the deny list names tools only, none of them allowed).

**G8. Commit.** Under `context.locked(p, wait=30)`: compare the live core and archive with the copies taken at the start. Equal: write. Live core has every snapshot entry line plus new ones (a `context add` during the run): append each new line to the end of its section in the new core, then write (the core may then exceed the cap; print the over-cap notice of G12). Anything else: fail `files changed during the run`, write nothing. Writing: take both backups first, write the archive then the core through a temp file and `os.replace`, copy the committed core to `out/core.after.md`; an exception after the backups restores both files from them. A failed run changes no file in `D` except `failures` in `<p>.dream.json`.

**G9. Locks.** One context lock per project: `fcntl.lockf` (never `flock`: the two do not exclude each other on macOS) on `D/<p>.md.lock`, taken only through `context.locked(project, wait)`, which polls every 0.1 s and raises `ValueError("locked by another writer (the nightly run?); retry in a moment")` after `wait` seconds. `lockf` locks belong to the process: a test that needs a held lock holds it from a subprocess. One run at a time per project: `fcntl.flock(LOCK_EX | LOCK_NB)` on `D/dream/<p>/run.lock`; held means `dream: <p> already running`, exit 0.

**G10. Stdout lines of `dream.py run`** (exact): `dream: off` · `dream: skipped, weekly <n>%` · `dream: <p> skipped, unchanged sources` · `dream: <p> skipped, no repo root` · `dream: <p> already running` · `dream: <p> failed — <check>` · `dream: <p> ok — no changes` · `dream: <p> ok — merged <n>, archived <n>, stale <n>, added <n>; <k> proposals; <c> contradictions` · with `--dry-run` the word `ok` is `dry run` and the diff follows. Exit 0 unless a project failed (1) or the arguments are wrong (2).

**G11. Discord ops** (written with `discord_feed.outbox_write(tc_env.discord_dir(p), op)`, only when `discord_feed.channel_of(p)` is non-empty):
- Changes post: `{"op": "post", "text": "🌙 memory: merged <n>, archived <n>, stale <n>, added <n>; <k> proposals; <c> contradictions\n<summary>", "tier": "progress", "mention_user": false, "key": "dream-<p>-<run>", "files": ["<abs out/diff.txt>"], "buttons": [{"label": "Revert", "style": 4, "custom_id": "ab:dream:revert:<p>:<run>"}, {"label": "File proposals", "style": 1, "custom_id": "ab:dream:file:<p>:<run>"}]}`. Text cut to 1900 characters. The File proposals button is present only when k > 0. A `custom_id` over 100 characters drops both buttons and appends `\nrevert: tmux-ctl context dream-revert <p> <run>`.
- Contradictions post (only when c > 0): `{"op": "post", "text": "🌙 memory: these entries contradict each other. Which is right?\n1. A: <a>\n   B: <b>…", "tier": "decision", "mention_user": true, "key": "dream-<p>-<run>-contra"}`, at most 5 pairs, text cut to 1900.
- Failure post, written when `failures` becomes exactly 3: `{"op": "post", "text": "🌙 memory: <p> failed 3 nights running — <check>", "tier": "critical", "mention_user": true, "key": "dream-<p>-fail-<run>"}`.
- Click results are new `post` ops (tier `progress`, no mention, key `dream-<p>-<run>-reverted` / `-filed`), never `edit` ops: the bridge's `opEdit` sends `components: []`, which would remove the other button.
- Click id: `^ab:dream:(revert|file):([A-Za-z0-9][A-Za-z0-9._-]*):(\d{8}-\d{4})$`. Audit results: revert → `reverted` | `already reverted` | `stale: newer run <id>` | `unknown`; file → `filed <n>` | `already filed` | `no proposals` | `unknown`; a click whose project is not the consuming bridge's project → `ignored`; a user outside `access.json` `allowFrom` → `rejected`.

**G12. `context` CLI texts.** After an `add` that leaves the core over 8192 bytes, a second stdout line: `context: core over 8 KB (<n>), the nightly run will condense it` (`<n>` = bytes). `search` prints one line per match, `[core] <Section>: <entry line>` or `[archive] <Section>: <entry line>`, core first, file order; no match prints `context: no entries match` on stderr; exit 0 either way.

**G13. Recall hook.** Additional context text: `Archived project context matching the files in your task:` then one entry line per row. At most 4096 bytes of entry lines, whole entries only, newest date first. Marker: `<state dir>/context-recall/<session_id>` where the state dir is `$TC_STATE`, else `${TMPDIR:-/tmp}/tmux-ctl-<uid>` (the rule of `tc_env.state_dir`). Kill switch `TC_CONTEXT=0`. Any error: no output, exit 0.

**G14. Tests never touch real state.** Every test sets `TC_CONTEXT_DIR`, `TC_STATE` and `HOME` to temp dirs and removes them. The model is `board/tests/fixtures/dream/claude`, a fake put first on PATH (or named by `TC_DREAM_CLAUDE`). The only real-state checks are the read-only ones the tasks name, and the two user gates.

**G15. Running suites.** Run suites with `tmux-ctl run [-t secs] tests "<cmd>"`, not the Bash tool. The whole-repo verdict is `zsh tools/tests/all.zsh; echo rc=$?` (rc 4 with `SLOW:` and ALL PASS is only the time budget). New `board/tests/test_*.py` and `tools/tests/test_*.zsh` files are picked up by name; nothing to register.

**G16. Commits.** Conventional with scope (`feat(board): …`, `feat(tmux-ctl): …`, `feat(plugin): …`, `docs(…): …`); end with the attribution trailer your harness specifies. Stage only the task's own files (`git add <paths>`).

**User decisions (already made):** (spec "Decisions (user, 2026-11-12)", quoted)
- "**Memory may be rewritten without asking; rules and skills are only proposed.** The job keeps the core file within 8 KB and moves the rest to an archive (nothing deleted), posts the diff with a Revert button. Rule, skill and workflow changes become ideas or task-observer notes for the user."
- "**A small core plus targeted recall**, not a bigger injection: core ≤ 8 KB always; archived entries matched to the files a task names, ≤ 4 KB; search on demand."
- "Contradictions are flagged, never resolved by the job."

**Spec vs code** (the spec is 12 days old; each line is what the code or a probe shows today, and the ruling):
- S1. Lock. Spec: a `mkdir`-style `<p>.lock`. Code: `context.add` takes `fcntl.lockf` on `<p>.md.lock` and blocks without limit. Ruling: keep the code's lock, add the 5 s bound (G9).
- S2. Where the model writes. Spec: Write/Edit on the live `<p>.md` and `<p>.archive.md`, restored from backups on failure. Ruling: the model edits copies in the run dir and the script commits them (G8). A lock held across a 15-minute model run cannot coexist with "`context add` waits up to 5 s", and the gate then needs no path outside the working directory. "Restore on failure" becomes "a failed run never wrote"; the restore path remains for a failure in the middle of the commit.
- S3. Flags. Spec: `claude -p --model sonnet --effort medium`, settings with `dontAsk`. Ruling: add `--restricted --tools … --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json` (G6); every flag is in `claude --help` of 2.1.328 and was used in the probe.
- S4. Sizes. Spec: cores of 33 KB and 39 KB, 24 ledgers, 217 `Ruling:` lines. Today: 52652 and 45632 bytes, 36 ledgers, 318 lines. Ruling: no design change; the first run reads every ledger (292 KB of `progress.md`).
- S5. Outside tmux. `bin/tmux-ctl` line 92 dies without `$TMUX` for everything but `discord`; launchd has no tmux. Ruling: `context dream*` subcommands run outside tmux and take the project as an argument.
- S6. Project to repo. The spec does not say how a context key finds its repo. Ruling: the session path of the live tmux session whose group or name is `<p>` (not a `@tc_bg` one), through `relay.root_for`; else the `root` remembered in `<p>.dream.json`; else `--root`; else the project is skipped (`no repo root`).
- S7. Metrics. `tmux-ctl metrics` has no generic record command; readers skip unknown kinds (`board/metrics.py` header). Ruling: the run appends `{"kind": "dream", …}` with `metrics.append`, only when the repo already has `docs/superpowers/metrics/runs.jsonl`.
- S8. "The board writes one post op". Ruling: the dream process writes it with `discord_feed.outbox_write`, as `board/discord_send.py` does from the CLI; the bridge picks it up either way.
- S9. Buttons. The bridge `deferUpdate`s every click before the board sees it and an `edit` op removes all buttons. Ruling: click results are new posts; a repeated tap changes nothing and is only audited (G11).
- S10. Filing proposals. `tmux-ctl idea` needs tmux and the observer's `new-observation.sh` lives in the plugin directory (`~/.claude/plugins/**/task-observer/scripts/`), not in the workspace. Ruling: ideas go through `ideas.add` (the function behind `tmux-ctl idea`); the observer script is `$TC_OBSERVER_SCRIPT`, else the newest match of that glob, with workspace `${TASK_OBSERVER_WORKSPACE:-~/.task-observer}`; when it is not found the observer proposals stay unfiled and are reported.
- S11. The hook's "session's state dir". Ruling: G13's marker path; the `UserPromptSubmit` stdin shape was probed (keys `cwd`, `hook_event_name`, `permission_mode`, `prompt`, `prompt_id`, `session_id`, `transcript_path`).
- S12. Additions the spec does not name: `dream.json` fields `run`, `root`, `failures`, `reverted`; `--force` (skip the digest and usage checks); `tmux-ctl context dream-revert <p> <run>` (the Revert button's function, for projects with no channel); `tmux-ctl context dream-schedule install|status|uninstall` (the spec names the job, not its installer).
- S13. Weekly usage. The number `tmux-ctl metrics start` records: `usage.plan_limits(usage.tap_entries(now, 10 ** 9))["seven_day"]["used_percentage"]`. Ruling: a tap whose `seven_day.resets_at` is in the past, or no tap, counts as unknown and the night runs.
- S14. Reports input. `docs/superpowers/reports/` holds one top-level `.md` and two audit directories. Ruling: the glob is the spec's `reports/*.md`, top level only.
- S15. The live install links `~/.local/bin/tmux-ctl` into the main checkout, so the launchd job runs whatever `main` holds. Ruling: the schedule is installed only in the user gate, after the merge.

**Probes** (run by the plan author on 2026-11-18, Claude Code 2.1.328, macOS):
- P1, the gate. In a scratch dir, `claude -p --model haiku --effort low --restricted --tools "Read,Grep,Glob,Write,Edit" --permission-mode dontAsk --settings ../settings.json --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json < ../prompt.txt` with G7's settings. Results, confirmed on the filesystem (only `core.md` and `out/report.json` changed): Write `out/report.json` OK; Edit `core.md` OK; Read `inputs/a.md` OK; Write `../elsewhere/escape.txt` refused ("is outside …; --restricted confines the file tools to the working directory"); Write to an absolute path outside refused (same); Write `out/link/x` where `out/link` is a symlink to an outside dir refused ("resolves through a symlink to …"); Write `inputs/new.md` (inside the cwd, no allow rule) refused ("denied because Claude Code is running in don't ask mode"); Write `out/../inputs/dotdot.md` refused (same); Bash: no such tool; Read of an outside file and Read through the symlink refused. Result JSON keys used by G6 were present; cost $0.0035.
- P2, the hook. A `UserPromptSubmit` command hook given by `--settings` received the keys listed in S11, and its `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "The magic word is PLUGH."}}` reached the model (it answered `PLUGH`).
- P3, launchd. `man launchd.plist`: `StartCalendarInterval <dictionary of integers …>`, "launchd will start the job the next time the computer wakes up". A plist from `plistlib.dumps` with `"StartCalendarInterval": {"Hour": 3, "Minute": 30}` passes `plutil -lint` (`OK`).
- Not probed: whether an in-process teammate's brief fires `UserPromptSubmit`. Task 9 checks it on a real teammate.

---

## File map

| File | Task | Role |
|---|---|---|
| `board/context.py` (modify) | 1 | `CAP`, `archive_path`, `locked`, `entries`, `search`, the over-cap notice, CLI `search` |
| `bin/tmux-ctl` (modify) | 1, 4, 5, 7 | `context search`; `context dream`, `dream-report`; `dream-file`, `dream-revert`; `dream-schedule` |
| `claude/worker.md`, `claude/orchestrator.md` (modify) | 1 | the `context search` line; the nightly run and archive in "Shared project context" |
| `board/dream_check.py` (create) | 2 | pure checks and counts, `verify` CLI |
| `claude/dream.md`, `claude/dream-settings.json` (create) | 3 | the model's prompt; the gate |
| `tools/tests/check_real_dream_gate.zsh` (create) | 3 | the real-`claude` gate probe (not in the suite: its name is not `test_*`) |
| `board/dream.py` (create; modify in 5) | 4 | the run |
| `board/tests/fixtures/dream/claude` (create) | 4 | the fake model |
| `board/dream_actions.py`, `board/dream_discord.py` (create) | 5 | revert and file; post and click |
| `board/discord_controls.py` (modify) | 5 | route `ab:dream:` clicks |
| `claude/plugin/scripts/context-recall.sh` (create), `claude/plugin/hooks/hooks.json`, `claude/plugin/.claude-plugin/plugin.json` (modify) | 6 | recall hook |
| `board/dream_schedule.py` (create), `docs/INSTALL.md` (modify) | 7 | launchd job |

Tasks 1, 2, 3 and 6 share no file and can run in parallel. Tasks 4, 5 and 7 run in that order (each edits `bin/tmux-ctl`). Tasks 8 and 9 are user gates after the merge.

---

### Task 1: Context archive, bounded lock, search

**Goal:** `board/context.py` knows the archive file, takes its lock with a 5 s bound, warns when an add leaves the core over 8192 bytes, and searches core and archive; `tmux-ctl context search` exposes it and the agent rules mention it.

**Files:**
- Modify: `board/context.py`
- Modify: `bin/tmux-ctl` (header comment lines 29-30; the `context)` case, lines 542-551)
- Modify: `claude/worker.md`, `claude/orchestrator.md` ("Shared project context", lines 84-90)
- Test: `board/tests/test_context.py`, `tools/tests/test_ctl_context.zsh`

**Acceptance Criteria:**
- [ ] `context.CAP == 8192`; `context.archive_path("p")` is `D/p.archive.md`; a bad project name raises `ValueError` as `context_path` does
- [ ] `context.locked(project, wait)` is a context manager on `D/<p>.md.lock` using `fcntl.lockf`; while a subprocess holds the lock, `add` waits and succeeds when it is released within 5 s, and exits 2 with `context: locked by another writer (the nightly run?); retry in a moment` when it is held longer
- [ ] An add that leaves the core at more than 8192 bytes still succeeds and prints, after the `added under …` line, `context: core over 8 KB (<n>), the nightly run will condense it`; an add that leaves it at or under 8192 prints no such line
- [ ] `context.entries(text)` returns `[(section, line)]` in file order for a file in G2's format; `context.search(project, words)` returns `[(source, section, line)]`, core before archive, for entries containing every word case-insensitively
- [ ] `tmux-ctl context search usage tap` prints `[core] <Section>: <line>` and `[archive] <Section>: <line>` rows (G12); no match prints `context: no entries match` on stderr and exits 0; `tmux-ctl context search` with no word exits 2 with the usage line
- [ ] `tmux-ctl help` lists `context search`; `claude/worker.md` and `claude/orchestrator.md` each say: before relearning something about a file, run `tmux-ctl context search <words>`; `claude/orchestrator.md` also says the core is condensed nightly to 8 KB and that the rest is in `<project>.archive.md`
- [ ] Real state, read-only: `TC_CONTEXT_DIR=~/.local/state/agent-board/context python3 -I board/context.py search --project agent-board usage` exits 0 and prints at least one `[core]` row from the 52 KB file written over the last three weeks; `git status --short` and the file's `shasum` are unchanged by it

**Verify:** `python3 -m unittest board.tests.test_context && zsh tools/tests/test_ctl_context.zsh` → `OK` and `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `board/tests/test_context.py` add a class `ArchiveAndSearchTest` (same `setUp`/`tearDown` shape as `ContextPathTest`: temp `TC_CONTEXT_DIR`, temp `HOME`). Tests and the mutation that must make each fail:
  - `test_lock_wait_times_out`: a subprocess runs `python3 -c` that takes `fcntl.lockf(LOCK_EX)` on `D/p.md.lock` and sleeps 8 s; `context.locked("p", wait=0.5)` raises `ValueError`. Mutation: replace the polling loop by a blocking `lockf` → the test hangs past its 5 s `subprocess` deadline and fails.
  - `test_add_waits_for_a_short_hold`: the holder sleeps 1 s; `context.add` returns the line. Mutation: `wait=0` in `add` → `ValueError`.
  - `test_over_cap_notice`: fill the core past 8192 bytes with adds; `main(["add", …])` stdout has the notice with the file's real byte count. Mutation: compare `len(text)` instead of bytes with a `·`-heavy file sized between the two counts → notice missing.
  - `test_no_notice_at_cap`: a core of exactly 8192 bytes after the add prints one line. Mutation: `>=` instead of `>` → fails.
  - `test_search_all_words_both_files`: core has `usage tap` and `usage only`, archive has `Usage TAP archived`; `search("p", ["usage", "tap"])` returns the core row then the archive row with their sections. Mutation: `any` instead of `all` → three rows.
  - `test_search_no_archive_file`: no archive file → core rows only, no exception.
- [ ] **Step 2: Run them, see them fail.** `python3 -m unittest board.tests.test_context` → `AttributeError: module 'context' has no attribute 'locked'` (and the like).
- [ ] **Step 3: Implement.** The lock helper, run once by the plan author against a held lock (0.5 s wait → `ValueError`, 5 s wait → acquired):

```python
@contextlib.contextmanager
def locked(project, wait=5.0):
    """Exclusive fcntl.lockf on <file>.lock, polled every 0.1 s for up to `wait` seconds; ValueError when it stays held."""
    p = context_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{p}.lock", "w") as lk:
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.lockf(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise ValueError("locked by another writer (the nightly run?); retry in a moment")
                time.sleep(0.1)
        yield p
```

  `add` uses `with locked(project) as p:` in place of its `open(...)`/`lockf` pair and keeps the rest of its body. `main` prints the notice when `context_path(project).stat().st_size > CAP`. `entries(text)` walks lines, tracks the current `## ` heading, and yields `(section, line)` for lines starting `- `. `search` reads `show(project)` and the archive file when it exists. Add the `search` subparser (`--project`, `words` nargs `+`).
- [ ] **Step 4: `bin/tmux-ctl`.** In the `context)` case add `search) [[ -n "$1" ]] || die 'usage: tmux-ctl context search <words…>'; python3 -I "${0:A:h:h}/board/context.py" search --project "$FEEDKEY" -- "$@" ;;` and extend the usage `die` text and the header comment (lines 29-30) with `search <words…>`. In `tools/tests/test_ctl_context.zsh` add checks for the two row formats (write an archive file by hand into `$TC_CONTEXT_DIR/tt.archive.md`), the no-match stderr line with exit 0, the no-word exit 2, and `help` listing `context search`.
- [ ] **Step 5: Rules.** One line in `claude/worker.md` (in "How work is done here") and one in `claude/orchestrator.md` ("Shared project context"); plus the orchestrator sentence about the nightly condensing and `<project>.archive.md`.
- [ ] **Step 6: Run and commit.** Verify command green, then the real-state check of the last criterion. `git add board/context.py board/tests/test_context.py bin/tmux-ctl tools/tests/test_ctl_context.zsh claude/worker.md claude/orchestrator.md`; commit `feat(board): context archive, bounded lock and search`.

---

### Task 2: `board/dream_check.py`, the checks

**Goal:** Pure functions that decide whether a consolidated core and archive may replace the old ones, and count what changed; a `verify` CLI over five paths.

**Files:**
- Create: `board/dream_check.py`
- Test: `board/tests/test_dream_check.py`

**Acceptance Criteria:**
- [ ] `parse(text)` returns `(entries, problems)` per G2; all four real context files parse with zero problems (read-only test, skipped when `~/.local/state/agent-board/context/agent-board.md` is absent)
- [ ] `check(old_core, old_archive, new_core, new_archive, report, root=None)` returns `None` when G5's file checks pass, else the check text, in G5's order: `report invalid: …`, `core invalid: …`, `core over 8192 bytes (<n>)`, `archive invalid: …`, `entry lost: <first 60 chars>`, `stale claim: <path> exists`
- [ ] A core entry carrying an `archived` or `stale` suffix fails as `core invalid: archived entry in the core`
- [ ] A merged entry is accepted only under G3 (declared in `changed.merged`, files a superset, date not older); the four rejections (undeclared, a file dropped, an older date, `into` matching no new entry) each return `entry lost: …`
- [ ] `stale claim` is checked only when `root` is given; an entry newly marked stale with no `(files: …)` group fails as `stale claim: no files cited`
- [ ] `counts(old_core, old_archive, new_core, new_archive, report)` returns `{"merged", "archived", "stale", "added"}` per G4, from the files, whatever numbers the report claims
- [ ] `report_problem(report)` returns `None` or the reason for every shape rule of G4 (wrong type at each key, a proposal kind outside `idea|observer`, an empty proposal text)
- [ ] `diff(old_core, old_archive, new_core, new_archive, project)` returns one unified diff text over both files (`difflib.unified_diff`, file labels `<p>.md` and `<p>.archive.md`), empty when nothing changed
- [ ] `python3 -I board/dream_check.py verify --old-core A --old-archive B --new-core C --new-archive D --report R [--root DIR]` prints `ok` and exits 0, or prints the check text and exits 1; a missing `--old-archive` or `--new-archive` file reads as empty
- [ ] `CAP` in this module equals `context.CAP` (a test imports both)

**Verify:** `python3 -m unittest board.tests.test_dream_check` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_dream_check.py`, building texts from a small helper `doc(map=[…], run=[…], gotchas=[…], decisions=[…])`. Each guard test with the mutation that must fail it:
  - `test_over_cap_rejected` (core of 8193 bytes; 8192 passes). Mutation: `>=` → the 8192 case fails; measuring `len(str)` → a multi-byte core passes wrongly.
  - `test_lost_entry_rejected`. Mutation: return `[]` from `lost` → fails.
  - `test_merged_entry_accepted`, `test_merge_dropping_a_file_rejected`, `test_merge_with_older_date_rejected`, `test_undeclared_merge_rejected`, `test_merge_into_missing_entry_rejected`. Mutation: drop the `files_of(t) >= files_of(o)` clause → the file test fails; drop the date clause → the date test fails.
  - `test_moved_entry_with_suffixes_is_not_lost` (an old core entry present in the new archive with ` · archived …` and ` · stale: … gone`). Mutation: compare lines instead of `base` → fails.
  - `test_missing_heading`, `test_stray_line`, `test_undated_entry`, `test_archived_entry_in_core`.
  - `test_stale_claim_file_exists` (temp `root` with the cited file present → fails; absent → passes). Mutation: skip the existence test → fails.
  - `test_counts_ignore_the_report` (report claims 99 of each). Mutation: return `report["changed"]` → fails.
  - `test_real_files_parse` (read-only, skipped when absent): prints nothing, asserts zero problems and `len(entries) > 100` for `agent-board.md`, so it cannot pass on an empty file.
  - `test_verify_cli_ok_and_fail` (subprocess, both exits).
- [ ] **Step 2: Run, see them fail.** `ModuleNotFoundError: No module named 'dream_check'`.
- [ ] **Step 3: Implement.** The core of the module, run once by the plan author against the four real files (0 problems; 211, 165, 18 and 0 entries) and against the merge cases above (each printed `True`). Copy it verbatim and build `check`, `counts`, `report_problem`, `diff` and `main` around it:

```python
import re

CAP = 8192   # context.CAP; test_cap_matches_context keeps them equal
SECTIONS = ("Map", "How to run", "Gotchas", "Decisions")
ENTRY_RE = re.compile(r"^- .+ · (\d{4}-\d{2}-\d{2})( · archived \d{4}-\d{2}-\d{2})?( · stale: .+ gone)?$")
SUFFIX_RE = re.compile(r"( · archived \d{4}-\d{2}-\d{2})?( · stale: .+ gone)?$")
FILES_RE = re.compile(r"\(files: ([^)]*)\)")


def base(line):
    """The entry without its archive suffixes: what must survive a run byte for byte."""
    return SUFFIX_RE.sub("", line)


def files_of(line):
    m = FILES_RE.search(line)
    return {f.strip() for f in m.group(1).split(",") if f.strip()} if m else set()


def date_of(line):
    return ENTRY_RE.match(line).group(1)


def parse(text):
    """(entries, problems): entries is [(section, line)] in file order; problems is empty when the file is well formed."""
    entries, problems, seen, section = [], [], [], None
    for n, line in enumerate(text.split("\n"), 1):
        if line.startswith("## "):
            section = line[3:]
            seen.append(section)
        elif line.startswith("- "):
            if section is None:
                problems.append(f"line {n}: entry before any heading")
            elif not ENTRY_RE.match(line):
                problems.append(f"line {n}: not a valid entry")
            else:
                entries.append((section, line))
        elif line.strip() and not (section is None and (line.startswith("# ") or line.startswith("Last curated: "))):
            problems.append(f"line {n}: not an entry, heading or blank")
    if tuple(seen) != SECTIONS:
        problems.append(f"headings are {seen}, want {list(SECTIONS)}")
    return entries, problems


def lost(old_lines, new_lines, merged):
    """Old entries that survive neither verbatim nor through a declared merge. merged = report['changed']['merged']."""
    new_bases = {base(l) for l in new_lines}
    out = []
    for o in old_lines:
        if base(o) in new_bases:
            continue
        ok = False
        for m in merged:
            if o[:60] not in m.get("from", []):
                continue
            for t in new_lines:
                if t[:60] == m.get("into") and files_of(t) >= files_of(o) and date_of(t) >= date_of(o):
                    ok = True
        if not ok:
            out.append(o)
    return out
```

  An empty old or new archive text is treated as the archive skeleton (four headings) before `parse`.
- [ ] **Step 4: Run and commit.** Verify command → `OK`. `git add board/dream_check.py board/tests/test_dream_check.py`; commit `feat(board): dream_check, the consolidation checks`.

---

### Task 3: The dream prompt and its permission gate

**Goal:** A prompt that makes one Sonnet run at medium effort produce a core, an archive and a `report.json` that pass `dream_check.check` on this project's real 52 KB context file, inside a permission gate that accepts exactly G7.

**Files:**
- Create: `claude/dream.md`
- Create: `claude/dream-settings.json`
- Create: `tools/tests/check_real_dream_gate.zsh`
- Test: `board/tests/test_dream_settings.py`

**Constraints:**
- `claude/dream-settings.json` has exactly G7's content; `board/tests/test_dream_settings.py` asserts the `allow` list, the `deny` list and `defaultMode` by equality, and that no `allow` entry starts with `Bash`, `Write(` outside the three paths, or names a path containing `..` or starting with `/` or `~`.
- The prompt covers the spec's six model steps (§2 "What the model does") in the model's terms: the working directory layout of G1 (`core.md`, `archive.md`, `inputs/ledgers/<name>/progress.md`, `inputs/reports/*.md`, `inputs/observer/*.md`, `inputs/gitlog.txt`, `inputs/missing-files.txt`), the entry format and suffixes of G2, the merge rule of G3 as an instruction (a merged entry keeps the newest date and the union of `files:`, and is declared in `changed.merged` with the first 60 characters of each line), the report shape of G4 with one filled example, and the cap as a byte count of the whole `core.md` file.
- The prompt says what the model must not do: delete an entry, resolve a contradiction (both entries stay untouched and are listed), rewrite an entry it is not merging, write anywhere but `core.md`, `archive.md` and `out/report.json`, propose more than 10 proposals.
- Core choice follows the spec: How to run, the gotchas that cost time recently, current decisions; the rest moves to the archive with ` · archived <today>`; an entry whose cited files are all in `inputs/missing-files.txt` moves with ` · stale: <path> gone` as well.
- Proposals come only from a ruling or ledger problem that recurs in three or more specs, with `evidence` as `inputs/ledgers/<name>/progress.md:<line>` references.
- The prompt reads as instructions to a capable model with no context: it explains why (agents get only this core at session start; the script rejects the run if an entry is lost or the core is over the cap), and it tells the model to count bytes conservatively (aim for 7500).
- `tools/tests/check_real_dream_gate.zsh` repeats probe P1 with the committed settings file and `--model haiku --effort low`: it builds the scratch layout under `mktemp -d`, runs the eleven attempts from one prompt, and asserts on the filesystem (not on the model's words) that exactly `core.md` and `out/report.json` changed, that nothing exists under the outside directories, and that no `bash.txt` exists; it prints `checked 11 attempts` and `GATE OK`, exits 1 otherwise, and removes its scratch dir.

**Acceptance Criteria:**
- [ ] `python3 -m unittest board.tests.test_dream_settings` passes; changing any allow entry in the JSON (for example `Edit(out/**)` to `Edit(**)`) fails it
- [ ] `zsh tools/tests/check_real_dream_gate.zsh` run once by the implementer prints `checked 11 attempts` and `GATE OK` (one real `claude` call, about $0.01); its output is in the task report
- [ ] Bypasses tried and refused, each named in the script: `../` relative write, absolute outside write, write through a symlink inside `out/`, write inside the cwd outside the three paths, `out/../inputs/` normalisation, Bash absent, outside Read, Read through a symlink
- [ ] One real prompt run by the implementer on a copy: with `core.md` = a copy of `~/.local/state/agent-board/context/agent-board.md`, an archive skeleton and `inputs/` built by hand from `docs/superpowers/ledgers/*/progress.md`, G6's argv produces files for which `python3 -I board/dream_check.py verify …` prints `ok` (if Task 2 is not merged into the task's base yet, the three checks are done by hand: `wc -c core.md` ≤ 8192, four headings, `grep -c '^- '` of old ≤ new core + archive + merged `from` items); the run's cost and the verify output are in the task report
- [ ] `claude/dream.md` names every key of G4 and both suffix formats of G2 (`grep -c` for each of `changed`, `merged`, `contradictions`, `proposals`, `summary`, `archived`, `stale:` is at least 1)

**Verify:** `python3 -m unittest board.tests.test_dream_settings && grep -c -E 'changed|merged|contradictions|proposals|summary' claude/dream.md` → `OK` and a count of at least 5

Commit: `feat(claude): the dream prompt and its permission gate`, staging the four files; end with the attribution trailer your harness specifies.

---

### Task 4: `board/dream.py`, the run

**Goal:** `tmux-ctl context dream <project>|--all [--dry-run] [--force]` runs the consolidation for a project end to end with every skip, check, backup, lock and record of the spec's §2 and "Error handling", and `tmux-ctl context dream-report <project>` prints the last run.

**Files:**
- Create: `board/dream.py`
- Create: `board/tests/fixtures/dream/claude` (executable fake)
- Modify: `bin/tmux-ctl` (line 92 check; an early dispatch after the `discord` one at line 287; header comment)
- Test: `board/tests/test_dream.py`, `tools/tests/test_ctl_dream.zsh`

**Acceptance Criteria:**
- [ ] `TC_DREAM=0` or a file `D/dream.off` prints `dream: off`, exits 0, starts no model
- [ ] Weekly usage at or over 85 (S13's number, from a tap file under the test's `TC_STATE/statusline/`) prints `dream: skipped, weekly <n>%` and starts no model; 84, a tap whose `resets_at` passed, and no tap all run; `--force` runs at 99
- [ ] The digest is a sha1 over the core, the archive, each `docs/superpowers/ledgers/*/progress.md` and `docs/superpowers/reports/*.md` (path and bytes, sorted), the byte total of the observer log dir and the repo's HEAD sha; a second run with nothing changed prints `dream: <p> skipped, unchanged sources`; touching any one of the six sources makes it run; `--force` runs regardless
- [ ] The repo root resolves per S6, in that order; none → `dream: <p> skipped, no repo root`
- [ ] The model's argv, cwd, stdin trailer and scrubbed environment equal G6 exactly (the fake records them); the run dir holds the inputs of G1, with `inputs/gitlog.txt` from `git log --name-status` since `last_run` (30 days on a first run) and `inputs/missing-files.txt` listing every cited path that does not exist under the root
- [ ] Fake `good`: both files replaced, both backups hold the old bytes, `<p>.dream.json` advanced with the post-run digest, `out/run.json`, `out/diff.txt` and `out/core.after.md` written, stdout is G10's `ok` line with the script's own counts
- [ ] Fake `overcap`, `lost`, `badreport`, `noreport`, `exit1`, `hang` (with the timeout patched to 1 s): stdout `dream: <p> failed — <check>` with G5's text, exit 1, core and archive byte-identical to before, `last_run` and `sources_digest` not advanced, `failures` incremented; a later good run resets `failures` to 0
- [ ] Fake `merged`: accepted, count merged = 2
- [ ] A `context add` made while the model runs survives the commit in its section; a rewrite of the core during the run fails as `files changed during the run`
- [ ] A write failure injected after the backups (patch `os.replace` to raise on the core) leaves both files byte-identical to the backups and reports `write failed: …`
- [ ] `--dry-run` runs the model in a temp dir, prints `dream: <p> dry run — …` and the diff, and leaves `D` byte-identical (compare a recursive listing with sizes and hashes before and after), with no run dir, backup, `dream.json`, metrics line or Discord op
- [ ] A second process while one holds `run.lock` prints `dream: <p> already running`, exit 0
- [ ] Backups and run dirs with a run id older than 14 days are pruned after a successful run; younger ones stay
- [ ] A repo with `docs/superpowers/metrics/runs.jsonl` gains one line `{"kind": "dream", "at", "project", "run", "outcome", "cost_usd", "tokens", "duration_s", "model": "sonnet"}`; a repo without the file gains nothing; `metrics.last_runs` over a log with that line returns what it returned before
- [ ] `--all` runs every project of G1's rule in sorted order and exits 1 if any failed, after trying all
- [ ] `tmux-ctl context dream <p>`, `dream --all` and `dream-report <p>` work with `TMUX` unset; `tmux-ctl context show` with `TMUX` unset still dies with `not inside tmux`; `dream-report` prints the last `out/run.json` fields and the report's summary, proposals and contradictions, or `dream: <p> has no run yet`
- [ ] Real state, read-only: `TC_DREAM_CLAUDE=$PWD/board/tests/fixtures/dream/claude FAKE_DREAM_MODE=unchanged tmux-ctl context dream agent-board --dry-run --force` against the real context dir prints `dream: agent-board failed — core over 8192 bytes (<n>)` with n over 50000, and `shasum` of every file under `~/.local/state/agent-board/context` is the same before and after

**Verify:** `python3 -m unittest board.tests.test_dream && zsh tools/tests/test_ctl_dream.zsh` → `OK` and `ALL PASS`

**Steps:**

- [ ] **Step 1: The fake model.** `board/tests/fixtures/dream/claude`: an executable `#!/usr/bin/env python3` script. It appends one JSON line `{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": <text>, "env": {<the eight names of G6 that are set>}}` to `$FAKE_DREAM_LOG` when that is set, then acts on `$FAKE_DREAM_MODE` in its cwd: `good` (keep the first two entries of each section in `core.md`, move the rest to `archive.md` with ` · archived <today>`, write a valid report), `merged` (also replace the first two Map entries by one entry with both files and the newer date, declared in `changed.merged`), `overcap` (leave an over-cap core), `lost` (drop one entry from both files), `badreport` (`out/report.json` = `not json`), `noreport`, `unchanged` (touch nothing, valid empty report), `exit1` (exit 1), `hang` (sleep 60), `slow` (sleep `$FAKE_DREAM_SLEEP` then act as `good`). Every mode but `exit1`/`hang` prints `{"is_error": false, "total_cost_usd": 0.01, "duration_ms": 5, "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}}`.
- [ ] **Step 2: Failing tests** in `board/tests/test_dream.py`: one `unittest.TestCase` with a temp `TC_CONTEXT_DIR`, `TC_STATE`, `HOME`, a temp git repo (`git init`, one ledger, one report, one commit) passed as `--root`, an over-cap fixture core whose entries are dated across more than one day and cite files of that repo, some of them missing, and `TC_DREAM_CLAUDE` pointing at the fake. One test per acceptance criterion above. Guard tests and the mutation that must fail each:
  - `test_off_starts_no_model` / `test_usage_skip_starts_no_model` / `test_digest_skip_starts_no_model`: assert the fake's log file does not exist. Mutation: remove the early return → the log exists.
  - `test_argv_is_exact`: equality with G6's list. Mutation: drop `--restricted` from the argv → fails.
  - `test_env_is_scrubbed`: the test sets all eight names; the fake's `env` object is empty. Mutation: pass `os.environ` unchanged → fails.
  - `test_failed_run_changes_nothing` (one subTest per failing mode): hashes of every file in `D` except `<p>.dream.json`, and of `D/backups` listing, equal before and after; the hash set is asserted non-empty. Mutation: write the files before the checks → fails.
  - `test_add_during_run_survives` (mode `slow`, a thread calls `context.add` in a subprocess during the sleep). Mutation: skip the re-append → the entry is missing.
  - `test_rewrite_during_run_fails`. Mutation: skip the snapshot comparison → the run reports ok.
  - `test_write_failure_restores`. Mutation: remove the restore → the archive differs from its backup.
  - `test_dry_run_writes_nothing`: the listing is asserted to contain the core, so it cannot pass on an empty dir. Mutation: use the real run dir under `D` → fails.
  - `test_prune_keeps_recent`. Mutation: prune by mtime instead of run id (the test backdates only the names) → fails.
  - `test_metrics_line_only_where_log_exists`.
- [ ] **Step 3: Run, see them fail.** `ModuleNotFoundError: No module named 'dream'`.
- [ ] **Step 4: Implement `board/dream.py`.** Start it like `board/discord_ideas.py` (lines 20-23): `sys.path.insert(0, str(Path(__file__).resolve().parent))`, then import `context`, `dream_check`, `discord_feed`, `metrics`, `relay`, `tc_env`, `usage`. Shape: `main(argv)` with subcommands `run` and `report`; `run_project(project, now, dry_run, force, root)` returning a result dict (`outcome` in `ok|unchanged|failed|skipped`, `check`, `counts`, `run`, `run_dir`, `report`); small functions `projects()`, `resolve_root(project, state, root_arg)`, `weekly_pct(now)`, `digest(project, root)`, `prepare(run_dir, project, root, state)`, `run_model(run_dir, project, now)`, `commit(project, snapshot, new_core, new_archive, run, run_dir)`, `prune(project, now)`, `record_metrics(root, rec)`. The live tmux lookup for S6 uses the same listing as `board/restore.py` line 154 (`list-sessions -F '#{session_name}\t#{session_group}\t#{session_path}\t#{@tc_bg}'`) through the tmux binary `$TC_TMUX`, else `~/.local/bin/tmux`, else `tmux`; a failing tmux is "no live session". The observer inputs are the files under `${TASK_OBSERVER_WORKSPACE:-~/.task-observer}/skill-observations/observation-log/*.md` changed since `last_run` whose text contains the project name; a missing dir is no input. A metrics or prune error is printed to stderr and never fails the run. Leave one function `notify(result)` that does nothing yet; Task 5 fills it.
- [ ] **Step 5: `bin/tmux-ctl`.** Line 92 becomes (run by the plan author in zsh: `context dream` and `context dream-file` pass with `TMUX` empty, `context show` and `idea` do not):

```zsh
[[ -n "$TMUX" || "$1" == discord || ( "$1" == context && "$2" == dream* ) ]] || die "not inside tmux"   # discord and context dream* work outside tmux
```

  After the `discord` early dispatch (line 287) add one for `context` with `$1` in `dream`, `dream-report`: `dream` maps to `python3 -I "${0:A:h:h}/board/dream.py" run "$@"` (argument required: `--all` or a project), `dream-report` to `dream.py report "${1:-$FEEDKEY}"`, exiting with the script's status; an empty project dies with the usage line. Add the two lines to the header comment. `tools/tests/test_ctl_dream.zsh` (uses `lib.zsh`, `tt_setup claude`, temp `TC_CONTEXT_DIR`, the fake through `TC_DREAM_CLAUDE`, `--root "$TT_DIR/repo"`): a good run through `tmux-ctl`, the same with `TMUX= TMUX_PANE=`, `dream-report` after it, `dream` with no argument exits 2, `context show` outside tmux dies, `help` lists `context dream`.
- [ ] **Step 6: Run and commit.** Verify command green; then the read-only real-state criterion; then `tmux-ctl run -t 900 tests "zsh tools/tests/all.zsh; echo rc=\$?"` and read the runner's verdict line. `git add board/dream.py board/tests/test_dream.py board/tests/fixtures/dream/claude bin/tmux-ctl tools/tests/test_ctl_dream.zsh`; commit `feat(board): the nightly memory consolidation run`.

---

### Task 5: Discord post, Revert, File proposals

**Goal:** A run with changes posts G11's ops to the project's home channel; the Revert and File proposals buttons and their CLI twins act once, safely against double taps, repeats and out-of-order taps; three failed nights post one critical line.

**Files:**
- Create: `board/dream_actions.py`, `board/dream_discord.py`
- Modify: `board/dream.py` (`notify`, subcommands `file` and `revert`), `board/discord_controls.py` (lines 160-166), `bin/tmux-ctl`
- Test: `board/tests/test_dream_actions.py`, `board/tests/test_dream_discord.py`, `board/tests/test_discord_controls.py`, `tools/tests/test_ctl_dream.zsh`

**Acceptance Criteria:**
- [ ] After an `ok` run with any count, proposal or contradiction above zero, and a home channel: exactly one changes op with G11's keys and values (text, tier `progress`, key, absolute `files`, buttons, File proposals only when k > 0); `discord_feed._check` accepts it; `out/run.json` records `posted: true`. With `ok — no changes`, with `--dry-run`, or with no channel: no op, and `dream-report` still prints the report
- [ ] Contradictions add the `decision`-tier op with both entries quoted; none without contradictions
- [ ] `failures` reaching 3 writes the critical op once; the 1st, 2nd and 4th failure write none
- [ ] `dream_actions.revert(project, run)`, under `context.locked`: restores both backups of that run, re-appends to the restored core every entry line of the live core that is not in `out/core.after.md` (in its section), saves the pre-revert files as `D/backups/<p>.md.<run>.pre-revert` and `…archive.md.<run>.pre-revert`, sets `reverted` in `<p>.dream.json`, clears `sources_digest` so the next night runs again, returns `reverted`
- [ ] Double tap and repeat: a second `revert` of the same run returns `already reverted` and changes no byte; an entry added between the two taps is still there
- [ ] Out of order: reverting run A after a later run B committed returns `stale: newer run <B>` and changes no byte; reverting a run whose backups were pruned or never existed returns `unknown`
- [ ] Concurrency: clicks of one project are consumed one at a time under the controls-state `flock`; `revert` and the nightly commit exclude each other and `context add` through the context lock (a test holds the lock from a subprocess and sees `revert` wait, then act); a revert that lands while a run is in its model step makes that run fail as `files changed during the run`
- [ ] `dream_actions.file_proposals(project, run=None)` (default: the last run) files each proposal once: `idea` through `ideas.add(project, text, detail="evidence: …")`, `observer` by running the script of S10 and writing the body into the path it prints; the id `sha1(kind + "\0" + text)[:12]` is appended to `D/dream/<p>/filed.json` after each success, so a second call returns `already filed`, a crash halfway never refiles, and the same proposal from a later night is not filed twice; at most 20 per call; returns `filed <n>` (plus `, skipped <m> observer (no task-observer script)` when S10's script is missing, those staying unfiled) or `no proposals`
- [ ] The observer subprocess has a 10 s timeout and the handler does no network call, so one click costs at most 20 short subprocesses inside the board's overview tick; Discord's 3 s interaction deadline is met by the bridge's `deferUpdate` before the event file is written
- [ ] `discord_controls.consume_events` routes a `click` whose `custom_id` starts `ab:dream:` to `dream_discord.click(project, user, cid, now)` for an allowlisted user and audits its result; another user is audited `rejected` and nothing runs; a click for another project's id is `ignored`; a malformed id is `unknown`; the event file is removed in every case
- [ ] Each acting click writes its result post (G11): `↩️ memory run <run> reverted` or `📌 filed <n> proposals`; a tap that did nothing writes no post
- [ ] `tmux-ctl context dream-file [<p>]` and `tmux-ctl context dream-revert <p> <run>` print the same results and work with `TMUX` unset when the project is given

**Verify:** `python3 -m unittest board.tests.test_dream_actions board.tests.test_dream_discord board.tests.test_discord_controls && zsh tools/tests/test_ctl_dream.zsh` → `OK` and `ALL PASS`

**Steps:**

- [ ] **Step 1: Failing tests.** `board/tests/test_dream_actions.py` builds its state by running `dream.run_project` with the fake (`good`, then again for run B with a patched `now` one minute later), so revert is tested on what a real run leaves. Guard tests and their mutations:
  - `test_second_revert_changes_nothing`: file hashes equal between tap one and tap two, with an add in between asserted present. Mutation: remove the `reverted` check → the add is lost and the hashes differ.
  - `test_revert_of_older_run_is_stale`. Mutation: compare nothing with `dream.json.run` → run B's core is overwritten.
  - `test_revert_keeps_entries_added_since`. Mutation: restore without re-appending → fails.
  - `test_revert_waits_for_the_lock` (subprocess holder). Mutation: write outside `context.locked` → the restore happens while the lock is held (the test checks the file is unchanged during the hold).
  - `test_file_each_once` / `test_file_same_proposal_next_night_once` / `test_file_resumes_after_crash` (patch `ideas.add` to raise on the second call; a retry files only the rest). Mutation: write `filed.json` once at the end → the first idea is filed twice.
  - `test_observer_script_missing_leaves_unfiled`; `test_observer_note_written` (a fake `new-observation.sh` in a temp dir named by `TC_OBSERVER_SCRIPT` that creates and prints a path).
  `board/tests/test_dream_discord.py`: op shapes by equality with G11 for a fixed project and run; `test_no_file_button_without_proposals`; `test_long_custom_id_drops_buttons`; `test_critical_only_at_three`; `test_click_wrong_project_ignored`; `test_click_results_are_posts_not_edits` (no op with `"op": "edit"` in the outbox; the outbox is asserted non-empty). In `board/tests/test_discord_controls.py`: an `ab:dream:revert:…` click event from an allowlisted and a non-allowlisted user, audit lines asserted, following the `ab:ideas:` click tests of `board/tests/test_discord_ideas_wiring.py` (an event file in `<dir>/events`, `access.json` with `allowFrom`, then `discord_controls.consume_events`).
- [ ] **Step 2: Run, see them fail** (`ModuleNotFoundError` for the two new modules; the controls test fails on the audit result `ignored`).
- [ ] **Step 3: Implement.** `dream_discord.py` follows the structure of `board/discord_ideas.py` (`CID_RE`, a `click` function returning the audit string, ops validated with `discord_feed._check` before any is written). Differences from `discord_ideas` that change behaviour, all of them: (1) the outbox dir is always `tc_env.discord_dir(project)`, never the ops dir; (2) results are `post` ops, not `edit` ops (S9); (3) there is no request file and no separate state lock: the state is `<p>.dream.json` and `filed.json`, guarded by the context lock inside `dream_actions`; (4) `click` takes the consuming project and refuses an id for another project. In `discord_controls.consume_events` add, before the `ab:ideas:` branch (line 162), a branch for `kind == "click"` with a `custom_id` starting `ab:dream:` that audits `dream_discord.click(project, user, cid, time.time()) if user in allow else "rejected"`; import `dream_discord` at the top with the other board imports. `dream.notify(result)` calls `dream_discord.post_run(...)` and `dream_discord.post_failure(...)`; an exception there is printed to stderr and never fails the run. The ops-bot consumer (`discord_ops._click`) is not touched: the post goes to the project's channel, so its clicks arrive in the project's events dir.
- [ ] **Step 4: `bin/tmux-ctl`.** Extend Task 4's early dispatch with `dream-file` (`dream.py file "${1:-$FEEDKEY}"`) and `dream-revert` (`dream.py revert "$1" "$2"`, both required); header comment; two checks in `tools/tests/test_ctl_dream.zsh`.
- [ ] **Step 5: Run and commit.** Verify command green; then `tmux-ctl run -t 900 tests "zsh tools/tests/all.zsh; echo rc=\$?"`. `git add` the nine files; commit `feat(board): dream post, Revert and File proposals`.

---

### Task 6: The recall hook `context-recall.sh`

**Goal:** At a session's first prompt, archive entries whose `files:` match the repo paths the prompt names are injected as additional context, at most 4096 bytes, once per session.

**Files:**
- Create: `claude/plugin/scripts/context-recall.sh` (executable)
- Create: `tools/tests/fixtures/context-recall/brief.md`
- Modify: `claude/plugin/hooks/hooks.json`, `claude/plugin/.claude-plugin/plugin.json` (description)
- Test: `tools/tests/test_context_recall.zsh`, `tools/tests/test_plugin.zsh`

**Acceptance Criteria:**
- [ ] stdin is the `UserPromptSubmit` JSON (S11's keys); the script reads `prompt`, `session_id` and `cwd`; the project key comes from the tmux pane exactly as in `context-inject.sh` lines 11-17
- [ ] Paths: every token of the prompt (split on whitespace, with surrounding quotes, backticks, brackets and trailing `.,;:)` and a trailing `:<line>` removed) that names an existing file or directory under `git -C <cwd> rev-parse --show-toplevel`, given relative to it or as an absolute path under it, and contains a `/` or a `.`; the fixture brief yields at least `claude/plugin/scripts/context-inject.sh`, `board/discord_controls.py`, `board/metrics.py`, `claude/plugin/hooks/hooks.json`, `claude/overseer-settings.json` and `board/usage.py`
- [ ] An archive entry matches when one of its `files:` paths equals a prompt path, has the same non-empty parent directory as a prompt path, or lies under a prompt path that is a directory; an entry citing only `README.md` does not match a prompt naming `CLAUDE.md` (empty parent)
- [ ] Output: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Archived project context matching the files in your task:\n<entry lines>"}}`; entries newest date first, whole entries only, their lines totalling at most 4096 bytes; with 6 KB of matching entries the output holds only the newest that fit
- [ ] Once per session: the first prompt of a `session_id` writes the marker of G13 whether or not anything matched; a second prompt of the same id prints nothing; another id runs again
- [ ] No output and exit 0 for: a prompt with no existing path (a handoff path outside the repo), no archive file, an empty archive, `TC_CONTEXT=0`, no tmux pane, garbage on stdin, a cwd that is not a git repo
- [ ] `hooks.json` gains `"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/context-recall.sh\" --scoped", "timeout": 5}]}]`; `claude plugin validate claude/plugin` still passes; `plugin.json`'s description names `context-recall`; `test_plugin.zsh` checks the registration (no matcher, `--scoped`, timeout 5), and that the script is executable (the existing "all four hooks" check already requires the `"${CLAUDE_PLUGIN_ROOT}/scripts/….sh" --scoped` form of every command)
- [ ] The fixture is aged real state: `brief.md` is the "Decided" paragraph below, and the test's archive holds entries dated on at least three different days, two of them citing the same file

**Verify:** `zsh tools/tests/test_context_recall.zsh && zsh tools/tests/test_plugin.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: The fixture.** `tools/tests/fixtures/context-recall/brief.md` is this text, a paragraph of the real brief that started this plan (keep it verbatim; the test depends on its punctuation):

```text
- Ground every task in the current code before writing it: `claude/plugin/scripts/context-inject.sh` (CAP), `tmux-ctl context` (find it in `bin/tmux-ctl` / `tools/lib/`), the Discord click routing (`board/discord_controls.py`, `board/discord_ops.py`, `board/discord_feed.py` post ops and buttons — the /ideas feature that just merged is the freshest example of `ab:<kind>:…` buttons), `tmux-ctl metrics` (`board/metrics.py`), an existing launchd install (the reboot-auto-restore `agent-board restore schedule install` is the freshest pattern), `claude/plugin/hooks/hooks.json`, the overseer's settings file `claude/overseer-settings.json` (a pattern for a restricted headless settings file), and the usage numbers `tmux-ctl awake` / usage alerts read (`board/usage.py`). Where the spec's assumptions no longer match the code (paths, names, hook formats), say so in a "Spec vs code" note in the plan header and follow the code, with a one-line ruling each.
```

- [ ] **Step 2: Failing test** `tools/tests/test_context_recall.zsh`, built like `tools/tests/test_context_inject.zsh` (same `tt_setup claude`, `TC_CONTEXT_DIR="$TT_DIR/ctx"`, a `run_hook` helper that pipes a payload and captures stdout, stderr and rc, and a `ctx` helper that extracts `additionalContext`), plus `export TC_STATE="$TT_DIR/state"` and a payload builder that JSON-encodes the prompt, a session id and `cwd="$TT_REPO"` with `python3 -c`. One `check` per acceptance criterion. Guard checks and their mutations:
  - "second prompt of the session: nothing". Mutation: never write the marker → output appears twice.
  - "marker written when nothing matched". Mutation: write the marker only on a match → a later prompt with paths injects in the same session.
  - "6 KB of matches: output entry lines ≤ 4096 bytes, and at least one entry present" (the second half keeps it from passing on empty output). Mutation: no cap → over 4096.
  - "the entry cut at the cap is absent as a whole". Mutation: cut by bytes → a partial line.
  - "top-level file does not match another top-level file". Mutation: allow the empty parent → matches.
  - "no path in the prompt: silent" checks rc 0 and empty stdout and stderr.
- [ ] **Step 3: Run, see it fail** (`no such file or directory: …/context-recall.sh`).
- [ ] **Step 4: Implement** as `context-inject.sh` is built: bash, the same kill switch and tmux key lines, then one `python3 -I - "$dir/$project.archive.md" "$state_dir" <<'PY'` block that reads the hook JSON from a variable (capture stdin with `payload=$(cat)` first and pass it in the environment, since the heredoc takes stdin), does the marker, the path extraction, the match and the cap, and prints the JSON. Differences from `context-inject.sh` that change behaviour, all of them: (1) stdin is parsed, not drained; (2) the event name is `UserPromptSubmit`; (3) the file is `<project>.archive.md`; (4) it writes a marker and so needs the state dir; (5) there is no truncation note, entries past the cap are dropped silently. The script is self-contained: a plugin script cannot import from `board/`.
- [ ] **Step 5: Register and commit.** Edit `hooks.json` and `plugin.json`, update `test_plugin.zsh`, run `claude plugin validate claude/plugin` (expect it to pass), run the Verify command. `git add` the six files; commit `feat(plugin): context-recall hook, archived context matched to the files a task names`.

---

### Task 7: The launchd job and install docs

**Goal:** `tmux-ctl context dream-schedule install|status|uninstall` manages the LaunchAgent `com.user.agent-board-dream` that runs `tmux-ctl context dream --all` at 03:30 local.

**Files:**
- Create: `board/dream_schedule.py`
- Modify: `bin/tmux-ctl`, `docs/INSTALL.md` (after the restore schedule lines 134-136)
- Test: `board/tests/test_dream_schedule.py`, `tools/tests/test_ctl_dream.zsh`

**Acceptance Criteria:**
- [ ] `plist_text(cli_path, home, log)` parses with `plistlib.loads` to exactly: `Label` `com.user.agent-board-dream`; `ProgramArguments` `[<cli_path>, "context", "dream", "--all"]`; `StartCalendarInterval` `{"Hour": 3, "Minute": 30}`; `WorkingDirectory` home; `StandardOutPath` and `StandardErrorPath` `<agent base>/dream.launchd.log`; `EnvironmentVariables` with `PATH` `<home>/.local/bin:/opt/homebrew/bin:<home>/.bun/bin:/usr/bin:/bin` and `LANG`; no `RunAtLoad`, no `StartInterval`, no `AbandonProcessGroup`
- [ ] The generated plist passes `plutil -lint` (a test, skipped off macOS)
- [ ] `install` resolves `tmux-ctl` as `~/.local/bin/tmux-ctl` when executable, else the one beside the checkout, before writing anything; backs up an existing plist to `<name>.bak-YYYYMMDD`; runs `bootout` then `bootstrap gui/<uid> <plist>` through the `DS_LAUNCHCTL` seam; a failing bootstrap exits 1 with launchctl's message
- [ ] `uninstall` boots out and removes the plist, or prints `not installed`; `status` prints `loaded` or `not loaded`, then one line per project with a `<p>.dream.json`: `<p>: last run <ISO>, failures <n>`, or `no runs yet`
- [ ] Off macOS every subcommand prints `macOS only` and exits 2
- [ ] Tests never call the real `launchctl` and never write under the real `~/Library` (`HOME` is a temp dir, `DS_LAUNCHCTL` a recording fake); the test asserts the fake was called, so it cannot pass with no call made
- [ ] `tmux-ctl context dream-schedule status` works with `TMUX` unset; `docs/INSTALL.md` documents the three commands, `TC_DREAM=0` and the `dream.off` file, and that the job runs the code of whatever branch the main checkout holds

**Verify:** `python3 -m unittest board.tests.test_dream_schedule && zsh tools/tests/test_ctl_dream.zsh` → `OK` and `ALL PASS`

**Steps:**

- [ ] **Step 1: Failing tests** in `board/tests/test_dream_schedule.py`, following `board/tests/test_restore_schedule.py` (temp `HOME`, a fake launchctl script that appends its argv to a file). Guard test: `test_no_run_at_load` asserts the three absent keys; mutation: copy `restore_schedule.plist_text` unchanged → fails.
- [ ] **Step 2: Run, see them fail** (`ModuleNotFoundError: No module named 'dream_schedule'`).
- [ ] **Step 3: Implement** by following `board/restore_schedule.py`. Differences that change behaviour, all of them: (1) `StartCalendarInterval {"Hour": 3, "Minute": 30}` replaces `RunAtLoad` and `StartInterval` (probe P3); (2) no `AbandonProcessGroup` (the job starts nothing that must outlive it); (3) the program is `tmux-ctl context dream --all`, resolved as `tools/discord_watch.py` `tmux_ctl_path` does (lines 524-531), not `agent-board`; (4) the seam variable is `DS_LAUNCHCTL`; (5) `uninstall` has no snapshot to mark; (6) `status` reads `<p>.dream.json` files instead of the restore snapshot; (7) the log is `tc_env.agent_base() / "dream.launchd.log"`. The platform check, the backup of an old plist, the bootout-then-bootstrap order and `main(cmd)`'s exit codes are the same.
- [ ] **Step 4: `bin/tmux-ctl` and docs.** Extend the early dispatch with `dream-schedule` (`python3 -I -c` is not needed: `dream_schedule.py` gets an `if __name__ == "__main__": sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))` and the `sys.path` insert); header comment; one check in `test_ctl_dream.zsh` with `DS_LAUNCHCTL` set to a fake and `HOME` to a temp dir; the INSTALL section.
- [ ] **Step 5: Run and commit.** Verify command green; then the whole-repo verdict `tmux-ctl run -t 900 tests "zsh tools/tests/all.zsh; echo rc=\$?"`, read from the runner's own summary line. `git add` the five files; commit `feat(board): launchd schedule for the nightly memory run`.

---

### Task 8: User gate, one real run on a copy

**Goal:** After the merge, one real `claude -p` consolidation of a copy of `~/.local/state/agent-board/context` passes `dream_check.py verify` with a core of at most 8192 bytes, the real context dir is byte-identical afterwards, the gate probe prints `GATE OK`, and the user has read the diff.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- none (runs the merged code; writes only under a temp dir, plus one `dream` line in `docs/superpowers/metrics/runs.jsonl` and, with the user's yes, the LaunchAgent plist)

**Acceptance Criteria:**
- [ ] Before: `G=$(mktemp -d)`; `cp -R ~/.local/state/agent-board/context "$G/ctx"`; `find ~/.local/state/agent-board/context -type f -exec shasum {} + | sort > "$G/before.sha"` lists at least 4 files
- [ ] `TC_CONTEXT_DIR="$G/ctx" TC_STATE="$G/state" tmux-ctl context dream agent-board --force` (real `claude`, Sonnet, medium effort; the copy has no `dream.json`, so every ledger is an input; the temp `TC_STATE` has no Discord channel, so nothing is posted for a run on a copy) prints `dream: agent-board ok — merged <n>, archived <n>, …` and exits 0 within 15 minutes
- [ ] `wc -c < "$G/ctx/agent-board.md"` is at most 8192, and `python3 -I board/dream_check.py verify --old-core ~/.local/state/agent-board/context/agent-board.md --old-archive /dev/null --new-core "$G/ctx/agent-board.md" --new-archive "$G/ctx/agent-board.archive.md" --report "$G"/ctx/dream/agent-board/*/out/report.json --root ~/agent-board` prints `ok`
- [ ] The same `find … shasum` listing after the run equals `"$G/before.sha"` (`diff` prints nothing): the real context dir was not touched
- [ ] `zsh tools/tests/check_real_dream_gate.zsh` prints `checked 11 attempts` and `GATE OK`
- [ ] `tail -1 ~/agent-board/docs/superpowers/metrics/runs.jsonl` is a `"kind": "dream"` line with `cost_usd` above 0; the cost is reported to the user
- [ ] The user has opened `"$G"/ctx/dream/agent-board/*/out/diff.txt` and the new core, and said the core reads right, or named what is wrong (which reopens Task 3's prompt)
- [ ] With the user's yes: `tmux-ctl context dream-schedule install`, then `tmux-ctl context dream-schedule status` prints `loaded`

**Verify:** `zsh tools/tests/check_real_dream_gate.zsh; tmux-ctl context dream-schedule status` → `checked 11 attempts`, `GATE OK`, `loaded`

**Steps:** run the criteria in order from the main checkout after the merge, capture every command's output, show the user the summary line, the cost, the diff path and the new core's size, and wait for the user's answer before the install and before closing.

---

### Task 9: User gate, the post and buttons on the phone

**Goal:** After the first real run on the real context dir, the user sees the `🌙 memory:` post with `diff.txt` in the project's Discord channel, a tap on File proposals files each proposal once, and a tap on Revert restores the pre-run core, with audit lines `filed <n>`, `reverted` and `already reverted`.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- none (real state: the real context dir, the project's Discord channel, the ideas file)

**Acceptance Criteria:**
- [ ] A real run on the real dir happened (the 03:30 job, or `tmux-ctl context dream agent-board --force` with the user's yes) and `wc -c < ~/.local/state/agent-board/context/agent-board.md` is at most 8192
- [ ] The user confirms on the phone: one post starting `🌙 memory: merged`, with `diff.txt` attached and the buttons Revert and File proposals (the second only if the run had proposals)
- [ ] The user taps File proposals: a post `📌 filed <n> proposals` appears, the ideas file or the observer log gained n entries, and a second tap adds nothing (`already filed` in the audit log)
- [ ] The user taps Revert: a post `↩️ memory run <run> reverted` appears; `cmp` of the core with `~/.local/state/agent-board/context/backups/agent-board.md.<run>` shows no difference except entries added since the run; a second tap changes nothing (`already reverted` in the audit log)
- [ ] `tail -8 ~/.local/state/agent-board/discord/agent-board/audit.jsonl` shows the four click lines with the user's id and those results
- [ ] A new session started after the next successful run gets a core that ends without the `… truncated, full file at` line
- [ ] Recall on a real teammate (the point "Probes" left open): once the real archive exists, the lead starts a teammate whose brief names `board/usage.py` and asks it whether its context holds `Archived project context matching the files in your task:`; the answer, yes or no, is recorded, and a no becomes a follow-up for the lead, not a silent pass

**Verify:** `tail -8 ~/.local/state/agent-board/discord/agent-board/audit.jsonl; wc -c ~/.local/state/agent-board/context/agent-board.md ~/.local/state/agent-board/context/agent-board.archive.md` → the click lines `filed <n>`, `already filed`, `reverted`, `already reverted`, and both byte counts

**Steps:** the lead tells the user what to tap and in which order (File proposals, File proposals again, Revert, Revert again), reads the audit log and the files after each tap, and reports each result with its output. The Revert leaves the memory uncondensed until the next night, which re-runs because `revert` clears the digest.

---

## Self-review (author)

- Spec coverage: §1 Files → G1, Tasks 1, 4. §2 nightly run → Tasks 2, 3, 4, 7 (kill switches, digest and usage skips, model step, inputs, the six model steps, the three checks, `dream-file`, the metrics line). §3 Discord → Task 5, G11. §4 recall → Task 6 (hook), Task 1 (search and the rule lines). Error handling → Task 4 (failure, timeout, not advanced), Task 5 (critical at three), Task 1 (lock, 5 s), Task 4 (`dream-report`). Testing → each bullet has a named test; the real run and the phone are Tasks 8 and 9.
- Every guard test names its mutation; the snippets in Tasks 1, 2 and 4 were run once in zsh and Python by the author; every external value cites probe P1, P2 or P3.
- Task 3 is `frontier` and has no Steps block. Tasks 5 and 6 answer the delivery questions (double tap, repeat, out of order, concurrency, deadline). Tasks 5, 6 and 7 name every difference from the component they follow.
