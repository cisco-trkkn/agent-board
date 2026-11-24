"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const POLICY_VERSION = 1;

const row = (max_attempts, backoff, timeout_min, no_retry_on, on_exhausted) =>
  ({ max_attempts, backoff_s: [backoff], timeout_min, no_retry_on, on_exhausted });
const impl = () => row(2, 30, 90, ["blocked", "usage_limit"], "architect");

const DEFAULT_RETRY = {
  implement: impl(), fix: impl(), refresh: impl(),
  review: row(2, 30, 45, ["usage_limit"], "architect"),
  final_review: row(2, 60, 90, ["usage_limit"], "architect"),
  architect: row(2, 60, 30, ["usage_limit"], "park"),
  bounce: row(3, 0, null, [], "architect"),
  fix_round: row(5, 0, null, [], "architect"),
};

function loadConfig(repo) {
  const file = path.join(repo, "docs/superpowers/engine.json");
  let raw;
  try { raw = fs.readFileSync(file, "utf8"); } catch (e) {
    if (e.code === "ENOENT") return { test: null, test_ok: [0], retry: {}, raw: "{}" };
    throw e;
  }
  const j = JSON.parse(raw);
  return { test: j.test || null, test_ok: j.test_ok || [0], retry: j.retry || {}, raw };
}

function retryFor(config, kind) {
  return { ...(DEFAULT_RETRY[kind] || {}), ...((config && config.retry && config.retry[kind]) || {}) };
}

const policyHash = (config) =>
  crypto.createHash("sha256").update(config && config.raw !== undefined ? config.raw : "{}").digest("hex");

module.exports = { POLICY_VERSION, DEFAULT_RETRY, loadConfig, retryFor, policyHash };
