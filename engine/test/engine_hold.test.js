"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const db = require("../lib/engine/db");
const policy = require("../lib/engine/policy");
const rebuild = require("../lib/engine/rebuild");
const hold = require("../lib/engine/hold");

const HOLD_BIN = path.join(__dirname, "..", "bin", "hold.js");
const RULES = hold.rulesFor({});

// The plan author's 36 cases: [rule id, expected held, command].
const CASES = [
  ...["git push", "git push origin main", "git  push", "git -C /x push", "git -c a=b push", "/usr/bin/git push",
    "env A=1 git push", "cd x && git push", "bash -c 'git push'", "echo git push", "git --no-pager push"].map((c) => ["git_push", true, c]),
  ...["git pushd", "git status; echo push", "gitpush", "git log --grep push", "\"git\" push", "g\\it push"].map((c) => ["git_push", false, c]),
  ...["git reset --hard", "git reset --hard HEAD~1", "git -C w reset --hard"].map((c) => ["git_reset_hard", true, c]),
  ...["git reset --soft HEAD~1", "git reset HEAD f; echo --hard"].map((c) => ["git_reset_hard", false, c]),
  ...["git branch -D x", "git branch --delete --force x", "git branch -d --force x", "git branch -df x", "git branch -vD x"]
    .map((c) => ["git_branch_force_delete", true, c]),
  ...["git branch -d x", "git branch -a"].map((c) => ["git_branch_force_delete", false, c]),
  ...["git clean -fdx", "git clean -n"].map((c) => ["git_clean", true, c]),
  ["git_clean", false, "git cleanup"],
  ...["gh pr merge 3", "glab mr merge 4", "echo x | gh pr merge --squash"].map((c) => ["pr_merge", true, c]),
  ["pr_merge", false, "gh pr view 3"],
];

test("the case table has the plan author's 36 cases", () => assert.equal(CASES.length, 36));

for (const [id, held, command] of CASES) {
  test(`${id} ${held ? "holds" : "passes"}: ${command}`, () => {
    const rule = RULES.find((r) => r.id === id);
    assert.ok(rule, id);
    const m = hold.match([rule], { tool_name: "Bash", tool_input: { command }, cwd: "/nowhere" }, "/nowhere/wt");
    assert.equal(!!m, held);
  });
}

test("DEFAULT_HOLDS carry the seven ids in order", () => {
  assert.deepEqual(hold.DEFAULT_HOLDS.map((r) => r.id), ["git_push", "git_reset_hard", "git_branch_force_delete", "git_clean",
    "rm_recursive_outside", "write_outside", "pr_merge"]);
  assert.deepEqual(hold.rulesFor({ holds: [{ tool: "Bash", pattern: "x", outside_worktree: false }] }).map((r) => r.id).slice(7), ["config:0"]);
});

test("a config rule whose regex does not compile throws with its index", () => {
  assert.throws(() => hold.rulesFor({ holds: [{ tool: "Bash", pattern: "ok", outside_worktree: false },
    { tool: "Bash", pattern: "(", outside_worktree: false }] }), /^Error: bad hold rule 1: /);
});

// ---- path cases
function world() {
  const e = tmpEnv();
  const wt = path.join(e.root, "wt");
  fs.mkdirSync(wt, { recursive: true });
  fs.mkdirSync(path.join(e.root, "elsewhere"), { recursive: true });
  return { e, wt, root: e.root };
}
const bash = (command, wt) => ({ tool_name: "Bash", tool_input: { command }, cwd: wt });
const heldBy = (input, wt, rules = RULES) => hold.match(rules, input, wt);

test("rm and write paths against the worktree", () => {
  const { e, wt, root } = world();
  try {
    assert.equal(heldBy(bash("rm -rf build", wt), wt), null);        // mutation "drop the outside_worktree check": this becomes held
    assert.equal(heldBy(bash("rm -rf ../other", wt), wt).id, "rm_recursive_outside");
    assert.equal(heldBy(bash("rm -rf /tmp/x", wt), wt).id, "rm_recursive_outside");
    assert.equal(heldBy(bash("rm -r ~/x", wt), wt).id, "rm_recursive_outside");
    assert.equal(heldBy(bash("rm -f a.txt", wt), wt), null);          // not recursive
    // known limit: the cd is not followed, so wt2 resolves against cwd to <wt>/wt2
    assert.equal(heldBy(bash("cd .. && rm -rf wt2", wt), wt), null);
    const w = (tool, input) => heldBy({ tool_name: tool, tool_input: input, cwd: wt }, wt);
    assert.equal(w("Write", { file_path: path.join(wt, "a.js"), content: "" }), null);
    assert.equal(w("Write", { file_path: path.join(root, "elsewhere", "a.js"), content: "" }).id, "write_outside");
    assert.equal(w("Edit", { file_path: path.join(wt, "..", "x.js") }).id, "write_outside");
    assert.equal(w("NotebookEdit", { notebook_path: path.join(root, "elsewhere", "n.ipynb") }).id, "write_outside");
    assert.equal(w("NotebookEdit", { notebook_path: path.join(wt, "n.ipynb") }), null);
    assert.equal(w("Read", { file_path: path.join(root, "elsewhere", "a.js") }), null);
  } finally { e.restore(); }
});

