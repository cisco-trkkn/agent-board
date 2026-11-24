"use strict";
// Table tests for the spec-driven strategy: events in, commands out. No database, no backend, no process.
// Every decide() call in this file gets deep-frozen input, so any write to its input throws.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const strategy = require("../lib/engine/strategy/spec_driven");
const bounce = require("../lib/engine/bounce");
const { DEFAULT_RETRY, retryFor } = require("../lib/engine/policy");

const { decide } = strategy;
const RETRY = Object.fromEntries(Object.keys(DEFAULT_RETRY).map((k) => [k, retryFor({}, k)]));
const withRetry = (kind, over) => ({ ...RETRY, [kind]: { ...RETRY[kind], ...over } });

const clone = (v) => JSON.parse(JSON.stringify(v));
function deepFreeze(v) {
  if (v && typeof v === "object" && !Object.isFrozen(v)) {
    Object.freeze(v);
    Object.values(v).forEach(deepFreeze);
  }
  return v;
}

const T = (n, tier, files) => ({ n, subject: `task ${n}`, tier, files: files || [`src/f${n}.js`], verifyCommand: `test ${n}` });
const plan = (...tiers) => tiers.map((tier, i) => T(i + 1, tier));
const F = (severity, task, text) => ({ severity, task, text: text || `${severity} on ${task}` });
const DONE = { status: "done", commits: ["abc"], concerns: [] };
const PASS = { verdict: "pass", findings: [] };
const findings = (...list) => ({ verdict: "findings", findings: list });

const implement = (task, tier) => ({ type: "start_job", kind: "implement", task, tier });
const runCheck = (task) => ({ type: "run_check", task });
const review = (task, tier) => ({ type: "start_job", kind: "review", task, tier: tier || "standard" });
const batch = (...tasks) => ({ type: "start_job", kind: "review", tier: "standard", tasks });
const deferred = (text, task) => (task === undefined ? { type: "log", kind: "deferred", text } : { type: "log", kind: "deferred", text, task });
const FINAL = [{ type: "set_state", state: "final_review" }, { type: "start_job", kind: "final_review", tier: "frontier" }];
const INTEGRATE = [{ type: "set_state", state: "integrating" }, { type: "request_integrate" }];
const ruling = (text, cost) => ({ type: "record_ruling", text, cost_if_wrong: cost, by: "architect" });

// Plays the engine core: keeps the event log and the job rows, feeds decide() one event at a time.
function harness(tasks, opts = {}) {
  const jobs = [];
  const events = [];
  let seq = 0;
  const h = {
    jobs, events,
    state: () => ({ spec: { id: "s", state: "running" }, tasks, jobs, events, retry: opts.retry || RETRY }),
    feed(kind, detail = {}) {
      const event = { seq: ++seq, ts: seq, spec: "s", job: detail.job || null, kind, detail: { rows: [], ...detail } };
      const cmds = decide(deepFreeze(clone(h.state())), deepFreeze(clone(event)));
      events.push(event);
      for (const c of cmds) {
        if (c.type !== "start_job") continue;
        const task = c.task === undefined ? null : c.task;
        jobs.push({ id: `s:${c.kind}${task === null ? "" : task}:${jobs.length + 1}`, spec: "s", kind: c.kind, task, tier: c.tier, state: "running" });
      }
      return cmds;
    },
    last(kind, task) {
      const j = [...jobs].reverse().find((x) => x.kind === kind && (task === undefined || x.task === task));
      assert.ok(j, `no ${kind} job for task ${task}`);
      return j;
    },
    start: (stale = false) => { h.feed("spec_started"); return h.feed("stale_result", { stale }); },
    done(kind, task, status, extra = {}) {
      const j = h.last(kind, task);
      return h.feed("job_done", { job: j.id, kind, task: j.task, status: status || (/review/.test(kind) ? PASS : DONE), ...extra });
    },
    failed(kind, task, reason = "gone") {
      const j = h.last(kind, task);
      return h.feed("job_failed", { job: j.id, kind, task: j.task, reason });
    },
    check: (task, ok, text) => h.feed("check_result", ok ? { task, ok: true } : { task, ok: false, text: text || `not ok ${task}\nfull log: /l` }),
    // implement <n> reported done and its check came back green
    green(task, kind = "implement") { assert.deepEqual(h.done(kind, task), [runCheck(task)]); return h.check(task, true); },
    architect: (kase, decision, at = {}, text = "the ruling", cost = "the cost") =>
      h.feed("architect_decision", { case: kase, decision, ruling: text, cost_if_wrong: cost, ...at }),
    // every task implemented, green and passed by its own review; returns the commands of the last review
    throughTasks() {
      let out = h.start();
      for (const t of tasks) {
        assert.deepEqual(out, [implement(t.n, t.tier)]);
        assert.deepEqual(h.green(t.n), [review(t.n)]);
        out = h.done("review", t.n);
      }
      return out;
    },
  };
  return h;
}

// ---- step 1: stale check -------------------------------------------------------------------------------------------

test("spec_started asks for the stale check and starts no job", () => {
  const h = harness(plan("standard"));
  assert.deepEqual(h.feed("spec_started"), [{ type: "run_check", check: "stale" }]);
});

