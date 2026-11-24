"use strict";
// The architect pass (spec section 4): the cases, and the case file a fresh frontier session is given.
// The case file holds the task or finding text, the relevant report and review, the spec's Decisions section,
// and the spec's events so far; nothing else but the answer contract.

const CASES = ["fix_rounds_exhausted", "blocked", "verify_red", "residual_findings", "tests_red_after_merge", "failed_twice"];
const DECISIONS = ["proceed", "retry_higher_tier", "park", "fail_spec"];
const CASE_TEXT = {
  fix_rounds_exhausted: "the fix rounds are exhausted and the review still has findings",
  blocked: "an implementer reported blocked",
  verify_red: "the verify command is still red after the bounces",
  residual_findings: "findings remain after the re-review",
  tests_red_after_merge: "the project tests are red after the merge",
  failed_twice: "a job failed on every attempt its retry policy allows",
};
const NOISE = /^(inbox_|timer_fired$|deadline$|step_)/; // tick bookkeeping, not part of the spec's story

// The spec's "## Decisions" section (up to the next level-2 heading), or "".
function decisions(specText) {
  const m = /^## Decisions[^\n]*\n([\s\S]*?)(?=^## |(?![\s\S]))/m.exec(String(specText || ""));
  return m ? m[1].trim() : "";
}

function eventLine(e) {
  let d = e.detail;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch (_) { d = {}; } }
  d = d && typeof d === "object" ? d : {};
  const bits = [];
  for (const k of ["task", "case", "decision", "reason", "outcome", "answer", "ok", "text", "question"]) {
    if (d[k] !== undefined && d[k] !== null && d[k] !== "") bits.push(`${k}=${String(d[k]).replace(/\s+/g, " ").slice(0, 200)}`);
  }
  return `${e.seq} ${e.kind}${e.job ? ` ${e.job}` : ""}${bits.length ? ` ${bits.join(" ")}` : ""}`;
}

const part = (title, body) => `## ${title}\n\n${body === undefined || body === null || String(body).trim() === "" ? "(none)" : String(body).trim()}\n`;

// c = {kase, spec, job?, task?, finding, report, review, decisions, events, reportPath, refusal?}
function build(c) {
  const lines = [
    `# Architect case: ${c.kase}`,
    "",
    `Spec ${c.spec}: ${CASE_TEXT[c.kase] || c.kase}.${c.job ? ` Job: ${c.job}.` : ""}${c.task === undefined || c.task === null ? "" : ` Task: ${c.task}.`}`,
    "",
    part("Task or finding", c.finding),
    part("Report", c.report),
    part("Review", c.review),
    part("Spec decisions", c.decisions),
    part("Events so far", (c.events || []).filter((e) => !NOISE.test(e.kind)).map(eventLine).join("\n")),
    "## Your answer",
    "",
    "Decide one of: `proceed` (go on as if this step had passed, the finding parked), `retry_higher_tier` (re-run the job one",
    "tier up, once per job), `park` (the spec waits for the user, your ruling is the question), `fail_spec`.",
  ];
  if (c.refusal) lines.push("", `Your earlier answer was refused (${c.refusal}): choose another decision.`);
  lines.push(
    "",
    `Report file: ${c.reportPath}`,
    "",
    "Write your reasoning there; its last fenced block must be:",
    "",
    "```json:status",
    '{"decision": "proceed" | "retry_higher_tier" | "park" | "fail_spec", "ruling": "<one sentence>", "cost_if_wrong": "<what it costs if wrong>"}',
    "```",
    "",
  );
  return lines.join("\n");
}

module.exports = { CASES, DECISIONS, decisions, eventLine, build };