test("a worktree path through a symlinked parent is not outside", () => {
  const { e, wt } = world();
  try {
    const link = path.join(e.root, "link");
    fs.symlinkSync(e.root, link);
    const viaLink = path.join(link, "wt");
    assert.equal(heldBy({ tool_name: "Write", tool_input: { file_path: path.join(viaLink, "a.js") }, cwd: wt }, wt), null);
    assert.equal(heldBy({ tool_name: "Write", tool_input: { file_path: path.join(wt, "a.js") }, cwd: wt }, viaLink), null);
    assert.equal(heldBy(bash(`rm -rf ${viaLink}/build`, wt), wt), null);
  } finally { e.restore(); }
});

test("a config Write|Edit rule matches the relative path", () => {
  const { e, wt } = world();
  try {
    const rules = hold.rulesFor({ holds: [{ tool: "Write|Edit", pattern: "claude/orchestrator\\.md$", outside_worktree: false }] });
    const cfg = rules.filter((r) => r.id === "config:0");
    const ed = (p) => ({ tool_name: "Edit", tool_input: { file_path: p }, cwd: wt });
    assert.equal(heldBy(ed(path.join(wt, "claude/orchestrator.md")), wt, cfg).id, "config:0");
    assert.equal(heldBy(ed(path.join(wt, "claude/skills/x/SKILL.md")), wt, cfg), null);
    assert.equal(heldBy({ tool_name: "Read", tool_input: { file_path: path.join(wt, "claude/orchestrator.md") }, cwd: wt }, wt, cfg), null);
  } finally { e.restore(); }
});

// ---- hash and question
test("callHash drops description and sorts keys", () => {
  const a = hold.callHash("Bash", { command: "ls", description: "one" });
  assert.equal(a, hold.callHash("Bash", { command: "ls", description: "two" })); // mutation "hash with description" breaks this
  assert.equal(hold.callHash("Write", { file_path: "a", content: "b" }), hold.callHash("Write", { content: "b", file_path: "a" }));
  assert.equal(hold.callHash("Write", { x: { b: 1, a: 2 } }), hold.callHash("Write", { x: { a: 2, b: 1 } }));
  assert.notEqual(a, hold.callHash("Bash", { command: "ls -l", description: "one" }));
  assert.match(a, /^[0-9a-f]{64}$/);
});

test("question forms", () => {
  assert.equal(hold.question("Bash", { command: "git push" }), "Bash: git push");
  assert.equal(hold.question("Write", { file_path: "/a/b", content: "x" }), "Write: /a/b");
  assert.equal(hold.question("NotebookEdit", { notebook_path: "/n" }), "NotebookEdit: /n");
  assert.equal(hold.question("Other", { b: 1, a: 2 }), 'Other: {"a":2,"b":1}');
  assert.equal(hold.question("Bash", { command: "x".repeat(400) }).length, 300);
});

// ---- decide
const TABLES = ["specs", "jobs", "events", "steps", "timers", "waits", "holds", "inbox"];
const counts = (d) => Object.fromEntries(TABLES.map((t) => [t, d.prepare(`SELECT count(*) n FROM ${t}`).get().n]));
// rows enter with an event, as the core writes them, so that rebuild.check can replay them
function seed(d, table, row, spec = null) {
  db.tx(d, () => { db.put(d, table, row); db.event(d, { spec, kind: `seed_${table}`, rows: [{ table, row }] }); });
}
function decideWorld() {
  const w = world();
  const d = db.open("p");
  seed(d, "specs", { id: "S", state: "running", worktree: w.wt }, "S");
  seed(d, "jobs", { id: "J", spec: "S", kind: "implement", state: "running" }, "S");
  seed(d, "specs", { id: "T", state: "running" }, "T");
  const env = { ENGINE_JOB: "J", ENGINE_PROJECT: "p", ENGINE_DIR: w.e.engineDir, ENGINE_WORKTREE: w.wt };
  const input = (command, description) => ({ tool_name: "Bash", tool_input: { command, description }, cwd: w.wt, session_id: "sess1" });
  const done = () => { d.close(); w.e.restore(); };
  const check = () => assert.equal(rebuild.check("p").rc, 0, JSON.stringify(rebuild.check("p").diffs));
  return { ...w, d, env, input, done, check };
}
const pass = (w, over) => ({ hold_id: "pass1", spec: "S", job: "J", call_hash: hold.callHash("Bash", { command: "git push" }),
  tool: "Bash", input: "{}", created_at: 1000, expires_at: 5000, used_at: null, ...over });

