"use strict";
// Renders the progress ledger (docs/superpowers/ledgers/<plan>/progress.md) from a spec's events, in the
// line forms board/metrics.py `ledger_fields` counts. Input: events as db rows ({kind, detail}) or plain objects;
// `detail` may be a JSON string or an object, its fields are merged over the event's own.
const parse = (s) => {
  if (s && typeof s === "object") return s;
  try { return JSON.parse(s) || {}; } catch (_) { return {}; }
};
const flat = (e) => ({ ...e, ...parse(e.detail) });

const LINES = {
  dispatched: (e) => `Task ${e.task}: dispatched ${e.window} (${e.tier}, ${e.model})`,
  green_check: (e) => `Task ${e.task}: green check ok (verify rc ${e.rc === undefined ? 0 : e.rc}) — ${e.sha}`,
  review: (e) => (e.findings ? `Task ${e.task}: review ❌ ${e.findings} finding(s)${e.text ? `: ${e.text}` : ""}` : `Task ${e.task}: review ✅ clean`),
  fix_round: (e) => `Task ${e.task}: fix round ${e.round}`,
  minor: (e) => `Task ${e.task}: minor (deferred): ${e.text}`,
  ruling: (e) => `Ruling: ${e.text} — ${e.cost || e.cost_if_wrong}`,
  fix_wave: () => "Final review: fix wave",
  integrated: (e) => (e.outcome === "tests_red" ? "Merge: tests red after the merge" : null),
  job_done: (e) => {
    const row = (e.rows || []).find((r) => r && r.table === "jobs");
    if (!row || !row.row || row.row.kind !== "final_review") return null;
    const n = ((e.status && e.status.findings) || []).filter((x) => x && (x.severity === "critical" || x.severity === "important")).length;
    return `Final review: ${n} critical/important finding(s)`;
  },
  task_complete: (e) => `Task ${e.task}: complete (commits ${e.first}..${e.last}, review clean)`,
};

function render(events) {
  const out = ["# Progress", ""];
  for (const raw of events) {
    const e = flat(raw);
    const f = LINES[e.kind];
    const line = f ? f(e) : null;
    if (line !== null) out.push(line);
  }
  return out.join("\n") + "\n";
}

module.exports = { render, LINES };
