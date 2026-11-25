"use strict";
// engine wake (spec 14, Task 6): moveDue, the drain filter and re-check, handleRow, and the CLI on a scratch tmux server.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, scratchTmux } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const rebuild = require("../lib/engine/rebuild");
const schedule = require("../lib/engine/schedule");
const inbox = require("../lib/engine/inbox");
const paths = require("../lib/engine/paths");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const DAY = 86400;

const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

// An isolated engine dir, state dir and scratch tmux server (one session kept alive so the server stays up).
function world() {
  const e = tmpEnv();
  const tm = scratchTmux();
  cleanups.push(() => { tm.kill(); e.restore(); });
  assert.equal(tm.run(["new-session", "-d", "-s", "keep"]).status, 0);
  const sock = tm.run(["display-message", "-p", "#{socket_path}"]).stdout.trim();
  const tmpdir = path.dirname(path.dirname(sock));
  // in-process tmux calls (handleRow, steps checks) reach the scratch server through the same TMUX_TMPDIR
  const oldTmp = process.env.TMUX_TMPDIR;
  process.env.TMUX_TMPDIR = tmpdir;
  cleanups.push(() => { if (oldTmp === undefined) delete process.env.TMUX_TMPDIR; else process.env.TMUX_TMPDIR = oldTmp; });
  const env = { ...process.env, TC_ENGINE_DIR: e.engineDir, TC_STATE: e.state, TMUX_TMPDIR: tmpdir,
    TMUX_DASH_TMUX_ARGS: `-L ${tm.socket} -f /dev/null` };
  delete env.TMUX;
  const w = {
    e, tm, env, tmpdir,
    tmuxArgs: ["-L", tm.socket, "-f", "/dev/null"],
    wake() { return cp.spawnSync("node", [ENGINE, "wake"], { env, encoding: "utf8", timeout: 60000 }); },
    db(project = "p") { const d = dbm.open(project); return d; },
  };
  return w;
}
const events = (db, kind) => db.prepare("SELECT * FROM events WHERE kind=?").all(kind).map((r) => ({ ...r, d: JSON.parse(r.detail) }));
const ok = (project = "p") => assert.equal(rebuild.check(project).rc, 0, JSON.stringify(rebuild.check(project).diffs));
const nowS = () => Date.now() / 1000;

function addRow(db, name, command, due_at, extra = {}) {
  schedule.add(db, { name, rule: extra.rule || "every 1m", command, cwd: extra.cwd || os.tmpdir(), skip_if_weekly_usage: extra.skip === undefined ? 85 : extra.skip, env: extra.env || {} }, nowS());
  const row = db.prepare("SELECT * FROM timers WHERE id=?").get(`schedule:${name}`);
  db.prepare("UPDATE timers SET due_at=? WHERE id=?").run(due_at, row.id); // test fixture: back-date the row
}

function tap(w, pct) {
  const dir = path.join(w.e.state, "statusline");
  fs.mkdirSync(dir, { recursive: true });
  const t = nowS();
  fs.writeFileSync(path.join(dir, "x.json"), JSON.stringify({ received_at: t, rate_limits: { seven_day: { used_percentage: pct, resets_at: t + DAY } } }));
}

test("moveDue: a row due three days ago yields one inbox row and a future due_at (missed occurrences collapse)", () => {
  const w = world();
  const db = w.db();
  const now = nowS();
  const old = now - 3 * DAY;
  addRow(db, "a", "echo", old);
  const n = schedule.moveDue(db, now);
  assert.equal(n, 1);
  const rows = db.prepare("SELECT * FROM inbox WHERE source='schedule'").all();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].source_id, `a@${old}`);
  assert.equal(rows[0].kind, "run");
  assert.equal(JSON.parse(rows[0].payload).command, "echo");
  assert.ok(db.prepare("SELECT due_at FROM timers WHERE id='schedule:a'").get().due_at > now);
  const ev = events(db, "schedule_due");
  assert.equal(ev.length, 1);
  assert.deepEqual(ev[0].d.rows.map((r) => r.table), ["timers", "inbox"]);
  assert.equal(schedule.moveDue(db, now), 0);
  ok();
  db.close();
});

test("moveDue skips a retired row and a row not yet due", () => {
  const w = world();
  const db = w.db();
  const now = nowS();
  addRow(db, "future", "echo", now + 600);
  addRow(db, "gone", "echo", now - 10);
  schedule.rm(db, "gone", now);
  assert.equal(schedule.moveDue(db, now), 0);
  assert.equal(db.prepare("SELECT count(*) c FROM inbox").get().c, 0);
  db.close();
});

