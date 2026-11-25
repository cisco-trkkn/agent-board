"use strict";
// Schedule rows in a running engine, `schedule run-now`, and resume (spec 14, Task 7).
// The core runs on the fake backend; the schedule runner uses real tmux on a scratch server only.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, scratchTmux } = require("./engine_helpers");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const dbm = require("../lib/engine/db");
const rebuild = require("../lib/engine/rebuild");
const schedule = require("../lib/engine/schedule");
const cli = require("../lib/engine/cli");

const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const PROJECT = "sc";
const ENGINE = path.resolve(__dirname, "../bin/engine.js");

const REAL_ENGINE = path.join(process.env.HOME || os.homedir(), ".local/state/agent-board/engine");
const realList = () => { try { return fs.readdirSync(REAL_ENGINE).filter((n) => !n.startsWith("agent-board.")).sort(); } catch (_) { return []; } };
const REAL_BEFORE = realList();

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const PASS = report({ verdict: "pass", findings: [] });
const worker = (text) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const task = (subject) => ({ subject, description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"] })}\n\`\`\`` });

const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

// One isolated world: engine dir, state dir, scratch tmux server (a session kept alive), and a repo with a two-task plan.
function world(o = {}) {
  const e = tmpEnv();
  const tm = scratchTmux();
  assert.equal(tm.run(["new-session", "-d", "-s", "keep"]).status, 0);
  const sock = tm.run(["display-message", "-p", "#{socket_path}"]).stdout.trim();
  const tmpdir = path.dirname(path.dirname(sock));
  const oldTmp = process.env.TMUX_TMPDIR;
  const oldArgs = process.env.TMUX_DASH_TMUX_ARGS;
  process.env.TMUX_TMPDIR = tmpdir;
  process.env.TMUX_DASH_TMUX_ARGS = `-L ${tm.socket} -f /dev/null`;
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "esc-"));
  fs.mkdirSync(path.join(wt, "docs/superpowers/plans"), { recursive: true });
  fs.mkdirSync(path.join(wt, "docs/superpowers/specs"), { recursive: true });
  fs.writeFileSync(path.join(wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: [task("T1"), task("T2")] }));
  fs.writeFileSync(path.join(wt, SPEC), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n\n## Design\n\nbody\n");
  const ctl = path.join(e.root, "tmux-ctl");
  fs.writeFileSync(ctl, "#!/bin/sh\necho fresh\nexit 0\n", { mode: 0o755 });
  const clock = { t: Math.floor(Date.now() / 1000) };
  const w = { e, tm, wt, ctl, clock, tmpdir, tmuxArgs: ["-L", tm.socket, "-f", "/dev/null"], kill: null, engines: [], finals: [] };
  const script = {};
  for (const n of [1, 2]) { script[`implement${n}`] = worker(DONE); script[`review${n}`] = worker(PASS); }
  script.final_review = worker(PASS);
  w.script = o.script || script;
  w.engine = () => {
    const backend = fake.createBackend({ script: w.script, now: () => clock.t });
    const eng = core.start({
      project: PROJECT, repo: wt, backend, tmuxCtl: ctl, tmuxArgs: w.tmuxArgs,
      now: () => { if (w.kill && w.kill()) throw new Error("killed"); return clock.t; },
      integrate: async () => ({ outcome: "merged" }), revert: async () => {}, finalize: async (s, outcome) => { w.finals.push(outcome); },
      tell: () => {}, notify: () => {}, transcriptRoot: path.join(e.root, "transcripts"), sleep: async () => { clock.t += 5; },
    });
    w.engines.push(eng);
    w.eng = eng;
    w.db = eng.db;
    return eng;
  };
  w.engine();
  w.add = () => w.eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1" });
  w.step = async () => { clock.t += 5; await w.eng.tick(); };
  w.q = (sql, ...a) => w.db.prepare(sql).all(...a);
  w.events = (kind) => w.q("SELECT * FROM events WHERE kind=? ORDER BY seq", kind).map((r) => ({ ...r, d: JSON.parse(r.detail) }));
  w.windows = () => (tm.run(["list-windows", "-t", `=${PROJECT}-bg:`, "-F", "#{window_name}"]).stdout || "").split("\n").filter(Boolean);
  w.until = async (pred, max = 200) => {
    for (let i = 0; i < max; i++) { if (pred()) return; await w.step(); }
    assert.fail(`not reached after ${max} ticks`);
  };
  w.row = (name, command, extra = {}) => inbox.insert(w.db, { source: "schedule", source_id: `${name}@now:${clock.t}`, kind: "run",
    payload: { name, command, cwd: os.tmpdir(), env: {}, skip_if_weekly_usage: null, force: true, ...extra } }, clock.t);
  w.check = () => { const r = rebuild.check(PROJECT); assert.deepEqual(r.diffs, []); assert.equal(r.rc, 0); };
  cleanups.push(() => {
    for (const x of w.engines) { try { x.stop(); } catch (_) { /* stopped */ } }
    tm.kill();
    if (oldTmp === undefined) delete process.env.TMUX_TMPDIR; else process.env.TMUX_TMPDIR = oldTmp;
    if (oldArgs === undefined) delete process.env.TMUX_DASH_TMUX_ARGS; else process.env.TMUX_DASH_TMUX_ARGS = oldArgs;
    e.restore();
    fs.rmSync(wt, { recursive: true, force: true });
  });
  return w;
}

