"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { tmpEnv, gitRepo, scratchTmux } = require("./engine_helpers");
const paths = require("../lib/engine/paths");
const db = require("../lib/engine/db");
const policy = require("../lib/engine/policy");

function cols(d, t) { return d.prepare(`PRAGMA table_info(${t})`).all().map((c) => c.name); }

test("specSlug follows the slug rule", () => {
  assert.equal(paths.specSlug("docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1"), "pcee-engine-p1");
  assert.equal(paths.specSlug("docs/superpowers/specs/2026-11-10-pcee-engine-design.md"), "pcee-engine");
  assert.equal(paths.specSlug("x/foo.md#part-12"), "foo-p12");
});

test("paths honour TC_ENGINE_DIR and TC_STATE", () => {
  const e = tmpEnv();
  try {
    assert.equal(paths.engineDir(), e.engineDir);
    assert.equal(paths.dbPath("p"), path.join(e.engineDir, "p.sqlite"));
    assert.equal(paths.lockPath("p"), path.join(e.engineDir, "p.lock"));
    assert.equal(paths.stateDir(), e.state);
    assert.equal(paths.statusDir(), path.join(e.state, "agent-status"));
    assert.equal(paths.feedPath("p"), path.join(e.state, "feed", "p.jsonl"));
    assert.equal(paths.workspace("/w"), "/w/.superpowers/engine");
  } finally { e.restore(); }
});

test("stateDir and feedPath defaults without TC_STATE", () => {
  const e = tmpEnv();
  const oldT = process.env.TMPDIR, oldH = process.env.HOME;
  try {
    delete process.env.TC_STATE;
    process.env.TMPDIR = "/tmp/x/";
    process.env.HOME = "/h";
    assert.equal(paths.stateDir(), `/tmp/x/tmux-ctl-${process.getuid()}`);
    assert.equal(paths.feedPath("p"), "/h/.local/state/agent-board/feed/p.jsonl");
    delete process.env.TC_ENGINE_DIR;
    assert.equal(paths.engineDir(), "/h/.local/state/agent-board/engine");
  } finally {
    if (oldT === undefined) delete process.env.TMPDIR; else process.env.TMPDIR = oldT;
    process.env.HOME = oldH;
    e.restore();
  }
});

test("open creates the directory, the schema and WAL", () => {
  const e = tmpEnv();
  try {
    const d = db.open("p");
    assert.ok(fs.existsSync(paths.dbPath("p")));
    assert.equal(d.prepare("PRAGMA journal_mode").get().journal_mode, "wal");
    assert.deepEqual(cols(d, "specs"), ["id", "position", "runner", "integration", "push", "batch", "state", "outcome", "worktree", "branch", "plan", "strategy", "backend", "policy_version", "policy_hash", "base", "created_at", "updated_at"]);
    assert.deepEqual(cols(d, "jobs"), ["id", "spec", "kind", "task", "tier", "model", "effort", "state", "attempt", "brief", "report", "window", "pane", "session_id", "base", "head", "tools", "mcp", "started_at", "ended_at", "needs_you_since", "needs_you_total", "detail"]);
    assert.deepEqual(cols(d, "events"), ["seq", "ts", "spec", "job", "kind", "detail"]);
    assert.deepEqual(cols(d, "steps"), ["key", "spec", "kind", "state", "result", "created_at", "updated_at"]);
    assert.deepEqual(cols(d, "timers"), ["id", "spec", "job", "kind", "due_at", "payload", "fired_at"]);
    assert.deepEqual(cols(d, "waits"), ["id", "spec", "step", "question", "options", "asked_at", "answered_at", "answer", "note"]);
    assert.deepEqual(cols(d, "retry_policies"), ["kind", "max_attempts", "backoff_s", "timeout_min", "no_retry_on", "on_exhausted"]);
    assert.deepEqual(cols(d, "inbox"), ["id", "source", "source_id", "spec", "job", "kind", "payload", "received_at", "state", "handled_at", "reason"]);
    d.close();
    db.open("p").close(); // idempotent
  } finally { e.restore(); }
});

test("put writes a full row with defaults and returns it", () => {
  const e = tmpEnv();
  try {
    const d = db.open("p");
    const r = db.put(d, "specs", { id: "a", state: "queued" });
    assert.equal(r.id, "a");
    const row = d.prepare("SELECT * FROM specs WHERE id='a'").get();
    assert.equal(row.strategy, "spec-driven");
    assert.equal(row.backend, "claude-tmux");
    assert.equal(row.runner, null);
    db.put(d, "specs", { id: "a", state: "running" });
    const row2 = d.prepare("SELECT * FROM specs WHERE id='a'").get();
    assert.equal(row2.state, "running");
    assert.equal(row2.strategy, "spec-driven");
    db.put(d, "jobs", { id: "a:implement1:1", spec: "a" });
    const j = d.prepare("SELECT * FROM jobs").get();
    assert.equal(j.tools, "all");
    assert.equal(j.needs_you_total, 0);
    d.close();
  } finally { e.restore(); }
});

