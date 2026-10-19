# Installability Refactors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: planned, not applied.** Written with the install docs (`docs/INSTALL.md`). Nothing below has been implemented.

**Goal:** Make agent-board installable on a new machine with one command (`./install.sh`) and no hand edits beyond an opt-in config merge, without changing behaviour for the existing install.

**Architecture:** Three changes in order. First, scripts stop assuming the `~/.local/bin` and `~/.local/share` layout: they find binaries through an override → `~/.local/bin` → `PATH` chain, and find repo files relative to their own resolved path. Second, the repo ships everything an install needs: tmux and settings fragments, the skills and agent definitions the rules name. Third, an idempotent `install.sh` links, checks and merges, with `--check`, `--dry-run` and `--uninstall` modes, and CI runs both suites on macOS and Linux.

**Tech Stack:** zsh 5.9, tmux 3.x, Python 3.11+ stdlib, GitHub Actions.

**Spec:** none separate. The gaps this plan closes are listed in "Why" below and in `docs/INSTALL.md` (the manual steps it replaces).

### Why (the install gaps found while writing the docs)

1. **Hardcoded binary paths.** `tmux-dash`, `tmux-web-attach`, `tmux-jump`, `tmux-teammate-window` and `board/server.py` call `~/.local/bin/{tmux,ttyd,fzf}` with no override. `TC_TMUX` works only in some scripts. A Homebrew-only machine needs hand-made symlinks.
2. **Hardcoded live-path layout.** `tmux-ctl` types `~/.local/bin/tmux-ctl _done` into panes and calls `~/.local/share/tmux-dash/{ideas,relay}.py` and `~/.claude/hooks/artifact-register.sh`. `tmux-dash` runs `~/.local/share/tmux-dash/server.py`. `board/artifacts.py` runs `~/.claude/hooks/artifact-register.sh`. Each one needs its symlink.
3. **Config outside the repo.** The tmux hooks and bindings and the Claude Code hook registrations live only in the author's `~/.tmux.conf` and `~/.claude/settings.json`.
4. **Missing dependencies of the rules.** `claude/orchestrator.md` and `worker.md` name the `tmux-orchestrator` and `handoff` skills and the `effort-*` agent types, which are not in the repo, plus two personal skills (`task-observer`, `gitlab-ci-loop`).
5. **No install, check or uninstall script.** No dependency check either; `jq` failing only shows up at the first `tmux-ctl run`.
6. **macOS-only bits.** `open` in `tmux-dash`.
7. **No CI.** Both suites run only on the author's Mac.

## Global Constraints

