"use strict";
// Schedule rows (spec section 14): a schedule is a `timers` row of kind `schedule`, id `schedule:<name>`.
// `inbox.moveDueTimers` never fires them; the wake runner (later tasks) does.
const { tx, put, event } = require("./db");
const rules = require("./schedule_rules");

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

module.exports = { add, list, rm, shellJoin };
