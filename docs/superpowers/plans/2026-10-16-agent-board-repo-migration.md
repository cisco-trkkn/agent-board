# Agent Board repo migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Agent Board toolkit (code, tests, lead/worker rules, hooks, specs, plans and ideas) out of master-gcp-repo into its own local git repo `~/agent-board`, served live through symlinks, and give it its own Agent Board project.

**Architecture:** `~/agent-board` becomes the single source. Its layout mirrors the live install: `board/` ↔ `~/.local/share/tmux-dash`, `tools/` ↔ `~/.local/share/tmux-tools`, `bin/<script>` ↔ `~/.local/bin/<script>`, `claude/` ↔ `~/.claude/{orchestrator.md,worker.md,hooks/<toolkit hooks>}`. Each live path is replaced by a symlink into the repo, so the `main` checkout is what runs. The board docs leave master-gcp-repo through an MR into `dev3`, and the ideas move from `~/.claude/ideas/master-gcp-repo.md` to `~/.claude/ideas/agent-board.md`.

**Tech Stack:** git, zsh, rsync, tmux, Python 3 `unittest`, `agent-ci` (gitlab-ci-loop) for the monorepo MR.

**Spec:** none. This is an ops plan; the decisions are recorded below.

## Global Constraints

- **Repo:** `~/agent-board`, default branch `main`, local only (no remote, no GitLab project).
- **Repo layout (exact):**
  - `board/` ← `~/.local/share/tmux-dash` (the `.py` files, `index.html`, `vendor/`, `tests/`)
  - `tools/tests/` ← `~/.local/share/tmux-tools/tests` (including `fixtures/`)
  - `bin/` ← `~/.local/bin/{dev,claude-orchestrator,tmux-ctl,tmux-dash,tmux-agent-cleanup,tmux-dev-layout,tmux-jump,tmux-session-closed,tmux-teammate-window,tmux-web-attach}` (not `tmux` or `claude`, which are binaries)
  - `claude/orchestrator.md`, `claude/worker.md` ← `~/.claude/`
  - `claude/hooks/{artifact-register.sh,bash-mirror.sh,kill-guard.sh}` ← `~/.claude/hooks/` (the toolkit hooks the `tools/tests` cover; `~/.claude/settings.json` is not changed)
  - `docs/superpowers/specs/`, `docs/superpowers/plans/`, `docs/superpowers/model-routing.json`
- **Never copied:** `*.bak*`, `*.after-*`, `*.before-*`, `*.pre-repo-*`, `*.next`, `__pycache__/`, `tests.bak*/`, `.lock` files.
- **Live swap backups:** each replaced live path is first renamed to `<path>.pre-repo-20261016`; never delete them in this plan.
- **Monorepo rules (master-gcp-repo):** feature branch `agent/remove-agent-board-docs` from `origin/dev3`, MR into `dev3` only through `agent-ci`; never push to `dev3`/`staging`/`main`; conventional commit with scope.
- **Never** `pkill`/`killall` by pattern; restart the board only with `tmux-dash stop && tmux-dash start`.
- Commits in `~/agent-board` end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**User decisions (already made):**
- "Whole toolkit": the board plus tmux-tools, the `bin/` scripts, `orchestrator.md` and `worker.md` move. `~/.claude/CLAUDE.md`, skills and settings stay where they are.
- Repo at `~/agent-board`, local only: the user creates any GitLab project later.
- Live paths become symlinks into the repo checkout.
- Board docs are copied to the new repo, then removed from master-gcp-repo `dev3` through an MR; `agent/board-agent-controls` (never pushed) is deleted locally after its spec and plan are copied.
- master-gcp-repo is for monorepo work only.

---

### Task 0: Create the `~/agent-board` repo

**Goal:** A `main` branch in `~/agent-board` whose first commit holds every toolkit file, the eight board docs and this plan, byte-identical to their sources.