const dispatched = (w) => w.events("dispatched").map((e) => `${e.d.kind || ""}:${e.d.job}`);

test("a drained schedule row opens its window on the same tick, and a spec's dispatch order is the same with it", async () => {
  // run A: no schedule row
  const a = world();
  a.add();
  await a.until(() => a.q("SELECT 1 FROM specs WHERE id=? AND state='done'", SPEC).length === 1);
  const base = dispatched(a);
  assert.ok(base.length >= 5, base.join(" "));
  a.check();
  // run B: a schedule row arrives while a job is running
  const b = world();
  b.add();
  await b.until(() => b.q("SELECT 1 FROM jobs WHERE state='running'").length === 1);
  b.row("echo1", "sleep 20");
  const before = b.events("schedule_started").length;
  await b.step(); // the tick that drains the row opens the window
  assert.equal(before, 0);
  assert.equal(b.events("schedule_started").length, 1, "the window opened one tick late");
  assert.deepEqual(b.windows().filter((n) => n.startsWith("sched·")), ["sched·echo1"]);
  await b.until(() => b.q("SELECT 1 FROM specs WHERE id=? AND state='done'", SPEC).length === 1);
  assert.deepEqual(dispatched(b), base);
  b.check();
});

test("a run's end is recorded on a later tick, without blocking the tick", async () => {
  const w = world();
  w.row("slow", "sleep 2; exit 3");
  const t0 = Date.now();
  await w.step();
  assert.ok(Date.now() - t0 < 1500, `the tick waited ${Date.now() - t0} ms for the command`);
  assert.equal(w.events("schedule_started").length, 1);
  assert.equal(w.events("schedule_ran").length, 0);
  const end = Date.now() + 30000;
  while (Date.now() < end && !w.events("schedule_ran").length) { await sleep(300); await w.step(); }
  const ran = w.events("schedule_ran");
  assert.equal(ran.length, 1);
  assert.equal(ran[0].d.rc, 3);
  await w.step();
  assert.equal(w.events("schedule_ran").length, 1);
  w.check();
});

test("the queue's end is not delayed by an open run; the next tick after the end records it", async () => {
  const w = world();
  w.add();
  w.row("long", "sleep 3");
  await w.until(() => w.q("SELECT 1 FROM specs WHERE id=? AND state='done'", SPEC).length === 1);
  assert.equal(w.events("schedule_started").length, 1);
  assert.equal(w.events("schedule_ran").length, 0, "the run ended before the queue did: make it longer");
  assert.equal(await w.eng.finish(), true, "an open run delayed the end of the queue");
  const end = Date.now() + 30000;
  while (Date.now() < end && !w.events("schedule_ran").length) { await sleep(300); await w.step(); }
  assert.equal(w.events("schedule_ran").length, 1);
  w.check();
});

