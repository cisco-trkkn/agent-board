"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync, execFileSync } = require("node:child_process");

const BIN = path.join(__dirname, "../bin/registry.js");

// run(args, opts) -> {code, stdout, stderr}: the registry CLI in a child node process.
function run(args, opts) {
  const r = spawnSync(process.execPath, [BIN, ...args], { encoding: "utf8", ...opts });
  return { code: r.status, stdout: r.stdout, stderr: r.stderr };
}

// scratchRepo() -> a temp git repo on branch main with a test identity.
// Callers remove it with cleanup(dir) in an after() hook.
function scratchRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reg-"));
  const git = (...args) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
  git("init", "-q", "-b", "main");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  return {
    dir,
    git,
    write(rel, text) {
      const abs = path.join(dir, rel);
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      fs.writeFileSync(abs, text);
    },
    commit(msg) {
      git("add", "-A");
      git("commit", "-q", "--allow-empty", "-m", msg);
      return git("rev-parse", "HEAD");
    },
  };
}

function cleanup(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

module.exports = { run, scratchRepo, cleanup };
