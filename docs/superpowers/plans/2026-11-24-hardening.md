# Hardening (SHA-pinned merge approval, safe and easy scout sources, context recall for teammates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three independent hardening parts: (a) the Discord Merge button's approval line carries the full SHA and the lead merges only that SHA; (b) one URL safety check for every scout source add, request and fetch hop, kind detection, and an instant ✅ add from `#scout` or `/source`; (c) a PostToolUse hook that gives teammates the archived context entries for the files they touch.

**Architecture:** (a) is a one-line change in `board/discord_merge.py` plus a continuation paragraph under Queue mode step 2 of `claude/orchestrator.md`. (b) puts `check_url_safe` and `detect` in `board/scout_sources.py`. `board/scout_fetch.py` stops urllib from following redirects and follows them by hand, checking each hop. A single add path (`add_url`) serves the CLI, `#scout` and `/source`, and the Discord side reaches it through the existing bridge-event → `discord_controls` path. (c) is a new hook script, `claude/plugin/scripts/context-recall-file.sh`, modelled on `context-recall.sh`.

**Tech Stack:** Python 3 standard library (`board/`, runs under both python.org 3.14 and launchd's `/usr/bin/python3` 3.9), Node (`tools/discord-bridge`, `node --test`), bash and zsh hooks and tests, tmux 3.8 for the scratch-server tests.

**Spec:** docs/superpowers/specs/2026-11-23-hardening-design.md

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-23-hardening-design.md",
 "base": "ec8b2098142d6daf991b86ae18cc029d141b7cd8",
 "refreshed_from": {"base": "8b6ef53ab674e52449a1e39220d29633bf6e3477",
                    "stale_paths": ["bin/tmux-ctl", "board/discord_feed.py", "board/discord_ops.py", "claude/orchestrator.md",
                                    "tools/discord-bridge/bridge.js", "tools/discord-bridge/lib/commands.js",
                                    "tools/discord-bridge/test/commands.test.js", "tools/discord-bridge/test/fake-client.js",
                                    "tools/tests/test_plugin.zsh"]},
 "depends_on": [],
 "writes": [
  {"path": "board/discord_merge.py", "mode": "modify"},
  {"path": "board/tests/test_discord_merge.py", "mode": "modify"},
  {"path": "claude/orchestrator.md", "mode": "modify"},
  {"path": "tools/tests/test_queue_ask_rule.zsh", "mode": "modify"},
  {"path": "board/scout_sources.py", "mode": "modify"},
  {"path": "board/scout_fetch.py", "mode": "modify"},
  {"path": "board/tests/test_scout_sources.py", "mode": "modify"},
  {"path": "board/tests/test_scout_fetch.py", "mode": "modify"},
  {"path": "board/tests/test_scout_fetch_local.py", "mode": "modify"},
  {"path": "bin/tmux-ctl", "mode": "modify"},
  {"path": "board/discord_controls.py", "mode": "modify"},
  {"path": "board/tests/test_discord_controls.py", "mode": "modify"},
  {"path": "tools/discord-bridge/lib/commands.js", "mode": "modify"},
  {"path": "tools/discord-bridge/bridge.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/commands.test.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/scout-source.test.js", "mode": "create"},
  {"path": "claude/plugin/scripts/context-recall-file.sh", "mode": "create"},
  {"path": "claude/plugin/hooks/hooks.json", "mode": "modify"},
  {"path": "tools/tests/test_context_recall_file.zsh", "mode": "create"},
  {"path": "tools/tests/test_plugin.zsh", "mode": "modify"}
 ],
 "reads": ["claude/plugin/scripts/context-recall.sh", "tools/tests/test_context_recall.zsh", "tools/tests/lib.zsh",
           "board/discord_ops.py", "board/discord_feed.py", "tools/discord-bridge/test/fake-client.js",
           "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/liveness-bridge.test.js",
           "claude/plugin/scripts/spec-boundary-nudge.sh"],
 "produces": ["scout_sources.check_url_safe", "scout_sources.detect", "scout_sources.add_url", "context-recall-file hook"],
 "consumes": [],
 "tests": ["board/tests/test_discord_merge.py", "tools/tests/test_queue_ask_rule.zsh", "board/tests/test_scout_sources.py",
           "board/tests/test_scout_fetch.py", "board/tests/test_scout_fetch_local.py", "board/tests/test_discord_controls.py",
           "tools/discord-bridge/test/commands.test.js", "tools/discord-bridge/test/scout-source.test.js",
           "tools/tests/test_context_recall_file.zsh", "tools/tests/test_plugin.zsh"]}
```

## Global Constraints

- The live install runs this checkout's `main`, so nothing here touches live state. That rules out the live bridge, `~/.local/state/agent-board/scout`, the real `access.json`, the real archive (read-only checks only) and the live Discord channels. Board tests set `TC_STATE` (and `TC_SCOUT_DIR`) to temp dirs, as the existing classes do.
- The scout suites keep their local `http://127.0.0.1` server. The URL check has two test seams: `scout_sources._HTTP_OK_HOSTS` (empty in production; a host listed there skips both the scheme and the address test) and `scout_sources._resolve(host)` (the resolver). Every scout test `Base.setUp` patches both, `_HTTP_OK_HOSTS = ("127.0.0.1",)` and `_resolve` returning `["93.184.215.14"]`, so no test resolves a real name except the one test that has to.
- Python code runs under `/usr/bin/python3` 3.9 (launchd) as well as 3.14. Use no syntax or stdlib API newer than 3.9. Both interpreters were run once on the T3/T4 code below and passed.
- `bin/tmux-ctl help` prints a pinned line range (`sed -n '2,86p'` on main since new-project-remote added the `project` line; 9 suites pin it). The scout help line (still line 79 on main) is edited in place and no header line is added.
- Refreshed against main `ec8b209` (2026-11-24). Every plan-authored diff in Tasks 1–4 and 6 was re-applied to main with `patch -p1` (no offset, no fuzz). On a patched copy of main, the scout suites ran (138 tests OK), `test_discord_merge.py` was OK, and `test_queue_ask_rule.zsh` gave `9 FAILED` before the Task 2 rule edit and `ALL PASS` after it. Main has 9 `^  N. ` lines in `claude/orchestrator.md` before and after.
- `tools/discord-bridge/bridge.js` on main (remote-lead-liveness): every channel send goes through `sendOwn(ch, payload)`, and a message reply goes through `noteOwn(await msg.reply(…))`. Both record the message id in `st.own_sent`, so liveness does not count the bridge's own post as the lead's answer. `tools/discord-bridge/test/liveness-bridge.test.js` ("guard: every home-channel send goes through the one noteOwn helper") pins exactly one `.send(` and one non-interaction `.reply(` in `bridge.js`. No task adds a raw `.send(` or message `.reply(` to `bridge.js`, and none edits that guard test. Interaction replies (`i.reply`, `i.deferReply`, `i.editReply`) are not channel sends.
- `claude/orchestrator.md` Queue mode step lines are matched one line each (`^  N. `) by `tools/tests/test_plugin.zsh` and `tools/tests/test_queue_ask_rule.zsh`. New rule text goes on a continuation paragraph (5-space indent), never as a new step line.
- zsh suites run as `env -u AGENT_BOARD_LEAD zsh <test>`. The board suite as a whole runs through `tmux-ctl run -t 900 tests "…"`, never with its exit code read through a `| tail` pipe.
- The bridge tests run with `npm test` inside `tools/discord-bridge`. A fresh worktree runs `npm ci` there first.
- Commits are path-scoped (`git add <paths>`, `git commit -- <paths>` style) and conventional with a scope (`fix(discord): …`, `feat(scout): …`, `feat(plugin): …`). They end with the attribution trailer your harness specifies.
- Error and reason strings are fixed by the spec. A refusal is `Refusal("<class> address <ip>")` (`private address 10.0.0.5`, `link-local address 169.254.169.254`, …), `url must start with https://` or `host does not resolve: <host>`. A fetch refusal is `scout_fetch.Refused("refused: <reason>")`, a `FetchError` subclass, so the fetchers' "raises FetchError only" contract holds.

**User decisions (already made):**
- One spec, three parts (user, Discord, 2026-11-23, E-Q1 1).
- Adding a scout source must be easy: `source: <url>` or `/source <url>` detects the kind, and ✅ adds it at once with a test fetch whose result is shown (user, Discord, 2026-11-23, E-Q2 1).

**Assumptions (planner, not asked):**
- A1. `_HTTP_OK_HOSTS` exempts a host from the address test as well as the scheme test. It is a test seam, empty in production. Without this, the local 127.0.0.1 test server could not be fetched.
- A2. The Discord REST calls (`scout_fetch._discord`, a fixed configured API base, not a source URL) do not go through `check_url_safe`. Only `get()`, the source-URL fetch, does. Redirects are off for `_discord` too, since the opener has no redirect handler.
- A3. The default name is the existing `request_name` rule: the host's first label without `www.`, plus the first path segment, slugged, with `-2`, `-3`… on a clash. Examples: `github-anthropics`, `npmjs-package`. The spec's "host without `www.`" is read as that rule. The optional `[name]` argument overrides it.
- A4. The `github_releases` URL is `https://api.github.com/repos/<o>/<r>/releases` (what `_github_releases` fetches). The `npm` URL is `https://registry.npmjs.org/<pkg>` (what `_npm` expects, like the built-in `claude-code-npm` source).
- A5. `source: <url> [name]` keeps today's free text after the URL. When that text is one token matching `NAME_RE`, it is the name. Otherwise it is the `why`, as today.
- A6. DNS rebinding between the check and urllib's own resolution is out of scope: the spec asks for a check of the resolved addresses, not for pinning the connection to them.
- A7. After merge, the live discord bridge must be restarted before `/source` is registered with Discord. That is shared state, so no task does it: the run's final report names it for the lead.

---

### Task 1: Merge approval line carries the full SHA

**Goal:** `on_merge` sends `[Discord] merge approved for <spec> @ <full sha>`, the SHA it just checked against the branch tip.

**Files:**
- Modify: `board/discord_merge.py` (`on_merge`, its docstring)
- Test: `board/tests/test_discord_merge.py` (the three tests that assert the lead line)

**Acceptance Criteria:**
- [ ] With an unchanged tip, the lead line is exactly `[Discord] merge approved for spec-x @ <40-hex sha of the branch>`.
- [ ] A moved tip still sends nothing and posts a fresh request (`test_changed_branch_edits_and_posts_fresh_request` unchanged and passing).
- [ ] RED before the change: the three edited tests fail on the old line, and the mutation "send the line without ` @ <sha>`" is that RED run.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_merge.py'` → `OK`

**Steps:**

- [ ] **Step 1: Edit the tests (RED).** Apply this test diff (generated against the base; `git apply` it from the worktree root):

````diff
--- a/board/tests/test_discord_merge.py
+++ b/board/tests/test_discord_merge.py
@@ -213,7 +213,10 @@
     def test_equal_sha_sends_the_lead_line(self):
         src = self.posted()
         out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
-        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])
+        sha = git(self.repo, "rev-parse", "feat")
+        self.assertRegex(sha, r"^[0-9a-f]{40}$")
+        # mutation: send the line without " @ <sha>" (or with the 8-char key) -> fails
+        self.assertEqual(self.lines, [("proj", f"[Discord] merge approved for spec-x @ {sha}")])
         self.assertEqual(out, {"result": "merged", "text": "merge approved — sent to the lead"})
         self.assertEqual(len(self.feed()), 1)
 
@@ -255,7 +258,7 @@
         src = f"merge:7:{self.evfile()['sha'][:8]}"
         out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
         self.assertEqual(out["result"], "merged")
-        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])
+        self.assertEqual(self.lines, [("proj", f"[Discord] merge approved for spec-x @ {self.evfile()['sha']}")])
 
     def test_diffs_ignore_user_git_config_color_and_external_diff(self):
         # M1: a real git run with color.ui=always and diff.external set; the stored output must be plain
@@ -300,7 +303,7 @@
             ops.consume(self.add, lambda argv: "", NOW, on_merge=dm.on_merge)
         audit = [json.loads(l) for l in (self.ops / "audit.jsonl").read_text().splitlines()]
         self.assertEqual([a["result"] for a in audit], ["merged", "unknown"])
-        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])
+        self.assertEqual(self.lines, [("proj", f"[Discord] merge approved for spec-x @ {self.evfile()['sha']}")])
         self.assertEqual(ops._default_merge.__name__, "_default_merge")
 
     def test_default_on_merge_is_discord_merge(self):