test("decide: ENGINE_JOB unset is none, and nothing is created or loaded", () => {
  const e = tmpEnv();
  try {
    const r = hold.decide(null, { tool_name: "Bash", tool_input: { command: "git push" }, cwd: "/" }, { ENGINE_DIR: e.engineDir }, 1000);
    assert.deepEqual(r, { decision: "none" });
    assert.equal(fs.existsSync(e.engineDir), false);
    const code = `const h=require(${JSON.stringify(path.join(__dirname, "../lib/engine/hold.js"))});
      h.decide(null,{tool_name:"Bash",tool_input:{command:"git push"},cwd:"/"},{},1);
      const bad=Object.keys(require.cache).filter(k=>/engine\\/db\\.js$/.test(k));
      console.log(JSON.stringify({bad, sqlite: process.moduleLoadList.some(m=>/sqlite/.test(m))}));`;
    const out = JSON.parse(cp.execFileSync(process.execPath, ["-e", code], { encoding: "utf8" }));
    assert.deepEqual(out, { bad: [], sqlite: false });
  } finally { e.restore(); }
});

test("decide: a non-matching call writes nothing", () => {
  const w = decideWorld();
  try {
    const before = counts(w.d);
    assert.deepEqual(hold.decide(null, w.input("git status"), w.env, 1000), { decision: "none" });
    assert.deepEqual(counts(w.d), before);
    w.check();
  } finally { w.done(); }
});

test("decide: a matching call without a pass is denied with one inbox row", () => {
  const w = decideWorld();
  try {
    const before = counts(w.d);
    const r = hold.decide(null, w.input("git push", "d"), w.env, 1000);
    assert.equal(r.decision, "deny");
    assert.match(r.hold_id, /^[0-9a-f-]{36}$/);
    assert.equal(r.reason, `held for approval ${r.hold_id}: report status blocked with the concern "awaiting approval ${r.hold_id}", then stop`);
    assert.deepEqual(counts(w.d), { ...before, inbox: before.inbox + 1 });
    const row = w.d.prepare("SELECT * FROM inbox").get();
    assert.deepEqual([row.source, row.source_id, row.spec, row.job, row.kind, row.state], ["approval", r.hold_id, "S", "J", "hold", "new"]);
    assert.deepEqual(JSON.parse(row.payload), { hold_id: r.hold_id, tool: "Bash", input: { command: "git push", description: "d" },
      call_hash: hold.callHash("Bash", { command: "git push" }), rule: "git_push", session_id: "sess1", cwd: w.wt });
    w.check();
  } finally { w.done(); }
});

test("decide: a pass allows once, then the same call is held again", () => {
  const w = decideWorld();
  try {
    seed(w.d, "holds", pass(w), "S");
    const r = hold.decide(null, w.input("git push", "other words"), w.env, 1000);
    assert.deepEqual(r, { decision: "allow", hold_id: "pass1" });
    assert.equal(w.d.prepare("SELECT used_at FROM holds").get().used_at, 1000);
    const evs = w.d.prepare("SELECT * FROM events WHERE kind='hold_pass_used'").all();
    assert.equal(evs.length, 1);
    const rows = JSON.parse(evs[0].detail).rows;
    assert.equal(rows[0].table, "holds");
    assert.equal(rows[0].row.hold_id, "pass1");
    assert.equal(rows[0].row.used_at, 1000);
    w.check();
    const again = hold.decide(null, w.input("git push"), w.env, 1001);
    assert.equal(again.decision, "deny");
    assert.notEqual(again.hold_id, "pass1");
    assert.equal(w.d.prepare("SELECT count(*) n FROM events WHERE kind='hold_pass_used'").get().n, 1);
    w.check();
  } finally { w.done(); }
});

test("decide: an expired pass is refused", () => { // mutation "ignore expires_at" makes this allow
  const w = decideWorld();
  try {
    seed(w.d, "holds", pass(w, { expires_at: 999 }), "S");
    assert.equal(hold.decide(null, w.input("git push"), w.env, 1000).decision, "deny");
    assert.equal(w.d.prepare("SELECT used_at FROM holds").get().used_at, null);
    w.check();
  } finally { w.done(); }
});

test("decide: a pass of another spec is refused", () => { // mutation "match on hash only" makes this allow
  const w = decideWorld();
  try {
    seed(w.d, "holds", pass(w, { spec: "T" }), "T");
    assert.equal(hold.decide(null, w.input("git push"), w.env, 1000).decision, "deny");
    assert.equal(w.d.prepare("SELECT used_at FROM holds").get().used_at, null);
    w.check();
  } finally { w.done(); }
});

