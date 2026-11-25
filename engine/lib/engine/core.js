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
// - An approval hold (spec 13) is an `approval` inbox row written by the worker's PreToolUse hook (hold.js). Its drain
//   marks the job held and parks the spec; the answer is a `signal` like any other, and its commands (the pass row, the
//   resume job) are pumped like any other, so a crash between them applies only the missing one.
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
const hold = require("./hold");
const schedule = require("./schedule");
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
const PK = { specs: "id", jobs: "id", steps: "key", timers: "id", waits: "id", retry_policies: "kind", inbox: "id", holds: "hold_id" };
const PASS_S = 3600; // an approval's pass is good for one hour from the answer (spec 13)
const MY_STEPS = ["check", "stale_check", "integrate"];
const NEVER_PARK = ["metrics_start", "metrics_record", "metrics_ask", "artifact", "awake_off", "registry_report", "commit_report", "metrics_record_parked", "queue_report", "schedule_run", "plist_remove"]; // measurement and notices
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
const ENDED_AT_PROMPT = ["worker_busy", "job_ended"]; // how a needs-you wait closes without the user
const NOT_LEAD = "COALESCE(runner, 'engine') != 'lead'"; // a lead-run spec never reaches the strategy, a job or the policy check (R7)

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
  function emit(kind, { spec = null, job = null, rows = [], kind: detailKind, ...extra } = {}) { // a `kind` in the fields is the detail's
    W(() => {
      const full = rows.map(([table, row]) => { put(db, table, row); return { table, row: get(table, row[PK[table]]) }; });
      event(db, { spec, job, kind, rows: full, ts: now(), ...extra, detailKind });
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

  // extra: {kind (required), recommendation?, options?, stored?, ...tag}. The recommendation is the site's, else the kind's default.
  function park(spec, question, step, extra = {}) {
    const { kind, recommendation, options: opts, ...rest } = extra;
    if (!kind) throw new Error("park needs a kind");
    if (inbox.openWaitFor(db, spec.id)) return false;
    const t = now();
    const rec = policy.recommendationFor(kind, recommendation);
    const options = opts || "approve|deny|fail";
    const n = db.prepare("SELECT COUNT(*) AS n FROM waits WHERE spec=?").get(spec.id).n;
    const wait = { id: `${spec.id}@${t}#${n + 1}`, spec: spec.id, step, question, options,
      asked_at: t, answered_at: null, answer: null, note: null, kind, recommendation: JSON.stringify(rec) };
    const command = `tmux-ctl engine signal ${spec.id} ${options}`;
    emit("awaiting_you", { spec: spec.id, rows: [["waits", wait], ["specs", { ...spec, state: "awaiting_you", updated_at: t }]],
      question, step, prev_state: spec.state, command, kind, recommendation: rec,
      text: `I recommend: ${rec.option} (${rec.confidence}): ${rec.why} — ${question} — answer with: ${command}`, ...rest });
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

  // ---- budget (spec 8b) ----

  const capsOf = (spec) => ({ attempts: spec.budget_attempts == null ? config.budget.attempts : spec.budget_attempts,
    tokens: spec.budget_tokens == null ? config.budget.tokens : spec.budget_tokens });
  const reachedOf = (spec) => { const c = capsOf(spec); return { attempts: (spec.spent_attempts || 0) >= c.attempts, tokens: (spec.spent_tokens || 0) >= c.tokens }; };

  // The job's tokens at its end: the backend's answer, or null with the reason. A job that never started has none to read.
  function usageOf(job) {
    if (job.started_at === null || job.started_at === undefined) return null;
    if (typeof backend.usage !== "function") return { tokens: null, reason: "the backend reports no usage" };
    try {
      const u = backend.usage(handleOf(job), { since: job.started_at });
      if (u && Number.isInteger(u.tokens)) return { tokens: u.tokens };
      return { tokens: null, reason: (u && u.reason) || "the backend gave no token count" };
    } catch (e) {
      return { tokens: null, reason: `usage failed: ${String((e && e.message) || e)}` };
    }
  }
  // Writes the job's tokens into the rows of its end event: the job row, and the spec row (merged into the one
  // endNeedsYou already returns). Returns the event fields.
  function tokenRows(job, rows) {
    const u = usageOf(job);
    if (!u) return {};
    const jr = rows.find((r) => r[0] === "jobs" && r[1].id === job.id);
    if (jr) jr[1] = { ...jr[1], tokens: u.tokens };
    if (u.tokens) {
      const sr = rows.find((r) => r[0] === "specs");
      if (sr) sr[1] = { ...sr[1], spent_tokens: (sr[1].spent_tokens || 0) + u.tokens };
      else { const spec = get("specs", job.spec); rows.push(["specs", { ...spec, spent_tokens: (spec.spent_tokens || 0) + u.tokens }]); }
    }
    return u.tokens === null ? { tokens: null, tokens_missing: u.reason, lower_bound: true } : { tokens: u.tokens };
  }
  // The cap recommendation (8b): approve when the last three completed tasks had no fix round, else fail.
  function capRecommendation(spec) {
    const last = all("SELECT * FROM events WHERE spec=? AND kind='task_complete' ORDER BY seq DESC LIMIT 3", spec.id).map((e) => (parse(e.detail) || {}).task);
    const fixes = all("SELECT * FROM events WHERE spec=? AND kind='fix_round'", spec.id).map((e) => (parse(e.detail) || {}).task);
    if (last.length === 3 && !last.some((n) => fixes.includes(n))) return policy.SITE_RECS.budget_extend;
    return policy.SITE_RECS.budget_loop;
  }

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
      if (park(get("specs", job.spec), `permission prompt in ${job.window}`, `core:needs_you:${job.id}`, { kind: "needs_you" })) {
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
      if (spec.state === "awaiting_you" && turnFreeFor(spec.id)) rows.push(["specs", { ...spec, state: prev, outcome: null, updated_at: t }]);
    }
    return { fields, rows };
  }

  // A failed attempt (spec 10.2): the job ends, and its retry policy decides what follows. The retry row is written
  // with the failure, so a crash cannot lose it.
  function failAttempt(job, reason0) {
    if (detailOf(job).held) return endHeld(job, reason0);
    const t = now();
    const d = detailOf(job);
    const pol = retryRow(job.kind);
    const reason = reason0 === "model_limit" && d.model_fallback ? "model_limit_after_fallback" : reason0;
    const tryN = d.try || 1;
    const spec = get("specs", job.spec);
    const ny = endNeedsYou(job, t);
    const rows = [...cancelTimers(job.id), ["jobs", { ...job, ...ny.fields, state: "failed", ended_at: t, head: gitHead(wtOf(spec)) }], ...ny.rows];
    const proto = { kind: job.kind, task: job.task === null ? undefined : job.task, tier: job.tier, model: job.model };
    const carry = { ...d, deadline: undefined, dl: undefined, nudged_at: undefined, told_at: undefined, parked: undefined, resumed_at: undefined, reserved: undefined };
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
    const spend = tokenRows(job, rows);
    emit("job_failed", { spec: spec.id, job: job.id, rows, task: job.task === null ? undefined : job.task, reason, try: tryN,
      exhausted, on_exhausted: pol.on_exhausted, retry: next ? next.id : null, text: `${label(job)} failed: ${reason}`, ...spend, ...contextTokens(job, opts.transcriptRoot) });
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

  // Every end of a held job (A5: a valid report, ready, its window gone, any timeout): it is `escalated`, with no
  // retry, no architect case and no input for the strategy. The answer to its hold starts the job that goes on.
  function endHeld(job, how) {
    const t = now();
    const spec = get("specs", job.spec);
    const ny = endNeedsYou(job, t);
    const rows = [...cancelTimers(job.id), ["jobs", { ...job, ...ny.fields, state: "escalated", ended_at: t, head: gitHead(wtOf(spec)) }], ...ny.rows];
    const spend = tokenRows(job, rows);
    emit("held_job_ended", { spec: job.spec, job: job.id, rows, hold: detailOf(job).held, how, text: `${label(job)} held: ${how}`,
      ...spend, ...contextTokens(job, opts.transcriptRoot) });
    status.delete(job.id);
  }
  // A held worker is told to write its report and stop: its window is closed once the report is there, ready or not.
  function endHeldWithReport() {
    for (const j of all("SELECT * FROM jobs WHERE state='running' ORDER BY rowid")) {
      if (detailOf(j).held && validReport(j)) endHeld(j, "report");
    }
  }

  // A job ended with a valid report.
  function finishJob(job, st) {
    if (detailOf(job).held) return endHeld(job, "report");
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
    const ctx = { ...tokenRows(job, rows), ...contextTokens(job, opts.transcriptRoot) };
    status.delete(job.id);
    if (job.kind === "architect") {
      emit("architect_decision", { spec: spec.id, job: d.target || null, rows, case: d.case, task: d.task === null ? undefined : d.task,
        decision: st.decision, ruling: st.ruling, cost_if_wrong: st.cost_if_wrong, recommend: st.recommend, architect_job: job.id,
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
    if (p.state === "model_limit" || p.state === "usage_limit") {
      const st = validReport(job); // a finished job whose pane also shows a limit line is done, not a limit failure
      if (st) finishJob(job, st); else failAttempt(job, p.state);
      return undefined;
    }
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
        r.rows.push(["waits", { ...wait, answered_at: t, answer: "worker_busy", note: null }]);
        if (turnFreeFor(spec.id)) r.rows.push(["specs", { ...spec, state: prev, outcome: null, updated_at: t }]); // else `unparked` at its turn
      }
      emit("needs_you_end", { spec: cur.spec, job: cur.id, rows: r.rows });
      cur = get("jobs", cur.id);
    }
    if (p.state !== "ready") return undefined;
    if (detailOf(cur).held) { endHeld(cur, validReport(cur) ? "report" : "ready"); return undefined; }
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

  // ---- the turn across parked specs (spec section 11) ----

  const newestWait = (specId) => db.prepare("SELECT * FROM waits WHERE spec=? ORDER BY asked_at DESC, rowid DESC LIMIT 1").get(specId) || null;
  // Parked specs whose wait is answered and not applied yet, oldest answer first: a user answer stored while another
  // spec held the turn, or a needs-you wait its worker ended.
  function heldSpecs() {
    const out = [];
    for (const spec of all(`SELECT * FROM specs WHERE state='awaiting_you' AND ${NOT_LEAD}`)) {
      if (inbox.openWaitFor(db, spec.id)) continue;
      const wait = newestWait(spec.id);
      if (!wait || wait.answered_at === null) continue;
      if (!ENDED_AT_PROMPT.includes(wait.answer)) { // a user answer whose signal is written has its commands pending, not its turn
        const sig = lastEvent(spec.id, "signal");
        if (sig && sig.detail.wait === wait.id) continue;
      }
      out.push({ spec, wait });
    }
    return out.sort((x, y) => x.wait.answered_at - y.wait.answered_at);
  }
  const holder = (but) => db.prepare("SELECT id FROM specs WHERE state NOT IN ('queued','done','awaiting_you') AND id IS NOT ? LIMIT 1").get(but === undefined ? null : but);
  // Whether a parked spec may go on now: no other spec holds the turn and no other answered spec is ahead of it.
  const turnFreeFor = (specId) => !holder(specId) && !heldSpecs().some((h) => h.spec.id !== specId);
  // A needs-you wait its worker ended while the spec is still parked: the job's end is decided when the spec is unparked.
  function waitsForUnpark(spec) {
    if (spec.state !== "awaiting_you" || inbox.openWaitFor(db, spec.id)) return false;
    const w = newestWait(spec.id);
    return !!w && ENDED_AT_PROMPT.includes(w.answer);
  }

  // The `signal` input: the answer applied. `wait` is the answered row (its answered_at is when the user answered).
  function writeSignal(spec, wait) {
    const asked = (lastEvent(spec.id, "awaiting_you") || { detail: {} }).detail;
    const rows = [["waits", wait]];
    // a denied hold goes on too (spec 13): the spec leaves the park with the signal itself, as an approve does, so a
    // crash before the resume job is created cannot hand the turn to another spec
    const goesOn = wait.answer === "approve" || (wait.answer === "deny" && String(wait.step).startsWith("core:hold:"));
    if (goesOn) rows.push(["specs", { ...spec, state: asked.prev_state || "running", outcome: null, updated_at: now() }]);
    emit("signal", { spec: spec.id, rows, answer: wait.answer, note: wait.note, step: wait.step, question: wait.question, wait: wait.id, kind: wait.kind,
      recommendation: parse(wait.recommendation), stored: asked.stored, answered_at: wait.answered_at, text: `${wait.answer}: ${wait.question}` });
  }

  function onSignal(row) {
    const t = now();
    const spec = row.spec ? get("specs", row.spec) : null;
    const wait = spec ? inbox.openWaitFor(db, spec.id) : null;
    if (!spec || spec.state !== "awaiting_you" || !wait) return { drop: "spec is not waiting" };
    const p = parse(row.payload) || {};
    if (!String(wait.options || "approve|deny|fail").split("|").includes(p.answer)) return { drop: `unknown answer ${p.answer}` };
    const answered = { ...wait, answered_at: t, answer: p.answer, note: p.note === undefined ? null : p.note };
    if (turnFreeFor(spec.id)) { writeSignal(spec, answered); return undefined; }
    // another spec holds the turn: the answer is stored on the wait at once and applied when the turn is free
    emit("answer_held", { spec: spec.id, rows: [["waits", answered]], answer: answered.answer, note: answered.note, wait: wait.id, text: `${p.answer} (held): ${wait.question}` });
    return undefined;
  }

  // ---- the queue's rows (spec section 6) ----

  const specRow = (s) => {
    const t = now();
    const row = { position: 0, runner: "engine", integration: "keep", push: 0, batch: null, state: "queued", outcome: null, worktree: repo,
      branch: null, strategy: "spec-driven", backend: "claude-tmux", policy_version: null, policy_hash: null, base: null,
      created_at: t, updated_at: t, ...s };
    if (row.budget_attempts === undefined || row.budget_attempts === null) row.budget_attempts = config.budget.attempts;
    if (row.budget_tokens === undefined || row.budget_tokens === null) row.budget_tokens = config.budget.tokens;
    row.spent_attempts = row.spent_attempts || 0;
    row.spent_tokens = row.spent_tokens || 0;
    return row;
  };

  // A drained `enqueue` row becomes the spec, at the end of the queue. A spec the enqueue already found the engine
  // cannot run arrives as lead-run with the reason.
  function onEnqueue(row) {
    const p = parse(row.payload) || {};
    if (!row.spec) return { drop: "no spec" };
    if (get("specs", row.spec)) return { drop: "spec already added" };
    // a row of an earlier queue whose `engine start` failed (the lead ran that queue itself): the newest enqueue row names the live batch
    const newest = db.prepare("SELECT payload FROM inbox WHERE kind='enqueue' ORDER BY id DESC LIMIT 1").get();
    const live = newest ? (parse(newest.payload) || {}).batch : undefined;
    if (live !== undefined && p.batch !== live) return { drop: "stale batch" };
    const or = (v) => (v === undefined ? null : v);
    const runner = p.runner === "lead" ? "lead" : "engine";
    const spec = specRow({ id: row.spec, position: db.prepare("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM specs").get().p, runner,
      integration: p.integration || "keep", push: p.push ? 1 : 0, batch: or(p.batch), gate: or(p.gate), worktree: or(p.worktree), branch: or(p.branch),
      plan: or(p.plan), backend: opts.backendKind || "claude-tmux", budget_attempts: or(p.budget_attempts), budget_tokens: or(p.budget_tokens) });
    emit("spec_added", { spec: spec.id, rows: [["specs", spec]], runner, queued: true, text: spec.id });
    if (p.reason) emit("handed_to_lead", { spec: spec.id, reason: p.reason, text: p.reason });
    return undefined;
  }

  // `engine done`: the lead finished its spec. The lead recorded its own metrics and ledger; the engine only ends the turn.
  function onDone(row) {
    const spec = row.spec ? get("specs", row.spec) : null;
    if (!spec || spec.runner !== "lead" || spec.state !== "running") return { drop: "no lead turn open" };
    const outcome = String((parse(row.payload) || {}).outcome);
    emit(realIntegrate.isFailure(outcome) ? "fail_spec" : "spec_done", { spec: spec.id, rows: [["specs", { ...spec, state: "done", outcome, updated_at: now() }]],
      outcome, by: "lead", text: outcome });
    return undefined;
  }

  // A drained `approval` row (spec 13): the hook denied a stop-class call of a running job. The job is marked held and
  // the spec parks with the exact call; what the answer needs (the job and the call) is stored with the park.
  function onHold(row) {
    const p = parse(row.payload) || {};
    const id = p.hold_id || row.source_id;
    const job = row.job ? get("jobs", row.job) : null;
    const spec = job ? get("specs", job.spec) : row.spec ? get("specs", row.spec) : null;
    if (spec && spec.state === "done") return { drop: "spec done" };
    if (!job || !spec || job.state !== "running") return { drop: "job not running" };
    const question = hold.question(p.tool, p.input);
    const d = detailOf(job);
    // A7: one open question per spec, and one hold per job (its worker was told to stop after the first)
    const why = d.held ? "job already held" : spec.state === "awaiting_you" || inbox.openWaitFor(db, spec.id) ? "spec already waiting" : null;
    if (why) {
      emit("hold_skipped", { spec: spec.id, job: job.id, hold: id, reason: why, question, text: `${why}: ${question}` });
      return { drop: why };
    }
    emit("held", { spec: spec.id, job: job.id, rows: [["jobs", withDetail({ ...job, session_id: p.session_id || job.session_id }, { ...d, held: id })]],
      hold: id, tool: p.tool, rule: p.rule, call_hash: p.call_hash, text: question });
    park(spec, question, `core:hold:${id}`, { kind: "stop_class", options: "approve|deny|fail", job: job.id, hold: id,
      stored: { job: job.id, tool: p.tool, input: p.input === undefined ? null : p.input, call_hash: p.call_hash } });
    return undefined;
  }

  function handler(row) {
    if (produced) throw STOP; // one undecided input at a time: pump before the next row
    if (row.source === "approval") return onHold(row);
    if (row.source === "schedule") return schedule.handleRow(db, row, { project, tmuxArgs: opts.tmuxArgs, now: now() });
    if (row.source === "worker") return onWorker(row);
    if (row.source === "timer") return onTimer(row);
    if (row.source === "user") {
      if (row.kind === "signal") return onSignal(row);
      if (row.kind === "enqueue") return onEnqueue(row);
      if (row.kind === "done") return onDone(row);
      return { drop: `unknown user row kind ${row.kind}` };
    }
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
    if (what === "hold" && d.answer !== "fail") { // approve: the pass, then the resume; deny: the resume with the note
      const h = d.stored || {};
      const resume = { type: "hold_resume", hold: id, job: h.job, answer: d.answer, note: d.note };
      return d.answer === "approve" ? [{ type: "hold_pass", hold: id, ...h, answered_at: d.answered_at }, resume] : [resume];
    }
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
    if (what === "budget") return id === "cap" ? [{ type: "extend_budget" }] : []; // an unknown cost: tokens stay null, the spec goes on
    return []; // integrate: its steps row is still at intent, so it runs again
  }

  // The strategy's commands for an input, plus the core's own: ledger lines, user gates, exhausted retry policies.
  function expand(spec, ev, cmds) {
    const d = ev.detail;
    const p = plan(spec);
    const out = [];
    if (ev.kind === "signal") {
      out.push({ type: "record_ruling", by: "user", cost_if_wrong: "the user's own call",
        text: `${d.answer}${d.note ? ` (${d.note})` : ""}: ${d.question}`,
        kind: d.kind, recommended: d.recommendation ? d.recommendation.option : null, answer: d.answer, answered_at: d.answered_at,
        followed: !!d.recommendation && d.answer === d.recommendation.option }, { type: "metrics_ask", wait: d.wait });
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
        out.push({ type: "park", question: `user gate: task ${c.task} ${p.byN.get(c.task).subject}`, step: `core:gate:${c.task}`, stored: c, kind: "user_gate" });
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
      if (d.on_exhausted === "park") out.push({ type: "park", question: what, step: `core:exhausted:${job.id}`, kind: "architect_park", recommendation: policy.SITE_RECS.exhausted });
      if (d.on_exhausted === "fail_spec") out.push(done(`failed — ${label(job)}: ${d.reason}`));
    }
    // 8b: a finished job whose cost cannot be measured parks the spec (only a finished job; a failed attempt is a lower bound)
    if ((ev.kind === "job_done" || ev.kind === "architect_decision") && d.tokens_missing && !out.some((c) => c.type === "set_state" && c.state === "done")) {
      const id = ev.kind === "job_done" ? ev.job : d.architect_job;
      out.push({ type: "park", question: `cost unknown for job ${id}`, step: `core:budget:unknown:${id}`, kind: "budget", recommendation: policy.SITE_RECS.cost_unknown });
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
      if (!park(spec, c.question, c.step, { options: c.options, stored: c.stored, kind: c.kind, recommendation: c.recommendation || policy.SITE_RECS[c.site], ...tag })) emit("park_skipped", { ...base, question: c.question, step: c.step });
    } else if (c.type === "escalate") {
      applyEscalate(spec, c, base);
    } else if (c.type === "record_ruling") {
      emit("ruling", { ...base, text: c.text, cost_if_wrong: c.cost_if_wrong, by: c.by,
        ...(c.by === "user" ? { kind: c.kind, recommended: c.recommended, answer: c.answer, followed: c.followed, answered_at: c.answered_at } : {}) });
    } else if (c.type === "metrics_ask") {
      metricsAsk(spec, c, base);
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
        { ...detailOf(old), try: 1, deadline: undefined, dl: undefined, nudged_at: undefined, told_at: undefined, reserved: undefined });
      emit("job_created", { ...base, job: job.id, rows: [["jobs", job]], task: old.task === null ? undefined : old.task, tier: job.tier, retry_of: old.id });
    } else if (c.type === "extend_budget") {
      const cur = get("specs", spec.id);
      const caps = capsOf(cur);
      const hit = reachedOf(cur);
      const next = { attempts: hit.attempts ? Math.ceil(caps.attempts * 1.5) : caps.attempts, tokens: hit.tokens ? Math.ceil(caps.tokens * 1.5) : caps.tokens };
      emit("budget_extended", { ...base, rows: [["specs", { ...cur, budget_attempts: next.attempts, budget_tokens: next.tokens, updated_at: t }]],
        attempts: next.attempts, tokens: next.tokens, text: `budget extended: attempts ${next.attempts}, tokens ${next.tokens}` });
    } else if (c.type === "hold_pass") {
      // the one-time pass (spec 13): hold.js finds it by call hash and spec, sets used_at and allows the call once
      const row = { hold_id: c.hold, spec: spec.id, job: c.job === undefined ? null : c.job, call_hash: c.call_hash === undefined ? null : c.call_hash,
        tool: c.tool === undefined ? null : c.tool, input: JSON.stringify(c.input === undefined ? null : c.input), created_at: t,
        expires_at: (c.answered_at === undefined || c.answered_at === null ? t : c.answered_at) + PASS_S, used_at: null };
      emit("hold_pass", { ...base, job: row.job, rows: [["holds", row]], hold: c.hold, expires_at: row.expires_at, text: `approval ${c.hold} granted` });
    } else if (c.type === "hold_resume") {
      // the job that goes on after a hold: the held job's kind, task, tier and model. dispatch() resumes the held
      // session with resume_text, or starts a fresh worker whose brief carries the held call and the answer.
      const old = c.job ? get("jobs", c.job) : null;
      if (!old) {
        emit("hold_resume_skipped", { ...base, hold: c.hold, text: `no held job for approval ${c.hold}` });
      } else {
        const note = c.note === null || c.note === undefined || String(c.note).trim() === "" ? "no reason given" : c.note;
        const text = c.answer === "approve" ? `approval ${c.hold} granted: retry the held call exactly as before`
          : `denied: ${note}. Continue without it, or report blocked.`;
        const job = newJob(spec, { kind: old.kind, task: old.task === null ? undefined : old.task, tier: old.tier, model: old.model },
          { ...detailOf(old), try: 1, deadline: undefined, dl: undefined, nudged_at: undefined, told_at: undefined, reserved: undefined, parked: undefined,
            resumed_at: undefined, held: undefined, resume_of: old.id, hold: c.hold, hold_answer: c.answer, resume_text: text });
        emit("job_created", { ...base, job: job.id, rows: [["jobs", job]], task: old.task === null ? undefined : old.task, tier: job.tier,
          resume_of: old.id, hold: c.hold, hold_answer: c.answer });
      }
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
      if (!park(spec, `unknown escalation case: ${c.case}`, "core:case", { kind: "architect_park", recommendation: policy.SITE_RECS.unknown_case, ...base })) emit("park_skipped", { ...base, case: c.case });
      return;
    }
    if (c.refusal) {
      const since = (lastEvent(spec.id, "signal") || { seq: 0 }).seq;
      const n = all("SELECT * FROM events WHERE spec=? AND kind='refused' AND seq>?", spec.id, since)
        .map((e) => parse(e.detail) || {}).filter((d) => d.case === c.case && d.target === c.job).length;
      if (n >= 2) {
        const question = `retry_higher_tier refused twice for ${c.job === undefined ? c.case : c.job}`;
        if (!park(spec, question, `core:refused:${c.case}`, { stored: c, kind: "architect_park", recommendation: policy.SITE_RECS.refused, ...base })) emit("park_skipped", { ...base, question });
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
    for (const s of all(`SELECT id FROM specs WHERE state!='queued' AND ${NOT_LEAD} ORDER BY position, created_at`)) {
      if (waitsForUnpark(get("specs", s.id))) continue; // no job of a spec without the turn is created
      if (await pump(s.id)) any = true;
    }
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
      if (res.outcome === "parked") { park(get("specs", spec.id), res.question, "core:integrate", { kind: "stop_class", recommendation: res.recommendation }); return; }
      emit("integrated", { spec: spec.id, rows: [finished(res)], outcome: res.outcome, merge: res.merge, text: String(res.outcome) });
    }
  }

  async function advance() {
    for (let moved = true; moved;) {
      moved = await pumpAll();
      for (const s of all(`SELECT * FROM specs WHERE state NOT IN ('queued','done','awaiting_you') AND ${NOT_LEAD} ORDER BY position, created_at`)) {
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
    if (d.hold) { // a fresh worker after a hold whose session could not be resumed (spec 13)
      const prev = d.resume_of ? get("jobs", d.resume_of) : null;
      const asked = db.prepare("SELECT question FROM waits WHERE step=? ORDER BY asked_at DESC LIMIT 1").get(`core:hold:${d.hold}`);
      out.push("## Held call", "", `The earlier worker on this job was stopped at a call that needed the user's approval (${d.hold}).`, "",
        `Earlier report: ${prev && prev.report ? prev.report : "(none)"}`, `Call: ${asked ? asked.question : "(unknown)"}`,
        `Answer: ${d.hold_answer === "approve" ? "approved: retry the held call exactly as before" : d.resume_text}`, "");
    }
    out.push(reportSection(reportPath, reviewer));
    return out.join("\n");
  }

  // The report contract of one job: the fresh brief and every resume text of that job say it in these words.
  function reportSection(reportPath, reviewer) {
    return ["## Report", "", `Report file: ${reportPath}`, "", "Write your report there. Its last fenced block must be:", "",
      "```json:status", reviewer ? STATUS_SHAPES.reviewer : STATUS_SHAPES.worker, "```", ""].join("\n");
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
    // concurrency 1 for the spec that holds the turn; a parked spec's worker still at its prompt does not block the next spec (A3)
    if (db.prepare("SELECT 1 FROM jobs j JOIN specs s ON s.id=j.spec WHERE j.state='running' AND s.state!='awaiting_you' LIMIT 1").get()) return;
    const job = db.prepare(`SELECT j.* FROM jobs j JOIN specs s ON s.id=j.spec WHERE j.state='pending' AND s.state NOT IN ('queued','done','awaiting_you') AND ${NOT_LEAD.replace("runner", "s.runner")} ORDER BY j.rowid LIMIT 1`).get();
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
    if (!d.reserved) { // 8b: a job reserves one attempt, once; a job that already did (a crash after the reserve) does not again
      const hit = reachedOf(spec);
      if (hit.attempts || hit.tokens) {
        const c = capsOf(spec);
        park(spec, `budget reached: attempts ${spec.spent_attempts || 0}/${c.attempts}, tokens ${spec.spent_tokens || 0}/${c.tokens}`, "core:budget:cap",
          { kind: "budget", options: "approve|fail", recommendation: capRecommendation(spec) });
        return;
      }
      emit("budget_reserve", { spec: spec.id, job: job.id, attempt: job.attempt, rows: [["specs", { ...spec, spent_attempts: (spec.spent_attempts || 0) + 1 }],
        ["jobs", withDetail(job, { ...d, reserved: true })]], text: `attempt ${(spec.spent_attempts || 0) + 1}/${capsOf(spec).attempts}: ${job.id}` });
      d.reserved = true; // the rows written below carry the detail on
      job.detail = JSON.stringify(d);
    }
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
      const fresh = { id: ready.id, kind: ready.kind, task: ready.task, model: ready.model, effort: ready.effort,
        brief: ready.brief, report: ready.report, worktree: wt, window: ready.window };
      // fix rounds and answered holds resume the worker's own session when it can be resumed; the session is told the
      // brief, or after a hold the answer alone. The new job goes along (A6): the window gets its ENGINE_JOB.
      if (prev && prev.pane && prev.session_id) {
        try { handle = await backend.resume(handleOf(prev), d.hold ? `${d.resume_text}\n\n${reportSection(ready.report, ["review", "re_review", "final_review"].includes(job.kind))}` : text, fresh); how = "resume"; } catch (_) { handle = null; }
      }
      if (!handle) handle = await backend.start(fresh);
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

  // One `ask` metrics line per user answer (spec 8a). The step row makes a replay run the command once; a failed
  // command is a failed step and the spec goes on. The ask_recorded event always follows (the pump's one command, one event).
  function metricsAsk(spec, c, base) {
    const w = get("waits", c.wait);
    const rec = (w && parse(w.recommendation)) || {};
    const iso = (s) => new Date(s * 1000).toISOString();
    const json = { spec: spec.id, batch: spec.batch === undefined ? null : spec.batch, kind: w ? w.kind : null, recommended: rec.option === undefined ? null : rec.option,
      confidence: rec.confidence === undefined ? null : rec.confidence, answer: w ? w.answer : null,
      followed: !!w && rec.option !== undefined && w.answer === rec.option, asked_at: w ? iso(w.asked_at) : null, answered_at: w && w.answered_at ? iso(w.answered_at) : null };
    let ok = true;
    try {
      steps.run(db, { key: `metrics_ask:${c.wait}`, spec: spec.id, kind: "metrics_ask", facts: { wait: c.wait } }, () => {
        const hasBatch = spec.batch !== null && spec.batch !== undefined && spec.batch !== "";
        const r = cp.spawnSync(tmuxCtl, ["metrics", "append", "ask", "--json", JSON.stringify(json), ...(hasBatch ? ["--batch", String(spec.batch)] : [])],
          { cwd: repo, env, encoding: "utf8", timeout: 60000 });
        if (r.error || r.status !== 0) throw new Error(`metrics append ask: ${(r.stderr || (r.error && r.error.message) || "").trim().split("\n")[0]}`);
        return { wait: c.wait };
      }, { now });
    } catch (_) { ok = false; /* recorded as a failed step */ }
    emit("ask_recorded", { ...base, wait: c.wait, ok });
  }

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

  // The gate of a lead-run spec (spec section 6): `metrics gate <id>`, once, as a step; its answer is the gate_result event.
  function gateOf(spec) {
    const have = lastEvent(spec.id, "gate_result");
    if (have) return have.detail;
    const res = steps.run(db, { key: `gate:${spec.id}`, spec: spec.id, kind: "gate", facts: { gate: spec.gate } }, () => {
      const r = cp.spawnSync(tmuxCtl, ["metrics", "gate", String(spec.gate)], { cwd: repo, env, encoding: "utf8", timeout: 120000 });
      const line = `${r.stdout || ""}\n${r.stderr || ""}\n${(r.error && r.error.message) || ""}`.split("\n").map((l) => l.trim()).find(Boolean) || "";
      return { gate: spec.gate, rc: r.error || r.status === null ? -1 : r.status, line };
    }, { now }).result;
    emit("gate_result", { spec: spec.id, gate: res.gate, rc: res.rc, line: res.line, text: `gate ${res.gate}: exit ${res.rc}` });
    return res;
  }

  // A lead-run spec at its turn: its gate first, then the lead_turn the lead line is derived from. The spec is then
  // `running` with no policy version, and the engine waits for the `done` row (R7).
  function leadTurn(spec) {
    if (spec.gate !== null && spec.gate !== undefined && spec.gate !== "") {
      const g = gateOf(spec);
      if (g.rc !== 0) {
        const outcome = `failed — gate ${g.gate}: ${g.line}`;
        if (spec.batch !== null && spec.batch !== undefined && spec.batch !== "") { // measurement never blocks: a failed record is a failed step
          try {
            steps.run(db, { key: `metrics_record:${spec.id}`, spec: spec.id, kind: "metrics_record", facts: { spec: spec.id, batch: spec.batch } }, () => {
              const r = cp.spawnSync(tmuxCtl, realIntegrate.metricsRecordArgv({ db, repo }, spec, outcome), { cwd: repo, env, encoding: "utf8", timeout: 60000 });
              if (r.error || r.status !== 0) throw new Error(`metrics record: ${(r.stderr || (r.error && r.error.message) || "").trim().split("\n")[0]}`);
              return { spec: spec.id, batch: spec.batch, outcome };
            }, { now });
          } catch (_) { /* recorded as a failed step */ }
        }
        emit("fail_spec", { spec: spec.id, rows: [["specs", { ...spec, state: "done", outcome, updated_at: now() }]], outcome, text: outcome });
        return;
      }
    }
    emit("lead_turn", { spec: spec.id, rows: [["specs", { ...spec, state: "running", updated_at: now() }]], text: spec.id });
  }

  // The turn: at most one spec is past `queued` and not parked or done. When none is, an answered parked spec gets it
  // first (oldest answer first), then the next queued spec by position.
  function startQueued() {
    if (holder()) return;
    const held = heldSpecs()[0];
    if (held) {
      if (ENDED_AT_PROMPT.includes(held.wait.answer)) {
        const prev = (lastEvent(held.spec.id, "awaiting_you") || { detail: {} }).detail.prev_state || "running";
        emit("unparked", { spec: held.spec.id, rows: [["specs", { ...held.spec, state: prev, outcome: null, updated_at: now() }]], answer: held.wait.answer, text: held.wait.answer });
      } else {
        writeSignal(held.spec, held.wait);
      }
      return;
    }
    const spec = db.prepare("SELECT * FROM specs WHERE state='queued' ORDER BY position, created_at LIMIT 1").get();
    if (!spec) return;
    if (spec.runner === "lead") { leadTurn(spec); return; }
    const added = lastEvent(spec.id, "spec_added");
    if (added && added.detail.queued) { // a queue's spec whose plan no longer compiles is handed to the lead; its turn comes on the next tick
      try { plan(spec); } catch (e) {
        const reason = String((e && e.message) || e);
        emit("handed_to_lead", { spec: spec.id, rows: [["specs", { ...spec, runner: "lead", updated_at: now() }]], reason, text: reason });
        return;
      }
    }
    plan(spec); // a plan the engine cannot compile is an error before anything starts
    metricsStart(spec); // not for a lead-run spec: the lead runs its own (R17)
    const t = now();
    emit("spec_started", { spec: spec.id, rows: [["specs", { ...spec, state: "running", policy_version: policy.POLICY_VERSION, policy_hash: hash, updated_at: t }], ...retryRows()],
      text: spec.id });
  }

  // ---- the end of the queue (spec section 11) ----

  // Nothing is runnable: no spec holds the turn (an open lead turn does), none is queued, no parked spec has an answer
  // waiting and the inbox is empty.
  const atEnd = () => !holder() && !db.prepare("SELECT 1 FROM specs WHERE state='queued' LIMIT 1").get() && !heldSpecs().length
    && !db.prepare("SELECT 1 FROM inbox WHERE state='new' LIMIT 1").get();
  const queueOpen = () => {
    const fin = db.prepare("SELECT MAX(seq) AS s FROM events WHERE kind='queue_finished'").get().s || 0;
    return !!db.prepare("SELECT 1 FROM events WHERE kind='spec_added' AND seq>? AND json_extract(detail, '$.queued')=1 LIMIT 1").get(fin);
  };

  // A spec still parked at the end is completed as failed, but its state, wait, worktree and windows stay: a later
  // signal resumes it, and finalize records it again (R6: this record is its own step kind, with no check).
  function failParked() {
    for (const spec of all(`SELECT * FROM specs WHERE state='awaiting_you' AND outcome IS NULL AND ${NOT_LEAD} ORDER BY position, created_at`)) {
      const wait = inbox.openWaitFor(db, spec.id);
      if (!wait) continue;
      const outcome = `failed — awaiting you: ${wait.question}`;
      if (spec.batch !== null && spec.batch !== undefined && spec.batch !== "") {
        try {
          steps.run(db, { key: `metrics_record:${spec.id}:parked:${wait.id}`, spec: spec.id, kind: "metrics_record_parked", facts: { spec: spec.id, batch: spec.batch } }, () => {
            const r = cp.spawnSync(tmuxCtl, realIntegrate.metricsRecordArgv({ db, repo }, spec, outcome), { cwd: repo, env, encoding: "utf8", timeout: 60000 });
            if (r.error || r.status !== 0) throw new Error(`metrics record: ${(r.stderr || (r.error && r.error.message) || "").trim().split("\n")[0]}`);
            return { spec: spec.id, batch: spec.batch, outcome };
          }, { now });
        } catch (_) { /* recorded as a failed step */ }
      }
      emit("parked_failed", { spec: spec.id, rows: [["specs", { ...spec, outcome, updated_at: now() }]], question: wait.question, outcome, text: outcome });
    }
  }

  // The report hook is a step keyed per queue end, and never blocks it: a failure is a report_failed event and a
  // queue_finished with no report. A step left at intent runs the hook again (queue.reportHooks gives no reportPath, so the
  // check answers not_done; a hook with a reportPath whose file exists would be taken as done), and the hook must be idempotent.
  async function queueReport() {
    if (!opts.report) return null;
    const fin = db.prepare("SELECT MAX(seq) AS s FROM events WHERE kind='queue_finished'").get().s || 0;
    const key = `queue_report:${fin}`;
    const have = steps.getRow(db, key);
    if (have && have.state === "done") return (parse(have.result) || {}).path || null;
    const ctx = { db, repo, project, tmuxCtl, env, now };
    const desc = { key, spec: null, kind: "queue_report" };
    try {
      steps.begin(db, { ...desc, facts: { path: typeof opts.reportPath === "function" ? opts.reportPath(ctx) : null } }, { now });
      const out = await opts.report(ctx);
      const p = typeof out === "string" && out ? out : null;
      steps.finish(db, desc, { path: p }, { now });
      return p;
    } catch (e) {
      const msg = String((e && e.message) || e).split("\n")[0];
      try { steps.fail(db, steps.getRow(db, key) || desc, msg, { now }); } catch (_) { /* the event below is the record */ }
      emit("report_failed", { error: msg, text: `report failed: ${msg}` });
      return null;
    }
  }

  function policyCheck() {
    for (const s of all(`SELECT * FROM specs WHERE state NOT IN ('queued','done','awaiting_you') AND policy_version IS NOT NULL AND ${NOT_LEAD}`)) {
      if (s.policy_version === policy.POLICY_VERSION && s.policy_hash === hash) continue;
      const tag = (v, h) => `${v}:${String(h).slice(0, 8)}`;
      park(s, `engine rules changed (${tag(s.policy_version, s.policy_hash)}→${tag(policy.POLICY_VERSION, hash)}): continue under the new rules?`, "core:policy", { kind: "policy_change" });
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
      const row = specRow(s);
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
        endHeldWithReport();
        await advance();
        // scheduled runs are not jobs: their windows open and their ends are recorded here, and neither waits for the command
        const sctx = { project, tmuxArgs: opts.tmuxArgs, now: now() };
        schedule.runIntents(db, sctx);
        schedule.finishRuns(db, sctx);
        await closeWindows();
        await dispatch();
      } catch (e) {
        fail(e);
      } finally {
        if (!stopped) flush();
      }
    },

    // The end of the queue, when nothing is runnable (else false): parked specs are failed with their waits kept, and
    // an open queue gets its report (opts.report) and its queue_finished. A queue that already has one gets no second.
    async finish() {
      if (halted || stopped) return false;
      try {
        if (!atEnd()) return false;
        failParked();
        if (queueOpen()) {
          const report = await queueReport();
          emit("queue_finished", { report, text: report || "no report" });
        }
        return true;
      } catch (e) {
        fail(e);
        return false;
      } finally {
        if (!stopped) flush();
      }
    },

    // The pause between two ticks.
    wait: () => sleep(opts.tickMs === undefined ? TICK_S * 1000 : opts.tickMs),

    // Runs one spec to its outcome in the foreground; a parked spec keeps the engine ticking until it is answered.
    async run(specId) {
      for (;;) {
        await E.tick();
        const s = get("specs", specId);
        if (s && s.state === "done") return s.outcome;
        if (halted) throw new Error(`engine stopped: ${halted}`);
        await E.wait();
      }
    },

    // Recovery (spec section 9), before the first tick of a restarted engine: reconcile intent steps, then look at
    // every job marked running. The ticks that follow fire due timers, drain the inbox and compare the policy.
    async resume() {
      try {
        const rec = steps.reconcile(db, opts.stepsCtx || { repo, mainRepo: repo, tmuxCtl, session: opts.session, tmuxArgs: opts.tmuxArgs, project }, { now });
        for (const r of rec.rerun) {
          const sp = r.kind === "metrics_start" && r.spec ? get("specs", r.spec) : null;
          if (sp) metricsStart(sp); // the start never ran
          if (r.kind === "plist_remove") require("./launchd").rerunPlistRemove(db, r); // the unlink never ran
        }
        for (const p of rec.park) {
          const s = get("steps", p.key);
          if (s && NEVER_PARK.includes(s.kind)) { // measurement and notices never park: the unknown row is failed
            steps.fail(db, s, `could not tell whether ${s.key} ran`, { now });
            continue;
          }
          if (!s || MY_STEPS.includes(s.kind) || s.kind === "gate" || !s.spec) continue; // the core's own rows are simply run again
          const spec = get("specs", s.spec);
          if (spec && spec.state !== "done") park(spec, p.question, `core:step:${p.key}`, { kind: "cannot_tell" });
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

module.exports = { start, takeLock, contextTokens, fixStats, tapReset, TICK_S, HEARTBEAT_S, NO_PROGRESS_S, NUDGE_GRACE_S, TOOL_LIMIT_S, NEEDS_YOU_PARK_S };
