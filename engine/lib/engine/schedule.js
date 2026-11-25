"use strict";
// Schedule rows (spec section 14): a schedule is a `timers` row of kind `schedule`, id `schedule:<name>`.
// `inbox.moveDueTimers` never fires them; the wake runner (later tasks) does.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const { tx, put, event } = require("./db");
const rules = require("./schedule_rules");
const inbox = require("./inbox");
const steps = require("./steps");
const paths = require("./paths");

const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const SAFE_WORD = /^[A-Za-z0-9_./:=@%+-]+$/;

const badInput = (msg) => Object.assign(new Error(msg), { code: "bad_input" });

// zsh-style quoting: a plain word stays bare, any other is single-quoted with ' as '\''.
function shellJoin(words) {
  return words.map((w) => (SAFE_WORD.test(w) ? w : `'${w.replace(/'/g, "'\\''")}'`)).join(" ");
}

const payloadOf = (row) => JSON.parse(row.payload);

// -> {status: "added" | "unchanged", due_at}. An active row with another rule or command throws; a retired row is
// replaced by a put of the same id (replay keeps the last put).
function add(db, { name, rule, command, skip_if_weekly_usage = 85, cwd, env = {} }, now) {
  if (typeof name !== "string" || !NAME.test(name)) throw badInput(`bad schedule name "${name}": letters, digits, . _ - and a letter or digit first`);
  const text = String(rule).trim();
  try { rules.parseRule(text); } catch (e) { throw badInput(e.message); }
  if (typeof command !== "string" || !command.trim()) throw badInput("a schedule needs a command");
  const id = `schedule:${name}`;
  return tx(db, () => {
    const cur = db.prepare("SELECT * FROM timers WHERE id=? AND kind='schedule'").get(id);
    if (cur && cur.fired_at === null) {
      const p = payloadOf(cur);
      if (p.rule === text && p.command === command) return { status: "unchanged", due_at: cur.due_at };
      throw new Error(`schedule ${name} exists: rm it first`);
    }
    const due_at = rules.nextAfter(text, now, now);
    const row = put(db, "timers", {
      id, spec: null, job: null, kind: "schedule", due_at, fired_at: null,
      payload: JSON.stringify({ name, command, rule: text, skip_if_weekly_usage, cwd, env }),
    });
    event(db, { kind: "schedule_added", ts: now, name, rows: [{ table: "timers", row }] });
    return { status: "added", due_at };
  });
}

// Active rows by name, payload parsed, with due_at.
function list(db) {
  return db.prepare("SELECT * FROM timers WHERE kind='schedule' AND fired_at IS NULL").all()
    .map((r) => ({ ...payloadOf(r), due_at: r.due_at }))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

function rm(db, name, now) {
  tx(db, () => {
    const cur = db.prepare("SELECT * FROM timers WHERE id=? AND kind='schedule'").get(`schedule:${name}`);
    if (!cur || cur.fired_at !== null) throw new Error(`no schedule ${name}`);
    const row = put(db, "timers", { ...cur, fired_at: now });
    event(db, { kind: "schedule_removed", ts: now, name, rows: [{ table: "timers", row }] });
  });
}

// ---- the runner (Task 6) ---------------------------------------------------------------------------------------

const ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
const q = (w) => shellJoin([String(w)]);
// The tmux server a wake talks to: the rule of bin/_tc_bins.zsh `tc_tmux_resolve` (TMUX_DASH_TMUX_ARGS, else the server
// of $TMUX, else the dedicated `-L ${AGENT_BOARD_TMUX_SOCKET:-agent-board}` with the repo's config/tmux.conf).
// AGENT_BOARD_TMUX_CONF overrides the config file (a test seam: a scratch server must not load the real config).
function tmuxArgsFromEnv(env) {
  if ((env.TMUX_DASH_TMUX_ARGS || "").trim()) return env.TMUX_DASH_TMUX_ARGS.split(/\s+/).filter(Boolean);
  if (env.TMUX) return ["-S", String(env.TMUX).split(",")[0]];
  const conf = env.AGENT_BOARD_TMUX_CONF || path.resolve(__dirname, "../../../config/tmux.conf");
  return ["-L", env.AGENT_BOARD_TMUX_SOCKET || "agent-board", "-f", conf];
}
const tmuxRun = (ctx, args) =>
  cp.spawnSync("tmux", [...(ctx.tmuxArgs || []), ...args], { encoding: "utf8", timeout: 30000, env: { ...process.env, TMUX: "" } });

// Newest statusline tap's seven_day percentage, or null when there is none.
function weeklyUsage() {
  const dir = path.join(paths.stateDir(), "statusline");
  let best = null;
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith(".json")); } catch (_) { return null; }
  for (const n of names) {
    try {
      const j = JSON.parse(fs.readFileSync(path.join(dir, n), "utf8"));
      const pct = j && j.rate_limits && j.rate_limits.seven_day && j.rate_limits.seven_day.used_percentage;
      if (typeof pct !== "number") continue;
      const at = Number(j.received_at) || 0;
      if (!best || at > best.at) best = { at, pct };
    } catch (_) { /* unreadable tap */ }
  }
  return best ? best.pct : null;
}

