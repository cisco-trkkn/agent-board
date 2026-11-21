"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { scratchRepo, cleanup, run } = require("./helpers.js");
const { runReport } = require("../lib/registry/report.js");

const spec = (n) => `docs/superpowers/specs/2026-11-21-${n}-design.md`;
const PRED = "## Prediction against outcome";

function plan(n, writes) {
  const m = { spec: spec(n), base: "abc", depends_on: [], writes, reads: [] };
  return `# Plan ${n}\n\n**Spec:** ${spec(n)}\n\n\`\`\`json:manifest\n${JSON.stringify(m)}\n\`\`\`\n`;
}

// Specs a and b both declare `log` as an append. Branch pa changes a line of it (a violation); pb appends.
function setup(t, pairs) {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  r.write("log", "l1\nl2\n");
  r.write("f", "f\n");
  const base = r.commit("init");
  const appendLog = { path: "log", mode: "append" };
  r.git("checkout", "-q", "-b", "pa");
  r.write("docs/superpowers/plans/a.md", plan("a", [appendLog, { path: "f", mode: "modify" }]));
  r.write("log", "l1 changed\nl2\n");
  r.write("extra", "x\n");
  const ha = r.commit("a");
  r.git("checkout", "-q", "main");
  r.git("checkout", "-q", "-b", "pb");
  r.write("docs/superpowers/plans/b.md", plan("b", [appendLog]));
  r.write("log", "l1\nl2\nl3\n");
  const hb = r.commit("b");
  r.git("checkout", "-q", "main");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "rep-"));
  t.after(() => cleanup(tmp));
  const stub = path.join(tmp, "stub.js");
  fs.writeFileSync(stub, `const fs=require("fs");const a=process.argv.slice(2);
if(a[0]==="runs"){process.stdout.write(fs.readFileSync(process.env.STUB_RUNS,"utf8"));}
else if(a[0]==="append"){fs.appendFileSync(process.env.STUB_LOG,JSON.stringify(a)+"\\n");}`);
  const runs = path.join(tmp, "runs.json");
  const canned = {
    batch: "B1", base, at: 1, specs: [spec("a"), spec("b")],
    runs: { [spec("a")]: { spec: spec("a"), base, head: ha }, [spec("b")]: { spec: spec("b"), base, head: hb } },
    pairs: pairs === undefined ? [{ a: spec("a"), b: spec("b"), clean: true, paths: [] }] : pairs,
  };
  fs.writeFileSync(runs, JSON.stringify(canned));
  const log = path.join(tmp, "calls.log");
  process.env.REGISTRY_METRICS_CMD = `${process.execPath} ${stub}`;
  process.env.STUB_RUNS = runs;
  process.env.STUB_LOG = log;
  t.after(() => { delete process.env.REGISTRY_METRICS_CMD; delete process.env.STUB_RUNS; delete process.env.STUB_LOG; });
  const calls = () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n").map((l) => JSON.parse(JSON.parse(l)[3])) : []);
  return { r, tmp, calls };
}

test("report adds the section once over two runs and runs analyse first when no document exists", (t) => {
  const { r, calls } = setup(t);
  const a = runReport(r.dir, "B1");
  const b = runReport(r.dir, "B1");
  assert.strictEqual(a.docPath, b.docPath);
  const doc = fs.readFileSync(a.docPath, "utf8");
  assert.strictEqual(doc.split(PRED).length, 2);
  assert.ok(doc.indexOf("## Hot files") < doc.indexOf(PRED), "analysis sections precede the report");
  assert.ok(doc.trimEnd().endsWith("Textual results do not show semantic conflicts."));
  // analysis (from analyse), then one superseding line per report run
  assert.deepStrictEqual(calls().map((l) => l.appends_verified), [false, true, true]);
});

test("a violated append counts as modify in the superseding wave recount", (t) => {
  const { r, calls } = setup(t);
  runReport(r.dir, "B1");
  const [first, second] = calls();
  assert.strictEqual(first.waves.append, 1);
  assert.strictEqual(second.waves.append, 2);
  assert.strictEqual(second.parallelism, 1);
  assert.strictEqual(second.specs, 2);
  assert.deepStrictEqual(Object.keys(second).sort(), Object.keys(first).sort());
  assert.strictEqual(second.appends_verified, true);
});

test("per-spec facts list recalls, precision, refreshes, missed files and violations", (t) => {
  const { r } = setup(t);
  const { docPath } = runReport(r.dir, "B1");
  const sec = fs.readFileSync(docPath, "utf8").split(PRED)[1];
  assert.match(sec, /\| spec \| recall_existing \| recall_created \| precision \| refreshes \| missed \| append violations \|/);
  const rowA = sec.split("\n").find((l) => l.startsWith(`| ${spec("a")} |`));
  assert.ok(rowA, "row for a");
  assert.strictEqual(rowA, `| ${spec("a")} | 0 | 0 | 0.5 | 0 | extra, log | log |`);
  const rowB = sec.split("\n").find((l) => l.startsWith(`| ${spec("b")} |`));
  assert.strictEqual(rowB, `| ${spec("b")} | 1 | - | 1 | 0 | - | - |`);
});

test("pair table: four totals per policy add up to the pair count", (t) => {
  const { r } = setup(t, [{ a: spec("a"), b: spec("b"), clean: true, paths: [] }, { a: spec("a"), b: spec("zz"), clean: false, paths: ["log"] }]);
  const { docPath } = runReport(r.dir, "B1");
  const sec = fs.readFileSync(docPath, "utf8").split(PRED)[1];
  const rows = sec.split("\n").filter((l) => /^\| (strict|append|writes_only) \|/.test(l));
  assert.strictEqual(rows.length, 3);
  for (const row of rows) {
    const n = row.split("|").slice(2, 6).map((x) => Number(x.trim()));
    assert.strictEqual(n.reduce((x, y) => x + y, 0), 2, row);
  }
  // a-b is clean; a-zz is conflicting and zz has no manifest, so it is never predicted.
  // columns: predicted&clean, predicted&conflicting, not predicted&conflicting, not predicted&clean
  const tot = (pol) => rows.find((l) => l.startsWith(`| ${pol} |`)).split("|").slice(2, 6).map((x) => Number(x.trim()));
  assert.deepStrictEqual(tot("strict"), [1, 0, 1, 0]);
  assert.deepStrictEqual(tot("append"), [0, 0, 1, 1]); // both writes are appends as declared
  assert.deepStrictEqual(tot("writes_only"), [1, 0, 1, 0]);
});

test("pairs null prints the unavailable line", (t) => {
  const { r } = setup(t, null);
  const { docPath } = runReport(r.dir, "B1");
  assert.ok(fs.readFileSync(docPath, "utf8").includes("Pairs: unavailable (git merge-tree failed)"));
});

test("registry report CLI: unknown batch is one registry: report: line, exit 1", (t) => {
  const { r, tmp } = setup(t);
  const bad = path.join(tmp, "bad.js");
  fs.writeFileSync(bad, 'process.stderr.write("metrics: runs: unknown batch ZZ\\n");process.exit(1);');
  const res = run(["report", "ZZ"], { cwd: r.dir, env: { ...process.env, REGISTRY_METRICS_CMD: `${process.execPath} ${bad}` } });
  assert.strictEqual(res.code, 1);
  assert.strictEqual(res.stderr.trim(), "registry: report: unknown batch ZZ");
});
