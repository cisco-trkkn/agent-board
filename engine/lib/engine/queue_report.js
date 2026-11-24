"use strict";
// The queue's morning report (spec sections 7 and 11): `render` is the text, a pure function of the database and the
// outputs of the outside reads; `write` is the engine's report hook (core.start({report, reportPath})). Every outside
// call is a `steps.run` row of a never-park kind, so a failing read or notice leaves a note, never a parked queue. The
// hook is idempotent: run twice it gives one file and one commit.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const steps = require("./steps");
const db_ = require("./db");
const integrate = require("./integrate");

const REPORT_DIR = "docs/superpowers/reports";
const METRICS_FILES = ["docs/superpowers/metrics/runs.jsonl", "docs/superpowers/metrics/tasks.jsonl"];
const parse = (s) => { try { return JSON.parse(s) || {}; } catch (_) { return {}; } };
const isoOf = (ts) => new Date(ts * 1000).toISOString();
const firstLine = (s) => String(s || "").split("\n").map((l) => l.trim()).find(Boolean) || "";

// The queue being reported: the specs added since the last queue_finished, with the seq and time of the first.
function queueOf(db) {
  const fin = db.prepare("SELECT MAX(seq) AS s FROM events WHERE kind='queue_finished'").get().s || 0;
  const adds = db.prepare("SELECT seq, ts, spec FROM events WHERE kind='spec_added' AND seq>? ORDER BY seq").all(fin);
  const ids = adds.map((a) => a.spec);
  const specs = ids.length
    ? db.prepare(`SELECT * FROM specs WHERE id IN (${ids.map(() => "?").join(",")}) ORDER BY position, created_at`).all(...ids) : [];
  return { fin, first: adds[0] || null, specs };
}
const dateOf = (q, now) => isoOf(q.first ? q.first.ts : (typeof now === "function" ? now() : Date.now() / 1000)).slice(0, 10);
const marker = (project, q) => `<!-- engine-queue: ${project} ${q.first ? q.first.seq : 0} -->`;
const lastLine = (file) => { try { return fs.readFileSync(file, "utf8").split("\n").filter((l) => l !== "").pop() || ""; } catch (_) { return null; } };

// <date>-queue.md, then -queue-2, -queue-3, ...: the first name that is free, or holds THIS queue's marker as its last line.
// Shared by reportPath and write, so both pick the same file.
function reportName(ctx, q) {
  const date = dateOf(q, ctx.now);
  const want = marker(ctx.project, q);
  for (let n = 1; ; n++) {
    const rel = path.join(REPORT_DIR, n === 1 ? `${date}-queue.md` : `${date}-queue-${n}.md`);
    const last = lastLine(path.resolve(ctx.repo, rel));
    if (last === null || last === want) return rel;
  }
}
const reportPath = (ctx) => reportName(ctx, queueOf(ctx.db));

// ---- render ----------------------------------------------------------------------------------------------------