test("event stores detail {rows, ...extra} and ts", () => {
  const e = tmpEnv();
  try {
    const d = db.open("p");
    const rows = [{ table: "specs", row: { id: "a" } }];
    const before = Date.now() / 1000;
    db.event(d, { spec: "a", job: null, kind: "spec_started", rows, why: "x" });
    db.event(d, { spec: "a", kind: "k2", rows: [], ts: 5 });
    const [a, b] = d.prepare("SELECT * FROM events ORDER BY seq").all();
    assert.deepEqual(JSON.parse(a.detail), { rows, why: "x" });
    assert.ok(a.ts >= before && a.ts <= Date.now() / 1000);
    assert.equal(a.kind, "spec_started");
    assert.equal(b.ts, 5);
    assert.deepEqual(JSON.parse(b.detail), { rows: [] });
    assert.equal(b.seq, a.seq + 1);
    d.close();
  } finally { e.restore(); }
});

test("tx commits row and event together", () => {
  const e = tmpEnv();
  try {
    const d = db.open("p");
    const out = db.tx(d, () => {
      db.put(d, "specs", { id: "a" });
      db.event(d, { spec: "a", kind: "k", rows: [] });
      return 7;
    });
    assert.equal(out, 7);
    assert.equal(d.prepare("SELECT count(*) n FROM specs").get().n, 1);
    assert.equal(d.prepare("SELECT count(*) n FROM events").get().n, 1);
    d.close();
  } finally { e.restore(); }
});

test("a tx that throws leaves no row and no event", () => {
  const e = tmpEnv();
  try {
    const d = db.open("p");
    assert.throws(() => db.tx(d, () => {
      db.put(d, "specs", { id: "a" });
      db.event(d, { spec: "a", kind: "k", rows: [] });
      throw new Error("boom");
    }), /boom/);
    assert.equal(d.prepare("SELECT count(*) n FROM specs").get().n, 0);
    assert.equal(d.prepare("SELECT count(*) n FROM events").get().n, 0);
    db.tx(d, () => db.put(d, "specs", { id: "b" })); // db usable after rollback
    d.close();
  } finally { e.restore(); }
});

test("DEFAULT_RETRY has every row of spec 10.2", () => {
  assert.equal(policy.POLICY_VERSION, 1);
  const R = policy.DEFAULT_RETRY;
  for (const k of ["implement", "fix", "refresh"]) {
    assert.deepEqual(R[k], { max_attempts: 2, backoff_s: [30], timeout_min: 90, no_retry_on: ["blocked", "usage_limit"], on_exhausted: "architect" });
  }
  assert.deepEqual(R.review, { max_attempts: 2, backoff_s: [30], timeout_min: 45, no_retry_on: ["usage_limit"], on_exhausted: "architect" });
  assert.deepEqual(R.final_review, { max_attempts: 2, backoff_s: [60], timeout_min: 90, no_retry_on: ["usage_limit"], on_exhausted: "architect" });
  assert.deepEqual(R.architect, { max_attempts: 2, backoff_s: [60], timeout_min: 30, no_retry_on: ["usage_limit"], on_exhausted: "park" });
  assert.deepEqual(R.bounce, { max_attempts: 3, backoff_s: [0], timeout_min: null, no_retry_on: [], on_exhausted: "architect" });
  assert.deepEqual(R.fix_round, { max_attempts: 5, backoff_s: [0], timeout_min: null, no_retry_on: [], on_exhausted: "architect" });
});

test("loadConfig, retryFor override and policyHash", () => {
  const g = gitRepo();
  try {
    const none = policy.loadConfig(g.dir);
    assert.deepEqual(none, { test: null, test_ok: [0], retry: {}, raw: "{}" });
    assert.equal(policy.policyHash(none), crypto.createHash("sha256").update("{}").digest("hex"));
    assert.deepEqual(policy.retryFor(none, "review"), policy.DEFAULT_RETRY.review);

    const raw = JSON.stringify({ test: "zsh t.zsh", test_ok: [0, 4], retry: { review: { max_attempts: 5 } } });
    fs.mkdirSync(path.join(g.dir, "docs/superpowers"), { recursive: true });
    fs.writeFileSync(path.join(g.dir, "docs/superpowers/engine.json"), raw);
    const cfg = policy.loadConfig(g.dir);
    assert.equal(cfg.test, "zsh t.zsh");
    assert.deepEqual(cfg.test_ok, [0, 4]);
    assert.equal(cfg.raw, raw);
    assert.deepEqual(policy.retryFor(cfg, "review"), { ...policy.DEFAULT_RETRY.review, max_attempts: 5 });
    assert.deepEqual(policy.retryFor(cfg, "architect"), policy.DEFAULT_RETRY.architect);
    assert.equal(policy.policyHash(cfg), crypto.createHash("sha256").update(raw).digest("hex"));
  } finally { g.cleanup(); }
});

test("helpers: tmpEnv restores, gitRepo has a main commit, scratchTmux runs", () => {
  const before = process.env.TC_ENGINE_DIR;
  const e = tmpEnv();
  assert.notEqual(process.env.TC_ENGINE_DIR, before);
  e.restore();
  assert.equal(process.env.TC_ENGINE_DIR, before);
  const g = gitRepo();
  try {
    assert.equal(g.git("rev-parse", "--abbrev-ref", "HEAD").trim(), "main");
    assert.equal(g.git("rev-list", "--count", "HEAD").trim(), "1");
  } finally { g.cleanup(); }
  const t = scratchTmux();
  try {
    assert.equal(t.run(["new-session", "-d", "-s", "x"]).status, 0);
    assert.match(t.run(["list-sessions"]).stdout, /^x:/);
  } finally { t.kill(); }
});
