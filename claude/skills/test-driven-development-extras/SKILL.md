---
name: "test-driven-development-extras"
description: Local additions to superpowers-extended-cc:test-driven-development. Use together with superpowers-extended-cc:test-driven-development, every time it runs, before the first RED run of any test. For code under test that has side effects (creates windows, worktrees or processes, writes to the network or outside a temp dir), the isolation seam goes in before the RED run, and a leak check follows the run. When a decision rests on an external command's output, at least one test runs that command for real on a scratch fixture. A test counts as evidence only when its own results appear in the cited output, a test the host cannot run gets a runtime that can, and the repo's test lints pass before the RED commit. A test that asserts a value is absent from output runs in every output mode, with a planted dummy value.
---

# test-driven-development extras

Load alongside `superpowers-extended-cc:test-driven-development`. The base skill's RED step ("run the test, watch it fail") stands; this file adds a gate in front of that run (sections 1–2), a limit on stubbing (section 3), rules for what counts as a run (sections 4–5), and a rule for absence tests (section 6).

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

## 3. One real run of a deciding external command

A stub removes exactly the behaviour it replaces. When the code's decision rests on an external command's output (git, terraform, gcloud, a SQL query), write at least one test that runs the command for real on a scratch fixture: a temporary repo, a local file, a test database. Stub only the network or cost-bearing parts around it.

Example: every test of a release gate stubbed `git diff --name-only` with a hand-picked file list and passed. A test in a temporary repo showed that git's default rename detection lists a moved file only by its destination; the fix was `--no-renames`.

When the command needs real cloud state and tests must not make cloud calls, pin the exact argv in tests, and name one real run as a post-apply gate in the plan or runbook, with its expected output. Say in the report that the real run is still owed.

## 4. A run counts only if its results are in the output

Green output proves only what the command collected. When you add a test file, cite output that shows that file's tests: their ids, or a collected count that includes them. If the project's check runner does not select the new test (or the file you changed), run the test directly and cite that, or wire it in.

Example: a branch reported `agent-ci check` 15/16 passing; the runner had no check for the new test directory, and a direct run showed 4 of 66 failing.

A test the host cannot run (an old bash, a missing service) is not "covered by CI". Find a runtime that can run it first: a container matching the CI image, or a newer binary from brew. If none works, report it as "never executed". Example: seven tests needing bash 4 were labelled CI-only for two review rounds; a `python:3.11` container ran them in minutes and found three fixture bugs.

## 5. House rules before the RED commit

Before committing the RED test, run the repo's own lints and health checks that cover test files (the mapped `agent-ci check`, or the repo's equivalent). A test has to pass the repo's rules for test code as well as fail for the right reason. Fixing it before the commit is a free edit; after it, a repo that keeps test-before-fix commits needs a fixup rebase.

## 6. Absence tests run in every output mode

A test that asserts a value never reaches the output (a secret, a token, a password) proves it only for the output mode it ran in. Display defaults truncate long reprs, so a leak can be invisible at default verbosity and plain under another flag.

Plant a known dummy value, make the case fail, and count its hits in each mode the tool offers: for pytest, default, `-vv`, `-l` (`--showlocals`) and `--tb=long`. Also make one real failing call where the value travels (a refused connection to a closed local port, not a stubbed client: stubs hide the frames that print a request's headers). Then run the tests from the guard's own folder and from a parent folder, because a conftest guard behaves differently by collection root. A pass at the default mode alone doesn't count.

Example: a redaction test passed by default; with `-l` a local still held the raw string, and with `-vv` a config dataclass repr printed every token.

## Before you finish

Each test of a side-effecting command ran through a seam, and a leak check is on record after the run. Where an external command's flags decide the outcome, one test runs it for real. Each new test appears by name or count in the output you cite, and any test you could not run is reported as never executed. Each absence test was run in every output mode, with its hit counts.