function render({ db, project, outputs = {}, now }) {
  const q = queueOf(db);
  const o = { batches: {}, ...outputs };
  const out = [`# Queue report ${dateOf(q, now)}`, "", `Written by the engine (${project}).`, "", "## Specs", ""];
  const evs = (spec, kind) => db.prepare("SELECT * FROM events WHERE spec=? AND kind=? ORDER BY seq").all(spec, kind).map((e) => ({ ...e, d: parse(e.detail) }));
  for (const s of q.specs) {
    out.push(`### ${s.id}`, "", `- Outcome: ${s.outcome || s.state}`, `- Runner: ${s.runner}`, `- Branch: ${s.branch || "-"}`);
    const merged = evs(s.id, "integrated").filter((e) => e.d.merge).pop();
    if (merged) out.push(`- Merge commit: ${merged.d.merge}`);
    const mr = /^mr (\S+)/.exec(String(s.outcome || ""));
    if (mr) out.push(`- MR: ${mr[1]}`);
    if (s.runner !== "lead") {
      const lower = db.prepare("SELECT 1 FROM jobs WHERE spec=? AND ended_at IS NOT NULL AND started_at IS NOT NULL AND tokens IS NULL LIMIT 1").get(s.id);
      out.push(`- Spend: attempts ${s.spent_attempts || 0}/${s.budget_attempts == null ? "-" : s.budget_attempts} · tokens ${s.spent_tokens || 0}/${s.budget_tokens == null ? "-" : s.budget_tokens}${lower ? " (lower bound)" : ""}`);
    }
    if (s.runner === "lead") out.push("- Rulings:", "  - (lead-run: the lead appends its rulings)");
    else {
      const r = evs(s.id, "ruling");
      if (!r.length) out.push("- Rulings: none");
      else { out.push("- Rulings:"); for (const e of r) out.push(`  - ${e.d.text} — cost if wrong: ${e.d.cost_if_wrong}`); }
    }
    const win = [...new Set(evs(s.id, "needs_you").map((e) => (/permission prompt in (.+)$/.exec(e.d.text || "") || [])[1] || e.job).filter(Boolean))];
    out.push(win.length ? `- Permission prompts seen: ${win.join(", ")}` : "- Permission prompts seen: none");
    const gates = db.prepare("SELECT question FROM waits WHERE spec=? AND kind='user_gate' AND answered_at IS NULL ORDER BY asked_at").all(s.id);
    if (!gates.length) out.push("- User gates waiting: none");
    else { out.push("- User gates waiting:"); for (const g of gates) out.push(`  - ${g.question}`); }
    out.push("");
  }
  out.push("## Awaiting you", "");
  const waits = q.specs.map((s) => db.prepare("SELECT * FROM waits WHERE spec=? AND answered_at IS NULL ORDER BY asked_at DESC LIMIT 1").get(s.id)).filter(Boolean);
  if (!waits.length) out.push("none", "");
  for (const w of waits) {
    const rec = parse(w.recommendation);
    out.push(`### ${w.spec}`, "");
    if (rec.option) out.push(`- I recommend: ${rec.option} (${rec.confidence}): ${rec.why}`);
    out.push(`- Question: ${w.question}`, `- Answer with: tmux-ctl engine signal ${w.spec} ${w.options}`, "");
  }
  out.push("## Metrics", "");
  const batches = Object.keys(o.batches);
  if (!batches.length) out.push("(no batch)");
  for (const b of batches) {
    const x = o.batches[b];
    out.push(`### Batch ${b}`, "", x.reportErr ? `(not available: ${x.reportErr})` : String(x.report || "").trimEnd() || "(empty)", "");
    if (x.analysisErr) out.push(`Analysis: (not available: ${x.analysisErr})`);
    else for (const p of x.analysis || []) out.push(`Analysis: ${p}`);
    out.push("");
  }
  out.push(o.statusErr ? `(not available: ${o.statusErr})` : (String(o.status || "").split("\n").find((l) => l.startsWith("PCEE:")) || firstLine(o.status) || "(no status)"), "");
  out.push("## Sleep", "");
  if (o.sleepsErr) out.push(`(not available: ${o.sleepsErr})`);
  else if (!(o.sleeps || []).length) out.push("none");
  else for (const l of o.sleeps) out.push(l);
  out.push("", marker(project, q), "");
  return out.join("\n");
}

// ---- write -----------------------------------------------------------------------------------------------------

const envOf = (ctx) => ({ ...process.env, ...(ctx.env || {}) });
const spawn = (ctx, cmd, args, opts = {}) => cp.spawnSync(cmd, args, { encoding: "utf8", timeout: 120000, cwd: ctx.repo, env: envOf(ctx), ...opts });
const git = (ctx, args) => spawn(ctx, "git", ["-C", ctx.repo, ...args]);
const ctlOf = (ctx) => ctx.tmuxCtl || process.env.TC_TMUX_CTL || path.join(ctx.repo, "bin/tmux-ctl");

// One outside call as a step of a never-park kind. Returns {out} or {err} (the first error line); never throws.
function call(ctx, q, kind, key, argv) {
  try {
    const r = steps.run(ctx.db, { key, spec: null, kind, facts: { argv } }, () => {
      const p = spawn(ctx, ctlOf(ctx), argv);
      if (p.error || p.status !== 0) throw new Error(firstLine(p.stderr) || firstLine(p.stdout) || (p.error && p.error.message) || `exit ${p.status}`);
      return { out: p.stdout || "" };
    }, { now: ctx.now });
    return { out: r.result.out };
  } catch (e) { return { err: firstLine(e && e.message) || "failed" }; }
}

