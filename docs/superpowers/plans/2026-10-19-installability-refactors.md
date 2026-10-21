# Project-Scoped Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: planned, not applied.** Written alongside `docs/INSTALL.md`. Nothing below has been implemented.

**Goal:** Engineers who already use Claude Code and tmux can install agent-board with one command, and nothing it installs changes their other Claude Code or tmux sessions. Every agent-board setting, hook, skill, agent type and tmux hook applies only to sessions agent-board starts.

**Architecture:**
- **Claude Code.** Every Claude that agent-board starts (lead, worker, relay, board restart) is launched with `--settings <repo>/claude/settings.json` and `--plugin-dir <repo>/claude/plugin`. The settings file carries agent teams and the `AGENT_BOARD=1` marker. The plugin carries the hooks, skills and agent types. Hooks registered the old global way step aside in agent-board sessions, so each hook runs exactly once.
- **tmux.** agent-board gets its own tmux server (`-L agent-board -f <repo>/config/tmux.conf`), so its hooks, bindings and options never reach the user's tmux server.
- **Files.** Scripts find their files relative to the repo and find tools on `PATH`. The only install footprint is one `agent-board` command, plus state under `~/.local/state/agent-board/`.

**Tech Stack:** zsh 5.9, tmux 3.x, Python 3.9+ stdlib, Claude Code ≥ 2.1.303 (`--settings`, `--plugin-dir`), GitHub Actions.

**Spec:** none separate. The requirement is the user's (below). The gaps are listed in "Why" and in `docs/INSTALL.md` → "Known gaps in the scoped install".

### Why

Today's install and its interference with an existing setup:
1. **Global Claude Code settings.** Hooks, `env` (agent teams) and `teammateMode` are registered in `~/.claude/settings.json`. The scoped install in INSTALL.md moves them to a `--settings` file for the lead, but workers (`tmux-ctl agent` types a bare `claude -w …`) don't get it. Whether teammates inherit `--settings` hooks is unverified. (Verified on 2026-10-19: a `--settings` file's hooks and `env` apply to the session started with it; teammates are started with the lead's settings `env` on their command line.)
2. **Global skills and agents.** `tmux-orchestrator`, `handoff` and `effort-*` live in `~/.claude/skills|agents`, where every session sees them. The `tmux-orchestrator` skill even triggers in any tmux session.
3. **Global tmux hooks.** `after-split-window` and `session-closed` are set on the user's own tmux server.
4. **Fixed command names and paths.** `dev`, `tmux-ctl` and the other commands are linked into `~/.local/bin`. Scripts hardcode `~/.local/bin/{tmux,ttyd,fzf,tmux-ctl,tmux-web-attach,tmux-dev-layout,dev}`, `~/.local/share/tmux-dash` and `~/.claude/{hooks,orchestrator.md,worker.md}`.
5. **State in `~/.claude`.** Ideas (`~/.claude/ideas`) and handoffs (`~/.claude/handoffs`) sit inside the user's Claude Code config folder.
6. **No install, check or uninstall script, and no CI.** `open` in `tmux-dash` is macOS-only.

## Global Constraints

- **Zero interference.** After install, and after a full agent-board session, these are byte-identical to before: `~/.claude/settings.json`, `~/.claude/settings.local.json`, `~/.claude/skills/`, `~/.claude/agents/`, `~/.claude/CLAUDE.md`, `~/.tmux.conf`. The output of `tmux show-hooks -g` and `tmux list-keys` on the user's default tmux server is unchanged too. Task 9 tests exactly this list.
- **No Claude Code config outside the repo.** agent-board's Claude config reaches a session only through `--settings` and `--plugin-dir` on that session's command line.
- **The author's existing global install keeps working** until its owner runs `install.sh --migrate`. Every task stays backward compatible with it. Edits to `claude/*.md` and `bin/*` are made in a worktree and merged, never on the live `~/agent-board` checkout (it is symlinked live).
- **`install.sh` is cautious.** It never overwrites a real file, never repoints a symlink that points into a different checkout (it prints `would repoint X: A -> B`, and `--force-relink` is required), and never touches anything under `~/.claude/`.
- **Isolated tests.** Tests that touch tmux use `tools/tests/lib.zsh` (private socket, `-f /dev/null`). Tests that install use a scratch `HOME` from `mktemp -d`.
- **Green after every task:** `python3 -m unittest discover -s board/tests` and `zsh tools/tests/run-all.zsh`.
- **Python 3.9 compatible.** No `match`, no `X | None`, no `tomllib`.
- **Commits:** conventional commits with scope (`refactor(tmux-ctl): …`, `feat(install): …`), each ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- "If there are any refactors needed to ease installability those should not be applied only planned." (2026-10-19)
- "the engineers who will use this repo are already running claude code. I dont want this repo to interfere with that. All of the customizations should only apply to this project" (2026-10-19)
- Interpretation recorded by the plan author: "this project" means sessions started by agent-board (`dev`, the board, `tmux-ctl agent`, relay). Plain `claude` sessions anywhere else, including in a repo that also has an agent-board session, get nothing from agent-board.

---

### Task 1: Spike: what a lead's session config passes on to teammates

