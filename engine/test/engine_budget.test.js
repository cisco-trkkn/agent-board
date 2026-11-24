"use strict";
// Task 5 (spec 8b): the per-spec budget. Every dispatch reserves an attempt, every job end adds its tokens, a reached
// cap or an unmeasurable job parks the spec. In-process runs on the fake backend; one kill test with real child processes.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const dbm = require("../lib/engine/db");

const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const ENGINE = path.resolve(__dirname, "../bin/engine.js");

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const PASS = report({ verdict: "pass", findings: [] });
const FINDING = report({ verdict: "fail", findings: [{ severity: "Important", task: 1, text: "fix it" }] });
const worker = (text, tokens) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }, ...(tokens === undefined ? [] : [{ tokens }])];
const task = (subject) => ({
  subject,
  description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"] })}\n\`\`\``,
});
const tasks = (n) => Array.from({ length: n }, (_, i) => task(`T${i + 1}`));
const scriptFor = (n, tokens) => {
  const s = { final_review: worker(PASS, tokens) };
  for (let i = 1; i <= n; i++) { s[`implement${i}`] = worker(DONE, tokens); s[`review${i}`] = worker(PASS, tokens); }
  return s;
};

function mk(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "ebud-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  fs.writeFileSync(path.join(wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: o.tasks || tasks(1) }));
  fs.writeFileSync(path.join(wt, SPEC), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n\n## Design\n\nbody\n");
  if (o.config) fs.writeFileSync(path.join(wt, "docs/superpowers/engine.json"), JSON.stringify(o.config));
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, "#!/bin/sh\necho fresh\nexit 0\n", { mode: 0o755 });
  const clock = { t: 1000 };
  const inner = fake.createBackend({ script: o.script || scriptFor(1, 100), now: () => clock.t });
  const backend = o.noUsage ? { start: inner.start, close: inner.close, resume: inner.resume, poll: inner.poll, calls: inner.calls } : inner;
  const h = {
    env, wt, clock, backend,
    eng: core.start({
      project: "demo", repo: wt, backend, now: () => clock.t, tmuxCtl: ctl, strategy: o.strategy,
      integrate: async () => ({ outcome: "kept spec-demo" }), finalize: async () => {}, revert: async () => {},
      tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
    }),
    get db() { return h.eng.db; },
    add: (extra = {}) => h.eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1", ...extra }),
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
    parked: () => h.until(() => h.spec().state === "awaiting_you"),
    finished: () => h.until(() => h.spec().state === "done"),
  };
  t.after(() => { h.eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

test("addSpec stores the caps from the flags, else from config.budget, with the spend at 0", (t) => {
  const a = mk(t, { config: { budget: { attempts: 7, tokens: 700 } } });
  const s = a.add();
  assert.deepEqual([s.budget_attempts, s.budget_tokens, s.spent_attempts, s.spent_tokens], [7, 700, 0, 0]);
  const b = mk(t);
  const d = b.add({ budget_attempts: 3, budget_tokens: 30 });
  assert.deepEqual([d.budget_attempts, d.budget_tokens], [3, 30]);
  const c = mk(t);
  assert.deepEqual([c.add().budget_attempts, c.spec().budget_tokens], [60, 5000000]);
});

test("every dispatch writes budget_reserve before it, spent_attempts equals the dispatches, tokens add up", async (t) => {
  const h = mk(t);
  h.add();
  await h.finished();
  const kinds = h.events().map((e) => e.kind);
  const dispatched = h.of("dispatched");
  assert.equal(dispatched.length, 3);
  assert.equal(h.of("budget_reserve").length, 3);
  for (const d of dispatched) {
    const r = h.events().filter((e) => e.kind === "budget_reserve" && e.job === d.job)[0];
    assert.ok(r && r.seq < d.seq, `reserve before dispatch for ${d.job}`);
    assert.deepEqual([r.job, r.detail.attempt], [d.job, 1]);
  }
  assert.ok(kinds.includes("job_done"));
  assert.equal(h.spec().spent_attempts, 3);
  assert.equal(h.spec().spent_tokens, 300);
  const jobs = h.db.prepare("SELECT tokens FROM jobs").all();
  assert.deepEqual(jobs.map((j) => j.tokens), [100, 100, 100]);
  for (const e of h.of("job_done")) assert.equal(e.detail.tokens, 100);
});

test("a retry of a failed job reserves its own attempt", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }, { tokens: 10 }], review1: worker(PASS, 5), final_review: worker(PASS, 5) },
    config: { retry: { implement: { backoff_s: [0] } } } });
  h.add();
  await h.until(() => h.of("job_failed").length === 1 && h.of("dispatched").length >= 2);
  assert.equal(h.spec().spent_attempts, h.of("dispatched").length);
  assert.equal(h.of("budget_reserve").length, h.of("dispatched").length);
});

