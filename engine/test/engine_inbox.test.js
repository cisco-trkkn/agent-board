"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { tmpEnv } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const inbox = require("../lib/engine/inbox");

function fresh() {
  const e = tmpEnv();
  const db = dbm.open("t");
  return { e, db, done() { db.close(); e.restore(); } };
}
const TABLES = ["specs", "jobs", "events", "steps", "timers", "waits", "retry_policies"];
const counts = (db) => Object.fromEntries(TABLES.map((t) => [t, db.prepare(`SELECT count(*) c FROM ${t}`).get().c]));
const row = (db, sql, ...a) => db.prepare(sql).get(...a);
const states = (db) => db.prepare("SELECT state FROM inbox ORDER BY id").all().map((r) => r.state);
const REC = { option: "approve", why: "w", confidence: "low" };
const W = (o) => ({ kind: "cannot_tell", recommendation: REC, ...o });
const addSpec = (db, id, state) => dbm.put(db, "specs", { id, state });

test("insert is INSERT OR IGNORE and writes only inbox", () => {
  const f = fresh();
  try {
    const before = counts(f.db);
    inbox.insert(f.db, { source: "user", source_id: "a", spec: "s", kind: "signal", payload: { answer: "approve" } }, 10);
    inbox.insert(f.db, { source: "user", source_id: "a", spec: "s", kind: "signal", payload: { answer: "deny" } }, 11);
    assert.deepEqual(counts(f.db), before);
    const rows = f.db.prepare("SELECT * FROM inbox").all();
    assert.equal(rows.length, 1);
    assert.equal(rows[0].state, "new");
    assert.equal(rows[0].received_at, 10);
    assert.deepEqual(JSON.parse(rows[0].payload), { answer: "approve" });
  } finally { f.done(); }
});

test("moveDueTimers fires each due timer once, including one due while down", () => {
  const f = fresh();
  try {
    dbm.put(f.db, "timers", { id: "t1", spec: "s", job: "j", kind: "retry", due_at: 100, payload: '{"a":1}', fired_at: null });
    dbm.put(f.db, "timers", { id: "t2", spec: "s", job: null, kind: "deadline", due_at: 500, payload: null, fired_at: null });
    dbm.put(f.db, "timers", { id: "t3", spec: "s", job: null, kind: "retry", due_at: 50, payload: null, fired_at: 60 });
    assert.equal(inbox.moveDueTimers(f.db, 1000 - 600), 1);
    assert.equal(inbox.moveDueTimers(f.db, 400), 0);
    const r = f.db.prepare("SELECT * FROM inbox").all();
    assert.equal(r.length, 1);
    assert.equal(r[0].source, "timer");
    assert.equal(r[0].source_id, "t1@100");
    assert.equal(r[0].kind, "retry");
    assert.equal(r[0].job, "j");
    assert.equal(row(f.db, "SELECT fired_at FROM timers WHERE id='t1'").fired_at, 400);
    assert.equal(row(f.db, "SELECT fired_at FROM timers WHERE id='t2'").fired_at, null);
    const ev = f.db.prepare("SELECT * FROM events WHERE kind='timer_fired'").all();
    assert.equal(ev.length, 1);
    const tables = JSON.parse(ev[0].detail).rows.map((x) => x.table).sort();
    assert.deepEqual(tables, ["inbox", "timers"]);
    assert.equal(inbox.moveDueTimers(f.db, 600), 1);
    assert.equal(inbox.moveDueTimers(f.db, 700), 0);
  } finally { f.done(); }
});

test("workerRows maps status and gone events to rows", () => {
  const f = fresh();
  try {
    dbm.put(f.db, "jobs", { id: "s:implement1:1", spec: "s", kind: "implement" });
    const h = { job: "s:implement1:1", window: "w", pane: "%3" };
    const evs = [
      { handle: h, type: "started" },
      { handle: h, type: "status", state: "needs-you", updatedAt: 42, tool: "Bash" },
      { handle: h, type: "gone" },
    ];
    const rows = inbox.workerRows(f.db, evs, 5);
    assert.deepEqual(rows.map((r) => r.source_id), ["s:implement1:1:%3:needs-you:42", "s:implement1:1:%3:gone"]);
    inbox.workerRows(f.db, evs, 6);
    const all = f.db.prepare("SELECT * FROM inbox ORDER BY id").all();
    assert.equal(all.length, 2);
    assert.equal(all[0].source, "worker");
    assert.equal(all[0].spec, "s");
    assert.equal(all[0].job, "s:implement1:1");
    assert.equal(all[0].kind, "status");
    assert.equal(all[1].kind, "gone");
  } finally { f.done(); }
});

