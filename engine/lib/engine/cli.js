"use strict";
// The engine's command line (spec section 5): run, status, events, resume, signal, rebuild.
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

const SUBS = ["run", "status", "events", "resume", "signal", "rebuild"];
const USAGE = `engine: usage: engine <${SUBS.join("|")}> ...\n`;
const ANSWERS = ["approve", "deny", "fail"];
const OK_OUTCOME = /^(merged|mr|kept)/;
// Bookkeeping events the foreground printer hides: three deadline re-arms per job every two minutes, timer and inbox
// plumbing, session id updates and the step journal's intent/done pair. `engine events` prints everything.
const QUIET = /^(deadline|timer_fired|inbox_.*|job_session|step_intent|step_done)$/;
const TICK_MS_FAKE = 100;

const VALUE_FLAGS = new Set(["--integration", "--batch", "--project", "--backend", "--note", "--script"]);
const BOOL_FLAGS = new Set(["--push", "--waiting", "--check", "--apply"]);

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

function makeBackend(kind, flags, session, tmuxCtl) {
  if (kind === "fake") {
    let script = {};
    if (flags.script) script = JSON.parse(fs.readFileSync(flags.script, "utf8"));
    return { backend: require("./backend/fake").createBackend({ script }), tickMs: TICK_MS_FAKE };
  }
  if (kind === "claude-tmux") {
    if (!session) throw Object.assign(new Error("run it from a tmux session (TC_SESSION is not set)"), { usage: true });
    const tmuxArgs = (process.env.TMUX_DASH_TMUX_ARGS || "").split(/\s+/).filter(Boolean);
    const backend = require("./backend/claude_tmux").createBackend({ session, tmuxCtl, statusDir: paths.statusDir(), tmuxArgs });
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

function startCore(ctx, flags, backendKind) {
  const core = require("./core");
  const tmuxCtl = tmuxCtlPath();
  const session = process.env.TC_SESSION || "";
  const { backend, tickMs, tmuxArgs } = makeBackend(backendKind, flags, session, tmuxCtl);
  const eng = core.start({
    project: ctx.project, repo: ctx.repo, backend, tmuxCtl, session, tmuxArgs, tickMs,
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
    io.err(`engine: run: ${p.error || "usage: engine run <spec> --integration merge|mr|keep [--push] [--batch <id>] [--project P] [--backend claude-tmux|fake]"}\n`);
    return 2;
  }
  const spec = p.pos[0];
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  const backendKind = p.flags.backend || "claude-tmux";

  const worktree = git(io.cwd, ["rev-parse", "--show-toplevel"]);
  if (!worktree) { io.err("engine: run: not inside a git checkout\n"); return 2; }
  const specFile = spec.split("#")[0];
  if (!fs.existsSync(path.resolve(worktree, specFile))) { io.err(`engine: run: no such spec file: ${specFile}\n`); return 2; }

  const found = findPlan(worktree, spec);
  if (!found) return yourTurn(io, spec, `no plan names ${spec} on its **Spec:** line`);
  if (found.ref) return yourTurn(io, spec, `its plan is on branch ${found.ref}, not in this checkout: run from that worktree`);
  const tasksFile = path.resolve(worktree, `${found.path}.tasks.json`);
  const c = compile(fs.existsSync(tasksFile) ? fs.readFileSync(tasksFile, "utf8") : null);
  if (c.error) return yourTurn(io, spec, `${found.path}: ${c.error}`);

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
      id: spec, plan: found.path, worktree, branch: git(worktree, ["branch", "--show-current"]) || null,
      integration: p.flags.integration, push: p.flags.push ? 1 : 0, batch: p.flags.batch || null, backend: backendKind,
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
  if (p.error || p.pos.length > 1) { io.err(`engine: status: ${p.error || "usage: engine status [<spec>] | status --waiting"}\n`); return 2; }
  const project = resolveProject(p.flags, io);
  if (!project) return 2;
  if (!dbExists(project)) { io.out(p.flags.waiting ? "nothing is waiting" : "no specs"); return 0; }
  const d = db.open(project);
  try {
    if (p.flags.waiting) {
      const rows = d.prepare("SELECT w.*, s.state AS spec_state FROM waits w JOIN specs s ON s.id=w.spec WHERE w.answered_at IS NULL AND s.state='awaiting_you' ORDER BY w.asked_at").all();
      if (!rows.length) { io.out("nothing is waiting"); return 0; }
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
    await eng.resume(); // spec section 9: intent steps, due timers, inbox, policy, then running jobs (the ticks that follow)
    let rc = 0;
    for (const s of open) if ((await runSpec(eng, s.id, io)) !== 0) rc = 1;
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
      default: return cmdRebuild(rest, io);
    }
  } catch (e) {
    io.err(`engine: ${sub}: ${String(e && e.message ? e.message : e).split("\n")[0]}\n`);
    return e && e.usage ? 2 : 1;
  }
}

module.exports = { main, eventLine, QUIET, USAGE };
