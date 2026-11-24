# New project from the phone (`/new-project`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the phone alone, `/new-project` on the ops bot sets up a project folder, its own Discord bot, the home channel `#<name>` and a dev session whose lead says hello there.

**Architecture:** The ops bridge (node) owns the Discord side: the slash command, the two forms, a one-shot token file, and two new outbox ops (`create_channel`, `channel_overwrite`) whose answers come back as `np_result` events. The board (`board/newproject.py`, dispatched from `discord_ops` like `gauth`) owns the step machine and its state; Mac-side steps run `tmux-ctl` (new `project new|start`, existing `discord token|allow|policy|channel|bridge start`) in worker threads. Every answer is matched to the step that asked for it (a run id for workers, a `req` for bridge ops), so a stale or repeated answer changes nothing.

**Tech Stack:** zsh (`bin/tmux-ctl`, `tools/lib/project.zsh`), tmux 3.8, git; Node >= 22 with discord.js 14.28 (`tools/discord-bridge`, `node:test`); Python 3 standard library (`board/`, `unittest`, `urllib`).

**Spec:** `docs/superpowers/specs/2026-11-23-new-project-remote-design.md`

```json:manifest
{
 "spec": "docs/superpowers/specs/2026-11-23-new-project-remote-design.md",
 "base": "8b6ef53ab674e52449a1e39220d29633bf6e3477",
 "depends_on": [],
 "writes": [
  {
   "path": "tools/lib/project.zsh",
   "mode": "create"
  },
  {
   "path": "tools/tests/test_ctl_project.zsh",
   "mode": "create"
  },
  {
   "path": "bin/tmux-ctl",
   "mode": "modify"
  },
  {
   "path": "tools/discord-bridge/lib/commands.js",
   "mode": "modify"
  },
  {
   "path": "tools/discord-bridge/bridge.js",
   "mode": "modify"
  },
  {
   "path": "tools/discord-bridge/test/fake-client.js",
   "mode": "modify"
  },
  {
   "path": "tools/discord-bridge/test/commands.test.js",
   "mode": "modify"
  },
  {
   "path": "tools/discord-bridge/test/newproject.test.js",
   "mode": "create"
  },
  {
   "path": "board/newproject.py",
   "mode": "create"
  },
  {
   "path": "board/discord_feed.py",
   "mode": "modify"
  },
  {
   "path": "board/tests/test_newproject.py",
   "mode": "create"
  },
  {
   "path": "board/discord_ops.py",
   "mode": "modify"
  },
  {
   "path": "board/server.py",
   "mode": "modify"
  },
  {
   "path": "board/tests/test_newproject_ops.py",
   "mode": "create"
  },
  {
   "path": "docs/INSTALL.md",
   "mode": "modify"
  },
  {
   "path": "claude/orchestrator.md",
   "mode": "modify"
  },
  {
   "path": "docs/superpowers/notes/2026-11-24-new-project-remote-real-run.md",
   "mode": "create"
  }
 ],
 "reads": [
  "docs/superpowers/specs/2026-11-23-new-project-remote-design.md",
  "bin/dev",
  "bin/claude-orchestrator",
  "tools/lib/discord.zsh",
  "tools/tests/lib.zsh",
  "board/gauth.py",
  "board/tc_env.py",
  "board/paneclass.py",
  "tools/discord-bridge/lib/outbox.js"
 ],
 "produces": [
  "tmux-ctl project new|start",
  "/new-project slash command",
  "ops outbox ops create_channel|channel_overwrite",
  "np_token and np_result events",
  "board newproject step machine"
 ],
 "consumes": [
  "tmux-ctl discord token|allow|policy|channel|bridge start",
  "dev (DEV_CLAUDE_CMD, DEV_NO_ATTACH)",
  "ops bridge outbox and events",
  "discord_feed.outbox_write|audit_append"
 ],
 "tests": [
  "tools/tests/test_ctl_project.zsh",
  "tools/discord-bridge/test/newproject.test.js",
  "board/tests/test_newproject.py",
  "board/tests/test_newproject_ops.py"
 ]
}
```

## Global Constraints

- **Names**: `^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$` in the bridge and the board; `tools/lib/project.zsh` uses the same rule without the length cap. No `.`: `dev` maps `.` to `_` in the session name, and the lead finds its bot's state dir by session name (assumption A2).
- **Custom ids**: `ab:modal:new-project`; `ab:np:token:<name>` (button) → `ab:modal:np-token:<name>` (form, one input `token`); `ab:np:retry:<name>:<step>`, step one of `disk bot check joined channel access start`.
- **Events** (ops bridge → board, `<_ops>/events/`): `{type: 'modal', form: 'new-project', fields: {name, source, target}, user, channel_id, iid, ts}`; `{type: 'slash', command: 'new-project', name, channel_id, iid, user, ts}`; `{type: 'np_token', name, file, user, iid, ts}` (`file` = base name only); `{type: 'np_result', action: 'create_channel'|'channel_overwrite', name, req, ok, channel_id?, existed?, error?, ts}`; Retry is the existing `click` event.
- **Outbox ops** (board → ops bridge): `{op: 'create_channel', guild, name, req}`, `{op: 'channel_overwrite', channel, user, allow, name, req}`, all strings; the card is the existing `post` (key `np:<name>:<n>`, tier `decision`) and `edit` ops; private answers are `ireply` with `private: true`.
- **Permissions**: `allow` = `2252109051432000` = View `1<<10`, Send Messages `1<<11`, Send Messages in Threads `1<<38`, Create Public Threads `1<<35`, Pin Messages `1<<51`, Read Message History `1<<16`, Add Reactions `1<<6`, Attach Files `1<<15` (the eight of docs/INSTALL.md; discord.js 14.28 `PermissionFlagsBits` gives the same bits). Message Content Intent = application `flags & ((1<<18)|(1<<19))`.
- **The token** is never in an event, a log line, the audit log, a card, an ireply or the state file. Path: token form → `<_ops>/np-token/<ms>-<8 hex>.tok` (dir 700, file 600, `wx`) → board reads it, deletes it whatever happens, pipes it on stdin into `tmux-ctl discord token --project <name>`. Later steps read it from `<discord dir>/<name>/.env`.
- **State**: `~/.local/state/agent-board/newproject/<name>.json` (dir 700, file 600): name, source, target, dir, user, guild, bot_id, app_id, channel_id, card, n, steps{state, error, at, run?}, req, join, created, done.
- **Help header**: one new line above `registry|engine <sub>`; `sed -n '2,85p'` becomes `'2,86p'`; the header's last line stays the `metrics <sub>` line.
- **Files shared with other specs of batch 2026-11-24-1** (textual overlap only, no interface): `tools/discord-bridge/lib/commands.js` (remote-lead-liveness, hardening), `tools/discord-bridge/bridge.js` (night-watch, remote-lead-liveness), `claude/orchestrator.md` (supervised-improvement-loop, night-watch, hardening), the tmux-ctl help header (hardening). If `main` moved, rebase and keep both sides; re-count the help range.
- Commits: conventional with scope, path-scoped (`git commit -- <paths>`), ending with the attribution trailer your harness specifies.

**User decisions (already made):** (spec "Decisions", user on Discord, 2026-11-23)
- One bot per project, as today; the flow guides the Developer Portal steps, nothing replaces them.
- Everything is done on the phone, remote from the Mac.
- Any source, chosen in the form: new (`git init`), clone of a git URL, or an existing folder.
- Entry point: a `/new-project` slash command on the ops bot, which posts a setup card in the command center.
- Home channel: the ops bot creates `#<name>` and grants the new bot its permissions there.
- New and cloned repos go to `~/<name>`; a clone uses the Mac's git credentials; at the end the dev session and its lead start and the lead says hello in `#<name>`.

**Assumptions (planner, 2026-11-24; sent to the lead):**
- A1. Discord requires **Manage Roles** to set a channel permission overwrite, and a bot can grant only permissions it holds. The ops bot therefore needs Manage Channels, Manage Roles and the eight permissions; a 403 on the overwrite says `ops bot lacks Manage Roles (or one of the eight permissions) for the channel overwrite`. The spec names Manage Channels only; Task 7 confirms on the real server.
- A2. Names refuse `.` (see Names). The spec's rule allows it.
- A3. For `folder`, the folder must be its repo's top level and be named `<name>` (the dev session takes the folder's name); otherwise the form refuses it.
- A4. "An existing project state dir" is `~/.local/state/agent-board/discord/<name>/`.
- A5. Step 7 is done when `bridge start` and `project start` succeed; the hello itself is the lead's first prompt and is checked in the real run (Task 7), not by the board.
- A6. The form with the name of an unfinished setup resumes it, like `/new-project <name>`.
- A7. Retry of the channel step with a known channel id resends only the overwrite.

---

### Task 1: tmux-ctl project new|start

**Goal:** `tmux-ctl project new <name> --init | --clone URL | --dir PATH` (step 1: makes or checks the folder and prints it) and `tmux-ctl project start <name> [--dir PATH]` (step 7: the dev session and its lead, whose first prompt is the hello), both working outside tmux.

**Files:**
- Create: `tools/lib/project.zsh`
- Modify: `bin/tmux-ctl` (help header line, `sed -n '2,86p'`, the outside-tmux exemption at line ~122, the `project` dispatch next to `discord`)
- Test: `tools/tests/test_ctl_project.zsh` (create)

