# Remote access (Telegram channel per dev lead) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each project's dev lead can be reached from the user's phone through its own Telegram bot (the official `telegram@claude-plugins-official` channel plugin), including relayed teammate approvals.

**Architecture:** A per-project bot token lives in `${TC_STATE:-$HOME/.local/state/agent-board}/telegram/<project>/.env`, written by a new `tmux-ctl telegram` subcommand. `bin/claude-orchestrator` exports `TELEGRAM_STATE_DIR` (lead process only) and adds `--channels plugin:telegram@claude-plugins-official` when that token exists. A new `tmux-ctl approve` presses the one-time yes / no option of a teammate's permission prompt, verified against captured real prompt screens. The board marks a lead whose claude runs with the channel flag with a `tg` badge. Lead rules and INSTALL docs describe the remote protocol.

**Tech Stack:** zsh (`bin/tmux-ctl`, `tools/lib/*.zsh`, tests on a scratch tmux server via `tools/tests/lib.zsh`), Python 3 stdlib (`board/server.py`, unittest), vanilla JS in `board/index.html`.

**Spec:** `docs/superpowers/specs/2026-11-09-remote-access-design.md`

## Global Constraints

- **Never run the full suites** (user rule). Run only the targeted tests each task names, e.g. `zsh tools/tests/test_ctl_telegram.zsh`, never `run-all.zsh` or `unittest discover` over a whole dir.
- **No pushes.** Commit on `feat/remote-access` in the worktree `.claude/worktrees/remote-access` only. Conventional commits with scope (`feat(tmux-ctl): …`); end each commit with the attribution trailer your harness specifies.
- **The token never appears in any output**: stdout, stderr, logs, test output, commit messages. Tokens are read from stdin only, never argv.
- Telegram state dir: `${TC_STATE:-$HOME/.local/state/agent-board}/telegram/<project>/`, mode 700; `.env` mode 600 containing exactly `TELEGRAM_BOT_TOKEN=<token>`. **Not** `TC_STATE_DIR` (that defaults to `$TMPDIR`, which macOS cleans). `<project>` = `#{?session_group,#{session_group},#{session_name}}` of the current tmux session with a trailing `-bg` dropped for `@tc_bg` sessions (exactly what `bin/tmux-ctl` computes as `FEEDKEY`); outside tmux, `--project <name>` is required.
- Token shape: `^[0-9]+:[A-Za-z0-9_-]{30,}$`. Test dummy token: `123456789:AAdummydummydummydummydummydummy00` (35 chars after the colon; never a real token).
- Channel flag, verbatim: `--channels plugin:telegram@claude-plugins-official`. `TELEGRAM_STATE_DIR` is exported in the lead process only, never via `tc_tmux set-environment`.
- Kill switch: `TC_TELEGRAM=0` disables the channel opt-in in `claude-orchestrator`.
- `access.json` (plugin 0.0.7 `server.ts`): `{"dmPolicy": "pairing"|"allowlist"|"disabled", "allowFrom": ["<id>", …], …}`; pairing count = `allowFrom` length. Poller pid in `<dir>/bot.pid`; a live poller's `ps -o args=` contains `server.ts`.
- `tmux-ctl approve` never selects an option whose label contains `always`, `don't ask` or `allow all` (case-insensitive). Prompt option labels come from captured real screens (Task 3), not hand-written.
- `bin/tmux-ctl`'s `help` prints `sed -n '2,37p'`: when header lines are added, widen that range so the whole header (and nothing after it) prints.
- Spec-10 code in `bin/claude-orchestrator` (`AGENT_BOARD_LEAD=1`, the `tc_tmux set-environment` lines, `MODEL_ARGS`) stays as it is.

**User decisions (already made):**
- Telegram channel (official plugin) on dev leads only; one bot per project.
- Teammate permission prompts may be approved remotely through the lead under spec §5.
- Bun 1.4.4 (`~/.bun/bin`) and plugin 0.0.7 (user scope) are installed.
- Integration: merge to `main` locally, no push.

**Known environment fact:** in sessions without a token the plugin's MCP server exits at once, which Claude Code reports as `plugin:telegram:telegram … Connection closed`. That is expected (spec "Error handling") and not a bug to fix here.

---

### Task 1: `tmux-ctl telegram token|status|forget`

**Goal:** Per-project bot token storage and status, never printing the token.

