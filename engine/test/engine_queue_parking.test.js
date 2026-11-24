"use strict";
// Parked specs across the queue and the queue's end (spec section 11). In-process scenarios drive core + queue.step
// with an injected clock and one scripted worker set per spec; the child-process ones run the real CLI on the fake
// backend, a scratch git repo and a temp TC_ENGINE_DIR. Nothing here opens ~/.local/state/agent-board.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const db = require("../lib/engine/db");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const rebuild = require("../lib/engine/rebuild");
const queue = require("../lib/engine/queue");
const steps = require("../lib/engine/steps");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const spec = (name) => `docs/superpowers/specs/2026-01-01-${name}-design.md`;
const plan = (name) => `docs/superpowers/plans/2026-01-01-${name}.md`;
const [S1, S2, S3] = ["one", "two", "three"].map(spec);

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const PASS = report({ verdict: "pass", findings: [] });
const worker = (text, k = 1) => [{ status: "busy", at: k }, { report: text, at: 3 * k }, { status: "ready", at: 5 * k }];
const GOOD = (k) => ({ implement1: worker(DONE, k), review1: worker(PASS, k), final_review: worker(PASS, k) });
const task = (meta = {}) => ({
  subject: "T1",
  description: `Do T1.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"], ...meta })}\n\`\`\``,
});
const GATED = [task({ userGate: true })];
const ctlStub = (root) => `#!/bin/sh\necho "$@" >> "${root}/ctl.log"\necho fresh\nexit 0\n`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const readLines = (file) => (fs.existsSync(file) ? fs.readFileSync(file, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);
const T0 = Date.UTC(2026, 0, 1, 20, 0, 0) / 1000;

// ---- in-process ------------------------------------------------------------------------------------------------

// o.specs: {one: {tasks, script}, two: ...}: each spec has its own plan and its own scripted workers. The one fake
// backend reads its script through a proxy that answers for the spec of the job being started, so `usage` and every
// other backend call are the fake's own.
function mkq(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eqp-"));
  for (const d of ["plans", "specs"]) fs.mkdirSync(path.join(wt, "docs/superpowers", d), { recursive: true });
  const names = Object.keys(o.specs);
  for (const n of names) {
    fs.writeFileSync(path.join(wt, `${plan(n)}.tasks.json`), JSON.stringify({ tasks: o.specs[n].tasks || [task()] }));
    fs.writeFileSync(path.join(wt, spec(n)), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  }
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, ctlStub(env.root), { mode: 0o755 });
  const clock = { t: T0 };
  let cur = null;
  const script = new Proxy({}, { get: (_, key) => ((o.specs[cur] || {}).script || GOOD(1))[key] });
  const inner = fake.createBackend({ script, now: () => clock.t });
  const backend = { ...inner, start: (job) => { cur = String(job.id).split(":")[0]; return inner.start(job); } };
  const finals = [];
  const eng = core.start({
    project: "demo", repo: wt, backend, now: () => clock.t, tmuxCtl: ctl, report: o.report, reportPath: o.reportPath,
    integrate: async (s) => ({ outcome: `kept ${s.branch}` }), revert: async () => {}, finalize: async (s, outcome) => { finals.push([s.id, outcome]); },
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const h = {
    env, wt, clock, eng, finals,
    enqueue: (name, payload = {}) => queue.enqueue(eng.db, spec(name), { runner: "engine", integration: "keep", push: 0, batch: "b1", worktree: wt, branch: `spec-${name}`, plan: plan(name), ...payload }, clock.t),
    async step(n = 1, dt = 5) { for (let i = 0; i < n; i++) { clock.t += dt; await queue.step(eng, "demo"); } },
    async until(pred, what, max = 600) {
      for (let i = 0; i < max; i++) { if (pred()) return; await h.step(); }
      assert.fail(`not reached after ${max} ticks: ${what}; events: ${h.kinds().join(" ")}`);
    },
    // the loop of `engine start`, on the injected clock
    run: () => queue.run(eng, { project: "demo" }),
    events: () => eng.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    kinds: () => h.events().map((e) => e.kind).filter((k) => !/^(inbox_|timer_fired$|deadline$|step_|job_session$)/.test(k)),
    of: (kind, id) => h.events().filter((e) => e.kind === kind && (id === undefined || e.spec === id)),
    seq: (kind, id) => { const e = h.of(kind, id); assert.equal(e.length, 1, `one ${kind} for ${id}, got ${e.length}`); return e[0].seq; },
    spec: (id) => eng.db.prepare("SELECT * FROM specs WHERE id=?").get(id),
    jobs: (id) => eng.db.prepare("SELECT * FROM jobs WHERE spec=? ORDER BY rowid").all(id),
    wait: (id) => inbox.openWaitFor(eng.db, id),
    signal: (id, answer = "approve") => inbox.signal(eng.db, id, answer, undefined, clock.t),
    texts: () => readLines(path.join(env.engineDir, "demo.lead.jsonl")).map((l) => l.text),
    ctlLog: () => (fs.existsSync(path.join(env.root, "ctl.log")) ? fs.readFileSync(path.join(env.root, "ctl.log"), "utf8").split("\n").filter(Boolean) : []),
    parked: (id) => (h.spec(id) || {}).state === "awaiting_you",
    done: (id) => (h.spec(id) || {}).state === "done",
  };
  t.after(() => { eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

// Mutation: "apply an answer as soon as it is drained" -> the spec leaves awaiting_you while the second holds the turn
// (the state assertion), and its signal precedes the second's spec_done.
test("the first spec parks on a user gate, the second runs; an answer during it is held; the first resumes and finishes before the third starts", async (t) => {
  const h = mkq(t, { specs: { one: { tasks: GATED }, two: {}, three: {} } });
  for (const n of ["one", "two", "three"]) h.enqueue(n);
  await h.until(() => h.of("job_created", S2).length === 1, "the second spec at work");
  assert.equal(h.spec(S1).state, "awaiting_you");
  assert.equal(h.spec(S3).state, "queued");
  assert.deepEqual(h.signal(S1), { rc: 0 });
  const heldAt = h.clock.t + 5;
  await h.step();
  assert.equal(h.of("answer_held", S1).length, 1);
  assert.equal(h.of("answer_held", S1)[0].detail.answer, "approve");
  assert.equal(h.spec(S1).state, "awaiting_you", "no state change while the second holds the turn");
  assert.equal(h.of("signal", S1).length, 0);
  assert.equal(h.of("ruling", S1).length, 0, "the ruling is written when the answer is applied");
  const w = h.eng.db.prepare("SELECT * FROM waits WHERE spec=?").get(S1);
  assert.deepEqual([w.answer, w.answered_at], ["approve", heldAt], "the answer is stored on the wait at once");
  // R18: a held answer closes the wait
  assert.deepEqual(h.signal(S1), { rc: 2, msg: `no open wait for ${S1}` });
  await h.until(() => h.done(S3), "the queue's last spec");
  assert.deepEqual([S1, S2, S3].map((s) => h.spec(s).outcome), ["kept spec-one", "kept spec-two", "kept spec-three"]);
  const order = [h.seq("spec_started", S2), h.seq("answer_held", S1), h.seq("spec_done", S2), h.seq("signal", S1), h.seq("spec_done", S1), h.seq("spec_started", S3)];
  assert.deepEqual(order, order.slice().sort((a, b) => a - b), `by seq: ${order}`);
  // the ruling and the ask line carry the time the answer was given, not the time it was applied
  const ruling = h.of("ruling", S1)[0];
  assert.equal(ruling.detail.answered_at, heldAt);
  assert.ok(ruling.ts > heldAt);
  const ask = h.ctlLog().filter((l) => l.startsWith("metrics append ask"));
  assert.equal(ask.length, 1);
  assert.match(ask[0], new RegExp(`"answered_at":"${new Date(heldAt * 1000).toISOString()}"`));
  assert.equal(rebuild.check("demo").rc, 0);
});

// Mutation: "held answers resume by queue position" -> the first spec's signal comes first.
test("two parked specs answered in the reverse of their parking order resume in the order of their answers", async (t) => {
  const h = mkq(t, { specs: { one: { tasks: GATED }, two: { tasks: GATED }, three: { script: GOOD(10) } } });
  for (const n of ["one", "two", "three"]) h.enqueue(n);
  await h.until(() => h.of("job_created", S3).length === 1, "the third spec at work");
  assert.ok(h.seq("awaiting_you", S1) < h.seq("awaiting_you", S2));
  h.signal(S2);
  await h.step();
  h.signal(S1);
  await h.step();
  assert.deepEqual(h.events().filter((e) => e.kind === "answer_held").map((e) => e.spec), [S2, S1]);
  assert.deepEqual([h.spec(S1).state, h.spec(S2).state], ["awaiting_you", "awaiting_you"]);
  await h.until(() => h.done(S1) && h.done(S2), "both parked specs");
  const order = [h.seq("spec_done", S3), h.seq("signal", S2), h.seq("spec_done", S2), h.seq("signal", S1), h.seq("spec_done", S1)];
  assert.deepEqual(order, order.slice().sort((a, b) => a - b), `by seq: ${order}`);
  assert.equal(rebuild.check("demo").rc, 0);
});

// Mutations: "dispatch waits for every running job" -> the second spec's job is not dispatched while the first's job
// row is running; "a parked spec's job end is pumped at once" -> a job of the first spec is created before the second is done;
// "the worker going busy gives the spec its state back at once" -> two specs hold the turn (the state assertion).
test("a spec parked on needs-you: the next spec's job is dispatched while its job still runs; its job end is recorded, and it starts nothing new until the second spec is done", async (t) => {
  const prompt = [{ status: "needs-you", at: 1 }, { status: "busy", at: 640 }, { report: DONE, at: 642 }, { status: "ready", at: 644 }];
  const h = mkq(t, { specs: { one: { script: { ...GOOD(1), implement1: prompt } }, two: { script: GOOD(20) } } });
  h.enqueue("one");
  h.enqueue("two");
  await h.until(() => h.of("dispatched", S2).length === 1, "the second spec's first job");
  assert.equal(h.of("needs_you_parked", S1).length, 1);
  assert.deepEqual(h.jobs(S1).map((j) => j.state), ["running"], "the first spec's job row is still running");
  assert.equal(h.eng.db.prepare("SELECT COUNT(*) AS n FROM jobs WHERE state='running'").get().n, 2);
  await h.until(() => h.of("job_done", S1).length === 1, "the parked spec's job end");
  assert.equal(h.done(S2), false, "the second spec is still at work");
  assert.equal(h.spec(S1).state, "awaiting_you", "the first spec does not take the turn back");
  assert.equal(h.of("needs_you_end", S1).length, 1);
  assert.equal(h.wait(S1), null, "the worker going busy closed the wait");
  await h.until(() => h.done(S2), "the second spec");
  assert.deepEqual(h.eng.db.prepare("SELECT kind FROM events WHERE spec=? AND (kind IN ('job_created','dispatched') OR (kind='check_requested' AND json_extract(detail, '$.check')='verify')) AND seq<? ORDER BY seq").all(S1, h.seq("spec_done", S2)).map((e) => e.kind),
    ["job_created", "dispatched"], "nothing of the first spec was created or started while the second had the turn");
  await h.until(() => h.done(S1), "the first spec");
  assert.equal(h.of("unparked", S1).length, 1);
  assert.ok(h.of("job_done", S1)[0].seq < h.seq("spec_done", S2) && h.seq("spec_done", S2) < h.seq("unparked", S1));
  assert.ok(h.eng.db.prepare("SELECT MIN(seq) AS s FROM events WHERE spec=? AND kind='check_requested' AND json_extract(detail, '$.check')='verify'").get(S1).s > h.seq("unparked", S1), "its verify check is requested only after it has the turn back");
  assert.equal(h.spec(S1).outcome, "kept spec-one");
  assert.equal(h.jobs(S1).filter((j) => j.kind === "implement").length, 1, "the parked job was not run again");
  assert.equal(rebuild.check("demo").rc, 0);
});

// Mutation: "a parked spec keeps the turn" -> the second spec never starts.
test("a spec that parks on its budget cap gives the turn away like any other park", async (t) => {
  const h = mkq(t, { specs: { one: {}, two: {} } });
  h.enqueue("one", { budget_attempts: 1 });
  h.enqueue("two");
  await h.until(() => h.done(S2), "the second spec");
  const asked = h.of("awaiting_you", S1);
  assert.equal(asked.length, 1);
  assert.equal(asked[0].detail.step, "core:budget:cap");
  assert.ok(asked[0].seq < h.seq("spec_started", S2));
  assert.equal(h.spec(S1).state, "awaiting_you");
  assert.equal(await h.run(), 0);
  assert.match(h.spec(S1).outcome, /^failed — awaiting you: budget reached: attempts 1\/1/);
});

// Mutations: "parked_failed ignores an existing outcome" -> a second parked_failed and record; "finish does not check
// that a queue is open" -> a second queue_finished; "parked_failed closes the wait" -> the wait assertion.
test("the end of the queue: an unanswered parked spec is failed with its wait kept, recorded once, and queue_finished is written once", async (t) => {
  const h = mkq(t, { specs: { one: { tasks: GATED }, two: {} } });
  h.enqueue("one");
  h.enqueue("two");
  assert.equal(await h.run(), 0);
  assert.deepEqual([h.spec(S1).state, h.spec(S1).outcome], ["awaiting_you", "failed — awaiting you: user gate: task 1 T1"]);
  assert.equal(h.wait(S1).question, "user gate: task 1 T1", "the wait is still open");
  assert.equal(h.spec(S2).outcome, "kept spec-two");
  assert.equal(h.of("parked_failed", S1)[0].detail.question, "user gate: task 1 T1");
  assert.ok(h.seq("spec_done", S2) < h.seq("parked_failed", S1) && h.seq("parked_failed", S1) < h.of("queue_finished")[0].seq);
  const rec = () => h.ctlLog().filter((l) => l.startsWith(`metrics record ${S1} --batch b1 --outcome failed — awaiting you: user gate: task 1 T1 --budget `));
  assert.equal(rec().length, 1);
  const step = h.eng.db.prepare("SELECT * FROM steps WHERE key=?").get(`metrics_record:${S1}:parked:${h.wait(S1).id}`);
  assert.deepEqual([step.kind, step.state], ["metrics_record_parked", "done"]);
  assert.deepEqual(queue.unfinished(h.eng.db), [], "the queue has finished");
  assert.deepEqual(h.texts(), [`[Engine] awaiting you: ${S1}: user gate: task 1 T1`, "[Engine] queue finished: (no report)"]);
  // a second start of the same queue: nothing to do, nothing written twice
  assert.equal(await h.run(), 0);
  assert.equal(h.of("queue_finished").length, 1);
  assert.equal(h.of("parked_failed").length, 1);
  assert.equal(rec().length, 1);
  // a later answer resumes it, to its real outcome, recorded by finalize; still one queue_finished
  assert.deepEqual(h.signal(S1), { rc: 0 });
  assert.equal(await h.run(), 0);
  assert.deepEqual([h.spec(S1).state, h.spec(S1).outcome], ["done", "kept spec-one"]);
  assert.deepEqual(h.finals.filter((f) => f[0] === S1), [[S1, "kept spec-one"]]);
  assert.equal(h.of("queue_finished").length, 1);
  assert.equal(h.texts().length, 2);
  assert.equal(rebuild.check("demo").rc, 0);
});

// R15. Mutation: "queue_finished ignores the report hook" -> the line says (no report).
test("the report hook's path is the queue_finished event's report and the lead line's text", async (t) => {
  const seen = [];
  const h = mkq(t, { specs: { one: {} }, report: async (ctx) => { seen.push(Object.keys(ctx).sort().join(",")); return "docs/superpowers/reports/2026-01-01-queue.md"; } });
  h.enqueue("one");
  assert.equal(await h.run(), 0);
  assert.equal(seen.length, 1);
  assert.equal(h.of("queue_finished")[0].detail.report, "docs/superpowers/reports/2026-01-01-queue.md");
  assert.deepEqual(h.texts(), ["[Engine] queue finished: docs/superpowers/reports/2026-01-01-queue.md"]);
  assert.ok(h.seq("spec_done", S1) < h.of("queue_finished")[0].seq);
});

// I1. Mutation: "drop the catch around the report hook" -> the engine halts, no queue_finished, start exits 1 (this test fails).
test("a report hook that throws: report_failed with its first line, then queue_finished with no report, and the loop returns 0", async (t) => {
  const h = mkq(t, { specs: { one: {} }, report: async () => { throw new Error("disk full\nsecond line"); } });
  h.enqueue("one");
  assert.equal(await h.run(), 0);
  assert.ok(!h.eng.halted);
  assert.equal(h.of("report_failed").length, 1);
  assert.equal(h.of("report_failed")[0].detail.error, "disk full");
  assert.deepEqual(h.of("queue_finished").map((e) => e.detail.report), [null]);
  assert.ok(h.seq("report_failed") < h.seq("queue_finished"));
  assert.deepEqual(h.texts(), ["[Engine] queue finished: (no report)"]);
  const row = h.eng.db.prepare("SELECT kind, state FROM steps WHERE kind='queue_report'").get();
  assert.equal(row.state, "failed");
  assert.equal(await h.run(), 0, "a restart adds nothing");
  assert.equal(h.of("queue_finished").length, 1);
});

// I1. Mutation: "the queue_report check answers not_done" -> the hook is called a second time.
test("a kill between the report hook and queue_finished: after the restart one queue_finished, and a report that exists is not made again", async (t) => {
  let calls = 0;
  const rel = "docs/superpowers/reports/2026-01-01-queue.md";
  const h = mkq(t, { specs: { one: {} }, reportPath: () => rel, report: async () => { calls++; return rel; } });
  h.enqueue("one");
  await h.until(() => h.done(S1), "the spec done");
  // the state a kill leaves: the step at intent, the report written, no queue_finished
  steps.begin(h.eng.db, { key: "queue_report:0", spec: null, kind: "queue_report", facts: { path: rel } }, { now: () => h.clock.t });
  fs.mkdirSync(path.dirname(path.join(h.wt, rel)), { recursive: true });
  fs.writeFileSync(path.join(h.wt, rel), "# report\n");
  await h.eng.resume();
  assert.equal(await h.run(), 0);
  assert.equal(calls, 0, "the hook was not called");
  assert.deepEqual(h.of("queue_finished").map((e) => e.detail.report), [rel]);
  assert.equal(await h.run(), 0);
  assert.equal(h.of("queue_finished").length, 1);
});

// I1. Mutation: "an intent row whose report is missing is failed instead of run again" -> the hook is not called.
test("a kill between the report hook's start and its report: the hook runs again", async (t) => {
  let calls = 0;
  const rel = "docs/superpowers/reports/2026-01-01-queue.md";
  const h = mkq(t, { specs: { one: {} }, reportPath: () => rel, report: async () => { calls++; return rel; } });
  h.enqueue("one");
  await h.until(() => h.done(S1), "the spec done");
  steps.begin(h.eng.db, { key: "queue_report:0", spec: null, kind: "queue_report", facts: { path: rel } }, { now: () => h.clock.t });
  await h.eng.resume();
  assert.equal(await h.run(), 0);
  assert.equal(calls, 1);
  assert.deepEqual(h.of("queue_finished").map((e) => e.detail.report), [rel]);
});

// Minor 1. Mutation: "key the parked record per spec" -> one call, with the first park's question.
test("a spec parked twice is recorded once per wait, the last record carrying the second park's outcome", async (t) => {
  const h = mkq(t, { specs: { one: { tasks: [task({ userGate: true }), task({ userGate: true })] } } });
  h.enqueue("one");
  assert.equal(await h.run(), 0);
  const first = h.wait(S1);
  const rec = () => h.ctlLog().filter((l) => l.startsWith(`metrics record ${S1} --batch b1 --outcome failed — awaiting you: `));
  assert.equal(rec().length, 1);
  assert.deepEqual(h.signal(S1), { rc: 0 });
  assert.equal(await h.run(), 0);
  const second = h.wait(S1);
  assert.ok(second && second.id !== first.id, "parked again on a new wait");
  assert.equal(rec().length, 2);
  assert.ok(rec()[0].includes(first.question) && rec()[1].includes(second.question), rec().join("\n"));
  assert.notEqual(first.question, second.question);
});

// Mutation: "parked_failed closes the wait" -> the answer 26 hours later finds no open wait (signal rc 2).
test("aged state: a spec parked on needs-you, the queue ended, answered 26 hours later across a day boundary: its timers fire once each, the parked job is not failed, and the spec runs to its outcome", async (t) => {
  const late = 26 * 3600 + 1500; // seconds after the job's start: the worker leaves its prompt well after the answer
  const prompt = [{ status: "needs-you", at: 1 }, { status: "busy", at: late }, { report: DONE, at: late + 2 }, { status: "ready", at: late + 4 }];
  const h = mkq(t, { specs: { one: { script: { ...GOOD(1), implement1: prompt } }, two: {}, three: {} } });
  for (const n of ["one", "two", "three"]) h.enqueue(n);
  assert.equal(await h.run(), 0);
  assert.deepEqual([S1, S2, S3].map((s) => [h.spec(s).state, h.spec(s).outcome]),
    [["awaiting_you", `failed — awaiting you: permission prompt in one·implement1`], ["done", "kept spec-two"], ["done", "kept spec-three"]]);
  const parkedJob = h.jobs(S1)[0];
  assert.equal(parkedJob.state, "running", "its window is untouched");
  assert.ok(h.eng.db.prepare("SELECT COUNT(*) AS n FROM jobs").get().n >= 3, "three workers' jobs in the database");
  const day0 = new Date(h.clock.t * 1000).getUTCDate();
  h.clock.t = T0 + 26 * 3600;
  assert.notEqual(new Date(h.clock.t * 1000).getUTCDate(), day0);
  assert.equal(await h.run(), 0, "a start with nothing answered ends at once");
  assert.equal(h.spec(S1).state, "awaiting_you");
  assert.deepEqual(h.signal(S1), { rc: 0 });
  // approve re-arms the prompt's 10 minutes; the worker is still at its prompt when they run out, so the spec parks
  // again and, with nothing else runnable, the loop ends once more
  assert.equal(await h.run(), 0);
  assert.equal(h.of("signal", S1).length, 1);
  assert.equal(h.spec(S1).state, "awaiting_you");
  assert.equal(h.of("job_failed", S1).length, 0);
  // then the worker's prompt is answered in its window: the next start sees it busy and the spec runs to its outcome
  h.clock.t = T0 + late + 60; // past the scripted moment (counted from the job's start)
  assert.equal(await h.run(), 0);
  assert.deepEqual([h.spec(S1).state, h.spec(S1).outcome], ["done", "kept spec-one"]);
  assert.equal(h.of("job_failed", S1).length, 0, "the parked job was never failed");
  assert.deepEqual(h.jobs(S1).filter((j) => j.kind === "implement").map((j) => [j.id, j.state]), [[parkedJob.id, "done"]]);
  // every deadline timer of the parked job that came due fired exactly once
  const timers = h.eng.db.prepare("SELECT id, fired_at FROM timers WHERE job=? AND kind='deadline'").all(parkedJob.id);
  const fired = h.of("timer_fired").flatMap((e) => e.detail.rows.filter((r) => r.table === "timers").map((r) => r.row.id));
  assert.ok(timers.length >= 2, `the prompt's deadline and the one armed by the late answer: ${timers.map((x) => x.id)}`);
  for (const x of timers) assert.ok(fired.filter((id) => id === x.id).length <= 1, `${x.id} fired at most once`);
  assert.ok(fired.filter((id) => timers.some((x) => x.id === id)).length >= 2, "deadlines fired during the park and after the late answer");
  assert.equal(h.of("needs_you_parked", S1).length, 2, "the deadline after the late answer parked it again instead of failing it");
  assert.equal(h.of("queue_finished").length, 1);
  assert.equal(rebuild.check("demo").rc, 0);
});

// ---- child processes -------------------------------------------------------------------------------------------

// A scratch project: the main checkout and one spec worktree (branch spec-demo) holding three specs and their plans.
// o.gated: the names whose one task is a user gate. Retries wait no time, so a worker killed with its engine runs again at once.
function project(t, o = {}) {
  const env = tmpEnv();
  const repo = gitRepo();
  const w = (rel, text) => {
    fs.mkdirSync(path.dirname(path.join(repo.dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(repo.dir, rel), text);
  };
  for (const n of ["one", "two", "three"]) {
    w(spec(n), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
    w(plan(n), `# Plan\n\n**Spec:** ${spec(n)}\n`);
    const tasks = (o.gated || ["one"]).includes(n) ? GATED : n === o.long ? [task(), task(), task()] : [task()];
    w(`${plan(n)}.tasks.json`, JSON.stringify({ tasks }));
  }
  w("docs/superpowers/engine.json", JSON.stringify({ retry: { implement: { backoff_s: [0] }, review: { backoff_s: [0] }, final_review: { backoff_s: [0] } } }));
  repo.git("add", "-A");
  repo.git("commit", "-q", "-m", "specs and plans");
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eqp-wt-"));
  fs.rmSync(wt, { recursive: true });
  repo.git("worktree", "add", "-q", "-b", "spec-demo", wt);
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, ctlStub(env.root), { mode: 0o755 });
  const scriptFile = path.join(env.root, "script.json");
  const k = o.k || 0.1;
  fs.writeFileSync(scriptFile, JSON.stringify({ ...GOOD(k), implement2: worker(DONE, k), review2: worker(PASS, k), implement3: worker(DONE, k), review3: worker(PASS, k) }));
  const childEnv = { ...process.env, HOME: env.root, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "demo", TC_TMUX_CTL: ctl };
  for (const k of ["TMUX", "TC_SESSION", "NODE_TEST_CONTEXT"]) delete childEnv[k];
  const children = [];
  const p = {
    env, repo, wt,
    run(args, opts = {}) {
      const r = cp.spawnSync("node", [ENGINE, ...args], { cwd: wt, env: childEnv, encoding: "utf8", timeout: opts.timeout || 60000 });
      const err = (r.stderr || "").split("\n").filter((l) => !/ExperimentalWarning: SQLite|--trace-warnings/.test(l)).join("\n");
      return { code: r.status, signal: r.signal, out: r.stdout, err };
    },
    // the same without blocking this process: the kill matrix runs several projects at once, and a blocking child
    // here would delay another project's answer past the moment it is meant for
    runA(args) {
      return new Promise((resolve) => {
        const c = cp.spawn("node", [ENGINE, ...args], { cwd: wt, env: childEnv, stdio: ["ignore", "pipe", "pipe"] });
        let out = "";
        let err = "";
        c.stdout.on("data", (b) => { out += b; });
        c.stderr.on("data", (b) => { err += b; });
        c.once("exit", (code) => resolve({ code, out, err }));
      });
    },
    enqueueAll() {
      for (const n of ["one", "two", "three"]) {
        const r = p.run(["enqueue", spec(n), "--runner", "engine", "--integration", "keep", "--batch", "b1"]);
        assert.deepEqual([r.code, r.out.trim()], [0, `queued ${spec(n)} (engine)`], r.err);
      }
    },
    start() {
      const child = cp.spawn("node", [ENGINE, "start", "--here", "--backend", "fake", "--script", scriptFile], { cwd: wt, env: childEnv, stdio: ["ignore", "pipe", "pipe"] });
      let out = "";
      child.stdout.on("data", (b) => { out += b; });
      child.stderr.on("data", (b) => { out += b; });
      children.push(child);
      return { child, out: () => out.split("\n").slice(-12).join("\n"), exit: new Promise((r) => child.once("exit", (code) => r(code))) };
    },
    resume: (opts) => p.run(["resume", "--backend", "fake", "--script", scriptFile], opts),
    ctlLog: () => (fs.existsSync(path.join(env.root, "ctl.log")) ? fs.readFileSync(path.join(env.root, "ctl.log"), "utf8").split("\n").filter(Boolean) : []),
    lines: () => readLines(path.join(env.engineDir, "demo.lead.jsonl")).map((l) => l.text),
    // several projects live in this process at once (the kill matrix): each read names its own engine dir
    read(fn) { process.env.TC_ENGINE_DIR = env.engineDir; const d = db.open("demo"); try { return fn(d); } finally { d.close(); } },
    peek(fn) { try { return fs.existsSync(path.join(env.engineDir, "demo.sqlite")) ? p.read(fn) : null; } catch (_) { return null; } },
    events: (kind) => p.read((d) => d.prepare("SELECT * FROM events WHERE kind=? ORDER BY seq").all(kind)),
    kinds: () => p.peek((d) => d.prepare("SELECT kind FROM events ORDER BY seq").all().map((e) => e.kind)) || [],
    spec: (id) => p.read((d) => d.prepare("SELECT * FROM specs WHERE id=?").get(id)),
    started: (id) => !!p.peek((d) => d.prepare("SELECT 1 FROM events WHERE kind='spec_started' AND spec=?").get(id)),
    async until(pred, what, ms = 60000) {
      const t0 = Date.now();
      for (;;) {
        if (pred()) return;
        assert.ok(Date.now() - t0 < ms, `not reached in ${ms} ms: ${what}`);
        await sleep(25);
      }
    },
    cleanup() {
      for (const c of children) { try { c.kill("SIGKILL"); } catch (_) { /* gone */ } }
      try { repo.git("worktree", "remove", "--force", wt); } catch (_) { /* already gone */ }
      repo.cleanup();
      env.restore();
    },
  };
  if (t) t.after(p.cleanup);
  return p;
}

// Mutation: "engine resume ends the queue again" -> a second queue_finished; "finalize is skipped for a spec that was
// parked-failed" -> no second record.
test("no answer: engine start exits 0 with the first spec failed — awaiting you and its wait open; a later signal and engine resume complete and re-record it", async (t) => {
  const p = project(t);
  p.enqueueAll();
  const s = p.start();
  assert.equal(await s.exit, 0, s.out());
  const gate = "user gate: task 1 T1";
  assert.deepEqual([p.spec(S1).state, p.spec(S1).outcome], ["awaiting_you", `failed — awaiting you: ${gate}`]);
  assert.deepEqual([S2, S3].map((x) => p.spec(x).outcome), ["kept spec-demo", "kept spec-demo"]);
  assert.equal(p.read((d) => d.prepare("SELECT COUNT(*) AS n FROM waits WHERE spec=? AND answered_at IS NULL").get(S1).n), 1, "its wait is still open");
  const records = () => p.ctlLog().filter((l) => l.startsWith(`metrics record ${S1} `));
  assert.equal(records().length, 1);
  assert.ok(records()[0].startsWith(`metrics record ${S1} --batch b1 --outcome failed — awaiting you: ${gate} --budget `), records()[0]);
  assert.equal(p.events("queue_finished").length, 1);
  assert.deepEqual(p.lines(), [`[Engine] awaiting you: ${S1}: ${gate}`,
    `[Engine] queue finished: docs/superpowers/reports/${new Date(p.events("spec_added")[0].ts * 1000).toISOString().slice(0, 10)}-queue.md`]);
  assert.equal(p.run(["status", "--unfinished"]).code, 1, "queue_finished closed the queue");
  assert.equal(p.run(["start", "--preflight"]).code, 1);
  const waiting = p.run(["status", "--waiting"]);
  assert.match(waiting.out, new RegExp(`answer: {3}tmux-ctl engine signal ${S1} approve`), "the parked spec is still listed with its signal command");

  assert.equal(p.run(["signal", S1, "approve"]).code, 0);
  const r = p.resume();
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out, new RegExp(`^outcome: kept spec-demo$`, "m"));
  assert.deepEqual([p.spec(S1).state, p.spec(S1).outcome], ["done", "kept spec-demo"]);
  assert.equal(records().length, 2);
  assert.ok(records()[1].startsWith(`metrics record ${S1} --batch b1 --outcome kept spec-demo --budget `), records()[1]);
  assert.equal(p.events("queue_finished").length, 1, "still exactly one queue_finished");
  assert.equal(p.lines().length, 2);
  assert.equal(p.run(["rebuild", "--check"]).code, 0);
});

// Mutation: "engine resume waits for every open spec's outcome" (part 1's loop) -> the 30 s limit kills it.
test("engine resume with one answered and one unanswered parked spec finishes the answered one and exits within 30 s", async (t) => {
  const p = project(t, { gated: ["one", "two"] });
  p.enqueueAll();
  assert.equal(await p.start().exit, 0);
  assert.deepEqual([S1, S2].map((x) => p.spec(x).state), ["awaiting_you", "awaiting_you"]);
  assert.equal(p.run(["signal", S2, "approve"]).code, 0);
  const t0 = Date.now();
  const r = p.resume({ timeout: 30000 });
  assert.equal(r.signal, null, `engine resume was still running after 30 s: ${r.out}`);
  assert.ok(Date.now() - t0 < 30000);
  assert.equal(r.code, 0, r.err + r.out);
  assert.deepEqual([p.spec(S2).state, p.spec(S2).outcome], ["done", "kept spec-demo"]);
  assert.deepEqual([p.spec(S1).state, p.spec(S1).outcome], ["awaiting_you", "failed — awaiting you: user gate: task 1 T1"]);
  assert.match(r.out, new RegExp(`^awaiting you: ${S1}: user gate: task 1 T1$`, "m"));
  assert.match(r.out, /^outcome: kept spec-demo$/m);
  assert.equal(p.events("queue_finished").length, 1);
  assert.equal(p.events("parked_failed").length, 2, "no second parked_failed for the one still waiting");
  // an unanswered parked spec alone: resume has nothing runnable and exits at once
  const again = p.resume({ timeout: 30000 });
  assert.deepEqual([again.signal, again.code], [null, 0], again.err + again.out);
  assert.equal(p.run(["rebuild", "--check"]).code, 0);
});

// ---- the kill matrix of the parking run --------------------------------------------------------------------------

const ORDERED = ["spec_started", "signal", "spec_done", "fail_spec", "parked_failed", "queue_finished"];
const ordered = (p) => p.read((d) => d.prepare(`SELECT kind, spec FROM events WHERE kind IN (${ORDERED.map(() => "?").join(",")}) ORDER BY seq`).all(...ORDERED).map((e) => `${e.kind} ${e.spec || "-"}`));
const outcomes = (p) => p.read((d) => d.prepare("SELECT id, state, outcome FROM specs ORDER BY position").all().map((s) => `${s.id} ${s.state} ${s.outcome}`));

// The parking run: the first spec parks on its user gate; the answer is written once the second spec has started
// (whether or not an engine is alive at that moment), so it is held; the first resumes before the third.
// `kill`: an event kind; the engine is killed by pid the first time that kind is in the database, then started again.
async function parkingRun(p, kill) {
  for (const n of ["one", "two", "three"]) assert.equal((await p.runA(["enqueue", spec(n), "--runner", "engine", "--integration", "keep", "--batch", "b1"])).code, 0);
  let s = p.start();
  let signalled = null;
  const answer = () => {
    if (signalled || !p.started(S2)) return;
    signalled = p.runA(["signal", S1, "approve"]);
  };
  if (kill) {
    let early = null;
    s.exit.then((c) => { early = c; });
    await p.until(() => {
      answer();
      if (p.kinds().includes(kill)) return true;
      if (early !== null) assert.fail(`engine start exited ${early} before ${kill}: ${s.out()}`);
      return false;
    }, `event ${kill}`);
    s.child.kill("SIGKILL"); // by pid, never a pattern
    await s.exit;
    answer();
    s = p.start();
  }
  p.last = s;
  let code = null;
  s.exit.then((c) => { code = c; });
  await p.until(() => { answer(); return code !== null; }, "engine start to exit", 120000);
  const sig = await signalled;
  assert.equal(sig && sig.code, 0, `engine signal: ${sig && sig.err}`);
  return code;
}

// Mutation: "apply an answer as soon as it is drained" -> no answer_held in the reference run and another order of
// turn events.
test("kill at each distinct event kind of the three-spec parking run, then engine start: the same outcomes and the same order of turn events, rebuild --check 0", async (t) => {
  // the second spec has three tasks: it holds the turn long enough for the answer to arrive while it runs, whatever the load
  const ref = project(t, { k: 0.15, long: "two" });
  assert.equal(await parkingRun(ref, null), 0);
  const refOrder = ordered(ref);
  const refOutcomes = outcomes(ref);
  assert.deepEqual(refOrder, [`spec_started ${S1}`, `spec_started ${S2}`, `spec_done ${S2}`, `signal ${S1}`, `spec_done ${S1}`, `spec_started ${S3}`, `spec_done ${S3}`, "queue_finished -"]);
  assert.equal(ref.events("answer_held").length, 1, "the answer was held in the reference run");
  // R18, on the finished reference: nothing is waiting
  assert.equal(ref.run(["signal", S1, "approve"]).code, 2);
  const killPoints = [...new Set(ref.kinds())];
  assert.ok(killPoints.includes("answer_held") && killPoints.includes("queue_finished") && killPoints.length >= 15, killPoints.join(","));

  const tally = [];
  const failures = [];
  const one = async (kind) => {
    const t0 = Date.now();
    const p = project(null, { k: 0.15, long: "two" });
    let ok = false;
    let why = "";
    try {
      const code = await parkingRun(p, kind);
      assert.equal(code, 0, `engine start after the kill: ${p.last.out()}`);
      assert.deepEqual(outcomes(p), refOutcomes, "same final outcomes");
      assert.deepEqual(ordered(p), refOrder, "same order of turn events");
      const c = await p.runA(["rebuild", "--check"]);
      assert.equal(c.code, 0, `rebuild --check: ${c.out}${c.err}`);
      ok = true;
    } catch (e) {
      why = String((e && e.message) || e).split("\n").slice(0, 30).join(" | ");
    } finally {
      tally.push(`${kind} ${ok ? "ok" : "FAIL"} ${Date.now() - t0}${why ? ` ${why}` : ""}`);
      if (!ok) failures.push(kind);
      p.cleanup();
    }
  };
  // six kill points at a time: each has its own repo, engine dir and processes
  const todo = killPoints.slice();
  await Promise.all([0, 1, 2, 3, 4, 5].map(async () => { while (todo.length) await one(todo.shift()); }));
  if (failures.length) console.log(`kill-point tally:\n${tally.join("\n")}`);
  assert.deepEqual(failures, [], `kill points that failed:\n${tally.join("\n")}`);
});

// R18, through the CLI, while a spec holds the turn. Mutation: "status --waiting lists only open waits" -> nothing is waiting.
test("a held answer: a second engine signal exits 2 with no open wait, and status --waiting lists the spec as answer held", async (t) => {
  const p = project(t, { k: 0.6 });
  p.enqueueAll();
  const s = p.start();
  await p.until(() => p.started(S2), "the second spec to start");
  assert.equal(p.run(["signal", S1, "approve", "--note", "go"]).code, 0);
  await p.until(() => (p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM events WHERE kind='answer_held'").get().n) || 0) === 1, "answer_held");
  assert.equal(p.spec(S2).state !== "done", true, "the second spec still holds the turn");
  const second = p.run(["signal", S1, "approve"]);
  assert.equal(second.code, 2);
  assert.match(second.err, new RegExp(`no open wait for ${S1}`));
  const w = p.run(["status", "--waiting"]);
  assert.equal(w.code, 0);
  assert.match(w.out, new RegExp(`^${S1}\\n {2}answer held: approve \\(go\\)$`, "m"), w.out);
  assert.equal(await s.exit, 0);
  assert.equal(p.spec(S1).outcome, "kept spec-demo");
  assert.equal(p.run(["status", "--waiting"]).out.trim(), "nothing is waiting");
});
