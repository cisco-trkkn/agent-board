"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const ledger = require("../lib/engine/ledger");

const jobDone = (kind, findings) => ({ kind: "job_done", detail: JSON.stringify({ rows: [{ table: "jobs", row: { id: "j1", kind } }], status: { findings } }) });
const f = (severity) => ({ severity, text: "x" });

test("integrated tests_red renders the merge line", () => {
  const out = ledger.render([{ kind: "integrated", detail: JSON.stringify({ outcome: "tests_red" }) }]);
  assert.match(out, /^Merge: tests red after the merge$/m);
});

test("a merged integrated event adds no line", () => {
  const out = ledger.render([{ kind: "integrated", detail: JSON.stringify({ outcome: "merged" }) }]);
  assert.equal(out, "# Progress\n\n");
});

test("final_review job_done counts critical and important findings", () => {
  const out = ledger.render([jobDone("final_review", [f("critical"), f("important"), f("minor"), f("important")])]);
  assert.match(out, /^Final review: 3 critical\/important finding\(s\)$/m);
});

test("final_review with no findings renders 0", () => {
  assert.match(ledger.render([jobDone("final_review", [])]), /^Final review: 0 critical\/important finding\(s\)$/m);
});

test("a review job's job_done adds no line, and render skips null (mutation: drop the skip)", () => {
  const out = ledger.render([jobDone("review", [f("critical")])]);
  assert.equal(out, "# Progress\n\n");
  assert.ok(!out.includes("null"));
});
