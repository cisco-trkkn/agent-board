"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const core = require("../lib/engine/core");
const architect = require("../lib/engine/architect");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const paths = require("../lib/engine/paths");
const policy = require("../lib/engine/policy");
const rebuild = require("../lib/engine/rebuild");

const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const NOISE = /^(inbox_|timer_fired$|deadline$|step_|job_session$)/;

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = report({ status: "blocked", commits: [], concerns: ["needs a secret"] });
const PASS = report({ verdict: "pass", findings: [] });
const FINDINGS = (task, severity = "important") => report({ verdict: "findings", findings: [{ severity, task, text: `wrong in ${task}` }] });
const DECIDE = (decision) => report({ decision, ruling: `ruling ${decision}`, cost_if_wrong: `cost of ${decision}` });
const worker = (text) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }];

const task = (subject, meta = {}) => ({
  subject,
  description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"], ...meta })}\n\`\`\``,
});

// The fake backend plus two test seams: raw events pushed by the test, and scripted reports for resumed sessions
// (fake.resume plays no script: the report path is read from the brief text, as a worker would).
function wrap(inner, clock) {
  const extra = [];
  const w = {
    calls: inner.calls,
    resumeReports: [],
    start: (job) => inner.start(job),
    close: (h) => inner.close(h),
    async resume(h, text) {
      const nh = await inner.resume(h, text);
      const m = /Report file: (\S+)/.exec(text);
      const rep = w.resumeReports.shift();
      if (m && rep) {
        extra.push({ due: clock.t + 1, make: () => {
          fs.mkdirSync(path.dirname(m[1]), { recursive: true });
          fs.writeFileSync(m[1], rep);
          return { handle: nh, type: "status", state: "ready", updatedAt: clock.t, tool: null, lastToolAt: null, turnStartedAt: clock.t };
        } });
      }
      return nh;
    },
    push: (ev) => extra.push({ due: clock.t, make: () => ev }),
    poll() {
      const out = inner.poll();
      const due = extra.filter((e) => e.due <= clock.t);
      for (const e of due) extra.splice(extra.indexOf(e), 1);
      return out.concat(due.map((e) => e.make()));
    },
  };
  return w;
}

function mk(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "ecore-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  fs.writeFileSync(path.join(wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: o.tasks || [task("T1")] }));
  fs.writeFileSync(path.join(wt, SPEC), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n\n## Design\n\nbody\n");
  if (o.config) fs.writeFileSync(path.join(wt, "docs/superpowers/engine.json"), JSON.stringify(o.config));
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, `#!/bin/sh\necho "$@" >> "${env.root}/ctl.log"\necho ${o.stale ? "stale" : "fresh"}\nexit ${o.stale ? 1 : 0}\n`, { mode: 0o755 });
  const clock = { t: 1000 };
  const script = o.script || {};
  const backend = wrap(fake.createBackend({ script, now: () => clock.t }), clock);
  const tells = [];
  const notes = [];
  const integrations = [];
  const finals = [];
  const reverts = [];
  const eng = core.start({
    project: o.project || "demo", repo: wt, backend, now: () => clock.t, tmuxCtl: ctl,
    integrate: o.integrate || (async (spec) => { integrations.push(spec.id); return { outcome: "merged" }; }),
    revert: o.revert || (async (spec) => { reverts.push(spec.id); }),
    finalize: o.finalize || (async (spec, outcome) => { finals.push(outcome); }), strategy: o.strategy,
    tell: (handle, text) => tells.push({ window: handle.window, text }),
    notify: (text) => notes.push(text),
    transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const h = {
    env, wt, clock, script, backend, tells, notes, integrations, finals, reverts, eng, db: eng.db,
    add: (extra = {}) => eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1", ...extra }),
    async step(n = 1, dt = 5) { for (let i = 0; i < n; i++) { clock.t += dt; await eng.tick(); } },
    async until(pred, max = 400) {
      for (let i = 0; i < max; i++) { if (pred()) return; clock.t += 5; await eng.tick(); }
      assert.fail(`not reached after ${max} ticks; events: ${h.kinds().join(" ")}`);
    },
    events: () => eng.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    kinds: () => h.events().map((e) => e.kind).filter((k) => !NOISE.test(k)),
    of: (kind) => h.events().filter((e) => e.kind === kind),
    spec: () => eng.db.prepare("SELECT * FROM specs WHERE id=?").get(SPEC),
    jobs: () => eng.db.prepare("SELECT * FROM jobs ORDER BY rowid").all(),
    job: (id) => eng.db.prepare("SELECT * FROM jobs WHERE id=?").get(id),
    wait: () => inbox.openWaitFor(eng.db, SPEC),
    signal: (answer, note) => assert.equal(inbox.signal(eng.db, SPEC, answer, note, clock.t).rc, 0),
    feed: () => fs.readFileSync(paths.feedPath(o.project || "demo"), "utf8").trim().split("\n").map((l) => JSON.parse(l)),
    done: () => (h.spec() || {}).state === "done",
  };
  t.after(() => { eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

const status = (handle, state, clock, extra = {}) =>
  ({ handle, type: "status", state, updatedAt: clock.t, tool: null, lastToolAt: null, turnStartedAt: clock.t, ...extra });
const handleOf = (h, id) => { const j = h.job(id); return { job: j.id, window: j.window, pane: j.pane }; };

// ---- the whole run -----------------------------------------------------------------------------------------

test("three-task plan runs from spec_started to done: outcome from integrate, every window closed, event sequence", async (t) => {
  const script = { final_review: worker(PASS) };
  for (const n of [1, 2, 3]) { script[`implement${n}`] = worker(DONE); script[`review${n}`] = worker(PASS); }
  const h = mk(t, { tasks: [task("T1"), task("T2"), task("T3")], script });
  h.add();
  await h.until(h.done);
  assert.equal(h.spec().outcome, "merged");
  assert.deepEqual(h.integrations, [SPEC]);
  const perTask = ["job_created", "dispatched", "job_done", "check_requested", "check_result", "green_check",
    "job_created", "dispatched", "job_done", "review", "task_complete"];
  assert.deepEqual(h.kinds(), [
    "spec_added", "spec_started", "check_requested", "stale_result",
    ...perTask, ...perTask, ...perTask,
    "spec_state", "job_created", "dispatched", "job_done",
    "spec_state", "integrate_requested", "integrated", "spec_done",
  ]);
  const ids = h.jobs().map((j) => j.id);
  assert.deepEqual(ids, ["demo:implement1:1", "demo:review1:1", "demo:implement2:1", "demo:review2:1",
    "demo:implement3:1", "demo:review3:1", "demo:final_review:1"]);
  const started = h.backend.calls.filter((c) => c.method === "start").map((c) => c.job.id);
  const closed = h.backend.calls.filter((c) => c.method === "close").map((c) => c.handle.job);
  assert.deepEqual(started, ids);
  assert.deepEqual(closed, ids);
  for (const j of h.jobs()) {
    assert.equal(j.state, "done");
    assert.equal(j.tools, "all");
    assert.equal(j.mcp, "all");
    assert.ok(fs.readFileSync(j.brief, "utf8").includes(`Report file: ${j.report}`));
  }
  // the job handed to the backend carries what the contract needs
  const first = h.backend.calls[0].job;
  for (const k of ["id", "kind", "model", "effort", "brief", "report", "worktree"]) assert.ok(first[k], k);
  assert.equal(first.model, "sonnet");
  assert.equal(h.job("demo:final_review:1").tier, "frontier");
  // every event reached the feed, in order, and the tables replay from the events
  assert.equal(h.feed().length, h.events().length);
  assert.deepEqual(h.feed().map((l) => l.kind), h.events().map((e) => e.kind));
  assert.deepEqual(rebuild.check("demo").diffs, []);
  // retry_policies rows were written through events
  assert.equal(h.db.prepare("SELECT max_attempts FROM retry_policies WHERE kind='bounce'").get().max_attempts, 3);
});

test("a stale manifest starts a refresh job first", async (t) => {
  const h = mk(t, { stale: true, script: { refresh: worker(DONE), implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  h.add();
  await h.until(h.done);
  assert.equal(h.of("stale_result")[0].detail.stale, true);
  assert.equal(h.jobs()[0].id, "demo:refresh:1");
  assert.match(fs.readFileSync(path.join(h.env.root, "ctl.log"), "utf8"), /^registry stale docs\/superpowers\/specs\/2026-01-01-demo-design\.md$/m);
});

// ---- finish rules (spec section 2) ---------------------------------------------------------------------------

test("finish: ready with a valid report is done and the window is closed by the pane the engine started", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE) } });
  h.add();
  await h.until(() => h.of("job_done").length === 1);
  const j = h.job("demo:implement1:1");
  assert.equal(j.state, "done");
  await h.step();
  const close = h.backend.calls.find((c) => c.method === "close");
  assert.equal(close.handle.pane, j.pane);
  assert.equal(h.db.prepare("SELECT state FROM steps WHERE key='close_window:demo:implement1:1'").get().state, "done");
  assert.equal(h.tells.length, 0);
  const end = h.of("job_done")[0].detail;
  assert.equal(end.context_tokens, null);
  assert.match(end.context_missing, /no transcript/);
});

test("finish: ready without a report is told the report path once; a second ready fails the attempt", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "busy", at: 1 }, { status: "ready", at: 2 }, { status: "busy", at: 11 }, { status: "ready", at: 12 }] } });
  h.add();
  await h.until(() => h.tells.length === 1);
  const j = h.job("demo:implement1:1");
  assert.equal(j.state, "running");
  assert.ok(h.tells[0].text.includes(j.report));
  assert.equal(h.tells[0].window, j.window);
  await h.until(() => h.of("job_failed").length === 1);
  assert.equal(h.of("job_failed")[0].detail.reason, "no_report");
  assert.equal(h.tells.length, 1);
  assert.equal(h.job("demo:implement1:1").state, "failed");
});

