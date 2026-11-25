"use strict";
// Approval holds in the core (spec 13, plan part 3 Task 3): a drained `approval` row parks the spec with the exact
// call; approve writes a one-time pass and resumes the worker, deny resumes it with the note, fail fails the spec.
// The hook is the real one: engine/bin/hold.js as a child process with the job's ENGINE_* environment.
//
// Mutations run against these tests (each made the named test fail; see the task report):
//   park without dropping a finished job's row   fails "a hold for a job that is not running is dropped"
//   drop the pass command on approve             fails "approve: one pass row, one resume ..."
//   keep the spec parked on deny                 fails "deny with a note: ..."
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv } = require("./engine_helpers");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const paths = require("../lib/engine/paths");
const rebuild = require("../lib/engine/rebuild");
const hold = require("../lib/engine/hold");
const dbm = require("../lib/engine/db");

const PROJECT = "holdt";
const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const HOLD_BIN = path.join(__dirname, "..", "bin", "hold.js");
const HELD = "demo:implement1:1";
const RESUMED = "demo:implement1:2";
const APPROVE_TEXT = (id) => `approval ${id} granted: retry the held call exactly as before`;
// what a resumed session receives: the fixed sentence, then the report contract of the NEW job (same wording as a fresh brief)
const REPORT_LINES = (report) => ["## Report", "", `Report file: ${report}`, "", "Write your report there. Its last fenced block must be:"];
const assertResumeText = (text, sentence, report) => {
  assert.ok(text.startsWith(sentence + "\n"), `starts with the exact sentence: ${text}`);
  for (const l of REPORT_LINES(report)) assert.ok(text.includes(l), `names the new job's report (${l}): ${text}`);
  assert.ok(text.includes("json:status"), text);
};

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = (id) => report({ status: "blocked", commits: [], concerns: [`awaiting approval ${id}`] });
const PASS = report({ verdict: "pass", findings: [] });
const worker = (text) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }];
const BUSY = [{ status: "busy", at: 1 }];

const task = (subject) => ({
  subject,
  description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"] })}\n\`\`\``,
});