test("stale_result: stale starts one refresh job, fresh starts the first implement", () => {
  // mutation: swap the two branches of `d.stale ? refresh : advance` → both asserts fail
  const stale = harness(plan("mechanical", "standard"));
  assert.deepEqual(stale.start(true), [{ type: "start_job", kind: "refresh", tier: "frontier" }]);
  assert.deepEqual(stale.done("refresh"), [implement(1, "mechanical")]);
  const fresh = harness(plan("mechanical", "standard"));
  assert.deepEqual(fresh.start(false), [implement(1, "mechanical")]);
});

test("a task without a tier runs on the standard tier", () => {
  const h = harness([T(1, undefined)]);
  assert.deepEqual(h.start(), [implement(1, "standard")]);
});

// ---- step 3: green check and bounces -------------------------------------------------------------------------------

test("implement done asks the engine for the green check", () => {
  const h = harness(plan("standard"));
  h.start();
  assert.deepEqual(h.done("implement", 1), [runCheck(1)]);
});

test("red 1 and red 2 bounce to the implementer's session, the third red escalates", () => {
  // mutation: change `t.reds >= max` to `t.reds > max` in onCheck → "third red escalates" fails (a third bounce instead)
  const h = harness(plan("standard", "standard"));
  h.start();
  h.done("implement", 1);
  const implId = h.last("implement", 1).id;
  assert.deepEqual(h.check(1, false, "not ok a\nfull log: /x"), [
    { type: "start_job", kind: "fix", task: 1, tier: "standard", resume_of: implId, findings: "not ok a\nfull log: /x", bounce: 1 },
  ]);
  assert.deepEqual(h.done("fix", 1), [runCheck(1)]);
  assert.deepEqual(h.check(1, false, "not ok b"), [
    { type: "start_job", kind: "fix", task: 1, tier: "standard", resume_of: implId, findings: "not ok b", bounce: 2 },
  ]);
  h.done("fix", 1);
  assert.deepEqual(h.check(1, false, "not ok c"), [{ type: "escalate", case: "verify_red", job: h.last("fix", 1).id, task: 1 }], "third red escalates");
});

test("the bounce limit comes from state.retry.bounce, not a literal", () => {
  // mutation: replace `policy(ctx, "bounce").max_attempts` with 3 → the second red bounces instead of escalating
  const h = harness(plan("standard"), { retry: withRetry("bounce", { max_attempts: 2 }) });
  h.start();
  h.done("implement", 1);
  assert.equal(h.check(1, false)[0].bounce, 1);
  h.done("fix", 1);
  assert.deepEqual(h.check(1, false), [{ type: "escalate", case: "verify_red", job: h.last("fix", 1).id, task: 1 }]);
});

test("a green check resets the red count: reds are counted per run of reds, not per task", () => {
  // mutation: delete `t.reds = 0` on a green check → the red after the review escalates (2 + 1 = 3) instead of bounce 1
  const h = harness(plan("standard"));
  h.start();
  h.done("implement", 1);
  h.check(1, false);
  h.done("fix", 1);
  h.check(1, false);
  h.done("fix", 1);
  assert.deepEqual(h.check(1, true), [review(1)]);
  h.done("review", 1, findings(F("important", 1)));
  h.done("fix", 1);
  assert.equal(h.check(1, false)[0].bounce, 1);
});

test("reds of one task do not count against another", () => {
  // mutation: count reds on ctx instead of the task (`ctx.reds`) → task 2's first red escalates
  const h = harness(plan("standard", "standard"));
  h.start();
  h.done("implement", 1);
  h.check(1, false);
  h.done("fix", 1);
  h.check(1, false);
  h.done("fix", 1);
  h.check(1, true);
  h.done("review", 1);
  h.done("implement", 2);
  assert.equal(h.check(2, false)[0].bounce, 1);
});

// ---- step 4: review and batches ------------------------------------------------------------------------------------

test("green on a standard task starts its review on the standard tier; a pass starts the next task", () => {
  const h = harness(plan("standard", "frontier"));
  h.start();
  assert.deepEqual(h.green(1), [review(1)]);
  assert.deepEqual(h.done("review", 1), [implement(2, "frontier")]);
});

test("a green mechanical task is held while the next task is mechanical; the batch is one review", () => {
  // mutation: drop `batchable(next)` from the hold condition → task 2 is held past the standard task 3 (implement 3, no review)
  const h = harness(plan("mechanical", "mechanical", "standard"));
  h.start();
  assert.deepEqual(h.green(1), [implement(2, "mechanical")], "task 1 held, task 2 dispatched");
  assert.deepEqual(h.green(2), [batch(1, 2)], "the batch closes before the standard task");
  assert.deepEqual(h.done("review"), [implement(3, "standard")]);
  assert.deepEqual(h.green(3), [review(3)]);
});