````

- [ ] **Step 2: Run, expect 3 failures.** `python3 -m unittest discover -s board/tests -p 'test_discord_merge.py'` → `FAILED (failures=3)`: `test_equal_sha_sends_the_lead_line`, `test_merge_request_from_a_spec_worktree_survives_its_removal`, `test_second_tap_is_unknown_through_discord_ops`. (The planner ran this once: exactly these three.)

- [ ] **Step 3: Implement.**

````diff
--- a/board/discord_merge.py
+++ b/board/discord_merge.py
@@ -140,7 +140,8 @@
 
 
 def on_merge(project, src_key, rec, add_line, now):
-    """The Merge button. Same branch tip as posted -> `[Discord] merge approved for <spec>` to the lead; a moved or deleted
+    """The Merge button. Same branch tip as posted -> `[Discord] merge approved for <spec> @ <full sha>` to the lead (the sha
+    just checked: the lead merges that sha, never the branch name); a moved or deleted
     branch -> nothing is sent, and a moved one gets a fresh request. Returns {"result", "text"} for discord_ops, which edits
     both copies; never touches the ops state (its lock is held)."""
     m = SRC_RE.match(str(src_key))
@@ -158,7 +159,7 @@
         return {"result": "stale", "text": "superseded by a newer request"}
     now_sha = rev_parse(ev["repo"], ev["branch"])
     if now_sha == ev["sha"]:
-        add_line(project, f"[Discord] merge approved for {ev['spec']}")
+        add_line(project, f"[Discord] merge approved for {ev['spec']} @ {now_sha}")   # pinned: the lead merges this sha only
         return {"result": "merged", "text": "merge approved — sent to the lead"}
     if now_sha:
         request(project, ev["repo"], task, ev["spec"], ev["branch"], ev["target"], ev["tests"], ev["verdict"], ev.get("findings") or [], now)
````

- [ ] **Step 4: Run, expect `OK`.** Then also `python3 -m unittest discover -s board/tests -p 'test_discord_ops.py'` → `OK` (it mocks `on_merge`; it must not change).

- [ ] **Step 5: Commit** `board/discord_merge.py board/tests/test_discord_merge.py` as `fix(discord): merge approval line pins the checked sha`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/discord_merge.py", "board/tests/test_discord_merge.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_merge.py'", "acceptanceCriteria": ["unchanged tip: lead line is '[Discord] merge approved for spec-x @ <40-hex sha>'", "moved tip still re-posts and sends nothing", "RED run: the three edited tests fail on the old line"], "modelTier": "mechanical"}
```

### Task 2: Lead rule merges only the approved SHA

**Goal:** `claude/orchestrator.md` Queue mode step 2 points the `merge approved` line at a new continuation paragraph, **Pinned merge approval**. That paragraph checks `git rev-parse <branch>` against the SHA, merges the SHA and never the branch name, re-requests on a mismatch or on a line without `@ <sha>`, and records `merged <merge sha>`.

**Files:**
- Modify: `claude/orchestrator.md` (Queue mode step 2 and one new continuation paragraph after the "A failing `tmux-ctl registry` command…" paragraph)
- Test: `tools/tests/test_queue_ask_rule.zsh`

**Acceptance Criteria:**
- [ ] `test_queue_ask_rule.zsh` has 9 new checks on the pinned paragraph (one continuation line). They cover the SHA check, the SHA merge, the re-request, the kept `awaiting merge approval <branch>` outcome, the unpinned old line and `merged <merge sha>`. All 9 fail on the base (the planner ran the RED once: `9 FAILED`) and pass after.
- [ ] Every existing check in `test_queue_ask_rule.zsh` and `test_plugin.zsh` still passes. No new `^  N. ` step line.

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_queue_ask_rule.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: Add the checks (RED).**

````diff
--- a/tools/tests/test_queue_ask_rule.zsh
+++ b/tools/tests/test_queue_ask_rule.zsh
@@ -17,4 +17,16 @@
 check 'ask records the metrics run as --outcome kept' has 'metrics record <spec> --batch <id> --outcome kept'
 check 'ask stores push false' has '`ask` stores `"push": false`'
 check 'morning report lists specs still awaiting merge approval' has 'lists each spec still awaiting merge approval with its branch'
+# the pinned merge approval: a continuation paragraph of step 2 (not a step line), one line
+pinned="$(grep -F '     **Pinned merge approval.**' "$DOC")"
+pin() { print -r -- "$pinned" | grep -qF -- "$1" }
+check 'pinned rule is one continuation line'               test "$(print -r -- "$pinned" | grep -c .)" -eq 1
+check 'step 2 sends the merge to the pinned rule'          has 'with `merge` of the approved SHA only, as Pinned merge approval below says'
+check 'pinned: the approved line carries the full sha'     pin '`[Discord] merge approved for <spec> @ <sha>`, where `<sha>` is the full SHA'
+check 'pinned: the branch tip is checked against the sha'  pin 'run `git rev-parse <branch>`'
+check 'pinned: the sha is merged, not the branch name'     pin '`git merge <sha>`, never the branch name'
+check 'pinned: outcome records the merge sha'              pin 'record `metadata.outcome = "merged <merge sha>"`'
+check 'pinned: a moved tip is re-requested, not merged'    pin 'When it differs, do not merge: run `tmux-ctl discord merge-request` again'
+check 'pinned: the outcome stays awaiting merge approval'  pin 'keep `metadata.outcome = "awaiting merge approval <branch>"`'
+check 'pinned: a line without the sha is not pinned'       pin 'without ` @ <sha>` (a card posted before this rule) is not pinned: re-request the same way and never merge on it'
 tt_done
````

Run `env -u AGENT_BOARD_LEAD zsh tools/tests/test_queue_ask_rule.zsh` → `9 FAILED`. The mutation is deleting the paragraph again, which is this same RED.

- [ ] **Step 2: Edit the rule.** The step 2 sentence changes in place (the existing regex check `merge approved for <spec>`[^.]*merged <sha>` still matches: there is no period between them). The paragraph is one line:

````diff
--- a/claude/orchestrator.md
+++ b/claude/orchestrator.md
@@ -76,7 +76,7 @@
   4. Mark ideas taken up as `- [x] … → <spec path>` and dropped ones as `- [-] …`. Never delete an idea.
 - **Queue mode.** Queued specs run overnight without the user. Check when a Next steps round starts and right after `regroup` step 4 creates a `Plan & run:` task: two or more pending `Plan & run:` tasks, and none has `metadata.queue` yet, start queue mode. A queue whose tasks already carry `metadata.queue`, or whose answers the handoff doc lists (a resumed or handed-off session: recreate the pending `Plan & run:` tasks with that metadata), is not asked again.
   1. **Ask once, up front**, before running anything, with at most two AskUserQuestion calls; every question names the specs by title and stands on its own. Call 1: the default integration for every item (merge to `main` locally / push and open an MR / keep the branch / approve from the phone); which items differ from it, as a multiSelect with a None option, the running plan (the `regroup` path) first as `Running plan: <title>`, then the specs (3 items per question, AskUserQuestion's 4-option limit: more go in further questions, 4 per call, call 1 first); and, only when the default is the MR, consent to push those branches, the running plan's too, and run `gitlab-ci-loop` on them (If installed). Call 2, only when needed: each excepted item's option, 4 per call, plus the push consent if an exception chose the MR and call 1 did not ask it. More than two calls only for a queue too big for two. A push yes is the user's "asked to push" for those branches only, never `main` or `master`; a no turns them into "keep the branch". Write each answer to its task with TaskUpdate: `metadata.queue = {"integration": "merge" | "mr" | "keep" | "ask", "push": true | false, "answeredAt": "<ISO>"}` (`ask` stores `"push": false`), with `answeredAt` read from `date -u +%Y-%m-%dT%H:%M:%SZ`, never written by hand. The running plan's answer goes on the first `Plan & run:` task as `metadata.queue.current = {"plan": "<plan path>", "integration": …, "push": …, "answeredAt": …}`; that plan's `finishing-a-development-branch` uses it. A spec queued after the batch gets one question then, with the queue default recommended. Apart from that one question, after the batch the lead asks the user nothing until the morning report; anything that would need an answer fails that spec instead (step 3). After writing the answers, run `tmux-ctl awake on --queue --lid` (`--queue` binds the hold to the tmux server, so a relay does not end it); without the sudoers rule it falls back to the plain hold, so nothing new is asked, and a battery, lid or heat warning it prints is told to the user in one line, as a notice, not a question. In a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`, run `tmux-ctl metrics batch start --config seq-sdd <spec paths>` and write the batch id it prints into each queued task's `metadata.queue.batch`. A spec queued later joins that batch: do not run `batch start` again, and write that batch id into its task's `metadata.queue.batch`; its `start` line names the batch. In a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`, a lead in Queue mode whose pending `Plan & run:` tasks have no `metadata.queue.batch` runs `tmux-ctl metrics batch start` for those pending specs before the next one starts.
-  2. **Run each spec in order:** at the start of each `Plan & run:` task, run `tmux-ctl awake status` and, when it is off, `tmux-ctl awake on --queue --lid`; then branch off `main` as it stands now, in a worktree under `.claude/worktrees/`; write `metadata.worktree = ".claude/worktrees/<name>"` and `metadata.branch = "<branch>"` on the task with TaskUpdate; `superpowers-extended-cc:writing-plans`, then set the task's `metadata.plan` to the plan path (TaskUpdate), then a fresh Skill call to `superpowers-extended-cc:subagent-driven-development`; then `superpowers-extended-cc:finishing-a-development-branch` with the stored option instead of its menu (its tests before and after, the live-checkout checks and the worktree cleanup still run; an uncommitted user edit crosses the merge as a dry-run-checked patch). With `ask`, run `finishing-a-development-branch` up to its integration step with the option "keep the branch", then `tmux-ctl discord merge-request --project <p> --task <id> --spec <spec> --branch <b> --tests "<verdict line>" --verdict "<final review verdict>" [--finding "<line>"]…`, record `metadata.outcome = "awaiting merge approval <branch>"` (the metrics record for it is `tmux-ctl metrics record <spec> --batch <id> --outcome kept`; the morning report lists each spec still awaiting merge approval with its branch), mark the task completed and start the next spec. On `[Discord] merge approved for <spec>`, run `finishing-a-development-branch` with `merge` for that spec's branch (its pre-merge tests and live-checkout checks still run) and update the outcome to `merged <sha>`; on `[Discord] keep branch for <spec>`, update it to `kept <branch>`; neither line is ever a push. Mark the task completed with `metadata.outcome`: `merged <sha>` / `mr <url>` / `kept <branch>` / `failed — <one line>`. In a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`, run `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>` after the branch and worktree exist, before `writing-plans`, and `tmux-ctl metrics record <spec> --batch <id> --outcome <outcome>` after `finishing-a-development-branch` (for a failed spec, after its outcome is written). Commit `docs/superpowers/metrics/runs.jsonl` and `docs/superpowers/metrics/tasks.jsonl` by themselves on `main`, path-scoped (`git add` both paths; `tasks.jsonl` is new after the first `record`), as `docs(metrics): <spec basename>`; when the live checkout is mid-change, leave it uncommitted until the report. Measurement never fails a spec: when a `tmux-ctl metrics` command fails, note its one-line error and go on. **Spec boundary:** the end of a spec runs in this order: outcome, metrics `record` and its commit, ledger archive, then the handoff. Once the task is completed with its `metadata.outcome` and those steps have run, run `agent-board:handoff` on yourself if another `Plan & run:` task is pending. This holds for every outcome (merged, mr, kept, failed, awaiting merge approval). The doc's Queue state names the next spec, and the new lead starts it with `writing-plans`. A "Not now" case from "Handing off on your own" still wins: the boundary handoff waits while one holds and runs at the first turn after.
+  2. **Run each spec in order:** at the start of each `Plan & run:` task, run `tmux-ctl awake status` and, when it is off, `tmux-ctl awake on --queue --lid`; then branch off `main` as it stands now, in a worktree under `.claude/worktrees/`; write `metadata.worktree = ".claude/worktrees/<name>"` and `metadata.branch = "<branch>"` on the task with TaskUpdate; `superpowers-extended-cc:writing-plans`, then set the task's `metadata.plan` to the plan path (TaskUpdate), then a fresh Skill call to `superpowers-extended-cc:subagent-driven-development`; then `superpowers-extended-cc:finishing-a-development-branch` with the stored option instead of its menu (its tests before and after, the live-checkout checks and the worktree cleanup still run; an uncommitted user edit crosses the merge as a dry-run-checked patch). With `ask`, run `finishing-a-development-branch` up to its integration step with the option "keep the branch", then `tmux-ctl discord merge-request --project <p> --task <id> --spec <spec> --branch <b> --tests "<verdict line>" --verdict "<final review verdict>" [--finding "<line>"]…`, record `metadata.outcome = "awaiting merge approval <branch>"` (the metrics record for it is `tmux-ctl metrics record <spec> --batch <id> --outcome kept`; the morning report lists each spec still awaiting merge approval with its branch), mark the task completed and start the next spec. On `[Discord] merge approved for <spec>`, run `finishing-a-development-branch` with `merge` of the approved SHA only, as Pinned merge approval below says (its pre-merge tests and live-checkout checks still run) and update the outcome to `merged <sha>`; on `[Discord] keep branch for <spec>`, update it to `kept <branch>`; neither line is ever a push. Mark the task completed with `metadata.outcome`: `merged <sha>` / `mr <url>` / `kept <branch>` / `failed — <one line>`. In a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`, run `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>` after the branch and worktree exist, before `writing-plans`, and `tmux-ctl metrics record <spec> --batch <id> --outcome <outcome>` after `finishing-a-development-branch` (for a failed spec, after its outcome is written). Commit `docs/superpowers/metrics/runs.jsonl` and `docs/superpowers/metrics/tasks.jsonl` by themselves on `main`, path-scoped (`git add` both paths; `tasks.jsonl` is new after the first `record`), as `docs(metrics): <spec basename>`; when the live checkout is mid-change, leave it uncommitted until the report. Measurement never fails a spec: when a `tmux-ctl metrics` command fails, note its one-line error and go on. **Spec boundary:** the end of a spec runs in this order: outcome, metrics `record` and its commit, ledger archive, then the handoff. Once the task is completed with its `metadata.outcome` and those steps have run, run `agent-board:handoff` on yourself if another `Plan & run:` task is pending. This holds for every outcome (merged, mr, kept, failed, awaiting merge approval). The doc's Queue state names the next spec, and the new lead starts it with `writing-plans`. A "Not now" case from "Handing off on your own" still wins: the boundary handoff waits while one holds and runs at the first turn after.
 
      Step 2 additions (before, and at the start of, each spec's run):
 
@@ -92,6 +92,8 @@
      **Entry gates.** In a repo that has `docs/superpowers/metrics/configs/upfront-seq.md`: a spec whose header has a line `Entry gate: <id>` is not planned up front. When its turn comes, run `tmux-ctl registry report <batch>` for the batch that just ran (the id in `metadata.queue.batch`), then `tmux-ctl metrics gate <id>`. Exit 0: plan and run the spec. Any other exit: do not plan it; complete its task with `failed — gate <id>: <the command's output line>` and run `tmux-ctl metrics record … --outcome failed`.
 
      **A failing `tmux-ctl registry` command never blocks the queue:** note its one-line error, plan that spec just in time and skip its stale check.
+
+     **Pinned merge approval.** The Merge button sends `[Discord] merge approved for <spec> @ <sha>`, where `<sha>` is the full SHA it just checked. Before merging, run `git rev-parse <branch>` for that spec's branch. When it equals `<sha>`, run `finishing-a-development-branch` with `merge` of `<sha>` itself (`git merge <sha>`, never the branch name, so a commit that lands after the check is not merged) and record `metadata.outcome = "merged <merge sha>"`. When it differs, do not merge: run `tmux-ctl discord merge-request` again with the same flags (fresh evidence) and keep `metadata.outcome = "awaiting merge approval <branch>"`. A `[Discord] merge approved for <spec>` line without ` @ <sha>` (a card posted before this rule) is not pinned: re-request the same way and never merge on it.
   3. **A spec that fails is skipped, not asked about:** where `superpowers-extended-cc:subagent-driven-development` would stop for one of its four stop classes, or the merged result goes red, the final review leaves load-bearing findings, or the user's patch won't apply, keep the branch unmerged, record `failed — <why>`, mark its task completed with that outcome so the next `Plan & run:` task unblocks and the morning report fires, and go on with the next spec. A spec that builds on a failed one is still attempted. User-gate tasks are not run; they wait for the morning. A teammate permission prompt waiting more than 10 minutes is recorded, and if the spec cannot progress it fails with `blocked on a permission prompt in ✦ <name>`.
   4. **Handoffs** during the queue relay without asking. One happens at every spec boundary (step 2), and its doc takes the handoff skill's boundary shape; the doc's Queue state (State of the work in a mid-spec doc) says `Queue mode: on` and lists each queued spec with its `metadata.queue` (see the handoff skill).
   5. **Morning report**, when the last `Plan & run:` task is completed: write `docs/superpowers/reports/YYYY-MM-DD-queue.md` (the run's start date, in UTC) and commit it on `main` (leave it uncommitted if the live checkout is mid-change), then `tmux-ctl artifact <path>`. Per spec: title and spec path, outcome, branch or merge commit or MR URL, every `Ruling:` from its ledger with what it costs if wrong, user-gate checks waiting, permission prompts seen. In a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`, add a **Metrics** section: the output of `tmux-ctl metrics report <batch>`. In a repo that has `docs/superpowers/metrics/configs/upfront-seq.md`, run `tmux-ctl registry report <batch>` before the Metrics section, and name the analysis document path it prints after that section; commit that document and its `<batch>.relations.json` (when it exists) on `main` with the report. Then, when `docs/superpowers/metrics/roadmap` exists, update the Status table (state, evidence, date) of the document that `docs/superpowers/metrics/roadmap` names, for every stage whose spec ran in this queue, and commit it with the report. Run `tmux-ctl awake sleeps <run start>` with the earliest `answeredAt` and add a **Sleep** section listing its lines, or `none`; then run `tmux-ctl awake off`. Then leave queue mode and run the ideas steps.
````

- [ ] **Step 3: Run both suites** (Verify line) → `ALL PASS` twice. `test_plugin.zsh` runs a headless `claude -p` probe when `claude` is on PATH, so give it a few minutes.

- [ ] **Step 4: Commit** `claude/orchestrator.md tools/tests/test_queue_ask_rule.zsh` as `docs(lead): merge approval merges the pinned sha only`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/orchestrator.md", "tools/tests/test_queue_ask_rule.zsh"], "verifyCommand": "env -u AGENT_BOARD_LEAD zsh tools/tests/test_queue_ask_rule.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["9 new pinned-rule checks fail on base and pass after", "existing queue and plugin checks pass", "no new step line"], "modelTier": "mechanical"}
```

### Task 3: One URL check for scout adds, requests and fetches

**Goal:** `scout_sources.check_url_safe(url)` refuses non-https URLs (outside the `_HTTP_OK_HOSTS` seam), unresolvable hosts and any non-global resolved or literal address. It is called by `add_source`, by the `#scout` request path (`_check_request_url` now delegates to it) and by the `discord_channel` link fetch (it replaces the loopback check). `scout_fetch.get()` checks every hop and follows at most 5 redirects by hand. It drops `Authorization` on a hop to another host.

**Files:**
- Modify: `board/scout_sources.py` (`_resolve`, `_addr_class`, `check_url_safe`, `_check_request_url`, `add_source`)
- Modify: `board/scout_fetch.py` (`Refused`, `_Redirect`, `_NoRedirect`, `MAX_REDIRECTS`, `_OPENER`, `_open`, `get`, the `_discord_channel` link check)
- Test: `board/tests/test_scout_sources.py`, `board/tests/test_scout_fetch.py`, `board/tests/test_scout_fetch_local.py`

**Acceptance Criteria:**
- [ ] Each refused class has a test through a fake resolver with the exact reason: 169.254.169.254, 10/8, 172.16/12, 192.168/16, 127/8, ::1, fc00::/7, fe80::/10, multicast v4 and v6, unspecified, 100.64/10 (non-global), IPv4-mapped IPv6. One bad address among global ones refuses (mutation: test only `ips[0]`). Literal IP hosts are refused without the resolver.
- [ ] One real resolution of `localhost` is refused as `loopback address …`. The decimal form `https://2130706433/` is too (a bypass the planner tried: macOS `getaddrinfo` resolves it to 127.0.0.1).
- [ ] A redirect to `https://10.0.0.5/…` and a redirect to a name that resolves to 169.254.169.254 both raise `Refused` before the hop is requested (mutation: check only the first URL, and these fail). Five redirects are followed and six fail with `more than 5 redirects`. `Authorization` reaches only the first host (mutation: same headers every hop, and the test fails).
- [ ] `tmux-ctl scout source add` with a host resolving to 10.0.0.5, or the literal 169.254.169.254, exits 2 with `scout: <reason>`. A `#scout` request to a private host is logged `refused: private address 10.0.0.5` and gets no reply.
- [ ] Every existing scout test passes unchanged except for the seam added to each `Base.setUp`. The planner ran all of them: 126 tests OK under 3.14 and under `/usr/bin/python3` 3.9.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_scout_[sf]*.py' && /usr/bin/python3 -B -m unittest discover -s board/tests -p 'test_scout_[sf]*.py'` → `OK` twice

**Steps:**

- [ ] **Step 1: Tests and seam (RED).** Apply the three test diffs (generated against the base). The seam block goes into each test file's `Base.setUp`. `UrlCheckTest` is a plain `TestCase` (no seam) so it can use the real resolver once.

````diff
--- a/board/tests/test_scout_sources.py
+++ b/board/tests/test_scout_sources.py
@@ -3,6 +3,7 @@
 import io
 import json
 import os
+import socket
 import sys
 import tempfile
 import threading
@@ -108,6 +109,11 @@
         Handler.routes, Handler.messages, Handler.posted, Handler.reacted, Handler.seen = {}, [], [], {}, []
         Handler.fail_posts = 0
         self.now = 1_800_000_000.0
+        import scout_sources as _ss   # the URL check's test seam: the local server is http on 127.0.0.1; other hosts resolve to a global address
+        for _n, _v in (("_HTTP_OK_HOSTS", ("127.0.0.1",)), ("_resolve", lambda host: ["93.184.215.14"])):
+            _p = mock.patch.object(_ss, _n, _v)
+            _p.start()
+            self.addCleanup(_p.stop)
 
     def sources(self, *rows, health=None):
         ss.save({"sources": [dict({"why": "", "added": "x", "builtin": False}, **r) for r in rows], "health": health or {}})
@@ -194,6 +200,14 @@
         self.assertEqual([l.split("\t")[0] for l in out.splitlines()], ["Claude Code 2.1.302", "Claude Code 2.1.301"])
         self.assertEqual(tree(self.scout), before)
         self.assertEqual(self.cli("source", "test", "nope")[0], 2)
+
+    def test_add_refuses_a_private_or_unresolvable_host(self):
+        with mock.patch.object(ss, "_resolve", lambda host: ["10.0.0.5"]):
+            rc, out, err = self.cli("source", "add", "intra", "--kind", "rss", "--url", "https://intra.example.com/f.xml")
+        self.assertEqual((rc, err.strip()), (2, "scout: private address 10.0.0.5"))
+        rc, out, err = self.cli("source", "add", "meta", "--kind", "html_links", "--url", "https://169.254.169.254/latest/")
+        self.assertEqual((rc, err.strip()), (2, "scout: link-local address 169.254.169.254"))
+        self.assertNotIn("intra", [s["name"] for s in ss.load()["sources"]])
 
 
 class PollTest(Base):
@@ -420,6 +434,14 @@
         self.assertEqual(self.seen_state()["requests"]["9001"]["message_id"], "200")
         self.assertEqual(self.seen_state()["state"]["scout"], {"after": "200"})
 
+    def test_request_to_a_private_host_is_refused_and_logged(self):
+        url = "https://intra.example.com/feed"
+        Handler.messages = [dmsg(200, f"source: {url} internal")]
+        with mock.patch.object(ss, "_resolve", lambda host: ["10.0.0.5"]):
+            ss.poll(self.now)
+        self.assertEqual(Handler.posted, [])
+        self.assertIn(f"poll scout: request {url} refused: private address 10.0.0.5", self.log())
+
     def test_kind_guess(self):
         self.serve("/a", "<html>x</html>", "application/atom+xml")
         self.serve("/b", "<?xml version='1.0'?><x/>", "text/html")
@@ -432,7 +454,71 @@
         self.assertEqual(ss.request_name("https://www.Example.com/Some Path/x", {"scout"}), "example-some-path")
         self.assertEqual(ss.request_name("https://blog.example.com/a", {"blog-a"}), "blog-a-2")
         self.assertEqual(ss.request_name("https://blog.example.com/", set()), "blog")
+
+
+class UrlCheckTest(unittest.TestCase):
+    """check_url_safe: each refused address class through a fake resolver, literal IP hosts, one real resolution."""
+
+    def check(self, url, addrs=()):
+        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()), mock.patch.object(ss, "_resolve", lambda host: list(addrs)):
+            ss.check_url_safe(url)
+
+    def refused(self, url, addrs=()):
+        with self.assertRaises(ss.Refusal) as cm:
+            self.check(url, addrs)
+        return str(cm.exception)
+
+    def test_each_refused_class_through_the_resolver(self):
+        cases = [("169.254.169.254", "link-local"), ("10.0.0.5", "private"), ("172.16.3.4", "private"),
+                 ("192.168.1.1", "private"), ("127.0.0.1", "loopback"), ("127.8.9.10", "loopback"), ("::1", "loopback"),
+                 ("fc00::1", "private"), ("fd12::1", "private"), ("fe80::1", "link-local"), ("224.0.0.1", "multicast"),
+                 ("ff02::1", "multicast"), ("0.0.0.0", "unspecified"), ("::", "unspecified"), ("100.64.0.1", "non-global"),
+                 ("::ffff:10.0.0.5", "private"), ("::ffff:169.254.169.254", "link-local")]
+        for ip, cls in cases:
+            self.assertEqual(self.refused("https://feeds.example.com/x", [ip]), f"{cls} address {ip}", ip)
+        self.assertRaises(ss.Refusal, self.check, "https://feeds.example.com/x", ["240.0.0.1"])   # reserved
 
+    def test_one_bad_address_among_global_ones_refuses(self):
+        # mutation: test only the first resolved address -> passes
+        self.assertEqual(self.refused("https://a.example.com/", ["93.184.215.14", "10.1.2.3"]), "private address 10.1.2.3")
 
+    def test_literal_ip_hosts(self):
+        for url, why in (("https://169.254.169.254/latest/meta-data", "link-local address 169.254.169.254"),
+                         ("https://[::1]:8443/x", "loopback address ::1"),
+                         ("https://[::ffff:127.0.0.1]/", "loopback address ::ffff:127.0.0.1"),
+                         ("https://10.0.0.5/feed", "private address 10.0.0.5")):
+            self.assertEqual(self.refused(url, ["93.184.215.14"]), why, url)   # the resolver is not asked for a literal
+
+    def test_global_addresses_pass(self):
+        self.check("https://a.example.com/feed", ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
+        self.check("https://8.8.8.8/x")
+        self.check("https://a.example.com/x", ["::ffff:8.8.8.8"])
+
+    def test_scheme_and_resolution_failures(self):
+        self.assertEqual(self.refused("http://a.example.com/", ["93.184.215.14"]), "url must start with https://")
+        self.assertEqual(self.refused("ftp://a.example.com/", ["93.184.215.14"]), "url must start with https://")
+        self.assertEqual(self.refused("https://empty.example.com/", []), "host does not resolve: empty.example.com")
+
+        def boom(host):
+            raise socket.gaierror(8, "nodename nor servname provided")
+        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()), mock.patch.object(ss, "_resolve", boom):
+            with self.assertRaises(ss.Refusal) as cm:
+                ss.check_url_safe("https://nothere.invalid/")
+        self.assertEqual(str(cm.exception), "host does not resolve: nothere.invalid")
+
+    def test_real_resolution_of_localhost_is_refused(self):
+        # the real resolver (no fake): localhost and the decimal form of 127.0.0.1 both resolve to loopback
+        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()):
+            for url in ("https://localhost/x", "https://2130706433/x"):
+                with self.assertRaises(ss.Refusal) as cm:
+                    ss.check_url_safe(url)
+                self.assertTrue(str(cm.exception).startswith("loopback address "), (url, str(cm.exception)))
+
+    def test_http_ok_hosts_seam_skips_scheme_and_address(self):
+        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ("127.0.0.1",)):
+            ss.check_url_safe("http://127.0.0.1:8000/x")
+        self.assertEqual(ss._HTTP_OK_HOSTS, ())   # empty in production
+
+
 if __name__ == "__main__":
     unittest.main()
````

````diff
--- a/board/tests/test_scout_fetch.py
+++ b/board/tests/test_scout_fetch.py
@@ -21,6 +21,7 @@
 class Handler(BaseHTTPRequestHandler):
     extra = {}      # path -> (bytes, content type); overrides the fixture dir
     seen = []       # (path, headers dict) of every request
+    redirects = {}  # path -> Location of a 302
 
     def log_message(self, *a):
         pass
@@ -28,6 +29,12 @@
     def do_GET(self):
         Handler.seen.append((self.path, dict(self.headers)))
         path = self.path.split("?")[0]
+        if path in Handler.redirects:
+            self.send_response(302)
+            self.send_header("Location", Handler.redirects[path])
+            self.send_header("Content-Length", "0")
+            self.end_headers()
+            return
         if path == "/500":
             self.send_response(500)
             self.end_headers()
@@ -71,6 +78,12 @@
         self.addCleanup(p.stop)
         Handler.extra = {}
         Handler.seen = []
+        Handler.redirects = {}
+        import scout_sources as _ss   # the URL check's test seam: the local server is http on 127.0.0.1; other hosts resolve to a global address
+        for _n, _v in (("_HTTP_OK_HOSTS", ("127.0.0.1",)), ("_resolve", lambda host: ["93.184.215.14"])):
+            _p = mock.patch.object(_ss, _n, _v)
+            _p.start()
+            self.addCleanup(_p.stop)
         g = mock.patch.object(sf, "_gh_token", return_value=None)
         g.start()
         self.addCleanup(g.stop)
@@ -127,8 +140,69 @@
             with self.assertRaises(sf.FetchError):
                 sf.get(self.base + "/npm.json")
         self.assertEqual(m.call_args.kwargs.get("timeout"), 20)
+
+
+class RedirectTest(Base):
+    """get() follows redirects by hand: every hop passes scout_sources.check_url_safe before it is requested."""
+
+    def ok_hosts(self, *hosts):
+        import scout_sources
+        p = mock.patch.object(scout_sources, "_HTTP_OK_HOSTS", hosts)
+        p.start()
+        self.addCleanup(p.stop)
+
+    def test_redirects_followed_by_hand(self):
+        Handler.redirects = {"/r1": "/r2", "/r2": "/npm.json"}
+        st, body, _ = sf.get(self.base + "/r1")
+        self.assertEqual(st, 200)
+        self.assertIn(b"latest", body)
+        self.assertEqual([p for p, _ in Handler.seen], ["/r1", "/r2", "/npm.json"])
+
+    def test_first_url_refused_before_any_request(self):
+        with self.assertRaises(sf.Refused) as cm:
+            sf.get("https://10.0.0.5/feed")
+        self.assertEqual(str(cm.exception), "refused: private address 10.0.0.5")
+        self.assertEqual(Handler.seen, [])
+
+    def test_redirect_to_a_private_address_is_refused(self):
+        # mutation: check only the first URL in get() -> the hop is requested and the test sees a network error instead
+        Handler.redirects = {"/r1": "https://10.0.0.5/meta"}
+        with self.assertRaises(sf.Refused) as cm:
+            sf.get(self.base + "/r1")
+        self.assertEqual(str(cm.exception), "refused: private address 10.0.0.5")
+        self.assertEqual([p for p, _ in Handler.seen], ["/r1"])
+
+    def test_redirect_to_a_name_that_resolves_to_metadata_is_refused(self):
+        import scout_sources
+        fake = lambda host: ["169.254.169.254"] if host == "metadata.example.com" else ["93.184.215.14"]
+        with mock.patch.object(scout_sources, "_resolve", fake):
+            Handler.redirects = {"/r1": "https://metadata.example.com/latest/meta-data"}
+            with self.assertRaises(sf.Refused) as cm:
+                sf.get(self.base + "/r1")
+        self.assertEqual(str(cm.exception), "refused: link-local address 169.254.169.254")
+
+    def test_at_most_five_redirects(self):
+        Handler.redirects = {f"/l{i}": f"/l{i + 1}" for i in range(6)}
+        Handler.extra["/l6"] = (b"end", "text/plain")
+        self.assertEqual(sf.get(self.base + "/l1")[1], b"end")   # five hops: followed
+        self.assertEqual(len(Handler.seen), 6)
+        Handler.seen = []
+        with self.assertRaises(sf.FetchError) as cm:   # six hops: refused after the fifth
+            sf.get(self.base + "/l0")
+        self.assertEqual(str(cm.exception), "more than 5 redirects")
+        self.assertEqual(len(Handler.seen), 6)
 
+    def test_authorization_goes_only_to_the_first_host(self):
+        # mutation: send the same headers on every hop -> the second request carries the token
+        self.ok_hosts("127.0.0.1", "localhost")
+        port = self.srv.server_address[1]
+        Handler.redirects = {"/r1": f"http://localhost:{port}/npm.json"}
+        sf.get(self.base + "/r1", headers={"Authorization": "Bearer T"})
+        self.assertEqual(Handler.seen[0][1].get("Authorization"), "Bearer T")
+        self.assertEqual(Handler.seen[1][0], "/npm.json")
+        self.assertNotIn("Authorization", Handler.seen[1][1])
 
+
 class DispatchTest(Base):
     def test_unknown_kind(self):
         for k in ("nope", None, ""):
````

````diff
--- a/board/tests/test_scout_fetch_local.py
+++ b/board/tests/test_scout_fetch_local.py
@@ -100,6 +100,11 @@
         p.start()
         self.addCleanup(p.stop)
         Handler.routes, Handler.messages, Handler.seen, Handler.raw_messages = {}, [], [], None
+        import scout_sources as _ss   # the URL check's test seam: the local server is http on 127.0.0.1; other hosts resolve to a global address
+        for _n, _v in (("_HTTP_OK_HOSTS", ("127.0.0.1",)), ("_resolve", lambda host: ["93.184.215.14"])):
+            _p = mock.patch.object(_ss, _n, _v)
+            _p.start()
+            self.addCleanup(_p.stop)
 
 
 class PluginTest(Base):
````

Run the Verify command's first half. Expected RED: `AttributeError` on `ss.check_url_safe` / `ss._resolve` / `sf.Refused` (the patch targets do not exist yet), not an import error from a typo.

- [ ] **Step 2: Implement.**

````diff
--- a/board/scout_sources.py
+++ b/board/scout_sources.py
@@ -9,9 +9,11 @@
 import contextlib
 import fcntl
 import hashlib
+import ipaddress
 import json
 import os
 import re
+import socket
 import sys
 import time
 import urllib.parse
@@ -136,12 +138,52 @@
         raise Refusal("url must start with https://")
 
 
-def _check_request_url(url):
-    """The source-add URL rule for a requested URL (https only), except hosts in _HTTP_OK_HOSTS."""
+def _resolve(host):
+    """Every address host resolves to, as strings (test seam: tests replace it with a fake resolver)."""
+    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
+
+
+def _addr_class(ip):
+    """None for a global address, else the class that refuses it. An IPv4-mapped IPv6 address is judged as its IPv4."""
+    a = ipaddress.ip_address(ip.split("%", 1)[0])
+    if getattr(a, "ipv4_mapped", None):
+        a = a.ipv4_mapped
+    for cls, flag in (("unspecified", a.is_unspecified), ("loopback", a.is_loopback), ("link-local", a.is_link_local),
+                      ("multicast", a.is_multicast), ("private", a.is_private), ("reserved", a.is_reserved)):
+        if flag:
+            return cls
+    return None if a.is_global else "non-global"
+
+
+def check_url_safe(url):
+    """The one URL rule for every source add, #scout request and fetch hop: https (http only for _HTTP_OK_HOSTS, a test
+    seam that is empty in production and also skips the address test), and every address the host resolves to (or the
+    literal IP) is global. Refusal("<one line>") otherwise."""
     u = urllib.parse.urlsplit(url or "")
-    if u.scheme == "http" and u.hostname in _HTTP_OK_HOSTS:
+    host = u.hostname
+    if host and host in _HTTP_OK_HOSTS and u.scheme in ("http", "https"):
         return
-    _check_url("rss", url)
+    if u.scheme != "https" or not host:
+        raise Refusal("url must start with https://")
+    try:
+        ipaddress.ip_address(host.split("%", 1)[0])
+        ips = [host]
+    except ValueError:
+        try:
+            ips = _resolve(host)
+        except (OSError, UnicodeError):
+            raise Refusal(f"host does not resolve: {host}") from None
+    if not ips:
+        raise Refusal(f"host does not resolve: {host}")
+    for ip in ips:
+        cls = _addr_class(ip)
+        if cls:
+            raise Refusal(f"{cls} address {ip}")
+
+
+def _check_request_url(url):
+    """Kept for callers of the old name: the same rule as check_url_safe."""
+    check_url_safe(url)
 
 
 def add_source(name, kind, url, why="", prefix=None, now=None):
@@ -150,6 +192,8 @@
     if not NAME_RE.match(name or ""):
         raise Refusal(f"bad name {name!r} (must match {NAME_RE.pattern})")
     _check_url(kind, url)
+    if kind not in ("discord_channel", "plugin"):
+        check_url_safe(url)
     with _lock():
         st = load()
         if any(s["name"] == name for s in st["sources"]):
````

````diff
--- a/board/scout_fetch.py
+++ b/board/scout_fetch.py
@@ -36,6 +36,27 @@
     pass
 
 
+class Refused(FetchError):
+    """A URL (or a redirect hop) that scout_sources.check_url_safe refuses."""
+
+
+class _Redirect(Exception):
+    def __init__(self, url):
+        super().__init__(url)
+        self.url = url
+
+
+class _NoRedirect(urllib.request.HTTPRedirectHandler):
+    """Redirects are never followed by urllib: get() follows them by hand so each hop is checked first."""
+
+    def redirect_request(self, req, fp, code, msg, headers, newurl):
+        return None
+
+
+MAX_REDIRECTS = 5
+REDIRECT_CODES = (301, 302, 303, 307, 308)
+
+
 FALLBACK_CA = "/etc/ssl/cert.pem"
 
 
@@ -51,7 +72,7 @@
 
 
 # no HTTPCookieProcessor: no cookies are stored or replayed
-_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))
+_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()), _NoRedirect)
 
 
 def _open(req):
@@ -60,19 +81,36 @@
         with _OPENER.open(req, timeout=TIMEOUT) as r:
             return r.status, r.read(MAX_BYTES), r.headers.get("Content-Type", "")
     except urllib.error.HTTPError as e:
+        loc = e.headers.get("Location") if e.code in REDIRECT_CODES else None
         e.close()
+        if loc:
+            raise _Redirect(urllib.parse.urljoin(req.full_url, loc)) from None
         raise FetchError(f"HTTP {e.code} for {req.full_url}") from None
     except Exception as e:  # URLError, timeout, ssl, bad url, connection reset
         raise FetchError(f"{type(e).__name__}: {e}") from None
 
 
 def get(url, accept=None, headers=None):
-    """GET url -> (status, body bytes (at most MAX_BYTES), content type). FetchError on a network error or status >= 400."""
+    """GET url -> (status, body bytes (at most MAX_BYTES), content type). Each hop (the URL, then each redirect, at most
+    MAX_REDIRECTS) passes scout_sources.check_url_safe before it is requested: Refused otherwise. An Authorization header
+    goes only to the first URL's host. FetchError on a network error or status >= 400."""
+    import scout_sources  # lazy: scout_sources imports this module
     h = {"User-Agent": UA}
     if accept:
         h["Accept"] = accept
     h.update(headers or {})