**Files:**
- Create: `~/agent-board/{board,tools,bin,claude}/…` (copied), `~/agent-board/docs/superpowers/{specs,plans}/…` (copied), `~/agent-board/.gitignore`, `~/agent-board/README.md`, `~/agent-board/CLAUDE.md`
- Modify: `~/agent-board/docs/superpowers/plans/2026-10-16-board-agent-controls.md` (Global Constraints, first bullet)

**Acceptance Criteria:**
- [ ] `diff -rq` between each repo directory and its live source, with the never-copied patterns excluded, prints nothing.
- [ ] `docs/superpowers/` holds the 3 specs (`handoff-relay-artifacts-panel`, `board-layout-navigation`, `board-agent-controls`), their 3 plans and `.tasks.json` files, `model-routing.json`, and this plan. The two `tasks.json` files that are modified but uncommitted in the master-gcp-repo main checkout are copied from the working tree, not from git.
- [ ] `git -C ~/agent-board status --short` is empty after the commit, and `git ls-files | grep -E 'bak|__pycache__'` prints nothing.
- [ ] Both test suites pass when run from the repo: `python3 -m unittest discover -s board/tests` is OK, and `zsh tools/tests/run-all.zsh` exits 0.
- [ ] The group A plan's first Global Constraint now describes the repo workflow (text in Step 5).

**Verify:** `cd ~/agent-board && git log --oneline && python3 -m unittest discover -s board/tests 2>&1 | tail -1` → one commit, `OK`

**Steps:**

- [ ] **Step 1: Copy the code** (the plan file already sits in `~/agent-board/docs/superpowers/plans/`):

```bash
set -e
cd ~/agent-board
X=(--exclude='*.bak*' --exclude='*.after-*' --exclude='*.before-*' --exclude='*.pre-repo-*' --exclude='*.next' --exclude='__pycache__' --exclude='tests.bak*' --exclude='*.lock')
rsync -a "${X[@]}" ~/.local/share/tmux-dash/ board/
rsync -a "${X[@]}" ~/.local/share/tmux-tools/ tools/
mkdir -p bin claude/hooks
for f in dev claude-orchestrator tmux-ctl tmux-dash tmux-agent-cleanup tmux-dev-layout tmux-jump tmux-session-closed tmux-teammate-window tmux-web-attach; do cp -p ~/.local/bin/$f bin/$f; done
cp -p ~/.claude/orchestrator.md ~/.claude/worker.md claude/
for h in artifact-register.sh bash-mirror.sh kill-guard.sh; do cp -p ~/.claude/hooks/$h claude/hooks/$h; done
```

- [ ] **Step 2: Copy the docs**

```bash
set -e
cd ~/agent-board
M=~/master-gcp-repo
mkdir -p docs/superpowers/specs docs/superpowers/plans
git -C $M fetch -q origin dev3
for p in specs/2026-10-16-handoff-relay-artifacts-panel-design.md specs/2026-10-16-board-layout-navigation-design.md \
         plans/2026-10-16-handoff-relay-artifacts-panel.md plans/2026-10-16-board-layout-navigation.md model-routing.json; do
  git -C $M show origin/dev3:docs/superpowers/$p > docs/superpowers/$p
done
# the main checkout's tasks.json files carry uncommitted status updates: take the working-tree versions
cp -p $M/docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md.tasks.json docs/superpowers/plans/
cp -p $M/docs/superpowers/plans/2026-10-16-board-layout-navigation.md.tasks.json docs/superpowers/plans/
for p in specs/2026-10-16-board-agent-controls-design.md plans/2026-10-16-board-agent-controls.md plans/2026-10-16-board-agent-controls.md.tasks.json; do
  git -C $M show agent/board-agent-controls:docs/superpowers/$p > docs/superpowers/$p
done
```

- [ ] **Step 3: Repo files**

`~/agent-board/.gitignore`:

```gitignore
__pycache__/
*.bak*
*.pre-repo-*
*.next
.superpowers/
```

`~/agent-board/README.md`:

