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
const rebuild = require("../lib/engine/rebuild");
const { DatabaseSync } = require("node:sqlite");

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
    assert.deepEqual(cols(d, "specs"), ["id", "position", "runner", "integration", "push", "batch", "state", "outcome", "worktree", "branch", "plan", "strategy", "backend", "policy_version", "policy_hash", "base", "created_at", "updated_at", "gate", "budget_attempts", "budget_tokens", "spent_attempts", "spent_tokens"]);
    assert.deepEqual(cols(d, "jobs"), ["id", "spec", "kind", "task", "tier", "model", "effort", "state", "attempt", "brief", "report", "window", "pane", "session_id", "base", "head", "tools", "mcp", "started_at", "ended_at", "needs_you_since", "needs_you_total", "detail", "tokens"]);
    assert.deepEqual(cols(d, "events"), ["seq", "ts", "spec", "job", "kind", "detail"]);
    assert.deepEqual(cols(d, "steps"), ["key", "spec", "kind", "state", "result", "created_at", "updated_at"]);
    assert.deepEqual(cols(d, "timers"), ["id", "spec", "job", "kind", "due_at", "payload", "fired_at"]);
    assert.deepEqual(cols(d, "waits"), ["id", "spec", "step", "question", "options", "asked_at", "answered_at", "answer", "note", "kind", "recommendation"]);
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
  assert.equal(policy.POLICY_VERSION, 2);
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
    assert.deepEqual(none, { test: null, test_ok: [0], retry: {}, holds: [], budget: { attempts: 60, tokens: 5000000 }, raw: "{}" });
    const H = (raw) => crypto.createHash("sha256").update(raw + "\n" + JSON.stringify({ ASK_DEFAULTS: policy.ASK_DEFAULTS, SITE_RECS: policy.SITE_RECS })).digest("hex");
    assert.equal(policy.policyHash(none), H("{}"));
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
    assert.equal(policy.policyHash(cfg), H(raw));
    assert.deepEqual(cfg.budget, { attempts: 60, tokens: 5000000 });
    const raw2 = JSON.stringify({ budget: { tokens: 10 } });
    fs.writeFileSync(path.join(g.dir, "docs/superpowers/engine.json"), raw2);
    assert.deepEqual(policy.loadConfig(g.dir).budget, { attempts: 60, tokens: 10 });
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