**Goal:** Find out whether a teammate spawned by a lead started with `--settings S --plugin-dir P` gets S's hooks and P's hooks, skills and agents. Record the answer and the fallback the next tasks use.

**Files:**
- Create: `docs/superpowers/specs/2026-10-20-teammate-config-inheritance.md` (use the execution date in the name)

**Acceptance Criteria:**
- [ ] The doc has the sections `## Setup`, `## Observations`, `## Answer`, `## Fallback chosen`.
- [ ] Observations cite captured evidence for each of: the teammate pane's `pane_start_command` (copied with `tmux display -p -t <pane> '#{pane_start_command}'`); a marker file written by a `PreToolUse` hook from S, fired by a teammate tool call; and the same from a hook in P.
- [ ] The answer is one of: "inherits both", "inherits only env", "inherits nothing". The fallback for that answer is named concretely (for example: hooks are registered in the plugin and gated on `AGENT_BOARD=1` because env is inherited; or, if nothing is inherited, the `after-split-window` handler respawns the teammate with the flags added).

**Verify:** `grep -c '^## ' docs/superpowers/specs/2026-10-20-teammate-config-inheritance.md` → `4`

```json:metadata
{"files": ["docs/superpowers/specs/2026-10-20-teammate-config-inheritance.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/specs/2026-10-20-teammate-config-inheritance.md", "acceptanceCriteria": ["four required sections", "pane_start_command and hook-marker evidence for S and P", "answer is one of three values with a concrete fallback"], "modelTier": "frontier"}
```

---

### Task 2: Every launcher passes the agent-board session config

**Goal:** The lead, workers, relay and board restart all start Claude with `--settings <repo>/claude/settings.json` and with `<repo>/bin` on `PATH`. Hooks run exactly once per tool call, whether they are registered the scoped way, the legacy global way, or both. This closes the "workers have no hooks" gap and makes the user's wrapper from INSTALL.md §4 unnecessary.

**Files:**
- Create: `claude/settings.json` (`env`: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `AGENT_BOARD=1`; `teammateMode: auto`; the three hooks as `"$AGENT_BOARD_REPO/claude/hooks/<name>.sh" --scoped`, with the shell expanding the variable when the hook runs; no absolute paths; Task 3 moves the hooks into the plugin)
- Create: `bin/_ab_claude.zsh` (sourced helper: `ab_claude_args` prints the flags; `ab_path` prints `<repo>/bin:$PATH`)
- Modify: `bin/claude-orchestrator` (exports `PATH="$(ab_path)"` and adds the flags), `bin/tmux-ctl` (`agent` case: typed line is `PATH=… claude -w … <flags> …`), `board/relay.py` (`respawn`)
- Modify: `claude/hooks/kill-guard.sh`, `claude/hooks/bash-mirror.sh`, `claude/hooks/artifact-register.sh`. The dedupe rule: run when called with `--scoped`. Without `--scoped` (the legacy global registration), exit 0 if `AGENT_BOARD=1`, because the scoped registration covers that session, and otherwise run as today. The manual `--path` mode of `artifact-register.sh` always runs.
- Test: `tools/tests/test_prompt_argv.zsh` (extend), `tools/tests/test_hook_gate.zsh`, `board/tests/test_relay.py` (extend)

**Acceptance Criteria:**
- [ ] `claude-orchestrator` execs `claude … --settings <repo>/claude/settings.json …` with `<repo>/bin` first on `PATH`, where `<repo>` is `${0:A:h:h}`. Checked with a stub `claude` on `PATH` that prints its argv and `$PATH`.
- [ ] `TC_AGENT_DRYRUN=1 tmux-ctl agent w --force "a b"` prints a command line containing `--settings <repo>/claude/settings.json` and `PATH=<repo>/bin:`.
- [ ] `relay.respawn()` still types `claude-orchestrator …`, so the flags come from `claude-orchestrator` itself. `test_relay.py` asserts the typed text is unchanged.
- [ ] On real fixtures from `tools/tests/fixtures/`, `bash-mirror.sh` writes exactly one feed entry in each of these cases:
  - `--scoped` with `AGENT_BOARD=1`;
  - no flag without `AGENT_BOARD` (legacy);
  - both registrations firing, simulated as two calls: no flag and `--scoped`, with `AGENT_BOARD=1`.
  `artifact-register.sh` writes exactly one manifest line in the same cases, and kill-guard blocks exactly once.
- [ ] `artifact-register.sh --path F` (used by `tmux-ctl artifact` and board saves) records regardless of `AGENT_BOARD`.