test("a batch closes at 5 tasks and at the plan's end", () => {
  // mutation: change `held.length < BATCH_MAX` to `<=` → the fifth green dispatches task 6 instead of the review
  const h = harness(plan(...Array(7).fill("mechanical")));
  h.start();
  for (const n of [1, 2, 3, 4]) assert.deepEqual(h.green(n), [implement(n + 1, "mechanical")]);
  assert.deepEqual(h.green(5), [batch(1, 2, 3, 4, 5)]);
  assert.deepEqual(h.done("review"), [implement(6, "mechanical")]);
  assert.deepEqual(h.green(6), [implement(7, "mechanical")]);
  assert.deepEqual(h.green(7), [batch(6, 7)], "plan end closes the batch");
  assert.deepEqual(h.done("review"), FINAL);
});

test("a task whose files match the exclusion is never batched, whatever its tier", () => {
  // mutation: remove the BATCH_EXCLUDE test from batchable() → green 1 holds task 1 and dispatches task 2
  const tasks = [T(1, "mechanical"), T(2, "mechanical", ["src/a.js", ".github/workflows/ci.yml"]), T(3, "mechanical"), T(4, "mechanical")];
  const h = harness(tasks);
  h.start();
  assert.deepEqual(h.green(1), [review(1)], "the next task is excluded, so task 1 is reviewed alone");
  assert.deepEqual(h.done("review", 1), [implement(2, "mechanical")]);
  assert.deepEqual(h.green(2), [review(2)], "the excluded task gets its own review");
  assert.deepEqual(h.done("review", 2), [implement(3, "mechanical")]);
  assert.deepEqual(h.green(3), [implement(4, "mechanical")]);
  assert.deepEqual(h.green(4), [batch(3, 4)]);
});

test("the exclusion regex is the Global Constraints one, verbatim", () => {
  // mutation: drop the `i` flag → "Config/app.yml" and "SECURITY.md" stop matching
  assert.equal(String(strategy.BATCH_EXCLUDE),
    String(/(^|\/)(\.gitlab-ci|\.github\/|\.agent-ci|ci\/|migrations?\/|security|auth|settings(\.local)?\.json|config\/|\.env)/i));
  const excluded = [".gitlab-ci.yml", ".github/workflows/x.yml", ".agent-ci.yml", "ci/run.sh", "db/migrations/001.sql", "migration/1.py",
    "SECURITY.md", "lib/auth.js", "src/auth/login.js", ".claude/settings.json", "settings.local.json", "Config/app.yml", "app/.env"];
  const batched = ["src/app.js", "docs/plan.md", "lib/oauth.js", "src/circuit/x.js", "reconfig/x.js", "engine/lib/engine/db.js"];
  for (const f of excluded) assert.equal(strategy.batchable(T(1, "mechanical", ["src/ok.js", f])), false, f);
  for (const f of batched) assert.equal(strategy.batchable(T(1, "mechanical", [f])), true, f);
  assert.equal(strategy.batchable(T(1, "standard", ["src/app.js"])), false, "only mechanical tasks batch");
});

test("a batch verdict is per task: each task with findings gets its own fix loop, lowest first", () => {
  // mutation: change owner() to `() => tasks[0]` (every finding to the batch's first task) → task 2's fix round is not the first command
  const h = harness(plan("mechanical", "mechanical", "mechanical", "standard"));
  h.start();
  h.green(1);
  h.green(2);
  assert.deepEqual(h.green(3), [batch(1, 2, 3)]);
  const f2 = F("important", 2);
  const f3 = F("critical", 3);
  assert.deepEqual(h.done("review", undefined, findings(f3, F("minor", 1, "nit"), f2)), [
    deferred("nit", 1),
    { type: "start_job", kind: "fix", task: 2, tier: "mechanical", round: 1, findings: [f2], resume_of: h.last("implement", 2).id },
  ]);
  assert.deepEqual(h.done("fix", 2), [runCheck(2)]);
  assert.deepEqual(h.check(2, true), [review(2)], "a fix without fix_stats is re-reviewed on the standard tier, alone");
  assert.deepEqual(h.done("review", 2), [
    { type: "start_job", kind: "fix", task: 3, tier: "mechanical", round: 1, findings: [f3], resume_of: h.last("implement", 3).id },
  ]);
  h.done("fix", 3);
  h.check(3, true);
  assert.deepEqual(h.done("review", 3), [implement(4, "standard")], "task 1 passed in the batch; the plan goes on");
});

// ---- step 5: fix loop ----------------------------------------------------------------------------------------------

test("critical and important findings start fix rounds 1 to 5; round 5's findings escalate", () => {
  // mutation: change `t.rounds > max` to `t.rounds >= max` in fixRound → round 5 escalates instead of starting a fix
  // mutation: change `t.rounds <= RESUME_FIX_ROUNDS` to `<` → round 3 loses resume_of
  const h = harness(plan("standard", "standard"));
  h.start();
  const implId = h.last("implement", 1).id;
  assert.deepEqual(h.green(1), [review(1)]);
  for (let round = 1; round <= 5; round++) {
    const f = F(round % 2 ? "important" : "critical", 1, `finding ${round}`);
    const want = { type: "start_job", kind: "fix", task: 1, tier: "standard", round, findings: [f] };
    if (round <= 3) want.resume_of = implId; // rounds 1-3 resume the implementer, 4-5 are fresh workers
    assert.deepEqual(h.done("review", 1, findings(f)), [want], `fix round ${round}`);
    assert.deepEqual(h.green(1, "fix"), [review(1)], `re-review ${round}`);
  }
  assert.deepEqual(h.done("review", 1, findings(F("important", 1))),
    [{ type: "escalate", case: "fix_rounds_exhausted", job: h.last("fix", 1).id, task: 1 }]);
});