// The fake backend plus the test's seams: raw events pushed by the test, a start that returns no session id
// (o.noSession), and reports for resumed sessions (fake.resume plays no script): the next text in resumeReports is
// written to the resume job's report path, then the session goes ready.
function wrap(inner, clock, o = {}) {
  const extra = [];
  const w = {
    calls: inner.calls,
    resumeReports: [],
    async start(job) {
      const h = await inner.start(job);
      if (o.noSession) delete h.session_id;
      return h;
    },
    close: (h) => inner.close(h),
    usage: (h, opts) => inner.usage(h, opts),
    async resume(h, text, job) {
      const nh = await inner.resume(h, text, job);
      const rep = w.resumeReports.shift();
      if (rep && job && job.report) {
        extra.push({ due: clock.t + 1, make: () => {
          fs.mkdirSync(path.dirname(job.report), { recursive: true });
          fs.writeFileSync(job.report, rep);
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

// The clock starts at the real time: the hook child process reads the real clock, and a pass must not look expired to it.
function mk(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "ehold-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  fs.mkdirSync(path.join(wt, "build"), { recursive: true });
  fs.writeFileSync(path.join(wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: o.tasks || [task("T1")] }));
  fs.writeFileSync(path.join(wt, SPEC), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  const outside = path.join(env.root, "elsewhere");
  fs.mkdirSync(outside, { recursive: true });
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, `#!/bin/sh\necho "$@" >> "${env.root}/ctl.log"\necho fresh\nexit 0\n`, { mode: 0o755 });
  const clock = { t: Math.floor(Date.now() / 1000) };
  const script = o.script || { implement1: BUSY };
  const h = { env, wt, outside, clock, script, ctl, tells: [], finals: [], kill: null, backends: [] };
  // One engine process on this test's database. `now` is also the crash seam: it throws while h.kill() says so.
  h.engine = () => {
    const backend = wrap(fake.createBackend({ script, now: () => clock.t }), clock, o);
    h.backends.push(backend);
    const eng = core.start({
      project: PROJECT, repo: wt, backend, tmuxCtl: ctl,
      now: () => { if (h.kill && h.kill()) throw new Error("killed"); return clock.t; },
      integrate: async () => ({ outcome: "merged" }), revert: async () => {},
      finalize: async (spec, outcome) => { h.finals.push(outcome); },
      tell: (handle, text) => h.tells.push({ window: handle.window, text }), notify: () => {},
      transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
    });
    Object.assign(h, { eng, db: eng.db, backend });
    return eng;
  };
  h.engine();
  Object.assign(h, {
    add: () => h.eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1" }),
    async step(n = 1) { for (let i = 0; i < n; i++) { clock.t += 5; await h.eng.tick(); } },
    async until(pred, max = 200) {
      for (let i = 0; i < max; i++) { if (pred()) return; clock.t += 5; await h.eng.tick(); }
      assert.fail(`not reached after ${max} ticks; events: ${h.events().map((e) => e.kind).join(" ")}`);
    },
    q: (sql, ...a) => h.db.prepare(sql).all(...a),
    events: () => h.q("SELECT * FROM events ORDER BY seq").map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    of: (kind) => h.events().filter((e) => e.kind === kind),
    spec: () => h.q("SELECT * FROM specs WHERE id=?", SPEC)[0],
    job: (id) => h.q("SELECT * FROM jobs WHERE id=?", id)[0],
    detail: (id) => JSON.parse(h.job(id).detail),
    wait: () => inbox.openWaitFor(h.db, SPEC),
    signal: (answer, note) => assert.equal(inbox.signal(h.db, SPEC, answer, note, clock.t).rc, 0),
    feed: () => fs.readFileSync(paths.feedPath(PROJECT), "utf8").trim().split("\n").map((l) => JSON.parse(l)),
    calls: (method) => h.backends.flatMap((b) => b.calls).filter((c) => c.method === method),
    approvals: () => h.q("SELECT * FROM inbox WHERE source='approval' ORDER BY id"),
    running: (id) => !!h.job(id) && h.job(id).state === "running",
    check: () => { const r = rebuild.check(PROJECT); assert.deepEqual(r.diffs, []); assert.equal(r.rc, 0); },
  });
  t.after(() => { h.eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

const hookEnv = (h, jobId) => ({ PATH: process.env.PATH, HOME: h.env.root, ENGINE_JOB: jobId, ENGINE_PROJECT: PROJECT,
  ENGINE_DIR: h.env.engineDir, ENGINE_WORKTREE: h.wt });
const hookInput = (h, jobId, call) => {
  const job = h.job(jobId);
  const sid = call.session_id === undefined ? job && job.session_id : call.session_id;
  return { tool_name: call.tool, tool_input: call.input, cwd: h.wt, ...(sid ? { session_id: sid } : {}) };
};
function decisionOf(r) {
  assert.equal(r.status, 0, r.stderr);
  if (!r.stdout.trim()) return { decision: "none" };
  const o = JSON.parse(r.stdout).hookSpecificOutput;
  return { decision: o.permissionDecision, reason: o.permissionDecisionReason, id: (/approval ([0-9a-f-]{36})/.exec(o.permissionDecisionReason) || [])[1] };
}
// The worker's tool call reaching the PreToolUse hook: engine/bin/hold.js with the job's environment.
const hook = (h, jobId, call) => decisionOf(cp.spawnSync(process.execPath, [HOLD_BIN],
  { input: JSON.stringify(hookInput(h, jobId, call)), encoding: "utf8", env: hookEnv(h, jobId) }));
// The same decision at a chosen time (a seam of this test file only: bin/hold.js reads the real clock).
const HOOK_AT = `const hold = require(${JSON.stringify(path.join(__dirname, "..", "lib", "engine", "hold.js"))});
let s = ""; process.stdin.on("data", (c) => { s += c; }); process.stdin.on("end", () => {
  const r = hold.decide(null, JSON.parse(s), process.env, Number(process.env.HOOK_NOW));
  if (r.decision !== "none") process.stdout.write(JSON.stringify({ hookSpecificOutput: { permissionDecision: r.decision,
    permissionDecisionReason: r.decision === "deny" ? r.reason : "approval " + r.hold_id + " used" } }) + "\\n"); });`;
const hookAt = (h, jobId, call, now) => decisionOf(cp.spawnSync(process.execPath, ["-e", HOOK_AT],
  { input: JSON.stringify(hookInput(h, jobId, call)), encoding: "utf8", env: { ...hookEnv(h, jobId), HOOK_NOW: String(now) } }));

const bash = (command) => ({ tool: "Bash", input: { command, description: "as the model wrote it" } });
const PUSH = bash("git push origin main");

// A running implement job whose worker made `call`: the hook denied it and the core drained the row.
async function held(t, o = {}, call = PUSH) {
  const h = mk(t, o);
  h.add();
  await h.until(() => h.running(HELD));
  const r = hook(h, HELD, call);
  assert.equal(r.decision, "deny");
  await h.step();
  return { h, id: r.id, call };
}
// The held worker does as the deny reason says: it writes its report (blocked) and stops.
async function stopWorker(h, jobId, id) {
  const j = h.job(jobId);
  fs.mkdirSync(path.dirname(j.report), { recursive: true });
  fs.writeFileSync(j.report, BLOCKED(id));
  h.backend.push({ handle: { job: j.id, window: j.window, pane: j.pane }, type: "status", state: "ready", updatedAt: h.clock.t,
    tool: null, lastToolAt: null, turnStartedAt: h.clock.t });
  await h.step();
}
const noDecision = (h) => {
  assert.equal(h.of("job_done").length, 0);
  assert.equal(h.of("job_failed").length, 0);
  assert.equal(h.of("escalated").length, 0);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM jobs WHERE kind='architect'")[0].n, 0);
};

// ---- the park ----------------------------------------------------------------------------------------------------

const RULE_CALLS = [
  ["git_push", () => PUSH, "Bash: git push origin main"],
  ["git_reset_hard", () => bash("git reset --hard HEAD~1"), "Bash: git reset --hard HEAD~1"],
  ["git_branch_force_delete", () => bash("git branch -D old"), "Bash: git branch -D old"],
  ["git_clean", () => bash("git clean -fdx"), "Bash: git clean -fdx"],
  ["rm_recursive_outside", (h) => bash(`rm -rf ${h.outside}`), (h) => `Bash: rm -rf ${h.outside}`],
  ["write_outside", (h) => ({ tool: "Write", input: { file_path: path.join(h.outside, "x.txt"), content: "x" } }), (h) => `Write: ${path.join(h.outside, "x.txt")}`],
  ["pr_merge", () => bash("gh pr merge 3 --squash"), "Bash: gh pr merge 3 --squash"],
];

test("every default rule has a park case", () => assert.deepEqual(RULE_CALLS.map((r) => r[0]), hold.DEFAULT_HOLDS.map((r) => r.id)));

for (const [rule, callOf, questionOf] of RULE_CALLS) {
  test(`${rule}: the held call parks the spec with the exact call; the job ends escalated and its window is closed`, async (t) => {
    const h = mk(t);
    h.add();
    await h.until(() => h.running(HELD));
    const call = callOf(h);
    const question = typeof questionOf === "function" ? questionOf(h) : questionOf;
    const r = hook(h, HELD, call);
    assert.equal(r.decision, "deny");
    assert.equal(r.reason, `held for approval ${r.id}: report status blocked with the concern "awaiting approval ${r.id}", then stop`);
    await h.step();
    assert.equal(h.spec().state, "awaiting_you");
    const w = h.wait();
    assert.equal(w.kind, "stop_class");
    assert.equal(w.options, "approve|deny|fail");
    assert.equal(w.question, question);
    assert.equal(w.question, hold.question(call.tool, call.input));
    assert.equal(w.step, `core:hold:${r.id}`);
    assert.equal(JSON.parse(w.recommendation).option, "deny");
    assert.equal(h.q("SELECT COUNT(*) AS n FROM waits")[0].n, 1);
    assert.equal(h.of("held")[0].detail.rule, rule);
    assert.equal(h.approvals()[0].state, "done");
    await h.step(); // the feed is written at the end of a tick
    const line = h.feed().find((l) => l.kind === "awaiting_you");
    assert.equal(line.tier, "decision");
    assert.ok(line.text.includes(question), line.text);
    // the worker is still in its window until it has written its report
    assert.equal(h.job(HELD).state, "running");
    assert.equal(h.calls("close").length, 0);
    await stopWorker(h, HELD, r.id);
    const j = h.job(HELD);
    assert.equal(j.state, "escalated");
    assert.ok(j.ended_at);
    assert.deepEqual(h.calls("close").map((c) => c.handle.pane), [j.pane]);
    assert.equal(h.q("SELECT state FROM steps WHERE key=?", `close_window:${HELD}`)[0].state, "done");
    noDecision(h);
    assert.equal(h.spec().state, "awaiting_you");
    h.check();
  });
}

test("a call inside the worktree (rm -rf build) writes no row and the job finishes normally", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: BUSY } });
  h.add();
  await h.until(() => h.running(HELD));
  assert.equal(hook(h, HELD, bash("rm -rf build")).decision, "none");
  assert.equal(h.approvals().length, 0);
  await h.until(() => h.of("job_done").length === 1);
  assert.equal(h.of("job_done")[0].job, HELD);
  assert.equal(h.job(HELD).state, "done");
  assert.equal(h.q("SELECT COUNT(*) AS n FROM waits")[0].n, 0);
  h.check();
});

test("a held job ends escalated once its report is written, before any ready", async (t) => {
  const { h, id } = await held(t);
  const j = h.job(HELD);
  fs.mkdirSync(path.dirname(j.report), { recursive: true });
  fs.writeFileSync(j.report, BLOCKED(id));
  await h.step();
  assert.equal(h.job(HELD).state, "escalated");
  assert.deepEqual(h.calls("close").map((c) => c.handle.pane), [j.pane]);
  noDecision(h);
  h.check();
});

test("a held job that goes ready without a report ends escalated: no report nudge, no failed attempt", async (t) => {
  const { h } = await held(t);
  const j = h.job(HELD);
  h.backend.push({ handle: { job: j.id, window: j.window, pane: j.pane }, type: "status", state: "ready", updatedAt: h.clock.t,
    tool: null, lastToolAt: null, turnStartedAt: h.clock.t });
  await h.step();
  assert.equal(h.job(HELD).state, "escalated");
  assert.equal(h.of("report_nudge").length, 0);
  assert.deepEqual(h.tells, []);
  noDecision(h);
  h.check();
});

test("A5: a held job's blocked report starts no architect job and no retry; neither does its window going or a timeout", async (t) => {
  const a = await held(t);
  await stopWorker(a.h, HELD, a.id);
  assert.equal(a.h.job(HELD).state, "escalated");
  noDecision(a.h);
  assert.equal(a.h.q("SELECT COUNT(*) AS n FROM jobs")[0].n, 1);
  assert.equal(a.h.q("SELECT COUNT(*) AS n FROM timers WHERE fired_at IS NULL")[0].n, 0);
  a.h.check();
});

test("A5: a held job whose window goes without a report ends escalated, with no retry job", async (t) => {
  const { h } = await held(t);
  const j = h.job(HELD);
  h.backend.push({ handle: { job: j.id, window: j.window, pane: j.pane }, type: "gone" });
  await h.step();
  assert.equal(h.job(HELD).state, "escalated");
  noDecision(h);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM jobs")[0].n, 1);
  h.check();
});

test("A5: a held job that runs into the heartbeat timeout ends escalated, with no retry job", async (t) => {
  const { h } = await held(t);
  await h.until(() => h.job(HELD).state !== "running", 60);
  assert.equal(h.job(HELD).state, "escalated");
  assert.equal(h.of("held_job_ended")[0].detail.how, "heartbeat_timeout");
  noDecision(h);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM jobs")[0].n, 1);
  h.check();
});

// ---- the answers -------------------------------------------------------------------------------------------------

test("approve: one pass row, one resume of the held session with the exact text and the new job; the pass allows the call once, then it is held again", async (t) => {
  const { h, id, call } = await held(t);
  await stopWorker(h, HELD, id);
  const session = h.job(HELD).session_id;
  assert.ok(session);
  h.signal("approve");
  await h.until(() => h.running(RESUMED));
  const answered = h.q("SELECT * FROM waits WHERE step=?", `core:hold:${id}`)[0];
  assert.equal(answered.answer, "approve");
  const passes = h.q("SELECT * FROM holds");
  assert.equal(passes.length, 1);
  assert.equal(passes[0].hold_id, id);
  assert.equal(passes[0].expires_at, answered.answered_at + 3600);
  assert.equal(passes[0].used_at, null);
  assert.equal(passes[0].spec, SPEC);
  assert.equal(passes[0].job, HELD);
  assert.equal(passes[0].tool, "Bash");
  assert.equal(passes[0].call_hash, hold.callHash(call.tool, call.input));
  assert.deepEqual(h.q("SELECT id FROM jobs ORDER BY rowid").map((j) => j.id), [HELD, RESUMED]);
  const d = h.detail(RESUMED);
  assert.deepEqual({ resume_of: d.resume_of, hold: d.hold, hold_answer: d.hold_answer, resume_text: d.resume_text },
    { resume_of: HELD, hold: id, hold_answer: "approve", resume_text: APPROVE_TEXT(id) });
  const held0 = h.job(HELD);
  const fresh = h.job(RESUMED);
  assert.deepEqual([fresh.kind, fresh.task, fresh.tier, fresh.model], [held0.kind, held0.task, held0.tier, held0.model]);
  const resumes = h.calls("resume");
  assert.equal(resumes.length, 1);
  assert.equal(resumes[0].handle.session_id, session);
  assertResumeText(resumes[0].text, APPROVE_TEXT(id), fresh.report);
  assert.notEqual(fresh.report, h.job(HELD).report);
  assert.equal(resumes[0].job.id, RESUMED);
  assert.equal(resumes[0].job.report, fresh.report);
  assert.deepEqual(h.calls("start").map((c) => c.job.id), [HELD]);
  assert.equal(h.spec().state, "running");
  // the resumed worker retries the call: allowed once
  const again = hook(h, RESUMED, { ...call, input: { ...call.input, description: "retried, worded differently" } });
  assert.equal(again.decision, "allow");
  assert.ok(h.q("SELECT used_at FROM holds")[0].used_at);
  assert.equal(h.of("hold_pass_used").length, 1);
  // the same call a second time is held again, under a new hold id
  const third = hook(h, RESUMED, call);
  assert.equal(third.decision, "deny");
  assert.notEqual(third.id, id);
  await h.step();
  assert.equal(h.spec().state, "awaiting_you");
  assert.equal(h.wait().step, `core:hold:${third.id}`);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, 1);
  h.check();
});

test("approve: the resumed job's report moves the spec on to its outcome", async (t) => {
  const { h, id } = await held(t, { script: { implement1: BUSY, review1: worker(PASS), final_review: worker(PASS) } });
  await stopWorker(h, HELD, id);
  h.backend.resumeReports.push(DONE);
  h.signal("approve");
  await h.until(() => h.spec().state === "done");
  assert.equal(h.spec().outcome, "merged");
  assert.equal(h.of("job_done")[0].job, RESUMED);
  assert.equal(h.job(HELD).state, "escalated");
  assert.equal(h.of("job_failed").length, 0);
  h.check();
});

test("approve while the held worker is still in its window: no second job of the spec is dispatched until it has ended", async (t) => {
  const { h, id } = await held(t);
  h.signal("approve");
  await h.step(3);
  assert.equal(h.job(HELD).state, "running");
  assert.equal(h.job(RESUMED).state, "pending");
  assert.equal(h.calls("resume").length, 0);
  await stopWorker(h, HELD, id);
  await h.until(() => h.running(RESUMED));
  assert.equal(h.calls("resume").length, 1);
  h.check();
});

test("a pass older than one hour is refused", async (t) => {
  const { h, id, call } = await held(t);
  await stopWorker(h, HELD, id);
  h.signal("approve");
  await h.until(() => h.running(RESUMED));
  const late = hookAt(h, RESUMED, call, h.q("SELECT expires_at FROM holds")[0].expires_at + 1); // 3601 s after the answer
  assert.equal(late.decision, "deny");
  assert.notEqual(late.id, id);
  assert.equal(h.q("SELECT used_at FROM holds")[0].used_at, null);
  // one second before the hour is up it would still pass
  assert.equal(hookAt(h, RESUMED, call, h.q("SELECT expires_at FROM holds")[0].expires_at - 1).decision, "allow");
  await h.step();
  h.check();
});

test("deny with a note: no pass, the session is resumed with the note and the spec is back in its previous state", async (t) => {
  const { h, id } = await held(t);
  await stopWorker(h, HELD, id);
  h.signal("deny", "use a PR");
  await h.step();
  assert.equal(h.spec().state, "running");
  assert.equal(h.spec().outcome, null);
  await h.until(() => h.running(RESUMED));
  assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, 0);
  const resumes = h.calls("resume");
  assert.equal(resumes.length, 1);
  assertResumeText(resumes[0].text, "denied: use a PR. Continue without it, or report blocked.", h.job(RESUMED).report);
  assert.equal(resumes[0].handle.session_id, h.job(HELD).session_id);
  assert.equal(resumes[0].job.id, RESUMED);
  assert.equal(h.detail(RESUMED).hold_answer, "deny");
  assert.equal(h.spec().state, "running");
  assert.equal(h.of("fail_spec").length + h.of("spec_done").length, 0);
  h.check();
});

test("deny without a note says no reason given", async (t) => {
  const { h, id } = await held(t);
  await stopWorker(h, HELD, id);
  h.signal("deny");
  await h.until(() => h.running(RESUMED));
  assertResumeText(h.calls("resume")[0].text, "denied: no reason given. Continue without it, or report blocked.", h.job(RESUMED).report);
  assert.equal(h.spec().state, "running");
  h.check();
});

test("fail with a note fails the spec and the held job is not resumed", async (t) => {
  const { h, id } = await held(t);
  await stopWorker(h, HELD, id);
  h.signal("fail", "x");
  await h.step(3);
  assert.equal(h.spec().state, "done");
  assert.equal(h.spec().outcome, "failed — x");
  assert.deepEqual(h.finals, ["failed — x"]);
  assert.equal(h.calls("resume").length, 0);
  assert.deepEqual(h.q("SELECT id FROM jobs").map((j) => j.id), [HELD]);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, 0);
  h.check();
});

test("a hold left unanswered at the end of the queue fails the spec as awaiting you, with its wait kept", async (t) => {
  const { h, id } = await held(t);
  await stopWorker(h, HELD, id);
  await h.step();
  assert.equal(await h.eng.finish(), true);
  assert.equal(h.spec().outcome, "failed — awaiting you: Bash: git push origin main");
  assert.equal(h.spec().state, "awaiting_you");
  assert.equal(h.wait().step, `core:hold:${id}`);
  h.check();
});

// ---- a session that cannot be resumed ------------------------------------------------------------------------------

test("unresumable (resume fails), approve: a fresh worker gets the held call in its brief, and the pass still allows the call", async (t) => {
  const { h, id, call } = await held(t, { script: { implement1: BUSY, resume_fails: true } });
  await stopWorker(h, HELD, id);
  h.signal("approve");
  await h.until(() => h.running(RESUMED));
  assert.equal(h.calls("resume").length, 1); // tried, and it threw
  assert.deepEqual(h.calls("start").map((c) => c.job.id), [HELD, RESUMED]);
  const brief = fs.readFileSync(h.job(RESUMED).brief, "utf8");
  const section = brief.slice(brief.indexOf("## Held call"));
  assert.ok(brief.includes("## Held call"), brief);
  assert.ok(section.includes(h.job(HELD).report), section);
  assert.ok(section.includes("Bash: git push origin main"), section);
  assert.ok(section.includes("approved: retry the held call exactly as before"), section);
  assert.equal(h.of("dispatched").pop().detail.how, "start");
  assert.equal(hook(h, RESUMED, call).decision, "allow"); // bound to the call and the spec, not the session
  h.check();
});

test("unresumable (no session id), deny: no resume is tried and the fresh worker's brief carries the deny text", async (t) => {
  const { h, id } = await held(t, { noSession: true });
  assert.equal(h.job(HELD).session_id, null);
  await stopWorker(h, HELD, id);
  h.signal("deny", "use a PR");
  await h.until(() => h.running(RESUMED));
  assert.equal(h.calls("resume").length, 0);
  assert.deepEqual(h.calls("start").map((c) => c.job.id), [HELD, RESUMED]);
  const brief = fs.readFileSync(h.job(RESUMED).brief, "utf8");
  const section = brief.slice(brief.indexOf("## Held call"));
  assert.ok(brief.includes("## Held call"), brief);
  assert.ok(section.includes(h.job(HELD).report), section);
  assert.ok(section.includes("denied: use a PR. Continue without it, or report blocked."), section);
  h.check();
});

test("the session id the hook saw is the one resumed when the backend gave none", async (t) => {
  const { h, id } = await held(t, { noSession: true }, { ...PUSH, session_id: "sess-from-hook" });
  assert.equal(h.job(HELD).session_id, "sess-from-hook");
  await stopWorker(h, HELD, id);
  h.signal("approve");
  await h.until(() => h.running(RESUMED));
  assert.equal(h.calls("resume")[0].handle.session_id, "sess-from-hook");
  h.check();
});

// ---- rows the core does not park -----------------------------------------------------------------------------------

test("a second approval row while the spec's wait is open is a hold_skipped event, with no second wait", async (t) => {
  const { h, id } = await held(t);
  const second = hook(h, HELD, bash("git clean -fdx"));
  assert.equal(second.decision, "deny");
  await h.step();
  assert.equal(h.of("hold_skipped").length, 1);
  assert.equal(h.of("hold_skipped")[0].detail.hold, second.id);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM waits")[0].n, 1);
  assert.equal(h.wait().step, `core:hold:${id}`);
  assert.equal(h.approvals().length, 2);
  h.check();
});

test("a hold for a job that is not running is dropped with the reason job not running", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE), review1: BUSY } });
  h.add();
  await h.until(() => h.running("demo:review1:1"));
  assert.equal(h.job(HELD).state, "done");
  assert.equal(hook(h, HELD, PUSH).decision, "deny");
  await h.step();
  const row = h.approvals()[0];
  assert.deepEqual([row.state, row.reason], ["dropped", "job not running"]);
  assert.equal(h.spec().state, "running");
  assert.equal(h.q("SELECT COUNT(*) AS n FROM waits")[0].n, 0);
  assert.equal(h.of("held").length, 0);
  h.check();
});

