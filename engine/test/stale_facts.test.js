"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { run, scratchRepo, cleanup } = require("./helpers.js");

const F = "```";
const SPEC = "docs/superpowers/specs/x-design.md";
const PLAN = "docs/superpowers/plans/x.md";
const plan = (m) => `# P\n\n**Spec:** ${SPEC}\n\n${F}json:manifest\n${JSON.stringify(m)}\n${F}\n`;
const W = (path, mode) => ({ path, mode });

// A repo whose base commit has the given files; the plan is committed after the base (as on a plan branch).
function setup(t, files, writes, extra = {}) {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  for (const [k, v] of Object.entries(files)) r.write(k, v);
  const base = r.commit("base");
  r.write(PLAN, plan({ spec: SPEC, base, writes, reads: [], depends_on: [], ...extra }));
  r.commit("plan");
  return { r, base };
}
const facts = (r, base, head) => {
  const res = run(["facts", SPEC, "--base", base, "--head", head || "HEAD"], { cwd: r.dir });
  return { ...res, json: res.code === 0 ? JSON.parse(res.stdout) : null };
};

// ---- stale ----
test("stale: main modifies a modify path -> stale with that path", (t) => {
  const { r } = setup(t, { "a.txt": "1\n", "b.txt": "1\n" }, [W("a.txt", "modify")]);
  r.write("a.txt", "2\n"); r.commit("main moves a");
  const res = run(["stale", SPEC], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stdout], [1, "stale\na.txt\n"]);
});
test("stale: reads and append paths count; output sorted", (t) => {
  const { r } = setup(t, { "z.txt": "1\n", "a.txt": "1\n", "k.txt": "1\n" }, [W("z.txt", "append")], { reads: ["a.txt"] });
  r.write("z.txt", "2\n"); r.write("a.txt", "2\n"); r.write("k.txt", "2\n"); r.commit("main moves");
  const res = run(["stale", SPEC], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stdout], [1, "stale\na.txt\nz.txt\n"]);
});
test("stale: an unlisted path changing is fresh", (t) => {
  const { r } = setup(t, { "a.txt": "1\n", "b.txt": "1\n" }, [W("a.txt", "modify")]);
  r.write("b.txt", "2\n"); r.commit("main moves b");
  const res = run(["stale", SPEC], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stdout], [0, "fresh\n"]);
});
test("stale: a create path that now exists is stale", (t) => {
  const { r } = setup(t, { "a.txt": "1\n" }, [W("new.txt", "create")]);
  r.write("new.txt", "x\n"); r.commit("main created it");
  const res = run(["stale", SPEC], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stdout], [1, "stale\nnew.txt\n"]);
});
test("stale: --main picks the ref; default is main", (t) => {
  const { r } = setup(t, { "a.txt": "1\n" }, [W("a.txt", "modify")]);
  r.git("branch", "other");
  r.write("a.txt", "2\n"); r.commit("main moves a");
  assert.strictEqual(run(["stale", SPEC, "--main", "other"], { cwd: r.dir }).code, 0);
  assert.strictEqual(run(["stale", SPEC, "--main", "main"], { cwd: r.dir }).code, 1);
});
test("stale: no manifest -> stdout 'no manifest', exit 3", (t) => {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  r.write("docs/superpowers/plans/n.md", `# P\n\n**Spec:** ${SPEC}\n`);
  r.commit("plan without manifest");
  const res = run(["stale", SPEC], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stdout, res.stderr], [3, "no manifest\n", ""]);
});

