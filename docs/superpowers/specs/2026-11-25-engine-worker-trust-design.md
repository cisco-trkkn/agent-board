# Engine worker folder trust

Date: 2026-11-25. Status: draft for the user's approval. Queue: right after engine part 3 (batch 2026-11-24-1).

## Problem

A worker the engine starts (through `tmux-ctl agent`, backend `claude-tmux`) in a folder that Claude Code has not trusted stops at Claude Code's dialog: "Quick safety check: Is this a project you created or one you trust? … ❯ No, exit / Yes, I trust this folder". Nobody answers it. The engine sees no heartbeat, records `job_failed` (`heartbeat_timeout`) after 2 minutes, then retries into the same dialog. The engine part 3 real run (2026-11-25, `docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md`) hit this twice.

Queue worktrees never see the dialog. Claude Code keys trust on the git repository root, and a worktree uses its main checkout's root. A new repo hits it: a project made by `/new-project`, a first spec in another repo, or a scratch clone. The user ruled (Discord, 2026-11-25) that trust must not be a manual step.

## What Claude Code offers (docs, 2026-11-25)

- No CLI flag, env var or settings key pre-accepts trust. `-p` and the SDK skip the dialog, but the engine's workers are interactive sessions.
- The one documented route (permissions.md, "Project allow rules and workspace trust") is `projects["<root>"].hasTrustDialogAccepted = true` in `~/.claude.json`, where `<root>` is the git repo root, or the folder itself outside a repo.
- Claude Code owns `~/.claude.json` and rewrites it. Running sessions can overwrite an edit. The docs say nothing about locking. Claude Code keeps 5 backups in `~/.claude/backups/`.

## Decisions

- D1. **Which folders.** The engine trusts, on its own, the repo root of every job it launches. That covers any repo a queued spec runs in: queueing the spec is the user's consent (user, Discord 2026-11-25, option 1). It also covers scratch folders the engine itself creates. The lead's teammates and `tmux-ctl agent` run by hand are unchanged: they trust nothing unless `--trust` is passed.
- D2. **How.** A new `tmux-ctl trust <dir>` resolves the root. Inside a git repo that is `git rev-parse --path-format=absolute --git-common-dir` minus its trailing `/.git`, so a worktree resolves to its main checkout. Otherwise it is the folder itself. A home directory is refused (`refusing to trust $HOME`, exit 2).
  - The write: read `~/.claude.json`, set only `projects[<root>].hasTrustDialogAccepted = true` (creating `projects[<root>]` when missing, every other key kept), write a temp file in the same directory with mode 0600, then rename it over the original.
  - After the rename, read the file back and check the key. If it is missing (a session rewrote the file in between), retry up to 3 times, 200 ms apart.
  - Output: `trusted <root>`, `already trusted <root>`, or `could not trust <root>: <why>` (exit 1).
  - A file that does not parse as JSON is never written: exit 1 with `~/.claude.json does not parse: not touched`.
  - Seams: `HOME` (where `.claude.json` lives) and `TC_CLAUDE_JSON` (a full path override, for tests).
- D3. **Where it runs.** `tmux-ctl agent --trust` calls `tmux-ctl trust <dir>` just before it starts `claude`. A failed trust is printed and the launch goes on: D4's check catches the result. The `claude-tmux` backend's `launch()` always passes `--trust`.
- D4. **Fail fast on the dialog.** While a job has no heartbeat yet, the `claude-tmux` backend reads the job's pane (`capture-pane -p`) on each engine tick. If the pane shows the line `Is this a project you created or one you trust?`, the job fails at once with reason `trust_dialog`. There is no 2-minute wait and no retry.
  - The spec parks as `awaiting_you`, with the question `Claude Code asks to trust <root> (folder <dir>)`, options `approve|fail`, and the line `I recommend: approve (low)`.
  - The engine posts it like other waits (the bridge's 🔐 / needs-you path).
  - On `engine signal <spec> approve`, the engine runs `tmux-ctl trust <dir>`, kills the stuck window by its pane pid, and starts a fresh attempt. It does not count against the retry budget. On `fail`, the spec fails with `failed — folder not trusted: <root>`.
- D5. **Fixture.** The dialog text in tests comes from the real pane captured in the part 3 real run (quoted in its note), stored as `engine/test/fixtures/trust-dialog.txt`. It is not hand-written.

## Acceptance

- A1. `tmux-ctl trust` against a scratch `TC_CLAUDE_JSON` holding other projects and keys:
  - It sets the one key and changes nothing else (a JSON deep-equal check of every other key), and the file mode is 0600.
  - A second call prints `already trusted`.
  - A worktree path resolves to its main checkout's root, and `$HOME` is refused.
  - A file that does not parse is left byte-identical.
  - A concurrent writer (a loop rewriting the file without the key during the call) ends either `trusted` after a retry, or `could not trust`. It is never a silent pass.
- A2. `tmux-ctl agent --trust` in a scratch repo calls trust before `claude` starts (a stub `claude` logs the order). Without `--trust`, nothing is written.
- A3. The engine with the fake backend and a pane stub that prints the fixture:
  - The job fails `trust_dialog` within one tick and the spec parks with the question and options.
  - `approve` writes trust and starts a fresh attempt, with the retry count unchanged.
  - `fail` ends the spec with the message.
  - `engine rebuild --check` returns 0.
- A4. Real run: a fresh `git init` scratch repo outside any trusted folder, with a scratch `TC_ENGINE_DIR`, `TC_STATE` and tmux server. It uses the real `~/.claude.json`, so the trust entry for the scratch root is written for real, and the note records the root. One real Haiku worker starts with no dialog and reaches its first heartbeat.
  - The scratch root's entry is then removed with `tmux-ctl trust --remove <dir>`, the same atomic path, which this spec also adds, used only for cleanup.
  - A second run with trust deliberately failing (`TC_CLAUDE_JSON` pointing at a read-only copy) shows the `trust_dialog` park within one tick.
- A5. Never touched by tests: the real `~/.claude.json`, except A4's two documented writes; the real engine dir; the real tmux server.

## Out of scope

- Trusting folders for the lead's own teammates (they start in trusted repos).
- Any use of `--dangerously-skip-permissions` or `-p` to dodge the dialog: holds and permission prompts must keep working.
