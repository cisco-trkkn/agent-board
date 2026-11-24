"use strict";
// The queue runner (spec section 6): the two inbox writers (`enqueue`, `done`), the predicate that says whether a queue
// is unfinished, and the loop `engine start` runs. The core owns the turn (core.js startQueued) and every event; this
// file never writes a table but `inbox`.
const inbox = require("./inbox");
const lead = require("./lead");
const queueReport = require("./queue_report");

// The report hook of the real engine (core.start({report, reportPath})): the morning report and the path it will have.
const reportHooks = { report: queueReport.write, reportPath: queueReport.reportPath };

// A spec that still needs the engine: not done, and not a parked spec the end of a queue already failed (it keeps its
// wait and resumes on a signal: spec section 11).
// One that has an answer waiting (stored on its wait with no new open wait, or a signal still in the inbox) is open:
// the restore path must apply it.
const OPEN = "state!='done' AND NOT (state='awaiting_you' AND outcome IS NOT NULL" +
  " AND NOT EXISTS (SELECT 1 FROM inbox i WHERE i.spec=specs.id AND i.kind='signal' AND i.state='new')" +
  " AND (EXISTS (SELECT 1 FROM waits w WHERE w.spec=specs.id AND w.answered_at IS NULL)" +
  " OR NOT EXISTS (SELECT 1 FROM waits w WHERE w.spec=specs.id AND w.answered_at IS NOT NULL)))";
const openSpecs = (db) => db.prepare(`SELECT id FROM specs WHERE ${OPEN} ORDER BY position, created_at`).all().map((r) => r.id);

// The spec ids of an unfinished queue, in queue order; [] when there is none. One predicate for `status --unfinished`,
// `start --preflight` and the restore path (R12): the open specs, or, when every spec has ended, the specs enqueued
// (spec_added with `queued`) after the last queue_finished: an engine killed between its last spec's end and the
// queue's end still has the end to write. Specs added by `engine run` carry no `queued` and open no queue.
function unfinished(db) {
  const ids = openSpecs(db);
  if (ids.length) return ids;
  const fin = db.prepare("SELECT MAX(seq) AS s FROM events WHERE kind='queue_finished'").get().s || 0;
  return db.prepare("SELECT id FROM specs WHERE id IN (SELECT spec FROM events WHERE kind='spec_added' AND seq>? AND json_extract(detail, '$.queued')=1) " +
    "ORDER BY position, created_at").all(fin).map((r) => r.id);
}

const pendingEnqueue = (db) => db.prepare("SELECT COUNT(*) AS n FROM inbox WHERE state='new' AND source='user' AND kind='enqueue'").get().n;

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
// tick (the cursor is the file itself); each failure is one stderr line.
async function publish(eng, project, err = (s) => process.stderr.write(s)) {
  try { lead.publish(project, eng.db); } catch (e) {
    try { err(`engine: lead lines: ${String((e && e.message) || e).split("\n")[0]}\n`); } catch (_) { /* stderr is gone */ }
  }
}
async function step(eng, project, err) {
  await eng.tick();
  await publish(eng, project, err);
}

// The loop of `engine start` and `engine resume`: ticks until nothing is runnable and the core has written the queue's
// end (0), or the engine stopped on an internal error (1).
async function run(eng, { project }) {
  for (;;) {
    await step(eng, project);
    if (eng.halted) return 1;
    if (await eng.finish()) {
      await publish(eng, project); // the queue finished line
      return 0;
    }
    if (eng.halted) { await publish(eng, project); return 1; }
    await eng.wait();
  }
}

module.exports = { reportHooks, enqueue, done, openSpecs, unfinished, pendingEnqueue, step, run };