-    return _open(urllib.request.Request(url, headers=h))
+    origin = urllib.parse.urlsplit(url).hostname
+    for _ in range(MAX_REDIRECTS + 1):
+        try:
+            scout_sources.check_url_safe(url)
+        except scout_sources.Refusal as e:
+            raise Refused(f"refused: {e}") from None
+        hop = h if urllib.parse.urlsplit(url).hostname == origin else {k: v for k, v in h.items() if k.lower() != "authorization"}
+        try:
+            return _open(urllib.request.Request(url, headers=hop))
+        except _Redirect as r:
+            url = r.url
+    raise FetchError(f"more than {MAX_REDIRECTS} redirects")
 
 
 def _cut(text, limit=EXCERPT_MAX):
@@ -557,10 +595,7 @@
             if url in seen_urls:
                 continue
             try:
-                scout_sources._check_request_url(url)
-                if urllib.parse.urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1") \
-                        and urllib.parse.urlsplit(url).hostname not in scout_sources._HTTP_OK_HOSTS:
-                    raise scout_sources.Refusal("loopback")
+                scout_sources.check_url_safe(url)
             except scout_sources.Refusal:
                 continue
             seen_urls.add(url)
````

- [ ] **Step 3: Run the Verify command** → `OK` twice. Then run the two mutations named in the acceptance criteria once each and report their failures: in `get()`, check only on the first loop pass (`_ or scout_sources.check_url_safe(url)`), and send `h` on every hop. The planner's run: the two redirect-refusal tests ERROR and the Authorization test FAILs.

