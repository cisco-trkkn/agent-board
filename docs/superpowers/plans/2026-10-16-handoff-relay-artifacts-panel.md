# Handoff Relay, Artifacts Panel, Ideas Inbox and Activity Drawer: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hand long orchestrator sessions to a fresh lead in place, with the team carried over. Show session artifacts, a live editable plan, an ideas inbox and agent test runs in the Agent Board.

**Architecture:**
- A hook records artifacts into per-project JSONL manifests in the tmux-ctl state dir. Small Python modules next to the board server read those manifests, the ideas file, run records and lineage, and expose them as JSON endpoints.
- `tmux-ctl` routes agent `tests`/`shell` windows to a hidden `<project>-bg` session, records runs, and delegates `artifact`/`idea`/`relay` to those modules.
- The handoff skill checkpoints teammates, asks the user, and calls `tmux-ctl relay`. `relay.py` waits for the lead's turn to end and respawns the `claude` pane in place.

**Tech Stack:** zsh, tmux, jq, Python 3 stdlib (`unittest`, `http.server`, `fcntl`), vanilla JS/CSS in one HTML page, vendored `marked` 12.0.2 and `DOMPurify` 3.1.6.

**Spec:** `docs/superpowers/specs/2026-10-16-handoff-relay-artifacts-panel-design.md`

## Global Constraints

- **No VCS for tool files.**
  - The tool files (`~/.local/bin`, `~/.local/share/tmux-dash`, `~/.local/share/tmux-tools`, `~/.claude`) are not under version control.
  - Before the first edit of any existing file, make a one-time backup: `[[ -e F.bak-20261016 ]] || cp -p F F.bak-20261016`.
  - There are no git commits for them. Report the files changed instead.
- **Live tools are staged.** `tmux-ctl`, `dev`, `tmux-dev-layout`, `bash-mirror.sh` and `index.html` are in use by this team and the user right now.
  - Edit a staged copy (`F.next`, or `index.next.html`), test it, then swap it in with `mv` only after its tests pass.
  - zsh tests take the binary path from an env override (`TC_CTL`, `TC_LAYOUT`, `TC_DEV`, `TC_MIRROR`) so they can run against the staged copy.
- **Edit in place, restart once.**
  - `server.py` and new Python modules are edited in place. The running board loads them only at start.
  - Restart the board (`tmux-dash stop && tmux-dash`) only in Task 14.
- **Isolated tests.**
  - Every zsh test uses `~/.local/share/tmux-tools/tests/lib.zsh` (`tt_setup`), which runs an isolated tmux server (`-L`).
  - Never run a test against the user's real tmux server or the live `master-gcp-repo` session.
  - Never run `dev` or `tmux-dev-layout` on a real session.
- **Killing processes.** Never `pkill`/`killall`. Kill by PID only.
- **Running suites.**
  - zsh: `tmux-ctl run tests "zsh ~/.local/share/tmux-tools/tests/run-all.zsh"`.
  - Python: `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v"`.
- **Hooks never block.** The hook (`artifact-register.sh`) always exits 0 and is silent.
- **Board security.**
  - Board endpoints keep the token path, `Host` check and `X-Dash-Token` check for POSTs.
  - Files are served only from the manifest allowlist. Logs are served only by run id.
- **Names used everywhere:**
  - `<project>` is the canonical tmux session key: `#{?session_group,#{session_group},#{session_name}}`.
  - The hidden session is `<project>-bg`, with session option `@tc_bg 1`.
  - `$STATE` is `${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}`.
- **Files:**
  - Manifest: `$STATE/artifacts-<project>.jsonl`, entries `{ts,path,kind,agent,hash,url,session_id,epoch}`.
  - Lineage: `$STATE/lineage-<project>.jsonl`, entries `{ts,old_session_id,doc,pane}`. `epoch` = the number of lineage lines.
  - Runs: `$STATE/runs-<project>.jsonl`, entries `{id,ts,agent,win,session,cmd,cwd,exit,duration,log,summary}`. A start record has `exit: null`; the final record has the same id.
  - Logs: `$STATE/logs/<project>/<id>.log`.
  - Ideas: `${TC_IDEAS_DIR:-~/.claude/ideas}/<project>.md`.

**User decisions (already made):**
- The panel lives in the Agent Board as a hideable left sidebar.
- Plan interactions: comment to the lead, inline edit, see what changed with agent attribution. No ticking or reordering of tasks.
- Teammates are carried by checkpoint and respawn.
- The new lead replaces the old one in place, in the `claude` window.
- Every switch asks the user first.
- The panel seeds the current lead's artifacts on load, then accumulates for the page's lifetime. Refresh or close drops older sessions' items.
- Artifact registration: manifest plus hooks (option 1).
- Ideas are stored per project in `~/.claude/ideas/<project>.md`.
- `shell`/`tests` are replaced: the user keeps one plain `shell`, agent windows go to a hidden `-bg` session, and runs show in a board Activity drawer.
- The "Plan done" cue counts `- [ ]` / `- [x]` checkboxes in the plan file.

## Ownership and order

| Teammate (tier) | Tasks | Owns |
| --- | --- | --- |
| `layout` (standard) | 2, 3, 4, 5 | `tmux-ctl`, `dev`, `tmux-dev-layout`, `bash-mirror.sh`, `artifact-register.sh`, `settings.json`, tmux-tools tests |
| `panel` (standard) | 1, 7, 8, 9, 10, 11 | `server.py`, `index.html`, `paneclass.py`, `ideas.py`, `artifacts.py`, `activity.py`, `vendor/`, tmux-dash tests |
| `relay` (frontier) | 6, 12, 13 | `relay.py`, `test_relay.py`, handoff `SKILL.md`, `context-size-guard.sh`, `orchestrator.md`, `worker.md`, tmux-orchestrator `SKILL.md` |
| `review` (standard) | spec + quality review of every task; Task 14 | read-only until 14 |

Only `layout` edits `tmux-ctl`. Only `panel` edits `server.py`.

## File structure

| File | Responsibility |
| --- | --- |
| `~/.local/share/tmux-dash/paneclass.py` (new) | Classify a pane (claude working/waiting/ready, shell, program). Shared by the board and the relay. |
| `~/.local/share/tmux-dash/relay.py` (new) | Wait for turn end, respawn the `claude` pane with a prompt, write lineage. CLI for `tmux-ctl relay`. |
| `~/.local/share/tmux-dash/ideas.py` (new) | Locked append and parse of the ideas file. CLI for `tmux-ctl idea`. |
| `~/.local/share/tmux-dash/artifacts.py` (new) | Manifest summary, allowlisted read, hash-checked save, `CommentQueue`. |
| `~/.local/share/tmux-dash/activity.py` (new) | Run records, logs by id, parsed feed. |
| `~/.local/share/tmux-dash/server.py` | HTTP routes only. Imports the modules above. |
| `~/.local/share/tmux-dash/index.html` | Sidebar, viewer, ideas box, Activity drawer. |
| `~/.local/share/tmux-dash/vendor/{marked.min.js,purify.min.js}` (new) | Markdown rendering and sanitising. |
| `~/.claude/hooks/artifact-register.sh` (new) | Records manifest entries (hook mode and manual mode). |
| `~/.local/bin/tmux-ctl` | `-bg` routing, run records, `artifact`/`idea`/`relay` subcommands. |
| `~/.local/bin/dev`, `~/.local/bin/tmux-dev-layout` | Two user windows; idempotent migration; `-bg` creation. |
| `~/.claude/hooks/bash-mirror.sh` | Keeps writing feed logs once `tests` moved to `-bg`. |
| `~/.claude/skills/handoff/SKILL.md` | Checkpoint, Team section, confirm, relay. |
| `~/.claude/orchestrator.md`, `~/.claude/worker.md`, `~/.claude/skills/tmux-orchestrator/SKILL.md` | New rules and window tables. |

---

### Task 1: Shared pane classifier

**Goal:** Move `classify` and its regexes out of `server.py` into `paneclass.py`, add `pane_status(tmux, pane)` and a CLI, and have `server.py` import them.

**Files:**
- Create: `~/.local/share/tmux-dash/paneclass.py`
- Modify: `~/.local/share/tmux-dash/server.py` (remove `SHELLS`, `VERSION_RE`, `WAITING_RE`, `WORKING_RE`, `classify`; import them)
- Test: `~/.local/share/tmux-dash/tests/test_paneclass.py`

**Acceptance Criteria:**
- [ ] `server.classify is paneclass.classify`
- [ ] `pane_status(fake_tmux, "%3")` returns `("claude", "working")` for a pane showing "esc to interrupt"
- [ ] `python3 paneclass.py status` with no pane exits 2 with usage
- [ ] The existing `test_restart_orchestrator.py` still passes

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing test** `tests/test_paneclass.py`

```python
import importlib.util
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import paneclass  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_pc", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ClassifyTest(unittest.TestCase):
    def test_shell_idle(self):
        self.assertEqual(paneclass.classify("zsh", [], False), ("shell", "idle"))

    def test_working(self):
        self.assertEqual(paneclass.classify("2.1.0", ["✻ Thinking… (esc to interrupt)"], False), ("claude", "working"))

    def test_waiting(self):
        self.assertEqual(paneclass.classify("2.1.0", ["Do you want to proceed?", "❯ 1. Yes"], False), ("claude", "waiting"))

    def test_ready(self):
        self.assertEqual(paneclass.classify("2.1.0", ["> "], True), ("claude", "ready"))

    def test_program(self):
        self.assertEqual(paneclass.classify("vim", [], False), ("program", "running"))

    def test_server_uses_shared(self):
        self.assertIs(server.classify, paneclass.classify)


class PaneStatusTest(unittest.TestCase):
    def test_pane_status(self):
        calls = []

        def tmux(*a, check=False):
            calls.append(a)
            if a[0] == "display":
                return f"2.1.0{paneclass.SEP}0\n"
            return "line\n✻ Working (esc to interrupt)\n\n"

        self.assertEqual(paneclass.pane_status(tmux, "%3"), ("claude", "working"))
        self.assertEqual(calls[0][:3], ("display", "-p", "-t"))
        self.assertEqual(calls[1][0], "capture-pane")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_paneclass -v`
Expected: `ModuleNotFoundError: No module named 'paneclass'`

- [ ] **Step 3: Create `paneclass.py`**

```python
#!/usr/bin/env python3
"""paneclass: what a tmux pane is doing (claude working/waiting/ready, a shell, a program).

Shared by tmux-dash (server.py) and the handoff relay (relay.py), so both read panes the same way.
CLI: paneclass.py status <pane-id>   -> prints "<kind> <status>"
"""
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SHELLS = {"zsh", "bash", "sh", "fish", "-zsh", "-bash"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")
WAITING_RE = re.compile(
    r"Do you want to|Would you like to|\(y/n\)|❯\s*1\.\s*Yes|Allow this|Press Enter to continue|Enter to confirm",
    re.I,
)
WORKING_RE = re.compile(r"esc to interrupt", re.I)
SEP = "\x1f"


def classify(cmd, rows, bell):
    """kind: claude | shell | program ; status: waiting | working | ready | idle | running"""
    is_claude = bool(VERSION_RE.match(cmd)) or "claude" in cmd.lower()
    # Claude draws its prompts and spinner at the bottom; older scrollback may quote prompt text.
    tail = "\n".join(rows[-12:])
    if cmd in SHELLS:
        return "shell", "idle"
    if is_claude:
        if WORKING_RE.search(tail):  # no spinner while a prompt is open
            return "claude", "working"
        if WAITING_RE.search(tail):
            return "claude", "waiting"
        # Claude also rings the bell when it finishes; a real prompt is caught by WAITING_RE above.
        return "claude", "ready"
    return "program", "waiting" if bell else "running"


def tmux_runner(extra=()):
    """A tmux(*args, check=False) -> stdout callable; extra args (e.g. -S socket) go before the command."""
    base = [os.environ.get("TC_TMUX") or str(Path.home() / ".local" / "bin" / "tmux")]
    base += shlex.split(os.environ.get("TMUX_DASH_TMUX_ARGS", "")) + list(extra)

    def run(*args, check=False):
        r = subprocess.run(base + list(args), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"tmux {args[0]} failed")
        return r.stdout

    return run


def pane_status(tmux, pane, lines=40):
    info = tmux("display", "-p", "-t", pane, f"#{{pane_current_command}}{SEP}#{{window_bell_flag}}", check=True).strip()
    cmd, _, bell = info.partition(SEP)
    rows = [l.rstrip() for l in tmux("capture-pane", "-p", "-J", "-t", pane, "-S", f"-{lines}").splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return classify(cmd, rows, bell == "1")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "status":
        print(*pane_status(tmux_runner(), sys.argv[2]))
    else:
        print("usage: paneclass.py status <pane-id>", file=sys.stderr)
        sys.exit(2)
```

- [ ] **Step 4: Point `server.py` at it**

  Back up `server.py`. Delete the `SHELLS = …`, `VERSION_RE = …`, `WAITING_RE = …` (3 lines) and `WORKING_RE = …` definitions and the whole `def classify(...)` function. Directly after the line `HERE = Path(__file__).resolve().parent`, add:

```python
sys.path.insert(0, str(HERE))
from paneclass import SHELLS, VERSION_RE, WAITING_RE, WORKING_RE, classify  # noqa: E402,F401
```

  `SEP` stays in `server.py`; it is the same value.

