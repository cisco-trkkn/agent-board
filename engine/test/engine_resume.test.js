"use strict";
// Crash, resume and isolation (spec Testing, "Crash and resume"; spec section 9): the engine CLI as real child
// processes on the fake backend, killed with SIGKILL by pid at each event kind of a run, then `engine resume`.
// Everything lives in temp dirs (TC_ENGINE_DIR, TC_STATE, HOME, a scratch git repo); a leak check compares the real
// engine dir and the real tmux server `agent-board` before and after.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const db = require("../lib/engine/db");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";

// Kinds the core writes only because it resumed (or re-arms bookkeeping for a clock that restarted): excluded from
// the sequence comparison. `resumed` and `adopted` are written only by core.resume(); `deadline` and `nudged` are the
// heartbeat re-arm rows, whose count depends on how long a job ran, not on what happened.
const RESUME_ONLY = new Set(["resumed", "adopted", "deadline", "nudged"]);

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = report({ status: "blocked", commits: [], concerns: ["needs a secret"] });
const PASS = report({ verdict: "pass", findings: [] });
const PARK = report({ decision: "park", ruling: "ask the user", cost_if_wrong: "a day" });
const worker = (text, at = 0.4) => [{ status: "busy", at: 0.1 }, { report: text, at }, { status: "ready", at: at + 0.2 }];
const GOOD = { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) };

const task = (verifyCommand = "true") => ({
  subject: "T1",
  description: `Do T1.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand, modelTier: "standard", files: ["a.js"] })}\n\`\`\``,
});

