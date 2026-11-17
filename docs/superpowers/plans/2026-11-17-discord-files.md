# Discord files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Files go out to Discord (the morning report, a failed spec's test log, any file on request, a PNG of the board) and images the user sends come in to the lead.

**Architecture:** Everything outbound is an outbox `post` op with `files: [abs paths]`, which the node bridge already passes to discord.js. This plan adds the bridge's limits (10 files, 25 MB, missing file) and a cleanup flag for temporary files, the feed's two automatic attachments, and two CLI verbs (`tmux-ctl discord send`, `snap`) that write the op. Inbound images need only lead rules: the Discord plugin already delivers and downloads attachments.

**Tech Stack:** zsh (`tools/lib/discord.zsh`, `bin/tmux-ctl`), Python 3 (`board/discord_feed.py`, new `board/discord_send.py`, unittest), node (`tools/discord-bridge`, `node --test`), headless Google Chrome.

**Spec:** `docs/superpowers/specs/2026-11-11-discord-files-design.md`

## Global Constraints

- Bridge limits (spec §1): at most **10** files per post, each at most **25 MB** (`25 * 1024 * 1024` bytes). A bigger file is not attached and the post text gains the line `<name> too large (<size>)`, where `<name>` is the basename and `<size>` is a human size like `31.2 MB`.
- Op shape stays the one `board/discord_feed.py:_check` validates: `post` = `{op, text, tier, mention_user}` plus optional `thread_key`, `link_thread_key`, `files` (list of absolute paths). This plan adds one optional key, `delete_files` (bool).
- The board URL with its token is **never** in any op text, file name or log line the bridge posts (spec §1). The token lives in `~/.local/state/tmux-dash/token`; the URL is `http://127.0.0.1:${TMUX_DASH_PORT:-7700}/<token>/` (`bin/tmux-dash:21`).
- `snap` Chrome command (spec §1, verbatim): `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=<tmp>.png --window-size=1200,1600 <board url with token>`; no Chrome → exit 1 with `snap: Chrome not found`.
- `send` (spec §1): `tmux-ctl discord send [--thread <key>] <file>… [-m <text>]`; paths made absolute; each must exist and be readable, else exit 1 and no op is written.
- Failed-run log name: `<run id>.log`, the last **200** lines of the run's output file (spec §1).
- Tests never touch the real `~/.local/state/agent-board/discord/` dir, the real bot token, or the live board on :7700: scratch `TC_STATE`, scratch `HOME`, fake Chrome via `TC_CHROME`.
- Commits: conventional with scope; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- Files out: report + failed log automatically, `send` and `snap` on request (spec §1, decided over Discord 2026-11-11).
- Images in: downloaded and Read before answering; nothing copied into the repo unless asked (spec §2).
- Voice notes are out of scope (dropped by the user).
- Queue integration for this spec: merge locally, no push (queue metadata, answered 2026-11-11T17:29:55Z).