test("finish: a window gone without a report fails the attempt; gone with a valid report is done", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 2 }] } });
  h.add();
  await h.until(() => h.of("job_failed").length === 1);
  assert.equal(h.of("job_failed")[0].detail.reason, "gone");
  h.script.implement1 = [{ report: DONE, at: 1 }, { gone: true, at: 2 }];
  await h.until(() => h.of("job_done").length === 1);
  assert.equal(h.of("job_done")[0].job, "demo:implement1:2");
});

// ---- timeouts (spec 10.1) ------------------------------------------------------------------------------------
// Mutations run for these guards (each made the named test fail; see the task report):
//   HEARTBEAT_S 120 -> 1200            fails "heartbeat_timeout"
//   NUDGE_GRACE_S 300 -> 3000          fails "no_progress"
//   TOOL_LIMIT_S.Bash 900 -> 9000      fails "tool_timeout"
//   job deadline ignores timeout_min   fails "job_timeout"
//   needs-you guard removed in evaluate fails "no clock runs while needs-you"
// Further mutations (pump ordering, one open wait, one row per state change, the retry and limit guards) are in the report.

const firstFail = (h) => h.of("job_failed")[0];

test("heartbeat_timeout: no status for 2 minutes after the start fails the attempt, not before", async (t) => {
  const h = mk(t, { script: { implement1: [] } });
  h.add();
  await h.until(() => h.job("demo:implement1:1") && h.job("demo:implement1:1").state === "running");
  const t0 = h.job("demo:implement1:1").started_at;
  await h.until(() => h.clock.t >= t0 + 115);
  assert.equal(h.of("job_failed").length, 0);
  await h.step(2);
  assert.equal(firstFail(h).detail.reason, "heartbeat_timeout");
  assert.ok(firstFail(h).ts >= t0 + 120 && firstFail(h).ts <= t0 + 125);
  // the deadline is a timers row
  assert.ok(h.db.prepare("SELECT COUNT(*) AS n FROM timers WHERE kind='deadline' AND job='demo:implement1:1'").get().n >= 1);
});

// A worker that keeps its heartbeat fresh: one status per tick, built by `shape`.
async function beat(h, id, seconds, shape) {
  const end = h.clock.t + seconds;
  while (h.clock.t < end && h.job(id).state === "running") {
    h.backend.push(status(handleOf(h, id), "busy", h.clock, shape()));
    await h.step();
  }
}

test("no_progress: busy with no tool for 15 minutes is nudged once, then fails 5 minutes later", async (t) => {
  const h = mk(t, { script: { implement1: [] } });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  const t0 = h.job(id).started_at;
  const hung = () => ({ tool: null, lastToolAt: null, turnStartedAt: t0 });
  await beat(h, id, 890, hung);
  assert.equal(h.tells.length, 0);
  await beat(h, id, 30, hung);
  assert.equal(h.tells.length, 1);
  assert.ok(h.tells[0].text.includes(h.job(id).report));
  assert.equal(h.of("job_failed").length, 0);
  await beat(h, id, 270, hung);
  assert.equal(h.of("job_failed").length, 0);
  await beat(h, id, 40, hung);
  assert.equal(firstFail(h).detail.reason, "no_progress");
  assert.equal(h.tells.length, 1);
});

test("tool_timeout: a Bash call running 15 minutes fails the attempt", async (t) => {
  const h = mk(t, { script: { implement1: [] } });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  const t0 = h.clock.t;
  const bash = () => ({ tool: "Bash", lastToolAt: t0, turnStartedAt: t0 });
  await beat(h, id, 890, bash);
  assert.equal(h.of("job_failed").length, 0);
  await beat(h, id, 30, bash);
  assert.equal(firstFail(h).detail.reason, "tool_timeout");
  assert.equal(h.tells.length, 0);
  // ~180 heartbeats in one state are one worker row (spec section 12: one row per change of state)
  assert.equal(h.db.prepare("SELECT COUNT(*) AS n FROM inbox WHERE source='worker'").get().n, 1);
});