// tmux reuses pane ids after a server restart: the job id is part of the source id
test("workerRows: two jobs that reuse one pane id each get their gone row", () => {
  const f = fresh();
  try {
    dbm.put(f.db, "jobs", { id: "s:implement1:1", spec: "s", kind: "implement" });
    dbm.put(f.db, "jobs", { id: "s:implement1:2", spec: "s", kind: "implement" });
    for (const job of ["s:implement1:1", "s:implement1:2"]) {
      inbox.workerRows(f.db, [{ handle: { job, window: "w", pane: "%3" }, type: "status", state: "busy", updatedAt: 7 },
        { handle: { job, window: "w", pane: "%3" }, type: "gone" }], 5);
    }
    const gone = f.db.prepare("SELECT job, source_id FROM inbox WHERE kind='gone' ORDER BY id").all();
    assert.deepEqual(gone.map((r) => r.job), ["s:implement1:1", "s:implement1:2"]);
    assert.deepEqual(gone.map((r) => r.source_id), ["s:implement1:1:%3:gone", "s:implement1:2:%3:gone"]);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM inbox WHERE kind='status'").get().n, 2);
  } finally { f.done(); }
});

function users(db, n) {
  for (let i = 1; i <= n; i++) inbox.insert(db, { source: "user", source_id: "u" + i, spec: "s", kind: "signal", payload: { i } }, i);
}

test("three user rows between drains are handled together, oldest first", () => {
  const f = fresh();
  try {
    users(f.db, 3);
    const seen = [];
    const n = inbox.drain(f.db, (r) => { seen.push(r.source_id); }, 50);
    assert.equal(n, 3);
    assert.deepEqual(seen, ["u1", "u2", "u3"]);
    assert.deepEqual(states(f.db), ["done", "done", "done"]);
    const ev = f.db.prepare("SELECT * FROM events WHERE kind='inbox_user' ORDER BY seq").all();
    assert.equal(ev.length, 3);
    const d = JSON.parse(ev[0].detail);
    assert.equal(d.source_id, "u1");
    assert.deepEqual(d.payload, { i: 1 });
    assert.equal(d.rows[0].table, "inbox");
    assert.equal(d.rows[0].row.state, "done");
    assert.equal(d.rows[0].row.handled_at, 50);
    assert.equal(inbox.drain(f.db, () => assert.fail("handled twice"), 60), 0);
  } finally { f.done(); }
});

test("a handler that throws on row 2 rolls back that row only and stops the drain", () => {
  const f = fresh();
  try {
    users(f.db, 3);
    const seen = [];
    assert.throws(() => inbox.drain(f.db, (r, db) => {
      seen.push(r.source_id);
      if (r.source_id === "u2") { dbm.put(db, "steps", { key: "k", spec: "s" }); throw new Error("boom"); }
    }), /boom/);
    assert.deepEqual(seen, ["u1", "u2"]);
    assert.deepEqual(states(f.db), ["done", "new", "new"]);
    assert.equal(row(f.db, "SELECT count(*) c FROM steps").c, 0);
    assert.equal(f.db.prepare("SELECT count(*) c FROM events").get().c, 1);
    const again = [];
    inbox.drain(f.db, (r) => { again.push(r.source_id); });
    assert.deepEqual(again, ["u2", "u3"]);
  } finally { f.done(); }
});

test("a handler returning {drop} marks the row dropped with the reason", () => {
  const f = fresh();
  try {
    users(f.db, 1);
    inbox.drain(f.db, () => ({ drop: "not waiting" }), 9);
    const r = row(f.db, "SELECT * FROM inbox");
    assert.equal(r.state, "dropped");
    assert.equal(r.reason, "not waiting");
    assert.equal(JSON.parse(row(f.db, "SELECT detail FROM events").detail).rows[0].row.state, "dropped");
  } finally { f.done(); }
});

