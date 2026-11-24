"use strict";
// Task 4 (spec 8a): every parking site writes a kind and a recommendation, the answer records whether it followed it,
// and one `metrics append ask` line follows each user answer.
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
const policy = require("../lib/engine/policy");

const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const US = "\x1f";

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = report({ status: "blocked", commits: [], concerns: ["needs a secret"] });
const PASS = report({ verdict: "pass", findings: [] });
const REC = { option: "fail", why: "the plan is wrong", confidence: "high" };
const PARK = (recommend) => report({ decision: "park", ruling: "ruling park", cost_if_wrong: "cost", recommend });
const RETRY = report({ decision: "retry_higher_tier", ruling: "ruling retry", cost_if_wrong: "cost" });
const worker = (text) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }];
const task = (subject, meta = {}) => ({
  subject,
  description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"], ...meta })}\n\`\`\``,
});
const status = (handle, state, clock, extra = {}) =>
  ({ handle, type: "status", state, updatedAt: clock.t, tool: null, lastToolAt: null, turnStartedAt: clock.t, ...extra });
const handleOf = (h, id) => h.backend.calls.filter((c) => c.method === "start").map((c) => c.handle).filter(Boolean).find((x) => x.job === id)
  || { job: id, window: h.job(id).window, pane: h.job(id).pane };

// The fake backend plus a seam for raw events pushed by the test.
function wrap(inner, clock) {
  const extra = [];
  return {
    calls: inner.calls,
    start: (job) => inner.start(job), close: (h) => inner.close(h), resume: (h, t) => inner.resume(h, t), usage: (h, o) => inner.usage(h, o),
    push: (ev) => extra.push({ due: clock.t, make: () => ev }),
    poll() {
      const out = inner.poll();
      const due = extra.filter((e) => e.due <= clock.t);
      for (const e of due) extra.splice(extra.indexOf(e), 1);
      return out.concat(due.map((e) => e.make()));
    },
  };
}

