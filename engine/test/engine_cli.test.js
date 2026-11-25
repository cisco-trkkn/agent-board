"use strict";
// The engine CLI as a child process (spec section 5): every subcommand's exit code, on a fake backend, a scratch
// git repo and a temp TC_ENGINE_DIR. Nothing here opens ~/.local/state/agent-board.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo, scratchTmux } = require("./engine_helpers");
const db = require("../lib/engine/db");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const TMUX_CTL = path.resolve(__dirname, "../../bin/tmux-ctl");
const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const SPEC_B = "docs/superpowers/specs/2026-01-02-other-design.md";
const PLAN_B = "docs/superpowers/plans/2026-01-02-other.md";

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = report({ status: "blocked", commits: [], concerns: ["needs a secret"] });
const PASS = report({ verdict: "pass", findings: [] });
const FAIL_SPEC = report({ decision: "fail_spec", ruling: "give up", cost_if_wrong: "none" });
const worker = (text) => [{ status: "busy", at: 0.1 }, { report: text, at: 0.3 }, { status: "ready", at: 0.5 }];
const GOOD = { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) };

const task = (verifyCommand = "true") => ({
  subject: "T1",
  description: `Do T1.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand, modelTier: "standard", files: ["a.js"] })}\n\`\`\``,
});

// A scratch project: the main checkout (branch main) and a spec worktree on branch spec-demo holding a committed
// plan and its .tasks.json. `ctl` is a stub tmux-ctl that logs its arguments and answers "fresh".
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
  if (o.second) { // a second spec with its plan, for the runs that put one spec beside another
    w(SPEC_B, "# Other\n\n## Decisions\n\n- D1: keep it small.\n");
    w(PLAN_B, `# Other plan\n\n**Spec:** ${SPEC_B}\n`);
    w(`${PLAN_B}.tasks.json`, JSON.stringify({ tasks: [task()] }));
  }
  repo.git("add", "-A");
  repo.git("commit", "-q", "-m", "spec and plan");
  const wt = fs.mkdtempSync(path.join(os.tmpdir(), "ecli-wt-"));
  fs.rmSync(wt, { recursive: true });
  repo.git("worktree", "add", "-q", "-b", "spec-demo", wt);
  const log = path.join(env.root, "ctl.log");
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, o.ctlFail
    ? `#!/bin/sh\necho "$@" >> "${log}"\nif [ "$2" = start ]; then echo "metrics: unknown batch b1" >&2; exit 1; fi\necho fresh\nexit 0\n`
    : `#!/bin/sh\necho "$@" >> "${log}"\necho fresh\nexit 0\n`, { mode: 0o755 });
  const scriptFile = path.join(env.root, "script.json");
  fs.writeFileSync(scriptFile, JSON.stringify(o.script || GOOD));
  const childEnv = { ...process.env, HOME: env.root, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "demo", TC_TMUX_CTL: ctl };
  delete childEnv.TMUX;
  delete childEnv.TC_SESSION;
  const p = {
    env, repo, wt, ctl, log, scriptFile, childEnv,
    args: (...a) => a,
    run(args, opts = {}) {
      const r = cp.spawnSync("node", [ENGINE, ...args], { cwd: opts.cwd || wt, env: { ...childEnv, ...(opts.env || {}) }, encoding: "utf8", timeout: 60000 });
      return { code: r.status, out: r.stdout, err: r.stderr };
    },
    runSpec: (extra = []) => p.run(["run", SPEC, "--integration", "keep", "--batch", "b1", "--backend", "fake", "--script", scriptFile, ...extra]),
    ctlLog: () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8") : ""),
    open: () => db.open("demo"),
  };
  t.after(() => {
    try { repo.git("worktree", "remove", "--force", wt); } catch (_) { /* already gone */ }
    repo.cleanup();
    env.restore();
  });
  return p;
}

// ---- usage -----------------------------------------------------------------------------------------------------

test("no subcommand and a bad subcommand print the usage line and exit 2", (t) => {
  const p = project(t);
  for (const args of [[], ["bogus"]]) {
    const r = p.run(args);
    assert.equal(r.code, 2);
    assert.equal(r.err, "engine: usage: engine <run|status|events|resume|signal|rebuild|enqueue|start|done|schedule> ...\n");
  }
});

test("run without --integration, or with a bad one, exits 2", (t) => {
  const p = project(t);
  assert.equal(p.run(["run", SPEC]).code, 2);
  assert.equal(p.run(["run", SPEC, "--integration", "squash"]).code, 2);
  assert.equal(p.run(["run", "--integration", "keep"]).code, 2);
});

