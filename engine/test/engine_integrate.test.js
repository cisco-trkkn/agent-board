"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const integrate = require("../lib/engine/integrate");
const ledger = require("../lib/engine/ledger");

const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

// Main repo with engine.json committed, a bare `origin`, a feature branch in its own worktree, a fake
// tmux-ctl and a fake gh/glab that log argv.
function setup({ test: testCmd = "true", remoteUrl, integration = "merge", push = 1, branch = "feat-a" } = {}) {
  const e = tmpEnv();
  cleanups.push(() => e.restore());
  const g = gitRepo();
  cleanups.push(() => g.cleanup());
  const bare = path.join(e.root, "remote.git");
  cp.execFileSync("git", ["init", "-q", "--bare", bare]);
  g.git("remote", "add", "origin", bare);
  fs.mkdirSync(path.join(g.dir, "docs/superpowers"), { recursive: true });
  fs.writeFileSync(path.join(g.dir, "docs/superpowers/engine.json"), JSON.stringify({ test: testCmd }));
  g.git("add", "docs/superpowers/engine.json");
  g.git("commit", "-q", "-m", "engine.json");
  g.git("push", "-q", "origin", "main");
  const base = g.git("rev-parse", "HEAD").trim();
  const wt = path.join(e.root, "wt");
  g.git("worktree", "add", "-q", "-b", branch, wt, "main");
  fs.writeFileSync(path.join(wt, "feature.txt"), "f\n");
  cp.execFileSync("git", ["-C", wt, "add", "feature.txt"]);
  cp.execFileSync("git", ["-C", wt, "commit", "-q", "-m", "feat"]);
  const bin = path.join(e.root, "bin");
  fs.mkdirSync(bin);
  const log = path.join(e.root, "calls.log");
  for (const n of ["gh", "glab"]) fs.writeFileSync(path.join(bin, n), `#!/bin/sh\necho "${n} $@" >> "${log}"\necho https://example.test/pr/1\n`, { mode: 0o755 });
  const tc = path.join(bin, "tmux-ctl");
  fs.writeFileSync(tc, `#!/bin/sh\necho "tmux-ctl $@" >> "${log}"\nexit 0\n`, { mode: 0o755 });
  if (remoteUrl) g.git("remote", "set-url", "origin", remoteUrl);
  const db = dbm.open("p");
  const spec = { id: "s1", integration, push, batch: "b1", branch, worktree: wt, base, plan: "docs/superpowers/plans/2026-11-23-demo.md" };
  const ctx = { db, repo: g.dir, worktree: wt, tmuxCtl: tc, tasks: [], now: 1, env: { PATH: `${bin}:${process.env.PATH}` } };
  const calls = () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter(Boolean) : []);
  const keys = () => db.prepare("SELECT key, state FROM steps ORDER BY created_at, key").all();
  return { e, g, db, spec, ctx, bare, wt, calls, keys, base };
}

const msgs = (g) => g.git("log", "--format=%B%x00", "main").split("\0");

test("merge: tests before and after, merge commit with trailer, ledger, metrics record, worktree removed", () => {
  const s = setup();
  s.db.prepare("INSERT INTO events (ts, spec, kind, detail) VALUES (1, 's1', 'dispatched', ?)").run(JSON.stringify({ task: 1, window: "w", tier: "standard", model: "sonnet" }));
  const r = integrate.run(s.ctx, s.spec);
  assert.equal(r.outcome, "merged");
  assert.ok(fs.existsSync(path.join(s.g.dir, "feature.txt")));
  const key = `merge:feat-a@${s.base}`;
  assert.ok(msgs(s.g).some((m) => m.split("\n").includes(`Engine-Step: ${key}`)));
  assert.ok(msgs(s.g).some((m) => m.split("\n").includes("Engine-Step: commit_ledger:s1")));
  const ledgerFile = path.join(s.g.dir, "docs/superpowers/ledgers/2026-11-23-demo/progress.md");
  assert.match(fs.readFileSync(ledgerFile, "utf8"), /Task 1: dispatched w \(standard, sonnet\)/);
  assert.deepEqual(s.calls(), ["tmux-ctl metrics record s1 --batch b1 --outcome merged"]);
  assert.ok(!fs.existsSync(s.wt));
  assert.ok(s.g.git("branch", "--list", "feat-a").includes("feat-a"));
  assert.deepEqual(s.keys().map((k) => k.state), ["done", "done", "done", "done"]);
  assert.deepEqual(s.keys().map((k) => k.key).sort(), [key, "commit_ledger:s1", "metrics_record:s1", "worktree_remove:s1"].sort());
  // a second run reuses every step: no new commit, no second metrics call
  const head = s.g.git("rev-parse", "HEAD");
  assert.equal(integrate.run(s.ctx, s.spec).outcome, "merged");
  assert.equal(s.g.git("rev-parse", "HEAD"), head);
  assert.equal(s.calls().length, 1);
});

