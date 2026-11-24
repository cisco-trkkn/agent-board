"use strict";
// Side-effect journal (spec 10.4): every action outside the database is a `steps` row.
// intent (committed) -> act -> done | failed. On resume, reconcile() runs each intent row's check.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const { tx, put, event } = require("./db");

const nowOf = (now) => (typeof now === "function" ? now() : typeof now === "number" ? now : Date.now() / 1000);
const parse = (s) => {
  if (s === null || s === undefined) return null;
  try { return JSON.parse(s); } catch (_) { return null; }
};
const hydrate = (row) => (row ? { ...row, result: parse(row.result) } : row);
const getRow = (db, key) => hydrate(db.prepare("SELECT * FROM steps WHERE key=?").get(key));

function write(db, { key, spec, kind }, state, result, t, evKind, extra = {}) {
  return tx(db, () => {
    const old = db.prepare("SELECT created_at FROM steps WHERE key=?").get(key);
    const row = put(db, "steps", {
      key, spec: spec === undefined ? null : spec, kind, state,
      result: result === undefined ? null : JSON.stringify(result),
      created_at: old ? old.created_at : t, updated_at: t,
    });
    event(db, { spec: row.spec, kind: evKind, ts: t, rows: [{ table: "steps", row }], key, step_kind: kind, ...extra });
    return row;
  });
}

// Writes the intent row (own committed tx). `facts` are what the check needs to decide later.
function begin(db, desc, { now } = {}) {
  return write(db, desc, "intent", desc.facts || {}, nowOf(now), "step_intent");
}

function finish(db, desc, result, { now } = {}) {
  return write(db, desc, "done", result, nowOf(now), "step_done");
}

function run(db, desc, act, opts = {}) {
  const have = getRow(db, desc.key);
  if (have && have.state === "done") return { result: have.result, reused: true };
  begin(db, desc, opts);
  let result;
  try {
    result = act();
  } catch (e) {
    write(db, desc, "failed", { error: String((e && e.message) || e) }, nowOf(opts.now), "step_failed", { error: String((e && e.message) || e) });
    throw e;
  }
  if (result === undefined) result = null;
  finish(db, desc, result, opts);
  return { result };
}

const spawn = (cmd, args, opts = {}) => cp.spawnSync(cmd, args, { encoding: "utf8", timeout: 60000, ...opts });
const git = (dir, args) => spawn("git", ["-C", dir, ...args]);
const tmux = (ctx, args) => spawn("tmux", [...(ctx.tmuxArgs || []), ...args], { env: { ...process.env, TMUX: "" } });
const target = (ctx) => ctx.target || "main";
const mainRepo = (ctx) => ctx.mainRepo || ctx.repo;