- [ ] **Step 4: Commit** the five files as `fix(scout): one URL safety check for every add, request and fetch hop`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/scout_sources.py", "board/scout_fetch.py", "board/tests/test_scout_sources.py", "board/tests/test_scout_fetch.py", "board/tests/test_scout_fetch_local.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_scout_[sf]*.py' && /usr/bin/python3 -B -m unittest discover -s board/tests -p 'test_scout_[sf]*.py'", "acceptanceCriteria": ["each refused address class with its exact reason, fake resolver", "one real localhost resolution refused; decimal 127.0.0.1 refused", "redirect hop to private or metadata address refused before request; 5 redirects followed, 6 fail; Authorization only to the first host", "CLI add and #scout request refuse private hosts", "all scout suites pass under 3.14 and 3.9"], "modelTier": "standard"}
```

### Task 4: Kind detection and the one add path

**Goal:** `scout_sources.detect(url, taken=None) -> {kind, url, name, prefix?}` implements the spec's table, first match wins. It fetches at most one page through `get(…, timeout=10)` and falls back to `html_links` on a failed fetch. A refused URL or feed link raises `Refusal`. `add_url(url, name=None, kind=None, why="")` is the one add path. `tmux-ctl scout source add <name> [--kind <k>] --url <u>` makes `--kind` optional and edits the help line in place.

**Files:**
- Modify: `board/scout_sources.py` (`GH_RE`, `NPM_RE`, `FEED_TYPES`, `DETECT_TIMEOUT`, `_AltFeed`, `_taken`, `detect`, `add_url`, the CLI `add`)
- Modify: `board/scout_fetch.py` (`timeout` parameter on `_open` and `get`)
- Modify: `bin/tmux-ctl` (line 79, the scout help line, in place)
- Test: `board/tests/test_scout_sources.py` (`DetectTest`)

**Acceptance Criteria:**
- [ ] One test per table row, from inline HTML on the local server: GitHub repo, `/releases` and `.git` (no fetch); npm scoped and plain package; raw `CHANGELOG.md` (no fetch); a page with an rss or atom `<link rel="alternate">` gives the absolute feed URL; a URL that is itself a feed (by content type and by root element); anything else gives `html_links` with prefix = its path; a 404 falls back to `html_links`.
- [ ] A feed link to a private address raises `Refusal("private address 10.0.0.5")` (mutation: drop the feed-URL check, and the row is added). A `Refused` hop from `get` becomes `Refusal` with the bare reason.
- [ ] `detect` calls `get` exactly once, with `timeout=10`.
- [ ] Name defaults and duplicates: `github-anthropics`, then `-2` and `-3`, and names taken in `sources.json` count.
- [ ] The CLI without `--kind` detects the kind: `added feed1 (rss)`, `added cc (github_releases)` with the api URL stored. A private URL exits 2.
- [ ] `zsh bin/tmux-ctl help` prints `source add <name> [--kind <k>] --url <u>`, and the help line count is unchanged (`zsh bin/tmux-ctl help | wc -l` equal before and after).
- [ ] Real-state check, read-only. From the worktree, run `python3 -c 'import sys; sys.path.insert(0, "board"); import scout_sources as s; [print(x["name"], s.detect(x["url"], taken=set())["kind"]) for x in s.load(create=False)["sources"] if str(x["url"]).startswith("https://")]'` with `TC_SCOUT_DIR` unset (it reads the live `sources.json` and writes nothing: `load(create=False)`, no add). It prints one kind per live https source. Paste the output in the report. A network failure there is reported, not fixed.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_scout_[sf]*.py' && zsh bin/tmux-ctl help | grep -qF 'source add <name> [--kind <k>] --url <u>'` → `OK`, exit 0