// o.ask: exit code of the stubbed `tmux-ctl metrics append ask`. Every call is logged one line each, argv joined by \x1f.
function mk(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eask-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  fs.writeFileSync(path.join(wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: o.tasks || [task("T1")] }));
  fs.writeFileSync(path.join(wt, SPEC), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n\n## Design\n\nbody\n");
  if (o.config) fs.writeFileSync(path.join(wt, "docs/superpowers/engine.json"), JSON.stringify(o.config));
  const ctl = path.join(env.root, "tmux-ctl");
  const log = path.join(env.root, "ctl.log");
  fs.writeFileSync(ctl, `#!/bin/sh\nprintf '%s\\037' "$@" >> "${log}"\necho >> "${log}"\n`
    + `if [ "$1 $2 $3" = "metrics append ask" ]; then exit ${o.ask || 0}; fi\necho fresh\nexit 0\n`, { mode: 0o755 });
  const clock = { t: 1000 };
  const backend = wrap(fake.createBackend({ script: o.script || {}, now: () => clock.t }), clock);
  const copts = {
    project: "demo", repo: wt, backend, now: () => clock.t, tmuxCtl: ctl,
    integrate: o.real ? undefined : (o.integrate || (async () => ({ outcome: `kept ${o.keptAs || "spec-demo"}` }))), finalize: async () => {}, revert: async () => {}, strategy: o.strategy,
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  };
  const h = {
    env, wt, clock, backend, eng: core.start(copts),
    get db() { return h.eng.db; },
    restart() { h.eng.stop(); h.eng = core.start(copts); },
    add: (extra = {}) => h.eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1", ...extra }),
    async step(n = 1) { for (let i = 0; i < n; i++) { clock.t += 5; await h.eng.tick(); } },
    async until(pred, max = 400) {
      for (let i = 0; i < max; i++) { if (pred()) return; clock.t += 5; await h.eng.tick(); }
      assert.fail(`not reached after ${max} ticks; events: ${h.events().map((e) => e.kind).join(" ")}`);
    },
    events: () => h.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    of: (kind) => h.events().filter((e) => e.kind === kind),
    spec: () => h.db.prepare("SELECT * FROM specs WHERE id=?").get(SPEC),
    job: (id) => h.db.prepare("SELECT * FROM jobs WHERE id=?").get(id),
    wait: () => inbox.openWaitFor(h.db, SPEC),
    signal: (answer, note) => assert.equal(inbox.signal(h.db, SPEC, answer, note, clock.t).rc, 0),
    calls: () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter(Boolean).map((l) => l.split(US).filter((x, i, a) => i < a.length - 1 || x)) : []),
    asks: () => h.calls().filter((a) => a.slice(0, 3).join(" ") === "metrics append ask"),
    parked: () => h.until(() => h.spec().state === "awaiting_you"),
  };
  t.after(() => { h.eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

// A real git repo in the worktree for the real integrate: `main` checked out with a branch `spec-demo` at the first commit.
function gitWt(h, how = {}) {
  const g = (...a) => cp.execFileSync("git", ["-C", h.wt, ...a], { encoding: "utf8" });
  g("init", "-q", "-b", "main");
  g("config", "user.email", "t@example.com"); g("config", "user.name", "T"); g("config", "commit.gpgsign", "false");
  fs.writeFileSync(path.join(h.wt, "f.txt"), "a\n");
  fs.writeFileSync(path.join(h.wt, ".gitignore"), ".superpowers/\n"); // the engine's own workspace is not a mid-change checkout
  g("add", "-A"); g("commit", "-q", "-m", "init");
  g("branch", "spec-demo");
  if (how.conflict) {
    g("checkout", "-q", "spec-demo"); fs.writeFileSync(path.join(h.wt, "f.txt"), "b\n"); g("commit", "-qam", "b");
    g("checkout", "-q", "main"); fs.writeFileSync(path.join(h.wt, "f.txt"), "c\n"); g("commit", "-qam", "c");
  }
  if (how.dirty) fs.writeFileSync(path.join(h.wt, "dirty.txt"), "x\n");
  if (how.branch) g("checkout", "-q", "-b", how.branch);
}

const GREEN = { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) };
const D = policy.ASK_DEFAULTS;
const SITE = {
  tests_red: { option: "approve", why: "approve runs the project tests again", confidence: "low" },
  live: { option: "approve", why: "approve retries once the live checkout is clean", confidence: "low" },
  exhausted: { option: "approve", why: "approve runs the job once more", confidence: "low" },
  unknown_case: { option: "fail", why: "the strategy named a case the engine does not know", confidence: "medium" },
  refused: { option: "approve", why: "approve sends the case to the architect once more", confidence: "low" },
};

// One row per park site (Global Constraints table, rows 1 to 11; row 8 is three sites).
const SITES = [
  { name: "needs-you for 10 minutes", step: /^core:needs_you:demo:implement1:1$/, kind: "needs_you", rec: D.needs_you,
    async arrange(t) {
      const h = mk(t, { script: { implement1: [] }, config: { retry: { implement: { timeout_min: 3 } } } });
      h.add();
      const id = "demo:implement1:1";
      await h.until(() => h.job(id) && h.job(id).state === "running");
      h.backend.push(status(handleOf(h, id), "needs-you", h.clock));
      await h.step();
      await h.parked();
      return h;
    } },
  { name: "user gate", step: /^core:gate:1$/, kind: "user_gate", rec: D.user_gate,
    async arrange(t) { const h = mk(t, { tasks: [task("T1", { userGate: true })], script: GREEN }); h.add(); await h.parked(); return h; } },
  { name: "policy changed", step: /^core:policy$/, kind: "policy_change", rec: D.policy_change,
    async arrange(t) {
      const h = mk(t, { script: GREEN });
      h.add(); await h.step();
      h.db.prepare("UPDATE specs SET policy_version=0 WHERE id=?").run(SPEC);
      await h.step();
      return h;
    } },
  { name: "step check cannot tell", step: /^core:step:push:x$/, kind: "cannot_tell", rec: D.cannot_tell,
    async arrange(t) {
      const steps = require("../lib/engine/steps");
      const h = mk(t, { script: GREEN });
      h.add();
      steps.begin(h.db, { key: "push:x", spec: SPEC, kind: "push", facts: { remote: "nowhere", ref: "x" } }, { now: h.clock.t });
      await h.eng.resume();
      return h;
    } },
  { name: "architect park", step: /^architect:failed_twice:1:demo:implement1:2$/, kind: "architect_park", rec: REC,
    async arrange(t) { const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }], architect: worker(PARK(REC)) } }); h.add(); await h.parked(); return h; } },
  { name: "tests red before the merge", step: /^integrate$/, kind: "stop_class", rec: SITE.tests_red,
    async arrange(t) { const h = mk(t, { script: GREEN, integrate: async () => ({ outcome: "tests_red_before" }) }); h.add(); await h.parked(); return h; } },
  { name: "integrate: live checkout mid-change", step: /^core:integrate$/, kind: "stop_class", rec: SITE.live,
    async arrange(t) { const h = mk(t, { script: GREEN, real: true }); gitWt(h, { dirty: true }); h.add({ integration: "merge" }); await h.parked(); return h; } },
  { name: "integrate: live checkout on another branch", step: /^core:integrate$/, kind: "stop_class", rec: SITE.live,
    async arrange(t) { const h = mk(t, { script: GREEN, real: true }); gitWt(h, { branch: "other" }); h.add({ integration: "merge" }); await h.parked(); return h; } },
  { name: "integrate: push not permitted", step: /^core:integrate$/, kind: "stop_class", rec: D.stop_class,
    async arrange(t) { const h = mk(t, { script: GREEN, real: true }); h.add({ integration: "mr", push: 0 }); await h.parked(); return h; } },
  { name: "integrate: merge failed", step: /^core:integrate$/, kind: "stop_class", rec: D.stop_class,
    async arrange(t) { const h = mk(t, { script: GREEN, real: true }); gitWt(h, { conflict: true }); h.add({ integration: "merge" }); await h.parked(); return h; } },
  { name: "integrate: unknown integration answer", step: /^core:integrate$/, kind: "stop_class", rec: D.stop_class,
    async arrange(t) { const h = mk(t, { script: GREEN, real: true }); h.add({ integration: "bogus" }); await h.parked(); return h; } },
  { name: "retry policy exhausted, on_exhausted park", step: /^core:exhausted:demo:implement1:1$/, kind: "architect_park", rec: SITE.exhausted,
    async arrange(t) {
      const h = mk(t, { script: { implement1: worker(BLOCKED) }, config: { retry: { implement: { on_exhausted: "park" } } } });
      h.add(); await h.parked(); return h;
    } },
  { name: "unknown escalation case", step: /^core:case$/, kind: "architect_park", rec: SITE.unknown_case,
    async arrange(t) {
      const strategy = { decide: (s, ev) => (ev.kind === "spec_started" ? [{ type: "escalate", case: "bogus" }] : []) };
      const h = mk(t, { strategy }); h.add(); await h.parked(); return h;
    } },
  { name: "retry_higher_tier refused twice", step: /^core:refused:blocked$/, kind: "architect_park", rec: SITE.refused,
    async arrange(t) {
      const h = mk(t, { tasks: [task("T1", { modelTier: "frontier" })], script: { implement1: worker(BLOCKED), architect: worker(RETRY) } });
      h.add(); await h.parked(); return h;
    } },
];