test("waits: one open wait per spec, answer closes it", () => {
  const f = fresh();
  try {
    const w = inbox.openWait(f.db, { spec: "s", step: "integrating", question: "push?", options: "approve|deny|fail", kind: "stop_class", recommendation: REC }, 100);
    assert.equal(w.kind, "stop_class");
    assert.deepEqual(JSON.parse(w.recommendation), REC);
    assert.equal(w.id, "s@100");
    assert.equal(inbox.openWaitFor(f.db, "s").question, "push?");
    assert.throws(() => inbox.openWait(f.db, { spec: "s", step: "x", question: "q", ...W() }, 101));
    assert.equal(inbox.openWaitFor(f.db, "other"), null);
    const a = inbox.answerWait(f.db, "s", "approve", "ok", 150);
    assert.equal(a.answer, "approve");
    assert.equal(inbox.openWaitFor(f.db, "s"), null);
    const r = row(f.db, "SELECT * FROM waits WHERE id='s@100'");
    assert.equal(r.answered_at, 150);
    assert.equal(r.note, "ok");
    inbox.openWait(f.db, { spec: "s", step: "y", question: "again", ...W() }, 200);
    const kinds = f.db.prepare("SELECT kind FROM events ORDER BY seq").all().map((x) => x.kind);
    assert.deepEqual(kinds, ["wait_opened", "wait_answered", "wait_opened"]);
    assert.equal(JSON.parse(f.db.prepare("SELECT detail FROM events ORDER BY seq").all()[1].detail).rows[0].table, "waits");
  } finally { f.done(); }
});

test("signal returns rc 2 unless the spec is awaiting_you with an open wait; writes only inbox", () => {
  const f = fresh();
  try {
    addSpec(f.db, "s", "running");
    assert.deepEqual(inbox.signal(f.db, "s", "approve", null), { rc: 2, msg: "no open wait for s" });
    addSpec(f.db, "s", "awaiting_you");
    assert.deepEqual(inbox.signal(f.db, "s", "approve", null), { rc: 2, msg: "no open wait for s" });
    inbox.openWait(f.db, { spec: "s", step: "x", question: "q", ...W() }, 1);
    const before = counts(f.db);
    assert.deepEqual(inbox.signal(f.db, "s", "deny", "no thanks", 5), { rc: 0 });
    inbox.signal(f.db, "s", "deny", "no thanks", 6);
    assert.deepEqual(counts(f.db), before);
    const r = f.db.prepare("SELECT * FROM inbox").all();
    assert.equal(r.length, 2);
    assert.equal(r[0].source, "user");
    assert.equal(r[0].spec, "s");
    assert.match(r[0].source_id, /^[0-9a-f-]{36}$/);
    assert.notEqual(r[0].source_id, r[1].source_id);
    assert.deepEqual(JSON.parse(r[0].payload), { answer: "deny", note: "no thanks" });
  } finally { f.done(); }
});

test("a non-JSON string payload (via insert, and a timer row with raw text) drains to done", () => {
  const f = fresh();
  try {
    inbox.insert(f.db, { source: "user", source_id: "raw", spec: "s", kind: "signal", payload: "hello" }, 1);
    dbm.put(f.db, "timers", { id: "tr", spec: "s", job: null, kind: "retry", due_at: 5, payload: "not json", fired_at: null });
    assert.equal(inbox.moveDueTimers(f.db, 10), 1);
    const seen = [];
    assert.equal(inbox.drain(f.db, (r) => { seen.push(r.source); }, 20), 2);
    assert.deepEqual(states(f.db), ["done", "done"]);
    const ev = f.db.prepare("SELECT detail FROM events WHERE kind LIKE 'inbox_%' ORDER BY seq").all().map((e) => JSON.parse(e.detail).payload);
    assert.deepEqual(ev, ["hello", "not json"]);
    // an existing bad row written raw (older code) must not block the inbox either
    f.db.prepare("INSERT INTO inbox (source, source_id, spec, kind, payload, received_at, state) VALUES ('user','legacy','s','signal','plain text',30,'new')").run();
    assert.equal(inbox.drain(f.db, () => {}, 40), 1);
    assert.deepEqual(states(f.db), ["done", "done", "done"]);
  } finally { f.done(); }
});

test("signal refuses an answer that is not among the open wait's options", () => {
  const f = fresh();
  try {
    addSpec(f.db, "s", "awaiting_you");
    inbox.openWait(f.db, { spec: "s", step: "x", question: "q", options: "approve|fail", ...W() }, 1);
    assert.deepEqual(inbox.signal(f.db, "s", "deny", null, 2), { rc: 2, msg: "deny is not an option for s (approve|fail)" });
    assert.equal(f.db.prepare("SELECT count(*) c FROM inbox").get().c, 0);
    assert.deepEqual(inbox.signal(f.db, "s", "fail", null, 3), { rc: 0 });
  } finally { f.done(); }
});