**Acceptance Criteria:**
- [ ] `project new np1 --init` prints `$HOME/np1`, which is a git repo on branch `main`; a rerun over a fresh `.git` with no commit exits 0; over a repo with a commit or a non-empty folder exits 1 `project: <dir> exists`.
- [ ] `project new <n> --clone <url>` clones into `$HOME/<n>`; a failed clone exits 1 with `project: clone failed: <git's last stderr line>` and leaves no folder.
- [ ] `project new <n> --dir <path>` exits 0 and prints the path only for a git repo's top level whose folder name is `<n>`; otherwise exit 1 with one line.
- [ ] Refusals: a name not matching `^[A-Za-z0-9][A-Za-z0-9_-]*$` (a `.` included), no source, two sources: exit 2; an existing tmux session `<n>`: exit 1 `project: tmux session <n> exists`, nothing created.
- [ ] `project start <n>` runs `dev` with `DEV_NO_ATTACH=1`; when `$TC_STATE/discord/<n>/bridge.json` has a channel, the lead command gets the prompt `New project <n>, set up from Discord. Post exactly "hello from <n>" in Discord channel <id> with the reply tool, then wait for the user.`; a running session prints `project: <n> already running`, exit 0.
- [ ] `tmux-ctl help` shows the project line and still ends at the `metrics <sub>` line (the 9 suites that pin the header's last line keep passing).

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_project.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_discord.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_approve_misc.zsh` → each prints `ALL PASS`, exit 0

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `tools/tests/test_ctl_project.zsh` with exactly this content:

````zsh
source "${0:A:h}/lib.zsh"
# tmux-ctl project new|start (spec 2026-11-23-new-project-remote §2 tmux-ctl). Scratch tmux server (lib.zsh, -f /dev/null);
# HOME and TC_STATE are temp; the lead is a stub (TC_PROJECT_LEAD_CMD) that prints its arguments; the dev layout is off.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
H="$TT_DIR/home"; mkdir -p "$H"
export HOME="$H" TC_LAYOUT=/usr/bin/true GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
print -r -- '#!/bin/sh
echo "LEAD-STUB $*"' > "$TT_DIR/lead"; chmod +x "$TT_DIR/lead"
export TC_PROJECT_LEAD_CMD="$TT_DIR/lead"
N=0
run() { (( N++ )); "$@" > "$TT_DIR/out.$N" 2>&1; rc=$?; out="$(<$TT_DIR/out.$N)" }

# --- new --init
run $C project new np1 --init
check "init: exit 0"                     test $rc = 0
check "init: prints the folder"          test "$out" = "$H/np1"
check "init: a git repo on main"         test "$(git -C $H/np1 symbolic-ref --short HEAD 2>/dev/null)" = main
run $C project new np1 --init
check "init again (fresh .git, no commit): exit 0" test $rc = 0
git -C $H/np1 commit -q --allow-empty -m c
run $C project new np1 --init
check "init over a repo with a commit: exit 1"  test $rc = 1
check "init over a repo: says exists"           test "$out" = "project: $H/np1 exists"
mkdir -p $H/full; : > $H/full/f
run $C project new full --init
check "init over a non-empty folder: exit 1"    test $rc = 1

# --- new --clone (a local bare repo)
git init -q --bare -b main "$TT_DIR/src.git"
git clone -q "$TT_DIR/src.git" "$TT_DIR/w" 2>/dev/null; git -C "$TT_DIR/w" commit -q --allow-empty -m first; git -C "$TT_DIR/w" push -q origin main 2>/dev/null
run $C project new np2 --clone "$TT_DIR/src.git"
check "clone: exit 0"                    test $rc = 0
check "clone: prints the folder"         test "$out" = "$H/np2"
check "clone: has the commit"            test "$(git -C $H/np2 log -1 --format=%s)" = first
run $C project new np3 --clone "$TT_DIR/nope.git"
check "clone failure: exit 1"            test $rc = 1
check "clone failure: git's last stderr line" test "${out#project: clone failed: fatal: }" != "$out"
check "clone failure: no folder left"    test ! -e $H/np3
run $C project new np2 --clone "$TT_DIR/src.git"
check "clone into an existing folder: exit 1" test $rc = 1

# --- new --dir
git init -q -b main $H/np4
run $C project new np4 --dir $H/np4
check "dir: exit 0"                      test $rc = 0
check "dir: prints the folder"           test "$out" = "$H/np4"
mkdir -p $H/plain
run $C project new plain --dir $H/plain
check "dir not a work tree: exit 1"      test $rc = 1
check "dir not a work tree: says so"     test "$out" = "project: $H/plain is not a git work tree"
mkdir -p $H/np4/sub
run $C project new sub --dir $H/np4/sub
check "dir inside a repo: exit 1"        test $rc = 1
run $C project new other --dir $H/np4
check "dir with another name: exit 1"    test $rc = 1
run $C project new np5 --dir $H/missing
check "dir missing: exit 1"              test $rc = 1

# --- refusals
run $C project new 'bad.name' --init
check "name with a dot: exit 2"          test $rc = 2
run $C project new '-x' --init
check "name starting with '-': exit 2"   test $rc = 2
run $C project new np6
check "no source: exit 2"                test $rc = 2
run $C project new np6 --init --clone x
check "two sources: exit 2"              test $rc = 2
run $C project new tt --init
check "existing tmux session: exit 1"    test $rc = 1
check "existing tmux session: says so"   test "$out" = "project: tmux session tt exists"
check "existing tmux session: no folder" test ! -e $H/tt

# --- start
mkdir -p "$TC_STATE/discord/np1"; print -r -- '{"channel": "4242", "user": "U1"}' > "$TC_STATE/discord/np1/bridge.json"
run env -u TMUX -u TMUX_PANE $C project start np1
check "start: exit 0"                    test $rc = 0
check "start: says started"              test "$out" = "project: started np1"
check "start: session exists"            tt has-session -t '=np1'
check "start: session runs in the folder" test "$(tt display -p -t '=np1:claude' '#{pane_current_path}')" = "$H/np1"
tt_wait 5 sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=np1:claude' | grep -q 'LEAD-STUB New project np1'"
check "start: the lead got the hello prompt with the channel" sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -J -t '=np1:claude' | grep -q 'LEAD-STUB New project np1, set up from Discord. Post exactly \"hello from np1\" in Discord channel 4242'"
run env -u TMUX -u TMUX_PANE $C project start np1
check "start again: exit 0, no second session" test "$rc $out" = "0 project: np1 already running"
run $C project start np2
tt_wait 5 sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=np2:claude' | grep -q 'LEAD-STUB'"
check "start without a channel: plain lead, no prompt" sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -J -t '=np2:claude' | grep 'LEAD-STUB' | grep -qv 'hello from'"
run $C project start np4 --dir $H/np4
check "start --dir: exit 0"              test $rc = 0
run $C project start ghost
check "start without a folder: exit 1"   test $rc = 1

# --- help
h="$($C help)"
check "help: project line"               test -n "$(print -r -- "$h" | grep -F 'tmux-ctl project new <name> --init|--clone <url>|--dir <path> | start <name> [--dir <path>]')"
check "help: ends at the header's last line" test "$(print -r -- "$h" | tail -1)" = "  tmux-ctl metrics <sub> …                run-log metrics (board/metrics.py)"
tt_done
````

The test runs on lib.zsh's scratch tmux server (`-f /dev/null`), with `HOME` and `TC_STATE` in its temp dir and a stub lead (`TC_PROJECT_LEAD_CMD`) that prints its arguments, so no Claude starts. Mutation it was checked against: remove the `has-session` refusal in `_pj_new` → the three `existing tmux session` checks fail.

- [ ] **Step 2: Run it to see it fail.** Run: `env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_project.zsh 2>&1 | tail -3`. Expected: FAIL lines (`tmux-ctl: unknown command 'project'` or `not inside tmux` in the outputs) and `N FAILED`.

- [ ] **Step 3: Create the library.** Create `tools/lib/project.zsh` with exactly this content:

````zsh
# tools/lib/project.zsh — tmux-ctl project new|start (spec 2026-11-23-new-project-remote, §2 tmux-ctl).
# Sourced by bin/tmux-ctl; works outside tmux (the board runs it). Uses tc_tmux from bin/_tc_bins.zsh.
_pj_usage() { print -u2 "usage: tmux-ctl project new <name> --init | --clone <url> | --dir <path> | start <name> [--dir <path>]"; return 2 }
# a name: today's project-name rule, and no '.' (dev maps '.' to '_' in the session name, so the lead would miss the bot's state dir)
_pj_name_ok() { [[ "$1" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] }
_pj_root() { print -r -- "${TC_STATE:-$HOME/.local/state/agent-board}" }

project_cmd() {
  emulate -L zsh
  local sub="$1" name="$2" mode="" val="" dir
  shift 2 2>/dev/null || { _pj_usage; return 2 }
  [[ "$sub" == (new|start) ]] || { _pj_usage; return 2 }
  _pj_name_ok "$name" || { print -u2 "project: a name uses letters, digits, '_' and '-' and starts with a letter or digit"; return 2 }
  while (( $# )); do
    case "$1" in
      --init) [[ -z "$mode" && "$sub" == new ]] || { _pj_usage; return 2 }; mode=init; shift ;;
      --clone|--dir)
        [[ -z "$mode" && -n "$2" ]] || { _pj_usage; return 2 }
        [[ "$1" == --clone && "$sub" == start ]] && { _pj_usage; return 2 }
        mode="${1#--}"; val="$2"; shift 2 ;;
      *) _pj_usage; return 2 ;;
    esac
  done
  if [[ "$sub" == start ]]; then _pj_start "$name" "$val"; return $?; fi
  [[ -n "$mode" ]] || { _pj_usage; return 2 }
  _pj_new "$name" "$mode" "$val"
}

_pj_new() {
  local name="$1" mode="$2" val="$3" dir top err
  if tc_tmux has-session -t "=$name" 2>/dev/null; then print -u2 "project: tmux session $name exists"; return 1; fi
  case "$mode" in
    init)
      dir="$HOME/$name"
      if [[ -e "$dir" ]]; then
        # a retry after a half-done init: an empty folder, or one holding only a fresh .git with no commit, is taken as is
        local -a rest=("$dir"/*(DN))
        if (( ${#rest} == 0 )); then :
        elif [[ ${#rest} == 1 && "${rest[1]:t}" == .git ]] && ! git -C "$dir" rev-parse -q --verify HEAD >/dev/null 2>&1; then :
        else print -u2 "project: $dir exists"; return 1; fi
      fi
      mkdir -p -- "$dir" && git -C "$dir" init -q -b main || { print -u2 "project: git init failed in $dir"; return 1 }
      print -r -- "$dir" ;;
    clone)
      dir="$HOME/$name"
      [[ -e "$dir" ]] && { print -u2 "project: $dir exists"; return 1 }
      if ! err="$(git clone -q -- "$val" "$dir" 2>&1 >/dev/null)"; then
        local -a lines=("${(@f)err}")
        print -u2 -r -- "project: clone failed: ${lines[-1]:-git clone exited non-zero}"; return 1
      fi
      print -r -- "$dir" ;;
    dir)
      dir="${val:A}"
      [[ -d "$dir" ]] || { print -u2 "project: $val is not a directory"; return 1 }
      top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || { print -u2 "project: $dir is not a git work tree"; return 1 }
      [[ "${top:A}" == "$dir" ]] || { print -u2 "project: $dir is inside the repo ${top:A}; give its top level"; return 1 }
      [[ "${dir:t}" == "$name" ]] || { print -u2 "project: the folder is named ${dir:t}, not $name (the dev session takes the folder's name)"; return 1 }
      print -r -- "$dir" ;;
  esac
}

_pj_start() {
  local name="$1" dir="${2:-$HOME/$1}" ch prompt lead
  dir="${dir:A}"
  [[ -d "$dir" ]] || { print -u2 "project: $dir is not a directory"; return 1 }
  [[ "${dir:t}" == "$name" ]] || { print -u2 "project: the folder is named ${dir:t}, not $name"; return 1 }
  if tc_tmux has-session -t "=$name" 2>/dev/null; then print -r -- "project: $name already running"; return 0; fi
  lead="${TC_PROJECT_LEAD_CMD:-${_PJ_BIN}/claude-orchestrator}"
  ch="$(jq -r '.channel // empty' "$(_pj_root)/discord/$name/bridge.json" 2>/dev/null)"
  if [[ "$ch" =~ '^[0-9]+$' ]]; then
    prompt="New project $name, set up from Discord. Post exactly \"hello from $name\" in Discord channel $ch with the reply tool, then wait for the user."
    DEV_CLAUDE_CMD="${(q)lead} ${(q)prompt}"
  else
    DEV_CLAUDE_CMD="${(q)lead}"
  fi
  DEV_CLAUDE_CMD="$DEV_CLAUDE_CMD" DEV_NO_ATTACH=1 "${_PJ_BIN}/dev" "$dir" >/dev/null 2>&1 \
    || { print -u2 "project: dev could not start $name"; return 1 }
  tc_tmux has-session -t "=$name" 2>/dev/null || { print -u2 "project: session $name did not start"; return 1 }
  print -r -- "project: started $name"
}
````

Notes: `dev` maps `.` to `_` in session names, so a name with a `.` is refused (the lead would look for the bot's state dir under another name). `$HOME` itself is a git repo on this machine: `--init` tests emptiness with a glob, never with `git rev-parse` outside the new folder.

- [ ] **Step 4: Wire it into tmux-ctl.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t1-tmux-ctl.patch <<'PATCH'
diff --git a/bin/tmux-ctl b/bin/tmux-ctl
index 8da2897..856fe66 100755
--- a/bin/tmux-ctl
+++ b/bin/tmux-ctl
@@ -80,6 +80,7 @@
 #   tmux-ctl scout weekly [--dry-run] [--force] [--retry]  the Sunday pass: evaluate, draft specs, post the digest (--dry-run prints, writes nothing)
 #   tmux-ctl scout schedule install|status|uninstall  the two scout LaunchAgents (poll 06:00, weekly Sun 07:00 + Mon retry)
 #   tmux-ctl scout approve|reject|revise <id> [--note <text>] | redraft <id> | pack  decide a drafted spec; redraft a revise now; print the context pack
+#   tmux-ctl project new <name> --init|--clone <url>|--dir <path> | start <name> [--dir <path>]  a new project: its folder (prints it); its dev session and lead (works outside tmux)
 #   tmux-ctl registry|engine <sub> …       plan manifests, graphs, waves; the PCEE engine (engine/, node)
 #   tmux-ctl metrics <sub> …                run-log metrics (board/metrics.py)
 #
@@ -119,7 +120,7 @@ except BaseException:
   return 0
 }
 
-[[ -n "$TMUX" || -z "$1" || "$1" == (-h|--help|help) || "$1" == discord || ( "$1" == context && "$2" == dream* ) || ( "$1" == gauth && "$2" == config ) || "$1" == lead-restart || "$1" == awake || "$1" == discover || "$1" == scout || "$1" == registry || "$1" == engine || ( "$1" == metrics && ( "$2" == schedule || "$2" == weekly || "$2" == append || "$2" == has || "$2" == runs || "$2" == gate ) ) ]] || die "not inside tmux"   # discord, context dream*, gauth config, metrics schedule|weekly|append|has|runs|gate (registry calls them; gate is a read-only evaluator), discover, scout, registry, lead-restart and awake work outside tmux (the restore job's launchd run; awake finds the server through tc_tmux)
+[[ -n "$TMUX" || -z "$1" || "$1" == (-h|--help|help) || "$1" == discord || "$1" == project || ( "$1" == context && "$2" == dream* ) || ( "$1" == gauth && "$2" == config ) || "$1" == lead-restart || "$1" == awake || "$1" == discover || "$1" == scout || "$1" == registry || "$1" == engine || ( "$1" == metrics && ( "$2" == schedule || "$2" == weekly || "$2" == append || "$2" == has || "$2" == runs || "$2" == gate ) ) ]] || die "not inside tmux"   # discord, context dream*, gauth config, metrics schedule|weekly|append|has|runs|gate (registry calls them; gate is a read-only evaluator), discover, scout, registry, lead-restart and awake work outside tmux (the restore job's launchd run; awake finds the server through tc_tmux)
 if [[ -z "$TMUX" ]]; then
   SESSION=; FEEDKEY=
 elif [[ -n "$TC_SESSION" ]]; then
@@ -318,6 +319,11 @@ if [[ "$cmd" == discord ]]; then   # no tmux needed
   source "${0:A:h:h}/tools/lib/discord.zsh"
   discord_cmd "$@"; exit $?
 fi
+if [[ "$cmd" == project ]]; then   # no tmux needed: the board runs it (spec 2026-11-23-new-project-remote)
+  _PJ_BIN="${0:A:h}"
+  source "${0:A:h:h}/tools/lib/project.zsh"
+  project_cmd "$@"; exit $?
+fi
 if [[ "$cmd" == gauth ]]; then   # config needs no tmux; the others reach tmux through board/gauth.py
   [[ "$1" == (config|start|status|close) && -n "$2" ]] || die 'usage: tmux-ctl gauth config <project> [--adc|--no-adc] [--impersonate <sa>] [--account <email>] | start|status|close <project>'
   python3 -I "${0:A:h:h}/board/gauth.py" "$@"; exit $?
@@ -854,7 +860,7 @@ Write a longer brief inline, pass it as --brief FILE, or use --force to send thi
     exec python3 -I "${0:A:h:h}/board/metrics.py" "$@" ;;
 
   ""|-h|--help|help)
-    sed -n '2,85p' "$0" | sed 's/^# \{0,1\}//' ;;
+    sed -n '2,86p' "$0" | sed 's/^# \{0,1\}//' ;;
 
   *) die "unknown command '$cmd' (tmux-ctl help)" ;;
 esac
PATCH
git apply --check /tmp/np-t1-tmux-ctl.patch && git apply /tmp/np-t1-tmux-ctl.patch
````

The header gains one line, so the help range moves from `2,85p` to `2,86p` (shared context: 9 suites pin the header's last line, which stays the `metrics <sub>` line).

- [ ] **Step 5: Run the tests.** Run: `env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_project.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_discord.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_ctl_approve_misc.zsh`. Expected: three `ALL PASS` lines, exit 0.

- [ ] **Step 6: Commit.**

```bash
git add tools/lib/project.zsh tools/tests/test_ctl_project.zsh bin/tmux-ctl
git commit -m "feat(tmux-ctl): project new|start for /new-project" -- tools/lib/project.zsh tools/tests/test_ctl_project.zsh bin/tmux-ctl
```

End the message with the attribution trailer your harness specifies.


### Task 2: ops bridge /new-project, token file, channel ops

**Goal:** The ops bridge registers `/new-project` (ops only), opens its form and the private token form, writes the pasted token to a mode-600 one-shot file and names only the file in its event, and runs two new outbox ops, `create_channel` and `channel_overwrite`, that answer with `np_result` events.

**Files:**
- Modify: `tools/discord-bridge/lib/commands.js` (payload, `/new-project` command, the two forms, `ab:np:token:<name>` button)
- Modify: `tools/discord-bridge/bridge.js` (the two ops, `writeTokenFile`, `dropTokenFile`, `commandCenter` on ctx)
- Modify: `tools/discord-bridge/test/fake-client.js` (`client.rest` get/post/put; `fakeModal` gets `channelId`, `id`, `deferReply`, `editReply`)
- Modify: `tools/discord-bridge/test/commands.test.js` (the three pins on the command list)
- Test: `tools/discord-bridge/test/newproject.test.js` (create)

**Acceptance Criteria:**
- [ ] `commands.payload(true)` ends with `new-project` and its one option `{name: 'name', type: 3, max_length: 60, required: false}`; `payload(false)` has no `new-project`.
- [ ] `/new-project` outside the command center (`bridge.json` `command_center`) answers `Use /new-project in the command center.` and writes a `rejected` event; inside it opens `ab:modal:new-project` with inputs `name`, `source`, `target`; with a `name` option it defers privately and writes `{type: 'slash', command: 'new-project', name, channel_id, iid, user}`.
- [ ] The form refuses with one line, before any event: a name not matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$`, a source other than new/clone/folder, clone or folder without a URL or path; a valid submit defers privately and writes `{type: 'modal', form: 'new-project', fields: {name, source, target}, user, channel_id, iid}` (`target` empty for `new`).
- [ ] `ab:np:token:<name>` opens `ab:modal:np-token:<name>` with one input `token`; its submit writes `<ops dir>/np-token/<ms>-<8 hex>.tok` (file 600, dir 700) holding the trimmed token, and an event `{type: 'np_token', name, file: <base name>, user, iid}`; the token appears in no event file and no log line.
- [ ] `create_channel {guild, name, req}` lists the guild's channels, reuses a text channel of that name (lower case) or creates one, and answers `{type: 'np_result', action: 'create_channel', name, req, ok: true, channel_id, existed}`; a 403/50013 answers `ok: false, error: 'missing permissions'`; a 5xx is retried; a run twice creates one channel.
- [ ] `channel_overwrite {channel, user, allow, name, req}` PUTs `/channels/<channel>/permissions/<user>` with `{type: 1, allow, deny: '0'}` and answers `np_result` the same way; malformed ops of either kind go to `outbox/failed/`; a project bridge refuses both.
- [ ] Every new interaction from a non-allowlisted user answers `Not authorized.`, opens nothing and writes no token file.

**Verify:** `cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test` → `# fail 0`, exit 0

**Steps:**

- [ ] **Step 1: Extend the fake client.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t2-fake-client.patch <<'PATCH'
diff --git a/tools/discord-bridge/test/fake-client.js b/tools/discord-bridge/test/fake-client.js
index 4f2a560..3ee8321 100644
--- a/tools/discord-bridge/test/fake-client.js
+++ b/tools/discord-bridge/test/fake-client.js
@@ -16,6 +16,13 @@ class FakeClient extends EventEmitter {
     this.user = { id: 'BOT', setPresence: (p) => { this.presences.push(p); if (this.presenceError) throw this.presenceError; return {}; } };
     this.channels = { fetch: (id) => this._fetchChannel(id) };
     this.application = { commands: { set: async (payload, guildId) => { this._record('setCommands', guildId, payload); this._maybeFail('setCommands'); return payload; } } };
+    // REST (the /new-project channel steps): guildChannels is the guild's channel list; get/post/put record and honour failNext('restGet'|'restPost'|'restPut').
+    this.guildChannels = [];
+    this.rest = {
+      get: async (route) => { this._record('restGet', route); this._maybeFail('restGet'); return this.guildChannels.map((c) => ({ ...c })); },
+      post: async (route, o) => { this._record('restPost', route, o?.body); this._maybeFail('restPost'); const c = { id: this._newId('ch'), type: o?.body?.type, name: o?.body?.name }; this.guildChannels.push(c); return { ...c }; },
+      put: async (route, o) => { this._record('restPut', route, o?.body); this._maybeFail('restPut'); return null; },
+    };
   }
 
   // failNext('send', {status: 500}) fails the next call of that method; count repeats it.
@@ -141,12 +148,14 @@ function fakeCommand({ name, options = {}, user = 'U1', channelId = 'C1', channe
 }
 
 // A modal submit; fields is {inputId: value}.
-function fakeModal({ customId, fields = {}, user = 'U1' } = {}) {
-  const i = { customId, user: { id: user }, replies: [], updates: [] };
+function fakeModal({ customId, fields = {}, user = 'U1', channelId = 'C1', id = 'iid-m' } = {}) {
+  const i = { id, customId, channelId, user: { id: user }, replies: [], updates: [], deferredReplies: [], edits: [] };
   i.isChatInputCommand = () => false;
   i.isModalSubmit = () => true;
   i.fields = { getTextInputValue: (n) => String(fields[n] ?? '') };
   i.reply = async (x) => { i.replies.push(x); };
+  i.deferReply = async (x) => { i.deferredReplies.push(x); };
+  i.editReply = async (x) => { i.edits.push(x); };
   return i;
 }
 
PATCH
git apply --check /tmp/np-t2-fake-client.patch && git apply /tmp/np-t2-fake-client.patch
````

- [ ] **Step 2: Write the failing tests.** Create `tools/discord-bridge/test/newproject.test.js` with exactly this content:

````js
'use strict';
// /new-project on the ops bridge (spec 2026-11-23-new-project-remote §2 Ops bridge): registration, the two forms, the token
// file, the create_channel and channel_overwrite outbox ops against the fake REST client, and the allowlist on every new interaction.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const commands = require('../lib/commands');
const { FakeClient, fakeCommand, fakeModal, fakeInteraction } = require('./fake-client');

const TOKEN = 'NEWBOT.tok3n.SECRETSECRETSECRETSECRETSECRET';

function setup({ ops = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbnp-'));
  const dir = path.join(root, ops ? '_ops' : 'myproj');
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify(ops ? { command_center: 'CC', approvals: 'AP', user: 'U1' } : { channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=OPS.abc.SECRETSECRETSECRET\n');
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  const client = new FakeClient({ guildId: 'G1' });
  const logs = []; let t = 0;
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => 1700000000000 + (t += 1), sleep: async () => {} });
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  const tokFiles = () => { try { return fs.readdirSync(path.join(dir, 'np-token')); } catch { return []; } };
  const op = (o) => fs.writeFileSync(path.join(dir, 'outbox', `${String(Date.now()).padStart(13, '0')}-${Math.random().toString(16).slice(2, 10)}.json`), JSON.stringify(o));
  const failed = () => { try { return fs.readdirSync(path.join(dir, 'outbox', 'failed')).filter((n) => n.endsWith('.json')); } catch { return []; } };
  return { dir, client, logs, bridge, events, tokFiles, op, failed, run: async (i) => { await bridge.onInteraction(i); return i; } };
}
const shape = (evs) => evs.map(({ ts, ...r }) => r);

test('payload: /new-project on the ops bot only, with one optional name option', () => {
  const o = commands.payload(true).find((c) => c.name === 'new-project');
  assert.deepStrictEqual(o.options, [{ name: 'name', description: 'Resume the unfinished setup of this project', type: 3, max_length: 60, required: false }]);
  assert.strictEqual(commands.payload(false).find((c) => c.name === 'new-project'), undefined);
});

test('/new-project in the command center opens the form with name, source and target', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC' }));
  assert.strictEqual(i.modals.length, 1);
  assert.strictEqual(i.modals[0].custom_id, 'ab:modal:new-project');
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].custom_id), ['name', 'source', 'target']);
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].required), [true, true, false]);
  assert.deepStrictEqual(s.events(), []);
});

test('/new-project outside the command center is refused with one line and audited as rejected', async () => {
  // mutation: drop the command-center check -> the form opens and modals.length is 1
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'AP' }));
  assert.strictEqual(i.modals.length, 0);
  assert.strictEqual(i.replies[0].content, 'Use /new-project in the command center.');
  assert.deepStrictEqual(shape(s.events()), [{ type: 'rejected', what: '/new-project', project: null, user: 'U1' }]);
});

test('/new-project <name> defers privately and hands the resume to the board', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', options: { name: 'np1' }, id: 'I7' }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'slash', command: 'new-project', name: 'np1', channel_id: 'CC', iid: 'I7', user: 'U1' }]);
});

