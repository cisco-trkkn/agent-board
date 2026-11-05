# E2E: dry run of a two-spec overnight queue

A manual procedure and its recorded result, not a test script: a real Claude run is not repeatable in CI, so this file is named to stay out of `run-all.zsh`. Run on 2026-11-05 against branch `feat/overnight-queue`.

## Setup

    W=/Users/francisco.ruiz/agent-board/.claude/worktrees/overnight-queue
    R=/private/tmp/claude-503/oq-run; Q=$R/Q
    mkdir -p $Q/docs/superpowers/specs $R/state $R/ideas $R/context
    cd $Q && git init -q -b main
    printf '# Q\n' > README.md
    printf '# a design\n\nAdd a line `alpha` to README.md.\n' > docs/superpowers/specs/2026-11-05-a-design.md
    printf '# b design\n\nAdd a line `beta` to README.md.\n'  > docs/superpowers/specs/2026-11-05-b-design.md
    cp $W/docs/superpowers/model-routing.json docs/superpowers/
    git add -A && git commit -qm init
    S=oq-$$; export TMUX=          # the tester's own pane is inside the live server
    ~/.local/bin/tmux -L $S -f /dev/null new-session -d -s oq -x 200 -y 50 -c $Q
    ~/.local/bin/tmux -L $S -f /dev/null send-keys -t oq "export TC_STATE=$R/state TC_IDEAS_DIR=$R/ideas TC_CONTEXT_DIR=$R/context AGENT_BOARD_TMUX_SOCKET=$S TMUX_DASH_TMUX_ARGS='-L $S'" Enter
    ~/.local/bin/tmux -L $S -f /dev/null send-keys -t oq "claude --model opus --append-system-prompt-file $W/claude/orchestrator.md" Enter

The lead runs with the user's real `~/.claude` config and plugins; only its system prompt file is the branch's. The "trust this folder" prompt was accepted for `Q` only.

## Run

First prompt, typed with `send-keys -l` then `Enter`:

    Create two pending tasks, `Plan & run: docs/superpowers/specs/2026-11-05-a-design.md` and `Plan & run: docs/superpowers/specs/2026-11-05-b-design.md` (b blocked by a), then run the Next steps round.

The lead created both tasks and asked one `AskUserQuestion` call with two questions (shown as one tabbed dialog). Answers given:

1. Integration, "Two specs are queued to run unattended, in order: … how should its branch be integrated by default?": option 1, `Merge to main locally (Recommended)` (the other options were `Push and open an MR` and `Keep the branch`).
2. Exceptions, "Should either queued spec … be integrated differently …?": `None`.

Then Submit. After that the lead planned, ran (implementer, task reviewer, final reviewer teammates per spec), merged and verified spec a, then spec b, and wrote the morning report, with no further question. Permission prompts in the scratch panes: none (the lead ran in auto mode), so nothing was approved or denied. Wall clock from first prompt (00:27:26) to the lead's final message (about 12:39 AM): about 12 minutes, under the 60-minute cap.

## Results

- Transcript: `/Users/francisco.ruiz/.claude/projects/-private-tmp-claude-503-oq-run-Q/fa017e1d-819d-4db9-904a-5d061379d94b.jsonl`. A `python3 -I` script counting `AskUserQuestion` tool_use entries printed `ask at line 82`, `report first write line 615`, `count 1`: exactly one, before the report's first write.
- `git -C Q log --oneline main`:

        cc8f73c docs: queue report 2026-11-05
        eca86ee docs(ledger): 2026-11-05-b
        1869f81 docs: add beta line to README
        62a8beb plan: spec b (beta line)
        0232ee9 docs(ledger): 2026-11-05-a
        5ce498c docs: add alpha line to README
        ddae1a9 plan: spec a (alpha line)
        0a31df0 init

- `README.md` on `main`: `# Q`, `alpha`, `beta`. `git status --short` in `Q` was empty and `git branch -a` listed only `main` (both worktrees and branches removed).
- `Q/docs/superpowers/reports/2026-11-05-queue.md` exists, with a summary table and one section per spec (`## 1. a design`, `## 2. b design`) plus a process note. Outcomes: `merged` at `0232ee9` (a) and `merged` at `eca86ee` (b), both fast-forwards.
- Observation: the report names the fast-forward tip (the ledger commit) as the merge sha, which satisfies "merged <sha>"; the outcome column and the sha sit in separate table columns rather than the literal text `merged <sha>`.

## Clean-up

- `tmux -L oq-19948 kill-server` was run. `list-panes` before it showed the lead's `claude` (pid 19962, the pane's process) and the tmux server (pid 19961). `ps -axo pid,command | grep -E 'oq-run|oq-19948'` after it printed nothing: no `claude` or `✦` process from the run survives.
- Live checkout `/Users/francisco.ruiz/agent-board`: `git status --short` shows ` M claude/orchestrator.md`. The file's mtime is 00:08:54, before the run began at 00:26, and nothing in this run wrote to the live checkout, so the change is not from the run. The worktree shows only the lead's own ` M docs/superpowers/plans/2026-11-05-overnight-queue.md.tasks.json`, unchanged from before.
