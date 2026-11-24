"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const POLICY_VERSION = 2;

const ASK_KINDS = ["stop_class", "needs_you", "architect_park", "policy_change", "cannot_tell", "user_gate", "budget"];
const CONFIDENCE = ["low", "medium", "high"];
const ASK_DEFAULTS = {
  cannot_tell: { option: "approve", why: "the check cannot see the side effect; it most likely ran", confidence: "low" },
  policy_change: { option: "approve", why: "the new policy was set by the user", confidence: "medium" },
  needs_you: { option: "approve", why: "the worker is waiting on a prompt it raised", confidence: "low" },
  stop_class: { option: "deny", why: "an irreversible step needs your yes", confidence: "medium" },
  user_gate: { option: "approve", why: "the plan marks this task as yours to check", confidence: "low" },
};
const DEFAULT_BUDGET = { attempts: 60, tokens: 5000000 };

function recommendationFor(kind, override) {
  if (override) return override;
  if (ASK_DEFAULTS[kind]) return ASK_DEFAULTS[kind];
  throw new Error(`no recommendation for ${kind}`);
}

// Why a wait row is not acceptable, or null. `rec` is the recommendation (object or JSON text), `options` the wait's "a|b|c".
function waitProblem(row) {
  if (!ASK_KINDS.includes(row.kind)) return "kind";
  let rec = row.recommendation;
  if (typeof rec === "string") { try { rec = JSON.parse(rec); } catch { return "recommendation"; } }
  if (!rec || typeof rec !== "object" || Array.isArray(rec)) return "recommendation";
  const options = String(row.options === undefined || row.options === null ? "approve|deny|fail" : row.options).split("|");
  if (!options.includes(rec.option) || typeof rec.why !== "string" || !rec.why.trim() || !CONFIDENCE.includes(rec.confidence)) return "recommendation";
  return null;
}

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
    if (e.code === "ENOENT") return { test: null, test_ok: [0], retry: {}, budget: { ...DEFAULT_BUDGET }, raw: "{}" };
    throw e;
  }
  const j = JSON.parse(raw);
  return { test: j.test || null, test_ok: j.test_ok || [0], retry: j.retry || {}, budget: { ...DEFAULT_BUDGET, ...(j.budget || {}) }, raw };
}

function retryFor(config, kind) {
  return { ...(DEFAULT_RETRY[kind] || {}), ...((config && config.retry && config.retry[kind]) || {}) };
}

const policyHash = (config) =>
  crypto.createHash("sha256")
    .update((config && config.raw !== undefined ? config.raw : "{}") + "\n" + JSON.stringify(ASK_DEFAULTS)).digest("hex");

module.exports = { POLICY_VERSION, ASK_KINDS, ASK_DEFAULTS, DEFAULT_BUDGET, recommendationFor, waitProblem, DEFAULT_RETRY, loadConfig, retryFor, policyHash };
