"use strict";

// The spec-driven strategy (spec section 3, steps 1-6, and the strategy side of sections 4 and 10.2).
//
// decide(state, event) -> command[] is pure: no I/O, no clock, nothing kept between calls. It replays
// state.events (the spec's history) through the same step function that handles the new event, on a model
// built fresh for the call. Every counter (reds per task, fix rounds per task, failures per job kind and task,
// retry_higher_tier used per job kind and task) is therefore derived from the events alone. state.jobs is read
// only to look a job id up (its kind, task and tier).
//
// What the core supplies (Task 8):
// - event: an events row, {seq, kind, job, detail: {...fields}}; the flat form {type, ...fields} is read too.
// - state.events: every earlier input event of this spec as a row with the same kind and its fields in detail.
//   Rows of other kinds are ignored. A row with the new event's own seq is skipped.
// - state.retry[kind]: the loaded retryFor row for bounce, fix_round and each job kind.
// - job_done of a fix job: fix_stats {lines, files, added, tests_removed} for FIX_BASE..HEAD of the round.

const BOUNCE_MAX_LINES = 60; // cap of the bounce text, in lines (E2); bounce.js imports it

const BATCH_MAX = 5;
const BATCH_EXCLUDE = /(^|\/)(\.gitlab-ci|\.github\/|\.agent-ci|ci\/|migrations?\/|security|auth|settings(\.local)?\.json|config\/|\.env)/i;
const RESUME_FIX_ROUNDS = 3; // fix rounds 1 to 3 resume the worker's session; later rounds get a fresh worker
const SMALL_FIX = { lines: 20, files: 2, added: 0, tests_removed: 0 }; // subagent-driven-development-extras, lever 2

const TIERS = ["mechanical", "standard", "frontier"];
const CASES = ["fix_rounds_exhausted", "blocked", "verify_red", "residual_findings", "tests_red_after_merge", "failed_twice"];
const BLOCKING = ["critical", "important"];
const WORKERS = ["refresh", "implement", "fix", "fix_wave"];
const VERDICTS = ["review", "re_review", "final_review"];
const RETRY_ALIAS = { fix_wave: "fix", re_review: "final_review" }; // kinds without a row of their own in 10.2
const TESTS_RED_BEFORE = "project tests are red before the merge";

// ---- commands ------------------------------------------------------------------------------------------------------

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null));
const startJob = (fields) => clean({ type: "start_job", ...fields });
const escalate = (kase, job, task) => clean({ type: "escalate", case: kase, job, task });
const deferred = (text, task) => clean({ type: "log", kind: "deferred", text, task });
const done = (outcome) => ({ type: "set_state", state: "done", outcome });
const integrate = () => [{ type: "set_state", state: "integrating" }, { type: "request_integrate" }];

// ---- the model -----------------------------------------------------------------------------------------------------

const tierOf = (task) => (TIERS.includes(task.tier) ? task.tier : "standard");

// A task may join a review batch: mechanical, and none of its files is CI, security, migration or shared config.
function batchable(task) {
  return task.tier === "mechanical" && !(task.files || []).some((f) => BATCH_EXCLUDE.test(f));
}

function newModel(state) {
  const tasks = new Map();
  for (const task of state.tasks || []) {
    tasks.set(task.n, {
      n: task.n, plan: task,
      tier: tierOf(task), // the tier its implement and fix jobs run on; retry_higher_tier raises it
      started: false, held: false, reviewed: false, passed: false,
      open: null, // blocking findings waiting for (or in) a fix round
      reds: 0, lastRed: "", rounds: 0, fixStats: null,
      fresh: false, session: undefined, // session = the job whose session a bounce or a fix round resumes
      lastJob: undefined, lastFix: undefined,
    });
  }
  return {
    state, tasks,
    failures: {}, failReason: {}, tierUsed: new Set(),
    wave: [], residual: [], waveJob: undefined,
    ruling: "", blocked: "",
  };
}

const all = (ctx) => [...ctx.tasks.values()];
const jobRow = (ctx, id) => (id === undefined ? undefined : (ctx.state.jobs || []).find((j) => j.id === id));
const keyOf = (kind, task) => `${kind}:${task === undefined ? "" : task}`;
const opt = (v) => (v === null ? undefined : v);

function policy(ctx, kind) {
  const retry = ctx.state.retry || {};
  const row = retry[kind] || retry[RETRY_ALIAS[kind]];
  if (!row || !Number.isInteger(row.max_attempts)) throw new Error(`spec_driven: state.retry.${kind} is missing`);
  return row;
}