- The existing install (symlinks into `~/agent-board`) must keep working unchanged after every task: the resolution chain tries `~/.local/bin/<tool>` before `PATH`, and the `~/.claude/{orchestrator,worker}.md` paths before the repo copies.
- No new runtime dependencies. Python stays stdlib-only; shell stays zsh.
- `install.sh` never overwrites a real file or directory. It backs it up as `<F>.bak-YYYYMMDD` first, and refuses if that backup name is taken. It replaces only symlinks.
- `install.sh` never edits `~/.tmux.conf` or `~/.claude/settings.json` without `--with-config`. With it, the edit is idempotent and a backup is written first.
- Tests that touch tmux use `tools/tests/lib.zsh` (private socket, `-f /dev/null`). Tests that install use a scratch `HOME` under `mktemp -d`, never the real one.
- Both suites stay green after each task: `python3 -m unittest discover -s board/tests` and `zsh tools/tests/run-all.zsh`.
- Commit messages: conventional commits with scope (`refactor(tmux-ctl): …`, `feat(install): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):** "If there are any refactors needed to ease installability those should not be applied only planned." (2026-10-19). This plan is that plan; executing it needs a fresh go-ahead.

---

### Task 1: Resolve tool binaries through one chain

**Goal:** Every script and the board find tmux, ttyd and fzf as `override env var → ~/.local/bin/<tool> → PATH`, so a Homebrew-only machine works without extra symlinks.

**Files:**
- Create: `bin/_tc_bins.zsh` (sourced helper; not linked into `~/.local/bin` by the installer)
- Modify: `bin/dev`, `bin/tmux-ctl`, `bin/tmux-dev-layout`, `bin/tmux-session-closed`, `bin/tmux-dash`, `bin/tmux-web-attach`, `bin/tmux-jump`, `bin/tmux-teammate-window`, `bin/tmux-agent-cleanup`
- Modify: `board/server.py` (the `TMUX` list), `board/paneclass.py` (`tmux_runner`)
- Test: `tools/tests/test_bins.zsh`, `board/tests/test_paneclass.py`

**Acceptance Criteria:**
- [ ] With `TC_TMUX`, `TTYD_BIN`, `FZF_BIN` unset and no `~/.local/bin/tmux` in a scratch `HOME`, `tc_bin tmux` prints the `PATH` tmux.
- [ ] With `~/.local/bin/tmux` present it wins over `PATH`; with `TC_TMUX` set that wins over both.
- [ ] `grep -rn 'HOME/.local/bin/\(tmux\|ttyd\|fzf\)"' bin/` finds only `bin/_tc_bins.zsh`.
- [ ] `paneclass.tmux_runner()` uses `shutil.which("tmux")` when `TC_TMUX` is unset and `~/.local/bin/tmux` does not exist.
- [ ] Both suites pass.

**Verify:** `zsh tools/tests/test_bins.zsh && python3 -m unittest board.tests.test_paneclass 2>&1 | tail -1` → `ALL PASS` then `OK`

**Steps:**

- [ ] **Step 1: Write the failing test** `tools/tests/test_bins.zsh`:

```zsh
#!/usr/bin/env zsh
# test_bins.zsh — tool resolution: override env → ~/.local/bin → PATH
emulate -L zsh
source "${0:A:h}/lib.zsh"
REPO="${0:A:h:h:h}"
H="$(mktemp -d)"; trap 'rm -rf "$H"; tt_teardown' EXIT
mkdir -p "$H/pathbin" "$H/.local/bin"
print '#!/bin/sh\necho pathtmux' > "$H/pathbin/tmux"; chmod +x "$H/pathbin/tmux"
res() { HOME="$H" PATH="$H/pathbin:/usr/bin:/bin" zsh -c "unset TC_TMUX; ${1:+export TC_TMUX=$1;} source $REPO/bin/_tc_bins.zsh; tc_bin tmux TC_TMUX" }
check "PATH fallback"      [ "$(res)" = "$H/pathbin/tmux" ]
cp "$H/pathbin/tmux" "$H/.local/bin/tmux"
check "~/.local/bin wins"  [ "$(res)" = "$H/.local/bin/tmux" ]
check "override wins"      [ "$(res /opt/x/tmux)" = "/opt/x/tmux" ]
tt_done
```

- [ ] **Step 2: Run it and see it fail** — `zsh tools/tests/test_bins.zsh` → fails: `_tc_bins.zsh` not found.

- [ ] **Step 3: Implement** `bin/_tc_bins.zsh`:

```zsh
# _tc_bins.zsh — sourced by bin/ scripts. tc_bin <tool> <override-var>: print the binary to run.
# Order: $<override-var> → ~/.local/bin/<tool> (the original layout) → PATH. Falls back to the bare name.
tc_bin() {
  local v="${(P)2}"
  [[ -n "$v" ]] && { print -r -- "$v"; return }
  [[ -x "$HOME/.local/bin/$1" ]] && { print -r -- "$HOME/.local/bin/$1"; return }
  print -r -- "${commands[$1]:-$1}"
}
```

In each script replace the hardcoded path, sourcing through the resolved script dir so symlinks work:

```zsh
source "${0:A:h}/_tc_bins.zsh"
TMUX_BIN="$(tc_bin tmux TC_TMUX)"
```

`tmux-dash`: `TTYD_BIN="$(tc_bin ttyd TTYD_BIN)"`; `tmux-jump` and `tmux-agent-cleanup`: `FZF_BIN="$(tc_bin fzf FZF_BIN)"`. In `tmux-web-attach`, keep `TMUX_DASH_TMUX_ARGS` appended after the resolved binary.

In Python (`paneclass.tmux_runner` and `server.TMUX`), one shared helper in `paneclass.py`:

```python
def tmux_bin():
    local = Path.home() / ".local" / "bin" / "tmux"
    return os.environ.get("TC_TMUX") or (str(local) if os.access(local, os.X_OK) else shutil.which("tmux") or "tmux")
```

and `server.py` uses `TMUX = [paneclass.tmux_bin()] + shlex.split(...)`.

- [ ] **Step 4: Add a Python test** in `board/tests/test_paneclass.py` that sets `HOME` to a temp dir without `.local/bin/tmux`, unsets `TC_TMUX`, patches `shutil.which` to return `/x/tmux`, and asserts `paneclass.tmux_bin() == "/x/tmux"`.

- [ ] **Step 5: Run both suites** — `python3 -m unittest discover -s board/tests` → OK; `zsh tools/tests/run-all.zsh` → every file `ALL PASS`.

- [ ] **Step 6: Commit** — `refactor(bin): resolve tmux, ttyd and fzf via override, ~/.local/bin, then PATH` plus your harness's attribution trailer.

```json:metadata
{"files": ["bin/_tc_bins.zsh", "bin/dev", "bin/tmux-ctl", "bin/tmux-dev-layout", "bin/tmux-session-closed", "bin/tmux-dash", "bin/tmux-web-attach", "bin/tmux-jump", "bin/tmux-teammate-window", "bin/tmux-agent-cleanup", "board/server.py", "board/paneclass.py", "tools/tests/test_bins.zsh", "board/tests/test_paneclass.py"], "verifyCommand": "zsh tools/tests/test_bins.zsh && python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["PATH fallback works with no ~/.local/bin/tmux", "~/.local/bin wins over PATH; override wins over both", "only _tc_bins.zsh hardcodes ~/.local/bin tool paths", "paneclass.tmux_bin falls back to shutil.which", "both suites pass"], "modelTier": "standard"}
```

---

### Task 2: Find repo files relative to the repo, not the live layout

**Goal:** Scripts locate the board, hooks and rules files from their own resolved path, so only `bin/` needs linking. The existing `~/.claude/{orchestrator,worker}.md` keep priority as user overrides.

**Files:**
- Modify: `bin/tmux-ctl` (`_done` callback path, `idea`, `relay`, `artifact`, `agent` worker rules), `bin/tmux-dash` (`APP`), `bin/claude-orchestrator` (`PROMPT_FILE`)
- Modify: `board/artifacts.py` (`HOOK`)
- Test: `tools/tests/test_repo_paths.zsh`, `board/tests/test_artifacts.py`

**Acceptance Criteria:**
- [ ] `grep -n 'local/share/tmux-dash\|local/bin/tmux-ctl\|\.claude/hooks/artifact-register' bin/ board/*.py` returns nothing.
- [ ] `tmux-ctl run` still works when `~/.local/bin/tmux-ctl` does not exist: the typed callback is `${0:A}` quoted (`test_repo_paths.zsh` runs a run from a scratch `HOME`).
- [ ] `claude-orchestrator` uses `~/.claude/orchestrator.md` when it exists, else `<repo>/claude/orchestrator.md`; same order for `worker.md` in `tmux-ctl agent` (checked with `TC_AGENT_DRYRUN` plus a printed rules path).
- [ ] `artifacts.HOOK` is `Path(__file__).resolve().parent.parent / "claude/hooks/artifact-register.sh"`.
- [ ] Both suites pass.

**Verify:** `zsh tools/tests/test_repo_paths.zsh && zsh tools/tests/run-all.zsh | grep -c FAILED` → `ALL PASS` then `0`

**Steps:**

- [ ] **Step 1: Write the failing test** `tools/tests/test_repo_paths.zsh`. It uses `tt_setup`, sets `HOME` to a scratch dir with no `~/.local/bin`, calls `"$REPO/bin/tmux-ctl" run shell "echo hi"` and checks the output contains `hi` and `[exit 0]`. Then it calls `TC_AGENT_DRYRUN=1 "$REPO/bin/tmux-ctl" agent x --force "a b"` and checks stderr names `$REPO/claude/worker.md`.
- [ ] **Step 2: Run it and see it fail** — the run times out: `~/.local/bin/tmux-ctl: no such file`.
- [ ] **Step 3: Implement.** At the top of `tmux-ctl`: `SELF="${0:A}"; REPO="${SELF:h:h}"`. Then:
  - the typed callback becomes `${(q)SELF} _done $id \$?`;
  - `idea` runs `python3 -I "$REPO/board/ideas.py" …`; `relay` runs `"$REPO/board/relay.py"`; `artifact` runs `"$REPO/claude/hooks/artifact-register.sh"`;
  - `agent` picks `rules_file=~/.claude/worker.md` if readable, else `$REPO/claude/worker.md`, prints `tmux-ctl: worker rules: $rules_file` to stderr in dry-run mode, and passes `--append-system-prompt-file ${(q)rules_file}`.

  `tmux-dash`: `APP="${0:A:h:h}/board"`. `claude-orchestrator`: `PROMPT_FILE` = `~/.claude/orchestrator.md` if readable, else `${0:A:h:h}/claude/orchestrator.md`. `artifacts.py`: `HOOK` as in the acceptance criteria.
- [ ] **Step 4: Run both suites** → all pass.
- [ ] **Step 5: Commit** — `refactor(tmux-ctl): locate board, hooks and rules relative to the repo`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/tmux-ctl", "bin/tmux-dash", "bin/claude-orchestrator", "board/artifacts.py", "tools/tests/test_repo_paths.zsh", "board/tests/test_artifacts.py"], "verifyCommand": "zsh tools/tests/test_repo_paths.zsh && zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["no live-layout paths left in bin/ or board/*.py", "tmux-ctl run works without ~/.local/bin/tmux-ctl", "~/.claude rules files win, repo copies are the fallback", "artifacts.HOOK is repo-relative", "both suites pass"], "modelTier": "standard"}
```

---

### Task 3: Ship config fragments, skills and agent definitions in the repo

**Goal:** Everything the docs tell a user to copy by hand exists as a file in the repo: a sourceable tmux fragment, a hooks JSON fragment, and the skills and agent types the rules name.

**Files:**
- Create: `config/tmux.conf` (exactly the block in `docs/INSTALL.md` §4)
- Create: `config/claude-settings.json` (`env`, `teammateMode`, `hooks` from `docs/INSTALL.md` §5, with `~/.claude/hooks/...` commands)
- Create: `claude/skills/tmux-orchestrator/SKILL.md`, `claude/skills/handoff/SKILL.md` (and the handoff skill's `agents/` dir) from the author's live copies, with machine-specific paths removed
- Create: `claude/agents/effort-low.md`, `claude/agents/effort-medium.md`, `claude/agents/effort-high.md`
- Modify: `claude/orchestrator.md` (the task-observer and gitlab-ci-loop rows become "if installed")
- Test: `tools/tests/test_config_fragments.zsh`

**Acceptance Criteria:**
- [ ] `~/.local/bin/tmux -L t$$ -f config/tmux.conf start-server \; show-hooks -g` lists `after-split-window` and `session-closed`, then the server is killed.
- [ ] `python3 -c 'import json;json.load(open("config/claude-settings.json"))'` exits 0 and the file names the three repo hooks.
- [ ] `grep -rn '/Users/' claude/ config/` returns nothing.
- [ ] Every skill and agent name used in `claude/orchestrator.md` and `claude/worker.md` is either under `claude/skills/` or `claude/agents/`, comes from the superpowers-extended-cc plugin, or is marked "if installed".

**Verify:** `zsh tools/tests/test_config_fragments.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the test** `tools/tests/test_config_fragments.zsh` with the checks above. The tmux check uses its own `-L` socket and `kill-server` at the end.
- [ ] **Step 2: Run it and see it fail** (files missing).
- [ ] **Step 3: Create the files.** Copy the skills from `~/.claude/skills/{tmux-orchestrator,handoff}/` and the agents from `~/.claude/agents/effort-*.md`, read each file in full, and replace absolute home paths with `~`. In `orchestrator.md`, change the first and last skill-table rows to start with "If the skill is installed:".
- [ ] **Step 4: Run the test and both suites** → pass.
- [ ] **Step 5: Commit** — `feat(config): ship tmux and Claude settings fragments, skills and agent types`, with your harness's attribution trailer.

```json:metadata
{"files": ["config/tmux.conf", "config/claude-settings.json", "claude/skills/tmux-orchestrator/SKILL.md", "claude/skills/handoff/SKILL.md", "claude/agents/effort-low.md", "claude/agents/effort-medium.md", "claude/agents/effort-high.md", "claude/orchestrator.md", "tools/tests/test_config_fragments.zsh"], "verifyCommand": "zsh tools/tests/test_config_fragments.zsh", "acceptanceCriteria": ["config/tmux.conf sets both hooks", "config/claude-settings.json is valid JSON naming the three hooks", "no /Users/ paths in claude/ or config/", "every referenced skill/agent is shipped, from the plugin, or marked if installed"], "modelTier": "standard"}
```

---

### Task 4: `install.sh` with check, dry-run, config merge and uninstall

**Goal:** `./install.sh` links `bin/`, `claude/hooks/`, `claude/skills/`, `claude/agents/` into place with backups, checks dependencies, and with `--with-config` merges the tmux and settings fragments idempotently. `--uninstall` removes only links that point into this repo.

**Files:**
- Create: `install.sh`, `tools/merge_settings.py`
- Test: `tools/tests/test_install.zsh`, `board/tests/test_merge_settings.py`

**Acceptance Criteria:**
- [ ] `./install.sh --check` prints one line per dependency (zsh, tmux, ttyd, fzf, python3 ≥ 3.11, jq, git, claude) as `ok <path>` or `MISSING`, and exits 1 if any required one is missing.
- [ ] In a scratch `HOME`, `install.sh` creates links for every `bin/*` except `_*.zsh`, every hook, skill and agent; a pre-existing real `~/.local/bin/dev` is moved to `dev.bak-YYYYMMDD` first; a second run changes nothing (prints `unchanged` for every link).
- [ ] `--dry-run` prints the same plan and changes nothing (`find "$H" -newer marker` is empty).
- [ ] `--with-config` appends `source-file <repo>/config/tmux.conf` to `~/.tmux.conf` once (a second run doesn't duplicate it). It merges `config/claude-settings.json` into `~/.claude/settings.json`: existing keys are kept, hook entries are added only if no entry has the same `command`, and the original is backed up to `settings.json.bak-YYYYMMDD`.
- [ ] `--uninstall` removes only symlinks whose target is under the repo, and removes the `source-file` line; real files and backups stay.

**Verify:** `zsh tools/tests/test_install.zsh && python3 -m unittest board.tests.test_merge_settings` → `ALL PASS` then `OK`

**Steps:**

- [ ] **Step 1: Write `board/tests/test_merge_settings.py`.** Cases: empty file → the fragment; existing unrelated hooks kept; same command not duplicated; `env` keys merged without overwriting a user value; invalid JSON → exit 2, file untouched.
- [ ] **Step 2: Write `tools/tests/test_install.zsh`.** Use a scratch `HOME` (`mktemp -d`), `PATH` containing stub `tmux`/`ttyd`/`fzf`/`jq`/`claude` scripts, and run each acceptance criterion in turn.
- [ ] **Step 3: Run both and see them fail** (no `install.sh`, no `merge_settings.py`).
- [ ] **Step 4: Implement `tools/merge_settings.py`** (stdlib `json`; `merge(base, frag)`: dicts recurse, `hooks.<event>` lists append matcher groups whose commands are not already present, scalars keep the base value; write via temp file + `os.replace` after a dated backup).
- [ ] **Step 5: Implement `install.sh`** (zsh, `emulate -L zsh`; `REPO="${0:A:h}"`; `link SRC DST`: if `DST` is a symlink to `SRC` → `unchanged`; a symlink elsewhere → replace; a real file → back up, refusing if the backup exists; then `ln -s`; every action goes through a `do_or_print` helper for `--dry-run`).
- [ ] **Step 6: Run the tests and both suites** → pass.
- [ ] **Step 7: Commit** — `feat(install): one-command install, check, config merge and uninstall`, with your harness's attribution trailer.

```json:metadata
{"files": ["install.sh", "tools/merge_settings.py", "tools/tests/test_install.zsh", "board/tests/test_merge_settings.py"], "verifyCommand": "zsh tools/tests/test_install.zsh && python3 -m unittest board.tests.test_merge_settings", "acceptanceCriteria": ["--check lists deps and exits 1 when one is missing", "install links everything with dated backups and is idempotent", "--dry-run changes nothing", "--with-config merges tmux and settings idempotently with a backup", "--uninstall removes only repo links and the source-file line"], "modelTier": "standard"}
```

---

### Task 5: Portability and repo hygiene

**Goal:** Remove the macOS-only browser launch and ignore agent worktrees.

**Files:**
- Modify: `bin/tmux-dash` (the `open)` case), `.gitignore`

**Acceptance Criteria:**
- [ ] `tmux-dash` opens the URL with `open` on macOS, `xdg-open` when that exists, and otherwise only prints it (exit 0).
- [ ] `.gitignore` contains `.claude/worktrees/`.

**Verify:** `grep -n 'xdg-open' bin/tmux-dash && grep -nx '.claude/worktrees/' .gitignore` → one match each

**Steps:**

- [ ] **Step 1: Edit `bin/tmux-dash`**, replacing the `open)` case with:

```zsh
  open)   start; url
          if (( $+commands[open] )); then open "$(url)"
          elif (( $+commands[xdg-open] )); then xdg-open "$(url)" >/dev/null 2>&1
          fi ;;
```

- [ ] **Step 2: Append** `.claude/worktrees/` to `.gitignore`.
- [ ] **Step 3: Run both suites** → pass.
- [ ] **Step 4: Commit** — `fix(tmux-dash): open the board with xdg-open on Linux; ignore agent worktrees`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/tmux-dash", ".gitignore"], "verifyCommand": "grep -n 'xdg-open' bin/tmux-dash && grep -nx '.claude/worktrees/' .gitignore", "acceptanceCriteria": ["tmux-dash uses open, then xdg-open, else prints", ".gitignore ignores .claude/worktrees/"], "modelTier": "mechanical"}
```

---

### Task 6: CI on macOS and Linux

**Goal:** GitHub Actions runs both suites and `install.sh --check` on every push and PR, on `macos-latest` and `ubuntu-latest`.

**Files:**
- Create: `.github/workflows/test.yml`

**Acceptance Criteria:**
- [ ] The workflow installs tmux, ttyd, fzf, jq and zsh (brew on macOS, apt on Ubuntu) and runs `python3 -m unittest discover -s board/tests` and `zsh tools/tests/run-all.zsh`.
- [ ] A push of the branch shows both jobs green in `gh run list --branch <branch>`; any Linux-only failure is fixed in the scripts, not skipped in CI.

**Verify:** `gh run list --branch <branch> --limit 1 --json conclusion -q '.[0].conclusion'` → `success`

**Steps:**

- [ ] **Step 1: Write the workflow** with a matrix `os: [macos-latest, ubuntu-latest]`, `actions/checkout@v4`, `actions/setup-python@v5` (3.12), an install step per OS, then the two test commands and `./install.sh --check || true` (claude is not on CI runners, so the check is informational there).
- [ ] **Step 2: Push the branch** (only after the user approves pushing) and watch with `gh run watch`.
- [ ] **Step 3: Fix any Linux failure** with `superpowers-extended-cc:systematic-debugging`, one commit per root cause.
- [ ] **Step 4: Commit** — `ci: run board and toolkit suites on macOS and Linux`, with your harness's attribution trailer.

```json:metadata
{"files": [".github/workflows/test.yml"], "verifyCommand": "gh run list --limit 1 --json conclusion -q '.[0].conclusion'", "acceptanceCriteria": ["workflow runs both suites on macos-latest and ubuntu-latest", "latest run concludes success"], "modelTier": "standard"}
```

---

### Task 7: Rewrite INSTALL.md around `install.sh`

**Goal:** `docs/INSTALL.md` describes the one-command install. The manual steps move into an appendix, and the "planned, not applied" notes in all three docs are removed.

**Files:**
- Modify: `docs/INSTALL.md`, `docs/CUSTOMIZATION.md` (the `TC_TMUX` row, the new `TTYD_BIN`), `docs/ARCHITECTURE.md` (repository layout: `config/`, `install.sh`), `README.md`

**Acceptance Criteria:**
- [ ] INSTALL.md's main path is: prerequisites, `git clone`, `./install.sh --check`, `./install.sh --with-config`, verify.
- [ ] `grep -n 'not applied\|refactor plan' docs/*.md README.md` returns nothing.
- [ ] The CUSTOMIZATION env table lists `TTYD_BIN`, and the `TC_TMUX` row no longer lists exceptions.

**Verify:** `grep -c 'install.sh' docs/INSTALL.md` → ≥ 4, and the grep in criterion 2 → no output

**Steps:**

- [ ] **Step 1: Edit the docs** as listed.
- [ ] **Step 2: Commit** — `docs: install with install.sh`, with your harness's attribution trailer.

```json:metadata
{"files": ["docs/INSTALL.md", "docs/CUSTOMIZATION.md", "docs/ARCHITECTURE.md", "README.md"], "verifyCommand": "grep -c 'install.sh' docs/INSTALL.md", "acceptanceCriteria": ["INSTALL main path uses install.sh", "no 'not applied' or 'refactor plan' notes remain", "env table lists TTYD_BIN; TC_TMUX row has no exceptions"], "modelTier": "mechanical"}
```

---

### Task 8: End-to-end install check against a fresh HOME and the real install

**Goal:** Prove the install works from nothing and does not disturb the author's existing install.

**Files:**
- Create: `tools/tests/test_e2e_install.zsh`

**Acceptance Criteria:**
- [ ] Fresh state: in a scratch `HOME` with only `PATH` tools, `install.sh --with-config` and then `dev <scratch repo>` (with `DEV_NO_ATTACH=1`, `DEV_CLAUDE_CMD=true`, a private tmux socket) create session `<repo>` and `<repo>-bg`, and `tmux-ctl run tests "echo ok"` from the session returns `ok` / `[exit 0]`.
- [ ] Real state, read-only: `./install.sh --check --dry-run` against the real `HOME` prints `unchanged` for every link that already points into `~/agent-board` and proposes no backup of any existing file. Its output is saved in the task report.
- [ ] Aged state: the scratch run is repeated with a pre-seeded `TC_STATE` holding a `runs-<repo>.jsonl` and a feed log from a previous day with two agents, and the board's `activity.runs()` and `activity.feed()` still return them in order.

**Verify:** `zsh tools/tests/test_e2e_install.zsh` → `ALL PASS`; `./install.sh --check --dry-run | grep -vc unchanged` → only dependency lines

**Steps:**

- [ ] **Step 1: Write the test** with the three blocks above. Seed the aged state by copying content-stripped lines in the format `tmux-ctl run` and `bash-mirror.sh` write, with timestamps from yesterday.
- [ ] **Step 2: Run it** with `tmux-ctl run tests "zsh tools/tests/test_e2e_install.zsh"`; fix failures through `systematic-debugging`.
- [ ] **Step 3: Run the read-only real-state check** and paste its output into the report.
- [ ] **Step 4: Commit** — `test(install): end-to-end install from a fresh HOME`, with your harness's attribution trailer.

```json:metadata
{"files": ["tools/tests/test_e2e_install.zsh"], "verifyCommand": "zsh tools/tests/test_e2e_install.zsh", "acceptanceCriteria": ["fresh-HOME install + dev + tmux-ctl run works", "real HOME dry-run shows every existing link unchanged and no backups", "aged pre-seeded state still reads back in order"], "modelTier": "standard"}
```

## Order and dependencies

Task 1 → Task 2 → Task 3 → Task 4 → Task 8. Task 5 is independent. Task 6 follows Task 4 (it runs `install.sh --check`). Task 7 is last.