test("the round limit comes from state.retry.fix_round", () => {
  // mutation: replace `policy(ctx, "fix_round").max_attempts` with 5 → the second findings start round 2 instead of escalating
  const h = harness(plan("standard"), { retry: withRetry("fix_round", { max_attempts: 1 }) });
  h.start();
  h.green(1);
  assert.equal(h.done("review", 1, findings(F("important", 1)))[0].round, 1);
  h.green(1, "fix");
  assert.equal(h.done("review", 1, findings(F("important", 1)))[0].case, "fix_rounds_exhausted");
});

test("minor findings are logged as deferred and do not block the task", () => {
  // mutation: add "minor" to BLOCKING → a fix round starts instead of the next task
  const h = harness(plan("standard", "standard"));
  h.start();
  h.green(1);
  assert.deepEqual(h.done("review", 1, findings(F("minor", 1, "rename x"), F("minor", 1, "typo"))),
    [deferred("rename x", 1), deferred("typo", 1), implement(2, "standard")]);
});

test("a red check in fix round 4 bounces to that round's fresh fixer, not the first implementer", () => {
  // mutation: never update t.session on a fresh fix job → resume_of is the implement job
  const h = harness(plan("standard"));
  h.start();
  h.green(1);
  for (let round = 1; round <= 4; round++) {
    h.done("review", 1, findings(F("important", 1)));
    if (round < 4) h.green(1, "fix");
  }
  const fixer = h.last("fix", 1).id;
  h.done("fix", 1);
  const [cmd] = h.check(1, false);
  assert.equal(cmd.bounce, 1);
  assert.equal(cmd.resume_of, fixer);
});

test("a small fix on a mechanical task is re-reviewed on the mechanical tier; every other fix on standard", () => {
  // mutation: change `s.lines <= SMALL_FIX.lines` to `<` → the 20-line row fails; remove the tier test → the standard-task row fails
  const small = { lines: 20, files: 2, added: 0, tests_removed: 0 };
  const rows = [
    ["mechanical", small, "mechanical"],
    ["mechanical", { ...small, lines: 21 }, "standard"],
    ["mechanical", { ...small, files: 3 }, "standard"],
    ["mechanical", { ...small, added: 1 }, "standard"],
    ["mechanical", { ...small, tests_removed: 1 }, "standard"],
    ["mechanical", { lines: 3, files: 1 }, "standard"], // incomplete numbers are not small
    ["mechanical", undefined, "standard"],
    ["standard", small, "standard"],
    ["frontier", small, "standard"],
  ];
  for (const [tier, stats, want] of rows) {
    const h = harness([T(1, tier), T(2, "frontier")]);
    h.start();
    assert.deepEqual(h.green(1), [review(1)]);
    h.done("review", 1, findings(F("important", 1)));
    assert.deepEqual(h.done("fix", 1, DONE, stats ? { fix_stats: stats } : {}), [runCheck(1)]);
    assert.deepEqual(h.check(1, true), [review(1, want)], `${tier} ${JSON.stringify(stats)}`);
  }
});

test("fix_stats is also read from the job's status object", () => {
  const h = harness([T(1, "mechanical"), T(2, "frontier")]);
  h.start();
  h.green(1);
  h.done("review", 1, findings(F("important", 1)));
  h.done("fix", 1, { ...DONE, fix_stats: { lines: 2, files: 1, added: 0, tests_removed: 0 } });
  assert.deepEqual(h.check(1, true), [review(1, "mechanical")]);
});

// ---- blocked and failed jobs ---------------------------------------------------------------------------------------

test("an implementer reporting blocked escalates", () => {
  // mutation: drop the `status.status === "blocked"` branch → run_check instead of the escalation
  const h = harness(plan("standard"));
  h.start();
  assert.deepEqual(h.done("implement", 1, { status: "blocked", commits: [], concerns: ["no access"] }),
    [{ type: "escalate", case: "blocked", job: h.last("implement", 1).id, task: 1 }]);
});

test("job_failed: nothing the first time, failed_twice the second time for the same kind and task", () => {
  // mutation: change `n >= p.max_attempts` to `>` → the second failure returns []
  const h = harness(plan("standard", "standard"));
  h.start();
  assert.deepEqual(h.failed("implement", 1), []);
  assert.deepEqual(h.failed("implement", 1), [{ type: "escalate", case: "failed_twice", job: h.last("implement", 1).id, task: 1 }]);
});