test("drain with a source handles only that source's rows; without one it handles both", () => {
  const w = world();
  const db = w.db();
  inbox.insert(db, { source: "user", source_id: "u1", kind: "signal", payload: {} }, 1);
  inbox.insert(db, { source: "schedule", source_id: "s@1", kind: "run", payload: { command: "x" } }, 2);
  const seen = [];
  assert.equal(inbox.drain(db, (r) => { seen.push(r.source); }, 5, { source: "schedule" }), 1);
  assert.deepEqual(seen, ["schedule"]);
  assert.equal(db.prepare("SELECT state FROM inbox WHERE source='user'").get().state, "new");
  assert.equal(inbox.drain(db, (r) => { seen.push(r.source); }, 6), 1);
  assert.deepEqual(seen, ["schedule", "user"]);
  db.close();
});

test("drain re-reads the row: two connections handle one row once (one schedule_run step, one inbox_schedule event)", () => {
  const w = world();
  const db1 = w.db();
  const db2 = w.db();
  inbox.insert(db1, { source: "schedule", source_id: "r@1", kind: "run", payload: { name: "r", command: "echo hi", cwd: os.tmpdir(), env: {} } }, 1);
  // connection 2 took the row's id before connection 1 handled it: its first "next row" lookup answers the stale id
  const stale = db2.prepare("SELECT id FROM inbox WHERE state='new' ORDER BY id LIMIT 1").get();
  let served = false;
  const db2x = {
    exec: (s) => db2.exec(s),
    prepare(sql) {
      if (!served && /^SELECT id FROM inbox/.test(sql)) { served = true; return { get: () => stale }; }
      return db2.prepare(sql);
    },
  };
  const ctx = { project: "p", tmuxArgs: w.tmuxArgs, now: 10 };
  const h = (db) => (row) => schedule.handleRow(db, row, ctx);
  assert.equal(inbox.drain(db1, h(db1), 10, { source: "schedule" }), 1);
  assert.equal(inbox.drain(db2x, h(db2x), 11, { source: "schedule" }), 0);
  assert.equal(db1.prepare("SELECT count(*) c FROM steps WHERE kind='schedule_run'").get().c, 1);
  assert.equal(events(db1, "inbox_schedule").length, 1);
  ok();
  db1.close();
  db2.close();
});

test("handleRow: usage at or over the limit skips; force runs; a payload without command is dropped", () => {
  const w = world();
  const db = w.db();
  tap(w, 91);
  const ctx = { project: "p", tmuxArgs: w.tmuxArgs, now: 10 };
  const mk = (id, payload) => inbox.insert(db, { source: "schedule", source_id: id, kind: "run", payload }, 1);
  const base = { command: "echo hi", cwd: os.tmpdir(), env: {} };
  mk("a@1", { ...base, name: "a", skip_if_weekly_usage: 85 });
  mk("b@1", { ...base, name: "b", skip_if_weekly_usage: 85, force: true });
  mk("c@1", { name: "c" });
  mk("d@1", { ...base, name: "d", skip_if_weekly_usage: null });
  inbox.drain(db, (r) => schedule.handleRow(db, r, ctx), 10, { source: "schedule" });
  const sk = events(db, "schedule_skipped");
  assert.equal(sk.length, 1);
  assert.equal(sk[0].d.name, "a");
  assert.equal(sk[0].d.reason, "weekly usage 91% >= 85%");
  assert.equal(sk[0].d.usage, 91);
  assert.deepEqual(db.prepare("SELECT key FROM steps WHERE kind='schedule_run' ORDER BY key").all().map((r) => r.key), ["schedule_run:b@1", "schedule_run:d@1"]);
  assert.equal(db.prepare("SELECT reason FROM inbox WHERE source_id='c@1'").get().reason, "no command");
  assert.equal(db.prepare("SELECT state FROM inbox WHERE source_id='c@1'").get().state, "dropped");
  const f = JSON.parse(db.prepare("SELECT result FROM steps WHERE key='schedule_run:b@1'").get().result);
  assert.deepEqual(Object.keys(f).sort(), ["command", "cwd", "env", "log", "name", "rc_file", "window"]);
  assert.equal(f.window, "sched·b");
  ok();
  db.close();
});

test("handleRow: a window already open skips with 'still running'", () => {
  const w = world();
  assert.equal(w.tm.run(["new-session", "-d", "-s", "p-bg", "-n", "sched·busy", "sleep 30"]).status, 0);
  const db = w.db();
  inbox.insert(db, { source: "schedule", source_id: "busy@1", kind: "run", payload: { name: "busy", command: "x", cwd: os.tmpdir(), env: {} } }, 1);
  inbox.drain(db, (r) => schedule.handleRow(db, r, { project: "p", tmuxArgs: w.tmuxArgs, now: 10 }), 10, { source: "schedule" });
  const sk = events(db, "schedule_skipped");
  assert.equal(sk.length, 1);
  assert.equal(sk[0].d.reason, "still running");
  assert.equal(db.prepare("SELECT count(*) c FROM steps").get().c, 0);
  db.close();
});