test("tests red before: nothing merged", () => {
  const s = setup({ test: "false" });
  assert.deepEqual(integrate.run(s.ctx, s.spec), { outcome: "tests_red_before" });
  assert.ok(!fs.existsSync(path.join(s.g.dir, "feature.txt")));
  assert.deepEqual(s.keys(), []);
  assert.deepEqual(s.calls(), []);
});

test("without engine.json test: every task's verifyCommand in order", () => {
  const s = setup();
  fs.unlinkSync(path.join(s.g.dir, "docs/superpowers/engine.json"));
  s.g.git("commit", "-q", "-am", "drop engine.json");
  const mark = path.join(s.e.root, "order");
  s.ctx.tasks = [{ n: 1, verifyCommand: `echo one >> ${mark}` }, { n: 2, verifyCommand: `echo two >> ${mark}` }];
  assert.equal(integrate.run(s.ctx, s.spec).outcome, "merged");
  assert.equal(fs.readFileSync(mark, "utf8"), "one\ntwo\none\ntwo\n");
  s.ctx.tasks = [{ n: 1, verifyCommand: "false" }];
  const s2 = setup();
  fs.unlinkSync(path.join(s2.g.dir, "docs/superpowers/engine.json"));
  s2.g.git("commit", "-q", "-am", "drop");
  s2.ctx.tasks = [{ n: 1, verifyCommand: "false" }];
  assert.equal(integrate.run(s2.ctx, s2.spec).outcome, "tests_red_before");
});

test("live checkout dirty: parked, nothing changed; .claude/ and metrics lines do not count", () => {
  const s = setup();
  fs.writeFileSync(path.join(s.g.dir, "scratch.txt"), "x");
  const r = integrate.run(s.ctx, s.spec);
  assert.deepEqual(r, { outcome: "parked", question: "live checkout is mid-change", recommendation: { option: "approve", why: "approve retries once the live checkout is clean", confidence: "low" } });
  assert.deepEqual(s.keys(), []);
  assert.ok(!fs.existsSync(path.join(s.g.dir, "feature.txt")));
  fs.unlinkSync(path.join(s.g.dir, "scratch.txt"));
  fs.mkdirSync(path.join(s.g.dir, ".claude"));
  fs.writeFileSync(path.join(s.g.dir, ".claude/x"), "x");
  fs.mkdirSync(path.join(s.g.dir, "docs/superpowers/metrics"), { recursive: true });
  fs.writeFileSync(path.join(s.g.dir, "docs/superpowers/metrics/runs.jsonl"), "{}\n");
  assert.equal(integrate.run(s.ctx, s.spec).outcome, "merged");
});

