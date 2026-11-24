"use strict";
// Engine-core step 7 (spec §3) and the revert of §4. Every outside action is a `steps.run` row.
// ctx = {db, repo (main checkout), worktree, tmuxCtl, tasks?, now?, env?, target?}.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const steps = require("./steps");
const ledger = require("./ledger");
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

// commit_ledger, metrics_record (only with a batch; its failure is recorded, never thrown), worktree_remove (only when `removeWorktree`).
function finalize(ctx, spec, outcome, { removeWorktree = false } = {}) {
  commitLedger(ctx, spec, outcome);
  // Measurement never blocks a spec: no batch -> no step at all; a failing record stays a failed step and finalize goes on.
  if (spec.batch != null && spec.batch !== "") {
    try {
      run(ctx, spec, "metrics_record", `metrics_record:${spec.id}`, { spec: spec.id, batch: spec.batch }, () => {
        must(spawn(ctx, tmuxCtl(ctx), ["metrics", "record", spec.id, "--batch", String(spec.batch), "--outcome", outcome], { cwd: ctx.repo }), "metrics record");
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

module.exports = { isFailure, run: runIntegrate, revert, finalize, runTests, liveCheckoutBusy };
