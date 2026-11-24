"use strict";

const FENCE = /^```json:status[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/gm;
const SEVERITIES = ["critical", "important", "minor"];

const isStrArray = (v) => Array.isArray(v) && v.every((x) => typeof x === "string");
const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

function implementer(o) {
  return ["done", "blocked"].includes(o.status) && isStrArray(o.commits) && isStrArray(o.concerns);
}
function reviewer(o) {
  return ["pass", "findings"].includes(o.verdict) && Array.isArray(o.findings) &&
    o.findings.every((f) => isObj(f) && SEVERITIES.includes(f.severity) &&
      Number.isInteger(f.task) && typeof f.text === "string");
}
const recommend = (r) => isObj(r) && ["approve", "deny", "fail"].includes(r.option) &&
  typeof r.why === "string" && r.why.trim() !== "" && ["low", "medium", "high"].includes(r.confidence);
function architect(o) {
  return ["proceed", "retry_higher_tier", "park", "fail_spec"].includes(o.decision) &&
    typeof o.ruling === "string" && typeof o.cost_if_wrong === "string" && (o.decision !== "park" || recommend(o.recommend));
}

const SHAPES = {
  implement: implementer, fix: implementer, refresh: implementer, fix_wave: implementer,
  review: reviewer, re_review: reviewer, final_review: reviewer,
  architect,
};

// The LAST fenced block tagged json:status, checked against the job kind's shape; null otherwise.
function parse(text, kind) {
  const check = SHAPES[kind];
  if (!check || typeof text !== "string") return null;
  let last = null;
  for (const m of text.matchAll(FENCE)) last = m[1];
  if (last === null) return null;
  let obj;
  try { obj = JSON.parse(last); } catch { return null; }
  return isObj(obj) && check(obj) ? obj : null;
}

module.exports = { parse };