**Verify:** `zsh tools/tests/test_hook_gate.zsh && zsh tools/tests/test_prompt_argv.zsh && python3 -m unittest board.tests.test_relay` → `ALL PASS`, `ALL PASS`, `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** `test_hook_gate.zsh` runs each hook twice on `fixtures/ok.json` and `fixtures/tmuxctl.json` (with and without `AGENT_BOARD=1`) inside `tt_setup`, and checks the state dir. Extend `test_prompt_argv.zsh` with a stub `claude` that writes `"$@"` to a file, and assert the `--settings` path.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** `bin/_ab_claude.zsh`:

```zsh
# _ab_claude.zsh — sourced. The flags and PATH every agent-board Claude starts with.
AB_REPO="${${(%):-%x}:A:h:h}"
ab_claude_args() { print -r -- "--settings ${(q)AB_REPO}/claude/settings.json" }
ab_path() { print -r -- "$AB_REPO/bin:$PATH" }
```

`claude-orchestrator` sources it, runs `export PATH="$(ab_path)" AGENT_BOARD_REPO="$AB_REPO"`, and adds `${(z)$(ab_claude_args)}` before `"$@"`. In `tmux-ctl agent`, the typed line becomes `PATH=${(q)$(ab_path)} AGENT_BOARD_REPO=${(q)AB_REPO} claude -w … -n … $(ab_claude_args)${rules} ${(q)task}`. Each hook starts with the dedupe rule from Files; in `artifact-register.sh` that check comes after argument parsing and applies only when `manual=0`. Whether `AGENT_BOARD_REPO` reaches teammates is part of Task 1's evidence. If it doesn't, Task 3's plugin (`${CLAUDE_PLUGIN_ROOT}`) is the path that covers teammates.
- [ ] **Step 4: Run both suites** → pass.
- [ ] **Step 5: Commit** — `feat(claude): agent-board session config on every launcher; hooks gated on AGENT_BOARD`, with your harness's attribution trailer.

```json:metadata
{"files": ["claude/settings.json", "bin/_ab_claude.zsh", "bin/claude-orchestrator", "bin/tmux-ctl", "board/relay.py", "claude/hooks/kill-guard.sh", "claude/hooks/bash-mirror.sh", "claude/hooks/artifact-register.sh", "tools/tests/test_prompt_argv.zsh", "tools/tests/test_hook_gate.zsh", "board/tests/test_relay.py"], "verifyCommand": "zsh tools/tests/test_hook_gate.zsh && zsh tools/tests/test_prompt_argv.zsh && python3 -m unittest board.tests.test_relay", "acceptanceCriteria": ["claude-orchestrator passes --settings <repo>/claude/settings.json with <repo>/bin first on PATH", "tmux-ctl agent passes the same and PATH", "relay still types claude-orchestrator", "each hook fires exactly once for scoped, legacy and both registrations", "manual artifact registration always runs"], "modelTier": "standard"}
```

---

### Task 3: A session-only plugin for hooks, skills and agent types

**Goal:** Ship the hooks, the `tmux-orchestrator` and `handoff` skills and the `effort-*` agent types as a plugin in `claude/plugin/`. Every agent-board launcher loads it with `--plugin-dir`, and nothing is installed into `~/.claude`.

**Files:**
- Create: `claude/plugin/.claude-plugin/plugin.json` (`{"name": "agent-board", "version": "0.1.0", "description": "…"}`)
- Create: `claude/plugin/hooks/hooks.json` (the three hooks, commands as `"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.sh" --scoped`)
- Move: `claude/hooks/{kill-guard,bash-mirror,artifact-register}.sh` → `claude/plugin/scripts/`. `claude/hooks/<name>.sh` stays as a git-tracked relative symlink to the new location, so the legacy `~/.claude/hooks` links and `board/artifacts.py` keep working. The plugin is then self-contained even if Claude Code copies it into a cache. The hook registration moves out of `claude/settings.json` into `hooks.json`.
- Create: `claude/plugin/skills/tmux-orchestrator/SKILL.md`, `claude/plugin/skills/handoff/SKILL.md` (+ its `agents/`), copied from the author's live copies with home paths replaced by `~`, and with `~/.claude/handoffs` replaced by the Task 6 state path
- Create: `claude/plugin/agents/effort-{low,medium,high}.md`
- Modify: `bin/_ab_claude.zsh` (add `--plugin-dir ${AB_REPO}/claude/plugin`)
- Modify: `claude/orchestrator.md` (skill table: `task-observer` and `gitlab-ci-loop` rows prefixed "If installed:"; plugin skills named `agent-board:tmux-orchestrator`, `agent-board:handoff`), in a worktree
- Test: `tools/tests/test_plugin.zsh`

**Acceptance Criteria:**
- [ ] `claude plugin validate claude/plugin` exits 0, if that subcommand exists in the installed version. Otherwise `python3 -c` loads `plugin.json` and `hooks.json` as JSON.
- [ ] `grep -rn '/Users/' claude/` returns nothing.
- [ ] A headless probe (`claude -p --model haiku $(ab_claude_args) "…"` in a scratch git repo, with a probe hook variant writing a marker) shows the plugin's hook fired. A plain `claude -p` in the same folder shows it did not. The probe passes with the plugin directory copied elsewhere and loaded from the copy, which proves it has no `..` paths.
- [ ] Every skill and agent name in `claude/orchestrator.md` and `claude/worker.md` is shipped in the plugin, comes from superpowers-extended-cc, or is marked "If installed".

**Verify:** `zsh tools/tests/test_plugin.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write `test_plugin.zsh`** with the four checks. The probe check is skipped (printed as `skip - no claude`) when `claude` is not on `PATH`, as on CI.
- [ ] **Step 2: See it fail.**
- [ ] **Step 3: Create the plugin files.** Read each copied skill in full before committing it. If Task 1's answer is "inherits nothing", put the hooks in `claude/settings.json` instead and follow the Task 1 fallback.
- [ ] **Step 4: Run the test and both suites** → pass.
- [ ] **Step 5: Commit** — `feat(claude): session-only agent-board plugin with hooks, skills and agent types`, with your harness's attribution trailer.

