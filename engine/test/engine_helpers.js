"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");

function tmpEnv() {
  const old = { TC_ENGINE_DIR: process.env.TC_ENGINE_DIR, TC_STATE: process.env.TC_STATE, TC_IMPROVE_TICK: process.env.TC_IMPROVE_TICK };
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "eng-"));
  const engineDir = path.join(root, "engine");
  const state = path.join(root, "state");
  fs.mkdirSync(state, { recursive: true });
  process.env.TC_ENGINE_DIR = engineDir;
  process.env.TC_STATE = state;
  // No post-report `improve tick` row (queue_report.write): an engine a test restarts after a committed report would drain
  // it and open a window on the default tmux server. engine/test/improve_holds.test.js turns it back on.
  process.env.TC_IMPROVE_TICK = "0";
  return {
    root, engineDir, state,
    restore() {
      for (const [k, v] of Object.entries(old)) {
        if (v === undefined) delete process.env[k]; else process.env[k] = v;
      }
      fs.rmSync(root, { recursive: true, force: true });
    },
  };
}

function scratchTmux() {
  const dir = fs.mkdtempSync("/tmp/et-");
  const socket = "eng" + process.pid + Math.random().toString(36).slice(2, 7);
  const env = { ...process.env, TMUX_TMPDIR: dir };
  delete env.TMUX;
  const bin = process.env.TC_TMUX_BIN || "tmux";
  return {
    socket,
    run(args) {
      return cp.spawnSync(bin, ["-L", socket, "-f", "/dev/null", ...args], { env, encoding: "utf8" });
    },
    kill() {
      cp.spawnSync(bin, ["-L", socket, "-f", "/dev/null", "kill-server"], { env, encoding: "utf8" });
      fs.rmSync(dir, { recursive: true, force: true });
    },
  };
}

function gitRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "egit-"));
  const git = (...a) => cp.execFileSync("git", ["-C", dir, ...a], { encoding: "utf8" });
  git("init", "-q", "-b", "main");
  git("config", "user.email", "t@example.com");
  git("config", "user.name", "T");
  git("config", "commit.gpgsign", "false");
  fs.writeFileSync(path.join(dir, "README.md"), "x\n");
  git("add", "README.md");
  git("commit", "-q", "-m", "init");
  return { dir, git, cleanup() { fs.rmSync(dir, { recursive: true, force: true }); } };
}

module.exports = { tmpEnv, scratchTmux, gitRepo };