```markdown
# agent-board

The tmux `dev` orchestration toolkit and the Agent Board web UI.

| Repo path | Live path (symlink into this repo) |
| --- | --- |
| `board/` | `~/.local/share/tmux-dash` |
| `tools/` | `~/.local/share/tmux-tools` |
| `bin/<script>` | `~/.local/bin/<script>` |
| `claude/orchestrator.md`, `claude/worker.md` | `~/.claude/orchestrator.md`, `~/.claude/worker.md` |
| `claude/hooks/<hook>` | `~/.claude/hooks/<hook>` |

The checked-out branch is what runs. Restart the board after server changes: `tmux-dash stop && tmux-dash start`.
```

`~/agent-board/CLAUDE.md`:

```markdown
# agent-board

The tmux `dev` toolkit (`bin/`), the Agent Board (`board/`), its tests (`tools/tests/`, `board/tests/`), and the lead and worker rules (`claude/`). See README.md for how repo paths map to live paths.

## Commands

    python3 -m unittest discover -s board/tests     # board (server, artifacts, ideas, relay…)
    zsh tools/tests/run-all.zsh                     # tmux-ctl, dev layout, hooks (scratch tmux server)

## Rules

- The live install is symlinked to this checkout: whatever branch is checked out here runs for every tmux session. Keep `main` working; switch back to `main` when a branch is done.
- Specs and plans go in `docs/superpowers/`; ideas for this project go in `~/.claude/ideas/agent-board.md`.
- Conventional commits with scope: `feat(board): …`, `fix(tmux-ctl): …`, `docs(plan): …`.
```

- [ ] **Step 4: Check the copies match**

```bash
cd ~/agent-board
E=(-x '*.bak*' -x '*.after-*' -x '*.before-*' -x '__pycache__' -x 'tests.bak*' -x '*.lock')
diff -rq "${E[@]}" ~/.local/share/tmux-dash board
diff -rq "${E[@]}" ~/.local/share/tmux-tools tools
for f in bin/*; do cmp -s "$f" ~/.local/bin/${f:t} || echo "DIFF $f"; done
for f in claude/*.md; do cmp -s "$f" ~/.claude/${f:t} || echo "DIFF $f"; done
for f in claude/hooks/*; do cmp -s "$f" ~/.claude/hooks/${f:t} || echo "DIFF $f"; done
```

Expected: no output.

- [ ] **Step 5: Update the group A plan for the repo.** In `docs/superpowers/plans/2026-10-16-board-agent-controls.md`, replace the bullet that starts `- **Not under git:**` with:

```markdown
- **Repo:** the code lives in `~/agent-board` (`board/`, `bin/`, `claude/`). The live paths `~/.local/share/tmux-dash`, `~/.local/bin/tmux-*` and `~/.claude/orchestrator.md` are symlinks into that checkout, so edits are live at once. Work on branch `agent/board-agent-controls` in `~/agent-board` (`git switch -c agent/board-agent-controls`), commit after each task (`feat(board): …`), and skip the plan's `.bak-20261016-agentctl` backup steps. Paths below under `~/.local/share/tmux-dash/` are `board/` in the repo, and `~/.claude/orchestrator.md` is `claude/orchestrator.md`.
```

and in the test-command bullet replace `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests"` with `tmux-ctl run tests "cd ~/agent-board && python3 -m unittest discover -s board/tests"`. Make the same replacement in `2026-10-16-board-agent-controls.md.tasks.json` wherever the old test command appears (`grep -n 'discover -s tests' docs/superpowers/plans/2026-10-16-board-agent-controls.md*` → no match afterwards).

- [ ] **Step 6: Run both suites from the repo**

Run: `cd ~/agent-board && python3 -m unittest discover -s board/tests 2>&1 | tail -3` → `OK`
Run: `tmux-ctl run tests "cd ~/agent-board && zsh tools/tests/run-all.zsh"` → exit 0

The suites still exercise the live `~/.local/bin` scripts at this point. Task 1 makes those the repo's own files.

- [ ] **Step 7: Commit**