test("a command without a project (no --project, no TC_PROJECT) exits 2", (t) => {
  const p = project(t);
  const r = p.run(["status"], { env: { TC_PROJECT: "" } });
  assert.equal(r.code, 2);
  assert.match(r.err, /no project/);
});

// ---- run -------------------------------------------------------------------------------------------------------

test("run: a one-task plan reaches kept, prints one line per event, exit 0, metrics start ran as a step", (t) => {
  const p = project(t);
  const r = p.runSpec();
  assert.equal(r.code, 0, r.err + r.out);
  const lines = r.out.trim().split("\n");
  const events = lines.filter((l) => l !== lines[lines.length - 1]);
  for (const l of events) assert.match(l, /^\d\d:\d\d:\d\d \S+ \S+( .*)?$/, `event line: ${l}`);
  assert.ok(events.some((l) => /^\d\d:\d\d:\d\d spec_added - /.test(l)), "spec_added line");
  assert.ok(events.some((l) => / dispatched \S+:implement1:1 /.test(l)), "dispatched line carries the job id");
  assert.match(lines[lines.length - 1], /^outcome: kept spec-demo$/);
  assert.equal(events.filter((l) => /^\d\d:\d\d:\d\d (deadline|timer_fired|step_intent|step_done|job_session|inbox_\w+) /.test(l)).length, 0, "bookkeeping hidden");
  assert.match(p.ctlLog(), new RegExp(`metrics start ${SPEC} --batch b1 --worktree ${fs.realpathSync(p.wt).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  const d = p.open();
  try {
    const step = d.prepare("SELECT * FROM steps WHERE key=?").get(`metrics_start:${SPEC}`);
    assert.equal(step.kind, "metrics_start");
    assert.equal(step.state, "done");
    const s = d.prepare("SELECT * FROM specs WHERE id=?").get(SPEC);
    assert.equal(s.integration, "keep");
    assert.equal(s.push, 0);
    assert.equal(s.branch, "spec-demo");
    assert.equal(s.batch, "b1");
    assert.equal(s.plan, PLAN);
  } finally { d.close(); }
});

test("run: a spec already done prints its outcome again and exits by it, without running anything", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const before = p.ctlLog();
  const r = p.runSpec();
  assert.equal(r.code, 0);
  assert.equal(r.out.trim(), "outcome: kept spec-demo");
  assert.equal(p.ctlLog(), before);
});

test("run: a failed outcome exits 1", (t) => {
  const p = project(t, { script: { implement1: worker(BLOCKED), architect: worker(FAIL_SPEC) } });
  const r = p.runSpec();
  assert.equal(r.code, 1, r.err + r.out);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: failed — /);
});

test("run: a plan without a verifyCommand prints [Engine] your turn and exits 3, and inserts nothing", (t) => {
  const p = project(t, { tasks: [{ subject: "T1", description: "no metadata" }] });
  fs.writeFileSync(path.join(p.wt, `${PLAN}.tasks.json`), JSON.stringify({ tasks: [{ subject: "T1", description: "no metadata" }] }));
  const r = p.runSpec();
  assert.equal(r.code, 3);
  assert.equal(r.out.trim(), `[Engine] your turn: ${SPEC}`);
  assert.match(r.err, /no verifyCommand: task 1/);
  assert.equal(fs.existsSync(path.join(p.env.engineDir, "demo.sqlite")), false);
});

test("run: no .tasks.json, a plan only on another branch, and no plan naming the spec all exit 3", (t) => {
  const p = project(t);
  fs.rmSync(path.join(p.wt, `${PLAN}.tasks.json`));
  const a = p.runSpec();
  assert.equal(a.code, 3);
  assert.match(a.err, /no \.tasks\.json/);
  fs.writeFileSync(path.join(p.wt, PLAN), "# Demo plan\n\nno spec line\n");
  const b = p.runSpec();
  assert.equal(b.code, 3);
  assert.match(b.err, /its plan is on branch refs\/heads\/main/);
  const other = "docs/superpowers/specs/2026-01-02-other-design.md";
  fs.writeFileSync(path.join(p.wt, other), "# Other\n");
  const c = p.run(["run", other, "--integration", "keep", "--backend", "fake"]);
  assert.equal(c.code, 3);
  assert.match(c.err, /no plan names/);
  assert.equal(c.out.trim(), `[Engine] your turn: ${other}`);
});

test("run: a spec file that does not exist exits 2", (t) => {
  const p = project(t);
  const r = p.run(["run", "docs/superpowers/specs/nope.md", "--integration", "keep", "--backend", "fake"]);
  assert.equal(r.code, 2);
});

test("run: an unfinished spec already in the database exits 1 and points at resume", (t) => {
  const p = project(t);
  const d = p.open();
  d.prepare("INSERT INTO specs (id, state, integration) VALUES (?, 'running', 'keep')").run(SPEC);
  d.close();
  const r = p.runSpec();
  assert.equal(r.code, 1);
  assert.match(r.err, /use engine resume/);
});

// Mutation for the next two tests: the unfinished-spec check dropped from cmdRun fails the first (B is inserted).
test("M5: run B beside an unfinished spec A exits 1 naming A and its state, and inserts nothing", (t) => {
  const p = project(t, { second: true });
  const d = p.open();
  d.prepare("INSERT INTO specs (id, state, integration) VALUES (?, 'running', 'keep')").run(SPEC);
  d.close();
  const r = p.run(["run", SPEC_B, "--integration", "keep", "--backend", "fake", "--script", p.scriptFile]);
  assert.equal(r.code, 1, r.err + r.out);
  assert.ok(r.err.split("\n").includes(`engine: run: ${SPEC} is unfinished (running): use engine resume`), r.err);
  const e = p.open();
  try { assert.equal(e.prepare("SELECT COUNT(*) AS n FROM specs WHERE id=?").get(SPEC_B).n, 0, "B was not inserted"); } finally { e.close(); }
});

test("M5: a spec in awaiting_you that already has an outcome does not count as unfinished", (t) => {
  const p = project(t, { second: true });
  const d = p.open();
  d.prepare("INSERT INTO specs (id, state, outcome, integration) VALUES (?, 'awaiting_you', 'failed: x', 'keep')").run(SPEC);
  d.close();
  const r = p.run(["run", SPEC_B, "--integration", "keep", "--backend", "fake", "--script", p.scriptFile]);
  assert.doesNotMatch(r.err, /is unfinished/);
  const e = p.open();
  try { assert.equal(e.prepare("SELECT COUNT(*) AS n FROM specs WHERE id=?").get(SPEC_B).n, 1, "B was inserted"); } finally { e.close(); }
});

// ---- status and events -----------------------------------------------------------------------------------------

test("status: no database prints no specs; after a run it lists the spec and, by name, its jobs and last events", (t) => {
  const p = project(t);
  const none = p.run(["status"]);
  assert.equal(none.code, 0);
  assert.equal(none.out.trim(), "no specs");
  assert.equal(p.run(["status", "--waiting"]).out.trim(), "nothing is waiting");
  assert.equal(p.runSpec().code, 0);
  const all = p.run(["status"]);
  assert.equal(all.code, 0);
  assert.match(all.out, new RegExp(`^${SPEC}  done  kept spec-demo  keep$`, "m"));
  const one = p.run(["status", SPEC]);
  assert.equal(one.code, 0);
  assert.match(one.out, /:implement1:1 {2}done /);
  assert.match(one.out, /:review1:1 {2}done /);
  assert.match(one.out, /last events:/);
  const bad = p.run(["status", "docs/superpowers/specs/other.md"]);
  assert.equal(bad.code, 1);
  assert.match(bad.err, /no such spec/);
});

test("events: prints every event including the bookkeeping the foreground run hides; unknown spec exits 1", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const r = p.run(["events", SPEC]);
  assert.equal(r.code, 0);
  const lines = r.out.trim().split("\n");
  assert.match(lines[0], /^\d\d:\d\d:\d\d spec_added - /);
  assert.ok(lines.some((l) => / step_done /.test(l)), "step_done is listed by events");
  assert.ok(lines.length > r.out.trim().split("\n").filter((l) => !/ (step_intent|step_done|deadline|timer_fired|job_session|inbox_\w+) /.test(l)).length);
  const unknown = p.run(["events", "docs/superpowers/specs/other.md"]);
  assert.equal(unknown.code, 1);
  assert.equal(p.run(["events"]).code, 2);
});

// ---- signal and status --waiting -------------------------------------------------------------------------------

function park(p) {
  const d = p.open();
  db.tx(d, () => {
    db.put(d, "specs", { id: SPEC, state: "awaiting_you", integration: "keep", push: 0, position: 0, runner: "engine", created_at: 1, updated_at: 1 });
    db.put(d, "waits", { id: `${SPEC}@1#1`, spec: SPEC, step: "integrate", question: "live checkout is mid-change", options: "approve|deny|fail", asked_at: 1700000000, answered_at: null, answer: null, note: null,
      kind: "stop_class", recommendation: JSON.stringify({ option: "approve", why: "approve retries once the live checkout is clean", confidence: "low" }) });
  });
  d.close();
}

