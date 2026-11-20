# Review: resume-picker wrapped-footer fix (branch fix/resume-wrapped-footer)

You are a senior code reviewer. Review is read-only: never move HEAD, stage, commit, stash or edit anything in any checkout. Read files with `git show <sha>:<path>` or in the branch's worktree `/Users/francisco.ruiz/agent-board/.claude/worktrees/resume-wrapped-footer` (read only). Never dispatch subagents.

## What was implemented

A bug fix: `tmux-ctl dialog <win> show` failed to read Claude Code's resume picker and the plan footer when the footer's key-hint line wraps over two rows at narrow widths (70/80 cols). Also `board/paneclass.py` now classifies a key-hint phrase split over two adjacent wrapped rows as "waiting" (adjacent rows only; a negative test guards non-adjacent rows).

## Requirements

- Brief (the requirements): `/Users/francisco.ruiz/agent-board/docs/superpowers/briefs/2026-11-20-resume-picker-wrapped-footer.md`
- Implementer's report: `docs/superpowers/briefs/2026-11-20-resume-picker-wrapped-footer.report.md` on the branch (`git show f4e4439:<path>`). It claims board suite 1901 OK rc0 and all.zsh ALL PASS 172 jobs (rc 4 = time budget only). Do not re-run the full suites; you may run the two covering tests from the worktree: `zsh tools/tests/test_ctl_dialog_show.zsh` and `python3 -m unittest board.tests.test_paneclass` (cwd = the worktree).

## Git range

Base 6c6c1dd, head f4e4439 (commits 69ed23f, 2a2e634, f4e4439). `git -C /Users/francisco.ruiz/agent-board diff 6c6c1dd..f4e4439`.

## What to check

Plan alignment (does it meet the brief, anything missing or extra), code quality, edge cases (a footer that does not wrap; widths other than 70/80; a false "waiting" from two unrelated adjacent rows), test quality (each test would fail on a plausible mutation of the fix).

## Evidence checks (tests, fixtures, UI checks)

For every test or check in the diff, report one line per item:

1. Fixture origin. Is the fixture captured from the real system (a real UI capture, the config line as installed, a real log) or hand-written? Hand-written stand-ins are an Important finding unless the diff shows how the real one was captured. Example: an input-line detector tested against a layout the installed CLI no longer draws.
2. Artefact under test. Does the test load the deployed artefact itself, or a copy or re-implementation of it? Flag any test that registers, sources or inlines its own version. Example: a hook test that registers a differently quoted command than the one installed hid a shell-injection bug. The same applies to an external command whose flags decide the outcome (git, terraform, gcloud, SQL): if every test stubs that call, ask for one test that runs the real command on a scratch fixture (temporary repo, local file, test database). Where the command needs real cloud state and tests must not make cloud calls, accept instead: tests that pin the exact argv, plus one real run named as a post-apply gate in the plan or runbook, with its expected output. Neither present is a finding. Example: gate tests that stubbed `git diff --name-only` all passed, while git's rename detection listed a moved file only by its destination. An OS or stdlib platform API the code does not own (`os.confstr`, `sysconf`, locale, keychain) counts as an external command: if every test patches it, ask for one unpatched call on the host, and treat a try/except around it with no such test as a finding (one swallowed a ValueError and silently fell back to `/tmp`).
3. User-experienced check. Does a visibility or layout check measure what the user sees? `elementFromPoint` at the element's centre, or the element's `hidden` attribute. Some probes cannot return the failing value: `getBoundingClientRect` reports full size for an element an ancestor clips to 2px, and `offsetParent` is always null for a `position: fixed` element. A probe result the check could not explain ("could not place that text") under a PASS is a finding, not a footnote.
4. State. Did a passing e2e run only on fresh scratch state? Say so, and name the long-lived condition it never met (data across midnight, several agents, a worktree). Did the suite pass only on the author's machine? Flag tests that hard-code paths under HOME (`~/.local/bin`, `~/.config`), including tests that arrived through a merge, and ask for one run with a scratch HOME and a PATH without user-local bins.
5. Universal claims. Any finding of the form all / none / every / only must rest on uncapped output, with the total count stated (`grep -c`, or the full listing). Output cut with `head` shows that something exists, never that nothing else does. The same holds for a test that claims a value never reaches the output (a secret, a token): if it ran at one verbosity only, ask for hit counts of a planted dummy value under each output mode (pytest: default, `-vv`, `-l`, `--tb=long`) and one real failing call. Truncated reprs hide leaks at the default. An assertion over a whole environment mapping (`assertNotIn(k, env)`, `assert k not in os.environ`, equality of two env dicts) is itself a leak: its failure message prints every variable. Ask for an assertion on the single key.

## Other checks (any diff)

6. Inputs agents cannot read. A finding that depends on real data the agents cannot read (CI variables, production config) is not a deferred minor. Write it as an unchecked merge-gate item for the MR description, with the exact command a human runs to settle it. A clean auto-merge says nothing about semantics: where branches overlap, read the auto-merged files that hold tests or shared helpers, not only the conflicted ones.
7. Runbook preconditions. Every precondition in a runbook or operator doc ("must exist", "must be set", "is configured") names the command or file that creates it and the shape it needs. If the doc cannot derive it from source, it is marked as a human gate and says why. Treat "X must already exist" as a claim to resolve against the repo.
8. Endpoint trust. A finding that recommends validating a configurable endpoint must pin the part of the host only the owner controls (an exact allowlist, the project hash or number). A name pattern on a shared platform domain (`*.run.app`) matches anyone's service of that name.

Cite file:line for each finding.

## Output

Write the full review to `/Users/francisco.ruiz/agent-board/docs/superpowers/briefs/2026-11-20-resume-picker-wrapped-footer.review.rev-resume.md` (that file only; it stays untracked): Strengths, Issues by severity (Critical / Important / Minor, each with file:line and a failure scenario), the evidence lines, and a verdict "Ready to merge: yes / no / with fixes". Then SendMessage team-lead with the verdict and the Critical/Important one-liners.
