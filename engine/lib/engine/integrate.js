"use strict";
// Engine-core step 7 (spec §3) and the revert of §4. Every outside action is a `steps.run` row.
// ctx = {db, repo (main checkout), worktree, tmuxCtl, tasks?, now?, env?, target?}.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const steps = require("./steps");
const ledger = require("./ledger");
const improve = require("../improve");
const { loadConfig, SITE_RECS } = require("./policy");

const TEST_TIMEOUT = 30 * 60 * 1000;
const PROTECTED = new Set(["main", "master"]);
// A terminal outcome that is not a success: `failed — …` and `denied: <question>` (the only strings the engine emits).
const isFailure = (outcome) => /^(failed|denied)/.test(String(outcome));
const target = (ctx) => ctx.target || "main";
const envOf = (ctx) => ({ ...process.env, ...(ctx.env || {}) });
const tmuxCtl = (ctx) => ctx.tmuxCtl || process.env.TC_TMUX_CTL || path.join(ctx.repo, "bin/tmux-ctl");
const spawn = (ctx, cmd, args, opts = {}) => cp.spawnSync(cmd, args, { encoding: "utf8", timeout: 60000, env: envOf(ctx), ...opts });
const git = (ctx, dir, args) => spawn(ctx, "git", ["-C", dir, ...args]);
const must = (r, what) => {
  if (r.error || r.status !== 0) throw new Error(`${what} failed: ${(r.error && r.error.message) || (r.stderr || r.stdout || "").trim()}`);
  return (r.stdout || "").trim();
};
const parked = (question, recommendation) => (recommendation ? { outcome: "parked", question, recommendation } : { outcome: "parked", question });
const stepOpts = (ctx) => ({ now: ctx.now });
const run = (ctx, spec, kind, key, facts, act) =>
  steps.run(ctx.db, { key, spec: spec.id, kind, facts }, act, stepOpts(ctx));

// ---- tests ------------------------------------------------------------------------------------------------

// The project test command, else every task's verifyCommand in order. Runs as `zsh -c` in `cwd`.
function runTests(ctx, cwd) {
  const cfg = loadConfig(ctx.repo);
  const cmds = cfg.test ? [cfg.test] : (ctx.tasks || []).map((t) => t.verifyCommand).filter(Boolean);
  for (const c of cmds) {
    const r = cp.spawnSync("zsh", ["-c", c], { cwd, encoding: "utf8", timeout: TEST_TIMEOUT, env: envOf(ctx) });
    if (r.error || !cfg.test_ok.includes(r.status)) return { ok: false, command: c, rc: r.status };
  }
  return { ok: true };
}

// ---- live checkout (Queue mode's check) -----------------------------------------------------------------------

function liveCheckoutBusy(ctx) {
  const st = git(ctx, ctx.repo, ["status", "--porcelain"]);
  if (st.error || st.status !== 0) return "cannot read live checkout status";
  const dirty = st.stdout.split("\n").filter(Boolean).filter((l) => {
    const p = l.slice(3).replace(/^"|"$/g, "");
    return !(p.startsWith(".claude/") || p.startsWith("docs/superpowers/metrics/"));
  });
  if (dirty.length) return "dirty";
  const real = fs.realpathSync(ctx.repo);
  const pg = spawn(ctx, "pgrep", ["-x", "git"]);
  const pids = (pg.stdout || "").split("\n").filter(Boolean).filter((p) => Number(p) !== process.pid);
  if (pids.length) {
    const ls = spawn(ctx, "lsof", ["-a", "-d", "cwd", "-Fpn", "-p", pids.join(",")]);
    for (const l of (ls.stdout || "").split("\n")) if (l.startsWith("n") && l.slice(1) === real) return "busy";
  }
  return null;
}

// ---- steps --------------------------------------------------------------------------------------------------

function mergeKey(ctx, spec) {
  const have = ctx.db.prepare("SELECT key FROM steps WHERE spec=? AND kind='merge' AND key LIKE ? ORDER BY created_at LIMIT 1")
    .get(spec.id, `merge:${spec.branch}@%`);
  if (have) return have.key;
  const base = spec.base || must(git(ctx, ctx.repo, ["merge-base", spec.branch, target(ctx)]), "merge-base");
  return `merge:${spec.branch}@${base}`;
}

