"use strict";
const test = require("node:test");
const assert = require("node:assert");
const g = require("../lib/registry/graphs.js");
const past13 = require("./fixtures/past13.json");

const P = (spec, o = {}) => ({
  spec,
  manifest: {
    writes: (o.writes || []).map((w) => (typeof w === "string" ? { path: w, mode: "modify" } : w)),
    reads: o.reads || [],
    depends_on: o.deps || [],
  },
});
const ap = (p) => ({ path: p, mode: "append" });

test("appendPair: both append one file -> conflict under strict only (drop the append exemption -> fails)", () => {
  const plans = [P("a", { writes: [ap("f")] }), P("b", { writes: [ap("f")] })];
  assert.strictEqual(g.conflictEdges(plans, "strict", []).length, 1);
  assert.strictEqual(g.conflictEdges(plans, "append", []).length, 0);
  assert.strictEqual(g.conflictEdges(plans, "writes_only", []).length, 1);
  assert.deepStrictEqual(g.conflictEdges(plans, "strict", [])[0], { a: "a", b: "b", paths: ["f"], source: "manifest" });
});

test("write vs read -> conflict under strict and append, not writes_only (make writes_only count reads -> fails)", () => {
  const plans = [P("a", { writes: ["f"] }), P("b", { reads: ["f"] })];
  assert.strictEqual(g.conflictEdges(plans, "strict", []).length, 1);
  assert.strictEqual(g.conflictEdges(plans, "append", []).length, 1);
  assert.strictEqual(g.conflictEdges(plans, "writes_only", []).length, 0);
});

test("append write vs read of same path is still a conflict under append policy", () => {
  const plans = [P("a", { writes: [ap("f")] }), P("b", { reads: ["f"] })];
  assert.strictEqual(g.conflictEdges(plans, "append", []).length, 1);
});

test("hard dependency -> later wave, no conflict needed (ignore depends_on -> fails)", () => {
  const plans = [P("b", { writes: ["x"], deps: [{ spec: "a", kind: "hard" }] }), P("a", { writes: ["y"] })];
  assert.deepStrictEqual(g.waves(plans, "strict", []), { a: 0, b: 1 });
  assert.deepStrictEqual(g.dependencyEdges(plans, []), [{ from: "b", to: "a", kind: "hard", source: "manifest" }]);
});

test("soft dependency never moves a wave; deps outside the batch are dropped", () => {
  const plans = [P("b", { deps: [{ spec: "a", kind: "soft" }, { spec: "zzz", kind: "hard" }] }), P("a")];
  assert.deepStrictEqual(g.waves(plans, "strict", []), { a: 0, b: 0 });
  assert.deepStrictEqual(g.dependencyEdges(plans, []), [{ from: "b", to: "a", kind: "soft", source: "manifest" }]);
});

test("interface relation is a conflict under all three policies", () => {
  const plans = [P("a"), P("b")];
  const rel = [{ a: "b", b: "a", kind: "interface", why: "x" }];
  for (const pol of ["strict", "append", "writes_only"]) {
    assert.deepStrictEqual(g.conflictEdges(plans, pol, rel), [{ a: "a", b: "b", paths: [], source: "crossplan" }]);
    assert.deepStrictEqual(g.waves(plans, pol, rel), { a: 0, b: 1 });
  }
});

test("order relation is a dependency edge and moves a wave", () => {
  const plans = [P("a"), P("b")];
  const rel = [{ a: "b", b: "a", kind: "order", why: "x" }];
  assert.deepStrictEqual(g.dependencyEdges(plans, rel), [{ from: "b", to: "a", kind: "order", source: "crossplan" }]);
  assert.deepStrictEqual(g.waves(plans, "strict", rel), { a: 0, b: 1 });
});

test("hard dependency cycle throws", () => {
  const plans = [P("a", { deps: [{ spec: "b", kind: "hard" }] }), P("b", { deps: [{ spec: "a", kind: "hard" }] })];
  assert.throws(() => g.waves(plans, "strict", []), /^Error: dependency cycle: /);
});

test("tie-break is deterministic: input order does not change waves", () => {
  const plans = [P("c", { writes: ["f", "g"] }), P("a", { writes: ["f"] }), P("b", { writes: ["g"] }), P("d", { writes: ["h"] })];
  const w1 = g.waves(plans, "strict", []);
  const w2 = g.waves([...plans].reverse(), "strict", []);
  assert.deepStrictEqual(w1, w2);
  assert.deepStrictEqual(w1, { a: 1, b: 1, c: 0, d: 0 });
});

test("clusters: hard deps and non-append strict conflicts join; append-only pairs and soft/relations do not", () => {
  const plans = [
    P("a", { writes: ["f"] }), P("b", { writes: ["f"] }),
    P("c", { writes: [ap("l")] }), P("d", { writes: [ap("l")] }),
    P("e", { deps: [{ spec: "a", kind: "hard" }] }),
    P("h", { deps: [{ spec: "c", kind: "soft" }] }),
    P("i"),
  ];
  const rel = [{ a: "i", b: "d", kind: "interface", why: "x" }];
  assert.deepStrictEqual(g.clusters(plans, rel), [["a", "b", "e"], ["c"], ["d"], ["h"], ["i"]]);
});

test("hotFiles: paths written by >= 3 plans, count desc then path", () => {
  const plans = [P("a", { writes: ["x", "y"] }), P("b", { writes: ["x", "y"] }), P("c", { writes: ["x", "y", "w"] }), P("d", { writes: ["w"] }), P("e", { writes: ["w"] })];
  assert.deepStrictEqual(g.hotFiles(plans), [{ path: "w", count: 3 }, { path: "x", count: 3 }, { path: "y", count: 3 }]);
  assert.deepStrictEqual(g.hotFiles([P("a", { writes: ["x"] })]), []);
});

test("summary: counts, ratios to 4 decimals, empty -> zeros", () => {
  const plans = [P("a", { writes: ["f"] }), P("b", { writes: ["f"] }), P("c", { writes: ["z"] })];
  const s = g.summary(plans, []);
  assert.deepStrictEqual(s.waves, { strict: 2, append: 2, writes_only: 2 });
  assert.strictEqual(s.parallelism, 1.5);
  assert.strictEqual(s.clusters, 2);
  assert.strictEqual(g.summary([P("a"), P("b"), P("c")], []).parallelism, 3);
  const four = [P("a", { writes: ["f"] }), P("b", { writes: ["f"] }), P("c", { writes: ["f"] }), P("d", { writes: ["q"] })];
  assert.strictEqual(g.summary(four, []).parallelism, 1.3333);
  assert.deepStrictEqual(g.summary([], []), { waves: { strict: 0, append: 0, writes_only: 0 }, parallelism: 0, parallelism_strict: 0, parallelism_writes_only: 0, clusters: 0 });
});

test("past13: strict wave count is 6", () => {
  const plans = Object.entries(past13).map(([spec, files]) => ({
    spec,
    manifest: { writes: files.map((p) => ({ path: p, mode: "modify" })), reads: [], depends_on: [] },
  }));
  assert.strictEqual(plans.length, 13);
  assert.strictEqual(g.summary(plans, []).waves.strict, 6);
});
