"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, scratchTmux, gitRepo } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const steps = require("../lib/engine/steps");
const feed = require("../lib/engine/feed");
const paths = require("../lib/engine/paths");

const REPO = path.resolve(__dirname, "../..");
const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

function env() {
  const e = tmpEnv();
  cleanups.push(() => e.restore());
  const db = dbm.open("p");
  return { e, db };
}

// A fake tmux-ctl: logs argv; `metrics has start|run` exits 0 when <dir>/has-<which> exists, else 1.
function fakeTmuxCtl(dir) {
  const bin = path.join(dir, "fake-tmux-ctl");
  const log = path.join(dir, "tc.log");
  fs.writeFileSync(bin, `#!/bin/sh\necho "$@" >> "${log}"\nif [ "$1 $2" = "metrics has" ]; then [ -e "${dir}/has-$3" ]; exit $?; fi\nexit 0\n`, { mode: 0o755 });
  return { bin, calls: (re) => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter((l) => re.test(l)).length : 0) };
}

const stateOf = (db, key) => db.prepare("SELECT state FROM steps WHERE key=?").get(key).state;

test("run: intent then done, each in its own tx with an event carrying rows", () => {
  const { db } = env();
  const seen = [];
  const r = steps.run(db, { key: "k1", spec: "s", kind: "merge" }, () => { seen.push(stateOf(db, "k1")); return { sha: "abc" }; }, { now: 5 });
  assert.deepEqual(seen, ["intent"]);
  assert.deepEqual(r, { result: { sha: "abc" } });
  assert.equal(stateOf(db, "k1"), "done");
  const evs = db.prepare("SELECT kind, detail FROM events ORDER BY seq").all();
  assert.deepEqual(evs.map((x) => x.kind), ["step_intent", "step_done"]);
  const d = JSON.parse(evs[1].detail);
  assert.equal(d.rows[0].table, "steps");
  assert.equal(d.rows[0].row.state, "done");
  assert.equal(d.rows[0].row.created_at, 5);
});

test("run: a done key returns the stored result without acting; a throw records failed and rethrows", () => {
  const { db } = env();
  steps.run(db, { key: "k", spec: "s", kind: "push" }, () => ({ n: 1 }));
  let acted = 0;
  const r = steps.run(db, { key: "k", spec: "s", kind: "push" }, () => { acted++; return { n: 2 }; });
  assert.deepEqual(r, { result: { n: 1 }, reused: true });
  assert.equal(acted, 0);
  assert.throws(() => steps.run(db, { key: "bad", spec: "s", kind: "push" }, () => { throw new Error("boom"); }), /boom/);
  assert.equal(stateOf(db, "bad"), "failed");
  assert.match(db.prepare("SELECT result FROM steps WHERE key='bad'").get().result, /boom/);
  assert.deepEqual(db.prepare("SELECT kind FROM events WHERE kind='step_failed'").all().length, 1);
});

// Simulates the engine killed after intent: only begin() ran. Then reconcile; if not done, resume once.
function killedThenResume(db, ctx, desc, act) {
  steps.begin(db, desc);
  const rec = steps.reconcile(db, ctx);
  if (rec.rerun.length) {
    assert.equal(rec.rerun[0].key, desc.key);
    steps.run(db, desc, act);
  }
  return rec;
}

test("merge: killed, merged -> not re-run; killed, not merged -> merged exactly once", () => {
  const { db } = env();
  const repo = gitRepo(); cleanups.push(repo.cleanup);
  repo.git("checkout", "-q", "-b", "feat"); fs.writeFileSync(path.join(repo.dir, "f"), "1"); repo.git("add", "f"); repo.git("commit", "-q", "-m", "f");
  repo.git("checkout", "-q", "main");
  const ctx = { repo: repo.dir, mainRepo: repo.dir, target: "main" };
  const merges = () => Number(repo.git("rev-list", "--merges", "--count", "main").trim());
  const desc = { key: "merge:feat@x", spec: "s", kind: "merge", facts: { branch: "feat", target: "main" } };
  let acted = 0;
  const act = () => { acted++; repo.git("merge", "--no-ff", "-q", "-m", "m\n\nEngine-Step: merge:feat@x", "feat"); return {}; };
  const rec = killedThenResume(db, ctx, desc, act);
  assert.equal(rec.rerun.length, 1);
  assert.equal(merges(), 1);
  assert.equal(stateOf(db, desc.key), "done");
  // killed again after the merge happened: observed done
  const d2 = { ...desc, key: "merge:feat@y" };
  steps.begin(db, d2);
  const rec2 = steps.reconcile(db, ctx);
  assert.deepEqual(rec2.rerun, []);
  assert.equal(stateOf(db, d2.key), "done");
  assert.equal(acted, 1);
  assert.equal(merges(), 1);
});

