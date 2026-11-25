"use strict";
// Schedule rows (spec 14, Task 5): library functions on a temp database, and the CLI as a child process.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const rebuild = require("../lib/engine/rebuild");
const schedule = require("../lib/engine/schedule");
const rules = require("../lib/engine/schedule_rules");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const NOW = Date.UTC(2026, 0, 5, 12, 0, 0) / 1000;

function fresh() {
  const e = tmpEnv();
  const db = dbm.open("t");
  return { e, db, done() { db.close(); e.restore(); } };
}
const events = (db, kind) => db.prepare("SELECT * FROM events WHERE kind=?").all(kind);
const ok = () => assert.equal(rebuild.check("t").rc, 0, JSON.stringify(rebuild.check("t").diffs));

test("add writes the row and one schedule_added event; again is unchanged; another rule or command throws", () => {
  const f = fresh();
  try {
    const r = schedule.add(f.db, { name: "nightly", rule: " daily 03:30 ", command: "echo hi", cwd: "/w" }, NOW);
    assert.equal(r.status, "added");
    const row = f.db.prepare("SELECT * FROM timers WHERE id='schedule:nightly'").get();
    assert.equal(row.kind, "schedule");
    assert.equal(row.spec, null);
    assert.equal(row.job, null);
    assert.equal(row.fired_at, null);
    assert.equal(row.due_at, rules.nextAfter("daily 03:30", NOW));
    assert.deepEqual(JSON.parse(row.payload), { name: "nightly", command: "echo hi", rule: "daily 03:30", skip_if_weekly_usage: 85, cwd: "/w", env: {} });
    assert.equal(events(f.db, "schedule_added").length, 1);
    ok();
    assert.equal(schedule.add(f.db, { name: "nightly", rule: "daily 03:30", command: "echo hi", cwd: "/w" }, NOW + 5).status, "unchanged");
    assert.equal(events(f.db, "schedule_added").length, 1);
    assert.throws(() => schedule.add(f.db, { name: "nightly", rule: "daily 04:00", command: "echo hi", cwd: "/w" }, NOW), /schedule nightly exists: rm it first/);
    assert.throws(() => schedule.add(f.db, { name: "nightly", rule: "daily 03:30", command: "echo no", cwd: "/w" }, NOW), /exists: rm it first/);
    ok();
  } finally { f.done(); }
});

test("add validates the name and the rule; skip_if_weekly_usage null is kept", () => {
  const f = fresh();
  try {
    assert.throws(() => schedule.add(f.db, { name: "-x", rule: "daily 03:30", command: "c", cwd: "/" }, NOW), /name/);
    assert.throws(() => schedule.add(f.db, { name: "a b", rule: "daily 03:30", command: "c", cwd: "/" }, NOW), /name/);
    assert.throws(() => schedule.add(f.db, { name: "a", rule: "hourly", command: "c", cwd: "/" }, NOW), /bad rule/);
    assert.equal(f.db.prepare("SELECT count(*) c FROM timers").get().c, 0);
    schedule.add(f.db, { name: "a", rule: "every 15m", command: "c", skip_if_weekly_usage: null, cwd: "/", env: { LANG: "C" } }, NOW);
    const p = JSON.parse(f.db.prepare("SELECT payload FROM timers").get().payload);
    assert.equal(p.skip_if_weekly_usage, null);
    assert.deepEqual(p.env, { LANG: "C" });
    assert.equal(f.db.prepare("SELECT due_at FROM timers").get().due_at, rules.nextAfter("every 15m", NOW, NOW));
  } finally { f.done(); }
});

