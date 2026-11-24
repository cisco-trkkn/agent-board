"use strict";
// The queue's morning report (spec sections 7 and 11): render, write, the name of the file, the path-scoped commit, and
// the outside calls (stub tmux-ctl). A scratch git repo is the live checkout; nothing here calls the real tmux-ctl.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const queue = require("../lib/engine/queue");
const qr = require("../lib/engine/queue_report");

const spec = (name) => `docs/superpowers/specs/2026-01-01-${name}-design.md`;
const plan = (name) => `docs/superpowers/plans/2026-01-01-${name}.md`;
const [S1, S2] = ["one", "two"].map(spec);
const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const PASS = report({ verdict: "pass", findings: [] });
const worker = (text, k = 1) => [{ status: "busy", at: k }, { report: text, at: 3 * k }, { status: "ready", at: 5 * k }, { tokens: 10 }];
const GOOD = { implement1: worker(DONE), review1: worker(PASS), final_review: worker(PASS) };
const task = (meta = {}) => ({
  subject: "T1",
  description: `Do T1.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"], ...meta })}\n\`\`\``,
});
const T_START = Date.UTC(2026, 0, 1, 23, 50, 0) / 1000; // the queue starts 23:50 UTC and ends at 00:20 the next day
const ANALYSIS = "docs/superpowers/metrics/analysis/2026-01-01-1.md";

// A stub tmux-ctl that logs its argv and prints fixed outputs; `fail_<name>` files in its root make a call exit 1.
const ctlStub = (root) => `#!/bin/sh
echo "$@" >> "${root}/ctl.log"
case "$1 $2" in
  "metrics report") [ -f "${root}/fail_metrics" ] && { echo "metrics: no such batch $3" >&2; echo "second line" >&2; exit 1; }; echo "REPORT for batch $3"; echo "specs: 2"; exit 0 ;;
  "registry report") [ -f "${root}/fail_registry" ] && { echo "registry: broke" >&2; exit 1; }; echo "${ANALYSIS}"; exit 0 ;;
  "metrics status") echo "PCEE: 3 of 8 specs, gate K1 open"; echo "other"; exit 0 ;;
  "awake sleeps") echo "sleep 2026-01-02T00:05:00Z 600s"; exit 0 ;;
esac
exit 0
`;
const git = (dir, ...a) => require("node:child_process").execFileSync("git", ["-C", dir, ...a], { encoding: "utf8" });

function mk(t, o = {}) {
  const env = tmpEnv();
  const repo = gitRepo();
  const wt = repo.dir;
  const w = (rel, text) => { fs.mkdirSync(path.dirname(path.join(wt, rel)), { recursive: true }); fs.writeFileSync(path.join(wt, rel), text); };
  const names = o.names || ["one", "two"];
  for (const n of names) {
    w(`${plan(n)}.tasks.json`, JSON.stringify({ tasks: [n === "two" && !o.ungated ? task({ userGate: true }) : task()] }));
    w(spec(n), "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  }
  w(".gitignore", ".superpowers/\n");
  for (const f of ["runs.jsonl", "tasks.jsonl"]) w(`docs/superpowers/metrics/${f}`, "{}\n");
  w(ANALYSIS, "analysis\n");
  if (o.stale) w(`docs/superpowers/reports/2026-01-01-queue.md`, "# an old report with no marker\n");
  git(wt, "add", "-A"); git(wt, "commit", "-q", "-m", "fixtures");
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, ctlStub(env.root), { mode: 0o755 });
  const clock = { t: T_START };
  const backend = fake.createBackend({ script: GOOD, now: () => clock.t });
  const eng = core.start({
    project: "demo", repo: wt, backend, now: () => clock.t, tmuxCtl: ctl, ...queue.reportHooks,
    integrate: async (s) => ({ outcome: "merged", merge: "abc1234def" }), revert: async () => {}, finalize: async () => {},
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const h = {
    env, repo, wt, clock, eng, ctl,
    enqueued: 0,
    enqueue: (name, payload = {}) => (h.enqueued++, queue.enqueue(eng.db, spec(name), { runner: "engine", integration: "keep", push: 0, batch: "b1", worktree: wt, branch: `spec-${name}`, plan: plan(name), ...payload }, clock.t)),
    async until(pred, what, max = 600) {
      for (let i = 0; i < max; i++) { if (pred()) return; clock.t += 5; await queue.step(eng, "demo"); }
      assert.fail(`not reached: ${what}`);
    },
    events: () => eng.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) })),
    of: (kind) => h.events().filter((e) => e.kind === kind),
    ctxOf: () => ({ db: eng.db, repo: wt, project: "demo", tmuxCtl: ctl, env: {}, now: () => clock.t }),
    ctlLog: () => (fs.existsSync(path.join(env.root, "ctl.log")) ? fs.readFileSync(path.join(env.root, "ctl.log"), "utf8").split("\n").filter(Boolean) : []),
    commits: () => git(wt, "log", "--format=%s", "main").split("\n").filter((s) => s.startsWith("docs(report)")),
    // the queue's work, then the jump to 00:20 the next day and the queue's end
    async finishQueue(jump = true) {
      await h.until(() => {
        const n = (sql) => eng.db.prepare(sql).get().n;
        return n("SELECT COUNT(*) AS n FROM specs") === h.enqueued && n("SELECT COUNT(*) AS n FROM specs WHERE state IN ('done','awaiting_you')") === h.enqueued;
      }, "every spec at rest");
      if (jump) clock.t = Date.UTC(2026, 0, 2, 0, 20, 0) / 1000;
      assert.equal(await queue.run(eng, { project: "demo" }), 0);
    },
  };
  t.after(() => { eng.stop(); env.restore(); repo.cleanup(); });
  return h;
}
const H2 = (md) => md.split("\n").filter((l) => l.startsWith("## "));

