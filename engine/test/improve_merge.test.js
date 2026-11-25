"use strict";
// Task 10: the engine's improve merge entry (`engine merge-branch`) and the JS protected-path check.
// Every git command runs on a scratch repo in a temp dir; `tmux-ctl improve show` is a stub that prints a proposal file.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const integrate = require("../lib/engine/integrate");
const improve = require("../lib/improve");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const VECTORS = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../docs/superpowers/improve/glob-vectors.json"), "utf8"));

const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

// A scratch main checkout, a stub tmux-ctl answering `improve … show <id> --json` from proposal.json, and helpers
// that build a one-commit branch improve/<id> from main.
function setup({ state = "kept", cls = "low" } = {}) {
  const e = tmpEnv();
  cleanups.push(() => e.restore());
  const g = gitRepo();
  cleanups.push(() => g.cleanup());
  for (const [f, text] of [["docs/foo.md", "old\n"], ["claude/orchestrator.md", "rules\n"], ["other.txt", "o\n"]]) {
    fs.mkdirSync(path.dirname(path.join(g.dir, f)), { recursive: true });
    fs.writeFileSync(path.join(g.dir, f), text);
  }
  g.git("add", "-A");
  g.git("commit", "-q", "-m", "files");
  const bin = path.join(e.root, "bin");
  fs.mkdirSync(bin);
  const log = path.join(e.root, "calls.log");
  const pfile = path.join(e.root, "proposal.json");
  const tc = path.join(bin, "tmux-ctl");
  fs.writeFileSync(tc, `#!/bin/sh\necho "tmux-ctl $@" >> "${log}"\n[ -f "${pfile}" ] || { echo "improve: show: no proposal" >&2; exit 1; }\ncat "${pfile}"\n`, { mode: 0o755 });
  const setProposal = (p) => fs.writeFileSync(pfile, JSON.stringify(p));
  setProposal({ id: "P1", state, class: cls, kind: "procedure", target: "docs/foo.md" });
  const db = dbm.open("p");
  cleanups.push(() => { try { db.close(); } catch (_) { /* closed */ } });
  const ctx = { db, repo: g.dir, tmuxCtl: tc, project: "p", now: 1 };
  const head = (ref = "main") => g.git("rev-parse", ref).trim();
  // one commit on `improve/<id>` (or `name`) from main, in a throwaway worktree
  const branch = ({ id = "P1", file = "docs/foo.md", text = "new\n", name, key, trailers = true, extra = 0 } = {}) => {
    const b = name || `improve/${id}`;
    const k = key || `improve:${id}@${head()}`;
    const wt = path.join(e.root, `wt-${b.replace(/\//g, "-")}`);
    g.git("worktree", "add", "-q", "-b", b, wt, "main");
    const w = (...a) => cp.execFileSync("git", ["-C", wt, ...a], { encoding: "utf8" });
    fs.writeFileSync(path.join(wt, file), text);
    w("add", "--", file);
    w("commit", "-q", "-m", `improve(procedure): ${id} better words${trailers ? `\n\nProposal: ${id}\nEngine-Step: ${k}` : ""}`);
    for (let i = 0; i < extra; i++) { fs.writeFileSync(path.join(wt, "other.txt"), `x${i}\n`); w("commit", "-q", "-am", `extra ${i}`); }
    g.git("worktree", "remove", "--force", wt);
    return { branch: b, key: k, proposal: id };
  };
  const advance = (file = "other.txt", text = "moved\n") => { // main moves on, so the branch needs its rebase
    fs.writeFileSync(path.join(g.dir, file), text);
    g.git("commit", "-q", "-am", "main moves");
  };
  const stepRow = (key) => db.prepare("SELECT * FROM steps WHERE key=?").get(key);
  const calls = () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter(Boolean) : []);
  return { e, g, db, ctx, tc, head, branch, advance, stepRow, setProposal, calls };
}

test("every glob vector gets its protected value from the JS check (ruling A15)", () => {
  // mutation: translate `*` to `[^/]*` -> docs/superpowers/metrics/configs/a.md comes out not protected
  assert.ok(VECTORS.protected.length >= 20 && VECTORS.not_protected.length >= 8);
  for (const p of VECTORS.protected) assert.equal(improve.isProtected(p), true, `${p} must be protected`);
  for (const p of VECTORS.not_protected) assert.equal(improve.isProtected(p), false, `${p} must not be protected`);
});

