---
name: "requesting-code-review-extras"
description: Local additions to superpowers-extended-cc:requesting-code-review. Use together with requesting-code-review, every time it runs, before dispatching the reviewer. It adds five evidence checks to the reviewer prompt. Fixtures must be captured from the real system, a test must exercise the artefact itself and not a copy or a stubbed external command, visibility checks must measure what the user sees, a pass on fresh scratch state is flagged, and an all/none/every claim must rest on uncapped output with its count.
---

# requesting-code-review extras

Load alongside `superpowers-extended-cc:requesting-code-review`. Paste the section "Add to the reviewer prompt" into the reviewer's prompt, after "What to Check". The base skill's flow is unchanged.

Tests prove behaviour only on the state they run against. A hand-written fixture or a copy of the artefact passes while the real thing is broken, so the reviewer checks the evidence, not only the code.

## Add to the reviewer prompt

```
## Evidence checks (tests, fixtures, UI checks)

For every test or check in the diff, report one line per item:

1. Fixture origin. Is the fixture captured from the real system (a real UI capture, the config line as installed, a real log) or hand-written? Hand-written stand-ins are an Important finding unless the diff shows how the real one was captured. Example: an input-line detector tested against a layout the installed CLI no longer draws.
2. Artefact under test. Does the test load the deployed artefact itself, or a copy or re-implementation of it? Flag any test that registers, sources or inlines its own version. Example: a hook test that registers a differently quoted command than the one installed hid a shell-injection bug. The same applies to an external command whose flags decide the outcome (git, terraform, gcloud, SQL): if every test stubs that call, ask for one test that runs the real command on a scratch fixture (temporary repo, local file, test database). Example: gate tests that stubbed `git diff --name-only` all passed, while git's rename detection listed a moved file only by its destination.
3. User-experienced check. Does a visibility or layout check measure what the user sees? `elementFromPoint` at the element's centre, not `getBoundingClientRect`, which reports full size for an element an ancestor clips to 2px.
4. State. Did a passing e2e run only on fresh scratch state? Say so, and name the long-lived condition it never met (data across midnight, several agents, a worktree).
5. Universal claims. Any finding of the form all / none / every / only must rest on uncapped output, with the total count stated (`grep -c`, or the full listing). Output cut with `head` shows that something exists, never that nothing else does.

Cite file:line for each finding.
```

## Before you dispatch

Check that the prompt you send contains the five numbered checks. If the diff touches no tests, fixtures or UI checks, skip checks 1–4 and say so in the dispatch note; check 5 applies to every review.