test("tests red after the merge: tests_red, then revert commit, branch kept, never a reset", () => {
  // green in the worktree, red in the main checkout
  const s = setup({ test: `[ "$(basename "$PWD")" = wt ]` });
  const r = integrate.run(s.ctx, s.spec);
  assert.equal(r.outcome, "tests_red");
  assert.equal(s.g.git("rev-parse", "HEAD").trim(), r.merge);
  assert.deepEqual(s.calls(), []);
  const rv = integrate.revert(s.ctx, s.spec);
  assert.equal(rv.outcome, "reverted");
  assert.equal(rv.merge, r.merge);
  assert.ok(!fs.existsSync(path.join(s.g.dir, "feature.txt")));
  assert.equal(s.g.git("rev-parse", "HEAD").trim(), rv.revert);
  assert.equal(s.g.git("rev-parse", "HEAD~1").trim(), r.merge, "a revert commit on top, history kept");
  assert.ok(msgs(s.g)[0].split("\n").includes(`Engine-Step: revert:${r.merge}`));
  assert.ok(s.g.git("branch", "--list", "feat-a").includes("feat-a"));
  assert.ok(fs.existsSync(s.wt), "worktree untouched");
  const before = s.g.git("rev-parse", "HEAD");
  integrate.revert(s.ctx, s.spec);
  assert.equal(s.g.git("rev-parse", "HEAD"), before, "revert step written once");
  assert.equal(s.db.prepare("SELECT count(*) c FROM steps WHERE key=?").get(`revert:${r.merge}`).c, 1);
});

test("mr on github.com: push then gh pr create", () => {
  const s = setup({ integration: "mr", remoteUrl: null });
  s.g.git("remote", "set-url", "--push", "origin", s.bare);
  s.g.git("config", "url." + s.bare + ".insteadOf", "https://github.com/o/r.git");
  s.g.git("remote", "set-url", "origin", "https://github.com/o/r.git");
  const r = integrate.run(s.ctx, s.spec);
  assert.equal(r.outcome, "mr https://example.test/pr/1");
  assert.ok(s.g.git("--git-dir", s.bare, "branch", "--list", "feat-a").includes("feat-a"));
  assert.ok(s.calls().includes("gh pr create --base main --head feat-a --fill"));
  assert.ok(s.calls().includes("tmux-ctl metrics record s1 --batch b1 --outcome mr https://example.test/pr/1"));
  assert.ok(!fs.existsSync(path.join(s.g.dir, "feature.txt")), "mr does not merge");
  assert.ok(fs.existsSync(s.wt), "mr keeps the worktree");
  assert.equal(s.keys().filter((k) => k.key.startsWith("push:")).length, 1);
  assert.deepEqual(s.keys().filter((k) => k.state !== "done"), []);
});

test("mr elsewhere: glab mr create", () => {
  const s = setup({ integration: "mr" });
  assert.match(integrate.run(s.ctx, s.spec).outcome, /^mr https:/);
  assert.ok(s.calls().includes("glab mr create --target-branch main --source-branch feat-a --fill --yes"));
  assert.ok(!s.calls().some((c) => c.startsWith("gh ")));
});

test("mr without push consent: parked, no push, no gh", () => {
  const s = setup({ integration: "mr", push: 0 });
  const r = integrate.run(s.ctx, s.spec);
  assert.equal(r.outcome, "parked");
  assert.match(r.question, /no stored consent/);
  assert.equal(r.recommendation, undefined, "the policy default (stop_class: deny) applies");
  assert.equal(s.g.git("--git-dir", s.bare, "branch", "--list", "feat-a").trim(), "");
  assert.deepEqual(s.calls(), []);
});

test("mr never pushes main or master", () => {
  for (const branch of ["main", "master"]) {
    const s = setup({ integration: "mr", branch: branch === "main" ? "wt-main" : "master" });
    s.spec.branch = branch;
    const before = s.g.git("--git-dir", s.bare, "rev-parse", "main").trim();
    const r = integrate.run(s.ctx, { ...s.spec, base: s.base });
    assert.equal(r.outcome, "parked", branch);
    assert.match(r.question, /protected branch/);
    assert.deepEqual(s.calls(), []);
    assert.equal(s.g.git("--git-dir", s.bare, "rev-parse", "main").trim(), before);
  }
});

test("keep: kept <branch>, no merge, no push", () => {
  const s = setup({ integration: "keep" });
  assert.equal(integrate.run(s.ctx, s.spec).outcome, "kept feat-a");
  assert.ok(!fs.existsSync(path.join(s.g.dir, "feature.txt")));
  assert.equal(s.g.git("--git-dir", s.bare, "branch", "--list", "feat-a").trim(), "");
  assert.deepEqual(s.calls(), ["tmux-ctl metrics record s1 --batch b1 --outcome kept feat-a"]);
  assert.ok(fs.existsSync(s.wt));
  assert.deepEqual(s.keys().map((k) => k.key.split(":")[0]).sort(), ["commit_ledger", "metrics_record"]);
});