test("status --waiting shows question, options, asked at and the exact signal command", (t) => {
  const p = project(t);
  park(p);
  const r = p.run(["status", "--waiting"]);
  assert.equal(r.code, 0);
  assert.match(r.out, new RegExp(`^${SPEC}$`, "m"));
  assert.match(r.out, /question: live checkout is mid-change/);
  const lines = r.out.split("\n");
  assert.equal(lines[lines.indexOf(SPEC) + 1], "  I recommend: approve (low): approve retries once the live checkout is clean", "the recommendation is the first line under the spec id");
  assert.match(lines[lines.indexOf(SPEC) + 2], /^ {2}question:/);
  assert.match(r.out, /options: {2}approve\|deny\|fail/);
  assert.match(r.out, /asked at: 2023-11-14T22:13:20\.000Z/);
  assert.match(r.out, new RegExp(`answer: {3}tmux-ctl engine signal ${SPEC} approve\\|deny\\|fail`));
});

test("signal: an open wait gets an inbox row and exit 0; no wait exits 2; a bad answer exits 2", (t) => {
  const p = project(t);
  assert.equal(p.run(["signal", SPEC, "approve"]).code, 2, "no database");
  park(p);
  const bad = p.run(["signal", SPEC, "maybe"]);
  assert.equal(bad.code, 2);
  assert.match(bad.err, /usage: engine signal/);
  const other = p.run(["signal", "docs/superpowers/specs/other.md", "approve"]);
  assert.equal(other.code, 2);
  assert.match(other.err, /no open wait for docs\/superpowers\/specs\/other\.md/);
  const ok = p.run(["signal", SPEC, "deny", "--note", "not now"]);
  assert.equal(ok.code, 0, ok.err);
  assert.match(ok.out, /signalled .* deny/);
  assert.match(ok.out, /no engine is running/);
  const d = p.open();
  try {
    const row = d.prepare("SELECT * FROM inbox WHERE spec=? AND kind='signal'").get(SPEC);
    assert.deepEqual(JSON.parse(row.payload), { answer: "deny", note: "not now" });
  } finally { d.close(); }
});