test("job_timeout: the kind's timeout_min from engine.json ends a live, progressing job", async (t) => {
  const h = mk(t, { script: { implement1: [] }, config: { retry: { implement: { timeout_min: 3 } } } });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  const t0 = h.job(id).started_at;
  const live = () => ({ tool: "Read", lastToolAt: h.clock.t, turnStartedAt: h.clock.t });
  await beat(h, id, 170, live);
  assert.equal(h.of("job_failed").length, 0);
  await beat(h, id, 30, live);
  assert.equal(firstFail(h).detail.reason, "job_timeout");
  assert.ok(firstFail(h).ts >= t0 + 180);
});

test("no clock runs while needs-you: parks after 10 minutes, un-parks without a signal when the worker is busy again", async (t) => {
  const h = mk(t, { script: { implement1: [] }, config: { retry: { implement: { timeout_min: 3 } } } });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  h.backend.push(status(handleOf(h, id), "needs-you", h.clock));
  await h.step();
  assert.ok(h.job(id).needs_you_since);
  const since = h.job(id).needs_you_since;
  // silent for 9.5 minutes: past the heartbeat (2 min) and the job timeout (3 min), nothing fires
  await h.until(() => h.clock.t >= since + 590);
  assert.equal(h.of("job_failed").length, 0);
  assert.equal(h.spec().state, "running");
  await h.step(3);
  assert.equal(h.spec().state, "awaiting_you");
  assert.equal(h.wait().question, `permission prompt in ${h.job(id).window}`);
  await h.step(60); // still parked, still no timeout
  assert.equal(h.of("job_failed").length, 0);
  assert.equal(h.backend.calls.filter((c) => c.method === "close").length, 0);
  // the user answers the prompt in the window: the worker goes busy
  h.backend.push(status(handleOf(h, id), "busy", h.clock, { tool: "Read", lastToolAt: h.clock.t }));
  await h.step();
  assert.equal(h.spec().state, "running");
  assert.equal(h.wait(), null);
  assert.equal(h.of("signal").length, 0);
  const j = h.job(id);
  assert.equal(j.needs_you_since, null);
  assert.ok(j.needs_you_total >= 900);
  assert.equal(j.state, "running");
  // its time there is subtracted: the 3-minute job timeout has not fired although wall time is far past it
  await beat(h, id, 20, () => ({ tool: "Read", lastToolAt: h.clock.t, turnStartedAt: h.clock.t }));
  assert.equal(h.of("job_failed").length, 0);
});

// ---- retry policies (spec 10.2) ------------------------------------------------------------------------------

test("retry: attempts and the backoff timer come from engine.json; the job waits in backoff", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }] },
    config: { retry: { implement: { max_attempts: 3, backoff_s: [40, 70], on_exhausted: "park" } } } });
  h.add();
  await h.until(() => h.of("job_failed").length === 1);
  const failedAt = h.of("job_failed")[0].ts;
  const second = h.job("demo:implement1:2");
  assert.equal(second.state, "backoff");
  const timer = h.db.prepare("SELECT * FROM timers WHERE kind='retry' AND job=?").get(second.id);
  assert.equal(timer.due_at, failedAt + 40);
  await h.until(() => h.clock.t >= failedAt + 35);
  assert.equal(h.job(second.id).state, "backoff");
  await h.until(() => h.of("job_failed").length === 2);
  assert.ok(h.job(second.id).started_at >= failedAt + 40);
  const third = h.db.prepare("SELECT * FROM timers WHERE kind='retry' AND job='demo:implement1:3'").get();
  assert.equal(third.due_at, h.of("job_failed")[1].ts + 70);
  // on_exhausted: park
  await h.until(() => h.of("job_failed").length === 3);
  await h.step();
  assert.equal(h.job("demo:implement1:4"), undefined);
  assert.equal(h.spec().state, "awaiting_you");
  assert.match(h.wait().question, /implement1 failed: gone/);
  // approve runs it once more
  h.script.implement1 = worker(DONE);
  h.signal("approve");
  await h.until(() => h.of("job_done").length === 1);
  assert.equal(h.of("job_done")[0].job, "demo:implement1:4");
});

test("retry: on_exhausted architect escalates failed_twice after the default two attempts", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }], architect: worker(DECIDE("fail_spec")) } });
  h.add();
  await h.until(h.done);
  assert.equal(h.of("job_failed").length, 2);
  assert.equal(h.of("escalated")[0].detail.case, "failed_twice");
  assert.equal(h.spec().outcome, "failed — ruling fail_spec");
});

test("retry: on_exhausted fail_spec fails the spec", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }] },
    config: { retry: { implement: { max_attempts: 1, on_exhausted: "fail_spec" } } } });
  h.add();
  await h.until(h.done);
  assert.equal(h.of("job_failed").length, 1);
  assert.equal(h.spec().outcome, "failed — implement1: gone");
  assert.equal(h.of("fail_spec").length, 1);
  assert.equal(h.feed().find((l) => l.kind === "fail_spec").tier, "critical");
});

test("retry: no_retry_on blocked goes straight to on_exhausted, with no second attempt", async (t) => {
  // default policy: blocked is in no_retry_on, on_exhausted architect
  const a = mk(t, { script: { implement1: worker(BLOCKED), architect: worker(DECIDE("fail_spec")) } });
  a.add();
  await a.until(a.done);
  assert.equal(a.of("escalated")[0].detail.case, "blocked");
  assert.equal(a.jobs().filter((j) => j.kind === "implement").length, 1);
  // on_exhausted park
  const b = mk(t, { project: "demo2", script: { implement1: worker(BLOCKED) }, config: { retry: { implement: { on_exhausted: "park" } } } });
  b.add();
  await b.until(() => b.spec().state === "awaiting_you");
  assert.match(b.wait().question, /implement1 failed: blocked/);
  assert.equal(b.jobs().length, 1);
  assert.equal(b.of("job_failed")[0].detail.reason, "blocked");
  // blocked taken out of no_retry_on: it is retried like any failure
  const c = mk(t, { project: "demo3", script: { implement1: worker(BLOCKED) }, config: { retry: { implement: { no_retry_on: [], backoff_s: [0] } } } });
  c.add();
  await c.until(() => c.jobs().filter((j) => j.kind === "implement").length === 2);
  assert.equal(c.of("job_failed")[0].detail.reason, "blocked");
});

// ---- the architect (spec section 4) --------------------------------------------------------------------------

