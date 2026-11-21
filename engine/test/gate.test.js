"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { scratchRepo, cleanup } = require("./helpers.js");

const ROOT = path.join(__dirname, "../..");
const CTL = path.join(ROOT, "bin/tmux-ctl");

const ctl = (...a) => spawnSync("zsh", [CTL, "metrics", ...a], { encoding: "utf8" });

test("an analysis line appended with metrics append is read back by metrics gate K1", (t) => {
  const r = scratchRepo();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "gate-"));
  t.after(() => { cleanup(r.dir); fs.rmSync(tmp, { recursive: true, force: true }); });
  for (const f of ["gates/K1.md", "configs/upfront-seq.md"]) {
    const src = fs.readFileSync(path.join(ROOT, "docs/superpowers/metrics", f), "utf8");
    r.write(path.join("docs/superpowers/metrics", f), src);
  }
  r.commit("metrics docs");
  const log = path.join(tmp, "runs.jsonl");
  for (let i = 0; i < 4; i++) {
    fs.appendFileSync(log, JSON.stringify({ kind: "run", batch: "b", spec: `s${i}`, refreshes: 0,
      tokens: { total: 1000 }, manifest: { recall_existing: 0.95 }, manifest_tokens: 50 }) + "\n");
  }
  const ap = ctl("append", "analysis", "--repo", r.dir, "--json",
    JSON.stringify({ appends_verified: true, parallelism: 2, waves: { append: 2 } }), "--batch", "b", "--log", log);
  assert.equal(ap.status, 0, ap.stderr);
  const g = ctl("gate", "K1", "--repo", r.dir, "--log", log);
  assert.equal(g.status, 0, g.stdout + g.stderr);
  assert.match(g.stdout, /^gate K1: pass\n/);
  assert.match(g.stdout, /analysis\.parallelism 2 \(min 1\.5\) \(append waves 2\) pass/);
});
