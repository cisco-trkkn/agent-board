---
name: "fix-merge-conflicts"
description: Resolve merge conflicts non-interactively, validate build and tests, and finalize conflict resolution
---

# Fix merge conflicts

## Trigger

Branch has unresolved merge conflicts and needs a reliable path to a buildable state.

## Workflow

1. Detect all conflicting files from git status and conflict markers.
2. Resolve each conflict with minimal, correctness-first edits.
3. Prefer preserving both sides when safe. Otherwise, choose the variant that compiles and keeps public behavior stable.
4. Regenerate lockfiles with package manager tools instead of hand-editing.
5. Run compile, lint, and relevant tests.
6. Run the test suites once more with a scratch HOME and a PATH without user-local bins (`HOME=$(mktemp -d) PATH=/usr/bin:/bin <test command>`, keeping the toolchain's own path). Tests that came in clean from the other side were checked only on their author's machine; a hard-coded `~/.local/bin/<tool>` passes locally and fails on every CI runner.
7. Stage resolved files and summarize key decisions.

## Guardrails

- Keep changes minimal and readable.
- Do not leave conflict markers in any file.
- Avoid broad refactors while resolving conflicts.
- Do not push or tag during conflict resolution.

## Output

- Files resolved
- Notable resolution choices
- Build/test outcome, including the scratch-HOME run