const RED = { verifyCommand: "echo 'not ok 1 - boom'; exit 1" };
const CASE_RUNS = {
  blocked: { decision: "fail_spec", script: { implement1: worker(BLOCKED) } },
  failed_twice: { decision: "park", script: { implement1: [{ gone: true, at: 1 }] } },
  verify_red: { decision: "proceed", tasks: [task("T1", RED)], script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) },
    resumes: [DONE, DONE] },
  fix_rounds_exhausted: { decision: "proceed", config: { retry: { fix_round: { max_attempts: 1 } } },
    script: { implement1: worker(DONE), review1: worker(FINDINGS(1)), final_review: worker(PASS) }, resumes: [DONE] },
  residual_findings: { decision: "retry_higher_tier",
    script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(FINDINGS(1)), fix_wave: worker(DONE), re_review: worker(FINDINGS(1)) } },
  tests_red_after_merge: { decision: "fail_spec", script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) },
    integrate: async () => ({ outcome: "tests_red", merge: "abc" }) },
};

for (const [kase, run] of Object.entries(CASE_RUNS)) {
  test(`architect: ${kase} starts one frontier architect job with a case file; ${run.decision} is fed back and recorded as a ruling`, async (t) => {
    const calls = [];
    const h = mk(t, { tasks: run.tasks, config: run.config, integrate: run.integrate,
      script: { ...run.script, architect: worker(DECIDE(run.decision)) },
      revert: async (spec) => { calls.push(["revert", spec.id]); return { outcome: "reverted" }; },
      finalize: async (spec, outcome) => { calls.push(["finalize", outcome]); } });
    h.backend.resumeReports.push(...(run.resumes || []));
    h.add();
    await h.until(() => h.of("architect_decision").length === 1);
    assert.equal(h.of("escalated").length, 1);
    assert.equal(h.of("escalated")[0].detail.case, kase);
    const arch = h.jobs().filter((j) => j.kind === "architect");
    assert.equal(arch.length, 1);
    assert.equal(arch[0].tier, "frontier");
    assert.equal(arch[0].model, "fable");
    const file = fs.readFileSync(arch[0].brief, "utf8");
    assert.ok(file.startsWith(`# Architect case: ${kase}`));
    for (const head of ["## Task or finding", "## Report", "## Review", "## Spec decisions", "## Events so far", "## Your answer"]) assert.ok(file.includes(head), head);
    assert.ok(file.includes("D1: keep it small."));
    assert.ok(/\d+ spec_started/.test(file));
    assert.ok(file.includes(`Report file: ${arch[0].report}`));
    const dec = h.of("architect_decision")[0].detail;
    assert.equal(dec.case, kase);
    assert.equal(dec.decision, run.decision);
    assert.equal(dec.cost_if_wrong, `cost of ${run.decision}`);
    await h.step(2);
    const ruling = h.of("ruling").find((e) => e.detail.by === "architect");
    assert.equal(ruling.detail.text, `ruling ${run.decision}`);
    assert.equal(ruling.detail.cost_if_wrong, `cost of ${run.decision}`);
    if (run.decision === "park") {
      assert.equal(h.spec().state, "awaiting_you");
      assert.equal(h.wait().question, "ruling park");
      return;
    }
    if (kase === "residual_findings") { // the fix wave runs again one tier up
      await h.until(() => h.jobs().filter((j) => j.kind === "fix_wave").length === 2);
      assert.equal(h.jobs().filter((j) => j.kind === "fix_wave")[1].tier, "frontier");
      return;
    }
    await h.until(h.done);
    if (run.decision === "proceed") assert.equal(h.spec().outcome, "merged");
    if (run.decision === "fail_spec") assert.equal(h.spec().outcome, "failed — ruling fail_spec");
    if (kase === "tests_red_after_merge") assert.deepEqual(calls, [["revert", SPEC], ["finalize", "failed — ruling fail_spec"]]);
    if (kase === "verify_red") {
      const reds = h.of("check_result").filter((e) => !e.detail.ok);
      assert.equal(reds.length, 3);
      assert.ok(reds[0].detail.bounce_bytes > 0);
      assert.ok(reds[0].detail.text.includes("not ok 1 - boom"));
      assert.ok(file.includes("not ok 1 - boom"));
      assert.equal(h.backend.calls.filter((c) => c.method === "resume").length, 2);
    }
  });
}

test("architect: proceed after tests red after the merge finalizes, then ends the spec with the strategy's outcome", async (t) => {
  const calls = [];
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS), architect: worker(DECIDE("proceed")) },
    integrate: async () => ({ outcome: "tests_red", merge: "abc" }),
    revert: async () => { calls.push("revert"); }, finalize: async (spec, outcome) => { calls.push(`finalize ${outcome}`); } });
  h.add();
  await h.until(h.done);
  assert.equal(h.spec().outcome, "tests_red — proceed: ruling proceed");
  assert.deepEqual(calls, ["finalize tests_red — proceed: ruling proceed"]);
});

test("architect: a refused retry_higher_tier goes back with the refusal in the case file; a second refusal parks", async (t) => {
  // a frontier task cannot go a tier up, so every retry_higher_tier is refused
  const h = mk(t, { tasks: [task("T1", { modelTier: "frontier" })], script: { implement1: worker(BLOCKED), architect: worker(DECIDE("retry_higher_tier")) } });
  h.add();
  await h.until(() => h.spec().state === "awaiting_you");
  const arch = h.jobs().filter((j) => j.kind === "architect");
  assert.equal(arch.length, 2);
  assert.ok(!fs.readFileSync(arch[0].brief, "utf8").includes("was refused"));
  assert.match(fs.readFileSync(arch[1].brief, "utf8"), /Your earlier answer was refused \(retry_higher_tier refused: no tier above frontier\)/);
  assert.equal(h.wait().question, "retry_higher_tier refused twice for demo:implement1:1");
  assert.equal(h.of("refused").length, 2);
});