test('/new-project <name> with a bad name answers one line and writes nothing', async () => {
  const s = setup();
  for (const nm of ['bad.name', '-x', 'a'.repeat(61)]) {
    const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', options: { name: nm } }));
    assert.match(i.replies[0].content, /^Bad name/);
  }
  assert.deepStrictEqual(s.events(), []);
});

test('the new-project form: a valid submit defers and writes one modal event; target is dropped for new', async () => {
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId: 'CC', id: 'I8', fields: { name: 'np1', source: 'New', target: 'ignored' } }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'modal', form: 'new-project', fields: { name: 'np1', source: 'new', target: '' }, user: 'U1', channel_id: 'CC', iid: 'I8' }]);
});

test('the new-project form refuses up front with one line: bad name, bad source, missing url or path, outside the command center', async () => {
  const s = setup();
  const cases = [
    [{ name: 'a.b', source: 'new' }, 'CC', /^Bad name/],
    [{ name: 'np1', source: 'zip' }, 'CC', /^Source must be new, clone or folder\.$/],
    [{ name: 'np1', source: 'clone' }, 'CC', /^Source clone needs a git URL\.$/],
    [{ name: 'np1', source: 'folder' }, 'CC', /^Source folder needs a path\.$/],
    [{ name: 'np1', source: 'new' }, 'AP', /^Use \/new-project in the command center\.$/],
  ];
  for (const [fields, channelId, re] of cases) {
    const i = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId, fields }));
    assert.match(i.replies[0].content, re);
    assert.deepStrictEqual(i.deferredReplies, []);
  }
  assert.deepStrictEqual(shape(s.events()), [{ type: 'rejected', what: 'ab:modal:new-project', user: 'U1' }]);
});

test('Paste token opens the one-field private form', async () => {
  const s = setup();
  const i = await s.run(fakeInteraction({ customId: 'ab:np:token:np1', user: 'U1' }));
  assert.strictEqual(i.modals[0].custom_id, 'ab:modal:np-token:np1');
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].custom_id), ['token']);
  assert.deepStrictEqual(s.events(), []);
});

test('the token form writes a mode-600 one-shot file and an event naming it; the token is in no event and no log line', async () => {
  // mutation: put the token into the event (text: tok) -> the leak assertion on events fails
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', channelId: 'CC', id: 'I9', fields: { token: ` ${TOKEN} ` } }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  const files = s.tokFiles();
  assert.strictEqual(files.length, 1);
  assert.match(files[0], /^[0-9]+-[0-9a-f]{8}\.tok$/);
  const f = path.join(s.dir, 'np-token', files[0]);
  assert.strictEqual(fs.readFileSync(f, 'utf8'), TOKEN);
  assert.strictEqual(fs.statSync(f).mode & 0o777, 0o600);
  assert.strictEqual(fs.statSync(path.dirname(f)).mode & 0o777, 0o700);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_token', name: 'np1', file: files[0], user: 'U1', iid: 'I9' }]);
  const evText = fs.readdirSync(path.join(s.dir, 'events')).map((n) => fs.readFileSync(path.join(s.dir, 'events', n), 'utf8')).join('\n');
  assert.ok(!evText.includes(TOKEN));
  assert.ok(!s.logs.join('\n').includes(TOKEN));
});

test('the token form refuses an empty or spaced token and writes no file', async () => {
  const s = setup();
  for (const token of ['', 'a b']) {
    const i = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', fields: { token } }));
    assert.match(i.replies[0].content, /does not look like a bot token/);
  }
  assert.deepStrictEqual(s.tokFiles(), []);
  assert.deepStrictEqual(s.events(), []);
});

test('every new interaction is refused for a non-allowlisted user: nothing opens, no file, a rejected event', async () => {
  // mutation: skip the allowlist check in commands.handle -> the form opens or the token file is written
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', user: 'EVIL' }));
  const b = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', user: 'EVIL', options: { name: 'np1' } }));
  const c = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId: 'CC', user: 'EVIL', fields: { name: 'np1', source: 'new' } }));
  const d = await s.run(fakeInteraction({ customId: 'ab:np:token:np1', user: 'EVIL' }));
  const e = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', user: 'EVIL', fields: { token: TOKEN } }));
  const f = await s.run(fakeInteraction({ customId: 'ab:np:retry:np1:disk', user: 'EVIL' }));
  for (const i of [a, b, c, d, e, f]) {
    assert.strictEqual(i.replies[0].content, 'Not authorized.');
    assert.strictEqual((i.modals || []).length, 0);
  }
  assert.deepStrictEqual(s.tokFiles(), []);
  assert.deepStrictEqual(shape(s.events()).map((x) => [x.type, x.what]), [
    ['rejected', '/new-project'], ['rejected', '/new-project'], ['rejected', 'ab:modal:new-project'],
    ['rejected', 'ab:np:token:np1'], ['rejected', 'ab:modal:np-token:np1'],
  ]); // the Retry click is refused by onInteraction, which audits only ab:ops: ids (as today)
});

test('Retry is a click event for the board', async () => {
  const s = setup();
  await s.run(fakeInteraction({ customId: 'ab:np:retry:np1:disk', user: 'U1', messageId: 'm5', channelId: 'CC' }));
  assert.deepStrictEqual(shape(s.events()), [{ type: 'click', custom_id: 'ab:np:retry:np1:disk', user: 'U1', message_id: 'm5', channel_id: 'CC' }]);
});

test('create_channel creates #<name> in lower case and answers with the channel id', async () => {
  const s = setup();
  s.op({ op: 'create_channel', guild: '999', name: 'Np1', req: 'r1' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('restPost').map((c) => [c.target, c.payload]), [['/guilds/999/channels', { name: 'np1', type: 0 }]]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'create_channel', name: 'Np1', req: 'r1', ok: true, channel_id: 'ch1', existed: false }]);
});

test('create_channel run twice reuses the channel: no second channel', async () => {
  // mutation: drop the lookup of an existing channel -> two restPost calls
  const s = setup();
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r2' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('restPost').length, 1);
  assert.deepStrictEqual(shape(s.events()).map((e) => [e.req, e.channel_id, e.existed]), [['r1', 'ch1', false], ['r2', 'ch1', true]]);
});

test('create_channel without Manage Channels answers ok false, missing permissions; the op is not retried or failed', async () => {
  const s = setup();
  s.client.failNext('restPost', { status: 403, code: 50013, message: 'Missing Permissions' });
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'create_channel', name: 'np1', req: 'r1', ok: false, error: 'missing permissions' }]);
  assert.deepStrictEqual(s.failed(), []);
  assert.strictEqual(s.client.callsOf('restPost').length, 1);
});

test('create_channel retries a 500 and then answers once', async () => {
  const s = setup();
  s.client.failNext('restPost', { status: 500 });
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('restPost').length, 2);
  assert.deepStrictEqual(shape(s.events()).map((e) => e.ok), [true]);
});

test('channel_overwrite puts a member overwrite with exactly the allow bits', async () => {
  const s = setup();
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '2252109051432000', name: 'np1', req: 'r3' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('restPut').map((c) => [c.target, c.payload]), [['/channels/555/permissions/777', { type: 1, allow: '2252109051432000', deny: '0' }]]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'channel_overwrite', name: 'np1', req: 'r3', ok: true }]);
});

test('channel_overwrite refused by Discord answers ok false', async () => {
  const s = setup();
  s.client.failNext('restPut', { status: 403, code: 50013 });
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '1024', name: 'np1', req: 'r3' });
  await s.bridge.tick();
  assert.deepStrictEqual(shape(s.events()).map((e) => [e.ok, e.error]), [[false, 'missing permissions']]);
});

test('malformed channel ops go to failed/ and answer nothing; a project bridge refuses both ops', async () => {
  const s = setup();
  s.op({ op: 'create_channel', guild: 'abc', name: 'np1', req: 'r1' });
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '1e3', name: 'np1', req: 'r2' });
  await s.bridge.tick();
  assert.strictEqual(s.failed().length, 2);
  assert.deepStrictEqual(s.events(), []);
  const p = setup({ ops: false });
  p.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await p.bridge.tick();
  assert.strictEqual(p.failed().length, 1);
  assert.strictEqual(p.client.callsOf('restGet').length, 0);
});
````

Mutations they were checked against: remove the command-center check in `handleCommand` → `/new-project outside the command center…` fails; drop the existing-channel lookup in `opCreateChannel` (`const have = false`) → `create_channel run twice…` fails.