// ---- resume ----------------------------------------------------------------------------------------------------

test("resume: nothing unfinished exits 0; a spec whose engine was killed mid-job is carried to its outcome", async (t) => {
  const p = project(t);
  assert.equal(p.run(["resume", "--backend", "fake"]).out.trim(), "nothing to resume");
  fs.mkdirSync(path.join(p.repo.dir, "docs/superpowers"), { recursive: true });
  fs.writeFileSync(path.join(p.repo.dir, "docs/superpowers/engine.json"), JSON.stringify({ retry: { implement: { backoff_s: [0] } } }));
  const hang = path.join(p.env.root, "hang.json");
  fs.writeFileSync(hang, JSON.stringify({ implement1: [{ hang: true, at: 0.1 }] }));
  const child = cp.spawn("node", [ENGINE, "run", SPEC, "--integration", "keep", "--batch", "b1", "--backend", "fake", "--script", hang],
    { cwd: p.wt, env: p.childEnv, stdio: "ignore" });
  t.after(() => { try { child.kill("SIGKILL"); } catch (_) { /* gone */ } });
  const t0 = Date.now();
  for (;;) {
    if (fs.existsSync(path.join(p.env.engineDir, "demo.sqlite"))) {
      let n = 0;
      try { // the engine holds a write lock for a moment
        const d = p.open();
        try { n = d.prepare("SELECT COUNT(*) AS n FROM jobs WHERE state='running'").get().n; } finally { d.close(); }
      } catch (_) { n = 0; }
      if (n) break;
    }
    assert.ok(Date.now() - t0 < 20000, "the first engine never started a job");
    await new Promise((r) => setTimeout(r, 100));
  }
  child.kill("SIGKILL");
  await new Promise((r) => child.once("exit", r));
  const r = p.run(["resume", "--backend", "fake", "--script", p.scriptFile]);
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: kept spec-demo$/);
  assert.match(r.out, / resumed /);
  const st = p.run(["status"]);
  assert.match(st.out, /done {2}kept spec-demo/);
});

