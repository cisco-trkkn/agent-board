"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");

const report = require("../lib/engine/report");
const compile = require("../lib/engine/compile");
const bounce = require("../lib/engine/bounce");

const REPO = path.resolve(__dirname, "..", "..");
const TASKS = path.join(REPO, "docs/superpowers/plans/2026-11-21-interactive-tasks-window.md.tasks.json");

const fence = (obj) => "```json:status\n" + (typeof obj === "string" ? obj : JSON.stringify(obj)) + "\n```\n";

test("report: implementer shape, last block wins", () => {
  const first = { status: "blocked", commits: [], concerns: ["x"] };
  const second = { status: "done", commits: ["abc"], concerns: [] };
  const text = "intro\n" + fence(first) + "more text\n" + fence(second) + "tail\n";
  assert.deepEqual(report.parse(text, "implement"), second);
  assert.deepEqual(report.parse(fence(second), "fix"), second);
  assert.deepEqual(report.parse(fence(second), "refresh"), second);
  assert.deepEqual(report.parse(fence(second), "fix_wave"), second);
});

test("report: absent, malformed and wrong-shape give null", () => {
  assert.equal(report.parse("no block here", "implement"), null);
  assert.equal(report.parse(fence("{not json"), "implement"), null);
  assert.equal(report.parse("```json\n{\"status\":\"done\",\"commits\":[],\"concerns\":[]}\n```", "implement"), null);
  assert.equal(report.parse(fence({ status: "maybe", commits: [], concerns: [] }), "implement"), null);
  assert.equal(report.parse(fence({ status: "done", commits: "a", concerns: [] }), "implement"), null);
  assert.equal(report.parse(fence({ status: "done", commits: [] }), "implement"), null);
  assert.equal(report.parse(fence({ status: "done", commits: [], concerns: [] }), "review"), null);
  assert.equal(report.parse(fence({ status: "done", commits: [], concerns: [] }), "nonsense"), null);
  assert.equal(report.parse(null, "implement"), null);
  // a valid block followed by a broken last block: the last one counts
  assert.equal(report.parse(fence({ status: "done", commits: [], concerns: [] }) + fence("oops"), "implement"), null);
});

test("report: reviewer shape", () => {
  const ok = { verdict: "findings", findings: [{ severity: "important", task: 3, text: "t" }] };
  for (const k of ["review", "re_review", "final_review"]) assert.deepEqual(report.parse(fence(ok), k), ok);
  assert.deepEqual(report.parse(fence({ verdict: "pass", findings: [] }), "review"), { verdict: "pass", findings: [] });
  assert.equal(report.parse(fence({ verdict: "pass" }), "review"), null);
  assert.equal(report.parse(fence({ verdict: "findings", findings: [{ severity: "huge", task: 1, text: "t" }] }), "review"), null);
  assert.equal(report.parse(fence({ verdict: "findings", findings: [{ severity: "minor", task: "1", text: "t" }] }), "review"), null);
  assert.equal(report.parse(fence({ verdict: "findings", findings: [{ severity: "minor", task: 1 }] }), "review"), null);
  assert.equal(report.parse(fence({ verdict: "other", findings: [] }), "review"), null);
});

test("report: architect shape", () => {
  const ok = { decision: "retry_higher_tier", ruling: "r", cost_if_wrong: "c" };
  assert.deepEqual(report.parse(fence(ok), "architect"), ok);
  for (const d of ["proceed", "fail_spec"]) assert.ok(report.parse(fence({ ...ok, decision: d }), "architect"));
  const rec = { option: "approve", why: "w", confidence: "low" };
  assert.ok(report.parse(fence({ ...ok, decision: "park", recommend: rec }), "architect"));
  assert.equal(report.parse(fence({ ...ok, decision: "park" }), "architect"), null);
  for (const bad of [{ ...rec, option: "proceed" }, { ...rec, why: "" }, { ...rec, confidence: "sure" }, "approve"])
    assert.equal(report.parse(fence({ ...ok, decision: "park", recommend: bad }), "architect"), null);
  assert.ok(report.parse(fence({ ...ok, decision: "proceed", recommend: rec }), "architect"));
  assert.equal(report.parse(fence({ ...ok, decision: "x" }), "architect"), null);
  assert.equal(report.parse(fence({ decision: "proceed", ruling: "r" }), "architect"), null);
});

test("compile: real .tasks.json", () => {
  const text = fs.readFileSync(TASKS, "utf8");
  const res = compile.compile(text);
  assert.equal(res.error, undefined);
  const raw = JSON.parse(text).tasks;
  assert.equal(res.tasks.length, raw.length);
  res.tasks.forEach((t, i) => {
    assert.equal(t.n, i + 1);
    assert.equal(t.subject, raw[i].subject);
    assert.ok(["mechanical", "standard", "frontier"].includes(t.tier), t.tier);
    assert.ok(Array.isArray(t.files));
    assert.ok(t.verifyCommand.length > 0);
  });
  assert.deepEqual(res.tasks[0].files, ["board/planview.py", "board/tests/test_planview.py"]);
  assert.equal(res.tasks[0].tier, "mechanical");
  assert.equal(res.tasks[0].verifyCommand, "python3 -m unittest discover -s board/tests -p 'test_planview.py'");
});

function withMeta(meta) {
  return JSON.stringify({ tasks: [{ subject: "S", description: "body\n\n```json:metadata\n" + JSON.stringify(meta) + "\n```" }] });
}