- [ ] **Step 5: Run the whole suite**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v`
Expected: all tests OK, including `test_restart_orchestrator`.

- [ ] **Step 6: Report** the files changed and the test output to the lead.

```json:metadata
{"files": ["~/.local/share/tmux-dash/paneclass.py", "~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/tests/test_paneclass.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v", "acceptanceCriteria": ["server.classify is paneclass.classify", "pane_status returns (claude, working) for a working pane", "CLI usage exits 2", "test_restart_orchestrator passes"], "modelTier": "mechanical", "owner": "panel"}
```

---

### Task 2: Artifact registration hook

**Goal:** `artifact-register.sh` appends manifest entries for matching Write/Edit/MultiEdit/Artifact calls (hook mode) or for an explicit path (manual mode). It is then registered as an async PostToolUse hook.

**Files:**
- Create: `~/.claude/hooks/artifact-register.sh` (chmod +x)
- Modify: `~/.claude/settings.json` (add one PostToolUse entry; register last)
- Test: `~/.local/share/tmux-tools/tests/test_artifact_hook.zsh`

**Acceptance Criteria:**
- [ ] A plan write records `{kind:"plan", agent:"impl", hash:<64 hex>, epoch:0}` when the window is named `✦ impl`
- [ ] A non-matching path writes nothing
- [ ] `epoch` equals the number of lines in `lineage-<project>.jsonl`
- [ ] An Artifact publish records `kind:"published"` with the claude.ai URL
- [ ] Manual mode `--path P --kind K --agent A --project N` works outside tmux
- [ ] Invalid JSON and running outside tmux both exit 0 with no output
- [ ] `settings.json` stays valid JSON (`jq . settings.json`) with the new entry

**Verify:** `zsh ~/.local/share/tmux-tools/tests/test_artifact_hook.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** `test_artifact_hook.zsh`

```zsh
source "${0:A:h}/lib.zsh"
H="${TC_HOOK:-$HOME/.claude/hooks/artifact-register.sh}"
tt_setup claude
tt rename-window -t '=tt:claude' '✦ impl'
mkdir -p "$TT_DIR/r/docs/superpowers/plans" "$TT_DIR/sp/scratchpad"
plan="$TT_DIR/r/docs/superpowers/plans/p.md"; print "# P" > "$plan"
m="$TC_STATE/artifacts-tt.jsonl"
hook() { print -r -- "$1" | "$H" }
hook "{\"tool_name\":\"Write\",\"session_id\":\"S1\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "plan recorded"       test "$(jq -r .kind "$m" | tail -1)" = plan
check "agent from window"   test "$(jq -r .agent "$m" | tail -1)" = impl
check "hash present"        test "$(jq -r .hash "$m" | tail -1 | tr -d '\n' | wc -c | tr -d ' ')" = 64
check "session id"          test "$(jq -r .session_id "$m" | tail -1)" = S1
check "epoch 0"             test "$(jq -r .epoch "$m" | tail -1)" = 0
other="$TT_DIR/r/notes.md"; print x > "$other"
n0=$(wc -l < "$m")
hook "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$other\"}}"
check "unmatched ignored"   test "$(wc -l < "$m")" -eq "$n0"
print '{}' > "$TC_STATE/lineage-tt.jsonl"
hook "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "epoch from lineage"  test "$(jq -r .epoch "$m" | tail -1)" = 1
rep="$TT_DIR/sp/scratchpad/e2e-report.md"; print r > "$rep"
hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$rep\"}}"
check "report kind"         test "$(jq -r .kind "$m" | tail -1)" = report
ho="${TMPDIR:-/tmp}/tt-handoff-$$.md"; print h > "$ho"
hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ho\"}}"
check "tmp handoff kind"    test "$(jq -r .kind "$m" | tail -1)" = handoff
rm -f "$ho"
hook '{"tool_name":"Artifact","tool_input":{"file_path":"/x/page.html"},"tool_response":"Published https://claude.ai/code/artifact/abc-123 ok"}'
check "published url"       test "$(jq -r .url "$m" | tail -1)" = "https://claude.ai/code/artifact/abc-123"
( unset TMUX TMUX_PANE; "$H" --path "$other" --kind other --agent you --project tt )
check "manual mode"         test "$(jq -r '.agent+" "+.kind' "$m" | tail -1)" = "you other"
hook 'not json'; rc=$?
check "bad input exit 0"    test $rc -eq 0
out="$( unset TMUX TMUX_PANE; print -r -- "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$plan\"}}" | "$H"; print rc=$? )"
check "outside tmux silent" test "$out" = "rc=0"
tt_done
```

- [ ] **Step 2: Run it and see it fail**

Run: `zsh ~/.local/share/tmux-tools/tests/test_artifact_hook.zsh`
Expected: FAIL lines (the hook doesn't exist yet).

- [ ] **Step 3: Write the hook** `~/.claude/hooks/artifact-register.sh`

```zsh
#!/usr/bin/env zsh
# artifact-register.sh — record session artifacts for the Agent Board.
#   hook mode (PostToolUse Write|Edit|MultiEdit|Artifact): reads the hook JSON on stdin
#   manual mode: artifact-register.sh --path P [--kind K] [--agent A] [--project NAME]
# Appends {ts,path,kind,agent,hash,url,session_id,epoch} to $STATE/artifacts-<project>.jsonl.
# epoch = lines in $STATE/lineage-<project>.jsonl (one per handoff relay). Silent; always exits 0.
emulate -L zsh
STATE="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}"
TMUX_BIN="${TC_TMUX:-$HOME/.local/bin/tmux}"
{
  path= kind= agent= project= manual=0
  while (( $# )); do
    case "$1" in
      --path)    path="$2"; manual=1; shift 2 ;;
      --kind)    kind="$2"; shift 2 ;;
      --agent)   agent="$2"; shift 2 ;;
      --project) project="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ -z "$project" ]]; then
    [[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
    project="$("$TMUX_BIN" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}')" || exit 0
  fi
  [[ "$project" =~ '^[A-Za-z0-9._-]+$' ]] || exit 0
  if [[ -z "$agent" ]]; then
    [[ -n "$TMUX_PANE" ]] && agent="$("$TMUX_BIN" display -p -t "$TMUX_PANE" '#{window_name}')"
    agent="${agent#✦ }"; agent="${agent:-claude}"
  fi
  mkdir -p "$STATE"
  lineage="$STATE/lineage-$project.jsonl"
  epoch=0; [[ -f "$lineage" ]] && epoch=$(( $(wc -l < "$lineage") ))
  if (( manual )); then payload='{}'; else payload="$(cat)"; fi
  line="$(print -r -- "$payload" | python3 -I -c '
import hashlib, json, os, re, sys, time
manual, path, kind, agent, epoch, home, tmp = sys.argv[1:8]
manual = manual == "1"
url = sid = ""
if not manual:
    try:
        d = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = d.get("tool_name") or ""
    ti = d.get("tool_input") or {}
    sid = d.get("session_id") or ""
    if tool == "Artifact":
        m = re.search(r"https://claude\.ai/[\w/.-]+", json.dumps(d.get("tool_response") or ""))
        if not m:
            sys.exit(0)
        url, kind = m.group(0), "published"
        path = ti.get("file_path") or url
    elif tool in ("Write", "Edit", "MultiEdit"):
        path = ti.get("file_path") or ""
    else:
        sys.exit(0)
if not path:
    sys.exit(0)
if not url:
    path = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(path):
        sys.exit(0)
def kind_of(p):
    if not p.endswith(".md"):
        return ""
    h, t, base = os.path.realpath(home), os.path.realpath(tmp), os.path.basename(p)
    if "/docs/superpowers/plans/" in p: return "plan"
    if "/docs/superpowers/specs/" in p: return "spec"
    if p.startswith(os.path.join(h, ".claude", "handoffs") + os.sep): return "handoff"
    if p.startswith(t + os.sep) and "handoff" in base: return "handoff"
    if "/scratchpad/" in p and "report" in base: return "report"
    return ""
if not kind:
    kind = kind_of(path) or ("other" if manual else "")
if not kind:
    sys.exit(0)
digest = ""
if not url:
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
print(json.dumps({"ts": time.time(), "path": path, "kind": kind, "agent": agent, "hash": digest,
                  "url": url, "session_id": sid, "epoch": int(epoch)}))
' "$manual" "$path" "$kind" "$agent" "$epoch" "$HOME" "${TMPDIR:-/tmp}")"
  [[ -n "$line" ]] && print -r -- "$line" >> "$STATE/artifacts-$project.jsonl"
} >/dev/null 2>&1
exit 0
```

  Then run `chmod +x ~/.claude/hooks/artifact-register.sh`.

- [ ] **Step 4: Run the test**

Run: `zsh ~/.local/share/tmux-tools/tests/test_artifact_hook.zsh`
Expected: `ALL PASS`

- [ ] **Step 5: Register the hook (last)**

```zsh
f=~/.claude/settings.json; [[ -e $f.bak-20261016 ]] || cp -p $f $f.bak-20261016
jq '.hooks.PostToolUse += [{"matcher":"Write|Edit|MultiEdit|Artifact","hooks":[{"type":"command","command":"~/.claude/hooks/artifact-register.sh","async":true,"timeout":5}]}]' $f > $f.tmp && jq -e . $f.tmp >/dev/null && mv $f.tmp $f
jq '.hooks.PostToolUse | map(.matcher)' $f
```

  Expected: `["Bash", "Write|Edit|MultiEdit|Artifact"]`

- [ ] **Step 6: Report** the files changed and the test output.

```json:metadata
{"files": ["~/.claude/hooks/artifact-register.sh", "~/.claude/settings.json", "~/.local/share/tmux-tools/tests/test_artifact_hook.zsh"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/test_artifact_hook.zsh", "acceptanceCriteria": ["plan write recorded with agent impl, 64-hex hash, epoch 0", "non-matching path ignored", "epoch = lineage line count", "Artifact publish recorded with url", "manual mode works outside tmux", "bad input and outside tmux exit 0 silently", "settings.json valid with new entry"], "modelTier": "standard", "owner": "layout"}
```

---

### Task 3: Hidden agent session and run records in tmux-ctl

**Goal:** `tmux-ctl` sends `tests`/`shell` (and their lanes) to `<project>-bg`, records every `run` in `runs-<project>.jsonl` with a log and summary, and lists `-bg` windows. `bash-mirror.sh` keeps writing feeds after `tests` leaves the main session.

**Files:**
- Modify (staged): `~/.local/bin/tmux-ctl` → work in `~/.local/bin/tmux-ctl.next`
- Modify (staged): `~/.claude/hooks/bash-mirror.sh` → `bash-mirror.sh.next`
- Create: `~/.local/share/tmux-tools/tests/test_bg.zsh`
- Modify: `~/.local/share/tmux-tools/tests/*.zsh`
  - change `C=~/.local/bin/tmux-ctl` to `C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"`;
  - make the mirror test use `${TC_MIRROR:-…}`;
  - retarget agent windows to `=tt-bg:` (details in Step 5).

**Acceptance Criteria:**
- [ ] `tmux-ctl run tests 'echo hi'` prints `hi` and creates `tt-bg` with windows `shell tests` and `@tc_bg 1`
- [ ] The user's `shell` window in the main session never receives agent keystrokes
- [ ] The runs file holds a start record (`exit:null`) and a final record (`exit:0`) with the same id, plus a log file containing the output
- [ ] Summary `3 passed, 1 failed` is parsed from pytest-style output; `ALL PASS` / `N FAILED` from zsh runners
- [ ] `tmux-ctl list` shows `-bg` windows tagged `(bg)`; `read tests` reads the `-bg` window
- [ ] The full `run-all.zsh` passes against `tmux-ctl.next`, then the swap is done

**Verify:** `TC_CTL=~/.local/bin/tmux-ctl.next TC_MIRROR=~/.claude/hooks/bash-mirror.sh.next zsh ~/.local/share/tmux-tools/tests/run-all.zsh` → every file ends `ALL PASS`

**Steps:**

- [ ] **Step 1: Stage the copies**

```zsh
cd ~/.local/bin && cp -p tmux-ctl tmux-ctl.bak-20261016 && cp -p tmux-ctl tmux-ctl.next
cd ~/.claude/hooks && cp -p bash-mirror.sh bash-mirror.sh.bak-20261016 && cp -p bash-mirror.sh bash-mirror.sh.next
```

- [ ] **Step 2: Write the failing test** `test_bg.zsh`

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup claude shell
check "run goes to bg"       test "$($C run tests 'echo hi' | head -1)" = hi
check "bg session exists"    tt has-session -t '=tt-bg'
check "bg flagged"           test "$(tt show-options -qv -t '=tt-bg' @tc_bg)" = 1
check "bg windows"           test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | sort | tr '\n' ' ')" = "shell tests "
check "user shell untouched" sh -c "! $TT_BIN capture-pane -p -t '=tt:shell' | grep -q 'echo hi'"
r="$TC_STATE/runs-tt.jsonl"
check "start record"         test "$(jq -sr '[.[]|select(.cmd=="echo hi")]|first|.exit' "$r")" = null
check "final record"         test "$(jq -sr '[.[]|select(.cmd=="echo hi")]|last|.exit' "$r")" = 0
check "same id"              test "$(jq -sr '[.[]|select(.cmd=="echo hi")|.id]|unique|length' "$r")" = 1
lg="$(jq -sr 'last|.log' "$r")"
check "log written"          grep -qx hi "$lg"
check "session recorded"     test "$(jq -sr 'last|.session' "$r")" = tt-bg
$C run tests 'print "3 passed, 1 failed"; false' >/dev/null
check "summary parsed"       test "$(jq -sr 'last|.summary' "$r")" = "3 passed, 1 failed"
check "exit recorded"        test "$(jq -sr 'last|.exit' "$r")" = 1
check "agent recorded"       test "$(jq -sr 'last|.agent' "$r")" = claude
$C run tests 'print ALL PASS' >/dev/null
check "zsh summary"          test "$(jq -sr 'last|.summary' "$r")" = "ALL PASS"
check "list shows bg"        sh -c "$C list | grep -q 'tests .*(bg)'"
check "read bg"              sh -c "$C read tests 40 | grep -q 'echo hi'"
check "send to bg shell"     sh -c "$C send shell 'echo via-send' && sleep 1 && $TT_BIN capture-pane -p -t '=tt-bg:shell' | grep -q via-send"
tt_done
```

- [ ] **Step 3: Run it and see it fail**

Run: `TC_CTL=~/.local/bin/tmux-ctl.next zsh ~/.local/share/tmux-tools/tests/test_bg.zsh`
Expected: FAIL on "bg session exists" and later checks.

- [ ] **Step 4: Implement in `tmux-ctl.next`**

  (a) Directly after the `FEEDKEY=…` line, add:

```zsh
MAIN="$SESSION"
BG="$FEEDKEY-bg"   # hidden session for the agents' tests/shell windows and their lanes (user keeps a plain shell)
is_bg_win() { [[ "${1%%·*}" == (tests|shell) ]] }
ensure_bg() {
  t has-session -t "=$BG" 2>/dev/null && return
  local root; root="$(git rev-parse --show-toplevel 2>/dev/null)" || root="$PWD"
  t new-session -d -s "$BG" -n tests -c "$root"
  t new-window -d -t "=$BG:" -n shell -c "$root"
  t set-option -t "=$BG" @tc_bg 1
}
# use_win <win>: point $SESSION at the session that holds <win>
use_win() { if is_bg_win "$1"; then ensure_bg; SESSION="$BG"; else SESSION="$MAIN"; fi }
```

  (b) Add these helpers after `trim()`:

```zsh
# summarize <logfile>: "42 passed, 1 failed" (pytest-style) or "ALL PASS"/"N FAILED" (tmux-tools runners)
summarize() {
  local s
  s="$(grep -oE '[0-9]+ (passed|failed|errors?|skipped)' "$1" | tail -4 | paste -sd, - | sed 's/,/, /g')"
  [[ -z "$s" ]] && s="$(grep -oE '^(ALL PASS|[0-9]+ FAILED)$' "$1" | tail -1)"
  print -r -- "$s"
}
# run_record <exit|null> <duration> <summary>: append one record for the current run
run_record() {
  jq -nc --arg id "$id" --argjson ts "$t0" --arg agent "$(caller)" --arg win "$win" --arg session "$SESSION" \
    --arg cmd "$cmdtext" --arg cwd "$cdir" --argjson exit "$1" --argjson duration "$2" --arg log "$logf" --arg summary "$3" \
    '{id:$id,ts:$ts,agent:$agent,win:$win,session:$session,cmd:$cmd,cwd:$cwd,exit:$exit,duration:$duration,log:$log,summary:$summary}' \
    >> "$STATE/runs-$FEEDKEY.jsonl"
}
```

  (c) Replace the line `[[ "$cmd" == (_done|help|-h|--help|"") ]] || reap_lanes` with:

```zsh
if [[ "$cmd" != (_done|help|-h|--help|"") ]]; then
  for SESSION in "$MAIN" "$BG"; do t has-session -t "=$SESSION" 2>/dev/null && reap_lanes; done
  SESSION="$MAIN"
fi
```

  (d) Make `list)` print both sessions. Wrap the existing loop body in `list_session() { … }` with `$SESSION` unchanged inside, then:

```zsh
  list)
    list_session
    if t has-session -t "=$BG" 2>/dev/null; then
      SESSION="$BG"; list_session | sed 's/$/  (bg)/'; SESSION="$MAIN"
    fi ;;
```

  (e) In `read)`, `run)`, `send)` and `keys)`, put `use_win "$win"` right before `exists "$win"`. For `read)` the window variable is `win="$1"`, so call `use_win "$win"` after it is set.

  (f) In `run)`, directly after `id="$$-$RANDOM"; rm -f "$STATE/$id.rc"`, add:

```zsh
    cmdtext="$*"; t0=$EPOCHSECONDS; logf="$STATE/logs/$FEEDKEY/$id.log"; mkdir -p "${logf:h}"
    run_record null 0 ""
```

  Replace the timeout line's body so it records first:

```zsh
      (( ++ticks > timeout * 2 )) && { run_record 124 $(( EPOCHSECONDS - t0 )) "timeout"; print -u2 "tmux-ctl: still running after ${timeout}s — check: tmux-ctl read $win"; exit 124; }
```

  Replace the capture and print lines at the end of `run)` with:

```zsh
    hist=$(t display -p -t "$tgt" '#{history_size}')
    out="$(t capture-pane -p -J -t "$tgt" -S $(( start - hist )) | awk -v m="@@TCSTART-$id" 'f{print} $0==m{f=1}' | trim | sed '$d')"   # last line = the shell prompt again
    print -r -- "$out" > "$logf"
    run_record "$rc" $(( EPOCHSECONDS - t0 )) "$(summarize "$logf")"
    print -r -- "$out"
    print -r -- "[exit $rc]"
    exit "$rc" ;;
```

  (g) In the help header, after the `run` lines, add:
  `#                                          tests/shell (and lanes) live in the hidden session <project>-bg; runs are recorded for the board's Activity drawer`

- [ ] **Step 5: Retarget the existing tests**
  - In every `test_*.zsh` that sets `C=~/.local/bin/tmux-ctl`, change it to `C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"`.
  - In `test_mirror.zsh`, change the hook path to `"${TC_MIRROR:-$HOME/.claude/hooks/bash-mirror.sh}"`.
  - Where a test makes panes or lanes in `=tt:tests` / `=tt:shell` to exercise `tmux-ctl`:
    1. First run `$C run tests true >/dev/null` (this creates `tt-bg`).
    2. Then address `=tt-bg:tests` / `=tt-bg:shell` instead.
  - Rewrite `test_ctl_panes.zsh` to:

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup claude
$C run tests true >/dev/null
log="$TC_STATE/feed-tt-tests.log"; printf 'a\nb\nc\nd\n' > "$log"
fp="$(tt split-window -d -v -l 35% -t '=tt-bg:tests' -P -F '#{pane_id}' "tail -n 30 -F $log")"
tt set-option -p -t "$fp" @tc_role feed
tt select-pane -t "$fp"                                  # feed pane active: worst case
tt_wait 3 test "$(tt display -p -t "$fp" '#{pane_current_command}')" = tail
check "run uses main pane"      test "$($C run tests 'echo hi' | head -1)" = hi
$C run tests false >/dev/null; check "exit code kept" test $? -eq 1
check "read main"               tt_wait 3 sh -c "$C read tests 5 | grep -q 'echo hi'"
check "read feed"               sh -c "$C read tests feed 5 | grep -q '^d$'"
check "feed cmd"                test "$($C feed tests 3 | tr '\n' ' ')" = "b c d "
tt new-window -d -t '=tt-bg:' -n 'tests·x'; tt set-option -w -t '=tt-bg:tests·x' @tc_lane 1
check "list shows lane"         sh -c "$C list | grep -q 'tests·x.*(lane).*(bg)'"
check "list tests idle"         sh -c "$C list | grep -q ' tests  \[idle\]'"
tt_done
```

  (`read main` now waits up to 3s; it was the known flaky check.)

- [ ] **Step 6: Fix `bash-mirror.sh.next`**

  Replace `(( ${winarr[(Ie)$kind]} )) || exit 0` with:

```zsh
  # feeds are written for dev sessions: the agents' window lives in <project>-bg (or, before migration, here)
  "$T" has-session -t "=$canon-bg" 2>/dev/null || (( ${winarr[(Ie)$kind]} )) || exit 0