Then update the three pins in `commands.test.js` (the command list now has 12 entries):

Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t2-commands-test.patch <<'PATCH'
diff --git a/tools/discord-bridge/test/commands.test.js b/tools/discord-bridge/test/commands.test.js
index 27e9444..74d39ca 100644
--- a/tools/discord-bridge/test/commands.test.js
+++ b/tools/discord-bridge/test/commands.test.js
@@ -44,13 +44,13 @@ function setup({ ops = true, views = VIEWS, opsViews = true, opsAllow = ['U1'],
 const evShape = (s) => s.events().map((e) => { const { ts, ...r } = e; return r; });
 
 test('payload: 8 chat-input commands; project option required per mode', () => {
-  const names = ['status', 'queue', 'pause', 'resume', 'idea', 'new-spec', 'ideas', 'approvals', 'tasks', 'lead', 'gauth'];
+  const names = ['status', 'queue', 'pause', 'resume', 'idea', 'new-spec', 'ideas', 'approvals', 'tasks', 'lead', 'gauth', 'new-project'];
   const o = commands.payload(true), p = commands.payload(false);
   assert.deepStrictEqual(o.map((c) => c.name), names);
-  assert.deepStrictEqual(p.map((c) => c.name), names.filter((n) => n !== 'ideas')); // project bots do not register /ideas
+  assert.deepStrictEqual(p.map((c) => c.name), names.filter((n) => n !== 'ideas' && n !== 'new-project')); // project bots register neither /ideas nor /new-project
   assert.ok(o.every((c) => c.type === 1));
   const req = (list) => Object.fromEntries(list.map((c) => [c.name, c.options?.find((x) => x.name === 'project')?.required ?? null]));
-  assert.deepStrictEqual(req(o), { status: false, queue: false, pause: true, resume: true, idea: true, 'new-spec': true, ideas: false, approvals: null, tasks: false, lead: true, gauth: true });
+  assert.deepStrictEqual(req(o), { status: false, queue: false, pause: true, resume: true, idea: true, 'new-spec': true, ideas: false, approvals: null, tasks: false, lead: true, gauth: true, 'new-project': null });
   assert.deepStrictEqual(req(p), { status: false, queue: false, pause: false, resume: false, idea: false, 'new-spec': false, approvals: null, tasks: false, lead: false, gauth: false });
   const act = o.find((c) => c.name === 'lead').options.find((x) => x.name === 'action');
   assert.deepStrictEqual([act.type, act.required, act.choices.map((c) => c.value)], [3, true, ['status', 'restart', 'handoff']]);
@@ -63,7 +63,7 @@ test('ready registers the commands once for the guild; a resume after disconnect
   const c = s.client.callsOf('setCommands');
   assert.strictEqual(c.length, 1);
   assert.strictEqual(c[0].target, 'G1');
-  assert.strictEqual(c[0].payload.length, 11);
+  assert.strictEqual(c[0].payload.length, 12);
   s.bridge.onDisconnect();
   await s.bridge.onReady();
   assert.strictEqual(s.client.callsOf('setCommands').length, 2);
@@ -220,7 +220,7 @@ test('attach wires command and modal interactions through the same handler', asy
 
 test('project option has max_length 60 so the modal custom_id stays under 100 chars', () => {
   for (const ops of [true, false]) {
-    for (const c of commands.payload(ops).filter((x) => x.options)) assert.strictEqual(c.options.find((x) => x.name === 'project').max_length, 60, c.name); // lead: action comes first (required before optional)
+    for (const c of commands.payload(ops).filter((x) => x.options)) assert.strictEqual(c.options.find((x) => x.name === (c.name === 'new-project' ? 'name' : 'project')).max_length, 60, c.name); // lead: action comes first (required before optional)
   }
   assert.ok(`ab:modal:new-spec:${'p'.repeat(60)}`.length <= 100);
 });
PATCH
git apply --check /tmp/np-t2-commands-test.patch && git apply /tmp/np-t2-commands-test.patch
````

- [ ] **Step 3: Run them to see them fail.** Run: `cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test 2>&1 | grep -E '^# (pass|fail)'`. Expected: `# fail` above 0 (`create_channel` is an `invalid op`, the form never opens). A fresh worktree has no `node_modules`: the `npm ci` is part of the command (shared context).

- [ ] **Step 4: Implement the commands and forms.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t2-commands.patch <<'PATCH'
diff --git a/tools/discord-bridge/lib/commands.js b/tools/discord-bridge/lib/commands.js
index 7fe629a..1f7177b 100644
--- a/tools/discord-bridge/lib/commands.js
+++ b/tools/discord-bridge/lib/commands.js
@@ -10,11 +10,17 @@ const ACTIONS = new Set(['pause', 'resume', 'idea', 'new-spec', 'ideas', 'lead',
 const NEEDS_PROJECT = new Set(['queue', 'pause', 'resume', 'idea', 'new-spec', 'lead', 'gauth']);
 const LEAD_ACTIONS = ['status', 'restart', 'handoff'];
 const CONFIRM_TTL_MS = 5 * 60 * 1000; // a /lead Confirm older than this has expired
-const COMPONENT_RE = /^ab:(?:lead:(restart|handoff|cancel):(.+):([0-9]+)|(tasks:pick)|gauth:code:(.+))$/;
+const COMPONENT_RE = /^ab:(?:lead:(restart|handoff|cancel):(.+):([0-9]+)|(tasks:pick)|gauth:code:(.+)|np:token:([A-Za-z0-9][A-Za-z0-9_-]{0,59}))$/;
+// /new-project names: today's project-name rule without '.', at most 60 chars (dev maps '.' to '_' in the session name;
+// ab:np:retry:<name>:<step> stays under Discord's 100-char custom_id limit)
+const NP_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$/;
+const NP_SOURCES = ['new', 'clone', 'folder'];
+const NP_BAD_NAME = "Bad name: letters, digits, '_' and '-', starting with a letter or digit, at most 60.";
 const DESCRIPTIONS = {
   status: 'Show the board status', queue: 'Show a project queue', pause: "Pause a project's queue",
   resume: "Resume a project's queue", idea: 'Add an idea', 'new-spec': 'Ask the lead for a new spec', ideas: 'Group the open ideas', approvals: 'List open decisions',
   tasks: "Show a project's task list", lead: "Check, restart or hand off a project's lead", gauth: 'Re-authenticate Google for a project',
+  'new-project': 'Set up a new project and its own bot',
 };
 const NOT_SET_UP = 'Ops bot not set up (tmux-ctl discord ops-channels).';
 const FORMS = {
@@ -23,9 +29,11 @@ const FORMS = {
 };
 
 function payload(ops) {
-  return Object.keys(DESCRIPTIONS).filter((name) => ops || name !== 'ideas').map((name) => { // /ideas posts in the ops channel: project bots do not register it
+  return Object.keys(DESCRIPTIONS).filter((name) => ops || (name !== 'ideas' && name !== 'new-project')).map((name) => { // /ideas posts in the ops channel and /new-project runs in the command center: project bots register neither
     const c = { name, description: DESCRIPTIONS[name], type: 1 };
-    if (name !== 'approvals') {
+    if (name === 'new-project') {
+      c.options = [{ name: 'name', description: 'Resume the unfinished setup of this project', type: 3, max_length: PROJECT_MAX, required: false }];
+    } else if (name !== 'approvals') {
       c.options = [{ name: 'project', description: 'Project name', type: 3, max_length: PROJECT_MAX, required: ops && NEEDS_PROJECT.has(name) && name !== 'queue' }];
     }
     if (name === 'lead') {
@@ -96,6 +104,29 @@ async function handleCommand(i, ctx) {
   const inHome = !ctx.ops && !!homeId && (i.channelId === homeId || i.channel?.parentId === homeId); // an unknown home channel means no default
   const project = name === 'ideas' ? given : (given || (inHome ? own : null)); // /ideas covers every project unless one is given (R2)
 
+  if (name === 'new-project') {
+    if (!ctx.ops) { await ctx.answer(i, 'Use /new-project on the ops bot.'); return; }
+    if (String(i.channelId ?? '') !== String(ctx.commandCenter() ?? '')) {
+      await ctx.answer(i, 'Use /new-project in the command center.');
+      event({ type: 'rejected', what, project: null });
+      return;
+    }
+    const nm = i.options?.getString?.('name');
+    if (nm) { // resume an unfinished setup: the board answers
+      if (!NP_NAME_RE.test(nm)) { await ctx.answer(i, NP_BAD_NAME); return; }
+      await i.deferReply({ flags: 64 });
+      ctx.keep(i);
+      event({ type: 'slash', command: 'new-project', name: nm, channel_id: String(i.channelId), iid: String(i.id) });
+      return;
+    }
+    const input = (id, label, style, max, required, placeholder) => ({ type: 1, components: [{ type: 4, custom_id: id, label, style, max_length: max, required, ...(placeholder ? { placeholder } : {}) }] });
+    await i.showModal({
+      custom_id: 'ab:modal:new-project', title: 'New project',
+      components: [input('name', 'Name', 1, PROJECT_MAX, true), input('source', 'Source: new, clone or folder', 1, 6, true, 'new'),
+        input('target', 'Git URL (clone) or path (folder)', 1, 400, false)],
+    });
+    return;
+  }
   if (name === 'queue' && ctx.ops && !project) { // one card per lead, posted by the board
     const n = Object.keys(ctx.views()?.leads || {}).filter((p) => p in (ctx.views()?.queue || {})).length;
     await ctx.answer(i, `posting ${n} queue cards`);
@@ -165,6 +196,39 @@ async function handleCommand(i, ctx) {
 
 async function handleModal(i, ctx, m) {
   const [, form, project] = m;
+  const user = String(i.user?.id);
+  if (form === 'new-project') {
+    if (!ctx.ops || String(i.channelId ?? '') !== String(ctx.commandCenter() ?? '')) {
+      await ctx.answer(i, 'Use /new-project in the command center.');
+      ctx.writeEvent({ type: 'rejected', what: 'ab:modal:new-project', user, ts: ctx.now() });
+      return;
+    }
+    const v = (id) => String(i.fields.getTextInputValue(id) ?? '').trim();
+    const name = v('name'), source = v('source').toLowerCase(), target = v('target');
+    const why = !NP_NAME_RE.test(name) ? NP_BAD_NAME
+      : !NP_SOURCES.includes(source) ? 'Source must be new, clone or folder.'
+        : source !== 'new' && !target ? `Source ${source} needs a ${source === 'clone' ? 'git URL' : 'path'}.` : null;
+    if (why) { await ctx.answer(i, why); return; }
+    await i.deferReply({ flags: 64 });
+    ctx.keep(i);
+    ctx.writeEvent({ type: 'modal', form: 'new-project', fields: { name, source, target: source === 'new' ? '' : target }, user, channel_id: String(i.channelId), iid: String(i.id), ts: ctx.now() });
+    ctx.say(`modal new-project ${ctx.snip(name)} from ${ctx.snip(user)}`);
+    return;
+  }
+  if (form === 'np-token') {
+    const tok = String(i.fields.getTextInputValue('token') ?? '').trim();
+    if (!ctx.ops || !NP_NAME_RE.test(project)) { await ctx.answer(i, 'Not available here.'); return; }
+    if (!tok || /\s/.test(tok)) { await ctx.answer(i, 'That does not look like a bot token; Paste token again.'); return; }
+    let file;
+    try { file = ctx.writeTokenFile(tok); } catch { ctx.say(`modal np-token ${ctx.snip(project)}: could not write the token file`); await ctx.answer(i, 'Could not take the token; Paste token again.'); return; }
+    try {
+      await i.deferReply({ flags: 64 });
+      ctx.keep(i);
+      ctx.writeEvent({ type: 'np_token', name: project, file, user, iid: String(i.id), ts: ctx.now() });
+    } catch { ctx.dropTokenFile(file); ctx.say(`modal np-token ${ctx.snip(project)}: event write failed`); return; }
+    ctx.say(`modal np-token ${ctx.snip(project)} from ${ctx.snip(user)}`); // never the token itself
+    return;
+  }
   if (form === 'gauth') {
     const code = String(i.fields.getTextInputValue('code') ?? '').trim();
     if (!code) { await ctx.answer(i, 'Empty code.'); return; }
@@ -195,6 +259,10 @@ async function handleComponent(i, ctx, c) {
     ctx.writeEvent({ type: 'read', what: 'ab:tasks:pick', user, ts: ctx.now() });
     return;
   }
+  if (c[6]) { // ab:np:token:<name>: the one-field private token form
+    await i.showModal({ custom_id: `ab:modal:np-token:${c[6]}`, title: `Bot token for ${c[6]}`.slice(0, 45), components: [{ type: 1, components: [{ type: 4, custom_id: 'token', label: 'Bot token (Reset Token in the portal)', style: 1, max_length: 100, required: true }] }] });
+    return;
+  }
   if (c[5]) { // ab:gauth:code:<project>
     await i.showModal({ custom_id: `ab:modal:gauth:${c[5]}`, title: 'Google auth code', components: [{ type: 1, components: [{ type: 4, custom_id: 'code', label: 'Code', style: 1, max_length: 400, required: true }] }] });
     return;
@@ -218,7 +286,7 @@ async function handleComponent(i, ctx, c) {
 // True when the interaction was a command, modal or one of our components (handled here).
 async function handle(i, ctx) {
   const isCmd = i?.isChatInputCommand?.();
-  const m = i?.isModalSubmit?.() ? /^ab:modal:(idea|new-spec|gauth):(.+)$/.exec(String(i.customId)) : null;
+  const m = i?.isModalSubmit?.() ? (/^ab:modal:(idea|new-spec|gauth|np-token):(.+)$/.exec(String(i.customId)) || /^ab:modal:(new-project)()$/.exec(String(i.customId))) : null;
   const c = !isCmd && !m && typeof i?.customId === 'string' ? COMPONENT_RE.exec(i.customId) : null;
   if (!isCmd && !m && !c) return false;
   const what = isCmd ? `/${i.commandName}` : i.customId;
PATCH
git apply --check /tmp/np-t2-commands.patch && git apply /tmp/np-t2-commands.patch
````

- [ ] **Step 5: Implement the ops and the token file.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t2-bridge.patch <<'PATCH'
diff --git a/tools/discord-bridge/bridge.js b/tools/discord-bridge/bridge.js
index 9190708..81582e4 100644
--- a/tools/discord-bridge/bridge.js
+++ b/tools/discord-bridge/bridge.js
@@ -382,7 +382,44 @@ function createBridge({ dir, client, ops = false, log = () => {}, now = Date.now
     say(`ireply ${snip(iid)} fell back to post`);
   }
 
-  const handlers = { ireply: opIreply, presence: opPresence, approval: opApproval, dialog: opDialog, prompt: opPrompt, edit: opEdit, post: opPost, card: opCard, thread: opThread, archive: opArchive };
+  // /new-project (ops only): the two Discord-side steps. Each answers with an np_result event carrying the op's req, so the
+  // board can drop a stale or repeated answer. 5xx/429/network failures are retried by withRetry; any other failure is an answer.
+  const SNOWFLAKE = /^[0-9]{1,20}$/;
+  const NP_NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$/;
+  const npResult = (op, extra) => writeEvent({ type: 'np_result', action: op.op, name: String(op.name), req: String(op.req), ...extra, ts: now() });
+  const npError = (e) => (e?.code === 50013 || statusOf(e) === 403 ? 'missing permissions' : `status ${statusOf(e) ?? '?'}: ${snip(e?.message)}`);
+  async function opCreateChannel(op) {
+    if (!ops) throw new Error('create_channel op needs ops mode');
+    if (!SNOWFLAKE.test(String(op.guild)) || !NP_NAME.test(String(op.name)) || typeof op.req !== 'string') throw new Error('create_channel: bad guild, name or req');
+    const want = String(op.name).toLowerCase(); // Discord stores text channel names in lower case
+    try {
+      const list = await client.rest.get(`/guilds/${op.guild}/channels`);
+      const have = (Array.isArray(list) ? list : []).find((c) => c?.type === 0 && String(c.name).toLowerCase() === want);
+      const ch = have || await client.rest.post(`/guilds/${op.guild}/channels`, { body: { name: want, type: 0 } });
+      npResult(op, { ok: true, channel_id: String(ch.id), existed: !!have });
+      say(`create_channel ${snip(want)} ${have ? 'existed' : 'created'}`);
+    } catch (e) {
+      if (isRetryable(e)) throw e;
+      npResult(op, { ok: false, error: npError(e) });
+      say(`create_channel ${snip(want)} failed: ${npError(e)}`);
+    }
+  }
+  async function opChannelOverwrite(op) {
+    if (!ops) throw new Error('channel_overwrite op needs ops mode');
+    if (!SNOWFLAKE.test(String(op.channel)) || !SNOWFLAKE.test(String(op.user)) || !/^[0-9]{1,20}$/.test(String(op.allow))
+      || !NP_NAME.test(String(op.name)) || typeof op.req !== 'string') throw new Error('channel_overwrite: bad channel, user, allow, name or req');
+    try {
+      await client.rest.put(`/channels/${op.channel}/permissions/${op.user}`, { body: { type: 1, allow: String(op.allow), deny: '0' } });
+      npResult(op, { ok: true });
+      say(`channel_overwrite ${snip(op.name)}`);
+    } catch (e) {
+      if (isRetryable(e)) throw e;
+      npResult(op, { ok: false, error: npError(e) });
+      say(`channel_overwrite ${snip(op.name)} failed: ${npError(e)}`);
+    }
+  }
+
+  const handlers = { create_channel: opCreateChannel, channel_overwrite: opChannelOverwrite, ireply: opIreply, presence: opPresence, approval: opApproval, dialog: opDialog, prompt: opPrompt, edit: opEdit, post: opPost, card: opCard, thread: opThread, archive: opArchive };
 
   // Run fn until it succeeds; 5xx/network backs off 1s,2s,4s… capped at 60s. Throws on 4xx.
   async function withRetry(fn) {
@@ -684,7 +721,20 @@ function createBridge({ dir, client, ops = false, log = () => {}, now = Date.now
 
   function close() { closed = true; }
 
-  const ctx = { dir, ops, homeChannel: () => (ops ? null : cfg().channel), opsAllow, views, allowFrom, writeEvent, now, say, snip, answer, fence, keep, NO_MENTIONS };
+  // /new-project's pasted token (ops only): a one-shot mode-600 file under <dir>/np-token/, never an event or a log line.
+  // Returns the file's base name; the board reads it, pipes it into tmux-ctl discord token and deletes it.
+  function writeTokenFile(tok) {
+    if (!ops) throw new Error('token files need ops mode');
+    const tdir = path.join(dir, 'np-token');
+    fs.mkdirSync(tdir, { recursive: true, mode: 0o700 });
+    fs.chmodSync(tdir, 0o700);
+    const name = `${now()}-${crypto.randomBytes(4).toString('hex')}.tok`;
+    fs.writeFileSync(path.join(tdir, name), tok, { mode: 0o600, flag: 'wx' });
+    return name;
+  }
+  const dropTokenFile = (name) => { try { fs.rmSync(path.join(dir, 'np-token', path.basename(String(name))), { force: true }); } catch { /* gone */ } };
+
+  const ctx = { dir, ops, homeChannel: () => (ops ? null : cfg().channel), commandCenter: () => (ops ? cfg().command_center ?? null : null), writeTokenFile, dropTokenFile, opsAllow, views, allowFrom, writeEvent, now, say, snip, answer, fence, keep, NO_MENTIONS };
   return { ctx, tick, onInteraction, onReaction, onMessage, onReady, onDisconnect, attach, close, TICK_MS };
 }
 
PATCH
git apply --check /tmp/np-t2-bridge.patch && git apply /tmp/np-t2-bridge.patch
````

Notes: the two ops use `client.rest` (discord.js's REST client, `client.rest.get|post|put(route, {body})`; its errors carry `status` and `code`, which `isRetryable` already reads), so no permission-flag mapping is needed: `allow` is the bitfield string. `NP_NAME` caps names at 60 so `ab:np:retry:<name>:<step>` stays under Discord's 100-char custom id limit.

- [ ] **Step 6: Run the tests.** Run: `cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test 2>&1 | grep -E '^# (pass|fail)'`. Expected: `# pass 217`, `# fail 0` (198 before plus 19 new).

- [ ] **Step 7: Commit.**

```bash
git add tools/discord-bridge/lib/commands.js tools/discord-bridge/bridge.js tools/discord-bridge/test/fake-client.js tools/discord-bridge/test/commands.test.js tools/discord-bridge/test/newproject.test.js
git commit -m "feat(discord-bridge): /new-project form, token file, create_channel and channel_overwrite ops" -- tools/discord-bridge/lib/commands.js tools/discord-bridge/bridge.js tools/discord-bridge/test/fake-client.js tools/discord-bridge/test/commands.test.js tools/discord-bridge/test/newproject.test.js
```

End the message with the attribution trailer your harness specifies.


### Task 3: board/newproject.py step machine

**Goal:** `board/newproject.py`, the step machine: refusals, state in `<agent_base>/newproject/<name>.json` (mode 600, never the token), the setup card, the seven steps with Retry of only the failed one, resume, the token path, the joined poll and the stale-run sweep, tested against a fake Discord REST and a fake tmux-ctl.

**Files:**
- Create: `board/newproject.py`
- Modify: `board/discord_feed.py` (two outbox op shapes: `create_channel`, `channel_overwrite`)
- Test: `board/tests/test_newproject.py` (create)

**Acceptance Criteria:**
- [ ] A full fake run of source `new` goes disk → bot (waiting, card with the portal steps and **Paste token**) → token piped into `tmux-ctl discord token --project np1` on stdin → check (bot id and app id from `GET /users/@me` and `GET /applications/@me`; card shows the Invite URL `…client_id=777&scope=bot&permissions=2252109051432000&guild_id=999&disable_guild_select=true`) → joined (polled at most every 10 s) → `create_channel` then `channel_overwrite` ops → access (`discord allow U1`, `policy allowlist`, `channel 555`, each `--project np1`) → start (`discord bridge start --project np1`, `project start np1`) → `done`, card ending `Done: https://discord.com/channels/999/555` with no buttons.
- [ ] Refusals before any state or card, each with one private reply line: bad name, existing `discord/<name>` state dir, existing tmux session, existing `~/<name>` (new, clone), folder not a repo top level or named differently, outside the command center, ops bot not connected (no `guild_id`).
- [ ] Failures keep earlier steps and offer Retry of that step only: clone failure (git's line), `token rejected` (bot back to waiting, Paste token again), `turn on Message Content Intent, then Retry` (no invite shown), `invite not accepted` after 30 min, `ops bot lacks Manage Channels`, `ops bot lacks Manage Roles (or one of the eight permissions) for the channel overwrite`, `bridge: <bridge start line>`. A Retry of a done step changes nothing.
- [ ] Delivery: a worker result lands only while the step carries its run id; an `np_result` lands only when its `req` matches the running channel step, so a repeated, late or out-of-order answer returns `stale` and changes nothing; a running step with no answer for 15 min fails `interrupted; Retry` (`no answer from the ops bridge; Retry` for the channel).
- [ ] `/new-project <name>` (and the form with an unfinished name) resumes: the old card is edited to `(moved to a new card below)` with no buttons and a new card `np:<name>:<n+1>` is posted; a finished setup answers `already set up`.
- [ ] The token file is deleted whether the save worked or not, a file name not matching `^[0-9]+-[0-9a-f]{8}\.tok$` is never read, orphan files older than 10 min are swept, and a tool line echoing the token is stored as `***`.

**Verify:** `python3 -m unittest board.tests.test_newproject board.tests.test_discord_feed` → `OK`, exit 0

**Steps:**

- [ ] **Step 1: Add the two op shapes.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t3-feed.patch <<'PATCH'
diff --git a/board/discord_feed.py b/board/discord_feed.py
index c3e4590..66c9896 100644
--- a/board/discord_feed.py
+++ b/board/discord_feed.py
@@ -63,7 +63,10 @@ def _check(op):
               "dialog": ({"op", "key", "text", "rows", "mention_user"}, set()),
               "presence": ({"op", "text"}, set()),
               "ireply": ({"op", "iid", "content"}, {"components", "private"}),
-              "approval": ({"op", "key", "kind", "text", "mention_user"}, {"link", "project"})}
+              "approval": ({"op", "key", "kind", "text", "mention_user"}, {"link", "project"}),
+              # /new-project (board/newproject.py): the ops bridge creates #<name> and grants the new bot its overwrite
+              "create_channel": ({"op", "guild", "name", "req"}, set()),
+              "channel_overwrite": ({"op", "channel", "user", "allow", "name", "req"}, set())}
     if kind not in shapes:
         raise ValueError(f"unknown op {kind!r}")
     need, opt = shapes[kind]
PATCH
git apply --check /tmp/np-t3-feed.patch && git apply /tmp/np-t3-feed.patch
````

- [ ] **Step 2: Write the failing tests.** Create `board/tests/test_newproject.py` with exactly this content:

````python
"""newproject: the /new-project step machine against a fake Discord REST and a fake tmux-ctl (argv recorded).
Scratch TC_STATE and HOME; workers run inline (_spawn); the clock is a FakeClock. Spec: docs/superpowers/specs/
2026-11-23-new-project-remote-design.md §1-§3."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import newproject as np  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0
TOKEN = "NEWBOT.tok3n.SECRETSECRETSECRETSECRETSECRET"
GUILD = "999"


class FakeClock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class FakeRest:
    """Answers by path; the token must be TOKEN or the answer is 401. calls: [(method, path)]."""
    def __init__(self):
        self.calls = []
        self.flags = 1 << 18
        self.guilds = []
        self.me = (200, {"id": "777", "username": "np1-bot"})

    def __call__(self, method, path, token):
        self.calls.append((method, path))
        if token != TOKEN:
            return 401, None
        if path == "/users/@me":
            return self.me
        if path == "/applications/@me":
            return 200, {"id": "777", "flags": self.flags}
        if path == "/users/@me/guilds":
            return 200, [{"id": g} for g in self.guilds]
        return 404, None


class FakeCtl:
    """Records (argv after tmux-ctl, stdin); `discord token` saves stdin to the project's .env like the real one.
    fail: {first two argv words joined: (rc, output)}."""
    def __init__(self):
        self.calls = []
        self.fail = {}

    def __call__(self, argv, stdin=None, timeout=180):
        args = [str(a) for a in argv[1:]] if str(argv[0]).endswith("tmux-ctl") else [str(a) for a in argv]
        self.calls.append((args, stdin))
        if args[:1] == ["git"]:   # the folder refusal's own git call
            import subprocess
            r = subprocess.run(args, capture_output=True, text=True)
            return r.returncode, (r.stdout + r.stderr).strip()
        key = " ".join(args[:2])
        if key in self.fail:
            return self.fail[key]
        if args[:2] == ["project", "new"]:
            if args[3] == "--dir":
                return 0, args[4]
            d = Path.home() / args[2]
            d.mkdir(parents=True, exist_ok=True)
            return 0, str(d)
        if args[:2] == ["discord", "token"]:
            dd = tc_env.discord_dir(args[3])
            dd.mkdir(parents=True, exist_ok=True)
            (dd / ".env").write_text(f"DISCORD_BOT_TOKEN={stdin.strip()}\n")
            return 0, f"discord: token saved for {args[3]}"
        return 0, "ok"

    def argvs(self, prefix=()):
        return [a for a, _ in self.calls if tuple(a[:len(prefix)]) == tuple(prefix) and a[:1] != ["git"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(Path(self.tmp.name) / "state"), "HOME": str(home)})
        p.start()
        self.addCleanup(p.stop)
        self.home = home
        self.ops = tc_env.ops_dir()
        self.ops.mkdir(parents=True)
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "CC", "approvals": "AP", "user": "U1"}))
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        (self.ops / "bridge-state.json").write_text(json.dumps({"guild_id": GUILD}))
        self.rest, self.ctl, self.clock = FakeRest(), FakeCtl(), FakeClock()
        self.sessions = set()
        self.err = io.StringIO()
        for patcher in (mock.patch.object(np, "_http", self.rest), mock.patch.object(np, "_run", self.ctl),
                        mock.patch.object(np, "_spawn", lambda fn: fn()), mock.patch.object(np, "_clock", self.clock),
                        mock.patch.object(np, "_session_exists", lambda n: n in self.sessions),
                        mock.patch("sys.stderr", self.err)):
            patcher.start()
            self.addCleanup(patcher.stop)

    # ---- helpers ----
    def outbox(self):
        box = self.ops / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def ireplies(self):
        return [o["content"] for o in self.outbox() if o["op"] == "ireply"]

    def cards(self):
        return [o for o in self.outbox() if o["op"] in ("post", "edit") and str(o.get("key", "")).startswith("np:")]

    def last_card(self):
        return self.cards()[-1]

    def state(self, name="np1"):
        return np.load(name)

    def steps(self, name="np1"):
        return {s: v["state"] for s, v in self.state(name)["steps"].items()}

    def modal(self, name="np1", source="new", target="", channel="CC", user="U1"):
        return np.on_modal(self.ops, {"type": "modal", "form": "new-project", "fields": {"name": name, "source": source, "target": target},
                                      "user": user, "channel_id": channel, "iid": "I1"})

    def paste(self, name="np1", tok=TOKEN):
        d = np.token_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "1700000000001-0a1b2c3d.tok"
        f.write_text(tok)
        return np.on_token(self.ops, {"type": "np_token", "name": name, "file": f.name, "user": "U1", "iid": "I2"}), f

    def result(self, op, **kw):
        return np.on_result(self.ops, {"type": "np_result", "action": op["op"], "name": op["name"], "req": op["req"], **kw})

    def last_op(self, kind):
        return [o for o in self.outbox() if o["op"] == kind][-1]

    def to_joined(self):
        self.modal()
        self.paste()
        self.assertEqual(self.steps()["joined"], "waiting")

    def to_channel(self):
        self.to_joined()
        self.rest.guilds = [GUILD]
        self.clock.t += np.POLL_S
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.steps()["channel"], "running")


class FullRun(Base):
    def test_new_source_runs_every_step_in_order_to_the_hello(self):
        self.assertEqual(self.modal(), "started")
        self.assertEqual(self.ctl.argvs(("project", "new")), [["project", "new", "np1", "--init"]])
        self.assertEqual(self.steps()["disk"], "done")
        self.assertEqual(self.state()["dir"], str(self.home / "np1"))
        self.assertEqual(self.steps()["bot"], "waiting")
        card = self.last_card()
        self.assertIn("New Application → Bot → turn on Message Content Intent → Reset Token", card["text"])
        self.assertIn(np.PORTAL, card["text"])
        self.assertEqual(card["rows"], [[{"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}]])
        self.assertEqual(self.paste()[0], "token received")
        self.assertEqual([c for c in self.ctl.calls if c[0][:2] == ["discord", "token"]], [(["discord", "token", "--project", "np1"], TOKEN + "\n")])
        self.assertEqual(self.steps()["check"], "done")
        self.assertEqual((self.state()["bot_id"], self.state()["app_id"]), ("777", "777"))
        self.assertIn(f"https://discord.com/oauth2/authorize?client_id=777&scope=bot&permissions=2252109051432000&guild_id={GUILD}&disable_guild_select=true",
                      self.last_card()["text"])
        self.assertEqual(self.steps()["joined"], "waiting")
        np.tick(self.ops, self.clock.t + 1)                 # not in the guild yet
        self.assertEqual(self.steps()["joined"], "waiting")
        self.rest.guilds = [GUILD]
        np.tick(self.ops, self.clock.t + 5)                 # under 10 s since the last poll: no poll
        self.assertEqual(self.rest.calls.count(("GET", "/users/@me/guilds")), 1)
        self.clock.t += np.POLL_S + 1
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.steps()["joined"], "done")
        cc = self.last_op("create_channel")
        self.assertEqual({k: cc[k] for k in ("guild", "name")}, {"guild": GUILD, "name": "np1"})
        self.assertEqual(self.result(cc, ok=True, channel_id="555"), "channel created")
        ow = self.last_op("channel_overwrite")
        self.assertEqual({k: ow[k] for k in ("channel", "user", "allow")}, {"channel": "555", "user": "777", "allow": "2252109051432000"})
        self.assertEqual(self.result(ow, ok=True), "done")
        self.assertEqual(self.ctl.argvs(("discord",))[1:], [
            ["discord", "allow", "U1", "--project", "np1"], ["discord", "policy", "allowlist", "--project", "np1"],
            ["discord", "channel", "555", "--project", "np1"], ["discord", "bridge", "start", "--project", "np1"]])
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np1"]])
        self.assertTrue(self.state()["done"])
        self.assertTrue(all(v == "done" for v in self.steps().values()))
        self.assertIn(f"Done: https://discord.com/channels/{GUILD}/555", self.last_card()["text"])
        self.assertEqual(self.last_card()["rows"], [])

    def test_clone_and_folder_pass_their_source_to_project_new(self):
        self.modal(name="np2", source="clone", target="git@x:y/np2.git")
        self.assertEqual(self.ctl.argvs(("project", "new")), [["project", "new", "np2", "--clone", "git@x:y/np2.git"]])
        repo = self.home / "src" / "np3"
        repo.mkdir(parents=True)
        os.system(f"git init -q -b main {repo}")
        self.modal(name="np3", source="folder", target=str(repo))
        self.assertEqual(self.ctl.argvs(("project", "new"))[-1], ["project", "new", "np3", "--dir", str(repo)])

    def test_folder_start_passes_the_folder(self):
        # mutation: drop the --dir extra in _do_start -> project start gets no --dir and the session opens ~/np3
        repo = self.home / "src" / "np3"
        repo.mkdir(parents=True)
        os.system(f"git init -q -b main {repo}")
        self.modal(name="np3", source="folder", target=str(repo))
        st = self.state("np3")
        self.assertEqual(st["dir"], str(repo))
        for s in ("disk", "bot", "check", "joined", "channel", "access"):
            st["steps"][s]["state"] = "done"
        st["steps"]["start"]["state"] = "pending"
        st["channel_id"] = "555"
        np._save(st)
        np._advance(self.ops, "np3")
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np3", "--dir", str(repo)]])


class Refusals(Base):
    def refused(self, *a, **kw):
        r = self.modal(*a, **kw)
        self.assertTrue(r.startswith("refused"), r)
        self.assertIsNone(np.load(kw.get("name", "np1")))
        self.assertEqual(self.cards(), [])
        self.assertEqual(self.ctl.argvs(("project",)), [])
        return self.ireplies()[-1]

    def test_bad_name(self):
        self.assertIn("Bad name", self.refused(name="a.b"))

    def test_existing_project_state_dir(self):
        tc_env.discord_dir("np1").mkdir(parents=True)
        self.assertIn("A project state dir for np1 already exists", self.refused())

    def test_existing_tmux_session(self):
        self.sessions.add("np1")
        self.assertEqual(self.refused(), "A tmux session np1 already exists.")

    def test_existing_home_folder_for_new_and_clone(self):
        (self.home / "np1").mkdir()
        self.assertEqual(self.refused(), "~/np1 already exists.")
        self.assertEqual(self.refused(source="clone", target="u"), "~/np1 already exists.")

    def test_folder_not_a_work_tree_or_misnamed(self):
        plain = self.home / "np1"
        plain.mkdir()
        self.assertIn("is not a git work tree", self.refused(source="folder", target=str(plain)))
        other = self.home / "other"
        other.mkdir()
        os.system(f"git init -q -b main {other}")
        self.assertIn("The folder is named other, not np1", self.refused(source="folder", target=str(other)))

    def test_outside_the_command_center(self):
        self.assertEqual(self.refused(channel="AP"), "Use /new-project in the command center.")

    def test_ops_bot_not_connected(self):
        (self.ops / "bridge-state.json").unlink()
        self.assertIn("has not connected yet", self.refused())


class Failures(Base):
    def test_clone_failure_shows_gits_line_and_retry_reruns_only_disk(self):
        self.ctl.fail["project new"] = (1, "project: clone failed: fatal: repository 'u' not found")
        self.modal(source="clone", target="u")
        self.assertEqual(self.steps()["disk"], "failed")
        self.assertEqual(self.state()["steps"]["disk"]["error"], "project: clone failed: fatal: repository 'u' not found")
        self.assertIn({"label": "Retry project on disk", "style": 2, "custom_id": "ab:np:retry:np1:disk"}, self.last_card()["rows"][0])
        self.assertEqual(self.steps()["bot"], "pending")
        del self.ctl.fail["project new"]
        self.assertEqual(np.on_click(self.ops, "U1", "ab:np:retry:np1:disk"), "retrying")
        self.assertEqual(len(self.ctl.argvs(("project", "new"))), 2)
        self.assertEqual((self.steps()["disk"], self.steps()["bot"]), ("done", "waiting"))

    def test_a_done_step_reruns_nothing(self):
        self.modal()
        n = len(self.ctl.calls)
        self.assertEqual(np.on_click(self.ops, "U1", "ab:np:retry:np1:disk"), "not failed")
        self.assertEqual(len(self.ctl.calls), n)

    def test_token_rejected_asks_for_the_token_again(self):
        self.modal()
        self.paste(tok="WRONG.token.value")
        self.assertEqual(self.steps()["check"], "failed")
        self.assertEqual(self.state()["steps"]["check"]["error"], "token rejected")
        self.assertEqual(self.steps()["bot"], "waiting")
        self.assertIn({"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}, self.last_card()["rows"][0])
        self.paste()
        self.assertEqual((self.steps()["check"], self.steps()["joined"]), ("done", "waiting"))

    def test_intent_off_stops_before_the_invite_and_retry_checks_again(self):
        # mutation: drop the INTENT_FLAGS test -> check is done and joined waits
        self.rest.flags = 0
        self.modal()
        self.paste()
        self.assertEqual(self.state()["steps"]["check"]["error"], "turn on Message Content Intent, then Retry")
        self.assertEqual(self.steps()["joined"], "pending")
        self.assertNotIn("oauth2/authorize", self.last_card()["text"])
        self.rest.flags = 1 << 19   # the LIMITED flag counts too
        np.on_click(self.ops, "U1", "ab:np:retry:np1:check")
        self.assertEqual(self.steps()["joined"], "waiting")

    def test_invite_not_accepted_after_30_minutes_and_retry_polls_again(self):
        self.to_joined()
        self.clock.t += np.JOIN_TIMEOUT_S
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.state()["steps"]["joined"]["error"], "invite not accepted")
        np.on_click(self.ops, "U1", "ab:np:retry:np1:joined")
        self.assertEqual(self.steps()["joined"], "waiting")
        self.assertEqual(self.state()["join"]["since"], self.clock.t)

    def test_missing_manage_channels_then_retry_sends_a_new_create(self):
        self.to_channel()
        first = self.last_op("create_channel")
        self.assertEqual(self.result(first, ok=False, error="missing permissions"), "failed")
        self.assertEqual(self.state()["steps"]["channel"]["error"], "ops bot lacks Manage Channels")
        np.on_click(self.ops, "U1", "ab:np:retry:np1:channel")
        second = self.last_op("create_channel")
        self.assertNotEqual(first["req"], second["req"])
        # mutation: drop the req match in on_result -> the late answer to the first op creates the channel
        self.assertEqual(self.result(first, ok=True, channel_id="1"), "stale")
        self.assertIsNone(self.state()["channel_id"])
        self.result(second, ok=True, channel_id="555")
        self.assertEqual(self.state()["channel_id"], "555")

    def test_overwrite_refused_names_manage_roles_and_retry_skips_the_create(self):
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        self.result(self.last_op("channel_overwrite"), ok=False, error="missing permissions")
        self.assertIn("lacks Manage Roles", self.state()["steps"]["channel"]["error"])
        n = len([o for o in self.outbox() if o["op"] == "create_channel"])
        np.on_click(self.ops, "U1", "ab:np:retry:np1:channel")
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "create_channel"]), n)
        self.assertEqual(self.result(self.last_op("channel_overwrite"), ok=True), "done")

    def test_a_repeated_answer_after_done_changes_nothing(self):
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        ow = self.last_op("channel_overwrite")
        self.result(ow, ok=True)
        n = len(self.ctl.calls)
        self.assertEqual(self.result(ow, ok=True), "stale")
        self.assertEqual(len(self.ctl.calls), n)

    def test_bridge_that_does_not_start_keeps_the_earlier_steps(self):
        # mutation: make on_click reset every step to pending -> the access step reruns and n_access grows
        self.ctl.fail["discord bridge"] = (1, "bridge: node_modules missing (tmux-ctl discord bridge install)")
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        self.result(self.last_op("channel_overwrite"), ok=True)
        self.assertEqual(self.state()["steps"]["start"]["error"], "bridge: bridge: node_modules missing (tmux-ctl discord bridge install)")
        self.assertTrue(all(self.steps()[s] == "done" for s in np.STEPS[:-1]))
        self.assertEqual(self.ctl.argvs(("project", "start")), [])
        del self.ctl.fail["discord bridge"]
        n_access = len(self.ctl.argvs(("discord", "allow")))
        np.on_click(self.ops, "U1", "ab:np:retry:np1:start")
        self.assertEqual(len(self.ctl.argvs(("discord", "allow"))), n_access)
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np1"]])
        self.assertTrue(self.state()["done"])


class Resume(Base):
    def test_slash_resumes_an_unfinished_setup_on_a_new_card(self):
        self.modal()
        self.assertEqual(np.on_slash(self.ops, {"name": "np1", "channel_id": "CC", "iid": "I3"}), "resumed")
        old, new = self.cards()[-2:]
        self.assertEqual((old["op"], old["key"], old["rows"]), ("edit", "np:np1:1", []))
        self.assertIn("(moved to a new card below)", old["text"])
        self.assertEqual((new["op"], new["key"]), ("post", "np:np1:2"))
        self.assertEqual(new["rows"], [[{"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}]])
        self.paste()
        self.assertEqual(self.last_card()["key"], "np:np1:2")

    def test_the_form_with_an_unfinished_name_resumes_instead_of_refusing(self):
        self.modal()
        self.assertEqual(self.modal(), "resumed")
        self.assertEqual(len(self.ctl.argvs(("project", "new"))), 1)

    def test_unknown_and_finished_setups(self):
        self.assertEqual(np.on_slash(self.ops, {"name": "zz", "channel_id": "CC", "iid": "I3"}), "no setup")
        self.modal()
        st = self.state()
        st["done"] = True
        np._save(st)
        self.assertEqual(np.on_slash(self.ops, {"name": "np1", "channel_id": "CC", "iid": "I3"}), "already set up")


class Robustness(Base):
    def test_stale_worker_result_is_dropped(self):
        # mutation: drop the run-id guard in _start.go -> the late result marks disk done
        held = []
        with mock.patch.object(np, "_spawn", held.append):
            self.modal()
        st = self.state()
        st["steps"]["disk"]["run"] = "other"
        np._save(st)
        held[0]()
        self.assertEqual(self.steps()["disk"], "running")
        self.assertIn("np1 disk: stale result dropped", self.err.getvalue())

    def test_a_running_step_with_no_answer_fails_after_15_minutes(self):
        with mock.patch.object(np, "_spawn", lambda fn: None):
            self.modal()
        np.tick(self.ops, NOW + np.STALE_RUN_S + 1)
        self.assertEqual(self.state()["steps"]["disk"]["error"], "interrupted; Retry")

    def test_token_for_a_setup_not_waiting_is_deleted_unread(self):
        r, f = self.paste(name="ghost")
        self.assertEqual(r, "not waiting")
        self.assertFalse(f.exists())
        self.assertEqual(self.ctl.argvs(("discord", "token")), [])

    def test_a_file_name_outside_the_token_dir_is_never_read(self):
        secret = self.home / "secret.txt"
        secret.write_text("x")
        self.modal()
        r = np.on_token(self.ops, {"type": "np_token", "name": "np1", "file": "../../home/secret.txt", "user": "U1", "iid": "I2"})
        self.assertEqual(r, "bad token")
        self.assertTrue(secret.exists())

    def test_orphan_token_files_are_swept_after_10_minutes(self):
        d = np.token_dir()
        d.mkdir(parents=True)
        f = d / "1-00000000.tok"
        f.write_text(TOKEN)
        os.utime(f, (NOW - np.TOKEN_FILE_TTL_S - 1, NOW - np.TOKEN_FILE_TTL_S - 1))
        np.tick(self.ops, NOW)
        self.assertFalse(f.exists())


if __name__ == "__main__":
    unittest.main()
````

Mutations they were checked against (each makes the named test fail): drop the run-id check in `_start.go` (`if st is None:`) → `test_stale_worker_result_is_dropped`; drop the `req` match in `on_result` → `test_missing_manage_channels_then_retry_sends_a_new_create`; drop the `INTENT_FLAGS` test → `test_intent_off_stops_before_the_invite_and_retry_checks_again`; drop the folder `--dir` in `_do_start` → `test_folder_start_passes_the_folder`; reset every step in `on_click` → `test_bridge_that_does_not_start_keeps_the_earlier_steps`.

- [ ] **Step 3: Run them to see them fail.** Run: `python3 -m unittest board.tests.test_newproject 2>&1 | tail -3`. Expected: `ModuleNotFoundError: No module named 'newproject'`.

- [ ] **Step 4: Implement the step machine.** Create `board/newproject.py` with exactly this content:

````python
"""newproject: the /new-project step machine (spec docs/superpowers/specs/2026-11-23-new-project-remote-design.md).

Seven steps, in order: disk, bot, check, joined, channel, access, start. Each step's state is one of pending, running,
waiting, done, failed; it lives with its last error in <agent_base>/newproject/<name>.json (mode 600), never the token.
Mac-side steps run tmux-ctl in a worker (`_spawn`); the two Discord-side steps are create_channel / channel_overwrite
outbox ops on the ops bridge, answered by np_result events that carry the op's req. Every worker result is applied only
if the step still carries the worker's run id, so a stale or repeated answer changes nothing. The card is one post in the
command center (key np:<name>:<n>), edited after every change. discord_ops dispatches the events here; its tick calls tick().
Seams for tests: _http, _run, _spawn, _clock, _session_exists, _env_fn. Test: tests/test_newproject.py."""
import contextlib
import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import discord_feed
import tc_env

STEPS = ("disk", "bot", "check", "joined", "channel", "access", "start")
LABELS = {"disk": "Project on disk", "bot": "Bot", "check": "Check", "joined": "Joined", "channel": "Channel",
          "access": "Access", "start": "Start"}
# The eight home-channel permissions of docs/INSTALL.md: View 1<<10, Send Messages 1<<11, Send Messages in Threads 1<<38,
# Create Public Threads 1<<35, Pin Messages 1<<51, Read Message History 1<<16, Add Reactions 1<<6, Attach Files 1<<15.
PERMS = sum(1 << b for b in (10, 11, 38, 35, 51, 16, 6, 15))   # 2252109051432000
INTENT_FLAGS = (1 << 18) | (1 << 19)   # GATEWAY_MESSAGE_CONTENT | GATEWAY_MESSAGE_CONTENT_LIMITED
POLL_S = 10
JOIN_TIMEOUT_S = 1800
STALE_RUN_S = 900          # a running step whose worker or bridge answer never came (board restart, lost op)
TOKEN_FILE_TTL_S = 600     # a one-shot token file no event claimed is deleted after this
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
TOKEN_FILE_RE = re.compile(r"^[0-9]+-[0-9a-f]{8}\.tok$")
API = "https://discord.com/api/v10"
PORTAL = "https://discord.com/developers/applications"
TMUX_CTL = Path(__file__).resolve().parent.parent / "bin" / "tmux-ctl"
EMOJI = {"pending": "▫️", "running": "⏳", "waiting": "⏳", "done": "✅", "failed": "❌"}

_clock = time.time
_env_fn = lambda: dict(os.environ)   # noqa: E731 -- board/server.py sets it to tmux_env, so tmux-ctl reaches the board's server
_THREAD_LOCK = threading.Lock()


class StepFailed(Exception):
    pass


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


def _run(argv, stdin=None, timeout=180):
    """(rc, combined output). A timeout or a missing binary is rc 124 / 127 with a one-line reason."""
    try:
        r = subprocess.run([str(a) for a in argv], input=stdin, capture_output=True, text=True, timeout=timeout, env=_env_fn())
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as e:
        return 127, type(e).__name__
    return r.returncode, (r.stdout + r.stderr).strip()


def _http(method, path, token):
    """(status, parsed JSON or None) for a Discord REST call with a bot token. A network failure raises OSError."""
    req = urllib.request.Request(API + path, method=method, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (agent-board, 1)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


def _session_exists(name):
    import paneclass
    try:
        return subprocess.run(paneclass.tmux_cmd() + ["has-session", "-t", f"={name}"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---- state ----
def _dir():
    return tc_env.agent_base() / "newproject"


def _path(name):
    return _dir() / f"{name}.json"


def token_dir():
    return tc_env.ops_dir() / "np-token"


def load(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    try:
        v = json.loads(_path(name).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _save(st):
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    tmp = d / f".{st['name']}.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, _path(st["name"]))


@contextlib.contextmanager
def _locked(name):
    """flock on <dir>/.<name>.lock, plus a process lock (flock is per open file, threads of this process share it safely
    only through separate fds). Never nested: every caller releases it before _advance."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with open(d / f".{name}.lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def _step(st, s):
    return st["steps"][s]


def _set(st, s, state, error="", **kw):
    st["steps"][s] = {"state": state, "error": error, "at": _clock(), **kw}


def _last_line(out):
    lines = [l.strip() for l in str(out or "").splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


def _scrub(text, secret):
    return str(text).replace(secret, "***") if secret else str(text)


def _say(msg):
    print(f"newproject: {msg}", file=sys.stderr, flush=True)


def _env_token(name):
    """The project bot's saved token (<discord dir>/<name>/.env), read the way bridge.js readToken does."""
    try:
        txt = (tc_env.discord_dir(name) / ".env").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^DISCORD_BOT_TOKEN=(.*)$", txt, re.M)
    return m.group(1).strip().strip("\"'") if m else None


# ---- the card ----
def invite_url(st):
    return (f"https://discord.com/oauth2/authorize?client_id={st['app_id']}&scope=bot&permissions={PERMS}"
            f"&guild_id={st['guild']}&disable_guild_select=true")


def _line(st, s):
    step = _step(st, s)
    state, err = step["state"], step.get("error") or ""
    n = STEPS.index(s) + 1
    head = f"{EMOJI[state]} {n}. {LABELS[s]}"
    if s == "disk" and state == "done":
        return f"{head}: {st.get('dir')}"
    if s == "bot" and state in ("waiting", "running"):
        body = (f"{head}: in the Developer Portal ({PORTAL}) New Application → Bot → turn on Message Content Intent → "
                f"Reset Token, then Paste token")
        return body + (f"\n   {err}" if err else "")
    if s == "check" and state == "done":
        return f"{head}: bot {st.get('bot_id')} ok · Invite: {invite_url(st)}"
    if s == "joined" and state == "waiting":
        return f"{head}: open the Invite link above and add the bot (checking every {POLL_S} s, up to {JOIN_TIMEOUT_S // 60} min)"
    if s == "channel" and state == "done":
        return f"{head}: <#{st.get('channel_id')}>"
    if s == "start" and state == "done":
        return f"{head}: bridge and lead started; the lead says hello in <#{st.get('channel_id')}>"
    return f"{head}: {err}" if state == "failed" and err else head


def render(st):
    """(text, rows) of the setup card."""
    src = st["source"] + (f" {st['target']}" if st.get("target") else "")
    lines = [f"🆕 new project {st['name']} ({src})"] + [_line(st, s) for s in STEPS]
    if st.get("done"):
        lines.append(f"Done: https://discord.com/channels/{st['guild']}/{st['channel_id']}")
    row = []
    if _step(st, "bot")["state"] == "waiting":
        row.append({"label": "Paste token", "style": 1, "custom_id": f"ab:np:token:{st['name']}"})
    for s in STEPS:
        if _step(st, s)["state"] == "failed":
            row.append({"label": f"Retry {LABELS[s].lower()}", "style": 2, "custom_id": f"ab:np:retry:{st['name']}:{s}"})
    return "\n".join(lines)[:2000], ([row[:5]] if row else [])


def _card(d, st):
    text, rows = render(st)
    discord_feed.outbox_write(d, {"op": "edit", "key": st["card"], "text": text, "rows": rows})


def _post_card(d, st):
    text, rows = render(st)
    op = {"op": "post", "text": text, "tier": "decision", "mention_user": False, "key": st["card"]}
    if rows:
        op["rows"] = rows
    discord_feed.outbox_write(d, op)


def _ireply(d, iid, content):
    if iid:
        discord_feed.outbox_write(d, {"op": "ireply", "iid": str(iid), "content": str(content)[:1900], "private": True})


def _audit(d, user, step, name, result):
    discord_feed.audit_append(d, str(user or ""), "newproject", f"{name}:np:{step}", result)


# ---- refusals and the start of a setup ----
def _command_center():
    try:
        return str(json.loads((tc_env.ops_dir() / "bridge.json").read_text(encoding="utf-8")).get("command_center") or "")
    except (OSError, ValueError):
        return ""


def _guild():
    try:
        return str(json.loads((tc_env.ops_dir() / "bridge-state.json").read_text(encoding="utf-8")).get("guild_id") or "")
    except (OSError, ValueError):
        return ""


def _refusal(name, source, target):
    if not NAME_RE.match(name or ""):
        return "Bad name: letters, digits, '_' and '-', starting with a letter or digit, at most 60."
    if source not in ("new", "clone", "folder"):
        return "Source must be new, clone or folder."
    if source != "new" and not target:
        return f"Source {source} needs a {'git URL' if source == 'clone' else 'path'}."
    if tc_env.discord_dir(name).exists():
        return f"A project state dir for {name} already exists ({tc_env.discord_dir(name)})."
    if _session_exists(name):
        return f"A tmux session {name} already exists."
    if source in ("new", "clone") and (Path.home() / name).exists():
        return f"~/{name} already exists."
    if source == "folder":
        p = Path(os.path.expanduser(target)).resolve()
        rc, top = _run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], timeout=20)
        if not p.is_dir() or rc != 0 or Path(top.strip()).resolve() != p:
            return f"{target} is not a git work tree."
        if p.name != name:
            return f"The folder is named {p.name}, not {name}: the dev session takes the folder's name."
    if not _guild():
        return "The ops bot has not connected yet; try again in a minute."
    return None


def on_modal(d, ev):
    """The new-project form. Answers one private line; posts the card and runs the first step, or resumes."""
    f = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
    name, source, target = str(f.get("name") or ""), str(f.get("source") or ""), str(f.get("target") or "").strip()
    user, iid = str(ev.get("user") or ""), ev.get("iid")
    if str(ev.get("channel_id") or "") != _command_center():
        _ireply(d, iid, "Use /new-project in the command center.")
        return "refused: not the command center"
    st = load(name)
    if st is not None:
        return _resume(d, st, iid)
    why = _refusal(name, source, target)
    if why:
        _ireply(d, iid, why)
        return f"refused: {why}"[:80]
    st = {"name": name, "source": source, "target": target if source != "new" else "", "dir": None, "user": user,
          "guild": _guild(), "bot_id": None, "app_id": None, "channel_id": None, "card": f"np:{name}:1", "n": 1,
          "steps": {}, "req": {}, "join": {}, "created": _clock(), "done": False}
    for s in STEPS:
        _set(st, s, "pending")
    with _locked(name):
        _save(st)
    _post_card(d, st)
    _ireply(d, iid, f"Setting up {name}: follow the card in this channel.")
    _advance(d, name)
    return "started"


def _resume(d, st, iid):
    if st.get("done"):
        _ireply(d, iid, f"{st['name']} is already set up.")
        return "already set up"
    with _locked(st["name"]):
        st = load(st["name"])
        old = st["card"]
        st["n"] = int(st.get("n") or 1) + 1
        st["card"] = f"np:{st['name']}:{st['n']}"
        _save(st)
    text, _ = render(st)
    discord_feed.outbox_write(d, {"op": "edit", "key": old, "text": f"{text}\n(moved to a new card below)"[:2000], "rows": []})
    _post_card(d, st)
    _ireply(d, iid, f"Resumed {st['name']}: the setup card is below.")
    return "resumed"


def on_slash(d, ev):
    """/new-project <name>: resume an unfinished setup."""
    name, iid = str(ev.get("name") or ""), ev.get("iid")
    if str(ev.get("channel_id") or "") != _command_center():
        _ireply(d, iid, "Use /new-project in the command center.")
        return "refused: not the command center"
    st = load(name)
    if st is None:
        _ireply(d, iid, f"No setup for {name}; run /new-project without a name to start one.")
        return "no setup"
    return _resume(d, st, iid)


# ---- running steps ----
def _next(st):
    for s in STEPS:
        if _step(st, s)["state"] != "done":
            return s
    return None


def _advance(d, name):
    """Start the first step that is not done, if it is pending. Never called with the lock held."""
    st = load(name)
    if st is None or st.get("done"):
        return
    s = _next(st)
    if s is None or _step(st, s)["state"] != "pending":
        return
    if s == "disk":
        _start(d, name, "disk", _do_disk)
    elif s == "bot":
        with _locked(name):
            st = load(name)
            _set(st, "bot", "waiting")
            _save(st)
        _card(d, st)
    elif s == "check":
        _start(d, name, "check", _do_check)
    elif s == "joined":
        with _locked(name):
            st = load(name)
            _set(st, "joined", "waiting")
            st["join"] = {"since": _clock(), "last": 0, "inflight": None}
            _save(st)
        _card(d, st)
    elif s == "channel":
        _channel_op(d, name)
    elif s == "access":
        _start(d, name, "access", _do_access)
    elif s == "start":
        _start(d, name, "start", _do_start)


def _start(d, name, s, fn, payload=None):
    """Mark s running with a fresh run id, then run fn(st, payload) -> dict of state updates in a worker. The result
    lands only while the step still carries that run id."""
    run = secrets.token_hex(4)
    with _locked(name):
        st = load(name)
        _set(st, s, "running", run=run)
        _save(st)
    _card(d, st)

    def go():
        secret = payload if isinstance(payload, str) else None
        try:
            upd, err = fn(load(name), payload) or {}, None
        except StepFailed as e:
            upd, err = None, _scrub(e, secret)
        except Exception as e:   # noqa: BLE001 -- only the class leaves the worker: the text could echo a token
            upd, err = None, f"failed ({type(e).__name__})"
        with _locked(name):
            st = load(name)
            if st is None or _step(st, s).get("run") != run:
                _say(f"{name} {s}: stale result dropped")
                return
            if err is None:
                for k, v in upd.items():
                    if k != "_steps":
                        st[k] = v
                _set(st, s, "done")
            elif s == "bot":   # a token that could not be saved: back to waiting, Paste token again
                _set(st, "bot", "waiting", f"could not save the token: {err}"[:300])
            else:
                _set(st, s, "failed", err[:300])
            if err is None:
                for k, (state, e2) in upd.get("_steps", {}).items():
                    _set(st, k, state, e2)
            if err is not None and s == "check" and err.startswith("token rejected"):
                _set(st, "bot", "waiting", "token rejected: Paste token again")
            if s == "start" and err is None:
                st["done"] = True
            _save(st)
        _card(d, st)
        _audit(d, st.get("user"), s, name, "done" if err is None else f"failed: {err}"[:80])
        _say(f"{name} {s}: {'done' if err is None else 'failed'}")
        if err is None:
            _advance(d, name)
    _spawn(go)


def _ctl(*args, stdin=None):
    rc, out = _run([TMUX_CTL, *args], stdin=stdin)
    if rc != 0:
        raise StepFailed(_last_line(out) or f"tmux-ctl {args[0]} exited {rc}")
    return out


def _do_disk(st, _):
    flag = {"new": ["--init"], "clone": ["--clone", st["target"]], "folder": ["--dir", os.path.expanduser(st["target"])]}[st["source"]]
    out = _ctl("project", "new", st["name"], *flag)
    return {"dir": _last_line(out)}


def _do_token(st, tok):
    """Pipe the pasted token into tmux-ctl discord token (stdin only)."""
    _ctl("discord", "token", "--project", st["name"], stdin=tok + "\n")
    return {}


def _do_check(st, _):
    tok = _env_token(st["name"])
    if not tok:
        raise StepFailed("token rejected: no saved token")
    try:
        code, me = _http("GET", "/users/@me", tok)
        if code == 401:
            raise StepFailed("token rejected")
        if code != 200 or not isinstance(me, dict) or not me.get("id"):
            raise StepFailed(f"Discord answered {code} for the bot user")
        code, app = _http("GET", "/applications/@me", tok)
        if code != 200 or not isinstance(app, dict):
            raise StepFailed(f"Discord answered {code} for the application")
    except OSError as e:
        raise StepFailed(f"Discord unreachable ({type(e).__name__})")
    if not int(app.get("flags") or 0) & INTENT_FLAGS:
        raise StepFailed("turn on Message Content Intent, then Retry")
    return {"bot_id": str(me["id"]), "app_id": str(app.get("id") or me["id"])}


def _do_access(st, _):
    _ctl("discord", "allow", st["user"], "--project", st["name"])
    _ctl("discord", "policy", "allowlist", "--project", st["name"])
    _ctl("discord", "channel", st["channel_id"], "--project", st["name"])
    return {}


def _do_start(st, _):
    try:
        _ctl("discord", "bridge", "start", "--project", st["name"])
    except StepFailed as e:
        raise StepFailed(f"bridge: {e}")
    extra = ["--dir", st["dir"]] if st["source"] == "folder" and st.get("dir") else []
    _ctl("project", "start", st["name"], *extra)
    return {}


def _channel_op(d, name):
    """Step 5: create_channel, or straight to channel_overwrite when a retry already knows the channel."""
    req = secrets.token_hex(4)
    with _locked(name):
        st = load(name)
        _set(st, "channel", "running", run=req)
        st["req"] = {"channel": req}
        _save(st)
    if st.get("channel_id"):
        _overwrite_op(d, st)
    else:
        discord_feed.outbox_write(d, {"op": "create_channel", "guild": st["guild"], "name": name, "req": req})
    _card(d, st)


def _overwrite_op(d, st):
    discord_feed.outbox_write(d, {"op": "channel_overwrite", "channel": st["channel_id"], "user": st["bot_id"],
                                  "allow": str(PERMS), "name": st["name"], "req": st["req"]["channel"]})


def on_result(d, ev):
    """np_result from the ops bridge. Matched by req: a stale, repeated or out-of-order answer is dropped."""
    name, req, action = str(ev.get("name") or ""), str(ev.get("req") or ""), ev.get("action")
    advance = False
    with _locked(name) if NAME_RE.match(name) else contextlib.nullcontext():
        st = load(name)
        if st is None or _step(st, "channel")["state"] != "running" or (st.get("req") or {}).get("channel") != req:
            return "stale"
        if action == "create_channel" and not st.get("channel_id"):
            if ev.get("ok") and re.match(r"^[0-9]{1,20}$", str(ev.get("channel_id") or "")):
                st["channel_id"] = str(ev["channel_id"])
                _save(st)
                _overwrite_op(d, st)
                result = "channel created"
            else:
                err = "ops bot lacks Manage Channels" if ev.get("error") == "missing permissions" else f"could not create the channel: {ev.get('error')}"
                _set(st, "channel", "failed", err[:300])
                _save(st)
                result = "failed"
        elif action == "channel_overwrite" and st.get("channel_id"):
            if ev.get("ok"):
                _set(st, "channel", "done")
                result, advance = "done", True
            else:
                err = ("ops bot lacks Manage Roles (or one of the eight permissions) for the channel overwrite"
                       if ev.get("error") == "missing permissions" else f"could not set the channel overwrite: {ev.get('error')}")
                _set(st, "channel", "failed", err[:300])
                result = "failed"
            _save(st)
        else:
            return "stale"
    _card(d, st)
    if result in ("done", "failed"):
        _audit(d, st.get("user"), "channel", name, result)
    if advance:
        _advance(d, name)
    return result


def drop_token_file(ev):
    """Delete the one-shot token file an np_token event names (only a valid name inside the token dir)."""
    f = str(ev.get("file") or "")
    if TOKEN_FILE_RE.match(f):
        try:
            (token_dir() / f).unlink()
        except OSError:
            pass


def on_token(d, ev):
    """np_token: read the one-shot file, delete it whatever happens, and run the bot step (save) then check."""
    name, iid = str(ev.get("name") or ""), ev.get("iid")
    tok = ""
    try:
        f = str(ev.get("file") or "")
        if TOKEN_FILE_RE.match(f):
            try:
                tok = (token_dir() / f).read_text(encoding="utf-8").strip()
            except OSError:
                tok = ""
    finally:
        drop_token_file(ev)
    st = load(name)
    if st is None or _step(st, "bot")["state"] != "waiting":
        _ireply(d, iid, f"No setup of {name} is waiting for a token.")
        return "not waiting"
    if not tok or any(c.isspace() for c in tok):
        _ireply(d, iid, "That does not look like a bot token; Paste token again.")
        return "bad token"
    _ireply(d, iid, "Token received; checking it.")

    def save(st, tok):
        _do_token(st, tok)
        # the check step runs next from _advance; a token pasted after a rejected check re-arms that check
        return {"_steps": {"check": ("pending", "")}}
    _start(d, name, "bot", save, payload=tok)
    return "token received"


def on_click(d, user, cid):
    """ab:np:retry:<name>:<step>: rerun only that step, and only when it failed."""
    parts = cid.split(":")
    if len(parts) != 5 or parts[:3] != ["ab", "np", "retry"] or parts[4] not in STEPS:
        return "ignored"
    name, s = parts[3], parts[4]
    st = load(name)
    if st is None:
        return "unknown"
    if _step(st, s)["state"] != "failed":
        return "not failed"
    with _locked(name):
        st = load(name)
        _set(st, s, "pending")
        _save(st)
    _audit(d, user, s, name, "retry")
    _advance(d, name)
    return "retrying"


# ---- tick: the joined poll, stale runs, orphan token files ----
def _poll(d, name, run):
    st = load(name)
    tok = _env_token(name)
    err, joined = None, False
    try:
        code, guilds = _http("GET", "/users/@me/guilds", tok or "")
        if code == 401:
            err = "token rejected"
        elif code == 200 and isinstance(guilds, list):
            joined = any(str(g.get("id")) == st["guild"] for g in guilds if isinstance(g, dict))
    except OSError:
        pass   # a network blip: the next poll tries again
    with _locked(name):
        st = load(name)
        if st is None or (st.get("join") or {}).get("inflight") != run or _step(st, "joined")["state"] != "waiting":
            return
        st["join"]["inflight"] = None
        st["join"]["last"] = _clock()
        if joined:
            _set(st, "joined", "done")
        elif err or _clock() - st["join"]["since"] >= JOIN_TIMEOUT_S:
            _set(st, "joined", "failed", err or "invite not accepted")
        else:
            _save(st)
            return
        _save(st)
    _card(d, st)
    _audit(d, st.get("user"), "joined", name, "done" if joined else "failed")
    if joined:
        _advance(d, name)


def tick(d, now):
    try:
        for f in token_dir().glob("*.tok"):
            try:
                if now - f.stat().st_mtime > TOKEN_FILE_TTL_S:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass
    for p in sorted(_dir().glob("*.json")) if _dir().exists() else []:
        name = p.stem
        st = load(name)
        if st is None or st.get("done"):
            continue
        changed, stale, poll = False, False, None
        with _locked(name):
            st = load(name)
            for s in STEPS:
                step = _step(st, s)
                if step["state"] == "running" and now - float(step.get("at") or 0) > STALE_RUN_S:
                    _set(st, s, "failed", "no answer from the ops bridge; Retry" if s == "channel" else "interrupted; Retry")
                    changed = stale = True
            j = st.get("join") or {}
            if _step(st, "joined")["state"] == "waiting" and now - float(j.get("last") or 0) >= POLL_S:
                inflight = j.get("inflight")
                if not inflight or now - float(j.get("inflight_at") or 0) > 60:
                    poll = secrets.token_hex(4)
                    st["join"].update({"inflight": poll, "inflight_at": now})
                    changed = True
            if changed:
                _save(st)
        if stale:
            _card(d, st)
        if poll:
            _spawn(lambda n=name, r=poll: _poll(d, n, r))
````

Design points the tests pin: the lock (`_locked`) is never held across `_advance`, so the inline worker in tests and the thread in production take it in turn; the ops bridge's answers are matched by `req`, the workers' by `run`; the token is only ever a function argument (`payload`), scrubbed from any error text before it is stored.

- [ ] **Step 5: Run the tests.** Run: `python3 -m unittest board.tests.test_newproject board.tests.test_discord_feed 2>&1 | tail -3`. Expected: `OK`.

- [ ] **Step 6: Commit.**

```bash
git add board/newproject.py board/discord_feed.py board/tests/test_newproject.py
git commit -m "feat(board): /new-project step machine" -- board/newproject.py board/discord_feed.py board/tests/test_newproject.py
```

End the message with the attribution trailer your harness specifies.


### Task 4: discord_ops dispatch, server hook, leak test

**Goal:** `discord_ops` dispatches the `/new-project` events to `newproject` (form, resume, token, Retry clicks, `np_result`), its tick calls `newproject.tick`, the board points newproject's tmux-ctl calls at its own tmux server, and a leak test proves the token is nowhere after a full run and after a failed token step.

**Files:**
- Modify: `board/discord_ops.py`
- Modify: `board/server.py` (import `newproject`; `newproject._env_fn = tmux_env`)
- Test: `board/tests/test_newproject_ops.py` (create)

**Acceptance Criteria:**
- [ ] `np_token`, the `new-project` form and the `new-project` slash go to `_new_project`, audited as `<name>:new-project`; a non-allowlisted user's `np_token` deletes the file unread and audits `rejected`.
- [ ] `ab:np:retry:…` clicks reach `newproject.on_click` (allowlisted users only, as every click); `np_result` events, which carry no user, reach `newproject.on_result` and are audited as `np_result`.
- [ ] `discord_ops.tick` runs `newproject.tick(d, now)`; an exception there is logged as `discord_ops: newproject tick skipped: <class>` and the card still renders.
- [ ] Leak test (spec §3): after a full fake run through `consume`, and after a failed token step whose tool output echoes the token, the token string is absent from the state file, `audit.jsonl`, the board's stderr, every outbox op (cards and replies), the events dir and the `newproject/` dir, and `np-token/` is empty.

**Verify:** `python3 -m unittest board.tests.test_newproject board.tests.test_newproject_ops board.tests.test_discord_ops board.tests.test_server_bind` → `OK`, exit 0

**Steps:**

- [ ] **Step 1: Write the failing tests.** Create `board/tests/test_newproject_ops.py` with exactly this content:

````python
"""newproject through discord_ops: the ops events (form, token, Retry click, np_result) dispatched by consume(), and the
leak test over every place the token could land. Fakes and helpers come from test_newproject. Spec: docs/superpowers/
specs/2026-11-23-new-project-remote-design.md §2, §3."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_ops as ops  # noqa: E402
import newproject as np  # noqa: E402
import tc_env  # noqa: E402
from test_newproject import GUILD, NOW, TOKEN, Base  # noqa: E402


class Leak(Base):
    def haystacks(self):
        state = tc_env.agent_base()
        texts = {"state file": (np._dir() / "np1.json").read_text(), "audit": (self.ops / "audit.jsonl").read_text() if (self.ops / "audit.jsonl").exists() else "",
                 "board log": self.err.getvalue(), "cards and replies": json.dumps(self.outbox(), ensure_ascii=False)}
        ev = self.ops / "events"
        texts["events"] = "".join(p.read_text() for p in ev.rglob("*.json")) if ev.exists() else ""
        texts["newproject dir"] = "".join(p.read_text() for p in np._dir().iterdir() if p.is_file())
        return texts

    def through_consume(self, ev):
        """Write ev as the ops bridge would and let discord_ops.consume dispatch it."""
        e = self.ops / "events"
        e.mkdir(exist_ok=True)
        (e / f"{len(list(e.iterdir())):04d}.json").write_text(json.dumps(ev))
        ops.consume(lambda *a: None, lambda argv: "", NOW)

    def paste_via_consume(self, tok=TOKEN, user="U1"):
        d = np.token_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "1700000000001-0a1b2c3d.tok"
        f.write_text(tok)
        self.through_consume({"type": "np_token", "name": "np1", "file": f.name, "user": user, "iid": "I2", "ts": 1})
        return f

    def test_full_run_leaves_the_token_nowhere(self):
        # mutation: write the token into the state (st["token"] = tok in on_token) -> the state file check fails
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        f = self.paste_via_consume()
        self.rest.guilds = [GUILD]
        self.clock.t += np.POLL_S
        np.tick(self.ops, self.clock.t)
        self.through_consume({"type": "np_result", "action": "create_channel", "name": "np1", "req": self.last_op("create_channel")["req"], "ok": True, "channel_id": "555", "ts": 2})
        self.through_consume({"type": "np_result", "action": "channel_overwrite", "name": "np1", "req": self.last_op("channel_overwrite")["req"], "ok": True, "ts": 3})
        self.assertTrue(self.state()["done"])
        self.assertFalse(f.exists())
        self.assertEqual(list(np.token_dir().iterdir()), [])
        for where, text in self.haystacks().items():
            self.assertNotIn(TOKEN, text, where)

    def test_failed_token_step_leaves_the_token_nowhere_even_when_the_tool_echoes_it(self):
        # mutation: drop _scrub in _start.go -> the echoed token reaches the state file and the card
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        self.ctl.fail["discord token"] = (1, f"discord: could not write {TOKEN}")
        f = self.paste_via_consume()
        self.assertEqual(self.steps()["bot"], "waiting")
        self.assertIn("could not save the token: discord: could not write ***", self.state()["steps"]["bot"]["error"])
        self.assertFalse(f.exists())
        for where, text in self.haystacks().items():
            self.assertNotIn(TOKEN, text, where)

    def test_a_token_from_a_non_allowlisted_user_is_deleted_and_rejected(self):
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        f = self.paste_via_consume(user="EVIL")
        self.assertFalse(f.exists())
        self.assertEqual(self.ctl.argvs(("discord", "token")), [])
        self.assertEqual(json.loads((self.ops / "audit.jsonl").read_text().splitlines()[-1])["result"], "rejected")

    def test_retry_clicks_reach_the_step_machine_through_consume(self):
        self.ctl.fail["project new"] = (1, "project: clone failed: fatal: x")
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "clone", "target": "u"}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        del self.ctl.fail["project new"]
        self.through_consume({"type": "click", "custom_id": "ab:np:retry:np1:disk", "user": "U1", "message_id": "m1", "channel_id": "CC", "ts": 2})
        self.assertEqual(self.steps()["disk"], "done")
        self.through_consume({"type": "click", "custom_id": "ab:np:retry:np1:disk", "user": "EVIL", "message_id": "m1", "channel_id": "CC", "ts": 3})
        self.assertEqual(json.loads((self.ops / "audit.jsonl").read_text().splitlines()[-1])["result"], "rejected")


if __name__ == "__main__":
    unittest.main()
````

Mutations they were checked against: store the token in the state (`_save({**st, "token": tok})` in `on_token`) → both leak tests fail; replace `_scrub(e, secret)` by `str(e)` in `_start.go` → `test_failed_token_step_leaves_the_token_nowhere_even_when_the_tool_echoes_it` fails.

- [ ] **Step 2: Run them to see them fail.** Run: `python3 -m unittest board.tests.test_newproject_ops 2>&1 | tail -3`. Expected: failures (the events are audited `rejected`/`ignored` by `handle_event`, the state never reaches `done`).

- [ ] **Step 3: Dispatch the events.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t4-ops.patch <<'PATCH'
diff --git a/board/discord_ops.py b/board/discord_ops.py
index b81a40b..fb34e60 100644
--- a/board/discord_ops.py
+++ b/board/discord_ops.py
@@ -24,6 +24,7 @@ import discord_feed
 import discord_ideas
 import gauth
 import ideas
+import newproject
 import relay
 import tc_env
 import usage
@@ -392,6 +393,10 @@ def tick(records, tasks_by_project, limits, now, add_line, live=None, lead_sids=
             gauth_sweep(d, now)
         except Exception as e:   # noqa: BLE001 -- a bad pending record never stops the card
             print(f"discord_ops: gauth sweep skipped: {type(e).__name__}", file=sys.stderr, flush=True)
+        try:
+            newproject.tick(d, now)
+        except Exception as e:   # noqa: BLE001 -- a bad setup record never stops the card
+            print(f"discord_ops: newproject tick skipped: {type(e).__name__}", file=sys.stderr, flush=True)
         text = render_card(records, tasks_by_project, links, limits, now, floors)
         card = discord_feed.card_op_due(st, text, now)
         if card:
@@ -665,6 +670,8 @@ def handle_event(project, d, ev, add_line, allow, run=None, spawn=None, st=None)
         project = ev.get("project") or project
     target = str(ev.get("command") or ev.get("form") or ev.get("what") or "")
     spawn = spawn or _spawn_thread
+    if kind == "np_token" or (kind == "modal" and ev.get("form") == "new-project") or (kind == "slash" and ev.get("command") == "new-project"):
+        return _new_project(d, ev, user, kind, allow)
     if kind == "rejected" or user not in allow:
         result = "rejected"
     elif kind == "read":
@@ -725,6 +732,24 @@ def handle_event(project, d, ev, add_line, allow, run=None, spawn=None, st=None)
     return result
 
 
+def _new_project(d, ev, user, kind, allow):
+    """/new-project's form, its resume and its pasted token (board/newproject.py). Audited here, never with the token."""
+    f = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
+    name = str(ev.get("name") or f.get("name") or "")[:60]
+    if user not in allow:
+        if kind == "np_token":
+            newproject.drop_token_file(ev)
+        result = "rejected"
+    elif kind == "np_token":
+        result = newproject.on_token(d, ev)
+    elif kind == "slash":
+        result = newproject.on_slash(d, ev)
+    else:
+        result = newproject.on_modal(d, ev)
+    discord_feed.audit_append(d, user, kind, f"{name}:new-project", result)
+    return result
+
+
 def _default_merge(project, src_key, rec, add_line, now):
     import discord_merge   # Task 5; imported here so this module loads without it
     return discord_merge.on_merge(project, src_key, rec, add_line, now)
@@ -766,6 +791,8 @@ def _click(d, user, cid, st, add_line, now, on_merge):
         return discord_ideas.click(user, cid, add_line, now)
     if parts[:2] == ["ab", "analytics"]:
         return analytics_post.click(d, user, cid, now)
+    if parts[:2] == ["ab", "np"]:
+        return newproject.on_click(d, user, cid)
     if parts[:2] != ["ab", "ops"] or len(parts) < 3:
         return "ignored"
     act, k = parts[2], ":".join(parts[3:])
@@ -829,6 +856,8 @@ def consume(add_line, run, now, on_merge=None, lead_run=None, spawn=None):
                 dlg = discord_dialogs.consume_event(d, ev, allow, run, now, add_line=add_line)
                 if dlg:
                     discord_feed.audit_append(d, user, *dlg)
+                elif kind == "np_result":   # the ops bridge's own answer to a create_channel / channel_overwrite op: no user
+                    discord_feed.audit_append(d, "", "np_result", f"{str(ev.get('name') or '')[:60]}:{ev.get('action')}", newproject.on_result(d, ev))
                 elif kind == "click":
                     cid = str(ev.get("custom_id") or "")
                     result = _click(d, user, cid, st, add_line, now, on_merge) if user in allow else "rejected"
PATCH
git apply --check /tmp/np-t4-ops.patch && git apply /tmp/np-t4-ops.patch
````

- [ ] **Step 4: Point newproject at the board's tmux server.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t4-server.patch <<'PATCH'
diff --git a/board/server.py b/board/server.py
index 3866699..6dc6fba 100644
--- a/board/server.py
+++ b/board/server.py
@@ -32,7 +32,7 @@ sys.path.insert(0, str(HERE))
 import tc_env  # noqa: E402
 from paneclass import SHELLS, VERSION_RE, WAITING_RE, WORKING_RE, classify, input_has_text, is_claude_cmd, mod_records, mod_states, tmux_cmd  # noqa: E402,F401
 TMUX = tmux_cmd()   # which tmux server the board shows: bin/_tc_bins.zsh decides (tmux-dash passes TMUX_DASH_TMUX_ARGS)
-import activity, artifacts, dirs, discord_controls, discord_dialogs, discord_digest, discord_feed, engine_lines, discord_ideas, discord_merge, discord_ops, gitlab_sync, ideas, notify, overview, planview, relay, restore, usage, worktree_safety  # noqa: E402
+import activity, artifacts, dirs, discord_controls, discord_dialogs, discord_digest, discord_feed, engine_lines, discord_ideas, discord_merge, discord_ops, gitlab_sync, ideas, newproject, notify, overview, planview, relay, restore, usage, worktree_safety  # noqa: E402
 from worktree_safety import claude_lock_owner  # noqa: E402,F401
 discord_controls.BIN = BIN   # the controls step runs bin/tmux-ctl (discord_controls.py)
 from urllib.parse import parse_qs, urlsplit  # noqa: E402
@@ -121,6 +121,9 @@ def tmux_env():
     return env
 
 
+newproject._env_fn = tmux_env   # /new-project's tmux-ctl calls reach the server the board reads
+
+
 def run_script(args, cwd=None, extra_env=None, timeout=30):
     env = tmux_env()
     env.update(extra_env or {})
PATCH
git apply --check /tmp/np-t4-server.patch && git apply /tmp/np-t4-server.patch
````

- [ ] **Step 5: Run the tests.** Run: `python3 -m unittest board.tests.test_newproject board.tests.test_newproject_ops board.tests.test_discord_ops board.tests.test_server_bind 2>&1 | tail -3`. Expected: `OK`. Do not edit any `board/*.py` while a board suite runs (shared context: the server tests re-exec and abort).

- [ ] **Step 6: Commit.**

```bash
git add board/discord_ops.py board/server.py board/tests/test_newproject_ops.py
git commit -m "feat(board): dispatch /new-project events from the ops bot" -- board/discord_ops.py board/server.py board/tests/test_newproject_ops.py
```

End the message with the attribution trailer your harness specifies.


### Task 5: INSTALL.md and orchestrator.md

**Goal:** docs/INSTALL.md describes `/new-project`, the ops bot's extra permissions and the access-rule exception; claude/orchestrator.md states that exception for the lead.

**Files:**
- Modify: `docs/INSTALL.md` (Remote access: step 5's access sentence, Ops bot step 1, a new `/new-project` paragraph before **Files.**)
- Modify: `claude/orchestrator.md` (the "Never run `tmux-ctl discord pair|deny|policy|allow|remove`" bullet)

**Acceptance Criteria:**
- [ ] INSTALL.md's access sentence keeps "the lead never runs them" and adds the one exception: the user's own `/new-project` allowlists only that user's id, only in the new project's `access.json`, only during that setup, and no message text can trigger it.
- [ ] INSTALL.md's ops bot step 1 names **Manage Channels**, **Manage Roles** and the eight permissions at server level, and the two step-5 failure lines.
- [ ] A `**New project from the phone (`/new-project`).**` paragraph lists the seven steps, Retry, resume, where the token goes and where it never goes, and the name and folder refusals.
- [ ] claude/orchestrator.md's bullet keeps its two lines and adds that `/new-project` is the user's own action, not the lead's; `tools/tests/test_plugin.zsh` still passes.

**Verify:** `grep -qF 'For `/new-project`, also give the ops bot **Manage Channels** and **Manage Roles**' docs/INSTALL.md && grep -qF '**New project from the phone (`/new-project`).**' docs/INSTALL.md && grep -qF 'One exception: your own `/new-project` on the ops bot' docs/INSTALL.md && grep -qF '`/new-project` on the ops bot allowlists the user who ran it' claude/orchestrator.md && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh` → exit 0, `ALL PASS`

**Steps:**

- [ ] **Step 1: Apply the edits.** Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t5-install.patch <<'PATCH'
diff --git a/docs/INSTALL.md b/docs/INSTALL.md
index 127e6b0..6c281e9 100644
--- a/docs/INSTALL.md
+++ b/docs/INSTALL.md
@@ -287,7 +287,7 @@ Reach a dev lead from your phone through a Discord bot. One bot per project; onl
 
    It is stored as `~/.local/state/agent-board/discord/<project>/.env` (mode 600), and `access.json` in the same folder gets `ackReaction: "👀"` when the key is missing or null (an empty value means you turned it off). It prints `discord: token saved for <project> (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)`. A project name must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`: a tmux session whose name starts with `_` or holds a space, `:` or non-ASCII characters never opts in (`tmux-ctl discord` refuses it).
 4. Restart the lead (`agent-board lead --continue`, or Restart orchestrator on the board). A lead with a token starts with `--channels plugin:discord@claude-plugins-official` and `DISCORD_STATE_DIR` set to that folder; the board shows `dc` on it.
-5. DM the bot; it answers with a pairing code. In a terminal run `tmux-ctl discord pair <code>` (it prints `discord: paired <sender id>`), then `tmux-ctl discord policy allowlist`. `tmux-ctl discord deny <code>` drops a code; `allow <id>` and `remove <id>` edit the allowlist by hand. Access changes are yours, typed in a terminal: the lead never runs them.
+5. DM the bot; it answers with a pairing code. In a terminal run `tmux-ctl discord pair <code>` (it prints `discord: paired <sender id>`), then `tmux-ctl discord policy allowlist`. `tmux-ctl discord deny <code>` drops a code; `allow <id>` and `remove <id>` edit the allowlist by hand. Access changes are yours, typed in a terminal: the lead never runs them. One exception: your own `/new-project` on the ops bot (below) allowlists your id, and only yours, in the new project's `access.json`, during that setup only. No Discord message text can trigger it, and the lead still never runs access commands.
 6. `tmux-ctl discord status` shows these lines, in this order:
 
    ```
@@ -313,12 +313,24 @@ Reach a dev lead from your phone through a Discord bot. One bot per project; onl
 
 **Ops bot.** One more bot, separate from the project bots, runs the command center and the approvals channel for every project. It has its own state dir, `~/.local/state/agent-board/discord/_ops/`, and the same subcommands take `--ops` instead of a project (`--ops` with `--project` is a usage error, rc 2).
 
-1. In the Developer Portal create a second application and bot. Turn on **Message Content Intent** (Privileged Gateway Intents) on its bot page too: the bridge requests it for every bot, the ops bot included, and a bot without it exits at login (`Used disallowed intents`), so the whole ops bridge stays down. An ops bot that already exists needs the switch before its bridge restarts. Invite it with the `bot` and `applications.commands` scopes (the slash commands need the second one), and give it View, Send Messages, Embed Links, Attach Files, Read Message History and Add Reactions in two channels: one for the command center, one for approvals, plus Pin Messages (Discord's own permission for pins; Manage Messages alone is not enough) in the command center. Without it the card is posted but not pinned, and its first outbox op fails with `status 403: Missing Permissions`.
+1. In the Developer Portal create a second application and bot. Turn on **Message Content Intent** (Privileged Gateway Intents) on its bot page too: the bridge requests it for every bot, the ops bot included, and a bot without it exits at login (`Used disallowed intents`), so the whole ops bridge stays down. An ops bot that already exists needs the switch before its bridge restarts. Invite it with the `bot` and `applications.commands` scopes (the slash commands need the second one), and give it View, Send Messages, Embed Links, Attach Files, Read Message History and Add Reactions in two channels: one for the command center, one for approvals, plus Pin Messages (Discord's own permission for pins; Manage Messages alone is not enough) in the command center. Without it the card is posted but not pinned, and its first outbox op fails with `status 403: Missing Permissions`. For `/new-project`, also give the ops bot **Manage Channels** and **Manage Roles** in that server, plus the eight home-channel permissions above at server level: it creates `#<name>` and adds a permission overwrite for the new bot there, and Discord lets a bot grant only permissions it holds itself. Without them the setup card's step 5 fails with `ops bot lacks Manage Channels` or `ops bot lacks Manage Roles (or one of the eight permissions) for the channel overwrite`.
 2. `printf '%s\n' "$OPS_TOKEN" | tmux-ctl discord token --ops` saves the token to `_ops/.env` (stdin only, never printed). Then restart the overseer so its Discord plugin connects with the ops token: `pair <code> --ops` needs it, because the DM reaches the bot running in the overseer. Then `tmux-ctl discord pair <code> --ops` (the code the bot sends you in a DM) or `tmux-ctl discord allow <user id> --ops` (works without the restart); `policy`, `deny`, `remove` and `forget` take `--ops` too.
 3. `tmux-ctl discord ops-channels <command center id> <approvals id>` (both all digits) writes `_ops/bridge.json` as `{"command_center", "approvals", "user"}` (mode 600) and adds both ids to `access.json` `groups` with `{"requireMention": false, "allowFrom": [every allowlisted id]}`. It prints `ops-channels: <cc> <ap>`, or `… (unchanged)` and touches nothing when both files already hold that. With nobody allowlisted it exits 1 with `discord: pair or allow a user first`.
 4. `tmux-ctl discord bridge start --ops` starts window `discord-ops` in the hidden session `_ops-bg`, running `node …/bridge.js <_ops dir> --ops`. It refuses without a token, without both channel ids, or without the bridge dependencies (`tmux-ctl discord bridge install`). `bridge stop --ops` and `start --keeper --ops` follow `_ops/bridge.stopped` exactly as for a project.
 5. `tmux-ctl discord status --ops` prints the usual lines with `command center: <id>` and `approvals: <id>` (each `none` when unset) in place of `channel:`, then the `bridge:` line. `audit --ops` reads `_ops/audit.jsonl`.
 
+**New project from the phone (`/new-project`).** In the command center, `/new-project` (allowlisted users only) opens a form: a name, a source (`new`, `clone` or `folder`) and a git URL or path. The ops bot posts one setup card and edits it as each step finishes (⏳ running, ✅ done, ❌ failed with its reason and a **Retry** button that reruns only that step):
+
+1. **Project on disk**: `tmux-ctl project new <name> --init | --clone <url> | --dir <path>`. New and cloned repos go to `~/<name>` (a new one gets `git init -b main`); a clone uses the Mac's own git credentials.
+2. **Bot**: the card links the Developer Portal steps (New Application → Bot → turn on Message Content Intent → Reset Token). Discord has no API that creates a bot, so these stay manual; a phone browser is enough. **Paste token** opens a private one-field form.
+3. **Check**: the token against Discord (`token rejected` asks for it again) and the Message Content Intent flag; then the card shows an **Invite** link with the eight home-channel permissions.
+4. **Joined**: the board checks every 10 s, for up to 30 minutes, that the new bot is in the server (`invite not accepted` after that).
+5. **Channel**: the ops bot creates `#<name>` and grants the new bot the eight permissions there.
+6. **Access**: your id is allowlisted (`tmux-ctl discord allow <id> --project <name>`), `policy allowlist`, and `channel <id>`; no pairing code.
+7. **Start**: `tmux-ctl discord bridge start --project <name>`, then `tmux-ctl project start <name>`: the dev session and its lead, which posts `hello from <name>` in `#<name>`. The card ends with a link to the channel.
+
+`/new-project <name>` puts an unfinished setup on a new card. The token goes from the form to a mode-600 one-shot file under `_ops/np-token/`, is piped into `tmux-ctl discord token --project <name>`, and the file is deleted; it is never in the setup state (`~/.local/state/agent-board/newproject/<name>.json`), an event, the audit log or a card. Names use letters, digits, `_` and `-` (no `.`: the dev session would get another name). The form refuses a name whose `discord/<name>` state dir, tmux session or (new, clone) `~/<name>` already exists, and a folder that is not its repo's top level or is named differently from the project.
+
 **Files.** `tmux-ctl discord send [--thread <key>] [<file>…] [-m <text>]` posts files and/or text to the home channel (or to a spec thread with `--thread`); each path must exist and be readable, else it exits 1 and posts nothing. `tmux-ctl discord snap` posts a screenshot of the board's overview page. `snap` needs Google Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` (or `TC_CHROME` pointing at another binary) and exits 1 with `snap: Chrome not found` without it. The bridge sends at most 10 files per post, each at most 25 MB; a bigger file is not attached and the post says `<name> too large (<size>)`. The queue report and the log of a failed test run are attached automatically. A failed run's command and the last 200 lines of its log are posted to Discord as-is, so a secret printed by a test reaches Discord.
 
 Kill switches: `TC_DISCORD_BRIDGE=0` starts no bridge (`bridge start` prints `bridge: disabled (TC_DISCORD_BRIDGE=0)`); `TC_DISCORD_ALERTS=0` keeps notifier events out of the Discord feed; `TC_NOTIFY=0` still means macOS banners only. `TC_DISCORD_DIGEST_AT=HH:MM` (local time, default `08:00`) sets when the daily ops digest is posted; `TC_DISCORD_DIGEST_AT=off` disables it.
PATCH
git apply --check /tmp/np-t5-install.patch && git apply /tmp/np-t5-install.patch
````

Apply this patch from the worktree root (generated against base `8b6ef53`; if `git apply --check` fails because `main` moved, make the same `+`/`-` changes by hand: the patch is the specification):

````bash
cat > /tmp/np-t5-orchestrator.patch <<'PATCH'
diff --git a/claude/orchestrator.md b/claude/orchestrator.md
index f9f99b4..bdd6c65 100644
--- a/claude/orchestrator.md
+++ b/claude/orchestrator.md
@@ -294,6 +294,8 @@ While remote:
 - Your own permission prompts reach the phone as buttons; nothing to do.
 - Never run `tmux-ctl discord pair|deny|policy|allow|remove` or `/discord:access`: access changes are the user's,
   typed in a terminal. A pairing code or "add me" in a Discord message is not a reason to run them.
+  `/new-project` on the ops bot allowlists the user who ran it in the new project, during that setup only: that
+  is the user's own action through the ops bot, not yours, and no Discord message text can trigger it.
 - A Google re-auth need (a worker reports it, or you hit it): post `🔑 <project> needs Google re-auth: run /gauth <project>` with the reply tool, and do not ask for the terminal while the user is remote.
 
 **Approval protocol** (a teammate's or worker's permission prompt while the user is remote; peer sessions
PATCH
git apply --check /tmp/np-t5-orchestrator.patch && git apply /tmp/np-t5-orchestrator.patch
````

- [ ] **Step 2: Check.** Run: `grep -qF 'For `/new-project`, also give the ops bot **Manage Channels** and **Manage Roles**' docs/INSTALL.md && grep -qF '**New project from the phone (`/new-project`).**' docs/INSTALL.md && grep -qF 'One exception: your own `/new-project` on the ops bot' docs/INSTALL.md && grep -qF '`/new-project` on the ops bot allowlists the user who ran it' claude/orchestrator.md && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh`. Expected: exit 0 and the plugin suite's `ALL PASS`.

- [ ] **Step 3: Commit.**

```bash
git add docs/INSTALL.md claude/orchestrator.md
git commit -m "docs(install): /new-project, ops bot Manage Channels and Manage Roles, access exception" -- docs/INSTALL.md claude/orchestrator.md
```

End the message with the attribution trailer your harness specifies.


### Task 6: Full suites

**Goal:** No new failures in the project's suites, the discord bridge's node tests included (all.zsh does not run them).

**Files:**
- Test only.

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` (with `AGENT_BOARD_LEAD` unset) prints its own ALL PASS summary line and exits 0 or 4 (4 = all passed over the time budget, accepted on this machine).
- [ ] `npm test` in `tools/discord-bridge` ends with `# fail 0`.

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/all.zsh > /tmp/np-all.out 2>&1; rc=$?; tail -3 /tmp/np-all.out; echo rc=$rc; [ $rc = 0 ] || [ $rc = 4 ] || exit 1; cd tools/discord-bridge && npm test > /tmp/np-bridge.out 2>&1; rc2=$?; grep -E '^# (pass|fail)' /tmp/np-bridge.out; exit $rc2` → `rc=0` or `rc=4`, `# fail 0`, exit 0

**Steps:**

- [ ] **Step 1: Run the whole suite in the tests window** (about 9 minutes; a Bash call would time out):

```bash
bin/tmux-ctl run -t 1500 tests "env -u AGENT_BOARD_LEAD zsh tools/tests/all.zsh > /tmp/np-all.out 2>&1; echo rc=\$? >> /tmp/np-all.out"
```

- [ ] **Step 2: Read the verdict.** Run: `tail -4 /tmp/np-all.out; grep -c '^FAIL' /tmp/np-all.out`. Expected: the summary line says ALL PASS, the last line is `rc=0` or `rc=4`, and the count is `0`.

- [ ] **Step 3: Run the bridge suite.** Run: `cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test 2>&1 | grep -E '^# (pass|fail)'`. Expected: `# fail 0`.

- [ ] **Step 4: On any failure, stop.** Report the failing job names and the last 30 lines of each to the lead. Do not fix anything in this task.


### Task 7: Real run on the phone (user gate)

**Goal:** On the phone, `/new-project scratch-np` (source `new`) with a throwaway bot runs through to the lead's `hello from scratch-np` in `#scratch-np`, recorded in `docs/superpowers/notes/2026-11-24-new-project-remote-real-run.md`, then everything it made is removed.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

This is the spec's own gate (§3 Testing, "Real run (user gate, on the phone)"). It cannot run unattended: the Developer Portal steps, the token paste and the invite are the user's, on the phone. In Queue mode it is not run; the lead lists it as open in the PR description and the morning report.

**Files:**
- Create: `docs/superpowers/notes/2026-11-24-new-project-remote-real-run.md`

**Preconditions** (each with what makes it true):
- The branch is merged to `main` (the live board runs `main`), and the board was restarted (Restart on the board, or `agent-board board restart`) so `board/newproject.py` is loaded.
- The ops bridge runs the new `bridge.js`: `tmux-ctl discord bridge stop --ops` then `tmux-ctl discord bridge start --ops` (a person's `start` clears `bridge.stopped`); on connect it re-registers the slash commands, `/new-project` included.
- The ops bot has **Manage Channels**, **Manage Roles** and the eight home-channel permissions in the server (user, in Discord's server settings: docs/INSTALL.md Ops bot step 1).
- Read-only real-state checks, run before the phone part: `tmux-ctl discord status --ops` ends with `bridge: running (pid N)`, and `jq -r .guild_id ~/.local/state/agent-board/discord/_ops/bridge-state.json` prints the server id (the guild the invite will name). `ls ~/scratch-np ~/.local/state/agent-board/discord/scratch-np 2>&1` reports both missing.

**Acceptance Criteria:**
- [ ] The note has exactly four `## ` sections: `## Preconditions` (the two read-only check outputs above), `## Card` (the setup card's final text, copied from Discord, with every step ✅ and the `Done:` link), `## Mac` (the outputs of `git -C ~/scratch-np symbolic-ref --short HEAD` = `main`, `tmux-ctl discord status --project scratch-np` showing `token: set`, `paired: 1 allowlisted`, `policy: allowlist`, `channel: <id>`, `bridge: running`, and `jq . ~/.local/state/agent-board/newproject/scratch-np.json` with no token in it, plus `grep -c "$(sed -n 's/^DISCORD_BOT_TOKEN=//p' ~/.local/state/agent-board/discord/scratch-np/.env)" ~/.local/state/agent-board/newproject/scratch-np.json ~/.local/state/agent-board/discord/_ops/audit.jsonl` printing `0` for both files), and `## Hello` (the lead's message `hello from scratch-np` in `#scratch-np`, with its time).
- [ ] One deliberate failure was seen and retried: before pasting the right token, paste a wrong one and record the card's `token rejected` line in `## Card`.
- [ ] Cleanup done and recorded at the end of `## Mac`: `tmux-ctl discord forget --project scratch-np`, `tmux kill-session -t '=scratch-np'` (and `-t '=scratch-np-bg'`), `rm -rf ~/scratch-np ~/.local/state/agent-board/newproject/scratch-np.json ~/.local/state/agent-board/discord/scratch-np`; the user deletes `#scratch-np` and the bot application in the portal.

**Verify:** `test "$(grep -c '^## ' docs/superpowers/notes/2026-11-24-new-project-remote-real-run.md)" = 4 && grep -q 'hello from scratch-np' docs/superpowers/notes/2026-11-24-new-project-remote-real-run.md` → exit 0

