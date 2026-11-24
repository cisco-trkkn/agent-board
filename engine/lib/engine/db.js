"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");
const paths = require("./paths");
const policy = require("./policy");

const SCHEMA = `
CREATE TABLE IF NOT EXISTS specs(id TEXT PRIMARY KEY, position INT, runner TEXT, integration TEXT, push INT, batch TEXT,
  state TEXT, outcome TEXT, worktree TEXT, branch TEXT, plan TEXT, strategy TEXT DEFAULT 'spec-driven',
  backend TEXT DEFAULT 'claude-tmux', policy_version INT, policy_hash TEXT, base TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, spec TEXT, kind TEXT, task INT, tier TEXT, model TEXT, effort TEXT,
  state TEXT, attempt INT, brief TEXT, report TEXT, window TEXT, pane TEXT, session_id TEXT, base TEXT, head TEXT,
  tools TEXT DEFAULT 'all', mcp TEXT DEFAULT 'all', started_at REAL, ended_at REAL, needs_you_since REAL,
  needs_you_total REAL DEFAULT 0, detail TEXT);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, spec TEXT, job TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS steps(key TEXT PRIMARY KEY, spec TEXT, kind TEXT, state TEXT, result TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS timers(id TEXT PRIMARY KEY, spec TEXT, job TEXT, kind TEXT, due_at REAL, payload TEXT, fired_at REAL);
CREATE TABLE IF NOT EXISTS waits(id TEXT PRIMARY KEY, spec TEXT, step TEXT, question TEXT, options TEXT DEFAULT 'approve|deny|fail',
  asked_at REAL, answered_at REAL, answer TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS retry_policies(kind TEXT PRIMARY KEY, max_attempts INT, backoff_s TEXT, timeout_min REAL, no_retry_on TEXT, on_exhausted TEXT);
CREATE TABLE IF NOT EXISTS inbox(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, source_id TEXT, spec TEXT, job TEXT, kind TEXT,
  payload TEXT, received_at REAL, state TEXT DEFAULT 'new', handled_at REAL, reason TEXT, UNIQUE(source, source_id));
`;

// Columns part 2 added to tables part 1 already created (spec 8a, 8b).
const ADDED = [["specs", "gate", "TEXT"], ["specs", "budget_attempts", "INT"], ["specs", "budget_tokens", "INT"],
  ["specs", "spent_attempts", "INT DEFAULT 0"], ["specs", "spent_tokens", "INT DEFAULT 0"], ["jobs", "tokens", "INT"],
  ["waits", "kind", "TEXT"], ["waits", "recommendation", "TEXT"]];

function migrate(db) {
  for (const [table, col, type] of ADDED) {
    if (!db.prepare(`PRAGMA table_info(${table})`).all().some((c) => c.name === col)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${type}`);
  }
  // An open part 1 wait has no kind: it becomes a cannot_tell wait with that kind's default, and an event
  // carries the filled row so that a replay (rebuild) reaches the same table.
  const open = db.prepare("SELECT * FROM waits WHERE answered_at IS NULL AND kind IS NULL").all();
  if (!open.length) return;
  const rec = JSON.stringify(policy.ASK_DEFAULTS.cannot_tell);
  tx(db, () => {
    for (const w of open) {
      const row = { ...w, kind: "cannot_tell", recommendation: rec };
      putRaw(db, "waits", row);
      event(db, { spec: w.spec, kind: "wait_migrated", rows: [{ table: "waits", row }] });
    }
  });
}

function open(project) {
  fs.mkdirSync(path.dirname(paths.dbPath(project)), { recursive: true });
  const db = new DatabaseSync(paths.dbPath(project));
  db.exec("PRAGMA journal_mode=WAL");
  db.exec("PRAGMA busy_timeout=5000");
  db.exec(SCHEMA);
  migrate(db);
  return db;
}

function tx(db, fn) {
  db.exec("BEGIN IMMEDIATE");
  try {
    const out = fn();
    db.exec("COMMIT");
    return out;
  } catch (e) {
    db.exec("ROLLBACK");
    throw e;
  }
}

const ident = (s) => {
  if (!/^[a-z_][a-z0-9_]*$/i.test(s)) throw new Error(`bad identifier: ${s}`);
  return s;
};

// INSERT OR REPLACE deletes the old row, so absent columns take their default (or NULL).
function putRaw(db, table, row) {
  const keys = Object.keys(row);
  const sql = `INSERT OR REPLACE INTO ${ident(table)} (${keys.map(ident).join(",")}) VALUES (${keys.map(() => "?").join(",")})`;
  db.prepare(sql).run(...keys.map((k) => row[k]));
  return row;
}

// `put` refuses an open wait without a kind and a valid recommendation; an answered row is written as given.
// `putRaw` writes anything (replay and migration).
function put(db, table, row) {
  if (table === "waits" && (row.answered_at === null || row.answered_at === undefined) && policy.waitProblem(row)) {
    throw new Error("wait needs kind and recommendation");
  }
  return putRaw(db, table, row);
}

// `detailKind` is a `kind` field inside the detail (a wait's kind); `kind` itself is the event's.
function event(db, { spec = null, job = null, kind, rows = [], ts, detailKind, ...extra }) {
  const t = ts !== undefined ? ts : Date.now() / 1000;
  const detail = JSON.stringify({ rows, ...extra, ...(detailKind === undefined ? {} : { kind: detailKind }) });
  db.prepare("INSERT INTO events (ts, spec, job, kind, detail) VALUES (?,?,?,?,?)").run(t, spec, job, kind, detail);
}

module.exports = { open, tx, put, putRaw, event };
