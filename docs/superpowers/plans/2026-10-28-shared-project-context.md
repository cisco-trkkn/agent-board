# Shared Project Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One curated Markdown file per project, `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, that every agent-board lead, teammate and worker receives at session start through a SessionStart hook; teammates propose entries in their reports and only the lead writes, through `tmux-ctl context`.

**Architecture:** `board/context.py` (the `ideas.py` shape: path resolution from `TC_CONTEXT_DIR`, the ideas project key, an exclusive `fcntl` lock on `<file>.lock`, atomic rewrite) behind a `tmux-ctl context show | path | add` subcommand; a plugin SessionStart hook `context-inject.sh` (bash + `python3 -I`, `--scoped`, `TC_CONTEXT=0` off switch, fail-open) that injects the file as `additionalContext` under a fixed preface, cut at the last whole entry within 8 KB; rule text in `orchestrator.md` and the handoff skill; docs alongside the existing hooks and subcommands.

**Tech Stack:** Python 3 stdlib (`fcntl`, `argparse`), zsh (`bin/tmux-ctl`), bash + `python3 -I` hook, zsh tests on `tools/tests/lib.zsh` (scratch tmux server), Python `unittest`, Claude Code plugin hooks (`hooks.json`).

**Spec:** `docs/superpowers/specs/2026-10-28-shared-project-context-design.md`

**Precondition:** none. This plan runs first in the ideas round (shared-context → overseer → teams → night mode); the teams plan relies on the context file this plan defines and names this plan as its precondition.

**Workspace:** run in a new worktree `.claude/worktrees/shared-project-context` on branch `feat/shared-project-context` cut from `main`; no question about working on main.

## Global Constraints