**Files:**
- Create: `tools/lib/telegram.zsh` (function `telegram_cmd`, sourced by tmux-ctl like `tools/lib/awake.zsh`)
- Modify: `bin/tmux-ctl` (header help lines, `help` sed range, new `telegram)` case before `""|-h|--help|help)`)
- Test: `tools/tests/test_ctl_telegram.zsh`

**Acceptance Criteria:**
- [ ] `print -r -- "$TOK" | tmux-ctl telegram token` (inside a scratch tmux session `tt`) writes `$TC_STATE/telegram/tt/.env` = `TELEGRAM_BOT_TOKEN=$TOK`, file mode 600, dir mode 700, prints `telegram: token saved for tt (restart its lead to connect)`.
- [ ] In a grouped session (a second session `tt2` created with `new-session -t tt`), the key is the group name, not `tt2`.
- [ ] A token given as an argument (`tmux-ctl telegram token tt 123…`) is refused (exit 2, nothing written, stderr does not echo it).
- [ ] Bad shape (`print -r -- nope | tmux-ctl telegram token`) → `telegram: that does not look like a bot token`, exit 2, no `.env`.
- [ ] Outside tmux (`env -u TMUX -u TMUX_PANE`) without `--project` → exit 2 with a usage message; with `--project p1` it works.
- [ ] `status` prints the lines `token: set|missing`, `paired: <n> allowlisted|none`, `policy: <dmPolicy>` (`policy: pairing` when no access.json), `poller: running (pid N)|stopped`, `plugin: ok|missing`, `bun: ok|missing`. Poller is running only when `bot.pid`'s pid is alive and its `ps -o args=` contains `server.ts`.
- [ ] `status` warns with the spec's exact line when `$HOME/.claude/channels/telegram/.env` exists (tests point `HOME` at a temp dir).
- [ ] `forget` removes `.env`, keeps `access.json`, prints `telegram: token removed for <project>`.
- [ ] Across token, status and forget runs, `grep -c` of the dummy token's secret part over captured stdout+stderr is 0 (and the check prints how many output files it scanned, > 0).
- [ ] `tmux-ctl help` shows the new `telegram` and (Task 4) lines and still ends at the header's last line.