```bash
cd ~/agent-board && git init -q -b main && git add -A
git ls-files | grep -E 'bak|__pycache__|\.lock$' && echo "UNEXPECTED FILES" && exit 1
git commit -q -m "chore: import the Agent Board toolkit from ~/.local and master-gcp-repo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline
```

```json:metadata
{"files": ["~/agent-board/board", "~/agent-board/tools", "~/agent-board/bin", "~/agent-board/claude", "~/agent-board/docs/superpowers", "~/agent-board/.gitignore", "~/agent-board/README.md", "~/agent-board/CLAUDE.md"], "verifyCommand": "cd ~/agent-board && git log --oneline && python3 -m unittest discover -s board/tests 2>&1 | tail -1", "acceptanceCriteria": ["diff -rq of each repo dir vs live source (excludes applied) prints nothing", "docs/superpowers holds 3 specs, 3 plans + tasks.json (working-tree versions for the 2 modified), model-routing.json, this plan", "clean status after commit; no bak/__pycache__ tracked", "board unittest OK and tools run-all exit 0 from the repo", "group A plan constraint and test command updated to the repo workflow"], "modelTier": "mechanical"}
```

---

### Task 1: Point the live install at the repo

**Goal:** Every live toolkit path is a symlink into `~/agent-board`, the board restarts from it, and the tools behave as before.

**Files:**
- Modify (rename to `*.pre-repo-20261016` and replace with a symlink): `~/.local/share/tmux-dash`, `~/.local/share/tmux-tools`, the 10 `~/.local/bin` scripts, `~/.claude/orchestrator.md`, `~/.claude/worker.md`, and `~/.claude/hooks/{artifact-register.sh,bash-mirror.sh,kill-guard.sh}`

**Acceptance Criteria:**
- [ ] Each of the 17 live paths is a symlink whose `readlink` is the matching `~/agent-board/...` path, and each has a `*.pre-repo-20261016` sibling.
- [ ] The board answers HTTP 200 at `http://127.0.0.1:${TMUX_DASH_PORT:-7700}/$(cat ~/.local/state/tmux-dash/token)/` after `tmux-dash stop && tmux-dash start`, and `ps -o command= -p <server pid>` shows it was started after the swap.
- [ ] `tmux-ctl list` prints the session's windows, and a `tmux-ctl run tests "echo ok"` returns `ok`.
- [ ] Both suites pass again after the swap: `python3 -m unittest discover -s ~/.local/share/tmux-dash/tests` and `zsh ~/.local/share/tmux-tools/tests/run-all.zsh`.

**Verify:** `for p in ~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.local/bin/tmux-ctl ~/.claude/orchestrator.md; do readlink "$p"; done` → four `~/agent-board/...` paths

**Steps:**

- [ ] **Step 1: Re-check that nothing changed since Task 0.** Run the Task 0 Step 4 diff block again. If it prints anything, stop and report it to the lead; do not swap.

- [ ] **Step 2: Swap** (each rename and its symlink run back to back):

```bash
set -e
R=~/agent-board; S=pre-repo-20261016
swap() { [[ -L "$1" ]] && { echo "already a link: $1"; return; }; mv "$1" "$1.$S"; ln -s "$2" "$1"; }
swap ~/.local/share/tmux-dash  $R/board
swap ~/.local/share/tmux-tools $R/tools
for f in dev claude-orchestrator tmux-ctl tmux-dash tmux-agent-cleanup tmux-dev-layout tmux-jump tmux-session-closed tmux-teammate-window tmux-web-attach; do swap ~/.local/bin/$f $R/bin/$f; done
swap ~/.claude/orchestrator.md $R/claude/orchestrator.md
swap ~/.claude/worker.md       $R/claude/worker.md
for h in artifact-register.sh bash-mirror.sh kill-guard.sh; do swap ~/.claude/hooks/$h $R/claude/hooks/$h; done
```