test("bin/tmux-ctl#improve: only a hunk inside the improve) case is protected when hunks are given", () => {
  const src = ["case $cmd in", "  engine)", "    run ;;", "  improve)", "    a", "    b ;;", "  metrics)", "    m ;;", "esac"].join("\n");
  assert.equal(improve.isProtected("bin/tmux-ctl"), true); // path only: the whole file
  assert.equal(improve.isProtected("bin/tmux-ctl", { hunks: [[2, 3]], src }), false);
  assert.equal(improve.isProtected("bin/tmux-ctl", { hunks: [[8, 8]], src }), false);
  assert.equal(improve.isProtected("bin/tmux-ctl", { hunks: [[5, 5]], src }), true);
  assert.equal(improve.isProtected("bin/tmux-ctl", { hunks: [[1, 4]], src }), true);
  assert.deepEqual(improve.hunksOf("@@ -5 +5 @@\n-a\n+z\n@@ -7,2 +7,3 @@\n@@ -9,0 +11,2 @@\n"), [[5, 5], [7, 8], [9, 9]]);
});

test("merge-branch lands exactly one single-parent commit with the subject and both trailers (ruling A16)", () => {
  // mutation: `merge --no-ff` in place of `--ff-only` -> rev-list --count is 2 and the tip has two parents
  const s = setup();
  const b = s.branch();
  s.advance();
  const before = s.head();
  const r = integrate.mergeBranch(s.ctx, b);
  assert.equal(r.outcome, "merged", JSON.stringify(r));
  assert.equal(s.g.git("rev-list", "--count", `${before}..main`).trim(), "1");
  assert.equal(s.g.git("rev-list", "--parents", "-n", "1", "main").trim().split(" ").length, 2); // the commit and one parent
  assert.equal(s.g.git("rev-parse", "main^").trim(), before);
  const msg = s.g.git("log", "-1", "--format=%B", "main").split("\n");
  assert.equal(msg[0], "improve(procedure): P1 better words");
  assert.ok(msg.includes("Proposal: P1"));
  assert.ok(msg.includes(`Engine-Step: ${b.key}`));
  assert.equal(s.g.git("diff", "--name-only", before, "main").trim(), "docs/foo.md");
  assert.equal(r.commit, s.head());
  assert.equal(fs.readFileSync(path.join(s.g.dir, "docs/foo.md"), "utf8"), "new\n"); // the live checkout moved with main
  assert.equal(fs.readFileSync(path.join(s.g.dir, "other.txt"), "utf8"), "moved\n");
  const row = s.stepRow(b.key);
  assert.equal(row.kind, "merge");
  assert.equal(row.state, "done");
  assert.equal(row.spec, null);
  assert.equal(s.g.git("worktree", "list").trim().split("\n").length, 1); // the entry's rebase worktree is gone
  assert.deepEqual(s.calls(), ["tmux-ctl improve --project p show P1 --json"]);
});

test("a second merge-branch with the same key makes no second commit", () => {
  const s = setup();
  const b = s.branch();
  assert.equal(integrate.mergeBranch(s.ctx, b).outcome, "merged");
  const head = s.head();
  const again = integrate.mergeBranch(s.ctx, b);
  assert.deepEqual([again.outcome, again.commit, again.reused], ["merged", head, true]);
  assert.equal(s.head(), head);
});

test("resume: the step row is lost or still intent, the commit is on main -> finished by the trailer check, no new commit", () => {
  // mutation: drop the trailer check -> the step runs again; with the branch gone that is `failed`
  const s = setup();
  const b = s.branch();
  assert.equal(integrate.mergeBranch(s.ctx, b).outcome, "merged");
  const head = s.head();
  s.db.prepare("UPDATE steps SET state='intent' WHERE key=?").run(b.key);
  s.g.git("branch", "-D", b.branch);
  const again = integrate.mergeBranch(s.ctx, b);
  assert.deepEqual([again.outcome, again.commit], ["merged", head]);
  assert.equal(s.head(), head);
  assert.equal(s.stepRow(b.key).state, "done");
});

test("refuses an improve commit touching claude/orchestrator.md for a kept proposal", () => {
  // mutation: skip the protected check -> merged
  const s = setup({ state: "kept", cls: "low" });
  const b = s.branch({ file: "claude/orchestrator.md", text: "looser rules\n" });
  const before = s.head();
  const r = integrate.mergeBranch(s.ctx, b);
  assert.deepEqual([r.outcome, r.why], ["refused", "protected path claude/orchestrator.md"]);
  assert.equal(s.head(), before);
  assert.equal(s.stepRow(b.key), undefined);
});

test("refuses a promoted proposal whose class is protected; a promoted high one may touch the path", () => {
  // mutation: accept any promoted proposal -> the first merge lands
  const s = setup({ state: "promoted", cls: "protected" });
  const b = s.branch({ file: "claude/orchestrator.md", text: "looser rules\n" });
  const before = s.head();
  assert.deepEqual(integrate.mergeBranch(s.ctx, b), { outcome: "refused", why: "protected path claude/orchestrator.md" });
  assert.equal(s.head(), before);
  s.setProposal({ id: "P1", state: "promoted", class: "high" });
  assert.equal(integrate.mergeBranch(s.ctx, b).outcome, "merged");
  assert.equal(s.g.git("rev-list", "--count", `${before}..main`).trim(), "1");
});