test("compile: errors and defaults", () => {
  assert.deepEqual(compile.compile(null), { error: "no .tasks.json" });
  assert.deepEqual(compile.compile(undefined), { error: "no .tasks.json" });
  const two = JSON.stringify({ tasks: [
    { subject: "A", description: "```json:metadata\n{\"verifyCommand\":\"true\",\"modelTier\":\"standard\"}\n```" },
    { subject: "B", description: "```json:metadata\n{\"verifyCommand\":\"\",\"modelTier\":\"standard\"}\n```" },
  ] });
  assert.deepEqual(compile.compile(two), { error: "no verifyCommand: task 2" });
  assert.deepEqual(compile.compile(withMeta({ modelTier: "standard" })), { error: "no verifyCommand: task 1" });
  assert.deepEqual(compile.compile(JSON.stringify({ tasks: [{ subject: "S", description: "no fence" }] })), { error: "no verifyCommand: task 1" });
  assert.deepEqual(compile.compile(withMeta({ verifyCommand: "true", modelTier: "frontier" })),
    { tasks: [{ n: 1, subject: "S", tier: "frontier", files: [], verifyCommand: "true" }] });
});

test("compile: metadata fence tolerates a trailing newline, trailing text, and takes the last fence", () => {
  const fence = (o) => "```json:metadata\n" + JSON.stringify(o) + "\n```";
  const doc = (d) => JSON.stringify({ tasks: [{ subject: "S", description: d }] });
  const want = { tasks: [{ n: 1, subject: "S", tier: "standard", files: [], verifyCommand: "true" }] };
  const m = { verifyCommand: "true", modelTier: "standard" };
  assert.deepEqual(compile.compile(doc("body\n\n" + fence(m) + "\n")), want);
  assert.deepEqual(compile.compile(doc("body\n\n" + fence(m) + "\n\n  \n")), want);
  assert.deepEqual(compile.compile(doc("body\n\n" + fence(m) + "\n\nNotes after the fence.")), want);
  assert.deepEqual(compile.compile(doc(fence({ verifyCommand: "false", modelTier: "mechanical" }) + "\nmid\n" + fence(m) + "\ntail\n")), want);
});

function redRuns() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "bounce-"));
  try {
    fs.writeFileSync(path.join(d, "f.test.js"),
      "const t=require('node:test');const a=require('node:assert/strict');t('adds',()=>{a.equal(1+1,3)});\n");
    fs.writeFileSync(path.join(d, "t.py"),
      "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(1+1,3)\nunittest.main()\n");
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT; // else the inner run reports to the outer runner instead of printing
    const n = cp.spawnSync(process.execPath, ["--test", "--test-reporter=tap", "f.test.js"], { cwd: d, env, encoding: "utf8" });
    const p = cp.spawnSync("python3", ["t.py"], { cwd: d, encoding: "utf8" });
    return { node: n.stdout + n.stderr, py: p.stdout + p.stderr };
  } finally { fs.rmSync(d, { recursive: true, force: true }); }
}

test("bounce: real node --test and unittest red outputs", () => {
  const { node, py } = redRuns();
  assert.match(node, /^not ok 1 - adds/m);
  assert.match(py, /^FAILED/m);

  const a = bounce.text(node, "/tmp/log-a.txt");
  const la = a.text.split("\n");
  assert.ok(la.includes("not ok 1 - adds"));
  assert.ok(la.some((l) => /^\s+expected: 3/.test(l)));
  assert.ok(la.some((l) => /^\s+actual: 2/.test(l)));
  assert.ok(la.includes("# fail 1"));
  assert.equal(la[la.length - 1], "full log: /tmp/log-a.txt");
  assert.ok(!a.text.includes("duration_ms"));
  assert.equal(a.bytes, Buffer.byteLength(a.text));

  const b = bounce.text(py, "/tmp/log-b.txt");
  const lb = b.text.split("\n");
  assert.ok(lb.some((l) => /^FAIL: test_x/.test(l)));
  assert.ok(lb.includes("AssertionError: 2 != 3"));
  assert.ok(lb.includes("FAILED (failures=1)"));
  assert.ok(!lb.some((l) => l.startsWith("Traceback")));
  assert.equal(lb[lb.length - 1], "full log: /tmp/log-b.txt");
});

test("bounce: at most 3 detail lines per failure and the line cap", () => {
  const out = ["not ok 1 - a", "  at x", "  at y", "  at z", "  at w", "  expected: 1", "# fail 1"].join("\n");
  const r = bounce.text(out, "L");
  assert.deepEqual(r.text.split("\n"), ["not ok 1 - a", "  at x", "  at y", "  at z", "# fail 1", "full log: L"]);

  const many = [];
  for (let i = 0; i < 200; i++) many.push("not ok " + i + " - t" + i);
  many.push("# fail 200");
  const big = bounce.text(many.join("\n"), "L");
  const lines = big.text.split("\n");
  assert.equal(bounce.BOUNCE_MAX_LINES, 60);
  assert.equal(lines.length, bounce.BOUNCE_MAX_LINES);
  assert.equal(lines[lines.length - 1], "full log: L");
  assert.equal(lines[lines.length - 2], "# fail 200");
  assert.equal(lines[0], "not ok 0 - t0");

  assert.deepEqual(bounce.text("", "L").text, "full log: L");
});

test("architect.build's answer contract shows recommend and says park needs it", () => {
  const text = require("../lib/engine/architect").build({ kase: "blocked", spec: "s.md", finding: "F", reportPath: "/r" });
  assert.ok(text.includes('"recommend": {"option": "approve" | "deny" | "fail", "why": "<one line>", "confidence": "low" | "medium" | "high"}'));
  assert.match(text, /`recommend` is required for `park`/);
});