for (const [kind, which] of [["metrics_start", "start"], ["metrics_record", "run"]]) {
  test(`${kind}: killed, recorded -> not re-run; not recorded -> one call`, () => {
    const { e, db } = env();
    const fake = fakeTmuxCtl(e.root);
    const ctx = { tmuxCtl: fake.bin };
    const facts = { spec: "sp", batch: "b1" };
    const call = () => { cp.spawnSync(fake.bin, ["metrics", which === "start" ? "start" : "record", "--spec", "sp"]); return {}; };
    const rec = killedThenResume(db, ctx, { key: `${kind}:1`, spec: "sp", kind, facts }, call);
    assert.equal(rec.rerun.length, 1);
    assert.equal(fake.calls(new RegExp(`^metrics ${which === "start" ? "start" : "record"} `)), 1);
    assert.match(fs.readFileSync(path.join(e.root, "tc.log"), "utf8"), new RegExp(`metrics has ${which} --spec sp --batch b1`));
    fs.writeFileSync(path.join(e.root, `has-${which}`), "");
    const d2 = { key: `${kind}:2`, spec: "sp", kind, facts };
    const rec2 = killedThenResume(db, ctx, d2, call);
    assert.deepEqual(rec2.rerun, []);
    assert.equal(stateOf(db, d2.key), "done");
    assert.equal(fake.calls(new RegExp(`^metrics ${which === "start" ? "start" : "record"} `)), 1);
  });
}

for (const kind of ["revert", "commit_report", "commit_ledger"]) {
  test(`${kind}: killed, committed with Engine-Step -> not re-run; else one commit`, () => {
    const { db } = env();
    const repo = gitRepo(); cleanups.push(repo.cleanup);
    const ctx = { repo: repo.dir, mainRepo: repo.dir, target: "main" };
    const commit = (key) => { fs.writeFileSync(path.join(repo.dir, "x"), key); repo.git("add", "x"); repo.git("commit", "-q", "-m", `c\n\nEngine-Step: ${key}`); return {}; };
    const count = () => Number(repo.git("rev-list", "--count", "main").trim());
    let acted = 0;
    const k1 = `${kind}:a`;
    const rec = killedThenResume(db, ctx, { key: k1, spec: "s", kind }, () => { acted++; return commit(k1); });
    assert.equal(rec.rerun.length, 1);
    assert.equal(count(), 2);
    // a different key's commit does not satisfy this key (prefix safety)
    const k2 = `${kind}:a2`;
    commit(k2);
    const rec2 = killedThenResume(db, ctx, { key: `${kind}:a2x`, spec: "s", kind }, () => ({}));
    assert.equal(rec2.rerun.length, 1);
    // killed after the commit: observed done
    steps.begin(db, { key: k2, spec: "s", kind });
    assert.deepEqual(steps.reconcile(db, ctx).rerun, []);
    assert.equal(stateOf(db, k2), "done");
    assert.equal(acted, 1);
  });
}