function doMerge(ctx, spec) {
  const key = mergeKey(ctx, spec);
  const done = steps.getRow(ctx.db, key);
  if (!(done && done.state === "done")) {
    const busy = liveCheckoutBusy(ctx);
    if (busy) return parked("live checkout is mid-change", SITE_RECS.live_checkout);
    const cur = must(git(ctx, ctx.repo, ["rev-parse", "--abbrev-ref", "HEAD"]), "rev-parse");
    if (cur !== target(ctx)) return parked(`live checkout is on ${cur}, not ${target(ctx)}`, SITE_RECS.live_checkout);
  }
  try {
    const r = run(ctx, spec, "merge", key, { branch: spec.branch, target: target(ctx) }, () => {
      const m = git(ctx, ctx.repo, ["merge", "--no-ff", "-m", `Merge branch '${spec.branch}'\n\nEngine-Step: ${key}`, spec.branch]);
      if (m.status !== 0) {
        git(ctx, ctx.repo, ["merge", "--abort"]);
        throw new Error(`merge conflict: ${(m.stdout || m.stderr || "").trim().split("\n")[0]}`);
      }
      return { branch: spec.branch, target: target(ctx), merge: must(git(ctx, ctx.repo, ["rev-parse", "HEAD"]), "rev-parse") };
    });
    return { merge: r.result.merge };
  } catch (e) {
    return parked(`merge failed: ${e.message}`);
  }
}

function mrGuard(spec) {
  if (!spec.push) return parked("push not permitted: no stored consent");
  if (PROTECTED.has(spec.branch)) return parked(`push not permitted: ${spec.branch} is a protected branch`);
  return null;
}

function doMr(ctx, spec) {
  const g = mrGuard(spec);
  if (g) return g;
  commitLedger(ctx, spec); // before the push, so the PR carries it
  const sha = must(git(ctx, ctx.repo, ["rev-parse", spec.branch]), "rev-parse");
  const url = must(git(ctx, ctx.repo, ["config", "--get", "remote.origin.url"]), "remote url");
  run(ctx, spec, "push", `push:${spec.id}:${spec.branch}`, { remote: "origin", ref: `refs/heads/${spec.branch}`, sha }, () => {
    must(git(ctx, ctx.repo, ["push", "origin", `${spec.branch}:refs/heads/${spec.branch}`]), "push");
    return { remote: "origin", ref: `refs/heads/${spec.branch}`, sha };
  });
  const github = /github\.com/.test(url);
  const argv = github
    ? ["gh", ["pr", "create", "--base", target(ctx), "--head", spec.branch, "--fill"]]
    : ["glab", ["mr", "create", "--target-branch", target(ctx), "--source-branch", spec.branch, "--fill", "--yes"]];
  const r = run(ctx, spec, "mr_create", `mr_create:${spec.id}`, { branch: spec.branch }, () => {
    const out = must(spawn(ctx, argv[0], argv[1], { cwd: ctx.repo }), argv[0]);
    const m = out.match(/https?:\/\/\S+/g);
    return { url: m ? m[m.length - 1] : out.split("\n").pop() };
  });
  return { url: r.result.url };
}

// The ledger commit: `merge` -> the target branch in the main checkout (after the merge); `mr` and `keep` -> the
// spec branch in the spec worktree, so the main checkout never moves (for `mr` it runs before the push).
function commitLedger(ctx, spec, outcome = "") {
  const rel = path.join("docs/superpowers/ledgers", path.basename(spec.plan || spec.id).replace(/\.md$/, ""));
  const file = path.join(rel, "progress.md");
  // A failed or denied spec never merged: its ledger goes on the spec branch whatever the stored answer.
  const onSpecBranch = spec.integration === "mr" || spec.integration === "keep" || isFailure(outcome);
  const dir = onSpecBranch ? (spec.worktree || ctx.worktree) : ctx.repo;
  const branch = onSpecBranch ? spec.branch : target(ctx);
  run(ctx, spec, "commit_ledger", `commit_ledger:${spec.id}`, { branch, dir }, () => {
    const events = ctx.db.prepare("SELECT kind, detail FROM events WHERE spec=? ORDER BY seq").all(spec.id);
    fs.mkdirSync(path.join(dir, rel), { recursive: true });
    fs.writeFileSync(path.join(dir, file), ledger.render(events));
    must(git(ctx, dir, ["add", "--", file]), "git add");
    must(git(ctx, dir, ["commit", "-q", "-m", `docs(ledger): ${spec.id} progress\n\nEngine-Step: commit_ledger:${spec.id}`, "--", file]), "git commit");
    return { file, branch, dir };
  });
}

