"use strict";
// Replay check (spec 10.6): replay every event's rows into a scratch database and diff it with the live tables.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const db = require("./db");
const paths = require("./paths");

const tablesOf = (d) => d.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'events' ORDER BY name")
  .all().map((r) => r.name);
const pkOf = (d, t) => d.prepare(`PRAGMA table_info(${t})`).all().filter((c) => c.pk).sort((a, b) => a.pk - b.pk).map((c) => c.name);

// Replays into a fresh database made by db.js's own schema creation (db.open on a scratch engine dir).
function replay(project) {
  const live = db.open(project);
  const scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "rebuild-"));
  const old = process.env.TC_ENGINE_DIR;
  process.env.TC_ENGINE_DIR = scratchDir;
  let scratch;
  try { scratch = db.open(project); } finally {
    if (old === undefined) delete process.env.TC_ENGINE_DIR; else process.env.TC_ENGINE_DIR = old;
  }
  try {
    for (const ev of live.prepare("SELECT seq, detail FROM events ORDER BY seq").all()) {
      let rows = [];
      try { rows = (JSON.parse(ev.detail) || {}).rows || []; } catch { /* no rows */ }
      for (const { table, row } of rows) db.put(scratch, table, row);
    }
    const data = {};
    for (const t of tablesOf(scratch)) data[t] = scratch.prepare(`SELECT * FROM ${t}`).all();
    return { live, data, cleanup() { scratch.close(); fs.rmSync(scratchDir, { recursive: true, force: true }); } };
  } catch (e) {
    scratch.close(); live.close(); fs.rmSync(scratchDir, { recursive: true, force: true });
    throw e;
  }
}

const show = (v) => (v === null || v === undefined ? "NULL" : String(v));

function diff(live, data) {
  const diffs = [];
  for (const t of tablesOf(live)) {
    const pk = pkOf(live, t);
    const key = (r) => pk.map((c) => show(r[c])).join("|");
    const l = new Map(live.prepare(`SELECT * FROM ${t}`).all().map((r) => [key(r), r]));
    const p = new Map((data[t] || []).map((r) => [key(r), r]));
    for (const [k, lr] of l) {
      const pr = p.get(k);
      if (!pr) { diffs.push(`${t} ${k}: missing in replay`); continue; }
      for (const c of Object.keys(lr)) {
        if (show(lr[c]) !== show(pr[c])) diffs.push(`${t} ${k}: ${c} live=${show(lr[c])} replay=${show(pr[c])}`);
      }
    }
    for (const k of p.keys()) if (!l.has(k)) diffs.push(`${t} ${k}: missing in live`);
  }
  return diffs;
}

function check(project) {
  const r = replay(project);
  try {
    const diffs = diff(r.live, r.data);
    return { rc: diffs.length ? 1 : 0, diffs };
  } finally { r.live.close(); r.cleanup(); }
}

function lockHeld(project) {
  let pid;
  try { pid = parseInt(fs.readFileSync(paths.lockPath(project), "utf8").split("\n")[0], 10); } catch { return false; }
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}

function apply(project) {
  if (lockHeld(project)) return { rc: 2, msg: "engine lock held" };
  const r = replay(project);
  try {
    r.live.exec("PRAGMA wal_checkpoint(TRUNCATE)");
    const backup = `${paths.dbPath(project)}.bak-${Math.floor(Date.now() / 1000)}`;
    fs.copyFileSync(paths.dbPath(project), backup);
    db.tx(r.live, () => {
      for (const [t, rows] of Object.entries(r.data)) {
        r.live.exec(`DELETE FROM ${t}`);
        for (const row of rows) db.put(r.live, t, row);
      }
    });
    return { rc: 0, backup };
  } finally { r.live.close(); r.cleanup(); }
}

module.exports = { check, apply };