const hasLedger = (g, ref) => g.git("log", "--format=%B%x00", ref).split("\0").some((m) => m.split("\n").includes("Engine-Step: commit_ledger:s1"));

test("mr: ledger commit is on the spec branch before the push, main gets none, resume does not commit again", () => {
  const s = setup({ integration: "mr" });
  const mainHead = s.g.git("rev-parse", "main").trim();
  assert.match(integrate.run(s.ctx, s.spec).outcome, /^mr https:/);
  assert.ok(hasLedger(s.g, "feat-a"), "ledger on the spec branch");
  assert.ok(hasLedger(s.g, "refs/heads/feat-a") && s.g.git("--git-dir", s.bare, "log", "--format=%B", "feat-a").includes("Engine-Step: commit_ledger:s1"), "the push carried the ledger commit");
  assert.equal(s.g.git("rev-parse", "main").trim(), mainHead, "main has no new commit");
  assert.ok(fs.existsSync(path.join(s.wt, "docs/superpowers/ledgers/2026-11-23-demo/progress.md")));
  assert.ok(!fs.existsSync(path.join(s.g.dir, "docs/superpowers/ledgers")));
  // resume: a done commit_ledger row is put back to intent (killed after the commit); the CHECK reads the spec branch and finds it
  const branchHead = s.g.git("rev-parse", "feat-a").trim();
  s.db.prepare("UPDATE steps SET state='intent' WHERE key='commit_ledger:s1'").run();
  const rec = require("../lib/engine/steps").reconcile(s.db, { repo: s.g.dir, mainRepo: s.g.dir, target: "main", tmuxCtl: s.ctx.tmuxCtl });
  assert.deepEqual(rec.rerun, []);
  assert.equal(s.db.prepare("SELECT state FROM steps WHERE key=?").get("commit_ledger:s1").state, "done");
  assert.equal(s.g.git("rev-parse", "feat-a").trim(), branchHead);
});

test("keep: ledger commit is on the spec branch, main unchanged", () => {
  const s = setup({ integration: "keep" });
  const mainHead = s.g.git("rev-parse", "main").trim();
  assert.equal(integrate.run(s.ctx, s.spec).outcome, "kept feat-a");
  assert.ok(hasLedger(s.g, "feat-a"));
  assert.ok(!hasLedger(s.g, "main"));
  assert.equal(s.g.git("rev-parse", "main").trim(), mainHead);
});

// ---- ledger ----------------------------------------------------------------------------------------------

test("ledger.render lines are counted by metrics.py ledger_fields", () => {
  const ev = [
    { kind: "dispatched", detail: { task: 1, window: "w1", tier: "standard", model: "sonnet" } },
    { kind: "green_check", detail: { task: 1, sha: "abc1234" } },
    { kind: "review", detail: { task: 1, findings: 2, text: "missing guard" } },
    { kind: "fix_round", detail: { task: 1, round: 1 } },
    { kind: "review", detail: { task: 1, findings: 1 } },
    { kind: "fix_round", detail: { task: 1, round: 2 } },
    { kind: "review", detail: { task: 1, findings: 0 } },
    { kind: "minor", detail: JSON.stringify({ task: 1, text: "naming" }) },
    { kind: "ruling", detail: { text: "proceed", cost: "a finding left open" } },
    { kind: "ruling", detail: { text: "retry", cost: "one more run" } },
    { kind: "fix_wave", detail: {} },
    { kind: "task_complete", detail: { task: 1, first: "a1", last: "b2" } },
    { kind: "step_done", detail: {} },
  ];
  const text = ledger.render(ev);
  for (const l of [
    "Task 1: dispatched w1 (standard, sonnet)", "Task 1: green check ok (verify rc 0) — abc1234", "Task 1: fix round 1",
    "Task 1: minor (deferred): naming", "Ruling: proceed — a finding left open", "Final review: fix wave",
    "Task 1: complete (commits a1..b2, review clean)",
  ]) assert.ok(text.split("\n").includes(l), l);
  const py = `import json,sys\nsys.path.insert(0, ${JSON.stringify(path.resolve(__dirname, "../../board"))})\nimport metrics\nprint(json.dumps(metrics.ledger_fields(sys.stdin.read(), "")))`;
  const r = cp.spawnSync("python3", ["-I", "-c", py], { input: text, encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), { bounces: 2, fix_rounds: 2, fix_wave: true, rulings: 2, parked: 1, final_findings: 0 });
});