```json:metadata
{"files": ["claude/plugin/.claude-plugin/plugin.json", "claude/plugin/hooks/hooks.json", "claude/plugin/skills/tmux-orchestrator/SKILL.md", "claude/plugin/skills/handoff/SKILL.md", "claude/plugin/agents/effort-low.md", "claude/plugin/agents/effort-medium.md", "claude/plugin/agents/effort-high.md", "bin/_ab_claude.zsh", "claude/orchestrator.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["plugin validates or its JSON loads", "no /Users/ paths under claude/", "plugin hook fires only in sessions launched with ab_claude_args", "every referenced skill/agent is shipped, from superpowers, or marked If installed"], "modelTier": "standard"}
```

---

### Task 4: A dedicated tmux server for agent-board

**Goal:** agent-board runs on its own tmux server (`-L agent-board`, config `<repo>/config/tmux.conf`). Its hooks, options and bindings never touch the user's default server, and the user's `~/.tmux.conf` needs no edit.

**Files:**
- Create: `config/tmux.conf`, `bin/_tc_bins.zsh` (the resolver), `tools/tests/test_dedicated_server.zsh`
- Modify: every `bin/` script that runs tmux, `claude/hooks/bash-mirror.sh`, `claude/hooks/artifact-register.sh`, `board/server.py`, `board/paneclass.py`

**Constraints:**
- One resolver decides the tmux command for every caller: `bin/` scripts, hook scripts, `board/server.py`, `board/paneclass.py`, `tmux-web-attach`, and commands run from inside the server by `run-shell` and hooks. `TC_TMUX` / `TMUX_DASH_TMUX_ARGS` remain as overrides.
- `config/tmux.conf` holds the `after-split-window` and `session-closed` hooks, `monitor-bell`, `bell-action`, the passthrough and extended-keys settings, and the bindings from INSTALL.md §5. It must not `source` the user's `~/.tmux.conf`. An optional `~/.config/agent-board/tmux.local.conf` is sourced if present, for personal bindings.
- Attaching works from inside and outside the user's own tmux. Inside, `dev` must not nest silently: it switches the client when it is on the agent-board server, and otherwise tells the user the attach command (or opens a new terminal tab where possible).
- The author's existing sessions on the default server keep working until migrated. Resolver precedence: `TC_TMUX` → `$TMUX`'s socket when set (a command running inside any tmux server talks to that server) → `-L agent-board`. Only commands started outside tmux (`dev`, `tmux-dash`) pick the dedicated server.
- Consider doing this in two commits: the resolver with socket detection first, then the dedicated server and `config/tmux.conf`.

**Acceptance Criteria:**
- [ ] After `dev <scratch repo>` and a teammate split (simulated as in `test_teammate_window.zsh`), `tmux -L default show-hooks -g` and `tmux -L default list-keys` print the same as before the run (diffed).
- [ ] `tmux -L agent-board show-hooks -g` lists both hooks.
- [ ] The board lists sessions on the agent-board server, and its terminals attach to them.
- [ ] Legacy: with a session on a separate private socket standing in for the user's default server, and `$TMUX` pointing at it, `tmux-ctl run tests "echo ok"`, `tmux-teammate-window` and `bash-mirror.sh` all act on that server, not on `-L agent-board`.
- [ ] Nesting: `dev <repo>` run from a pane on a different tmux server does not attach inside it. It prints the attach command (`tmux -L agent-board attach -t <name>`) and exits 0. Run from a pane on the agent-board server, it switches the client.
- [ ] All existing zsh tests pass with the harness's private socket standing in for `-L agent-board`.

**Verify:** `zsh tools/tests/test_dedicated_server.zsh` → `ALL PASS`

```json:metadata
{"files": ["config/tmux.conf", "bin/_tc_bins.zsh", "bin/dev", "bin/tmux-ctl", "bin/tmux-dev-layout", "bin/tmux-session-closed", "bin/tmux-dash", "bin/tmux-web-attach", "bin/tmux-jump", "bin/tmux-teammate-window", "bin/tmux-agent-cleanup", "claude/hooks/bash-mirror.sh", "claude/hooks/artifact-register.sh", "board/server.py", "board/paneclass.py", "tools/tests/test_dedicated_server.zsh"], "verifyCommand": "zsh tools/tests/test_dedicated_server.zsh", "acceptanceCriteria": ["default server hooks and keys unchanged after a full dev session", "agent-board server has both hooks", "board lists and attaches agent-board sessions", "existing zsh tests pass"], "modelTier": "frontier"}
```

---

### Task 5: Repo-relative paths, PATH lookup, one `agent-board` command

**Goal:** No script depends on files linked into `~/.local/bin`, `~/.local/share` or `~/.claude`. The install footprint is one command, `agent-board <subcommand>`, that dispatches to `bin/*`.

