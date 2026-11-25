"use strict";
// The engine's command line (spec sections 5 and 6): run, status, events, resume, signal, rebuild, and the queue's
// enqueue, start and done.
// main(argv, io) resolves to the exit code; io = {out, err, cwd} (defaults: stdout, stderr, process.cwd()).
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const paths = require("./paths");
const feed = require("./feed");
const { compile } = require("./compile");
const { findPlan, mainRoot } = require("../registry/git");

// node:sqlite prints an experimental warning on load: these load only when a subcommand needs the database, so a
// usage error stays one clean line.
const lazy = (name) => new Proxy({}, { get: (_, k) => require(name)[k] });
const db = lazy("./db");
const inbox = lazy("./inbox");
const rebuild = lazy("./rebuild");
const lead = lazy("./lead");
const queue = lazy("./queue");
const schedule = lazy("./schedule");

const SUBS = ["run", "status", "events", "resume", "signal", "rebuild", "enqueue", "start", "done", "schedule", "wake"];
const USAGE = `engine: usage: engine <${SUBS.join("|")}> ...\n`;
const ANSWERS = ["approve", "deny", "fail"];
const OK_OUTCOME = /^(merged|mr|kept)/;
// Bookkeeping events the foreground printer hides: three deadline re-arms per job every two minutes, timer and inbox
// plumbing, session id updates and the step journal's intent/done pair. `engine events` prints everything.
const QUIET = /^(deadline|timer_fired|inbox_.*|job_session|step_intent|step_done)$/;
const TICK_MS_FAKE = 100;

const VALUE_FLAGS = new Set(["--integration", "--batch", "--project", "--backend", "--note", "--script", "--budget-attempts", "--budget-tokens",
  "--runner", "--gate", "--worktree", "--outcome", "--rule", "--skip-if-weekly-usage"]);
const BOOL_FLAGS = new Set(["--push", "--waiting", "--check", "--apply", "--preflight", "--here", "--unfinished", "--dry-run"]);

function parseArgs(argv) {
  const pos = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (VALUE_FLAGS.has(a)) {
      if (i + 1 >= argv.length || argv[i + 1].startsWith("--")) return { error: `${a} needs a value` };
      flags[a.slice(2)] = argv[++i];
    } else if (BOOL_FLAGS.has(a)) {
      flags[a.slice(2)] = true;
    } else if (a.startsWith("--")) {
      return { error: `unknown option ${a}` };
    } else {
      pos.push(a);
    }
  }
  return { pos, flags };
}