test("kill between the intent and the window: one window and one schedule_started after resume", async () => {
  const w = world();
  w.row("crash", "sleep 20");
  // the engine dies once the intent is committed and before runIntents opens the window
  w.kill = () => w.q("SELECT 1 FROM steps WHERE kind='schedule_run' AND state='intent'").length > 0;
  await w.step();
  assert.equal(w.q("SELECT state FROM steps WHERE kind='schedule_run'")[0].state, "intent");
  assert.deepEqual(w.windows().filter((n) => n.startsWith("sched·")), []);
  assert.equal(w.events("schedule_started").length, 0);
  w.eng.stop();
  w.kill = null;
  const eng = w.engine();
  await eng.resume();
  assert.equal(w.q("SELECT state FROM steps WHERE kind='schedule_run'")[0].state, "intent", "resume must leave a not_done run at intent");
  await w.step();
  assert.deepEqual(w.windows().filter((n) => n.startsWith("sched·")), ["sched·crash"]);
  assert.equal(w.events("schedule_started").length, 1);
  await w.step();
  assert.equal(w.events("schedule_started").length, 1);
  assert.equal(w.q("SELECT state FROM steps WHERE kind='schedule_run'")[0].state, "done");
  w.check();
});

test("resume: a run whose window is open is done by the check; an unknown one is failed, never parked", async () => {
  const w = world();
  w.row("open", "sleep 20");
  await w.step();
  assert.equal(w.events("schedule_started").length, 1);
  // an intent row for a run whose state cannot be told (tmux cannot be started): failed, not parked
  const facts = { name: "ghost", command: "true", cwd: os.tmpdir(), env: {}, window: "sched·ghost", rc_file: path.join(w.e.root, "ghost.rc"), log: path.join(w.e.root, "ghost.log") };
  w.db.prepare("INSERT INTO steps(key, spec, kind, state, result, created_at, updated_at) VALUES (?,?,?,?,?,?,?)")
    .run("schedule_run:ghost@1", null, "schedule_run", "intent", JSON.stringify(facts), w.clock.t, w.clock.t);
  w.eng.stop();
  const oldPath = process.env.PATH;
  const eng = w.engine();
  process.env.PATH = "/nonexistent";
  try { await eng.resume(); } finally { process.env.PATH = oldPath; }
  const ghost = w.q("SELECT state FROM steps WHERE key='schedule_run:ghost@1'")[0];
  assert.equal(ghost.state, "failed");
  assert.equal(w.q("SELECT count(*) c FROM waits WHERE answered_at IS NULL")[0].c, 0);
});

// ---- schedule run-now ----

function cliWorld() {
  const w = world();
  const d = dbm.open(PROJECT);
  schedule.add(d, { name: "echo1", rule: "daily 03:30", command: "echo hi; exit 3", cwd: os.tmpdir(), skip_if_weekly_usage: 85, env: {} }, Date.now() / 1000);
  d.close();
  w.eng.stop(); // no engine running unless a test starts one
  w.run = async (args) => {
    const out = [];
    const err = [];
    const rc = await cli.main(args, { out: (s) => out.push(s), err: (s) => err.push(s), cwd: w.wt });
    return { rc, out: out.join("\n"), err: err.join("") };
  };
  return w;
}

test("schedule run-now with no engine running runs the command now and waits for it", async () => {
  const w = cliWorld();
  const r = await w.run(["schedule", "run-now", "echo1", "--project", PROJECT]);
  assert.equal(r.rc, 0, r.err);
  const d = dbm.open(PROJECT);
  const ran = d.prepare("SELECT * FROM events WHERE kind='schedule_ran'").all().map((e) => JSON.parse(e.detail));
  assert.equal(ran.length, 1);
  assert.equal(ran[0].rc, 3);
  assert.equal(fs.readFileSync(ran[0].log, "utf8").trim(), "hi");
  const ib = d.prepare("SELECT * FROM inbox WHERE source='schedule'").all();
  assert.equal(ib.length, 1);
  assert.match(ib[0].source_id, /^echo1@now:\d+$/);
  assert.equal(JSON.parse(ib[0].payload).force, true);
  assert.equal(d.prepare("SELECT due_at FROM timers WHERE id='schedule:echo1'").get().due_at > Date.now() / 1000, true);
  d.close();
  w.check();
});