test("architect.build: the case file holds the finding, report, review, decisions and events, and the refusal when given", () => {
  const text = architect.build({ kase: "blocked", spec: "s.md", job: "j:implement1:1", task: 1, finding: "F", report: "R", review: "",
    decisions: architect.decisions("# S\n\n## Decisions\n\n- one\n- two\n\n## Next\n\nx\n"),
    events: [{ seq: 1, kind: "spec_started", job: null, detail: "{}" }, { seq: 2, kind: "timer_fired", detail: "{}" },
      { seq: 3, kind: "job_failed", job: "j", detail: JSON.stringify({ reason: "gone" }) }], reportPath: "/tmp/r.md" });
  assert.match(text, /## Task or finding\n\nF\n/);
  assert.match(text, /## Report\n\nR\n/);
  assert.match(text, /## Review\n\n\(none\)\n/);
  assert.match(text, /## Spec decisions\n\n- one\n- two\n/);
  assert.match(text, /## Events so far\n\n1 spec_started\n3 job_failed j reason=gone\n/);
  assert.ok(!text.includes("timer_fired"));
  assert.ok(!text.includes("## Next"));
  assert.deepEqual(architect.CASES, require("../lib/engine/strategy/spec_driven").CASES);
});

// ---- parking and signals (spec 10.3) ---------------------------------------------------------------------------

// A strategy that parks on a stop-class step (a push to a shared branch), as spec section 4 requires of one.
const stopClass = {
  decide(state, event) {
    const e = event.detail && typeof event.detail === "object" ? { name: event.kind, ...event.detail } : event;
    if (e.name === "spec_started") return [{ type: "park", question: "push to the shared branch release", step: "push" }];
    if (e.name === "signal" && e.step === "push") {
      if (e.answer === "approve") return [{ type: "set_state", state: "done", outcome: "pushed" }];
      if (e.answer === "deny") return [{ type: "set_state", state: "done", outcome: "kept (push skipped)" }];
      return [{ type: "set_state", state: "done", outcome: `failed — ${e.note}` }];
    }
    return [];
  },
};

for (const [answer, outcome] of [["approve", "pushed"], ["deny", "kept (push skipped)"], ["fail", "failed — not tonight"]]) {
  test(`parking: a stop-class case parks the spec; ${answer} is applied on the next tick as a user ruling`, async (t) => {
    const h = mk(t, { strategy: stopClass });
    h.add();
    await h.step(2);
    assert.equal(h.spec().state, "awaiting_you");
    assert.equal(h.db.prepare("SELECT COUNT(*) AS n FROM waits WHERE answered_at IS NULL").get().n, 1);
    assert.equal(h.wait().question, "push to the shared branch release");
    assert.equal(h.wait().step, "push");
    const line = h.feed().find((l) => l.kind === "awaiting_you");
    assert.equal(line.tier, "decision");
    assert.ok(line.text.includes("push to the shared branch release"));
    assert.ok(line.text.includes(`tmux-ctl engine signal ${SPEC} approve|deny|fail`));
    h.signal(answer, answer === "fail" ? "not tonight" : undefined);
    await h.step();
    assert.equal(h.spec().state, "done");
    assert.equal(h.spec().outcome, outcome);
    assert.equal(h.wait(), null);
    const rulings = h.of("ruling");
    assert.equal(rulings.length, 1);
    assert.equal(rulings[0].detail.by, "user");
    assert.ok(rulings[0].detail.text.startsWith(answer));
    assert.equal(h.of("signal")[0].detail.step, "push");
    assert.equal(h.of("spec_done").length + h.of("fail_spec").length, 1); // one set_state done, the strategy's
  });
}

const GATED = () => [task("T1", { userGate: true })];

test("parking: a user-gate task parks before its job; approve resumes at the stored step", async (t) => {
  const h = mk(t, { tasks: GATED(), script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  h.add();
  await h.step(3);
  assert.equal(h.spec().state, "awaiting_you");
  assert.equal(h.wait().question, "user gate: task 1 T1");
  assert.equal(h.jobs().length, 0);
  assert.equal(h.feed().find((l) => l.kind === "awaiting_you").tier, "decision");
  h.signal("approve");
  await h.step();
  assert.equal(h.spec().state, "running");
  assert.equal(h.jobs()[0].id, "demo:implement1:1");
  await h.until(h.done);
  assert.equal(h.spec().outcome, "merged");
  assert.equal(h.of("ruling").filter((e) => e.detail.by === "user").length, 1);
});

test("parking: deny on a user gate fails with denied: <question>; fail fails with the note", async (t) => {
  const a = mk(t, { tasks: GATED() });
  a.add();
  await a.until(() => a.spec().state === "awaiting_you");
  a.signal("deny");
  await a.step();
  assert.equal(a.spec().outcome, "denied: user gate: task 1 T1");
  assert.equal(a.jobs().length, 0);
  const b = mk(t, { project: "demo2", tasks: GATED() });
  b.add();
  await b.until(() => b.spec().state === "awaiting_you");
  b.signal("fail", "wrong week");
  await b.step();
  assert.equal(b.spec().outcome, "failed — wrong week");
  assert.equal(b.of("ruling")[0].detail.by, "user");
});

test("parking: under run() the engine keeps ticking until the answer arrives; a signal for a spec that is not waiting is dropped", async (t) => {
  const h = mk(t, { tasks: GATED(), script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  h.add();
  inbox.insert(h.db, { source: "user", source_id: "early", spec: SPEC, kind: "signal", payload: { answer: "approve", note: null } }, h.clock.t);
  let ticksParked = 0;
  const origTick = h.eng.tick;
  h.eng.tick = async () => {
    await origTick();
    if (h.spec().state === "awaiting_you" && ++ticksParked === 4) h.signal("approve");
  };
  const outcome = await h.eng.run(SPEC);
  assert.equal(outcome, "merged");
  assert.ok(ticksParked >= 4);
  const early = h.db.prepare("SELECT state, reason FROM inbox WHERE source_id='early'").get();
  assert.equal(early.state, "dropped");
  assert.match(early.reason, /not waiting/);
});

test("parking: integrate that parks opens a wait; approve runs integrate again", async (t) => {
  let n = 0;
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) },
    integrate: async () => (++n === 1 ? { outcome: "parked", question: "live checkout is mid-change" } : { outcome: "merged" }) });
  h.add();
  await h.until(() => h.spec().state === "awaiting_you");
  assert.equal(h.wait().question, "live checkout is mid-change");
  await h.step(3);
  assert.equal(n, 1);
  h.signal("approve");
  await h.until(h.done);
  assert.equal(n, 2);
  assert.equal(h.spec().outcome, "merged");
});

// ---- policy version (spec 10.5) --------------------------------------------------------------------------------

test("policy: a spec stamped with version 0 parks with the rules-changed question; approve re-stamps and continues", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  h.add();
  await h.step();
  const hash = policy.policyHash(policy.loadConfig(h.wt));
  assert.equal(h.spec().policy_version, policy.POLICY_VERSION);
  assert.equal(h.spec().policy_hash, hash);
  h.db.prepare("UPDATE specs SET policy_version=0 WHERE id=?").run(SPEC);
  await h.step();
  assert.equal(h.spec().state, "awaiting_you");
  assert.equal(h.wait().question, `engine rules changed (0:${hash.slice(0, 8)}→1:${hash.slice(0, 8)}): continue under the new rules?`);
  h.signal("approve");
  await h.step();
  assert.equal(h.spec().policy_version, 1);
  assert.notEqual(h.spec().state, "awaiting_you");
  await h.until(h.done);
  assert.equal(h.spec().outcome, "merged");
});

test("policy: another hash parks too; deny fails the spec with policy changed", async (t) => {
  const h = mk(t, { script: { implement1: [] } });
  h.add();
  await h.step();
  const hash = h.spec().policy_hash;
  h.db.prepare("UPDATE specs SET policy_hash='0123456789abcdef' WHERE id=?").run(SPEC);
  await h.step();
  assert.equal(h.wait().question, `engine rules changed (1:01234567→1:${hash.slice(0, 8)}): continue under the new rules?`);
  h.signal("deny");
  await h.step();
  assert.equal(h.spec().state, "done");
  assert.equal(h.spec().outcome, "failed — policy changed");
});

test("policy: an answer and a finished job drained in one tick are each decided in turn", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  h.add();
  await h.step(); // implement1 is dispatched; its report and ready arrive with the next poll
  assert.equal(h.job("demo:implement1:1").state, "running");
  h.db.prepare("UPDATE specs SET policy_version=0 WHERE id=?").run(SPEC);
  // the answer is already in the inbox when the tick parks the spec, ahead of the worker's rows
  inbox.insert(h.db, { source: "user", source_id: "quick", spec: SPEC, kind: "signal", payload: { answer: "approve", note: null } }, h.clock.t);
  await h.step();
  assert.equal(h.db.prepare("SELECT state FROM inbox WHERE source_id='quick'").get().state, "done");
  assert.equal(h.spec().policy_version, 1);
  assert.equal(h.of("policy_restamped").length, 1);
  assert.equal(h.of("job_done").length, 1);
  assert.equal(h.of("check_result").length, 1); // the job's own commands were applied too
  await h.until(h.done);
  assert.equal(h.spec().outcome, "merged");
  assert.equal(h.of("awaiting_you").length, 1);
});

test("parking: one open wait per spec; a permission prompt waits its turn behind an open question", async (t) => {
  const h = mk(t, { script: { implement1: [] } });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  h.backend.push(status(handleOf(h, id), "needs-you", h.clock));
  await h.step();
  h.db.prepare("UPDATE specs SET policy_version=0 WHERE id=?").run(SPEC);
  await h.step();
  assert.match(h.wait().question, /^engine rules changed/);
  await h.step(130); // 10 minutes of needs-you pass while the policy question is open
  assert.equal(h.db.prepare("SELECT COUNT(*) AS n FROM waits").get().n, 1);
  assert.match(h.wait().question, /^engine rules changed/);
  h.signal("approve");
  await h.step(14);
  assert.equal(h.wait().question, `permission prompt in ${h.job(id).window}`);
  assert.equal(h.db.prepare("SELECT COUNT(*) AS n FROM waits WHERE answered_at IS NULL").get().n, 1);
});

// ---- usage and model limits (Error handling) -------------------------------------------------------------------

test("usage limit: dispatch pauses until the reset time the status-line tap reports, and fires once", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "usage_limit", at: 1 }] } });
  h.add();
  await h.until(() => h.job("demo:implement1:1") && h.job("demo:implement1:1").state === "running");
  const reset = h.clock.t + 1800;
  fs.mkdirSync(path.join(h.env.state, "statusline"), { recursive: true });
  fs.writeFileSync(path.join(h.env.state, "statusline", "old.json"), JSON.stringify({ received_at: 5,
    rate_limits: { five_hour: { used_percentage: 100, resets_at: h.clock.t + 99999 } } }));
  fs.writeFileSync(path.join(h.env.state, "statusline", "new.json"), JSON.stringify({ received_at: h.clock.t,
    rate_limits: { five_hour: { used_percentage: 100, resets_at: reset }, seven_day: { used_percentage: 40, resets_at: reset + 5000 } } }));
  await h.until(() => h.of("job_failed").length === 1);
  assert.equal(h.of("job_failed")[0].detail.reason, "usage_limit");
  const timers = () => h.db.prepare("SELECT * FROM timers WHERE kind='usage_reset'").all();
  assert.equal(timers().length, 1);
  assert.equal(timers()[0].due_at, reset);
  assert.equal(h.job("demo:implement1:2").state, "backoff");
  assert.match(h.notes[0], /^\[Engine\] paused: usage limit until /);
  h.script.implement1 = worker(DONE);
  await h.until(() => h.clock.t >= reset - 10);
  assert.equal(h.backend.calls.filter((c) => c.method === "start").length, 1); // nothing dispatched while paused
  await h.until(() => h.of("job_done").length === 1);
  assert.equal(h.of("job_done")[0].job, "demo:implement1:2");
  assert.ok(h.job("demo:implement1:2").started_at >= reset);
  assert.equal(h.of("usage_resumed").length, 1);
  assert.equal(timers().length, 1);
  // outside the retry count: no escalation, the retry is attempt try 1 again
  assert.equal(h.of("escalated").length, 0);
});