test("failures are counted per job kind and task, and a finished job resets the count", () => {
  // mutation: remove `delete ctx.failures[keyOf(kind, task)]` from onJobDone → round 2's fix failing once escalates
  const h = harness(plan("standard", "standard"));
  h.start();
  assert.deepEqual(h.failed("implement", 1), []);
  h.green(1);
  assert.deepEqual(h.failed("review", 1), [], "another kind");
  h.done("review", 1, findings(F("important", 1)));
  assert.deepEqual(h.failed("fix", 1), []);
  h.green(1, "fix");
  h.done("review", 1, findings(F("important", 1)));
  assert.deepEqual(h.failed("fix", 1), [], "round 2's fix failing once is a first failure");
  h.green(1, "fix");
  h.done("review", 1);
  assert.deepEqual(h.failed("implement", 2), [], "another task");
});

test("usage_limit and model_limit failures are the core's and never count", () => {
  // mutation: remove the `model_limit` line, or replace the no_retry_on test with `false` → the heartbeat_timeout call escalates
  const h = harness(plan("standard"));
  h.start();
  assert.deepEqual(h.failed("implement", 1, "usage_limit"), []);
  assert.deepEqual(h.failed("implement", 1, "model_limit"), []);
  assert.deepEqual(h.failed("implement", 1, "heartbeat_timeout"), []);
  assert.equal(h.failed("implement", 1, "job_timeout")[0].case, "failed_twice");
});

test("the failure limit and on_exhausted come from state.retry", () => {
  // mutation: replace `p.max_attempts` with 2 → the 3-attempt row escalates on the second failure
  const three = harness(plan("standard"), { retry: withRetry("implement", { max_attempts: 3 }) });
  three.start();
  assert.deepEqual(three.failed("implement", 1), []);
  assert.deepEqual(three.failed("implement", 1), []);
  assert.equal(three.failed("implement", 1)[0].case, "failed_twice");
  // mutation: drop the `on_exhausted === "architect"` test → this returns an escalation the core did not ask for
  const parks = harness(plan("standard"), { retry: withRetry("implement", { on_exhausted: "park" }) });
  parks.start();
  parks.failed("implement", 1);
  assert.deepEqual(parks.failed("implement", 1), []);
});

test("a missing retry row is an error, not a silent default", () => {
  const h = harness(plan("standard"), { retry: {} });
  h.start();
  h.done("implement", 1);
  assert.throws(() => h.check(1, false), /state\.retry\.bounce/);
});

// ---- step 6: final review ------------------------------------------------------------------------------------------

test("the last task passing starts the final review on the frontier tier", () => {
  const h = harness(plan("standard", "standard"));
  assert.deepEqual(h.throughTasks(), FINAL);
});

test("a clean final review goes to integration; minors are deferred on the way", () => {
  const clean = harness(plan("standard"));
  clean.throughTasks();
  assert.deepEqual(clean.done("final_review"), INTEGRATE);
  const minors = harness(plan("standard"));
  minors.throughTasks();
  assert.deepEqual(minors.done("final_review", undefined, findings(F("minor", 1, "nit"))), [deferred("nit", 1), ...INTEGRATE]);
});

test("final findings: one fix_wave, then one re_review, then integration when clean", () => {
  // mutation: change the fix_wave start_job's kind to "fix" → the first assert fails
  const h = harness(plan("mechanical", "frontier", "standard"));
  h.start();
  h.green(1);
  h.done("review", 1);
  h.green(2);
  h.done("review", 2);
  h.green(3);
  assert.deepEqual(h.done("review", 3), FINAL);
  const blocking = [F("important", 1), F("critical", 3)];
  assert.deepEqual(h.done("final_review", undefined, findings(blocking[0], F("minor", 2, "nit"), blocking[1])), [
    deferred("nit", 2),
    { type: "start_job", kind: "fix_wave", tier: "standard", findings: blocking }, // the highest tier among the tasks with findings
  ]);
  assert.deepEqual(h.done("fix_wave"), [{ type: "start_job", kind: "re_review", tier: "frontier", findings: blocking }]);
  assert.deepEqual(h.done("re_review"), INTEGRATE);
});

test("residual findings after the re-review escalate; no second fix wave", () => {
  // mutation: change `if (kind === "final_review")` to `if (true)` → a second fix_wave starts instead of the escalation
  const h = harness(plan("standard"));
  h.throughTasks();
  h.done("final_review", undefined, findings(F("important", 1)));
  h.done("fix_wave");
  assert.deepEqual(h.done("re_review", undefined, findings(F("important", 1, "still there"), F("minor", 1, "nit"))),
    [deferred("nit", 1), { type: "escalate", case: "residual_findings", job: h.last("fix_wave").id }]);
});

// ---- integration results -------------------------------------------------------------------------------------------

test("integrated: the outcome ends the spec; tests red after the merge escalate", () => {
  // mutation: drop the `tests_red` branch → set_state done with outcome tests_red
  const ok = harness(plan("standard"));
  ok.throughTasks();
  ok.done("final_review");
  assert.deepEqual(ok.feed("integrated", { outcome: "mr https://x/1" }), [{ type: "set_state", state: "done", outcome: "mr https://x/1" }]);
  const red = harness(plan("standard"));
  red.throughTasks();
  red.done("final_review");
  assert.deepEqual(red.feed("integrated", { outcome: "tests_red" }), [{ type: "escalate", case: "tests_red_after_merge" }]);
});