The old `*.bak-*` files inside `~/.local/share/tmux-dash` now live in `~/.local/share/tmux-dash.pre-repo-20261016`. Nothing is deleted.

- [ ] **Step 3: Check every link**

```bash
for p in ~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.local/bin/{dev,claude-orchestrator,tmux-ctl,tmux-dash,tmux-agent-cleanup,tmux-dev-layout,tmux-jump,tmux-session-closed,tmux-teammate-window,tmux-web-attach} ~/.claude/{orchestrator.md,worker.md} ~/.claude/hooks/{artifact-register.sh,bash-mirror.sh,kill-guard.sh}; do
  t=$(readlink "$p"); [[ "$t" == $HOME/agent-board/* && -e "$p" && -e "$p.pre-repo-20261016" ]] && echo "ok $p" || echo "BAD $p -> $t"
done
```

Expected: 17 `ok` lines.

- [ ] **Step 4: Restart the board and check it**

```bash
tmux-dash stop && tmux-dash start
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${TMUX_DASH_PORT:-7700}/$(cat ~/.local/state/tmux-dash/token)/"
```

Expected: `200`. Restarting ends the `_web-*` viewer sessions; the user reloads the board tab.

- [ ] **Step 5: Tools and suites through the live paths**

Run: `tmux-ctl list` → the window list. Run: `tmux-ctl run tests "echo ok"` → `ok`.
Run: `cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests 2>&1 | tail -1` → `OK`
Run: `tmux-ctl run tests "zsh ~/.local/share/tmux-tools/tests/run-all.zsh"` → exit 0