// The argv (after tmux-ctl) of `metrics record` for a spec's end: the outcome, its budget spend and the session id -> job
// kind of its engine jobs, so the metrics side can tell engine jobs from the lead's (Global Constraints). One builder:
// the parked-failed record of Task 8 calls it too.
function metricsRecordArgv(ctx, spec, outcome) {
  const cur = ctx.db.prepare("SELECT * FROM specs WHERE id=?").get(spec.id) || spec;
  const caps = loadConfig(ctx.repo).budget;
  const pick = (v, d) => (v === undefined || v === null ? d : v);
  const jobs = ctx.db.prepare("SELECT session_id, kind, ended_at, started_at, tokens FROM jobs WHERE spec=? ORDER BY rowid").all(spec.id);
  const engineJobs = {};
  for (const j of jobs) if (j.session_id) engineJobs[j.session_id] = j.kind;
  const budget = {
    attempts: [pick(cur.spent_attempts, 0), pick(cur.budget_attempts, caps.attempts)],
    tokens: [pick(cur.spent_tokens, 0), pick(cur.budget_tokens, caps.tokens)],
    lower_bound: jobs.some((j) => j.ended_at !== null && j.started_at !== null && j.tokens === null),
  };
  return ["metrics", "record", spec.id, "--batch", String(spec.batch), "--outcome", outcome,
    "--budget", JSON.stringify(budget), "--engine-jobs", JSON.stringify(engineJobs)];
}

// commit_ledger, metrics_record (only with a batch; its failure is recorded, never thrown), worktree_remove (only when `removeWorktree`).
function finalize(ctx, spec, outcome, { removeWorktree = false } = {}) {
  commitLedger(ctx, spec, outcome);
  // Measurement never blocks a spec: no batch -> no step at all; a failing record stays a failed step and finalize goes on.
  if (spec.batch != null && spec.batch !== "") {
    try {
      run(ctx, spec, "metrics_record", `metrics_record:${spec.id}`, { spec: spec.id, batch: spec.batch }, () => {
        must(spawn(ctx, tmuxCtl(ctx), metricsRecordArgv(ctx, spec, outcome), { cwd: ctx.repo }), "metrics record");
        return { spec: spec.id, batch: spec.batch, outcome };
      });
    } catch (_) { /* steps.run already wrote the failed row and its step_failed event */ }
  }
  if (removeWorktree) {
    const wt = spec.worktree || ctx.worktree;
    run(ctx, spec, "worktree_remove", `worktree_remove:${spec.id}`, { path: wt }, () => {
      must(git(ctx, ctx.repo, ["worktree", "remove", wt]), "worktree remove");
      return { path: wt };
    });
  }
}

// ---- the improve loop's merge entry (improve plan Task 10, rulings A16 and A17) -------------------------------------------

// The sha of the commit on `ref` whose message has the line `Engine-Step: <key>`, or null.
function stepCommit(ctx, key, ref) {
  const r = git(ctx, ctx.repo, ["log", ref, "--format=%H%n%B%x00"]);
  if (r.error || r.status !== 0) return null;
  const want = `Engine-Step: ${key}`;
  for (const rec of r.stdout.split("\0")) {
    const lines = rec.trim().split("\n");
    if (lines.slice(1).some((l) => l.trim() === want)) return lines[0];
  }
  return null;
}