**Files:**
- Create: `bin/agent-board` (dispatcher: `agent-board dev|ctl|dash|jump|cleanup|help`; `ctl` maps to `tmux-ctl`)
- Modify: `bin/_tc_bins.zsh` (from Task 4: `tc_bin <tool> <override-var>` = override → `PATH` → `~/.local/bin/<tool>`)
- Modify: `bin/tmux-ctl` (typed `_done` callback uses `${(q)${0:A}}`; `idea`/`relay`/`artifact` use `$REPO/board/…` and `$REPO/claude/hooks/…`; worker rules from `$REPO/claude/worker.md`, with a user override at `~/.config/agent-board/worker.md`)
- Modify: `bin/tmux-dash` (`APP="${0:A:h:h}/board"`, `tmux-web-attach` from `${0:A:h}`), `bin/dev` (`TC_LAYOUT` default `${0:A:h}/tmux-dev-layout`), `bin/claude-orchestrator` (rules from `$REPO/claude/orchestrator.md`, user override at `~/.config/agent-board/orchestrator.md`)
- Modify: `board/server.py` (`TMUX_CTL`, `DEV` from `HERE.parent / "bin"`), `board/artifacts.py` (`HOOK = HERE.parent / "claude/hooks/artifact-register.sh"`)
- Test: `tools/tests/test_repo_paths.zsh`, `board/tests/test_artifacts.py`

**Acceptance Criteria:**
- [ ] `grep -rnE '\.local/(bin|share)|\.claude/(hooks|orchestrator|worker)' bin/ board/*.py claude/hooks/` matches only the documented legacy fallbacks in `_tc_bins.zsh` and `claude-orchestrator`.
- [ ] In a scratch `HOME` with no `~/.local` and no `~/.claude`, `tmux-ctl run shell "echo hi"` (run in `tt_setup`) prints `hi` and `[exit 0]`, and `TC_AGENT_DRYRUN=1 tmux-ctl agent w --force "a b"` names `$REPO/claude/worker.md`.
- [ ] `agent-board help` lists the subcommands. `agent-board dev --help`, `agent-board ctl help` and `agent-board dash status` each run the matching script.
- [ ] Both suites pass.

**Verify:** `zsh tools/tests/test_repo_paths.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write `test_repo_paths.zsh`** for criteria 2 and 3, with `HOME` set to a `mktemp -d`.
- [ ] **Step 2: See it fail** (the run times out on `~/.local/bin/tmux-ctl: no such file`).
- [ ] **Step 3: Implement the edits listed in Files.** The dispatcher:

```zsh
#!/usr/bin/env zsh
# agent-board <command> [args] — the single entry point; commands live next to this file.
emulate -L zsh
here="${0:A:h}"
case "$1" in
  dev)     shift; exec "$here/dev" "$@" ;;
  ctl)     shift; exec "$here/tmux-ctl" "$@" ;;
  dash)    shift; exec "$here/tmux-dash" "$@" ;;
  jump)    shift; exec "$here/tmux-jump" "$@" ;;
  cleanup) shift; exec "$here/tmux-agent-cleanup" "$@" ;;
  *)       print "usage: agent-board dev|ctl|dash|jump|cleanup [args]" ;;
esac
```

  Agents keep calling `tmux-ctl` by name: the launchers put `<repo>/bin` first on `PATH` (Task 2's `ab_path`), and teammates and their Bash calls inherit it. Settings `env` values are not shell-expanded, so the settings file is never used for `PATH`.
- [ ] **Step 4: Run both suites** → pass.
- [ ] **Step 5: Commit** — `refactor(bin): repo-relative paths and a single agent-board command`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/agent-board", "bin/_tc_bins.zsh", "bin/tmux-ctl", "bin/tmux-dash", "bin/dev", "bin/claude-orchestrator", "board/server.py", "board/artifacts.py", "tools/tests/test_repo_paths.zsh", "board/tests/test_artifacts.py"], "verifyCommand": "zsh tools/tests/test_repo_paths.zsh", "acceptanceCriteria": ["no live-layout paths outside documented legacy fallbacks", "tmux-ctl run and agent work with an empty HOME", "agent-board dispatcher runs each subcommand", "both suites pass"], "modelTier": "standard"}
```

---

### Task 6: State out of `~/.claude`; `install.sh` with check, uninstall and migrate

**Goal:** agent-board state and config move out of `~/.claude`: ideas and handoffs go to `~/.local/state/agent-board/{ideas,handoffs}`, still reading the old `~/.claude/ideas` when the new folder is empty, and usage alert thresholds go to `~/.config/agent-board/usage-alerts.json`, falling back to `~/.claude/usage-alerts.json`. `./install.sh` makes the single `agent-board` link, checks dependencies, and migrates an existing global install.

