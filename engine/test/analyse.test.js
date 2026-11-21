"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { scratchRepo, cleanup } = require("./helpers.js");
const { runAnalyse } = require("../lib/registry/analyse.js");

const REPO_ROOT = path.join(__dirname, "../..");
const spec = (n) => `docs/superpowers/specs/2026-11-21-${n}-design.md`;

function plan(n, mf, extra) {
  const m = mf && {
    spec: spec(n), base: "abc", depends_on: mf.deps || [],
    writes: (mf.writes || []).map((p) => (typeof p === "string" ? { path: p, mode: "modify" } : p)),
    reads: mf.reads || [],
  };
  return `# Plan ${n}\n\n**Spec:** ${spec(n)}\n\n${m ? "```json:manifest\n" + JSON.stringify(m) + "\n```\n" : ""}${extra || ""}`;
}

function setup(t, canned) {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  r.write("README.md", "x");
  r.commit("init");
  r.git("checkout", "-q", "-b", "pa");
  r.write("docs/superpowers/plans/a.md", plan("a", { writes: ["f", { path: "log", mode: "append" }] }));
  r.commit("a");
  r.git("checkout", "-q", "main");
  r.git("checkout", "-q", "-b", "pb");
  r.write("docs/superpowers/plans/b.md", plan("b", { writes: ["f"], deps: [{ spec: spec("c"), kind: "hard" }] }));
  r.commit("b");
  r.git("checkout", "-q", "main");
  r.write("docs/superpowers/plans/c.md", plan("c", { writes: [{ path: "log", mode: "append" }], reads: ["g"] }));
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "stub-"));
  t.after(() => cleanup(tmp));
  const stub = path.join(tmp, "stub.js");
  fs.writeFileSync(stub, `const fs=require("fs");const a=process.argv.slice(2);
if(a[0]==="runs"){process.stdout.write(fs.readFileSync(process.env.STUB_RUNS,"utf8"));}
else if(a[0]==="append"){fs.appendFileSync(process.env.STUB_LOG,JSON.stringify(a)+"\\n");}`);
  const runs = path.join(tmp, "runs.json");
  fs.writeFileSync(runs, JSON.stringify(canned || { batch: "B1", base: "abc", at: 1, specs: [spec("a"), spec("b"), spec("c")], runs: {}, pairs: null }));
  const log = path.join(tmp, "calls.log");
  process.env.REGISTRY_METRICS_CMD = `${process.execPath} ${stub}`;
  process.env.STUB_RUNS = runs;
  process.env.STUB_LOG = log;
  t.after(() => { delete process.env.REGISTRY_METRICS_CMD; delete process.env.STUB_RUNS; delete process.env.STUB_LOG; });
  return { r, tmp, log };
}

test("document sections in order, analysis line counts right (reorder sections -> fails)", (t) => {
  const { r, tmp, log } = setup(t);
  const rel = path.join(tmp, "rel.json");
  fs.writeFileSync(rel, JSON.stringify([{ a: spec("a"), b: spec("c"), kind: "interface", why: "shared api" }]));
  const { docPath, line } = runAnalyse(r.dir, "B1", rel);
  const doc = fs.readFileSync(docPath, "utf8");
  const heads = ["# Analysis B1", "## Manifests", "## Dependency graph", "## Conflict graph", "### strict", "### append", "### writes_only",
    "## Clusters", "## Waves", "## Hot files", "## Plans without a manifest"];
  let at = -1;
  for (const h of heads) { const i = doc.indexOf(h + "\n", at + 1); assert.ok(i > at, h); at = i; }
  assert.ok(doc.includes("shared api"));
  assert.ok(docPath.endsWith("docs/superpowers/metrics/analysis/B1.md"));
  assert.deepStrictEqual(line, {
    kind: "analysis", batch: "B1", specs: 3,
    waves: { strict: 3, append: 3, writes_only: 3 },
    parallelism: 1, parallelism_strict: 1, parallelism_writes_only: 1,
    appends_verified: false, clusters: 1, relations: 1,
  });
  const call = JSON.parse(fs.readFileSync(log, "utf8").trim().split("\n")[0]);
  assert.deepStrictEqual(call.slice(0, 3), ["append", "analysis", "--json"]);
  assert.deepStrictEqual(JSON.parse(call[3]), line);
});

test("order relation shows the cross-plan suffix in the dependency graph", (t) => {
  const { r, tmp } = setup(t);
  const rel = path.join(tmp, "rel.json");
  fs.writeFileSync(rel, JSON.stringify([{ a: spec("a"), b: spec("c"), kind: "order", why: "needs c first" }]));
  const { docPath } = runAnalyse(r.dir, "B1", rel);
  assert.match(fs.readFileSync(docPath, "utf8"), /\(cross-plan: needs c first\)/);
});

test("malformed relations file is ignored with a line; unknown specs are not counted", (t) => {
  const { r, tmp } = setup(t);
  const rel = path.join(tmp, "rel.json");
  fs.writeFileSync(rel, "{not json");
  let res = runAnalyse(r.dir, "B1", rel);
  assert.match(fs.readFileSync(res.docPath, "utf8"), /^relations: ignored \(.+\)$/m);
  assert.strictEqual(res.line.relations, 0);
  fs.writeFileSync(rel, JSON.stringify([{ a: spec("a"), b: "nope", kind: "conflict", why: "x" }, { a: spec("a"), b: spec("b"), kind: "weird", why: "x" }]));
  res = runAnalyse(r.dir, "B1", rel);
  assert.strictEqual(res.line.relations, 0);
});

