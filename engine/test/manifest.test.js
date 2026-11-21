"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { run, scratchRepo, cleanup } = require("./helpers.js");

const LIB = "../lib/registry/";
const FENCE = "```";
const planText = (m, spec) =>
  `# Plan\n\n**Spec:** ${spec || "docs/superpowers/specs/x-design.md"}\n\n${FENCE}json:manifest\n${typeof m === "string" ? m : JSON.stringify(m)}\n${FENCE}\n`;
const tasksJson = (filesPerTask) =>
  JSON.stringify({ planPath: "p", tasks: filesPerTask.map((files, i) => ({ id: String(i), description: `x\n\n${FENCE}json:metadata\n${JSON.stringify({ files })}\n${FENCE}\n` })) });

test("parseManifest: valid block", () => {
  const { parseManifest } = require(LIB + "manifest.js");
  const m = { spec: "s", base: "abc", writes: [{ path: "a", mode: "create" }], reads: ["b"], depends_on: [{ spec: "y", kind: "hard" }] };
  assert.deepStrictEqual(parseManifest(planText(m)), { manifest: m });
});
test("parseManifest: errors", () => {
  const { parseManifest } = require(LIB + "manifest.js");
  const ok = { spec: "s", base: "abc", writes: [], reads: [] };
  assert.deepStrictEqual(parseManifest("# no fence"), { error: "no manifest" });
  assert.deepStrictEqual(parseManifest(planText("{nope")), { error: "manifest: bad JSON" });
  const { base, ...nobase } = ok;
  assert.deepStrictEqual(parseManifest(planText(nobase)), { error: "manifest: base missing" });
  const { writes, ...nowrites } = ok;
  assert.deepStrictEqual(parseManifest(planText(nowrites)), { error: "manifest: writes missing" });
  assert.deepStrictEqual(parseManifest(planText({ ...ok, writes: [{ path: "a", mode: "zap" }] })), { error: "manifest: bad mode zap for a" });
  assert.deepStrictEqual(parseManifest(planText({ ...ok, depends_on: [{ spec: "y", kind: "meh" }] })), { error: "manifest: bad kind meh" });
});
test("taskFiles: union of each task's metadata files", () => {
  const { taskFiles } = require(LIB + "manifest.js");
  assert.deepStrictEqual(taskFiles(tasksJson([["a", "b"], ["b", "c"], []])).sort(), ["a", "b", "c"]);
});

test("git.js helpers on a real repo", (t) => {
  const g = require(LIB + "git.js");
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  r.write("f.txt", "hi\n");
  const sha = r.commit("one");
  assert.strictEqual(g.existsAt(r.dir, sha, "f.txt"), true);
  assert.strictEqual(g.existsAt(r.dir, sha, "nope.txt"), false);
  assert.strictEqual(g.show(r.dir, sha, "f.txt"), "hi\n");
  assert.strictEqual(g.show(r.dir, sha, "nope.txt"), null);
  assert.strictEqual(g.git(r.dir, ["rev-parse", "HEAD"]).out.trim(), sha);
  assert.strictEqual(g.git(r.dir, ["rev-parse", "nonexistent-ref"]).rc !== 0, true);
  assert.strictEqual(fs.realpathSync(g.mainRoot(r.dir)), fs.realpathSync(r.dir));
  // a worktree resolves to the main checkout
  const wt = r.dir + "-wt";
  t.after(() => cleanup(wt));
  r.git("worktree", "add", "-q", "-b", "side", wt);
  assert.strictEqual(fs.realpathSync(g.mainRoot(wt)), fs.realpathSync(r.dir));
});

test("findPlan: working tree beats a branch; #part line beats a plain one", (t) => {
  const g = require(LIB + "git.js");
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  const P = "docs/superpowers/plans/";
  const spec = "docs/superpowers/specs/e-design.md";
  r.write(P + "a-branch.md", `# A\n\n**Spec:** ${spec}#part-2\n`);
  r.commit("base");
  r.git("branch", "feat");
  r.git("checkout", "-q", "feat");
  r.write(P + "b-feat.md", `# B\n\n**Spec:** ${spec}\n`);
  r.commit("feat plan");
  r.git("checkout", "-q", "main");
  assert.strictEqual(g.findPlan(r.dir, "docs/superpowers/specs/none.md"), null);
  // part-1 request: plain match only on a branch plan and the a-branch plan (core matches); working tree first
  let f = g.findPlan(r.dir, spec + "#part-2");
  assert.strictEqual(f.path, P + "a-branch.md");
  assert.strictEqual(f.ref, null);
  // plain spec: a-branch (working tree, core match, no exact suffix match? line contains spec) wins over branch
  f = g.findPlan(r.dir, spec);
  assert.strictEqual(f.ref, null);
  // branch-only plan found with its ref
  r.write(P + "c-wt.md", `# C\n\n**Spec:** docs/superpowers/specs/only-feat-design.md\n`);
  r.git("add", "-A"); r.git("commit", "-q", "-m", "c"); r.git("checkout", "-q", "feat");
  r.write(P + "d-feat.md", `# D\n\n**Spec:** docs/superpowers/specs/zzz-design.md\n`);
  r.commit("d");
  r.git("checkout", "-q", "main");
  f = g.findPlan(r.dir, "docs/superpowers/specs/zzz-design.md");
  assert.strictEqual(f.path, P + "d-feat.md");
  assert.strictEqual(f.ref, "refs/heads/feat");
  assert.match(f.text, /zzz/);
});