test("render: the headings, in order, the first three lines, the marker; two specs in queue order; the date of the first spec_added", async (t) => {
  const h = mk(t);
  h.enqueue("one"); h.enqueue("two");
  await h.finishQueue();
  const rel = h.of("queue_finished")[0].detail.report;
  assert.equal(rel, "docs/superpowers/reports/2026-01-01-queue.md", "named for the start date, though it ended on 2026-01-02");
  const md = fs.readFileSync(path.join(h.wt, rel), "utf8");
  assert.deepEqual(H2(md), ["## Specs", "## Awaiting you", "## Metrics", "## Sleep"]);
  assert.deepEqual(md.split("\n").slice(0, 3), ["# Queue report 2026-01-01", "", "Written by the engine (demo)."]);
  assert.equal(md.trimEnd().split("\n").pop(), `<!-- engine-queue: demo ${h.of("spec_added")[0].seq} -->`);
  assert.deepEqual(md.split("\n").filter((l) => l.startsWith("### ")).slice(0, 2), [`### ${S1}`, `### ${S2}`]);
  const one = md.slice(md.indexOf(`### ${S1}`), md.indexOf(`### ${S2}`));
  for (const want of ["- Outcome: merged", "- Runner: engine", "- Branch: spec-one", "- Merge commit: abc1234def", "- Spend: attempts 3/60 · tokens 30/5000000", "- Rulings: none",
    "- Permission prompts seen: none", "- User gates waiting: none"]) assert.ok(one.includes(want), `${want} in:\n${one}`);
  const two = md.slice(md.indexOf(`### ${S2}`), md.indexOf("## Awaiting you"));
  assert.ok(two.includes("- User gates waiting:\n  - user gate: task 1 T1"), two);
  const aw = md.slice(md.indexOf("## Awaiting you"), md.indexOf("## Metrics"));
  assert.ok(aw.includes("I recommend: approve (low): the plan marks this task as yours to check"), aw);
  assert.ok(aw.includes(`tmux-ctl engine signal ${S2} approve|deny|fail`), aw);
  const mt = md.slice(md.indexOf("## Metrics"), md.indexOf("## Sleep"));
  assert.ok(mt.includes("REPORT for batch b1") && mt.includes(`Analysis: ${ANALYSIS}`) && mt.includes("PCEE: 3 of 8 specs, gate K1 open"), mt);
  assert.ok(md.slice(md.indexOf("## Sleep")).includes("sleep 2026-01-02T00:05:00Z 600s"));
});

