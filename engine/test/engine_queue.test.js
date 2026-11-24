"use strict";
// The queue runner (spec section 6): engine enqueue, start and done, gates, and the lead-lines file.
// Child-process scenarios run the real CLI on the fake backend, a scratch git repo and a temp TC_ENGINE_DIR; the
// in-process ones drive core + queue.step with an injected clock. Nothing here opens ~/.local/state/agent-board.
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
const steps = require("../lib/engine/steps");
const rebuild = require("../lib/engine/rebuild");
const queue = require("../lib/engine/queue");
const lead = require("../lib/engine/lead");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const SPEC_A = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN_A = "docs/superpowers/plans/2026-01-01-demo.md";
const SPEC_L = "docs/superpowers/specs/2026-01-03-lead-design.md";
const SPEC_G = "docs/superpowers/specs/2026-01-04-gated-design.md";
const GATE_LINE = "gate K9: no-go (3 of 8 specs)";

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const PASS = report({ verdict: "pass", findings: [] });
const worker = (text, k = 0.1) => [{ status: "busy", at: k }, { report: text, at: 3 * k }, { status: "ready", at: 5 * k }];
const GOOD = (k) => ({ implement1: worker(DONE, k), review1: worker(PASS, k), final_review: worker(PASS, k) });
const task = (meta = {}) => ({
  subject: "T1",
  description: `Do T1.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"], ...meta })}\n\`\`\``,
});
// A stub tmux-ctl: logs its arguments; `metrics gate <id>` prints two lines and exits by the file gate.rc (default 1).
const ctlStub = (root) => `#!/bin/sh\necho "$@" >> "${root}/ctl.log"\n` +
  `if [ "$1 $2" = "metrics gate" ]; then echo "gate $3: no-go (3 of 8 specs)"; echo "a second line"; exit $(cat "${root}/gate.rc" 2>/dev/null || echo 1); fi\n` +
  "echo fresh\nexit 0\n";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const leadFile = (engineDir) => path.join(engineDir, "demo.lead.jsonl");
