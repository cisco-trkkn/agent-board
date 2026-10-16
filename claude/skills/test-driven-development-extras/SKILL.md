---
name: "test-driven-development-extras"
description: Local additions to superpowers-extended-cc:test-driven-development. Use together with superpowers-extended-cc:test-driven-development, every time it runs, before the first RED run of any test. It adds one rule for code under test that has side effects (creates windows, worktrees or processes, writes to the network or outside a temp dir). The isolation seam goes in before the RED run, and a leak check follows the run.
---

# test-driven-development extras

Load alongside `superpowers-extended-cc:test-driven-development`. The base skill's RED step ("run the test, watch it fail") stands; this file adds a gate in front of that run.

## Why

A RED run executes the code as it is now. When the check you are about to add does not exist yet, nothing stops a test case from going all the way through, so against a side-effecting command a red run is a live run.

Incident: argument checks were written for a command that creates a tmux window and a git worktree, then starts an agent session. The RED run came before any refusal or dry-run seam existed, so each of nine test cases launched a real worker. The user cleaned up windows, worktrees and branches by hand.

## 1. Seam before RED

Before the first RED run, ask: what does the code under test do when the new behaviour is absent? If the answer is a real side effect (process or window launch, worktree or branch creation, network write, write outside a temp dir), isolate first:

- a dry-run flag or env var that stops before the effect;
- an injected runner, or a stub binary first on `PATH`;
- or a scratch environment that cannot reach the real one, such as a tmux server on its own socket with `-L <sock> -f /dev/null`, or a throwaway repo and `$HOME`.

Add the seam as its own step, then run RED through it. RED means the assertion fails; it never means the real command ran.

## 2. Leak check after every run

After each RED and GREEN run, look for what the test should not have left behind and confirm it is gone: `tmux list-windows -a`, `git worktree list` and `git branch`, `pgrep -fl <command>`, new files outside the temp dir.

Example: the isolated run finishes with 22 of 22 passing, and `tmux list-windows -a | grep ' w[0-9]'` prints nothing.

A leak found means the seam is incomplete. Stop, clean up only what the test created, fix the seam, then rerun RED.

## Before you finish

Each test of a side-effecting command ran through a seam, and a leak check is on record after the run.
