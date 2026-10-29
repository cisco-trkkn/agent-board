# Teams in One Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Several orchestrators ("teams") run parallel PRDs in one project session without colliding: each team gets its own worktree, branch and labelled windows; file claims give early overlap warnings at plan time and at edit time; merges into `main` take turns under a lock; the shared ideas inbox and the shared context file work for all teams; the board shows one section per team; the overseer gets a "claims overlap" event.

**Architecture:** Two new pure-Python modules under `board/` (`claims.py`: the claims registry under an `fcntl` lock, overlap rules, staleness; `mergelock.py`: a per-project `O_EXCL` lock file with dead-holder reclaim) are driven by new `tmux-ctl` subcommands (`claim`, `merge-lock`, `merge-check`) and by a new fail-open PreToolUse hook (`claims-guard.sh`). `bin/dev --team <name>` adds a team to the project session (worktree `.claude/worktrees/team-<name>`, branch `team/<name>`, windows `<name>·claude` / `<name>·plan` tagged `@tc_team` and `@tc_team_root`); `tmux-teammate-window`, `planview`, `relay.py` and the board's `restart_orchestrator` learn to read those tags. `ideas.py` accepts `[~]` (taken up by a team). The board gains `/api/teams` and `/api/claims` and renders team sections; `board/notify.py` (from the overseer plan) gains event 7.

**Tech Stack:** Python 3 stdlib (`unittest`, `fcntl`, `fnmatch`), zsh, bash (hooks), tmux 3.8, git 2.54 (`git merge-tree --write-tree`).

**Spec:** `docs/superpowers/specs/2026-10-28-teams-in-one-project-design.md`

**Preconditions (earlier plans, merged into `main` before this one starts):**
1. `docs/superpowers/plans/2026-10-28-shared-project-context.md` (shared-context): `board/context.py`, `tmux-ctl context`, `claude/plugin/scripts/context-inject.sh`. Task 13 relies on them.
2. `docs/superpowers/plans/2026-10-28-overseer.md` (overseer): `board/overview.py`, `board/notify.py`, `/api/overview`. Task 10 extends them with event 7.

**Workspace:** run in a new worktree `.claude/worktrees/teams-in-one-project` on branch `feat/teams-in-one-project` cut from `main`; no question about working on main.

## Global Constraints

