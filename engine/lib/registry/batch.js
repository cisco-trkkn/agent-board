"use strict";
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// The argv prefix of the metrics CLI: REGISTRY_METRICS_CMD (split on spaces) or this checkout's tmux-ctl.
function metricsCmd() {
  const env = process.env.REGISTRY_METRICS_CMD;
  if (env && env.trim()) return env.trim().split(/\s+/);
  return ["zsh", path.join(__dirname, "../../../bin/tmux-ctl"), "metrics"];
}

function runMetrics(repo, args) {
  const [cmd, ...pre] = metricsCmd();
  const r = spawnSync(cmd, [...pre, ...args], { cwd: repo, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return { rc: r.status === null ? 1 : r.status, out: r.stdout || "", err: (r.stderr || "").trim().split("\n")[0] };
}

// readBatch(repo, id, extra) -> parsed `metrics runs <id> --json`
function readBatch(repo, id, extra) {
  const r = runMetrics(repo, ["runs", id, "--json", ...(extra || [])]);
  if (r.rc !== 0) throw new Error(`unknown batch ${id}`);
  try { return JSON.parse(r.out); } catch (_) { throw new Error(`bad metrics runs output for ${id}`); }
}

// appendAnalysis(repo, obj, extra): `extra` argv (["--log", tmp]) is for tests only.
function appendAnalysis(repo, obj, extra) {
  const r = runMetrics(repo, ["append", "analysis", "--json", JSON.stringify(obj), ...(extra || [])]);
  if (r.rc !== 0) throw new Error(r.err || "metrics append failed");
}

module.exports = { metricsCmd, readBatch, appendAnalysis };
