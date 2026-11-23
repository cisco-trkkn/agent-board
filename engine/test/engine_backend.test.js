"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { tmpEnv } = require("./engine_helpers.js");
const fake = require("../lib/engine/backend/fake.js");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Poll until pred(events) holds; returns every event seen.
async function collect(backend, pred, timeoutMs = 10000) {
  const seen = [];
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    seen.push(...backend.poll());
    if (pred(seen)) return seen;
    await sleep(25);
  }
  return seen;
}

// makeBackend(dir) -> {backend, job(extra), cleanup?}; drive(ctx, handle) makes the started job
// go through `ready` and a report. Task 5 supplies a real-process makeBackend and drive.
function conformance(name, makeBackend, drive) {
  test(`${name}: start returns a handle and emits started`, async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeBackend(env.root); t.after(() => ctx.cleanup && ctx.cleanup());
    const job = ctx.job({});
    const handle = await ctx.backend.start(job);
    assert.equal(handle.job, job.id);
    assert.ok(handle.window && handle.pane);
    const ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "started"));
    const started = ev.find((x) => x.type === "started");
    assert.ok(started);
    assert.equal(started.handle.job, job.id);
  });

  test(`${name}: ready then report`, async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeBackend(env.root); t.after(() => ctx.cleanup && ctx.cleanup());
    const job = ctx.job({});
    const handle = await ctx.backend.start(job);
    await drive(ctx, handle);
    const ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "report"));
    const kinds = ev.map((x) => x.type);
    const ready = kinds.findIndex((k, i) => k === "status" && ev[i].state === "ready");
    const rep = kinds.indexOf("report");
    assert.ok(ready >= 0, "a status ready event: " + kinds);
    assert.ok(rep > ready, "report comes after ready");
    for (const e of ev) assert.equal(e.handle.job, job.id);
    assert.ok(fs.existsSync(ev[rep].path));
    assert.match(fs.readFileSync(ev[rep].path, "utf8"), /json:status/);
  });

  test(`${name}: close emits gone`, async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeBackend(env.root); t.after(() => ctx.cleanup && ctx.cleanup());
    const job = ctx.job({});
    const handle = await ctx.backend.start(job);
    await ctx.backend.close(handle);
    const ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "gone"));
    const gone = ev.find((x) => x.type === "gone");
    assert.ok(gone);
    assert.equal(gone.handle.job, job.id);
  });

  test(`${name}: resume returns a new handle for the same job`, async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeBackend(env.root); t.after(() => ctx.cleanup && ctx.cleanup());
    const job = ctx.job({});
    const handle = await ctx.backend.start(job);
    const next = await ctx.backend.resume(handle, "fix the findings");
    assert.equal(next.job, job.id);
    assert.ok(next.pane);
    if (ctx.resumed) assert.deepEqual(ctx.resumed(), [{ handle, text: "fix the findings" }]);
  });
}

const REPORT = "done\n\n```json:status\n{\"status\":\"DONE\"}\n```\n";

function makeFake(root) {
  let clock = 1000;
  const reportDir = path.join(root, "reports");
  fs.mkdirSync(reportDir, { recursive: true });
  const backend = fake.createBackend({
    now: () => clock, reportDir,
    script: {
      implement1: [
        { status: "busy", tool: { name: "Bash", arg: "ls", startedAt: 1000 }, at: 0 },
        { status: "ready", at: 5 },
        { report: REPORT, at: 5 },
      ],
    },
  });
  return {
    backend, advance(s) { clock += s; },
    job: (x) => ({ id: "s:implement1:1", kind: "implement", task: 1, ...x }),
    resumed: () => backend.calls.filter((c) => c.method === "resume").map((c) => ({ handle: c.handle, text: c.text })),
  };
}
const driveFake = async (ctx) => { ctx.advance(10); };

module.exports = { conformance, collect };