test("render: a lead-run spec has the one rulings line and no Spend line; pure on a database with no outputs", (t) => {
  const env = tmpEnv(); t.after(() => env.restore());
  const d = dbm.open("demo");
  dbm.put(d, "specs", { id: "docs/l.md", position: 0, runner: "lead", state: "running", integration: "keep", push: 0, batch: null, created_at: 1, updated_at: 1 });
  dbm.event(d, { spec: "docs/l.md", kind: "spec_added", ts: 1, rows: [] });
  const md = qr.render({ db: d, project: "demo", outputs: {}, now: () => 1 });
  assert.ok(md.includes("- Rulings:\n  - (lead-run: the lead appends its rulings)"));
  assert.ok(!md.includes("- Spend:"));
  assert.deepEqual(H2(md), ["## Specs", "## Awaiting you", "## Metrics", "## Sleep"]);
  assert.equal(md, qr.render({ db: d, project: "demo", outputs: {}, now: () => 1 }), "render is deterministic");
});

// Mutation: "commit without the live-checkout check" -> the dirty-checkout test finds a commit.
test("a committed report: one commit with the trailer, only the listed paths; then artifact and awake off, once each, in that order", async (t) => {
  const h = mk(t);
  h.enqueue("one"); h.enqueue("two");
  fs.appendFileSync(path.join(h.wt, "docs/superpowers/metrics/runs.jsonl"), '{"run":1}\n'); // a metrics line the run wrote: dirty, but allowed
  await h.finishQueue();
  const rel = h.of("queue_finished")[0].detail.report;
  assert.equal(h.commits().length, 1);
  const msg = git(h.wt, "log", "-1", "--format=%B");
  assert.ok(msg.startsWith("docs(report): queue 2026-01-01"), msg);
  assert.ok(msg.split("\n").includes(`Engine-Step: commit_report:${rel}`), msg);
  const files = git(h.wt, "show", "--name-only", "--format=", "HEAD").split("\n").filter(Boolean).sort();
  assert.deepEqual(files, [rel, "docs/superpowers/metrics/runs.jsonl"].sort(), "only paths that changed, all from the list");
  assert.equal(git(h.wt, "status", "--porcelain").trim(), "");
  const log = h.ctlLog();
  const art = log.filter((l) => l.startsWith("artifact "));
  assert.deepEqual(art, [`artifact ${path.join(h.wt, rel)}`]);
  assert.equal(log.filter((l) => l === "awake off").length, 1);
  assert.ok(log.indexOf(art[0]) < log.indexOf("awake off"), "artifact before awake off");
  assert.ok(log.includes(`awake sleeps ${new Date(h.of("spec_added")[0].ts * 1000).toISOString()}`));
  assert.equal(h.of("report_uncommitted").length, 0);
});

test("a dirty live checkout: the report is written and shown, not committed, one report_uncommitted event", async (t) => {
  const h = mk(t);
  h.enqueue("one"); h.enqueue("two");
  await h.until(() => h.of("spec_done").length === 1, "the first spec done");
  fs.writeFileSync(path.join(h.wt, "wip.txt"), "someone's work\n");
  await h.finishQueue();
  const rel = h.of("queue_finished")[0].detail.report;
  assert.ok(fs.existsSync(path.join(h.wt, rel)));
  assert.equal(h.commits().length, 0, "no commit");
  const ev = h.of("report_uncommitted");
  assert.equal(ev.length, 1);
  assert.match(ev[0].detail.reason, /dirty/);
  assert.equal(ev[0].detail.path, rel);
  assert.equal(h.ctlLog().filter((l) => l.startsWith("artifact ")).length, 1, "still shown");
  assert.equal(h.ctlLog().filter((l) => l === "awake off").length, 1);
});

test("main is not the checked-out branch: not committed, report_uncommitted", async (t) => {
  const h = mk(t);
  h.enqueue("one"); h.enqueue("two");
  await h.until(() => h.of("spec_done").length === 1, "the first spec done");
  git(h.wt, "checkout", "-q", "-b", "other");
  await h.finishQueue();
  assert.equal(h.commits().length, 0);
  assert.match(h.of("report_uncommitted")[0].detail.reason, /main/);
});

