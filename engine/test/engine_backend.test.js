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

  test("fake: resume records the job; resume_fails makes it throw", async () => {
    const b = fake.createBackend({ script: {} });
    const h = await b.start({ id: "s:implement1:1", kind: "implement", task: 1 });
    await b.resume(h, "t", { id: "s:implement1:2" });
    assert.deepEqual(b.calls.find((c) => c.method === "resume").job, { id: "s:implement1:2" });
    const f = fake.createBackend({ script: { resume_fails: true } });
    const h2 = await f.start({ id: "s:implement1:1", kind: "implement", task: 1 });
    await assert.rejects(() => f.resume(h2, "t", {}), /cannot resume/);
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

// ---- claude-tmux: real tmux windows on a scratch server, fake-worker standing in for claude ----
if (require.main === module) {
  const cp = require("node:child_process");
  const { scratchTmux, gitRepo } = require("./engine_helpers.js");
  const claudeTmux = require("../lib/engine/backend/claude_tmux.js");
  const paths = require("../lib/engine/paths.js");
  const REPO = path.join(__dirname, "../..");
  const WORKER = path.join(__dirname, "fixtures/engine/fake-worker.js");
  const VALID = "done\n\n```json:status\n{\"status\":\"done\",\"commits\":[],\"concerns\":[]}\n```\n";

  async function makeClaudeTmux(root, agentCmd) {
    const tmux = scratchTmux();
    const sess = "eng";
    tmux.run(["new-session", "-d", "-s", sess, "-n", "main", "-x", "200", "-y", "50"]);
    const sock = tmux.run(["display", "-p", "#{socket_path}"]).stdout.trim();
    const repo = gitRepo();
    const worktree = path.join(root, "wt");
    repo.git("worktree", "add", "-q", worktree, "-b", "wtb");
    const statusDir = paths.statusDir();
    const report = path.join(root, "reports", "r.md");
    const brief = path.join(root, "brief.md");
    fs.writeFileSync(brief, "Goal: do it.\n");
    // fake-worker writes DONE (not a valid implementer report), so a wrapper replaces it once the worker is ready
    const wrapper = path.join(root, "w.js");
    fs.writeFileSync(wrapper, `const cp=require("node:child_process"),fs=require("node:fs");
const [w,r,s]=process.argv.slice(2);
cp.spawnSync(process.execPath,[w,r,s,"noreport"],{stdio:"ignore"});
fs.mkdirSync(require("node:path").dirname(r),{recursive:true});fs.writeFileSync(r,${JSON.stringify(VALID)});\n`);
    const argvLog = path.join(root, "argv.log");
    const ctl = path.join(root, "ctl.sh");
    fs.writeFileSync(ctl, `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(argvLog)}\nexec ${JSON.stringify(path.join(REPO, "bin/tmux-ctl"))} "$@"\n`, { mode: 0o755 });
    const env = {
      TMUX_TMPDIR: path.dirname(path.dirname(sock)),
      TC_AGENT_CMD: agentCmd || `FAKE_PANE=$TMUX_PANE ${process.execPath} ${wrapper} ${WORKER} ${report} ${path.join(statusDir, "fake.json")}`,
    };
    // a second call is a second engine process: a backend that started no window
    const make = () => claudeTmux.createBackend({
      session: sess, tmuxCtl: ctl, statusDir,
      tmuxArgs: ["-L", tmux.socket, "-f", "/dev/null"], env,
    });
    const backend = make();
    return {
      backend, make, tmux, argvLog, worktree, report,
      job: (x) => ({ id: "myspec-p1:implement1:1", spec: "myspec-p1", kind: "implement", task: 1, attempt: 1, tier: "standard",
        model: "sonnet", effort: "low", brief, report, worktree, ...x }),
      cleanup() { tmux.kill(); repo.cleanup(); },
    };
  }
  const driveTmux = async () => {};
  conformance("claude-tmux", makeClaudeTmux, driveTmux);

  test("claude-tmux: start passes --dir, model, effort, brief; window is <slug>·<kind><task>", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({}));
    assert.equal(h.window, "myspec-p1·implement1");
    assert.match(h.pane, /^%\d+$/);
    const argv = fs.readFileSync(ctx.argvLog, "utf8").trim();
    assert.equal(argv, `agent myspec-p1·implement1 --dir ${ctx.worktree} --model sonnet --effort low --brief ${path.join(env.root, "brief.md")}`);
  });

  test("claude-tmux: resume runs agent --resume <session_id> with the text as the brief", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({}));
    const next = await ctx.backend.resume(h, "fix the findings");
    assert.match(next.session_id, /^fake-worker-\d+$/);
    const lines = fs.readFileSync(ctx.argvLog, "utf8").trim().split("\n");
    assert.equal(lines.length, 2);
    assert.match(lines[1], new RegExp(`^agent \\S+ --dir ${ctx.worktree} --resume ${next.session_id} --model sonnet --effort low --brief \\S+$`));
    const briefArg = lines[1].split(" --brief ")[1];
    assert.equal(fs.readFileSync(briefArg, "utf8"), "fix the findings");
    assert.notEqual(next.window, h.window);
  });

  test("claude-tmux: a job's env goes to tmux-ctl agent as --env K=V; a job without env gets none, on start and on resume", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({ env: { CLAUDE_CODE_EXPERIMENTAL_CODE_MODE: "1", OTHER_VAR: "a b" } }));
    // the next job on that session has no env of its own: the earlier job's env must not ride along
    const h2 = await ctx.backend.resume(h, "fix it", ctx.job({ id: "myspec-p1:fix1:1", kind: "fix" }));
    await ctx.backend.resume(h2, "again", ctx.job({ id: "myspec-p1:implement1:2", attempt: 2, env: { CLAUDE_CODE_EXPERIMENTAL_CODE_MODE: "1" } }));
    const lines = fs.readFileSync(ctx.argvLog, "utf8").trim().split("\n");
    assert.equal(lines[0], `agent myspec-p1·implement1 --dir ${ctx.worktree} --env CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 --env OTHER_VAR=a b --model sonnet --effort low --brief ${path.join(env.root, "brief.md")}`);
    assert.doesNotMatch(lines[1], /--env/);
    assert.match(lines[2], / --resume \S+ --env CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 --model /);
  });

  // The logging tmux-ctl stub also logs the four ENGINE_ variables of its env.
  test("claude-tmux: start and resume pass the new job's ENGINE_ variables", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const envLog = path.join(env.root, "env.log");
    const ctl2 = path.join(env.root, "ctl2.sh");
    fs.writeFileSync(ctl2, `#!/bin/sh\nprintf '%s|%s|%s|%s\\n' "$ENGINE_JOB" "$ENGINE_PROJECT" "$ENGINE_DIR" "$ENGINE_WORKTREE" >> ${JSON.stringify(envLog)}\nexec ${JSON.stringify(path.join(REPO, "bin/tmux-ctl"))} "$@"\n`, { mode: 0o755 });
    const sock = ctx.tmux.run(["display", "-p", "#{socket_path}"]).stdout.trim();
    const b = claudeTmux.createBackend({ session: "eng", tmuxCtl: ctl2, statusDir: paths.statusDir(), project: "proj",
      tmuxArgs: ["-L", ctx.tmux.socket, "-f", "/dev/null"],
      env: { TMUX_TMPDIR: path.dirname(path.dirname(sock)),
        TC_AGENT_CMD: `FAKE_PANE=$TMUX_PANE ${process.execPath} ${WORKER} ${ctx.report} ${path.join(paths.statusDir(), "fake.json")} noreport` } });
    const h = await b.start(ctx.job({}));
    const job2 = ctx.job({ id: "myspec-p1:implement1:2", attempt: 2 });
    await b.resume(h, "again", job2);
    const lines = fs.readFileSync(envLog, "utf8").trim().split("\n");
    assert.equal(lines[0], `myspec-p1:implement1:1|proj|${paths.engineDir()}|${path.resolve(ctx.worktree)}`);
    // mutation "launch with e.job on resume": the second line would carry the old id
    assert.equal(lines[1], `myspec-p1:implement1:2|proj|${paths.engineDir()}|${path.resolve(ctx.worktree)}`);
  });

  test("claude-tmux: close saves the pane's last lines to <workspace>/logs/<job>-<attempt>.log, then the pane is gone", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({}));
    await sleep(500);
    await ctx.backend.close(h);
    const log = path.join(paths.workspace(ctx.worktree), "logs", "myspec-p1_implement1-1.log");
    assert.ok(fs.existsSync(log), log);
    const ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "gone"));
    assert.equal(ev.filter((x) => x.type === "gone").length, 1);
  });

  test("claude-tmux: status events fire on each change of state or updatedAt, not on repeats", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root, "sleep 60"); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({}));
    const f = path.join(paths.statusDir(), "fake.json");
    fs.mkdirSync(paths.statusDir(), { recursive: true });
    const write = (state, updatedAt) => fs.writeFileSync(f, JSON.stringify({ pane: h.pane, session_id: "s1", state, updatedAt, tool: null }));
    await collect(ctx.backend, (e) => e.some((x) => x.type === "started"));
    fs.rmSync(f, { force: true });
    await sleep(100);
    write("busy", 100);
    let ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "status"));
    assert.deepEqual(ev.filter((x) => x.type === "status").map((x) => [x.state, x.updatedAt]), [["busy", 100]]);
    assert.deepEqual(ctx.backend.poll(), []);
    write("busy", 101);
    ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "status"));
    assert.deepEqual(ev.filter((x) => x.type === "status").map((x) => [x.state, x.updatedAt]), [["busy", 101]]);
    // another pane's record, newer, is ignored
    fs.writeFileSync(path.join(paths.statusDir(), "other.json"), JSON.stringify({ pane: "%9999", state: "needs-you", updatedAt: 500 }));
    await sleep(100);
    assert.deepEqual(ctx.backend.poll(), []);
  });

  // Fixtures: Claude's real limit sentences, probed 2026-11-24 over ~/.claude/projects/**/*.jsonl (synthetic assistant
  // lines): "You've hit your 5-hour limit · resets 12:30am (America/New_York)" x16, "You've hit your weekly limit ·
  // resets …" x10, "You've hit your session limit · resets 5:30pm (America/New_York)" x2. No model-limit line was
  // found (plan assumption A8): fake-worker's "Fable" sentence is invented.
  async function limitEvents(mode, ms) {
    const env = tmpEnv();
    const agent = (r) => `FAKE_PANE=$TMUX_PANE ${process.execPath} ${WORKER} ${path.join(r, "rep.md")} ${path.join(paths.statusDir(), "fake.json")} ${mode}`;
    const ctx = await makeClaudeTmux(env.root, agent(env.root));
    try {
      await ctx.backend.start(ctx.job({}));
      const seen = [];
      const end = Date.now() + ms;
      while (Date.now() < end) { seen.push(...ctx.backend.poll()); await sleep(100); }
      return seen.filter((x) => x.type === "status");
    } finally { ctx.cleanup(); env.restore(); }
  }
  const limitStates = (ev) => ev.map((x) => x.state).filter((s) => s.endsWith("_limit"));

  test("claude-tmux: a usage-limit pane yields one usage_limit status event", async () => {
    const ev = await limitEvents("usage-limit", 3000);
    assert.deepEqual(limitStates(ev), ["usage_limit"]);
    const x = ev.find((e) => e.state === "usage_limit");
    assert.equal(typeof x.updatedAt, "number");
    assert.deepEqual([x.tool, x.lastToolAt, x.turnStartedAt], [null, null, null]);
  });

  test("claude-tmux: a model-limit pane yields one model_limit status event", async () => {
    assert.deepEqual(limitStates(await limitEvents("model-limit", 3000)), ["model_limit"]);
  });

  // Mutation: match /limit/ only -> this pane ("no limit here") reports a limit.
  test("claude-tmux: a pane that only says 'no limit here' yields no limit event", async () => {
    assert.deepEqual(limitStates(await limitEvents("noreport", 2500)), []);
  });

  // Mutation: the unanchored /You've hit your (.+?) limit/ -> the quoted sentence reports a usage limit.
  test("claude-tmux: a pane that quotes the limit sentence mid-line yields no limit event", async () => {
    assert.deepEqual(limitStates(await limitEvents("quote-limit", 2500)), []);
  });

  test("claude-tmux: weekly and session sentences are usage limits, any other kind a model limit", async () => {
    const cases = [["weekly", "usage_limit"], ["session", "usage_limit"], ["5-hour", "usage_limit"], ["Opus", "model_limit"]];
    for (const [kind, want] of cases) {
      const env = tmpEnv();
      const ctx = await makeClaudeTmux(env.root, `printf "You've hit your ${kind} limit · resets 5:30pm (America/New_York)\\n"; sleep 60`);
      try {
        await ctx.backend.start(ctx.job({}));
        let ev = [];
        const end = Date.now() + 3000;
        while (Date.now() < end && !ev.some((x) => x.state && x.state.endsWith("_limit"))) { ev.push(...ctx.backend.poll()); await sleep(100); }
        assert.deepEqual(limitStates(ev.filter((x) => x.type === "status")), [want], kind);
      } finally { ctx.cleanup(); env.restore(); }
    }
  });

  test("claude-tmux: a busy handle's pane is not captured", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root, "sleep 60"); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({}));
    fs.mkdirSync(paths.statusDir(), { recursive: true });
    fs.writeFileSync(path.join(paths.statusDir(), "fake.json"), JSON.stringify({ pane: h.pane, session_id: "s1", state: "busy", updatedAt: 100, tool: null }));
    const log = path.join(env.root, "tmux-calls.log");
    const bin = path.join(env.root, "tmux-log.sh");
    fs.writeFileSync(bin, `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(log)}\nexec tmux "$@"\n`, { mode: 0o755 });
    const logged = claudeTmux.createBackend({ session: "eng", tmuxCtl: "unused", statusDir: paths.statusDir(),
      tmuxArgs: ["-L", ctx.tmux.socket, "-f", "/dev/null"], tmuxBin: bin,
      env: { TMUX_TMPDIR: path.dirname(path.dirname(ctx.tmux.run(["display", "-p", "#{socket_path}"]).stdout.trim())) } });
    // adopt the pane so the logging backend watches it
    assert.equal(await logged.adopt(ctx.job({}), h), true);
    const captures = () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "").split("\n").filter((l) => l.includes("capture-pane")).length;
    for (let i = 0; i < 3; i++) { logged.poll(); await sleep(50); }
    assert.equal(captures(), 0);
    fs.writeFileSync(path.join(paths.statusDir(), "fake.json"), JSON.stringify({ pane: h.pane, session_id: "s1", state: "ready", updatedAt: 101, tool: null }));
    logged.poll();
    assert.equal(captures(), 1);
  });

  // Mutations run for adopt (see the Task 8 fix report): the pane-exists check removed, and the window-name check
  // removed, each fail this test.
  test("claude-tmux: a second backend adopts a running job's pane, watches it and closes it", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root, "sleep 60"); t.after(() => ctx.cleanup());
    const job = ctx.job({});
    const h = await ctx.backend.start(job);
    const row = { job: h.job, window: h.window, pane: h.pane, session_id: undefined }; // what the core rebuilds from the jobs row
    const b2 = ctx.make();
    assert.deepEqual(b2.poll(), []);
    assert.equal(await b2.adopt(job, { ...row, pane: "%9999" }), false, "no such pane");
    assert.equal(await b2.adopt(job, { ...row, window: "another-window" }), false, "a reused pane id under another window");
    assert.deepEqual(b2.poll(), []);
    assert.equal(await b2.adopt(job, row), true);
    assert.equal(await b2.adopt(job, row), true, "adopting twice watches once");
    fs.mkdirSync(paths.statusDir(), { recursive: true });
    fs.writeFileSync(path.join(paths.statusDir(), "fake.json"), JSON.stringify({ pane: h.pane, session_id: "s9", state: "ready", updatedAt: 100, tool: null }));
    fs.mkdirSync(path.dirname(ctx.report), { recursive: true });
    fs.writeFileSync(ctx.report, VALID);
    let ev = await collect(b2, (e) => e.some((x) => x.type === "report") && e.some((x) => x.type === "status"));
    assert.deepEqual(ev.filter((x) => x.type === "status").map((x) => [x.state, x.handle.job, x.handle.pane, x.handle.session_id]),
      [["ready", job.id, h.pane, "s9"]]);
    assert.equal(ev.filter((x) => x.type === "report").length, 1);
    assert.equal(ev.filter((x) => x.type === "started").length, 0);
    await b2.close(row);
    assert.ok(fs.existsSync(path.join(paths.workspace(ctx.worktree), "logs", "myspec-p1_implement1-1.log")));
    ev = await collect(b2, (e) => e.some((x) => x.type === "gone"));
    assert.equal(ev.filter((x) => x.type === "gone").length, 1);
    assert.ok(!ctx.tmux.run(["list-panes", "-a", "-F", "#{pane_id}"]).stdout.split("\n").includes(h.pane));
  });

  test("claude-tmux: a report that does not parse for the job kind emits no report event", async (t) => {
    const env = tmpEnv(); t.after(() => env.restore());
    const ctx = await makeClaudeTmux(env.root); t.after(() => ctx.cleanup());
    const h = await ctx.backend.start(ctx.job({ kind: "review" }));
    const ev = await collect(ctx.backend, (e) => e.some((x) => x.type === "report"), 6000);
    assert.ok(h.pane);
    assert.ok(!ev.some((x) => x.type === "report"), "implementer report is not a review report");
  });

  test("claude-tmux: real agent-status dir (read-only): every file is a record with pane and state, or skipped", (t) => {
    const dir = path.join(process.env.TC_STATE || `${(process.env.TMPDIR || "/tmp").replace(/\/+$/, "")}/tmux-ctl-${process.getuid()}`, "agent-status");
    const { records, skipped } = claudeTmux.readStatusFiles(dir);
    for (const r of records) { assert.equal(typeof r.pane, "string"); assert.equal(typeof r.state, "string"); }
    console.log(`real statusDir ${dir}: read ${records.length} records, skipped ${skipped}`);
    if (!fs.existsSync(dir)) return;
    assert.ok(records.length > 0, "an existing statusDir yields at least one record");
    assert.equal(records.length + skipped, fs.readdirSync(dir).filter((f) => f.endsWith(".json")).length);
  });
}

