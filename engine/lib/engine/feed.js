"use strict";
// Best-effort mirror of engine events to the board feed (spec Addition: publish to the feed).
const fs = require("node:fs");
const path = require("node:path");
const paths = require("./paths");

const CRITICAL = new Set(["fail_spec", "engine_error"]);
const DECISION = new Set(["park", "awaiting_you"]);
const PROGRESS = new Set(["job_done", "review_verdict", "merge"]);

function tier(event, detail) {
  if (CRITICAL.has(event.kind)) return "critical";
  if (DECISION.has(event.kind) || (event.kind === "ruling" && detail.needs_user)) return "decision";
  if (PROGRESS.has(event.kind)) return "progress";
  return "routine";
}

function specName(spec) {
  if (!spec) return "";
  return path.basename(String(spec).split("#")[0]).replace(/\.md$/, "");
}

function summary(detail) {
  for (const k of ["text", "question", "reason", "error", "key"]) {
    if (typeof detail[k] === "string" && detail[k]) return detail[k];
  }
  return "";
}

function line(project, event) {
  let detail = event.detail;
  if (typeof detail === "string") { try { detail = JSON.parse(detail); } catch (_) { detail = {}; } }
  detail = detail && typeof detail === "object" ? detail : {};
  const s = summary(detail);
  const text = `${event.kind}${s ? ": " + s : ""}`.replace(/\s+/g, " ").trim().slice(0, 300);
  return {
    ts: event.ts, project, spec: specName(event.spec), kind: event.kind, tier: tier(event, detail), text,
    refs: event.job ? { run: event.job } : {},
  };
}

function publish(project, event) {
  try {
    const p = paths.feedPath(project);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.appendFileSync(p, JSON.stringify(line(project, event)) + "\n");
  } catch (_) { /* best effort, never fails the job */ }
}

module.exports = { publish, line };