test("tests red before the merge park the spec; approve integrates again, deny and fail end it", () => {
  const question = "project tests are red before the merge";
  const mk = () => {
    const h = harness(plan("standard"));
    h.throughTasks();
    h.done("final_review");
    assert.deepEqual(h.feed("integrated", { outcome: "tests_red_before" }), [{ type: "park", question, step: "integrate", kind: "stop_class", site: "tests_red" }]);
    return h;
  };
  assert.deepEqual(mk().feed("signal", { answer: "approve", note: null, step: "integrate" }), [{ type: "request_integrate" }]);
  assert.deepEqual(mk().feed("signal", { answer: "deny", note: null, step: "integrate" }),
    [{ type: "set_state", state: "done", outcome: `denied: ${question}` }]);
  assert.deepEqual(mk().feed("signal", { answer: "fail", note: "give up", step: "integrate" }),
    [{ type: "set_state", state: "done", outcome: "failed — give up" }]);
});

// ---- architect decisions (spec section 4) --------------------------------------------------------------------------

// A spec driven to each escalation case; returns the harness and the escalate command.
const CASES = {
  verify_red() {
    const h = harness(plan("standard", "standard"));
    h.start();
    h.done("implement", 1);
    h.check(1, false, "red 1");
    h.done("fix", 1);
    h.check(1, false, "red 2");
    h.done("fix", 1);
    return [h, h.check(1, false, "red 3")[0]];
  },
  fix_rounds_exhausted() {
    const h = harness(plan("standard", "standard"), { retry: withRetry("fix_round", { max_attempts: 1 }) });
    h.start();
    h.green(1);
    h.done("review", 1, findings(F("important", 1, "first")));
    h.green(1, "fix");
    return [h, h.done("review", 1, findings(F("important", 1, "second"), F("critical", 1, "third")))[0]];
  },
  blocked() {
    const h = harness(plan("standard", "standard"));
    h.start();
    return [h, h.done("implement", 1, { status: "blocked", commits: [], concerns: ["no access", "no docs"] })[0]];
  },
  failed_twice() {
    const h = harness(plan("standard", "standard"));
    h.start();
    h.failed("implement", 1, "gone");
    return [h, h.failed("implement", 1, "job_timeout")[0]];
  },
  residual_findings() {
    const h = harness(plan("standard"));
    h.throughTasks();
    h.done("final_review", undefined, findings(F("important", 1, "first")));
    h.done("fix_wave");
    return [h, h.done("re_review", undefined, findings(F("important", 1, "left over")))[0]];
  },
  tests_red_after_merge() {
    const h = harness(plan("standard"));
    h.throughTasks();
    h.done("final_review");
    return [h, h.feed("integrated", { outcome: "tests_red" })[0]];
  },
};
const at = (esc) => ({ ...(esc.job ? { job: esc.job } : {}), ...(esc.task ? { task: esc.task } : {}) });

test("every case escalates with exactly the spec's case names", () => {
  assert.deepEqual(Object.keys(CASES).sort(), [...strategy.CASES].sort());
  for (const [name, mk] of Object.entries(CASES)) {
    const [, esc] = mk();
    assert.equal(esc.type, "escalate", name);
    assert.equal(esc.case, name);
  }
});

test("architect proceed: the finding is parked as deferred and the spec goes on as if the step had passed", () => {
  // mutation: return only the ruling for `proceed` → every row fails (nothing continues)
  const want = {
    // the red check counts as green: the task goes to review
    verify_red: [deferred("parked (verify_red): red 3", 1), review(1)],
    // the review counts as passed: the next task starts
    fix_rounds_exhausted: [deferred("parked (fix_rounds_exhausted): second", 1), deferred("parked (fix_rounds_exhausted): third", 1), implement(2, "standard")],
    // the blocked job counts as done: its check runs
    blocked: [deferred("parked (blocked): implement blocked: no access; no docs", 1), runCheck(1)],
    failed_twice: [deferred("parked (failed_twice): implement failed twice (job_timeout)", 1), runCheck(1)],
    residual_findings: [deferred("parked (residual_findings): left over", 1), ...INTEGRATE],
    tests_red_after_merge: [deferred("parked (tests_red_after_merge): tests red after the merge"),
      { type: "set_state", state: "done", outcome: "tests_red — proceed: the ruling" }],
  };
  for (const [name, mk] of Object.entries(CASES)) {
    const [h, esc] = mk();
    assert.deepEqual(h.architect(name, "proceed", at(esc)), [ruling("the ruling", "the cost"), ...want[name]], name);
  }
});

test("architect proceed on a review that failed twice passes the tasks it covered", () => {
  const h = harness(plan("mechanical", "mechanical", "standard"));
  h.start();
  h.green(1);
  assert.deepEqual(h.green(2), [batch(1, 2)]);
  h.failed("review");
  const [esc] = h.failed("review");
  assert.deepEqual(esc, { type: "escalate", case: "failed_twice", job: h.last("review").id });
  assert.deepEqual(h.architect("failed_twice", "proceed", at(esc)),
    [ruling("the ruling", "the cost"), deferred("parked (failed_twice): review failed twice (gone)"), implement(3, "standard")]);
});