test("attempts cap reached before a dispatch: parked with options approve|fail, nothing dispatched, question with a/A and t/T", async (t) => {
  const h = mk(t, { config: { budget: { attempts: 1 } } });
  h.add();
  await h.parked();
  const w = h.wait();
  assert.equal(w.step, "core:budget:cap");
  assert.equal(w.kind, "budget");
  assert.equal(w.options, "approve|fail");
  assert.equal(w.question, "budget reached: attempts 1/1, tokens 100/5000000");
  assert.equal(h.of("dispatched").length, 1);
  assert.equal(h.of("budget_reserve").length, 1);
  // R11: the signal command offers exactly the wait's options, no deny
  const ev = h.of("awaiting_you").pop();
  assert.match(ev.detail.command, / approve\|fail$/);
  assert.ok(!/deny/.test(ev.detail.command));
});

test("cap park recommends fail / the spec is looping when the last three tasks were not clean", async (t) => {
  const h = mk(t, { tasks: tasks(2), script: { ...scriptFor(2, 100) }, config: { budget: { tokens: 300 } } });
  h.add();
  await h.parked();
  assert.deepEqual(JSON.parse(h.wait().recommendation), { option: "fail", why: "the spec is looping", confidence: "medium" });
});

test("a fix round on one of the last three completed tasks makes the cap recommendation fail", async (t) => {
  const h = mk(t, { tasks: tasks(4), script: scriptFor(4, 100), config: { budget: { tokens: 700, attempts: 99 } } });
  h.add();
  await h.until(() => h.of("task_complete").length >= 3);
  // the ledger's fix_round event of task 1, written between the third completion and the cap
  h.db.prepare("INSERT INTO events (spec, job, kind, ts, detail) VALUES (?, NULL, 'fix_round', ?, ?)").run(SPEC, h.clock.t, JSON.stringify({ task: 1, round: 1 }));
  await h.parked();
  assert.equal(h.wait().step, "core:budget:cap");
  assert.equal(h.wait().question, "budget reached: attempts 7/99, tokens 700/700");
  assert.equal(JSON.parse(h.wait().recommendation).option, "fail");
});

test("token cap crossed by scripted counts: parks before the next dispatch, approve / extend by 50% after three clean tasks", async (t) => {
  const h = mk(t, { tasks: tasks(4), script: scriptFor(4, 100), config: { budget: { tokens: 600, attempts: 99 } } });
  h.add();
  await h.parked();
  assert.equal(h.of("task_complete").length, 3);
  assert.equal(h.wait().question, "budget reached: attempts 6/99, tokens 600/600");
  assert.deepEqual(JSON.parse(h.wait().recommendation), { option: "approve", why: "extend by 50%", confidence: "medium" });
  const dispatchedBefore = h.of("dispatched").length;
  h.signal("approve");
  await h.until(() => h.of("budget_extended").length === 1);
  const ext = h.of("budget_extended")[0];
  assert.equal(h.spec().budget_tokens, 900);
  assert.equal(h.spec().budget_attempts, 99, "a cap that was not reached stays");
  assert.ok(ext.detail.cause && ext.detail.idx !== undefined, "tagged with cause and idx");
  await h.until(() => h.of("dispatched").length > dispatchedBefore);
  await h.finished();
  assert.equal(h.spec().outcome, "kept spec-demo");
});

test("approve extends both caps when both were reached (ceil of 1.5x)", async (t) => {
  const h = mk(t, { tasks: tasks(1), config: { budget: { attempts: 1, tokens: 100 } } });
  h.add();
  await h.parked();
  h.signal("approve");
  await h.until(() => h.of("budget_extended").length === 1);
  assert.deepEqual([h.spec().budget_attempts, h.spec().budget_tokens], [2, 150]);
});