function isSmall(s) {
  return !!s && ["lines", "files", "added", "tests_removed"].every((k) => Number.isInteger(s[k])) &&
    s.lines <= SMALL_FIX.lines && s.files <= SMALL_FIX.files && s.added <= SMALL_FIX.added &&
    s.tests_removed <= SMALL_FIX.tests_removed;
}

// ---- the graph -----------------------------------------------------------------------------------------------------

// Nothing is in flight: pick the next job. Open findings first (lowest task), then the held batch, then the
// next task, then the final review.
function advance(ctx) {
  const tasks = all(ctx);
  const open = tasks.find((t) => t.open);
  if (open) return fixRound(ctx, open);
  const held = tasks.filter((t) => t.held);
  const next = tasks.find((t) => !t.started);
  if (held.length) {
    const grows = next && held.length < BATCH_MAX && held.every((t) => batchable(t.plan)) && batchable(next.plan);
    if (!grows) {
      return [held.length === 1
        ? startJob({ kind: "review", task: held[0].n, tier: "standard" })
        : startJob({ kind: "review", tier: "standard", tasks: held.map((t) => t.n) })];
    }
  }
  if (next) {
    next.started = true;
    next.fresh = true;
    return [startJob({ kind: "implement", task: next.n, tier: next.tier })];
  }
  if (tasks.every((t) => t.passed)) {
    return [{ type: "set_state", state: "final_review" }, startJob({ kind: "final_review", tier: "frontier" })];
  }
  return [];
}

function fixRound(ctx, t) {
  if (t.rounds > policy(ctx, "fix_round").max_attempts) return [escalate("fix_rounds_exhausted", t.lastFix, t.n)];
  const resume = t.rounds <= RESUME_FIX_ROUNDS ? t.session : undefined;
  if (resume === undefined) t.fresh = true;
  return [startJob({ kind: "fix", task: t.n, tier: t.tier, round: t.rounds, findings: t.open, resume_of: resume })];
}

// The task's check is green: its first review (alone or in a batch), or the re-review of a fix.
function afterGreen(ctx, t) {
  if (t.reviewed) {
    const tier = t.plan.tier === "mechanical" && isSmall(t.fixStats) ? "mechanical" : "standard";
    return [startJob({ kind: "review", task: t.n, tier })];
  }
  t.held = true;
  return advance(ctx);
}

// The tasks a review job's verdict speaks for: a re-review covers its one task, a first review every held task.
function covered(ctx, task) {
  const t = ctx.tasks.get(task);
  if (t && t.reviewed) return [t];
  const held = all(ctx).filter((x) => x.held);
  if (t && !held.includes(t)) return [t];
  return held;
}

// A worker job (refresh, implement, fix, fix_wave) ended with status done.
function afterWorker(ctx, kind, task) {
  if (kind === "refresh") return advance(ctx);
  if (kind === "fix_wave") return [startJob({ kind: "re_review", tier: "frontier", findings: ctx.wave })];
  return ctx.tasks.has(task) ? [{ type: "run_check", task }] : [];
}

// A reviewer job (review, final_review, re_review) ended with a verdict.
function afterVerdict(ctx, kind, task, status) {
  const findings = Array.isArray(status.findings) ? status.findings : [];
  const blocking = findings.filter((f) => BLOCKING.includes(f.severity));
  const minors = findings.filter((f) => !BLOCKING.includes(f.severity));
  if (kind === "review") {
    const tasks = covered(ctx, task);
    if (!tasks.length) return [];
    const owner = (f) => tasks.find((t) => t.n === f.task) || tasks[0];
    const out = minors.map((f) => deferred(f.text, owner(f).n));
    for (const t of tasks) {
      const mine = blocking.filter((f) => owner(f) === t);
      t.held = false;
      t.reviewed = true;
      t.fixStats = null;
      t.open = mine.length ? mine : null;
      t.passed = !mine.length;
      if (mine.length) t.rounds += 1;
    }
    return out.concat(advance(ctx));
  }
  const out = minors.map((f) => deferred(f.text, f.task));
  if (!blocking.length) return out.concat(integrate());
  if (kind === "final_review") {
    ctx.wave = blocking;
    const tier = blocking.map((f) => ctx.tasks.get(f.task)).filter(Boolean)
      .reduce((top, t) => (TIERS.indexOf(t.tier) > TIERS.indexOf(top) ? t.tier : top), "standard");
    return out.concat([startJob({ kind: "fix_wave", tier, findings: blocking })]);
  }
  ctx.residual = blocking;
  return out.concat([escalate("residual_findings", ctx.waveJob)]);
}

// ---- event handlers ------------------------------------------------------------------------------------------------