test("a hold for a spec that is done is dropped with the reason spec done", async (t) => {
  const h = mk(t);
  h.add();
  await h.until(() => h.running(HELD));
  // the spec ends while its worker is still in its window (the row and its event, as the core writes them)
  dbm.tx(h.db, () => {
    const row = { ...h.spec(), state: "done", outcome: "failed — test" };
    dbm.put(h.db, "specs", row);
    dbm.event(h.db, { spec: SPEC, kind: "fail_spec", ts: h.clock.t, rows: [{ table: "specs", row }] });
  });
  assert.equal(hook(h, HELD, PUSH).decision, "deny");
  await h.step();
  const row = h.approvals()[0];
  assert.deepEqual([row.state, row.reason], ["dropped", "spec done"]);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM waits")[0].n, 0);
  h.check();
});

// ---- crash and resume ----------------------------------------------------------------------------------------------

// The engine stops with `n` of the signal's commands applied (0: only the signal event; 3: the pass is written, the
// resume job is not). The commands of an approve are: the ruling, the ask record, the pass, the resume job.
for (const n of [0, 1, 2, 3]) {
  test(`crash after the signal with ${n} of its commands applied, then resume: exactly one pass, one resume job, one resume call`, async (t) => {
    const { h, id } = await held(t);
    await stopWorker(h, HELD, id);
    h.signal("approve");
    h.kill = () => {
      const sig = h.db.prepare("SELECT seq FROM events WHERE kind='signal' ORDER BY seq DESC LIMIT 1").get();
      if (!sig) return false;
      return h.db.prepare("SELECT detail FROM events WHERE seq>?").all(sig.seq).filter((e) => JSON.parse(e.detail).cause === sig.seq).length === n;
    };
    await h.step();
    assert.match(String(h.eng.halted), /killed/);
    const sig = h.q("SELECT seq FROM events WHERE kind='signal'")[0].seq;
    const caused = () => h.events().filter((e) => e.detail.cause === sig).map((e) => [e.detail.idx, e.kind]);
    assert.equal(caused().length, n);
    assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, n === 3 ? 1 : 0);
    assert.equal(h.job(RESUMED), undefined);
    h.eng.stop();
    h.kill = null;
    // a new engine process on the same database
    h.engine();
    await h.eng.resume();
    await h.until(() => h.running(RESUMED));
    await h.step(2);
    assert.deepEqual(caused(), [[0, "ruling"], [1, "ask_recorded"], [2, "hold_pass"], [3, "job_created"]]);
    assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, 1);
    assert.deepEqual(h.q("SELECT id FROM jobs ORDER BY rowid").map((j) => j.id), [HELD, RESUMED]);
    const resumes = h.calls("resume");
    assert.equal(resumes.length, 1);
    assertResumeText(resumes[0].text, APPROVE_TEXT(id), h.job(RESUMED).report);
    assert.equal(resumes[0].job.id, RESUMED);
    assert.equal(h.of("signal").length, 1);
    assert.equal(h.eng.halted, null);
    h.check();
  });
}