const OLD_SCHEMA = `
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
const NEW_COLS = { specs: ["gate", "budget_attempts", "budget_tokens", "spent_attempts", "spent_tokens"], jobs: ["tokens"], waits: ["kind", "recommendation"] };
const REC = { option: "approve", why: "because", confidence: "low" };

test("policy: version 2, ASK_DEFAULTS rows, recommendationFor", () => {
  assert.equal(policy.POLICY_VERSION, 2);
  assert.deepEqual(policy.ASK_KINDS, ["stop_class", "needs_you", "architect_park", "policy_change", "cannot_tell", "user_gate", "budget"]);
  assert.deepEqual(policy.ASK_DEFAULTS, {
    cannot_tell: { option: "approve", why: "the check cannot see the side effect; it most likely ran", confidence: "low" },
    policy_change: { option: "approve", why: "the new policy was set by the user", confidence: "medium" },
    needs_you: { option: "approve", why: "the worker is waiting on a prompt it raised", confidence: "low" },
    stop_class: { option: "deny", why: "an irreversible step needs your yes", confidence: "medium" },
    user_gate: { option: "approve", why: "the plan marks this task as yours to check", confidence: "low" },
  });
  assert.deepEqual(policy.recommendationFor("stop_class"), policy.ASK_DEFAULTS.stop_class);
  assert.deepEqual(policy.recommendationFor("budget", REC), REC);
  assert.throws(() => policy.recommendationFor("budget"), /no recommendation for budget/);
});

test("fresh database has the added columns", () => {
  const e = tmpEnv();
  try {
    const d = db.open("fresh");
    for (const [t, cs] of Object.entries(NEW_COLS)) for (const c of cs) assert.ok(cols(d, t).includes(c), `${t}.${c}`);
    d.close();
  } finally { e.restore(); }
});

test("an aged part 1 database opens without loss, gains the columns and passes rebuild.check", () => {
  const e = tmpEnv();
  try {
    fs.mkdirSync(path.dirname(paths.dbPath("aged")), { recursive: true });
    const old = new DatabaseSync(paths.dbPath("aged"));
    old.exec(OLD_SCHEMA);
    const spec = { id: "s1", position: 1, state: "awaiting_you", created_at: 1, updated_at: 2 };
    const job = { id: "s1:implement1:1", spec: "s1", kind: "implement", task: 1, state: "done", attempt: 1 };
    const w1 = { id: "s1@10", spec: "s1", step: "x", question: "q1", options: "approve|deny|fail", asked_at: 10, answered_at: 20, answer: "approve", note: "n" };
    const w2 = { id: "s1@30", spec: "s1", step: "y", question: "q2", options: "approve|deny|fail", asked_at: 30, answered_at: null, answer: null, note: null };
    const ins = (t, r) => old.prepare(`INSERT INTO ${t} (${Object.keys(r).join(",")}) VALUES (${Object.keys(r).map(() => "?").join(",")})`).run(...Object.values(r));
    ins("specs", spec); ins("jobs", job); ins("waits", w1); ins("waits", w2);
    const ev = (kind, rows) => old.prepare("INSERT INTO events (ts, spec, job, kind, detail) VALUES (1,'s1',NULL,?,?)").run(kind, JSON.stringify({ rows }));
    ev("a", [{ table: "specs", row: spec }, { table: "jobs", row: job }]);
    ev("b", [{ table: "waits", row: w1 }]);
    ev("c", [{ table: "waits", row: w2 }]);
    old.close();

    const d = db.open("aged");
    for (const [t, cs] of Object.entries(NEW_COLS)) for (const c of cs) assert.ok(cols(d, t).includes(c), `${t}.${c}`);
    for (const [t, r] of [["specs", spec], ["jobs", job], ["waits", w1]]) {
      const got = d.prepare(`SELECT * FROM ${t} WHERE id=?`).get(r.id);
      for (const [k, v] of Object.entries(r)) assert.equal(got[k], v, `${t}.${k}`);
    }
    assert.equal(d.prepare("SELECT kind FROM waits WHERE id='s1@10'").get().kind, null);
    assert.equal(d.prepare("SELECT spent_attempts FROM specs").get().spent_attempts, 0);
    // R10: the open wait is filled with cannot_tell and its default recommendation
    const open = d.prepare("SELECT * FROM waits WHERE id='s1@30'").get();
    assert.equal(open.kind, "cannot_tell");
    assert.deepEqual(JSON.parse(open.recommendation), policy.ASK_DEFAULTS.cannot_tell);
    d.close();
    // opening again changes nothing and adds no second event
    const d2 = db.open("aged");
    assert.equal(d2.prepare("SELECT count(*) c FROM events").get().c, 4);
    d2.close();
    assert.deepEqual(rebuild.check("aged"), { rc: 0, diffs: [] });
  } finally { e.restore(); }
});

test("put on waits: an open row needs a kind and a valid recommendation; answered rows are written as given", () => {
  const e = tmpEnv();
  try {
    const d = db.open("w");
    const base = { id: "a", spec: "s", step: "x", question: "q", options: "approve|deny", asked_at: 1, answered_at: null };
    const bad = [
      {}, { kind: "stop_class" }, { recommendation: JSON.stringify(REC) },
      { kind: "nonsense", recommendation: JSON.stringify(REC) },
      { kind: "budget", recommendation: JSON.stringify({ ...REC, option: "fail" }) },
      { kind: "budget", recommendation: JSON.stringify({ ...REC, why: "" }) },
      { kind: "budget", recommendation: JSON.stringify({ ...REC, confidence: "certain" }) },
      { kind: "budget", recommendation: "not json" },
    ];
    for (const extra of bad) assert.throws(() => db.put(d, "waits", { ...base, ...extra }), /wait needs kind and recommendation/, JSON.stringify(extra));
    assert.throws(() => db.put(d, "waits", { ...base, answered_at: undefined }), /wait needs kind and recommendation/);
    db.put(d, "waits", { ...base, kind: "budget", recommendation: JSON.stringify(REC) });
    assert.equal(d.prepare("SELECT kind FROM waits WHERE id='a'").get().kind, "budget");
    // answered rows are not checked
    db.put(d, "waits", { id: "b", spec: "s", step: "x", question: "q", asked_at: 1, answered_at: 2, answer: "approve" });
    assert.equal(d.prepare("SELECT answer FROM waits WHERE id='b'").get().answer, "approve");
    // putRaw writes without the check
    db.putRaw(d, "waits", { ...base, id: "c" });
    assert.equal(d.prepare("SELECT id FROM waits WHERE id='c'").get().id, "c");
    d.close();
  } finally { e.restore(); }
});

test("an existing part 2 database gains the holds table on open", () => {
  const e = tmpEnv();
  try {
    fs.mkdirSync(e.engineDir, { recursive: true });
    const old = new DatabaseSync(paths.dbPath("p"));
    old.exec(db.SCHEMA.split("\n").filter((l) => !/holds\(/.test(l)).join("\n"));
    assert.equal(old.prepare("SELECT count(*) n FROM sqlite_master WHERE name='holds'").get().n, 0);
    old.close();
    const d = db.open("p");
    assert.deepEqual(cols(d, "holds"), ["hold_id", "spec", "job", "call_hash", "tool", "input", "created_at", "expires_at", "used_at"]);
    d.close();
    assert.equal(rebuild.check("p").rc, 0);
  } finally { e.restore(); }
});

test("loadConfig returns holds, rejects a non-list, and the policy hash covers them", () => {
  const repo = gitRepo();
  try {
    assert.deepEqual(policy.loadConfig(repo.dir).holds, []);
    const f = path.join(repo.dir, "docs/superpowers/engine.json");
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, JSON.stringify({ test: "x" }));
    const a = policy.loadConfig(repo.dir);
    assert.deepEqual(a.holds, []);
    fs.writeFileSync(f, JSON.stringify({ test: "x", holds: [{ tool: "Bash", pattern: "p", outside_worktree: false }] }));
    const b = policy.loadConfig(repo.dir);
    assert.equal(b.holds.length, 1);
    assert.notEqual(policy.policyHash(a), policy.policyHash(b));
    fs.writeFileSync(f, JSON.stringify({ holds: "no" }));
    assert.throws(() => policy.loadConfig(repo.dir), /engine\.json holds must be a list/);
  } finally { repo.cleanup(); }
});

// Two processes opening a project's database for the first time both see the part 2 columns missing; only one ALTER can win.
// The engine child died with "duplicate column name: budget_tokens" when a reader (engine status, a test's peek) opened the
// database at the same moment. Each round is a fresh database and 6 processes released at one wall-clock instant.
test("concurrent first opens of a fresh database all succeed", async () => {
  const cp = require("node:child_process");
  const e = tmpEnv();
  try {
    const dbm = path.resolve(__dirname, "../lib/engine/db.js");
    const code = `const t = Number(process.argv[1]); while (Date.now() < t) {} require(${JSON.stringify(dbm)}).open(process.argv[2]).close();`;
    const failures = [];
    for (let round = 0; round < 8; round++) {
      const at = String(Date.now() + 500);
      const kids = Array.from({ length: 6 }, () => cp.spawn("node", ["-e", code, at, `race${round}`], { stdio: ["ignore", "ignore", "pipe"] }));
      const done = await Promise.all(kids.map((k) => new Promise((r) => { let err = ""; k.stderr.on("data", (d) => { err += d; }); k.on("exit", (c) => r({ c, err })); })));
      for (const d of done) if (d.c !== 0) failures.push(d.err.split("\n").find((l) => /Error|duplicate/.test(l)) || `exit ${d.c}`);
    }
    assert.deepEqual(failures, []);
  } finally { e.restore(); }
});
