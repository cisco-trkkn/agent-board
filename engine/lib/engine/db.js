"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");
const paths = require("./paths");

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

function open(project) {
  fs.mkdirSync(path.dirname(paths.dbPath(project)), { recursive: true });
  const db = new DatabaseSync(paths.dbPath(project));
  db.exec("PRAGMA journal_mode=WAL");
  db.exec("PRAGMA busy_timeout=5000");
  db.exec(SCHEMA);
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
function put(db, table, row) {
  const keys = Object.keys(row);
  const sql = `INSERT OR REPLACE INTO ${ident(table)} (${keys.map(ident).join(",")}) VALUES (${keys.map(() => "?").join(",")})`;
  db.prepare(sql).run(...keys.map((k) => row[k]));
  return row;
}

function event(db, { spec = null, job = null, kind, rows = [], ts, ...extra }) {
  const t = ts !== undefined ? ts : Date.now() / 1000;
  const detail = JSON.stringify({ rows, ...extra });
  db.prepare("INSERT INTO events (ts, spec, job, kind, detail) VALUES (?,?,?,?,?)").run(t, spec, job, kind, detail);
}

module.exports = { open, tx, put, event };