test("plan without a manifest is left out and listed", (t) => {
  const { r } = setup(t);
  r.write("docs/superpowers/plans/c.md", plan("c", null));
  const { docPath, line } = runAnalyse(r.dir, "B1", null);
  const doc = fs.readFileSync(docPath, "utf8");
  assert.strictEqual(line.specs, 2);
  assert.match(doc.split("## Plans without a manifest")[1], new RegExp(spec("c")));
});

test("rerun keeps an existing Prediction against outcome section", (t) => {
  const { r } = setup(t);
  const { docPath } = runAnalyse(r.dir, "B1", null);
  fs.appendFileSync(docPath, "\n## Prediction against outcome\n\nKEEP ME\n");
  runAnalyse(r.dir, "B1", null);
  const doc = fs.readFileSync(docPath, "utf8");
  assert.ok(doc.includes("## Prediction against outcome\n\nKEEP ME"));
  assert.strictEqual(doc.split("## Prediction against outcome").length, 2);
});

test("unknown batch throws unknown batch <id>", (t) => {
  const { r, tmp } = setup(t);
  const bad = path.join(tmp, "bad.js");
  fs.writeFileSync(bad, 'process.stderr.write("metrics: runs: unknown batch ZZ\\n");process.exit(1);');
  process.env.REGISTRY_METRICS_CMD = `${process.execPath} ${bad}`;
  assert.throws(() => runAnalyse(r.dir, "ZZ", null), /unknown batch ZZ/);
});

test("real tmux-ctl metrics append --log writes a parseable analysis line", (t) => {
  const { r, tmp } = setup(t);
  const real = path.join(tmp, "real.jsonl");
  const stubRuns = process.env.STUB_RUNS;
  // reads still come from the stub; the append goes through the real tmux-ctl
  const wrap = path.join(tmp, "wrap.js");
  fs.writeFileSync(wrap, `const cp=require("child_process"),fs=require("fs");const a=process.argv.slice(2);
if(a[0]==="runs"){process.stdout.write(fs.readFileSync(${JSON.stringify(stubRuns)},"utf8"));}
else{const x=cp.spawnSync("zsh",[${JSON.stringify(path.join(REPO_ROOT, "bin/tmux-ctl"))},"metrics",...a],{stdio:"inherit"});process.exit(x.status);}`);
  process.env.REGISTRY_METRICS_CMD = `${process.execPath} ${wrap}`;
  const { line } = runAnalyse(r.dir, "B1", null, { extra: ["--log", real] });
  const lines = fs.readFileSync(real, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.strictEqual(lines.length, 1);
  assert.strictEqual(lines[0].kind, "analysis");
  assert.strictEqual(lines[0].batch, "B1");
  assert.strictEqual(lines[0].specs, line.specs);
});

test("real metrics runs and append work with TMUX removed, on a batch line in the real shape", (t) => {
  const { r, tmp } = setup(t);
  const log = path.join(tmp, "real2.jsonl");
  const base = r.git("rev-parse", "HEAD");
  const batchLine = { kind: "batch", batch: "B9", at: "2026-11-21T10:00:00Z", base, assignment: { [spec("a")]: "seq-sdd", [spec("b")]: "seq-sdd", [spec("c")]: "seq-sdd" }, configs: ["seq-sdd"], groups: [] };
  fs.writeFileSync(log, JSON.stringify(batchLine) + "\n");
  process.env.REGISTRY_METRICS_CMD = `zsh ${path.join(REPO_ROOT, "bin/tmux-ctl")} metrics`;
  const saved = process.env.TMUX;
  delete process.env.TMUX;
  t.after(() => { if (saved !== undefined) process.env.TMUX = saved; });
  const b = require("../lib/registry/batch.js").readBatch(r.dir, "B9", ["--log", log]);
  assert.strictEqual(b.batch, "B9");
  assert.deepStrictEqual(b.specs, [spec("a"), spec("b"), spec("c")]);
  assert.throws(() => require("../lib/registry/batch.js").readBatch(r.dir, "NOPE", ["--log", log]), /unknown batch NOPE/);
  const { line } = runAnalyse(r.dir, "B9", null, { extra: ["--log", log] });
  assert.strictEqual(line.specs, 3);
  const last = fs.readFileSync(log, "utf8").trim().split("\n").pop();
  assert.strictEqual(JSON.parse(last).kind, "analysis");
});

test("a non-'unknown batch' failure relays the metrics stderr line", (t) => {
  const { r, tmp } = setup(t);
  const bad = path.join(tmp, "bad2.js");
  fs.writeFileSync(bad, 'process.stderr.write("tmux-ctl: not inside tmux\\n");process.exit(2);');
  process.env.REGISTRY_METRICS_CMD = `${process.execPath} ${bad}`;
  assert.throws(() => runAnalyse(r.dir, "B1", null), /not inside tmux/);
});