function onJobDone(ctx, d, job) {
  const row = jobRow(ctx, job) || {};
  const kind = d.kind || row.kind;
  const task = opt(d.task === undefined ? row.task : d.task);
  const status = d.status || {};
  delete ctx.failures[keyOf(kind, task)];
  if (VERDICTS.includes(kind)) return afterVerdict(ctx, kind, task, status);
  if (!WORKERS.includes(kind)) return [];
  const t = ctx.tasks.get(task);
  if (t && (kind === "implement" || kind === "fix")) {
    t.lastJob = job;
    if (kind === "fix") t.lastFix = job;
    if (t.fresh) { t.session = job; t.fresh = false; }
  }
  if (kind === "fix_wave") ctx.waveJob = job;
  if (status.status === "blocked") {
    ctx.blocked = (status.concerns || []).join("; ");
    return [escalate("blocked", job, task)];
  }
  if (t && kind === "fix") t.fixStats = d.fix_stats || status.fix_stats || null;
  return afterWorker(ctx, kind, task);
}

function onJobFailed(ctx, d, job) {
  const row = jobRow(ctx, job) || {};
  const kind = d.kind || row.kind;
  const task = opt(d.task === undefined ? row.task : d.task);
  const p = policy(ctx, kind);
  const architect = p.on_exhausted === "architect"; // park and fail_spec are applied by the core
  if (d.reason === "model_limit") return []; // retried by the core outside the count
  if ((p.no_retry_on || []).includes(d.reason)) {
    return d.reason === "blocked" && architect ? [escalate("blocked", job, task)] : [];
  }
  const key = keyOf(kind, task);
  const n = ctx.failures[key] = (ctx.failures[key] || 0) + 1;
  ctx.failReason[key] = d.reason;
  return n >= p.max_attempts && architect ? [escalate("failed_twice", job, task)] : [];
}

function onCheck(ctx, d) {
  const t = ctx.tasks.get(d.task);
  if (!t) return [];
  if (d.ok) {
    t.reds = 0;
    return afterGreen(ctx, t);
  }
  t.reds += 1;
  t.lastRed = d.text === undefined || d.text === null ? "" : String(d.text);
  const max = policy(ctx, "bounce").max_attempts;
  if (t.reds >= max) return [escalate("verify_red", t.lastJob, t.n)];
  return [startJob({ kind: "fix", task: t.n, tier: t.tier, resume_of: t.session, findings: t.lastRed, bounce: t.reds })];
}

function onIntegrated(ctx, d) {
  if (d.outcome === "tests_red") return [escalate("tests_red_after_merge")];
  if (d.outcome === "tests_red_before") return [{ type: "park", question: TESTS_RED_BEFORE, step: "integrate", kind: "stop_class", site: "tests_red" }];
  return [done(d.outcome)];
}

// proceed: the finding is parked as a deferred log line and the spec goes on as if the failed step had passed.
function proceed(ctx, kase, row, task) {
  const t = ctx.tasks.get(task);
  const parked = (text, n) => deferred(`parked (${kase}): ${text}`, n);
  if (kase === "verify_red" && t) {
    t.reds = 0;
    return [parked(t.lastRed, t.n)].concat(afterGreen(ctx, t));
  }
  if (kase === "fix_rounds_exhausted" && t) {
    const out = (t.open || []).map((f) => parked(f.text, t.n));
    t.open = null;
    t.passed = true;
    return out.concat(advance(ctx));
  }
  if (kase === "blocked" && row && WORKERS.includes(row.kind)) {
    return [parked(`${row.kind} blocked: ${ctx.blocked}`, task)].concat(afterWorker(ctx, row.kind, task));
  }
  if (kase === "failed_twice" && row) {
    const out = [parked(`${row.kind} failed twice (${ctx.failReason[keyOf(row.kind, task)]})`, task)];
    if (VERDICTS.includes(row.kind)) return out.concat(afterVerdict(ctx, row.kind, task, { verdict: "pass", findings: [] }));
    return WORKERS.includes(row.kind) ? out.concat(afterWorker(ctx, row.kind, task)) : out;
  }
  if (kase === "residual_findings") {
    const out = ctx.residual.map((f) => parked(f.text, f.task));
    ctx.residual = [];
    return out.concat(integrate());
  }
  if (kase === "tests_red_after_merge") {
    return [parked("tests red after the merge"), done(`tests_red — proceed: ${ctx.ruling}`)];
  }
  return [];
}