**Steps:**

- [ ] **Step 1: Tests (RED).** Apply (generated against the file as Task 3 leaves it):

````diff
--- a/board/tests/test_scout_sources.py
+++ b/board/tests/test_scout_sources.py
@@ -454,8 +454,101 @@
         self.assertEqual(ss.request_name("https://www.Example.com/Some Path/x", {"scout"}), "example-some-path")
         self.assertEqual(ss.request_name("https://blog.example.com/a", {"blog-a"}), "blog-a-2")
         self.assertEqual(ss.request_name("https://blog.example.com/", set()), "blog")
+
+
+class DetectTest(Base):
+    """detect(): one row of the spec's table per test, from inline HTML served by the local server."""
+
+    def test_github_repo_and_releases_need_no_fetch(self):
+        for url in ("https://github.com/anthropics/claude-code", "https://github.com/anthropics/claude-code/releases",
+                    "https://github.com/anthropics/claude-code.git"):
+            d = ss.detect(url, taken=set())
+            self.assertEqual((d["kind"], d["url"]), ("github_releases", "https://api.github.com/repos/anthropics/claude-code/releases"), url)
+        self.assertEqual(Handler.seen, [])
+
+    def test_npm_package_page(self):
+        d = ss.detect("https://www.npmjs.com/package/@anthropic-ai/claude-code", taken=set())
+        self.assertEqual((d["kind"], d["url"]), ("npm", "https://registry.npmjs.org/@anthropic-ai/claude-code"))
+        d = ss.detect("https://www.npmjs.com/package/left-pad", taken=set())
+        self.assertEqual(d["url"], "https://registry.npmjs.org/left-pad")
+
+    def test_raw_changelog(self):
+        url = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
+        self.assertEqual(ss.detect(url, taken=set())["kind"], "changelog_md")
+        self.assertEqual(ss.detect(url, taken=set())["url"], url)
+        self.assertEqual(Handler.seen, [])
+
+    def test_page_with_a_feed_link_gives_the_absolute_feed_url(self):
+        self.serve("/blog", '<html><head><link rel="stylesheet" href="/s.css">'
+                            '<link rel="alternate" type="application/rss+xml" href="/blog/feed.xml"></head></html>', "text/html")
+        self.serve("/news", '<html><head><link rel="Alternate home" type="application/atom+xml" '
+                            'href="https://feeds.example.com/atom"></head></html>', "text/html")
+        self.assertEqual(ss.detect(self.base + "/blog", taken=set())[ "url"], self.base + "/blog/feed.xml")
+        self.assertEqual(ss.detect(self.base + "/blog", taken=set())["kind"], "rss")
+        self.assertEqual(ss.detect(self.base + "/news", taken=set())["url"], "https://feeds.example.com/atom")
 
+    def test_feed_link_to_a_private_address_is_refused(self):
+        # mutation: drop the check of the feed URL -> an rss row pointing at 10.0.0.5
+        self.serve("/blog", '<html><head><link rel="alternate" type="application/rss+xml" href="https://10.0.0.5/f"></head></html>', "text/html")
+        with self.assertRaises(ss.Refusal) as cm:
+            ss.detect(self.base + "/blog", taken=set())
+        self.assertEqual(str(cm.exception), "private address 10.0.0.5")
 
