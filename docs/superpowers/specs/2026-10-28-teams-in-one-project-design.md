# Teams: several orchestrators in one project, without collisions

Idea (francisco_ruiz inbox, 2026-10-16): "if I had multiple orchestrators in a project and each with their own PRD. How could I get
them to collaborate on execution so the sub agents never conflict and share context efficiently".

This is Group B, part 2 (B2). B1, the overseer, has its own spec: `2026-10-28-overseer-design.md`.

## Problem

A project has one lead in its `claude` window. A second orchestrator in the same repo can be started by hand, but then:
- the two share the checkout and `main`;
- they share the plan window;
- nothing tells either one that the other is editing the same files;
- their merges can race;
- both can take the same idea from the inbox.

## Decisions (user, 2026-10-28)

- **Use case:** parallel features, separate PRDs run at the same time. They should mostly not interact.
- **Isolation:** each team works on its own branch in its own worktree.
- **Overlap:** claims with early warning, not hard locks and not detection at merge time.
- **Layout:** one project session, with each team's windows grouped and labelled by team.

## Behaviour

### Teams in one session
- **The default team** is the project's existing lead. Its windows keep their current names (`claude`, `plan`), so a single-team
  project is unchanged.
- **`dev --team <name>`** adds a team to the current project session:
  - a worktree `.claude/worktrees/team-<name>` on branch `team/<name>`, cut from `main`;
  - windows `<name>·claude` (the lead, started in that worktree with `claude-orchestrator`) and `<name>·plan`, placed together
    after the existing windows;
  - a team lead's teammates open as `<name>·✦ <teammate>`, next to that team's windows.

  `·` separates team and window because `:` is tmux's `session:window` separator.
- **Team options:** each team window carries `@tc_team=<name>` and `@tc_team_root=<worktree>`.
  - `relay.session_root` and `restart_orchestrator` use `@tc_team_root` when the lead's window has one, else `session_path`
    as now. A team lead relays or restarts into its own worktree.
- **Separate per team:** lead, plan window (showing that lead's task list), Claude Code team, teammates and lanes
  (`tests·<agent>`, unchanged).
- **`dev --team <name> --close`:**
  - closes the team's windows and releases its claims;
  - refuses while `team/<name>` is not merged into `main`, unless `--force` is given;
  - worktree cleanup follows the existing merged-worktree sweep.
- **Board:** the project page shows one section per team: lead, plan progress, teammates, runs, claims.

### Claims
- **Registry:** `$TC_STATE/claims-<project>.json` holds `{team: [{path, plan, ts}]}`. A path is a file, a directory (which
  covers everything under it) or a glob.
  - Managed by `board/claims.py`, under an exclusive lock.
  - Exposed as `tmux-ctl claim add <paths…> | list | release [<paths>|--all]`. Calls run under the caller's `@tc_team`, or the
    default team.
- **Plan time:** `claude/skills/writing-plans-extras/SKILL.md` gains a rule. When the project has two or more teams, the plan header
  lists `Claims:`, the union of every task's Files, and the lead runs `tmux-ctl claim add` before execution starts.
  - **On an overlap** with another team's claim, `claim add` records the claim anyway, prints each overlap (path, the other team,
    its plan) and exits 3.
  - **It also notifies** the other team's lead with `tmux-ctl tell <team>·claude`.
  - The two leads settle it by message. If they can't agree, each brings it to the user.
- **Edit time:** a new PreToolUse(Edit|Write|MultiEdit) hook, `claude/plugin/scripts/claims-guard.sh`.
  - When the target path is claimed by another team, it lets the edit through with a message to the agent: "`<path>` is claimed
    by team `<other>` (plan `<plan>`); tell your lead before continuing". It also sends a one-line note to the claiming team's lead.
  - It is silent when the project has one team, for the agent's own claims, for unclaimed paths, with `TC_CLAIMS=0`, and on any
    error. It never blocks.
- **Release:** `finishing-a-development-branch` releases the team's claims after its merge (orchestrator rule), and so does
  `--close`. Claims older than 7 days are marked stale in `claim list` and on the board.
- **Overseer:** the B1 notifier gains event 7, claims overlap, fired once per new overlap.