// {state, class, ...} of a proposal from `tmux-ctl improve show <id> --json`, or null.
function proposalOf(ctx, id) {
  const args = ["improve", ...(ctx.project ? ["--project", ctx.project] : []), "show", id, "--json"];
  const r = spawn(ctx, tmuxCtl(ctx), args, { cwd: ctx.repo });
  if (r.error || r.status !== 0) return null;
  try {
    const p = JSON.parse(r.stdout);
    return p && typeof p === "object" && typeof p.state === "string" ? p : null;
  } catch (_) { return null; }
}

// The first protected path the one commit of `branch` (over `base`) touches, or null.
function protectedPath(ctx, base, branch) {
  const names = must(git(ctx, ctx.repo, ["diff", "--name-only", "--no-renames", base, branch]), "git diff").split("\n").filter(Boolean);
  for (const p of names) {
    if (!improve.isProtected(p)) continue;
    const diff = git(ctx, ctx.repo, ["diff", "-U0", "--no-renames", base, branch, "--", p]);
    const old = git(ctx, ctx.repo, ["show", `${base}:${p}`]);
    if (diff.status !== 0 || improve.isProtected(p, { hunks: improve.hunksOf(diff.stdout), src: old.status === 0 ? old.stdout : "" })) return p;
  }
  return null;
}

// Rebases `branch` onto the target in a worktree of its own, never in the live checkout.
function rebaseOnto(ctx, branch) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "improve-merge-"));
  const wt = path.join(tmp, "wt");
  try {
    must(git(ctx, ctx.repo, ["worktree", "add", "-q", wt, branch]), "worktree add");
    const r = git(ctx, wt, ["rebase", target(ctx)]);
    if (r.status !== 0) {
      git(ctx, wt, ["rebase", "--abort"]);
      throw new Error(`rebase conflict: ${branch} no longer applies on ${target(ctx)}`);
    }
  } finally {
    git(ctx, ctx.repo, ["worktree", "remove", "--force", wt]);
    fs.rmSync(tmp, { recursive: true, force: true });
    git(ctx, ctx.repo, ["worktree", "prune"]);
  }
}

// Lands the one commit of `improve/<id>` on the target: rebase in its own worktree, then `merge --ff-only`, so the commit
// with `Proposal: <id>` and `Engine-Step: <key>` is the commit on the target and no merge commit exists (ruling A16).
// One `steps` row, kind `merge`, key `key`. ctx = {db, repo, tmuxCtl?, project?, env?, now?, target?}.
// -> {outcome: "merged", commit} | {outcome: "waiting"|"refused"|"failed", why}. Nothing is written for waiting and refused.
function mergeBranch(ctx, { branch, key, proposal }) {
  const tgt = target(ctx);
  const refused = (why) => ({ outcome: "refused", why });
  if (!/^improve\/[A-Za-z0-9._-]+$/.test(String(branch))) return refused(`${branch} is not an improve branch`);
  if (!/^[A-Za-z0-9_-]+$/.test(String(proposal))) return refused(`bad proposal id ${proposal}`);
  if (!new RegExp(`^improve:${proposal}[@:]`).test(String(key))) return refused(`key must start with improve:${proposal}`);
  const have = steps.getRow(ctx.db, key);
  if (have && have.state === "done") return { outcome: "merged", commit: have.result.commit, reused: true };
  const desc = { key, spec: null, kind: "merge" };
  // resume (spec 10.4): the commit is already on the target, the row was never finished
  const landed = stepCommit(ctx, key, tgt);
  if (landed) {
    steps.finish(ctx.db, desc, { branch, target: tgt, commit: landed, reconciled: true }, stepOpts(ctx));
    return { outcome: "merged", commit: landed };
  }
  if (git(ctx, ctx.repo, ["rev-parse", "-q", "--verify", `refs/heads/${branch}`]).status !== 0) return { outcome: "failed", why: `no branch ${branch}` };
  let base;
  try {
    base = must(git(ctx, ctx.repo, ["merge-base", tgt, branch]), "merge-base");
    const n = Number(must(git(ctx, ctx.repo, ["rev-list", "--count", `${base}..${branch}`]), "rev-list"));
    if (n !== 1) return refused(`${branch} has ${n} commits, want 1`);
    const msg = must(git(ctx, ctx.repo, ["log", "-1", "--format=%B", branch]), "git log").split("\n").map((l) => l.trim());
    if (!msg.includes(`Proposal: ${proposal}`)) return refused(`${branch} has no Proposal: ${proposal} trailer`);
    if (!msg.includes(`Engine-Step: ${key}`)) return refused(`${branch} has no Engine-Step: ${key} trailer`);
    const p = proposalOf(ctx, proposal);
    if (!p) return refused(`cannot read proposal ${proposal}`);
    const hit = protectedPath(ctx, base, branch);
    if (hit && !(p.state === "promoted" && p.class !== "protected")) return refused(`protected path ${hit}`);
  } catch (e) {
    return { outcome: "failed", why: e.message };
  }
  if (liveCheckoutBusy(ctx)) return { outcome: "waiting", why: "live checkout is mid-change" };
  const cur = git(ctx, ctx.repo, ["rev-parse", "--abbrev-ref", "HEAD"]);
  if (cur.status !== 0 || cur.stdout.trim() !== tgt) return { outcome: "waiting", why: `live checkout is on ${(cur.stdout || "").trim() || "?"}, not ${tgt}` };
  try {
    const r = steps.run(ctx.db, { ...desc, facts: { branch, target: tgt } }, () => {
      if (base !== must(git(ctx, ctx.repo, ["rev-parse", tgt]), "rev-parse")) rebaseOnto(ctx, branch);
      must(git(ctx, ctx.repo, ["merge", "--ff-only", "-q", branch]), "merge --ff-only");
      return { branch, target: tgt, commit: must(git(ctx, ctx.repo, ["rev-parse", "HEAD"]), "rev-parse") };
    }, stepOpts(ctx));
    return { outcome: "merged", commit: r.result.commit };
  } catch (e) {
    return { outcome: "failed", why: e.message };
  }
}