+    def test_url_that_is_itself_a_feed(self):
+        self.serve("/a", "<html>x</html>", "application/atom+xml")
+        self.serve("/b", "<?xml version='1.0'?><rss/>", "text/html")
+        self.serve("/c", "<feed></feed>", "text/plain")
+        for p in ("/a", "/b", "/c"):
+            self.assertEqual((ss.detect(self.base + p, taken=set())["kind"], ss.detect(self.base + p, taken=set())["url"]),
+                             ("rss", self.base + p), p)
+
+    def test_anything_else_is_html_links_with_its_path_as_prefix(self):
+        self.serve("/docs/changes", "<html><body><a href='/docs/changes/1'>one</a></body></html>", "text/html")
+        d = ss.detect(self.base + "/docs/changes", taken=set())
+        self.assertEqual((d["kind"], d["url"], d["prefix"]), ("html_links", self.base + "/docs/changes", "/docs/changes/"))
+
+    def test_failed_fetch_falls_back_to_html_links(self):
+        d = ss.detect(self.base + "/missing/page", taken=set())   # 404
+        self.assertEqual((d["kind"], d["prefix"]), ("html_links", "/missing/page/"))
+
+    def test_refused_url_and_redirect_hop(self):
+        with self.assertRaises(ss.Refusal):
+            ss.detect("https://10.0.0.5/x", taken=set())
+        Handler.routes["/go"] = (200, b"", "text/html")
+        import scout_fetch
+        with mock.patch.object(scout_fetch, "get", side_effect=scout_fetch.Refused("refused: link-local address 169.254.169.254")):
+            with self.assertRaises(ss.Refusal) as cm:
+                ss.detect(self.base + "/go", taken=set())
+        self.assertEqual(str(cm.exception), "link-local address 169.254.169.254")
+
+    def test_one_fetch_with_a_10_second_timeout(self):
+        import scout_fetch
+        with mock.patch.object(scout_fetch, "get", return_value=(200, b"<html></html>", "text/html")) as g:
+            ss.detect(self.base + "/x", taken=set())
+        self.assertEqual(g.call_count, 1)
+        self.assertEqual(g.call_args.kwargs.get("timeout"), 10)
+
+    def test_name_default_and_duplicates(self):
+        self.assertEqual(ss.detect("https://github.com/Anthropics/claude-code", taken=set())["name"], "github-anthropics")
+        self.assertEqual(ss.detect("https://github.com/anthropics/x", taken={"github-anthropics"})["name"], "github-anthropics-2")
+        self.assertEqual(ss.detect("https://github.com/anthropics/x", taken={"github-anthropics", "github-anthropics-2"})["name"],
+                         "github-anthropics-3")
+        self.sources({"name": "github-anthropics", "kind": "rss", "url": "https://a.example/f"})
+        self.assertEqual(ss.detect("https://github.com/anthropics/y")["name"], "github-anthropics-2")   # taken read from sources.json
+
+    def test_cli_add_without_kind_detects_it(self):
+        import scout_fetch   # add_source takes https only, so the fetch is faked rather than served over http
+        with mock.patch.object(scout_fetch, "get", return_value=(200, b"<?xml version='1.0'?><rss/>", "application/rss+xml")):
+            rc, out, _ = self.cli("source", "add", "feed1", "--url", "https://feeds.example.com/f.xml")
+        self.assertEqual((rc, out.strip()), (0, "added feed1 (rss)"))
+        rc, out, _ = self.cli("source", "add", "cc", "--url", "https://github.com/anthropics/claude-code")
+        self.assertEqual((rc, out.strip()), (0, "added cc (github_releases)"))
+        row = [s for s in ss.load()["sources"] if s["name"] == "cc"][0]
+        self.assertEqual(row["url"], "https://api.github.com/repos/anthropics/claude-code/releases")
+        rc, _, err = self.cli("source", "add", "bad", "--url", "https://10.0.0.5/")
+        self.assertEqual((rc, err.strip()), (2, "scout: private address 10.0.0.5"))
+
+
 class UrlCheckTest(unittest.TestCase):
     """check_url_safe: each refused address class through a fake resolver, literal IP hosts, one real resolution."""
 
````

Run `python3 -m unittest discover -s board/tests -p 'test_scout_sources.py' -k DetectTest`. Expected: every test ERRORs with `AttributeError: module 'scout_sources' has no attribute 'detect'` (the CLI test fails with rc 2, `--kind` required).

- [ ] **Step 2: Implement.**

````diff
--- a/board/scout_sources.py
+++ b/board/scout_sources.py
@@ -17,6 +17,7 @@
 import sys
 import time
 import urllib.parse
+from html.parser import HTMLParser
 from pathlib import Path
 
 import discord_feed
@@ -184,6 +185,77 @@
 def _check_request_url(url):
     """Kept for callers of the old name: the same rule as check_url_safe."""
     check_url_safe(url)
+
+
+GH_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/releases)?/?$")
+NPM_RE = re.compile(r"^https://www\.npmjs\.com/package/((?:@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+)/?$")
+FEED_TYPES = ("application/rss+xml", "application/atom+xml")
+DETECT_TIMEOUT = 10
+
+
+class _AltFeed(HTMLParser):
+    """The first <link rel="alternate" type="application/rss+xml|application/atom+xml" href=…>."""
+
+    def __init__(self):
+        super().__init__(convert_charrefs=True)
+        self.href = None
+
+    def handle_starttag(self, tag, attrs):
+        a = {k: (v or "") for k, v in attrs}
+        if tag == "link" and self.href is None and "alternate" in a.get("rel", "").lower().split() \
+                and a.get("type", "").lower().strip() in FEED_TYPES and a.get("href", "").strip():
+            self.href = a["href"].strip()
+
+
+def _taken():
+    seen = _read(scout_dir() / "seen.json", {})
+    reqs = seen.get("requests") if isinstance(seen.get("requests"), dict) else {}
+    return {s["name"] for s in load(create=False)["sources"]} | {r.get("name") for r in reqs.values() if isinstance(r, dict)}
+
+
+def detect(url, taken=None):
+    """url -> {kind, url, name, prefix?}; first match wins (spec 2026-11-23-hardening §b2). At most one page is fetched
+    (through check_url_safe, DETECT_TIMEOUT s); a failed fetch falls back to html_links. Refusal for a refused URL."""
+    check_url_safe(url)
+    name = request_name(url, _taken() if taken is None else set(taken))
+    m = GH_RE.match(url)
+    if m:
+        return {"kind": "github_releases", "url": f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/releases", "name": name}
+    m = NPM_RE.match(url)
+    if m:
+        return {"kind": "npm", "url": f"https://registry.npmjs.org/{m.group(1)}", "name": name}
+    if urllib.parse.urlsplit(url).path.endswith("CHANGELOG.md"):
+        return {"kind": "changelog_md", "url": url, "name": name}
+    try:
+        _, body, ctype = scout_fetch.get(url, timeout=DETECT_TIMEOUT)
+    except scout_fetch.Refused as e:
+        raise Refusal(str(e).split(": ", 1)[-1]) from None
+    except scout_fetch.FetchError:
+        body, ctype = b"", ""
+    p = _AltFeed()
+    try:
+        p.feed(body.decode("utf-8", "replace"))
+        p.close()
+    except Exception:  # noqa: BLE001  (odd markup: no feed link)
+        p.href = None
+    if p.href:
+        feed = urllib.parse.urljoin(url, p.href)
+        check_url_safe(feed)
+        return {"kind": "rss", "url": feed, "name": name}
+    head = body[:200].lstrip().lower()
+    if "xml" in (ctype or "").lower() or head.startswith((b"<?xml", b"<rss", b"<feed")):
+        return {"kind": "rss", "url": url, "name": name}
+    return {"kind": "html_links", "url": url, "name": name, "prefix": urllib.parse.urlsplit(url).path.rstrip("/") + "/"}
+
+
+def add_url(url, name=None, kind=None, why="", now=None):
+    """The one add path (the CLI, a #scout request, /source): detect() picks kind, url and name unless kind is given."""
+    if kind is None:
+        d = detect(url)
+        kind, url, name = d["kind"], d["url"], name or d["name"]
+    elif not name:
+        name = request_name(url, _taken())
+    return add_source(name, kind, url, why)
 
 
 def add_source(name, kind, url, why="", prefix=None, now=None):
@@ -432,7 +504,7 @@
     sp = sub.add_parser("source").add_subparsers(dest="sub", required=True)
     a = sp.add_parser("add")
     a.add_argument("name")
-    a.add_argument("--kind", required=True)
+    a.add_argument("--kind")
     a.add_argument("--url", required=True)
     a.add_argument("--why", default="")
     sp.add_parser("list")
@@ -450,7 +522,7 @@
             n, m, f = poll()
             print(f"poll: {n} new from {m} sources, {f} failed")
         elif args.sub == "add":
-            row = add_source(args.name, args.kind, args.url, args.why)
+            row = add_url(args.url, args.name, args.kind, args.why)
             print(f"added {row['name']} ({row['kind']})")
         elif args.sub == "list":
             st = load()
````

````diff
--- a/board/scout_fetch.py
+++ b/board/scout_fetch.py
@@ -75,10 +75,10 @@
 _OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()), _NoRedirect)
 
 
-def _open(req):
+def _open(req, timeout=TIMEOUT):
     """Open a Request -> (status, body (at most MAX_BYTES), content type). FetchError text never carries request headers."""
     try:
-        with _OPENER.open(req, timeout=TIMEOUT) as r:
+        with _OPENER.open(req, timeout=timeout) as r:
             return r.status, r.read(MAX_BYTES), r.headers.get("Content-Type", "")
     except urllib.error.HTTPError as e:
         loc = e.headers.get("Location") if e.code in REDIRECT_CODES else None
@@ -90,7 +90,7 @@
         raise FetchError(f"{type(e).__name__}: {e}") from None
 
 
-def get(url, accept=None, headers=None):
+def get(url, accept=None, headers=None, timeout=TIMEOUT):
     """GET url -> (status, body bytes (at most MAX_BYTES), content type). Each hop (the URL, then each redirect, at most
     MAX_REDIRECTS) passes scout_sources.check_url_safe before it is requested: Refused otherwise. An Authorization header
     goes only to the first URL's host. FetchError on a network error or status >= 400."""
@@ -107,7 +107,7 @@
             raise Refused(f"refused: {e}") from None
         hop = h if urllib.parse.urlsplit(url).hostname == origin else {k: v for k, v in h.items() if k.lower() != "authorization"}
         try:
-            return _open(urllib.request.Request(url, headers=hop))
+            return _open(urllib.request.Request(url, headers=hop), timeout)
         except _Redirect as r:
             url = r.url
     raise FetchError(f"more than {MAX_REDIRECTS} redirects")
````

In `bin/tmux-ctl` line 79, change `source add <name> --kind <k> --url <u> [--why <t>]` to `source add <name> [--kind <k>] --url <u> [--why <t>]`, the same line with no line added. Measure `zsh bin/tmux-ctl help | wc -l` before and after: the two numbers are equal.

- [ ] **Step 3: Run the Verify command** → `OK`, exit 0. Then run the feed-link mutation once (delete the `check_url_safe(feed)` line) and report `test_feed_link_to_a_private_address_is_refused` failing. Then run the real-state check from the acceptance criteria.

- [ ] **Step 4: Commit** the four files as `feat(scout): detect a source's kind; one add path; --kind optional`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/scout_sources.py", "board/scout_fetch.py", "bin/tmux-ctl", "board/tests/test_scout_sources.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_scout_[sf]*.py' && zsh bin/tmux-ctl help | grep -qF 'source add <name> [--kind <k>] --url <u>'", "acceptanceCriteria": ["one test per detection table row", "private feed link refused; Refused hop becomes Refusal", "one fetch, timeout 10", "name defaults and -2/-3, sources.json names count", "CLI add without --kind detects; private URL rc 2", "help line edited in place, line count unchanged", "read-only detect over the live sources.json, output in the report"], "modelTier": "standard"}
```

### Task 5: Instant add from #scout and /source

**Goal:** `source: <url> [name]` in `#scout` and a new `/source <url> [name]` slash command on the agent-board bot reply at once with `<name> · <kind> · <url>` and `react ✅ to add`. A ✅ from an allowFrom user adds the source at once through `add_url` and fetches it once. The reply is then edited to `added: <name> (<kind>)` plus the first 3 item titles, or to `added, first fetch failed: <reason>`. A refused URL gets `refused: <reason>` and no ✅ prompt.