test("resume: a finished (failed) spec is not resumed", (t) => {
  const p = project(t, { script: { implement1: worker(BLOCKED), architect: worker(FAIL_SPEC) } });
  const first = p.runSpec();
  assert.equal(first.code, 1);
  assert.equal(p.run(["resume", "--backend", "fake"]).out.trim(), "nothing to resume", "a done spec is not resumed");
});

// Mutation: cmdResume returns "nothing to resume" before starting the core -> the row stays at intent (fails this test).
test("resume: every spec done and a close_window row at intent: the core starts, reconciles the row and exits 0", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const d = p.open();
  db.put(d, "steps", { key: "close_window:demo:final", spec: SPEC, kind: "close_window", state: "intent", result: JSON.stringify({ pane: "%999999" }), created_at: 1, updated_at: 1 });
  d.close();
  // the close_window check lists panes with tmux: point it at a scratch socket directory, never the user's server
  const tmuxDir = fs.mkdtempSync("/tmp/et-");
  t.after(() => fs.rmSync(tmuxDir, { recursive: true, force: true }));
  const r = p.run(["resume", "--backend", "fake"], { env: { TMUX_TMPDIR: tmuxDir } });
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out, /reconciled 1 step\(s\)/);
  const e = p.open();
  try { assert.equal(e.prepare("SELECT state FROM steps WHERE key='close_window:demo:final'").get().state, "done"); } finally { e.close(); }
  assert.equal(p.run(["resume", "--backend", "fake"]).out.trim(), "nothing to resume", "no row at intent: nothing to resume");
});

// ---- metrics start (F1, F2) ------------------------------------------------------------------------------------

test("run: a failing metrics start leaves the step failed, prints its step_failed line, and the run still reaches its outcome", (t) => {
  const p = project(t, { ctlFail: true });
  const r = p.runSpec();
  assert.equal(r.code, 0, r.err + r.out);
  assert.match(r.out, /step_failed - metrics start: .*unknown batch b1/);
  assert.match(r.out.trim().split("\n").pop(), /^outcome: kept spec-demo$/);
  const d = p.open();
  try {
    const step = d.prepare("SELECT * FROM steps WHERE key=?").get(`metrics_start:${SPEC}`);
    assert.equal(step.state, "failed");
    assert.match(step.result, /unknown batch b1/);
    assert.equal(d.prepare("SELECT state FROM specs WHERE id=?").get(SPEC).state, "done");
  } finally { d.close(); }
});

test("the metrics start argv is accepted by the real board/metrics.py parser (spec positional, --batch, --worktree)", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const argv = p.ctlLog().split("\n").find((l) => l.startsWith("metrics start ")).trim().split(" ").slice(2);
  assert.equal(argv[0], SPEC);
  // A parse error exits 2 with "usage:"; an accepted argv gets as far as the log lookup ("unknown batch").
  // (the real parser also wants the worktree under .claude/worktrees/, so that one value is swapped)
  argv[argv.indexOf("--worktree") + 1] = path.join(p.repo.dir, ".claude/worktrees/x");
  const r = cp.spawnSync("python3", [path.resolve(__dirname, "../../board/metrics.py"), "start", ...argv, "--repo", p.repo.dir], { encoding: "utf8" });
  assert.doesNotMatch(r.stderr, /unrecognized arguments|usage:/);
  assert.match(r.stderr + r.stdout, /unknown batch b1/);
});

// ---- rebuild ---------------------------------------------------------------------------------------------------

test("rebuild --check exits 0 on a faithful database and 1 on a drifted one; --apply repairs it", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const ok = p.run(["rebuild", "--check"]);
  assert.equal(ok.code, 0, ok.out + ok.err);
  assert.match(ok.out, /replay matches/);
  const d = p.open();
  d.prepare("UPDATE specs SET state='queued', outcome=NULL WHERE id=?").run(SPEC);
  d.close();
  const bad = p.run(["rebuild", "--check"]);
  assert.equal(bad.code, 1);
  assert.match(bad.out, /specs .*state live=queued replay=done/);
  const fix = p.run(["rebuild", "--apply"]);
  assert.equal(fix.code, 0, fix.err);
  assert.match(fix.out, /backup /);
  assert.equal(p.run(["rebuild", "--check"]).code, 0);
});

