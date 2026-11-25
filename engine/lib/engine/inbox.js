"use strict";
// The inbox, timers and waits (spec 10.3 and 12): the engine's durable wake-up path.
const crypto = require("node:crypto");
const { tx, put, event } = require("./db");

const nowS = (now) => (now !== undefined ? now : Date.now() / 1000);
// Payloads are always stored as JSON text. `parse` never throws: a non-JSON text (an old or hand-written row) comes back raw.
const json = (v) => JSON.stringify(v ?? null);
const parse = (s) => {
  if (s === null || s === undefined) return null;
  try { return JSON.parse(s); } catch { return s; }
};

// The one writer that appends no event: it writes only `inbox`. Its row reaches `events` when drained.
function insert(db, { source, source_id, spec = null, job = null, kind = null, payload = null }, now) {
  db.prepare(
    "INSERT OR IGNORE INTO inbox (source, source_id, spec, job, kind, payload, received_at, state) VALUES (?,?,?,?,?,?,?, 'new')",
  ).run(source, source_id, spec, job, kind, json(payload), nowS(now));
}

const inboxRow = (db, source, source_id) => db.prepare("SELECT * FROM inbox WHERE source=? AND source_id=?").get(source, source_id);

// Move every due, unfired timer into the inbox: one tx per timer, with its event. Oldest due first.
function moveDueTimers(db, now) {
  const t = nowS(now);
  const due = db.prepare("SELECT * FROM timers WHERE fired_at IS NULL AND kind != 'schedule' AND due_at <= ? ORDER BY due_at, id").all(t);
  let n = 0;
  for (const timer of due) {
    tx(db, () => {
      const cur = db.prepare("SELECT * FROM timers WHERE id=?").get(timer.id);
      if (!cur || cur.fired_at !== null) return;
      const fired = put(db, "timers", { ...cur, fired_at: t });
      const source_id = `${cur.id}@${cur.due_at}`;
      insert(db, { source: "timer", source_id, spec: cur.spec, job: cur.job, kind: cur.kind, payload: parse(cur.payload) }, t);
      const irow = inboxRow(db, "timer", source_id);
      event(db, { spec: cur.spec, job: cur.job, kind: "timer_fired", ts: t,
        rows: [{ table: "timers", row: fired }, { table: "inbox", row: irow }] });
      n++;
    });
  }
  return n;
}

// Backend `status`/`gone` events -> worker inbox rows. Returns the rows it offered (duplicates are ignored by insert).
function workerRows(db, events, now) {
  const out = [];
  for (const ev of events) {
    if (ev.type !== "status" && ev.type !== "gone") continue;
    const h = ev.handle || {};
    // the job id comes first: tmux reuses pane ids after a server restart, and a later job's row must not be a duplicate
    const who = h.job ? `${h.job}:${h.pane}` : `${h.pane}`;
    const source_id = ev.type === "gone" ? `${who}:gone` : `${who}:${ev.state}:${ev.updatedAt}`;
    let spec = h.spec || null;
    if (!spec && h.job) {
      const j = db.prepare("SELECT spec FROM jobs WHERE id=?").get(h.job);
      spec = j ? j.spec : null;
    }
    const { handle, type, ...rest } = ev;
    const r = { source: "worker", source_id, spec, job: h.job || null, kind: type, payload: { ...rest, pane: h.pane, window: h.window } };
    insert(db, r, now);
    out.push(r);
  }
  return out;
}

// Handle every `new` row, oldest first (by id). `handle(row, db)` runs INSIDE the drain's tx for that row, so it may
// call put/event too. It returns undefined, or {drop: "<reason>"} to mark the row dropped. A throw rolls back that row
// only (it stays `new`), stops the drain and is rethrown. Returns the number of rows handled.
function drain(db, handle, now) {
  const t = nowS(now);
  let n = 0;
  for (;;) {
    const next = db.prepare("SELECT id FROM inbox WHERE state='new' ORDER BY id LIMIT 1").get();
    if (!next) return n;
    tx(db, () => {
      const r = db.prepare("SELECT * FROM inbox WHERE id=?").get(next.id);
      const res = handle(r, db);
      const drop = res && res.drop ? String(res.drop) : null;
      db.prepare("UPDATE inbox SET state=?, handled_at=?, reason=? WHERE id=?").run(drop ? "dropped" : "done", t, drop, r.id);
      const done = db.prepare("SELECT * FROM inbox WHERE id=?").get(r.id);
      event(db, { spec: r.spec, job: r.job, kind: `inbox_${r.source}`, ts: t,
        rows: [{ table: "inbox", row: done }], payload: parse(r.payload), source_id: r.source_id });
    });
    n++;
  }
}

const openWaitFor = (db, spec) =>
  db.prepare("SELECT * FROM waits WHERE spec=? AND answered_at IS NULL ORDER BY asked_at DESC LIMIT 1").get(spec) || null;

function openWait(db, { spec, step, question, options, kind, recommendation }, now) {
  const t = nowS(now);
  return tx(db, () => {
    if (openWaitFor(db, spec)) throw new Error(`open wait already exists for ${spec}`);
    const w = { id: `${spec}@${t}`, spec, step, question, asked_at: t, answered_at: null, answer: null, note: null,
      kind, recommendation: typeof recommendation === "string" ? recommendation : json(recommendation) };
    if (options !== undefined) w.options = options;
    else w.options = "approve|deny|fail";
    put(db, "waits", w);
    event(db, { spec, kind: "wait_opened", ts: t, rows: [{ table: "waits", row: db.prepare("SELECT * FROM waits WHERE id=?").get(w.id) }] });
    return db.prepare("SELECT * FROM waits WHERE id=?").get(w.id);
  });
}

function answerWait(db, spec, answer, note, now) {
  const t = nowS(now);
  return tx(db, () => {
    const w = openWaitFor(db, spec);
    if (!w) throw new Error(`no open wait for ${spec}`);
    const row = put(db, "waits", { ...w, answered_at: t, answer, note: note === undefined ? null : note });
    event(db, { spec, kind: "wait_answered", ts: t, rows: [{ table: "waits", row }] });
    return row;
  });
}

// `engine signal`: returns the exit code and message instead of exiting. Writes only the inbox.
function signal(db, spec, answer, note, now) {
  const s = db.prepare("SELECT state FROM specs WHERE id=?").get(spec);
  if (!s || s.state !== "awaiting_you" || !openWaitFor(db, spec)) return { rc: 2, msg: `no open wait for ${spec}` };
  const w = openWaitFor(db, spec);
  if (!String(w.options || "approve|deny|fail").split("|").includes(answer)) {
    return { rc: 2, msg: `${answer} is not an option for ${spec} (${w.options || "approve|deny|fail"})` };
  }
  insert(db, { source: "user", source_id: crypto.randomUUID(), spec, kind: "signal",
    payload: { answer, note: note === undefined ? null : note } }, now);
  return { rc: 0 };
}

module.exports = { insert, moveDueTimers, workerRows, drain, openWait, answerWait, openWaitFor, signal };