test("schedule run-now with an engine running queues the row for it", async () => {
  const w = cliWorld();
  const eng = w.engine(); // this process holds the lock: a live pid
  const r = await w.run(["schedule", "run-now", "echo1", "--project", PROJECT]);
  assert.equal(r.rc, 0, r.err);
  assert.match(r.out, /queued for the running engine/);
  assert.equal(w.q("SELECT count(*) c FROM steps WHERE kind='schedule_run'")[0].c, 0);
  assert.equal(w.windows().filter((n) => n.startsWith("sched·")).length, 0);
  assert.equal(w.q("SELECT count(*) c FROM inbox WHERE source='schedule' AND state='new'")[0].c, 1);
  await w.step(); // the engine's tick drains it
  assert.equal(w.q("SELECT count(*) c FROM steps WHERE kind='schedule_run'")[0].c, 1);
  assert.equal(w.events("schedule_started").length, 1);
  eng.stop();
  w.check();
});

test("schedule run-now: an unknown or retired name exits 1 with `no schedule <name>`", async () => {
  const w = cliWorld();
  let r = await w.run(["schedule", "run-now", "nope", "--project", PROJECT]);
  assert.equal(r.rc, 1);
  assert.match(r.err, /no schedule nope/);
  assert.equal((await w.run(["schedule", "rm", "echo1", "--project", PROJECT])).rc, 0);
  r = await w.run(["schedule", "run-now", "echo1", "--project", PROJECT]);
  assert.equal(r.rc, 1);
  assert.match(r.err, /no schedule echo1/);
  const d = dbm.open(PROJECT);
  assert.equal(d.prepare("SELECT count(*) c FROM inbox WHERE source='schedule'").get().c, 0);
  d.close();
  r = await w.run(["schedule", "run-now", "--project", PROJECT]);
  assert.equal(r.rc, 2);
});

test("schedule run-now runs only its own project", async () => {
  const w = cliWorld();
  const d2 = dbm.open("other");
  schedule.add(d2, { name: "o1", rule: "every 1m", command: "echo other", cwd: os.tmpdir(), skip_if_weekly_usage: null, env: {} }, Date.now() / 1000);
  d2.prepare("UPDATE timers SET due_at=? WHERE id='schedule:o1'").run(Date.now() / 1000 - 600); // due, but not this project's run
  d2.close();
  const r = await w.run(["schedule", "run-now", "echo1", "--project", PROJECT]);
  assert.equal(r.rc, 0, r.err);
  const d = dbm.open("other");
  assert.equal(d.prepare("SELECT count(*) c FROM events WHERE kind IN ('schedule_due','schedule_started','schedule_ran')").get().c, 0);
  d.close();
  assert.ok(r.out.includes(PROJECT) && !r.out.includes("other"), r.out);
});

test("leak check: the real engine dir gained no file, and the real tmux server has no session sc-bg", () => {
  const env = { ...process.env };
  delete env.TMUX;
  delete env.TMUX_TMPDIR;
  const r = cp.spawnSync("tmux", ["has-session", "-t", `=${PROJECT}-bg`], { env, encoding: "utf8" });
  assert.notEqual(r.status, 0, `a session ${PROJECT}-bg exists on the real tmux server`);
  const after = realList();
  assert.deepEqual(after, REAL_BEFORE, "the real engine dir gained or lost a file");
  assert.ok(!after.some((n) => n.startsWith(`${PROJECT}.`) || n === "other.sqlite"), "a file named for a test project is in the real engine dir");
  void ENGINE;
});