test("decide: a different call does not use the pass", () => {
  const w = decideWorld();
  try {
    seed(w.d, "holds", pass(w), "S");
    assert.equal(hold.decide(null, w.input("git push origin x"), w.env, 1000).decision, "deny");
    assert.equal(w.d.prepare("SELECT used_at FROM holds").get().used_at, null);
  } finally { w.done(); }
});

test("decide: a job that is not in the database is denied with a new hold", () => {
  const w = decideWorld();
  try {
    const r = hold.decide(null, w.input("git push"), { ...w.env, ENGINE_JOB: "ghost" }, 1000);
    assert.equal(r.decision, "deny");
    assert.equal(w.d.prepare("SELECT job, spec FROM inbox").get().job, "ghost");
  } finally { w.done(); }
});

test("decide: config holds come from the main checkout of the worktree (real git)", () => {
  const e = tmpEnv();
  const repo = gitRepo();
  try {
    fs.mkdirSync(path.join(repo.dir, "docs/superpowers"), { recursive: true });
    fs.writeFileSync(path.join(repo.dir, "docs/superpowers/engine.json"),
      JSON.stringify({ holds: [{ tool: "Bash", pattern: "deploy-prod", outside_worktree: false }] }));
    const wt = path.join(e.root, "wt-git");
    repo.git("worktree", "add", "-q", "-b", "side", wt);
    const env = { ENGINE_JOB: "J", ENGINE_PROJECT: "p", ENGINE_DIR: e.engineDir, ENGINE_WORKTREE: wt };
    const d = db.open("p");
    seed(d, "jobs", { id: "J", spec: "S", state: "running" }, "S");
    const r = hold.decide(null, { tool_name: "Bash", tool_input: { command: "deploy-prod now" }, cwd: wt, session_id: "s" }, env, 1);
    assert.equal(r.decision, "deny");
    assert.equal(JSON.parse(d.prepare("SELECT payload FROM inbox").get().payload).rule, "config:0");
    d.close();
  } finally { repo.cleanup(); e.restore(); }
});

// ---- the process
function runBin(env, stdin) {
  const clean = { PATH: process.env.PATH, HOME: process.env.HOME };
  return cp.spawnSync(process.execPath, [HOLD_BIN], { env: { ...clean, ...env }, input: stdin, encoding: "utf8" });
}

test("bin: prints deny JSON, then allow JSON, and nothing for none", () => {
  const w = decideWorld();
  try {
    const stdin = (c) => JSON.stringify(w.input(c));
    const none = runBin(w.env, stdin("git status"));
    assert.deepEqual([none.status, none.stdout], [0, ""]);
    const deny = runBin(w.env, stdin("git push"));
    assert.equal(deny.status, 0);
    const dj = JSON.parse(deny.stdout).hookSpecificOutput;
    assert.equal(dj.hookEventName, "PreToolUse");
    assert.equal(dj.permissionDecision, "deny");
    assert.match(dj.permissionDecisionReason, /^held for approval [0-9a-f-]{36}: report status blocked/);
    seed(w.d, "holds", pass(w, { expires_at: Date.now() / 1000 + 600 }), "S");
    const allow = runBin(w.env, stdin("git push"));
    assert.equal(allow.status, 0);
    assert.equal(JSON.parse(allow.stdout).hookSpecificOutput.permissionDecision, "allow");
    w.check();
  } finally { w.done(); }
});

test("bin: unparsable stdin and unset ENGINE_JOB print nothing and exit 0", () => {
  const w = decideWorld();
  try {
    assert.deepEqual([runBin(w.env, "not json").status, runBin(w.env, "not json").stdout], [0, ""]);
    const r = runBin({}, JSON.stringify(w.input("git push")));
    assert.deepEqual([r.status, r.stdout], [0, ""]);
  } finally { w.done(); }
});

test("bin: an unwritable database after a match fails closed; before a match it stays quiet", () => {
  const w = decideWorld();
  try {
    const blocker = path.join(w.root, "file");
    fs.writeFileSync(blocker, "x");
    const env = { ...w.env, ENGINE_DIR: path.join(blocker, "sub") };
    const r = runBin(env, JSON.stringify(w.input("git push")));
    assert.equal(r.status, 0);
    const o = JSON.parse(r.stdout).hookSpecificOutput;
    assert.equal(o.permissionDecision, "deny");
    assert.match(o.permissionDecisionReason, /^engine hold check failed: .+; report status blocked$/);
    const q = runBin(env, JSON.stringify(w.input("git status")));
    assert.deepEqual([q.status, q.stdout], [0, ""]);
  } finally { w.done(); }
});

test("leak check: the real engine directory was not touched", () => {
  const real = path.join(os.homedir(), ".local/state/agent-board/engine");
  assert.equal(fs.existsSync(real) && fs.readdirSync(real).some((f) => f.startsWith("p.sqlite")), false);
});