- **Repo:** `~/agent-board` is the live install (`~/.local/bin/agent-board` links into it): execute in the worktree above, never in the live checkout. Commands are in `~/agent-board/CLAUDE.md`. Conventional commits with scope (`feat(board): …`, `feat(tmux-ctl): …`, `feat(plugin): …`, `docs(rules): …`, `test(e2e): …`).
- **Commit steps** end with the attribution trailer your harness specifies; never a literal `Co-Authored-By` line in this plan.
- **Agents' shell is zsh** (gotchas in `~/.claude/CLAUDE.md`): quote a word starting with `=`; `$VAR` is not word-split. Scratch tmux servers start with `-L <sock> -f /dev/null` (`tools/tests/lib.zsh` does). A suite verdict comes from the runner's own summary line (`Ran N tests` + `OK`, `ALL PASS`), or from its exit code plus an uncapped failure count; never from a `tail`.
- **Runners:** `python3 -m unittest discover -s board/tests`; `zsh tools/tests/run-all.zsh` (a new `tools/tests/test_*.zsh` is picked up automatically: `run-all.zsh` globs `test_*.zsh(N)`, checked). Long runs go through `tmux-ctl run -t <secs> tests '<cmd>'`.
- **The file** (spec, exact): path `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`; `<project>` is the ideas key, `tmux-ctl`'s `$FEEDKEY` (session group, else session name, `-bg` stripped), validated by the same rule as `ideas.ideas_path` (`[A-Za-z0-9_-][A-Za-z0-9._-]*`, not `.`/`..`). Layout: `# <project>: shared agent context`, `Last curated: YYYY-MM-DD`, blank, then `## Map`, `## How to run`, `## Gotchas`, `## Decisions` in that order, one bullet per entry `- <fact> (files: path/a, path/b) · YYYY-MM-DD`; `add` appends today's date (`· YYYY-MM-DD`, local time) when the entry has none, refuses any other section name (case-sensitive), creates the file with the four headings the first time, and takes an exclusive `fcntl.lockf` on `<file>.lock` (the `ideas.py` lock). Nothing is committed to the repo.
- **The hook** (spec, exact): `claude/plugin/scripts/context-inject.sh`, registered in `claude/plugin/hooks/hooks.json` as `SessionStart`, no matcher (fires on startup, resume, clear and compact), `"${CLAUDE_PLUGIN_ROOT}/scripts/context-inject.sh" --scoped`, `"timeout": 5`. Output: `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"<preface>\n\n<file>"}}`; preface exactly `Shared project context, curated by the lead; propose additions as 'Context learned' in your report.`; cap 8192 bytes on the file part: over it, keep whole lines up to the end of the last whole entry (an entry is a `- ` line plus its indented continuation lines; a `## ` line is also a boundary), strip trailing blank lines, append `… truncated, full file at <absolute path>`. No file, empty or whitespace-only file, no `$TMUX`/`$TMUX_PANE`, `TC_CONTEXT=0`, or any error: exit 0 with no output. Stdin is drained, not parsed.
- **Hook pattern:** `plan-handoff-guard.sh` and `sdd-call-guard.sh` (bash wrapper, `python3 -I`, `--scoped` accepted, an off switch, fail-open). Every place that lists the existing hooks lists `context-inject` too (observation #102): `docs/INSTALL.md`, `docs/ARCHITECTURE.md`, `claude/plugin/.claude-plugin/plugin.json`, `claude/plugin/hooks/hooks.json`, `tools/tests/test_plugin.zsh` (found by `grep -rl sdd-call-guard docs/ README.md claude/ tools/tests/`); the env-var table in `docs/CUSTOMIZATION.md` and the subcommand tables in `docs/ARCHITECTURE.md` and the tmux-orchestrator skill list `TC_CONTEXT_DIR`/`TC_CONTEXT` and `tmux-ctl context`.
- **External-tool values, probed 2026-10-28 (claude 2.1.312, tmux 3.8):** a SessionStart hook receives on stdin `{"session_id":…,"transcript_path":…,"cwd":…,"hook_event_name":"SessionStart","source":"startup"}` and inherits `TMUX` and `TMUX_PANE` from the Claude process (probe: a throwaway plugin whose hook dumped stdin and `env`); a reply of the shape above reached the model (haiku answered the codeword the hook injected); `claude -p --allowedTools <tools...>` takes every following word, so a prompt argument after it is swallowed (`Error: Input must be provided either through stdin or as a prompt argument`), which is why the e2e pipes the prompt on stdin.
- **Test isolation** (observation #101): every test and the e2e set `TC_CONTEXT_DIR` to a scratch folder and put fixtures at the real layout, `$TC_CONTEXT_DIR/<project>.md` with `<project>` the scratch session name (`tt`); the hook test runs the real hook inside the scratch tmux server so the key is resolved the live way. All writes go to scratch `TC_STATE`, `TC_IDEAS_DIR` and `TC_CONTEXT_DIR`; the real `~/.local/state/agent-board/context` (absent on 2026-10-28) and the real ideas file are read-only.
- **Real fixtures** (observation #107): the over-cap unit fixture is synthetic but shape-exact (dated entries across 2026-10-01..30, continuation lines, built to straddle the boundary); the e2e pairs it with a read-only copy of the real `~/.local/state/agent-board/ideas/agent-board.md` (15.8 KB, dated 2026-10-16..28, the same bullet shape).
- **Plan-authored code was run once by the author** (writing-plans-extras §8) on a scratch copy of `a59ffc7`: every test file, hook, diff, RED/GREEN expectation and mutation below is quoted from those runs.
- **Model tiers:** Tasks 1, 2, 4, 5 `mechanical` (complete code or diffs in the steps, 2–4 files each); Tasks 3 and 6 `standard` (a real-tmux test of a new hook; a run against live Claude). No frontier task.
- **Native tasks:** the plan author created none (four plans share one task list); the lead creates them from `.tasks.json` when this plan starts.

**User decisions (already made, 2026-10-28):**
- Covers all three kinds of context equally: codebase map, how-to-run knowledge, decisions.
- The lead curates. Teammates propose; only the lead writes.
- Location: one per-project state file outside the repo, next to the ideas inbox. Nothing is committed.
- Delivery: a SessionStart hook injects it into every agent, within a size cap.
- Approach 1: one curated Markdown file; each entry carries a `(files: …)` suffix so a staleness check can be added later without changing the format.

**Rulings made while planning (the spec is silent; cheap to change):**
- `add` also sets `Last curated:` to today, and appends at the end of its section (newest last).
- An existing file that lacks the `## <section>` heading makes `add` refuse with `ValueError` and write nothing (the order is fixed; the lead restores the headings by hand). Headings are matched case-sensitively.
- The 8 KB cap applies to the file part of the injection; the preface and the truncation note come on top.
- The hook mirrors `tmux-ctl`'s `-bg` strip, so a Claude started in the hidden `<project>-bg` session reads the project's file.
- Docs beyond the spec's INSTALL/ARCHITECTURE: `docs/CUSTOMIZATION.md` (the env-var table) and the tmux-orchestrator skill (the subcommand table) list the new names too (observation #102). `docs/ARCHITECTURE.md`'s "All hooks are silent and exit 0 except kill-guard's" line now also names the two guards' blocks, which it had missed.
- The e2e (Task 6) runs on the branch before the merge, on a scratch server, with headless `claude -p` sessions started in the scratch session's pane environment: the "teammate's first turn" is a fresh haiku process loading the plugin the same way a teammate does; the lead is a sonnet process given `claude/orchestrator.md`. A full interactive `dev` session with a real team is not scripted; the lead re-runs the script from `main` after the merge (the spec's "E2E after merge").

---

### Task 1: board/context.py with tests

**Goal:** `board/context.py` resolves `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, and its `add` writes a dated entry under one of the four fixed headings under an exclusive lock, creating the four-section file the first time; `show` and `path` read.

**Files:**
- Create: `board/context.py` (mode 755)
- Create: `board/tests/test_context.py`

**Acceptance Criteria:**
- [ ] `python3 -m unittest discover -s board/tests -p 'test_context.py'` prints `Ran 15 tests` and `OK`
- [ ] The three mutations in Step 5 each fail the named test (lock removed → `test_add_blocks_while_the_lock_is_held`; date not appended → `test_add_dates_an_undated_entry_and_keeps_a_dated_one`; section check removed → `test_unknown_section_refused_and_nothing_written` and `test_cli`)
- [ ] `python3 -m unittest discover -s board/tests` prints `Ran 482 tests` and `OK`
- [ ] `context_path` rejects the same names as `ideas.ideas_path` (`a/b`, `..`, `.`, empty, `.hidden`) and resolves `TC_CONTEXT_DIR` first, else `~/.local/state/agent-board/context`
- [ ] The file `add` creates is byte-exact: `# <project>: shared agent context`, `Last curated: YYYY-MM-DD`, blank, then `## Map`, `## How to run`, `## Gotchas`, `## Decisions` each followed by one blank line; entries are `- <text> · YYYY-MM-DD`, appended at the end of their section; an entry already ending in ` · YYYY-MM-DD` keeps its date

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_context.py'` → `Ran 15 tests` … `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Create `board/tests/test_context.py` exactly as below (the fixture layout is the real one: `$TC_CONTEXT_DIR/<project>.md`, the same path `context_path()` resolves, and `.lock` beside it).

```python
import fcntl
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import context  # noqa: E402
import ideas  # noqa: E402

SKELETON = ("# p: shared agent context\nLast curated: 2026-10-28\n\n"
            "## Map\n\n## How to run\n\n## Gotchas\n\n## Decisions\n")
T0 = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))   # 2026-10-28 local


class ContextPathTest(unittest.TestCase):
    """Path resolution: TC_CONTEXT_DIR, else ~/.local/state/agent-board/context; the key rules match ideas.py."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.pop("TC_CONTEXT_DIR", None)
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name

    def tearDown(self):
        os.environ["HOME"] = self.old_home
        if self.old_env is not None:
            os.environ["TC_CONTEXT_DIR"] = self.old_env
        else:
            os.environ.pop("TC_CONTEXT_DIR", None)
        self.tmp.cleanup()

    def test_default_dir_under_home(self):
        self.assertEqual(context.context_path("p"),
                         Path(self.tmp.name) / ".local" / "state" / "agent-board" / "context" / "p.md")

    def test_tc_context_dir_wins(self):
        os.environ["TC_CONTEXT_DIR"] = os.path.join(self.tmp.name, "elsewhere")
        self.assertEqual(context.context_path("p"), Path(self.tmp.name) / "elsewhere" / "p.md")

    def test_project_key_rules_match_ideas(self):
        for good in ("agent-board", "foo_bar", "a.b", "x-1"):
            self.assertEqual(context.context_path(good).name, ideas.ideas_path(good).name)
        for bad in ("a/b", "..", ".", "", ".hidden"):
            with self.assertRaises(ValueError):
                ideas.ideas_path(bad)
            with self.assertRaises(ValueError):
                context.context_path(bad)


class ContextAddTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_CONTEXT_DIR"] = self.tmp.name
        self.p = Path(self.tmp.name) / "p.md"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_CONTEXT_DIR", None)

    def read(self):
        return self.p.read_text()

    def test_add_creates_the_four_section_file(self):
        line = context.add("p", "Map", "board code is in board/ (files: board/server.py)", now=T0)
        self.assertEqual(line, "- board code is in board/ (files: board/server.py) · 2026-10-28")
        self.assertEqual(self.read(), SKELETON.replace("## Map\n", "## Map\n" + line + "\n"))

    def test_add_places_entries_under_the_right_heading_in_order(self):
        context.add("p", "Gotchas", "g1", now=T0)
        context.add("p", "Map", "m1", now=T0)
        context.add("p", "Gotchas", "g2", now=T0)
        context.add("p", "Decisions", "d1", now=T0)
        context.add("p", "How to run", "h1", now=T0)
        self.assertEqual(self.read(), (
            "# p: shared agent context\nLast curated: 2026-10-28\n\n"
            "## Map\n- m1 · 2026-10-28\n\n"
            "## How to run\n- h1 · 2026-10-28\n\n"
            "## Gotchas\n- g1 · 2026-10-28\n- g2 · 2026-10-28\n\n"
            "## Decisions\n- d1 · 2026-10-28\n"))

    def test_add_dates_an_undated_entry_and_keeps_a_dated_one(self):
        context.add("p", "Map", "undated", now=T0)
        context.add("p", "Map", "dated · 2026-01-02", now=T0)
        self.assertIn("- undated · 2026-10-28\n- dated · 2026-01-02\n", self.read())

    def test_add_normalises_whitespace_and_refuses_empty(self):
        self.assertEqual(context.add("p", "Map", "  two\n words ", now=T0), "- two words · 2026-10-28")
        with self.assertRaises(ValueError):
            context.add("p", "Map", "   ")

    def test_unknown_section_refused_and_nothing_written(self):
        with self.assertRaisesRegex(ValueError, "unknown section"):
            context.add("p", "Notes", "x")
        with self.assertRaisesRegex(ValueError, "unknown section"):
            context.add("p", "map", "x")        # headings are case-sensitive
        self.assertFalse(self.p.exists())

    def test_add_updates_last_curated(self):
        self.p.write_text(SKELETON.replace("2026-10-28", "2026-01-01"))
        context.add("p", "Map", "m", now=T0)
        self.assertIn("Last curated: 2026-10-28\n", self.read())
        self.assertNotIn("2026-01-01", self.read())

    def test_missing_heading_in_an_existing_file_is_refused(self):
        self.p.write_text("# p: shared agent context\nLast curated: 2026-01-01\n\n## Map\n")
        with self.assertRaises(ValueError):
            context.add("p", "Gotchas", "g", now=T0)
        self.assertEqual(self.read(), "# p: shared agent context\nLast curated: 2026-01-01\n\n## Map\n")

    def test_empty_file_is_treated_as_new(self):
        self.p.write_text("")
        context.add("p", "Map", "m", now=T0)
        self.assertTrue(self.read().startswith("# p: shared agent context\n"))

    def test_show_and_path(self):
        self.assertEqual(context.show("p"), "")
        context.add("p", "Map", "m", now=T0)
        self.assertEqual(context.show("p"), self.read())
        self.assertEqual(context.context_path("p"), self.p)

    def test_add_blocks_while_the_lock_is_held(self):
        # Hold the lock in this process; a child `add` must not touch the file until it is released.
        # Mutation: remove the lockf call in _locked() -> "unchanged while locked" fails.
        context.add("p", "Map", "first", now=T0)
        before = self.read()
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        with open(f"{self.p}.lock", "w") as lk:
            fcntl.lockf(lk, fcntl.LOCK_EX)
            child = subprocess.Popen([sys.executable, "-I", str(HERE / "context.py"), "add", "--project", "p",
                                      "--section", "Map", "--", "second"], env=env)
            time.sleep(0.7)
            self.assertIsNone(child.poll(), "child finished while the lock was held")
            self.assertEqual(self.read(), before, "unchanged while locked")
            fcntl.lockf(lk, fcntl.LOCK_UN)
        self.assertEqual(child.wait(timeout=10), 0)
        self.assertIn("- second · ", self.read())

    def test_concurrent_cli_adds_all_land(self):
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        secs = list(context.SECTIONS)
        procs = [subprocess.Popen([sys.executable, "-I", str(HERE / "context.py"), "add", "--project", "p",
                                   "--section", secs[n % 4], "--", f"entry {n}"], env=env) for n in range(20)]
        self.assertEqual([p.wait() for p in procs], [0] * 20)
        text = self.read()
        self.assertEqual(text.count("# p: shared agent context"), 1)
        self.assertEqual(sorted(int(m) for m in re.findall(r"^- entry (\d+) · ", text, re.M)), list(range(20)))
        for n in range(20):   # each entry sits under its own heading
            sec_text = text.split(f"## {secs[n % 4]}\n", 1)[1].split("\n## ", 1)[0]
            self.assertIn(f"- entry {n} · ", sec_text)

    def test_cli(self):
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        run = lambda *a: subprocess.run([sys.executable, "-I", str(HERE / "context.py"), *a], env=env,
                                        capture_output=True, text=True)
        r = run("show", "--project", "p")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = run("path", "--project", "p")
        self.assertEqual((r.returncode, r.stdout), (0, f"{self.p}\n"))
        r = run("add", "--project", "p", "--section", "Gotchas", "--", "flaky", "test")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^added under ## Gotchas: - flaky test · \d{4}-\d{2}-\d{2}\n$")
        r = run("add", "--project", "p", "--section", "Nope", "--", "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown section", r.stderr)
        r = run("show", "--project", "p")
        self.assertEqual(r.stdout, self.read())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: RED.** Run: `python3 -m unittest discover -s board/tests -p 'test_context.py'`
Expected: `ModuleNotFoundError: No module named 'context'` (1 error, `FAILED (errors=1)`).

- [ ] **Step 3: Write `board/context.py`** exactly as below, then `chmod +x board/context.py`.

```python
#!/usr/bin/env python3
"""context: the per-project shared agent context, ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md
(spec: docs/superpowers/specs/2026-10-28-shared-project-context-design.md).

One curated Markdown file per project, read by every agent at session start (the plugin's context-inject.sh hook).
Layout, fixed section order:

  # <project>: shared agent context
  Last curated: YYYY-MM-DD

  ## Map
  - <fact> (files: path/a, path/b) · YYYY-MM-DD
  ## How to run
  ## Gotchas
  ## Decisions

One bullet per entry; the trailing date is when the entry was last checked. Only the lead writes (teammates propose
"Context learned" items in their reports). Every writer takes an exclusive lock on <file>.lock, like ideas.py; the lead's
pruning and rewording are ordinary edits of the file.

  context.py show --project P
  context.py path --project P
  context.py add  --project P --section "<Map|How to run|Gotchas|Decisions>" -- TEXT
"""
import argparse
import fcntl
import os
import re
import sys
import time
from pathlib import Path

SECTIONS = ("Map", "How to run", "Gotchas", "Decisions")
DATED_RE = re.compile(r" · \d{4}-\d{2}-\d{2}$")
PROJECT_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")   # the same key rule as ideas.ideas_path


def context_dir():
    return Path(os.environ.get("TC_CONTEXT_DIR") or Path.home() / ".local" / "state" / "agent-board" / "context")


def context_path(project):
    if not PROJECT_RE.fullmatch(project or "") or project in (".", ".."):
        raise ValueError(f"bad project name {project!r}")
    return context_dir() / f"{project}.md"


def _today(now=None):
    return time.strftime("%Y-%m-%d", time.localtime(now))


def skeleton(project, now=None):
    return (f"# {project}: shared agent context\nLast curated: {_today(now)}\n\n"
            + "\n".join(f"## {s}\n" for s in SECTIONS))


def show(project):
    p = context_path(project)
    return p.read_text() if p.is_file() else ""


def _insert(text, section, line, now=None):
    """Append `line` at the end of `## section` (before the next heading), and set Last curated to today."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, l in enumerate(lines) if l.rstrip("\n") == f"## {section}"]
    if len(heads) != 1:
        raise ValueError(f"no single '## {section}' heading in the file; restore the four headings")
    i = heads[0] + 1
    end = i
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    body = lines[i:end]
    while body and not body[-1].strip():   # trailing blank lines of the section
        body.pop()
    tail = [line + "\n"] + (["\n"] if end < len(lines) else [])
    lines[i:end] = body + tail
    out = "".join(lines)
    out, n = re.subn(r"^Last curated: .*$", f"Last curated: {_today(now)}", out, count=1, flags=re.M)
    return out


def add(project, section, entry, now=None):
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section!r}; one of: {', '.join(SECTIONS)}")
    entry = " ".join(str(entry).split())
    if not entry:
        raise ValueError("empty entry")
    line = f"- {entry}" if DATED_RE.search(entry) else f"- {entry} · {_today(now)}"
    p = context_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        text = p.read_text() if p.is_file() else ""
        if not text.strip():
            text = skeleton(project, now)
        new = _insert(text, section, line, now)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(new)
        os.replace(tmp, p)
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-project shared agent context")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "path"):
        sub.add_parser(name).add_argument("--project", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--section", required=True)
    a.add_argument("text", nargs="+")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "show":
            sys.stdout.write(show(args.project))
        elif args.cmd == "path":
            print(context_path(args.project))
        else:
            print(f"added under ## {args.section}: {add(args.project, args.section, ' '.join(args.text))}")
        return 0
    except ValueError as e:
        print(f"context: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: GREEN.** Run: `python3 -m unittest discover -s board/tests -p 'test_context.py'`
Expected: `Ran 15 tests` … `OK`.

- [ ] **Step 5: Mutation check.** Copy `board/context.py` to a backup first; after each run restore it from the backup. Each mutation must fail the named test; report the three failing runs.
  - Replace the line `        fcntl.lockf(lk, fcntl.LOCK_EX)` with `        pass` → `test_add_blocks_while_the_lock_is_held` FAILS (and, in this author's run, `test_concurrent_cli_adds_all_land` too).
  - Replace `    line = f"- {entry}" if DATED_RE.search(entry) else f"- {entry} · {_today(now)}"` with `    line = f"- {entry}"` → `test_add_dates_an_undated_entry_and_keeps_a_dated_one` FAILS (6 more fail with it).
  - Replace `    if section not in SECTIONS:` with `    if False:` → `test_unknown_section_refused_and_nothing_written` and `test_cli` FAIL.
  After restoring, the GREEN run of Step 4 passes again.

- [ ] **Step 6: Whole board suite.** Run: `python3 -m unittest discover -s board/tests`
Expected: `Ran 482 tests` … `OK` (467 before this task + 15).

- [ ] **Step 7: Commit.**

```bash
git add board/context.py board/tests/test_context.py
git commit -m "feat(board): context.py, the per-project shared agent context file (show/path/add under a lock)"
```
End with the attribution trailer your harness specifies.

---

### Task 2: tmux-ctl context subcommand with tests

**Goal:** `tmux-ctl context show | path | add <section> "<entry>"` calls `board/context.py` with `--project "$FEEDKEY"`, the same key `tmux-ctl idea` uses, and the help text lists it.

**Files:**
- Modify: `bin/tmux-ctl` (usage header after the `idea` line; new `context)` case after `idea)`; help range `2,31p` → `2,33p`)
- Create: `tools/tests/test_ctl_context.zsh`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/test_ctl_context.zsh` prints `ALL PASS` (17 checks)
- [ ] Before the `tmux-ctl` edit the same test prints `11 FAILED` (the RED run)
- [ ] From a `-bg` pane (`TC_SESSION=tt-bg`, `@tc_bg` set) the file is `<TC_CONTEXT_DIR>/tt.md`, never `tt-bg.md`: the key matches `tmux-ctl idea`
- [ ] `tmux-ctl help` lists `tmux-ctl context` and still ends with the blank line
- [ ] `tmux-ctl artifact "$(tmux-ctl context path)"` registers the file with kind `other` in `$TC_STATE/artifacts-<project>.jsonl` (the board's artifacts panel)
- [ ] An unknown section, a missing subcommand and `add` without an entry exit 2 and write nothing

**Verify:** `zsh tools/tests/test_ctl_context.zsh` → `ALL PASS` (17 checks)

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `tools/tests/test_ctl_context.zsh` exactly as below. `run-all.zsh` globs `test_*.zsh`, so it is picked up with no registration (checked: `tools/tests/run-all.zsh` line 5, `for f in "$dir"/test_*.zsh(N)`).

```zsh
source "${0:A:h}/lib.zsh"
# tmux-ctl context show|path|add: the shared project context file, keyed like `tmux-ctl idea` (board/context.py).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_CONTEXT_DIR="${$(mktemp -d "${TMPDIR:-/tmp}/ttctx.XXXXXX"):A}"
tt_setup claude
f="$TC_CONTEXT_DIR/tt.md"
check "path before any add"                  test "$($C context path)" = "$f"
check "show before any add: empty, exit 0"   sh -c "out=\$($C context show) && [ -z \"\$out\" ]"
out="$($C context add Map 'the board is board/server.py (files: board/server.py)')"
check "add creates the file under the session key"   test -s "$f"
check "add prints the line"                  zsh -c '[[ $1 == "added under ## Map: - the board is board/server.py (files: board/server.py) · "[0-9]* ]]' _ "$out"
check "four headings in order"               test "$(grep '^## ' "$f" | sed 's/^## //' | tr '\n' '|')" = 'Map|How to run|Gotchas|Decisions|'
check "entry under Map, dated"               grep -q '^- the board is board/server.py (files: board/server.py) · 20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]$' "$f"
$C context add 'How to run' 'zsh tools/tests/run-all.zsh (files: tools/tests/run-all.zsh)' >/dev/null
check "a two-word section name works"        sh -c "sed -n '/^## How to run/,/^## Gotchas/p' ${(q)f} | grep -q run-all"
check "show prints the file"                 test "$($C context show)" = "$(<$f)"
check "unknown section exits 2"              sh -c "! $C context add Notes x 2>/dev/null"
check "unknown section writes nothing"       test "$(grep -c '^- ' "$f")" -eq 2
check "no subcommand exits 2"                sh -c "! $C context 2>/dev/null"
check "add without an entry exits 2"         sh -c "! $C context add Map 2>/dev/null"
# the key is the ideas key: from a -bg pane it is the project, never <project>-bg (the rule `tmux-ctl idea` follows)
tt new-session -d -s tt-bg -c "$TT_DIR"; tt set-option -t '=tt-bg:' @tc_bg 1
TC_SESSION=tt-bg $C context add Gotchas "from the bg pane" >/dev/null
check "key strips -bg"                       grep -q 'from the bg pane' "$f"
check "no -bg-bg key"                        test ! -e "$TC_CONTEXT_DIR/tt-bg.md"
check "help lists context"                   sh -c "$C help | grep -q 'tmux-ctl context'"
check "help still ends at the blank line"    test "$($C help | tail -1)" = ""
# the file opens in the board's artifacts panel (spec: tmux-ctl artifact "$(tmux-ctl context path)")
$C artifact "$($C context path)" >/dev/null
check "artifact registers the context file"  test "$(jq -r --arg p "$f" 'select(.path==$p)|.kind' "$TC_STATE/artifacts-tt.jsonl" | tail -1)" = other
rm -rf "$TC_CONTEXT_DIR"
tt_done
```

- [ ] **Step 2: RED.** Run: `zsh tools/tests/test_ctl_context.zsh`
Expected: `11 FAILED` (every check that needs the subcommand: path, show, add creates, add prints, four headings, entry under Map, two-word section, unknown section writes nothing, key strips -bg, help lists context, artifact registers). `tmux-ctl` answers `unknown command 'context' (tmux-ctl help)` on stderr.

- [ ] **Step 3: Edit `bin/tmux-ctl`.** Apply this diff (generated from the file at `a59ffc7`; `git apply` from the worktree root, or the same three edits with the Edit tool). The help text is printed by line range, so the two new header lines move `sed -n '2,31p'` to `'2,33p'`: without that the new usage lines are cut off and the help no longer ends at the blank `#` line.

```diff
diff --git a/bin/tmux-ctl b/bin/tmux-ctl
index 0e5237a..4aebd8d 100755
--- a/bin/tmux-ctl
+++ b/bin/tmux-ctl
@@ -26,6 +26,8 @@
 #   tmux-ctl agents                        worker status + last lines
 #   tmux-ctl artifact <path> [--kind K]    show a file in the board's artifacts panel
 #   tmux-ctl idea  <text>                  file an idea for after the plan (never act on it now)
+#   tmux-ctl context show|path|add <section> "<entry>"
+#                                          the project's shared agent context file (lead curates; sections Map, How to run, Gotchas, Decisions)
 #   tmux-ctl relay <doc> [--old-session ID] after this turn, restart the claude window as a fresh
 #                                          orchestrator that starts from <doc> (handoff skill only)
 #
@@ -441,6 +443,17 @@ Write a longer brief inline, pass it as --brief FILE, or use --force to send thi
     [[ -n "$*" ]] || die "usage: tmux-ctl idea <text>"
     python3 -I "${0:A:h:h}/board/ideas.py" add --project "$FEEDKEY" -- "$*" ;;
 
+  context)
+    sub="$1"; [[ -n "$sub" ]] && shift
+    case "$sub" in
+      show|path) python3 -I "${0:A:h:h}/board/context.py" "$sub" --project "$FEEDKEY" ;;
+      add)
+        [[ -n "$1" && -n "$2" ]] || die 'usage: tmux-ctl context add <Map|How to run|Gotchas|Decisions> "<entry>"'
+        sec="$1"; shift
+        python3 -I "${0:A:h:h}/board/context.py" add --project "$FEEDKEY" --section "$sec" -- "$*" ;;
+      *) die 'usage: tmux-ctl context show | path | add <section> "<entry>"' ;;
+    esac ;;
+
   relay)
     [[ -n "$1" ]] || die "usage: tmux-ctl relay <handoff-doc> [--old-session <id>]"
     doc="${1:A}"; shift; old=""
@@ -464,7 +477,7 @@ Write a longer brief inline, pass it as --brief FILE, or use --force to send thi
     print -r -- "relay scheduled: ${FEEDKEY}:claude restarts with $doc once this turn ends (log: $log)" ;;
 
   ""|-h|--help|help)
-    sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//' ;;
+    sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//' ;;
 
   *) die "unknown command '$cmd' (tmux-ctl help)" ;;
 esac
```

- [ ] **Step 4: GREEN.** Run: `zsh tools/tests/test_ctl_context.zsh`
Expected: `ALL PASS` (17 checks).

- [ ] **Step 5: Commit.**

```bash
git add bin/tmux-ctl tools/tests/test_ctl_context.zsh
git commit -m "feat(tmux-ctl): context show|path|add, the shared project context keyed like idea"
```
End with the attribution trailer your harness specifies.

---

### Task 3: context-inject SessionStart hook, registered, with tests

**Goal:** A SessionStart hook in the agent-board plugin injects the project's context file as `additionalContext` under the spec's preface, cut at the last whole entry within 8 KB, silent when there is no file, no tmux pane, `TC_CONTEXT=0` or any error.

**Files:**
- Create: `claude/plugin/scripts/context-inject.sh` (mode 755)
- Create: `tools/tests/test_context_inject.zsh`
- Modify: `claude/plugin/hooks/hooks.json` (new `SessionStart` entry)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (`description` names the hook)
- Modify: `tools/tests/test_plugin.zsh` (one registration check)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/test_context_inject.zsh` prints `ALL PASS` (15 checks); before the hook exists it prints `14 FAILED`
- [ ] The four mutations in Step 5 each fail the named check
- [ ] `zsh tools/tests/test_plugin.zsh` prints `ALL PASS`, and `1 FAILED` with the hooks.json entry reverted
- [ ] Output shape is `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"<preface>\n\n<file or cut file>"}}`; the preface is exactly `Shared project context, curated by the lead; propose additions as 'Context learned' in your report.`
- [ ] Over the cap, the file part is at most 8192 bytes, ends with a complete entry, and is followed by `… truncated, full file at <absolute path>`; an entry whose continuation line crosses the boundary is dropped whole
- [ ] No file, an empty or whitespace-only file, `TC_CONTEXT=0`, no `$TMUX`/`$TMUX_PANE`, an unreadable file: exit 0, nothing on stdout or stderr; a binary file or garbage stdin: exit 0, nothing on stderr
- [ ] hooks.json registers `"${CLAUDE_PLUGIN_ROOT}/scripts/context-inject.sh" --scoped` under `SessionStart` with no matcher and `"timeout": 5`

**Verify:** `zsh tools/tests/test_context_inject.zsh && zsh tools/tests/test_plugin.zsh` → both print `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing hook test.** Create `tools/tests/test_context_inject.zsh` exactly as below. It runs the hook for real inside the scratch tmux server (`tt_setup` exports `TMUX` and `TMUX_PANE` for session `tt`), so the project key resolves the way it does in a live session; the fixture is at the real layout, `$TC_CONTEXT_DIR/tt.md`. The stdin payload is the shape a real SessionStart delivered in the author's probe (claude 2.1.312, 2026-10-28).

```zsh
source "${0:A:h}/lib.zsh"
# context-inject: SessionStart hook that injects ${TC_CONTEXT_DIR}/<project>.md as additionalContext, capped at 8 KB.
# The hook runs for real inside the scratch server: tt_setup exports TMUX and TMUX_PANE for session `tt`, so the key is `tt`.
H="${TC_CTXINJECT:-$TT_REPO/claude/plugin/scripts/context-inject.sh}"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx"; mkdir -p "$TC_CONTEXT_DIR"
f="$TC_CONTEXT_DIR/tt.md"
CAP=8192
PREFACE="Shared project context, curated by the lead; propose additions as 'Context learned' in your report."
# stdin shape of a real SessionStart (claude 2.1.312, probed 2026-10-28): session_id, transcript_path, cwd, hook_event_name, source
payload() { print -r -- '{"session_id":"s1","transcript_path":"/tmp/none.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' }
run_hook() { payload | "$H" "$@" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)" }
ctx() { print -r -- "$out" | python3 -c 'import json,sys; h=json.load(sys.stdin)["hookSpecificOutput"]; assert h["hookEventName"]=="SessionStart", h; sys.stdout.write(h["additionalContext"])' 2>/dev/null }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]] }

run_hook;                       check "no file: no output, exit 0"            silent
: > "$f"; run_hook;             check "empty file: no output, exit 0"         silent
print -n '  \n\n' > "$f"; run_hook; check "whitespace-only file: no output"   silent
small=$'# tt: shared agent context\nLast curated: 2026-10-28\n\n## Map\n- the board is board/server.py (files: board/server.py) · 2026-10-28\n\n## How to run\n\n## Gotchas\n\n## Decisions\n'
print -rn -- "$small" > "$f"; run_hook
check "small file: exit 0, nothing on stderr"            test $rc -eq 0 -a -z "$err"
check "small file: preface, blank line, file verbatim"   test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
run_hook --scoped
check "--scoped: same output"                            test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
payload | TC_CONTEXT=0 "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "TC_CONTEXT=0: no output, exit 0"                  silent
echo 'not json' | "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "garbage stdin: exit 0, still injects (stdin is drained, not parsed)"  test $rc -eq 0 -a -z "$err" -a -n "$out"
payload | TMUX= TMUX_PANE= "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "outside tmux: no output, exit 0"                  silent
chmod 000 "$f"; run_hook; chmod 644 "$f"
check "unreadable file: no output, exit 0"               silent
head -c 300 /dev/urandom > "$f"; run_hook
check "binary file: exit 0, nothing on stderr"           test $rc -eq 0 -a -z "$err"
# a -bg pane (hidden tests/shell session, @tc_bg set) reads the project's file, never <project>-bg.md
bgpane="$(tt new-session -d -s tt-bg -c "$TT_DIR" -P -F '#{pane_id}')"; tt set-option -t '=tt-bg:' @tc_bg 1
print -rn -- "$small" > "$f"
payload | TMUX_PANE="$bgpane" "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "-bg pane: injects the project's file"             test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
# over the cap: an aged, multi-day file (entries dated across 2026-10-01..30, some with continuation lines), built so the
# entry that straddles the 8192-byte boundary has its first line inside the cap and its continuation line over it
python3 - "$f" "$CAP" <<'PY'
import sys
cap = int(sys.argv[2])
nbytes = lambda ls: len("".join(ls).encode())
lines = ["# tt: shared agent context\n", "Last curated: 2026-10-28\n", "\n", "## Map\n"]
n = 0
while nbytes(lines) + 100 <= cap - 60:                      # ~100-byte entries, every fifth one with a continuation line
    lines.append(f"- map entry {n:03d} " + "x" * 58 + f" (files: board/f{n}.py) · 2026-10-{1 + n % 30:02d}\n")
    if n % 5 == 0:
        lines.append("  continuation detail " + "y" * 40 + "\n")
    n += 1
room = cap - nbytes(lines)                                   # 60..159 bytes left
first = "- straddling entry " + "s" * (room - 10 - len("- straddling entry  · 2026-10-29\n".encode())) + " · 2026-10-29\n"
lines.append(first)                                          # fits, with 10 bytes to spare
assert nbytes(lines) <= cap, nbytes(lines)
lines.append("  continuation of the straddling entry " + "c" * 40 + "\n")   # overflows: the whole entry must go
assert nbytes(lines) > cap
lines += ["\n", "## How to run\n"]
for m in range(30):
    lines.append(f"- run entry {m:03d} " + "z" * 60 + f" (files: tools/t{m}.zsh) · 2026-10-{1 + m % 30:02d}\n")
lines += ["\n", "## Gotchas\n", "- g1 · 2026-10-02\n", "\n", "## Decisions\n", "- d1 · 2026-10-03\n"]
open(sys.argv[1], "w").write("".join(lines))
PY
check "fixture is over the cap"  test "$(wc -c < "$f")" -gt $CAP
run_hook
check "over the cap: exit 0, nothing on stderr"          test $rc -eq 0 -a -z "$err"
ctx > "$TT_DIR/ctx.txt"
check "over the cap: cut at an entry boundary, body <= 8192 bytes, note names the path" python3 - "$f" "$TT_DIR/ctx.txt" "$PREFACE" "$CAP" <<'PY'
import sys
src, got, preface, cap = open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3], int(sys.argv[4])
assert got.startswith(preface + "\n\n"), got[:120]
rest = got[len(preface) + 2:]
note = "… truncated, full file at " + sys.argv[1] + "\n"
assert rest.endswith(note), rest[-200:]
body = rest[: -len(note)]
assert len(body.encode()) <= cap, len(body.encode())
# oracle: the longest prefix of the file that ends right before an entry/heading start (or EOF) and fits the cap
lines = src.splitlines(keepends=True)
cuts = [i for i, l in enumerate(lines) if l.startswith(("- ", "## "))] + [len(lines)]
best = max(c for c in cuts if len("".join(lines[:c]).encode()) <= cap)
assert body == "".join(lines[:best]).rstrip("\n") + "\n", (body[-300:], "".join(lines[:best])[-300:])
assert body.rstrip("\n").splitlines()[-1].startswith("- "), body[-200:]     # last kept line is a complete entry
assert "- straddling entry" not in body, body[-300:]                     # the entry over the boundary went whole
assert "## How to run" not in body                                           # everything after it went too
PY
tt_done
```

- [ ] **Step 2: RED.** Run: `zsh tools/tests/test_context_inject.zsh`
Expected: `14 FAILED` (the hook script does not exist; every check but "fixture is over the cap" fails).

- [ ] **Step 3: Write `claude/plugin/scripts/context-inject.sh`** exactly as below, then `chmod 755 claude/plugin/scripts/context-inject.sh`. Pattern: `plan-handoff-guard.sh` (bash wrapper, `python3 -I - <<'PY'`, `--scoped` accepted, off switch, fail-open). Differences from that script, all of them: (1) it is a SessionStart hook, so a non-empty result is JSON on stdout, never an exit 2; (2) it resolves the project from tmux (`$TMUX`'s socket, `$TMUX_PANE`, session group else name, `-bg` stripped when the session has `@tc_bg`, the rule `tmux-ctl`'s `FEEDKEY` uses) before Python runs; (3) stdin is drained, not parsed; (4) the switch is `TC_CONTEXT=0`.

```bash
#!/usr/bin/env bash
# SessionStart: inject the project's shared context file, ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md,
# as additionalContext (spec: docs/superpowers/specs/2026-10-28-shared-project-context-design.md). <project> is the ideas key:
# the pane's session group, else its session name, with a -bg suffix stripped when the session carries @tc_bg (the same rule
# as tmux-ctl's FEEDKEY). Cap 8 KB on the file part: over it, the file is cut at the end of the last whole entry that fits and
# a truncation note names the full path. No file, an empty one, no tmux pane, or any error: no output, exit 0 (the session
# always starts). The hook JSON on stdin (session_id, transcript_path, cwd, hook_event_name, source) is drained, not read.
# Kill switch: TC_CONTEXT=0. --scoped (the plugin registration) is accepted and changes nothing.
[[ "$TC_CONTEXT" == 0 ]] && { cat >/dev/null; exit 0; }
cat >/dev/null
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
tmux_bin="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$tmux_bin" ]] || tmux_bin=tmux
sock="${TMUX%%,*}"
project=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null) || exit 0
sess=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null) || exit 0
[[ -n "$("$tmux_bin" -S "$sock" show-options -qv -t "=$sess:" @tc_bg 2>/dev/null)" ]] && project="${project%-bg}"
[[ "$project" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] || exit 0
dir="${TC_CONTEXT_DIR:-$HOME/.local/state/agent-board/context}"
python3 -I - "$dir/$project.md" <<'PY' 2>/dev/null || exit 0
import json, sys
CAP = 8192
PREFACE = "Shared project context, curated by the lead; propose additions as 'Context learned' in your report."
try:
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    if not data.strip():
        sys.exit(0)
    body = data.decode("utf-8", "replace")
    if len(data) > CAP:
        lines = body.splitlines(keepends=True)
        keep, used, start = len(lines), 0, 0      # start: where the entry or heading that holds the current line began
        for i, line in enumerate(lines):
            if line.startswith(("- ", "## ")):
                start = i
            used += len(line.encode())
            if used > CAP:
                keep = start
                break
        body = "".join(lines[:keep]).rstrip("\n") + "\n… truncated, full file at " + path + "\n"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": PREFACE + "\n\n" + body}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
```

- [ ] **Step 4: GREEN.** Run: `zsh tools/tests/test_context_inject.zsh`
Expected: `ALL PASS` (15 checks).

- [ ] **Step 5: Mutation check** (edit, run, restore from a `cp` backup; report the four failing runs):
  - `keep = start` → `keep = i` (cut at the overflowing line instead of the entry's start) → the check "over the cap: cut at an entry boundary, body <= 8192 bytes, note names the path" FAILS.
  - `CAP = 8192` → `CAP = 10**9` → the same check FAILS.
  - delete ` && project="${project%-bg}"` from the `@tc_bg` line → "-bg pane: injects the project's file" FAILS.
  - delete the `[[ "$TC_CONTEXT" == 0 ]] …` line → "TC_CONTEXT=0: no output, exit 0" FAILS.

- [ ] **Step 6: Register the hook.** Apply this diff to `claude/plugin/hooks/hooks.json` and `claude/plugin/.claude-plugin/plugin.json` (no `matcher`: the hook fires on every source, startup, resume, clear and compact; timeout 5; `--scoped`, as the existing `test_plugin.zsh` check "uses CLAUDE_PLUGIN_ROOT/scripts for all four hooks" requires of every command).

```diff
diff --git a/claude/plugin/.claude-plugin/plugin.json b/claude/plugin/.claude-plugin/plugin.json
index efb0594..c488f5b 100644
--- a/claude/plugin/.claude-plugin/plugin.json
+++ b/claude/plugin/.claude-plugin/plugin.json
@@ -1,5 +1,5 @@
 {
   "name": "agent-board",
   "version": "0.1.0",
-  "description": "Agent Board session plugin: bash-mirror, kill-guard, artifact-register, plan-handoff-guard and sdd-call-guard hooks, the tmux-orchestrator and handoff skills, and the effort-* agent types. Loaded per session with --plugin-dir; nothing is installed into ~/.claude."
+  "description": "Agent Board session plugin: bash-mirror, kill-guard, artifact-register, plan-handoff-guard, sdd-call-guard and context-inject hooks, the tmux-orchestrator and handoff skills, and the effort-* agent types. Loaded per session with --plugin-dir; nothing is installed into ~/.claude."
 }
diff --git a/claude/plugin/hooks/hooks.json b/claude/plugin/hooks/hooks.json
index 59fee28..bddd3bf 100644
--- a/claude/plugin/hooks/hooks.json
+++ b/claude/plugin/hooks/hooks.json
@@ -1,5 +1,12 @@
 {
   "hooks": {
+    "SessionStart": [
+      {
+        "hooks": [
+          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/context-inject.sh\" --scoped", "timeout": 5 }
+        ]
+      }
+    ],
     "PreToolUse": [
       {
         "matcher": "Bash",
```

- [ ] **Step 7: Registration test.** In `tools/tests/test_plugin.zsh`, insert this block immediately before the line that starts `check "settings.json no longer registers hooks (no double run)"`:

```zsh
check "hooks.json registers context-inject on SessionStart (no matcher: every source), --scoped, timeout 5" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["SessionStart"]
hit = [(e.get("matcher"), h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/context-inject.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] is None and hit[0][1]["timeout"] == 5, hit
PY
```

  RED (with the diff of Step 6 reverted): `zsh tools/tests/test_plugin.zsh` prints `FAIL - hooks.json registers context-inject on SessionStart …` and `1 FAILED`. GREEN (diff applied): `ALL PASS`.

- [ ] **Step 8: Verify.** Run: `zsh tools/tests/test_context_inject.zsh && zsh tools/tests/test_plugin.zsh`
Expected: both print `ALL PASS`.

- [ ] **Step 9: Commit.**

```bash
git add claude/plugin/scripts/context-inject.sh tools/tests/test_context_inject.zsh claude/plugin/hooks/hooks.json claude/plugin/.claude-plugin/plugin.json tools/tests/test_plugin.zsh
git commit -m "feat(plugin): context-inject SessionStart hook injects the shared project context, capped at 8 KB"
```
End with the attribution trailer your harness specifies.

---

### Task 4: Teammate and lead rules, handoff skill

**Goal:** Teammate reports end with `Context learned:` bullets, the lead's merge, prune and condense duties are in `orchestrator.md`, and the handoff skill merges before relaying and carries one `Shared context:` line.

**Files:**
- Modify: `claude/orchestrator.md` (rule 4 of "Teammates and workers don't talk to the user"; new section after "Ideas inbox")
- Modify: `claude/plugin/skills/handoff/SKILL.md` (step 2 bullet list)
- Modify: `tools/tests/test_plugin.zsh` (five checks)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/test_plugin.zsh` prints `ALL PASS`; with the two rule files unedited it prints `4 FAILED`
- [ ] `orchestrator.md` rule 4 says the report ends with `Context learned:` bullets tagged `Map`, `How to run`, `Gotchas` or `Decisions`, citing `(files: …)`, limited to facts that would have saved the teammate time searching, `Context learned: none` otherwise, and that teammates never write the file
- [ ] `orchestrator.md` has a `## Shared project context` section naming `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, `tmux-ctl context add` at each deliverable (skip duplicates, re-date re-checked entries, delete wrong ones), pruning at `finishing-a-development-branch`, condensing over 8 KB, and never copying the file into briefs or handoffs
- [ ] The handoff skill's step 2 merges unmerged `Context learned` items first and writes exactly one line `Shared context: ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, never the entries, and leaves it out outside tmux
- [ ] Neither rule file names `~/.local/state/agent-board/context` without the `${TC_CONTEXT_DIR:-…}` form

**Verify:** `zsh tools/tests/test_plugin.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing checks.** In `tools/tests/test_plugin.zsh`, insert this block immediately before the line that starts `check "no rule or doc outside docs/superpowers history points at ~/.claude/ideas as THE path"`:

```zsh
# the shared context file (spec 2026-10-28-shared-project-context): the teammate rule, the lead's merge duty and the handoff line
check "orchestrator.md names Context learned" grep -qF 'Context learned' "$R/claude/orchestrator.md"
check "orchestrator.md tells the lead to merge with tmux-ctl context add" grep -qF 'tmux-ctl context add' "$R/claude/orchestrator.md"
check "lead and handoff rules name \${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}" test "$(grep -lF '${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | wc -l)" -eq 2
check "no rule names the context dir without TC_CONTEXT_DIR" test -z "$(grep -n '~/.local/state/agent-board/context' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | grep -vF '${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}')"
check "handoff skill merges Context learned before relaying" grep -qF 'Context learned' "$P/skills/handoff/SKILL.md"
```

- [ ] **Step 2: RED.** Run: `zsh tools/tests/test_plugin.zsh`
Expected: `4 FAILED`: "orchestrator.md names Context learned", "orchestrator.md tells the lead to merge with tmux-ctl context add", "lead and handoff rules name ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}", "handoff skill merges Context learned before relaying". ("no rule names the context dir without TC_CONTEXT_DIR" passes vacuously before the edit; it guards the wording after it.)

- [ ] **Step 3: Edit the rules.** Apply this diff to `claude/orchestrator.md` (teammate rule 4 gains the `Context learned` report ending; a new `## Shared project context` section follows `## Ideas inbox`) and `claude/plugin/skills/handoff/SKILL.md` (a `Shared context` bullet after `Ideas` in step 2).

```diff
diff --git a/claude/orchestrator.md b/claude/orchestrator.md
index 7963958..7bf68c9 100644
--- a/claude/orchestrator.md
+++ b/claude/orchestrator.md
@@ -59,6 +59,14 @@ The user keeps ideas for future work in `${TC_IDEAS_DIR:-~/.local/state/agent-bo
   3. Take each chosen group through `brainstorming`, one at a time.
   4. Mark ideas taken up as `- [x] … → <spec path>` and dropped ones as `- [-] …`. Never delete an idea.
 
+## Shared project context
+
+Every agent-board session starts with the project's shared context file, `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md` (`<project>` is the ideas key: the tmux session group, else the session name), injected by the plugin's `context-inject` SessionStart hook under the preface "Shared project context, curated by the lead". Sections, in a fixed order: `Map`, `How to run`, `Gotchas`, `Decisions`; one bullet per entry, `- <fact> (files: path/a, path/b) · YYYY-MM-DD`, the date being when the entry was last checked. You curate it; teammates only propose.
+- **At each deliverable** (a task's review passed, a teammate's report in): merge the durable `Context learned` items with `tmux-ctl context add <section> "<entry>"` (`add` dates the entry and creates the file with its four headings the first time). Skip items already there; re-date an entry a teammate checked again; delete one a teammate showed to be wrong. Rewording and deleting are ordinary edits with the Edit tool after `tmux-ctl context path`.
+- **At `finishing-a-development-branch`:** prune entries whose cited files the branch removed or renamed.
+- **Over 8 KB** (the hook's cap; it injects a truncated copy and says so): condense the oldest entries.
+- Never copy the file into briefs or handoff docs: every agent gets it from the hook. `tmux-ctl context show` prints it; `tmux-ctl artifact "$(tmux-ctl context path)"` opens it in the board's artifacts panel.
+
 ## Plan comments from the board
 
 A line starting `[Plan comment] <file> § <section>: "<quote>" — <note>` was sent by the user from the board's artifacts panel. Treat it as user feedback on that part of the plan:
@@ -144,7 +152,11 @@ paraphrase them, because a shorter copy loses rule 3's exception first.
 4. It reports back with evidence: commands run, their output, files changed, assumptions made. Where
    the repo maps changed paths to CI checks (`.agent-ci.yml`), it runs the mapped checks for its diff
    (`agent-ci check`) before reporting done, and again after every fix round. The brief's verify
-   command proves the task's own claim, not that nothing next to it broke.
+   command proves the task's own claim, not that nothing next to it broke. The report ends with
+   `Context learned:` bullets, each tagged with its section (`Map`, `How to run`, `Gotchas` or
+   `Decisions`), citing its files (`(files: …)`), and limited to facts that would have saved this
+   teammate time searching; `Context learned: none` when there are none. Teammates never write the
+   shared context file; only the lead does.
 5. Run test suites and long builds with `tmux-ctl run [-t secs] [-C dir] tests "<cmd>"` (options before
    the window): it runs in the hidden session `<project>-bg` (a lane window `tests·<you>` if `tests` is
    busy), in your own worktree unless `-C` says otherwise, and the user sees every run in the Agent
diff --git a/claude/plugin/skills/handoff/SKILL.md b/claude/plugin/skills/handoff/SKILL.md
index a69ef97..d01bd7c 100644
--- a/claude/plugin/skills/handoff/SKILL.md
+++ b/claude/plugin/skills/handoff/SKILL.md
@@ -31,6 +31,7 @@ To find "the recent handoff for this project", filter by the `Project:` line fir
 - **Team**: one entry per teammate, built from its checkpoint, so the next lead can respawn it as is. Lead with name, role and model tier, then the checkpoint note: task, files owned, progress, next step, assumptions, risks. Mark teammates without a reply as `no checkpoint` and include their captured output, if any.
 - **Previous session**: its id, so it stays resumable with `claude --resume <id>`. Write a placeholder first and fill it in as below.
 - **Ideas**: one line: `Ideas inbox: ${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md (do not read until the plan is done)`, with `TC_IDEAS_DIR` resolved from your environment when it is set. `<project>` is the tmux session name: `tmux display -p '#{?session_group,#{session_group},#{session_name}}'`. Never copy ideas into the doc. Outside tmux, leave this line out.
+- **Shared context**: first merge any unmerged `Context learned` items from teammate reports and checkpoints with `tmux-ctl context add <section> "<entry>"` (inside tmux). Then one line: `Shared context: ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, with `TC_CONTEXT_DIR` resolved from your environment when it is set and `<project>` as for Ideas. Never copy entries into the doc: the next orchestrator gets them from the SessionStart hook. Outside tmux, leave this line out.
 - **Suggested skills**: the skills the next lead should invoke with the Skill tool.
 
 Redact secrets and personal data.
```

- [ ] **Step 4: GREEN.** Run: `zsh tools/tests/test_plugin.zsh`
Expected: `ALL PASS` (the existing check "orchestrator.md / worker.md skill names resolve" still passes: the new text names no `ns:skill`).

- [ ] **Step 5: Commit.**

```bash
git add claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md tools/tests/test_plugin.zsh
git commit -m "docs(rules): Context learned in teammate reports; the lead curates the shared context; handoff names the file"
```
End with the attribution trailer your harness specifies.

---

### Task 5: Docs: hook, env vars and subcommand alongside the existing ones

**Goal:** `docs/INSTALL.md`, `docs/ARCHITECTURE.md`, `docs/CUSTOMIZATION.md` and the tmux-orchestrator skill name the hook, `TC_CONTEXT=0`, `TC_CONTEXT_DIR` and `tmux-ctl context` wherever the existing hooks, variables and subcommands are listed.

**Files:**
- Modify: `docs/INSTALL.md` (line 23 hook list; line 106 "four")
- Modify: `docs/ARCHITECTURE.md` (Other subcommands table; Hooks table and its closing line; new section after Ideas inbox; State paths; Tests table)
- Modify: `docs/CUSTOMIZATION.md` (§1 environment table)
- Modify: `claude/plugin/skills/tmux-orchestrator/SKILL.md` (command table)

**Acceptance Criteria:**
- [ ] The Verify command prints `docs/INSTALL.md:1`, `docs/ARCHITECTURE.md:3`, `docs/CUSTOMIZATION.md:2`, `1`, `docs/CUSTOMIZATION.md:1`, `docs/ARCHITECTURE.md:4`, `docs/INSTALL.md:1`, `1`, `ALL PASS`
- [ ] `grep -rl 'sdd-call-guard' docs/ README.md claude/ tools/tests/`, minus the guard's own script, test and fixtures and `writing-plans-extras`, lists only files that also contain `context-inject` (INSTALL.md, ARCHITECTURE.md, hooks.json, plugin.json, test_plugin.zsh)
- [ ] `docs/ARCHITECTURE.md` has a `## Shared project context` section and a hooks-table row for `context-inject.sh` naming the preface, the 8 KB cut, the silent cases and `TC_CONTEXT=0`
- [ ] `docs/CUSTOMIZATION.md` §1 has rows for `TC_CONTEXT_DIR` (default `~/.local/state/agent-board/context`) and `TC_CONTEXT`

**Verify:** `grep -c 'context-inject' docs/INSTALL.md docs/ARCHITECTURE.md docs/CUSTOMIZATION.md && grep -c 'tmux-ctl context' claude/plugin/skills/tmux-orchestrator/SKILL.md && grep -c 'TC_CONTEXT_DIR' docs/CUSTOMIZATION.md docs/ARCHITECTURE.md docs/INSTALL.md && grep -c 'lists none of the agent-board hooks' docs/INSTALL.md && zsh tools/tests/test_plugin.zsh 2>/dev/null | grep -E '^(ALL PASS|[0-9]+ FAILED)$'` → `docs/INSTALL.md:1`, `docs/ARCHITECTURE.md:3`, `docs/CUSTOMIZATION.md:2`, `1`, `docs/CUSTOMIZATION.md:1`, `docs/ARCHITECTURE.md:4`, `docs/INSTALL.md:1`, `1`, `ALL PASS`

**Steps:**

- [ ] **Step 1: RED.** Run the Verify command. Expected on the unedited files: `docs/INSTALL.md:0 docs/ARCHITECTURE.md:0 docs/CUSTOMIZATION.md:0` and exit 1 (the chain stops at the first grep).

- [ ] **Step 2: Edit the docs.** Apply this diff (generated from the files at `a59ffc7`). Every place that lists the plugin's hooks or `tmux-ctl`'s subcommands gains the new one (observation #102): the INSTALL hook list, the ARCHITECTURE hooks table, its "All hooks are silent" line (which also names the two guards' blocks, missing until now), its subcommand table and state paths and tests rows, a new `## Shared project context` section after `## Ideas inbox`, the CUSTOMIZATION environment table (`TC_CONTEXT_DIR`, `TC_CONTEXT`), and the tmux-orchestrator skill's command table. `INSTALL.md`'s "none of the four agent-board hooks" becomes "none of the agent-board hooks" (there are seven now); the migration table's "the four agent-board hooks … in `~/.claude/settings.json`" stays, it describes the pre-plugin install.

```diff
diff --git a/claude/plugin/skills/tmux-orchestrator/SKILL.md b/claude/plugin/skills/tmux-orchestrator/SKILL.md
index cf8d5cc..1a35044 100644
--- a/claude/plugin/skills/tmux-orchestrator/SKILL.md
+++ b/claude/plugin/skills/tmux-orchestrator/SKILL.md
@@ -36,6 +36,7 @@ The user watches agent runs in the Agent Board's Activity drawer and plans, spec
 | `tmux-ctl agents` | Each worker's state (working / WAITING ON USER / exited) and last lines |
 | `tmux-ctl artifact <path>` | Show a file in the board's artifacts panel |
 | `tmux-ctl idea "<text>"` | File an idea for later |
+| `tmux-ctl context show \| path \| add <section> "<entry>"` | The project's shared context file (sections `Map`, `How to run`, `Gotchas`, `Decisions`). The lead curates it; teammates propose `Context learned` items in their reports |
 | `tmux-ctl relay <doc>` | Used only by `/handoff`, and only the lead (the session's `claude` window) can run it: from any other window it refuses and prints the manual start command, which you give to the user |
 
 ## How to use it
diff --git a/docs/ARCHITECTURE.md b/docs/ARCHITECTURE.md
index e8ebb74..ae8b687 100644
--- a/docs/ARCHITECTURE.md
+++ b/docs/ARCHITECTURE.md
@@ -117,6 +117,7 @@ Design points:
 | `agents` | each worker's state (working / WAITING ON USER / exited) and last lines |
 | `artifact <path> [--kind K]` | register a file in the board's artifacts panel |
 | `idea <text>` | append to `~/.local/state/agent-board/ideas/<project>.md` |
+| `context show \| path \| add <section> "<entry>"` | the project's shared context file, `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`; see [Shared project context](#shared-project-context) |
 | `relay <doc> [--old-session ID]` | after this turn, restart the `claude` window as a fresh orchestrator reading `<doc>` (used by `/handoff`) |
 
 ## Agent teams and workers
@@ -141,9 +142,10 @@ The hooks ship in the agent-board plugin (`claude/plugin/hooks/hooks.json`, scri
 | PostToolUse + PostToolUseFailure, `Bash` | `bash-mirror.sh` | `feed-<project>-{tests,shell}.log` | Classifies the command as `tests` (pytest, make, npm test, go test, cargo, terraform plan, …) or `shell`, appends a header `── HH:MM:SS · agent · cwd · exit N · @epoch`, the first line and the last 12 output lines. Skips `tmux-ctl` calls (those are recorded as runs). Caps the log at 2 MB (keeps the last 1 MB). Only in dev sessions. |
 | PostToolUse, `Write\|Edit\|MultiEdit\|Artifact` | `artifact-register.sh` | `artifacts-<project>.jsonl` | Kinds by path: `docs/superpowers/plans/` → plan, `…/specs/` → spec, `~/.local/state/agent-board/handoffs/` (or the old `~/.claude/handoffs/`) or a tmp `*handoff*` → handoff, `scratchpad/*report*` → report, Artifact tool URL → published. Other files are ignored unless registered by hand (`--path`). Records sha256, agent, session id and epoch. |
 | PostToolUse, `Bash` | `worktree-sweep.sh` | `feed-<project>-shell.log` (a `swept: removed …; kept …` entry, dev sessions only); the sweep log is the engine's | Acts only when the command contained `git merge`, `git pull`, `glab mr merge` or `git branch -d/-D`; then starts `agent-worktrees sweep <repo>` in the background and never blocks or fails the call. See [Worktree cleanup](#agent-teams-and-workers). |
+| SessionStart (no matcher: startup, resume, clear and compact) | `context-inject.sh` | nothing; prints `hookSpecificOutput.additionalContext` | Injects `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md` (`<project>` is the ideas key, `-bg` stripped) under the preface "Shared project context, curated by the lead; propose additions as 'Context learned' in your report." Over 8 KB it keeps the last whole entry that fits and appends `… truncated, full file at <path>`. No file, an empty one, no tmux pane or any error: silent exit 0. `TC_CONTEXT=0` disables it. See [Shared project context](#shared-project-context). |
 | Stop / PostToolUse `TaskUpdate` (optional, not registered by agent-board; `claude/hooks/`) | `superpowers-hook.sh <name>` | — | Finds the superpowers-extended-cc plugin wherever it is installed and runs its example hook; silent no-op without the plugin. |
 
-All hooks are silent and exit 0 except kill-guard's deliberate block.
+All hooks are silent and exit 0, except the deliberate blocks of `kill-guard`, `plan-handoff-guard` and `sdd-call-guard` (exit 2) and `context-inject`'s `additionalContext` output.
 
 ## The Agent Board
 
@@ -236,6 +238,10 @@ Plan comments and `[Board]` requests sit in an in-memory `CommentQueue` per proj
 
 `board/ideas.py` owns `${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md` (an older `~/.claude/ideas/<project>.md` is copied across on first use, and the original stays). Each idea is `- [ ] YYYY-MM-DD HH:MM · text` with indented detail lines; `[x]` means taken up (`→ <spec>`), `[-]` dropped (or `→ moved to <project>`). Ideas are never deleted. Writers take an exclusive `fcntl` lock on `<file>.lock`. Edits address an idea by a key and raise `Stale` (HTTP 409) if the file changed underneath. The lead files `idea:` messages here and only reads the file once a plan is finished.
 
+## Shared project context
+
+`board/context.py` owns `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`: one curated Markdown file per project with a `Last curated: YYYY-MM-DD` line and four sections in a fixed order (`Map`, `How to run`, `Gotchas`, `Decisions`), one bullet per entry, `- <fact> (files: path/a, path/b) · YYYY-MM-DD` (the date is when the entry was last checked; `(files: …)` is expected for Map and How-to-run entries, so a staleness check can be added later). `add` creates the file with its four headings the first time, appends under the named heading, dates an undated entry, refuses an unknown section, and takes the same exclusive `fcntl` lock on `<file>.lock` as `ideas.py`; the lead's pruning and rewording are plain edits of the file. `tmux-ctl context show | path | add <section> "<entry>"` calls it with the ideas key. The plugin's SessionStart hook `context-inject.sh` injects the file into every agent-board lead, teammate and worker, capped at 8 KB (see [Hooks](#hooks)); teammates propose entries as `Context learned` bullets in their reports, and only the lead writes. Nothing is committed to the repo.
+
 ## State files
 
 Runtime state lives in `TC_STATE`, default `${TMPDIR:-/tmp}/tmux-ctl-$UID/`. It is per-user and is deleted per project when the session closes.
@@ -262,14 +268,14 @@ Durable user data is in `~/.local/state/agent-board/` (`ideas/`, `handoffs/`, `w
 - **Claude Code.** Every Claude agent-board starts (the lead via `claude-orchestrator`, workers via `tmux-ctl agent`) gets `--settings <clone>/claude/session-settings.json` and `--plugin-dir <clone>/claude/plugin` from `bin/_ab_claude.zsh`, so the hooks, skills and agent types exist only in those sessions. Teammates get the lead's own `--settings` and `--plugin-dir` flags from Claude Code; the tmux session environment carries only `PATH` and `AGENT_BOARD_REPO`, which `claude-orchestrator` sets on the session. `~/.claude` is never written, except by `install.sh --migrate`, which removes what the earlier global install left there.
 - **tmux.** `bin/_tc_bins.zsh` is the one resolver for the tmux command. Its order, first match wins: `TMUX_DASH_TMUX_ARGS`; the server named by `$TMUX` (hooks, `tmux-ctl`, the tests; skipped by the entry points `dev` and `tmux-dash`, which always use agent-board's server); otherwise `tmux -L ${AGENT_BOARD_TMUX_SOCKET:-agent-board} -f <clone>/config/tmux.conf`. A server started that way loads `config/tmux.conf` (the `after-split-window` and `session-closed` hooks, bell and passthrough options, the `D`, `f` and `W` bindings) instead of `~/.tmux.conf`. `board/paneclass.py` asks the same resolver, so Python and zsh agree on the server.
 - **Legacy detection.** On an install from before the dedicated server, `tc_tmux_legacy` is true: `~/.tmux.conf` still has agent-board's hook lines (`tmux-teammate-window` or `tmux-session-closed`) and no `agent-board` server is running. Then `dev` and `tmux-dash` keep using the user's own server until `install.sh --migrate` removes those lines. "The user's own server" is the one the command was typed in when `$TMUX` is set (`-S` its socket), else tmux's default server.
-- **State paths.** Durable data: `~/.local/state/agent-board/` (`ideas/`, `handoffs/`, `migrated-YYYYMMDD/`). Board process state: `~/.local/state/tmux-dash/`. Runtime state: `TC_STATE`. Optional user overrides: `~/.config/agent-board/` (`orchestrator.md`, `worker.md`, `tmux.local.conf`, `usage-alerts.json`).
+- **State paths.** Durable data: `~/.local/state/agent-board/` (`ideas/`, `context/`, `handoffs/`, `migrated-YYYYMMDD/`). Board process state: `~/.local/state/tmux-dash/`. Runtime state: `TC_STATE`. Optional user overrides: `~/.config/agent-board/` (`orchestrator.md`, `worker.md`, `tmux.local.conf`, `usage-alerts.json`).
 - **Helper binaries.** ttyd and fzf come from `TTYD_BIN` / `FZF_BIN`, else `PATH`, else `~/.local/bin/<tool>`; tmux from `TC_TMUX`, else `~/.local/bin/tmux` if executable, else `tmux` on `PATH` (`tc_tmux_bin`; `board/paneclass.py` uses the same order).
 
 ## Tests
 
 | Suite | Command | How it isolates |
 | --- | --- | --- |
-| Board (Python `unittest`) | `python3 -m unittest discover -s board/tests` | temporary `TC_STATE` / `TC_IDEAS_DIR`, fake tmux runners |
+| Board (Python `unittest`) | `python3 -m unittest discover -s board/tests` | temporary `TC_STATE` / `TC_IDEAS_DIR` / `TC_CONTEXT_DIR`, fake tmux runners |
 | Install helpers (Python `unittest`) | `python3 -m unittest discover -s tools/tests -p 'test_*.py'` | `install_lib` (the `install.sh --migrate` settings and tmux edits) on temporary files |
 | Toolkit (zsh) | `zsh tools/tests/run-all.zsh` | `tools/tests/lib.zsh` starts a private tmux server (`-L tctest-…  -f /dev/null`) with a temp `TC_STATE`, and kills it on exit. Covers tmux-ctl, the dev layout, the plugin and hooks, `install.sh` |
 
diff --git a/docs/CUSTOMIZATION.md b/docs/CUSTOMIZATION.md
index 2fbd854..84900b2 100644
--- a/docs/CUSTOMIZATION.md
+++ b/docs/CUSTOMIZATION.md
@@ -30,6 +30,8 @@ A project-specific settings file is not an override: it is passed per lead, see
 | `TC_SESSION` | caller's session | `tmux-ctl` | Target a different session (the board sets it for actions). |
 | `TC_LAYOUT` | `tmux-dev-layout` next to `dev` | `dev` | Replace the layout step with your own script (called as `<script> <session> <root>`). |
 | `TC_IDEAS_DIR` | `~/.local/state/agent-board/ideas` | `ideas.py` (board, `tmux-ctl idea`) | Where idea files live. |
+| `TC_CONTEXT_DIR` | `~/.local/state/agent-board/context` | `context.py` (`tmux-ctl context`), `context-inject.sh` | Where the shared project context files live. |
+| `TC_CONTEXT` | unset | `context-inject.sh` | `0` turns off the SessionStart injection of the shared context file. |
 | `TC_AGENT_DRYRUN` | unset | `tmux-ctl agent` | Test seam: print the task and stop before creating a window. |
 | `TMUX_DASH_PORT` | `7700` | `tmux-dash`, `server.py` | Board HTTP port. |
 | `TMUX_DASH_TTYD_PORT` | `7701` | `tmux-dash`, `server.py` | ttyd port. |
diff --git a/docs/INSTALL.md b/docs/INSTALL.md
index 9855a22..452549f 100644
--- a/docs/INSTALL.md
+++ b/docs/INSTALL.md
@@ -20,7 +20,7 @@ agent-board installs from a clone of this repo with one script, `install.sh`, an
 | `~/.config/agent-board/` | **not created**; optional overrides you write yourself ([CUSTOMIZATION](CUSTOMIZATION.md)) | none |
 | `~/.claude/projects/` (your transcripts) | **read only**, by the board's Usage tab | none: nothing is written there |
 
-How the rest reaches Claude without touching `~/.claude`: every Claude that agent-board starts gets `--settings` with the settings file in `<clone>/claude/` (agent teams, `teammateMode`, the `AGENT_BOARD=1` marker) and `--plugin-dir <clone>/claude/plugin` (the `bash-mirror`, `artifact-register`, `kill-guard` and `worktree-sweep` hooks, `plan-handoff-guard` (refuses writing-plans' execution-choice question; `PLAN_HANDOFF_GUARD=0` disables it), `sdd-call-guard` (denies an Agent dispatch while a plan has no `subagent-driven-development` Skill call, which would make superpowers' handoff guard refuse later questions; `SDD_CALL_GUARD=0` disables it), the `tmux-orchestrator` and `handoff` skills, the `effort-low`/`-medium`/`-high` agent types). That covers the lead, the workers started by `tmux-ctl agent`, and the teammates, which Claude Code starts with the lead's own `--settings` and `--plugin-dir` flags. Plain `claude` outside agent-board loads none of it.
+How the rest reaches Claude without touching `~/.claude`: every Claude that agent-board starts gets `--settings` with the settings file in `<clone>/claude/` (agent teams, `teammateMode`, the `AGENT_BOARD=1` marker) and `--plugin-dir <clone>/claude/plugin` (the `bash-mirror`, `artifact-register`, `kill-guard` and `worktree-sweep` hooks, `plan-handoff-guard` (refuses writing-plans' execution-choice question; `PLAN_HANDOFF_GUARD=0` disables it), `sdd-call-guard` (denies an Agent dispatch while a plan has no `subagent-driven-development` Skill call, which would make superpowers' handoff guard refuse later questions; `SDD_CALL_GUARD=0` disables it), `context-inject` (a SessionStart hook that injects the project's shared context file, `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, capped at 8 KB; `TC_CONTEXT=0` disables it), the `tmux-orchestrator` and `handoff` skills, the `effort-low`/`-medium`/`-high` agent types). That covers the lead, the workers started by `tmux-ctl agent`, and the teammates, which Claude Code starts with the lead's own `--settings` and `--plugin-dir` flags. Plain `claude` outside agent-board loads none of it.
 
 > **Used the author's earlier global setup, or an earlier version of this guide?** Run `./install.sh --migrate` (see [Migrating](#migrating-from-the-global-setup)). Otherwise the old global hooks run next to the new ones.
 
@@ -103,7 +103,7 @@ Detach with the usual `Ctrl-b d`. agent-board's tmux server uses tmux's default
 
 **Your own setup is untouched:**
 
-Nothing under `~/.claude` was written by `./install.sh`. In a plain `claude` session started outside agent-board, `/hooks` lists none of the four agent-board hooks. In the agent-board lead, `/hooks` lists them.
+Nothing under `~/.claude` was written by `./install.sh`. In a plain `claude` session started outside agent-board, `/hooks` lists none of the agent-board hooks. In the agent-board lead, `/hooks` lists them.
 
 ### Things to know
 
```

- [ ] **Step 3: GREEN.** Run the Verify command. Expected: `docs/INSTALL.md:1`, `docs/ARCHITECTURE.md:3`, `docs/CUSTOMIZATION.md:2`, `1`, `docs/CUSTOMIZATION.md:1`, `docs/ARCHITECTURE.md:4`, `docs/INSTALL.md:1`, `1`, `ALL PASS`.

- [ ] **Step 4: Commit.**

```bash
git add docs/INSTALL.md docs/ARCHITECTURE.md docs/CUSTOMIZATION.md claude/plugin/skills/tmux-orchestrator/SKILL.md
git commit -m "docs: shared project context, the context-inject hook, TC_CONTEXT_DIR and tmux-ctl context alongside the existing entries"
```
End with the attribution trailer your harness specifies.

---

### Task 6: End to end on a scratch server with real aged state

**Goal:** On a scratch tmux server, a seeded entry reaches a fresh Claude's first turn through the hook, a lead with the new rules merges a `Context learned` item with `tmux-ctl context add`, the hook cuts a real aged file at an entry boundary, and the real context folder is untouched.

**USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `tools/tests/e2e-context.zsh`
- Create: `docs/superpowers/plans/2026-10-28-shared-project-context-e2e-report.md`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/e2e-context.zsh` prints `ALL PASS` (6 checks), with the haiku reply containing the seeded codeword, the Gotchas entry present after the sonnet lead's turn, the real ideas file cut at an entry boundary within 8192 bytes, and `~/.local/state/agent-board/context` listed identically before and after
- [ ] All writes went to the scratch `TC_STATE`, `TC_IDEAS_DIR` and `TC_CONTEXT_DIR` under `$TT_DIR` (removed by `tt_teardown`); the real `~/.local/state/agent-board/ideas/agent-board.md` was only copied
- [ ] `python3 -m unittest discover -s board/tests` prints `Ran 482 tests` and `OK`; `zsh tools/tests/run-all.zsh` exits 0 with `grep -c '^FAIL'` = 0 and lists `### test_context_inject.zsh` and `### test_ctl_context.zsh`
- [ ] The report exists with the seven sections and quotes the outputs, and is registered in the artifacts panel

**Verify:** `zsh tools/tests/e2e-context.zsh` → `ALL PASS` (6 checks)

**Steps:**

- [ ] **Step 1: Write the e2e script.** Create `tools/tests/e2e-context.zsh` exactly as below (named `e2e-…`, not `test_…`, so `run-all.zsh` does not pay its two API calls). It needs a terminal, `claude` on PATH and the real file `~/.local/state/agent-board/ideas/agent-board.md` (over 8 KB; the script skips step 3 with a `skip -` line if it is not).

```zsh
#!/usr/bin/env zsh
# e2e-context.zsh — shared project context, end to end, on a scratch tmux server (lib.zsh, `-L tctest-… -f /dev/null`):
#   1. a seeded entry reaches a fresh Claude's first turn through the plugin's SessionStart hook (headless haiku, run in
#      the scratch session's pane environment, so the key is `tt`);
#   2. a lead running with claude/orchestrator.md merges a teammate's "Context learned" item with `tmux-ctl context add`
#      (headless sonnet, Bash allowed for `tmux-ctl context` only);
#   3. the hook's truncation on a REAL aged file: a read-only copy of ~/.local/state/agent-board/ideas/agent-board.md
#      (15 KB, entries dated across days; the same bullet shape) is injected cut at an entry boundary within 8 KB;
#   4. the real context folder ~/.local/state/agent-board/context is untouched (listing before == after).
# Not a test_*.zsh: run-all does not pick it up (it makes two small API calls). Run it from the worktree:
#   zsh tools/tests/e2e-context.zsh
# Every write goes to the scratch TC_STATE, TC_IDEAS_DIR and TC_CONTEXT_DIR under $TT_DIR, removed by tt_teardown.
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
source "$R/bin/_ab_claude.zsh"
REAL="$HOME/.local/state/agent-board/context"
before="$(ls -la "$REAL" 2>&1)"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx" TC_IDEAS_DIR="$TT_DIR/ideas" PATH="$R/bin:$PATH"
C="$R/bin/tmux-ctl"; H="$R/claude/plugin/scripts/context-inject.sh"
print -r -- "scratch socket: $TT_SOCK_NAME · TC_CONTEXT_DIR=$TC_CONTEXT_DIR · TC_STATE=$TC_STATE"
print -r -- "--- real context folder before: $before"

# 1. seed (as the lead would) and a fresh agent's first turn
word="QUARTZ-$$"
$C context add Map "the board server is board/server.py and the codeword for this run is $word (files: board/server.py)"
print -r -- "--- seeded file ($TC_CONTEXT_DIR/tt.md):"; cat "$TC_CONTEXT_DIR/tt.md"
work="$TT_DIR/work"; mkdir -p "$work"; git -C "$work" init -q
a1="$(cd "$work" && claude -p --model haiku ${(Q)${(z)"$(ab_claude_args)"}} 'What is the codeword in the shared project context you were given? Reply with the codeword only.' </dev/null 2>"$TT_DIR/a1.err")"
print -r -- "--- first-turn reply (haiku): $a1"
check "1. seeded entry reached a fresh agent's first turn" zsh -c '[[ $1 == *"$2"* ]]' _ "$a1" "$word"
[[ "$a1" == *"$word"* ]] || cat "$TT_DIR/a1.err"

# 2. the lead merges a teammate's "Context learned" item as orchestrator.md says
prompt="A teammate's final report ended with:
Context learned:
- Gotchas: test_ctl_busy.zsh needs an idle tests window first (files: tools/tests/test_ctl_busy.zsh)
Merge it into the shared project context as your rules say, then reply with the single word done."
# the prompt goes on stdin: --allowedTools takes every following word (claude 2.1.312), so a prompt argument after it is swallowed
a2="$(cd "$work" && print -r -- "$prompt" | claude -p --model sonnet ${(Q)${(z)"$(ab_claude_args)"}} --append-system-prompt-file "$R/claude/orchestrator.md" --allowedTools 'Bash(tmux-ctl context:*)' 2>"$TT_DIR/a2.err")"
print -r -- "--- lead reply (sonnet): $a2"
print -r -- "--- file after the merge:"; cat "$TC_CONTEXT_DIR/tt.md"
check "2. the lead merged the item under Gotchas" sh -c "sed -n '/^## Gotchas/,/^## Decisions/p' ${(q)TC_CONTEXT_DIR}/tt.md | grep -q 'test_ctl_busy.zsh needs an idle tests window'"
check "2. Map entry still there (no rewrite of other sections)" grep -q "$word" "$TC_CONTEXT_DIR/tt.md"
grep -q 'test_ctl_busy.zsh needs an idle tests window' "$TC_CONTEXT_DIR/tt.md" || cat "$TT_DIR/a2.err"

# 3. truncation on a real aged file (read-only copy; the real file is never opened for writing)
real_ideas="$HOME/.local/state/agent-board/ideas/agent-board.md"
if [[ -s "$real_ideas" && $(wc -c < "$real_ideas") -gt 8192 ]]; then
  cp "$real_ideas" "$TC_CONTEXT_DIR/tt.md"
  print -r -- "--- real aged file: $real_ideas, $(wc -c < "$real_ideas") bytes, dates $(grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$real_ideas" | sort -u | sed -n '1p;$p' | tr '\n' ' ')"
  print -r -- '{"session_id":"e2e","transcript_path":"/tmp/none.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' | "$H" --scoped > "$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?
  check "3. hook exit 0, nothing on stderr" test $rc -eq 0 -a ! -s "$TT_DIR/e"
  check "3. cut at an entry boundary, body <= 8192 bytes, note names the path" python3 - "$TC_CONTEXT_DIR/tt.md" "$TT_DIR/o" <<'PY'
import json, sys
src = open(sys.argv[1]).read(); ctx = json.load(open(sys.argv[2]))["hookSpecificOutput"]["additionalContext"]
preface = "Shared project context, curated by the lead; propose additions as 'Context learned' in your report.\n\n"
assert ctx.startswith(preface); rest = ctx[len(preface):]
note = "… truncated, full file at " + sys.argv[1] + "\n"; assert rest.endswith(note), rest[-200:]
body = rest[:-len(note)]; assert len(body.encode()) <= 8192, len(body.encode())
lines = src.splitlines(keepends=True)
cuts = [i for i, l in enumerate(lines) if l.startswith(("- ", "## "))] + [len(lines)]
best = max(c for c in cuts if len("".join(lines[:c]).encode()) <= 8192)
assert body == "".join(lines[:best]).rstrip("\n") + "\n"
print(f"kept {best} of {len(lines)} lines, {len(body.encode())} bytes; last kept line: {body.rstrip().splitlines()[-1][:80]}")
PY
else
  print -r -- "skip - no real ideas file over 8 KB at $real_ideas"
fi

# 4. real state untouched
after="$(ls -la "$REAL" 2>&1)"
check "4. real context folder unchanged" test "$before" = "$after"
print -r -- "--- real context folder after: $after"
tt_done
```

- [ ] **Step 2: Run it once:** `zsh tools/tests/e2e-context.zsh`
Expected: `ALL PASS` (6 checks). The author's run (2026-10-28, on the complete change set): haiku replied the codeword (`QUARTZ-<pid>`); sonnet, given only `claude/orchestrator.md`, ran `tmux-ctl context add Gotchas …` and replied `done`, and the Map entry stayed; the real ideas file (15,778 bytes, dates 2026-10-16..28) was cut to 30 of 60 lines, 7,973 bytes, last kept line a complete `- [x] 2026-10-16 15:23 · …` entry; `~/.local/state/agent-board/context` did not exist before or after. If step 2 fails because the lead did not run the command, read `$TT_DIR/a2.err` (printed by the script) before touching the rules: the prompt is on stdin because `--allowedTools` takes every following word.

- [ ] **Step 3: Whole suites on the branch.** Run `python3 -m unittest discover -s board/tests` (expected `Ran 482 tests` … `OK`) and, through `tmux-ctl run -t 2400 tests 'zsh tools/tests/run-all.zsh > /tmp/runall.$$.log 2>&1; echo rc=$?; grep -c "^FAIL" /tmp/runall.$$.log'` (expected `rc=0` and `0`; the verdict is the exit code plus the uncapped FAIL count, never a `tail`). `run-all.zsh` prints `### test_context_inject.zsh` and `### test_ctl_context.zsh`: the new files are picked up.

- [ ] **Step 4: Write the report** `docs/superpowers/plans/2026-10-28-shared-project-context-e2e-report.md` with these sections, each quoting the script's output verbatim: `## Setup` (socket name, `TC_CONTEXT_DIR`, `TC_STATE`, models used), `## 1. First turn` (seeded file, haiku reply), `## 2. Lead merge` (sonnet reply, file after), `## 3. Real aged file` (path, size, date span, the `kept N of M lines` line), `## 4. Real state` (the before/after listing of `~/.local/state/agent-board/context`), `## Suites` (the two verdict lines of Step 3), `## Bugs found` (or `none`). The Write hook registers it in the board's artifacts panel (`scratchpad/*report*` is not its path, so run `tmux-ctl artifact <report> --kind report` after writing).

- [ ] **Step 5: Commit.**

```bash
git add tools/tests/e2e-context.zsh docs/superpowers/plans/2026-10-28-shared-project-context-e2e-report.md
git commit -m "test(e2e): shared project context end to end on a scratch server, with the real aged ideas file"
```
End with the attribution trailer your harness specifies.

- [ ] **After the merge (the lead, from `main`):** `zsh tools/tests/e2e-context.zsh` once more, the spec's "E2E after merge"; paste its `ALL PASS` line into the report under `## After merge`.

---

## Self-review (done by the author, 2026-10-28)

- **Spec coverage:** file path/layout/sections/entries/`add` rules/lock → Task 1; `tmux-ctl context` + `--project "$FEEDKEY"` + artifacts panel → Task 2; hook, registration, preface, cap, no-file, `TC_CONTEXT=0`, errors → Task 3; teammate `Context learned` rule, lead duties (merge, skip, re-date, delete, prune at finishing, condense over 8 KB), handoff merge and `Shared context:` line → Task 4; INSTALL/ARCHITECTURE (+CUSTOMIZATION, skill table) → Task 5; the spec's `test_context.py`, `test_context_inject.zsh` and `test_plugin.zsh` items → Tasks 1, 3, 4; "E2E after merge" → Task 6 plus the lead's post-merge re-run. Out of scope stays out: no staleness check, no transcript mining, no cross-project context.
- **Placeholders:** none; every code step carries the full file or the generated diff.
- **Names:** `context_path`, `context_dir`, `show`, `add(project, section, entry, now=None)`, `SECTIONS`, `DATED_RE` are used identically in Tasks 1, 2 (CLI: `show|path|add --project P --section S -- TEXT`) and 6; the preface string, cap and note are identical in Tasks 3, 4, 5 and 6.
- **Verify = verifyCommand:** each task's Verify command is byte-identical to its `verifyCommand` in `.tasks.json` (checked mechanically by the author).