test("usage limit: without a tap reading the timer is one hour out", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "usage_limit", at: 1 }] } });
  h.add();
  await h.until(() => h.of("job_failed").length === 1);
  assert.equal(h.db.prepare("SELECT due_at FROM timers WHERE kind='usage_reset'").get().due_at, h.of("job_failed")[0].ts + 3600);
});

test("usage limit: a tap reading of 100% pauses dispatch before any start, until its reset", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE) } });
  const reset = h.clock.t + 600;
  fs.mkdirSync(path.join(h.env.state, "statusline"), { recursive: true });
  fs.writeFileSync(path.join(h.env.state, "statusline", "s.json"), JSON.stringify({ received_at: h.clock.t,
    rate_limits: { seven_day: { used_percentage: 100, resets_at: reset } } }));
  h.add();
  await h.until(() => h.clock.t >= reset - 10);
  assert.equal(h.backend.calls.length, 0);
  assert.equal(h.of("usage_limit").length, 1);
  assert.equal(h.of("job_failed").length, 0);
  fs.rmSync(path.join(h.env.state, "statusline", "s.json"));
  await h.until(() => h.of("job_done").length === 1);
  assert.ok(h.job("demo:implement1:1").started_at >= reset);
});

test("model_limit: the job reruns once on Opus outside the count, with a model_fallback event", async (t) => {
  const h = mk(t, { tasks: [task("T1", { modelTier: "frontier" })], script: { implement1: [{ status: "model_limit", at: 1 }] } });
  h.add();
  await h.until(() => h.of("model_fallback").length === 1);
  assert.equal(h.job("demo:implement1:1").model, "fable");
  const again = h.job("demo:implement1:2");
  assert.equal(again.model, "opus");
  assert.equal(h.of("job_failed")[0].detail.reason, "model_limit");
  h.script.implement1 = [{ gone: true, at: 1 }];
  await h.until(() => h.of("job_failed").length === 2);
  // the first counted failure: one more attempt follows (2 allowed), so the fallback was outside the count
  await h.until(() => h.of("job_failed").length === 3);
  assert.equal(h.of("model_fallback").length, 1);
  assert.equal(h.jobs().filter((j) => j.kind === "implement").length, 3);
  await h.until(() => h.of("escalated").length === 1);
  assert.equal(h.of("escalated")[0].detail.case, "failed_twice");
});

// ---- internal errors, the lock, resume -------------------------------------------------------------------------

