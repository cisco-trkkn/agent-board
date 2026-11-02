# A session's `path` is its project root

Status: approved in chat 2026-11-02; the home guard and the cache rules below were approved by the user 2026-11-02. Idea source: the board-bugs Task 8 e2e (`docs/superpowers/plans/2026-10-29-board-bugs-e2e-report.md`).

## Problem

`/api/state` gives every session a `path`, set in `board/server.py` `build_state` (around line 316) and again in `label_targets` (around line 345) from **window 1's `#{pane_current_path}`**. Claude Code is launched in `~` in every project session, so window 1's cwd is `~` for `agent-board`, `interiors` and `master-gcp-repo` alike (checked on the live server 2026-11-02; their tmux `#{session_path}` is the repo).

Five consumers read `path` expecting the project root:

- `/api/usage` (`server.py` around 930) and the card alerts and labels (`usage.py` `_project_live`, `_agent_windows`), which scope live sessions with `in_project(cwd, path)`; today every project's Usage view shows only the home-folder lead;
- the card worktree list, `cached_worktrees(s["path"])`;
- `project_repo(sess)`, used by the worktree sweep and by moving a doc between projects;
- the session header, `#sess-path` in `board/index.html`.

The same root cause was fixed for `session_path()` in board-bugs (a): `relay.session_root(tmux, sess)` already returns the right answer, by a separate `tmux display` call.

## Design

### Root derivation (one rule, shared)

- New `relay.root_for(start_path)`: the first of `start_path`, `$HOME` that is a non-empty existing directory, mapped through `main_checkout()`; if neither is, `str(Path.home())`. This is exactly `session_root`'s current rule.
- `session_root(tmux, sess)` keeps its signature and calls `root_for` with the `#{session_path}` it reads.
- `build_state` and `label_targets` add `#{session_path}` to the `list-panes -a` format they already run (no extra tmux call) and set `s["path"] = root_for(<session_path>)` once per session. The "window 1's cwd, else the first pane's" rule is removed.
- Home guard (changed from the first draft; approved by the user 2026-11-02): `~` is itself a git repo, so a plain folder under it would resolve to `~`. `main_checkout(d)` returns `d` when git's `--show-toplevel` for `d` is `$HOME` (compared with `os.path.realpath` on both sides) and `d` is not `$HOME`. This is `bin/dev`'s rule. It compares the toplevel, not the common dir's parent: a linked worktree of the `~` repo has its own toplevel and still maps to `~`. One `git rev-parse --path-format=absolute --git-common-dir --show-toplevel` call reads both; where `--show-toplevel` fails (a bare repo, inside `.git`) the non-zero exit keeps today's outcome, `d`.
- `root_for`'s git lookup is cached per `start_path` inside `relay.root_for` (a module-level dict) as `(has own .git, root)`. A plain folder inside a parent repo changes when it is `git init`ed, so an entry is recomputed when `os.path.exists(<d>/.git)` differs from the stored value (one stat per lookup, no git). A removed directory drops its entry and falls back to `$HOME`. A failure to run git (see Error handling) is never cached, so the next poll retries; a non-zero git exit (not a repo) is an answer and is cached.

### Consumers

No consumer code changes. They receive the project's main checkout. Each pane's own `path` stays its real `#{pane_current_path}`, so worker matching by pane cwd (`usage._agent_windows`) is unchanged. A session started in `~` (for example `francisco_ruiz`) still maps to `~`.

Why this scopes correctly: Claude Code records the lead's working folder (the repo it `cd`s into) in transcripts and tap files, not the process launch folder. On 2026-11-02 the live tap files show leads with `cwd` = their repo, so `in_project(cwd, root)` and `_agent_windows`' "the `claude` window matches the newest lead whose cwd is the repo" both match.

### Error handling

- Empty or removed `#{session_path}` → `$HOME`, then `main_checkout`.
- `main_checkout` returns the directory itself for a non-git folder.
- The git call has `timeout=10` and catches `OSError` and `subprocess.SubprocessError` (git missing, hung): `main_checkout` returns the directory itself and `root_for` does not cache that result.
- `state()` must not raise on any of these: a raise blanks the board.

## Out of scope

- A lead whose working folder is outside its repo (a scratch dir) still drops out of the project's Usage view, as today.
- `in_project`'s rule (exact root or under `<root>/.claude/worktrees/`) is unchanged.
- The Usage tab's other behaviour (tap overlay, alerts, plan limits) is unchanged.

## Testing

Unit (board suite, temp `TC_STATE`, a fake `tmux` runner returning `list-panes` rows):

- `build_state` and `label_targets`: window 1's cwd `~`, `#{session_path}` = a scratch git repo → `path` is that repo. Mutation: restore the window-1 rule → fails.
- `#{session_path}` = a worktree of the scratch repo → `path` is the main checkout (real `git worktree add` on a scratch repo, not a stub).
- `#{session_path}` removed or empty → `path` is `$HOME` (patched `HOME` to a temp dir).
- `/api/usage?session=<s>` for such a session returns that project's live rows, not the home lead's.
- `session_root` keeps passing its existing tests.

Real-state check (a second board on port 7710 from the worktree; 7700 untouched; read-only against the live tmux server):

- `/api/usage?session=` for `agent-board`, `interiors`, `master-gcp-repo` each returns that project's live rows; the row counts match an in-process `usage.report()` for the same root, stated uncapped.
- Each card's `path` in `/api/state` is the project root, and its worktree list is that project's.