// ---- facts ----
test("facts: recall, precision and the declared/touched/both/missed counts", (t) => {
  const { r, base } = setup(t, { "a.txt": "1\n", "b.txt": "1\n", "c.txt": "1\n" },
    [W("a.txt", "modify"), W("c.txt", "modify"), W("n1.txt", "create")]);
  r.write("a.txt", "2\n"); r.write("b.txt", "2\n"); r.write("n1.txt", "x\n"); r.write("n2.txt", "y\n");
  r.write("docs/superpowers/notes/x.md", "ignored\n");
  r.commit("work");
  const { code, json } = facts(r, base);
  assert.strictEqual(code, 0);
  assert.strictEqual(json.recall_existing, 0.5);   // a declared, b not
  assert.strictEqual(json.recall_created, 0.5);    // n1 declared, n2 not
  assert.strictEqual(json.precision, 2 / 3);       // a and n1 touched of a, c, n1
  assert.deepStrictEqual([json.declared, json.touched, json.both], [3, 4, 2]);
  assert.deepStrictEqual(json.missed, ["b.txt", "n2.txt"]);
  assert.deepStrictEqual(json.append_violations, []);
  assert.deepStrictEqual([json.refreshes, json.stale_paths], [0, 0]);
  assert.deepStrictEqual(json.writes, [W("a.txt", "modify"), W("c.txt", "modify"), W("n1.txt", "create")]);
});
test("facts: nothing touched that existed or was created -> null recalls; no writes -> null precision", (t) => {
  const { r, base } = setup(t, { "a.txt": "1\n" }, []);
  r.write("docs/superpowers/x.md", "d\n"); r.commit("docs only");
  const { json } = facts(r, base);
  assert.deepStrictEqual([json.recall_existing, json.recall_created, json.precision], [null, null, null]);
  assert.deepStrictEqual([json.declared, json.touched, json.both], [0, 0, 0]);
});
test("facts: writes under docs/superpowers/ do not count for precision or declared", (t) => {
  const { r, base } = setup(t, { "a.txt": "1\n" }, [W("a.txt", "modify"), W("docs/superpowers/plans/x.md.tasks.json", "create")]);
  r.write("a.txt", "2\n"); r.commit("work");
  const { json } = facts(r, base);
  assert.deepStrictEqual([json.precision, json.declared], [1, 1]);
});
test("facts: recall_created 0.5, refreshed_from gives refreshes 1 and stale_paths 2", (t) => {
  const { r, base } = setup(t, {}, [W("n1.txt", "create"), W("n3.txt", "create")],
    { refreshed_from: { base: "abc", stale_paths: ["p", "q"] } });
  r.write("n1.txt", "x\n"); r.write("n2.txt", "y\n"); r.commit("work");
  const { json } = facts(r, base);
  assert.strictEqual(json.recall_created, 0.5);
  assert.deepStrictEqual([json.refreshes, json.stale_paths], [1, 2]);
});
test("facts: no manifest -> registry: facts: no manifest, exit 3", (t) => {
  const r = scratchRepo();
  t.after(() => cleanup(r.dir));
  r.write("docs/superpowers/plans/n.md", `# P\n\n**Spec:** ${SPEC}\n`);
  const base = r.commit("plan without manifest");
  const res = run(["facts", SPEC, "--base", base, "--head", "HEAD"], { cwd: r.dir });
  assert.deepStrictEqual([res.code, res.stderr.trim()], [3, "registry: facts: no manifest"]);
});
test("facts: the plan is read at --head, not from the working tree", (t) => {
  // main's plan declares b.txt; the branch's plan (the head) declares a.txt, which the branch modifies
  const { r, base } = setup(t, { "a.txt": "1\n", "b.txt": "1\n" }, [W("b.txt", "modify")]);
  r.git("checkout", "-q", "-b", "feat");
  r.write(PLAN, plan({ spec: SPEC, base, writes: [W("a.txt", "modify")], reads: [], depends_on: [] }));
  r.write("a.txt", "2\n");
  const head = r.commit("work");
  r.git("checkout", "-q", "main");
  const { code, json } = facts(r, base, head);
  assert.strictEqual(code, 0);
  assert.deepStrictEqual([json.recall_existing, json.writes], [1, [W("a.txt", "modify")]]);
});

// ---- append verification ----
const append = (t, before, after, mode = "append") => {
  const { r, base } = setup(t, { "log.txt": before }, [W("log.txt", mode)]);
  r.write("log.txt", after); r.commit("work");
  return facts(r, base).json;
};
const L = (n) => Array.from({ length: n }, (_, i) => `l${i}\n`).join("");
test("append: one added block is not a violation", (t) => {
  const j = append(t, L(5), L(5) + "x\ny\n");
  assert.deepStrictEqual([j.append_violations, j.recall_existing], [[], 1]);
});
test("append: two separate blocks are a violation and a miss", (t) => {
  const j = append(t, L(6), "top\n" + L(6) + "bottom\n");
  assert.deepStrictEqual([j.append_violations, j.recall_existing], [["log.txt"], 0]);
  assert.deepStrictEqual([j.both, j.missed], [0, ["log.txt"]]);
});
test("append: a changed line is a violation", (t) => {
  const j = append(t, L(5), L(5).replace("l2", "CHANGED"));
  assert.deepStrictEqual([j.append_violations, j.recall_existing], [["log.txt"], 0]);
});
test("append: a deleted line is a violation", (t) => {
  const j = append(t, L(5), L(5).replace("l2\n", ""));
  assert.deepStrictEqual([j.append_violations, j.recall_existing], [["log.txt"], 0]);
});
test("append: a deleted line starting with -- is still a violation", (t) => {
  const j = append(t, "--x\nkeep\n", "keep\n");
  assert.deepStrictEqual(j.append_violations, ["log.txt"]);
});
test("append: declared append that is not touched is no violation", (t) => {
  const { r, base } = setup(t, { "log.txt": "1\n", "o.txt": "1\n" }, [W("log.txt", "append")]);
  r.write("o.txt", "2\n"); r.commit("work");
  assert.deepStrictEqual(facts(r, base).json.append_violations, []);
});
test("append: a modify file with an add-only diff is never an append violation; one with two blocks neither", (t) => {
  const j = append(t, L(6), "top\n" + L(6) + "bottom\n", "modify");
  assert.deepStrictEqual([j.append_violations, j.recall_existing], [[], 1]);
});