test("an internal error stops dispatching, records engine_error and leaves everything as it is", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) },
    integrate: async () => { throw new Error("git exploded"); } });
  h.add();
  await assert.rejects(h.eng.run(SPEC), /engine stopped: git exploded/);
  assert.equal(h.of("engine_error").length, 1);
  assert.equal(h.of("engine_error")[0].detail.error, "git exploded");
  assert.equal(h.feed().find((l) => l.kind === "engine_error").tier, "critical");
  assert.match(h.notes[0], /^\[Engine\] stopped: git exploded/);
  const before = h.events().length;
  await h.step(3);
  assert.equal(h.events().length, before);
  assert.equal(h.spec().state, "integrating");
});

// Mutation run for this guard: `if (alive(pid)) throw` removed -> this test fails (no throw).
test("lock: a second start for the same project throws engine already running (pid <n>); a dead pid's lock is taken over", async (t) => {
  const h = mk(t);
  assert.equal(fs.readFileSync(paths.lockPath("demo"), "utf8").split("\n")[0], String(process.pid));
  assert.throws(() => core.start({ project: "demo", repo: h.wt, backend: h.backend }), new RegExp(`^Error: engine already running \\(pid ${process.pid}\\)$`));
  h.eng.stop();
  assert.equal(fs.existsSync(paths.lockPath("demo")), false);
  const dead = cp.spawnSync(process.execPath, ["-e", "console.log(process.pid)"], { encoding: "utf8" }).stdout.trim();
  fs.writeFileSync(paths.lockPath("demo"), `${dead}\n`);
  const again = core.start({ project: "demo", repo: h.wt, backend: h.backend });
  assert.equal(fs.readFileSync(paths.lockPath("demo"), "utf8").split("\n")[0], String(process.pid));
  again.stop();
});

test("resume: a running job whose window is gone is finished from its valid report, else run again as a new attempt", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "busy", at: 1 }] } });
  h.add();
  await h.until(() => h.job("demo:implement1:1") && h.job("demo:implement1:1").state === "running");
  const j = h.job("demo:implement1:1");
  h.eng.stop();
  // a new engine process: a fresh backend that knows no window
  const clock = h.clock;
  const mkEngine = () => core.start({ project: "demo", repo: h.wt, now: () => clock.t, tmuxCtl: path.join(h.env.root, "tmux-ctl"),
    backend: wrap(fake.createBackend({ script: { implement1: worker(DONE) }, now: () => clock.t }), clock),
    integrate: async () => ({ outcome: "merged" }), finalize: async () => {}, tell: () => {}, notify: () => {}, transcriptRoot: h.env.root });
  const e2 = mkEngine();
  await e2.resume();
  clock.t += 5; await e2.tick();
  const q = (sql, ...a) => e2.db.prepare(sql).all(...a);
  assert.equal(q("SELECT state FROM jobs WHERE id=?", j.id)[0].state, "failed");
  assert.equal(JSON.parse(q("SELECT detail FROM events WHERE kind='job_failed'")[0].detail).reason, "gone");
  assert.equal(q("SELECT kind FROM events WHERE kind='resumed'").length, 1);
  // the second attempt is started; kill again after its report exists
  for (let i = 0; i < 20 && !q("SELECT 1 FROM jobs WHERE id='demo:implement1:2' AND state='running'").length; i++) { clock.t += 5; await e2.tick(); }
  const j2 = q("SELECT * FROM jobs WHERE id='demo:implement1:2'")[0];
  assert.equal(j2.state, "running");
  fs.mkdirSync(path.dirname(j2.report), { recursive: true });
  fs.writeFileSync(j2.report, DONE);
  e2.stop();
  const e3 = mkEngine();
  await e3.resume();
  clock.t += 5; await e3.tick();
  assert.equal(e3.db.prepare("SELECT state FROM jobs WHERE id=?").get(j2.id).state, "done");
  assert.equal(e3.db.prepare("SELECT COUNT(*) AS n FROM jobs WHERE kind='implement'").get().n, 2); // not run twice
  assert.deepEqual(rebuild.check("demo").diffs, []);
  e3.stop();
});

// ---- fix round 1 (findings I1, I2, I4, I5) ---------------------------------------------------------------------
// Mutations run for these guards (each made the named test fail; see the fix report):
//   finalize called only after tests_red            fails "finalize: every terminal outcome"
//   revert called for every failed outcome          fails "finalize: every terminal outcome"
//   endNeedsYou rows dropped in failAttempt         fails "a job that fails while its permission-prompt wait is open"
//   endNeedsYou rows dropped in finishJob           fails "a job that finishes while its permission-prompt wait is open"
//   the ready exemption from the heartbeat removed  fails "a ready worker that stops refreshing its status"
//   the catch around backend.close removed          fails "a window that cannot be closed"

test("finalize: every terminal outcome is finalized once (merged, failed, denied); revert only after tests red", async (t) => {
  const a = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  a.add();
  await a.until(a.done);
  await a.step(3);
  assert.deepEqual(a.finals, ["merged"]);
  assert.deepEqual(a.reverts, []);
  const b = mk(t, { project: "demo2", script: { implement1: [{ gone: true, at: 1 }] },
    config: { retry: { implement: { max_attempts: 1, on_exhausted: "fail_spec" } } } });
  b.add();
  await b.until(b.done);
  await b.step(3);
  assert.deepEqual(b.finals, ["failed — implement1: gone"]);
  assert.deepEqual(b.reverts, []);
  const c = mk(t, { project: "demo3", tasks: GATED() });
  c.add();
  await c.until(() => c.spec().state === "awaiting_you");
  c.signal("deny");
  await c.step(3);
  assert.deepEqual(c.finals, ["denied: user gate: task 1 T1"]);
  assert.deepEqual(c.reverts, []);
});

async function parkedPrompt(t, o = {}) {
  const h = mk(t, { script: { implement1: [] }, config: { retry: { implement: { backoff_s: [0] } } }, ...o });
  h.add();
  const id = "demo:implement1:1";
  await h.until(() => h.job(id) && h.job(id).state === "running");
  h.backend.push(status(handleOf(h, id), "needs-you", h.clock));
  await h.step();
  await h.until(() => h.spec().state === "awaiting_you");
  assert.equal(h.wait().step, `core:needs_you:${id}`);
  return { h, id };
}

test("a job that fails while its permission-prompt wait is open closes the wait and un-parks the spec", async (t) => {
  const { h, id } = await parkedPrompt(t);
  h.script.implement1 = worker(DONE);
  h.backend.push({ handle: handleOf(h, id), type: "gone" });
  await h.step();
  assert.equal(firstFail(h).detail.reason, "gone");
  assert.equal(h.wait(), null);
  assert.equal(h.spec().state, "running");
  assert.equal(h.db.prepare("SELECT answer FROM waits WHERE step=?").get(`core:needs_you:${id}`).answer, "job_ended");
  const j = h.job(id);
  assert.equal(j.needs_you_since, null);
  assert.ok(j.needs_you_total >= 600);
  // the retry is not stuck behind a question about a dead window
  await h.until(() => h.of("job_done").length === 1);
  assert.equal(h.of("job_done")[0].job, "demo:implement1:2");
  assert.equal(h.of("signal").length, 0);
  assert.deepEqual(rebuild.check("demo").diffs, []);
});

