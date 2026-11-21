"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { mainRoot } = require("./git.js");
const { readBatch, appendAnalysis } = require("./batch.js");
const { computeFacts } = require("./facts.js");
const { runAnalyse, loadPlans, analysisLine, PRED } = require("./analyse.js");
const G = require("./graphs.js");

const POLICIES = ["strict", "append", "writes_only"];
const SENTENCE = "Textual results do not show semantic conflicts.";
const fmt = (x) => (x === null || x === undefined ? "-" : String(Math.round(x * 1e4) / 1e4));
const list = (a) => (a && a.length ? a.join(", ") : "-");

function factsRows(repo, batch) {
  const rows = [];
  for (const spec of batch.specs || []) {
    const r = (batch.runs || {})[spec];
    if (!r || !r.base || !r.head) continue;
    try { rows.push({ spec, f: computeFacts(repo, spec, r.base, r.head) }); } catch (e) {
      rows.push({ spec, error: String(e.message).split("\n")[0] });
    }
  }
  return rows;
}

// A violated append is a modify for the recount.
function downgrade(plans, rows) {
  const bad = new Map(rows.filter((x) => x.f).map((x) => [x.spec, new Set(x.f.append_violations)]));
  return plans.map((p) => {
    const v = bad.get(p.spec);
    if (!v || !v.size) return p;
    const writes = (p.manifest.writes || []).map((w) => (w.mode === "append" && v.has(w.path) ? { ...w, mode: "modify" } : w));
    return { spec: p.spec, manifest: { ...p.manifest, writes } };
  });
}

function pairTable(pairs, plans, relations) {
  if (pairs === null || pairs === undefined) return ["Pairs: unavailable (git merge-tree failed)"];
  const o = ["| policy | predicted & clean | predicted & conflicting | not predicted & conflicting | not predicted & clean |", "| --- | --- | --- | --- | --- |"];
  for (const pol of POLICIES) {
    const pred = new Set(G.conflictEdges(plans, pol, relations).map((e) => `${e.a}|${e.b}`));
    const t = [0, 0, 0, 0];
    for (const p of pairs) {
      const predicted = pred.has(`${[p.a, p.b].sort().join("|")}`);
      t[predicted ? (p.clean ? 0 : 1) : (p.clean ? 3 : 2)] += 1;
    }
    o.push(`| ${pol} | ${t.join(" | ")} |`);
  }
  return o;
}

function section(rows, pairLines) {
  const o = [PRED, "", "| spec | recall_existing | recall_created | precision | refreshes | missed | append violations |", "| --- | --- | --- | --- | --- | --- | --- |"];
  for (const x of rows) {
    if (x.error) { o.push(`| ${x.spec} | n/a: ${x.error} | | | | | |`); continue; }
    const f = x.f;
    o.push(`| ${x.spec} | ${fmt(f.recall_existing)} | ${fmt(f.recall_created)} | ${fmt(f.precision)} | ${f.refreshes} | ${list(f.missed)} | ${list(f.append_violations)} |`);
  }
  if (!rows.length) o.push("| none | | | | | | |");
  o.push("", ...pairLines, "", SENTENCE, "");
  return o.join("\n");
}

function runReport(repo, batchId, relationsPath, opts) {
  const extra = (opts && opts.extra) || [];
  const batch = readBatch(repo, batchId, extra);
  const docPath = path.join(mainRoot(repo), "docs/superpowers/metrics/analysis", `${batchId}.md`);
  if (!fs.existsSync(docPath)) runAnalyse(repo, batchId, relationsPath, { extra });
  const { plans, relations } = loadPlans(repo, batch, relationsPath, batchId);
  const rows = factsRows(repo, batch);
  const body = section(rows, pairTable(batch.pairs, plans, relations));
  let doc = fs.readFileSync(docPath, "utf8");
  const i = doc.indexOf(PRED);
  if (i >= 0) doc = doc.slice(0, i);
  doc = doc.replace(/\s+$/, "") + "\n\n" + body;
  fs.writeFileSync(docPath, doc);
  const line = analysisLine(batchId, downgrade(plans, rows), relations, true);
  appendAnalysis(repo, line, extra);
  return { docPath, line };
}

function main(argv, ctx) {
  let batchId = null;
  let rel = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--relations") rel = argv[++i] || null;
    else if (!batchId) batchId = argv[i];
  }
  if (!batchId) throw new Error("usage: registry report <batch> [--relations <file>]");
  const { docPath } = runReport(ctx.cwd, batchId, rel);
  ctx.out(`report: ${path.relative(mainRoot(ctx.cwd), docPath)}`);
  return 0;
}

module.exports = { runReport, main };