test("crash after a deny signal with none of its commands applied, then resume: one resume job, and the spec holds the turn meanwhile", async (t) => {
  const { h, id } = await held(t);
  await stopWorker(h, HELD, id);
  h.signal("deny", "use a PR");
  h.kill = () => {
    const sig = h.db.prepare("SELECT seq FROM events WHERE kind='signal' ORDER BY seq DESC LIMIT 1").get();
    return !!sig && !h.db.prepare("SELECT detail FROM events WHERE seq>?").all(sig.seq).some((e) => JSON.parse(e.detail).cause === sig.seq);
  };
  await h.step();
  assert.match(String(h.eng.halted), /killed/);
  assert.equal(h.spec().state, "running"); // the signal itself returned the spec to its state: no other spec can take the turn
  h.eng.stop();
  h.kill = null;
  h.engine();
  await h.eng.resume();
  await h.until(() => h.running(RESUMED));
  assert.deepEqual(h.q("SELECT id FROM jobs ORDER BY rowid").map((j) => j.id), [HELD, RESUMED]);
  assert.equal(h.calls("resume").length, 1);
  assert.equal(h.q("SELECT COUNT(*) AS n FROM holds")[0].n, 0);
  h.check();
});

// ---- leak check ----------------------------------------------------------------------------------------------------

test("leak check: the real engine directory was not touched", () => {
  const real = path.join(os.homedir(), ".local/state/agent-board/engine");
  assert.equal(fs.existsSync(real) && fs.readdirSync(real).some((f) => f.startsWith(`${PROJECT}.`)), false);
});