// The live checkout's state, ignoring the report file itself (a rerun after a kill finds it written and uncommitted).
function busy(ctx, file) {
  const why = integrate.liveCheckoutBusy({ db: ctx.db, repo: ctx.repo, env: ctx.env });
  if (why !== "dirty") return why;
  const st = git(ctx, ["status", "--porcelain"]);
  const rest = (st.stdout || "").split("\n").filter(Boolean).map((l) => l.slice(3).replace(/^"|"$/g, ""))
    .filter((p) => !(p.startsWith(".claude/") || p.startsWith("docs/superpowers/metrics/") || p === file));
  return rest.length ? "dirty" : null;
}

function write(ctx) {
  const q = queueOf(ctx.db);
  const seq = q.first ? q.first.seq : 0;
  const o = { batches: {} };
  const batches = [...new Set(q.specs.map((s) => s.batch).filter((b) => b !== null && b !== undefined && b !== ""))];
  const analysis = [];
  for (const b of batches) {
    const rep = call(ctx, q, "registry_report", `metrics_report:${seq}:${b}`, ["metrics", "report", String(b)]);
    const reg = call(ctx, q, "registry_report", `registry_report:${seq}:${b}`, ["registry", "report", String(b)]);
    const paths = (reg.out || "").split("\n").map((l) => l.trim()).filter(Boolean);
    analysis.push(...paths);
    o.batches[b] = { report: rep.out, reportErr: rep.err, analysis: paths, analysisErr: reg.err };
  }
  const st = call(ctx, q, "registry_report", `metrics_status:${seq}`, ["metrics", "status"]);
  o.status = st.out; o.statusErr = st.err;
  const sl = call(ctx, q, "registry_report", `awake_sleeps:${seq}`, ["awake", "sleeps", q.first ? isoOf(q.first.ts) : isoOf(typeof ctx.now === "function" ? ctx.now() : Date.now() / 1000)]);
  o.sleeps = (sl.out || "").split("\n").map((l) => l.trimEnd()).filter(Boolean); o.sleepsErr = sl.err;

  const rel = reportName(ctx, q);
  const abs = path.resolve(ctx.repo, rel);
  const why = busy(ctx, rel) || (git(ctx, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout || "").trim() !== "main" && "main is not checked out";
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, render({ db: ctx.db, project: ctx.project, outputs: o, now: ctx.now }));

  if (why) {
    const reason = why === true || typeof why !== "string" ? "cannot commit" : (why === "dirty" || why === "busy" ? `the live checkout is ${why}` : why);
    db_.event(ctx.db, { kind: "report_uncommitted", ts: typeof ctx.now === "function" ? ctx.now() : Date.now() / 1000, reason, path: rel });
  } else {
    const key = `commit_report:${rel}`;
    try {
      steps.run(ctx.db, { key, spec: null, kind: "commit_report", facts: { path: rel } }, () => {
        if (steps.CHECKS.commit_report({ ...ctx, mainRepo: ctx.repo }, { key }) === "done") return { path: rel, reused: true }; // killed after the commit, before its done
        const files = [rel, ...METRICS_FILES, ...analysis].filter((p, i, a) => a.indexOf(p) === i)
          .map((p) => path.relative(ctx.repo, path.resolve(ctx.repo, p))).filter((p) => !p.startsWith("..") && fs.existsSync(path.resolve(ctx.repo, p)));
        const add = git(ctx, ["add", "--", ...files]);
        if (add.status !== 0) throw new Error(`git add: ${firstLine(add.stderr)}`);
        const c = git(ctx, ["commit", "-q", "-m", `docs(report): queue ${dateOf(q, ctx.now)}\n\nEngine-Step: ${key}`, "--", ...files]);
        if (c.status !== 0) throw new Error(`git commit: ${firstLine(c.stderr) || firstLine(c.stdout)}`);
        return { path: rel };
      }, { now: ctx.now });
    } catch (e) {
      db_.event(ctx.db, { kind: "report_uncommitted", ts: typeof ctx.now === "function" ? ctx.now() : Date.now() / 1000, reason: `commit failed: ${firstLine(e && e.message)}`, path: rel });
    }
  }
  call(ctx, q, "artifact", `artifact:${seq}:${rel}`, ["artifact", abs]);
  call(ctx, q, "awake_off", `awake_off:${seq}`, ["awake", "off"]);
  return rel;
}

module.exports = { render, write, reportPath, reportName, queueOf };
