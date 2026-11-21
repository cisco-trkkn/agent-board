"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { run, scratchRepo, cleanup } = require("./helpers.js");

const USAGE = "registry: usage: registry <validate|analyse|stale|report|facts> ...\n";

test("no args prints the usage line and exits 2", () => {
  const r = run([]);
  assert.equal(r.code, 2);
  assert.equal(r.stderr, USAGE);
});

test("an unknown subcommand prints the usage line and exits 2", () => {
  const r = run(["bogus"]);
  assert.equal(r.code, 2);
  assert.equal(r.stderr, USAGE);
});

test("a subcommand that throws prints one error line and exits 1", () => {
  const r = run(["facts"]);
  assert.equal(r.code, 1);
  assert.match(r.stderr, /^registry: facts: [^\n]+\n$/);
});

test("scratchRepo makes a main-branch git repo and cleanup removes it", () => {
  const repo = scratchRepo();
  try {
    repo.write("a/b.txt", "one\n");
    const sha = repo.commit("first");
    assert.equal(repo.git("rev-parse", "--abbrev-ref", "HEAD"), "main");
    assert.equal(sha.length, 40);
    assert.equal(fs.readFileSync(repo.dir + "/a/b.txt", "utf8"), "one\n");
  } finally {
    cleanup(repo.dir);
  }
  assert.equal(fs.existsSync(repo.dir), false);
});
