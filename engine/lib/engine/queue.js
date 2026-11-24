"use strict";
// The queue runner (spec section 6): the two inbox writers (`enqueue`, `done`), the predicate that says whether a queue
// is unfinished, and the loop `engine start` runs. The core owns the turn (core.js startQueued) and every event; this
// file never writes a table but `inbox`.
const inbox = require("./inbox");
const lead = require("./lead");

// A spec that still needs the engine: not done, and not a parked spec the end of a queue already failed (it keeps its
// wait and resumes on a signal: spec section 11).
const OPEN = "state!='done' AND NOT (state='awaiting_you' AND outcome IS NOT NULL)";
const openSpecs = (db) => db.prepare(`SELECT id FROM specs WHERE ${OPEN} ORDER BY position, created_at`).all().map((r) => r.id);

// The spec ids of an unfinished queue, in queue order; [] when there is none. One predicate for `status --unfinished`,
// `start --preflight` and the restore path (R12): open specs, unless a queue_finished event follows the newest spec_added.
function unfinished(db) {
  const ids = openSpecs(db);
  if (!ids.length) return [];
  const last = (kind) => db.prepare("SELECT MAX(seq) AS s FROM events WHERE kind=?").get(kind).s || 0;
  return last("queue_finished") > last("spec_added") ? [] : ids;
}

const pendingEnqueue = (db) => db.prepare("SELECT COUNT(*) AS n FROM inbox WHERE state='new' AND source='user' AND kind='enqueue'").get().n;
const pendingRows = (db) => db.prepare("SELECT COUNT(*) AS n FROM inbox WHERE state='new'").get().n;

// `engine enqueue`: one inbox row; the same spec and batch twice is one row. The core turns it into the spec when drained.
function enqueue(db, spec, payload, now) {
  inbox.insert(db, { source: "user", source_id: `enqueue:${spec}@${payload.batch}`, spec, kind: "enqueue", payload }, now);
}

// `engine done`: returns the exit code and message instead of exiting, as inbox.signal does. Writes only the inbox.
function done(db, spec, outcome, now) {
  const s = db.prepare("SELECT runner, state FROM specs WHERE id=?").get(spec);
  if (!s || s.runner !== "lead" || s.state !== "running") return { rc: 2, msg: `no lead turn open for ${spec}` };
  inbox.insert(db, { source: "user", source_id: `done:${spec}`, spec, kind: "done", payload: { outcome: String(outcome) } }, now);
  return { rc: 0 };
}

// One tick, then the lead lines of whatever it wrote. A line that cannot be appended now is appended after a later
// tick: the cursor is the file itself.
async function step(eng, project) {
  await eng.tick();
  try { lead.publish(project, eng.db); } catch (_) { /* the next tick tries again */ }
}

// The loop of `engine start`: ticks until no spec is open and the inbox is empty (0), or the engine stopped on an
// internal error (1).
async function run(eng, { project }) {
  for (;;) {
    await step(eng, project);
    if (eng.halted) return 1;
    if (!pendingRows(eng.db) && !openSpecs(eng.db).length) return 0;
    await eng.wait();
  }
}

module.exports = { enqueue, done, openSpecs, unfinished, pendingEnqueue, step, run };
