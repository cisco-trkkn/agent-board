---
name: "test-driven-development-extras"
description: Local additions to superpowers-extended-cc:test-driven-development. Use together with superpowers-extended-cc:test-driven-development, every time it runs, before the first RED run of any test. Adds an isolation seam and leak check for side-effecting code, one real unpatched run, and evidence rules.
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

"External command" means any call into a platform the code does not own: a subprocess, and also an OS or stdlib platform API (`os.confstr`, `sysconf`, locale, keychain) or a network call. At least one test calls it unpatched on the host. A try/except around such a call also needs a test that the real call succeeds, because the except turns a failing call into silent wrong behaviour.

Example: a launchd fallback called `os.confstr('CS_DARWIN_USER_TEMP_DIR')` inside a try/except, and its unit test patched `os.confstr`. On the host, Python does not know that name and raises ValueError; the except swallowed it and the code silently used `/tmp`. Only a bare-environment e2e run, days later, showed it.

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

The test's own failure message can leak too. When the container is an environment or any mapping that may hold secrets, assert on the one key (`assertIsNone(env.get(k), k)`, or `assert env.get(k) is None, k`). Never assert membership in the whole mapping or compare two whole environments: on failure, `assertNotIn(k, env)` prints every variable, and RED fails by design. Example: a RED run of `assertNotIn("TF_DATA_DIR", env)` printed the whole process environment, a session token included.

## Before you finish

Each test of a side-effecting command ran through a seam, and a leak check is on record after the run. Where an external command's flags or a platform API call decide the outcome, one test runs it for real, unpatched. Each new test appears by name or count in the output you cite, and any test you could not run is reported as never executed. Each absence test was run in every output mode, with its hit counts.
