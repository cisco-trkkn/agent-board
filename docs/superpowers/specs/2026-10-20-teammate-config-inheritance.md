# Teammate config inheritance — spike

Date: 2026-10-19 · Plan: `docs/superpowers/plans/2026-10-19-installability-refactors.md`, Task 1.
Claude Code 2.1.303. Raw evidence: `.superpowers/sdd/2026-10-19-installability-refactors/spike/`.

Question: when a lead runs with `--settings S --plugin-dir P`, does a teammate it spawns get S's
hooks and `env`, and P's hooks and skills?

## Setup

Private tmux server, nothing from the user's config:

    ~/.local/bin/tmux -L abspike -f /dev/null new-session -d -s spike -c <worktree> -x 220 -y 50

Lead, typed into the `spike` pane. `ABSPIKE_EXPORTED` is a plain exported shell variable; it is the
probe for "does the lead's process environment reach teammates":

    unset $(env | grep -E "^CLAUDE" | cut -d= -f1); export ABSPIKE_EXPORTED=from-shell; claude --model haiku --settings <spike>/S.json --plugin-dir <spike>/P

**S.json** — settings `env` (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `ABSPIKE_SETTINGS_ENV=from-S`),
`teammateMode: tmux`, `permissions.allow: ["Bash(echo:*)"]`, and one `PreToolUse` hook on `Bash`:
`sh <spike>/hook-S.sh` (absolute path).