test("architect retry_higher_tier re-runs the job one tier up", () => {
  // mutation: use `TIERS.indexOf(row.tier)` without the + 1 → the re-run keeps its tier
  const rows = {
    // the job that left the check red was a bounce fix: a fresh fixer one tier up gets the red output
    verify_red: { type: "start_job", kind: "fix", task: 1, tier: "frontier", findings: "red 3" },
    fix_rounds_exhausted: { type: "start_job", kind: "fix", task: 1, tier: "frontier", findings: [F("important", 1, "second"), F("critical", 1, "third")] },
    blocked: implement(1, "frontier"),
    failed_twice: implement(1, "frontier"),
    residual_findings: { type: "start_job", kind: "fix_wave", tier: "frontier", findings: [F("important", 1, "left over")] },
  };
  for (const [name, want] of Object.entries(rows)) {
    const [h, esc] = CASES[name]();
    assert.deepEqual(h.architect(name, "retry_higher_tier", at(esc)), [ruling("the ruling", "the cost"), want], name);
  }
});

test("after a retry_higher_tier the task's later jobs stay on the higher tier and bounce to the new worker", () => {
  const [h, esc] = CASES.blocked();
  h.architect("blocked", "retry_higher_tier", at(esc));
  const fresh = h.last("implement", 1).id;
  assert.notEqual(fresh, esc.job);
  h.done("implement", 1);
  assert.deepEqual(h.check(1, false, "red"), [{ type: "start_job", kind: "fix", task: 1, tier: "frontier", resume_of: fresh, findings: "red", bounce: 1 }]);
});

test("retry_higher_tier is refused the second time for the same job, and escalates again", () => {
  // mutation: never add to ctx.tierUsed → the second decision starts a third implement job
  const [h, esc] = CASES.failed_twice();
  h.architect("failed_twice", "retry_higher_tier", at(esc));
  h.failed("implement", 1);
  const [again] = h.failed("implement", 1);
  assert.equal(again.case, "failed_twice");
  assert.notEqual(again.job, esc.job);
  assert.deepEqual(h.architect("failed_twice", "retry_higher_tier", at(again), "again", "c2"), [
    ruling("again", "c2"),
    { type: "log", kind: "refused", text: "retry_higher_tier refused: already used for implement 1", task: 1 },
    { type: "escalate", case: "failed_twice", job: again.job, task: 1 },
  ]);
});

test("retry_higher_tier is refused when there is no higher tier or no job", () => {
  // mutation: drop the `!up` test → a start_job with tier undefined
  const h = harness(plan("frontier"));
  h.start();
  const [esc] = h.done("implement", 1, { status: "blocked", commits: [], concerns: [] });
  assert.deepEqual(h.architect("blocked", "retry_higher_tier", at(esc)), [
    ruling("the ruling", "the cost"),
    { type: "log", kind: "refused", text: "retry_higher_tier refused: no tier above frontier", task: 1 },
    esc,
  ]);
  const [m, red] = CASES.tests_red_after_merge();
  assert.deepEqual(m.architect("tests_red_after_merge", "retry_higher_tier", at(red)), [
    ruling("the ruling", "the cost"),
    { type: "log", kind: "refused", text: "retry_higher_tier refused: no job to re-run" },
    red,
  ]);
});

test("architect park parks the spec with the ruling as the question", () => {
  for (const [name, mk] of Object.entries(CASES)) {
    const [h, esc] = mk();
    const recommend = { option: "fail", why: "the plan is wrong", confidence: "high" };
    assert.deepEqual(h.feed("architect_decision", { case: name, decision: "park", ruling: "should we drop task 1?", cost_if_wrong: "a day", recommend, ...at(esc) }), [
      ruling("should we drop task 1?", "a day"),
      { type: "park", question: "should we drop task 1?", step: `architect:${name}:${esc.task || ""}:${esc.job || ""}`, kind: "architect_park", recommendation: recommend },
    ], name);
  }
});

test("architect fail_spec ends the spec as failed with the ruling", () => {
  for (const [name, mk] of Object.entries(CASES)) {
    const [h, esc] = mk();
    assert.deepEqual(h.architect(name, "fail_spec", at(esc), "cannot be built", "the spec"), [
      ruling("cannot be built", "the spec"),
      { type: "set_state", state: "done", outcome: "failed — cannot be built" },
    ], name);
  }
});

test("a signal on an architect park: approve goes on as proceed would, deny and fail end the spec", () => {
  // mutation: ignore `signal` events → all three return []
  const parked = () => {
    const [h, esc] = CASES.fix_rounds_exhausted();
    const [, park] = h.architect("fix_rounds_exhausted", "park", at(esc), "accept the two findings?", "rework");
    return [h, park.step];
  };
  let [h, step] = parked();
  assert.deepEqual(h.feed("signal", { answer: "approve", note: null, step }),
    [deferred("parked (fix_rounds_exhausted): second", 1), deferred("parked (fix_rounds_exhausted): third", 1), implement(2, "standard")]);
  [h, step] = parked();
  assert.deepEqual(h.feed("signal", { answer: "deny", note: null, step }),
    [{ type: "set_state", state: "done", outcome: "denied: accept the two findings?" }]);
  [h, step] = parked();
  assert.deepEqual(h.feed("signal", { answer: "fail", note: "not worth it", step }),
    [{ type: "set_state", state: "done", outcome: "failed — not worth it" }]);
  [h] = parked();
  assert.deepEqual(h.feed("signal", { answer: "approve", note: null, step: "permission prompt" }), [], "a wait the strategy did not open");
});

