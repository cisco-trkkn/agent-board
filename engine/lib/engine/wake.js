"use strict";
// `engine wake` (spec 14): move due schedule rows, and for a project with no engine running take the lock and run a
// short pass that drains only `schedule` rows.
const fs = require("node:fs");
const path = require("node:path");
const paths = require("./paths");
const dbm = require("./db");
const inbox = require("./inbox");
const schedule = require("./schedule");
const steps = require("./steps");
const core = require("./core");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const parseJson = (s) => { try { return JSON.parse(s); } catch (_) { return {}; } };

async function pass(db, project, ctx, t0) {
  const sctx = { repo: ".", project, session: `${project}-bg`, tmuxArgs: ctx.tmuxArgs };
  const seq0 = (db.prepare("SELECT max(seq) m FROM events").get().m) || 0;
  // reconcile the schedule_run rows only: other kinds belong to a running engine
  const mine = (row) => row.kind === "schedule_run";
  const rec = steps.reconcile(db, sctx, { now: t0, only: mine });
  for (const k of rec.park) steps.fail(db, db.prepare("SELECT * FROM steps WHERE key=?").get(k.key), k.question, { now: t0 });
  const hctx = { project, tmuxArgs: ctx.tmuxArgs };
  inbox.drain(db, (row) => schedule.handleRow(db, row, { ...hctx, now: Date.now() / 1000 }), Date.now() / 1000, { source: "schedule" });
  const keys = new Set(schedule.runIntents(db, hctx));
  // every open run of this pass (this one or an earlier wake's) waits for its rc file, at most its timeout_min (A10)
  const deadline = new Map();
  for (const r of db.prepare("SELECT * FROM steps WHERE kind='schedule_run' AND state='done'").all()) {
    if (db.prepare("SELECT 1 FROM events WHERE kind='schedule_ran' AND json_extract(detail,'$.key')=?").get(r.key)) continue;
    if (!keys.has(r.key)) continue;
    const src = r.key.slice("schedule_run:".length);
    const ib = db.prepare("SELECT payload FROM inbox WHERE source='schedule' AND source_id=?").get(src);
    const tm = Number(parseJson(ib && ib.payload).timeout_min);
    deadline.set(r.key, Date.now() + (tm > 0 ? tm : 120) * 60000);
  }
  for (;;) {
    schedule.finishRuns(db, hctx);
    for (const k of [...deadline.keys()]) {
      if (db.prepare("SELECT 1 FROM events WHERE kind='schedule_ran' AND json_extract(detail,'$.key')=?").get(k) || Date.now() > deadline.get(k)) deadline.delete(k);
    }
    if (!deadline.size) break;
    await sleep(1000);
  }
  const ev = (kind) => db.prepare("SELECT count(*) c FROM events WHERE kind=? AND seq>?").get(kind, seq0).c;
  return { ran: ev("schedule_ran"), skipped: ev("schedule_skipped") };
}

async function run({ io, now, project: only } = {}) {
  const out = (io && io.out) || ((s) => process.stdout.write(s + "\n"));
  const dir = paths.engineDir();
  let files = [];
  try { files = fs.readdirSync(dir).filter((f) => f.endsWith(".sqlite")).sort(); } catch (_) { /* no engine dir */ }
  if (only) files = files.filter((f) => path.basename(f, ".sqlite") === only); // `schedule run-now`: one project
  const tmuxArgs = schedule.tmuxArgsFromEnv(process.env);
  let rc = 0;
  try { return (rc = await each(files, tmuxArgs, now, out)); } finally { stamp(rc); }
}

// C1: every pass leaves `<engine dir>/wake.last` (ISO time and the pass's rc): `wake status` and `schedule migrate` read it.
function stamp(rc) {
  try {
    const dir = paths.engineDir();
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "wake.last"), `${new Date().toISOString()} rc ${rc}\n`);
  } catch (_) { /* a stamp that cannot be written must not fail the pass */ }
}

async function each(files, tmuxArgs, now, out) {
  let rc = 0;
  for (const f of files) {
    const project = path.basename(f, ".sqlite");
    let db = null;
    let lock = null;
    try {
      db = dbm.open(project);
      const t0 = now !== undefined ? now : Date.now() / 1000;
      const due = schedule.moveDue(db, t0);
      try { lock = core.takeLock(project); } catch (e) {
        if (/already running/.test(e.message)) { out(`${project}: engine running, ${due} due`); continue; }
        throw e;
      }
      const r = await pass(db, project, { tmuxArgs }, t0);
      out(`${project}: ${due} due, ${r.ran} ran, ${r.skipped} skipped`);
    } catch (e) {
      rc = 1;
      out(`${project}: error: ${String((e && e.message) || e).split("\n")[0]}`);
    } finally {
      if (lock) { try { fs.rmSync(lock, { force: true }); } catch (_) { /* gone */ } }
      if (db) { try { db.close(); } catch (_) { /* closed */ } }
    }
  }
  return rc;
}

module.exports = { run };