// Each active row due at `now` moves to its next occurrence, with one `schedule` inbox row and a schedule_due event. -> count.
function moveDue(db, now) {
  const due = db.prepare("SELECT * FROM timers WHERE kind='schedule' AND fired_at IS NULL AND due_at <= ? ORDER BY due_at, id").all(now);
  let n = 0;
  for (const t of due) {
    tx(db, () => {
      const cur = db.prepare("SELECT * FROM timers WHERE id=?").get(t.id);
      if (!cur || cur.fired_at !== null || cur.due_at > now) return;
      const p = payloadOf(cur);
      const row = put(db, "timers", { ...cur, due_at: rules.nextAfter(p.rule, now, cur.due_at) });
      const source_id = `${p.name}@${cur.due_at}`;
      inbox.insert(db, { source: "schedule", source_id, kind: "run", payload: p }, now);
      const irow = db.prepare("SELECT * FROM inbox WHERE source='schedule' AND source_id=?").get(source_id);
      event(db, { kind: "schedule_due", ts: now, name: p.name, rows: [{ table: "timers", row }, { table: "inbox", row: irow }] });
      n++;
    });
  }
  return n;
}

const rowPayload = (row) => {
  let p = null;
  try { p = JSON.parse(row.payload); } catch (_) { return {}; }
  return p && typeof p === "object" ? p : {};
};
const runKey = (source_id) => String(source_id).slice(String(source_id).indexOf("@") + 1).replace(/:/g, "-");
const nameOf = (row, p) => p.name || String(row.source_id).split("@")[0];

// Runs inside the drain's tx: a skip is one event, a run is a `schedule_run` step at intent (written like steps.begin, without its own tx).
function handleRow(db, row, ctx) {
  const t = ctx.now !== undefined ? ctx.now : Date.now() / 1000;
  const p = rowPayload(row);
  if (typeof p.command !== "string" || !p.command.trim()) return { drop: "no command" };
  const name = nameOf(row, p);
  const usage = weeklyUsage();
  const limit = p.skip_if_weekly_usage;
  if (!p.force && typeof limit === "number" && usage !== null && usage >= limit) {
    event(db, { kind: "schedule_skipped", ts: t, name, reason: `weekly usage ${usage}% >= ${limit}%`, usage });
    return undefined;
  }
  const window = `sched·${name}`;
  const l = steps.listWindows(ctx, `${ctx.project}-bg`);
  if (!l.unknown && l.lines.includes(window)) {
    event(db, { kind: "schedule_skipped", ts: t, name, reason: "still running", usage });
    return undefined;
  }
  const base = path.join(paths.engineDir(), "sched", ctx.project, `${name}-${runKey(row.source_id)}`);
  const facts = { name, command: p.command, cwd: p.cwd || process.cwd(), env: p.env || {}, window, rc_file: `${base}.rc`, log: `${base}.log` };
  const key = `schedule_run:${row.source_id}`;
  const srow = put(db, "steps", { key, spec: null, kind: "schedule_run", state: "intent", result: JSON.stringify(facts), created_at: t, updated_at: t });
  event(db, { kind: "step_intent", ts: t, rows: [{ table: "steps", row: srow }], key, step_kind: "schedule_run", usage });
  return undefined;
}