function tmuxList(ctx, args) {
  const r = tmux(ctx, args);
  if (r.error) return { unknown: true };
  if (r.status !== 0) {
    if (/no server running|can't find session|no sessions|error connecting|No such file/i.test(r.stderr || "")) return { lines: [] };
    return { unknown: true };
  }
  return { lines: r.stdout.split("\n").filter(Boolean) };
}

function engineStepCommit(ctx, key, facts = {}) {
  const r = git(facts.dir || mainRepo(ctx), ["log", facts.branch || target(ctx), "--format=%B%x00"]);
  if (r.error || r.status !== 0) return "unknown";
  const want = `Engine-Step: ${key}`;
  const hit = r.stdout.split("\0").some((msg) => msg.split("\n").some((l) => l.trim() === want));
  return hit ? "done" : "not_done";
}

function metricsHas(which) {
  return (ctx, row) => {
    const f = row.result || {};
    const r = spawn(ctx.tmuxCtl, ["metrics", "has", which, "--spec", String(f.spec), "--batch", String(f.batch)]);
    if (r.error) return "unknown";
    if (r.status === 0) return "done";
    return r.status === 1 ? "not_done" : "unknown";
  };
}

const norm = (p) => {
  try { return fs.realpathSync(p); } catch (_) {
    try { return path.join(fs.realpathSync(path.dirname(p)), path.basename(p)); } catch (_2) { return path.resolve(p); }
  }
};

const CHECKS = {
  start_worker(ctx, row) {
    const f = row.result || {};
    const l = tmuxList(ctx, ["list-windows", "-t", `=${ctx.session}:`, "-F", "#{window_name}\t#{pane_id}"]);
    if (l.unknown) return "unknown";
    for (const line of l.lines) {
      const [name, pane] = line.split("\t");
      if (name === f.window) { row.found = { pane }; return "done"; }
    }
    return "not_done";
  },
  close_window(ctx, row) {
    const f = row.result || {};
    const l = tmuxList(ctx, ["list-panes", "-a", "-F", "#{pane_id}"]);
    if (l.unknown) return "unknown";
    return l.lines.includes(f.pane) ? "not_done" : "done";
  },
  merge(ctx, row) {
    const f = row.result || {};
    const r = git(mainRepo(ctx), ["merge-base", "--is-ancestor", f.branch, f.target || target(ctx)]);
    if (r.error) return "unknown";
    if (r.status === 0) return "done";
    return r.status === 1 ? "not_done" : "unknown";
  },
  revert: (ctx, row) => engineStepCommit(ctx, row.key),
  commit_report: (ctx, row) => engineStepCommit(ctx, row.key),
  commit_ledger: (ctx, row) => engineStepCommit(ctx, row.key, row.result || {}),
  metrics_start: metricsHas("start"),
  metrics_record: metricsHas("run"),
  // the owners of these steps (tasks 4 and 9) have no check yet: an unfinished row is unknown, and fails
  metrics_ask: () => "unknown",
  artifact: () => "unknown",
  awake_off: () => "unknown",
  registry_report: () => "unknown",
  push(ctx, row) {
    const f = row.result || {};
    const r = git(ctx.repo || mainRepo(ctx), ["ls-remote", f.remote, f.ref]);
    if (r.error || r.status !== 0) return "unknown";
    const sha = (r.stdout.split("\n").filter(Boolean)[0] || "").split(/\s+/)[0];
    return sha && sha === f.sha ? "done" : "not_done";
  },
  worktree_remove(ctx, row) {
    const f = row.result || {};
    const r = git(mainRepo(ctx), ["worktree", "list", "--porcelain"]);
    if (r.error || r.status !== 0) return "unknown";
    const want = norm(f.path);
    const listed = r.stdout.split("\n").filter((l) => l.startsWith("worktree ")).map((l) => norm(l.slice(9)));
    return listed.includes(want) ? "not_done" : "done";
  },
};

// An intent row the check could not decide, for a kind that never blocks a run: failed, with its step_failed event.
function fail(db, row, error, { now } = {}) {
  return write(db, row, "failed", { ...(parse(row.result) || row.result || {}), error }, nowOf(now), "step_failed", { error });
}

// Runs the check of every intent row. Acts on nothing: the caller re-runs `rerun` and parks `park`.
function reconcile(db, ctx, { now } = {}) {
  const out = { rerun: [], park: [] };
  for (const raw of db.prepare("SELECT * FROM steps WHERE state='intent' ORDER BY created_at, key").all()) {
    const row = hydrate(raw);
    let verdict = "unknown";
    try {
      const check = CHECKS[row.kind];
      if (check) verdict = check(ctx, row);
    } catch (_) { verdict = "unknown"; }
    if (verdict === "done") {
      finish(db, row, { ...(row.result || {}), ...(row.found || {}), reconciled: true }, { now });
    } else if (verdict === "not_done") {
      delete row.found;
      out.rerun.push(row);
    } else {
      out.park.push({ key: row.key, question: `could not tell whether ${row.key} ran` });
    }
  }
  return out;
}

module.exports = { run, begin, finish, fail, reconcile, CHECKS, getRow };
