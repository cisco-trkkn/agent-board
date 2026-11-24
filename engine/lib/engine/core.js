"use strict";
// The engine core (spec sections 2, 4, 9, 10 and Error handling): one tick moves due timers and worker status
// changes into the inbox, drains it, advances each spec and dispatches the next job.
//
// How it stays restartable:
// - Every strategy input (spec_started, stale_result, job_done, job_failed, check_result, architect_decision,
//   integrated, signal) is one `events` row with its fields in `detail`. The commands that answer it are applied one
//   transaction each, and each of their events carries `cause` (the input's seq) and `idx`. The strategy is pure, so
//   after a crash `pump` recomputes the commands of the last input and applies the ones without an event.
// - Work outside the database that a command asks for is a row first: a `pending` job, or a `steps` row at `intent`
//   of kind `check`, `stale_check` or `integrate`. The tick acts on those rows, so nothing lives only in memory.
// - A worker's latest status (heartbeat, tool, turn times) is memory only: it is re-read from the backend.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const { open, tx, put, event } = require("./db");
const paths = require("./paths");
const policy = require("./policy");
const { compile } = require("./compile");
const report = require("./report");
const bounce = require("./bounce");
const inbox = require("./inbox");
const steps = require("./steps");
const feed = require("./feed");
const realIntegrate = require("./integrate");
const architect = require("./architect");
const specDriven = require("./strategy/spec_driven");

const TICK_S = 5;
const HEARTBEAT_S = 120; // no status for this long fails the attempt
const NO_PROGRESS_S = 900; // busy with no tool for this long: one nudge
const NUDGE_GRACE_S = 300; // still no progress this long after the nudge: the attempt fails
const TOOL_LIMIT_S = { Bash: 900 }; // a tool's own limit plus 5 minutes
const TOOL_LIMIT_DEFAULT_S = 900;
const NEEDS_YOU_PARK_S = 600;
const REPORT_GRACE_S = 300; // told the report path and still idle without one
const USAGE_FALLBACK_S = 3600;
const CHECK_TIMEOUT_MS = 30 * 60 * 1000;

const INPUTS = ["spec_started", "stale_result", "job_done", "job_failed", "check_result", "architect_decision", "integrated", "signal"];
const PK = { specs: "id", jobs: "id", steps: "key", timers: "id", waits: "id", retry_policies: "kind", inbox: "id" };
const MY_STEPS = ["check", "stale_check", "integrate"];
const NEVER_PARK = ["metrics_start", "metrics_record", "metrics_ask", "artifact", "awake_off", "registry_report", "commit_report"]; // measurement and notices
const WORKER_KINDS = ["refresh", "implement", "fix", "fix_wave"];
const RETRY_ALIAS = { fix_wave: "fix", re_review: "final_review" };
const BLOCKING = ["critical", "important"];
const DEFAULT_MODELS = { mechanical: "haiku", standard: "sonnet", frontier: "fable" };
const DEFAULT_EFFORT = { mechanical: "low", standard: "medium", frontier: "high" };
const STATUS_SHAPES = {
  worker: '{"status": "done" | "blocked", "commits": ["<sha>"], "concerns": ["<text>"]}',
  reviewer: '{"verdict": "pass" | "findings", "findings": [{"severity": "critical" | "important" | "minor", "task": <n>, "text": "<text>"}]}',
};
const STOP = Symbol("stop drain");

const parse = (s) => {
  if (s === null || s === undefined) return null;
  if (typeof s === "object") return s;
  try { return JSON.parse(s); } catch (_) { return null; }
};
const fileName = (id) => String(id).replace(/[:/]/g, "_");
const short = (sha) => (sha ? String(sha).slice(0, 12) : "-");
const readOr = (p, or = "") => { try { return fs.readFileSync(p, "utf8"); } catch (_) { return or; } };

// ---- the lock (spec section 9) -------------------------------------------------------------------------------

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}

function takeLock(project) {
  const file = paths.lockPath(project);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const pid = parseInt(readOr(file).split("\n")[0], 10);
  if (Number.isInteger(pid) && pid > 0 && alive(pid)) throw new Error(`engine already running (pid ${pid})`);
  fs.writeFileSync(file, `${process.pid}\n`);
  return file;
}

// ---- readers of the platform (each has one unpatched test) ------------------------------------------------------

// E3: the job's final context size, from its session's transcript, or null with the reason.
function contextTokens(job, root) {
  if (!job.session_id) return { context_tokens: null, context_missing: "no session id" };
  const base = root || path.join(process.env.CLAUDE_CONFIG_DIR || path.join(process.env.HOME || "", ".claude"), "projects");
  let file = null;
  try {
    for (const d of fs.readdirSync(base)) {
      const p = path.join(base, d, `${job.session_id}.jsonl`);
      if (fs.existsSync(p)) { file = p; break; }
    }
  } catch (_) { /* no projects directory */ }
  if (!file) return { context_tokens: null, context_missing: `no transcript for session ${job.session_id}` };
  const script = path.resolve(__dirname, "../../../board/ctxsize.py");
  const r = cp.spawnSync("python3", ["-I", script, "last", file], { encoding: "utf8", timeout: 20000 });
  const n = parseInt((r.stdout || "").trim(), 10);
  if (r.error || !Number.isInteger(n)) return { context_tokens: null, context_missing: "no context size in the transcript" };
  return { context_tokens: n };
}

const git = (dir, args) => cp.spawnSync("git", ["-C", dir, ...args], { encoding: "utf8", timeout: 60000 });
function gitHead(dir) {
  const r = git(dir, ["rev-parse", "HEAD"]);
  return r.error || r.status !== 0 ? null : r.stdout.trim();
}