test("a job that finishes while its permission-prompt wait is open closes the wait and un-parks the spec", async (t) => {
  const { h, id } = await parkedPrompt(t, { project: "demo2" });
  fs.mkdirSync(path.dirname(h.job(id).report), { recursive: true });
  fs.writeFileSync(h.job(id).report, DONE);
  h.backend.push({ handle: handleOf(h, id), type: "gone" });
  await h.step();
  assert.equal(h.job(id).state, "done");
  assert.equal(h.job(id).needs_you_since, null);
  assert.equal(h.wait(), null);
  assert.notEqual(h.spec().state, "awaiting_you");
  assert.equal(h.of("check_requested").filter((e) => e.detail.check === "verify").length, 1); // the run went on
});

test("a ready worker that stops refreshing its status ends no_report at the report grace, not heartbeat_timeout", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "busy", at: 1 }, { status: "ready", at: 2 }] } });
  h.add();
  await h.until(() => h.tells.length === 1);
  const told = h.of("report_nudge")[0].ts;
  await h.until(() => h.clock.t >= told + 290); // silent for far more than the 120 s heartbeat
  assert.equal(h.of("job_failed").length, 0);
  await h.step(3);
  assert.equal(firstFail(h).detail.reason, "no_report");
  assert.ok(firstFail(h).ts >= told + 300 && firstFail(h).ts <= told + 305);
});

test("a window that cannot be closed is recorded as a failed step and does not stop the engine", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) } });
  let tried = 0;
  h.backend.close = async () => { tried++; throw new Error("no such pane"); };
  h.add();
  await h.until(h.done);
  await h.step(3);
  assert.equal(h.eng.halted, null);
  assert.equal(h.of("engine_error").length, 0);
  assert.equal(tried, 3); // once per job, not again every tick
  const failed = h.of("step_failed").filter((e) => e.detail.step_kind === "close_window");
  assert.equal(failed.length, 3);
  assert.equal(failed[0].detail.error, "no such pane");
  assert.equal(h.db.prepare("SELECT state FROM steps WHERE key='close_window:demo:implement1:1'").get().state, "failed");
  assert.deepEqual(rebuild.check("demo").diffs, []);
});

// ---- real runs of the platform calls the core's decisions rest on ----------------------------------------------

test("context tokens: python3 ctxsize.py reads the job's transcript; a missing one is null with its reason", (t) => {
  const env = tmpEnv();
  t.after(() => env.restore());
  const root = path.join(env.root, "projects");
  fs.mkdirSync(path.join(root, "-some-proj"), { recursive: true });
  const line = { type: "assistant", isSidechain: false, requestId: "r1",
    message: { usage: { input_tokens: 10, cache_read_input_tokens: 2000, cache_creation_input_tokens: 300, output_tokens: 5 } } };
  fs.writeFileSync(path.join(root, "-some-proj", "sess-1.jsonl"), JSON.stringify(line) + "\n");
  assert.deepEqual(core.contextTokens({ session_id: "sess-1" }, root), { context_tokens: 2310 });
  assert.deepEqual(core.contextTokens({ session_id: "nope" }, root), { context_tokens: null, context_missing: "no transcript for session nope" });
  assert.deepEqual(core.contextTokens({ session_id: null }, root), { context_tokens: null, context_missing: "no session id" });
});

test("fix_stats: measured with git over the review's head to HEAD", (t) => {
  const g = gitRepo();
  t.after(() => g.cleanup());
  fs.mkdirSync(path.join(g.dir, "test"));
  fs.writeFileSync(path.join(g.dir, "a.js"), "one\ntwo\nthree\n");
  fs.writeFileSync(path.join(g.dir, "test/a.test.js"), "test('x', () => {});\ntest('y', () => {});\n");
  g.git("add", "."); g.git("commit", "-q", "-m", "base");
  const base = g.git("rev-parse", "HEAD").trim();
  fs.writeFileSync(path.join(g.dir, "a.js"), "one\nTWO\nthree\nfour\n");
  fs.writeFileSync(path.join(g.dir, "b.js"), "new\n");
  fs.writeFileSync(path.join(g.dir, "test/a.test.js"), "test('x', () => {});\n");
  g.git("add", "."); g.git("commit", "-q", "-m", "fix");
  assert.deepEqual(core.fixStats(g.dir, base), { lines: 5, files: 3, added: 1, tests_removed: 1 });
  assert.equal(core.fixStats(g.dir, null), null);
});

// ---- task 8b: adopted jobs get a fresh heartbeat window on resume ---------------------------------------------
// Mutation run for this guard: the `resumed_at` / re-arm rows removed from the adopted branch of resume() ->
// this test fails (the job is failed heartbeat_timeout on the first tick after resume).
test("resume: an adopted job's heartbeat and no-progress deadlines are re-armed from the resume time", async (t) => {
  const h = mk(t, { script: { implement1: [{ status: "busy", at: 1 }] } });
  h.add();
  await h.until(() => h.job("demo:implement1:1") && h.job("demo:implement1:1").state === "running");
  const j = h.job("demo:implement1:1");
  h.eng.stop();
  const clock = h.clock;
  clock.t += 600; // the engine was down for 10 minutes: the last status is that old
  const backend = wrap(fake.createBackend({ script: {}, now: () => clock.t }), clock);
  backend.adopt = async () => true;
  const e2 = core.start({ project: "demo", repo: h.wt, now: () => clock.t, tmuxCtl: path.join(h.env.root, "tmux-ctl"), backend,
    integrate: async () => ({ outcome: "merged" }), finalize: async () => {}, tell: () => {}, notify: () => {}, transcriptRoot: h.env.root });
  t.after(() => e2.stop());
  const state = () => e2.db.prepare("SELECT state FROM jobs WHERE id=?").get(j.id).state;
  const reason = () => e2.db.prepare("SELECT detail FROM events WHERE kind='job_failed'").all().map((e) => JSON.parse(e.detail).reason);
  await e2.resume();
  assert.equal(e2.db.prepare("SELECT detail FROM events WHERE kind='resumed'").all().map((e) => JSON.parse(e.detail).watched)[0], 1);
  clock.t += 5; await e2.tick();
  assert.equal(state(), "running", "stale status from before the restart does not fail the job");
  for (let i = 0; i < 20; i++) { clock.t += 5; await e2.tick(); } // 105 s after resume
  assert.equal(state(), "running");
  for (let i = 0; i < 4; i++) { clock.t += 5; await e2.tick(); } // past 120 s after resume plus a tick
  assert.deepEqual(reason(), ["heartbeat_timeout"]);
  assert.deepEqual(rebuild.check("demo").diffs, []);
});
