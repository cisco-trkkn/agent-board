"use strict";
const { test, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");
const { tmpEnv } = require("./engine_helpers");
const db = require("../lib/engine/db");
const paths = require("../lib/engine/paths");
const rebuild = require("../lib/engine/rebuild");

let env;
beforeEach(() => { env = tmpEnv(); });
afterEach(() => env.restore());

function seed(project) {
  const d = db.open(project);
  db.tx(d, () => {
    const s = { id: "s1", position: 1, state: "queued", created_at: 1, updated_at: 1 };
    db.put(d, "specs", s);
    db.event(d, { spec: "s1", kind: "spec_added", rows: [{ table: "specs", row: s }] });
  });
  db.tx(d, () => {
    const s = { id: "s1", position: 1, state: "running", created_at: 1, updated_at: 2 };
    const j = { id: "s1:implement1:1", spec: "s1", kind: "implement", task: 1, state: "running", attempt: 1 };
    db.put(d, "specs", s);
    db.put(d, "jobs", j);
    db.event(d, { spec: "s1", job: j.id, kind: "job_started", rows: [{ table: "specs", row: s }, { table: "jobs", row: j }] });
  });
  d.close();
}

test("check: log and tables agree -> rc 0", () => {
  seed("p");
  assert.deepEqual(rebuild.check("p"), { rc: 0, diffs: [] });
});

test("check: row changed behind the log -> rc 1 naming it", () => {
  seed("p");
  const d = db.open("p");
  d.exec("UPDATE jobs SET state='done' WHERE id='s1:implement1:1'");
  d.close();
  const r = rebuild.check("p");
  assert.equal(r.rc, 1);
  assert.deepEqual(r.diffs, ["jobs s1:implement1:1: state live=done replay=running"]);
});

test("check: row missing from replay and from live", () => {
  seed("p");
  const d = db.open("p");
  d.exec("INSERT INTO timers(id, spec) VALUES ('t1','s1')");
  d.exec("DELETE FROM jobs");
  d.close();
  const r = rebuild.check("p");
  assert.equal(r.rc, 1);
  assert.ok(r.diffs.includes("timers t1: missing in replay"));
  assert.ok(r.diffs.includes("jobs s1:implement1:1: missing in live"));
});

test("apply: repairs, keeps backup", () => {
  seed("p");
  const d = db.open("p");
  d.exec("UPDATE jobs SET state='done'");
  d.close();
  const r = rebuild.apply("p");
  assert.equal(r.rc, 0);
  assert.equal(rebuild.check("p").rc, 0);
  const baks = fs.readdirSync(env.engineDir).filter((f) => /^p\.sqlite\.bak-\d+$/.test(f));
  assert.equal(baks.length, 1);
  const b = new DatabaseSync(path.join(env.engineDir, baks[0]));
  assert.equal(b.prepare("SELECT state FROM jobs").get().state, "done");
  b.close();
});

test("apply: live lock pid -> rc 2, nothing changed", () => {
  seed("p");
  const d = db.open("p");
  d.exec("UPDATE jobs SET state='done'");
  d.close();
  fs.writeFileSync(paths.lockPath("p"), `${process.pid}\n`);
  assert.deepEqual(rebuild.apply("p"), { rc: 2, msg: "engine lock held" });
  assert.equal(rebuild.check("p").rc, 1);
  assert.equal(fs.readdirSync(env.engineDir).filter((f) => f.includes(".bak-")).length, 0);
});

test("apply: dead pid or junk lock is not held", () => {
  seed("p");
  fs.writeFileSync(paths.lockPath("p"), "junk\n");
  assert.equal(rebuild.apply("p").rc, 0);
  fs.writeFileSync(paths.lockPath("p"), "2147483646\n");
  assert.equal(rebuild.apply("p").rc, 0);
});

// ---- final review I6: a pending user answer survives rebuild ------------------------------------------------
function withNewInboxRow(project) {
  seed(project);
  const d = db.open(project);
  d.prepare("INSERT INTO inbox (source, source_id, spec, kind, payload, received_at, state) VALUES ('user','sig-1','s1','signal','{}',5,'new')").run();
  d.close();
}

test("check: a state='new' inbox row (written without an event) is not a difference", () => {
  withNewInboxRow("p");
  assert.deepEqual(rebuild.check("p"), { rc: 0, diffs: [] });
});

test("apply: a state='new' inbox row survives", () => {
  withNewInboxRow("p");
  assert.equal(rebuild.apply("p").rc, 0);
  const d = db.open("p");
  const rows = d.prepare("SELECT source_id, state FROM inbox").all().map((r) => ({ ...r }));
  d.close();
  assert.deepEqual(rows, [{ source_id: "sig-1", state: "new" }]);
});

test("check: an open wait without a kind (a part 1 event) replays through putRaw", () => {
  seed("p");
  const d = db.open("p");
  const w = { id: "s1@5", spec: "s1", step: "x", question: "q", options: "approve|deny|fail", asked_at: 5, answered_at: null, answer: null, note: null };
  db.putRaw(d, "waits", w);
  db.event(d, { spec: "s1", kind: "wait_opened", rows: [{ table: "waits", row: w }] });
  d.close();
  assert.deepEqual(rebuild.check("p"), { rc: 0, diffs: [] });
});