const pad = (n) => String(n).padStart(2, "0");
function hms(ts) {
  const d = new Date(ts * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function iso(ts) { return new Date(ts * 1000).toISOString(); }

function parseJson(s) {
  if (s && typeof s === "object") return s;
  try { return JSON.parse(s); } catch (_) { return {}; }
}

function shortText(detail) {
  const d = detail && typeof detail === "object" ? detail : {};
  for (const k of ["text", "question", "reason", "error", "outcome", "window", "key"]) {
    if (typeof d[k] === "string" && d[k]) return d[k].replace(/\s+/g, " ").slice(0, 140);
  }
  return "";
}

// <HH:MM:SS> <kind> <job or -> <short text>
function eventLine(e) {
  const t = shortText(parseJson(e.detail));
  return `${hms(e.ts)} ${e.kind} ${e.job || "-"}${t ? " " + t : ""}`;
}

function dbExists(project) { return fs.existsSync(paths.dbPath(project)); }

function engineRunning(project) {
  let pid;
  try { pid = parseInt(fs.readFileSync(paths.lockPath(project), "utf8").split("\n")[0], 10); } catch (_) { return false; }
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}

function git(dir, args) {
  const r = cp.spawnSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}

// The tmux-ctl of this install (the engine lives in its checkout), unless TC_TMUX_CTL says otherwise.
const tmuxCtlPath = () => process.env.TC_TMUX_CTL || path.resolve(__dirname, "../../../bin/tmux-ctl");

// ---- backend and core ------------------------------------------------------------------------------------------

function makeBackend(kind, flags, session, tmuxCtl, project) {
  if (kind === "fake") {
    let script = {};
    if (flags.script) script = JSON.parse(fs.readFileSync(flags.script, "utf8"));
    return { backend: require("./backend/fake").createBackend({ script }), tickMs: TICK_MS_FAKE };
  }
  if (kind === "claude-tmux") {
    if (!session) throw Object.assign(new Error("run it from a tmux session (TC_SESSION is not set)"), { usage: true });
    const tmuxArgs = (process.env.TMUX_DASH_TMUX_ARGS || "").split(/\s+/).filter(Boolean);
    const backend = require("./backend/claude_tmux").createBackend({ session, tmuxCtl, statusDir: paths.statusDir(), tmuxArgs, project });
    return { backend, tmuxArgs };
  }
  throw Object.assign(new Error(`unknown backend ${kind} (claude-tmux|fake)`), { usage: true });
}

// A lead notification: printed in the foreground and published as a feed decision line (the board and the Discord
// bridge show feed lines). `tmux-ctl tell` refuses the lead's window, so it is not used.
function notifier(project, out) {
  return (text) => {
    out(text);
    feed.publish(project, { ts: Date.now() / 1000, spec: null, job: null, kind: "park", detail: { text } });
  };
}

function startCore(ctx, flags, backendKind, extra = {}) {
  const core = require("./core");
  const tmuxCtl = tmuxCtlPath();
  const session = process.env.TC_SESSION || "";
  const { backend, tickMs, tmuxArgs } = makeBackend(backendKind, flags, session, tmuxCtl, ctx.project);
  const eng = core.start({
    project: ctx.project, repo: ctx.repo, backend, tmuxCtl, session, tmuxArgs, tickMs, backendKind, ...queue.reportHooks, ...extra,
    notify: notifier(ctx.project, ctx.out),
    onEvent: (e) => { if (!QUIET.test(e.kind)) ctx.out(eventLine(e)); },
  });
  return eng;
}

function resolveProject(flags, io) {
  const p = flags.project || process.env.TC_PROJECT;
  if (!p) { io.err("engine: no project: run it from a tmux session or pass --project\n"); return null; }
  return p;
}

// ---- run -------------------------------------------------------------------------------------------------------

function yourTurn(io, spec, why) {
  io.err(`engine: ${why}\n`);
  io.out(`[Engine] your turn: ${spec}`);
  return 3;
}

// --budget-attempts and --budget-tokens as spec columns, or {error}.
function budgetFlags(flags) {
  const budget = {};
  for (const [flag, col] of [["budget-attempts", "budget_attempts"], ["budget-tokens", "budget_tokens"]]) {
    if (flags[flag] === undefined) continue;
    if (!/^[1-9]\d*$/.test(flags[flag])) return { error: `--${flag} needs a positive integer, got ${flags[flag]}` };
    budget[col] = Number(flags[flag]);
  }
  return { budget };
}

// Whether the engine can run the spec from this checkout: {plan} or {why} (spec Error handling).
function planCheck(worktree, spec) {
  const found = findPlan(worktree, spec);
  if (!found) return { why: `no plan names ${spec} on its **Spec:** line` };
  if (found.ref) return { why: `its plan is on branch ${found.ref}, not in this checkout: run from that worktree` };
  const tasksFile = path.resolve(worktree, `${found.path}.tasks.json`);
  const c = compile(fs.existsSync(tasksFile) ? fs.readFileSync(tasksFile, "utf8") : null);
  if (c.error) return { why: `${found.path}: ${c.error}` };
  return { plan: found.path };
}

async function runSpec(eng, specId, io) {
  const stop = () => { eng.stop(); process.exit(130); };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    const outcome = await eng.run(specId);
    io.out(`outcome: ${outcome}`);
    return OK_OUTCOME.test(String(outcome)) ? 0 : 1;
  } finally {
    process.removeListener("SIGINT", stop);
    process.removeListener("SIGTERM", stop);
  }
}

async function cmdRun(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length !== 1 || !["merge", "mr", "keep"].includes(p.flags.integration)) {
    io.err(`engine: run: ${p.error || "usage: engine run <spec> --integration merge|mr|keep [--push] [--batch <id>] [--budget-attempts N] [--budget-tokens N] [--project P] [--backend claude-tmux|fake]"}\n`);
    return 2;
  }
  const spec = p.pos[0];
  const { budget, error } = budgetFlags(p.flags);
  if (error) { io.err(`engine: run: ${error}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  const backendKind = p.flags.backend || "claude-tmux";

  const worktree = git(io.cwd, ["rev-parse", "--show-toplevel"]);
  if (!worktree) { io.err("engine: run: not inside a git checkout\n"); return 2; }
  const specFile = spec.split("#")[0];
  if (!fs.existsSync(path.resolve(worktree, specFile))) { io.err(`engine: run: no such spec file: ${specFile}\n`); return 2; }

  const found = planCheck(worktree, spec);
  if (found.why) return yourTurn(io, spec, found.why);

  const repo = mainRoot(worktree);
  const eng = startCore({ project, repo, out: io.out }, p.flags, backendKind);
  try {
    const have = eng.db.prepare("SELECT * FROM specs WHERE id=?").get(spec);
    if (have && have.state === "done") {
      io.out(`outcome: ${have.outcome}`);
      return OK_OUTCOME.test(String(have.outcome)) ? 0 : 1;
    }
    // one unfinished spec at a time: a spec in awaiting_you that already has an outcome (the end of a queue) is finished
    const other = eng.db.prepare("SELECT id, state FROM specs WHERE id!=? AND state!='done' AND NOT (state='awaiting_you' AND outcome IS NOT NULL) ORDER BY position, created_at LIMIT 1").get(spec);
    if (other) { io.err(`engine: run: ${other.id} is unfinished (${other.state}): use engine resume\n`); return 1; }
    if (have) { io.err(`engine: run: ${spec} is already in the database (${have.state}): use engine resume\n`); return 1; }
    eng.addSpec({
      id: spec, plan: found.plan, worktree, branch: git(worktree, ["branch", "--show-current"]) || null,
      integration: p.flags.integration, push: p.flags.push ? 1 : 0, batch: p.flags.batch || null, backend: backendKind, ...budget,
    });
    if (!eng.db.prepare("SELECT 1 FROM specs WHERE id=?").get(spec)) { io.err(`engine: run: could not insert ${spec}\n`); return 1; }
    // the core runs `metrics start` itself, as the metrics_start step, when the spec starts
    return await runSpec(eng, spec, io);
  } finally {
    eng.stop();
  }
}

// ---- status, events --------------------------------------------------------------------------------------------

function cmdStatus(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length > 1) { io.err(`engine: status: ${p.error || "usage: engine status [<spec>] | status --waiting | status --unfinished"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (p.flags.unfinished) { // exit 0 and the spec ids when a queue is unfinished, else exit 1 and nothing
    if (!dbExists(project)) return 1;
    const u = db.open(project);
    let ids;
    try { ids = queue.unfinished(u); } finally { u.close(); }
    for (const id of ids) io.out(id);
    return ids.length ? 0 : 1;
  }
  if (!dbExists(project)) { io.out(p.flags.waiting ? "nothing is waiting" : "no specs"); return 0; }
  const d = db.open(project);
  try {
    if (p.flags.waiting) {
      const rows = d.prepare("SELECT w.*, s.state AS spec_state FROM waits w JOIN specs s ON s.id=w.spec WHERE w.answered_at IS NULL AND s.state='awaiting_you' ORDER BY w.asked_at").all();
      // a held answer closed its wait (R18): the spec is still parked, with nothing left to answer
      const held = d.prepare("SELECT s.id, (SELECT answer FROM waits w WHERE w.spec=s.id ORDER BY asked_at DESC, rowid DESC LIMIT 1) AS answer, " +
        "(SELECT note FROM waits w WHERE w.spec=s.id ORDER BY asked_at DESC, rowid DESC LIMIT 1) AS note FROM specs s " +
        "WHERE s.state='awaiting_you' AND NOT EXISTS (SELECT 1 FROM waits w WHERE w.spec=s.id AND w.answered_at IS NULL) ORDER BY s.position, s.created_at").all()
        .filter((h) => h.answer !== null);
      if (!rows.length && !held.length) { io.out("nothing is waiting"); return 0; }
      for (const h of held) {
        io.out(h.id);
        io.out(`  answer held: ${h.answer}${h.note ? ` (${h.note})` : ""}`);
      }
      for (const w of rows) {
        io.out(w.spec);
        let rec = null;
        try { rec = JSON.parse(w.recommendation); } catch (_) { rec = null; }
        if (rec) io.out(`  I recommend: ${rec.option} (${rec.confidence}): ${rec.why}`);
        io.out(`  question: ${w.question}`);
        io.out(`  options:  ${w.options}`);
        io.out(`  asked at: ${iso(w.asked_at)}`);
        io.out(`  answer:   tmux-ctl engine signal ${w.spec} ${w.options}`);
      }
      return 0;
    }
    if (p.pos.length === 0) {
      const specs = d.prepare("SELECT * FROM specs ORDER BY position, created_at").all();
      if (!specs.length) { io.out("no specs"); return 0; }
      for (const s of specs) io.out(`${s.id}  ${s.state}  ${s.outcome || "-"}  ${s.integration}${s.push ? "+push" : ""}`);
      return 0;
    }
    const s = d.prepare("SELECT * FROM specs WHERE id=?").get(p.pos[0]);
    if (!s) { io.err(`engine: status: no such spec ${p.pos[0]}\n`); return 1; }
    io.out(`${s.id}  ${s.state}  ${s.outcome || "-"}`);
    io.out(`  integration ${s.integration}${s.push ? " +push" : ""}  batch ${s.batch || "-"}  branch ${s.branch || "-"}  worktree ${s.worktree || "-"}`);
    const lower = d.prepare("SELECT 1 FROM jobs WHERE spec=? AND ended_at IS NOT NULL AND started_at IS NOT NULL AND tokens IS NULL LIMIT 1").get(s.id);
    io.out(`  attempts ${s.spent_attempts || 0}/${s.budget_attempts == null ? "-" : s.budget_attempts} · tokens ${s.spent_tokens || 0}/${s.budget_tokens == null ? "-" : s.budget_tokens}${lower ? " (lower bound)" : ""}`);
    io.out("jobs:");
    for (const j of d.prepare("SELECT * FROM jobs WHERE spec=? ORDER BY rowid").all(s.id)) {
      io.out(`  ${j.id}  ${j.state}  ${j.model}/${j.effort}  attempt ${j.attempt}${j.window ? "  " + j.window : ""}`);
    }
    io.out("last events:");
    const last = d.prepare("SELECT * FROM events WHERE spec=? ORDER BY seq DESC LIMIT 8").all(s.id).reverse();
    for (const e of last) io.out(`  ${eventLine(e)}`);
    return 0;
  } finally { d.close(); }
}

function cmdEvents(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length !== 1) { io.err(`engine: events: ${p.error || "usage: engine events <spec>"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (!dbExists(project)) { io.err(`engine: events: no events for ${p.pos[0]}\n`); return 1; }
  const d = db.open(project);
  try {
    const rows = d.prepare("SELECT * FROM events WHERE spec=? ORDER BY seq").all(p.pos[0]);
    if (!rows.length) { io.err(`engine: events: no events for ${p.pos[0]}\n`); return 1; }
    for (const e of rows) io.out(eventLine(e));
    return 0;
  } finally { d.close(); }
}

// ---- resume, signal, rebuild -----------------------------------------------------------------------------------

// The foreground loop of `engine start` and `engine resume`: resume (spec section 9), then tick until nothing is
// runnable. The lead lines are published after every tick. Resolves to queue.run's code.
async function runLoop(eng, project) {
  const stop = () => { eng.stop(); process.exit(130); };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    lead.begin(project, eng.db); // before resume and the first drain: nothing older than this start becomes a lead line
    await eng.resume();
    return await queue.run(eng, { project });
  } finally {
    process.removeListener("SIGINT", stop);
    process.removeListener("SIGTERM", stop);
  }
}

async function cmdResume(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length) { io.err(`engine: resume: ${p.error || "usage: engine resume [--project P] [--backend claude-tmux|fake]"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (!dbExists(project)) { io.out("nothing to resume"); return 0; }
  const peek = db.open(project);
  let open;
  let intents;
  try {
    open = peek.prepare("SELECT id, backend FROM specs WHERE state!='done' ORDER BY position, created_at").all();
    intents = peek.prepare("SELECT COUNT(*) AS n FROM steps WHERE state='intent'").get().n;
  } finally { peek.close(); }
  if (!open.length && !intents) { io.out("nothing to resume"); return 0; }
  const repo = mainRoot(git(io.cwd, ["rev-parse", "--show-toplevel"]) || io.cwd);
  const eng = startCore({ project, repo, out: io.out }, p.flags, p.flags.backend || (open[0] || {}).backend || "claude-tmux");
  try {
    if (!open.length) { // every spec is done, but a step (a close_window) was left at intent: reconcile it and stop
      await eng.resume();
      await eng.tick();
      io.out(`reconciled ${intents} step(s)`);
      return 0;
    }
    // the queue's loop: every runnable spec goes to its outcome; a parked spec nobody answered ends as `failed — awaiting you` with a metrics record, and `engine signal` plus `engine resume` resumes it
    let rc = await runLoop(eng, project);
    for (const s of open) {
      const cur = eng.db.prepare("SELECT state, outcome FROM specs WHERE id=?").get(s.id);
      if (cur.state === "done") {
        io.out(`outcome: ${cur.outcome}`);
        if (!OK_OUTCOME.test(String(cur.outcome))) rc = 1;
      } else {
        const w = inbox.openWaitFor(eng.db, s.id);
        io.out(cur.state === "awaiting_you" && w ? `awaiting you: ${s.id}: ${w.question}` : `${s.id}: ${cur.state}`);
      }
    }
    return rc;
  } finally {
    eng.stop();
  }
}

function cmdSignal(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length !== 2 || !ANSWERS.includes(p.pos[1])) {
    io.err(`engine: signal: ${p.error || "usage: engine signal <spec> approve|deny|fail [--note <text>]"}\n`);
    return 2;
  }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  const [spec, answer] = p.pos;
  if (!dbExists(project)) { io.err(`engine: signal: no open wait for ${spec}\n`); return 2; }
  const d = db.open(project);
  try {
    const r = inbox.signal(d, spec, answer, p.flags.note, Date.now() / 1000);
    if (r.rc !== 0) { io.err(`engine: signal: ${r.msg}\n`); return r.rc; }
  } finally { d.close(); }
  io.out(`signalled ${spec}: ${answer}`);
  if (!engineRunning(project)) io.out("no engine is running: tmux-ctl engine resume continues it");
  return 0;
}

// ---- the queue: enqueue, start, done (spec section 6) ----------------------------------------------------------

const START_RUNNING = 4; // `engine start` when an engine already runs for the project (R5): not a failure for the caller
const ENQUEUE_USAGE = "usage: engine enqueue <spec> --runner lead|engine --integration merge|mr|keep [--push] --batch <id> [--gate <id>] [--worktree <path>] [--budget-attempts N] [--budget-tokens N] [--project P]";

// Writes one inbox row and nothing else. A spec the engine cannot run is queued for the lead, never refused: a queue
// is enqueued unattended, and a refused spec would drop out of it.
function cmdEnqueue(args, io) {
  const p = parseArgs(args);
  const f = p.flags || {};
  if (p.error || p.pos.length !== 1 || !["lead", "engine"].includes(f.runner) || !["merge", "mr", "keep"].includes(f.integration) || !f.batch) {
    io.err(`engine: enqueue: ${p.error || ENQUEUE_USAGE}\n`);
    return 2;
  }
  const { budget, error } = budgetFlags(f);
  if (error) { io.err(`engine: enqueue: ${error}\n`); return 2; }
  const project = resolveProject(f, io);
  if (!project) return 2;
  const spec = p.pos[0];
  const worktree = git(f.worktree ? path.resolve(io.cwd, f.worktree) : io.cwd, ["rev-parse", "--show-toplevel"]);
  if (f.worktree && !worktree) { io.err(`engine: enqueue: --worktree ${f.worktree} is not a git checkout\n`); return 2; }
  let runner = f.runner;
  let why = null;
  let plan = null;
  if (runner === "engine") {
    if (f.gate) why = "a gated spec runs under the lead";
    else if (!worktree) why = "not inside a git checkout";
    else if (!fs.existsSync(path.resolve(worktree, spec.split("#")[0]))) why = `no such spec file: ${spec.split("#")[0]}`;
    else ({ why = null, plan = null } = planCheck(worktree, spec));
    if (why) runner = "lead";
  }
  const d = db.open(project);
  try {
    const have = d.prepare("SELECT state FROM specs WHERE id=?").get(spec);
    if (have) { io.err(`engine: enqueue: ${spec} is already in the database (${have.state})\n`); return 1; }
    queue.enqueue(d, spec, { runner, integration: f.integration, push: f.push ? 1 : 0, batch: f.batch, gate: f.gate || null, worktree: worktree || null,
      branch: (worktree && git(worktree, ["branch", "--show-current"])) || null, plan, ...budget, ...(why ? { reason: why } : {}) }, Date.now() / 1000);
  } finally { d.close(); }
  if (why) io.err(`engine: enqueue: ${why}: queued for the lead\n`);
  io.out(`queued ${spec} (${runner})`);
  return 0;
}

// --preflight: 0 when the lock is free and there is something to run (R12: the --unfinished predicate, or a new enqueue
// row); 4 when an engine already runs (R5: for the caller that is as good as started); 1 with nothing to do.
function preflight(project, io) {
  if (engineRunning(project)) { io.err(`engine: start: an engine is already running for ${project}\n`); return START_RUNNING; }
  let todo = false;
  if (dbExists(project)) {
    const d = db.open(project);
    try { todo = queue.pendingEnqueue(d) > 0 || queue.unfinished(d).length > 0; } finally { d.close(); }
  }
  if (!todo) { io.err("engine: start: nothing queued and no unfinished spec\n"); return 1; }
  return 0;
}

async function cmdStart(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length) { io.err(`engine: start: ${p.error || "usage: engine start [--preflight] [--here] [--project P] [--backend claude-tmux|fake] [--script F]"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (p.flags.preflight) return preflight(project, io);
  const running = () => { io.err(`engine: start: an engine is already running for ${project}\n`); return START_RUNNING; };
  if (engineRunning(project)) return running();
  const repo = mainRoot(git(io.cwd, ["rev-parse", "--show-toplevel"]) || io.cwd);
  let eng;
  try { eng = startCore({ project, repo, out: io.out }, p.flags, p.flags.backend || "claude-tmux"); } catch (e) {
    if (/^engine already running/.test(String(e && e.message))) return running(); // another start took the lock in between
    throw e;
  }
  try {
    const rc = await runLoop(eng, project);
    io.out(rc === 0 ? "queue finished" : "engine stopped: tmux-ctl engine start continues it");
    return rc;
  } finally {
    eng.stop();
  }
}

function cmdDone(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length !== 1 || !p.flags.outcome) { io.err(`engine: done: ${p.error || "usage: engine done <spec> --outcome <text>"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  const spec = p.pos[0];
  if (!dbExists(project)) { io.err(`engine: done: no lead turn open for ${spec}\n`); return 2; }
  const d = db.open(project);
  try {
    const r = queue.done(d, spec, p.flags.outcome, Date.now() / 1000);
    if (r.rc !== 0) { io.err(`engine: done: ${r.msg}\n`); return r.rc; }
  } finally { d.close(); }
  io.out(`done ${spec}: ${p.flags.outcome}`);
  if (!engineRunning(project)) io.out("no engine is running: tmux-ctl engine start continues the queue");
  return 0;
}

const SCHEDULE_USAGE = "usage: engine schedule add <name> --rule \"<rule>\" [--skip-if-weekly-usage <0-100|none>] -- <command...> | list | rm <name> | run-now <name> | migrate [--dry-run]";
const lt = (n) => String(n).padStart(2, "0");
// Local time as YYYY-MM-DD HH:MM.
function localTime(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${lt(d.getMonth() + 1)}-${lt(d.getDate())} ${lt(d.getHours())}:${lt(d.getMinutes())}`;
}

// The words after the first `--` are the command, never flags.
async function cmdSchedule(args, io) {
  const cut = args.indexOf("--");
  const head = cut < 0 ? args : args.slice(0, cut);
  const words = cut < 0 ? [] : args.slice(cut + 1);
  const p = parseArgs(head);
  const usage = (why) => { io.err(`engine: schedule: ${why || SCHEDULE_USAGE}\n`); return 2; };
  if (p.error) return usage(`${p.error}\n${SCHEDULE_USAGE}`);
  const [verb, name, ...extra] = p.pos;
  if (!["add", "list", "rm", "run-now", "migrate"].includes(verb) || extra.length) return usage();
  if (verb === "migrate") {
    if (name || words.length) return usage();
    const dry = !!p.flags["dry-run"];
    const project = dry ? (p.flags.project || process.env.TC_PROJECT || null) : resolveProject(p.flags, io);
    if (!dry && !project) return 2;
    return await require("./launchd").migrate({ dryRun: dry, project, io });
  }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (verb === "add") {
    const f = p.flags;
    if (!name || !f.rule || !words.length || !words.join("").length) return usage();
    let skip = 85;
    if (f["skip-if-weekly-usage"] !== undefined) {
      const v = f["skip-if-weekly-usage"];
      if (v === "none") skip = null;
      else if (/^\d+$/.test(v) && Number(v) <= 100) skip = Number(v);
      else return usage();
    }
    const command = words.length === 1 ? words[0] : schedule.shellJoin(words);
    const cwd = git(io.cwd, ["rev-parse", "--show-toplevel"]) || io.cwd;
    const d = db.open(project);
    try {
      const now = Date.now() / 1000;
      let r;
      try { r = schedule.add(d, { name, rule: f.rule, command, skip_if_weekly_usage: skip, cwd }, now); } catch (e) {
        if (e.code === "bad_input") return usage(`${e.message}\n${SCHEDULE_USAGE}`);
        io.err(`engine: schedule: ${e.message}\n`);
        return 1;
      }
      if (r.status === "unchanged") io.out(`unchanged ${name}`);
      else io.out(`added ${name}: ${f.rule.trim()}, next ${localTime(r.due_at)}`);
      return 0;
    } finally { d.close(); }
  }
  if (words.length) return usage();
  if (verb === "list" && name) return usage();
  if ((verb === "rm" || verb === "run-now") && !name) return usage();
  if (verb === "run-now") return await runNow(project, name, io);
  if (!dbExists(project)) {
    if (verb === "list") { io.out("no schedules"); return 0; }
    io.err(`engine: schedule: no schedule ${name}\n`);
    return 1;
  }
  const d = db.open(project);
  try {
    if (verb === "list") {
      const rows = schedule.list(d);
      if (!rows.length) io.out("no schedules");
      for (const r of rows) io.out(`${r.name}  ${r.rule}  next ${localTime(r.due_at)}  ${r.command}`);
      return 0;
    }
    try { schedule.rm(d, name, Date.now() / 1000); } catch (e) { io.err(`engine: schedule: ${e.message}\n`); return 1; }
    io.out(`removed ${name}`);
    return 0;
  } finally { d.close(); }
}

// Inserts the run-now row (spec 14). With no engine running the short pass of `engine wake` for this project runs it now
// and waits like a wake; with one running, its next tick drains the row.
async function runNow(project, name, io) {
  if (!dbExists(project)) { io.err(`engine: schedule: no schedule ${name}\n`); return 1; }
  const d = db.open(project);
  try {
    const cur = d.prepare("SELECT * FROM timers WHERE id=? AND kind='schedule'").get(`schedule:${name}`);
    if (!cur || cur.fired_at !== null) { io.err(`engine: schedule: no schedule ${name}\n`); return 1; }
    const t = Date.now() / 1000;
    const payload = { ...JSON.parse(cur.payload), force: true };
    inbox.insert(d, { source: "schedule", source_id: `${name}@now:${Math.floor(t)}`, kind: "run", payload }, t);
  } finally { d.close(); }
  if (engineRunning(project)) { io.out(`queued for the running engine: ${name}`); return 0; }
  return await require("./wake").run({ io, project });
}

async function cmdWake(args, io) {
  if (!args.length) return await require("./wake").run({ io });
  const sub = args[0];
  if (args.length > 1 || !["install", "status", "uninstall"].includes(sub)) { io.err("engine: wake: usage: engine wake [install|status|uninstall]\n"); return 2; }
  return require("./launchd")[sub](io);
}

function cmdRebuild(args, io) {
  const p = parseArgs(args);
  if (p.error || p.pos.length || !!p.flags.check === !!p.flags.apply) {
    io.err(`engine: rebuild: ${p.error || "usage: engine rebuild --check|--apply"}\n`);
    return 2;
  }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (!dbExists(project)) { io.err("engine: rebuild: no database for this project\n"); return 2; }
  if (p.flags.check) {
    const r = rebuild.check(project);
    for (const line of r.diffs) io.out(line);
    io.out(r.rc === 0 ? "replay matches the live tables" : `${r.diffs.length} difference(s) between the replay and the live tables`);
    return r.rc;
  }
  const r = rebuild.apply(project);
  if (r.rc !== 0) { io.err(`engine: rebuild: ${r.msg}\n`); return r.rc; }
  io.out(`tables rebuilt from the events; backup ${r.backup}`);
  return 0;
}

// ---- entry -----------------------------------------------------------------------------------------------------

async function main(argv, io0) {
  const io = {
    out: (s) => process.stdout.write(s + "\n"),
    err: (s) => process.stderr.write(s),
    cwd: process.cwd(),
    ...(io0 || {}),
  };
  const sub = argv[0];
  if (!SUBS.includes(sub)) { io.err(USAGE); return 2; }
  const rest = argv.slice(1);
  try {
    switch (sub) {
      case "run": return await cmdRun(rest, io);
      case "status": return cmdStatus(rest, io);
      case "events": return cmdEvents(rest, io);
      case "resume": return await cmdResume(rest, io);
      case "signal": return cmdSignal(rest, io);
      case "enqueue": return cmdEnqueue(rest, io);
      case "start": return await cmdStart(rest, io);
      case "done": return cmdDone(rest, io);
      case "schedule": return await cmdSchedule(rest, io);
      case "wake": return await cmdWake(rest, io);
      default: return cmdRebuild(rest, io);
    }
  } catch (e) {
    io.err(`engine: ${sub}: ${String(e && e.message ? e.message : e).split("\n")[0]}\n`);
    return e && e.usage ? 2 : 1;
  }
}

module.exports = { main, eventLine, QUIET, USAGE };