test("fail on the cap park fails the spec with the note", async (t) => {
  const h = mk(t, { config: { budget: { attempts: 1 } } });
  h.add();
  await h.parked();
  h.signal("fail", "too dear");
  await h.finished();
  assert.equal(h.spec().outcome, "failed — too dear");
});

test("a job whose tokens cannot be measured parks the spec: cost unknown for job <id>; approve goes on with tokens null", async (t) => {
  const h = mk(t, { script: { implement1: worker(DONE, null), review1: worker(PASS, 5), final_review: worker(PASS, 5) } });
  h.add();
  await h.parked();
  const id = h.of("job_done")[0].job;
  assert.equal(h.wait().question, `cost unknown for job ${id}`);
  assert.equal(h.wait().step, `core:budget:unknown:${id}`);
  assert.equal(h.wait().kind, "budget");
  assert.deepEqual(JSON.parse(h.wait().recommendation), { option: "approve", why: "count it as unknown and go on", confidence: "low" });
  assert.equal(h.job(id).tokens, null);
  assert.equal(h.spec().spent_tokens, 0);
  assert.equal(h.of("job_done")[0].detail.tokens, null);
  assert.ok(h.of("job_done")[0].detail.tokens_missing);
  h.signal("approve");
  await h.finished();
  assert.equal(h.job(id).tokens, null, "left null");
  assert.equal(h.spec().spent_tokens, 10);
});

test("a backend without usage counts as unknown: the reason names it", async (t) => {
  const h = mk(t, { noUsage: true });
  h.add();
  await h.parked();
  assert.equal(h.of("job_done")[0].detail.tokens_missing, "the backend reports no usage");
});

test("R8: a failed attempt with null tokens sets lower_bound and does not park", async (t) => {
  const h = mk(t, { script: { implement1: [{ gone: true, at: 1 }, { tokens: null }], review1: worker(PASS, 5), final_review: worker(PASS, 5) },
    config: { retry: { implement: { backoff_s: [0] } } } });
  h.add();
  await h.until(() => h.of("job_failed").length === 1);
  const f = h.of("job_failed")[0];
  assert.equal(f.detail.tokens, null);
  assert.equal(f.detail.lower_bound, true);
  assert.equal(h.job(f.job).tokens, null);
  assert.notEqual(h.spec().state, "awaiting_you");
  assert.ok(!h.of("awaiting_you").some((e) => /cost unknown/.test(e.detail.question)));
});

test("the unknown-cost park is skipped when another wait is already open", async (t) => {
  const strategy = { decide: (s, ev) => {
    if (ev.kind === "spec_started") return [{ type: "start_job", kind: "implement", task: 1 }];
    if (ev.kind === "job_done") return [{ type: "park", question: "first", step: "x", kind: "cannot_tell" }];
    return [];
  } };
  const h = mk(t, { strategy, script: { implement1: worker(DONE, null) } });
  h.add();
  await h.parked();
  assert.equal(h.wait().question, "first");
  const skipped = h.of("park_skipped");
  assert.equal(skipped.length, 1);
  assert.match(skipped[0].detail.question, /^cost unknown for job /);
});

