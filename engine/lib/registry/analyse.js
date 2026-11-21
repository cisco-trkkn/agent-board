"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { findPlan, mainRoot } = require("./git.js");
const { parseManifest } = require("./manifest.js");
const { readBatch, appendAnalysis } = require("./batch.js");
const G = require("./graphs.js");

const POLICIES = ["strict", "append", "writes_only"];
const PRED = "## Prediction against outcome";
const REL_KINDS = ["conflict", "order", "interface"];

function loadRelations(file) {
  if (!file) return { list: [], note: null };
  let raw;
  try { raw = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) {
    return { list: [], note: `relations: ignored (${e.code === "ENOENT" ? "file missing" : "bad JSON"})` };
  }
  if (!Array.isArray(raw)) return { list: [], note: "relations: ignored (not a list)" };
  return { list: raw, note: null };
}

const list = (a) => (a.length ? a.join(", ") : "-");

function build(batchId, plans, missing, relations, relNote) {
  const why = new Map();
  for (const r of relations) why.set(`${r.kind}|${[r.a, r.b].sort().join("|")}`, r.why);
  const suffix = (kind, x, y) => {
    const w = why.get(`${kind}|${[x, y].sort().join("|")}`);
    return w === undefined ? "" : ` (cross-plan: ${w})`;
  };
  const o = [`# Analysis ${batchId}`, ""];
  if (relNote) o.push(relNote, "");
  o.push("## Manifests", "", "| spec | base | writes | reads | depends_on |", "| --- | --- | --- | --- | --- |");
  for (const p of plans) {
    const m = p.manifest;
    o.push(`| ${p.spec} | ${m.base} | ${list((m.writes || []).map((w) => `${w.path} (${w.mode})`))} | ${list(m.reads || [])} | ${list((m.depends_on || []).map((d) => `${d.spec} (${d.kind})`))} |`);
  }
  o.push("", "## Dependency graph", "");
  const deps = G.dependencyEdges(plans, relations);
  if (!deps.length) o.push("none");
  for (const e of deps) o.push(`- ${e.from} -> ${e.to} [${e.kind}]${e.source === "crossplan" ? suffix(e.kind, e.from, e.to) : ""}`);
  o.push("", "## Conflict graph", "");
  for (const pol of POLICIES) {
    o.push(`### ${pol}`, "");
    const es = G.conflictEdges(plans, pol, relations);
    if (!es.length) o.push("none");
    for (const e of es) {
      const sfx = e.source === "crossplan" ? (suffix("conflict", e.a, e.b) || suffix("interface", e.a, e.b)) : "";
      o.push(`- ${e.a} — ${e.b}: ${list(e.paths)}${sfx}`);
    }
    o.push("");
  }
  o.push("## Clusters", "");
  const cl = G.clusters(plans);
  if (!cl.length) o.push("none");
  cl.forEach((c, i) => o.push(`- cluster ${i + 1}: ${c.join(", ")}`));
  o.push("", "## Waves", "");
  for (const pol of POLICIES) {
    o.push(`### ${pol}`, "");
    const w = G.waves(plans, pol, relations);
    const by = new Map();
    for (const [s, n] of Object.entries(w)) { if (!by.has(n)) by.set(n, []); by.get(n).push(s); }
    if (!by.size) o.push("none");
    for (const n of [...by.keys()].sort((x, y) => x - y)) o.push(`wave ${n}: ${by.get(n).sort().join(", ")}`);
    o.push("");
  }
  o.push("## Hot files", "");
  const hot = G.hotFiles(plans);
  if (!hot.length) o.push("none");
  for (const h of hot) o.push(`- ${h.path}: ${h.count}`);
  o.push("", "## Plans without a manifest", "");
  if (!missing.length) o.push("none");
  for (const m of missing) o.push(`- ${m.spec}: ${m.reason}`);
  return o.join("\n") + "\n";
}

function runAnalyse(repo, batchId, relationsPath, opts) {
  const extra = (opts && opts.extra) || [];
  const batch = readBatch(repo, batchId, extra);
  const plans = [];
  const missing = [];
  for (const spec of batch.specs || []) {
    const f = findPlan(repo, spec);
    if (!f) { missing.push({ spec, reason: "no plan found" }); continue; }
    const r = parseManifest(f.text);
    if (r.error) missing.push({ spec, reason: r.error });
    else plans.push({ spec, manifest: r.manifest });
  }
  const { list: rawRel, note } = loadRelations(relationsPath);
  const planned = new Set(plans.map((p) => p.spec));
  const relations = rawRel.filter((r) => r && r.a !== r.b && planned.has(r.a) && planned.has(r.b) && REL_KINDS.includes(r.kind));
  let doc = build(batchId, plans, missing, relations, note);
  const root = mainRoot(repo);
  const docPath = path.join(root, "docs/superpowers/metrics/analysis", `${batchId}.md`);
  let keep = "";
  try {
    const old = fs.readFileSync(docPath, "utf8");
    const i = old.indexOf(PRED);
    if (i >= 0) keep = "\n" + old.slice(i).replace(/\s+$/, "") + "\n";
  } catch (_) { /* first run */ }
  fs.mkdirSync(path.dirname(docPath), { recursive: true });
  fs.writeFileSync(docPath, doc + keep);
  const s = G.summary(plans, relations);
  const line = {
    kind: "analysis", batch: batchId, specs: plans.length, waves: s.waves,
    parallelism: s.parallelism, parallelism_strict: s.parallelism_strict,
    parallelism_writes_only: s.parallelism_writes_only,
    appends_verified: false, clusters: s.clusters, relations: relations.length,
  };
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
  if (!batchId) throw new Error("usage: registry analyse <batch> [--relations <file>]");
  const { docPath } = runAnalyse(ctx.cwd, batchId, rel);
  ctx.out(`analysis: ${path.relative(mainRoot(ctx.cwd), docPath)}`);
  return 0;
}

module.exports = { runAnalyse, main };