test("an architect decision resets the counters of its task", () => {
  // mutation: keep t.reds after `proceed` → the red after the review escalates at once
  const [h, esc] = CASES.verify_red();
  h.architect("verify_red", "proceed", at(esc));
  h.done("review", 1, findings(F("important", 1)));
  h.done("fix", 1);
  assert.equal(h.check(1, false)[0].bounce, 1);
});

// ---- contract ------------------------------------------------------------------------------------------------------

test("purity: frozen input, equal output on a second call, no module state between specs", () => {
  // mutation: cache the model on the function (`decide.c = decide.c || newModel(state)`) → the calls differ;
  // mutation: write `ctx.state.spec.x = 1` in onArchitect → the frozen call throws
  const [h] = CASES.fix_rounds_exhausted();
  const state = h.state();
  const event = { seq: 999, ts: 1, spec: "s", job: null, kind: "architect_decision",
    detail: { rows: [], case: "fix_rounds_exhausted", task: 1, job: h.last("fix", 1).id, decision: "proceed", ruling: "r", cost_if_wrong: "c" } };
  const a = decide(deepFreeze(clone(state)), deepFreeze(clone(event)));
  const other = harness(plan("mechanical", "mechanical"));
  other.start();
  other.green(1);
  const b = decide(deepFreeze(clone(state)), deepFreeze(clone(event)));
  assert.deepEqual(a, b);
  assert.equal(a.length, 4);
  // the frozen copies are really frozen: a write must throw, so a strategy that wrote would have thrown above
  const frozen = deepFreeze(clone(state));
  assert.throws(() => { frozen.events.push(1); }, TypeError);
  assert.throws(() => { frozen.tasks[0].tier = "x"; }, TypeError);
});

test("the event being decided is not counted twice when state.events already holds it", () => {
  // mutation: drop the `row.seq === cur.seq` skip → the first red is counted twice (bounce 2)
  const h = harness(plan("standard"));
  h.start();
  h.done("implement", 1);
  const event = { seq: 50, ts: 50, spec: "s", job: null, kind: "check_result", detail: { rows: [], task: 1, ok: false, text: "red" } };
  const state = h.state();
  const [cmd] = decide({ ...state, events: [...state.events, event] }, event);
  assert.equal(cmd.bounce, 1);
});

test("events of other kinds and a flat event are handled: unknown is [], flat reads like a row", () => {
  const h = harness(plan("standard"));
  h.start();
  assert.deepEqual(h.feed("job_started", { job: "x" }), []);
  assert.deepEqual(h.feed("ruling", { text: "x" }), []);
  const flat = { type: "job_done", job: h.last("implement", 1).id, kind: "implement", task: 1, status: DONE };
  assert.deepEqual(decide(h.state(), flat), [runCheck(1)]);
});

test("every command is one of the contract's types", () => {
  const types = new Set(["start_job", "run_check", "record_ruling", "park", "escalate", "set_state", "request_integrate", "log"]);
  const kinds = new Set(["refresh", "implement", "review", "fix", "final_review", "fix_wave", "re_review"]);
  for (const [name, mk] of Object.entries(CASES)) {
    const [h, esc] = mk();
    const cmds = [esc, ...h.architect(name, "proceed", at(esc))];
    for (const c of cmds) {
      assert.ok(types.has(c.type), `${name}: ${c.type}`);
      if (c.type === "start_job") assert.ok(kinds.has(c.kind) && strategy.TIERS.includes(c.tier), JSON.stringify(c));
      for (const v of Object.values(c)) assert.notEqual(v, undefined, `no undefined field in ${JSON.stringify(c)}`);
    }
  }
});

test("BOUNCE_MAX_LINES lives in the strategy; bounce.js re-exports it without a require cycle", () => {
  // mutation: define a second constant in bounce.js with another value → the equality fails
  assert.equal(strategy.BOUNCE_MAX_LINES, 60);
  assert.equal(bounce.BOUNCE_MAX_LINES, strategy.BOUNCE_MAX_LINES);
  const dir = path.join(__dirname, "..", "lib", "engine");
  assert.match(fs.readFileSync(path.join(dir, "bounce.js"), "utf8"), /require\("\.\/strategy\/spec_driven"\)/);
  assert.doesNotMatch(fs.readFileSync(path.join(dir, "bounce.js"), "utf8"), /BOUNCE_MAX_LINES\s*=\s*\d/);
  assert.doesNotMatch(fs.readFileSync(path.join(dir, "strategy", "spec_driven.js"), "utf8"), /require\(/, "the strategy requires nothing");
  // 61 failing lines in, at most 60 lines out
  const out = bounce.text(Array.from({ length: 80 }, (_, i) => `not ok ${i}`).join("\n"), "/log").text.split("\n");
  assert.equal(out.length, 60);
});