// ---- task 8b: a failed spec's ledger goes on the spec branch ---------------------------------------------------
// Mutation run for this guard: `outcome.startsWith("failed")` dropped from the onSpecBranch test in commitLedger ->
// the merge-integration case fails (the ledger lands on main, and main's HEAD moves).
for (const outcome of ["failed — implement1: gone", "failed", "denied: user gate: task 1 T1"]) {
  test(`finalize(${outcome}) on a merge spec: ledger on the spec branch, main untouched, resume does not commit again`, () => {
    const s = setup({ integration: "merge" });
    const mainHead = s.g.git("rev-parse", "main").trim();
    integrate.finalize(s.ctx, s.spec, outcome);
    assert.ok(hasLedger(s.g, "feat-a"), "ledger on the spec branch");
    assert.ok(!hasLedger(s.g, "main"));
    assert.equal(s.g.git("rev-parse", "main").trim(), mainHead, "main's HEAD unchanged");
    assert.ok(!fs.existsSync(path.join(s.g.dir, "docs/superpowers/ledgers")), "main checkout untouched");
    assert.ok(fs.existsSync(s.wt), "worktree kept");
    const branchHead = s.g.git("rev-parse", "feat-a").trim();
    integrate.finalize(s.ctx, s.spec, outcome); // resume after a done commit_ledger
    assert.equal(s.g.git("rev-parse", "feat-a").trim(), branchHead, "no second ledger commit");
  });
}

// Measurement never blocks a spec: no batch -> no `metrics record`; a failing record leaves its step failed.
for (const integration of ["keep", "mr", "merge"]) {
  test(`${integration} with no batch: metrics record is not run, the outcome is reached`, () => {
    const s = setup({ integration, remoteUrl: null });
    if (integration === "mr") {
      s.g.git("remote", "set-url", "--push", "origin", s.bare);
      s.g.git("config", "url." + s.bare + ".insteadOf", "https://github.com/o/r.git");
      s.g.git("remote", "set-url", "origin", "https://github.com/o/r.git");
    }
    s.spec.batch = null;
    const r = integrate.run(s.ctx, s.spec);
    assert.match(r.outcome, integration === "keep" ? /^kept / : integration === "mr" ? /^mr / : /^merged$/);
    assert.ok(!s.calls().some((c) => c.startsWith("tmux-ctl")), s.calls().join("|"));
    assert.ok(!s.keys().some((k) => k.key.startsWith("metrics_record")));
  });
}

test("merge with a batch and a failing metrics record: step failed, outcome reached, worktree still removed", () => {
  const s = setup();
  fs.writeFileSync(s.ctx.tmuxCtl, `#!/bin/sh\necho "tmux-ctl $@" >> "${path.join(s.e.root, "calls.log")}"\necho "metrics: record: unknown batch b1" >&2\nexit 1\n`, { mode: 0o755 });
  const r = integrate.run(s.ctx, s.spec);
  assert.equal(r.outcome, "merged");
  assert.equal(s.keys().find((k) => k.key === "metrics_record:s1").state, "failed");
  assert.equal(s.keys().find((k) => k.key === "worktree_remove:s1").state, "done");
  assert.ok(!fs.existsSync(s.wt));
  const ev = s.db.prepare("SELECT detail FROM events WHERE spec='s1' AND kind='step_failed'").all();
  assert.equal(ev.length, 1);
  assert.match(ev[0].detail, /metrics record failed/);
  assert.equal(s.calls().length, 1); // no retry
});