test("rebuild --apply with the engine lock held exits 2; no flag or both flags exit 2", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  fs.writeFileSync(path.join(p.env.engineDir, "demo.lock"), `${process.pid}\n`);
  const held = p.run(["rebuild", "--apply"]);
  assert.equal(held.code, 2);
  assert.match(held.err, /engine lock held/);
  assert.equal(p.run(["rebuild"]).code, 2);
  assert.equal(p.run(["rebuild", "--check", "--apply"]).code, 2);
});

// ---- tmux-ctl engine -------------------------------------------------------------------------------------------

test("tmux-ctl engine bogus exits 2 with the usage line, outside tmux too", () => {
  const env = { ...process.env };
  delete env.TMUX;
  const r = cp.spawnSync("zsh", [TMUX_CTL, "engine", "bogus"], { env, encoding: "utf8" });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /engine: usage: engine <run\|status/);
});

test("tmux-ctl engine exports TC_PROJECT from the session's feed key: status reads that project's database", (t) => {
  const e = tmpEnv();
  const tm = scratchTmux();
  t.after(() => { tm.kill(); e.restore(); });
  assert.equal(tm.run(["new-session", "-d", "-s", "cliproj", "-x", "80", "-y", "24"]).status, 0);
  const sock = tm.run(["display", "-p", "#{socket_path}"]).stdout.trim();
  const prev = process.env.TC_ENGINE_DIR;
  const d = db.open("cliproj");
  d.prepare("INSERT INTO specs (id, state, integration) VALUES ('s1.md', 'queued', 'keep')").run();
  d.close();
  if (prev === undefined) delete process.env.TC_ENGINE_DIR; else process.env.TC_ENGINE_DIR = prev;
  const env = { ...process.env, TMUX: `${sock},0,0`, TMUX_DASH_TMUX_ARGS: `-L ${tm.socket}`, TMUX_TMPDIR: path.dirname(sock).replace(/\/tmux-\d+$/, ""),
    TC_SESSION: "cliproj", TC_ENGINE_DIR: e.engineDir, TC_STATE: e.state, HOME: e.root };
  delete env.TC_PROJECT;
  const r = cp.spawnSync("zsh", [TMUX_CTL, "engine", "status"], { env, encoding: "utf8", timeout: 30000 });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^s1\.md {2}queued {2}- {2}keep$/m);
});

// ---- budget (Task 5, spec 8b) ----

test("run --budget-attempts/--budget-tokens: stored on the spec; a value that is not a positive integer exits 2 and starts nothing", (t) => {
  const bad = project(t);
  for (const v of ["0", "-1", "1.5", "abc", "5x"]) {
    for (const flag of ["--budget-attempts", "--budget-tokens"]) {
      const r = bad.runSpec([flag, v]);
      assert.equal(r.code, 2, `${flag} ${v}: ${r.err}`);
      assert.match(r.err, new RegExp(`${flag} needs a positive integer`));
    }
  }
  assert.ok(!fs.existsSync(path.join(bad.env.engineDir, "demo.sqlite")), "nothing was created");
  const p = project(t);
  const r = p.runSpec(["--budget-attempts", "20", "--budget-tokens", "123456"]);
  assert.equal(r.code, 0, r.err + r.out);
  const d = p.open();
  try {
    const s = d.prepare("SELECT * FROM specs WHERE id=?").get(SPEC);
    assert.deepEqual([s.budget_attempts, s.budget_tokens, s.spent_attempts, s.spent_tokens], [20, 123456, 3, 0]);
  } finally { d.close(); }
  // finalize passed the spend and the engine jobs to `metrics record`
  assert.match(p.ctlLog(), /metrics record \S+ --batch b1 --outcome kept spec-demo --budget \{"attempts":\[3,20\],"tokens":\[0,123456\],"lower_bound":false\} --engine-jobs \{/);
});

test("status <spec> prints attempts a/A · tokens t/T, with (lower bound) once an ended job has null tokens", (t) => {
  const p = project(t);
  assert.equal(p.runSpec().code, 0);
  const plain = p.run(["status", SPEC]);
  assert.match(plain.out, /^  attempts 3\/60 · tokens 0\/5000000$/m);
  assert.doesNotMatch(plain.out, /lower bound/);
  const d = p.open();
  try { d.prepare("UPDATE jobs SET tokens=NULL WHERE rowid=(SELECT MIN(rowid) FROM jobs)").run(); } finally { d.close(); }
  assert.match(p.run(["status", SPEC]).out, /^  attempts 3\/60 · tokens 0\/5000000 \(lower bound\)$/m);
});