// ---- validate ----
function fixture(t, { manifest = {}, tasks = [["new.txt"]], files = { "old.txt": "x\n", "log.txt": "l\n" }, noTasks = false } = {}) {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  for (const [k, v] of Object.entries(files)) r.write(k, v);
  const base = r.commit("base");
  const m = { spec: "docs/superpowers/specs/x-design.md", base, depends_on: [],
    writes: [{ path: "old.txt", mode: "modify" }, { path: "log.txt", mode: "append" }, { path: "new.txt", mode: "create" }],
    reads: [], produces: [], consumes: [], tests: [], ...manifest };
  const plan = "docs/superpowers/plans/p.md";
  r.write(plan, typeof manifest === "string" ? manifest : planText(m));
  if (!noTasks) r.write(plan + ".tasks.json", tasksJson(tasks));
  return { r, plan, base };
}
const validate = (r, plan) => run(["validate", plan], { cwd: r.dir });
const lines = (res) => res.stdout.split("\n").filter(Boolean);

test("validate: valid plan exits 0 with no output", (t) => {
  const { r, plan } = fixture(t, { tasks: [["old.txt", "new.txt"], ["log.txt"]] });
  const res = validate(r, plan);
  assert.deepStrictEqual([res.code, res.stdout, res.stderr], [0, "", ""]);
});
test("validate: absolute plan path and subdirectory cwd", (t) => {
  const { r, plan } = fixture(t, { tasks: [["new.txt"]] });
  assert.strictEqual(run(["validate", path.join(r.dir, plan)], { cwd: r.dir }).code, 0);
  fs.mkdirSync(path.join(r.dir, "sub"));
  assert.strictEqual(run(["validate", path.join(r.dir, plan)], { cwd: path.join(r.dir, "sub") }).code, 0);
});
test("validate: missing plan file", (t) => {
  const { r } = fixture(t);
  const res = validate(r, "docs/superpowers/plans/nope.md");
  assert.strictEqual(res.code, 1);
  assert.strictEqual(res.stderr.trim(), "registry: validate: no such plan docs/superpowers/plans/nope.md");
});
test("validate: no argument is a usage error", (t) => {
  const { r } = fixture(t);
  const res = run(["validate"], { cwd: r.dir });
  assert.strictEqual(res.code, 1);
  assert.match(res.stderr, /registry: validate: usage: registry validate <plan>/);
});
test("validate: no manifest", (t) => {
  const { r, plan } = fixture(t, { manifest: "# nothing\n" });
  const res = validate(r, plan);
  assert.strictEqual(res.code, 1);
  assert.deepStrictEqual(lines(res).slice(0, 1), ["no manifest"]);
});
test("validate: bad JSON and missing key", (t) => {
  let f = fixture(t, { manifest: planText("{nope") });
  assert.deepStrictEqual(lines(validate(f.r, f.plan)).slice(0, 1), ["manifest: bad JSON"]);
  f = fixture(t, { manifest: planText({ spec: "s", writes: [] }) });
  assert.deepStrictEqual(lines(validate(f.r, f.plan)).slice(0, 1), ["manifest: base missing"]);
});
test("validate: create path that exists at base", (t) => {
  const { r, plan } = fixture(t, { manifest: { writes: [{ path: "old.txt", mode: "create" }] }, tasks: [["old.txt"]] });
  const res = validate(r, plan);
  assert.strictEqual(res.code, 1);
  assert.deepStrictEqual(lines(res), ["create path exists at base: old.txt"]);
});
test("validate: modify and append paths missing at base, in manifest order", (t) => {
  const { r, plan } = fixture(t, { manifest: { writes: [{ path: "gone.txt", mode: "modify" }, { path: "gone2.txt", mode: "append" }] }, tasks: [["gone.txt", "gone2.txt"]] });
  assert.deepStrictEqual(lines(validate(r, plan)), ["modify path missing at base: gone.txt", "append path missing at base: gone2.txt"]);
});
test("validate: base not found stops path checks but coverage still runs", (t) => {
  const { r, plan } = fixture(t, { manifest: { base: "deadbeefdeadbeef" }, tasks: [["new.txt", "zzz.txt"]] });
  const res = validate(r, plan);
  assert.strictEqual(res.code, 1);
  assert.deepStrictEqual(lines(res), ["base not found: deadbeefdeadbeef", "task file not covered: zzz.txt"]);
});
test("validate: task file in neither writes nor reads; reads cover; sorted", (t) => {
  const { r, plan } = fixture(t, { manifest: { reads: ["rd.txt"] }, tasks: [["new.txt", "zeta.txt", "rd.txt"], ["alpha.txt"]] });
  assert.deepStrictEqual(lines(validate(r, plan)), ["task file not covered: alpha.txt", "task file not covered: zeta.txt"]);
});
test("validate: no .tasks.json", (t) => {
  const { r, plan } = fixture(t, { noTasks: true });
  const res = validate(r, plan);
  assert.strictEqual(res.code, 1);
  assert.deepStrictEqual(lines(res), ["no .tasks.json"]);
});