for (const s of SITES) {
  test(`park site: ${s.name} writes kind ${s.kind} and its recommendation`, async (t) => {
    const h = await s.arrange(t);
    const w = h.wait();
    assert.ok(w, "a wait is open");
    assert.match(w.step, s.step);
    assert.equal(w.kind, s.kind);
    assert.deepEqual(JSON.parse(w.recommendation), s.rec);
    const ev = h.of("awaiting_you").pop();
    assert.equal(ev.detail.kind, s.kind);
    assert.deepEqual(ev.detail.recommendation, s.rec);
  });
}

test("park needs a kind: a strategy that parks without one stops the engine with that error", async (t) => {
  const strategy = { decide: (s, ev) => (ev.kind === "spec_started" ? [{ type: "park", question: "q", step: "x" }] : []) };
  const h = mk(t, { strategy });
  h.add();
  await h.step(3);
  assert.ok(h.of("engine_error").some((e) => /park needs a kind/.test(e.detail.error)), "engine_error names the missing kind");
  assert.equal(h.wait(), null);
});

test("awaiting_you text shows the recommendation first, and a wait with options approve|fail builds its command from them", async (t) => {
  const strategy = { decide: (s, ev) => (ev.kind === "spec_started"
    ? [{ type: "park", question: "go on?", step: "x", kind: "user_gate", options: "approve|fail" }] : []) };
  const h = mk(t, { strategy });
  h.add();
  await h.parked();
  const d = h.of("awaiting_you")[0].detail;
  assert.equal(d.command, `tmux-ctl engine signal ${SPEC} approve|fail`);
  assert.equal(d.text, `I recommend: approve (low): ${D.user_gate.why} — go on? — answer with: tmux-ctl engine signal ${SPEC} approve|fail`);
  assert.equal(h.wait().options, "approve|fail");
});

// ---- the answer ------------------------------------------------------------------------------------------------

const gated = (t, o = {}) => mk(t, { tasks: [task("T1", { userGate: true })], script: GREEN, ...o });

