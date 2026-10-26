---
name: "requesting-code-review-extras"
description: Local additions to superpowers-extended-cc:requesting-code-review. Use together with requesting-code-review, every time it runs, before dispatching the reviewer. It adds evidence checks to the reviewer prompt. Fixtures must be captured from the real system, a test must exercise the artefact itself and not a copy or a stubbed external command, visibility checks must measure what the user sees, a pass on fresh scratch state or on the author's own HOME is flagged, and an all/none/every claim, including a secret-absence test, must rest on uncapped output with its count in every output mode. It also checks runbook preconditions, inputs agents cannot read, and endpoint trust, and pins the review range to the merge-base.
---

# requesting-code-review extras

Load alongside `superpowers-extended-cc:requesting-code-review`. Paste the section "Add to the reviewer prompt" into the reviewer's prompt, after "What to Check". The base skill's flow is unchanged.

Tests prove behaviour only on the state they run against. A hand-written fixture or a copy of the artefact passes while the real thing is broken, so the reviewer checks the evidence, not only the code.

## Add to the reviewer prompt

```
## Evidence checks (tests, fixtures, UI checks)

For every test or check in the diff, report one line per item:

1. Fixture origin. Is the fixture captured from the real system (a real UI capture, the config line as installed, a real log) or hand-written? Hand-written stand-ins are an Important finding unless the diff shows how the real one was captured. Example: an input-line detector tested against a layout the installed CLI no longer draws.
2. Artefact under test. Does the test load the deployed artefact itself, or a copy or re-implementation of it? Flag any test that registers, sources or inlines its own version. Example: a hook test that registers a differently quoted command than the one installed hid a shell-injection bug. The same applies to an external command whose flags decide the outcome (git, terraform, gcloud, SQL): if every test stubs that call, ask for one test that runs the real command on a scratch fixture (temporary repo, local file, test database). Where the command needs real cloud state and tests must not make cloud calls, accept instead: tests that pin the exact argv, plus one real run named as a post-apply gate in the plan or runbook, with its expected output. Neither present is a finding. Example: gate tests that stubbed `git diff --name-only` all passed, while git's rename detection listed a moved file only by its destination.
3. User-experienced check. Does a visibility or layout check measure what the user sees? `elementFromPoint` at the element's centre, or the element's `hidden` attribute. Some probes cannot return the failing value: `getBoundingClientRect` reports full size for an element an ancestor clips to 2px, and `offsetParent` is always null for a `position: fixed` element. A probe result the check could not explain ("could not place that text") under a PASS is a finding, not a footnote.
4. State. Did a passing e2e run only on fresh scratch state? Say so, and name the long-lived condition it never met (data across midnight, several agents, a worktree). Did the suite pass only on the author's machine? Flag tests that hard-code paths under HOME (`~/.local/bin`, `~/.config`), including tests that arrived through a merge, and ask for one run with a scratch HOME and a PATH without user-local bins.
5. Universal claims. Any finding of the form all / none / every / only must rest on uncapped output, with the total count stated (`grep -c`, or the full listing). Output cut with `head` shows that something exists, never that nothing else does. The same holds for a test that claims a value never reaches the output (a secret, a token): if it ran at one verbosity only, ask for hit counts of a planted dummy value under each output mode (pytest: default, `-vv`, `-l`, `--tb=long`) and one real failing call. Truncated reprs hide leaks at the default.

## Other checks (any diff)

6. Inputs agents cannot read. A finding that depends on real data the agents cannot read (CI variables, production config) is not a deferred minor. Write it as an unchecked merge-gate item for the MR description, with the exact command a human runs to settle it. A clean auto-merge says nothing about semantics: where branches overlap, read the auto-merged files that hold tests or shared helpers, not only the conflicted ones.
7. Runbook preconditions. Every precondition in a runbook or operator doc ("must exist", "must be set", "is configured") names the command or file that creates it and the shape it needs. If the doc cannot derive it from source, it is marked as a human gate and says why. Treat "X must already exist" as a claim to resolve against the repo.
8. Endpoint trust. A finding that recommends validating a configurable endpoint must pin the part of the host only the owner controls (an exact allowlist, the project hash or number). A name pattern on a shared platform domain (`*.run.app`) matches anyone's service of that name.

Cite file:line for each finding.
```

## Before you dispatch

Check that the prompt you send contains the eight numbered checks. If the diff touches no tests, fixtures or UI checks, skip checks 1–4 and say so in the dispatch note; checks 5–8 apply to every review.

Pin the range to where the branch diverged: `BASE_SHA=$(git merge-base origin/<target> HEAD)`, or tell the reviewer to diff `<target>...HEAD` (three dots). A two-dot diff against a moving branch name (`origin/dev3..HEAD`) also shows everything the target gained since, reversed.