test("list shows active rows by name; rm retires with schedule_removed; add of the retired name replaces it", () => {
  const f = fresh();
  try {
    schedule.add(f.db, { name: "b", rule: "daily 01:00", command: "x", cwd: "/" }, NOW);
    schedule.add(f.db, { name: "a", rule: "daily 02:00", command: "y", cwd: "/" }, NOW);
    assert.deepEqual(schedule.list(f.db).map((r) => r.name), ["a", "b"]);
    assert.equal(schedule.list(f.db)[0].command, "y");
    schedule.rm(f.db, "a", NOW + 1);
    assert.deepEqual(schedule.list(f.db).map((r) => r.name), ["b"]);
    assert.equal(events(f.db, "schedule_removed").length, 1);
    ok();
    assert.throws(() => schedule.rm(f.db, "a", NOW + 2), /no schedule a/);
    assert.throws(() => schedule.rm(f.db, "zzz", NOW + 2), /no schedule zzz/);
    assert.equal(schedule.add(f.db, { name: "a", rule: "daily 05:00", command: "z", cwd: "/" }, NOW + 3).status, "added");
    assert.equal(schedule.list(f.db).find((r) => r.name === "a").command, "z");
    assert.equal(events(f.db, "schedule_added").length, 3);
    ok();
  } finally { f.done(); }
});

test("shellJoin: plain words stay bare, others get single quotes with ' as '\\''", () => {
  assert.equal(schedule.shellJoin(["context", "dream", "--all", "a/b.c:d=e@f%g+h-i"]), "context dream --all a/b.c:d=e@f%g+h-i");
  assert.equal(schedule.shellJoin(["echo", "a b", "it's", ""]), "echo 'a b' 'it'\\''s' ''");
});

// ---- CLI ---------------------------------------------------------------------------------------------------------

function cli(t) {
  const env = tmpEnv();
  t.after(() => env.restore());
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "esch-"));
  t.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  const childEnv = { ...process.env, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state };
  delete childEnv.TC_PROJECT;
  return (args, o = {}) => {
    const r = cp.spawnSync("node", [ENGINE, ...args, ...(o.noProject ? [] : [])], { cwd: o.cwd || cwd, env: childEnv, encoding: "utf8" });
    return { code: r.status, out: r.stdout, err: r.stderr, cwd };
  };
}

test("CLI add prints added with the local next time, again prints unchanged, a different rule exits 1", (t) => {
  const run = cli(t);
  const a = run(["schedule", "add", "n1", "--rule", "daily 03:30", "--project", "t", "--", "echo hi"]);
  assert.equal(a.code, 0, a.err);
  assert.match(a.out, /^added n1: daily 03:30, next \d{4}-\d{2}-\d{2} 03:30\n$/);
  const again = run(["schedule", "add", "n1", "--rule", "daily 03:30", "--project", "t", "--", "echo hi"]);
  assert.equal(again.code, 0);
  assert.equal(again.out, "unchanged n1\n");
  const clash = run(["schedule", "add", "n1", "--rule", "daily 04:00", "--project", "t", "--", "echo hi"]);
  assert.equal(clash.code, 1);
  assert.match(clash.err, /schedule n1 exists: rm it first/);
  ok2();
  function ok2() { assert.equal(rebuild.check("t").rc, 0); }
});

test("CLI add: one word after -- is verbatim, more words are zsh-quoted, flags after -- are command words, cwd is the cwd or the git toplevel", (t) => {
  const run = cli(t);
  assert.equal(run(["schedule", "add", "p", "--rule", "every 5m", "--project", "t", "--", "a | b"]).code, 0);
  assert.equal(run(["schedule", "add", "q", "--rule", "every 5m", "--project", "t", "--skip-if-weekly-usage", "none", "--", "ls", "--rule", "x y"]).code, 0);
  const d = dbm.open("t");
  try {
    const p = JSON.parse(d.prepare("SELECT payload FROM timers WHERE id='schedule:p'").get().payload);
    const q = JSON.parse(d.prepare("SELECT payload FROM timers WHERE id='schedule:q'").get().payload);
    assert.equal(p.command, "a | b");
    assert.equal(q.command, "ls --rule 'x y'");
    assert.equal(q.skip_if_weekly_usage, null);
    assert.equal(p.skip_if_weekly_usage, 85);
    assert.ok(path.isAbsolute(p.cwd));
  } finally { d.close(); }
});