**Lead rulings (planning, 2026-11-17):**
- **P1 — failed log goes in the spec thread as its own post.** The code posts a failed outcome to the home channel (critical, `mention_user`, `link_thread_key`), not into the thread (`board/discord_feed.py:384-392`). The spec says "attached to the spec thread's `failed — …` post". Ruling: keep the home post unchanged, and add one `progress` post into the spec thread (`thread_key` = the spec's key), text `failed run log: <cmd> (exit <n>)`, carrying the log, emitted before the `archive` op. Cost if wrong: the log is one tap away from the home alert instead of on it.
- **P2 — which run is "its failing test run".** Run records (`$TC_STATE_DIR/runs-<project>.jsonl`, written by `bin/tmux-ctl:198-204`) carry no spec field. Ruling: the newest record with `exit` not null and not 0, `cwd` containing `/.claude/worktrees/`, and `ts` within the 24 h before the outcome event. None found → the thread post says `failed — no failing test run recorded` with no file. Cost if wrong: a log from another worktree's run is attached; the post names its command, so the user sees which run it is.
- **P3 — report path.** The `report_written` event carries the basename only (`file=name`). Ruling: `derive` adds `path=<absolute path>` to its refs, and `ops_for_events` attaches `[refs["path"]]`. Old events without `path` post without a file.
- **P4 — temp cleanup.** The bridge has no ack. Ruling: `snap` writes its PNG under `<discord dir>/tmp/` and its op carries `delete_files: true`; after a **successful** send the bridge unlinks each listed file that resolves inside `<dir>/tmp/` and nothing else (a path outside is left alone and logged). A failed send leaves the PNG for the failed/ op. Cost if wrong: a PNG lingers in `tmp/` (no leak: the dir is the user's own state).
- **P5 — missing file at send time.** Ruling: the bridge drops it and adds the line `<name> not found` (the post itself still goes). Over 10 files: the first 10 go, then the line `<k> more files not sent (10 max)`.
- **P6 — `send` writes through Python.** The shell has no outbox writer. Ruling: a small CLI `board/discord_send.py` builds the op and calls `discord_feed.outbox_write` (which runs `_check`), so the shell never writes JSON by hand. `snap` adds `--virtual-time-budget=5000` after `--headless=new`, because the overview page is a JS app that polls its API and a screenshot taken at load is blank; Task 5 checks a real PNG is not blank.

---

### Task 1: Bridge: file limits, missing files, temp cleanup

**Goal:** `opPost` enforces 10 files / 25 MB with the spec's lines, drops missing files with a line, and deletes `delete_files` temp files under `<dir>/tmp/` after a successful send.

**Files:**
- Modify: `tools/discord-bridge/bridge.js` (`opPost`, ~:131-153)
- Modify: `tools/discord-bridge/test/bridge.test.js` (the files test at ~:248-256 uses a non-existent `/tmp/a.txt`; switch it to real temp files)
- Modify: `tools/discord-bridge/README.md` (op table: `files` limits and `delete_files`)

**Acceptance Criteria:**
- [ ] A post with 2 real small files sends both paths in `payload.files`.
- [ ] A file over 25 MB is not in `payload.files`, and `payload.content` contains `<name> too large (<size>)` (size like `26.0 MB`). Use a sparse file (`fs.truncateSync(p, 26*1024*1024)`), not 26 MB of data.
- [ ] A missing path is not in `payload.files` and the content has `<name> not found`; the op is still removed (sent), not moved to failed/.
- [ ] 12 files → the first 10 attached, content has `2 more files not sent (10 max)`.
- [ ] Content stays ≤ 2000 chars with the added lines (lines are appended before the existing slice).
- [ ] `delete_files: true` with a file in `<dir>/tmp/` → the file is gone after a successful send; a file outside `<dir>/tmp/` (also listed) is kept and a log line names it; a send that fails (fake client `failNext('send', {status: 400})`) keeps the tmp file.
- [ ] Guard tests name their mutation: remove the size check → the oversize test fails; remove the `tmp/` containment check → the outside-file test fails.

**Verify:** `cd tools/discord-bridge && node --test` → all pass, 0 fail

**Steps:**

- [ ] **Step 1: Write the failing tests** in `test/bridge.test.js`, using the existing harness `s` (`s.put(post(...))`, `s.client.callsOf('send')`, `s.failed()`), with files made in a fresh `fs.mkdtempSync` dir and `<s.dir>/tmp/` for the cleanup cases.
- [ ] **Step 2: Run** `node --test` → the new tests fail for the missing behaviour (not for a harness error).
- [ ] **Step 3: Implement** in `opPost`, before `payload.content` is sliced:

```js
const MAX_FILES = 10, MAX_BYTES = 25 * 1024 * 1024;
function fmtSize(n) { return (n / (1024 * 1024)).toFixed(1) + ' MB'; }
function pickFiles(paths) {
  const ok = [], notes = [];
  for (const p of paths.slice(0, MAX_FILES)) {
    let st; try { st = fs.statSync(p); } catch { notes.push(`${path.basename(p)} not found`); continue; }
    if (st.size > MAX_BYTES) notes.push(`${path.basename(p)} too large (${fmtSize(st.size)})`);
    else ok.push(p);
  }
  if (paths.length > MAX_FILES) notes.push(`${paths.length - MAX_FILES} more files not sent (${MAX_FILES} max)`);
  return { ok, notes };
}
```

  After `await target.send(payload)` succeeds and `op.delete_files === true`: for each of `op.files`, `const r = path.resolve(p)`; unlink only when `r.startsWith(path.join(dir, 'tmp') + path.sep)`, else log `delete_files: kept <r> (outside tmp/)`. Use the bridge's existing `dir`/log helpers (read how `opPost` gets them).
- [ ] **Step 4: Run** `node --test` → all pass; run the two named mutations and paste each failing test.
- [ ] **Step 5: Update** README's op table; **commit** `feat(discord): bridge file limits and temp cleanup` (stage only the three files).

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/README.md"], "verifyCommand": "cd tools/discord-bridge && node --test", "acceptanceCriteria": ["2 small files attached", "oversize replaced by '<name> too large (<size>)'", "missing file dropped with '<name> not found', op still sent", "12 files: 10 sent + 'more files not sent' line", "content <= 2000 chars", "delete_files deletes only under <dir>/tmp/ after success; kept on failure", "guard tests name their mutations"], "modelTier": "standard"}
```

---

### Task 2: Feed: report and failed-run log attachments, `delete_files` key

**Goal:** The morning report post carries the report file; a failed spec gets a thread post with the last 200 lines of its failing run as `<run id>.log`; `_check` accepts `delete_files`.

**Files:**
- Modify: `board/discord_feed.py` (`_POST_OPT` :21, `derive` :357-366, `ops_for_events` :373-400)
- Test: `board/tests/test_discord_feed.py`

**Acceptance Criteria:**
- [ ] `_POST_OPT` gains `"delete_files": bool`; `outbox_write` accepts a post with `delete_files: True` and rejects `delete_files: "yes"` (ValueError).
- [ ] P3: `derive` puts `path=<abs report path>` in the `report_written` refs; `ops_for_events` gives the report post `files: [path]` (home channel, no `thread_key`, as now). An event without `path` → a post without `files` (test it).
- [ ] P1/P2: for a completed `Plan & run` task whose outcome starts with `failed`, with a run record fixture in a scratch `TC_STATE` (`runs-proj.jsonl`: one start record `exit: null` and the final record `exit: 1` with the same `id`, `cwd` under `/x/.claude/worktrees/w`, `ts` 1 h before now, `log` pointing at a 300-line fixture file):
  - `derive` writes `<discord dir>/attachments/<id>.log` holding exactly the last 200 lines of the log;
  - the ops are, in order: the home critical post (unchanged), a post `{"op":"post","text":"failed run log: <cmd> (exit 1)","tier":"progress","mention_user":false,"thread_key":<rid>,"files":[<attachments path>]}`, then the `archive` op.
- [ ] Records that must not be picked (one test each): `exit: 0`; `exit: null` only; `cwd` outside `/.claude/worktrees/`; `ts` older than 24 h; a missing `log` file. Each → the thread post text `failed — no failing test run recorded` and no `files`.
- [ ] The newest of two qualifying records wins.
- [ ] `<discord dir>/attachments/` keeps at most 20 files (oldest removed).
- [ ] A successful (`merged …`) outcome adds no log post.
- [ ] Guard tests name their mutation: drop the `exit != 0` filter → the `exit: 0` test fails; drop the cwd filter → the outside-cwd test fails.
- [ ] The existing discord test modules still pass.

**Verify:** `python3 -m unittest board.tests.test_discord_feed board.tests.test_discord_wiring board.tests.test_discord_controls` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** with the module's `Base` fixture (`TC_STATE` patched to a tempdir, `self.root` temp repo, the report fixture at `docs/superpowers/reports/2026-11-16-queue.md`, lead tasks as dicts with `metadata.outcome = "failed — tests red"`). Read the existing report test (~:459) and failed-outcome tests (~:450, ~:593) first and follow them.
- [ ] **Step 2: Run** the Verify command → the new tests fail for the missing behaviour.
- [ ] **Step 3: Implement.** Run records live at `tc_env.state_dir() / f"runs-{project}.jsonl"`; `ts` is epoch seconds (int); records with the same `id` appear twice (start, final) — use the last one per `id`. Sketch:

```python
def _failed_run_log(project, now):
    recs = {}
    f = tc_env.state_dir() / f"runs-{project}.jsonl"
    for line in (f.read_text(errors="replace").splitlines() if f.is_file() else []):
        try: r = json.loads(line)
        except ValueError: continue
        if isinstance(r, dict) and r.get("id"): recs[r["id"]] = r
    ok = [r for r in recs.values()
          if r.get("exit") not in (None, 0) and "/.claude/worktrees/" in str(r.get("cwd", ""))
          and isinstance(r.get("ts"), (int, float)) and now - 86400 <= r["ts"] <= now
          and os.path.isfile(str(r.get("log", "")))]
    if not ok: return None
    r = max(ok, key=lambda r: r["ts"])
    ...  # write the last 200 lines to tc_env.discord_dir(project)/"attachments"/f"{r['id']}.log", prune to 20
    return {"log_file": str(dest), "cmd": r.get("cmd", ""), "exit": r["exit"]}
```

  `derive` calls it only when it emits a new failed `spec_outcome` (inside the `emit` key's first time, not on replay) and puts the result's keys into the event refs. `now` is the epoch-seconds value `derive(project, root, lead_tasks, state, now, …)` already receives (`board/discord_feed.py:292`).
- [ ] **Step 4: Run** the Verify command → OK; run the named mutations and paste each failure; run `python3 -m unittest discover -s board/tests` once (background it; > 120 s) and paste `Ran N tests` / `OK`.
- [ ] **Step 5: Commit** `feat(discord): feed attaches the queue report and a failed run's log`.

```json:metadata
{"files": ["board/discord_feed.py", "board/tests/test_discord_feed.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_feed board.tests.test_discord_wiring board.tests.test_discord_controls", "acceptanceCriteria": ["delete_files bool accepted, non-bool rejected", "report post carries files [abs path]; no path -> no files", "failed outcome: attachments/<id>.log = last 200 lines; ops home post, thread log post, archive", "non-qualifying records -> 'failed — no failing test run recorded', no files", "newest qualifying record wins", "attachments dir capped at 20", "merged outcome adds no log post", "guard tests name their mutations"], "modelTier": "standard"}
```

---

### Task 3: `tmux-ctl discord send` and `snap`

**Goal:** `send` writes a post op with absolute, checked paths; `snap` screenshots the board with headless Chrome into `<dir>/tmp/` and sends it with `delete_files`, never exposing the token.

**Files:**
- Create: `board/discord_send.py` (CLI: builds the op, calls `discord_feed.outbox_write`)
- Modify: `tools/lib/discord.zsh` (`_dc_usage` :10, `discord_cmd` :14-77: early branch for `send`/`snap` before the one-positional check at :41 and `_dc_tokenish`)
- Modify: `bin/tmux-ctl` (header usage comment :44-46)
- Test: `tools/tests/test_ctl_discord_send.zsh` (new; follow `tools/tests/test_ctl_discord.zsh`'s harness)

**Acceptance Criteria:**
- [ ] `tmux-ctl discord send a.txt sub/b.log -m "here" --project tt` (relative paths) → exactly one op in `$TC_STATE/discord/tt/outbox/`, `files` = the two absolute paths, `text` = `here`, `tier` = `progress`, `mention_user` = false, exit 0, stdout `send: 1 post, 2 files`.
- [ ] No `-m` → text is the basenames joined by `, `.
- [ ] `--thread k1` → `thread_key: "k1"`.
- [ ] A missing file, a directory, or an unreadable file (`chmod 000`) → exit 1, `send: <path>: not found` / `not a file` / `not readable`, and **no** op (count the outbox before and after).
- [ ] No files → usage, exit 2. More than 10 files → exit 2 `send: at most 10 files`.
- [ ] A path containing a dot and ≥ 50 chars is accepted (not rejected as token-ish).
- [ ] `snap` with `TC_CHROME` pointing at a fake chrome script (writes a 1x1 PNG to the `--screenshot=` path and records its argv to a file) and a fake token file `$HOME/.local/state/tmux-dash/token` containing `SECRETTOKEN123`:
  - the fake's argv has `--headless=new`, `--virtual-time-budget=5000`, `--window-size=1200,1600`, `--screenshot=<dir>/tmp/snap-*.png` and the URL `http://127.0.0.1:7700/SECRETTOKEN123/`;
  - one op: `files` = that PNG, `delete_files: true`, text `board snapshot <HH:MM>`;
  - `grep -c SECRETTOKEN123` over every file under `$TC_STATE/discord/tt/` (count printed) = 0, and over the command's stdout+stderr = 0.
- [ ] `snap` with `TC_CHROME` set to a non-existent path → exit 1, `snap: Chrome not found`, no op. Without `TC_CHROME` the default is the spec's absolute Chrome path.
- [ ] `snap` when the fake chrome writes no PNG → exit 1 `snap: no screenshot`, no op.
- [ ] Usage line and the `bin/tmux-ctl` header list `send [--thread <key>] <file>… [-m <text>]` and `snap [<project>]`.
- [ ] Guard tests name their mutation: skip the readable check → the `chmod 000` test fails; put the URL in the op text → the token-count test fails.

**Verify:** `zsh tools/tests/test_ctl_discord_send.zsh; echo rc=$?` → `rc=0` and no `FAIL` line

**Steps:**

- [ ] **Step 1:** `board/discord_send.py`:

```python
#!/usr/bin/env python3
"""discord_send.py <project> <thread_key|-> <delete 0|1> <text> <abs file>...: write one post op."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_feed, tc_env

def main(argv):
    project, thread, delete, text, files = argv[0], argv[1], argv[2] == "1", argv[3], argv[4:]
    op = {"op": "post", "text": text, "tier": "progress", "mention_user": False, "files": files}
    if thread != "-": op["thread_key"] = thread
    if delete: op["delete_files"] = True
    discord_feed.outbox_write(tc_env.discord_dir(project), op)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

  (`outbox_write(dir, op)` takes the discord dir and appends `outbox/` itself: `board/discord_feed.py:95-98`.)
- [ ] **Step 2: Write the failing zsh tests** (harness: `source "${0:A:h}/lib.zsh"`, `tt_setup claude`, scratch `HOME`, fakes in `$S/bin`, `check`/`run` helpers, `trap 'cleanup; tt_teardown' EXIT`). Run → they fail with usage (exit 2), not a harness error.
- [ ] **Step 3: Implement** in `discord.zsh`: an early `send|snap` branch that parses `--thread`, `-m`, `--project` itself and collects files, resolves each with `${f:A}`, checks `-e` / `-f` / `-r` before writing anything, then calls `python3 -I "${0:A:h:h}/board/discord_send.py" …` (resolve the repo root the way the file already does for other helpers). `snap`: `chrome=${TC_CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}`; `[[ -x $chrome ]] || { print -u2 "snap: Chrome not found"; return 1 }`; token from `$HOME/.local/state/tmux-dash/token`, port `${TMUX_DASH_PORT:-7700}`; PNG `$dir/tmp/snap-$(date +%s)-$$.png` (`mkdir -p`); run Chrome with its stdout/stderr to `/dev/null` (Chrome may echo the URL); `[[ -s $png ]] || { print -u2 "snap: no screenshot"; return 1 }`; then the send path with delete `1`. Never echo the URL.
- [ ] **Step 4: Run** the Verify command → rc=0; run the named mutations and paste each failure; run `zsh tools/tests/test_ctl_discord.zsh; echo rc=$?` (the existing discord CLI suite) → rc=0.
- [ ] **Step 5: Commit** `feat(tmux-ctl): discord send and snap`.

```json:metadata
{"files": ["board/discord_send.py", "tools/lib/discord.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_discord_send.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord_send.zsh; echo rc=$?", "acceptanceCriteria": ["send writes one op with absolute files, text, tier progress", "default text = basenames", "--thread passes thread_key", "missing/dir/unreadable -> exit 1, no op", "no files usage exit 2; >10 files exit 2", "long dotted path accepted", "snap: fake chrome argv, op with delete_files, token count 0 in state and output", "snap no chrome -> exit 1 'snap: Chrome not found'", "snap no PNG -> exit 1", "usage lines updated", "guard tests name their mutations"], "modelTier": "standard"}
```

---

### Task 4: Lead rules and docs

**Goal:** The lead knows to use `send`/`snap` for file requests from Discord and to download and Read images the user sends.

**Files:**
- Modify: `claude/orchestrator.md` (§ Remote: Discord, the "While remote:" bullets ~:247-258)
- Modify: `docs/INSTALL.md` (the Discord section: one paragraph on `send`/`snap` and the Chrome requirement)

**Acceptance Criteria:**
- [ ] A new bullet after the bullet that ends "post them yourself as before." (~:252), verbatim: `- When the user asks for a file, a report, a log or a picture of the board from Discord, use \`tmux-ctl discord send\` or \`snap\`.`
- [ ] A new bullet after the AskUserQuestion bullet (~:253-254), verbatim: `- An image the user sends (\`attachment_count\` on the channel tag) is downloaded with \`download_attachment\` and Read before answering. For a bug report it goes to \`systematic-debugging\` like any other bug, and the reply cites the downloaded path. The file stays in the plugin's inbox dir; nothing is copied into the repo unless the user asks.`
- [ ] INSTALL names `tmux-ctl discord send [--thread <key>] <file>… [-m <text>]`, `snap`, that `snap` needs Google Chrome at the standard path (or `TC_CHROME`), and the bridge limits (10 files, 25 MB).
- [ ] The edit is applied from a generated diff that passes `patch --dry-run` (the file is the live lead rules once merged).

**Verify:** `grep -c 'tmux-ctl discord send' claude/orchestrator.md docs/INSTALL.md && grep -c 'download_attachment' claude/orchestrator.md` → each count ≥ 1

**Steps:**

- [ ] **Step 1:** Copy `claude/orchestrator.md` to the scratchpad, insert the two bullets there, generate `diff -u live copy > p.diff`, `patch --dry-run claude/orchestrator.md < p.diff`, then apply it.
- [ ] **Step 2:** Edit `docs/INSTALL.md`.
- [ ] **Step 3:** Run the Verify command; **commit** `docs(discord): send, snap and image rules`.

```json:metadata
{"files": ["claude/orchestrator.md", "docs/INSTALL.md"], "verifyCommand": "grep -c 'tmux-ctl discord send' claude/orchestrator.md docs/INSTALL.md && grep -c 'download_attachment' claude/orchestrator.md", "acceptanceCriteria": ["send/snap bullet verbatim after the bridge bullet", "image bullet verbatim after the AskUserQuestion bullet", "INSTALL documents send, snap, Chrome, limits", "patch dry-run before applying"], "modelTier": "mechanical"}
```

---

### Task 5: Real-state end-to-end (scratch outputs)

**Goal:** The whole outbound path runs once against real state: the real run log and real reports, real Chrome against a board served from this worktree, and the real bridge on its fake client. The real Discord dir stays untouched, and the results are in a note.

**Files:**
- Create: `docs/superpowers/notes/2026-11-17-discord-files-e2e.md`

**Acceptance Criteria:**
- [ ] Read-only against the real run log: `_failed_run_log("agent-board", now)` with `TC_STATE_DIR` pointing at the real state dir **read-only** (copy `runs-agent-board.jsonl` into a scratch dir first and point `TC_STATE` there, so the attachments write goes to scratch). The note pastes which record it picks (id, cmd, exit) or that none qualified, and the line count of the written log (≤ 200).
- [ ] The real newest `docs/superpowers/reports/*-queue.md` in the main checkout (read-only) goes through `derive` + `ops_for_events` with a scratch `TC_STATE`: the note pastes the report op, whose `files` is that file's absolute path.
- [ ] Real Chrome: a board started from this worktree on a scratch port (`TMUX_DASH_PORT=7712`, scratch `TMUX_DASH_TOKEN`, `python3 board/server.py`), then `TMUX_DASH_PORT=7712 tmux-ctl discord snap` with a scratch `HOME` whose token file holds the scratch token and a scratch `TC_STATE`. The PNG exists, is at least 20 KB (a blank page is smaller; paste its size), and the lead can Read it and see the board. The note pastes the op and `grep -c <scratch token>` = 0 over the scratch discord dir. Stop the scratch board afterwards (paste that the port is free).
- [ ] The node bridge with the fake client drains that scratch outbox: the report post and the snap post are sent with their files, the snap PNG is deleted afterwards, and `failed/` is empty.
- [ ] `tmux-ctl discord send` of a 26 MB sparse file through the bridge with the fake client gives the `too large` line.
- [ ] The real `~/.local/state/agent-board/discord/agent-board/` dir: checksums before and after with the file count (`find … -type f | sort | xargs md5 -q | md5 -q`). The live bridge may write there meanwhile; any difference is explained file by file (live bridge log lines, live outbox ops), with per-file before/after md5 lines.

**Verify:** `test -s docs/superpowers/notes/2026-11-17-discord-files-e2e.md && grep -c 'too large' docs/superpowers/notes/2026-11-17-discord-files-e2e.md && grep -c 'snap' docs/superpowers/notes/2026-11-17-discord-files-e2e.md`

**Steps:**

- [ ] **Step 1:** Record the before-checksums of the real discord dir (per file and total, with the count).
- [ ] **Step 2:** Run the checks with harness scripts in your scratchpad. Never use the live board on :7700, never the real bot token, never write under the real state dirs.
- [ ] **Step 3:** Record the after-checksums; write the note with each output pasted (fence any block containing ``` with ````).
- [ ] **Step 4: Commit** `docs(notes): discord files real-state e2e`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-17-discord-files-e2e.md"], "verifyCommand": "test -s docs/superpowers/notes/2026-11-17-discord-files-e2e.md && grep -c 'too large' docs/superpowers/notes/2026-11-17-discord-files-e2e.md && grep -c 'snap' docs/superpowers/notes/2026-11-17-discord-files-e2e.md", "acceptanceCriteria": ["failed-run pick on a copy of the real run log, pasted", "real report through derive/ops: files abs path", "real Chrome snap against a scratch board: PNG >= 20 KB, readable, token count 0, port freed", "bridge fake client sends report and snap with files, PNG deleted, failed empty", "26 MB send gives too large line", "real discord dir per-file checksums before/after with count"], "modelTier": "standard"}
```

---

### Task 6: User gate: a snapshot on the phone, a photo back

**Goal:** After merge, `snap` arrives in `#agent-board` on the user's phone, and a photo the user sends is described by the lead.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none

**Acceptance Criteria:**
- [ ] After merge (the live bridge runs `tools/discord-bridge` from main; restart it with `tmux-ctl discord bridge stop` / `start` after asking), `tmux-ctl discord snap` posts a PNG of the board to `#agent-board`, the user confirms it shows the board, and `ls <discord dir>/tmp/` shows the PNG gone.
- [ ] `tmux-ctl discord send docs/superpowers/specs/2026-11-11-discord-files-design.md -m "spec"` arrives as an attachment.
- [ ] The user sends a photo; the lead downloads it with `download_attachment`, Reads it, and describes it in a reply citing the downloaded path.
- [ ] snap with the real HOME while the user's Chrome is open posts within 60 s; if not, add `--user-data-dir=<dir>/tmp/chrome-profile` and re-run.
- [ ] a 15 MB send arrives (or gives the too-large line) and `failed/` stays empty — settles whether Discord's per-file limit is 10 MB or 25 MB.
- [ ] The board URL and token appear in no Discord message (the user checks the snap post text; `grep -c` of the token over `bridge.log` = 0).

**Verify:** `grep -c "$(cat ~/.local/state/tmux-dash/token)" ~/.local/state/agent-board/discord/agent-board/bridge.log` → `0`, plus the user's Discord confirmation.

```json:metadata
{"files": [], "verifyCommand": "grep -c \"$(cat ~/.local/state/tmux-dash/token)\" ~/.local/state/agent-board/discord/agent-board/bridge.log", "acceptanceCriteria": ["snap PNG arrives and shows the board; tmp PNG deleted", "send of the spec arrives as attachment", "user photo downloaded, Read and described with its path", "token in no Discord message; bridge.log token count 0", "snap with the real HOME while the user's Chrome is open posts within 60 s; if not, add `--user-data-dir=<dir>/tmp/chrome-profile` and re-run", "a 15 MB send arrives (or gives the too-large line) and `failed/` stays empty — settles whether Discord's per-file limit is 10 MB or 25 MB"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```