// The zsh line a run's window executes.
function runLine(f) {
  const env = Object.entries(f.env || {}).filter(([k]) => ENV_KEY.test(k)).map(([k, v]) => `export ${k}=${q(v)};`).join(" ");
  // a newline before `)`: a command that ends in a # comment must not swallow it
  return `( ${env} ${f.command}\n) 2>&1 | tee ${q(f.log)}; print -r -- $` + `{pipestatus[1]} > ${q(f.rc_file)}`;
}

const parseResult = (r) => { try { return JSON.parse(r); } catch (_) { return {}; } };

// Opens the window of every `schedule_run` step at intent. -> the keys it started.
function runIntents(db, ctx) {
  const started = [];
  const bg = `${ctx.project}-bg`;
  for (const srow of db.prepare("SELECT * FROM steps WHERE kind='schedule_run' AND state='intent' ORDER BY created_at, key").all()) {
    const f = parseResult(srow.result);
    const desc = { key: srow.key, spec: null, kind: "schedule_run" };
    const t = ctx.now !== undefined ? ctx.now : Date.now() / 1000;
    try {
      fs.mkdirSync(path.dirname(f.log), { recursive: true });
      if (tmuxRun(ctx, ["has-session", "-t", `=${bg}`]).status !== 0) {
        const r = tmuxRun(ctx, ["new-session", "-d", "-s", bg, "-n", "shell", "-c", f.cwd]);
        if (r.status !== 0) throw new Error(`new-session: ${(r.stderr || "").trim()}`);
        tmuxRun(ctx, ["set-option", "-t", `=${bg}:`, "@tc_bg", "1"]);
      }
      const r = tmuxRun(ctx, ["new-window", "-d", "-t", `=${bg}:`, "-n", f.window, "-c", f.cwd, "zsh", "-c", runLine(f)]);
      if (r.status !== 0) throw new Error(`new-window: ${(r.stderr || "").trim()}`);
    } catch (e) {
      steps.fail(db, srow, String(e.message || e), { now: t });
      continue;
    }
    steps.finish(db, desc, { ...f, started_at: t }, { now: t });
    tx(db, () => event(db, { kind: "schedule_started", ts: t, name: f.name, key: srow.key, window: f.window, rc_file: f.rc_file, log: f.log }));
    started.push(srow.key);
  }
  return started;
}

// One `schedule_ran` for each done run whose rc file exists. -> the keys it recorded.
// A recorded run is marked on its own step (`ran: true` in the result): the next ticks skip it without a query on events.
const OPEN_RUNS = "SELECT * FROM steps WHERE kind='schedule_run' AND state='done' AND json_extract(result,'$.ran') IS NULL ORDER BY created_at, key";
function finishRuns(db, ctx) {
  const out = [];
  for (const srow of db.prepare(OPEN_RUNS).all()) {
    const f = parseResult(srow.result);
    if (!f.rc_file) continue;
    const desc = { key: srow.key, spec: null, kind: "schedule_run" };
    const t = ctx.now !== undefined ? ctx.now : Date.now() / 1000;
    // an earlier tick wrote the event and died before the mark: mark now, record nothing twice
    if (db.prepare("SELECT 1 FROM events WHERE kind='schedule_ran' AND json_extract(detail,'$.key')=?").get(srow.key)) {
      steps.finish(db, desc, { ...f, ran: true }, { now: t });
      continue;
    }
    let text;
    try { text = fs.readFileSync(f.rc_file, "utf8"); } catch (_) { continue; }
    const rc = parseInt(text.trim(), 10);
    if (!Number.isInteger(rc)) continue;
    tx(db, () => event(db, { kind: "schedule_ran", ts: t, name: f.name, key: srow.key, rc, log: f.log }));
    steps.finish(db, desc, { ...f, ran: true }, { now: t });
    out.push(srow.key);
  }
  return out;
}

module.exports = { tmuxArgsFromEnv, add, list, rm, shellJoin, weeklyUsage, moveDue, handleRow, runIntents, finishRuns, runLine };