test("CLI add: cwd is the git toplevel of the caller's cwd, else the cwd", (t) => {
  const run = cli(t);
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "esch-repo-"));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  cp.spawnSync("git", ["init", "-q", repo]);
  fs.mkdirSync(path.join(repo, "sub"));
  assert.equal(run(["schedule", "add", "g", "--rule", "every 5m", "--project", "t", "--", "x"], { cwd: path.join(repo, "sub") }).code, 0);
  const plain = run(["schedule", "add", "h", "--rule", "every 5m", "--project", "t", "--", "x"]);
  const d = dbm.open("t");
  try {
    const g = JSON.parse(d.prepare("SELECT payload FROM timers WHERE id='schedule:g'").get().payload);
    const h = JSON.parse(d.prepare("SELECT payload FROM timers WHERE id='schedule:h'").get().payload);
    assert.equal(fs.realpathSync(g.cwd), fs.realpathSync(repo));
    assert.equal(fs.realpathSync(h.cwd), fs.realpathSync(plain.cwd));
  } finally { d.close(); }
});

test("CLI add: bad name, bad rule, missing command, bad skip value exit 2 with usage", (t) => {
  const run = cli(t);
  const base = ["schedule", "add"];
  for (const args of [
    [...base, "-x", "--rule", "daily 03:30", "--project", "t", "--", "c"],
    [...base, "n", "--rule", "nope", "--project", "t", "--", "c"],
    [...base, "n", "--rule", "daily 03:30", "--project", "t"],
    [...base, "n", "--rule", "daily 03:30", "--project", "t", "--"],
    [...base, "n", "--project", "t", "--", "c"],
    [...base, "n", "--rule", "daily 03:30", "--skip-if-weekly-usage", "101", "--project", "t", "--", "c"],
    [...base, "n", "--rule", "daily 03:30", "--skip-if-weekly-usage", "abc", "--project", "t", "--", "c"],
    ["schedule", "--project", "t"],
    ["schedule", "bogus", "--project", "t"],
  ]) {
    const r = run(args);
    assert.equal(r.code, 2, args.join(" ") + " " + r.err);
    assert.match(r.err, /usage/);
  }
});

test("CLI list, rm, unknown rm, add after rm; rebuild stays clean", (t) => {
  const run = cli(t);
  assert.equal(run(["schedule", "list", "--project", "t"]).out, "no schedules\n");
  run(["schedule", "add", "b", "--rule", "weekly Sun 07:00", "--project", "t", "--", "scout", "weekly"]);
  run(["schedule", "add", "a", "--rule", "daily 03:30", "--project", "t", "--", "echo hi"]);
  const l = run(["schedule", "list", "--project", "t"]);
  assert.equal(l.code, 0);
  const lines = l.out.trim().split("\n");
  assert.match(lines[0], /^a {2}daily 03:30 {2}next \d{4}-\d{2}-\d{2} 03:30 {2}echo hi$/);
  assert.match(lines[1], /^b {2}weekly Sun 07:00 {2}next \d{4}-\d{2}-\d{2} 07:00 {2}scout weekly$/);
  const rm = run(["schedule", "rm", "a", "--project", "t"]);
  assert.equal(rm.code, 0);
  assert.equal(rm.out, "removed a\n");
  const again = run(["schedule", "rm", "a", "--project", "t"]);
  assert.equal(again.code, 1);
  assert.match(again.err, /no schedule a/);
  assert.equal(run(["schedule", "rm", "--project", "t"]).code, 2);
  assert.equal(run(["schedule", "add", "a", "--rule", "daily 04:00", "--project", "t", "--", "z"]).code, 0);
  assert.equal(rebuild.check("t").rc, 0);
});

test("CLI takes the project from TC_PROJECT", (t) => {
  const env = tmpEnv();
  t.after(() => env.restore());
  const r = cp.spawnSync("node", [ENGINE, "schedule", "list"], { env: { ...process.env, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: "t" }, encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "no schedules\n");
});