```

- [ ] **Step 7: Run everything against the staged copies**

Run: `TC_CTL=~/.local/bin/tmux-ctl.next TC_MIRROR=~/.claude/hooks/bash-mirror.sh.next zsh ~/.local/share/tmux-tools/tests/run-all.zsh`
Expected: every file prints `ALL PASS`. Fix and re-run until it does.

- [ ] **Step 8: Swap in**

```zsh
chmod +x ~/.local/bin/tmux-ctl.next ~/.claude/hooks/bash-mirror.sh.next
mv ~/.local/bin/tmux-ctl.next ~/.local/bin/tmux-ctl && mv ~/.claude/hooks/bash-mirror.sh.next ~/.claude/hooks/bash-mirror.sh
zsh ~/.local/share/tmux-tools/tests/run-all.zsh
```

  Expected: all pass with the installed files.

- [ ] **Step 9: Report** the files changed and the test output. Tell the lead that agent runs now go to `<project>-bg`.

```json:metadata
{"files": ["~/.local/bin/tmux-ctl", "~/.claude/hooks/bash-mirror.sh", "~/.local/share/tmux-tools/tests/test_bg.zsh", "~/.local/share/tmux-tools/tests/test_ctl_panes.zsh", "~/.local/share/tmux-tools/tests/test_ctl_lanes.zsh", "~/.local/share/tmux-tools/tests/test_mirror.zsh"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/run-all.zsh", "acceptanceCriteria": ["run tests creates tt-bg with shell+tests and @tc_bg 1", "user shell gets no agent keystrokes", "start and final run records with same id plus log", "summary parsed for pytest and zsh runners", "list tags bg windows; read tests reads bg", "run-all passes against .next then after swap"], "modelTier": "standard", "owner": "layout"}
```

---

### Task 4: Two user windows and idempotent migration

**Goal:** `dev` creates only `claude` + a plain `shell`. `tmux-dev-layout` creates `<project>-bg`, migrates old sessions (moves `tests`, removes feed/watch panes and labels), and runs `.dev/windows` watch commands in `-bg`.

**Files:**
- Modify (staged): `~/.local/bin/dev` → `dev.next`; `~/.local/bin/tmux-dev-layout` → `tmux-dev-layout.next`
- Modify: `~/.local/share/tmux-tools/tests/test_layout.zsh` (full rewrite below)

**Acceptance Criteria:**
- [ ] After layout, the main session has exactly `claude shell` and `-bg` has `shell tests` with `@tc_bg 1`
- [ ] No pane in the main session has `@tc_role`; `@tc_label` is unset on `shell`
- [ ] Running the layout a second time changes nothing
- [ ] A `.dev/windows` `tests:` command runs in exactly one watch pane in `-bg:tests`
- [ ] A busy `tests` window in the main session is left in place, with a note on stderr
- [ ] `DEV_NO_ATTACH=1 dev <dir>` yields `claude shell` plus `<name>-bg`

**Verify:** `TC_LAYOUT=~/.local/bin/tmux-dev-layout.next TC_DEV=~/.local/bin/dev.next zsh ~/.local/share/tmux-tools/tests/test_layout.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Stage** `dev.next` and `tmux-dev-layout.next` (back up both, then copy).

- [ ] **Step 2: Write the failing test** (replaces `test_layout.zsh`)

```zsh
source "${0:A:h}/lib.zsh"
L="${TC_LAYOUT:-$HOME/.local/bin/tmux-dev-layout}"
D="${TC_DEV:-$HOME/.local/bin/dev}"
tt_setup                                     # old layout: claude shell tests
wins() { tt list-windows -t "=$1" -F '#{window_name}' | sort | tr '\n' ' ' }
fp="$(tt split-window -d -v -t '=tt:tests' -P -F '#{pane_id}' 'sleep 600')"; tt set-option -p -t "$fp" @tc_role feed
sp="$(tt split-window -d -v -t '=tt:shell' -P -F '#{pane_id}' 'sleep 600')"; tt set-option -p -t "$sp" @tc_role feed
tt set-option -w -t '=tt:shell' @tc_label x
"$L" tt "$TT_DIR"
check "user windows"     test "$(wins tt)" = "claude shell "
check "bg windows"       test "$(wins tt-bg)" = "shell tests "
check "bg flagged"       test "$(tt show-options -qv -t '=tt-bg' @tc_bg)" = 1
check "no role panes"    test -z "$(tt list-panes -s -t '=tt' -F '#{@tc_role}' | tr -d '\n')"
check "label dropped"    test -z "$(tt show-options -wqv -t '=tt:shell' @tc_label)"
check "moved tests bare" test "$(tt list-panes -t '=tt-bg:tests' | wc -l | tr -d ' ')" = 1
"$L" tt "$TT_DIR"
check "idempotent"       test "$(wins tt)|$(wins tt-bg)" = "claude shell |shell tests "
mkdir -p "$TT_DIR/.dev"; printf '# c\ntests: while :; do echo W; sleep 1; done\n' > "$TT_DIR/.dev/windows"
"$L" tt "$TT_DIR"
wp="$(tt list-panes -t '=tt-bg:tests' -F '#{pane_id} #{@tc_role}' | awk '$2=="watch"{print $1}')"
check "watch in bg"      test -n "$wp"
check "watch runs"       tt_wait 3 sh -c "$TT_BIN capture-pane -p -t $wp | grep -qx W"
"$L" tt "$TT_DIR"
check "one watch"        test "$(tt list-panes -t '=tt-bg:tests' -F '#{@tc_role}' | grep -c watch)" = 1
# busy tests window in an unmigrated session stays put
tt new-session -d -s old -n claude -c "$TT_DIR"; tt new-window -d -t '=old:' -n tests -c "$TT_DIR" 'sleep 600'
err="$("$L" old "$TT_DIR" 2>&1 >/dev/null)"
check "busy tests kept"  sh -c "$TT_BIN list-windows -t '=old' -F '#{window_name}' | grep -qx tests"
check "busy note"        zsh -c 'print -r -- "$1" | grep -q busy' x "$err"
mkdir -p "$TT_DIR/proj"
out="$(DEV_NO_ATTACH=1 DEV_CLAUDE_CMD=true TC_LAYOUT="$L" "$D" "$TT_DIR/proj")"
check "dev ready"        zsh -c 'print -r -- "$1" | grep -q ready' x "$out"
check "dev windows"      test "$(wins proj)" = "claude shell "
check "dev bg"           test "$(wins proj-bg)" = "shell tests "
tt_done
```

- [ ] **Step 3: Run it and see it fail**

Run: `TC_LAYOUT=~/.local/bin/tmux-dev-layout.next TC_DEV=~/.local/bin/dev.next zsh ~/.local/share/tmux-tools/tests/test_layout.zsh`
Expected: FAIL on "user windows".

- [ ] **Step 4: Write `tmux-dev-layout.next`**

```zsh
#!/usr/bin/env zsh
# tmux-dev-layout <session> <root> — idempotently shape a dev session. The user keeps `claude` and a plain
# `shell`; the agents' tests/shell windows live in the hidden session <project>-bg (see tmux-ctl ensure_bg).
# Migrates old layouts: moves an idle `tests` window to -bg, closes feed/watch panes, drops status labels.
# Optional .dev/windows lines `tests: <cmd>` / `shell: <cmd>` run as a watch pane in the -bg window.
emulate -L zsh
sess="$1" root="$2"
[[ -n "$sess" && -n "$root" ]] || { print -u2 "usage: tmux-dev-layout <session> <root>"; exit 0 }
TMUX_BIN="${TC_TMUX:-$HOME/.local/bin/tmux}"
t() { "$TMUX_BIN" "$@" }
t has-session -t "=$sess" 2>/dev/null || exit 0
key="$(t display -p -t "=$sess:" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null)"; key="${key:-$sess}"
bg="$key-bg"
has_win() { t list-windows -t "=$1" -F '#{window_name}' 2>/dev/null | grep -qxF -- "$2" }
SHELLS='(zsh|bash|sh|fish|-zsh|-bash)'

# old layout: feed/watch panes and status labels in the user's windows
for win in shell tests; do
  has_win "$sess" "$win" || continue
  for p in ${(f)"$(t list-panes -t "=$sess:$win" -F '#{pane_id} #{@tc_role}')"}; do
    [[ "${p#* }" == (feed|watch) ]] && t kill-pane -t "${p%% *}"
  done
  t set-option -wu -t "=$sess:$win" @tc_label 2>/dev/null
done

# the hidden agent session (same shape as tmux-ctl ensure_bg)
if ! t has-session -t "=$bg" 2>/dev/null; then
  if has_win "$sess" tests && [[ "$(t display -p -t "=$sess:tests" '#{pane_current_command}')" == ${~SHELLS} ]]; then
    t new-session -d -s "$bg" -n shell -c "$root"
    t move-window -s "=$sess:tests" -t "=$bg:"
  else
    t new-session -d -s "$bg" -n tests -c "$root"
    t new-window -d -t "=$bg:" -n shell -c "$root"
  fi
  t set-option -t "=$bg" @tc_bg 1
fi
if has_win "$sess" tests; then
  if [[ "$(t display -p -t "=$sess:tests" '#{pane_current_command}')" == ${~SHELLS} ]]; then
    t kill-window -t "=$sess:tests"
  else
    print -u2 "tmux-dev-layout: '$sess:tests' is busy; left in place (run again when it is idle)"
  fi
fi
has_win "$sess" shell || t new-window -d -t "=$sess:" -n shell -c "$root"

# optional watch commands, in the -bg windows
if [[ -r "$root/.dev/windows" ]]; then
  while IFS= read -r line; do
    [[ "$line" == [[:space:]]#'#'* || -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ '^(tests|shell):[[:space:]]*(.+)$' ]] || continue
    win="$match[1]" cmd="$match[2]"
    has_win "$bg" "$win" || continue
    t list-panes -t "=$bg:$win" -F '#{@tc_role}' | grep -qx watch && continue
    wp="$(t split-window -d -h -P -F '#{pane_id}' -t "=$bg:$win" -c "$root" "zsh -lc ${(q)cmd}")"
    [[ -n "$wp" ]] && t set-option -p -t "$wp" @tc_role watch
  done < "$root/.dev/windows"
fi
exit 0
```

- [ ] **Step 5: Edit `dev.next`**
  - Delete the line `"$TMUX_BIN" new-window -d -t "=$name:" -n tests -c "$root"`.
  - Change the header comment to `# Windows: 1 claude · 2 shell (yours). Agent windows live in the hidden session <name>-bg.`
  - Replace `"$HOME/.local/bin/tmux-dev-layout"` with `"${TC_LAYOUT:-$HOME/.local/bin/tmux-dev-layout}"`.

- [ ] **Step 6: Run the test**

Run: the Verify command. Expected: `ALL PASS`. Then run `TC_CTL=~/.local/bin/tmux-ctl zsh ~/.local/share/tmux-tools/tests/run-all.zsh` with `TC_LAYOUT`/`TC_DEV` exported to the `.next` files. Expected: all pass.

- [ ] **Step 7: Swap in** (`chmod +x`, then `mv dev.next dev`, `mv tmux-dev-layout.next tmux-dev-layout`) and re-run `run-all.zsh` with no overrides.

- [ ] **Step 8: Report.** Do not run `dev` on the user's live session; the user decides when to migrate.

```json:metadata
{"files": ["~/.local/bin/dev", "~/.local/bin/tmux-dev-layout", "~/.local/share/tmux-tools/tests/test_layout.zsh"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/test_layout.zsh", "acceptanceCriteria": ["main session = claude shell; -bg = shell tests with @tc_bg 1", "no role panes and no label in main session", "second run changes nothing", "one watch pane in -bg:tests from .dev/windows", "busy tests window kept with stderr note", "dev yields claude shell plus <name>-bg"], "modelTier": "standard", "owner": "layout"}
```

---

### Task 5: `tmux-ctl artifact`, `idea` and `relay`

**Goal:** Add three thin subcommands that delegate to the hook (Task 2), `ideas.py` (Task 7) and `relay.py` (Task 6).

**Files:**
- Modify (staged): `~/.local/bin/tmux-ctl` → `tmux-ctl.next`
- Create: `~/.local/share/tmux-tools/tests/test_ctl_relay.zsh`

**Acceptance Criteria:**
- [ ] `tmux-ctl artifact <file> --kind handoff` appends a `handoff` entry for the caller's project
- [ ] `tmux-ctl idea "try X"` appends `- [ ] … · try X` to `$TC_IDEAS_DIR/<project>.md`
- [ ] `tmux-ctl relay <doc> --old-session OLD1` returns at once, then, once the `claude` pane is idle, respawns it running `claude-orchestrator 'Read <doc> and continue from where the previous session left off.'` and appends lineage with `old_session_id: OLD1`
- [ ] `tmux-ctl relay /missing.md` exits 2
- [ ] The help text lists the three commands

**Verify:** `TC_CTL=~/.local/bin/tmux-ctl.next zsh ~/.local/share/tmux-tools/tests/test_ctl_relay.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** `test_ctl_relay.zsh`

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
STUB="$(mktemp -d "${TMPDIR:-/tmp}/ttstub.XXXXXX")"
cat > "$STUB/claude-orchestrator" <<'EOF'
#!/bin/sh
printf '%s\n' "$@" > "$RELAY_OUT"
exec sleep 600
EOF
chmod +x "$STUB/claude-orchestrator"
export PATH="$STUB:$PATH" RELAY_OUT="$STUB/args" TC_IDEAS_DIR="$STUB/ideas"
tt_setup claude
doc="$TT_DIR/h.md"; print "# handoff" > "$doc"
$C artifact "$doc" --kind handoff >/dev/null
check "artifact registered" test "$(jq -r .kind "$TC_STATE/artifacts-tt.jsonl" | tail -1)" = handoff
$C idea "try X" >/dev/null
check "idea filed"          grep -q '^- \[ \] .* · try X$' "$STUB/ideas/tt.md"
out="$($C relay "$doc" --old-session OLD1)"
check "relay scheduled"     zsh -c 'print -r -- "$1" | grep -q "relay scheduled"' x "$out"
check "orchestrator started" tt_wait 30 test -s "$STUB/args"
check "prompt names doc"    grep -qF "Read $doc and continue from where the previous session left off." "$STUB/args"
check "lineage written"     test "$(jq -r .old_session_id "$TC_STATE/lineage-tt.jsonl")" = OLD1
$C relay /nope-$$.md 2>/dev/null; rc=$?
check "missing doc refused" test $rc -eq 2
check "help lists relay"    sh -c "$C help | grep -q 'tmux-ctl relay'"
rm -rf "$STUB"
tt_done
```

- [ ] **Step 2: Run it and see it fail**

Run: copy the installed `tmux-ctl` to `tmux-ctl.next`, then run the Verify command.
Expected: FAIL (`unknown command 'artifact'`).

- [ ] **Step 3: Add the subcommands** before the `""|-h|--help|help)` case in `tmux-ctl.next`:

```zsh
  artifact)
    [[ -n "$1" ]] || die "usage: tmux-ctl artifact <path> [--kind plan|spec|handoff|report|other]"
    p="${1:A}"; shift; k=other
    [[ "$1" == --kind && -n "$2" ]] && k="$2"
    [[ -f "$p" ]] || die "no file '$p'"
    "$HOME/.claude/hooks/artifact-register.sh" --path "$p" --kind "$k" --project "$FEEDKEY"
    print -r -- "registered $p ($k)" ;;

  idea)
    [[ -n "$*" ]] || die "usage: tmux-ctl idea <text>"
    python3 -I "$HOME/.local/share/tmux-dash/ideas.py" add --project "$FEEDKEY" -- "$*" ;;

  relay)
    [[ -n "$1" ]] || die "usage: tmux-ctl relay <handoff-doc> [--old-session <id>]"
    doc="${1:A}"; shift; old=""
    [[ "$1" == --old-session && -n "$2" ]] && old="$2"
    [[ -f "$doc" ]] || die "no handoff doc '$doc'"
    log="$STATE/relay-$FEEDKEY.log"
    sock="$(t display -p '#{socket_path}')"
    # detached: the lead that asked for the relay must finish its turn before its pane is replaced
    t run-shell -b "python3 -I ${(q)HOME}/.local/share/tmux-dash/relay.py --session ${(q)FEEDKEY} --doc ${(q)doc} --old-session ${(q)old} --state ${(q)STATE} --socket ${(q)sock} > ${(q)log} 2>&1"
    print -r -- "relay scheduled: $FEEDKEY:claude restarts with $doc once this turn ends (log: $log)" ;;
```

  Add these to the header help block (it prints lines 2–22; widen the `sed -n '2,22p'` range to cover the new lines):

```
#   tmux-ctl artifact <path> [--kind K]    show a file in the board's artifacts panel
#   tmux-ctl idea  <text>                  file an idea for after the plan (never act on it now)
#   tmux-ctl relay <doc> [--old-session ID] after this turn, restart the claude window as a fresh
#                                          orchestrator that starts from <doc> (handoff skill only)
```

- [ ] **Step 4: Run the test**

Run: the Verify command. Expected: `ALL PASS`. Then run the full `run-all.zsh` with `TC_CTL=~/.local/bin/tmux-ctl.next`.

- [ ] **Step 5: Swap in** (`mv tmux-ctl.next tmux-ctl`), re-run `run-all.zsh`, and report.

```json:metadata
{"files": ["~/.local/bin/tmux-ctl", "~/.local/share/tmux-tools/tests/test_ctl_relay.zsh"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/test_ctl_relay.zsh", "acceptanceCriteria": ["artifact subcommand appends handoff entry", "idea subcommand appends to ideas file", "relay respawns idle claude pane with doc prompt and writes lineage", "missing doc exits 2", "help lists artifact/idea/relay"], "modelTier": "mechanical", "owner": "layout"}
```

---

### Task 6: `relay.py`, the in-place handoff

**Goal:** A module and CLI that wait for the lead's turn to end, respawn the `claude` pane with `claude-orchestrator "<prompt>"`, and append lineage. On any failure it leaves the old pane alone and prints the manual command.

**Files:**
- Create: `~/.local/share/tmux-dash/relay.py`
- Test: `~/.local/share/tmux-dash/tests/test_relay.py`

**Acceptance Criteria:**
- [ ] `wait_turn_end` needs 2 consecutive `idle`/`ready` polls; with statuses working, ready, working, ready, ready it returns True after 5 polls
- [ ] `wait_turn_end` returns False when the cap passes with the lead still working
- [ ] `relay()` calls `respawn-pane -k -t %5 -c <root>` before `send-keys … -l -- claude-orchestrator 'Read /d.md and continue from where the previous session left off.'` and `send-keys … Enter`
- [ ] `relay()` appends one lineage line `{ts, old_session_id, doc, pane}`
- [ ] When busy, `relay()` raises, never calls `respawn-pane`, and writes no lineage
- [ ] `main()` returns 1 on failure and prints `claude-orchestrator 'Read …'` to stderr

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_relay -v` → OK

**Steps:**

- [ ] **Step 1: Write the failing test** `tests/test_relay.py`

```python
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paneclass  # noqa: E402
import relay  # noqa: E402

SEP = paneclass.SEP


class FakeTmux:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            return "/not/a/repo\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]


def statuses(*seq):
    return mock.patch.object(paneclass, "pane_status", side_effect=[("claude", s) for s in seq])


class WaitTest(unittest.TestCase):
    def test_needs_two_in_a_row(self):
        sleeps = []
        with statuses("working", "ready", "working", "ready", "ready"):
            self.assertTrue(relay.wait_turn_end(FakeTmux(), "%5", sleep=sleeps.append))
        self.assertEqual(len(sleeps), 4)

    def test_times_out(self):
        clock = iter(range(0, 1000, 2))
        with statuses(*["working"] * 100):
            ok = relay.wait_turn_end(FakeTmux(), "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock))
        self.assertFalse(ok)


class RelayTest(unittest.TestCase):
    def test_relay_respawns_and_writes_lineage(self):
        fake = FakeTmux()
        with tempfile.TemporaryDirectory() as d, statuses("idle", "idle"):
            msg = relay.relay(fake, "proj", "/d.md", d, "OLD1", sleep=lambda s: None)
            lines = (Path(d) / "lineage-proj.jsonl").read_text().splitlines()
        self.assertIn("relayed", msg)
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual((rec["old_session_id"], rec["doc"], rec["pane"]), ("OLD1", "/d.md", "%5"))
        rp = [c for c in fake.calls if c[0] == "respawn-pane"]
        sk = [c for c in fake.calls if c[0] == "send-keys"]
        self.assertEqual(rp[0], ("respawn-pane", "-k", "-t", "%5", "-c", "/not/a/repo"))
        self.assertEqual(sk[0], ("send-keys", "-t", "%5", "-l", "--",
                                 "claude-orchestrator 'Read /d.md and continue from where the previous session left off.'"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%5", "Enter"))
        self.assertLess(fake.names().index("respawn-pane"), fake.names().index("send-keys"))

    def test_busy_leaves_pane_alone(self):
        fake = FakeTmux()
        clock = iter(range(0, 1000, 2))
        with tempfile.TemporaryDirectory() as d, statuses(*["working"] * 100):
            with self.assertRaises(RuntimeError):
                relay.relay(fake, "proj", "/d.md", d, "", cap=6, sleep=lambda s: None, clock=lambda: next(clock))
            self.assertFalse((Path(d) / "lineage-proj.jsonl").exists())
        self.assertNotIn("respawn-pane", fake.names())

    def test_main_failure_prints_manual_command(self):
        err = io.StringIO()
        with mock.patch.object(relay, "relay", side_effect=RuntimeError("boom")), redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", "/tmp"])
        self.assertEqual(rc, 1)
        self.assertIn("claude-orchestrator 'Read /d.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_relay -v`
Expected: `ModuleNotFoundError: No module named 'relay'`

- [ ] **Step 3: Write `relay.py`**

```python
#!/usr/bin/env python3
"""relay: hand a dev session's `claude` window to a fresh orchestrator, in place.

  relay.py --session S --doc D [--old-session ID] [--state DIR] [--socket PATH]

Waits until the lead's turn has ended (paneclass says idle/ready on two polls in a row, 2s apart,
120s cap), respawns the pane with `claude-orchestrator "Read <doc> ..."`, and appends
{ts, old_session_id, doc, pane} to <state>/lineage-<session>.jsonl. The board's
restart_orchestrator uses respawn() too. On failure the old pane is left alone.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import paneclass  # noqa: E402

SEP = paneclass.SEP
ENDED = {"idle", "ready"}


def prompt_for(doc):
    return f"Read {doc} and continue from where the previous session left off."


def wait_turn_end(tmux, pane, poll=2.0, cap=120.0, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + cap
    streak = 0
    while True:
        _, status = paneclass.pane_status(tmux, pane)
        streak = streak + 1 if status in ENDED else 0
        if streak >= 2:
            return True
        if clock() >= deadline:
            return False
        sleep(poll)


def claude_pane(tmux, sess):
    for line in tmux("list-windows", "-t", f"={sess}", "-F", f"#{{window_name}}{SEP}#{{window_index}}", check=True).splitlines():
        name, _, idx = line.partition(SEP)
        if name == "claude":
            return tmux("list-panes", "-t", f"={sess}:{idx}", "-F", "#{pane_id}", check=True).splitlines()[0]
    return None


def session_root(tmux, sess):
    path = tmux("display", "-p", "-t", f"={sess}:", "#{pane_current_path}").strip()
    r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else path


def respawn(tmux, pane, root, prompt=None):
    """Replace whatever runs in pane with a fresh shell in root, then start claude-orchestrator [prompt]."""
    tmux("respawn-pane", "-k", "-t", pane, "-c", root, check=True)  # no command: fresh default shell
    cmd = "claude-orchestrator" + (f" {shlex.quote(prompt)}" if prompt else "")
    tmux("send-keys", "-t", pane, "-l", "--", cmd, check=True)
    tmux("send-keys", "-t", pane, "Enter", check=True)


def relay(tmux, sess, doc, state_dir, old_session_id="", **wait):
    pane = claude_pane(tmux, sess)
    if pane is None:
        raise RuntimeError(f"no claude window in {sess}")
    if not wait_turn_end(tmux, pane, **wait):
        raise RuntimeError("the lead is still busy after the wait; not switching. Run tmux-ctl relay again when it is idle")
    respawn(tmux, pane, session_root(tmux, sess), prompt_for(doc))
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(state_dir) / f"lineage-{sess}.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "old_session_id": old_session_id, "doc": str(doc), "pane": pane}) + "\n")
    return f"relayed {sess}:claude to a fresh orchestrator with {doc}"


def default_state():
    return os.environ.get("TC_STATE") or f"{os.environ.get('TMPDIR', '/tmp').rstrip('/')}/tmux-ctl-{os.getuid()}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="hand the claude window to a fresh orchestrator")
    ap.add_argument("--session", required=True)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--old-session", default="")
    ap.add_argument("--state", default=default_state())
    ap.add_argument("--socket", default="")
    a = ap.parse_args(argv)
    tmux = paneclass.tmux_runner(["-S", a.socket] if a.socket else [])
    try:
        print(relay(tmux, a.session, a.doc, a.state, a.old_session))
        return 0
    except Exception as e:
        print(f"relay failed: {e}\nThe old session is untouched. Start the new lead by hand in the claude window:\n"
              f"  claude-orchestrator {shlex.quote(prompt_for(a.doc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_relay -v`
Expected: OK (6 tests).

- [ ] **Step 5: Report** the files and the output to the lead.

```json:metadata
{"files": ["~/.local/share/tmux-dash/relay.py", "~/.local/share/tmux-dash/tests/test_relay.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_relay -v", "acceptanceCriteria": ["two consecutive idle/ready polls required", "returns False at cap while working", "respawn-pane then send-keys literal orchestrator prompt then Enter", "one lineage line appended", "busy: raises, no respawn, no lineage", "main returns 1 and prints manual command"], "modelTier": "standard", "owner": "relay"}
```

---

### Task 7: `ideas.py`, the locked ideas inbox

**Goal:** Add, parse and count ideas in `${TC_IDEAS_DIR:-~/.claude/ideas}/<project>.md` under an exclusive lock, with a CLI used by `tmux-ctl idea`.

**Files:**
- Create: `~/.local/share/tmux-dash/ideas.py`
- Test: `~/.local/share/tmux-dash/tests/test_ideas.py`

**Acceptance Criteria:**
- [ ] `add("p", "a\nb", "x\ny")` writes `- [ ] YYYY-MM-DD HH:MM · a b` with two indented detail lines, under a `# Ideas: p` header created once
- [ ] `load` parses the `[ ]`/`[x]`/`[-]` statuses as open/taken/dropped, with detail
- [ ] `open_count` counts only open ideas
- [ ] 20 concurrent CLI `add` processes produce 20 entries
- [ ] A project name with `/` or `..` raises `ValueError`; an empty text raises `ValueError`

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_ideas -v` → OK

**Steps:**

- [ ] **Step 1: Write the failing test** `tests/test_ideas.py`

```python
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import ideas  # noqa: E402


class IdeasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_IDEAS_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_IDEAS_DIR", None)

    def test_add_and_load(self):
        ideas.add("p", "a\nb", "x\ny", now=0)
        text = (Path(self.tmp.name) / "p.md").read_text()
        self.assertTrue(text.startswith("# Ideas: p\n\n"))
        self.assertRegex(text, r"- \[ \] \d{4}-\d{2}-\d{2} \d{2}:\d{2} · a b\n  x\n  y\n")
        ideas.add("p", "second")
        self.assertEqual(text.count("# Ideas"), 1)
        got = ideas.load("p")
        self.assertEqual([i["text"] for i in got], ["a b", "second"])
        self.assertEqual(got[0]["detail"], "x\ny")

    def test_statuses(self):
        (Path(self.tmp.name) / "p.md").write_text(
            "# Ideas: p\n\n- [ ] 2026-10-16 10:00 · one\n- [x] 2026-10-16 10:01 · two → docs/s.md\n- [-] 2026-10-16 10:02 · three\n")
        self.assertEqual([i["status"] for i in ideas.load("p")], ["open", "taken", "dropped"])
        self.assertEqual(ideas.open_count("p"), 1)

    def test_bad_input(self):
        for bad in ("a/b", "..", ""):
            with self.assertRaises(ValueError):
                ideas.add(bad, "x")
        with self.assertRaises(ValueError):
            ideas.add("p", "   ")

    def test_concurrent_cli(self):
        env = {**os.environ, "TC_IDEAS_DIR": self.tmp.name}
        procs = [subprocess.Popen([sys.executable, "-I", str(HERE / "ideas.py"), "add", "--project", "p", "--", f"idea {n}"], env=env)
                 for n in range(20)]
        self.assertEqual([p.wait() for p in procs], [0] * 20)
        self.assertEqual(len(ideas.load("p")), 20)
        self.assertEqual(sorted(int(re.search(r"\d+$", i["text"]).group()) for i in ideas.load("p")), list(range(20)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail** (`ModuleNotFoundError: No module named 'ideas'`).

- [ ] **Step 3: Write `ideas.py`**

```python
#!/usr/bin/env python3
"""ideas: the per-project ideas inbox, ${TC_IDEAS_DIR:-~/.claude/ideas}/<project>.md.

Each idea is "- [ ] YYYY-MM-DD HH:MM · text" with detail as indented lines; [x] = taken up
(followed by "→ <spec>"), [-] = dropped. Ideas are never deleted. Every writer appends under an
exclusive lock on <file>.lock. Agents do not read this file while a plan is running.

  ideas.py add --project P [--detail D] -- TEXT
  ideas.py list --project P
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

LINE_RE = re.compile(r"^- \[( |x|-)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")
STATUS = {" ": "open", "x": "taken", "-": "dropped"}


def ideas_dir():
    return Path(os.environ.get("TC_IDEAS_DIR") or Path.home() / ".claude" / "ideas")


def ideas_path(project):
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", project or "") or project in (".", ".."):
        raise ValueError(f"bad project name {project!r}")
    return ideas_dir() / f"{project}.md"


def add(project, text, detail="", now=None):
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("empty idea")
    p = ideas_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    first = f"- [ ] {stamp} · {text}"
    entry = first + "\n" + "".join(f"  {l.strip()}\n" for l in str(detail).splitlines() if l.strip())
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        new = not p.exists() or p.stat().st_size == 0
        with open(p, "a") as f:
            if new:
                f.write(f"# Ideas: {project}\n\n")
            f.write(entry)
    return first


def load(project):
    p = ideas_path(project)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        m = LINE_RE.match(line)
        if m:
            out.append({"status": STATUS[m[1]], "ts": m[2], "text": m[3], "detail": ""})
        elif out and line.startswith("  ") and line.strip():
            d = out[-1]["detail"]
            out[-1]["detail"] = f"{d}\n{line.strip()}" if d else line.strip()
    return out


def open_count(project):
    return sum(1 for i in load(project) if i["status"] == "open")


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-project ideas inbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--detail", default="")
    a.add_argument("text", nargs="+")
    ls = sub.add_parser("list")
    ls.add_argument("--project", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "add":
            print(f"noted for later: {add(args.project, ' '.join(args.text), args.detail)}")
        else:
            print(json.dumps(load(args.project), indent=1))
        return 0
    except ValueError as e:
        print(f"ideas: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests.** Expected: OK (4 tests).

- [ ] **Step 5: Report.**

```json:metadata
{"files": ["~/.local/share/tmux-dash/ideas.py", "~/.local/share/tmux-dash/tests/test_ideas.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_ideas -v", "acceptanceCriteria": ["add writes header once, collapsed text, indented detail", "load parses open/taken/dropped with detail", "open_count counts open only", "20 concurrent CLI adds give 20 entries", "bad project and empty text raise ValueError"], "modelTier": "mechanical", "owner": "panel"}
```

---

### Task 8: Artifacts module and endpoints

**Goal:** `artifacts.py` summarises the manifest and lineage, serves allowlisted files, saves with a hash check, and queues comments. `server.py` exposes them and delivers comments only when the lead is not showing a prompt.

**Files:**
- Create: `~/.local/share/tmux-dash/artifacts.py`
- Modify: `~/.local/share/tmux-dash/server.py`
  - `do_GET`: `api/artifacts`, `api/artifact`
  - `_act`: `save`, `comment`
  - `do_POST`: 409 mapping and a 2 MiB body cap
  - `build_state`: calls `deliver_comments`
- Test: `~/.local/share/tmux-dash/tests/test_artifacts.py`

**Acceptance Criteria:**
- [ ] `summary("p")` groups entries by path (published entries by URL), sorts newest first, and returns `epoch` = lineage lines, `active_plan` = newest plan path, `started_from` = last lineage doc
- [ ] `read` raises `FileNotFoundError` for a path not in the manifest and for URL entries
- [ ] `save` with a stale `base_hash` raises `Conflict` carrying the current `{text, hash}`; with the right hash it writes atomically and calls the hook with `--agent you`
- [ ] `CommentQueue.deliver` sends nothing when status is `waiting` or kind is not `claude`; otherwise it types `[Plan comment] plan.md § Task 3: "quote" — note` and empties the queue; a send error re-queues the rest
- [ ] `server._act({"action":"save",…})` with a stale hash raises `artifacts.Conflict`; `do_POST` turns that into HTTP 409 with `current`
- [ ] `GET api/artifact` for an unlisted path returns 404

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing test** `tests/test_artifacts.py`

```python
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import artifacts  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_art", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        os.environ["TC_STATE"] = str(self.state)
        self.plan = Path(self.tmp.name) / "plan.md"
        self.plan.write_text("# Plan\n")
        self.spec = Path(self.tmp.name) / "spec.md"
        self.spec.write_text("# Spec\n")
        rows = [
            {"ts": 1, "path": str(self.spec), "kind": "spec", "agent": "claude", "hash": sha("# Spec\n"), "url": "", "epoch": 0},
            {"ts": 2, "path": str(self.plan), "kind": "plan", "agent": "claude", "hash": "old", "url": "", "epoch": 0},
            {"ts": 3, "path": str(self.plan), "kind": "plan", "agent": "impl", "hash": sha("# Plan\n"), "url": "", "epoch": 1},
            {"ts": 4, "path": "/x/page.html", "kind": "published", "agent": "claude", "hash": "", "url": "https://claude.ai/code/artifact/a", "epoch": 1},
        ]
        (self.state / "artifacts-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "garbage\n")
        (self.state / "lineage-p.jsonl").write_text(json.dumps({"ts": 2.5, "old_session_id": "O", "doc": "/h.md", "pane": "%1"}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)


class SummaryTest(Base):
    def test_summary(self):
        s = artifacts.summary("p")
        self.assertEqual(s["epoch"], 1)
        self.assertEqual(s["active_plan"], str(self.plan))
        self.assertEqual(s["started_from"], "/h.md")
        self.assertEqual([i["kind"] for i in s["items"]], ["published", "plan", "spec"])
        plan = s["items"][1]
        self.assertEqual(len(plan["history"]), 2)
        self.assertEqual(plan["latest"]["agent"], "impl")

    def test_empty_project(self):
        s = artifacts.summary("none")
        self.assertEqual((s["epoch"], s["items"], s["active_plan"], s["started_from"]), (0, [], None, None))


class ReadSaveTest(Base):
    def test_read_allowlist(self):
        self.assertEqual(artifacts.read("p", str(self.plan))["text"], "# Plan\n")
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", "/etc/passwd")
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", "/x/page.html")

    def test_save_conflict(self):
        with self.assertRaises(artifacts.Conflict) as cm:
            artifacts.save("p", str(self.plan), "stale", "new\n")
        self.assertEqual(cm.exception.current["text"], "# Plan\n")
        self.assertEqual(self.plan.read_text(), "# Plan\n")

    def test_save_ok(self):
        with mock.patch.object(artifacts.subprocess, "run") as run:
            got = artifacts.save("p", str(self.plan), sha("# Plan\n"), "# Plan v2\n")
        self.assertEqual(self.plan.read_text(), "# Plan v2\n")
        self.assertEqual(got["hash"], sha("# Plan v2\n"))
        args = run.call_args[0][0]
        self.assertEqual(args[1:], ["--path", str(self.plan), "--agent", "you", "--project", "p"])

    def test_server_save_conflict(self):
        with self.assertRaises(artifacts.Conflict):
            server._act({"action": "save", "session": "p", "path": str(self.plan), "base_hash": "stale", "text": "x"})


class CommentTest(unittest.TestCase):
    def test_line_format(self):
        q = artifacts.CommentQueue()
        c = q.add("p", "/r/plan.md", "Task 3", 'do  "X"', "split  it")
        self.assertEqual(artifacts.CommentQueue.line(c), '[Plan comment] plan.md § Task 3: "do "X"" — split it')

    def test_held_while_waiting(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/plan.md", "", "", "note")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "waiting", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "shell", "idle", lambda p, t: sent.append(t)), 0)
        self.assertEqual(sent, [])
        self.assertEqual(q.deliver("p", "%1", "claude", "working", lambda p, t: sent.append(t)), 1)
        self.assertEqual(sent, ["[Plan comment] plan.md: — note"])
        self.assertEqual(q.pending("p"), [])

    def test_send_error_requeues(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/a.md", "", "", "one")
        q.add("p", "/r/a.md", "", "", "two")

        def boom(p, t):
            raise RuntimeError("tmux gone")

        self.assertEqual(q.deliver("p", "%1", "claude", "ready", boom), 0)
        self.assertEqual(len(q.pending("p")), 2)

    def test_empty_note_rejected(self):
        with self.assertRaises(ValueError):
            artifacts.CommentQueue().add("p", "/a.md", "", "", "  ")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail** (`No module named 'artifacts'`).

- [ ] **Step 3: Write `artifacts.py`**

```python
"""artifacts: the session artifact manifest written by ~/.claude/hooks/artifact-register.sh.

summary() for the board's panel, read() of allowlisted files only, save() with a hash check,
and CommentQueue: plan comments typed into the lead's pane, never while it shows a prompt.
"""
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

HOOK = Path.home() / ".claude" / "hooks" / "artifact-register.sh"


def state_dir():
    return Path(os.environ.get("TC_STATE") or f"{os.environ.get('TMPDIR', '/tmp').rstrip('/')}/tmux-ctl-{os.getuid()}")


def jsonl(path):
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def entries(project):
    return jsonl(state_dir() / f"artifacts-{project}.jsonl")


def lineage(project):
    return jsonl(state_dir() / f"lineage-{project}.jsonl")


def summary(project):
    by = {}
    for e in entries(project):
        key = e.get("url") or e.get("path")
        if not key:
            continue
        it = by.setdefault(key, {"path": e.get("path", ""), "kind": e.get("kind", "other"), "url": e.get("url", ""), "history": []})
        it["history"].append({k: e.get(k) for k in ("ts", "agent", "hash", "epoch")})
    items = []
    for it in by.values():
        it["latest"] = it["history"][-1]
        items.append(it)
    items.sort(key=lambda i: i["latest"]["ts"] or 0, reverse=True)
    lin = lineage(project)
    plans = [i for i in items if i["kind"] == "plan"]
    return {"epoch": len(lin), "lineage": lin, "items": items,
            "active_plan": plans[0]["path"] if plans else None,
            "started_from": lin[-1].get("doc") if lin else None}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def read(project, path):
    if not any(e.get("path") == path and not e.get("url") for e in entries(project)):
        raise FileNotFoundError(path)
    data = Path(path).read_bytes()
    return {"path": path, "text": data.decode("utf-8", "replace"), "hash": _sha(data)}


class Conflict(Exception):
    def __init__(self, current):
        super().__init__("the file changed since you loaded it")
        self.current = current


def save(project, path, base_hash, text):
    cur = read(project, path)  # also the allowlist check
    if cur["hash"] != base_hash:
        raise Conflict(cur)
    p = Path(path)
    tmp = p.with_name(f".{p.name}.tmux-dash.tmp")
    tmp.write_text(text)
    os.replace(tmp, p)
    subprocess.run([str(HOOK), "--path", path, "--agent", "you", "--project", project],
                   capture_output=True, timeout=10, env={**os.environ, "TC_STATE": str(state_dir())})
    return read(project, path)


def _flat(s, limit):
    return " ".join(str(s or "").split())[:limit]


class CommentQueue:
    """Plan comments waiting for the lead, per session. Delivered by typing one line into the claude pane."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}

    def add(self, sess, path, anchor, quote, note):
        note = _flat(note, 2000)
        if not note:
            raise ValueError("write a note")
        c = {"id": uuid.uuid4().hex[:8], "path": path, "anchor": _flat(anchor, 80), "quote": _flat(quote, 200),
             "note": note, "ts": time.time()}
        with self._lock:
            self._items.setdefault(sess, []).append(c)
        return c

    def pending(self, sess):
        with self._lock:
            return list(self._items.get(sess, []))

    @staticmethod
    def line(c):
        where = f" § {c['anchor']}" if c["anchor"] else ""
        quote = f' "{c["quote"]}"' if c["quote"] else ""
        return f"[Plan comment] {Path(c['path']).name}{where}:{quote} — {c['note']}"

    def deliver(self, sess, pane, kind, status, send):
        """send(pane, text) types text + Enter. Holds everything while the lead shows a prompt or is not running."""
        if kind != "claude" or status == "waiting":
            return 0
        with self._lock:
            items = self._items.pop(sess, [])
        for n, c in enumerate(items):
            try:
                send(pane, self.line(c))
            except Exception:
                with self._lock:
                    self._items[sess] = items[n:] + self._items.get(sess, [])
                return n
        return len(items)
```

- [ ] **Step 4: Wire up `server.py`**

  Add the imports next to the paneclass import: `import artifacts  # noqa: E402` and `from urllib.parse import parse_qs, urlsplit`.

  Add the module-level helpers:

```python
COMMENTS = artifacts.CommentQueue()
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def project_arg(q):
    sess = (q.get("session") or [""])[0]
    if not NAME_RE.fullmatch(sess):
        raise ValueError("bad session")
    return sess


def send_line(pane, text):
    tmux("send-keys", "-t", pane, "-l", "--", text, check=True)
    time.sleep(0.2)
    tmux("send-keys", "-t", pane, "Enter", check=True)


def deliver_comments(sessions):
    for s in sessions:
        if not COMMENTS.pending(s["name"]):
            continue
        for w in s["windows"]:
            if w["name"] == "claude" and w["panes"]:
                p = w["panes"][0]
                COMMENTS.deliver(s["name"], p["id"], p["kind"], p["status"], send_line)
```

  In `build_state`, just before `return {...}`, add `deliver_comments(out)`.

  In `do_GET`, compute `q = parse_qs(urlsplit(self.path).query)` after `_guard`, and add these branches before the final `else`:

```python
        elif sub == "api/artifacts":
            try:
                sess = project_arg(q)
                self._json(200, {**artifacts.summary(sess), "comments": COMMENTS.pending(sess)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub == "api/artifact":
            try:
                self._json(200, artifacts.read(project_arg(q), (q.get("path") or [""])[0]))
            except (FileNotFoundError, ValueError):
                self._json(404, {"error": "not an artifact of this session"})
```

  In `_act`, before the final `raise`:

```python
    if a in ("save", "comment", "idea") and not NAME_RE.fullmatch(sess):
        raise RuntimeError("bad session")
    if a == "save":
        return artifacts.save(sess, body["path"], body["base_hash"], body["text"])
    if a == "comment":
        COMMENTS.add(sess, body["path"], body.get("anchor", ""), body.get("quote", ""), body.get("note", ""))
        return "comment queued for the lead"
```

  In `do_POST`:
  - Change `min(n, 65536)` to `min(n, 2_097_152)`.
  - Add, before `except Exception as e:`:

```python
        except artifacts.Conflict as e:
            self._json(409, {"ok": False, "message": str(e), "current": e.current})
```

- [ ] **Step 5: Run the whole suite.** Expected: all OK.

- [ ] **Step 6: Report.**

```json:metadata
{"files": ["~/.local/share/tmux-dash/artifacts.py", "~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/tests/test_artifacts.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v", "acceptanceCriteria": ["summary groups/sorts and returns epoch, active_plan, started_from", "read refuses unlisted paths and URL entries", "save: Conflict on stale hash, atomic write and hook call on match", "CommentQueue holds while waiting or not claude, delivers exact line, re-queues on error", "server save conflict -> 409 with current", "api/artifact 404 for unlisted path"], "modelTier": "standard", "owner": "panel"}
```

---

### Task 9: Ideas, runs, logs and feed endpoints; hide `-bg`; relay respawn

**Goal:** `activity.py` reads run records, logs (by id only) and parsed feed blocks. `server.py` serves ideas/runs/log/feed, takes `idea` actions, hides `@tc_bg` sessions, and restarts the orchestrator through `relay.respawn`.

**Files:**
- Create: `~/.local/share/tmux-dash/activity.py`
- Modify: `~/.local/share/tmux-dash/server.py`
- Modify: `~/.local/share/tmux-dash/tests/test_restart_orchestrator.py` (the send-keys assertion)
- Test: `~/.local/share/tmux-dash/tests/test_activity.py`

**Acceptance Criteria:**
- [ ] `activity.runs("p")` returns one record per id (the final record wins), newest first
- [ ] `activity.log_text("p", id)` returns the log; an unknown id, or a record whose `log` points outside `$STATE/logs/p/`, raises `FileNotFoundError`
- [ ] `activity.feed("p")` parses `── HH:MM:SS · agent · cwd · exit N` blocks into `{win,time,agent,cwd,exit,cmd,tail}`
- [ ] `build_state` skips panes whose session has `@tc_bg` = 1
- [ ] `api/ideas` returns `{ideas, open}`; action `idea` appends
- [ ] `restart_orchestrator` uses `relay.respawn`; the updated test expects `("send-keys","-t","%7","-l","--","claude-orchestrator")` then `("send-keys","-t","%7","Enter")`
- [ ] `api/runs` adds `window_index` for running records

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing test** `tests/test_activity.py`

```python
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import activity  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_act", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        os.environ["TC_STATE"] = str(self.state)
        logs = self.state / "logs" / "p"
        logs.mkdir(parents=True)
        (logs / "a.log").write_text("hi\n")
        recs = [
            {"id": "a", "ts": 10, "exit": None, "log": str(logs / "a.log"), "cmd": "pytest"},
            {"id": "b", "ts": 20, "exit": None, "log": str(logs / "b.log"), "cmd": "make"},
            {"id": "a", "ts": 10, "exit": 0, "log": str(logs / "a.log"), "cmd": "pytest", "summary": "3 passed"},
            {"id": "evil", "ts": 5, "exit": 0, "log": "/etc/hosts", "cmd": "x"},
        ]
        (self.state / "runs-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (self.state / "feed-p-tests.log").write_text(
            "── 14:02:01 · impl · ~/r · exit 0\n$ pytest -q\n3 passed\n\n── 14:03:00 · panel · ~/r · exit 1\n$ make\nboom\n\n")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def test_runs_dedupe(self):
        got = activity.runs("p")
        self.assertEqual([r["id"] for r in got], ["b", "a", "evil"])
        self.assertEqual(got[1]["exit"], 0)

    def test_log_by_id(self):
        self.assertEqual(activity.log_text("p", "a"), "hi\n")
        for bad in ("nope", "evil"):
            with self.assertRaises(FileNotFoundError):
                activity.log_text("p", bad)

    def test_feed_blocks(self):
        got = activity.feed("p")
        self.assertEqual([(b["agent"], b["exit"], b["cmd"]) for b in got], [("impl", 0, "pytest -q"), ("panel", 1, "make")])
        self.assertEqual(got[0]["tail"], "3 passed")
        self.assertEqual(got[0]["win"], "tests")


class HideBgTest(unittest.TestCase):
    def test_bg_sessions_hidden(self):
        S = server.SEP
        row = lambda sess, bg: S.join([sess, "1", "1", "tests", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", bg])
        out = "\n".join([row("proj", ""), row("proj-bg", "1")])
        with mock.patch.object(server, "tmux", return_value=out), \
             mock.patch.object(server, "pane_text", return_value=[]), \
             mock.patch.object(server, "cached_worktrees", return_value=[]):
            names = [s["name"] for s in server.build_state()["sessions"]]
        self.assertEqual(names, ["proj"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail** (`No module named 'activity'`).

- [ ] **Step 3: Write `activity.py`**

```python
"""activity: agent test/build runs recorded by `tmux-ctl run`, their logs, and the command feed."""
import os
import re
from pathlib import Path

from artifacts import jsonl, state_dir

HEAD_RE = re.compile(r"^── (\d\d:\d\d:\d\d) · (.*?) · (.*) · exit (-?\d+)$")


def runs(project, limit=100):
    latest = {}
    for r in jsonl(state_dir() / f"runs-{project}.jsonl"):
        if r.get("id"):
            latest[r["id"]] = r  # the final record replaces the start record
    return sorted(latest.values(), key=lambda r: r.get("ts") or 0, reverse=True)[:limit]


def log_text(project, run_id, max_bytes=512_000):
    root = (state_dir() / "logs" / project).resolve()
    for r in reversed(jsonl(state_dir() / f"runs-{project}.jsonl")):
        if r.get("id") == run_id:
            p = Path(r.get("log") or "").resolve()
            if not str(p).startswith(str(root) + os.sep):
                raise FileNotFoundError(run_id)
            return p.read_bytes()[-max_bytes:].decode("utf-8", "replace")
    raise FileNotFoundError(run_id)


def feed(project, limit=200):
    out = []
    for win in ("tests", "shell"):
        p = state_dir() / f"feed-{project}-{win}.log"
        if not p.exists():
            continue
        cur = None
        for line in p.read_text(errors="replace").splitlines():
            m = HEAD_RE.match(line)
            if m:
                cur = {"win": win, "time": m[1], "agent": m[2], "cwd": m[3], "exit": int(m[4]), "cmd": "", "tail": ""}
                out.append(cur)
            elif cur is not None and line.startswith("$ ") and not cur["cmd"]:
                cur["cmd"] = line[2:]
            elif cur is not None and line.strip():
                cur["tail"] = f"{cur['tail']}\n{line}" if cur["tail"] else line
    out.sort(key=lambda b: b["time"])
    return out[-limit:]
```

- [ ] **Step 4: Server changes**
  - Imports: `import activity, ideas, relay  # noqa: E402`.
  - **`build_state`:**
    - Append `"#{@tc_bg}"` to the format list.
    - Change `len(f) == 14` to `len(f) == 15`, and add `and f[14] != "1"` to the filter.
    - Unpack with `sess, attached, widx, wname, bell, agent, pidx, pid, title, cmd, path, pact, wact, mate = f[:14]`.
  - **`do_GET`:** add these branches.

```python
        elif sub == "api/ideas":
            try:
                sess = project_arg(q)
                self._json(200, {"ideas": ideas.load(sess), "open": ideas.open_count(sess)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub == "api/runs":
            try:
                sess = project_arg(q)
                rs = activity.runs(sess)
                idx = {}
                for r in rs:
                    if r.get("exit") is None and r.get("session"):
                        if r["session"] not in idx:
                            idx[r["session"]] = dict(l.split(SEP, 1) for l in tmux(
                                "list-windows", "-t", f"={r['session']}", "-F", f"#{{window_name}}{SEP}#{{window_index}}").splitlines() if SEP in l)
                        r["window_index"] = idx[r["session"]].get(r.get("win"))
                self._json(200, {"runs": rs})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub == "api/log":
            try:
                txt = activity.log_text(project_arg(q), (q.get("id") or [""])[0])
                self._send(200, txt.encode(), "text/plain; charset=utf-8")
            except (FileNotFoundError, ValueError):
                self._json(404, {"error": "no log (still running?)"})
        elif sub == "api/feed":
            try:
                self._json(200, {"feed": activity.feed(project_arg(q))})
            except ValueError as e:
                self._json(400, {"error": str(e)})
```

  - **`_act`:**

```python
    if a == "idea":
        return ideas.add(sess, body.get("text", ""), body.get("detail", ""))
```

    `ideas.add` raises `ValueError` on bad input. `do_POST`'s generic handler already turns that into 400.
  - **`restart_orchestrator`:**
    - In the `claude` branch, replace `tmux("respawn-pane", "-k", "-t", pane, "-c", root, check=True)` with `relay.respawn(tmux, pane, root)`.
    - In the `else` branch, add `relay.respawn(tmux, pane, root)` after the `move-window` lines.
    - Delete the shared `tmux("send-keys", "-t", pane, "claude-orchestrator", "Enter", check=True)` line.
  - **`test_restart_orchestrator.py`:** replace the send-keys assertion (line 86) with:

```python
        sk = fake.find("send-keys")
        self.assertEqual(sk[0], ("send-keys", "-t", "%7", "-l", "--", "claude-orchestrator"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%7", "Enter"))
```

    If any test asserts `respawn-pane` is absent in the new-window branch, update it to expect one `respawn-pane` on `%9`.

- [ ] **Step 5: Run the whole suite.** Expected: all OK.

- [ ] **Step 6: Report.**

```json:metadata
{"files": ["~/.local/share/tmux-dash/activity.py", "~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/tests/test_activity.py", "~/.local/share/tmux-dash/tests/test_restart_orchestrator.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v", "acceptanceCriteria": ["runs deduped by id, newest first", "log by id only, outside-dir refused", "feed blocks parsed", "@tc_bg sessions hidden", "api/ideas and idea action", "restart_orchestrator via relay.respawn with updated test", "running runs carry window_index"], "modelTier": "standard", "owner": "panel"}
```

---

### Task 10: Board sidebar: artifacts, viewer, changes, edit, comment

**Goal:** A hideable left sidebar listing session artifacts (seed plus accumulate rule), and a document viewer with Read / Changes / Edit modes, agent-attributed change highlights, conflict handling and comments to the lead.

**Files:**
- Create: `~/.local/share/tmux-dash/vendor/marked.min.js`, `~/.local/share/tmux-dash/vendor/purify.min.js`
- Modify: `~/.local/share/tmux-dash/server.py` (serve `vendor/*.js`, allowlisted names)
- Modify (staged): `~/.local/share/tmux-dash/index.html` → `index.next.html`

**Acceptance Criteria:**
- [ ] ◀/▶ collapses the sidebar to a 36px rail; the state survives a reload (`localStorage` `dash.side`, read and write inside try/catch)
- [ ] On load the list shows only current-epoch items plus the active plan plus the handoff doc the lead started from; items written after load are added; nothing is dropped until reload
- [ ] Items group under "Session N (current)" headings by epoch, newest first; Plan is pinned on top; each item shows a kind icon, an agent badge, and a dot when its hash differs from the last-viewed hash
- [ ] Read renders sanitized markdown (marked + DOMPurify). Changes shows raw lines, with added lines highlighted and tagged with the agent that added them. Edit saves with `base_hash`
- [ ] On 409 the conflict view shows both texts with Reload / Overwrite / Copy mine
- [ ] Selecting text in Read and pressing Comment sends `{path, anchor: nearest heading, quote, note}`; pending comments show under the Plan pin
- [ ] `GET vendor/marked.min.js` returns `application/javascript`; `GET vendor/other.js` returns 404

**Verify:** `python3 -m unittest discover -s ~/.local/share/tmux-dash/tests -v` plus `test_vendor_route` passing; the live check in Task 14

**Steps:**

- [ ] **Step 1: Vendor the libraries**

```zsh
mkdir -p ~/.local/share/tmux-dash/vendor && cd ~/.local/share/tmux-dash/vendor
curl -fsSL https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js -o marked.min.js
curl -fsSL https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js -o purify.min.js
head -c 120 marked.min.js; echo; head -c 120 purify.min.js
```

  Expected: both start with a license comment.

- [ ] **Step 2: Serve them (test first)**

  Add to `tests/test_artifacts.py`:

```python
class VendorRouteTest(unittest.TestCase):
    def test_vendor_route(self):
        self.assertEqual(server.vendor_file("marked.min.js").name, "marked.min.js")
        self.assertIsNone(server.vendor_file("other.js"))
        self.assertIsNone(server.vendor_file("../server.py"))
```

  Then add to `server.py`:

```python
VENDOR = {"marked.min.js", "purify.min.js"}


def vendor_file(name):
    return HERE / "vendor" / name if name in VENDOR else None
```

  And in `do_GET`:

```python
        elif sub.startswith("vendor/"):
            f = vendor_file(sub[len("vendor/"):])
            if f is None or not f.exists():
                self._send(404, b"not found", "text/plain")
            else:
                self._send(200, f.read_bytes(), "application/javascript; charset=utf-8", {"Cache-Control": "max-age=86400"})
```

  `_send` sets `Cache-Control: no-store` before the extra headers. Move the default `no-store` header so it is only sent when `extra` lacks `Cache-Control`.

- [ ] **Step 3: Stage the page:** `cp -p index.html index.html.bak-20261016 && cp -p index.html index.next.html`.

  To preview the staged page, temporarily point `do_GET`'s `""` branch at `os.environ.get("TMUX_DASH_PAGE", "index.html")`. Run a second board on port 7710 for preview: `TMUX_DASH_PAGE=index.next.html TMUX_DASH_PORT=7710 TMUX_DASH_TOKEN=$(cat ~/.local/state/tmux-dash/token) python3 server.py`, started with `tmux-ctl send shell`. Stop it later by PID.

- [ ] **Step 4: Markup.**
  - In `<head>`, after the existing `<style>`, add `<script src="vendor/marked.min.js"></script><script src="vendor/purify.min.js"></script>`.
  - Replace `<main id="main">` … `</main>` so `main` sits in a row with the sidebar:

```html
  <div class="row">
    <aside class="side" id="side">
      <div class="side-head"><b>Artifacts</b><button class="ghost" id="side-toggle" title="Hide panel">◀</button></div>
      <div class="side-body">
        <div id="pin-plan"></div>
        <div id="ideas-box"></div>
        <div id="art-groups"></div>
      </div>
    </aside>
    <main id="main">
      <!-- existing .col and .term section unchanged -->
      <section class="doc" id="doc">
        <div class="term-head">
          <b id="doc-title"></b>
          <nav class="tabs" id="doc-modes"><button data-mode="read">Read</button><button data-mode="changes">Changes</button><button data-mode="edit">Edit</button></nav>
          <button class="ghost" id="doc-comment" disabled title="Select text first">Comment</button>
          <button class="ghost" id="doc-close" title="Close">✕</button>
        </div>
        <div class="doc-banner" id="doc-banner"></div>
        <div class="doc-body" id="doc-body"></div>
      </section>
    </main>
  </div>
```

- [ ] **Step 5: CSS** (append to the `<style>` block; it uses the existing tokens `--panel`, `--panel-2`, `--border`, `--text`, `--muted`, `--mono`, `--shadow`):

```css
.app { grid-template-rows: auto auto 1fr; }
.row { display: flex; min-height: 0; }
.row > main { flex: 1; min-width: 0; }
.side { width: 320px; flex: none; display: flex; flex-direction: column; border-right: 1px solid var(--border); background: var(--panel); min-height: 0; transition: width .15s; }
.side.collapsed { width: 36px; }
.side.collapsed .side-body, .side.collapsed .side-head b { display: none; }
.side-head { display: flex; align-items: center; gap: 8px; padding: 10px 10px 10px 14px; border-bottom: 1px solid var(--border); }
.side-head b { flex: 1; }
.side-body { overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; }
.art-group h4 { margin: 4px 4px 6px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.art { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 6px 8px; border-radius: 8px; border: 1px solid transparent; background: none; }
.art:hover, .art.sel { background: var(--panel-2); border-color: var(--border); }
.art .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art .dot { width: 7px; height: 7px; border-radius: 50%; background: #e5534b; flex: none; }
.badge { font-size: 11px; color: var(--muted); background: var(--panel-2); border-radius: 6px; padding: 1px 6px; }
.pending { font-size: 12px; color: var(--muted); padding: 2px 8px; }
main.with-doc { grid-template-columns: minmax(320px, .8fr) minmax(460px, 1.4fr); }
.doc { display: none; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); flex-direction: column; min-height: 0; overflow: hidden; }
main.with-doc .doc { display: flex; }
main.with-doc .term { display: none; }
.doc-banner:empty { display: none; }
.doc-banner { padding: 8px 14px; font-size: 13px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
.doc-body { overflow: auto; padding: 14px 18px; flex: 1; }
.doc-body pre.lines { font: 12px/1.55 var(--mono); margin: 0; white-space: pre-wrap; }
.doc-body .add { background: rgba(46, 160, 67, .18); display: block; }
.doc-body .add .who { float: right; font-size: 10px; color: var(--muted); }
.doc-body textarea { width: 100%; height: 100%; min-height: 60vh; font: 12px/1.55 var(--mono); }
.conflict { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.conflict pre { font: 11.5px/1.5 var(--mono); background: var(--panel-2); padding: 8px; border-radius: 8px; max-height: 50vh; overflow: auto; white-space: pre-wrap; }
@media (max-width: 900px) { .side { position: absolute; z-index: 5; height: calc(100% - 60px); } .side.collapsed { position: static; } }
```

- [ ] **Step 6: JS.** Add after `function render()`:

```js
// ── artifacts panel: page-lifetime state per session (cleared by reload) ──
const KIND_ICON = { plan: "▤", spec: "◇", handoff: "⇄", report: "▦", published: "↗", other: "•" };
const ART = {};
const artFor = (name) => (ART[name] ||= { items: new Map(), versions: new Map(), seen: new Map(), loadedAt: Date.now() / 1000, first: true, epoch: 0, plan: null, startedFrom: null, comments: [] });
let docSel = null, docMode = "read", docSelection = null;
const api = (path) => fetch(`${API}/${path}`, { cache: "no-store" });
async function post(body) {
  const r = await fetch(`${API}/action`, { method: "POST", headers: { "Content-Type": "application/json", "X-Dash-Token": TOKEN }, body: JSON.stringify(body) });
  return { status: r.status, j: await r.json().catch(() => ({})) };
}

try { if (localStorage.getItem("dash.side") === "collapsed") $("#side").classList.add("collapsed"); } catch (e) {}
$("#side-toggle").onclick = () => {
  const c = $("#side").classList.toggle("collapsed");
  $("#side-toggle").textContent = c ? "▶" : "◀";
  try { localStorage.setItem("dash.side", c ? "collapsed" : "open"); } catch (e) {}
};
$("#side-toggle").textContent = $("#side").classList.contains("collapsed") ? "▶" : "◀";

async function pollArtifacts() {
  const s = session(); if (!s) return;
  const A = artFor(s.name);
  const r = await api(`artifacts?session=${encodeURIComponent(s.name)}`); if (!r.ok) return;
  const d = await r.json();
  Object.assign(A, { epoch: d.epoch, plan: d.active_plan, startedFrom: d.started_from, comments: d.comments || [] });
  for (const it of d.items) {
    const key = it.url || it.path;
    const seed = A.first && (it.latest.epoch === d.epoch || it.path === d.active_plan || it.path === d.started_from);
    if (A.items.has(key) || seed || it.latest.ts >= A.loadedAt) A.items.set(key, it);
  }
  A.first = false;
  for (const it of A.items.values()) if (!it.url) await trackVersion(s.name, A, it);
  renderArtifacts();
  if (docSel && docMode !== "edit") renderDoc();
}

async function trackVersion(name, A, it) {
  const vs = A.versions.get(it.path) || [];
  if (vs.length && vs[vs.length - 1].hash === it.latest.hash) return;
  const r = await api(`artifact?session=${encodeURIComponent(name)}&path=${encodeURIComponent(it.path)}`); if (!r.ok) return;
  const f = await r.json();
  if (vs.length && vs[vs.length - 1].hash === f.hash) return;
  const h = it.history.slice().reverse().find((x) => x.hash === f.hash);
  vs.push({ hash: f.hash, agent: (h || it.latest).agent, text: f.text });
  if (vs.length > 30) vs.splice(1, vs.length - 30);   // keep the first (baseline) and the last 29
  A.versions.set(it.path, vs);
}

function artButton(A, it) {
  const b = el("button", "art" + (docSel === (it.url || it.path) ? " sel" : ""));
  b.append(el("span", "", KIND_ICON[it.kind] || "•"), el("span", "nm", it.url ? it.url.split("/").pop() : it.path.split("/").pop()), el("span", "badge", it.latest.agent || "?"));
  const vs = A.versions.get(it.path);
  if (!it.url && vs && A.seen.get(it.path) !== vs[vs.length - 1].hash) b.append(el("span", "dot"));
  b.title = it.url || it.path;
  b.onclick = () => it.url ? window.open(it.url, "_blank", "noopener") : openDoc(it.path);
  return b;
}

function renderArtifacts() {
  const s = session(); if (!s) return;
  const A = artFor(s.name);
  const pin = $("#pin-plan"); pin.replaceChildren();
  const plan = A.plan && A.items.get(A.plan);
  if (plan) {
    pin.append(el("div", "art-group"), artButton(A, plan));
    pin.firstChild.append(el("h4", "", "Plan"));
    if (A.comments.length) pin.append(el("div", "pending", `${A.comments.length} comment${A.comments.length > 1 ? "s" : ""} waiting for the lead`));
    const vs = A.versions.get(A.plan);
    const txt = vs && vs[vs.length - 1].text;
    if (txt && /- \[x\]/i.test(txt) && !/- \[ \]/.test(txt)) pin.append(el("div", "pending", `Plan done · ${window.ideasOpen || 0} ideas ready for next steps`));
  }
  const groups = new Map();
  for (const it of A.items.values()) {
    if (it.path === A.plan) continue;
    const e = it.latest.epoch ?? 0;
    if (!groups.has(e)) groups.set(e, []);
    groups.get(e).push(it);
  }
  const box = $("#art-groups"); box.replaceChildren();
  for (const e of [...groups.keys()].sort((a, b) => b - a)) {
    const g = el("div", "art-group");
    g.append(el("h4", "", `Session ${e + 1}${e === A.epoch ? " (current)" : ""}`));
    for (const it of groups.get(e).sort((a, b) => b.latest.ts - a.latest.ts)) g.append(artButton(A, it));
    box.append(g);
  }
  if (!A.items.size) box.append(el("div", "pending", "No artifacts yet in this session."));
}

function openDoc(path) {
  docSel = path; docMode = "read";
  $("#main").classList.add("with-doc");
  renderDoc(); renderArtifacts();
}
$("#doc-close").onclick = () => { docSel = null; $("#main").classList.remove("with-doc"); renderArtifacts(); };
for (const b of $("#doc-modes").children) b.onclick = () => { docMode = b.dataset.mode; renderDoc(); };

function lineDiff(a, b) {   // LCS line diff: B's lines, each {text, added}
  const A = a.split("\n"), B = b.split("\n"), n = A.length, m = B.length;
  if (n * m > 4e6) return B.map((text) => ({ text, added: false }));
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (j < m) {
    if (i < n && A[i] === B[j]) { out.push({ text: B[j], added: false }); i++; j++; }
    else if (i < n && dp[i + 1][j] >= dp[i][j + 1]) i++;
    else { out.push({ text: B[j], added: true }); j++; }
  }
  return out;
}

function changesSince(vs, seenHash) {   // added lines vs the last-viewed version, each tagged with the agent that added it
  let base = vs.findIndex((v) => v.hash === seenHash); if (base < 0) base = 0;
  const who = new Map();
  for (let k = base + 1; k < vs.length; k++) for (const l of lineDiff(vs[k - 1].text, vs[k].text)) if (l.added) who.set(l.text, vs[k].agent);
  return lineDiff(vs[base].text, vs[vs.length - 1].text).map((l) => ({ ...l, agent: l.added ? who.get(l.text) || vs[vs.length - 1].agent : null }));
}

function nearestHeading(node) {
  for (let n = node; n && n !== $("#doc-body"); n = n.previousElementSibling || n.parentElement) {
    if (n.nodeType === 1 && /^H[1-6]$/.test(n.tagName)) return n.textContent.trim();
  }
  return "";
}

function renderDoc() {
  const s = session(); if (!s || !docSel) return;
  const A = artFor(s.name), vs = A.versions.get(docSel) || [];
  const cur = vs[vs.length - 1];
  $("#doc-title").textContent = docSel.split("/").pop();
  for (const b of $("#doc-modes").children) b.classList.toggle("on", b.dataset.mode === docMode);
  const body = $("#doc-body"), banner = $("#doc-banner");
  if (!cur) { body.textContent = "Loading…"; return; }
  const ch = changesSince(vs, A.seen.get(docSel));
  const added = ch.filter((l) => l.added);
  banner.textContent = added.length && docMode !== "changes" ? `${added.length} line${added.length > 1 ? "s" : ""} changed by ${[...new Set(added.map((l) => l.agent))].join(", ")} since you last looked — see Changes` : "";
  if (docMode === "read") {
    body.innerHTML = DOMPurify.sanitize(marked.parse(cur.text));
    A.seen.set(docSel, cur.hash);
  } else if (docMode === "changes") {
    const pre = el("pre", "lines");
    for (const l of ch) {
      const row = el("span", l.added ? "add" : "", l.text || " ");
      if (l.added) row.append(el("span", "who", l.agent));
      pre.append(row, l.added ? "" : "\n");
    }
    body.replaceChildren(pre);
    A.seen.set(docSel, cur.hash);
  } else {
    const ta = el("textarea"); ta.value = cur.text;
    const save = el("button", "primary", "Save");
    const base = cur.hash;
    save.onclick = async () => {
      const { status, j } = await post({ action: "save", session: s.name, path: docSel, base_hash: base, text: ta.value });
      if (status === 200) { toast("Saved"); docMode = "read"; await pollArtifacts(); }
      else if (status === 409) showConflict(s.name, ta.value, j.current);
      else toast(j.message || "Save failed", true);
    };
    body.replaceChildren(save, ta);
  }
  renderArtifacts();
}

function showConflict(name, mine, current) {
  const body = $("#doc-body");
  const grid = el("div", "conflict");
  const theirs = el("div"); theirs.append(el("b", "", "Their version (on disk)"), el("pre", "", current.text));
  const yours = el("div"); yours.append(el("b", "", "Your version"), el("pre", "", mine));
  grid.append(theirs, yours);
  const reload = el("button", "", "Reload"), over = el("button", "primary", "Overwrite"), copy = el("button", "", "Copy mine");
  reload.onclick = async () => { docMode = "read"; await pollArtifacts(); renderDoc(); };
  over.onclick = async () => {
    const { status, j } = await post({ action: "save", session: name, path: docSel, base_hash: current.hash, text: mine });
    if (status === 200) { toast("Saved"); docMode = "read"; await pollArtifacts(); } else toast(j.message || "Save failed", true);
  };
  copy.onclick = () => navigator.clipboard.writeText(mine).then(() => toast("Copied"), () => toast("Copy failed", true));
  body.replaceChildren(el("p", "", "The file changed while you were editing."), reload, over, copy, grid);
}

document.addEventListener("selectionchange", () => {
  const sel = document.getSelection();
  const inDoc = docMode === "read" && sel && !sel.isCollapsed && $("#doc-body").contains(sel.anchorNode);
  docSelection = inDoc ? { quote: sel.toString().trim().slice(0, 200), anchor: nearestHeading(sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement) } : docSelection;
  $("#doc-comment").disabled = !inDoc && !docSelection;
});
$("#doc-comment").onclick = () => {
  if (!docSelection) return;
  const s = session(), box = el("div", "doc-banner");
  const ta = el("textarea"); ta.rows = 3; ta.placeholder = `Note for the lead about "${docSelection.quote.slice(0, 60)}"`;
  const send = el("button", "primary", "Send to lead"), cancel = el("button", "ghost", "Cancel");
  const sel = docSelection;
  send.onclick = async () => {
    const { status, j } = await post({ action: "comment", session: s.name, path: docSel, anchor: sel.anchor, quote: sel.quote, note: ta.value });
    toast(j.message || (status === 200 ? "Queued" : "Failed"), status !== 200);
    if (status === 200) { box.remove(); docSelection = null; pollArtifacts(); }
  };
  cancel.onclick = () => box.remove();
  box.append(ta, send, cancel);
  $("#doc-banner").after(box);
  ta.focus();
};
```

  Then change the poll loop line to:

```js
(async function poll() { try { await refresh(); await pollArtifacts(); } catch (e) { console.error(e); } finally { setTimeout(poll, 2000); } })();
```

  When a terminal opens, the doc view yields: in `openTerm`, add `$("#main").classList.remove("with-doc");` as its first line.

- [ ] **Step 7: Check the staged page** on the preview board (port 7710) with a scratch tmux session (`tt`-style, via `TC_STATE` pointing at a temp dir with hand-written manifest lines). Confirm each acceptance criterion by eye, or with Chrome tools if available. Then stop the preview board by its PID.

- [ ] **Step 8: Swap in** with `mv index.next.html index.html`. The live board serves it on the next request. Revert `TMUX_DASH_PAGE` only if you added it; keep it if it stays harmless (default `index.html`). Run the Python suite again and report.

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html", "~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/vendor/marked.min.js", "~/.local/share/tmux-dash/vendor/purify.min.js", "~/.local/share/tmux-dash/tests/test_artifacts.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v", "acceptanceCriteria": ["sidebar collapses and remembers state", "seed current epoch + active plan + started_from, then accumulate", "epoch groups, pinned plan, kind icon, agent badge, updated dot", "Read sanitized markdown, Changes with agent tags, Edit with base_hash", "409 conflict view with Reload/Overwrite/Copy mine", "Comment sends anchor+quote+note; pending shown", "vendor route allowlist"], "modelTier": "standard", "owner": "panel"}
```

---

### Task 11: Board Ideas box and Activity drawer

**Goal:** A pinned Ideas box (count, list, add) and an Activity drawer under the main area with Runs (cards, log, Open live, red fail count) and Commands (feed filterable by agent).

**Files:**
- Modify (staged): `~/.local/share/tmux-dash/index.html` → `index.next.html`

**Acceptance Criteria:**
- [ ] The Ideas header shows `Ideas · N` (open count); the open ideas are listed; Enter in the input posts `idea` and the list refreshes
- [ ] The Plan pin's "Plan done · N ideas ready" uses the same N
- [ ] The Activity drawer is collapsed by default; its header shows a red `N failed` for failed runs not yet seen while collapsed; opening it clears the count
- [ ] Runs tab: a card per run with agent, command, time, a spinner while `exit===null`, then ✔/✘ and the summary. Clicking shows the log in a `<pre>`. **Open live** opens the ttyd terminal on `run.session`/`window_index` while running
- [ ] Commands tab: feed blocks with an agent filter `<select>` built from the agents present

**Verify:** the live check in Task 14 (the page has no unit test harness); `python3 -m unittest discover -s ~/.local/share/tmux-dash/tests -v` stays green

**Steps:**

- [ ] **Step 1: Stage** `index.next.html` from the current `index.html`.

- [ ] **Step 2: Markup.** Add as the last child of `<main id="main">`:

```html
      <section class="activity" id="activity">
        <button class="act-head" id="act-toggle"><b>Activity</b> <span class="fails" id="act-fails"></span><span class="chev">▸</span></button>
        <div class="act-body">
          <nav class="tabs"><button data-tab="runs" class="on">Runs</button><button data-tab="cmds">Commands</button><select id="act-agent"><option value="">All agents</option></select></nav>
          <div id="act-runs"></div>
          <div id="act-cmds" hidden></div>
        </div>
      </section>
```

- [ ] **Step 3: CSS**

```css
main { grid-template-rows: minmax(0, 1fr) auto; }
.activity { grid-column: 1 / -1; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); overflow: hidden; }
.act-head { display: flex; gap: 8px; align-items: center; width: 100%; border: 0; border-radius: 0; padding: 8px 12px; background: none; }
.act-head .chev { margin-left: auto; transition: transform .15s; }
.activity.open .chev { transform: rotate(90deg); }
.act-body { display: none; max-height: 38vh; overflow: auto; padding: 0 12px 12px; }
.activity.open .act-body { display: block; }
.fails:empty { display: none; }
.fails { color: #fff; background: #e5534b; border-radius: 999px; font-size: 11px; padding: 1px 8px; }
.run { border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; margin-top: 8px; cursor: pointer; }
.run .top { display: flex; gap: 8px; align-items: center; }
.run code { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 12px var(--mono); }
.run pre, .cmd pre { font: 11.5px/1.5 var(--mono); background: var(--panel-2); padding: 8px; border-radius: 8px; max-height: 30vh; overflow: auto; white-space: pre-wrap; margin: 8px 0 0; }
.ok { color: #2ea043; } .bad { color: #e5534b; }
.spin { display: inline-block; animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
.cmd { border-bottom: 1px solid var(--border); padding: 6px 0; font-size: 12.5px; }
.ideas-list { display: flex; flex-direction: column; gap: 4px; }
.idea { font-size: 13px; padding: 4px 8px; border-radius: 8px; background: var(--panel-2); }
.idea small { color: var(--muted); display: block; }
```

- [ ] **Step 4: JS.** Add after the artifacts code:

```js
// ── ideas box ──
window.ideasOpen = 0;
async function pollIdeas() {
  const s = session(); if (!s) return;
  const r = await api(`ideas?session=${encodeURIComponent(s.name)}`); if (!r.ok) return;
  const d = await r.json();
  window.ideasOpen = d.open;
  const box = $("#ideas-box");
  if (!box.dataset.built) {
    box.dataset.built = "1";
    box.append(el("div", "art-group"));
    const inp = el("input"); inp.placeholder = "Idea for later… (Enter)"; inp.id = "idea-input";
    const det = el("textarea"); det.rows = 2; det.placeholder = "Detail (optional)"; det.id = "idea-detail";
    inp.onkeydown = async (e) => {
      if (e.key !== "Enter" || !inp.value.trim()) return;
      const { status, j } = await post({ action: "idea", session: session().name, text: inp.value, detail: det.value });
      toast(status === 200 ? "Noted for later" : (j.message || "Failed"), status !== 200);
      if (status === 200) { inp.value = ""; det.value = ""; pollIdeas(); }
    };
    box.append(inp, det, el("div", "ideas-list"));
  }
  box.querySelector(".art-group").replaceChildren(el("h4", "", `Ideas · ${d.open}`));
  const list = box.querySelector(".ideas-list"); list.replaceChildren();
  for (const i of d.ideas.filter((i) => i.status === "open").slice(-20).reverse()) {
    const row = el("div", "idea", i.text); row.append(el("small", "", i.ts + (i.detail ? " · " + i.detail.split("\n")[0] : "")));
    list.append(row);
  }
}

// ── activity drawer ──
const ACT = { open: false, tab: "runs", seenFails: new Set(), openLogs: new Set() };
$("#act-toggle").onclick = () => { ACT.open = !ACT.open; $("#activity").classList.toggle("open", ACT.open); pollActivity(); };
for (const b of $("#activity nav").querySelectorAll("button")) b.onclick = () => {
  ACT.tab = b.dataset.tab;
  for (const x of $("#activity nav").querySelectorAll("button")) x.classList.toggle("on", x === b);
  $("#act-runs").hidden = ACT.tab !== "runs"; $("#act-cmds").hidden = ACT.tab !== "cmds";
  pollActivity();
};
$("#act-agent").onchange = () => pollActivity();

async function pollActivity() {
  const s = session(); if (!s) return;
  const r = await api(`runs?session=${encodeURIComponent(s.name)}`); if (!r.ok) return;
  const runs = (await r.json()).runs || [];
  const failed = runs.filter((x) => x.exit !== null && x.exit !== 0);
  if (ACT.open) failed.forEach((x) => ACT.seenFails.add(x.id));
  const unseen = failed.filter((x) => !ACT.seenFails.has(x.id)).length;
  $("#act-fails").textContent = unseen ? `${unseen} failed` : "";
  if (!ACT.open) return;
  if (ACT.tab === "runs") renderRuns(s, runs); else await renderCmds(s);
}

function renderRuns(s, runs) {
  const box = $("#act-runs"); box.replaceChildren();
  if (!runs.length) box.append(el("div", "pending", "No agent runs yet."));
  for (const x of runs) {
    const card = el("div", "run"), top = el("div", "top");
    const st = x.exit === null ? el("span", "spin", "◌") : el("span", x.exit === 0 ? "ok" : "bad", x.exit === 0 ? "✔" : "✘");
    top.append(st, el("span", "badge", x.agent), el("code", "", x.cmd), el("span", "badge", x.summary || (x.exit === null ? "running" : `exit ${x.exit}`)),
      el("small", "", new Date(x.ts * 1000).toLocaleTimeString()));
    if (x.exit === null && x.window_index != null) {
      const live = el("button", "ghost", "Open live");
      live.onclick = (e) => { e.stopPropagation(); openTerm({ name: x.session }, { index: x.window_index, name: x.win }); };
      top.append(live);
    }
    card.append(top);
    card.onclick = async () => {
      if (ACT.openLogs.has(x.id)) { ACT.openLogs.delete(x.id); card.querySelector("pre")?.remove(); return; }
      ACT.openLogs.add(x.id);
      const lr = await api(`log?session=${encodeURIComponent(s.name)}&id=${encodeURIComponent(x.id)}`);
      card.append(el("pre", "", lr.ok ? await lr.text() : "Still running — use Open live."));
    };
    box.append(card);
  }
}

async function renderCmds(s) {
  const r = await api(`feed?session=${encodeURIComponent(s.name)}`); if (!r.ok) return;
  const feed = (await r.json()).feed || [];
  const sel = $("#act-agent"), want = sel.value;
  const agents = [...new Set(feed.map((b) => b.agent))].sort();
  sel.replaceChildren(el("option", "", "All agents")); sel.firstChild.value = "";
  for (const a of agents) { const o = el("option", "", a); o.value = a; sel.append(o); }
  sel.value = agents.includes(want) ? want : "";
  const box = $("#act-cmds"); box.replaceChildren();
  for (const b of feed.filter((b) => !sel.value || b.agent === sel.value).reverse()) {
    const row = el("div", "cmd");
    row.append(el("span", b.exit === 0 ? "ok" : "bad", b.exit === 0 ? "✔ " : "✘ "), el("span", "badge", b.agent), " ", el("code", "", b.cmd), " ", el("small", "", `${b.time} · ${b.win}`));
    if (b.tail) row.append(el("pre", "", b.tail));
    box.append(row);
  }
}
```

  Change the poll loop line to:

```js
(async function poll() { try { await refresh(); await pollArtifacts(); await pollIdeas(); await pollActivity(); } catch (e) { console.error(e); } finally { setTimeout(poll, 2000); } })();
```

  `openTerm` reads `s.name`, `w.index` and `w.name` only. Check that, and if it reads more, pass those fields as well.

- [ ] **Step 5: Check on the preview board** with a scratch session that has run records and an ideas file (`TC_IDEAS_DIR`). Then **swap in** (`mv index.next.html index.html`) and report.

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests -v", "acceptanceCriteria": ["Ideas header count, list, Enter posts idea", "Plan done cue uses open count", "drawer collapsed by default with unseen fail count cleared on open", "Runs cards with spinner, status, summary, log, Open live", "Commands feed with agent filter"], "modelTier": "standard", "owner": "panel"}
```

---

### Task 12: Handoff skill: checkpoint, Team section, confirm, relay

**Goal:** Rewrite the user-only `/handoff` skill so it checkpoints teammates, writes the doc with a Team section to `~/.claude/handoffs/`, registers it, shuts the team down, asks the user, and relays. Also point the context guard at it.

**Files:**
- Modify: `~/.claude/skills/handoff/SKILL.md`
- Modify: `~/.claude/hooks/context-size-guard.sh` (the two message strings only)

**Acceptance Criteria:**
- [ ] The skill keeps `disable-model-invocation: true` and the argument hint
- [ ] The steps, in order: checkpoint (2-minute timeout → `no checkpoint` + last 40 lines via `tmux-ctl read`) → write the doc with Team section, old session id and ideas-file link → `tmux-ctl artifact <doc> --kind handoff` → shut down with the ToolSearch hint → AskUserQuestion "Switch to a fresh orchestrator now?" (Yes / Not yet) → on Yes `tmux-ctl relay <doc> --old-session <id>`, on Not yet print the doc path and the relay command
- [ ] Outside a dev session (no `$TMUX`), it falls back to the old behaviour: print the path and paste prompt
- [ ] The guard message says `/handoff` checkpoints the team and asks before switching, and no longer says `/clear`
- [ ] A live run in a scratch session with two haiku teammates produces a doc with both Team entries, asks the question, and on Yes the new lead starts from the doc (checked in Task 14)

**Verify:** `grep -c 'tmux-ctl relay' ~/.claude/skills/handoff/SKILL.md` ≥ 1; `grep -c '/clear' ~/.claude/hooks/context-size-guard.sh` = 0; the live check in Task 14

**Steps:**

- [ ] **Step 1: Back up both files.**

- [ ] **Step 2: Write `SKILL.md`**

````markdown
---
name: handoff
description: Hand this session to a fresh orchestrator: checkpoint the team, write a handoff doc, ask, then relay in place.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

Hand the work in this session to a fresh orchestrator. If the user passed arguments, they describe what the next session should focus on; tailor the doc to that.

## 1. Checkpoint the team (skip if you have no teammates)

Send every teammate this message with SendMessage:

> Handoff checkpoint. Finish or pause your current step at a safe point (don't leave a file half-edited), then reply to me with exactly these fields: name, role, model tier, current task (id and subject), files you own, progress so far, next step, assumptions made, anything unfinished or risky. Then stop and wait; a shutdown request follows.

Wait up to 2 minutes for the replies. For a teammate that has not answered, record `no checkpoint`. Add the last 40 lines of its window from `tmux-ctl read "✦ <name>" 40`, or from `tmux-ctl read <name> 40` if the window has no ✦ prefix.

## 2. Write the handoff doc

Save to `~/.claude/handoffs/YYYY-MM-DD-<short-slug>.md` (today's date). Include:

- **Focus**: what the next session is for (the arguments, or your best summary).
- **State of the work**: what is done, in progress and next. Reference the plan, spec, branch, MR and commits by path or URL instead of copying them.
- **Team**: one entry per teammate, built from its checkpoint: name, role, model tier, task, files owned, progress, next step, assumptions, risks. Mark teammates without a reply as `no checkpoint` and include their captured output.
- **Previous session**: its id, so it stays resumable with `claude --resume <id>`. Find the id as the basename (without `.jsonl`) of the newest file in `~/.claude/projects/<cwd with / replaced by ->/`.
- **Ideas**: one line: `Ideas inbox: ~/.claude/ideas/<project>.md (do not read until the plan is done)`. `<project>` is the tmux session name. Never copy ideas into the doc.
- **Suggested skills**: the skills the next lead should invoke with the Skill tool.

Redact secrets and personal data.

Register it: `tmux-ctl artifact <doc> --kind handoff`.

## 3. Shut the team down

Send each teammate a `shutdown_request`. End its `reason` with: "To approve: first load SendMessage's schema with ToolSearch query \"select:SendMessage\", then send `message` as a JSON object, not a string." Confirm each one is gone.

## 4. Ask before switching (never skip)

Ask with AskUserQuestion: "Switch to a fresh orchestrator now?"

- **Yes**: "This window restarts as a new orchestrator that starts from the doc and respawns the team. This session stays resumable."
- **Not yet**: "Keep this session. I'll print the doc path and the command to switch later."

## 5. Relay

- **On Yes:** run `tmux-ctl relay <doc> --old-session <id>`. Then end your turn with one line: "Switching once this turn ends; the new orchestrator starts from <doc>." The relay waits for your turn to end, then replaces this window.
- **On Not yet, or outside tmux (`$TMUX` unset):** end with

```
Handoff saved: <absolute path>

Switch later: tmux-ctl relay <absolute path> --old-session <id>
Or start a session by hand: Read <absolute path> and continue from where the previous session left off.
```
````

- [ ] **Step 3: Guard message.** In `context-size-guard.sh`, replace the `msg=` string with:

  `"🛑 CONTEXT AT ${k}K TOKENS (limit ${THRESHOLD}). Run /handoff: it checkpoints the team, writes a handoff doc and asks before switching this window to a fresh orchestrator. Or /compact to stay here."`

  In the `ctx` string, replace the sentence about `/clear` with: `"...strongly recommending the user run /handoff (it checkpoints the team, writes the doc, and asks before relaying to a fresh orchestrator in this window)."`

  Keep the rest unchanged.

- [ ] **Step 4: Verify with the grep commands, then report.** The live run is part of Task 14.

```json:metadata
{"files": ["~/.claude/skills/handoff/SKILL.md", "~/.claude/hooks/context-size-guard.sh"], "verifyCommand": "grep -c 'tmux-ctl relay' ~/.claude/skills/handoff/SKILL.md && ! grep -q '/clear' ~/.claude/hooks/context-size-guard.sh", "acceptanceCriteria": ["user-only frontmatter kept", "checkpoint -> doc with Team -> register -> shutdown -> ask -> relay order", "outside tmux falls back to path + paste prompt", "guard message updated, no /clear", "live run checked in Task 14"], "modelTier": "frontier", "owner": "relay"}
```

---

### Task 13: Prompt and doc updates

**Goal:** Teach the orchestrator, workers and the tmux-orchestrator skill:
- the start-from-handoff respawn rule;
- the ideas rules and the Next steps round;
- `[Plan comment]` handling;
- the new window layout.

**Files:**
- Modify: `~/.claude/orchestrator.md`, `~/.claude/worker.md`, `~/.claude/skills/tmux-orchestrator/SKILL.md`

**Acceptance Criteria:**
- [ ] `orchestrator.md` has a "Starting from a handoff" section: respawn each Team entry with the same name, role and tier, with its state note first in its prompt; `no checkpoint` teammates re-check their files first
- [ ] `orchestrator.md` has an "Ideas inbox" section:
  - `idea:` → `tmux-ctl idea`, reply "noted for later", never act;
  - never read the ideas file during a plan;
  - after `finishing-a-development-branch`, run the Next steps round (group, brainstorm now / park / drop via AskUserQuestion, then `brainstorming` per chosen group; mark `[x] … → <spec>` / `[-]`)
- [ ] `orchestrator.md` treats `[Plan comment] …` lines as user feedback on the plan (assess, update the plan if right, tell the user what changed)
- [ ] The window tables and rule 5 in all three files say:
  - the user has `claude` + their own `shell`;
  - agent `tests`/`shell` windows live in hidden `<project>-bg`;
  - `tmux-ctl run tests` is still how suites run;
  - the user watches runs in the board's Activity drawer;
  - never type into the user's `shell`
- [ ] Teammate prompts never mention the ideas file

**Verify:** `grep -n 'Starting from a handoff\|Ideas inbox\|\[Plan comment\]\|-bg' ~/.claude/orchestrator.md` shows all four; `grep -n '\-bg' ~/.claude/worker.md ~/.claude/skills/tmux-orchestrator/SKILL.md` shows each file

**Steps:**

- [ ] **Step 1: Back up all three files.**

- [ ] **Step 2: Add to `orchestrator.md`** after the "Default: use an agent team" section:

```markdown
## Starting from a handoff

If your first prompt says to read a handoff doc (`~/.claude/handoffs/…`), read it first. If it has a **Team** section, start the team again before anything else:
- Respawn every teammate with the same name, role and tier (see "Models and effort").
- Start each teammate's prompt with the usual teammate rules, then its checkpoint note from the doc: task, files, progress, next step, assumptions.
- A teammate marked `no checkpoint` gets its captured output, and is told to re-check the state of its files before continuing.

Then continue with the plan, using the task list and the plan file as the source of truth.

## Ideas inbox

The user keeps ideas for future work in `~/.claude/ideas/<project>.md` (the board's Ideas box, or `tmux-ctl idea`).
- A user message starting with `idea:` is filed, not acted on: run `tmux-ctl idea "<the rest>"`, reply "noted for later" in one line, and carry on with the current work.
- Don't read the ideas file while a plan is in progress, and never mention it to teammates.
- **Next steps round.** When every plan task is complete and `finishing-a-development-branch` has run, read the open ideas (`- [ ]`):
  1. Group related ideas and note any that overlap with what was just built.
  2. Ask with AskUserQuestion, per group: brainstorm now / park / drop.
  3. Take each chosen group through `brainstorming`, one at a time.
  4. Mark ideas taken up as `- [x] … → <spec path>` and dropped ones as `- [-] …`. Never delete an idea.

## Plan comments from the board

A line starting `[Plan comment] <file> § <section>: "<quote>" — <note>` was sent by the user from the board's artifacts panel. Treat it as user feedback on that part of the plan:
1. Decide whether it is right.
2. Update the plan or the tasks if it is.
3. Tell the user in one or two lines what changed, or why nothing did.
```

- [ ] **Step 3: Replace rule 5** in `orchestrator.md` ("Teammates and workers don't talk to the user") with:

```markdown
5. Run test suites and long builds with `tmux-ctl run tests "<cmd>"`: it runs in the hidden session `<project>-bg` (a lane window `tests·<you>` if `tests` is busy), in your own worktree (`-C <dir>` to override), and the user sees every run in the Agent Board's Activity drawer. Use your Bash tool for everything else. Never type into the user's own `shell` window.
```

- [ ] **Step 4: Replace "The session's windows"** table and its lead-in in `orchestrator.md` with:

```markdown
| Window | Use |
| --- | --- |
| `claude` | you, the team lead |
| `✦ <name>` | one per teammate while the team runs; closes when you shut it down |
| `shell` | the user's own terminal. Never type into it |
| `<project>-bg` (hidden session) | the agents' `tests` and `shell` windows and their lanes, driven only through `tmux-ctl` |

The user follows agent runs and commands in the Agent Board's Activity drawer, and plans, specs, handoffs and reports in its artifacts panel. Drive `tests` and `shell` with `tmux-ctl` (full reference: the tmux-orchestrator skill); those names resolve to `<project>-bg`:
```

  Keep the existing `tmux-ctl` bullet list after it. Change "`read <win> feed|watch [lines]` reads its feed or watch pane" to "`read <win> [lines]` reads a window". Add the bullets:
  - `tmux-ctl artifact <path>`: show a file in the board's artifacts panel.
  - `tmux-ctl idea "<text>"`: file an idea for later.
  - `tmux-ctl relay <doc>`: used only by `/handoff`.

- [ ] **Step 5: `worker.md` and `tmux-orchestrator/SKILL.md`.** Find their window table and the rule about `tmux-ctl run tests`. Replace them with the same wording as Steps 3–4: the 4-row table, the `-bg` sentence, and the never-type-into-`shell` sentence. Leave everything else unchanged.

- [ ] **Step 6: Run the Verify greps and report the diff summary** (`diff F.bak-20261016 F` for each file).

```json:metadata
{"files": ["~/.claude/orchestrator.md", "~/.claude/worker.md", "~/.claude/skills/tmux-orchestrator/SKILL.md"], "verifyCommand": "grep -n 'Starting from a handoff\\|Ideas inbox\\|\\[Plan comment\\]\\|-bg' ~/.claude/orchestrator.md", "acceptanceCriteria": ["handoff respawn rule", "ideas rules and Next steps round", "Plan comment handling", "window tables and rule 5 updated in all three files", "no ideas mention in teammate prompts"], "modelTier": "standard", "owner": "relay"}
```

---

### Task 14: Live end-to-end check

**Goal:** Prove the whole flow in a scratch dev session, without touching the user's live session, and write a report.

**Files:**
- Create: `/private/tmp/claude-503/-Users-francisco-ruiz-master-gcp-repo/20f37e48-168c-4854-80f1-56dc95410fe8/scratchpad/e2e-handoff-report.md`

**Acceptance Criteria:**
- [ ] Both suites are green with the installed files (`run-all.zsh`; `unittest discover`)
- [ ] The board is restarted (`tmux-dash stop && tmux-dash`), and `curl` of `/api/state` lists no `-bg` sessions
- [ ] In a scratch repo `~/tmp-e2e-relay` (`git init`), `DEV_NO_ATTACH=1 dev` gives `claude shell` plus the hidden `-bg`
- [ ] **Artifacts:** a plan file written by the scratch lead appears in the sidebar with an agent badge; an edit by a teammate shows a dot and an attributed Changes line; an inline edit saves; an edit made while an agent changed the file shows the conflict view
- [ ] **Comments:** a comment is held while the lead shows a permission prompt and delivered after
- [ ] **Ideas:** an idea added from the board appears in `~/.claude/ideas/tmp-e2e-relay.md` (or `TC_IDEAS_DIR`); `idea:` in chat files it without action
- [ ] **Activity:** a `tmux-ctl run tests` failing run shows ✘ with the summary and a red count; Open live attaches while a `sleep 20` run is going
- [ ] **Handoff:** `/handoff` with two haiku teammates writes a doc with both Team entries, asks the question, and on Yes the `claude` window restarts from the doc, respawns both teammates, and the sidebar shows "Session 2 (current)" while the page keeps Session 1 items; after a page reload only the current items (plus plan and handoff doc) remain
- [ ] **Cleanup:** the scratch session is closed by `kill-session` on its name only, and the user's sessions are untouched (`tmux ls` before/after)

**Verify:** the report lists each criterion with the command or screenshot evidence and PASS/FAIL

**Steps:**

- [ ] **Step 1:** Record `tmux ls`. Run both suites with `tmux-ctl run tests`.
- [ ] **Step 2:** Restart the board and check `/api/state`.
- [ ] **Step 3: Scratch repo and session.**
  - Create the scratch repo, run `DEV_NO_ATTACH=1 dev ~/tmp-e2e-relay`, and start its lead (the `dev` default sends `claude-orchestrator`).
  - The `claude-orchestrator` in that session is a real Claude. Give it small scripted prompts with `tmux-ctl tell`-style typing only through the board's send box, or ask the user to drive the prompts.
  - Every permission prompt it shows is the user's to answer. Tell the lead which window needs them.
- [ ] **Step 4:** Walk each acceptance criterion in Chrome (claude-in-chrome tools, with a GIF of the handoff named `handoff_relay.gif`). Capture evidence.
- [ ] **Step 5:** Close the scratch session and its `-bg` by name, remove `~/tmp-e2e-relay`, and compare `tmux ls`.
- [ ] **Step 6:** Write the report and send its path and the PASS/FAIL summary to the lead.

```json:metadata
{"files": ["/private/tmp/claude-503/-Users-francisco-ruiz-master-gcp-repo/20f37e48-168c-4854-80f1-56dc95410fe8/scratchpad/e2e-handoff-report.md"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/run-all.zsh && cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests", "acceptanceCriteria": ["suites green", "board restarted, no -bg in state", "scratch dev session layout", "artifacts panel flows incl. conflict", "comment held during prompt", "ideas from board and chat", "activity runs, fail count, open live", "handoff with team relayed; page keeps Session 1 until reload", "scratch cleaned, user sessions untouched"], "modelTier": "standard", "owner": "review"}
```

---

## Dependencies

| Task | Blocked by |
| --- | --- |
| 1, 2, 3, 7 | — |
| 4 | 3 |
| 6 | 1 |
| 5 | 2, 3, 4, 6, 7 (only `layout` edits `tmux-ctl`; Task 4 finishes first so the stage files don't overlap) |
| 8 | 1, 2 |
| 9 | 3, 6, 7, 8 |
| 10 | 8, 9 |
| 11 | 10 |
| 12 | 5 |
| 13 | 4, 5 |
| 14 | 1–13 |
