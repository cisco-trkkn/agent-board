"use strict";
// The hang guard: a test backend wrapper that builds its own {start, close, resume, ...} object around a fake backend must
// forward `usage`, or the core records no usage and parks every job "cost unknown" (a missing one hung a suite for 6 h).
// A wrapper that spreads the inner backend (`...inner`) forwards it already.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// the object literals (no nested braces) that define `start:` and `close:` as functions and neither spread nor name `usage`
function wrappersWithoutUsage(src) {
  const bad = [];
  for (const m of src.matchAll(/\{[^{}]*\bstart:\s*\([^)]*\)\s*=>[^{}]*\bclose:\s*\([^)]*\)\s*=>[^{}]*\}/g)) {
    if (!/\busage\b/.test(m[0]) && !/\.\.\.\w+/.test(m[0])) bad.push(m[0].slice(0, 80));
  }
  return bad;
}

// Mutation: make wrappersWithoutUsage return [] -> the self-check below fails.
test("the scanner flags a wrapper that drops usage and accepts one that forwards it or spreads the inner backend", () => {
  assert.equal(wrappersWithoutUsage("const b = { start: (job) => inner.start(job), close: (h) => inner.close(h), resume: (h) => inner.resume(h) };").length, 1);
  assert.equal(wrappersWithoutUsage("const b = { start: (job) => inner.start(job), close: (h) => inner.close(h), usage: (h, o) => inner.usage(h, o) };").length, 0);
  assert.equal(wrappersWithoutUsage("const b = { ...inner, start: (job) => inner.start(job), close: (h) => inner.close(h) };").length, 0);
});

test("every backend wrapper in engine/test forwards usage", () => {
  const dir = __dirname;
  const seen = [];
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith(".js") && n !== path.basename(__filename))) {
    const bad = wrappersWithoutUsage(fs.readFileSync(path.join(dir, f), "utf8"));
    for (const b of bad) seen.push(`${f}: ${b}`);
  }
  assert.deepEqual(seen, []);
});