const readLines = (file) => (fs.existsSync(file) ? fs.readFileSync(file, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);

// ---- the child-process fixture -----------------------------------------------------------------------------------

function project(t, o = {}) {
  const env = tmpEnv();
  const repo = gitRepo();
  const w = (rel, text) => {
    fs.mkdirSync(path.dirname(path.join(repo.dir, rel)), { recursive: true });
    fs.writeFileSync(path.join(repo.dir, rel), text);
  };
  w(SPEC_A, "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  w(PLAN_A, `# Demo plan\n\n**Spec:** ${SPEC_A}\n`);
  w(`${PLAN_A}.tasks.json`, JSON.stringify({ tasks: o.tasks || [task()] }));
  w(SPEC_L, "# Lead-run\n");
  w(SPEC_G, "# Gated\n");
  repo.git("add", "-A");
  repo.git("commit", "-q", "-m", "specs and plan");
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eq-wt-"));
  fs.rmSync(wt, { recursive: true });
  repo.git("worktree", "add", "-q", "-b", "spec-demo", wt);
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, ctlStub(env.root), { mode: 0o755 });
  const scriptFile = path.join(env.root, "script.json");
  fs.writeFileSync(scriptFile, JSON.stringify(GOOD(0.1)));
  const childEnv = { ...process.env, HOME: env.root, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "demo", TC_TMUX_CTL: ctl };
  for (const k of ["TMUX", "TC_SESSION", "NODE_TEST_CONTEXT"]) delete childEnv[k];
  const children = [];
  const p = {
    env, repo, wt, childEnv,
    run(args, opts = {}) {
      const r = cp.spawnSync("node", [ENGINE, ...args], { cwd: opts.cwd || wt, env: childEnv, encoding: "utf8", timeout: 60000 });
      // node:sqlite prints an experimental warning on stderr whenever a subcommand opens the database: not the engine's text
      const err = r.stderr.split("\n").filter((l) => !/ExperimentalWarning: SQLite|--trace-warnings/.test(l)).join("\n");
      return { code: r.status, out: r.stdout, err };
    },
    enqueue: (spec, runner, extra = [], opts) => p.run(["enqueue", spec, "--runner", runner, "--integration", "keep", "--batch", "b1", ...extra], opts),
    // `engine start` in the background: {child, out(), exit: Promise<code>}
    start() {
      const child = cp.spawn("node", [ENGINE, "start", "--here", "--backend", "fake", "--script", scriptFile], { cwd: wt, env: childEnv, stdio: ["ignore", "pipe", "pipe"] });
      let out = "";
      child.stdout.on("data", (b) => { out += b; });
      child.stderr.on("data", (b) => { out += b; });
      children.push(child);
      return { child, out: () => out, exit: new Promise((r) => child.once("exit", (code) => r(code))) };
    },
    ctlLog: () => (fs.existsSync(path.join(env.root, "ctl.log")) ? fs.readFileSync(path.join(env.root, "ctl.log"), "utf8").split("\n").filter(Boolean) : []),
    lines: () => readLines(leadFile(env.engineDir)),
    // reads through a fresh connection; the engine holds a write lock only for a moment
    read(fn) { const d = db.open("demo"); try { return fn(d); } finally { d.close(); } },
    events: (kind) => p.read((d) => d.prepare("SELECT * FROM events WHERE kind=? ORDER BY seq").all(kind)),
    spec: (id) => p.read((d) => d.prepare("SELECT * FROM specs WHERE id=?").get(id)),
    async until(pred, what, ms = 30000) {
      const t0 = Date.now();
      for (;;) {
        let ok = false;
        try { ok = pred(); } catch (_) { ok = false; }
        if (ok) return;
        assert.ok(Date.now() - t0 < ms, `not reached in ${ms} ms: ${what}`);
        await sleep(100);
      }
    },
    yourTurn: (spec) => p.lines().filter((l) => l.text === `[Engine] your turn: ${spec}`),
  };
  t.after(() => {
    for (const c of children) { try { c.kill("SIGKILL"); } catch (_) { /* gone */ } }
    try { repo.git("worktree", "remove", "--force", wt); } catch (_) { /* already gone */ }
    repo.cleanup();
    env.restore();
  });
  return p;
}

// ---- the three-spec queue ----------------------------------------------------------------------------------------

// Mutations: "startQueued takes the lowest id, not the lowest position" -> the order assertion; "onDone dropped" -> the
// lead-run spec never ends; "the gate's exit code ignored" -> a lead_turn for the gated spec; "metrics start also for
// runner lead" (R17) -> a second `metrics start` line; "status --unfinished ignores the state" -> the last exit code.
test("a queue of an engine, a lead and a gated spec runs in order: kept, engine done, the gate failure; start exits 0", async (t) => {
  const p = project(t);
  assert.equal(p.run(["status", "--unfinished"]).code, 1, "no database: nothing unfinished");
  const qa = p.enqueue(SPEC_A, "engine");
  assert.equal(qa.code, 0, qa.err);
  assert.equal(qa.out.trim(), `queued ${SPEC_A} (engine)`);
  assert.equal(p.enqueue(SPEC_L, "lead").out.trim(), `queued ${SPEC_L} (lead)`);
  assert.equal(p.enqueue(SPEC_G, "lead", ["--gate", "K9"]).code, 0);
  const un0 = p.run(["status", "--unfinished"]);
  assert.deepEqual([un0.code, un0.out], [1, ""], "rows still in the inbox are not an unfinished queue");
  const early = p.run(["done", SPEC_L, "--outcome", "merged abc1234"]);
  assert.equal(early.code, 2);
  assert.match(early.err, new RegExp(`no lead turn open for ${SPEC_L}`));

  const s = p.start();
  await p.until(() => p.yourTurn(SPEC_L).length === 1, "the your-turn line of the lead-run spec");
  await sleep(500); // a few more ticks: the engine waits
  assert.equal(p.spec(SPEC_A).outcome, "kept spec-demo");
  assert.deepEqual([p.spec(SPEC_L).state, p.spec(SPEC_L).runner, p.spec(SPEC_L).outcome], ["running", "lead", null]);
  assert.equal(p.spec(SPEC_G).state, "queued", "the gated spec waits for the lead-run spec's turn to end");
  assert.equal(s.child.exitCode, null, "engine start is still running");
  const mid = p.run(["status", "--unfinished"]);
  assert.equal(mid.code, 0, "mid-queue");
  assert.deepEqual(mid.out.trim().split("\n"), [SPEC_L, SPEC_G]);
  const notLead = p.run(["done", SPEC_G, "--outcome", "merged"]);
  assert.equal(notLead.code, 2, "a queued spec is not at a lead turn");

  const d = p.run(["done", SPEC_L, "--outcome", "merged abc1234"]);
  assert.equal(d.code, 0, d.err);
  assert.equal(await s.exit, 0, s.out());

  assert.deepEqual([p.spec(SPEC_L).state, p.spec(SPEC_L).outcome], ["done", "merged abc1234"]);
  assert.deepEqual([p.spec(SPEC_G).state, p.spec(SPEC_G).outcome], ["done", `failed — gate K9: ${GATE_LINE}`]);
  // the run order is the queue order
  const seq = (kind, spec) => p.events(kind).filter((e) => e.spec === spec).map((e) => e.seq);
  const order = [seq("spec_started", SPEC_A), seq("spec_done", SPEC_A), seq("lead_turn", SPEC_L), seq("spec_done", SPEC_L), seq("gate_result", SPEC_G), seq("fail_spec", SPEC_G)];
  assert.deepEqual(order.map((x) => x.length), [1, 1, 1, 1, 1, 1], "one of each");
  assert.deepEqual(order.flat(), order.flat().slice().sort((a, b) => a - b), "in queue order");
  assert.equal(p.events("lead_turn").length, 1, "no lead_turn for the gated spec");
  const gate = JSON.parse(p.events("gate_result")[0].detail);
  assert.deepEqual([gate.gate, gate.rc, gate.line], ["K9", 1, GATE_LINE]);
  assert.equal(p.read((x) => x.prepare("SELECT policy_version FROM specs WHERE id=?").get(SPEC_L).policy_version), null, "R7: a lead-run spec has no policy version");
  // the lead-lines file: your turn once, at its event's seq
  assert.deepEqual(p.lines().map((l) => [l.seq, l.text]), [[seq("lead_turn", SPEC_L)[0], `[Engine] your turn: ${SPEC_L}`],
    [p.events("queue_finished")[0].seq, "[Engine] queue finished: (no report)"]]);
  assert.ok(p.events("queue_finished")[0].seq > seq("fail_spec", SPEC_G)[0], "queue_finished is the queue's last event");
  assert.equal(typeof p.lines()[0].ts, "number");
  // metrics: start once, through the core's step, for the engine spec only (R17); the gate failure is recorded
  const log = p.ctlLog();
  assert.deepEqual(log.filter((l) => l.startsWith("metrics start ")).map((l) => l.split(" ")[2]), [SPEC_A]);
  assert.equal(p.read((x) => x.prepare("SELECT state FROM steps WHERE key=?").get(`metrics_start:${SPEC_A}`).state), "done");
  assert.deepEqual(log.filter((l) => l.startsWith("metrics gate ")), ["metrics gate K9"]);
  assert.equal(log.filter((l) => l.startsWith(`metrics record ${SPEC_G} --batch b1 --outcome failed — gate K9: `)).length, 1, log.join("\n"));
  assert.equal(log.filter((l) => l.startsWith(`metrics record ${SPEC_L} `)).length, 0, "the lead records its own spec");
  // afterwards
  // the queue_finished event closed the queue
  assert.equal(p.events("queue_finished").length, 1);
  const closed = p.run(["status", "--unfinished"]);
  assert.deepEqual([closed.code, closed.out], [1, ""]);
  assert.equal(p.run(["done", SPEC_L, "--outcome", "merged"]).code, 2, "the turn is over");
  const pre = p.run(["start", "--preflight"]);
  assert.equal(pre.code, 1, "nothing queued, nothing unfinished");
  assert.equal(pre.err.trim().split("\n").length, 1, "one reason line");
  const chk = p.run(["rebuild", "--check"]);
  assert.equal(chk.code, 0, chk.out);
});

// ---- enqueue -----------------------------------------------------------------------------------------------------

// Mutation: "source_id is a fresh uuid" -> two rows for one spec and batch.
test("enqueue twice for one spec and batch is one inbox row, and writes no table but inbox", (t) => {
  const p = project(t);
  p.read(() => null); // creates the schema
  const tables = () => p.read((d) => Object.fromEntries(d.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all()
    .map((r) => [r.name, d.prepare(`SELECT COUNT(*) AS n FROM ${r.name}`).get().n])));
  const before = tables();
  assert.equal(p.enqueue(SPEC_A, "engine", ["--push", "--budget-attempts", "20", "--budget-tokens", "1000"]).code, 0);
  assert.equal(p.enqueue(SPEC_A, "engine").code, 0);
  const after = tables();
  assert.equal(after.inbox, 1);
  assert.deepEqual({ ...after, inbox: 0 }, { ...before, inbox: 0 }, "every other table is untouched");
  const row = p.read((d) => d.prepare("SELECT * FROM inbox").get());
  assert.deepEqual([row.source, row.source_id, row.spec, row.kind, row.state], ["user", `enqueue:${SPEC_A}@b1`, SPEC_A, "enqueue", "new"]);
  const pl = JSON.parse(row.payload);
  assert.deepEqual([pl.runner, pl.integration, pl.push, pl.batch, pl.plan, pl.branch, pl.budget_attempts, pl.budget_tokens],
    ["engine", "keep", 1, "b1", PLAN_A, "spec-demo", 20, 1000]);
  assert.equal(fs.realpathSync(pl.worktree), fs.realpathSync(p.wt));
});

test("enqueue: bad arguments exit 2 and write nothing; a spec already in specs exits 1", (t) => {
  const p = project(t);
  const bad = [
    ["enqueue", SPEC_A, "--integration", "keep", "--batch", "b1"], // no runner
    ["enqueue", SPEC_A, "--runner", "robot", "--integration", "keep", "--batch", "b1"],
    ["enqueue", SPEC_A, "--runner", "engine", "--integration", "squash", "--batch", "b1"],
    ["enqueue", SPEC_A, "--runner", "engine", "--integration", "keep"], // no batch
    ["enqueue", "--runner", "engine", "--integration", "keep", "--batch", "b1"], // no spec
    ["enqueue", SPEC_A, "--runner", "engine", "--integration", "keep", "--batch", "b1", "--budget-tokens", "0"],
    ["enqueue", SPEC_A, "--runner", "engine", "--integration", "keep", "--batch", "b1", "--bogus"],
  ];
  for (const a of bad) {
    const r = p.run(a);
    assert.equal(r.code, 2, `${a.join(" ")}: ${r.err}`);
    assert.match(r.err, /^engine: enqueue: /);
  }
  assert.equal(fs.existsSync(path.join(p.env.engineDir, "demo.sqlite")), false, "nothing was created");
  p.read((d) => d.prepare("INSERT INTO specs (id, state, integration) VALUES (?, 'done', 'keep')").run(SPEC_A));
  const dup = p.enqueue(SPEC_A, "engine");
  assert.equal(dup.code, 1);
  assert.match(dup.err, /already in the database \(done\)/);
  assert.equal(p.read((d) => d.prepare("SELECT COUNT(*) AS n FROM inbox").get().n), 0);
});

// Mutation: "enqueue exits 3 as engine run does for a plan it cannot run" -> the exit code and the missing row.
test("enqueue: a plan without a verifyCommand is queued for the lead with the stated line, and gets [Engine] your turn at its turn", async (t) => {
  const p = project(t);
  fs.writeFileSync(path.join(p.wt, `${PLAN_A}.tasks.json`), JSON.stringify({ tasks: [{ subject: "T1", description: "no metadata" }] }));
  const q = p.enqueue(SPEC_A, "engine");
  assert.equal(q.code, 0, q.err);
  assert.equal(q.err.trim(), `engine: enqueue: ${PLAN_A}: no verifyCommand: task 1: queued for the lead`);
  assert.equal(q.out.trim(), `queued ${SPEC_A} (lead)`);
  // history from before this start (an engine run long ago) and no lead file. Mutation: "engine start does not call
  // lead.begin" -> the old stopped: line is the file's first line.
  p.read((x) => db.event(x, { kind: "engine_error", error: "an old error", ts: 1 }));
  const s = p.start();
  await p.until(() => p.yourTurn(SPEC_A).length === 1, "the your-turn line");
  assert.deepEqual(p.lines().map((l) => l.text), [`[Engine] your turn: ${SPEC_A}`], "nothing from before this start");
  assert.equal(p.spec(SPEC_A).runner, "lead");
  const handed = p.events("handed_to_lead");
  assert.equal(handed.length, 1);
  assert.equal(JSON.parse(handed[0].detail).reason, `${PLAN_A}: no verifyCommand: task 1`);
  assert.equal(p.events("spec_started").length, 0, "the strategy never saw it");
  assert.equal(p.run(["done", SPEC_A, "--outcome", "failed — no plan"]).code, 0);
  assert.equal(await s.exit, 0, s.out());
  assert.equal(p.events("fail_spec").length, 1, "a failed outcome from engine done is a fail_spec");
  assert.equal(p.ctlLog().filter((l) => l.startsWith("metrics start")).length, 0, "R17: the lead runs metrics start");
  assert.equal(p.run(["rebuild", "--check"]).code, 0);
});

test("enqueue: no .tasks.json, no plan naming the spec, a missing spec file and --gate with --runner engine are all queued for the lead", (t) => {
  const p = project(t);
  const other = "docs/superpowers/specs/2026-01-09-orphan-design.md";
  fs.writeFileSync(path.join(p.wt, other), "# Orphan\n");
  const a = p.enqueue(other, "engine");
  assert.deepEqual([a.code, a.out.trim()], [0, `queued ${other} (lead)`]);
  assert.match(a.err, /^engine: enqueue: no plan names .*: queued for the lead\n$/);
  const b = p.enqueue("docs/superpowers/specs/nope.md", "engine");
  assert.equal(b.code, 0);
  assert.match(b.err, /^engine: enqueue: no such spec file: .*: queued for the lead\n$/);
  const c = p.enqueue(SPEC_A, "engine", ["--gate", "K2"]);
  assert.equal(c.code, 0);
  assert.match(c.err, /^engine: enqueue: a gated spec runs under the lead: queued for the lead\n$/);
  fs.rmSync(path.join(p.wt, `${PLAN_A}.tasks.json`));
  const d = p.run(["enqueue", SPEC_A, "--runner", "engine", "--integration", "keep", "--batch", "b2"]);
  assert.equal(d.code, 0);
  assert.match(d.err, /no \.tasks\.json: queued for the lead/);
  const runners = p.read((x) => x.prepare("SELECT payload FROM inbox ORDER BY id").all().map((r) => JSON.parse(r.payload).runner));
  assert.deepEqual(runners, ["lead", "lead", "lead", "lead"]);
});

// ---- preflight ---------------------------------------------------------------------------------------------------

// Mutation: "preflight skips the lock" -> exit 0 while another engine holds it.
test("start --preflight: 4 while another engine holds the lock, 0 with a pending enqueue row, 1 with nothing to do", (t) => {
  const p = project(t);
  const none = p.run(["start", "--preflight"]);
  assert.equal(none.code, 1);
  assert.match(none.err, /^engine: start: nothing queued/);
  assert.equal(p.enqueue(SPEC_L, "lead").code, 0);
  assert.deepEqual(((r) => [r.code, r.out, r.err])(p.run(["start", "--preflight"])), [0, "", ""]);
  fs.writeFileSync(path.join(p.env.engineDir, "demo.lock"), `${process.pid}\n`); // this test process is alive
  // R5: an engine that already runs is exit 4 for the preflight too (the wrapper counts 0 and 4 as started).
  // Mutation: "preflight answers 1 for a held lock" -> this assertion.
  const held = p.run(["start", "--preflight"]);
  assert.equal(held.code, 4);
  assert.match(held.err, /^engine: start: an engine is already running/);
  assert.equal(held.err.trim().split("\n").length, 1);
  // R5. Mutation: "engine start leaves the held lock to the core's throw" -> exit 1.
  const second = p.run(["start", "--here", "--backend", "fake"]);
  assert.equal(second.code, 4, second.err);
  assert.match(second.err, /^engine: start: an engine is already running/);
  assert.equal(p.read((d) => d.prepare("SELECT COUNT(*) AS n FROM inbox WHERE state='new'").get().n), 1, "the second start drained nothing");
  fs.rmSync(path.join(p.env.engineDir, "demo.lock"));
  assert.equal(p.run(["start", "--preflight"]).code, 0);
  assert.equal(p.read((d) => d.prepare("SELECT COUNT(*) AS n FROM events").get().n), 0, "preflight only checks");
  assert.equal(p.run(["done", SPEC_L]).code, 2, "done without --outcome");
});

// ---- kill and restart --------------------------------------------------------------------------------------------

// Mutation: "lead.publish starts its cursor at 0" -> a second your-turn line after the restart; "startQueued ignores
// a running lead-run spec" -> a second lead_turn.
test("engine start killed while a lead turn is open, then started again: no second lead_turn, no second line, and engine done completes the queue", async (t) => {
  const p = project(t);
  assert.equal(p.enqueue(SPEC_L, "lead").code, 0);
  assert.equal(p.enqueue(SPEC_A, "engine").code, 0);
  const one = p.start();
  await p.until(() => p.yourTurn(SPEC_L).length === 1, "the your-turn line");
  one.child.kill("SIGKILL");
  await one.exit;
  assert.equal(p.run(["start", "--preflight"]).code, 0, "an unfinished queue and a dead lock holder");
  const two = p.start();
  await p.until(() => p.events("resumed").length === 1, "the second engine resumed");
  await sleep(600);
  assert.equal(two.child.exitCode, null, "the second engine waits at the lead turn");
  assert.equal(p.events("lead_turn").length, 1);
  assert.equal(p.yourTurn(SPEC_L).length, 1);
  assert.equal(p.run(["done", SPEC_L, "--outcome", "merged abc1234"]).code, 0);
  assert.equal(await two.exit, 0, two.out());
  assert.equal(p.spec(SPEC_L).outcome, "merged abc1234");
  assert.equal(p.spec(SPEC_A).outcome, "kept spec-demo");
  assert.equal(p.events("lead_turn").length, 1);
  assert.deepEqual(p.lines().map((l) => l.text), [`[Engine] your turn: ${SPEC_L}`, "[Engine] queue finished: (no report)"]);
  assert.equal(p.run(["rebuild", "--check"]).code, 0);
});

// ---- in-process: core + queue.step with an injected clock --------------------------------------------------------

function mkq(t, o = {}) {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eq-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  const tasksFile = path.join(wt, `${PLAN_A}.tasks.json`);
  fs.writeFileSync(tasksFile, JSON.stringify({ tasks: o.tasks || [task()] }));
  fs.writeFileSync(path.join(wt, SPEC_A), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, ctlStub(env.root), { mode: 0o755 });
  if (o.gateRc !== undefined) fs.writeFileSync(path.join(env.root, "gate.rc"), String(o.gateRc));
  const clock = { t: Date.UTC(2026, 0, 1, 20, 0, 0) / 1000 };
  const script = o.script || GOOD(1);
  const boot = () => core.start({
    project: "demo", repo: wt, backend: fake.createBackend({ script, now: () => clock.t }), now: () => clock.t, tmuxCtl: ctl,
    integrate: o.integrate || (async () => ({ outcome: "kept spec-demo" })), revert: async () => {}, finalize: async () => {},
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const h = {
    env, wt, clock, script, tasksFile, eng: boot(),
    reboot() { h.eng.stop(); h.eng = boot(); return h.eng; },
    enqueue: (spec, payload = {}) => queue.enqueue(h.eng.db, spec, { runner: "engine", integration: "keep", push: 0, batch: "b1", worktree: wt, branch: "spec-demo", plan: PLAN_A, ...payload }, clock.t),
    lead: (spec, payload = {}) => queue.enqueue(h.eng.db, spec, { runner: "lead", integration: "keep", push: 0, batch: "b1", worktree: null, branch: null, plan: null, ...payload }, clock.t),
    async step(n = 1, dt = 5) { for (let i = 0; i < n; i++) { clock.t += dt; await queue.step(h.eng, "demo"); } },
    async until(pred, max = 400) {
      for (let i = 0; i < max; i++) { if (pred()) return; await h.step(); }
      assert.fail(`not reached after ${max} ticks; events: ${h.kinds().join(" ")}`);
    },
    events: () => h.eng.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    kinds: () => h.events().map((e) => e.kind).filter((k) => !/^(inbox_|timer_fired$|deadline$|step_|job_session$)/.test(k)),
    of: (kind) => h.events().filter((e) => e.kind === kind),
    spec: (id) => h.eng.db.prepare("SELECT * FROM specs WHERE id=?").get(id),
    lines: () => readLines(leadFile(env.engineDir)),
    texts: () => h.lines().map((l) => l.text),
    ctlLog: () => (fs.existsSync(path.join(env.root, "ctl.log")) ? fs.readFileSync(path.join(env.root, "ctl.log"), "utf8").split("\n").filter(Boolean) : []),
  };
  t.after(() => { h.eng.stop(); env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  return h;
}

// Mutation: "leave the lead-run spec queued when lead_turn is written" -> a lead_turn on every tick; "policyCheck
// and dispatch include runner lead" has nothing to act on, so the guard is the count of timers, waits and jobs.
test("aged state: a lead turn open for 25 hours, across a day boundary, is neither failed, parked nor repeated, and engine done still completes it", async (t) => {
  const h = mkq(t);
  h.lead(SPEC_L);
  h.enqueue(SPEC_A);
  await h.step(2);
  assert.deepEqual(h.kinds(), ["spec_added", "spec_added", "lead_turn"]);
  assert.deepEqual([h.spec(SPEC_L).position, h.spec(SPEC_A).position], [0, 1]);
  const day0 = new Date(h.clock.t * 1000).getUTCDate();
  await h.step(150, 600); // 25 hours of ticks
  assert.ok(h.clock.t - Date.UTC(2026, 0, 1, 20, 0, 0) / 1000 >= 25 * 3600);
  assert.notEqual(new Date(h.clock.t * 1000).getUTCDate(), day0);
  assert.deepEqual(h.kinds(), ["spec_added", "spec_added", "lead_turn"], "nothing but the one lead_turn in 25 hours");
  assert.deepEqual([h.spec(SPEC_L).state, h.spec(SPEC_L).outcome, h.spec(SPEC_L).policy_version], ["running", null, null]);
  assert.equal(h.spec(SPEC_A).state, "queued", "the turn is held");
  for (const table of ["timers", "waits", "jobs"]) assert.equal(h.eng.db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0, table);
  assert.equal(h.eng.halted, null);
  assert.deepEqual(h.texts(), [`[Engine] your turn: ${SPEC_L}`]);
  assert.deepEqual(queue.done(h.eng.db, SPEC_L, "merged abc1234", h.clock.t), { rc: 0 });
  await h.until(() => h.spec(SPEC_A).state === "done");
  assert.deepEqual([h.spec(SPEC_L).state, h.spec(SPEC_L).outcome], ["done", "merged abc1234"]);
  assert.ok(h.of("spec_done")[0].seq < h.of("spec_started")[0].seq, "the engine spec started after the lead turn ended");
  assert.equal(h.of("lead_turn").length, 1);
  assert.equal(h.ctlLog().filter((l) => l.startsWith("metrics start ")).length, 1, "metrics start once, for the engine spec (R17)");
  assert.equal(rebuild.check("demo").rc, 0);
});

// Mutations: "any exit but 1 passes the gate" -> the exit 3 case gets a lead_turn; "the gate is skipped" -> no gate_result.
test("a gate stub that exits 0 leads to lead_turn; one that exits 3 fails the spec like exit 1", async (t) => {
  const ok = mkq(t, { gateRc: 0 });
  ok.lead(SPEC_G, { gate: "K9" });
  await ok.step(2);
  assert.deepEqual(ok.kinds(), ["spec_added", "gate_result", "lead_turn"]);
  assert.equal(ok.of("gate_result")[0].detail.rc, 0);
  assert.deepEqual(ok.texts(), [`[Engine] your turn: ${SPEC_G}`]);
  assert.equal(ok.spec(SPEC_G).state, "running");
  await ok.step(3);
  assert.deepEqual(ok.ctlLog().filter((l) => l.startsWith("metrics gate")), ["metrics gate K9"], "the gate ran once");

  const bad = mkq(t, { gateRc: 3 });
  bad.lead(SPEC_G, { gate: "K9" });
  bad.lead(SPEC_L);
  await bad.step(3);
  assert.deepEqual(bad.kinds(), ["spec_added", "spec_added", "gate_result", "fail_spec", "lead_turn"]);
  assert.equal(bad.of("gate_result")[0].detail.rc, 3);
  assert.deepEqual([bad.spec(SPEC_G).state, bad.spec(SPEC_G).outcome], ["done", `failed — gate K9: ${GATE_LINE}`]);
  assert.equal(bad.of("lead_turn")[0].spec, SPEC_L, "the queue goes on to the next spec");
  assert.deepEqual(bad.texts(), [`[Engine] your turn: ${SPEC_L}`]);
  assert.equal(bad.ctlLog().filter((l) => l.startsWith(`metrics record ${SPEC_G} --batch b1 --outcome failed — gate K9`)).length, 1);
  assert.equal(rebuild.check("demo").rc, 0);

  const nobatch = mkq(t, { gateRc: 1 });
  nobatch.lead(SPEC_G, { gate: "K9", batch: null });
  await nobatch.step(2);
  assert.equal(nobatch.spec(SPEC_G).outcome, `failed — gate K9: ${GATE_LINE}`);
  assert.equal(nobatch.ctlLog().filter((l) => l.startsWith("metrics record")).length, 0, "no batch: no record");
});

// Mutation: "resume parks a spec whose gate step is at intent" (the part 1 rule for a step without a check) -> an
// awaiting_you for a queued spec.
test("a gate step left at intent by a crash is run again at the spec's turn, not parked", async (t) => {
  const h = mkq(t, { gateRc: 0 });
  h.lead(SPEC_L);
  h.lead(SPEC_G, { gate: "K9" });
  await h.step(2); // both specs are in the queue; the first holds the turn
  assert.equal(h.spec(SPEC_G).state, "queued");
  steps.begin(h.eng.db, { key: `gate:${SPEC_G}`, spec: SPEC_G, kind: "gate", facts: { gate: "K9" } }, { now: h.clock.t });
  const e2 = h.reboot();
  await e2.resume();
  await h.step(2);
  assert.equal(h.of("awaiting_you").length, 0);
  assert.equal(h.spec(SPEC_G).state, "queued");
  assert.equal(e2.halted, null);
  assert.deepEqual(queue.done(e2.db, SPEC_L, "merged", h.clock.t), { rc: 0 });
  await h.step(3);
  assert.deepEqual(h.kinds().filter((k) => k !== "resumed"), ["spec_added", "spec_added", "lead_turn", "spec_done", "gate_result", "lead_turn"]);
  assert.equal(e2.db.prepare("SELECT state FROM steps WHERE key=?").get(`gate:${SPEC_G}`).state, "done");
  assert.deepEqual(h.ctlLog().filter((l) => l.startsWith("metrics gate")), ["metrics gate K9"]);
  assert.equal(rebuild.check("demo").rc, 0);
});

// Mutation: "the queue treats a plan that stopped compiling as engine run does (throw)" -> engine_error instead of the hand-over.
test("a plan that no longer compiles at the spec's turn hands the spec to the lead: handed_to_lead, then lead_turn, no engine_error", async (t) => {
  const h = mkq(t);
  h.enqueue(SPEC_A);
  fs.writeFileSync(h.tasksFile, JSON.stringify({ tasks: [{ subject: "T1", description: "the metadata is gone" }] }));
  await h.step(3);
  assert.deepEqual(h.kinds(), ["spec_added", "handed_to_lead", "lead_turn"]);
  assert.match(h.of("handed_to_lead")[0].detail.reason, /no verifyCommand: task 1/);
  assert.deepEqual([h.spec(SPEC_A).runner, h.spec(SPEC_A).state], ["lead", "running"]);
  assert.equal(h.eng.halted, null);
  assert.deepEqual(h.texts(), [`[Engine] your turn: ${SPEC_A}`]);
  assert.equal(h.ctlLog().filter((l) => l.startsWith("metrics start")).length, 0);
  assert.equal(rebuild.check("demo").rc, 0);
});

test("outside the queue (engine run), a plan that does not compile is still an engine error", async (t) => {
  const env = tmpEnv();
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "eq-"));
  t.after(() => { env.restore(); fs.rmSync(wt, { recursive: true, force: true }); });
  const eng = core.start({ project: "demo", repo: wt, backend: fake.createBackend({}), tmuxCtl: "/usr/bin/true", notify: () => {} });
  t.after(() => eng.stop());
  eng.addSpec({ id: SPEC_A, plan: PLAN_A, worktree: wt });
  await eng.tick();
  assert.match(String(eng.halted), /no \.tasks\.json/);
  assert.equal(eng.db.prepare("SELECT COUNT(*) AS n FROM events WHERE kind='handed_to_lead'").get().n, 0);
});

test("a done row for a spec that is not at a lead turn, and a second enqueue row for a spec already added, are dropped", async (t) => {
  const h = mkq(t);
  h.lead(SPEC_L);
  await h.step(2);
  assert.deepEqual(queue.done(h.eng.db, SPEC_A, "merged", h.clock.t), { rc: 2, msg: `no lead turn open for ${SPEC_A}` });
  inbox.insert(h.eng.db, { source: "user", source_id: "done:forged", spec: SPEC_A, kind: "done", payload: { outcome: "merged" } }, h.clock.t);
  h.lead(SPEC_L, { batch: "b2" }); // another batch: another row, the same spec
  // Mutation: "any other user row is a signal" -> the reason is the signal handler's "spec is not waiting".
  inbox.insert(h.eng.db, { source: "user", source_id: "x1", spec: SPEC_L, kind: "bogus", payload: { answer: "approve" } }, h.clock.t);
  await h.step(2);
  const rows = h.eng.db.prepare("SELECT kind, state, reason FROM inbox ORDER BY id").all();
  assert.deepEqual(rows.map((r) => [r.kind, r.state]), [["enqueue", "done"], ["done", "dropped"], ["enqueue", "dropped"], ["bogus", "dropped"]]);
  assert.equal(rows[3].reason, "unknown user row kind bogus");
  assert.equal(h.of("spec_added").length, 1);
  assert.equal(h.of("lead_turn").length, 1);
  assert.equal(rebuild.check("demo").rc, 0);
});

// ---- the lead lines ----------------------------------------------------------------------------------------------

// Mutation: "start the cursor at 0 on every call" -> duplicate seqs (the count and the uniqueness assertions).
test("the lead-lines file holds awaiting you, paused: usage limit until, and stopped:, in seq order, and publishing twice adds no duplicate seq", async (t) => {
  const h = mkq(t, { tasks: [task({ userGate: true })], script: { implement1: [{ status: "usage_limit", at: 1 }] },
    integrate: async () => { throw new Error("git exploded"); } });
  h.enqueue(SPEC_A);
  await h.until(() => h.spec(SPEC_A) && h.spec(SPEC_A).state === "awaiting_you");
  await h.step();
  assert.deepEqual(h.texts(), [`[Engine] awaiting you: ${SPEC_A}: user gate: task 1 T1`]);
  assert.equal(inbox.signal(h.eng.db, SPEC_A, "approve", undefined, h.clock.t).rc, 0);
  await h.until(() => h.of("usage_limit").length === 1);
  await h.step();
  const until = h.of("usage_limit")[0].detail.until;
  assert.equal(h.texts()[1], `[Engine] paused: usage limit until ${new Date(until * 1000).toISOString()}`);
  Object.assign(h.script, GOOD(1)); // after the reset the worker runs
  h.clock.t = until;
  await h.until(() => h.eng.halted !== null);
  await h.step();
  assert.deepEqual(h.texts().map((x) => x.replace(/until .*/, "until T")), [
    `[Engine] awaiting you: ${SPEC_A}: user gate: task 1 T1`, "[Engine] paused: usage limit until T", "[Engine] stopped: git exploded"]);
  const want = h.events().filter((e) => ["awaiting_you", "usage_limit", "engine_error"].includes(e.kind)).map((e) => e.seq);
  assert.deepEqual(h.lines().map((l) => l.seq), want, "one line per qualifying event, at its seq, in order");
  for (const l of h.lines()) assert.deepEqual(Object.keys(l), ["seq", "ts", "text"]);
  assert.equal(lead.publish("demo", h.eng.db), 0);
  assert.equal(lead.publish("demo", h.eng.db), 0);
  assert.deepEqual(h.lines().map((l) => l.seq), want, "no duplicate seq");
  assert.equal(new Set(h.lines().map((l) => l.seq)).size, h.lines().length);
});

test("lead.publish: the five texts, a torn last line, and a file from another database is set aside as .old", (t) => {
  const env = tmpEnv();
  t.after(() => env.restore());
  const d = db.open("demo");
  t.after(() => d.close());
  const ev = (kind, spec, extra) => db.event(d, { kind, spec, ts: 5.5, ...extra });
  ev("spec_added", "a.md", {});
  ev("lead_turn", "a.md", {});
  ev("awaiting_you", "b.md", { question: "user gate: task 2 T2", detailKind: "user_gate" });
  ev("usage_limit", "b.md", { until: 86400 });
  ev("engine_error", null, { error: "git exploded" });
  ev("queue_finished", null, { report: "docs/superpowers/reports/2026-01-02-queue.md" });
  ev("queue_finished", null, { report: null });
  assert.equal(lead.publish("demo", d), 6);
  const file = leadFile(env.engineDir);
  assert.deepEqual(readLines(file), [
    { seq: 2, ts: 5.5, text: "[Engine] your turn: a.md" },
    { seq: 3, ts: 5.5, text: "[Engine] awaiting you: b.md: user gate: task 2 T2" },
    { seq: 4, ts: 5.5, text: "[Engine] paused: usage limit until 1970-01-02T00:00:00.000Z" },
    { seq: 5, ts: 5.5, text: "[Engine] stopped: git exploded" },
    { seq: 6, ts: 5.5, text: "[Engine] queue finished: docs/superpowers/reports/2026-01-02-queue.md" },
    { seq: 7, ts: 5.5, text: "[Engine] queue finished: (no report)" },
  ]);
  // a torn last line (a crash mid-append): the cursor is the last whole line's seq, and the next line starts on its own row
  fs.appendFileSync(file, '{"seq": 8, "ts"');
  ev("lead_turn", "c.md", {});
  assert.equal(lead.publish("demo", d), 1);
  const raw = fs.readFileSync(file, "utf8").split("\n").filter(Boolean);
  assert.deepEqual(JSON.parse(raw[raw.length - 1]), { seq: 8, ts: 5.5, text: "[Engine] your turn: c.md" });
  assert.equal(raw.length, 8, "the torn piece stays as its own (malformed) line");
  // a new database: the file's last seq is greater than the database's highest
  fs.writeFileSync(file, JSON.stringify({ seq: 9999, ts: 1, text: "[Engine] your turn: old.md" }) + "\n");
  assert.equal(lead.publish("demo", d), 7);
  assert.deepEqual(readLines(`${file}.old`).map((l) => l.seq), [9999]);
  assert.deepEqual(readLines(file).map((l) => l.seq), [2, 3, 4, 5, 6, 7, 8]);
});

// ---- the shared predicate (R12) ----------------------------------------------------------------------------------

// Mutations: "a parked-failed spec counts as open" -> the d.md assertion; "answers ignored" -> the stored-answer and inbox assertions; "only open specs count" -> the kill after the
// last done; "any spec_added opens a queue" -> the engine-run-only database.
test("queue.unfinished: open specs, or a queued spec added after the last queue_finished; an engine-run-only database is finished", (t) => {
  const env = tmpEnv();
  t.after(() => env.restore());
  const d = db.open("demo");
  t.after(() => d.close());
  assert.deepEqual(queue.unfinished(d), []);
  const add = (id, position, state, outcome = null, queued = true) => db.tx(d, () => {
    db.putRaw(d, "specs", { id, position, state, outcome, integration: "keep", created_at: 1, updated_at: 1 });
    db.event(d, { kind: "spec_added", spec: id, ...(queued ? { queued: true } : {}) });
  });
  add("run.md", 0, "done", "kept x", false); // what `engine run` leaves
  assert.deepEqual(queue.unfinished(d), [], "engine run alone is no queue");
  add("b.md", 2, "queued");
  add("a.md", 1, "running");
  add("c.md", 3, "done", "merged");
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md"], "the open specs, by position");
  add("d.md", 4, "awaiting_you", "failed — awaiting you: q");
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md"]);
  add("e.md", 5, "awaiting_you");
  // a parked-failed spec whose answer is waiting (stored on its wait, or a signal still in the inbox) is unfinished
  d.prepare("INSERT INTO waits(id, spec, question, asked_at, answered_at, answer) VALUES('d.md@1','d.md','q',1,2,'approve')").run();
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md", "d.md", "e.md"], "a stored answer");
  d.prepare("DELETE FROM waits WHERE spec='d.md'").run();
  d.prepare("INSERT INTO waits(id, spec, question, asked_at) VALUES('d.md@1','d.md','q',1)").run();
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md", "e.md"], "an open wait with no answer");
  inbox.insert(d, { source: "user", source_id: "s1", spec: "d.md", kind: "signal", payload: { answer: "approve", note: null } }, 3);
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md", "d.md", "e.md"], "a signal in the inbox");
  d.prepare("DELETE FROM inbox").run();
  d.prepare("DELETE FROM waits WHERE spec='d.md'").run();
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md", "e.md"]);
  assert.equal(queue.pendingEnqueue(d), 0);
  queue.enqueue(d, "f.md", { runner: "lead", batch: "b1" }, 1);
  assert.equal(queue.pendingEnqueue(d), 1);
  // the engine killed after the last spec ended and before queue_finished: still unfinished, with the queue's specs
  d.prepare("UPDATE specs SET state='done', outcome='merged' WHERE state!='done' AND outcome IS NULL").run();
  assert.deepEqual(queue.unfinished(d), ["a.md", "b.md", "c.md", "d.md", "e.md"]);
  db.event(d, { kind: "queue_finished", report: null });
  assert.deepEqual(queue.unfinished(d), [], "the queue has finished");
  add("run2.md", 6, "done", "kept y", false);
  assert.deepEqual(queue.unfinished(d), [], "an engine run after it changes nothing");
  add("g.md", 7, "done", "merged");
  assert.deepEqual(queue.unfinished(d), ["g.md"], "a spec enqueued after it opens a new queue");
});

// Mutation: "the floor is taken again at every start" -> the line written before a kill is lost (the last assertion);
// "no floor" -> the old lines are replayed (the first).
test("lead.begin: on a database with history and no lead file, nothing from before the start is published, everything after is, across a restart too", (t) => {
  const env = tmpEnv();
  t.after(() => env.restore());
  const d = db.open("demo");
  t.after(() => d.close());
  const file = leadFile(env.engineDir);
  db.event(d, { kind: "awaiting_you", spec: "old.md", question: "an old question" });
  db.event(d, { kind: "usage_limit", spec: "old.md", until: 5 });
  db.event(d, { kind: "engine_error", error: "an old error" });
  db.event(d, { kind: "queue_finished", report: "old-report.md" });
  lead.begin("demo", d);
  assert.equal(lead.publish("demo", d), 0);
  assert.equal(fs.existsSync(file), false);
  db.event(d, { kind: "lead_turn", spec: "new.md" });
  // the engine dies here, before it published; the next start begins again with the file still absent
  lead.begin("demo", d);
  assert.equal(lead.publish("demo", d), 1);
  assert.deepEqual(readLines(file).map((l) => [l.seq, l.text]), [[5, "[Engine] your turn: new.md"]]);
  lead.begin("demo", d);
  assert.equal(lead.publish("demo", d), 0);
});

// Mutation: "queue.step swallows a publish error silently" -> no line; "queue.step lets it throw" -> the step rejects.
test("queue.step: a lead-lines file that cannot be written is one stderr line per failure, and the tick still counts", async (t) => {
  const h = mkq(t);
  h.lead(SPEC_L);
  fs.mkdirSync(leadFile(h.env.engineDir), { recursive: true }); // a directory where the file should be
  const errs = [];
  await h.step(); // the spec is added; its turn comes on the next tick
  await queue.step(h.eng, "demo", (s) => errs.push(s));
  await queue.step(h.eng, "demo", (s) => errs.push(s));
  assert.equal(h.of("lead_turn").length, 1, "the engine went on");
  assert.equal(errs.length, 2);
  assert.match(errs[0], /^engine: lead lines: .*\n$/);
  fs.rmdirSync(leadFile(h.env.engineDir));
  await h.step();
  assert.deepEqual(h.texts(), [`[Engine] your turn: ${SPEC_L}`], "published once the file can be written");
});