**Rollback (only if Step 4 or 5 fails and can't be fixed by a path fix):** for each path, `rm "$p" && mv "$p.pre-repo-20261016" "$p"`, then restart the board, and report to the lead.

```json:metadata
{"files": ["~/.local/share/tmux-dash", "~/.local/share/tmux-tools", "~/.local/bin/*", "~/.claude/orchestrator.md", "~/.claude/worker.md", "~/.claude/hooks/*"], "verifyCommand": "for p in ~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.local/bin/tmux-ctl ~/.claude/orchestrator.md; do readlink \"$p\"; done", "acceptanceCriteria": ["17 live paths are symlinks into ~/agent-board, each with a .pre-repo-20261016 sibling", "board HTTP 200 after restart", "tmux-ctl list and run work", "board unittest OK and tools run-all exit 0 through the live paths"], "modelTier": "standard"}
```

---

### Task 2: Move the ideas to the agent-board project

**Goal:** All Agent Board ideas live in `~/.claude/ideas/agent-board.md`, the master-gcp-repo inbox is left with its header only, and the ideas already taken up are marked.

**Files:**
- Create: `~/.claude/ideas/agent-board.md`
- Modify: `~/.claude/ideas/master-gcp-repo.md` (backup `master-gcp-repo.md.bak-20261016-move`)

**Acceptance Criteria:**
- [ ] `agent-board.md` starts `# Ideas: agent-board` and holds all 12 entries from the old file, in order, each with its detail lines.
- [ ] These entries are `[x]` with their target: "ui button to shutdown one-off agents" and "restart orchestrator shouldk instead be a right click" → `docs/superpowers/specs/2026-10-16-board-agent-controls-design.md`; "all agent board code should really be in its own gitlab repo" → `docs/superpowers/plans/2026-10-16-agent-board-repo-migration.md`. The four existing `[x]` entries keep their targets.
- [ ] `master-gcp-repo.md` contains only `# Ideas: master-gcp-repo` and a blank line.
- [ ] `python3 -I ~/.local/share/tmux-dash/ideas.py list --project agent-board` (or the board's Ideas box on the agent-board project) shows the open ones.

**Verify:** `grep -c '^- \[' ~/.claude/ideas/agent-board.md; grep -c '^- \[' ~/.claude/ideas/master-gcp-repo.md` → `12`, `0`

**Steps:**

- [ ] **Step 1: Move**

```bash
set -e
cd ~/.claude/ideas
cp -p master-gcp-repo.md master-gcp-repo.md.bak-20261016-move
python3 - <<'EOF'
from pathlib import Path
src = Path("master-gcp-repo.md")
lines = src.read_text().splitlines()
assert lines[0] == "# Ideas: master-gcp-repo", lines[0]
body = lines[1:]
A = "docs/superpowers/specs/2026-10-16-board-agent-controls-design.md"
M = "docs/superpowers/plans/2026-10-16-agent-board-repo-migration.md"
marks = {"I need a ui button to shutdown one-off agents": A,
         "restart orchestrator shouldk instead be a right click": A,
         "all agent board code should really be in its own gitlab repo": M}
out, hit = [], set()
for l in body:
    for key, target in marks.items():
        if l.startswith("- [ ] ") and key in l:
            l = "- [x] " + l[6:] + f" → {target}"; hit.add(key)
    out.append(l)
assert hit == set(marks), set(marks) - hit
Path("agent-board.md").write_text("# Ideas: agent-board\n" + "\n".join(out) + "\n")
src.write_text("# Ideas: master-gcp-repo\n\n")
EOF
```

- [ ] **Step 2: Check** with the Verify command, then `head -20 ~/.claude/ideas/agent-board.md`. Check how `ideas.py` reads a project: `python3 -I ~/.local/share/tmux-dash/ideas.py --help`. Use its list subcommand if there is one; otherwise check the board's Ideas box once Task 4 has created the project.

```json:metadata
{"files": ["~/.claude/ideas/agent-board.md", "~/.claude/ideas/master-gcp-repo.md"], "verifyCommand": "grep -c '^- \\[' ~/.claude/ideas/agent-board.md; grep -c '^- \\[' ~/.claude/ideas/master-gcp-repo.md", "acceptanceCriteria": ["agent-board.md has the header and all 12 entries in order with details", "three entries newly [x] with targets; four existing [x] unchanged", "master-gcp-repo.md holds only its header", "the ideas show for the agent-board project"], "modelTier": "mechanical"}
```

---

### Task 3: Remove the board docs from master-gcp-repo

**Goal:** An MR into `dev3` deletes the six Agent Board docs from master-gcp-repo, the local-only `agent/board-agent-controls` branch and its worktree are gone, and the main checkout's two modified `tasks.json` files are restored.

**Files:**
- Delete (in master-gcp-repo, branch `agent/remove-agent-board-docs`): `docs/superpowers/specs/2026-10-16-handoff-relay-artifacts-panel-design.md`, `docs/superpowers/specs/2026-10-16-board-layout-navigation-design.md`, `docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md{,.tasks.json}`, `docs/superpowers/plans/2026-10-16-board-layout-navigation.md{,.tasks.json}`
- Keep: `docs/superpowers/model-routing.json` (the monorepo's own plans use it)

**Acceptance Criteria:**
- [ ] Before anything is deleted, each of the eight docs is checked byte-for-byte against its copy in `~/agent-board` (`cmp`). The two working-tree `tasks.json` files are compared with their working-tree versions.
- [ ] MR into `dev3` from `agent/remove-agent-board-docs`, titled `docs: move Agent Board specs and plans to the agent-board repo`, with a green pipeline. `agent-ci cycle` exits 0. Its URL is reported.
- [ ] `git worktree list` no longer shows `.claude/worktrees/board-agent-controls`, and `git branch --list agent/board-agent-controls` prints nothing.
- [ ] `git -C ~/master-gcp-repo status --short` is empty, after the two `tasks.json` files are restored.

**Verify:** `git -C ~/master-gcp-repo worktree list; git -C ~/master-gcp-repo status --short` → no board-agent-controls worktree; empty status

**Steps:**

- [ ] **Step 1: Check the copies**

```bash
M=~/master-gcp-repo; A=~/agent-board/docs/superpowers
git -C $M fetch -q origin dev3
for p in specs/2026-10-16-handoff-relay-artifacts-panel-design.md specs/2026-10-16-board-layout-navigation-design.md plans/2026-10-16-handoff-relay-artifacts-panel.md plans/2026-10-16-board-layout-navigation.md; do
  git -C $M show origin/dev3:docs/superpowers/$p | cmp -s - $A/$p && echo "ok $p" || echo "DIFF $p"; done
for p in plans/2026-10-16-handoff-relay-artifacts-panel.md.tasks.json plans/2026-10-16-board-layout-navigation.md.tasks.json; do
  cmp -s $M/docs/superpowers/$p $A/$p && echo "ok $p" || echo "DIFF $p"; done
for p in specs/2026-10-16-board-agent-controls-design.md plans/2026-10-16-board-agent-controls.md; do
  git -C $M show agent/board-agent-controls:docs/superpowers/$p | cmp -s - $A/$p && echo "ok $p" || echo "DIFF $p (expected for the plan: Task 0 Step 5 edited it)"; done
```

Expected: `ok` for every line, except `plans/2026-10-16-board-agent-controls.md`, which shows `DIFF` because Task 0 Step 5 edited it. For that file, `git -C ~/agent-board log --oneline -- docs/superpowers/plans/2026-10-16-board-agent-controls.md` must show the import commit. Any other `DIFF` means stop and report.

- [ ] **Step 2: Branch and delete**

```bash
set -e
cd ~/master-gcp-repo
git worktree add -q .claude/worktrees/remove-agent-board-docs -b agent/remove-agent-board-docs origin/dev3
cd .claude/worktrees/remove-agent-board-docs
git rm -q docs/superpowers/specs/2026-10-16-handoff-relay-artifacts-panel-design.md docs/superpowers/specs/2026-10-16-board-layout-navigation-design.md \
  docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md.tasks.json \
  docs/superpowers/plans/2026-10-16-board-layout-navigation.md docs/superpowers/plans/2026-10-16-board-layout-navigation.md.tasks.json
grep -rn "board-layout-navigation\|handoff-relay-artifacts-panel" docs mkdocs.yml 2>/dev/null && { echo "dangling references"; exit 1; } || true
git commit -q -m "docs: move Agent Board specs and plans to the agent-board repo

The Agent Board toolkit now lives in its own repo (~/agent-board); this
repo keeps only monorepo work.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If the grep finds references (an mkdocs nav entry or a link), remove them, `git commit --amend --no-edit`, and continue.

- [ ] **Step 3: Local checks, then the MR** (from the new worktree; it is clean):

Run: `agent-ci check` → all PASS
Run: `agent-ci cycle 2>&1 | tail -30; echo "exit ${pipestatus[1]}"` → `green ✓` and `exit 0`. Report the MR URL to the lead. Do not run `finish`; the lead runs it.

- [ ] **Step 4: Clean up the old branch, its worktree and the main checkout**

```bash
set -e
cd ~/master-gcp-repo
git worktree remove .claude/worktrees/board-agent-controls
git branch -D agent/board-agent-controls
git restore docs/superpowers/plans/2026-10-16-board-layout-navigation.md.tasks.json docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md.tasks.json
git worktree list; git status --short
```

```json:metadata
{"files": ["~/master-gcp-repo/docs/superpowers/specs", "~/master-gcp-repo/docs/superpowers/plans"], "verifyCommand": "git -C ~/master-gcp-repo worktree list; git -C ~/master-gcp-repo status --short", "acceptanceCriteria": ["all eight docs cmp-identical to the agent-board copies (group A plan: edited copy, import commit present)", "MR into dev3 from agent/remove-agent-board-docs green, URL reported", "board-agent-controls worktree and branch removed", "main checkout status clean"], "modelTier": "standard"}
```

---

### Task 4 (done before execution): the agent-board project

The planning session (master-gcp-repo) started the `agent-board` dev project, and its orchestrator runs this plan from the handoff `~/.claude/handoffs/2026-10-16-agent-board-migration.md`. Nothing to do here; after Task 3, continue with the handoff's Next steps (group A).