**Files:**
- Modify: `board/ideas.py` (`ideas_dir()`: `TC_IDEAS_DIR` → `~/.local/state/agent-board/ideas`; on first write, copy any `~/.claude/ideas/<project>.md` across, leaving the original in place)
- Modify: `claude/hooks/artifact-register.sh` (`handoff` kind also for `~/.local/state/agent-board/handoffs/`)
- Modify: `board/usage.py` (`ALERTS_PATH`: `~/.config/agent-board/usage-alerts.json` if it exists, else the legacy `~/.claude/usage-alerts.json`), with a test in `board/tests/test_usage.py`
- Create: `install.sh`, `tools/install_lib.py` (the settings and tmux "remove what agent-board added" logic, used only by `--migrate`)
- Test: `tools/tests/test_install.zsh`, `tools/tests/test_install_lib.py` (run by `python3 -m unittest discover -s tools/tests -p 'test_*.py'`, added to the documented test commands), `board/tests/test_ideas.py`

**Acceptance Criteria:**
- [ ] `./install.sh --check` prints one line per dependency (zsh, tmux, ttyd, fzf, python3 ≥ 3.9, jq, git, claude ≥ 2.1.303 with `--settings` and `--plugin-dir` in `claude --help`) as `ok <path>` or `MISSING <name>`, and exits 1 if any is missing.
- [ ] `./install.sh` in a scratch `HOME` creates exactly one link, `~/.local/bin/agent-board`, and a second run prints `unchanged`. If that path is a symlink into a different checkout, it prints `would repoint …` and exits 1 unless `--force-relink` is given. A real file there makes it exit 1 untouched.
- [ ] `--dry-run` prints the plan and changes nothing (`find "$H" -newer "$marker"` is empty).
- [ ] `--uninstall` removes only `~/.local/bin/agent-board`, and only if it links into this repo.
- [ ] `--migrate` on a scratch `HOME` seeded with the author's global layout (the hook entries in `~/.claude/settings.json`, the `~/.local/bin/<script>` links into the repo, the `~/.claude/{orchestrator,worker}.md` and hook links, the `~/.tmux.conf` hook lines) does the following:
  - removes exactly those entries and links;
  - backs up `settings.json` and `.tmux.conf` to `*.bak-YYYYMMDD` first;
  - leaves every other key and line byte-identical (diffed against the seed minus the removed lines);
  - prints each change it made.
- [ ] `--migrate` also retires the global copies of what the plugin now ships (Task 3), so agent-board sessions don't see each one twice: `~/.claude/skills/tmux-orchestrator/` (a directory), `~/.claude/skills/handoff` (removes only the link, never its `~/.agents/skills/handoff` target) and `~/.claude/agents/effort-{low,medium,high}.md`. Each is moved, not deleted, to `~/.local/state/agent-board/migrated-YYYYMMDD/` and printed. It acts only on entries that exist. `--keep-agents` leaves the three `effort-*` files in place, because plain `claude` sessions outside agent-board lose them otherwise and the migrate output says so.
- [ ] `install.sh` never writes under `~/.claude/` except in `--migrate`.
- [ ] `--repo DIR` makes `install.sh` treat `DIR` as the agent-board checkout instead of its own location, so a dry run from a worktree can judge the live `~/agent-board` links.
- [ ] Ideas: with only `~/.claude/ideas/p.md` present, `ideas.load("p")` returns its items. The first write creates `~/.local/state/agent-board/ideas/p.md` with the old items plus the new one, and leaves `~/.claude/ideas/p.md` byte-identical. `TC_IDEAS_DIR` still wins over both.
- [ ] Usage alerts: with both files present, `usage.thresholds()` reads `~/.config/agent-board/usage-alerts.json`. With only the legacy file present, it reads that one.
- [ ] Handoffs: `artifact-register.sh` gives kind `handoff` to a `.md` under `~/.local/state/agent-board/handoffs/` and still to one under `~/.claude/handoffs/` (`test_artifact_hook.zsh` has one case each).

**Verify:** `zsh tools/tests/test_install.zsh && python3 -m unittest discover -s tools/tests -p 'test_*.py'` → `ALL PASS`, `OK`

**Steps:**

- [ ] **Step 1: Write the tests.** The scratch `HOME` gets stub `tmux`/`ttyd`/`fzf`/`jq`/`claude` on `PATH`; the stub `claude --help` prints both flags. Write the migrate seed from the author's real config, with personal values replaced.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement** `ideas.py`'s new dir, `install.sh` (zsh; `REPO="${0:A:h}"`; every change goes through a `run_or_print` helper for `--dry-run`) and `install_lib.py`:
  - `strip_settings(path, commands)` drops hook entries whose `command` is in `commands`, drops `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` and `teammateMode` only with `--migrate-team-settings`, and writes through a temp file and `os.replace`;
  - `strip_tmux(path, patterns)` drops exactly the matching lines.
- [ ] **Step 4: Run the tests and both suites** → pass.
- [ ] **Step 5: Commit** — `feat(install): one-link install, dependency check, uninstall and migration from the global setup`, with your harness's attribution trailer.

```json:metadata
{"files": ["board/ideas.py", "board/usage.py", "board/tests/test_usage.py", "claude/hooks/artifact-register.sh", "install.sh", "tools/install_lib.py", "tools/tests/test_install.zsh", "tools/tests/test_install_lib.py", "board/tests/test_ideas.py"], "verifyCommand": "zsh tools/tests/test_install.zsh && python3 -m unittest discover -s tools/tests -p 'test_*.py'", "acceptanceCriteria": ["--check lists deps incl. claude flags, exits 1 if missing", "install makes only the agent-board link; idempotent; never repoints other checkouts without --force-relink", "--dry-run changes nothing", "--uninstall removes only its own link", "--migrate removes exactly the global agent-board entries with backups, rest byte-identical", "nothing under ~/.claude written outside --migrate"], "modelTier": "standard"}
```