### Shared resources
- **Merges into `main`:** they take turns.
  - `tmux-ctl merge-lock acquire|release` is a per-project lock file holding `{team, pid, ts}`, held while a lead test-merges,
    merges and runs the suites on `main`.
  - `acquire` reports the holder and waits, up to `-t <secs>`.
  - A lock whose holder process is gone is reclaimed.
  - Before merging, the lead runs `git merge-tree --write-tree` of its branch against `main` and against each other open
    `team/*` branch, and tells that team's lead about any conflict.
  - The live-checkout integration rules in `claude/orchestrator.md` still apply.
- **Ideas inbox:** shared. A next-steps or `regroup` round marks each idea it takes up as `- [~] … (team <name>)`, and other teams
  skip `[~]` ideas. They become `- [x] … → <spec>` as today. `board/ideas.py` and the board accept `[~]`.
- **Shared context** (`2026-10-28-shared-project-context-design.md`): one file per project, shared by all teams.
  - Every team lead may write to it, since the existing lock covers concurrent writes.
  - One team's entries reach the other teams at their next session start or compaction.
- **Tests and shell windows:** unchanged.

## Changes

| File | Change |
|---|---|
| `bin/dev`, `bin/tmux-dev-layout` | `--team <name>` and `--close`; grouped window placement; team options. |
| `bin/tmux-teammate-window` | Place `<team>·✦` windows with their team. |
| `board/relay.py`, `board/server.py` | Prefer `@tc_team_root` in `session_root` and in restart; team sections on the project page. |
| `board/claims.py` (new) | Claims registry, overlap detection, release, staleness. |
| `bin/tmux-ctl` | `claim`, `merge-lock` subcommands. |
| `claude/plugin/scripts/claims-guard.sh` (new), `claude/plugin/hooks/hooks.json`, `plugin.json` | Edit-time warning hook. |
| `claude/skills/writing-plans-extras/SKILL.md` | `Claims:` header and registration step when the project has two or more teams. |
| `claude/orchestrator.md` | Teams section: claims, overlap talks, merge-lock, `[~]` ideas, release at finish. |
| `board/ideas.py`, `board/index.html` | Accept and show `[~]`. |
| `board/notify.py` (from B1) | Event 7, claims overlap. |
| `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, `README.md` | Teams, claims, merge-lock, `TC_CLAIMS`, alongside existing entries. |

## Acceptance

- **`board/tests/test_claims.py`:**
  - add, then list;
  - overlap detection for an exact file, a directory prefix and a glob, with exit 3 and the overlap printed;
  - a team's own claims never count as an overlap;
  - release of given paths and of `--all`;
  - stale marking after 7 days;
  - concurrent adds under the lock both land.
- **`tools/tests/test_claims_guard.zsh`:**
  - warns on another team's path and lets the edit through (exit 0, with a message);
  - silent on own and unclaimed paths;
  - silent with a single team and with `TC_CLAIMS=0`;
  - lets the edit through on garbage input.
- **`tools/tests/test_teams.zsh`** (scratch tmux server, `-f /dev/null`):
  - `dev --team auth` creates the worktree and branch, and the windows `auth·claude` and `auth·plan`, grouped;
  - `@tc_team_root` is set;
  - a teammate window lands in the team's group;
  - relay and restart start the team lead in the team root;
  - `--close` is refused while the branch is unmerged and succeeds after a merge;
  - leak check afterwards.
- **Merge-lock tests:**
  - a second acquire reports the holder and times out;
  - release frees the lock;
  - a lock held by a dead pid is reclaimed.
- **Ideas:** a `[~]` round-trip through `ideas.py`, and other teams' rounds skip `[~]` ideas.
- **E2E after merge** (a scratch project with two teams whose plans both list one shared file):
  - claim registration reports the overlap to both leads;
  - an edit to the claimed file by the other team warns;
  - both branches merge into `main` one after the other under the merge-lock;
  - a context entry added by one team appears in the other team's lead after its restart.
  - The real state folders are untouched.

## Out of scope

- One large PRD split across leads, with dependencies between slices.
- Hard file locks.
- Teams spanning several repos.