if (require.main === module) {
  conformance("fake", makeFake, driveFake);

  test("fake: poll returns only events due by the clock, in order", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = makeFake(env.root);
    await ctx.backend.start(ctx.job({}));
    assert.deepEqual(ctx.backend.poll().map((e) => e.type), ["started", "status"]);
    ctx.advance(4);
    assert.deepEqual(ctx.backend.poll(), []);
    ctx.advance(1);
    const ev = ctx.backend.poll();
    assert.deepEqual(ev.map((e) => e.type), ["status", "report"]);
    assert.equal(ev[0].state, "ready");
    assert.equal(ev[1].path, path.join(env.root, "reports", "s:implement1:1.md"));
  });

  test("fake: job.report overrides the path; calls records start, close, resume", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = makeFake(env.root);
    const rp = path.join(env.root, "mine.md");
    const h = await ctx.backend.start(ctx.job({ report: rp, window: "w1" }));
    assert.equal(h.window, "w1");
    assert.match(h.pane, /^%fake\d+$/);
    assert.match(h.session_id, /^fake-sess-\d+$/);
    ctx.advance(10);
    assert.equal(ctx.backend.poll().find((e) => e.type === "report").path, rp);
    const h2 = await ctx.backend.resume(h, "again");
    await ctx.backend.close(h2);
    assert.deepEqual(ctx.backend.calls.map((c) => c.method), ["start", "resume", "close"]);
  });

  test("fake: gone and hang steps", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    let clock = 0;
    const b = fake.createBackend({
      now: () => clock, reportDir: env.root,
      script: { review: [{ hang: true, at: 1 }, { gone: true, at: 2 }] },
    });
    await b.start({ id: "s:review:1", kind: "review" });
    clock = 2;
    const ev = b.poll();
    assert.deepEqual(ev.map((e) => e.type), ["started", "status", "gone"]);
    assert.equal(ev[1].state, "busy");
    assert.equal(ev[1].tool, null);
  });
}

if (require.main === module) {
  const cp = require("node:child_process");
  const WORKER = path.join(__dirname, "fixtures/engine/fake-worker.js");
  const runWorker = (root, mode) => {
    const report = path.join(root, "r.md");
    const status = path.join(root, "s.json");
    const child = cp.spawn(process.execPath, [WORKER, report, status, mode], { env: { ...process.env, FAKE_PANE: "%99" }, stdio: "ignore" });
    const exited = new Promise((r) => child.on("exit", r));
    return { child, exited, report, status };
  };
  const waitFor = async (pred, ms = 8000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { if (pred()) return true; await sleep(25); }
    return false;
  };
  const readStatus = (p) => { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return null; } };

  for (const mode of ["done", "blocked"]) {
    test(`fake-worker ${mode}: report with json:status, then ready, then exits`, async (t) => {
      const env = tmpEnv(); t.after(() => env.restore());
      const w = runWorker(env.root, mode);
      t.after(() => w.child.kill());
      assert.ok(await waitFor(() => readStatus(w.status)?.state === "ready"));
      const s = readStatus(w.status);
      assert.equal(s.pane, "%99");
      assert.ok(s.session_id);
      assert.equal(typeof s.updatedAt, "number");
      assert.ok(s.updatedAt < 1e11, "seconds");
      const rep = fs.readFileSync(w.report, "utf8");
      assert.match(rep, new RegExp("```json:status\\n.*" + (mode === "done" ? "DONE" : "BLOCKED")));
      assert.equal(await w.exited, 0);
    });
  }

  test("fake-worker noreport: ready without a report", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const w = runWorker(env.root, "noreport");
    t.after(() => w.child.kill());
    assert.ok(await waitFor(() => readStatus(w.status)?.state === "ready"));
    assert.ok(!fs.existsSync(w.report));
  });

  test("fake-worker hang: busy with tool null until killed", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const w = runWorker(env.root, "hang");
    t.after(() => w.child.kill());
    assert.ok(await waitFor(() => readStatus(w.status)?.state === "busy"));
    assert.equal(readStatus(w.status).tool, null);
    w.child.kill();
    await w.exited;
  });

  test("fake-worker silent: writes nothing", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const w = runWorker(env.root, "silent");
    t.after(() => w.child.kill());
    await sleep(1500);
    assert.ok(!fs.existsSync(w.status));
    assert.ok(!fs.existsSync(w.report));
    assert.equal(fs.readdirSync(env.root).filter((f) => f.endsWith(".tmp")).length, 0);
  });
}