test("push: sha equal -> done; differs -> not_done; unreachable -> park", () => {
  const { db } = env();
  const repo = gitRepo(); cleanups.push(repo.cleanup);
  const remote = fs.mkdtempSync(path.join(os.tmpdir(), "erem-")); cleanups.push(() => fs.rmSync(remote, { recursive: true, force: true }));
  cp.execFileSync("git", ["init", "-q", "--bare", remote]);
  repo.git("remote", "add", "origin", remote);
  const sha = repo.git("rev-parse", "HEAD").trim();
  const ctx = { repo: repo.dir, mainRepo: repo.dir, target: "main" };
  const facts = { remote: "origin", ref: "refs/heads/feat", sha };
  steps.begin(db, { key: "push:1", spec: "s", kind: "push", facts });
  let rec = steps.reconcile(db, ctx);
  assert.equal(rec.rerun.length, 1);                     // not pushed yet
  let pushes = 0;
  steps.run(db, { key: "push:1", spec: "s", kind: "push", facts }, () => { pushes++; repo.git("push", "-q", "origin", `${sha}:refs/heads/feat`); return {}; });
  steps.begin(db, { key: "push:2", spec: "s", kind: "push", facts });   // killed after push
  rec = steps.reconcile(db, ctx);
  assert.deepEqual(rec.rerun, []);
  assert.equal(stateOf(db, "push:2"), "done");
  assert.equal(pushes, 1);
  steps.begin(db, { key: "push:3", spec: "s", kind: "push", facts: { ...facts, sha: "0".repeat(40) } });
  assert.equal(steps.reconcile(db, ctx).rerun.length, 1);   // remote ref has another sha
  repo.git("remote", "set-url", "origin", path.join(remote, "nope"));
  steps.begin(db, { key: "push:4", spec: "s", kind: "push", facts });
  rec = steps.reconcile(db, ctx);
  assert.deepEqual(rec.park.filter((x) => x.key === "push:4"), [{ key: "push:4", question: "could not tell whether push:4 ran" }]);
  assert.equal(rec.park.length, 2); // push:3 also: the remote is unreachable now
  assert.equal(stateOf(db, "push:4"), "intent");
});

test("worktree_remove: path still listed -> removed once; already gone -> not re-run", () => {
  const { db } = env();
  const repo = gitRepo(); cleanups.push(repo.cleanup);
  const wt = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ewt-")), "w"); cleanups.push(() => fs.rmSync(path.dirname(wt), { recursive: true, force: true }));
  repo.git("worktree", "add", "-q", "-b", "wb", wt);
  const ctx = { repo: repo.dir, mainRepo: repo.dir, target: "main" };
  let acted = 0;
  const act = () => { acted++; repo.git("worktree", "remove", "--force", wt); return {}; };
  const rec = killedThenResume(db, ctx, { key: "wr:1", spec: "s", kind: "worktree_remove", facts: { path: wt } }, act);
  assert.equal(rec.rerun.length, 1);
  assert.equal(acted, 1);
  steps.begin(db, { key: "wr:2", spec: "s", kind: "worktree_remove", facts: { path: wt } });
  assert.deepEqual(steps.reconcile(db, ctx).rerun, []);
  assert.equal(acted, 1);
});

// tmux kinds against a scratch server
test("start_worker adopts the pane of an existing window; close_window checks the pane is gone", (t) => {
  const { db } = env();
  const tm = scratchTmux(); cleanups.push(() => tm.kill());
  const started = tm.run(["new-session", "-d", "-s", "S", "-n", "w0"]);
  if (started.status !== 0) return t.skip("tmux unavailable");
  const sock = tm.run(["display-message", "-p", "-t", "S", "#{socket_path}"]).stdout.trim();
  const oldTmp = process.env.TMUX_TMPDIR;
  process.env.TMUX_TMPDIR = path.dirname(path.dirname(sock));
  cleanups.push(() => { if (oldTmp === undefined) delete process.env.TMUX_TMPDIR; else process.env.TMUX_TMPDIR = oldTmp; });
  const ctx = { session: "S", tmuxArgs: ["-L", tm.socket] };
  // not done: no window named "job-a"
  let acted = 0;
  const act = () => { acted++; tm.run(["new-window", "-d", "-t", "=S:", "-n", "job-a"]); return {}; };
  const rec = killedThenResume(db, ctx, { key: "sw:1", spec: "s", kind: "start_worker", facts: { window: "job-a" } }, act);
  assert.equal(rec.rerun.length, 1);
  assert.equal(acted, 1);
  // killed after the window exists: done, pane adopted, not started again
  steps.begin(db, { key: "sw:2", spec: "s", kind: "start_worker", facts: { window: "job-a" } });
  assert.deepEqual(steps.reconcile(db, ctx).rerun, []);
  const pane = tm.run(["list-windows", "-t", "=S:", "-F", "#{window_name} #{pane_id}"]).stdout.split("\n").find((l) => l.startsWith("job-a ")).split(" ")[1];
  assert.equal(JSON.parse(db.prepare("SELECT result FROM steps WHERE key='sw:2'").get().result).pane, pane);
  assert.equal(acted, 1);
  // close_window: pane present -> not_done, then gone -> done
  steps.begin(db, { key: "cw:1", spec: "s", kind: "close_window", facts: { pane } });
  assert.equal(steps.reconcile(db, ctx).rerun.length, 1);
  tm.run(["kill-pane", "-t", pane]);
  assert.deepEqual(steps.reconcile(db, ctx).rerun, []);
  assert.equal(stateOf(db, "cw:1"), "done");
});