test("refuses when the proposal cannot be read, the branch has two commits, a trailer is missing or the names do not match", () => {
  const s = setup();
  const before = s.head();
  const two = s.branch({ id: "P2", extra: 1 });
  assert.match(integrate.mergeBranch(s.ctx, two).why, /improve\/P2 has 2 commits, want 1/);
  const bare = s.branch({ id: "P3", trailers: false });
  assert.match(integrate.mergeBranch(s.ctx, bare).why, /no Proposal: P3 trailer/);
  const other = s.branch({ id: "P4", name: "feature/x" });
  assert.match(integrate.mergeBranch(s.ctx, other).why, /not an improve branch/);
  const good = s.branch({ id: "P5" });
  assert.match(integrate.mergeBranch(s.ctx, { ...good, key: "merge:x@1" }).why, /key must start with improve:P5/);
  fs.rmSync(path.join(s.e.root, "proposal.json"));
  const r = integrate.mergeBranch(s.ctx, good);
  assert.equal(r.outcome, "refused");
  assert.match(r.why, /cannot read proposal P5/);
  assert.equal(s.head(), before);
});

test("live checkout mid-change or on another branch: waiting, no commit, no step row", () => {
  // mutation: drop the liveCheckoutBusy call -> the fast-forward runs over the dirty file's checkout
  const s = setup();
  const b = s.branch();
  const before = s.head();
  fs.writeFileSync(path.join(s.g.dir, "other.txt"), "half an edit\n");
  const r = integrate.mergeBranch(s.ctx, b);
  assert.deepEqual([r.outcome, r.why], ["waiting", "live checkout is mid-change"]);
  assert.equal(s.head(), before);
  assert.equal(s.stepRow(b.key), undefined);
  s.g.git("checkout", "-q", "--", "other.txt");
  s.g.git("checkout", "-q", "-b", "side");
  assert.deepEqual(integrate.mergeBranch(s.ctx, b), { outcome: "waiting", why: "live checkout is on side, not main" });
  s.g.git("checkout", "-q", "main");
  assert.equal(integrate.mergeBranch(s.ctx, b).outcome, "merged");
});

test("a rebase conflict fails, leaves main alone and leaves no worktree or rebase behind", () => {
  const s = setup();
  const b = s.branch();
  s.advance("docs/foo.md", "main changed the same line\n");
  const before = s.head();
  const r = integrate.mergeBranch(s.ctx, b);
  assert.equal(r.outcome, "failed");
  assert.match(r.why, /rebase conflict/);
  assert.equal(s.head(), before);
  assert.equal(s.g.git("worktree", "list").trim().split("\n").length, 1);
  assert.equal(s.g.git("status", "--porcelain").trim(), "");
  assert.equal(s.stepRow(b.key).state, "failed");
});

// ---- the command line ---------------------------------------------------------------------------------------------

function cli(s, args) {
  return cp.spawnSync("node", [ENGINE, "merge-branch", ...args], {
    cwd: s.g.dir, encoding: "utf8",
    env: { ...process.env, TC_ENGINE_DIR: s.e.engineDir, TC_STATE: s.e.state, TC_TMUX_CTL: s.tc, TC_PROJECT: "" },
  });
}

test("engine merge-branch: exit 0 and the sha; exit 2 with `protected path <p>`; exit 3 while the checkout is mid-change", () => {
  const s = setup();
  s.db.close();
  const bad = s.branch({ id: "P2", file: "claude/orchestrator.md", text: "looser\n" });
  const before = s.head();
  let r = cli(s, [bad.branch, "--key", bad.key, "--proposal", "P2", "--project", "p"]);
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /^engine: merge-branch: protected path claude\/orchestrator\.md$/m);
  assert.equal(s.head(), before);
  const b = s.branch();
  fs.writeFileSync(path.join(s.g.dir, "other.txt"), "half\n");
  r = cli(s, [b.branch, "--key", b.key, "--proposal", "P1", "--project", "p"]);
  assert.equal(r.status, 3, r.stderr);
  assert.match(r.stderr, /waiting: live checkout is mid-change/);
  assert.equal(s.head(), before);
  s.g.git("checkout", "-q", "--", "other.txt");
  r = cli(s, [b.branch, "--key", b.key, "--proposal", "P1", "--project", "p"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout.trim(), `merged improve/P1: ${s.head()}`);
  assert.equal(s.g.git("rev-list", "--count", `${before}..main`).trim(), "1");
});

test("engine merge-branch: usage errors are exit 2", () => {
  const s = setup();
  s.db.close();
  for (const args of [[], ["improve/P1"], ["improve/P1", "--key", "improve:P1@x"], ["improve/P1", "--proposal", "P1"]]) {
    const r = cli(s, [...args, "--project", "p"]);
    assert.equal(r.status, 2, args.join(" "));
    assert.match(r.stderr, /usage: engine merge-branch <branch> --key <key> --proposal <id>/);
  }
});