// What a fix round changed, base..HEAD, in the units of the strategy's SMALL_FIX; null when it cannot be measured.
function fixStats(dir, base) {
  if (!base) return null;
  const num = git(dir, ["diff", "--numstat", `${base}..HEAD`]);
  const added = git(dir, ["diff", "--diff-filter=A", "--name-only", `${base}..HEAD`]);
  const body = git(dir, ["diff", "-U0", `${base}..HEAD`]);
  if ([num, added, body].some((r) => r.error || r.status !== 0)) return null;
  const rows = num.stdout.split("\n").filter(Boolean).map((l) => l.split("\t"));
  const lines = rows.reduce((n, [a, d]) => n + (parseInt(a, 10) || 0) + (parseInt(d, 10) || 0), 0);
  const removed = body.stdout.split("\n").filter((l) => /^-\s*(test|it|describe)\s*\(|^-\s*def test_|^-\s*@test\b/.test(l)).length;
  return { lines, files: rows.length, added: added.stdout.split("\n").filter(Boolean).length, tests_removed: removed };
}

// The newest status-line tap file's reset time for a window at 100%, or null.
function tapReset(t) {
  const dir = path.join(paths.stateDir(), "statusline");
  let newest = null;
  let names = [];
  try { names = fs.readdirSync(dir).filter((f) => f.endsWith(".json")); } catch (_) { return null; }
  for (const f of names) {
    const o = parse(readOr(path.join(dir, f), "null"));
    if (o && typeof o === "object" && o.rate_limits && (!newest || (o.received_at || 0) > (newest.received_at || 0))) newest = o;
  }
  if (!newest) return null;
  const full = Object.values(newest.rate_limits).filter((w) => w && w.used_percentage >= 100 && w.resets_at > t);
  return full.length ? Math.max(...full.map((w) => w.resets_at)) : null;
}

// ---- the engine ------------------------------------------------------------------------------------------------

function start(opts) {
  const { project, repo, backend } = opts;
  if (!project || !repo) throw new Error("core.start needs project and repo");
  const lockFile = takeLock(project);
  let db;
  try { db = open(project); } catch (e) { fs.rmSync(lockFile, { force: true }); throw e; }

  const now = opts.now || (() => Date.now() / 1000);
  const strategy = opts.strategy || specDriven;
  const config = opts.config || policy.loadConfig(repo);
  const hash = policy.policyHash(config);
  const tmuxCtl = opts.tmuxCtl || process.env.TC_TMUX_CTL || path.join(repo, "bin/tmux-ctl");
  const env = { ...process.env, ...(opts.env || {}) };
  const routing = parse(readOr(path.join(repo, "docs/superpowers/model-routing.json"), "null")) || {};
  const tell = opts.tell || ((handle, text) => { cp.spawnSync(tmuxCtl, ["tell", handle.window, text], { env, encoding: "utf8" }); });
  const notify = opts.notify || ((text) => process.stderr.write(`${text}\n`));
  const sleep = opts.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  // a worktree that is gone (a merged spec's, removed by its finalize) is read from the main checkout, where its work now is
  const wtOf = (spec) => (spec.worktree && fs.existsSync(spec.worktree) ? spec.worktree : repo);
  const ictx = (spec) => ({ db, repo, worktree: wtOf(spec), tmuxCtl, tasks: plan(spec).tasks, env: opts.env, now });
  const integrateFn = opts.integrate || ((spec) => realIntegrate.run(ictx(spec), spec));
  const revertFn = opts.revert || ((spec) => realIntegrate.revert(ictx(spec), spec));
  const finalizeFn = opts.finalize || ((spec, outcome) => realIntegrate.finalize(ictx(spec), spec, outcome));

  const status = new Map(); // job id -> the latest status event (memory only)
  const lastState = new Map(); // job id -> the state of the last worker row offered
  const pumped = new Map(); // spec id -> seq of the last input whose commands are all applied
  const plans = new Map();
  const closed = new Set();
  const effects = []; // actions to run after the drain's transaction commits (a tell)
  let inTx = false;
  let produced = false; // an input event was written since the last pump
  let halted = null;
  let stopped = false;
  let publishedSeq = (db.prepare("SELECT MAX(seq) AS s FROM events").get().s) || 0;

  // ---- rows and events ----

  const get = (table, id) => db.prepare(`SELECT * FROM ${table} WHERE ${PK[table]}=?`).get(id) || null;
  const all = (sql, ...a) => db.prepare(sql).all(...a);
  const W = (fn) => (inTx ? fn() : tx(db, fn));
  // One state change: the rows and their one event, in one transaction (the drain's own when inside it).
  function emit(kind, { spec = null, job = null, rows = [], ...extra } = {}) {
    W(() => {
      const full = rows.map(([table, row]) => { put(db, table, row); return { table, row: get(table, row[PK[table]]) }; });
      event(db, { spec, job, kind, rows: full, ts: now(), ...extra });
    });
    if (INPUTS.includes(kind)) produced = true;
  }
  const detailOf = (job) => parse(job.detail) || {};
  const withDetail = (job, d) => ({ ...job, detail: JSON.stringify(d) });
  const handleOf = (job) => ({ job: job.id, window: job.window, pane: job.pane, session_id: job.session_id || undefined });
  const lastEvent = (spec, kind) => {
    const e = db.prepare("SELECT * FROM events WHERE spec=? AND kind=? ORDER BY seq DESC LIMIT 1").get(spec, kind);
    return e ? { ...e, detail: parse(e.detail) || {} } : null;
  };

  function flush() {
    for (const e of all("SELECT * FROM events WHERE seq>? ORDER BY seq", publishedSeq)) {
      publishedSeq = e.seq;
      feed.publish(project, e);
      if (opts.onEvent) { try { opts.onEvent(e); } catch (_) { /* a printer never stops the engine */ } }
    }
  }

  // ---- the plan ----

  function plan(spec) {
    if (plans.has(spec.id)) return plans.get(spec.id);
    const file = path.resolve(wtOf(spec), `${spec.plan}.tasks.json`);
    const text = readOr(file, null);
    const c = compile(text);
    if (c.error) throw new Error(`${spec.id}: ${c.error}`);
    const doc = JSON.parse(text);
    const raw = Array.isArray(doc) ? doc : doc.tasks;
    const tasks = c.tasks.map((t, i) => ({ ...t, description: String((raw[i] || {}).description || ""),
      gate: /"userGate"\s*:\s*true/.test(String((raw[i] || {}).description || "")) }));
    const p = { tasks, byN: new Map(tasks.map((t) => [t.n, t])) };
    plans.set(spec.id, p);
    return p;
  }
  const retryRow = (kind) => policy.retryFor(config, policy.DEFAULT_RETRY[kind] || (config.retry || {})[kind] ? kind : RETRY_ALIAS[kind] || kind);
  const retryTable = () => {
    const out = {};
    for (const k of new Set([...Object.keys(policy.DEFAULT_RETRY), ...Object.keys(config.retry || {})])) out[k] = policy.retryFor(config, k);
    return out;
  };
  const slugOf = (spec) => paths.specSlug(spec.id);
  const label = (job) => `${job.kind}${job.task === null || job.task === undefined ? "" : job.task}`;

  // ---- parking (spec 10.3) ----

  function park(spec, question, step, extra = {}) {
    if (inbox.openWaitFor(db, spec.id)) return false;
    const t = now();
    const n = db.prepare("SELECT COUNT(*) AS n FROM waits WHERE spec=?").get(spec.id).n;
    const wait = { id: `${spec.id}@${t}#${n + 1}`, spec: spec.id, step, question, options: extra.options || "approve|deny|fail",
      asked_at: t, answered_at: null, answer: null, note: null,
      kind: "cannot_tell", recommendation: JSON.stringify(policy.ASK_DEFAULTS.cannot_tell) }; // Task 4 passes the real kind
    delete extra.options;
    const command = `tmux-ctl engine signal ${spec.id} approve|deny|fail`;
    emit("awaiting_you", { spec: spec.id, rows: [["waits", wait], ["specs", { ...spec, state: "awaiting_you", updated_at: t }]],
      question, step, prev_state: spec.state, command, text: `${question} — answer with: ${command}`, ...extra });
    return true;
  }

  // ---- jobs ----

  function newJob(spec, c, detail) {
    const task = c.task === undefined ? null : c.task;
    const n = db.prepare("SELECT COUNT(*) AS n FROM jobs WHERE spec=? AND kind=? AND task IS ?").get(spec.id, c.kind, task).n;
    const tier = c.tier || "standard";
    return {
      id: `${slugOf(spec)}:${c.kind}${task === null ? "" : task}:${n + 1}`, spec: spec.id, kind: c.kind, task, tier,
      model: c.model || routing[tier] || DEFAULT_MODELS[tier] || "sonnet",
      effort: (routing.effort && routing.effort[tier] !== "inherit" && routing.effort[tier]) || DEFAULT_EFFORT[tier] || "medium",
      state: c.state || "pending", attempt: n + 1, brief: null, report: null, window: null, pane: null, session_id: null,
      base: null, head: null, tools: "all", mcp: "all", started_at: null, ended_at: null, needs_you_since: null,
      needs_you_total: 0, detail: JSON.stringify(detail),
    };
  }
  const cancelTimers = (jobId) => all("SELECT * FROM timers WHERE job=? AND fired_at IS NULL", jobId).map((r) => ["timers", { ...r, fired_at: now() }]);

  // Arms the job's one deadline timer at `due`; returns the rows to write (the job row carries the timer's id).
  function deadlineRows(job, d, due) {
    const n = (d.dl || 0) + 1;
    const id = `dl:${job.id}:${n}`;
    const nd = { ...d, dl: n, deadline: id };
    return { rows: [...cancelTimers(job.id), ["timers", { id, spec: job.spec, job: job.id, kind: "deadline", due_at: due, payload: null, fired_at: null }],
      ["jobs", withDetail(job, nd)]], detail: nd };
  }

  // The next time one of the job's clocks can run out (spec 10.1), given its latest status.
  function nextDue(job, d, t) {
    const st = status.get(job.id);
    const ref0 = Math.max(job.started_at || 0, d.resumed_at || 0);
    const idle = !!st && st.state === "ready"; // an idle worker refreshes nothing: the report grace governs it, not the heartbeat
    const cands = idle ? [] : [Math.max(st ? st.updatedAt || 0 : 0, ref0) + HEARTBEAT_S];
    const pol = retryRow(job.kind);
    if (pol.timeout_min) cands.push(job.started_at + (job.needs_you_total || 0) + pol.timeout_min * 60);
    if (st && st.tool) cands.push(Math.max(st.lastToolAt || 0, ref0) + (TOOL_LIMIT_S[st.tool] || TOOL_LIMIT_DEFAULT_S));
    if (st && st.state === "busy" && !st.tool) cands.push(Math.max(st.lastToolAt || 0, st.turnStartedAt || 0, ref0) + NO_PROGRESS_S);
    if (d.nudged_at) cands.push(d.nudged_at + NUDGE_GRACE_S);
    if (d.told_at) cands.push(d.told_at + REPORT_GRACE_S);
    const future = cands.filter((c) => c > t);
    return future.length ? Math.min(...future) : t + TICK_S;
  }

  // A deadline fired: fail the attempt with the clock that ran out, nudge, park, or arm the next deadline.
  function evaluate(job, t) {
    const d = detailOf(job);
    if (job.needs_you_since !== null) { // every clock is stopped (spec section 2)
      if (d.parked) return;
      if (t - job.needs_you_since < NEEDS_YOU_PARK_S) {
        emit("deadline", { spec: job.spec, job: job.id, rows: deadlineRows(job, d, job.needs_you_since + NEEDS_YOU_PARK_S).rows });
        return;
      }
      // one open wait per spec: when another question is open, ask again in a minute
      if (park(get("specs", job.spec), `permission prompt in ${job.window}`, `core:needs_you:${job.id}`)) {
        emit("needs_you_parked", { spec: job.spec, job: job.id, rows: [["jobs", withDetail(job, { ...d, parked: true })]] });
      } else {
        emit("deadline", { spec: job.spec, job: job.id, rows: deadlineRows(job, d, t + 60).rows });
      }
      return;
    }
    const st = status.get(job.id);
    const ref0 = Math.max(job.started_at || 0, d.resumed_at || 0);
    const pol = retryRow(job.kind);
    const idle = !!st && st.state === "ready";
    if (!idle && t - Math.max(st ? st.updatedAt || 0 : 0, ref0) >= HEARTBEAT_S) return failAttempt(job, "heartbeat_timeout");
    if (pol.timeout_min && t - job.started_at - (job.needs_you_total || 0) >= pol.timeout_min * 60) return failAttempt(job, "job_timeout");
    if (st && st.tool && t - Math.max(st.lastToolAt || 0, ref0) >= (TOOL_LIMIT_S[st.tool] || TOOL_LIMIT_DEFAULT_S)) return failAttempt(job, "tool_timeout");
    if (d.told_at && st && st.state === "ready" && t - d.told_at >= REPORT_GRACE_S) return failAttempt(job, "no_report");
    const stuck = st && st.state === "busy" && !st.tool &&
      t - Math.max(st.lastToolAt || 0, st.turnStartedAt || 0, ref0) >= NO_PROGRESS_S;
    let nd = d;
    if (stuck && d.nudged_at && t - d.nudged_at >= NUDGE_GRACE_S) return failAttempt(job, "no_progress");
    if (stuck && !d.nudged_at) {
      nd = { ...d, nudged_at: t };
      const handle = handleOf(job);
      effects.push(() => tell(handle, `No progress for 15 minutes. Finish the job and write your report to ${job.report}`));
    } else if (!stuck && d.nudged_at) {
      nd = { ...d, nudged_at: null };
    }
    const r = deadlineRows(job, nd, nextDue(job, nd, t));
    emit(nd.nudged_at && !d.nudged_at ? "nudged" : "deadline", { spec: job.spec, job: job.id, rows: r.rows });
  }

  // A job that ends while it sat at a permission prompt: its needs-you clock stops, and a park that asked about its
  // window is closed with the spec back in the state it was parked from (as `needs_you_end` does). Returns the job
  // fields to merge and the rows to write with the job's end.
  function endNeedsYou(job, t) {
    if (job.needs_you_since === null) return { fields: {}, rows: [] };
    const fields = { needs_you_since: null, needs_you_total: (job.needs_you_total || 0) + (t - job.needs_you_since) };
    const rows = [];
    const wait = inbox.openWaitFor(db, job.spec);
    if (wait && wait.step === `core:needs_you:${job.id}`) {
      const spec = get("specs", job.spec);
      const prev = (lastEvent(spec.id, "awaiting_you") || { detail: {} }).detail.prev_state || "running";
      rows.push(["waits", { ...wait, answered_at: t, answer: "job_ended", note: null }]);
      if (spec.state === "awaiting_you") rows.push(["specs", { ...spec, state: prev, updated_at: t }]);
    }
    return { fields, rows };
  }

  // A failed attempt (spec 10.2): the job ends, and its retry policy decides what follows. The retry row is written
  // with the failure, so a crash cannot lose it.
  function failAttempt(job, reason0) {
    const t = now();
    const d = detailOf(job);
    const pol = retryRow(job.kind);
    const reason = reason0 === "model_limit" && d.model_fallback ? "model_limit_after_fallback" : reason0;
    const tryN = d.try || 1;
    const spec = get("specs", job.spec);
    const ny = endNeedsYou(job, t);
    const rows = [...cancelTimers(job.id), ["jobs", { ...job, ...ny.fields, state: "failed", ended_at: t, head: gitHead(wtOf(spec)) }], ...ny.rows];
    const proto = { kind: job.kind, task: job.task === null ? undefined : job.task, tier: job.tier, model: job.model };
    const carry = { ...d, deadline: undefined, dl: undefined, nudged_at: undefined, told_at: undefined, parked: undefined, resumed_at: undefined };
    let next = null;
    let exhausted = false;
    const after = [];
    if (reason === "model_limit") { // rerun once on Opus, outside the count
      next = newJob(spec, { ...proto, model: "opus" }, { ...carry, model_fallback: true });
      after.push(() => emit("model_fallback", { spec: spec.id, job: next.id, from: job.model, to: "opus", text: `${job.id} hit the model limit: rerun on opus` }));
    } else if (reason === "usage_limit") { // no retry count; dispatch waits for the reset
      next = newJob(spec, { ...proto, state: "backoff" }, { ...carry, wait_usage: true });
      const until = pauseForUsage(spec.id, rows);
      after.push(() => emit("usage_limit", { spec: spec.id, job: job.id, until, text: `usage limit until ${new Date(until * 1000).toISOString()}` }));
    } else if ((pol.no_retry_on || []).includes(reason) || tryN >= pol.max_attempts) {
      exhausted = true;
    } else {
      next = newJob(spec, { ...proto, state: "backoff" }, { ...carry, try: tryN + 1 });
      const list = Array.isArray(pol.backoff_s) ? pol.backoff_s : [pol.backoff_s || 0];
      const wait = Number(list[Math.min(tryN - 1, list.length - 1)]) || 0;
      rows.push(["timers", { id: `retry:${next.id}`, spec: spec.id, job: next.id, kind: "retry", due_at: t + wait, payload: null, fired_at: null }]);
    }
    if (next) rows.push(["jobs", next]);
    emit("job_failed", { spec: spec.id, job: job.id, rows, task: job.task === null ? undefined : job.task, reason, try: tryN,
      exhausted, on_exhausted: pol.on_exhausted, retry: next ? next.id : null, text: `${label(job)} failed: ${reason}`, ...contextTokens(job, opts.transcriptRoot) });
    for (const f of after) f();
    status.delete(job.id);
  }

  // Sets the usage_reset timer unless one is pending; returns its due time. `rows` receives the timer row.
  function pauseForUsage(specId, rows) {
    const t = now();
    const have = db.prepare("SELECT * FROM timers WHERE kind='usage_reset' AND fired_at IS NULL ORDER BY due_at LIMIT 1").get();
    if (have) return have.due_at;
    const until = tapReset(t) || t + USAGE_FALLBACK_S;
    rows.push(["timers", { id: `usage:${t}`, spec: specId, job: null, kind: "usage_reset", due_at: until, payload: null, fired_at: null }]);
    effects.push(() => notify(`[Engine] paused: usage limit until ${new Date(until * 1000).toISOString()}`));
    return until;
  }
  const usagePaused = () => !!db.prepare("SELECT 1 FROM timers WHERE kind='usage_reset' AND fired_at IS NULL LIMIT 1").get();

  // A job ended with a valid report.
  function finishJob(job, st) {
    const t = now();
    const spec = get("specs", job.spec);
    const d = detailOf(job);
    const wt = wtOf(spec);
    if (WORKER_KINDS.includes(job.kind) && st.status === "blocked") {
      const pol = retryRow(job.kind);
      // blocked is a failure unless the policy sends it straight to the architect, which the strategy does on job_done
      if (!(pol.no_retry_on || []).includes("blocked") || pol.on_exhausted !== "architect") return failAttempt(job, "blocked");
    }
    const ny = endNeedsYou(job, t);
    const done = { ...job, ...ny.fields, state: "done", ended_at: t, head: gitHead(wt) };
    const rows = [...cancelTimers(job.id), ["jobs", done], ...ny.rows];
    const ctx = contextTokens(job, opts.transcriptRoot);
    status.delete(job.id);
    if (job.kind === "architect") {
      emit("architect_decision", { spec: spec.id, job: d.target || null, rows, case: d.case, task: d.task === null ? undefined : d.task,
        decision: st.decision, ruling: st.ruling, cost_if_wrong: st.cost_if_wrong, architect_job: job.id,
        text: `${st.decision}: ${st.ruling}`, ...ctx });
      return;
    }
    const extra = {};
    if (job.kind === "fix") {
      const review = db.prepare("SELECT head FROM jobs WHERE spec=? AND kind='review' AND state='done' AND (task IS ? OR task IS NULL) ORDER BY rowid DESC LIMIT 1")
        .get(spec.id, job.task);
      extra.fix_stats = fixStats(wt, review && review.head);
    }
    emit("job_done", { spec: spec.id, job: job.id, rows, task: job.task === null ? undefined : job.task, status: st,
      text: `${label(job)} ${st.status || st.verdict}`, ...extra, ...ctx });
  }
  const validReport = (job) => (job.report ? report.parse(readOr(job.report, null), job.kind) : null);

  // ---- inbox handlers (each runs inside the drain's transaction for its row) ----

  function onWorker(row) {
    const job = row.job ? get("jobs", row.job) : null;
    const p = parse(row.payload) || {};
    if (!job || job.state !== "running") return { drop: "job already finished" };
    if (p.pane !== job.pane) return { drop: "stale pane" };
    const t = now();
    if (row.kind === "gone") {
      const st = validReport(job);
      if (st) finishJob(job, st); else failAttempt(job, "gone");
      return undefined;
    }
    if (p.state === "model_limit" || p.state === "usage_limit") { failAttempt(job, p.state); return undefined; }
    let cur = job;
    if (p.state === "needs-you") {
      if (cur.needs_you_since === null) {
        const d = detailOf(cur);
        const r = deadlineRows({ ...cur, needs_you_since: t }, { ...d, parked: false }, t + NEEDS_YOU_PARK_S);
        emit("needs_you", { spec: cur.spec, job: cur.id, rows: r.rows, text: `permission prompt in ${cur.window}` });
      }
      return undefined;
    }
    if (cur.needs_you_since !== null) { // answered in the window: the clocks run again, and a park for it ends
      const d = { ...detailOf(cur), parked: false, resumed_at: t };
      cur = { ...cur, needs_you_total: (cur.needs_you_total || 0) + (t - cur.needs_you_since), needs_you_since: null };
      const r = deadlineRows(cur, d, nextDue(cur, d, t));
      const spec = get("specs", cur.spec);
      const wait = inbox.openWaitFor(db, cur.spec);
      if (spec.state === "awaiting_you" && wait && wait.step === `core:needs_you:${cur.id}`) {
        const prev = (lastEvent(spec.id, "awaiting_you") || { detail: {} }).detail.prev_state || "running";
        r.rows.push(["waits", { ...wait, answered_at: t, answer: "worker_busy", note: null }], ["specs", { ...spec, state: prev, updated_at: t }]);
      }
      emit("needs_you_end", { spec: cur.spec, job: cur.id, rows: r.rows });
      cur = get("jobs", cur.id);
    }
    if (p.state !== "ready") return undefined;
    const st = validReport(cur);
    if (st) { finishJob(cur, st); return undefined; }
    const d = detailOf(cur);
    if (d.told_at) { failAttempt(cur, "no_report"); return undefined; }
    const nd = { ...d, told_at: t };
    const r = deadlineRows(cur, nd, nextDue(cur, nd, t));
    emit("report_nudge", { spec: cur.spec, job: cur.id, rows: r.rows, text: `no report yet: ${cur.report}` });
    const handle = handleOf(cur);
    effects.push(() => tell(handle, `Your report is missing or has no valid json:status block. Write it to ${cur.report}`));
    return undefined;
  }

  function onTimer(row) {
    const t = now();
    if (row.kind === "retry") {
      const job = row.job ? get("jobs", row.job) : null;
      if (!job || job.state !== "backoff") return { drop: "job is not in backoff" };
      emit("retry_due", { spec: job.spec, job: job.id, rows: [["jobs", { ...job, state: "pending" }]] });
      return undefined;
    }
    if (row.kind === "usage_reset") {
      const rows = all("SELECT * FROM jobs WHERE state='backoff'").filter((j) => detailOf(j).wait_usage)
        .map((j) => ["jobs", withDetail({ ...j, state: "pending" }, { ...detailOf(j), wait_usage: false })]);
      emit("usage_resumed", { spec: row.spec, rows, text: "usage limit reset: dispatching again" });
      return undefined;
    }
    if (row.kind === "deadline") {
      const job = row.job ? get("jobs", row.job) : null;
      if (!job || job.state !== "running") return { drop: "job already finished" };
      if (detailOf(job).deadline !== String(row.source_id).split("@")[0]) return { drop: "superseded deadline" };
      evaluate(job, t);
      return undefined;
    }
    return { drop: `no handler for timer kind ${row.kind}` };
  }

  function onSignal(row) {
    const t = now();
    const spec = row.spec ? get("specs", row.spec) : null;
    const wait = spec ? inbox.openWaitFor(db, spec.id) : null;
    if (!spec || spec.state !== "awaiting_you" || !wait) return { drop: "spec is not waiting" };
    const p = parse(row.payload) || {};
    if (!["approve", "deny", "fail"].includes(p.answer)) return { drop: `unknown answer ${p.answer}` };
    const asked = (lastEvent(spec.id, "awaiting_you") || { detail: {} }).detail;
    const rows = [["waits", { ...wait, answered_at: t, answer: p.answer, note: p.note === undefined ? null : p.note }]];
    if (p.answer === "approve") rows.push(["specs", { ...spec, state: asked.prev_state || "running", updated_at: t }]);
    emit("signal", { spec: spec.id, rows, answer: p.answer, note: p.note === undefined ? null : p.note, step: wait.step,
      question: wait.question, stored: asked.stored, text: `${p.answer}: ${wait.question}` });
    return undefined;
  }

  function handler(row) {
    if (produced) throw STOP; // one undecided input at a time: pump before the next row
    if (row.source === "worker") return onWorker(row);
    if (row.source === "timer") return onTimer(row);
    if (row.source === "user") return onSignal(row);
    return { drop: `no handler for source ${row.source}` };
  }

  async function drainAll() {
    for (;;) {
      let more = false;
      produced = false;
      inTx = true;
      try { inbox.drain(db, handler, now()); } catch (e) { if (e !== STOP) throw e; more = true; } finally { inTx = false; }
      for (const f of effects.splice(0)) await f();
      await pumpAll();
      if (!more) return;
    }
  }

  // ---- commands ----

  function stateFor(spec, upto) {
    const evs = all("SELECT * FROM events WHERE spec=? AND seq<=? ORDER BY seq", spec.id, upto)
      .filter((e) => INPUTS.includes(e.kind)).map((e) => ({ ...e, detail: parse(e.detail) || {} }));
    return { spec, tasks: plan(spec).tasks, jobs: all("SELECT * FROM jobs WHERE spec=? ORDER BY rowid", spec.id), events: evs, retry: retryTable() };
  }
  const done = (outcome) => ({ type: "set_state", state: "done", outcome });

  // What the core itself does with an answer to one of its own parks (step `core:<what>:<rest>`).
  function coreSignal(d) {
    const [, what, ...rest] = String(d.step).split(":");
    const id = rest.join(":");
    if (d.answer !== "approve") {
      if (what === "policy") return [done("failed — policy changed")];
      return [done(d.answer === "deny" ? `denied: ${d.question}` : `failed — ${d.note === null || d.note === undefined ? "" : d.note}`)];
    }
    if (what === "gate" && d.stored) return [{ ...d.stored, gate_ok: true }];
    if (what === "refused" && d.stored) return [{ ...d.stored, refusal: undefined }];
    if (what === "policy") return [{ type: "restamp" }];
    if (what === "step") return [{ type: "step_retry", key: id }];
    if (what === "exhausted") return [{ type: "retry_job", job: id }];
    if (what === "needs_you") return [{ type: "needs_you_again", job: id }];
    return []; // integrate: its steps row is still at intent, so it runs again
  }

  // The strategy's commands for an input, plus the core's own: ledger lines, user gates, exhausted retry policies.
  function expand(spec, ev, cmds) {
    const d = ev.detail;
    const p = plan(spec);
    const out = [];
    if (ev.kind === "signal") {
      out.push({ type: "record_ruling", by: "user", cost_if_wrong: "the user's own call",
        text: `${d.answer}${d.note ? ` (${d.note})` : ""}: ${d.question}` });
      if (String(d.step).startsWith("core:")) return out.concat(coreSignal(d));
    }
    if (ev.kind === "check_result" && d.ok) out.push({ type: "ledger", kind: "green_check", task: d.task, sha: short(d.sha), rc: 0 });
    const job = ev.job ? get("jobs", ev.job) : null;
    if (ev.kind === "job_done" && job && job.kind === "review") {
      const tasks = detailOf(job).tasks || [job.task];
      const blocking = ((d.status || {}).findings || []).filter((f) => BLOCKING.includes(f.severity));
      for (const n of tasks) {
        const mine = blocking.filter((f) => f.task === n || (!tasks.includes(f.task) && n === tasks[0]));
        out.push({ type: "ledger", kind: "review", task: n, findings: mine.length, text: mine.length ? mine[0].text : undefined });
        if (!mine.length) {
          const first = db.prepare("SELECT base FROM jobs WHERE spec=? AND kind='implement' AND task=? ORDER BY rowid LIMIT 1").get(spec.id, n);
          out.push({ type: "ledger", kind: "task_complete", task: n, first: short(first && first.base), last: short(job.head) });
        }
      }
    }
    cmds.forEach((c, i) => {
      const prev = cmds[i - 1];
      const next = cmds[i + 1];
      if (c.type === "start_job" && c.kind === "implement" && (p.byN.get(c.task) || {}).gate) {
        out.push({ type: "park", question: `user gate: task ${c.task} ${p.byN.get(c.task).subject}`, step: `core:gate:${c.task}`, stored: c });
      } else if (c.type === "start_job" && c.kind === "fix" && c.round) {
        out.push({ type: "ledger", kind: "fix_round", task: c.task, round: c.round }, c);
      } else if (c.type === "start_job" && c.kind === "fix_wave") {
        out.push({ type: "ledger", kind: "fix_wave" }, c);
      } else if (c.type === "log" && c.kind === "refused" && next && next.type === "escalate") {
        out.push({ ...c, job: next.job, case: next.case });
      } else if (c.type === "escalate" && prev && prev.type === "log" && prev.kind === "refused") {
        out.push({ ...c, refusal: prev.text });
      } else {
        out.push(c);
      }
    });
    if (ev.kind === "job_failed" && d.exhausted && job) {
      const what = `${label(job)} failed: ${d.reason}`;
      if (d.on_exhausted === "park") out.push({ type: "park", question: what, step: `core:exhausted:${job.id}` });
      if (d.on_exhausted === "fail_spec") out.push(done(`failed — ${label(job)}: ${d.reason}`));
    }
    return out;
  }

  async function apply(spec, c, tag) {
    const t = now();
    const base = { spec: spec.id, ...tag };
    if (c.type === "start_job") {
      const job = newJob(spec, c, { try: 1, findings: c.findings, resume_of: c.resume_of, bounce: c.bounce, round: c.round, tasks: c.tasks });
      emit("job_created", { ...base, job: job.id, rows: [["jobs", job]], task: c.task, tier: job.tier });
    } else if (c.type === "run_check") {
      const stale = c.check === "stale";
      const row = { key: `${stale ? "stale" : "check"}:${spec.id}:${stale ? "" : c.task}:${tag.cause}`, spec: spec.id, kind: stale ? "stale_check" : "check",
        state: "intent", result: JSON.stringify({ task: c.task === undefined ? null : c.task }), created_at: t, updated_at: t };
      emit("check_requested", { ...base, rows: [["steps", row]], task: c.task, check: stale ? "stale" : "verify" });
    } else if (c.type === "request_integrate") {
      const row = { key: `integrate:${spec.id}:${tag.cause}`, spec: spec.id, kind: "integrate", state: "intent", result: "{}", created_at: t, updated_at: t };
      emit("integrate_requested", { ...base, rows: [["steps", row]] });
    } else if (c.type === "park") {
      if (!park(spec, c.question, c.step, { options: c.options, stored: c.stored, ...tag })) emit("park_skipped", { ...base, question: c.question, step: c.step });
    } else if (c.type === "escalate") {
      applyEscalate(spec, c, base);
    } else if (c.type === "record_ruling") {
      emit("ruling", { ...base, text: c.text, cost_if_wrong: c.cost_if_wrong, by: c.by });
    } else if (c.type === "set_state" && c.state === "done") {
      const merged = lastEvent(spec.id, "integrated");
      // section 4: a spec that fails after tests red after its merge reverts that merge
      if (merged && merged.detail.outcome === "tests_red" && realIntegrate.isFailure(c.outcome)) await revertFn(spec);
      // every terminal outcome, failed and denied included, gets its ledger archive and metrics record. This runs before
      // the event commits; finalize's steps are keyed per spec, so a replay after a crash runs none of them twice.
      await finalizeFn(spec, c.outcome);
      const rows = [["specs", { ...spec, state: "done", outcome: c.outcome === undefined ? null : c.outcome, updated_at: t }]];
      const wait = inbox.openWaitFor(db, spec.id);
      if (wait) rows.push(["waits", { ...wait, answered_at: t, answer: "closed", note: "the spec ended" }]);
      emit(realIntegrate.isFailure(c.outcome) ? "fail_spec" : "spec_done", { ...base, rows, outcome: c.outcome, text: String(c.outcome) });
    } else if (c.type === "set_state") {
      emit("spec_state", { ...base, rows: [["specs", { ...spec, state: c.state, updated_at: t }]], state: c.state });
    } else if (c.type === "log") {
      const kind = c.kind === "deferred" ? "minor" : c.kind === "refused" ? "refused" : "log";
      emit(kind, { ...base, text: c.text, task: c.task, log_kind: c.kind, case: c.case, target: c.job });
    } else if (c.type === "ledger") {
      const { type, kind, ...fields } = c;
      emit(kind, { ...base, ...fields });
    } else if (c.type === "restamp") {
      const rows = [["specs", { ...spec, policy_version: policy.POLICY_VERSION, policy_hash: hash, updated_at: t }], ...retryRows()];
      emit("policy_restamped", { ...base, rows });
    } else if (c.type === "step_retry") {
      const s = get("steps", c.key);
      emit("step_reset", { ...base, rows: s ? [["steps", { ...s, state: "failed", updated_at: t }]] : [], key: c.key });
    } else if (c.type === "retry_job") {
      const old = get("jobs", c.job);
      const job = newJob(spec, { kind: old.kind, task: old.task === null ? undefined : old.task, tier: old.tier, model: old.model },
        { ...detailOf(old), try: 1, deadline: undefined, dl: undefined, nudged_at: undefined, told_at: undefined });
      emit("job_created", { ...base, job: job.id, rows: [["jobs", job]], task: old.task === null ? undefined : old.task, tier: job.tier, retry_of: old.id });
    } else if (c.type === "needs_you_again") {
      const job = get("jobs", c.job);
      const rows = job && job.state === "running" && job.needs_you_since !== null
        ? deadlineRows({ ...job, needs_you_since: t, needs_you_total: (job.needs_you_total || 0) + (t - job.needs_you_since) },
          { ...detailOf(job), parked: false }, t + NEEDS_YOU_PARK_S).rows : [];
      emit("needs_you", { ...base, job: c.job, rows });
    } else {
      emit("command_ignored", { ...base, command: c.type });
    }
  }

  // escalate: one architect job on the frontier tier (spec section 4). A refused retry_higher_tier goes back once
  // with the refusal in the case file; the second refusal for the same job parks the spec.
  function applyEscalate(spec, c, base) {
    if (!architect.CASES.includes(c.case)) {
      if (!park(spec, `unknown escalation case: ${c.case}`, "core:case", base)) emit("park_skipped", { ...base, case: c.case });
      return;
    }
    if (c.refusal) {
      const since = (lastEvent(spec.id, "signal") || { seq: 0 }).seq;
      const n = all("SELECT * FROM events WHERE spec=? AND kind='refused' AND seq>?", spec.id, since)
        .map((e) => parse(e.detail) || {}).filter((d) => d.case === c.case && d.target === c.job).length;
      if (n >= 2) {
        const question = `retry_higher_tier refused twice for ${c.job === undefined ? c.case : c.job}`;
        if (!park(spec, question, `core:refused:${c.case}`, { stored: c, ...base })) emit("park_skipped", { ...base, question });
        return;
      }
    }
    const job = newJob(spec, { kind: "architect", tier: "frontier" }, { try: 1, case: c.case, target: c.job, task: c.task, refusal: c.refusal });
    const rows = [["jobs", job]];
    const target = c.job ? get("jobs", c.job) : null;
    if (target && target.state !== "running") rows.push(["jobs", { ...target, state: "escalated" }]);
    emit("escalated", { ...base, job: job.id, rows, case: c.case, target: c.job, task: c.task, text: `${c.case}${c.job ? ` ${c.job}` : ""}` });
  }

  // Applies the commands of the spec's last input event that have no event yet. Returns whether it applied any.
  async function pump(specId) {
    const marks = INPUTS.map(() => "?").join(",");
    const last = db.prepare(`SELECT * FROM events WHERE spec=? AND kind IN (${marks}) ORDER BY seq DESC LIMIT 1`).get(specId, ...INPUTS);
    if (!last || pumped.get(specId) === last.seq) return false;
    const ev = { ...last, detail: parse(last.detail) || {} };
    const spec = get("specs", specId);
    const cmds = expand(spec, ev, strategy.decide(stateFor(spec, ev.seq), ev));
    const applied = all("SELECT detail FROM events WHERE spec=? AND seq>?", specId, ev.seq).filter((r) => (parse(r.detail) || {}).cause === ev.seq).length;
    for (let i = applied; i < cmds.length; i++) await apply(get("specs", specId), cmds[i], { cause: ev.seq, idx: i });
    pumped.set(specId, ev.seq);
    return applied < cmds.length;
  }
  async function pumpAll() {
    produced = false;
    let any = false;
    for (const s of all("SELECT id FROM specs WHERE state!='queued' ORDER BY position, created_at")) if (await pump(s.id)) any = true;
    return any;
  }

  // ---- acting on rows: checks, integrate, windows, dispatch ----

  async function act(spec, st) {
    const t = now();
    const wt = wtOf(spec);
    const finished = (result) => ["steps", { ...st, state: "done", result: JSON.stringify(result), updated_at: t }];
    if (st.kind === "stale_check") {
      const r = cp.spawnSync(tmuxCtl, ["registry", "stale", spec.id], { cwd: wt, env, encoding: "utf8", timeout: 120000 });
      const stale = (r.stdout || "").split("\n")[0].trim() === "stale";
      emit("stale_result", { spec: spec.id, rows: [finished({ stale })], stale, text: stale ? "stale" : "fresh" });
    } else if (st.kind === "check") {
      const n = (parse(st.result) || {}).task;
      const task = plan(spec).byN.get(n);
      let r = cp.spawnSync("zsh", ["-c", task.verifyCommand], { cwd: wt, env, encoding: "utf8", timeout: CHECK_TIMEOUT_MS });
      let output = `${r.stdout || ""}${r.stderr || ""}`;
      let ok = !r.error && r.status === 0;
      if (ok && fs.existsSync(path.join(wt, ".agent-ci.yml"))) {
        r = cp.spawnSync("agent-ci", ["check"], { cwd: wt, env, encoding: "utf8", timeout: CHECK_TIMEOUT_MS });
        output += `${r.stdout || ""}${r.stderr || ""}`;
        ok = !r.error && r.status === 0;
      }
      const log = path.join(paths.workspace(wt), "logs", `check-${n}-${st.key.split(":").pop()}.log`);
      fs.mkdirSync(path.dirname(log), { recursive: true });
      fs.writeFileSync(log, output);
      if (ok) {
        const sha = gitHead(wt);
        emit("check_result", { spec: spec.id, rows: [finished({ task: n, ok: true })], task: n, ok: true, sha, rc: 0 });
      } else {
        const b = bounce.text(output, log);
        emit("check_result", { spec: spec.id, rows: [finished({ task: n, ok: false })], task: n, ok: false, text: b.text, bounce_bytes: b.bytes,
          rc: r.status === undefined ? null : r.status });
      }
    } else if (st.kind === "integrate") {
      const res = (await integrateFn(spec)) || {};
      if (res.outcome === "parked") { park(get("specs", spec.id), res.question, "core:integrate"); return; }
      emit("integrated", { spec: spec.id, rows: [finished(res)], outcome: res.outcome, merge: res.merge, text: String(res.outcome) });
    }
  }

  async function advance() {
    for (let moved = true; moved;) {
      moved = await pumpAll();
      for (const s of all("SELECT * FROM specs WHERE state NOT IN ('queued','done','awaiting_you') ORDER BY position, created_at")) {
        const marks = MY_STEPS.map(() => "?").join(",");
        const st = db.prepare(`SELECT * FROM steps WHERE spec=? AND state='intent' AND kind IN (${marks}) ORDER BY created_at, key LIMIT 1`).get(s.id, ...MY_STEPS);
        if (!st) continue;
        await act(s, st);
        moved = true;
        break; // pump before the next row
      }
    }
  }

  async function closeWindows() {
    for (const j of all("SELECT j.* FROM jobs j JOIN specs s ON s.id=j.spec WHERE j.state='running' AND s.state='done'")) {
      emit("job_cancelled", { spec: j.spec, job: j.id, rows: [...cancelTimers(j.id), ["jobs", { ...j, state: "failed", ended_at: now() }]], text: "the spec ended" });
    }
    for (const j of all("SELECT * FROM jobs WHERE state IN ('done','failed','escalated') AND pane IS NOT NULL ORDER BY rowid")) {
      if (closed.has(j.id)) continue;
      const desc = { key: `close_window:${j.id}`, spec: j.spec, kind: "close_window", facts: { pane: j.pane } };
      const have = steps.getRow(db, desc.key);
      if (!(have && have.state === "done")) {
        steps.begin(db, desc, { now });
        let error = null;
        // a window this engine cannot close (a handle from an earlier process, a dead tmux server) is a failed step,
        // not an engine error: the run goes on and the window is left for the user
        try { await backend.close(handleOf(j)); } catch (e) { error = String((e && e.message) || e); }
        if (error === null) {
          steps.finish(db, desc, { pane: j.pane }, { now });
        } else {
          emit("step_failed", { spec: j.spec, job: j.id, rows: [["steps", { ...get("steps", desc.key), state: "failed", result: JSON.stringify({ error }), updated_at: now() }]],
            key: desc.key, step_kind: "close_window", error, text: `could not close ${j.window}: ${error}` });
        }
      }
      closed.add(j.id);
    }
  }

  function taskText(spec, n) {
    const task = plan(spec).byN.get(n);
    if (!task) return "";
    return [`## Task ${task.n}: ${task.subject}`, "", task.description, "", `Files: ${task.files.join(", ") || "-"}`, `Verify: \`${task.verifyCommand}\``, ""].join("\n");
  }

  function briefFor(spec, job, reportPath) {
    const d = detailOf(job);
    if (job.kind === "architect") return architectBrief(spec, job, d, reportPath);
    const reviewer = ["review", "re_review", "final_review"].includes(job.kind);
    const tasks = d.tasks || (job.task === null ? [] : [job.task]);
    const out = [`# ${job.kind} job ${job.id}`, "",
      `Spec: ${spec.id}`, `Plan: ${spec.plan}`, `Worktree: ${wtOf(spec)}`, `Branch: ${spec.branch}`, ""];
    if (reviewer) {
      out.push("You are a reviewer. Review the work against the task text and the spec; change no file but your report.", "");
      const scope = tasks.length ? all("SELECT * FROM jobs WHERE spec=? ORDER BY rowid", spec.id).filter((j) => tasks.includes(j.task) && WORKER_KINDS.includes(j.kind))
        : all("SELECT * FROM jobs WHERE spec=? ORDER BY rowid", spec.id).filter((j) => WORKER_KINDS.includes(j.kind));
      const first = scope.find((j) => j.base);
      out.push("## Review package", "", `Commit range: ${first ? first.base : spec.base || "(branch start)"}..${gitHead(wtOf(spec)) || "HEAD"}`, "");
      for (const j of scope) out.push(`- ${j.id}: brief ${j.brief}, report ${j.report}`);
      if (job.kind !== "review") {
        const parked = all("SELECT * FROM events WHERE spec=? AND kind IN ('minor','awaiting_you') ORDER BY seq", spec.id).map((e) => `- ${architect.eventLine(e)}`);
        out.push("", "## Deferred and parked so far", "", parked.join("\n") || "(none)");
      }
      out.push("");
    } else {
      out.push("You are an engine worker: claude/worker.md applies. Commit your work on this branch; do not push, merge or delete branches.", "");
    }
    for (const n of tasks) out.push(taskText(spec, n));
    if (d.findings !== undefined && d.findings !== null) {
      out.push(d.bounce ? `## The verify command is red (bounce ${d.bounce})` : "## Findings to fix", "",
        typeof d.findings === "string" ? d.findings : d.findings.map((f) => `- [${f.severity}] task ${f.task}: ${f.text}`).join("\n"), "");
    }
    if (d.resume_of) {
      const prev = get("jobs", d.resume_of);
      if (prev) out.push(`Earlier work on this task: brief ${prev.brief}, report ${prev.report}`, "");
    }
    out.push("## Report", "", `Report file: ${reportPath}`, "", "Write your report there. Its last fenced block must be:", "",
      "```json:status", reviewer ? STATUS_SHAPES.reviewer : STATUS_SHAPES.worker, "```", "");
    return out.join("\n");
  }

  function architectBrief(spec, job, d, reportPath) {
    const target = d.target ? get("jobs", d.target) : null;
    const taskN = d.task === undefined || d.task === null ? (target ? target.task : null) : d.task;
    const lastOf = (kind, pred) => { const e = all("SELECT * FROM events WHERE spec=? AND kind=? ORDER BY seq DESC", spec.id, kind)
      .map((x) => ({ ...x, detail: parse(x.detail) || {} })).find(pred || (() => true)); return e ? e.detail : {}; };
    const findings = (list) => (list || []).map((f) => `- [${f.severity}] task ${f.task}: ${f.text}`).join("\n");
    const review = db.prepare("SELECT * FROM jobs WHERE spec=? AND kind IN ('review','re_review','final_review') AND state IN ('done','escalated') ORDER BY rowid DESC LIMIT 1").get(spec.id);
    let finding = taskN === null ? "" : taskText(spec, taskN);
    if (d.case === "verify_red") finding += `\nThe verify command is red:\n\n${lastOf("check_result", (e) => e.detail.ok === false).text || ""}`;
    if (d.case === "fix_rounds_exhausted" || d.case === "residual_findings") {
      const verdict = review ? report.parse(readOr(review.report, ""), review.kind) : null;
      finding += `\nOpen findings:\n\n${findings(verdict && verdict.findings)}`;
    }
    if (d.case === "blocked") finding += `\nThe implementer reported blocked: ${(((lastOf("job_done", (e) => e.job === d.target).status) || {}).concerns || []).join("; ")}`;
    if (d.case === "failed_twice") finding += `\nFailures: ${all("SELECT * FROM events WHERE spec=? AND kind='job_failed' ORDER BY seq", spec.id).map((e) => `${e.job} ${(parse(e.detail) || {}).reason}`).join(", ")}`;
    if (d.case === "tests_red_after_merge") finding += `\nThe project tests are red after the merge (merge commit ${lastOf("integrated").merge || "unknown"}).`;
    return architect.build({
      kase: d.case, spec: spec.id, job: d.target, task: taskN, finding,
      report: target ? readOr(target.report, "") : "", review: review ? readOr(review.report, "") : "",
      decisions: architect.decisions(readOr(path.resolve(wtOf(spec), String(spec.id).split("#")[0]), "")),
      events: all("SELECT * FROM events WHERE spec=? ORDER BY seq", spec.id), reportPath, refusal: d.refusal,
    });
  }

  // The brief and report paths of a job, the same for a fresh dispatch and for a worker adopted after a crash.
  function jobPaths(spec, job) {
    const ws = paths.workspace(wtOf(spec));
    return { brief: path.join(ws, "briefs", `${fileName(job.id)}.md`), report: path.join(ws, "reports", `${fileName(job.id)}.md`) };
  }

  async function dispatch() {
    if (db.prepare("SELECT 1 FROM jobs WHERE state='running' LIMIT 1").get()) return; // concurrency 1
    const job = db.prepare("SELECT j.* FROM jobs j JOIN specs s ON s.id=j.spec WHERE j.state='pending' AND s.state NOT IN ('queued','done','awaiting_you') ORDER BY j.rowid LIMIT 1").get();
    if (!job) return;
    if (!usagePaused()) { // the status-line tap reads 100%: pause before spending a start
      const until = tapReset(now());
      if (until) {
        const rows = [];
        pauseForUsage(job.spec, rows);
        emit("usage_limit", { spec: job.spec, rows, until, text: `usage limit until ${new Date(until * 1000).toISOString()}` });
        for (const f of effects.splice(0)) await f();
      }
    }
    if (usagePaused()) return;
    const spec = get("specs", job.spec);
    const wt = wtOf(spec);
    const d = detailOf(job);
    const ready = { ...job, ...jobPaths(spec, job), window: `${slugOf(spec)}·${label(job)}` };
    const text = briefFor(spec, ready, ready.report);
    fs.mkdirSync(path.dirname(ready.brief), { recursive: true });
    fs.mkdirSync(path.dirname(ready.report), { recursive: true });
    fs.writeFileSync(ready.brief, text);
    const desc = { key: `start_worker:${job.id}`, spec: spec.id, kind: "start_worker", facts: { window: ready.window, job: job.id } };
    steps.begin(db, desc, { now });
    let handle = null;
    let how = "start";
    try {
      const prev = d.resume_of ? get("jobs", d.resume_of) : null;
      if (prev && prev.pane && prev.session_id) { // fix rounds resume the worker's own session when it can be resumed
        try { handle = await backend.resume(handleOf(prev), text); how = "resume"; } catch (_) { handle = null; }
      }
      if (!handle) handle = await backend.start({ id: ready.id, kind: ready.kind, task: ready.task, model: ready.model, effort: ready.effort,
        brief: ready.brief, report: ready.report, worktree: wt, window: ready.window });
    } catch (e) {
      const t = now();
      const row = get("steps", desc.key);
      const error = String((e && e.message) || e);
      emit("step_failed", { spec: spec.id, rows: [["steps", { ...row, state: "failed", result: JSON.stringify({ error }), updated_at: t }]], key: desc.key, step_kind: "start_worker", error });
      emit("job_running", { spec: spec.id, job: job.id, rows: [["jobs", { ...ready, state: "running", started_at: t }]], text: `start failed: ${error}` });
      failAttempt(get("jobs", job.id), "start_failed");
      return;
    }
    const t = now();
    const running = { ...ready, state: "running", started_at: t, window: handle.window || ready.window, pane: handle.pane,
      session_id: handle.session_id || null, base: gitHead(wt) };
    lastState.delete(job.id);
    const r = deadlineRows(running, d, t + HEARTBEAT_S);
    emit("dispatched", { spec: spec.id, job: job.id, rows: r.rows, task: job.task === null ? "-" : job.task, window: running.window,
      tier: job.tier, model: job.model, how, text: `${running.window} (${job.tier}, ${job.model})` });
    steps.finish(db, desc, { window: running.window, pane: handle.pane, job: job.id }, { now });
  }

  // ---- the tick's first steps ----

  const retryRows = () => Object.entries(retryTable()).map(([kind, r]) => ["retry_policies", { kind, max_attempts: r.max_attempts === undefined ? null : r.max_attempts,
    backoff_s: JSON.stringify(r.backoff_s === undefined ? [] : r.backoff_s), timeout_min: r.timeout_min === undefined ? null : r.timeout_min,
    no_retry_on: JSON.stringify(r.no_retry_on || []), on_exhausted: r.on_exhausted || null }]);

  // Measurement never blocks a spec: a failed metrics start stays a failed step (steps.run wrote the error and its
  // step_failed event) and the run goes on.
  function metricsStart(spec) {
    if (spec.batch === null || spec.batch === undefined || spec.batch === "") return;
    try {
      steps.run(db, { key: `metrics_start:${spec.id}`, spec: spec.id, kind: "metrics_start", facts: { spec: spec.id, batch: spec.batch } }, () => {
        const r = cp.spawnSync(tmuxCtl, ["metrics", "start", spec.id, "--batch", String(spec.batch), "--worktree", String(spec.worktree)],
          { cwd: repo, env, encoding: "utf8", timeout: 60000 });
        if (r.error || r.status !== 0) throw new Error(`metrics start: ${(r.stderr || (r.error && r.error.message) || "").trim().split("\n")[0]}`);
        return { spec: spec.id, batch: spec.batch };
      }, { now });
    } catch (_) { /* recorded as a failed step */ }
  }

  function startQueued() {
    if (db.prepare("SELECT 1 FROM specs WHERE state NOT IN ('queued','done','awaiting_you') LIMIT 1").get()) return;
    const spec = db.prepare("SELECT * FROM specs WHERE state='queued' ORDER BY position, created_at LIMIT 1").get();
    if (!spec) return;
    plan(spec); // a plan the engine cannot compile is an error before anything starts
    metricsStart(spec);
    const t = now();
    emit("spec_started", { spec: spec.id, rows: [["specs", { ...spec, state: "running", policy_version: policy.POLICY_VERSION, policy_hash: hash, updated_at: t }], ...retryRows()],
      text: spec.id });
  }

  function policyCheck() {
    for (const s of all("SELECT * FROM specs WHERE state NOT IN ('queued','done','awaiting_you') AND policy_version IS NOT NULL")) {
      if (s.policy_version === policy.POLICY_VERSION && s.policy_hash === hash) continue;
      const tag = (v, h) => `${v}:${String(h).slice(0, 8)}`;
      park(s, `engine rules changed (${tag(s.policy_version, s.policy_hash)}→${tag(policy.POLICY_VERSION, hash)}): continue under the new rules?`, "core:policy");
    }
  }

  function pollBackend() {
    const offered = [];
    for (const ev of backend.poll()) {
      const h = ev.handle || {};
      // by job id when the handle has one (pane ids repeat across processes and tmux restarts). A resumed session's
      // handle carries the job it resumed, with a pane that job never had: that one is matched by pane. An event whose
      // job is known and whose pane is that job's own is for an earlier attempt and is ignored.
      let job;
      if (h.job) {
        const named = get("jobs", h.job);
        if (named && named.state === "running") job = named.pane && h.pane && named.pane !== h.pane ? null : named;
        else if (named && named.pane === h.pane) job = null;
        else job = named ? db.prepare("SELECT * FROM jobs WHERE pane=? AND state='running'").get(h.pane) : null;
      } else {
        job = db.prepare("SELECT * FROM jobs WHERE pane=? AND state='running'").get(h.pane);
      }
      if (!job) continue;
      if (h.session_id && h.session_id !== job.session_id) emit("job_session", { spec: job.spec, job: job.id, rows: [["jobs", { ...job, session_id: h.session_id }]] });
      if (ev.type === "status") {
        status.set(job.id, ev);
        if (lastState.get(job.id) === ev.state) continue; // one row per change of state
        lastState.set(job.id, ev.state);
      } else if (ev.type !== "gone") {
        continue;
      }
      offered.push({ ...ev, handle: { ...h, job: job.id, spec: job.spec } });
    }
    if (offered.length) inbox.workerRows(db, offered, now());
  }

  function fail(e) {
    const msg = String((e && e.message) || e);
    halted = msg;
    inTx = false;
    try { tx(db, () => event(db, { kind: "engine_error", ts: now(), error: msg, text: msg })); } catch (_) { /* the database itself is the error */ }
    try { notify(`[Engine] stopped: ${msg}`); } catch (_) { /* best effort */ }
  }

  // ---- the public face ----

  const E = {
    db,
    get halted() { return halted; },

    addSpec(s) {
      const t = now();
      const row = { position: 0, runner: "engine", integration: "keep", push: 0, batch: null, state: "queued", outcome: null, worktree: repo,
        branch: null, strategy: "spec-driven", backend: "claude-tmux", policy_version: null, policy_hash: null, base: null,
        created_at: t, updated_at: t, ...s };
      emit("spec_added", { spec: row.id, rows: [["specs", row]], text: row.id });
      flush();
      return get("specs", row.id);
    },

    // One tick (spec section 10). After an internal error it does nothing: `engine resume` continues.
    async tick() {
      if (halted || stopped) return;
      try {
        startQueued();
        policyCheck();
        inbox.moveDueTimers(db, now());
        pollBackend();
        await pumpAll(); // the commands of an input decided last tick come before the next row
        await drainAll();
        await advance();
        await closeWindows();
        await dispatch();
      } catch (e) {
        fail(e);
      } finally {
        if (!stopped) flush();
      }
    },

    // Runs one spec to its outcome in the foreground; a parked spec keeps the engine ticking until it is answered.
    async run(specId) {
      for (;;) {
        await E.tick();
        const s = get("specs", specId);
        if (s && s.state === "done") return s.outcome;
        if (halted) throw new Error(`engine stopped: ${halted}`);
        await sleep(opts.tickMs === undefined ? TICK_S * 1000 : opts.tickMs);
      }
    },

    // Recovery (spec section 9), before the first tick of a restarted engine: reconcile intent steps, then look at
    // every job marked running. The ticks that follow fire due timers, drain the inbox and compare the policy.
    async resume() {
      try {
        const rec = steps.reconcile(db, opts.stepsCtx || { repo, mainRepo: repo, tmuxCtl, session: opts.session, tmuxArgs: opts.tmuxArgs }, { now });
        for (const r of rec.rerun) {
          const sp = r.kind === "metrics_start" && r.spec ? get("specs", r.spec) : null;
          if (sp) metricsStart(sp); // the start never ran
        }
        for (const p of rec.park) {
          const s = get("steps", p.key);
          if (s && NEVER_PARK.includes(s.kind)) { // measurement and notices never park: the unknown row is failed
            steps.fail(db, s, `could not tell whether ${s.key} ran`, { now });
            continue;
          }
          if (!s || MY_STEPS.includes(s.kind) || !s.spec) continue; // the core's own rows are simply run again
          const spec = get("specs", s.spec);
          if (spec && spec.state !== "done") park(spec, p.question, `core:step:${p.key}`);
        }
        // a start_worker step the check found done: its pane is adopted
        for (const s of all("SELECT * FROM steps WHERE kind='start_worker' AND state='done'")) {
          const res = parse(s.result) || {};
          const job = res.reconciled && res.job ? get("jobs", res.job) : null;
          if (!job || job.state !== "pending" || !res.pane) continue;
          const t = now();
          const spec = get("specs", job.spec);
          const running = { ...job, ...jobPaths(spec, job), state: "running", started_at: t, window: res.window, pane: res.pane, base: gitHead(wtOf(spec)) };
          emit("dispatched", { spec: job.spec, job: job.id, rows: deadlineRows(running, detailOf(job), t + HEARTBEAT_S).rows, task: job.task === null ? "-" : job.task,
            window: res.window, tier: job.tier, model: job.model, how: "adopted" });
        }
        let watched = 0;
        for (const job of all("SELECT * FROM jobs WHERE state='running' ORDER BY rowid")) {
          const spec = get("specs", job.spec);
          let ok = false;
          if (typeof backend.adopt === "function") {
            try { ok = !!(await backend.adopt({ ...job, worktree: wtOf(spec) }, handleOf(job))); } catch (_) { ok = false; }
          }
          if (ok) { // its heartbeat and no-progress clocks restart now: a status that went stale while the engine was down is not a hang
            watched++;
            const t = now();
            const d = { ...detailOf(job), resumed_at: t, nudged_at: null };
            emit("adopted", { spec: job.spec, job: job.id, rows: deadlineRows(job, d, nextDue(job, d, t)).rows });
            continue;
          }
          // its window is gone for this engine: finished from its report when valid, else a new attempt (the drain decides)
          inbox.insert(db, { source: "worker", source_id: `${job.id}:${job.pane}:gone:resume:${now()}`, spec: job.spec, job: job.id, kind: "gone",
            payload: { pane: job.pane, window: job.window } }, now());
        }
        emit("resumed", { rerun: rec.rerun.map((r) => r.key), parked: rec.park.map((p) => p.key), watched });
        halted = null;
      } catch (e) {
        fail(e);
      } finally {
        flush();
      }
    },

    stop() {
      if (stopped) return;
      stopped = true;
      try { flush(); } catch (_) { /* best effort */ }
      try { db.close(); } catch (_) { /* already closed */ }
      if (readOr(lockFile).split("\n")[0] === String(process.pid)) fs.rmSync(lockFile, { force: true });
    },
  };
  return E;
}

module.exports = { start, contextTokens, fixStats, tapReset, TICK_S, HEARTBEAT_S, NO_PROGRESS_S, NUDGE_GRACE_S, TOOL_LIMIT_S, NEEDS_YOU_PARK_S };