test("reconcile parks a row of an unknown kind", () => {
  const { db } = env();
  steps.begin(db, { key: "z", spec: "s", kind: "nope" });
  assert.deepEqual(steps.reconcile(db, {}).park, [{ key: "z", question: "could not tell whether z ran" }]);
});

// ---- feed ----
const ev = (kind, o = {}) => ({ ts: 100.5, spec: "/a/b/2026-11-23-x-design.md#part-2", job: null, kind, detail: { rows: [], ...(o.detail || {}) }, ...o.top });

test("feed.publish: tier map, spec name, text, refs", () => {
  const { e } = env();
  const tiers = {
    fail_spec: "critical", engine_error: "critical", park: "decision", awaiting_you: "decision",
    job_done: "progress", review: "progress", integrated: "progress", spec_done: "progress", step_done: "routine", task_complete: "routine",
  };
  for (const [k, t] of Object.entries(tiers)) feed.publish("p", ev(k));
  feed.publish("p", ev("ruling"));
  feed.publish("p", ev("job_done", { detail: { text: "x".repeat(400) + "\nmore" }, top: { job: "s:implement1:1" } }));
  const lines = fs.readFileSync(paths.feedPath("p"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const n = Object.keys(tiers).length;
  assert.deepEqual(lines.slice(0, n).map((l) => l.tier), Object.values(tiers));
  assert.equal(lines[n].tier, "routine");
  assert.equal(lines[0].spec, "2026-11-23-x-design");
  assert.equal(lines[0].project, "p");
  assert.equal(lines[0].text, "fail_spec");
  assert.deepEqual(lines[0].refs, {});
  const last = lines[n + 1];
  assert.equal(last.text.length, 300);
  assert.ok(!last.text.includes("\n"));
  assert.ok(last.text.startsWith("job_done: xxx"));
  assert.deepEqual(last.refs, { run: "s:implement1:1" });
  assert.ok(e);
});

test("feed.publish never throws on an unwritable path", () => {
  const { e } = env();
  fs.writeFileSync(path.join(e.state, "feed"), "a file, so feed/ cannot be a directory");
  assert.doesNotThrow(() => feed.publish("p", ev("merge")));
  assert.doesNotThrow(() => feed.publish("p", null));
});

test("feed line parses with board/discord_feed.read_events", () => {
  const { e } = env();
  feed.publish("p", ev("park", { detail: { question: "which way?" } }));
  const code = "import sys; sys.path.insert(0, sys.argv[1]); import json, discord_feed as d; evs, off = d.read_events('p'); print(json.dumps(evs))";
  const r = cp.spawnSync("python3", ["-I", "-c", code, path.join(REPO, "board")], { encoding: "utf8", env: { ...process.env, TC_STATE: e.state } });
  assert.equal(r.status, 0, r.stderr);
  const evs = JSON.parse(r.stdout);
  assert.equal(evs.length, 1);
  assert.equal(evs[0].tier, "decision");
  assert.equal(evs[0].text, "park: which way?");
  assert.equal(evs[0].spec, "2026-11-23-x-design");
});