// ---- usage (Task 5, spec 8b) ----
if (require.main === module) {
  const os = require("node:os");
  const claudeTmux = require("../lib/engine/backend/claude_tmux.js");

  test("fake usage: a {tokens: N} step answers N, {tokens: null} answers null with a reason, no step answers 0", async () => {
    const b = fake.createBackend({ script: { implement1: [{ tokens: 120 }], implement2: [{ tokens: null }] }, reportDir: os.tmpdir() });
    const h1 = await b.start({ id: "s:implement1:1", kind: "implement", task: 1 });
    const h2 = await b.start({ id: "s:implement2:1", kind: "implement", task: 2 });
    const h3 = await b.start({ id: "s:review1:1", kind: "review", task: 1 });
    assert.deepEqual(b.usage(h1, { since: 0 }), { tokens: 120 });
    const u2 = b.usage(h2, { since: 0 });
    assert.equal(u2.tokens, null);
    assert.ok(u2.reason);
    assert.deepEqual(b.usage(h3, { since: 0 }), { tokens: 0 });
    assert.deepEqual(b.usage({ job: "s:fix1:1" }, { since: 0 }), { tokens: 0 }, "a resumed job has no script");
  });

  // One transcript line. ts is ISO.
  const line = (id, u, extra = {}) => JSON.stringify({ type: "assistant", timestamp: extra.ts || "2026-01-01T00:00:10.000Z",
    message: { id, role: "assistant", model: extra.model || "claude-sonnet-5", usage: u } });
  const U = (i, o, c, r = 0) => ({ input_tokens: i, output_tokens: o, cache_creation_input_tokens: c, cache_read_input_tokens: r });
  const SINCE = Date.parse("2026-01-01T00:00:00.000Z") / 1000;
  function transcript(t, lines, sid = "sess-1") {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "etr-"));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    fs.mkdirSync(path.join(root, "-some-project"));
    fs.writeFileSync(path.join(root, "-some-project", `${sid}.jsonl`), lines.join("\n") + "\n");
    return { root, backend: claudeTmux.createBackend({ session: "s", tmuxCtl: "x", statusDir: root, transcriptRoot: root }), handle: { job: "j", session_id: sid } };
  }

  test("claude-tmux usage: input + output + cache creation, cache reads not counted", (t) => {
    const x = transcript(t, [line("m1", U(10, 20, 30, 9999)), line("m2", U(1, 2, 3))]);
    assert.deepEqual(x.backend.usage(x.handle, { since: SINCE }), { tokens: 66 });
  });

  test("claude-tmux usage: one message id on three lines counts once", (t) => {
    const x = transcript(t, [line("m1", U(10, 20, 30)), line("m1", U(10, 20, 30)), line("m1", U(10, 20, 30)), line("m2", U(1, 1, 1))]);
    assert.deepEqual(x.backend.usage(x.handle, { since: SINCE }), { tokens: 63 });
  });

  test("claude-tmux usage: <synthetic> rows, rows before `since`, and lines without usage are left out", (t) => {
    const x = transcript(t, [
      line("m1", U(1, 1, 1)),
      line("m2", U(100, 100, 100), { model: "<synthetic>" }),
      line("m3", U(100, 100, 100), { ts: "2025-12-31T23:59:59.000Z" }),
      JSON.stringify({ type: "user", timestamp: "2026-01-01T00:00:10.000Z", message: { role: "user", content: "hi" } }),
      "not json",
    ]);
    assert.deepEqual(x.backend.usage(x.handle, { since: SINCE }), { tokens: 3 });
  });

  test("claude-tmux usage: no session id, no file, no matching row -> tokens null with a reason", (t) => {
    const x = transcript(t, [line("m3", U(5, 5, 5), { ts: "2025-01-01T00:00:00.000Z" })]);
    for (const [handle, what] of [[{ job: "j" }, /session id/], [{ job: "j", session_id: "other" }, /no transcript/], [x.handle, /no usage rows/]]) {
      const u = x.backend.usage(handle, { since: SINCE });
      assert.equal(u.tokens, null);
      assert.match(u.reason, what);
    }
  });

  test("claude-tmux usage: the default root is $CLAUDE_CONFIG_DIR/projects", (t) => {
    const x = transcript(t, [line("m1", U(1, 1, 1))]);
    const old = process.env.CLAUDE_CONFIG_DIR;
    t.after(() => { if (old === undefined) delete process.env.CLAUDE_CONFIG_DIR; else process.env.CLAUDE_CONFIG_DIR = old; });
    const cfg = fs.mkdtempSync(path.join(os.tmpdir(), "ecfg-"));
    t.after(() => fs.rmSync(cfg, { recursive: true, force: true }));
    fs.symlinkSync(x.root, path.join(cfg, "projects"));
    process.env.CLAUDE_CONFIG_DIR = cfg;
    const b = claudeTmux.createBackend({ session: "s", tmuxCtl: "x", statusDir: x.root });
    assert.deepEqual(b.usage(x.handle, { since: SINCE }), { tokens: 3 });
  });

  // Real state, read-only: the newest transcript under the real ~/.claude/projects.
  test("claude-tmux usage on the newest real transcript: an integer above 0", (t) => {
    const root = path.join(process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"), "projects");
    if (!fs.existsSync(root)) { t.skip(`no ${root} on this machine`); console.log(`# skipped: no ${root}`); return; }
    const files = [];
    for (const d of fs.readdirSync(root)) {
      let names = [];
      try { names = fs.readdirSync(path.join(root, d)); } catch { continue; }
      for (const n of names) if (n.endsWith(".jsonl")) { const p = path.join(root, d, n); files.push({ p, m: fs.statSync(p).mtimeMs, sid: n.slice(0, -6) }); }
    }
    const withUsage = files.sort((a, b) => b.m - a.m).find((f) => /"usage"/.test(fs.readFileSync(f.p, "utf8")));
    console.log(`# real transcripts looked at: ${files.length}; newest with usage: ${withUsage ? path.basename(withUsage.p) : "none"}`);
    if (!withUsage) { t.skip("no real transcript with usage rows"); return; }
    const b = claudeTmux.createBackend({ session: "s", tmuxCtl: "x", statusDir: root, transcriptRoot: root });
    const u = b.usage({ job: "j", session_id: withUsage.sid }, { since: 0 });
    assert.ok(Number.isInteger(u.tokens) && u.tokens > 0, JSON.stringify(u));
  });
}