test("engine wake: rc 3 recorded with the log, lock gone, due_at in the future; a second wake runs nothing", () => {
  const w = world();
  const db = w.db();
  addRow(db, "echo1", "echo hi; exit 3", nowS() - 30);
  db.close();
  const r = w.wake();
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /^p: 1 due, 1 ran, 0 skipped$/m);
  const d = w.db();
  const ran = events(d, "schedule_ran");
  assert.equal(ran.length, 1);
  assert.equal(ran[0].d.rc, 3);
  assert.equal(ran[0].d.name, "echo1");
  assert.match(fs.readFileSync(ran[0].d.log, "utf8"), /hi/);
  assert.equal(events(d, "schedule_started").length, 1);
  assert.ok(d.prepare("SELECT due_at FROM timers WHERE id='schedule:echo1'").get().due_at > nowS());
  assert.ok(!fs.existsSync(paths.lockPath("p")));
  assert.equal(w.tm.run(["show-options", "-t", "=p-bg:", "@tc_bg"]).stdout.trim(), "@tc_bg 1");
  ok();
  d.close();
  const r2 = w.wake();
  assert.equal(r2.status, 0, r2.stderr);
  assert.match(r2.stdout, /^p: 0 due, 0 ran, 0 skipped$/m);
});

test("engine wake: a row due 3 days ago runs once", () => {
  const w = world();
  const db = w.db();
  addRow(db, "old", "echo old", nowS() - 3 * DAY);
  db.close();
  const r = w.wake();
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const d = w.db();
  assert.equal(d.prepare("SELECT count(*) c FROM inbox WHERE source='schedule'").get().c, 1);
  assert.equal(events(d, "schedule_ran").length, 1);
  ok();
  d.close();
});

test("engine wake: 91% weekly usage skips a limit-85 row; a force row runs anyway", () => {
  const w = world();
  tap(w, 91);
  const db = w.db();
  addRow(db, "limited", "echo no", nowS() - 30);
  inbox.insert(db, { source: "schedule", source_id: "forced@now:1", kind: "run",
    payload: { name: "forced", command: "echo yes", cwd: os.tmpdir(), env: {}, skip_if_weekly_usage: 85, force: true } }, nowS());
  db.close();
  const r = w.wake();
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /^p: 1 due, 1 ran, 1 skipped$/m);
  const d = w.db();
  assert.equal(events(d, "schedule_skipped")[0].d.name, "limited");
  const ran = events(d, "schedule_ran");
  assert.equal(ran.length, 1);
  assert.equal(ran[0].d.name, "forced");
  assert.equal(ran[0].d.rc, 0);
  ok();
  d.close();
});

test("engine wake: with the lock held by a live pid it inserts the inbox row and runs nothing", () => {
  const w = world();
  const db = w.db();
  addRow(db, "held", "echo held", nowS() - 30);
  db.close();
  fs.writeFileSync(paths.lockPath("p"), `${process.pid}\n`);
  const r = w.wake();
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /^p: engine running, 1 due$/m);
  const d = w.db();
  assert.equal(d.prepare("SELECT count(*) c FROM inbox WHERE source='schedule' AND state='new'").get().c, 1);
  assert.equal(d.prepare("SELECT count(*) c FROM steps").get().c, 0);
  assert.notEqual(w.tm.run(["has-session", "-t", "=p-bg"]).status, 0);
  assert.equal(fs.readFileSync(paths.lockPath("p"), "utf8").trim(), String(process.pid));
  ok();
  d.close();
});

test("engine wake: an error in one project prints it, the others run, exit 1", () => {
  const w = world();
  const db = w.db("bad");
  db.close();
  fs.writeFileSync(path.join(w.e.engineDir, "bad.sqlite"), "not a database");
  const g = w.db("good");
  addRow(g, "g", "echo g", nowS() - 30);
  g.close();
  const r = w.wake();
  assert.equal(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, /^bad: error: /m);
  assert.match(r.stdout, /^good: 1 due, 1 ran, 0 skipped$/m);
});

test("leak check: the real tmux server has no session p-bg", () => {
  const env = { ...process.env };
  delete env.TMUX;
  delete env.TMUX_TMPDIR;
  const r = cp.spawnSync("tmux", ["has-session", "-t", "=p-bg"], { env, encoding: "utf8" });
  assert.notEqual(r.status, 0, "a session p-bg exists on the real tmux server");
});