---

### Task 7: Portability and repo hygiene

**Goal:** Remove the macOS-only browser launch, ignore agent worktrees and scrub the personal path from a test fixture.

**Files:**
- Modify: `bin/tmux-dash` (the `open)` case), `.gitignore`, `tools/tests/fixtures/ok.json`

**Acceptance Criteria:**
- [ ] `tmux-dash` opens the URL with `open` on macOS, `xdg-open` when that exists, and otherwise only prints it.
- [ ] `.gitignore` contains the line `.claude/worktrees/`.
- [ ] `grep -rn '/Users/' tools/tests/fixtures/` returns nothing, and `test_mirror.zsh` and `test_artifact_hook.zsh` still pass.

**Verify:** `grep -c xdg-open bin/tmux-dash; grep -cx '.claude/worktrees/' .gitignore; grep -rc '/Users/' tools/tests/fixtures/ | grep -v ':0$'` → `1`, `1`, no output

**Steps:**

- [ ] **Step 1:** Replace the `open)` case in `bin/tmux-dash`:

```zsh
  open)   start; url
          if (( $+commands[open] )); then open "$(url)"
          elif (( $+commands[xdg-open] )); then xdg-open "$(url)" >/dev/null 2>&1
          fi ;;
```

- [ ] **Step 2:** `print '.claude/worktrees/' >> .gitignore`
- [ ] **Step 3:** In `tools/tests/fixtures/ok.json`, replace `"/Users/francisco.ruiz/proj"` with `"/Users/dev/proj"`. Check that no test asserts on the old value: `grep -rn 'francisco' tools/tests/` returns nothing.
- [ ] **Step 4:** Run `zsh tools/tests/run-all.zsh` → every file `ALL PASS`.
- [ ] **Step 5: Commit** — `chore: xdg-open fallback, ignore agent worktrees, scrub fixture path`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/tmux-dash", ".gitignore", "tools/tests/fixtures/ok.json"], "verifyCommand": "zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["tmux-dash uses open, then xdg-open, else prints", ".gitignore ignores .claude/worktrees/", "no /Users/ paths in fixtures; hook tests pass"], "modelTier": "mechanical"}
```

---

### Task 8: CI on macOS and Linux

**Goal:** GitHub Actions runs all suites and `install.sh --check` on every push and PR, on `macos-latest` and `ubuntu-latest`.

**Files:**
- Create: `.github/workflows/test.yml`

**Acceptance Criteria:**
- [ ] A matrix job installs tmux, ttyd, fzf, jq and zsh (brew / apt) and Python 3.9, then runs `python3 -m unittest discover -s board/tests`, `python3 -m unittest discover -s tools/tests -p 'test_*.py'` and `zsh tools/tests/run-all.zsh`.
- [ ] `./install.sh --check` runs and its output is shown. It is allowed to fail only on `MISSING claude`.
- [ ] The latest run on the branch succeeds. A Linux-only failure is fixed in the scripts, not skipped.

**Verify:** `gh run list --branch <branch> --limit 1 --json conclusion -q '.[0].conclusion'` → `success`

**Steps:**

- [ ] **Step 1:** Write the workflow (`actions/checkout@v4`, `actions/setup-python@v5` with `python-version: "3.9"`, one install step per OS).
- [ ] **Step 2:** Push the branch, **only after the user approves the push**, then `gh run watch`.
- [ ] **Step 3:** Fix Linux failures through `superpowers-extended-cc:systematic-debugging`, one commit per root cause.
- [ ] **Step 4: Commit** — `ci: run all suites on macOS and Linux`, with your harness's attribution trailer.

```json:metadata
{"files": [".github/workflows/test.yml"], "verifyCommand": "gh run list --branch <branch> --limit 1 --json conclusion -q '.[0].conclusion'", "acceptanceCriteria": ["matrix runs all suites on macos and ubuntu with python 3.9", "install.sh --check runs, may fail only on MISSING claude", "latest branch run concludes success"], "modelTier": "standard"}
```

---

### Task 9: End-to-end non-interference check

**Goal:** Prove that installing and using agent-board leaves a pre-existing Claude Code and tmux setup exactly as it was, and that it migrates the author's real global install correctly.

**Files:**
- Create: `tools/tests/test_e2e_isolation.zsh`

**Acceptance Criteria:**
- [ ] **Scratch, seeded:**
  - Setup: a scratch `HOME` holds a user's own `~/.claude/settings.json` (with an unrelated hook), `~/.claude/skills/x/SKILL.md`, `~/.claude/agents/y.md`, a `~/.tmux.conf` with its own `after-split-window` hook, and a running default tmux server on a private socket name.
  - Run: `install.sh`, then `agent-board dev <scratch repo>` (`DEV_NO_ATTACH=1`, a stub `claude`), a `tmux-ctl run tests "echo ok"`, and a simulated teammate split.
  - Pass: `shasum -a 256` of every file under the seeded `~/.claude`, of `~/.tmux.conf` and of `~/.zshrc` is unchanged; `~/.local/bin` holds only `agent-board` plus what was seeded; the user server's `show-hooks -g` and `list-keys` match their pre-run capture; the run printed `ok` and `[exit 0]`.
- [ ] **Plain session unaffected:** where `claude` is available, a plain `claude -p --model haiku` run in the scratch repo with a seeded user `UserPromptSubmit` probe hook fires only the user's hook. No agent-board hook marker appears.
- [ ] **Scratch, aged:** the same `HOME` gets a `TC_STATE` seeded with yesterday's `runs-<repo>.jsonl` and a feed log with two agents' entries spanning midnight. `activity.runs()` and `activity.feed()` return them in order next to the new run.
- [ ] **Real state, read-only:** `./install.sh --repo ~/agent-board --migrate --dry-run` (from any checkout) against the real `HOME` prints exactly the agent-board entries of the author's install (the three hook commands, 10 `~/.local/bin` links, the 2 rules links, 3 hook links, 2 tmux hook lines, 3 tmux binding lines (W, f, D), the 2 global skills and 3 `effort-*` agents) and nothing else. The output is saved in the task report and diffed against that expected list.

**Verify:** `zsh tools/tests/test_e2e_isolation.zsh` → `ALL PASS`; `./install.sh --repo ~/agent-board --migrate --dry-run | diff - tools/tests/fixtures/expected-migrate-plan.txt` → no output

**Steps:**

- [ ] **Step 1:** Write the test with the scratch and aged blocks. Write `tools/tests/fixtures/expected-migrate-plan.txt` from a listing of the real install (`ls -l ~/.local/bin ~/.claude/hooks`, the hook commands in `~/.claude/settings.json`), with the home path replaced by `~`.
- [ ] **Step 2:** Run it with `tmux-ctl run tests "zsh tools/tests/test_e2e_isolation.zsh"`; fix failures through `systematic-debugging`.
- [ ] **Step 3:** Run the real-state dry run and diff it.
- [ ] **Step 4: Commit** — `test(install): end-to-end non-interference and migration check`, with your harness's attribution trailer.

```json:metadata
{"files": ["tools/tests/test_e2e_isolation.zsh", "tools/tests/fixtures/expected-migrate-plan.txt"], "verifyCommand": "zsh tools/tests/test_e2e_isolation.zsh", "acceptanceCriteria": ["seeded user ~/.claude and ~/.tmux.conf hashes unchanged after install and a full session", "user tmux server hooks and keys unchanged", "aged pre-seeded state reads back in order", "real-HOME migrate dry run equals the expected list"], "modelTier": "standard"}
```

---

### Task 10: Rewrite the docs for the scoped install

**Goal:** `docs/INSTALL.md` becomes: prerequisites, clone, `./install.sh --check`, `./install.sh`, verify. The interim wrapper, the `~/.config/agent-board/` files and the known-gaps table are removed, and the "planned, not applied" notes go from every doc.

**Files:**
- Modify: `docs/INSTALL.md`, `docs/ARCHITECTURE.md` (plugin, dedicated server, state paths, layout), `docs/CUSTOMIZATION.md` (env table: `TTYD_BIN`, override files under `~/.config/agent-board/`), `README.md`

**Acceptance Criteria:**
- [ ] `grep -rniE 'not applied|planned|refactor|known gaps' docs/INSTALL.md docs/ARCHITECTURE.md docs/CUSTOMIZATION.md README.md` returns nothing.
- [ ] INSTALL.md contains `install.sh --check`, `install.sh`, `install.sh --uninstall` and `install.sh --migrate`.
- [ ] No doc tells the reader to edit `~/.claude/settings.json`, `~/.claude/skills`, `~/.claude/agents` or `~/.tmux.conf`: `grep -n 'settings.json\|tmux.conf' docs/INSTALL.md` matches only the migrate section.

**Verify:** `grep -c 'install.sh' docs/INSTALL.md` → ≥ 4, and the grep in criterion 1 → no output

**Steps:**

- [ ] **Step 1:** Edit the docs as listed.
- [ ] **Step 2: Commit** — `docs: scoped install with install.sh`, with your harness's attribution trailer.

```json:metadata
{"files": ["docs/INSTALL.md", "docs/ARCHITECTURE.md", "docs/CUSTOMIZATION.md", "README.md"], "verifyCommand": "grep -c 'install.sh' docs/INSTALL.md", "acceptanceCriteria": ["no planned/refactor/known-gaps notes remain", "INSTALL covers check, install, uninstall, migrate", "no doc tells users to edit global Claude or tmux config outside migrate"], "modelTier": "mechanical"}
```

## Order and dependencies

Task 1 → 2 → 3 → 4 → 5 → 6 → 9, one chain, because Tasks 2–6 all edit `bin/tmux-ctl`, `bin/claude-orchestrator` and the hook scripts. Task 7 is independent. Task 8 follows Task 6. Task 10 is last. Tasks 2 and 3 apply Task 1's answer; if it is "inherits nothing", Task 3 Step 3's fallback applies.