**Verify:** `zsh tools/tests/test_ctl_telegram.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** `tools/tests/test_ctl_telegram.zsh`: `source "${0:A:h}/lib.zsh"`; `tt_setup claude`; `C="$TT_REPO/bin/tmux-ctl"`; a temp `HOME` (`export HOME="$TT_DIR/home"`) so the default-dir warning and `~/.bun/bin` checks are controlled; stubs on a temp PATH dir: `claude` (prints `telegram@claude-plugins-official` for `plugin list` when `$S/plugin.ok` exists) and a poller stub started as `zsh -c 'exec -a "bun server.ts" sleep 600' &` (probed 2026-11-09: `ps -o args= -p $!` prints `bun server.ts 600`); the test asserts that `ps` line contains `server.ts` before relying on it. Write `bot.pid`, assert `poller: running (pid N)`; kill it, assert `poller: stopped`. Capture every command's stdout+stderr into `$S/out.N` files and at the end `grep -c` the token's secret part across them. Each guard test names its mutation in a comment, e.g. `# mutation: drop the shape check → bad-shape test fails`, `# mutation: chmod 644 → mode test fails`, `# mutation: accept "$2" as token → argv test fails`.
- [ ] **Step 2: Run** `zsh tools/tests/test_ctl_telegram.zsh` → FAIL (`unknown command 'telegram'`).
- [ ] **Step 3: Implement** `tools/lib/telegram.zsh`. Project key: `--project <name>` wins, else `$FEEDKEY` from tmux-ctl when `$TMUX` is set. tmux-ctl dies with `not inside tmux` before the case statement, so the `telegram` subcommand must be dispatched before that guard (move the `[[ -n "$TMUX" ]] || die` check so `telegram` with `--project` works outside tmux; keep every other command's behaviour). Token read: `if [[ -t 0 ]]; then read -rs "tok?Bot token: "; print -u2; else read -r tok; fi`. Write with `umask 077` in a subshell, `mkdir -p -m 700`, then `chmod 600`. Status reads `access.json` with `python3 -I -c` or `jq` (jq is already a dependency of tmux-ctl: `jq -r '.dmPolicy // "pairing"'`, `jq '.allowFrom|length'`).
- [ ] **Step 4: Run** `zsh tools/tests/test_ctl_telegram.zsh` → `ALL PASS`; for each named mutation, apply it on a scratch copy, run, see the named test FAIL, revert. Also run `zsh tools/tests/test_ctl_opts.zsh` (tmux-ctl option parsing must still pass).
- [ ] **Step 5: Commit** `git add tools/lib/telegram.zsh bin/tmux-ctl tools/tests/test_ctl_telegram.zsh` → `feat(tmux-ctl): telegram token/status/forget per project`

```json:metadata
{"files": ["tools/lib/telegram.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_telegram.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_telegram.zsh", "acceptanceCriteria": ["token saved mode 600 under project key (group and ungrouped)", "argv token refused", "bad shape exit 2 nothing written", "outside tmux needs --project", "status fields incl poller/plugin/bun", "default-dir warning", "forget keeps access.json", "token never in output (count of files scanned > 0)", "help range covers header"], "modelTier": "standard"}
```

### Task 2: Leads opt in to the channel (`bin/claude-orchestrator`)

**Goal:** A lead started for a project with a saved token gets the channel flag and `TELEGRAM_STATE_DIR`; nobody else does.

**Files:**
- Modify: `bin/claude-orchestrator`
- Test: `tools/tests/test_claude_orchestrator_tg.zsh`

**Acceptance Criteria:**
- [ ] With `$TC_STATE/telegram/<project>/.env` present (project from the tmux session as in Global Constraints), the stub `claude` sees `--channels plugin:telegram@claude-plugins-official` before the caller's args, and `TELEGRAM_STATE_DIR=$TC_STATE/telegram/<project>`.
- [ ] Without `.env`, or with `TC_TELEGRAM=0`, or outside tmux: neither the flag nor `TELEGRAM_STATE_DIR` (unset even if inherited from the caller's env).
- [ ] A caller passing `--channels …` (either `--channels X` or `--channels=X`) gets no second `--channels`.
- [ ] `tmux show-environment -t =tt TELEGRAM_STATE_DIR` reports it unset after the run.
- [ ] When `$HOME/.bun/bin` exists, it is on the PATH claude sees and in the session env's PATH (`tc_tmux set-environment PATH` already runs: put the bun dir on PATH before it). When absent, PATH is unchanged.
- [ ] Both `exec claude` lines (with and without the prompt file) carry the flag.

**Verify:** `zsh tools/tests/test_claude_orchestrator_tg.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test.** `tt_setup claude`; temp `HOME`; a stub dir first on PATH with an executable `claude` that writes `print -rl -- "$@" > $S/argv; print -r -- "${TELEGRAM_STATE_DIR-UNSET}" > $S/tsd; print -r -- "$PATH" > $S/path`. Run `"$TT_REPO/bin/claude-orchestrator" --continue` directly from the test shell (TMUX/TMUX_PANE point at the scratch server, so the session is `tt`). Cases: no token; token; token + `TC_TELEGRAM=0`; token + `--channels plugin:x`; token + `--channels=plugin:x`; token with `env -u TMUX -u TMUX_PANE`; inherited `TELEGRAM_STATE_DIR=/bogus` with no token → `UNSET`; `$HOME/.bun/bin` present vs absent. Mutations: drop the `TC_TELEGRAM` check → kill-switch case fails; drop the duplicate guard → `--channels` case sees two; use `tc_tmux set-environment TELEGRAM_STATE_DIR` → session-env case fails.
- [ ] **Step 2: Run** → FAIL on the token case.
- [ ] **Step 3: Implement.** Source `tools/lib/tc-env.zsh` only if needed; compute the project with `tc_tmux display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}'` (drop a trailing `-bg` only when `@tc_bg` is set, as tmux-ctl does). Build `TG_ARGS=()` and insert `"${TG_ARGS[@]}"` before `"$@"` in both exec lines. `unset TELEGRAM_STATE_DIR` when not opting in. Duplicate guard: `(( ${@[(I)--channels|--channels=*]} ))`.
- [ ] **Step 4: Run** → `ALL PASS`; check each mutation fails its case. Also run `zsh tools/tests/test_agent_name_guard.zsh` and `python3 -m unittest board.tests.test_orchestrator_path` from the repo root (both read this launcher).
- [ ] **Step 5: Commit** `feat(orchestrator): Telegram channel for leads with a saved token`

```json:metadata
{"files": ["bin/claude-orchestrator", "tools/tests/test_claude_orchestrator_tg.zsh"], "verifyCommand": "zsh tools/tests/test_claude_orchestrator_tg.zsh", "acceptanceCriteria": ["flag+env with token", "neither without token, TC_TELEGRAM=0, outside tmux; inherited TELEGRAM_STATE_DIR unset", "no doubled --channels (both spellings)", "TELEGRAM_STATE_DIR absent from tmux session env", "~/.bun/bin on PATH when present", "both exec lines"], "modelTier": "standard"}
```

### Task 3: Capture real permission-prompt screens

**Goal:** Fixtures of real Claude Code permission prompts (as `tmux capture-pane -p -J` shows them) for `tmux-ctl approve`, plus a README saying how they were captured and which key selects an option.

**Files:**
- Create: `tools/tests/fixtures/approve/README.md`, `tools/tests/fixtures/approve/*.txt`

**Acceptance Criteria:**
- [ ] At least three captures from a real `claude` (version noted in the README, from `claude --version`) on a scratch tmux server started with `-f /dev/null`, default permission mode, in a scratch git dir: a Bash command prompt (`bash-touch.txt`), a file write/edit prompt (`write.txt`), and one more tool kind (e.g. a WebFetch or a Bash command with a "don't ask again for …" option) — whichever offers an "always"/"don't ask again" option must be among them.
- [ ] One capture of the same pane after the prompt was answered (`after-yes.txt`) and one screen with no prompt (`no-prompt.txt`).
- [ ] README records: the exact commands used; which keystroke selects option N (probe: press the option's digit vs arrow+Enter, and record what the pane showed after); that the scratch session was killed and its dir removed (`ps` / `ls` evidence).
- [ ] No token, user path beyond `$HOME` replaced by `~`, or secret in the fixtures (`grep -c` for `/Users/` → 0 after redaction; the README says what was redacted).

**Verify:** `ls tools/tests/fixtures/approve/*.txt | wc -l; grep -c '/Users/' tools/tests/fixtures/approve/*.txt` → first line ≥ 5, then every file `:0`

**Steps:**

- [ ] **Step 1:** `S=$(mktemp -d); git -C $S init -q`; `~/.local/bin/tmux -L apcap -f /dev/null new-session -d -s ap -x 200 -y 50 -c $S`; start `claude --settings <(echo '{}')`-free plain `claude` in that pane with `--permission-mode default`; wait for its prompt; send a request like "run `touch made-by-test` with Bash" (send-keys text, sleep 1, send-keys Enter — see shared context); poll `capture-pane -p -J` until a prompt with numbered options shows; save it.
- [ ] **Step 2:** Probe the selection key on that prompt (digit key first); capture after; repeat for a Write prompt and a third kind.
- [ ] **Step 3:** Kill the scratch server (`-L apcap kill-server`), remove `$S`, confirm no leftover `claude` process from it (`ps -ax -o pid,args | grep -c "$S"` → 0, after printing how many processes were scanned).
- [ ] **Step 4:** Redact `/Users/<name>` to `~`; write README; commit `test(approve): captured permission-prompt fixtures`.

```json:metadata
{"files": ["tools/tests/fixtures/approve/README.md"], "verifyCommand": "ls tools/tests/fixtures/approve/*.txt | wc -l; grep -c '/Users/' tools/tests/fixtures/approve/*.txt", "acceptanceCriteria": [">=3 real prompt captures incl one with an always/don't-ask option", "after-yes and no-prompt captures", "README: commands, selection key probe, cleanup evidence", "no /Users/ paths or secrets"], "modelTier": "standard"}
```

### Task 4: `tmux-ctl approve <window> once|deny [--expect <text>]`

**Goal:** Press the one-time yes or the no option of the permission prompt showing in a window, refusing when there is none or when it is not the expected prompt.

**Files:**
- Modify: `bin/tmux-ctl` (header help line, `approve)` case; parsing helper may live in `tools/lib/approve.zsh`)
- Test: `tools/tests/test_ctl_approve.zsh`

**Acceptance Criteria:**
- [ ] Against a pane replaying each Task 3 prompt fixture (`cat fixture; sleep 600` in a scratch-server window), `approve <win> once` sends the key Task 3's README recorded for the option whose label starts with `Yes` and contains none of `always`, `don't ask`, `allow all` (case-insensitive), and prints `approve: <win>: chose "<label>"`. The test records the keys sent (a pane running `cat fixture; read -k1 k; print -r -- "GOT:$k"` shows which key arrived).
- [ ] `deny` picks the option whose label starts with `No`.
- [ ] `no-prompt.txt` → exit 1, `approve: no permission prompt in <win>`, no key sent.
- [ ] `--expect <text>`: when the prompt does not contain `<text>` verbatim → exit 1, `approve: the prompt in <win> changed`, no key sent. (This is the lead's "same prompt still showing" check from spec §5.3, made atomic.)
- [ ] A fixture variant whose only yes options contain `always`/`don't ask` → exit 1 for `once`, never presses them.
- [ ] Works on worker windows (`@tc_agent`), unlike `keys`.

**Verify:** `zsh tools/tests/test_ctl_approve.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** from the fixtures (never hand-written prompt text; the "only always options" variant is a fixture copy with the plain `Yes` line deleted by `sed`, and says so). Mutations: drop the `always` filter → the variant test presses it; drop the `--expect` check → changed-prompt test sends a key; drop the no-prompt check → exit-1 test fails.
- [ ] **Step 2: Run** → FAIL (`unknown command 'approve'`).
- [ ] **Step 3: Implement**: capture the pane (`capture-pane -p -J`, last ~40 lines), find the numbered option lines of the last prompt block (shape from the fixtures), choose, send the recorded key with `send-keys`.
- [ ] **Step 4: Run** → `ALL PASS`; each mutation fails its test. Also `zsh tools/tests/test_ctl_telegram.zsh` (shares tmux-ctl's header/help).
- [ ] **Step 5: Commit** `feat(tmux-ctl): approve a teammate's permission prompt once or deny`

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_approve.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_approve.zsh", "acceptanceCriteria": ["once picks one-time Yes from real fixtures, prints chosen label", "deny picks No", "no prompt exit 1 no key", "--expect mismatch exit 1 no key", "never presses always/don't ask", "works on worker windows"], "modelTier": "standard"}
```

### Task 5: Board `tg` badge on a lead with the channel

**Goal:** The board shows `tg` on a session's lead card when that lead's claude process runs with `--channels plugin:telegram`.

**Files:**
- Modify: `board/server.py` (`build_state`: add `#{pane_pid}` as a new LAST field of the list-panes format — `relay` and `label_targets` read `#{session_path}` as the last field of *their own* formats, check they are separate formats and untouched — and set `"telegram": true|false` on panes)
- Modify: `board/index.html` (`card()`: a `tg` badge with the spec's tooltip)
- Test: `board/tests/test_telegram_badge.py`

**Acceptance Criteria:**
- [ ] One `ps -A -o pid=,ppid=,args=` call per `build_state` (not per pane), only when at least one lead pane exists.
- [ ] Lead pane = a pane of kind claude in the session's `claude` window (same rule as `orchestrator()` in index.html, first branch). It is `telegram: true` when any process in its pane's process tree (pane_pid and descendants) has args containing `--channels plugin:telegram`.
- [ ] `telegram` is false for a lead without the flag and for a teammate window pane with the flag.
- [ ] Card shows a `tg` badge, tooltip exactly `Telegram channel on (delivery not checked by the board)`.
- [ ] A test asserts `ps` runs once for a state with two lead panes (mutation: call ps per pane → count test fails).

**Verify:** `python3 -m unittest board.tests.test_telegram_badge -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test** patching `server.tmux` (fake list-panes output with the new field count) and the ps runner (a function in server.py, e.g. `proc_table()`, so the test patches one seam). Follow the patching style of `board/tests/test_session_path.py`. Also `grep -n 'len(f) == 16' board/server.py` must become 17 consistently.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; add the badge in `card()` next to the status pill, reusing the existing `alert-badge` style or a small new class.
- [ ] **Step 4: Run** the new test plus `python3 -m unittest board.tests.test_session_path board.tests.test_session_root_path board.tests.test_poll_efficiency` → `OK`. Then a real-state check (read-only): start a second board on the live tmux server from the worktree (`TMUX_DASH_PORT=7710 TC_OVERSEER=0 python3 board/server.py`), `curl` its `/api/state` (token prefix printed at start) and confirm every live lead pane has `"telegram": false` today (no lead has the flag yet) and the call returns in < 2 s; stop that board.
- [ ] **Step 5: Commit** `feat(board): tg badge on a lead with the Telegram channel`

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_telegram_badge.py"], "verifyCommand": "python3 -m unittest board.tests.test_telegram_badge -v", "acceptanceCriteria": ["one ps per build_state", "lead pane tree with --channels plugin:telegram -> telegram true", "false without flag and on teammate panes", "tg badge with exact tooltip", "real-state check on live tmux via a 7710 board"], "modelTier": "standard"}
```

### Task 6: Lead rules, INSTALL docs, user-gate checklist

**Goal:** Write the remote protocol into the lead rules and the install guide, and the user's e2e checklist.

**Files:**
- Modify: `claude/orchestrator.md` (new section `## Remote: Telegram` before `## Rules`; one exception sentence in `## Rules` on the permission-prompt bullet)
- Modify: `docs/INSTALL.md` (section `## Remote access`)
- Create: `tools/tests/e2e-remote-access.md`

**Acceptance Criteria:**
- [ ] `orchestrator.md` "Remote: Telegram" states spec §3 (a channel message from an allowlisted sender is the user; replies via the plugin's `reply` tool when a task finishes, a decision is needed, or an agent waits on the user; outcome first; AskUserQuestion becomes a numbered Telegram question while remote) and §5 steps 1–5 with `tmux-ctl approve <win> once|deny --expect "<command text>"`, workers included, peer sessions excluded.
- [ ] The `## Rules` bullet "Never answer a teammate's or worker's permission prompt…" keeps its wording and gains "except through Remote: Telegram's approval protocol".
- [ ] The row the user edited locally (the Workflow table's "Carrying out a plan" row) is NOT touched by this task (`git diff main -- claude/orchestrator.md` shows no change on that row).
- [ ] INSTALL "Remote access" covers every item of spec §7, including "never `/telegram:configure`", one live lead per project, `TC_TELEGRAM=0`, `tmux-ctl telegram status`, and the Remote Control note.
- [ ] `e2e-remote-access.md` is an unchecked `- [ ]` checklist of every user-gate item in the spec's Testing section, each with the command to run and the expected observation.
- [ ] `grep -c 'Remote: Telegram' claude/orchestrator.md` ≥ 2 (heading + Rules reference).

**Verify:** `grep -c 'Remote: Telegram' claude/orchestrator.md; grep -c '^## Remote access' docs/INSTALL.md; grep -c '^- \[ \]' tools/tests/e2e-remote-access.md` → ≥2, 1, ≥8

**Steps:**

- [ ] **Step 1:** Write the three docs in the house style (short sentences, one rule per bullet). Use the real command names from Tasks 1 and 4 (`tmux-ctl telegram token <project>`, `tmux-ctl approve`).
- [ ] **Step 2:** Run the Verify line.
- [ ] **Step 3: Commit** `docs: Telegram remote access in the lead rules and INSTALL; e2e checklist`

```json:metadata
{"files": ["claude/orchestrator.md", "docs/INSTALL.md", "tools/tests/e2e-remote-access.md"], "verifyCommand": "grep -c 'Remote: Telegram' claude/orchestrator.md; grep -c '^## Remote access' docs/INSTALL.md; grep -c '^- \\[ \\]' tools/tests/e2e-remote-access.md", "acceptanceCriteria": ["orchestrator.md Remote: Telegram covers spec §3 and §5", "Rules bullet gains the exception", "user's locally edited workflow row untouched", "INSTALL Remote access covers spec §7", "e2e checklist covers every user-gate item"], "modelTier": "standard"}
```

### Task 7: User gate — remote access end to end (morning)

**Goal:** The user runs `tools/tests/e2e-remote-access.md` with a real bot and phone.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Test: `tools/tests/e2e-remote-access.md`

**Acceptance Criteria:**
- [ ] A phone message reaches the lead within ~30 s through Netskope, and the lead's reply arrives on the phone.
- [ ] A lead permission prompt is answered by a Telegram button.
- [ ] A teammate prompt approved with `approve n` shows accepted once in its pane.
- [ ] A second project's bot stays separate; `tmux-ctl telegram status` never shows the token.

**Verify:** the user ticks every box in `tools/tests/e2e-remote-access.md`

```json:metadata
{"files": ["tools/tests/e2e-remote-access.md"], "verifyCommand": "the user ticks every box in tools/tests/e2e-remote-access.md", "acceptanceCriteria": ["phone->lead within ~30s and reply arrives", "lead prompt answered by button", "teammate approve n accepted once", "second bot separate; status never shows token"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