**Files:**
- Modify: `board/scout_sources.py`, `board/scout_fetch.py` (`edit_message`, the `source:` request regex), `board/discord_controls.py`, `tools/discord-bridge/lib/commands.js`, `tools/discord-bridge/bridge.js`
- Test: `board/tests/test_scout_sources.py`, `board/tests/test_scout_fetch_local.py`, `board/tests/test_discord_controls.py`, `tools/discord-bridge/test/commands.test.js`
- Create: `tools/discord-bridge/test/scout-source.test.js`
- Read (must stay green, not edited): `tools/discord-bridge/test/liveness-bridge.test.js` (the `sendOwn` guard), `tools/discord-bridge/test/fake-client.js` (main's fakes: `fakeMessage` takes `createdTimestamp`, `authorBot`, `interactionMetadata` and keeps `reactions.cache` entries with `users.remove`; `fakeModal` has `deferReply`/`editReply`)

**Main as of `ec8b209` (refresh; the code this task changes moved since the plan was written):**
- `bridge.js` `onReaction` now sends `❓` from an allowlisted user to `onAsk` before the `REACT_EMOJI` test, in project mode. The scout ✅ branch goes after that line and leaves the `❓` path and the home-channel `react` event exactly as they are.
- `bridge.js` `onMessage` calls `track(msg)` first (lead liveness). `track` ignores messages outside the home channel. A bot message in the home channel whose id is not in `st.own_sent` counts as the lead's answer. A `source:` event from `#scout` runs after `track(msg)` and does not change it.
- `bridge.js` posts and replies only through `sendOwn` / `noteOwn` (see Global Constraints and the guard test). The `/source` prompt is the interaction's own reply, so `track` skips it (`interactionMetadata`) and no new `.send(` is needed. Any other bridge post uses an existing outbox op handler (`post` with `key`, then `edit` by that key), which already calls `sendOwn`. The board's `scout_fetch` REST post and `edit_message` target `#scout` only. A REST post into the agent-board home channel is not in `own_sent`, so liveness would read it as the lead's answer. That makes it out of bounds.
- `bridge.js` `handlers` now also holds `liveness_reply`, `liveness`, `create_channel` and `channel_overwrite`. A new outbox op kind needs a handler there and an entry in `board/discord_feed._check`'s `shapes` (main added `create_channel` and `channel_overwrite` to it). Prefer the existing `post` and `edit` ops, which need neither. If a new op kind turns out to be needed, ask the lead first: `board/discord_feed.py` is not in this task's files.
- `commands.js` `payload(ops)` on main: project bots register `/ideas` too, and only `/new-project` is ops-only. Registration is in `bridge.js` `register(ch)`: `commands.payload(ops)`. `/source` needs the bridge's project (`path.basename(dir)`) passed into `payload`. `commands.test.js` pins the exact list (12 names on the ops bot, 11 on a project bot, `setCommands` payload length 12). It also has a max_length test that reads each command's `project` option, or `name` for `new-project`. Edit those three tests so that `/source` appears only for `agent-board`, and so its own options (`url` required, `name` optional, each with a max_length) pass the max_length test.
- `commands.js` `handle()` also routes `ab:modal:new-project` / `np-token` and `ab:np:token:` components, and `ctx` carries `commandCenter`, `writeTokenFile` and `dropTokenFile`. `/source` is a new `handleCommand` branch and leaves those untouched.

**Constraints:**
- One add path: the ✅ handler calls `scout_sources.add_url` with the kind, URL and name stored at prompt time. It must not build its own row as `_check_requests` does today. Rewire `_check_requests` (the daily-poll fallback for a ✅ the bridge missed) to `add_url` too, so a pending request is added once whichever path sees the ✅ first. The pending record is removed under the `sources.lock` flock.
- "At once" means within one board tick of the Discord event, through the existing path: bridge event file → `board/discord_controls.consume_events`. The daily poll is not the path. The bridge today forwards reactions only in its home channel, on its own messages, for `REACT_EMOJI`. Extend it so a ✅ on a pending scout source prompt (`#scout` reply or `/source` reply) becomes an event, whatever channel that prompt is in. A `source:` message in `#scout` also becomes an event at once. The poll's request handling stays as the fallback for messages seen while the bridge was down, de-duplicated by `message_id`.
- `/source` is registered only by the agent-board project's bridge (`path.basename(dir) === 'agent-board'`), never by the ops bot or another project's bot. Only allowFrom users may use it (`commands.handle` already refuses others: keep that). Its reply must be a message that can take a reaction, so not an ephemeral one.
- Every Discord string is cut to the 2000-character limit and posted with no mentions. The source URL, the user's text and item titles are data, not markup, and are never echoed into a code fence unescaped (use `fence`). Nothing posts the bot token or request headers.
- `detect` and the first fetch run in the board's consumer, not in the Node bridge. The bridge only forwards events and edits or posts what the board asks for (outbox ops, or `scout_fetch` REST calls with a new `edit_message`, matching how today's poll replies).
- A5 applies (`[name]` is one `NAME_RE` token, otherwise the text is `why`). A duplicate name at ✅ time gets the next free `-N`.
- No change to how sources are polled, and no other fetch kinds (spec, Out of scope).

**Acceptance Criteria:**
- [ ] With a fake fetcher, ✅ from an allowFrom user on a pending prompt adds the source once and fetches it once (fetch count 1). The prompt is edited to `added: <name> (<kind>)` followed by exactly the first 3 titles. A second ✅, or the next poll's `_check_requests`, adds nothing and fetches nothing (mutation: drop the pending-record removal, and the source is added twice).
- [ ] A first fetch that raises gives `added, first fetch failed: <reason>`, the source stays in `sources.json`, and its health is unchanged by the add.
- [ ] A ✅ from a user not in allowFrom adds nothing and is audited `rejected`.
- [ ] A refused URL (fake resolver to 10.0.0.5) gets `refused: private address 10.0.0.5`. No prompt is recorded, so a later ✅ on that reply adds nothing.
- [ ] Node: `/source` appears in the agent-board bridge's command payload and not in the ops payload or another project's. `/source` from an allowed user writes one event carrying the URL and name. A non-allowed user gets `Not authorized.` and no source event. A ✅ on a recorded scout prompt outside the home channel writes one react event, and a ✅ on any other non-home message writes none.
- [ ] `source: <url> [name]` parsing: a one-token `NAME_RE` tail is the name, longer text is `why`, and a bare `source: <url>` is accepted.
- [ ] Main's liveness is unchanged. `liveness-bridge.test.js` passes unedited, including the guard (one `.send(` and one message `.reply(` in `bridge.js`). A `❓` from an allowlisted user still goes to `onAsk`. A scout ✅ prompt or `/source` reply never enters `st.liveness.bot_after` as the lead's answer. A node test checks this: after a `/source` reply in the home channel, `bot_after` holds no id outside `own_sent`.
- [ ] Every existing test in `board/tests/test_scout_*.py`, `board/tests/test_discord_controls.py` and the bridge suite still passes. In `commands.test.js`, only the payload, registration-count and max_length tests change, to add `/source` for `agent-board`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_scout_*.py' && python3 -m unittest discover -s board/tests -p 'test_discord_controls.py' && cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test` → `OK`, `OK`, then node's `# fail 0`

```json:metadata
{"files": ["board/scout_sources.py", "board/scout_fetch.py", "board/discord_controls.py", "board/tests/test_scout_sources.py", "board/tests/test_scout_fetch_local.py", "board/tests/test_discord_controls.py", "tools/discord-bridge/lib/commands.js", "tools/discord-bridge/bridge.js", "tools/discord-bridge/test/commands.test.js", "tools/discord-bridge/test/scout-source.test.js", "tools/discord-bridge/test/liveness-bridge.test.js", "tools/discord-bridge/test/fake-client.js"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_scout_*.py' && python3 -m unittest discover -s board/tests -p 'test_discord_controls.py' && cd tools/discord-bridge && (test -d node_modules || npm ci) && npm test", "acceptanceCriteria": ["checkmark adds once and fetches once with a fake fetcher; reply edited with added line and first 3 titles; second checkmark or poll adds nothing", "failed first fetch: 'added, first fetch failed: <reason>', source kept", "non-allowFrom checkmark rejected", "refused URL: 'refused: <reason>', no prompt", "/source only on the agent-board bridge, allowFrom only, one event; checkmark on a scout prompt outside home channel forwarded, others not", "source: <url> [name] parsing", "main liveness unchanged: liveness-bridge.test.js (sendOwn guard) passes unedited; question-mark still goes to onAsk; a /source reply never counts as the lead's answer", "existing scout, controls and bridge suites pass; commands.test.js changes only the payload, registration-count and max_length tests"], "modelTier": "frontier"}
```

### Task 6: Context recall for teammates (PostToolUse hook)

**Goal:** `claude/plugin/scripts/context-recall-file.sh` is registered on PostToolUse for `Read|Edit|Write|Grep|Glob`. It injects, as `additionalContext`, the archive entries whose `files:` cite the path the tool touched, at most once per (session, path). It skips entries already injected in the session and caps output at 4096 bytes, newest own date first. It uses the same project resolution, `TC_CONTEXT=0` kill switch and silent failure as `context-recall.sh`. Marker: `<state>/context-recall/<session_id>.paths`.

**Files:**
- Create: `claude/plugin/scripts/context-recall-file.sh` (mode 755)
- Modify: `claude/plugin/hooks/hooks.json` (one PostToolUse entry)
- Create: `tools/tests/test_context_recall_file.zsh`
- Modify: `tools/tests/test_plugin.zsh` (registration and executable checks)

**Acceptance Criteria:**
- [ ] A Read of a cited path injects its entries (and an entry citing its directory) once, newest first, with the header `Archived project context for <rel>:`. A second Read of the same path injects nothing. An Edit of a path whose entries were already injected injects nothing. A new path injects only its new entries. A path no entry cites injects nothing. Grep on a directory injects only entries citing that directory. Glob without a path, another tool, a path outside the repo and a bad session id all stay silent.
- [ ] `TC_CONTEXT=0`, no tmux pane, garbage stdin and a missing archive are silent (exit 0, no stdout, no stderr).
- [ ] 4 KB cap: 6 KB of matches gives whole lines only, at most 4096 bytes, newest first, fewer than all. A second Read of that path after the cap injects nothing (mutation: drop the `path<TAB><rel>` once-check, and this check fails; the planner ran it: `1 FAILED`).
- [ ] `hookEventName` is `PostToolUse`. That output shape is already used by `claude/plugin/scripts/spec-boundary-nudge.sh` and `teammate-remind.sh`, which serves as the probe that the harness reads `additionalContext` on PostToolUse.
- [ ] `test_plugin.zsh` checks the registration (matcher `Read|Edit|Write|Grep|Glob`, `--scoped`, timeout 5, not async) and that the script is executable.
- [ ] Real-state check, read-only, in a tmux pane of this project. Run `TC_STATE=$(mktemp -d)` with `print -r -- '{"session_id":"probe1","cwd":"'$PWD'","hook_event_name":"PostToolUse","tool_name":"Read","tool_input":{"file_path":"'$PWD'/board/scout_fetch.py"}}' | claude/plugin/scripts/context-recall-file.sh`. It reads the live archive `~/.local/state/agent-board/context/agent-board.archive.md` and writes only under the temp `TC_STATE`. Paste its output (entries or none) in the report.

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_context_recall_file.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: The test (RED).** Create `tools/tests/test_context_recall_file.zsh`:

````zsh
source "${0:A:h}/lib.zsh"
# context-recall-file: PostToolUse hook (Read|Edit|Write|Grep|Glob) that injects archived entries citing the path a tool touched,
# once per (session, path), skipping entries already injected in the session. Runs for real inside the scratch server (key `tt`);
# TC_CONTEXT_DIR and TC_STATE point at temp dirs. Spec: docs/superpowers/specs/2026-11-23-hardening-design.md, part c.
H="${TC_CTXRECALL_FILE:-$TT_REPO/claude/plugin/scripts/context-recall-file.sh}"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx"; mkdir -p "$TC_CONTEXT_DIR"
f="$TC_CONTEXT_DIR/tt.archive.md"
# payload <tool> <input json> [session] [cwd]: the PostToolUse stdin keys (as spec-boundary-nudge.sh and teammate-remind.sh read them)
payload() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[3],"transcript_path":"/tmp/none.jsonl","cwd":sys.argv[4],"permission_mode":"default","hook_event_name":"PostToolUse","tool_name":sys.argv[1],"tool_input":json.loads(sys.argv[2]),"tool_response":{},"tool_use_id":"t1"}))' "$1" "$2" "${3:-s1}" "${4:-$TT_REPO}" }
run_hook() { payload "$@" | "$H" --scoped >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)" }
fp() { print -r -- "{\"file_path\": \"$1\"}" }
ctx() { print -r -- "$out" | python3 -c 'import json,sys; h=json.load(sys.stdin)["hookSpecificOutput"]; assert h["hookEventName"]=="PostToolUse", h; sys.stdout.write(h["additionalContext"])' 2>/dev/null }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]] }
mkarchive() { python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n",
 "- usage rows carry a source (files: board/usage.py) · 2026-10-05 · archived 2026-11-18\n",
 "- plan limits come from the freshest tap (files: board/usage.py, board/server.py) · 2026-10-29 · archived 2026-11-10\n",
 "- metrics resolve from the main checkout (files: board/metrics.py) · 2026-10-20 · archived 2026-11-18\n",
 "- the readme is short (files: README.md) · 2026-09-01 · archived 2026-11-18\n",
 "- whole board dir note (files: board/) · 2026-08-01 · archived 2026-11-18\n",
 "\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
}
mkarchive
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s1
check "Read of a cited path: exit 0, nothing on stderr, output present" test $rc -eq 0 -a -z "$err" -a -n "$out"
check "header names the path"                                  test "$(ctx | head -1)" = "Archived project context for board/usage.py:"
check "entries citing the file and its directory, newest own date first" test "$(ctx | tail -n +2 | grep -o '· 20[0-9-]* ' | tr -d '·\n ')" = "2026-10-292026-10-052026-08-01"
check "an entry citing another file is not injected"           zsh -c '! print -r -- "$1" | grep -q "metrics resolve"' _ "$(ctx)"
check "marker file records the path"                            grep -qxF "path	board/usage.py" "$TC_STATE/context-recall/s1.paths"
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s1
check "second Read of the same path in the session: nothing"   silent
run_hook Edit "$(fp board/server.py)" s1
check "Edit of a path whose entries were all injected already: nothing" silent
run_hook Read "$(fp "$TT_REPO/board/metrics.py")" s1
check "a new cited path in the same session injects only its new entry" test "$(ctx | tail -n +2)" = "- metrics resolve from the main checkout (files: board/metrics.py) · 2026-10-20 · archived 2026-11-18"
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s2
check "another session id gets the entries again"              zsh -c 'print -r -- "$1" | grep -q "usage rows carry"' _ "$(ctx)"
run_hook Write "$(fp "$TT_REPO/bin/tmux-ctl")" s3
check "a path no entry cites: nothing"                          silent
run_hook Grep '{"pattern": "x", "path": "board"}' s4
check "Grep on a directory: only entries citing that directory" test "$(ctx | tail -n +2)" = "- whole board dir note (files: board/) · 2026-08-01 · archived 2026-11-18"
run_hook Glob '{"pattern": "*.md"}' s5
check "Glob without a path: nothing"                            silent
run_hook Bash '{"command": "cat README.md"}' s5
check "another tool: nothing"                                    silent
run_hook Read '{"file_path": "/etc/hosts"}' s5
check "a path outside the repo: nothing"                          silent
run_hook Read "$(fp "$TT_REPO/README.md")" '../x'
check "session_id ../x: silent, no file written"                  zsh -c '[[ $1 == 0 && -z "$2" ]] && [[ ! -e "$3/context-recall/../x.paths" && ! -e "$3/x.paths" ]]' _ $rc "$out" "$TC_STATE"
payload Read "$(fp "$TT_REPO/README.md")" s-kill | TC_CONTEXT=0 "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "TC_CONTEXT=0: silent"                                      silent
payload Read "$(fp "$TT_REPO/README.md")" s-notmux | TMUX= TMUX_PANE= "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "no tmux pane: silent"                                      silent
echo 'not json' | "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "garbage stdin: silent"                                     silent
rm -f "$f"; run_hook Read "$(fp "$TT_REPO/README.md")" s-noarch
check "no archive file: silent"                                   silent
# the cap: 6 KB of entries citing one path
python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n"]
for n in range(60):
    L.append(f"- big entry {n:02d} " + "x" * 75 + f" (files: board/usage.py) · 2026-09-{1 + n % 28:02d} · archived 2026-11-18\n")
L += ["\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s-cap
ctx | tail -n +2 > "$TT_DIR/lines.txt"
check "6 KB of matches: entry lines <= 4096 bytes, whole lines, newest first, fewer than all 60" python3 - "$TT_DIR/lines.txt" "$f" <<'PY'
import re, sys
b = open(sys.argv[1], "rb").read()
assert 0 < len(b) <= 4096, len(b)
got = b.decode().splitlines()
src = [l for l in open(sys.argv[2]).read().splitlines() if l.startswith("- ")]
date = lambda l: re.search(r"· (\d{4}-\d{2}-\d{2})", l).group(1)
assert all(g in src for g in got), "partial line"
assert [date(g) for g in got] == sorted([date(g) for g in got], reverse=True)
assert 0 < len(got) < len(src), len(got)
PY
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s-cap
check "once per (session, path): a second Read after the cap injects nothing more" silent
tt_done
````

Run `env -u AGENT_BOARD_LEAD zsh tools/tests/test_context_recall_file.zsh`. Expected RED: every check FAILs, because the hook script does not exist (rc 127, `no such file` on stderr). The mutation in Step 4 is what proves the once-check.

- [ ] **Step 2: The hook.** Create `claude/plugin/scripts/context-recall-file.sh` and `chmod 755` it:

````bash
#!/usr/bin/env bash
# PostToolUse (Read|Edit|Write|Grep|Glob): inject the archived context entries (${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.archive.md)
# whose `files:` cite the path the tool touched, so a teammate (its spawn prompt fires no UserPromptSubmit) gets recall too
# (spec: docs/superpowers/specs/2026-11-23-hardening-design.md, part c). The path: tool_input.file_path (Read, Edit, Write) or tool_input.path
# (Grep, Glob), resolved against cwd, repo-relative. An entry matches when it cites that path, or (for a file) a directory above it.
# Once per (session, path): <state dir>/context-recall/<session_id>.paths holds `path<TAB><rel>` and `entry<TAB><sha1>` lines, under flock;
# an entry already injected in this session is skipped. Output: at most 4096 bytes of whole entry lines, newest own date first.
# Same project resolution, kill switch (TC_CONTEXT=0) and silent failure as context-recall.sh. --scoped (the plugin registration) changes nothing.
[[ "$TC_CONTEXT" == 0 ]] && { cat >/dev/null; exit 0; }
payload=$(cat)
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
tmux_bin="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$tmux_bin" ]] || tmux_bin=tmux
sock="${TMUX%%,*}"
project=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null) || exit 0
sess=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null) || exit 0
[[ -n "$("$tmux_bin" -S "$sock" show-options -qv -t "=$sess:" @tc_bg 2>/dev/null)" ]] && project="${project%-bg}"
[[ "$project" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] || exit 0
dir="${TC_CONTEXT_DIR:-$HOME/.local/state/agent-board/context}"
state="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$(id -u)}"
HOOK_PAYLOAD="$payload" python3 -I - "$dir/$project.archive.md" "$state" <<'PY' 2>/dev/null || exit 0
import fcntl, hashlib, json, os, re, subprocess, sys
CAP = 4096
try:
    hook = json.loads(os.environ["HOOK_PAYLOAD"])
    sid, cwd, tool, ti = hook["session_id"], hook["cwd"], hook.get("tool_name"), hook.get("tool_input")
    if not (isinstance(sid, str) and isinstance(cwd, str) and isinstance(ti, dict)) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    arg = ti.get("file_path") if tool in ("Read", "Edit", "Write") else ti.get("path") if tool in ("Grep", "Glob") else None
    if not isinstance(arg, str) or not arg.strip():
        sys.exit(0)
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(0)
    root = os.path.realpath(r.stdout.strip())
    full = os.path.realpath(arg if os.path.isabs(arg) else os.path.join(cwd, arg))
    if full == root or not full.startswith(root + os.sep):
        sys.exit(0)
    rel, is_dir = os.path.relpath(full, root), os.path.isdir(full)
    try:
        with open(sys.argv[1], "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    marker_dir = os.path.join(sys.argv[2], "context-recall")
    os.makedirs(marker_dir, exist_ok=True)
    keep = []
    with open(os.path.join(marker_dir, sid + ".paths"), "a+", encoding="utf-8") as mf:
        fcntl.flock(mf, fcntl.LOCK_EX)
        mf.seek(0)
        done = mf.read().splitlines()
        if "path\t" + rel in done:
            sys.exit(0)
        seen = {l.split("\t", 1)[1] for l in done if l.startswith("entry\t")}
        mf.write("path\t" + rel + "\n")
        def hit(p):
            p = os.path.normpath(p.strip())
            if not p or p == ".":
                return False
            return p == rel or (not is_dir and rel.startswith(p + "/"))
        entries = []
        for line in text.splitlines():
            m = re.match(r"^- .+ · (\d{4}-\d{2}-\d{2})(?: · archived \d{4}-\d{2}-\d{2})?(?: · stale: .+ gone)?$", line)
            if not m:
                continue
            g = re.search(r"\(files: ([^)]*)\)", line)
            sha = hashlib.sha1(line.encode()).hexdigest()
            if g and sha not in seen and any(hit(p) for p in g.group(1).split(",")):
                entries.append((m.group(1), line, sha))
        entries.sort(key=lambda e: e[0], reverse=True)        # stable: file order among equal dates
        used = 0
        for _, line, sha in entries:
            n = len(line.encode()) + 1
            if used + n > CAP:
                break
            keep.append(line); used += n
            mf.write("entry\t" + sha + "\n")
    if keep:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": f"Archived project context for {rel}:\n" + "\n".join(keep)}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
````

- [ ] **Step 3: Register it.** In `claude/plugin/hooks/hooks.json`, add this entry to `PostToolUse` right after the `"matcher": "Bash"` entry (sync, not async: the output must reach the model):

```json
      {
        "matcher": "Read|Edit|Write|Grep|Glob",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/context-recall-file.sh\" --scoped", "timeout": 5 }
        ]
      },
```

In `tools/tests/test_plugin.zsh` (on main the anchor is still line 77; main's only change there is a `[Watch]` check near line 186), after the line `check "context-recall.sh is executable" test -x "$P/scripts/context-recall.sh"`, add:

````zsh
check "hooks.json registers context-recall-file on PostToolUse Read|Edit|Write|Grep|Glob, --scoped, timeout 5, not async" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PostToolUse"]
hit = [(e.get("matcher"), h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/context-recall-file.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] == "Read|Edit|Write|Grep|Glob" and hit[0][1]["timeout"] == 5 and not hit[0][1].get("async"), hit
PY
check "context-recall-file.sh is executable" test -x "$P/scripts/context-recall-file.sh"
````

- [ ] **Step 4: Run the Verify command** → `ALL PASS` twice (the planner ran the test file against this exact hook: 21 ok). Then run the mutation once: in a scratch copy of the hook, change `if "path\t" + rel in done:` to `if False:` and run the test with `TC_CTXRECALL_FILE=<copy>`. Expected: `FAIL - once per (session, path): a second Read after the cap injects nothing more`. Then run the real-state check from the acceptance criteria.

- [ ] **Step 5: Commit** the four files as `feat(plugin): context recall on file tools for teammates`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/plugin/scripts/context-recall-file.sh", "claude/plugin/hooks/hooks.json", "tools/tests/test_context_recall_file.zsh", "tools/tests/test_plugin.zsh"], "verifyCommand": "env -u AGENT_BOARD_LEAD zsh tools/tests/test_context_recall_file.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["cited path injected once per session and path; already-injected entries skipped; uncited path, other tool, outside path silent", "TC_CONTEXT=0, no pane, garbage stdin, no archive silent", "4 KB cap whole lines newest first; once-check mutation fails the cap re-read check", "hookEventName PostToolUse", "test_plugin checks registration and executable bit", "read-only run against the live archive, output in the report"], "modelTier": "standard"}
```

## Self-review notes

- Spec coverage. a: Tasks 1 and 2 (approved line with the full SHA, the rev-parse check, merge of the SHA, re-request, unpinned old line, `merged <merge sha>`, the tests named in the spec). b1: Task 3 (every add, request and fetch hop, each class, IPv4-mapped, literal IP, redirect hops at most 5, `Refusal` reasons). b2: Task 4 (table, name default, one fetch, 10 s, fallback). b3: Tasks 4 (`--kind` optional, help line in place, one add function) and 5 (Discord paths, instant add and fetch, edited reply, refused URL). c: Task 6.
- Dependencies: Task 4 needs Task 3 (`check_url_safe`, `Refused`). Task 5 needs Tasks 3 and 4 (`detect`, `add_url`). Tasks 1, 2 and 6 are independent.
- The planner ran every plan-authored diff and test once against the base (or, for Task 4, against Task 3's result), under zsh and Python 3.14, and the scout suites also under 3.9. The RED and mutation results quoted above are from those runs.