test("a failing metrics report or registry report: (not available: <first line>) and the report is still written and committed", async (t) => {
  const h = mk(t);
  fs.writeFileSync(path.join(h.env.root, "fail_metrics"), "");
  fs.writeFileSync(path.join(h.env.root, "fail_registry"), "");
  h.enqueue("one"); h.enqueue("two");
  await h.finishQueue();
  const rel = h.of("queue_finished")[0].detail.report;
  const md = fs.readFileSync(path.join(h.wt, rel), "utf8");
  assert.ok(md.includes("(not available: metrics: no such batch b1)"), md);
  assert.ok(!md.includes("second line"), "only the first error line");
  assert.ok(md.includes("Analysis: (not available: registry: broke)"), md);
  assert.equal(h.commits().length, 1);
  const rows = h.eng.db.prepare("SELECT kind, state FROM steps WHERE key LIKE 'metrics_report:%' OR key LIKE 'registry_report:%'").all();
  assert.deepEqual(rows.map((r) => [r.kind, r.state]), [["registry_report", "failed"], ["registry_report", "failed"]]);
  assert.equal(h.of("queue_finished").length, 1);
});

test("a re-run of the hook after a kill between the commit's intent and its done: still one commit, one file", async (t) => {
  const h = mk(t, { ungated: true });
  h.enqueue("one"); h.enqueue("two");
  await h.until(() => h.of("spec_done").length === 2, "both specs done");
  const ctx = h.ctxOf();
  const rel = qr.write(ctx);
  const before = fs.readFileSync(path.join(h.wt, rel), "utf8");
  h.eng.db.prepare("UPDATE steps SET state='intent' WHERE kind='commit_report'").run(); // the kill: committed, done not written
  assert.equal(qr.write(ctx), rel);
  assert.equal(h.commits().length, 1, "one commit");
  assert.equal(fs.readFileSync(path.join(h.wt, rel), "utf8"), before);
  assert.equal(h.eng.db.prepare("SELECT state FROM steps WHERE kind='commit_report'").get().state, "done");
  assert.equal(h.ctlLog().filter((l) => l.startsWith("artifact ")).length, 1, "the notices are steps too: shown once");
  assert.equal(h.ctlLog().filter((l) => l === "awake off").length, 1);
});

// R1: the second queue of the same day is -queue-2, a third -queue-3; each queue end has its own queue_report step.
test("the name: an earlier queue the same day gives -queue-2, a third -queue-3; each queue has its own queue_report step and report", async (t) => {
  const h = mk(t, { names: ["one", "two", "three"], ungated: true });
  h.enqueue("one");
  await h.finishQueue(false);
  h.enqueue("two");
  await h.finishQueue(false);
  h.enqueue("three", { branch: "spec-three" });
  await h.finishQueue(false);
  const reports = h.of("queue_finished").map((e) => e.detail.report);
  assert.deepEqual(reports, ["docs/superpowers/reports/2026-01-01-queue.md", "docs/superpowers/reports/2026-01-01-queue-2.md", "docs/superpowers/reports/2026-01-01-queue-3.md"]);
  const keys = h.eng.db.prepare("SELECT key FROM steps WHERE kind='queue_report' ORDER BY created_at").all().map((r) => r.key);
  assert.equal(new Set(keys).size, 3, `three queue_report steps: ${keys}`);
  for (const [i, rel] of reports.entries()) {
    const md = fs.readFileSync(path.join(h.wt, rel), "utf8");
    assert.ok(md.includes(`### ${[S1, S2, spec("three")][i]}`), rel);
  }
  assert.equal(h.commits().length, 3);
});

test("a stale file of the same name with no marker is skipped to the next suffix, and left alone", async (t) => {
  const h = mk(t, { stale: true, ungated: true });
  h.enqueue("one"); h.enqueue("two");
  await h.finishQueue();
  assert.equal(h.of("queue_finished")[0].detail.report, "docs/superpowers/reports/2026-01-01-queue-2.md");
  assert.equal(fs.readFileSync(path.join(h.wt, "docs/superpowers/reports/2026-01-01-queue.md"), "utf8"), "# an old report with no marker\n");
});

test("a rerun after a kill picks the same file: reportPath and write agree before and after the file exists", async (t) => {
  const h = mk(t, { ungated: true });
  h.enqueue("one"); h.enqueue("two");
  await h.until(() => h.of("spec_done").length === 2, "both specs done");
  const ctx = h.ctxOf();
  const first = qr.reportPath(ctx);
  assert.equal(qr.write(ctx), first);
  assert.equal(qr.reportPath(ctx), first, "the file now exists with this queue's marker: the same name");
  assert.equal(qr.write(ctx), first);
  assert.equal(h.commits().length, 1);
});