**P/** — a plugin: `.claude-plugin/plugin.json` (`name: abspike`), `hooks/hooks.json` with one
`PreToolUse` hook on `Bash`: `sh ${CLAUDE_PLUGIN_ROOT}/hook-P.sh`, and a skill
`skills/abspike-probe/SKILL.md` that replies "abspike-probe skill is loaded".

Both hooks call `hook-common.sh`, which appends to `markers/marker-S.txt` or `markers/marker-P.txt`:
the time, `TMUX_PANE`, the argv of the nearest `claude` ancestor, `ABSPIKE_EXPORTED`,
`ABSPIKE_SETTINGS_ENV`, `CLAUDE_PLUGIN_ROOT`, every `CLAUDE*`/`AGENT*`/`ABSPIKE*` variable, and the
hook's stdin JSON.

`watch-pane.sh` waited for a second pane and recorded its `pane_start_command`, `ps -t <tty>`,
`ps -E` (process environment) and `tmux show-environment` into `markers/pane-evidence.txt`.

**Round 1** (`send-prompt.sh`): the lead was asked to create a team with one teammate `probe`
(haiku) that runs `echo teammate-ran` and says whether a skill `abspike-probe` is available to it,
invoking it if so. The lead was told to run no Bash itself.

**Round 2** (`send-prompt2.sh`): before asking for a second teammate `probe2`, the controller set

    tmux -L abspike set-environment -g ABSPIKE_TMUX_GLOBAL from-tmux-global
    tmux -L abspike set-environment -t '=spike:' ABSPIKE_TMUX_SESSION from-tmux-session

to test whether the tmux server's global and session environment reach a teammate.

## Observations

### 1. How the teammate pane is started

`pane-evidence.txt`, pane `%1` (probe), copied with `tmux display -p -t %1 '#{pane_start_command}'`:

    "cd ~/agent-board/.claude/worktrees/create-remote-repo-push && env CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 NODE_EXTRA_CA_CERTS=~/.certs/netskope-bundle.pem ~/.local/share/claude/versions/2.1.303 --agent-id probe@session-460c3aeb --agent-name probe --team-name session-460c3aeb --agent-color blue --parent-session-id 460c3aeb-f11e-422e-bc1f-5483daedf896 --agent-type general-purpose --permission-mode auto --settings ~/agent-board/.claude/worktrees/create-remote-repo-push/.superpowers/sdd/2026-10-19-installability-refactors/spike/S.json --plugin-dir ~/agent-board/.claude/worktrees/create-remote-repo-push/.superpowers/sdd/2026-10-19-installability-refactors/spike/P --model haiku"

Pane `%2` (probe2) is identical apart from the agent name, colour and `--model`. So the lead copies
its own `--settings` and `--plugin-dir` onto every teammate's command line. The `env` prefix carries
exactly three variables: `CLAUDECODE`, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` and
`NODE_EXTRA_CA_CERTS`. Nothing else from the lead's process environment is on that line.

`ps -t ttys102` showed one Claude process on the pane (pid 49224) with that exact argv, so no wrapper
rewrote it. Its environment (`ps -E`, filtered to `ABSPIKE*`, `CLAUDE_PLUGIN*`,
`CLAUDE_CODE_EXPERIMENTAL*`, `CLAUDE_CODE_SETTINGS*`):

    pid 49224: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1

`ABSPIKE_EXPORTED` is absent: the lead's exported shell variable did not reach the teammate process.

### 2. The S hook fired in the teammate (settings hooks and `env` arrive)

`marker-S.txt`, first entry:

    === S 17:20:00 hookpid=49909 TMUX_PANE=%1
    claude_proc: ~/.local/share/claude/versions/2.1.303 --agent-id probe@session-460c3aeb … --settings …/spike/S.json --plugin-dir …/spike/P --model haiku
    ABSPIKE_EXPORTED=<unset> ABSPIKE_SETTINGS_ENV=from-S CLAUDE_PLUGIN_ROOT=<unset>
    env: ABSPIKE_SETTINGS_ENV=from-S CLAUDECODE=1 CLAUDE_CODE_CHILD_SESSION=1 … CLAUDE_CODE_SESSION_ID=d2875e88-7473-44af-81c3-1789c0025269 … CLAUDE_PROJECT_DIR=~/agent-board/.claude/worktrees/create-remote-repo-push
    stdin: {"session_id":"d2875e88-…","agent_type":"general-purpose",…,"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo teammate-ran",…}}

`TMUX_PANE=%1` and `session_id` d2875e88 (the teammate's session, not the lead's 460c3aeb) show
the hook ran inside the teammate for the teammate's own `echo teammate-ran`.

`ABSPIKE_SETTINGS_ENV=from-S` is present in the hook even though it is absent from the teammate
process's environment (Observation 1). The teammate's own Claude read S.json from its `--settings`
flag and applied `env` to its child processes. Settings `env` reaches teammates by re-reading the
file, not by environment inheritance.

### 3. The P hook fired in the teammate (plugin hooks arrive, with `CLAUDE_PLUGIN_ROOT`)

`marker-P.txt`, first entry:

    === P 17:20:00 hookpid=49910 TMUX_PANE=%1
    claude_proc: ~/.local/share/claude/versions/2.1.303 --agent-id probe@session-460c3aeb … --settings …/spike/S.json --plugin-dir …/spike/P --model haiku
    ABSPIKE_EXPORTED=<unset> ABSPIKE_SETTINGS_ENV=from-S CLAUDE_PLUGIN_ROOT=~/agent-board/.claude/worktrees/create-remote-repo-push/.superpowers/sdd/2026-10-19-installability-refactors/spike/P
    env: … CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/abspike-inline CLAUDE_PLUGIN_ROOT=…/spike/P CLAUDE_PROJECT_DIR=…

Same tool call (`tool_use_id` toolu_01F8wkmickUDRcyukcyp4VzT in both marker files), same second.
The hook command `sh ${CLAUDE_PLUGIN_ROOT}/hook-P.sh` resolved to the plugin directory passed with
`--plugin-dir`. Both hooks fired once each per tool call: two entries per file, one per teammate.

### 4. The plugin's skill is available to the teammate

The teammate transcript (`~/.claude/projects/…/d2875e88-7473-44af-81c3-1789c0025269.jsonl`) lists
the skill as `abspike:abspike-probe` in its available-skills list (plugin name as prefix), shows
`Launching skill: abspike:abspike-probe` with
`Base directory for this skill: …/spike/P/skills/abspike-probe`, and the teammate's report reads:

    1. Bash output of `echo teammate-ran`: `teammate-ran`
    2. Job 2: **yes**. `abspike:abspike-probe` is in my available-skills list.
    3. Verbatim skill output: `abspike-probe skill is loaded`

Agents (`agents/*.md`) were not probed; they load through the same plugin manifest as skills.

### 5. tmux global and session environment reach a teammate; the lead's shell exports do not

Round 2, `pane-evidence.txt`, pane `%2` (pid 60420):

    pid 60420: ABSPIKE_TMUX_GLOBAL=from-tmux-global
    pid 60420: ABSPIKE_TMUX_SESSION=from-tmux-session
    pid 60420: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
    --- tmux show-environment (session spike):
    ABSPIKE_TMUX_SESSION=from-tmux-session

and `marker-S.txt`, second entry (`TMUX_PANE=%2`, `echo teammate2-ran`):

    ABSPIKE_EXPORTED=<unset> ABSPIKE_SETTINGS_ENV=from-S CLAUDE_PLUGIN_ROOT=<unset>
    env: ABSPIKE_SETTINGS_ENV=from-S ABSPIKE_TMUX_GLOBAL=from-tmux-global ABSPIKE_TMUX_SESSION=from-tmux-session …

The teammate pane is created by tmux, so its process starts from the tmux server's environment
(global, overlaid with the session's), plus the three variables Claude Code adds explicitly. The
lead's own process environment is not the parent of the teammate's. Variables set with
`tmux set-environment` (global or session) before the split arrive in the teammate and in its hooks
and Bash calls; variables merely exported in the shell that started the lead do not.

### Summary table

| Item | In teammate? | Evidence |
|---|---|---|
| `--settings S` on argv | yes | pane_start_command, `ps` |
| `--plugin-dir P` on argv | yes | pane_start_command, `ps` |
| S `hooks` | yes | marker-S.txt, `TMUX_PANE=%1`, teammate session id |
| S `env` | yes (applied by the teammate's Claude, not inherited) | marker-S.txt vs `ps -E` |
| P `hooks`, `${CLAUDE_PLUGIN_ROOT}` | yes | marker-P.txt |
| P skills | yes, as `<plugin>:<skill>` | teammate transcript |
| Shell variable exported before `claude` | no | `ABSPIKE_EXPORTED=<unset>` everywhere |
| tmux session environment | yes (new panes) | pid 60420 `ps -E`, marker-S.txt round 2 |
| tmux global environment | yes (new panes) | pid 60420 `ps -E` |

## Answer

inherits both

Claude Code 2.1.303 starts each teammate with the lead's own `--settings` and `--plugin-dir` flags,
so the teammate loads S's hooks and `env` and P's hooks and skills itself. Only the lead's process
environment is not passed on.

## Fallback chosen

No respawn or `after-split-window` rewrite is needed. The plan's primary design stands, with these
rulings for Tasks 2 and 3:

**`AGENT_BOARD=1` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` come from settings `env`**
(`claude/settings.json`). Verified: `ABSPIKE_SETTINGS_ENV=from-S` reached both teammates' hooks.
This is the gate the hooks' dedupe rule reads.

**Hooks live in the plugin and reference `${CLAUDE_PLUGIN_ROOT}`** (Task 3:
`"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.sh" --scoped`). Verified: the P hook ran in both teammates
with `CLAUDE_PLUGIN_ROOT` set to the `--plugin-dir` path. No repo path needs to reach the teammate
for the hooks to work. The SDD ledger ruling holds: Task 3 removes the hook registration from
`claude/settings.json`, otherwise every hook runs twice in every session, teammates included.

**Task 2's launcher exports do not reach teammates.** `export AGENT_BOARD_REPO=… PATH=<repo>/bin:$PATH`
in `claude-orchestrator` (and the `PATH=… AGENT_BOARD_REPO=… claude -w …` line `tmux-ctl agent`
types) only cover the process started from that shell. Evidence: `ABSPIKE_EXPORTED`, exported the
same way, was `<unset>` in both teammates. Two consequences:

1. Task 2's interim hook form `"$AGENT_BOARD_REPO/claude/hooks/<name>.sh"` in `claude/settings.json`
   fires in the lead, workers and relay, but in a teammate `$AGENT_BOARD_REPO` is empty and the hook
   fails. Acceptable only because Task 3 follows in the same chain and replaces it with the plugin
   form; Task 2 must not be merged on its own.
2. Teammates' Bash calls to `tmux-ctl` by name (Task 5's assumption "teammates and their Bash calls
   inherit it") do not get `<repo>/bin` from the launcher's `PATH`.

**Mechanism chosen for `PATH` and `AGENT_BOARD_REPO` in teammates: the tmux session environment.**
`claude-orchestrator`, when `$TMUX` is set, runs

    tmux set-environment AGENT_BOARD_REPO "$AB_REPO"
    tmux set-environment PATH "$(ab_path)"

on the current session before exec'ing `claude` (same tmux binary resolution as the rest of `bin/`;
after Task 4, this is the agent-board server). Verified: `ABSPIKE_TMUX_SESSION`, set with
`set-environment -t '=spike:'` before the split, was in probe2's process environment and in its
hooks' environment, so it also reaches the teammate's Bash tool. The lead itself still gets both
from the shell export. Worker windows that `tmux-ctl agent` opens later in the same session get
them from the session environment too.

Why not the alternatives:

- Settings `env` for `PATH`: values are literal, not shell-expanded, and the repo path differs per
  install, so `claude/settings.json` cannot carry it (plan, Task 5).
- Global tmux environment (`set-environment -g`): also verified to arrive, but it is per server, so
  two checkouts on one server would fight. Session scope is per `dev` session.
- Resolving tools from `${CLAUDE_PLUGIN_ROOT}` inside the plugin: covers hooks (already chosen),
  not an agent typing `tmux-ctl` in Bash.

Caveats to carry into Task 2's tests: the session environment applies to panes and windows created
after `set-environment`, so it must run before the first teammate or worker split (it does: the
lead is the first thing in the session). A `~/.zshenv` that resets `PATH` would undo it for the
teammate's `zsh -c` start-up; `test_prompt_argv.zsh` should assert the `set-environment` calls, and
Task 9's end-to-end check should run a teammate split and `tmux-ctl` by name from the teammate pane.