// ---- entry points -------------------------------------------------------------------------------------------

function runIntegrate(ctx, spec) {
  const wt = spec.worktree || ctx.worktree;
  const merged = spec.integration === "merge";
  const mergeDone = merged && (steps.getRow(ctx.db, mergeKey(ctx, spec)) || {}).state === "done";
  if (!mergeDone && !runTests(ctx, wt).ok) return { outcome: "tests_red_before" };
  let outcome;
  if (merged) {
    const m = doMerge(ctx, spec);
    if (m.outcome === "parked") return m;
    if (!runTests(ctx, ctx.repo).ok) return { outcome: "tests_red", merge: m.merge };
    outcome = "merged";
  } else if (spec.integration === "mr") {
    const m = doMr(ctx, spec);
    if (m.outcome === "parked") return m;
    outcome = `mr ${m.url}`;
  } else if (spec.integration === "keep") {
    outcome = `kept ${spec.branch}`;
  } else {
    return parked(`unknown integration answer: ${spec.integration}`);
  }
  finalize(ctx, spec, outcome, { removeWorktree: merged });
  return { outcome };
}

function revert(ctx, spec) {
  const row = ctx.db.prepare("SELECT key FROM steps WHERE spec=? AND kind='merge' AND state='done' ORDER BY created_at DESC LIMIT 1").get(spec.id);
  if (!row) return parked("no merge to revert");
  const sha = steps.getRow(ctx.db, row.key).result.merge;
  const key = `revert:${sha}`;
  const r = run(ctx, spec, "revert", key, { merge: sha }, () => {
    must(git(ctx, ctx.repo, ["revert", "-m", "1", "--no-commit", sha]), "git revert");
    must(git(ctx, ctx.repo, ["commit", "-q", "-m", `Revert merge ${sha.slice(0, 12)}\n\nEngine-Step: ${key}`]), "git commit");
    return { merge: sha, revert: must(git(ctx, ctx.repo, ["rev-parse", "HEAD"]), "rev-parse") };
  });
  return { outcome: "reverted", merge: sha, revert: r.result.revert };
}

module.exports = { isFailure, run: runIntegrate, revert, finalize, metricsRecordArgv, runTests, liveCheckoutBusy, mergeBranch };