// The fake backend has no adopt (a fresh process has no memory of a worker started by a dead one), so the matrix
// preloads one into the child engines: adopt replays the job's scripted steps from now, the way the real backend finds
// a still-running pane and keeps watching it. Without it a job that was running at the kill is a gone window: a new attempt.
const ADOPT_PRELOAD = `"use strict";
const fake = require(${JSON.stringify(path.resolve(__dirname, "../lib/engine/backend/fake.js"))});
const create = fake.createBackend;
fake.createBackend = (opts) => {
  const b = create(opts);
  const adopted = new Set();
  if (process.env.ENGINE_TEST_ADOPT) b.adopt = async (job, handle) => { adopted.add(job.id); const h = await b.start(job); h.pane = handle.pane; return true; };
  const poll = b.poll;
  // an adopted pane's statuses the dead engine already took in are not sent again; the rest, and the report, are
  b.poll = () => {
    const evs = poll();
    if (!evs.some((e) => adopted.has(e.handle.job))) return evs;
    const d = require(${JSON.stringify(path.resolve(__dirname, "../lib/engine/db.js"))}).open(process.env.TC_PROJECT);
    try {
      const seen = (e) => e.type === "started" || (e.type === "status" && d.prepare("SELECT 1 FROM inbox WHERE job=? AND kind='status' AND json_extract(payload, '$.state')=?").get(e.handle.job, e.state));
      return evs.filter((e) => !(adopted.has(e.handle.job) && seen(e)));
    } finally { d.close(); }
  };
  return b;
};
`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A scratch project, as engine_cli.test.js builds one: a main checkout (branch main) and a spec worktree on branch
// spec-demo with a committed plan and its .tasks.json; a stub tmux-ctl that answers "fresh".
function project(t, o = {}) {
  const env = tmpEnv();
  const repo = gitRepo();
  const w = (rel, text) => {
    fs.mkdirSync(path.dirname(path.join(repo.dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(repo.dir, rel), text);
  };
  w(SPEC, "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  w(PLAN, `# Demo plan\n\n**Spec:** ${SPEC}\n`);
  w(`${PLAN}.tasks.json`, JSON.stringify({ tasks: o.tasks || [task()] }));
  // retries wait no time: a killed worker's second attempt starts at once
  w("docs/superpowers/engine.json", JSON.stringify({ retry: { implement: { backoff_s: [0] }, review: { backoff_s: [0] }, final_review: { backoff_s: [0] } } }));
  repo.git("add", "-A");
  repo.git("commit", "-q", "-m", "spec and plan");
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eres-wt-"));
  fs.rmSync(wt, { recursive: true });
  repo.git("worktree", "add", "-q", "-b", "spec-demo", wt);
  const ctl = path.join(env.root, "tmux-ctl");
  // o.actDelayS: `metrics start` (the act of the metrics_start step) takes that long, so a kill lands between step_intent and step_done
  // The stub logs every call and records a start in a marker file before it sleeps; `metrics has start` answers 1 until
  // that marker exists, so a start that was lost is redone and one that ran is found done.
  const slow = o.actDelayS ? `sleep ${o.actDelayS}\n` : "";
  const log = path.join(env.root, "ctl.log");
  const marker = path.join(env.root, "started");
  fs.writeFileSync(ctl, `#!/bin/sh\necho "$@" >> "${log}"\n`
    + `if [ "$1 $2" = "metrics start" ]; then touch "${marker}"; ${slow}exit 0; fi\n`
    + `if [ "$1 $2 $3" = "metrics has start" ]; then [ -f "${marker}" ] && exit 0; exit 1; fi\n`
    + `echo fresh\nexit 0\n`, { mode: 0o755 });
  const scriptFile = path.join(env.root, "script.json");
  fs.writeFileSync(scriptFile, JSON.stringify(o.script || GOOD));
  const childEnv = { ...process.env, HOME: env.root, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "demo", TC_TMUX_CTL: ctl };
  delete childEnv.TMUX;
  delete childEnv.TC_SESSION;
  const preload = path.join(env.root, "adopt-preload.js");
  // o.preDelayMs: the step starts that long after spec_added, so a kill lands before step_intent
  const delayPre = o.preDelayMs ? `const steps = require(${JSON.stringify(path.resolve(__dirname, "../lib/engine/steps.js"))});
const run = steps.run;
steps.run = (d, desc, ...rest) => { if (String(desc.key).startsWith("metrics_start:")) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ${o.preDelayMs}); return run(d, desc, ...rest); };
` : "";
  fs.writeFileSync(preload, ADOPT_PRELOAD + delayPre);
  childEnv.NODE_OPTIONS = `--require=${preload}`;
  if (o.adopt) childEnv.ENGINE_TEST_ADOPT = "1";
  const runArgs = ["run", SPEC, "--integration", "keep", "--batch", "b1", "--backend", "fake"];
  const p = {
    env, repo, wt, scriptFile, childEnv,
    starts: () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter((l) => l.startsWith("metrics start ")).length : 0),
    run(args, opts = {}) {
      const r = cp.spawnSync("node", [ENGINE, ...args], { cwd: wt, env: childEnv, encoding: "utf8", timeout: 120000, ...opts });
      return { code: r.status, out: r.stdout, err: r.stderr };
    },
    // the foreground run as a child we can kill by pid
    spawnRun(script = scriptFile) {
      const child = cp.spawn("node", [ENGINE, ...runArgs, "--script", script], { cwd: wt, env: childEnv, stdio: "ignore" });
      t.after(() => { try { child.kill("SIGKILL"); } catch (_) { /* gone */ } });
      child.exited = new Promise((r) => child.once("exit", r));
      return child;
    },
    resume: (script = scriptFile) => p.run(["resume", "--backend", "fake", "--script", script]),
    dbExists: () => fs.existsSync(path.join(env.engineDir, "demo.sqlite")),
    // a read-only look at the database; null while the engine has not created it
    peek(fn) {
      if (!p.dbExists()) return null;
      const d = db.open("demo");
      try { return fn(d); } finally { d.close(); }
    },
    kinds: () => p.peek((d) => d.prepare("SELECT kind FROM events ORDER BY seq").all().map((e) => e.kind)) || [],
    check: () => p.run(["rebuild", "--check"]),
  };
  t.after(() => {
    try { repo.git("worktree", "remove", "--force", wt); } catch (_) { /* already gone */ }
    repo.cleanup();
    env.restore();
  });
  return p;
}

// The deadline is for a run that never gets there, sized for a loaded machine: unloaded, the full run reaches its last event
// in 3.5 s (task_complete at 2.4 s), and under all.zsh's parallel load a whole kill point took 13-25 s, one stalled past 30 s.
async function until(fn, what, ms = 120000) {
  const t0 = Date.now();
  for (;;) {
    let v;
    try { v = fn(); } catch (_) { v = null; } // the engine holds a write lock for a moment
    if (v) return v;
    assert.ok(Date.now() - t0 < ms, `timed out waiting for ${what}`);
    await sleep(25);
  }
}

const plain = (v) => JSON.parse(JSON.stringify(v)); // sqlite rows have a null prototype
const distinct = (list) => [...new Set(list)];
// A core step journal row killed between its intent and its result is written again on resume (spec section 9: the
// core's own rows "are simply run again"), so a repeated step_intent in a row is one intent.
const sequence = (kinds) => kinds.filter((k) => !RESUME_ONLY.has(k)).filter((k, i, a) => !(k === "step_intent" && a[i - 1] === "step_intent"));

// ---- leak baseline ---------------------------------------------------------------------------------------------

function realEngineDir() {
  const dir = path.join(os.homedir(), ".local/state/agent-board/engine");
  try { return fs.readdirSync(dir).sort(); } catch (e) { return `absent: ${e.code}`; }
}
function realTmux() {
  const env = { ...process.env };
  delete env.TMUX;
  // session names only: window counts and attach state change under a live server
  const r = cp.spawnSync("tmux", ["-L", "agent-board", "list-sessions", "-F", "#{session_name}"], { env, encoding: "utf8" });
  return { status: r.status, names: r.status === 0 ? r.stdout.split("\n").filter(Boolean).sort() : null, err: r.status === 0 ? null : r.stderr, error: r.error ? r.error.code : null };
}
const leakBefore = { dir: realEngineDir(), tmux: realTmux() };


// ---- kill at every event kind (acceptance 1, 5) ----------------------------------------------------------------

test("kill at each distinct event kind of a run, then resume: same final state and event-kind sequence, no job twice, rebuild --check 0", async (t) => {
  // the uninterrupted run is the reference
  const ref = project(t, { adopt: true });
  const full = ref.run([...["run", SPEC, "--integration", "keep", "--batch", "b1", "--backend", "fake", "--script", ref.scriptFile]]);
  assert.equal(full.code, 0, full.err + full.out);
  const refKinds = ref.kinds();
  const refFinal = ref.peek((d) => plain({
    spec: d.prepare("SELECT state, outcome FROM specs").all(),
    jobs: d.prepare("SELECT id, state FROM jobs ORDER BY id").all(),
  }));
  const killPoints = distinct(refKinds);
  assert.ok(killPoints.length >= 8, `a full run has several event kinds, got ${killPoints.join(",")}`);

  const tally = path.join(ref.env.root, "tally.txt");
  const failures = [];
  for (const kind of killPoints) {
    await t.test(`kill after ${kind}`, async (st) => {
      const t0 = Date.now();
      let ok = false;
      try {
        const p = project(st, { adopt: true });
        const child = p.spawnRun();
        await until(() => p.kinds().includes(kind), `event ${kind}`);
        child.kill("SIGKILL"); // by pid, never a pattern
        await child.exited;
        const atKill = p.peek((d) => d.prepare("SELECT id, kind, task, state, report FROM jobs").all()) || [];
        const doneAtKill = atKill.filter((j) => j.state === "done");
        const validOnDisk = atKill.filter((j) => j.state === "running" && j.report && fs.existsSync(j.report)
          && /```json:status/.test(fs.readFileSync(j.report, "utf8")));

        const killKinds = p.kinds(); // the events at the kill, before resume writes more
        const r = p.resume();
        assert.equal(r.code, 0, `resume after ${kind}: ${r.err}${r.out}`);

        const final = p.peek((d) => plain({
          spec: d.prepare("SELECT state, outcome FROM specs").all(),
          jobs: d.prepare("SELECT id, kind, task, state FROM jobs ORDER BY id").all(),
        }));
        assert.deepEqual(final.spec, refFinal.spec, "same final spec state and outcome");
        assert.deepEqual(final.jobs.map((j) => ({ id: j.id, state: j.state })), refFinal.jobs, "same jobs, same states");
        // The core runs the metrics start itself (the first tick, before spec_started), so a kill at any point leaves it
        // either done, at intent (reconciled on resume) or not yet started (run by the first tick): the pair is never lost.
        const want = sequence(refKinds);
        assert.deepEqual(want.slice(0, 3), ["spec_added", "step_intent", "step_done"], "the reference starts with the metrics start pair");
        // The same holds at the other end: the pane close_window step runs after spec_done, outside the spec's own work. Once
        // spec_done is committed the spec is done and `engine resume` has nothing to resume (cli.js: "nothing to resume"),
        // so a kill before that step's step_done leaves it unfinished and resume does not redo it. Harmless: the window stays
        // for the user. Only that trailing step may be lost, and only when the kill is at spec_done.
        const afterDone = killKinds.slice(killKinds.lastIndexOf("spec_done") + 1);
        const lostClose = kind === "spec_done" && afterDone.length <= 1 && afterDone.every((k) => k === "step_intent");
        if (lostClose) {
          assert.deepEqual(want.slice(-3), ["spec_done", "step_intent", "step_done"], "the reference ends with the close_window pair");
          want.splice(want.length - (2 - afterDone.length), 2 - afterDone.length);
        }
        assert.deepEqual(sequence(p.kinds()), want, "same event-kind sequence, resume-only kinds excluded");

        // no job with a valid report runs twice: one `dispatched` event per job id, and no later attempt of a job
        // that was done (or whose valid report was on disk) when the engine died
        const dispatched = p.peek((d) => d.prepare("SELECT job FROM events WHERE kind='dispatched'").all().map((e) => e.job));
        for (const j of final.jobs) assert.equal(dispatched.filter((x) => x === j.id).length, 1, `${j.id} dispatched once`);
        for (const j of [...doneAtKill, ...validOnDisk]) {
          assert.equal(final.jobs.filter((x) => x.kind === j.kind && x.task === j.task).length, 1, `${j.id} had a report and got no second attempt`);
        }
        const c = p.check();
        assert.equal(c.code, 0, `rebuild --check after ${kind}: ${c.out}${c.err}`);
        ok = true;
      } finally {
        fs.appendFileSync(tally, `${kind} ${ok ? "ok" : "FAIL"} ${Date.now() - t0}\n`);
        if (!ok) failures.push(kind);
      }
    });
  }
  const text = fs.readFileSync(tally, "utf8");
  if (failures.length) console.log(`kill-point tally:\n${text}`);
  assert.deepEqual(failures, [], `kill points that failed:\n${text}`);
});

// ---- the metrics start window (run by the core's first tick, after spec_added) --------------------------------------
// Mutation for both: the core's metricsStart not called from startQueued (fails the first: no start call after resume), and
// the check of a metrics_start intent row answering "not_done" always (fails the second: two start calls).

test("kill between spec_added and the metrics start step: resume runs the start, exactly one call", async (t) => {
  const p = project(t, { adopt: true, preDelayMs: 2000 });
  const child = p.spawnRun();
  await until(() => p.kinds().includes("spec_added"), "spec_added");
  child.kill("SIGKILL");
  await child.exited;
  assert.deepEqual(p.kinds(), ["spec_added"], "killed before step_intent");
  assert.equal(p.starts(), 0, "no start call before the resume");
  const r = p.resume();
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: kept spec-demo$/);
  assert.equal(p.starts(), 1, "exactly one metrics start call after the resume");
  assert.deepEqual(p.kinds().filter((k) => k !== "resumed").slice(0, 3), ["spec_added", "step_intent", "step_done"]);
  assert.equal(p.peek((d) => d.prepare("SELECT state FROM steps WHERE kind='metrics_start'").get().state), "done");
  assert.equal(p.check().code, 0);
});

test("kill between step_intent and step_done of the metrics start: resume reconciles the intent row to done, no second start", async (t) => {
  const p = project(t, { adopt: true, actDelayS: 2 });
  const child = p.spawnRun();
  await until(() => p.kinds().includes("step_intent"), "step_intent");
  await until(() => p.starts() === 1, "the start call");
  child.kill("SIGKILL");
  await child.exited;
  assert.deepEqual(p.kinds(), ["spec_added", "step_intent"], "killed inside the act");
  const r = p.resume();
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: kept spec-demo$/);
  // the check (`metrics has start`, answered "done" because the start ran) closes the row: step_done at position 2, no second intent
  assert.deepEqual(p.kinds().slice(0, 3), ["spec_added", "step_intent", "step_done"]);
  const row = p.peek((d) => d.prepare("SELECT state, result FROM steps WHERE kind='metrics_start'").all());
  assert.equal(row.length, 1);
  assert.equal(row[0].state, "done");
  assert.equal(JSON.parse(row[0].result).reconciled, true, "closed by reconcile, not by a rerun");
  assert.equal(p.starts(), 1, "exactly one metrics start call in all");
  assert.equal(p.check().code, 0);
});

// ---- no adopt: a window that died with the engine is a new attempt (spec section 9) ---------------------------------

test("without adopt a worker running at the kill gets a second attempt; jobs with a report are not run again; same outcome", async (t) => {
  const p = project(t); // no adopt: the fake cannot find the dead engine's worker
  const hang = path.join(p.env.root, "hang-once.json");
  fs.writeFileSync(hang, JSON.stringify({ implement1: [{ hang: true, at: 0.1 }] }));
  const child = p.spawnRun(hang);
  await until(() => p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM jobs WHERE state='running'").get().n), "a running job");
  child.kill("SIGKILL");
  await child.exited;
  const r = p.resume(); // the full script: the second attempt finishes
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: kept spec-demo$/);
  const jobs = plain(p.peek((d) => d.prepare("SELECT id, kind, state FROM jobs ORDER BY id").all()));
  assert.deepEqual(jobs.filter((j) => j.kind === "implement").map((j) => [j.id, j.state]),
    [["demo:implement1:1", "failed"], ["demo:implement1:2", "done"]]);
  for (const k of ["review", "final_review"]) assert.equal(jobs.filter((j) => j.kind === k).length, 1, `${k} ran once`);
  assert.equal(p.check().code, 0);
});

// ---- signals (acceptance 2) ------------------------------------------------------------------------------------

test("a signal written before the kill and one written after the resume written after the resume are each applied once", async (t) => {
  const script = {
    implement1: worker(BLOCKED), implement2: worker(BLOCKED),
    architect: worker(PARK), architect1: worker(PARK), architect2: worker(PARK),
    review1: worker(PASS), review2: worker(PASS), final_review: worker(PASS),
  };
  const p = project(t, { tasks: [task(), { ...task(), subject: "T2" }], script });
  const sf = path.join(p.env.root, "park.json");
  fs.writeFileSync(sf, JSON.stringify(script));
  const child = p.spawnRun(sf);
  const waiting = () => p.peek((d) => d.prepare("SELECT * FROM waits WHERE answered_at IS NULL").all()).length === 1;
  await until(waiting, "the first park");

  // signal one: written to the live engine, which is SIGKILLed as soon as the inbox row exists (applied or not yet)
  const s1 = p.run(["signal", SPEC, "approve", "--note", "one"]);
  assert.equal(s1.code, 0, s1.err);
  assert.doesNotMatch(s1.out, /no engine is running/, "signal one must reach a live engine");
  await until(() => p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM inbox WHERE source='user'").get().n) >= 1, "signal one in the inbox");
  child.kill("SIGKILL");
  await child.exited;

  // resume in the background, wait for it to apply signal one and park again, then write signal two to the live engine
  const res = cp.spawn("node", [ENGINE, "resume", "--backend", "fake", "--script", sf], { cwd: p.wt, env: p.childEnv, stdio: "ignore" });
  t.after(() => { try { res.kill("SIGKILL"); } catch (_) { /* gone */ } });
  const resExit = new Promise((r) => res.once("exit", r));
  await until(() => p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM waits WHERE answered_at IS NOT NULL").get().n >= 1
    && d.prepare("SELECT COUNT(*) AS n FROM waits WHERE answered_at IS NULL").get().n === 1), "the second park after signal one");
  const s2 = p.run(["signal", SPEC, "approve", "--note", "two"]);
  assert.equal(s2.code, 0, s2.err);
  assert.equal(await resExit, 0);

  const sig = p.peek((d) => d.prepare("SELECT detail FROM events WHERE kind='signal' ORDER BY seq").all().map((e) => JSON.parse(e.detail).note));
  assert.deepEqual(sig, ["one", "two"], "each signal applied once, in order");
  const inboxUser = p.peek((d) => d.prepare("SELECT state FROM inbox WHERE source='user'").all().map((r) => r.state));
  assert.deepEqual(inboxUser, ["done", "done"]);
  assert.equal(p.peek((d) => d.prepare("SELECT state FROM specs").get().state), "done");
  assert.equal(p.check().code, 0);
});

// ---- timers (acceptance 3) -------------------------------------------------------------------------------------

test("a deadline and a usage_reset timer due while the engine was down fire once each on resume", async (t) => {
  const p = project(t);
  const hang = path.join(p.env.root, "hang.json");
  fs.writeFileSync(hang, JSON.stringify({ implement1: [{ hang: true, at: 0.1 }], review1: worker(PASS), final_review: worker(PASS) }));
  const child = p.spawnRun(hang);
  await until(() => p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM jobs WHERE state='running'").get().n), "a running job");
  child.kill("SIGKILL");
  await child.exited;

  // while down: the job's deadline timer and a usage_reset timer both fall due (written the way the core writes them)
  const ids = p.peek((d) => {
    const dl = d.prepare("SELECT * FROM timers WHERE kind='deadline' AND fired_at IS NULL ORDER BY due_at LIMIT 1").get();
    assert.ok(dl, "a pending deadline timer");
    const spec = d.prepare("SELECT id FROM specs").get().id;
    db.tx(d, () => {
      const row = db.put(d, "timers", { ...dl, due_at: 1 });
      const usage = db.put(d, "timers", { id: "usage:test", spec, job: null, kind: "usage_reset", due_at: 2, payload: null, fired_at: null });
      db.event(d, { spec, job: dl.job, kind: "test_arm", rows: [{ table: "timers", row }, { table: "timers", row: usage }] });
    });
    return { deadline: dl.id, usage: "usage:test" };
  });

  const r = p.resume(p.scriptFile); // the resumed worker is scripted to finish
  assert.equal(r.code, 0, r.err + r.out);
  const fired = p.peek((d) => d.prepare("SELECT * FROM events WHERE kind='timer_fired'").all().map((e) => ({ job: e.job, rows: JSON.parse(e.detail).rows })));
  for (const id of Object.values(ids)) {
    const n = fired.filter((f) => f.rows.some((x) => x.table === "timers" && x.row.id === id)).length;
    assert.equal(n, 1, `timer ${id} fired once`);
  }
  assert.equal(p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM events WHERE kind='usage_resumed'").get().n), 1, "the usage pause ended once");
  assert.equal(p.peek((d) => d.prepare("SELECT COUNT(*) AS n FROM timers WHERE fired_at IS NULL AND id IN (?, ?)").get(ids.deadline, ids.usage).n), 0);
  assert.equal(p.check().code, 0);
});

// ---- leak check (acceptance 4) ---------------------------------------------------------------------------------
// Last in the file: node:test runs a file's top-level tests in order.

test("leak check: the real engine dir and the real agent-board tmux server are unchanged", () => {
  assert.deepEqual(realEngineDir(), leakBefore.dir, "the real engine dir changed");
  assert.deepEqual(realTmux(), leakBefore.tmux, "the real agent-board tmux server changed");
});