for (const [answer, followed] of [["approve", true], ["deny", false]]) {
  test(`answer ${answer}: the signal event carries the wait, kind and recommendation; the ruling records followed: ${followed}`, async (t) => {
    const h = gated(t);
    h.add(); await h.parked();
    const wait = h.wait();
    h.signal(answer);
    await h.step();
    const sig = h.of("signal")[0].detail;
    assert.equal(sig.wait, wait.id);
    assert.equal(sig.kind, "user_gate");
    assert.deepEqual(sig.recommendation, D.user_gate);
    const r = h.of("ruling").filter((e) => e.detail.by === "user")[0].detail;
    assert.equal(r.kind, "user_gate");
    assert.equal(r.recommended, "approve");
    assert.equal(r.answer, answer);
    assert.equal(r.followed, followed);
  });
}

test("one metrics append ask per user answer: argv, exactly the nine JSON keys, ISO UTC times, an ask_recorded event", async (t) => {
  const h = gated(t);
  h.add(); await h.parked();
  const wait = h.wait();
  h.signal("deny");
  await h.step(2);
  const asks = h.asks();
  assert.equal(asks.length, 1);
  assert.deepEqual(asks[0].slice(0, 4), ["metrics", "append", "ask", "--json"]);
  assert.deepEqual(asks[0].slice(5), ["--batch", "b1"]);
  const j = JSON.parse(asks[0][4]);
  assert.deepEqual(Object.keys(j).sort(), ["answer", "answered_at", "asked_at", "batch", "confidence", "followed", "kind", "recommended", "spec"]);
  assert.equal(j.spec, SPEC); assert.equal(j.batch, "b1"); assert.equal(j.kind, "user_gate");
  assert.equal(j.recommended, "approve"); assert.equal(j.confidence, "low"); assert.equal(j.answer, "deny"); assert.equal(j.followed, false);
  assert.equal(j.asked_at, new Date(wait.asked_at * 1000).toISOString());
  assert.match(j.answered_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$/);
  assert.equal(h.db.prepare("SELECT state FROM steps WHERE key=?").get(`metrics_ask:${wait.id}`).state, "done");
  const rec = h.of("ask_recorded");
  assert.equal(rec.length, 1);
  assert.equal(typeof rec[0].detail.cause, "number");
  assert.equal(typeof rec[0].detail.idx, "number");
});

test("a failing metrics append ask leaves a failed step and the spec goes on", async (t) => {
  const h = gated(t, { ask: 1 });
  h.add(); await h.parked();
  const wait = h.wait();
  h.signal("approve");
  await h.until(() => h.spec().state === "done");
  assert.equal(h.db.prepare("SELECT state FROM steps WHERE key=?").get(`metrics_ask:${wait.id}`).state, "failed");
  assert.equal(h.of("step_failed").filter((e) => e.detail.step_kind === "metrics_ask").length, 1);
  assert.equal(h.spec().outcome, "kept spec-demo");
});

test("a wait closed by worker_busy or job_ended writes no ask line", async (t) => {
  for (const how of ["busy", "ended"]) {
    const h = mk(t, { script: { implement1: [] }, config: { retry: { implement: { backoff_s: [0] } } } });
    h.add();
    const id = "demo:implement1:1";
    await h.until(() => h.job(id) && h.job(id).state === "running");
    h.backend.push(status(handleOf(h, id), "needs-you", h.clock));
    await h.step();
    await h.parked();
    if (how === "busy") h.backend.push(status(handleOf(h, id), "busy", h.clock, { tool: "Read", lastToolAt: h.clock.t }));
    else h.backend.push({ handle: handleOf(h, id), type: "gone", at: h.clock.t });
    await h.step(3);
    assert.notEqual(h.spec().state, "awaiting_you", how);
    assert.equal(h.asks().length, 0, how);
    assert.equal(h.of("ask_recorded").length, 0, how);
    h.eng.stop();
  }
});

test("replay: a crash after the ask step runs the command once; the lost ask_recorded event is written again", async (t) => {
  const strategy = { decide: (s, ev) => {
    if (ev.kind === "spec_started") return [{ type: "park", question: "go?", step: "x", kind: "user_gate" }];
    return [];
  } };
  const h = mk(t, { strategy }); // the signal leaves the ask as its last command, as a crash after the step would
  h.add(); await h.parked();
  const wait = h.wait();
  h.signal("approve");
  await h.step(2);
  assert.equal(h.asks().length, 1);
  assert.equal(h.of("ask_recorded").length, 1);
  h.db.prepare("DELETE FROM events WHERE kind='ask_recorded'").run(); // the crash lost the event, the step row stayed done
  h.restart();
  await h.step(2);
  assert.equal(h.of("ask_recorded").length, 1);
  assert.equal(h.asks().length, 1, `one call for ${wait.id}`);
});