- **Repo:** `~/agent-board`. It is the live install (`~/.local/bin/agent-board` links into it): execute every task in the worktree named above, never in the live checkout. Commands are in `~/agent-board/CLAUDE.md`. Conventional commits with scope (`feat(board): …`, `feat(tmux-ctl): …`, `feat(dev): …`, `feat(plugin): …`, `docs(rules): …`, `docs: …`); every commit step ends with the attribution trailer your harness specifies.
- **Agents' shell is zsh** (gotchas in `~/.claude/CLAUDE.md`): quote `=name` tmux targets (`-t "=$sess:win"`), brace variables before a colon, never name a variable `path`. Scratch tmux servers start with `-L <sock> -f /dev/null`; use `tools/tests/lib.zsh` (`tt_setup`, `tt_teardown`), which does that and sets a scratch `TC_STATE`.
- **Suite verdicts** come from the runner's own summary line (`Ran N tests … OK`, `ALL PASS` / `N FAILED`), or from exit code plus an uncapped failure count (`zsh tools/tests/run-all.zsh > F; echo rc=$?; grep -c '^FAIL' F`). Never from `tail`.
- **Runners:** board tests `python3 -m unittest discover -s board/tests`; zsh tests `zsh tools/tests/run-all.zsh`, which picks up any `tools/tests/test_*.zsh` automatically (`for f in "$dir"/test_*.zsh(N)`, checked in `run-all.zsh`). Long runs go through `tmux-ctl run -t <secs> tests "<cmd>"`.
- **Team names** match `^[A-Za-z0-9_-]+$` and are never `default`. The project's existing lead is the **default team**, registry key `default`, windows `claude` and `plan`, teammate windows `✦ <name>`. A team `<t>` has windows `<t>·claude` and `<t>·plan`, teammate windows `<t>·✦ <name>`. The separator is `·` (U+00B7; `:` is tmux's session:window separator); `✦` is U+2726. Helpers: lead window of team t = `claude` if t == default else `t·claude`; teammate prefix = `✦ ` if default else `t·✦ `.
- **tmux window options** (set by `dev --team`, copied by `tmux-teammate-window`, read by everything else): `@tc_team=<name>`, `@tc_team_root=<worktree path>`. Probed on tmux 3.8 (2026-10-28): `new-window -d -a -t "=proj:<last index>" -n 'auth·claude'` places the window last; `display -p -t '=proj:auth·claude'` targets a dotted name exactly; `set-option -w … @tc_team auth` and `#{@tc_team}` round-trip. `new-window` without an index fills the lowest free index (`0 claude, 1 zz, 2 auth·claude` after killing 1), so grouped placement always uses `-a -t <anchor>`.
- **Team resolution in tools:** `tmux-ctl` sets `TEAM="${TC_TEAM:-$(t show-options -wqv -t "$TMUX_PANE" @tc_team)}"`, empty → `default` (`TC_TEAM` is the test seam, like `TC_SESSION`). The hook does the same with its own tmux call. The project key is `FEEDKEY` (session group, else session name, `-bg` stripped), as every other state file uses.
- **Team worktree and branch:** `<root>/.claude/worktrees/team-<name>` on `team/<name>`, cut from `main` (if the repo has no `main`, from the main checkout's current branch; the plan calls that branch `<base>`). `--close` refuses while `git merge-base --is-ancestor team/<name> <base>` fails, unless `--force`.
- **Claims registry:** `$TC_STATE/claims-<project>.json` = `{"<team>": [{"path": "<repo-relative>", "plan": "<plan path or ->", "ts": <epoch float>, "warned": ["<team>", …]}]}` (`warned` is the list of other teams already told once at edit time). Paths are repo-relative to the project's main checkout (so they line up across worktrees), normalised by `claims.norm`: `./` stripped, `//` collapsed, trailing `/` stripped, `..` segments refused. A path is a file, a directory (covers everything under it) or a glob (`fnmatch` semantics: `*` also crosses `/`, so `*.md` claims every Markdown file; a glob covers a path when it matches the path or one of its parent directories). `claims.overlaps(a, b)` = `covers(a, b) or covers(b, a)`. Writers hold an exclusive `fcntl.lockf` on `claims-<project>.json.lock` and rewrite atomically (`os.replace`), the ideas.py pattern. A claim is **stale** after 7 days (`STALE_DAYS = 7`). Exit code 3 = overlap recorded.
- **Merge lock:** `$TC_STATE/merge-lock-<project>.json` = `{"team", "pid", "ts"}`, created with `O_CREAT|O_EXCL`. `pid` is the lead pane's shell pid (`#{pane_pid}` of the caller's pane, alive as long as the lead's window lives: the lock outlives the `tmux-ctl` call that took it). A holder whose pid is gone is reclaimed. `acquire` waits up to `-t <secs>` (default 600), polling every second.
- **Edit-time hook** `claims-guard.sh` never blocks: it emits `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "<msg>"}, "systemMessage": "<msg>"}` with **no `permissionDecision` key** (an `allow` would skip the user's permission prompt for the edit). Claude Code's hooks reference (`https://code.claude.com/docs/en/hooks`, "PreToolUse decision control", read 2026-10-28) says `additionalContext` is "added to Claude's context alongside the tool result" and is ignored only for `defer`; Task 4 confirms delivery with one headless run. Silent (exit 0, no output) in every other case, including every error.
- **Off switches:** `TC_CLAIMS=0` silences the hook. New hooks follow `claude/plugin/scripts/plan-handoff-guard.sh` and `sdd-call-guard.sh`: a bash wrapper plus `python3 -I`, registered `--scoped` in `claude/plugin/hooks/hooks.json` with timeout 10, listed in `claude/plugin/.claude-plugin/plugin.json`, `docs/INSTALL.md` (line 23's hook list), `docs/ARCHITECTURE.md` (Hooks table), `tools/tests/test_plugin.zsh` (observation #102: every place that lists the hooks lists the new one; `grep -rn sdd-call-guard docs/ README.md claude/ tools/tests/` finds them).
- **Path parameters for test isolation** (observation #101): Python modules resolve state through `tc_env.state_dir()` (`TC_STATE`), ideas through `TC_IDEAS_DIR`, context through `TC_CONTEXT_DIR`; tests set those to temp dirs and put files at the real relative layout (`$TC_STATE/claims-<project>.json`, `$TC_STATE/merge-lock-<project>.json`, `$TC_STATE/runs-<project>.jsonl`, `$TC_STATE/artifacts-<project>.jsonl`). Nothing reads the real `~/.local/state` or the real `TC_STATE` except the read-only checks in Task 13.
- **Fixtures:** hook payloads in the zsh tests are built inline from the real PreToolUse shape (`{"session_id","transcript_path","cwd","hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path","old_string","new_string"}}`; `tools/tests/fixtures/docs-hook/README.md` documents how real payloads were captured on 2026-10-26) and labelled synthetic in a comment. No real session content is copied into the repo (observation #107).
- **Existing checks that must stay green and that these changes touch:** `tools/tests/test_plugin.zsh` (hook list, `/Users/` absence, skill-name resolution), `tools/tests/test_session_closed.zsh` (`mk`/`has` file lists), `tools/tests/test_layout.zsh` (`dev` windows `claude plan`), `tools/tests/test_teammate_window.zsh`, `board/tests/test_relay.py`, `board/tests/test_restart_orchestrator.py`, `board/tests/test_planview.py`, `board/tests/test_ideas*.py`, and every board test that fakes a `list-panes` row for `build_state` (`board/tests/test_usage.py` `label_rows`, `test_poll_efficiency.py`, `test_activity.py`, `test_worktree_board.py`): Task 9 widens that row from 15 to 17 fields.
- **Frontend:** `board/index.html` has no JS test runner; page changes are checked by grep in the task's Verify and by eye in Task 13 (`TMUX_DASH_PORT=7710 python3 board/server.py` from the worktree, never the live `:7700` board).
- **Delivery semantics** for the two consumers in this plan (writing-plans-extras §7): the edit-time note to the claiming lead is sent at most once per (claiming team, editing team, path) — the `warned` list — so repeated edits don't repeat it, and two hooks firing concurrently serialise on the registry lock; the overseer's event 7 is keyed per overlap (`<path>|<other team>`), fired once when the key first appears, not again while it persists, again after it disappears and comes back; it inherits notify.py's 5-minute per-kind-per-project rate limit.

**User decisions (already made):**
- "Use case: parallel features, separate PRDs run at the same time. They should mostly not interact."
- "Isolation: each team works on its own branch in its own worktree."
- "Overlap: claims with early warning, not hard locks and not detection at merge time."
- "Layout: one project session, with each team's windows grouped and labelled by team."

**Planner's choices (spec gaps closed here; see the report):**
- `tmux-ctl tell` accepts lead windows (`claude`, `<t>·claude`) as targets, with the same waiting-on-user refusals it applies to workers; the spec's `tmux-ctl tell <team>·claude` needs it.
- `tmux-ctl merge-check [<branch>]` wraps the spec's "run `git merge-tree --write-tree` against `main` and each other open `team/*` branch and tell that team's lead" in one command (probe 2026-10-28, git 2.54: a conflicting pair exits 1 and prints `CONFLICT (content): Merge conflict in f`; a clean pair exits 0 and prints the tree id).
- `dev --team` requires the project session to exist (plain `dev` first); it never creates the session and adds a team in one go.
- `tmux-ctl idea --claim "<key>"` / `--unclaim "<key>"` mark an idea `[~] … (team <t>)` and back; the `[~]` line keeps the `- [~] YYYY-MM-DD HH:MM · text (team <t>)` shape.
- The claims and merge-lock files are per-project state and are removed by `tmux-session-closed` like the other `TC_STATE` files.
- `caller()` in `tmux-ctl` strips `✦ ` wherever it is, so a team teammate `auth·✦ parse` records runs and lanes as `auth·parse` (lane `tests·auth·parse`); lanes otherwise unchanged, as the spec says.

---

### Task 1: claims registry module

**Goal:** `board/claims.py` owns `$TC_STATE/claims-<project>.json`: add with overlap detection, list with staleness, release, an edit-time `check`, and a CLI, all under the file lock.

**Files:**
- Create: `board/claims.py`
- Create: `board/tests/test_claims.py`

**Acceptance Criteria:**
- [ ] `claims.norm(p)` strips `./` and trailing `/`, collapses `//`, raises `ValueError` on empty, `.` or any `..` segment; `claims.covers(a, b)` and `claims.overlaps(a, b)` implement the Global Constraints rules (exact, directory prefix either way, glob either way with fnmatch semantics, glob matching a parent directory). The 12 cases in Step 2 pass.
- [ ] `claims.add(project, team, paths, plan, now=None)` records every path (even on overlap) and returns the overlaps as `[{"path", "team", "other_path", "plan"}]`, one per (my path, other team's claim) pair; a team's own claims never count; a path already claimed by the same team is re-dated, not duplicated.
- [ ] `claims.list_claims(project, now=None)` returns `{team: [{"path", "plan", "ts", "stale": bool}]}` with `stale` true when `now - ts >= 7*86400`; a missing or corrupt file gives `{}`.
- [ ] `claims.release(project, team, paths=None, all=False)` removes the given normalised paths (or all of the team's) and returns the count; an empty team key is dropped.
- [ ] `claims.check(project, team, path, record=False, now=None)` returns the other teams' claims covering `path` as `[{"team", "path", "plan", "notify": bool}]`; `notify` is true only the first time for that (claiming team, editing team, path) and only with `record=True`, which appends the editing team to the claim's `warned` list under the lock.
- [ ] `claims.overlaps_all(project)` returns every overlapping pair across teams once (`team < other_team` ordering), as `[{"team","path","other_team","other_path","plan","other_plan"}]`, sorted; used by Task 10.
- [ ] `claims.teams(project)` returns the sorted team names with at least one claim. `claims.DEFAULT_TEAM == "default"`, `claims.lead_window(team)` and `claims.mate_prefix(team)` follow Global Constraints.
- [ ] CLI (`python3 -I board/claims.py …`): `add --project P --team T [--plan PLAN] -- PATH…` prints each overlap as `overlap: <path> ↔ team <other> <other_path> (plan <plan>)` and exits 3 when there is one, else prints `claimed N path(s)` and exits 0; `list --project P [--json]` prints `team  path  plan  age` lines with `stale` appended after 7 days (or the dict as JSON); `release --project P --team T (-- PATH… | --all)` prints `released N`; `check --project P --team T [--record] -- PATH` prints the JSON list; `teams --project P`; `overlaps --project P` (JSON). Bad input exits 2 with `claims: <reason>` on stderr.
- [ ] Two concurrent `add` calls (threads or processes) both land: a test runs 2×20 adds in parallel and the file holds all 40 paths.
- [ ] `python3 -I` runs the CLI (the module inserts its own dir on `sys.path` before importing `tc_env`, like `relay.py`).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_claims.py' -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_claims.py`. Isolation: `setUp` sets `os.environ["TC_STATE"]` to a `TemporaryDirectory` (the module's `claims_path` reads `tc_env.state_dir()` at call time) and `tearDown` pops it. Tests, each with the mutation that must fail it:
  - `test_norm_and_covers` — the table in Step 2. Mutation: drop the parent-directory loop in `covers` → the `tools/tests/test_*.zsh` vs `tools/tests` case fails.
  - `test_add_then_list` — two teams, three paths; `list_claims` shows them with `stale False`. Mutation: write before lock release → still passes (not the target); mutation that fails it: drop the `ts` field.
  - `test_overlap_exact_dir_glob_reported_and_recorded` — team `a` claims `board/claims.py`, `docs`, `tools/tests/test_*.zsh`; team `b` adds `board/claims.py`, `docs/x.md`, `tools/tests/test_teams.zsh` → three overlaps returned AND all three recorded under `b`. Mutation: `return` before writing on overlap → fails.
  - `test_own_claims_never_overlap` — team `a` adds the same path twice → no overlap, one entry (re-dated). Mutation: remove the `team != other` filter → fails.
  - `test_release_paths_and_all`. Mutation: compare un-normalised paths → `release(..., ["./docs/"])` fails.
  - `test_stale_after_seven_days` — `now=ts + 7*86400` → stale; `now=ts + 7*86400 - 1` → not. Mutation: `>` instead of `>=` → fails.
  - `test_check_notify_once_with_record` — first `check(record=True)` → `notify True`; second → `notify False`; without `record` the flag never flips. Mutation: skip the `warned` append → second call fails.
  - `test_overlaps_all_pairs_once`. Mutation: emit both orders → count doubles, fails.
  - `test_concurrent_adds_both_land` — `ThreadPoolExecutor(2)` running 20 adds each. Mutation: remove `fcntl.lockf` → flaky loss (run 20× in the RED step to see at least one loss, or assert on a deliberately slowed `_rewrite` with `time.sleep(0.01)` inside the critical section: the mutation then loses writes deterministically).
  - `test_cli_add_exit_3_and_messages`, `test_cli_list_json`, `test_cli_release_all`, `test_cli_check_json`, `test_cli_bad_path_exit_2` — through `subprocess.run([sys.executable, "-I", str(CLAIMS)], env={**os.environ, "TC_STATE": tmp})`.

- [ ] **Step 2: RED.** `python3 -m unittest discover -s board/tests -p 'test_claims.py' -v` → errors on `import claims`. The overlap core the module must contain (run once by the plan's author on 2026-10-28 against the 12 cases: `overlap cases: 12 wrong: []`):

```python
import fnmatch, re
GLOB_CHARS = set("*?[")

def norm(p):
    p = str(p).strip()
    while p.startswith("./"):
        p = p[2:]
    p = re.sub(r"/+", "/", p).rstrip("/")
    if not p or p == "." or ".." in p.split("/"):
        raise ValueError(f"bad path {p!r}")
    return p

def is_glob(p):
    return any(c in GLOB_CHARS for c in p)

def covers(a, b):
    """claim a covers path b: same path, b inside directory a, or glob a matching b or one of b's parent dirs."""
    if a == b or b.startswith(a + "/"):
        return True
    if is_glob(a):
        parts = b.split("/")
        return any(fnmatch.fnmatchcase("/".join(parts[:i]), a) for i in range(1, len(parts) + 1))
    return False

def overlaps(a, b):
    return covers(a, b) or covers(b, a)

# (a, b, expected): exact, dir either way, glob either way, glob on a parent, non-overlaps
CASES = [("board/claims.py", "board/claims.py", True), ("board", "board/claims.py", True), ("board/claims.py", "board", True),
         ("board/*.py", "board/claims.py", True), ("board/claims.py", "board/*.py", True), ("docs/*", "docs/a/b.md", True),
         ("board/tests", "board/claims.py", False), ("board/claims.py", "board/claims_x.py", False), ("bo", "board/x", False),
         ("*.md", "docs/a.md", True), ("tools/tests/test_*.zsh", "tools/tests/test_teams.zsh", True), ("tools/tests", "tools/tests/test_*.zsh", True)]
```

- [ ] **Step 3: Implement** `board/claims.py`. Header like `relay.py` (docstring with the file format and CLI, `sys.path.insert(0, …)`, `import tc_env`). Project names are validated with the same regex as `ideas.ideas_path` (`[A-Za-z0-9_-][A-Za-z0-9._-]*`, not `.`/`..`). Shape:

```python
STALE_DAYS = 7
DEFAULT_TEAM = "default"

def lead_window(team): return "claude" if team == DEFAULT_TEAM else f"{team}·claude"
def mate_prefix(team): return "✦ " if team == DEFAULT_TEAM else f"{team}·✦ "
def claims_path(project): ...  # tc_env.state_dir() / f"claims-{project}.json"
def load(project): ...  # {} on missing/corrupt; drops entries without a str path
@contextmanager
def _locked(project): ...  # mkdir parent; open(f"{p}.lock","w") + fcntl.lockf(LOCK_EX); yield data dict; write tmp + os.replace
def add(project, team, paths, plan="-", now=None): ...
def list_claims(project, now=None): ...
def release(project, team, paths=None, all=False): ...
def check(project, team, path, record=False, now=None): ...
def overlaps_all(project): ...
def teams(project): ...
def main(argv=None): ...  # argparse subcommands add/list/release/check/teams/overlaps; ValueError -> "claims: …" exit 2
```

- [ ] **Step 4: GREEN**, then run each named mutation once, confirm its test fails, revert.

- [ ] **Step 5: Commit** `feat(board): claims registry with overlap detection, staleness and lock`.

```json:metadata
{"files": ["board/claims.py", "board/tests/test_claims.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_claims.py' -v", "acceptanceCriteria": ["norm/covers/overlaps pass the 12 cases", "add records on overlap and returns the pairs; own claims never overlap", "list marks stale at 7 days", "release by paths and --all", "check notifies once with record", "overlaps_all lists each pair once", "CLI exit codes 0/2/3 and messages", "concurrent adds both land"], "modelTier": "standard"}
```

### Task 2: `tmux-ctl claim`, team resolution, lead `tell`

**Goal:** `tmux-ctl` knows its team (`@tc_team`, `TC_TEAM` seam), exposes `claim add|list|release`, notifies the other team's lead on overlap, and `tell` can target lead windows.

**Files:**
- Modify: `bin/tmux-ctl` (help text lines 2–31; `caller()`; new `TEAM` resolution after `FEEDKEY`; `tell`; new `claim` case)
- Create: `tools/tests/test_ctl_claims.zsh`

**Acceptance Criteria:**
- [ ] After `FEEDKEY` is computed: `TEAM="${TC_TEAM:-$(t show-options -wqv -t "${TMUX_PANE:-=$SESSION:}" @tc_team 2>/dev/null)}"; TEAM="${TEAM:-default}"`; helper `lead_win() { [[ "$1" == default ]] && print -r -- claude || print -r -- "$1·claude" }`; helper `is_lead_win() { [[ "$1" == claude || "$1" == *·claude ]] }`.
- [ ] `tmux-ctl claim add [--plan P] <paths…>` runs `python3 -I "$REPO/board/claims.py" add --project "$FEEDKEY" --team "$TEAM" --plan "${plan:--}" -- "$@"`, prints its output, and for every overlap line also runs `"$TC_SELF" tell "$(lead_win <other>)" "[Claims] team $TEAM claimed <path> (plan P), which you hold (<other_path>, plan <theirs>): settle it by message, or bring it to the user"` (a failed `tell`, e.g. no such window, prints a `tmux-ctl: warning: could not tell …` line and does not change the exit code); exits with the Python exit code (3 on overlap). `claim list [--json]` and `claim release (<paths…> | --all)` pass through; `claim` with no or an unknown verb dies with usage (exit 2).
- [ ] `tell <win>` accepts `is_agent "$win" || is_lead_win "$win"`; the existing refusals (exited, bell, visible prompt) apply to both.
- [ ] `caller()` strips `✦ ` wherever it appears (`pw="${pw//✦ /}"`), so `auth·✦ parse` records as `auth·parse`.
- [ ] `tmux-ctl help` lists `claim add [--plan P] <paths…> | list [--json] | release (<paths…> | --all)` with one line on exit 3.
- [ ] Test `tools/tests/test_ctl_claims.zsh` (scratch server via `lib.zsh`; the lead stand-ins are windows running `sleep 600`, which `tell` types into because they are busy and show no prompt): `TC_TEAM=a $C claim add --plan pa board/x.py docs` exits 0 and `claims-tt.json` holds them; `TC_TEAM=b $C claim add --plan pb docs/y.md` exits 3, prints `overlap: docs/y.md ↔ team a docs (plan pa)`, and `tt capture-pane -p -t '=tt:a·claude'` contains `[Claims] team b claimed docs/y.md`; `claim list` shows both teams; `TC_TEAM=b $C claim release --all` prints `released 1`; `tell` on a `sleep` window named `a·claude` types the text (capture shows it) and `tell` on a non-lead non-agent window `other` is refused; `claim bogus` exits 2; `help` lists `claim`.

**Verify:** `zsh tools/tests/test_ctl_claims.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the zsh test** (`source "${0:A:h}/lib.zsh"`, `C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"`, `tt_setup claude`; `tt new-window -d -t '=tt:' -n 'a·claude' 'sleep 600'`, same for `b·claude` and `other`; `tt set-option -w -t '=tt:a·claude' @tc_team a`). Use `check "…" test …` lines as the other `test_ctl_*.zsh` files do. Mutation for the notify check: comment out the `tell` loop → the capture check fails. Mutation for `tell` acceptance: restore `is_agent` only → the `a·claude` tell check fails.
- [ ] **Step 2: RED**: run it; `claim` dies with `unknown command`.
- [ ] **Step 3: Implement** in `bin/tmux-ctl`: `REPO="${TC_SELF:h:h}"`; the `claim)` case:

```zsh
  claim)
    verb="$1"; shift 2>/dev/null
    case "$verb" in
      add)
        plan=""; [[ "$1" == --plan && -n "$2" ]] && { plan="$2"; shift 2 }
        [[ -n "$*" ]] || die "usage: tmux-ctl claim add [--plan P] <paths…>"
        out="$(python3 -I "$REPO/board/claims.py" add --project "$FEEDKEY" --team "$TEAM" --plan "${plan:--}" -- "$@" 2>&1)"; rc=$?
        print -r -- "$out"
        if (( rc == 3 )); then
          for line in ${(f)out}; do
            [[ "$line" =~ '^overlap: (.+) ↔ team ([A-Za-z0-9_-]+) (.+) \(plan (.*)\)$' ]] || continue
            "$TC_SELF" tell "$(lead_win "$match[2]")" "[Claims] team $TEAM claimed $match[1] (plan ${plan:--}), which you hold ($match[3], plan $match[4]): settle it by message, or bring it to the user" 2>/dev/null ||
              print -u2 "tmux-ctl: warning: could not tell team $match[2]'s lead ($(lead_win "$match[2]")) about $match[1]"
          done
        fi
        exit $rc ;;
      list)    exec python3 -I "$REPO/board/claims.py" list --project "$FEEDKEY" "$@" ;;
      release) [[ -n "$*" ]] || die "usage: tmux-ctl claim release (<paths…> | --all)"
               if [[ "$1" == --all ]]; then exec python3 -I "$REPO/board/claims.py" release --project "$FEEDKEY" --team "$TEAM" --all
               else exec python3 -I "$REPO/board/claims.py" release --project "$FEEDKEY" --team "$TEAM" -- "$@"; fi ;;
      *) die "usage: tmux-ctl claim add [--plan P] <paths…> | list [--json] | release (<paths…> | --all)" ;;
    esac ;;
```

  `tell`: replace `is_agent "$name" || die "'$name' is not a worker agent window"` with `is_agent "$name" || is_lead_win "$name" || die "'$name' is neither a worker agent window nor a lead window (claude, <team>·claude)"`. The `tell` call from `claim add` runs `tmux-ctl` recursively; `TC_SESSION`/`TMUX_PANE` are inherited, so it targets the same session.
- [ ] **Step 4: GREEN**; run `zsh tools/tests/test_ctl_relay.zsh` and `test_ctl_opts.zsh` too (they exercise `tell`/`help`).
- [ ] **Step 5: Commit** `feat(tmux-ctl): claim subcommand, team resolution, tell to lead windows`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_claims.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_claims.zsh", "acceptanceCriteria": ["TEAM from @tc_team or TC_TEAM, default otherwise", "claim add/list/release pass through with exit codes; overlap notifies the other lead via tell", "tell accepts lead windows", "caller strips ✦ anywhere", "help lists claim"], "modelTier": "standard"}
```

### Task 3: merge lock, merge-check, session-closed cleanup

**Goal:** `board/mergelock.py` plus `tmux-ctl merge-lock acquire|release|status` and `tmux-ctl merge-check`, and the claims/merge-lock files are removed when the project session closes.

**Files:**
- Create: `board/mergelock.py`
- Create: `board/tests/test_mergelock.py`
- Modify: `bin/tmux-ctl` (help; new `merge-lock` and `merge-check` cases)
- Modify: `bin/tmux-session-closed` (the `rm -f` list)
- Modify: `tools/tests/test_session_closed.zsh` (`mk` and `has` lists)
- Create: `tools/tests/test_merge_lock.zsh`

**Acceptance Criteria:**
- [ ] `mergelock.acquire(project, team, pid, timeout=600, now=None, sleep=time.sleep, clock=time.monotonic, alive=pid_alive)` creates `$TC_STATE/merge-lock-<project>.json` with `O_CREAT|O_EXCL` holding `{"team","pid","ts"}` and returns it; if the file exists and `alive(holder pid)` is false it removes it and retries (reclaim); if the same team and pid hold it, it refreshes `ts` (re-entrant); otherwise it polls every `sleep(1)` until `clock()` passes `timeout`, then raises `mergelock.Held(holder)`. `pid_alive` uses `os.kill(pid, 0)` (`ProcessLookupError` → False, `PermissionError` → True).
- [ ] `mergelock.release(project, team, force=False)` removes the file when `holder.team == team` (or `force`), returns True; returns False when free; raises `mergelock.NotHolder` when another team holds it and not `force`. `mergelock.status(project, alive=pid_alive)` → `{"held": bool, "holder": dict|None, "alive": bool}`.
- [ ] CLI: `acquire --project P --team T --pid N [-t SECS]` exits 0 printing `merge-lock: held by team T (pid N)`, or 1 printing `merge-lock: held by team X (pid Y) since <ISO>; gave up after S s`; `release --project P --team T [--force]` exits 0 (`released` / `was free`) or 2 (`held by team X; --force to take it`); `status --project P [--json]`.
- [ ] `tmux-ctl merge-lock acquire [-t secs]` passes `--pid "$(t display -p -t "${TMUX_PANE:-=$SESSION:}" '#{pane_pid}')"`; `release [--force]`, `status` pass through; project `FEEDKEY`, team `TEAM`.
- [ ] `tmux-ctl merge-check [<branch>]` (default branch `team/$TEAM`, or the current branch for the default team): for `<base>` (`main`, else the main checkout's current branch) and every other `team/*` branch (`git branch --list 'team/*'` minus `<branch>`), runs `git merge-tree --write-tree --name-only <other> <branch>`; on exit 1 prints `conflict with <other>: <files>` (the `CONFLICT` lines' file names) and, for a `team/<t>` other, runs `"$TC_SELF" tell "$(lead_win <t>)" "[Merge] team $TEAM's branch <branch> conflicts with yours in <files>"`; prints `no conflicts` and exits 0 when clean, exits 1 when any conflict.
- [ ] `bin/tmux-session-closed` also removes `claims-$n.json`, `claims-$n.json.lock` and `merge-lock-$n.json`; `tools/tests/test_session_closed.zsh` `mk` creates and `has` checks those names too (so "other project untouched" and "project state removed" cover them).
- [ ] Unit tests: second acquire by another team with a live pid reports the holder and times out (fake clock, no real sleep); release frees it; a holder with a dead pid is reclaimed (`alive=lambda p: False`); same team/pid is re-entrant; `NotHolder` on a foreign release; `status` shape; CLI exit codes via `subprocess`.
- [ ] zsh test: two scratch windows with different `@tc_team`; `TC_TEAM=a $C merge-lock acquire` → 0; `TC_TEAM=b $C merge-lock acquire -t 2` → 1 within ~3 s and names team a; `TC_TEAM=b $C merge-lock release` → 2; `TC_TEAM=a $C merge-lock release` → 0; a lock file written by hand with `"pid": 999999` (not a live pid: check with `kill -0`) is reclaimed by `acquire`; `merge-check` in a scratch repo with `main`, `team/a` (conflicting edit to `f`) and `team/b` (clean) run from team b's worktree reports `conflict with team/a` and exits 1, and types `[Merge]` into `a·claude`; with the conflict removed it prints `no conflicts`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_mergelock.py' -v && zsh tools/tests/test_merge_lock.zsh && zsh tools/tests/test_session_closed.zsh` → `OK`, `ALL PASS`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Unit tests first** (`TC_STATE` temp dir; injected `sleep`/`clock`/`alive`). Mutations: drop the reclaim branch → `test_dead_holder_reclaimed` fails; compare team only (not pid) in the re-entrant check → `test_same_team_other_pid_waits` fails; `release` without the team check → `test_foreign_release_refused` fails.
- [ ] **Step 2: Implement `board/mergelock.py`** (`sys.path.insert`, `import tc_env`; `Held(Exception)` carries `.holder`; `NotHolder(Exception)`); `acquire` loop:

```python
def acquire(project, team, pid, timeout=600, now=None, sleep=time.sleep, clock=time.monotonic, alive=pid_alive):
    p = lock_path(project); p.parent.mkdir(parents=True, exist_ok=True)
    deadline = clock() + timeout
    while True:
        rec = {"team": team, "pid": int(pid), "ts": now if now is not None else time.time()}
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            h = holder(project)
            if h is None or not alive(h.get("pid", 0)):
                try: p.unlink()
                except FileNotFoundError: pass
                continue
            if h.get("team") == team and h.get("pid") == int(pid):
                p.write_text(json.dumps(rec)); return rec
            if clock() >= deadline:
                raise Held(h)
            sleep(1); continue
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(rec))
        return rec
```

- [ ] **Step 3: `tmux-ctl`** cases `merge-lock)` and `merge-check)`; `merge-check` loop:

```zsh
  merge-check)
    root="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || die "run inside the project's git repo"; root="${root:h}"
    br="${1:-$( [[ "$TEAM" == default ]] && git branch --show-current || print -r -- "team/$TEAM" )}"
    base=main; git -C "$root" show-ref --verify --quiet refs/heads/main || base="$(git -C "$root" branch --show-current)"
    others=("$base" ${(f)"$(git -C "$root" branch --list 'team/*' --format='%(refname:short)')"})
    rc=0
    for o in $others; do
      [[ "$o" == "$br" ]] && continue
      out="$(git -C "$root" merge-tree --write-tree --name-only "$o" "$br" 2>&1)" && continue
      files="$(print -r -- "$out" | grep -oE 'Merge conflict in .*' | sed 's/Merge conflict in //' | paste -sd, -)"
      print -r -- "conflict with $o: ${files:-see git merge-tree}"; rc=1
      if [[ "$o" == team/* ]]; then
        "$TC_SELF" tell "$(lead_win "${o#team/}")" "[Merge] team $TEAM's branch $br conflicts with yours in ${files:-some files}" 2>/dev/null || print -u2 "tmux-ctl: warning: could not tell team ${o#team/}'s lead"
      fi
    done
    (( rc )) || print "no conflicts"
    exit $rc ;;
```

  Note (`git -C` probe 2026-10-28): `--name-only` prints the tree id, a blank line, then the `CONFLICT (content): Merge conflict in f` lines, and exits 1 on conflict.
- [ ] **Step 4: `tmux-session-closed` and its test.** Add to the `rm -f` list; in `test_session_closed.zsh` add `claims-$p.json merge-lock-$p.json` to `mk`'s loop and `-o -e "$TC_STATE/claims-$1.json" -o -e "$TC_STATE/merge-lock-$1.json"` to `has`.
- [ ] **Step 5: zsh test, GREEN, mutations, commit** `feat(tmux-ctl): merge-lock and merge-check; claims and lock files cleaned on session close`.

```json:metadata
{"files": ["board/mergelock.py", "board/tests/test_mergelock.py", "bin/tmux-ctl", "bin/tmux-session-closed", "tools/tests/test_session_closed.zsh", "tools/tests/test_merge_lock.zsh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_mergelock.py' -v && zsh tools/tests/test_merge_lock.zsh && zsh tools/tests/test_session_closed.zsh", "acceptanceCriteria": ["O_EXCL lock with {team,pid,ts}; dead-pid reclaim; re-entrant for same team+pid; timeout raises Held", "release only by holder unless --force", "tmux-ctl merge-lock passes the lead pane pid", "merge-check runs merge-tree against base and every other team branch, tells conflicting leads, exits 1 on conflict", "session-closed removes claims and merge-lock files"], "modelTier": "standard"}
```

### Task 4: `claims-guard.sh` edit-time hook

**Goal:** A fail-open PreToolUse(Edit|Write|MultiEdit) hook that tells the agent when its target path is claimed by another team and sends the claiming lead a one-line note once.

**Files:**
- Create: `claude/plugin/scripts/claims-guard.sh`
- Modify: `claude/plugin/hooks/hooks.json` (new PreToolUse entry, matcher `Edit|Write|MultiEdit`, `--scoped`, timeout 10)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (description names `claims-guard`)
- Modify: `tools/tests/test_plugin.zsh` (a check like the `sdd-call-guard` one)
- Create: `tools/tests/test_claims_guard.zsh`

**Acceptance Criteria:**
- [ ] Bash wrapper + `python3 -I`, `--scoped` accepted and ignored, `TC_CLAIMS=0` → `cat >/dev/null; exit 0`. Every error path exits 0 with no output (missing `$TMUX`/`$TMUX_PANE`, tmux unreachable, file outside a git repo, claims.py failing, malformed JSON).
- [ ] Resolves: `fp` = `tool_input.file_path` for `tool_name ∈ {Edit, Write, MultiEdit}` (else silent); tmux binary `${TC_TMUX:-$HOME/.local/bin/tmux if executable, else tmux}` with `-S "${TMUX%%,*}"`; `proj` = `#{?session_group,#{session_group},#{session_name}}` of `$TMUX_PANE` with `-bg` stripped; `team` = `#{@tc_team}` of that pane, empty → `default`; `rel` = `fp` relative to `git -C "$(dirname "$fp")" rev-parse --show-toplevel` (not under it → silent).
- [ ] Runs `python3 -I "$REPO/board/claims.py" check --project "$proj" --team "$team" --record -- "$rel"` (`REPO` = three dirs above the script). Empty result (`[]`) → silent: this covers the agent's own claims, unclaimed paths and a project with one team (no other team has claims).
- [ ] On hits: prints the JSON from Global Constraints with message `<rel> is claimed by team <other> (plan <plan>); tell your lead before continuing` (first hit; further hits appended as `; also team <x> (plan <p>)`), **no `permissionDecision`**, exit 0. For every hit with `notify: true`, runs `"$REPO/bin/tmux-ctl" tell "<other's lead window>" "[Claims] team <team> is editing <rel>, which you claimed (plan <plan>)"` (output discarded, failure ignored).
- [ ] `hooks.json` gains `{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/claims-guard.sh\" --scoped", "timeout": 10}]}` under `PreToolUse`; `test_plugin.zsh` gets `check "hooks.json registers claims-guard on PreToolUse Edit|Write|MultiEdit, --scoped, timeout 10"` modelled on the `sdd-call-guard` check; `plugin.json`'s description lists it.
- [ ] `test_claims_guard.zsh` (scratch server; `TC_STATE` from `tt_setup`; a scratch git repo `$TT_DIR/repo` with `main`; a window `b·claude` running `sleep 600`; the hook run with `TMUX`/`TMUX_PANE` of the `tt:claude` pane, whose `@tc_team` is set per case; payloads built inline, synthetic, real shape): warns on another team's path and lets the edit through (exit 0, stdout JSON whose `additionalContext` names the path and team, no `permissionDecision` key) and `b·claude`'s capture shows `[Claims] team a is editing`; a second run on the same path warns again but types nothing new (capture count unchanged); silent on own path; silent on an unclaimed path; silent when only one team has claims; silent with `TC_CLAIMS=0`; exit 0 and silent on `not json`, on a payload without `file_path`, on a path outside any repo, and with `TMUX` unset.
- [ ] One real run: from the worktree, `claude -p --model haiku --plugin-dir "$PWD/claude/plugin" --permission-mode bypassPermissions` in a scratch git dir whose tmux pane has `@tc_team` set (run it with `tmux-ctl run` from a scratch session, or set `TC_TEAM`-style env is NOT read by the hook: it needs a real pane with `@tc_team`), with a scratch `TC_STATE` seeded with a foreign claim on `probe.txt`, prompt: "Use the Write tool to write hi into ./probe.txt, then reply with the exact text of any additional context you received, or NO-CONTEXT." The reply quotes `is claimed by team`. If the harness classifier refuses the headless run (the plan's author was refused on 2026-10-28 when trying the same probe), record that in the task report and keep the zsh checks as the evidence; do not add `permissionDecision` to work around it.

**Verify:** `zsh tools/tests/test_claims_guard.zsh && zsh tools/tests/test_plugin.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: Write `test_claims_guard.zsh`.** Payload helper (synthetic, shape from `tools/tests/fixtures/docs-hook/README.md`'s real PostToolUse captures, PreToolUse adds `tool_input` only):

```zsh
payload() { python3 -c 'import json,sys; print(json.dumps({"session_id":"s","transcript_path":"/tmp/t.jsonl","cwd":sys.argv[2],"hook_event_name":"PreToolUse","tool_name":sys.argv[1],"tool_input":{"file_path":sys.argv[3],"old_string":"a","new_string":"b"}}))' "$@"; }
run_hook() { payload "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
silent() { run_hook "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }
warned() { run_hook "$@"; [[ $rc == 0 ]] && print -r -- "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; assert "permissionDecision" not in d; assert "claimed by team b" in d["additionalContext"]'; }
```

  Seed claims with `python3 -I "$TT_REPO/board/claims.py" add --project tt --team b --plan pb -- src/x.py` (the hook's `proj` is `tt`, from `tt_setup`'s session). Mutations: drop the `--record` flag → the "types nothing new on the second run" check still passes but the first-run capture check fails only if `tell` is also dropped; name the mutation that fails each: remove the `tell` call → "capture shows [Claims]" fails; remove the `[[ "$res" != "[]" ]]` guard → "silent on unclaimed" fails (it would emit an empty message); remove the `TC_CLAIMS` line → "silent with TC_CLAIMS=0" fails.
- [ ] **Step 2: RED** (hook missing → `silent` checks pass trivially, warn checks fail: that is the RED).
- [ ] **Step 3: Implement the hook:**

```bash
#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit): when the target path is claimed by another team (board/claims.py), tell the agent
# through additionalContext and the claiming team's lead once through `tmux-ctl tell`. Never blocks: no permissionDecision
# (an "allow" would skip the user's permission prompt). Silent for own/unclaimed paths, one-team projects, TC_CLAIMS=0 and
# on any error. --scoped (the plugin registration) is accepted and changes nothing.
[[ "$TC_CLAIMS" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 0
REPO="$(cd "$HERE/../../.." && pwd -P)" || exit 0
fp=$(printf '%s' "$input" | python3 -I -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(((d.get("tool_input") or {}).get("file_path") or "") if d.get("tool_name") in ("Edit", "Write", "MultiEdit") else "")
except Exception:
    print("")' 2>/dev/null) || exit 0
[[ -n "$fp" ]] || exit 0
TMUXBIN="${TC_TMUX:-}"; [[ -z "$TMUXBIN" && -x "$HOME/.local/bin/tmux" ]] && TMUXBIN="$HOME/.local/bin/tmux"; TMUXBIN="${TMUXBIN:-tmux}"
info=$("$TMUXBIN" -S "${TMUX%%,*}" display -p -t "$TMUX_PANE" $'#{?session_group,#{session_group},#{session_name}}\t#{@tc_team}' 2>/dev/null) || exit 0
proj="${info%%$'\t'*}"; team="${info#*$'\t'}"; proj="${proj%-bg}"; team="${team:-default}"
top=$(git -C "$(dirname "$fp")" rev-parse --show-toplevel 2>/dev/null) || exit 0
rel="${fp#"$top"/}"; [[ "$rel" != "$fp" && -n "$rel" ]] || exit 0
res=$(python3 -I "$REPO/board/claims.py" check --project "$proj" --team "$team" --record -- "$rel" 2>/dev/null) || exit 0
[[ -n "$res" && "$res" != "[]" ]] || exit 0
printf '%s' "$res" | python3 -I -c 'import json,sys
hits = json.load(sys.stdin); rel, team = sys.argv[1], sys.argv[2]
msg = f"{rel} is claimed by team {hits[0][\"team\"]} (plan {hits[0][\"plan\"]}); tell your lead before continuing"
msg += "".join(f"; also team {h[\"team\"]} (plan {h[\"plan\"]})" for h in hits[1:])
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}, "systemMessage": msg}))
for h in hits:
    if h.get("notify"):
        print(h["team"], file=sys.stderr)' "$rel" "$team" 2>"$HERE/../../../.claims-notify.$$" || exit 0
while read -r other; do
  [[ -n "$other" ]] || continue
  lead=claude; [[ "$other" != default ]] && lead="$other·claude"
  "$REPO/bin/tmux-ctl" tell "$lead" "[Claims] team $team is editing $rel, which you claimed" >/dev/null 2>&1 || true
done < "$HERE/../../../.claims-notify.$$"
rm -f "$HERE/../../../.claims-notify.$$"
exit 0
```

  Replace the temp-file hand-off with a `mktemp` under `${TMPDIR:-/tmp}` (never write into the repo): `nf=$(mktemp "${TMPDIR:-/tmp}/claims-notify.XXXXXX") || exit 0`, and include the plan name in the `[Claims]` line by printing `team<TAB>plan` on stderr. Keep the JSON on stdout only.
- [ ] **Step 4: Register** in `hooks.json` and `plugin.json`; add the `test_plugin.zsh` check; GREEN; run the headless probe (AC) once from a scratch `dev`-style session and quote the reply in the task report.
- [ ] **Step 5: Commit** `feat(plugin): claims-guard hook warns on another team's claimed path`.

```json:metadata
{"files": ["claude/plugin/scripts/claims-guard.sh", "claude/plugin/hooks/hooks.json", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh", "tools/tests/test_claims_guard.zsh"], "verifyCommand": "zsh tools/tests/test_claims_guard.zsh && zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["warns via additionalContext with no permissionDecision; exit 0", "notifies the claiming lead once per path (warned list)", "silent on own/unclaimed paths, one team, TC_CLAIMS=0, garbage input, no tmux", "registered --scoped timeout 10; plugin.json and test_plugin.zsh list it", "one real headless run quoted, or the refusal recorded"], "modelTier": "standard"}
```

### Task 5: `dev --team <name>` and `--close`

**Goal:** `dev [dir] --team <name>` adds a team (worktree, branch, grouped windows, options) to an existing project session; `--close [--force]` releases its claims and lock, closes its windows and leaves the worktree to the merged-worktree sweep; `tmux-dev-layout` re-creates a missing `<t>·plan`.

**Files:**
- Modify: `bin/dev` (argument parsing; team add/close; help lines 2–3)
- Modify: `bin/tmux-dev-layout` (ensure `<t>·plan` next to each `<t>·claude`)
- Modify: `bin/tmux-plan` (pass extra args through: `exec python3 -I "${0:A:h:h}/board/planview.py" watch "$1" --root "$2" "${@:3}"`)
- Create: `tools/tests/test_teams.zsh`

**Acceptance Criteria:**
- [ ] Parsing: `--team <name>`, `--close`, `--force` are removed from `$@` before `dir="${1:-$PWD}"`; a name not matching `^[A-Za-z0-9_-]+$` or equal to `default` → `dev: team name …` on stderr, exit 2; `--close`/`--force` without `--team` → usage, exit 2. `dev --help` documents `dev [dir] --team <name> [--close [--force]]`.
- [ ] With `--team` the session must exist (`tc_tmux has-session -t "=$name"`), else `dev: no session '<name>': run dev first` exit 2.
- [ ] Add: `wt="$root/.claude/worktrees/team-$team"`, `br="team/$team"`, `base` per Global Constraints; `git -C "$root" worktree add "$wt" "$br"` if the branch exists, else `… -b "$br" "$base"`; skipped when `$wt` is already a directory. Windows: if `<t>·claude` is missing, `new-window -d -a -t "=${name}:<last index>" -n "$team·claude" -c "$wt"`, options `@tc_team`, `@tc_team_root`, `automatic-rename off`, then `send-keys "${DEV_CLAUDE_CMD:-<bin>/claude-orchestrator}" Enter`; if `<t>·plan` is missing, `new-window -d -a -t "=${name}:$team·claude" -n "$team·plan" -c "$wt" "<bin>/tmux-plan <name> <wt> --lead-window <t>·claude --mate-prefix '<t>·✦ '"` with the same options. Idempotent: a second `dev --team auth` adds no window. Prints `team 'auth' ready in session '<name>' (worktree <wt>)`; then attaches as plain `dev` does (`DEV_NO_ATTACH` prints and exits), selecting `<t>·claude`.
- [ ] Close: refuses (`dev: team/<t> is not merged into <base>; dev --team <t> --close --force closes it anyway`, exit 2) unless merged or `--force`; then `python3 -I <repo>/board/claims.py release --project "$name" --team "$team" --all`, `python3 -I <repo>/board/mergelock.py release --project "$name" --team "$team" || true` (frees it only if this team holds it), kills every window of `=$name` whose `@tc_team` equals the team and every window of `=$name-bg` named `*·$team·*` (lanes), runs `<repo>/bin/agent-worktrees sweep --only "$wt" "$root" >/dev/null 2>&1 || true`, prints `closed team '<t>' (claims released; worktree <wt> is removed by the merged-worktree sweep when clean)`, exit 0. Never `git worktree remove` directly (the sweep's safety rules decide).
- [ ] `tmux-dev-layout`: for each window named `<t>·claude` with `@tc_team=<t>`, if `<t>·plan` is missing, create it after `<t>·claude` with the same command and options (root from `@tc_team_root`, else `$root`). Single-team sessions are unchanged (`test_layout.zsh` stays green).
- [ ] `test_teams.zsh` (scratch server; `$TT_DIR/proj` is a git repo with branch `main` and one commit; leads are `DEV_CLAUDE_CMD='sleep 600'`; `TC_LAYOUT=$TT_REPO/bin/tmux-dev-layout`): `dev proj` then `dev proj --team auth` → worktree dir exists, `git -C proj branch --list team/auth` non-empty, windows `auth·claude` and `auth·plan` exist with consecutive indices after `plan`, both carry `@tc_team=auth` and `@tc_team_root=<wt>`, the lead pane's `#{pane_current_path}` is `<wt>`, `auth·plan`'s `#{pane_start_command}` contains `--lead-window auth·claude`; second add is idempotent (window count unchanged); kill `auth·plan`, run the layout → it is back right after `auth·claude`; bad name exits 2; `--close` without a merge exits 2 and windows stay; after a commit on `team/auth` and `git -C proj merge team/auth`, `--close` exits 0, windows are gone, `claims-proj.json` (seeded with an `auth` claim beforehand) no longer has `auth`; a second team `b` with an unmerged commit closes with `--force`; leak check: the number of `sleep 600` processes (`ps -ax -o command | grep -c '[s]leep 600'`) after `tt_teardown`-equivalent `tt kill-session -t '=proj'` returns to the count taken before the test started.

**Verify:** `zsh tools/tests/test_teams.zsh && zsh tools/tests/test_layout.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: Write `test_teams.zsh`** (pattern: `tools/tests/test_layout.zsh`'s `dev` block; `before="$(ps -ax -o command | grep -c '[s]leep 600')"` at the top). Mutations: remove the `-a -t <last>` placement → "consecutive indices after plan" fails; remove the merged check → "close refused unmerged" fails; remove the claims release → "no auth in claims-proj.json" fails.
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement `bin/dev`.** Parse before `dir=`:

```zsh
team= close=0 force=0 rest=()
while (( $# )); do
  case "$1" in
    --team) [[ -n "$2" ]] || { print -u2 "dev: --team needs a name"; exit 2 }; team="$2"; shift 2 ;;
    --close) close=1; shift ;;
    --force) force=1; shift ;;
    *) rest+=("$1"); shift ;;
  esac
done
set -- "${rest[@]}"
if [[ -n "$team" ]]; then
  [[ "$team" =~ '^[A-Za-z0-9_-]+$' && "$team" != default ]] || { print -u2 "dev: team name must match [A-Za-z0-9_-]+ and not be 'default'"; exit 2 }
elif (( close || force )); then print -u2 "usage: dev [dir] --team <name> [--close [--force]]"; exit 2; fi
```

  After `name=` is computed and before the `has-session` block, branch on `$team` (functions `team_add`, `team_close`; `repo="${0:A:h:h}"`). Window creation uses `tc_tmux` throughout; the last index: `last="$(tc_tmux list-windows -t "=$name" -F '#{window_index}' | tail -1)"`. Closing windows: `for w in ${(f)"$(tc_tmux list-windows -t "=$name" -F '#{window_id}'$'\t''#{@tc_team}')"}; do [[ "${w#*$'\t'}" == "$team" ]] && tc_tmux kill-window -t "${w%%$'\t'*}"; done`.
- [ ] **Step 4: `tmux-dev-layout` and `tmux-plan`** per AC; GREEN; run `test_layout.zsh`.
- [ ] **Step 5: Commit** `feat(dev): --team adds a grouped team with its own worktree; --close releases it`.

```json:metadata
{"files": ["bin/dev", "bin/tmux-dev-layout", "bin/tmux-plan", "tools/tests/test_teams.zsh"], "verifyCommand": "zsh tools/tests/test_teams.zsh && zsh tools/tests/test_layout.zsh", "acceptanceCriteria": ["--team parses, validates, requires an existing session", "worktree team-<t> on team/<t> from base; grouped windows with @tc_team/@tc_team_root; idempotent", "--close refuses unmerged unless --force; releases claims and lock; kills team windows and lanes; sweep decides the worktree", "layout re-creates <t>·plan; single-team layout unchanged", "leak check in the test"], "modelTier": "standard"}
```

### Task 6: teammate windows and the plan window per team

**Goal:** A team lead's teammates open as `<t>·✦ <name>` beside the team's windows with the team options copied, and `planview` reads a team's lead window and teammate prefix.

**Files:**
- Modify: `bin/tmux-teammate-window` (name and options from the lead window's `@tc_team`)
- Modify: `board/planview.py` (`lead_session`, `owner_states`, `view`, `_snapshot`, `watch`, `main` take `lead_window="claude"`, `mate_prefix="✦ "`; CLI flags `--lead-window`, `--mate-prefix`)
- Modify: `board/tests/test_planview.py` (team cases)
- Modify: `tools/tests/test_teammate_window.zsh` (team placement case)
- Modify: `tools/tests/test_teams.zsh` (a teammate split from `auth·claude` lands in the group)

**Acceptance Criteria:**
- [ ] `tmux-teammate-window`: after computing `lead`, reads `team="$("$T" show-options -wqv -t "$pane" @tc_team 2>/dev/null)"` and `troot=…@tc_team_root`; the window name is `"${team:+$team·}✦ $name"`; after `break-pane` it sets `@tc_team` and `@tc_team_root` on the new window when `team` is non-empty. Placement unchanged: after the lead window, behind that lead's existing `@tc_teammate` windows (so between `<t>·claude` and `<t>·plan`, as the default team's `✦` windows sit between `claude` and `plan`).
- [ ] `planview.view(session, root, home, state_dir, tmux, lead_window="claude", mate_prefix="✦ ")`; `lead_session` targets `={session}:{lead_window}`; `owner_states` looks up `f"{mate_prefix}{owner}"`; `python3 -I board/planview.py view|watch <session> --root R [--lead-window W] [--mate-prefix P]`. Defaults keep every existing test green.
- [ ] `test_planview.py`: `test_team_lead_window_and_mate_prefix` — the sessions fixture entry points at the pane of `auth·claude`; a task owned by `parse` with window `auth·✦ parse` → `state ready`, and with `mate_prefix="✦ "` (default) → `gone`. Mutation: hardcode `✦ ` → fails. `test_cli_flags_pass_through` — `main(["view", "s", "--root", r, "--lead-window", "auth·claude", "--mate-prefix", "auth·✦ ", "--json"])` with the `TC_TMUX` shim used by the existing CLI test.
- [ ] `test_teammate_window.zsh`: a window `auth·claude` with `@tc_team auth` and `@tc_team_root $TT_DIR`; a split from it with the direct `--agent-name probe-t` shape → window `auth·✦ probe-t` right after `auth·claude`, with `@tc_teammate 1`, `@tc_team auth`, `@tc_team_root $TT_DIR`. Mutation: drop the option copy → fails.
- [ ] `test_teams.zsh`: the same split against the `dev --team auth` session → `auth·✦ probe-t` sits between `auth·claude` and `auth·plan`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_planview.py' -v && zsh tools/tests/test_teammate_window.zsh && zsh tools/tests/test_teams.zsh` → `OK`, `ALL PASS`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Tests first** (the three files above), RED.
- [ ] **Step 2: `tmux-teammate-window`:** after `lead="$(…)" || exit 0`:

```zsh
  team="$("$T" show-options -wqv -t "$pane" @tc_team 2>/dev/null)"; troot="$("$T" show-options -wqv -t "$pane" @tc_team_root 2>/dev/null)"
  …
  "$T" break-pane -d -a -s "$pane" -t "$target" -n "${team:+$team·}✦ $name" || exit 0
  "$T" set-option -w -t "$pane" @tc_teammate 1
  [[ -n "$team" ]] && { "$T" set-option -w -t "$pane" @tc_team "$team"; [[ -n "$troot" ]] && "$T" set-option -w -t "$pane" @tc_team_root "$troot"; }
```

- [ ] **Step 3: `planview.py`:** thread the two parameters through; the `tmux("display", "-p", "-t", f"={session}:{lead_window}", …)` call and `wins.get(f"{mate_prefix}{t['owner']}")`.
- [ ] **Step 4: GREEN, mutations, commit** `feat(board): team-aware teammate windows and plan view`.

```json:metadata
{"files": ["bin/tmux-teammate-window", "board/planview.py", "board/tests/test_planview.py", "tools/tests/test_teammate_window.zsh", "tools/tests/test_teams.zsh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_planview.py' -v && zsh tools/tests/test_teammate_window.zsh && zsh tools/tests/test_teams.zsh", "acceptanceCriteria": ["teammate window named <t>·✦ <name> with @tc_team/@tc_team_root copied, placed with its team", "planview lead_window and mate_prefix parameters and CLI flags; defaults unchanged", "tests cover team and default cases"], "modelTier": "standard"}
```

### Task 7: relay and restart in the team root

**Goal:** `tmux-ctl relay` from a team's `<t>·claude` window and the board's restart action start the new lead in that team's worktree (`@tc_team_root`), while the default team keeps today's behaviour.

**Files:**
- Modify: `board/relay.py` (`team_root`, `session_root(tmux, sess, window="claude")`, `claude_pane(tmux, sess, window="claude")`, `relay(..., window="claude")`, `--window`)
- Modify: `bin/tmux-ctl` (`relay`: accept `*·claude`, pass `--window "$cwin"`; message names the window)
- Modify: `board/server.py` (`restart_orchestrator(sess, confirm, window="claude")`; `_act` reads `body.get("window")`)
- Modify: `board/index.html` (`agentMenuItems`: restart for `w.name === "claude" || w.name.endsWith("·claude")`, passing `window: w.name`; the confirm text names the window)
- Modify: `board/tests/test_relay.py`, `board/tests/test_restart_orchestrator.py`
- Modify: `tools/tests/test_teams.zsh` (relay and restart start in the team root)

**Acceptance Criteria:**
- [ ] `relay.team_root(tmux, sess, window)` returns `tmux("show-options", "-wqv", "-t", f"={sess}:{window}", "@tc_team_root").strip()` (empty on error or for `window == "claude"`); `session_root` returns it as is when it is an existing directory (a team restarts in its worktree, not the main checkout), else the existing candidates. `claude_pane` finds the window by `window`. `relay()` appends `"window"` to the lineage record. `main` accepts `--window` (default `claude`).
- [ ] `tmux-ctl relay`: the lead check becomes `[[ ( "$cwin" == claude || "$cwin" == *·claude ) && "$csess" == "$FEEDKEY" ]]`; `--window $(h ${(q)cwin})` is added to the `run-shell` line; the message reads `relay scheduled: ${FEEDKEY}:${cwin} restarts with $doc …`.
- [ ] `restart_orchestrator(sess, confirm, window="claude")`: `window` must be `claude` or match `^[A-Za-z0-9_-]+·claude$` (else `RuntimeError`); root from `relay.session_root(tmux, sess, window)`; looks the window up by name; the "no window → create one" branch applies only to `claude` (a missing team window raises `no window '<w>' in <sess>`); message `restarted the orchestrator in {sess}:{window}`; `_act` passes `body.get("window") or "claude"`.
- [ ] `test_relay.py`: `RootTmux` answers `show-options … @tc_team_root` from a new `team_root` attribute; `test_team_window_root_is_its_worktree` (worktree dir exists → returned unchanged); `test_team_root_gone_falls_back_to_session_path`; `test_default_window_ignores_team_root`; `test_relay_with_window_targets_it_and_records_window`. Mutation: drop the `team_root` branch → the first fails.
- [ ] `test_restart_orchestrator.py`: `Fake` answers `show-options` with `self.team_root` when `"@tc_team_root"` is in the args (else `"1\n"` as now); `test_team_window_restarts_in_team_root`; `test_missing_team_window_is_an_error`; `test_bad_window_name_rejected`. Existing tests unchanged.
- [ ] `test_teams.zsh`: with the `claude-orchestrator` stub from `test_ctl_relay.zsh` (`$STUB/repo/bin/claude-orchestrator` writing its args and `pwd` to a file) and `AGENT_BOARD_REPO` pointing at the stub repo on the test server, `TMUX_PANE=<auth·claude pane> $C relay "$doc"` restarts that pane with `pwd` = the team worktree; the default `claude` relay still restarts in `proj`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_re*.py' -v && zsh tools/tests/test_teams.zsh && zsh tools/tests/test_ctl_relay.zsh` → `OK`, `ALL PASS`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Tests first**, RED.
- [ ] **Step 2: `relay.py`:**

```python
def team_root(tmux, sess, window="claude"):
    if window == "claude":
        return ""
    try:
        return tmux("show-options", "-wqv", "-t", f"={sess}:{window}", "@tc_team_root").strip()
    except Exception:
        return ""


def session_root(tmux, sess, window="claude"):
    tr = team_root(tmux, sess, window)
    if tr and os.path.isdir(tr):
        return tr          # a team lead restarts in its own worktree, by design
    cands = [...]          # unchanged
```

- [ ] **Step 3: `tmux-ctl`, `server.py`, `index.html`** per AC; GREEN; commit `feat(board): relay and restart a team lead in its worktree`.

```json:metadata
{"files": ["board/relay.py", "bin/tmux-ctl", "board/server.py", "board/index.html", "board/tests/test_relay.py", "board/tests/test_restart_orchestrator.py", "tools/tests/test_teams.zsh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_re*.py' -v && zsh tools/tests/test_teams.zsh && zsh tools/tests/test_ctl_relay.zsh", "acceptanceCriteria": ["session_root prefers an existing @tc_team_root for a team window; default unchanged", "tmux-ctl relay accepts <t>·claude and passes --window", "restart action takes window, validates it, restarts in the team root", "board menu offers restart on team lead windows", "tests cover team and default cases"], "modelTier": "standard"}
```

### Task 8: ideas `[~]` (taken up by a team)

**Goal:** `ideas.py`, the board and `tmux-ctl idea` accept `- [~] … (team <t>)`: claimed ideas are shown with their team, other teams skip them, and a claim can be released.

**Files:**
- Modify: `board/ideas.py` (`LINE_RE`, `STATUS`, `TEAM_RE`, `load`, guards in `edit`/`set_status`/`move`, new `claim`/`unclaim`, CLI)
- Modify: `board/server.py` (`_act`: `idea_claim` with `team`, `idea_unclaim`)
- Modify: `board/index.html` (render claimed ideas with a `team` tag; menu item Unclaim)
- Modify: `bin/tmux-ctl` (`idea --claim "<key>"` / `--unclaim "<key>"`, help line)
- Modify: `board/tests/test_ideas.py`, `board/tests/test_ideas_actions.py`
- Modify: `tools/tests/test_ctl_claims.zsh` (`idea --claim` round trip)

**Acceptance Criteria:**
- [ ] `LINE_RE = re.compile(r"^- \[( |x|-|~)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")`, `STATUS["~"] = "claimed"`, `TEAM_RE = re.compile(r" \(team ([A-Za-z0-9_-]+)\)$")`. `load` returns `"team": "<t>"` for claimed ideas (text without the suffix; the `key` keeps the raw text, as `moved_to` does) and `"team": ""` otherwise. Run once by the plan's author on 2026-10-28: the three sample lines parse as `~ 'idea one' team=auth`, ` 'plain'`, `x 'done → spec.md'`; the real inbox `~/.local/state/agent-board/ideas/agent-board.md` (59 lines, 53 ideas, 0 `[~]`) parses identically with the widened regex.
- [ ] `claim(project, key, team)`: open → `- [~] <ts> · <text> (team <t>)`; a non-open idea raises `ValueError("the idea is <status>")`. `unclaim(project, key)`: claimed → `- [ ] <ts> · <text>`; anything else raises. `edit`, `set_status` and `move` refuse a claimed idea with `the idea is claimed by team <t>`. `open_count` unchanged (claimed ideas are not open).
- [ ] CLI: `ideas.py claim --project P --team T -- KEY`, `ideas.py unclaim --project P -- KEY`; `tmux-ctl idea --claim "<key>"` → `claim` with `--team "$TEAM"`; `tmux-ctl idea --unclaim "<key>"`; plain `tmux-ctl idea <text>` unchanged (a text starting with `--claim`/`--unclaim` is treated as the flag; document it in help).
- [ ] Server: `idea_claim` (`body["team"]`, default `default`) → `ideas.claim`, returns `idea claimed by team <t>`; `idea_unclaim` → `idea released`.
- [ ] Board: claimed ideas render in the open list (newest first, same 20 cap) with class `idea claimed` and a `tag` `team <t>` after the text; their menu has one item `Unclaim` (`idea_unclaim`); `.idea.claimed` gets a left border in `var(--amber)`.
- [ ] Tests: `test_ideas.py` — `[~]` round trip (`claim` then `load` shows `claimed`/`team`, `unclaim` restores the exact original line), refusals, legacy lines unaffected; `test_ideas_actions.py` — `idea_claim`/`idea_unclaim` through `_act`; `test_ctl_claims.zsh` — `TC_TEAM=a $C idea "take me"` then `TC_TEAM=a $C idea --claim "<key>"` writes `- [~] … · take me (team a)` and `--unclaim` restores it. Mutation: drop the suffix strip in `load` → the `text` assertion fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ideas*.py' -v && zsh tools/tests/test_ctl_claims.zsh` → `OK`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Tests first**, RED (`claim` missing).
- [ ] **Step 2: `ideas.py`:**

```python
LINE_RE = re.compile(r"^- \[( |x|-|~)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")
STATUS = {" ": "open", "x": "taken", "-": "dropped", "~": "claimed"}
TEAM_RE = re.compile(r" \(team ([A-Za-z0-9_-]+)\)$")


def claim(project, key, team):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", team or ""):
        raise ValueError(f"bad team name {team!r}")

    def change(box, ts, raw, detail):
        if box != " ":
            raise ValueError(f"the idea is {STATUS[box]}")
        return f"- [~] {ts} · {raw} (team {team})", detail
    return _rewrite(project, key, change)


def unclaim(project, key):
    def change(box, ts, raw, detail):
        if box != "~":
            raise ValueError(f"the idea is {STATUS[box]}")
        return f"- [ ] {ts} · {TEAM_RE.sub('', raw)}", detail
    return _rewrite(project, key, change)
```

  In `load`: `tm = TEAM_RE.search(m[3]) if m[1] == "~" else None`; `"text": m[3][:tm.start()] if tm else (m[3][:mv.start()] if mv else m[3])`, `"team": tm[1] if tm else ""`. In `edit`/`set_status`/`move`'s `change`: `if box == "~": raise ValueError(f"the idea is claimed by team {TEAM_RE.search(raw)[1] if TEAM_RE.search(raw) else '?'}")` before the existing checks. CLI: two new subparsers.
- [ ] **Step 3: `server.py`, `index.html`, `tmux-ctl`;** GREEN; commit `feat(board): ideas taken up by a team are marked [~] (team <name>)`.

```json:metadata
{"files": ["board/ideas.py", "board/server.py", "board/index.html", "bin/tmux-ctl", "board/tests/test_ideas.py", "board/tests/test_ideas_actions.py", "tools/tests/test_ctl_claims.zsh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_ideas*.py' -v && zsh tools/tests/test_ctl_claims.zsh", "acceptanceCriteria": ["[~] parsed with team; claim/unclaim round trip; claimed ideas refuse edit/drop/move", "CLI and tmux-ctl idea --claim/--unclaim", "board renders claimed ideas with a team tag and Unclaim", "legacy lines and the real inbox parse unchanged"], "modelTier": "standard"}
```

### Task 9: board teams API and sections

**Goal:** `/api/state` windows carry their team, `/api/teams?session=` and `/api/claims?session=` summarise each team (lead, plan progress, teammates, runs, claims with staleness), and the project page shows one section per team when there are two or more.

**Files:**
- Create: `board/teams.py`
- Create: `board/tests/test_teams.py`
- Modify: `board/server.py` (`build_state` fmt 17 fields, `w["team"]`, `w["team_root"]`; routes `api/teams`, `api/claims`)
- Modify: `board/index.html` (Teams section; team tag on agent cards; `pollTeams`)
- Modify: `board/tests/test_usage.py`, `board/tests/test_poll_efficiency.py`, `board/tests/test_activity.py`, `board/tests/test_worktree_board.py` (fake `list-panes` rows widened to 17 fields where they are built; grep each for the row builder)

**Acceptance Criteria:**
- [ ] `build_state` appends `"#{@tc_team}", "#{@tc_team_root}"` to `fmt`; `len(f) == 17`; `w["team"] = f[15]`, `w["team_root"] = f[16]`; every existing board test still passes.
- [ ] `teams.summary(session, root, home, state_dir, tmux, windows, runs, now=None)` → list, default team first then sorted names from `windows[*]["team"]` and `claims.teams(session)`; each `{"name", "lead_window", "root" (team_root of the lead window, else root), "lead_present": bool, "plan": {"name","done","total","active"} from `planview.view(session, root_of_team, home, state_dir, tmux, lead_window=…, mate_prefix=…)` (`done` = completed count, `total` = len), "teammates": [names of windows `"teammate"` whose name starts with the team's mate prefix, prefix stripped], "runs": count of runs whose `agent` is the lead window or starts with `<t>·` (default: agents without `·`), "claims": claims.list_claims(session, now)[team] or []}`. Never raises: a failing planview or missing files give empty parts.
- [ ] Routes: `api/teams?session=` → `{"teams": [...]}` (`project_arg` validation, 400 on a bad name; root via `relay.session_root(tmux, sess)`, home `Path.home()/".claude"`, state `tc_env.state_dir()`, runs `activity.runs(sess)`; `etag=True`); `api/claims?session=` → `{"claims": claims.list_claims(sess), "stale_days": 7}`.
- [ ] Page: a `section-title` `Teams` with `id="sec-teams"` and a grid `id="teams"`, both hidden unless `teams.length > 1`; each team card shows `name`, `plan.name · done/total` (or `no plan`), `teammates` as tags, `runs` count, and each claim as `path` with a `tag stale` after 7 days; agent cards whose window has `team` get a `tag` with the team name in the `who` block; `pollTeams()` fetches `teams?session=` with `pollJSON` on the state poll cadence. Single-team projects render exactly as before (no Teams section, no tags).
- [ ] Tests (`test_teams.py`): a fake tmux answering `display` (lead pane), `list-windows` and `show-options`; windows fixture with `claude`, `plan`, `✦ a`, `auth·claude`, `auth·plan`, `auth·✦ b`; `$TC_STATE/claims-proj.json` with two teams, `runs-proj.jsonl` with agents `claude`, `a`, `auth·claude`, `auth·b`; home with a `tasks/session-…` list → `summary` gives two teams, runs 2/2, teammates `[a]`/`[b]`, plan done/total, stale flags; `test_single_team_default_only`; `test_api_teams_and_claims_routes` through `ThreadingHTTPServer` as `test_ideas_actions.test_stale_is_409` does (patch `state`, `relay.session_root`). Page: `grep -c 'id="teams"' board/index.html` = 1 and `grep -c 'api/teams\|teams?session=' board/index.html` ≥ 1 in the Verify.

**Verify:** `python3 -m unittest discover -s board/tests -v 2>&1 | tail -3 && grep -c 'id="teams"' board/index.html` → `OK` and `1`

**Steps:**

- [ ] **Step 1: Widen the row** in `build_state` and fix the fake rows in the four test files (search each for the 15-element row builders; `test_usage.py` has `label_rows`, which feeds `label_targets`'s own 9-field format, so check which format each helper feeds before editing). Run the whole board suite: green before the feature.
- [ ] **Step 2: `teams.py` tests first**, RED, implement, GREEN. Mutation: count runs by exact agent only → `runs` for `auth` drops to 1, fails.
- [ ] **Step 3: Routes and page.** `index.html`: add after the Agents title block `<div class="section-title" id="sec-teams" hidden><span>Teams</span></div><div class="grid" id="teams" hidden></div>`; `renderTeams(d)`; in `card()` after `who.append(el("b", …))` add `if (w.team) who.append(el("span", "tag", w.team));`.
- [ ] **Step 4: Commit** `feat(board): team sections, /api/teams and /api/claims`.

```json:metadata
{"files": ["board/teams.py", "board/tests/test_teams.py", "board/server.py", "board/index.html", "board/tests/test_usage.py", "board/tests/test_poll_efficiency.py", "board/tests/test_activity.py", "board/tests/test_worktree_board.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -v 2>&1 | tail -3 && grep -c 'id=\"teams\"' board/index.html", "acceptanceCriteria": ["build_state carries team and team_root per window (17 fields); all board tests green", "teams.summary per team: lead, plan progress, teammates, runs, claims with stale", "/api/teams and /api/claims routes with validation and etag", "page shows a Teams section only with two or more teams; team tags on agent cards"], "modelTier": "standard"}
```

### Task 10: overseer event 7, claims overlap

**Goal:** The overseer's digest record carries each project's claim overlaps (`claims`) and `notify.conditions` emits the kind `claims_overlap` once per overlap key, under the notifier's existing latch and rate limit.

**Files:**
- Modify: `board/overview.py` (`RECORD_KEYS` gains `"claims"`; `record()` fills it)
- Modify: `board/notify.py` (`KINDS` gains `"claims_overlap"`; `conditions()` adds it per overlap)
- Modify: `board/tests/test_overview.py` (`test_record_keys_and_plan` and a claims case)
- Modify: `board/tests/test_notify.py` (claims_overlap cases)

**Acceptance Criteria:**
- [ ] Read `board/overview.py` and `board/notify.py` as merged from the overseer plan (`docs/superpowers/plans/2026-10-28-overseer.md`, Tasks 2 and 3) first; keep their shapes: `overview.RECORD_KEYS` is a fixed tuple and `test_overview.test_record_keys_and_plan` asserts `tuple(record) == RECORD_KEYS`; `notify.KINDS` is a tuple; `notify.conditions(ov)` builds dicts through `add(project, kind, key, title, text)` inside a per-project loop; `Notifier.observe` latches per `(project, kind, key)` (an event fires when its key was not active in the previous overview; the first overview and a project's first appearance only seed) and rate-limits per `(project, kind)` at `RATE_S` = 300 s.
- [ ] `overview.RECORD_KEYS = (…, "spend_today", "claims")` (appended last) and `record()` sets `"claims": claims.overlaps_all(name)` inside a `try/except` that leaves `[]` on any error (a missing registry gives `[]`). Each item is `{"team", "path", "other_team", "other_path", "plan", "other_plan"}` (Task 1).
- [ ] `notify.KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "claims_overlap")`. In `conditions()`'s per-project loop: `for o in p.get("claims") or []: add(name, "claims_overlap", f"{o['path']}|{o['other_team']}", f"{name}: claims overlap", f"{o['team']} and {o['other_team']} both claim {o['path']}")`. The key stays the same while the overlap holds and disappears when it clears, so the existing latch gives: fires once when the overlap first appears, not again while it persists, again after a release and re-add; the 300 s per-(project, kind) limit and `TC_NOTIFY=0` apply unchanged. Differences from events 1–6, checked: none in mechanism; only the key source (a list on the record) and the text.
- [ ] `test_overview.py`: `test_record_keys_and_plan` extended for the new last key; `test_claims_empty_without_registry`; `test_claims_from_registry` (seed `$TC_STATE/claims-<p>.json` through `claims.add` for two teams with one overlapping path → one item with both teams). Mutation: drop the `claims` assignment → `test_record_keys_and_plan` fails on the tuple.
- [ ] `test_notify.py`: `test_claims_overlap_fires_once_then_latches` (overview A with no claims seeds; B with one overlap → one event with kind `claims_overlap`, key `docs/x.md|b`, text `a and b both claim docs/x.md`; B again → none); `test_claims_overlap_fires_again_after_clear` (C with no claims, then B → one event); `test_claims_overlap_rate_limited` (two different overlap keys in one overview → the second is dropped within 300 s, as the existing per-kind rule does); `test_claims_overlap_off_with_tc_notify_0`. Mutation: key by project only (`"claims"` as the key) → `test_claims_overlap_fires_again_after_clear` still passes but `test_claims_overlap_rate_limited` changes; the named mutation that fails: build the key from `o["team"]` only → two overlaps between the same teams on different paths collapse, failing `test_claims_overlap_rate_limited`'s candidate count (assert on `conditions()` directly: two candidates).
- [ ] The page's event list renders events by `title`/`text` (overseer Task 10); no `index.html` change unless the kind map there is a closed list: then add `claims_overlap` to it.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_notify.py' -v && python3 -m unittest discover -s board/tests -p 'test_overview.py' -v` → `OK` twice

**Steps:**

- [ ] **Step 1: Read the two modules** and confirm the names above (`RECORD_KEYS`, `record`, `KINDS`, `conditions`, `add`, `Notifier.observe`, `RATE_S`).
- [ ] **Step 2: Tests first** (seed registries through `claims.add` with `TC_STATE` on the test's temp dir; build overviews with the test file's existing helpers), RED.
- [ ] **Step 3: Implement:**

```python
# overview.py
import claims  # noqa: E402  (next to the existing imports)
RECORD_KEYS = ("project", "path", "attached", "plan", "needs_you", "last_run", "lead", "artifacts", "epoch", "alerts", "spend_today", "claims")
# in record(), last field:
    try:
        rec_claims = claims.overlaps_all(name)
    except Exception:   # noqa: BLE001 - no registry or a corrupt one: no overlaps
        rec_claims = []
    …  "spend_today": …, "claims": rec_claims}

# notify.py
KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "claims_overlap")
# in conditions(), inside `for p in ov.get("projects") or []:` after the alerts loop:
        for o in p.get("claims") or []:
            add(name, "claims_overlap", f"{o['path']}|{o['other_team']}", f"{name}: claims overlap",
                f"{o['team']} and {o['other_team']} both claim {o['path']}")
```

- [ ] **Step 4: GREEN, mutations, commit** `feat(board): overseer event 7, claims overlap`.

```json:metadata
{"files": ["board/overview.py", "board/notify.py", "board/tests/test_overview.py", "board/tests/test_notify.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_notify.py' -v && python3 -m unittest discover -s board/tests -p 'test_overview.py' -v", "acceptanceCriteria": ["RECORD_KEYS ends with claims; record() fills it from claims.overlaps_all, [] on error; test_record_keys_and_plan extended", "KINDS gains claims_overlap; conditions() adds one per overlap with key <path>|<other team>", "latch per key: once on appearance, again after clear; 300 s per-kind rate limit and TC_NOTIFY=0 unchanged", "tests for both modules"], "modelTier": "standard"}
```

### Task 11: rules: orchestrator, plan skill, handoff, plugin test

**Goal:** The lead and teammate rules describe teams, claims, overlap talks, the merge lock, `[~]` ideas and release at finish; the plan skill adds the `Claims:` header rule; `test_plugin.zsh` pins the names.

**Files:**
- Modify: `claude/orchestrator.md` (new `## Teams` section after "Ideas inbox"; rule 1 of the teammate rules; the Ideas inbox round text)
- Modify: `claude/skills/writing-plans-extras/SKILL.md` (new `## 14. Claims when the project has several teams`; the "Before you finish" list)
- Modify: `claude/plugin/skills/handoff/SKILL.md` (relay allowed from `<team>·claude`; `tmux-ctl read "<team>·✦ <name>"`)
- Modify: `tools/tests/test_plugin.zsh` (checks)

**Acceptance Criteria:**
- [ ] `orchestrator.md` `## Teams` says, in this order: how to know the project has several teams (`tmux-ctl claim list` shows another team, or `tmux list-windows` shows `<team>·claude` windows); your team is the window you run in (`dev --team <name>` started you in `.claude/worktrees/team-<name>` on `team/<name>`); **plan time**: with two or more teams the plan header lists `Claims:` (the union of every task's Files) and you run `tmux-ctl claim add --plan <plan path> <paths…>` before execution; on exit 3 read the printed overlaps, message the other lead (`tmux-ctl tell <team>·claude …`, or `claude` for the default team), settle who edits what or splits the file, and bring it to the user only if you cannot agree; **edit time**: a `claimed by team` note from the edit hook means a teammate must stop on that file and tell you; **merging**: `tmux-ctl merge-lock acquire -t 600`, `tmux-ctl merge-check`, the merge and the suites on `main` per the live-checkout rule, `tmux-ctl merge-lock release`, then `tmux-ctl claim release --all` (both also at the end of `finishing-a-development-branch`); `dev --team <name> --close` once merged; **ideas**: a round marks each idea it takes up with `tmux-ctl idea --claim "<key>"` (`- [~] … (team <name>)`), skips `[~]` ideas of other teams, and still ends with `- [x] … → <spec>`; **shared context**: every lead may `tmux-ctl context add`; other teams get entries at their next start or compaction.
- [ ] Teammate rule 1 gains: "If the edit hook says a path `is claimed by team <other>`, stop editing that file and tell the lead."
- [ ] `writing-plans-extras/SKILL.md` §14: when `tmux-ctl claim list` (or the lead's brief) shows two or more teams, the plan header carries `**Claims:**` listing the union of every task's Files (directories allowed), and the Execution Handoff step runs `tmux-ctl claim add --plan <plan path> <claims…>` before invoking subagent-driven-development; an exit 3 is settled with the other lead before execution starts. Add one line to "Before you finish". (`~/.claude/skills/writing-plans-extras` is a symlink into this repo: edit the repo file only.)
- [ ] Handoff skill: line 64's "refuses from any window but the session's `claude` window" becomes "…but the session's `claude` window or a team's `<team>·claude` window"; the read hint adds `<team>·✦ <name>`.
- [ ] `test_plugin.zsh` checks: `orchestrator.md` contains `tmux-ctl claim add`, `tmux-ctl merge-lock acquire`, `tmux-ctl merge-check`, `idea --claim` and `dev --team`; `writing-plans-extras/SKILL.md` contains `**Claims:**`; the handoff skill contains `<team>·claude`. The existing skill-name resolution check stays green (no new backticked `ns:name` tokens that don't resolve).

**Verify:** `zsh tools/tests/test_plugin.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Add the `test_plugin.zsh` checks**, RED.
- [ ] **Step 2: Write the three rule texts** per AC (short paragraphs and bullets, the file's existing voice; no `/Users/` paths).
- [ ] **Step 3: GREEN; commit** `docs(rules): teams, claims, merge lock and [~] ideas in the lead, plan and handoff rules`.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/skills/writing-plans-extras/SKILL.md", "claude/plugin/skills/handoff/SKILL.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["orchestrator.md Teams section covers detection, plan-time claims, overlap talks, edit-time note, merge lock + merge-check + release, --close, [~] ideas, shared context", "teammate rule 1 names the claimed-path note", "writing-plans-extras §14 Claims header and registration before execution", "handoff relay allowed from <team>·claude", "test_plugin.zsh pins the strings"], "modelTier": "standard"}
```

### Task 12: docs

**Goal:** `docs/ARCHITECTURE.md`, `docs/INSTALL.md` and `README.md` describe teams, claims, the merge lock, the hook and `TC_CLAIMS`, alongside the existing entries.

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/INSTALL.md`
- Modify: `README.md`

**Acceptance Criteria:**
- [ ] `ARCHITECTURE.md`: tags table gains `@tc_team` and `@tc_team_root` (window; set by `dev --team`, copied by `tmux-teammate-window`; the team's name and worktree); "Other subcommands" gains rows `claim add [--plan P] <paths…> \| list [--json] \| release (<paths…> \| --all)`, `merge-lock acquire [-t secs] \| release [--force] \| status`, `merge-check [<branch>]`, and the `idea` row mentions `--claim`/`--unclaim`; Hooks table gains the `claims-guard.sh` row (PreToolUse `Edit\|Write\|MultiEdit`; writes `claims-<project>.json` `warned` lists; notes: additionalContext + systemMessage, never a permissionDecision, silent otherwise, `TC_CLAIMS=0`); "Agent teams and workers" gains a **Teams** paragraph (`dev --team`, windows, worktree/branch, claims at plan and edit time, merge lock and merge-check, `--close`, `[~]` ideas, shared context); the Ideas inbox paragraph adds `[~]` = taken up by a team `(team <name>)`; the API table gains `GET api/teams?session=` and `GET api/claims?session=`; the State files table gains `claims-<p>.json` (`tmux-ctl claim`, the hook) and `merge-lock-<p>.json` (`tmux-ctl merge-lock`), both removed on session close; the Tests table mentions `test_teams.zsh`, `test_claims_guard.zsh`. The line "All hooks are silent and exit 0 except kill-guard's deliberate block" becomes "… except kill-guard's deliberate block and claims-guard's additionalContext note".
- [ ] `INSTALL.md` line 23's hook list adds `claims-guard` (warns when an edit targets a path another team claimed; `TC_CLAIMS=0` disables it).
- [ ] `README.md`: Commands line mentions `dev [dir] --team <name> [--close]`; Layout table's `bin/` row is unchanged.
- [ ] No `/Users/` paths; `grep -c 'claims-guard' docs/ARCHITECTURE.md docs/INSTALL.md` ≥ 1 each; `grep -c 'dev --team' docs/ARCHITECTURE.md README.md` ≥ 1 each.

**Verify:** `grep -c 'claims-guard' docs/ARCHITECTURE.md docs/INSTALL.md && grep -c 'dev --team' docs/ARCHITECTURE.md README.md && zsh tools/tests/test_plugin.zsh` → four counts ≥ 1 and `ALL PASS`

**Steps:**

- [ ] **Step 1: Edit the three files** per AC, in the surrounding voice (tables stay aligned; one row per item).
- [ ] **Step 2: Run the Verify; commit** `docs: teams, claims, merge lock and the claims-guard hook`.

```json:metadata
{"files": ["docs/ARCHITECTURE.md", "docs/INSTALL.md", "README.md"], "verifyCommand": "grep -c 'claims-guard' docs/ARCHITECTURE.md docs/INSTALL.md && grep -c 'dev --team' docs/ARCHITECTURE.md README.md && zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["tags, subcommands, hooks, Teams paragraph, ideas [~], API and state-file rows in ARCHITECTURE.md", "INSTALL.md hook list names claims-guard and TC_CLAIMS", "README names dev --team", "no /Users/ paths"], "modelTier": "mechanical"}
```

### Task 13: e2e, two teams in one scratch project

**Goal:** On a scratch tmux server, two teams whose plans both list one shared file register claims (both leads told), the other team's edit warns, both branches merge under the merge lock, and a context entry from one team reaches the other team's lead; plus read-only checks against the user's real state.

**Files:**
- Create: `tools/tests/e2e-teams.zsh` (not `test_*`: run-all does not pick it up)
- Create: `docs/superpowers/plans/2026-10-28-teams-in-one-project-e2e-report.md`

**Acceptance Criteria:**
- [ ] The script (via `lib.zsh`, scratch `TC_STATE`, scratch `TC_IDEAS_DIR` and `TC_CONTEXT_DIR`, a scratch git repo `$TT_DIR/proj` with `main`, leads `DEV_CLAUDE_CMD='sleep 900'`): `dev proj`, `dev proj --team a`, `dev proj --team b`; from a's lead pane (`TMUX_PANE`, `TC_TEAM` unset so `@tc_team` is read) `tmux-ctl claim add --plan pa src/shared.py src/a.py` → 0; from b's `tmux-ctl claim add --plan pb src/shared.py src/b.py` → 3, and the captures of `a·claude` and (b's own output) show the overlap; the claims-guard hook run with b's pane env on `<wt-b>/src/shared.py` emits the warning JSON and `a·claude`'s capture shows `[Claims] team b is editing src/shared.py`; a commit on each branch (disjoint edits), then from a: `merge-lock acquire`, `merge-check` (no conflicts), `git -C proj merge team/a`, `merge-lock release`; from b the same (its `acquire` while a holds, run in the background with `-t 30`, prints the holder then succeeds after a releases: the log shows both lines); `git -C proj log --oneline main` shows both merge commits; `TC_TEAM=a tmux-ctl context add Gotchas "shared.py is owned by team a"` then the real `claude/plugin/scripts/context-inject.sh` run with a SessionStart payload whose `cwd` is b's worktree prints that entry; `dev proj --team a --close` and `--team b --close` exit 0; the real folders `~/.local/state/agent-board/{ideas,context}` and the real `TC_STATE` are untouched (checksums of their listings before and after are equal).
- [ ] Read-only real-state checks, recorded in the report: (1) `python3 -I board/ideas.py list --project agent-board | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'` equals the count from `main`'s parser (`git show main:board/ideas.py > /tmp/ideas_main.py` run the same way) on the user's real inbox, and no idea has `status == "claimed"`; (2) the live board's `GET /api/state` for the real `agent-board` project (token from `~/.local/state/tmux-dash/token`, port 7700) is served by the live server on `main`, so instead start a second instance from the worktree on `TMUX_DASH_PORT=7710` against the real tmux server and read `api/teams?session=agent-board`: exactly one team, `default`, and the project page loads with no Teams section (a screenshot or the DOM count `document.querySelectorAll('#teams .card').length == 0` via the browser is noted); (3) `tmux-ctl claim list` from the real `agent-board` session prints nothing but the header (no claims exist).
- [ ] Optional real-Claude check of the context step (if the harness allows a headless run; `tools/tests/test_plugin.zsh` runs `claude -p` the same way): `cd <wt-b> && claude -p --model haiku <ab_claude_args from bin/_ab_claude.zsh> "Reply with the Gotchas entries of the shared project context you were given, verbatim."` → the reply contains `shared.py is owned by team a`. If refused, the report says so and the hook-level check stands.
- [ ] The report lists every command with its output (trimmed to the deciding lines), the before/after listing checksums, and the leak check (`ls /private/tmp/tmux-$UID` before and after, `ps` count of `sleep 900`).

**Verify:** `zsh tools/tests/e2e-teams.zsh > /tmp/e2e-teams.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/e2e-teams.out` → `rc=0` and `0`

**Steps:**

- [ ] **Step 1: Write the script** (pattern: `tools/tests/e2e-plan-window.zsh`; `check`/`ok`/`fail` from `lib.zsh`; print every command before running it so the output is the report's source). Before `tt_setup`: `ls -la ~/.local/state/agent-board/ideas ~/.local/state/agent-board/context "${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}" 2>/dev/null | shasum > "$before"`.
- [ ] **Step 2: Run it** through `tmux-ctl run -t 600 tests "zsh tools/tests/e2e-teams.zsh > /tmp/e2e-teams.out 2>&1; echo rc=\$?"`; fix the product (never the check) on a failure, with `systematic-debugging`.
- [ ] **Step 3: Real-state checks** (AC) and the optional headless run; write the report.
- [ ] **Step 4: Commit** `test(e2e): two teams in one project, with real-state checks`.

```json:metadata
{"files": ["tools/tests/e2e-teams.zsh", "docs/superpowers/plans/2026-10-28-teams-in-one-project-e2e-report.md"], "verifyCommand": "zsh tools/tests/e2e-teams.zsh > /tmp/e2e-teams.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/e2e-teams.out", "acceptanceCriteria": ["scratch two-team flow: claims overlap told to both leads, edit warns, both merges under the lock, context entry reaches the other team, close both", "real folders untouched (listing checksums equal)", "read-only real-state checks: real inbox parses identically with no claimed ideas; worktree board on :7710 shows one team for agent-board; claim list empty", "report with commands, outputs, leak check"], "modelTier": "standard"}
```

---

## Self-review (writing-plans)

1. **Spec coverage.** Teams in one session: default team unchanged (T5 AC, `test_layout.zsh` green), `dev --team` worktree/branch/windows/options (T5), teammates `<t>·✦` (T6), `session_root`/restart via `@tc_team_root` (T7), per-team plan window (T5+T6), `--close` with merged check and `--force`, claims released, sweep (T5), board sections (T9). Claims: registry, lock, `tmux-ctl claim` (T1, T2), plan-time rule and `Claims:` header (T11), overlap exit 3 + `tell` (T2), edit-time hook with every silence case (T4), release at finish and `--close` (T11, T5), stale after 7 days in `claim list` and on the board (T1, T9), overseer event 7 (T10). Shared resources: merge-lock with wait/timeout/reclaim and `merge-tree` check (T3), ideas `[~]` in `ideas.py`, the board and the rounds (T8, T11), shared context for all leads (T11 rule; T13 check), tests/shell windows unchanged (no task touches them). Changes table: every file row has a task (`bin/tmux-dev-layout` T5, `bin/tmux-teammate-window` T6, `board/relay.py`+`server.py` T7/T9, `board/claims.py` T1, `bin/tmux-ctl` T2/T3/T7/T8, hook files T4, `writing-plans-extras` T11, `orchestrator.md` T11, `ideas.py`+`index.html` T8, `notify.py` T10, docs T12). Acceptance list: `test_claims.py` T1 (all six bullets), `test_claims_guard.zsh` T4, `test_teams.zsh` T5/T6/T7 (incl. relay/restart and the leak check), merge-lock tests T3, ideas round trip T8, e2e T13.
2. **Placeholders:** none (`…` inside code blocks marks unchanged surrounding code, each next to the exact line it continues).
3. **Type consistency:** `claims.list_claims`/`claims.check`/`claims.overlaps_all`/`claims.teams`/`claims.lead_window`/`claims.mate_prefix` are used by T2–T4, T9, T10 under those names; `mergelock.acquire/release/status/Held/NotHolder` by T3 and T5; `planview.view(..., lead_window=, mate_prefix=)` by T6 and T9; `relay.session_root(tmux, sess, window)` by T7 and T9; `build_state` window keys `team`, `team_root` by T9.

## Execution Handoff

Invoke `superpowers-extended-cc:subagent-driven-development` (with `subagent-driven-development-extras`) now; no question.