// ---- the kill between budget_reserve and the dispatch ----

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function killProject(t) {
  const env = tmpEnv();
  const repo = gitRepo();
  const w = (rel, text) => { fs.mkdirSync(path.dirname(path.join(repo.dir, rel)), { recursive: true }); fs.writeFileSync(path.join(repo.dir, rel), text); };
  w(SPEC, "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  w(PLAN, `# Demo plan\n\n**Spec:** ${SPEC}\n`);
  w(`${PLAN}.tasks.json`, JSON.stringify({ tasks: tasks(1) }));
  w("docs/superpowers/engine.json", JSON.stringify({ retry: { implement: { backoff_s: [0] } } }));
  repo.git("add", "-A"); repo.git("commit", "-q", "-m", "spec and plan");
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "ebud-wt-"));
  fs.rmSync(wt, { recursive: true });
  repo.git("worktree", "add", "-q", "-b", "spec-demo", wt);
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, "#!/bin/sh\nif [ \"$1 $2 $3\" = \"metrics has start\" ]; then exit 1; fi\necho fresh\nexit 0\n", { mode: 0o755 });
  const scriptFile = path.join(env.root, "script.json");
  fs.writeFileSync(scriptFile, JSON.stringify(scriptFor(1, 100)));
  // the first backend start of a process takes 1.5 s, so the kill lands between the reserve and the dispatch
  const preload = path.join(env.root, "slow-start.js");
  fs.writeFileSync(preload, `"use strict";
const fake = require(${JSON.stringify(path.resolve(__dirname, "../lib/engine/backend/fake.js"))});
const create = fake.createBackend;
fake.createBackend = (o) => { const b = create(o); const s = b.start; let first = true;
  b.start = async (job) => { if (first) { first = false; Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1500); } return s(job); }; return b; };
`);
  const childEnv = { ...process.env, HOME: env.root, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "demo", TC_TMUX_CTL: ctl, NODE_OPTIONS: `--require=${preload}` };
  delete childEnv.TMUX; delete childEnv.TC_SESSION;
  const peek = (fn) => {
    if (!fs.existsSync(path.join(env.engineDir, "demo.sqlite"))) return null;
    const d = dbm.open("demo");
    try { return fn(d); } finally { d.close(); }
  };
  t.after(() => { try { repo.git("worktree", "remove", "--force", wt); } catch (_) { /* gone */ } repo.cleanup(); env.restore(); });
  return { env, wt, scriptFile, childEnv, peek };
}

test("kill between budget_reserve and the dispatch, then resume: one dispatched for that job, spent_attempts equals the dispatches", async (t) => {
  const p = killProject(t);
  const tally = path.join(p.env.root, "tally.txt");
  const t0 = Date.now();
  let ok = false;
  try {
    const child = cp.spawn("node", [ENGINE, "run", SPEC, "--integration", "keep", "--batch", "b1", "--backend", "fake", "--script", p.scriptFile],
      { cwd: p.wt, env: p.childEnv, stdio: "ignore" });
    t.after(() => { try { child.kill("SIGKILL"); } catch (_) { /* gone */ } });
    const exited = new Promise((r) => child.once("exit", r));
    for (let i = 0; ; i++) {
      let seen = false;
      try { seen = !!p.peek((d) => d.prepare("SELECT 1 FROM events WHERE kind='budget_reserve'").get()); } catch (_) { /* write lock */ }
      if (seen) break;
      assert.ok(i < 4800, "budget_reserve never appeared");
      await sleep(25);
    }
    child.kill("SIGKILL"); // by pid
    await exited;
    const atKill = p.peek((d) => ({ dispatched: d.prepare("SELECT COUNT(*) AS n FROM events WHERE kind='dispatched'").get().n,
      spent: d.prepare("SELECT spent_attempts AS n FROM specs").get().n }));
    assert.deepEqual(atKill, { dispatched: 0, spent: 1 }, "the kill landed between the reserve and the dispatch");
    const r = cp.spawnSync("node", [ENGINE, "resume", "--backend", "fake", "--script", p.scriptFile], { cwd: p.wt, env: p.childEnv, encoding: "utf8", timeout: 120000 });
    assert.equal(r.status, 0, r.stderr + r.stdout);
    const end = p.peek((d) => ({
      spec: d.prepare("SELECT state, outcome, spent_attempts, spent_tokens FROM specs").get(),
      dispatched: d.prepare("SELECT job FROM events WHERE kind='dispatched'").all().map((e) => e.job),
      reserves: d.prepare("SELECT COUNT(*) AS n FROM events WHERE kind='budget_reserve'").get().n,
    }));
    assert.equal(end.spec.state, "done");
    assert.equal(end.dispatched.filter((j) => /implement1:1$/.test(j)).length, 1, "one dispatch for the killed job");
    assert.equal(end.spec.spent_attempts, end.dispatched.length, "every counted attempt is one dispatch");
    assert.equal(end.reserves, end.dispatched.length);
    ok = true;
  } finally {
    fs.appendFileSync(tally, `budget_reserve ${ok ? "ok" : "FAIL"} ${Date.now() - t0}\n`);
    if (!ok) console.log(`kill-point tally:\n${fs.readFileSync(tally, "utf8")}`);
  }
});