// retry_higher_tier: the escalated job runs again one tier up, once per job kind and task; else it is refused
// and the case escalates again.
function retryHigher(ctx, kase, row, job, task) {
  const refuse = (why) => [clean({ type: "log", kind: "refused", text: `retry_higher_tier refused: ${why}`, task }), escalate(kase, job, task)];
  if (!row) return refuse("no job to re-run");
  const key = keyOf(row.kind, task);
  if (ctx.tierUsed.has(key)) return refuse(`already used for ${row.kind}${task === undefined ? "" : ` ${task}`}`);
  const up = TIERS.includes(row.tier) ? TIERS[TIERS.indexOf(row.tier) + 1] : undefined;
  if (!up) return refuse(`no tier above ${row.tier}`);
  ctx.tierUsed.add(key);
  const t = ctx.tasks.get(task);
  const cmd = { kind: row.kind, task, tier: up };
  if (t && (row.kind === "implement" || row.kind === "fix")) {
    if (row.kind === "fix") cmd.findings = t.reds > 0 ? t.lastRed : opt(t.open);
    t.reds = 0;
    t.tier = up;
    t.fresh = true; // a worker on another model is a new session
  }
  if (row.kind === "review") {
    const tasks = covered(ctx, task);
    if (tasks.length > 1) { cmd.task = undefined; cmd.tasks = tasks.map((x) => x.n); }
  }
  if (row.kind === "fix_wave") {
    cmd.findings = ctx.residual.length ? ctx.residual : ctx.wave;
    ctx.wave = cmd.findings;
  }
  return [startJob(cmd)];
}

function onArchitect(ctx, d, job) {
  const row = jobRow(ctx, job);
  const task = opt(d.task === undefined && row ? row.task : d.task);
  const out = [{ type: "record_ruling", text: d.ruling, cost_if_wrong: d.cost_if_wrong, by: "architect" }];
  ctx.ruling = d.ruling;
  if (row) delete ctx.failures[keyOf(row.kind, task)];
  if (d.decision === "proceed") return out.concat(proceed(ctx, d.case, row, task));
  if (d.decision === "retry_higher_tier") return out.concat(retryHigher(ctx, d.case, row, job, task));
  if (d.decision === "park") {
    const step = `architect:${d.case}:${task === undefined ? "" : task}:${job === undefined ? "" : job}`;
    return out.concat([{ type: "park", question: d.ruling, step, kind: "architect_park", ...(d.recommend ? { recommendation: d.recommend } : {}) }]);
  }
  if (d.decision === "fail_spec") return out.concat([done(`failed — ${d.ruling}`)]);
  return [];
}

// The user's answer to a wait this strategy opened (step "integrate" or "architect:<case>:<task>:<job>").
function onSignal(ctx, d) {
  const step = String(d.step === undefined || d.step === null ? "" : d.step);
  let question;
  let approve;
  if (step === "integrate") {
    question = TESTS_RED_BEFORE;
    approve = () => [{ type: "request_integrate" }];
  } else if (step.startsWith("architect:")) {
    const [, kase, n, ...rest] = step.split(":"); // a job id has colons of its own, so it comes last
    const job = rest.join(":") || undefined;
    question = ctx.ruling;
    approve = () => proceed(ctx, kase, jobRow(ctx, job), n === "" ? undefined : Number(n));
  } else {
    return [];
  }
  if (d.answer === "approve") return approve();
  if (d.answer === "deny") return [done(`denied: ${question}`)];
  if (d.answer === "fail") return [done(`failed — ${d.note === undefined || d.note === null ? "" : d.note}`)];
  return [];
}

const HANDLERS = {
  spec_started: () => [{ type: "run_check", check: "stale" }],
  stale_result: (ctx, d) => (d.stale ? [startJob({ kind: "refresh", tier: "frontier" })] : advance(ctx)),
  job_done: onJobDone,
  job_failed: onJobFailed,
  check_result: onCheck,
  architect_decision: onArchitect,
  integrated: onIntegrated,
  signal: onSignal,
};

// An events row {kind, job, detail} or a flat event {type, ...fields} -> {name, seq, d, job}.
function normalise(e) {
  const isRow = e.detail !== null && typeof e.detail === "object";
  const d = isRow ? e.detail : e;
  const job = d.job === undefined || d.job === null ? (isRow ? e.job : undefined) : d.job;
  return { name: isRow ? e.kind : e.type || e.kind, seq: e.seq, d, job: opt(job) };
}

function step(ctx, e) {
  const handler = Object.prototype.hasOwnProperty.call(HANDLERS, e.name) ? HANDLERS[e.name] : null;
  return handler ? handler(ctx, e.d, e.job) : [];
}

function decide(state, event) {
  const ctx = newModel(state);
  const cur = normalise(event);
  for (const row of state.events || []) {
    if (cur.seq !== undefined && cur.seq !== null && row.seq === cur.seq) continue;
    step(ctx, normalise(row));
  }
  return step(ctx, cur);
}

module.exports = { decide, batchable, BOUNCE_MAX_LINES, BATCH_MAX, BATCH_EXCLUDE, RESUME_FIX_ROUNDS, SMALL_FIX, TIERS, CASES };
