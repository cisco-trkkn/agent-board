"use strict";
// The improvement loop inside the engine (improve plan Task 11): the protected-path holds of an engine worker, the weekly
// `improve` schedule, the schedule inbox row after a committed morning report, and the report's `## Improve` section.
// Isolation: every test has a temp TC_ENGINE_DIR and TC_STATE, the fake backend and a scratch git repo. The one path that
// could open a tmux window (a schedule row that is not skipped) points at a scratch tmux server and a stub tmux-ctl.
//
// Mutations run against these tests (each made the named test fail; see the task report):
//   rulesFor without the protected rules                 fails "a fake worker's Edit ..." and the vector test
//   protectedHolds reads protected.txt of the engine     fails "protectedHolds reads the file of the repo it is given"
//   the row written before the commit check              fails "an uncommitted report writes no row"
//   the TC_IMPROVE_TICK check removed                    fails "TC_IMPROVE_TICK=0: a committed report writes no row"
//   skip_if_weekly_usage 86 in the row's payload         fails "... is skipped at 85% weekly usage"
//   count every improve_variants event, not specs of P1  fails "the report's Improve section ..."
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const inbox = require("../lib/engine/inbox");
const dbm = require("../lib/engine/db");
const rebuild = require("../lib/engine/rebuild");
const hold = require("../lib/engine/hold");
const qr = require("../lib/engine/queue_report");
const improve = require("../lib/improve");

const REPO = path.resolve(__dirname, "../..");
const PROTECTED_REL = "docs/superpowers/improve/protected.txt";
const VECTORS = JSON.parse(fs.readFileSync(path.join(REPO, "docs/superpowers/improve/glob-vectors.json"), "utf8"));
const HOLD_BIN = path.join(__dirname, "..", "bin", "hold.js");
const TOOLS = "Write|Edit|MultiEdit|NotebookEdit";
const PROJECT = "impt";
const SPEC = "docs/superpowers/specs/2026-01-01-demo-design.md";
const PLAN = "docs/superpowers/plans/2026-01-01-demo.md";
const HELD = "demo:implement1:1";
const IMPROVE_ID = /^improve_protected:\d+$/;

const REAL_ENGINE = path.join(process.env.HOME || os.homedir(), ".local/state/agent-board/engine");
const realList = () => { try { return fs.readdirSync(REAL_ENGINE).sort().join("\n"); } catch (_) { return ""; } };
const REAL_BEFORE = realList();
test.after(() => assert.equal(realList(), REAL_BEFORE, "the real engine dir has the same files as before the tests"));

const write = (root, rel, text) => { fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true }); fs.writeFileSync(path.join(root, rel), text); };
const edit = (tool, file) => ({ tool_name: tool, tool_input: { file_path: file, old_string: "a", new_string: "b" } });

// ---- the rules ---------------------------------------------------------------------------------------------------

test("protectedHolds: one rule per whole-file line, the four write tools, never outside-only; ~ lines; no rule for a #section line", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "iph-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  assert.deepEqual(improve.protectedHolds(dir), [], "a missing protected.txt adds no rule");
  write(dir, PROTECTED_REL, "a/b.md\n# a comment\n\n~/.claude/settings*.json\nbin/tmux-ctl#improve\ndocs/x/**\n");
  const rules = improve.protectedHolds(dir);
  assert.equal(rules.length, 3, "bin/tmux-ctl#improve adds no hold: the merge entry guards that section by hunk (spec section 6)");
  for (const r of rules) assert.deepEqual(Object.keys(r).sort(), ["outside_worktree", "pattern", "tool"]);
  for (const r of rules) assert.deepEqual([r.tool, r.outside_worktree, typeof r.pattern], [TOOLS, false, "string"]);
  const re = rules.map((r) => new RegExp(r.pattern));
  for (const r of rules) assert.ok(r.pattern.startsWith("^") && r.pattern.endsWith("$"), `anchored: ${r.pattern}`);
  assert.deepEqual([re[0].test("a/b.md"), re[0].test("a/bxmd"), re[0].test("x/a/b.md")], [true, false, false]);
  const home = os.homedir();
  assert.ok(re[1].test(path.join(home, ".claude/settings.local.json")), "a ~/ line is an absolute-path pattern");
  assert.equal(re[1].test(".claude/settings.json"), false);
  assert.equal(re[1].test("~/.claude/settings.json"), false);
  for (const f of ["bin/tmux-ctl", "bin/tmux-ctl#improve"]) assert.equal(re.some((x) => x.test(f)), false, `${f} is not held`);
  assert.deepEqual([re[2].test("docs/x/a/b.md"), re[2].test("docs/x/a\nb"), re[2].test("docs/xy")], [true, true, false]);
});

test("protectedHolds reads the file of the repo it is given, not the engine's own", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "iph-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  write(dir, PROTECTED_REL, "only/this.md\n");
  assert.deepEqual(improve.protectedHolds(dir).map((r) => r.pattern), ["^only/this\\.md$"]);
});

test("rulesFor: the defaults, then the config rules, then improve_protected:<n>; DEFAULT_HOLDS is the same seven", (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "iph-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  write(dir, PROTECTED_REL, "a.md\nb.md\n");
  const seven = ["git_push", "git_reset_hard", "git_branch_force_delete", "git_clean", "rm_recursive_outside", "write_outside", "pr_merge"];
  assert.deepEqual(hold.DEFAULT_HOLDS.map((r) => r.id), seven);
  const ids = hold.rulesFor({ holds: [{ tool: "Bash", pattern: "x", outside_worktree: false }] }, dir).map((r) => r.id);
  assert.deepEqual(ids, [...seven, "config:0", "improve_protected:0", "improve_protected:1"]);
  assert.deepEqual(hold.rulesFor({}).map((r) => r.id), seven, "no repo: no protected rule");
  assert.deepEqual(hold.rulesFor({}, path.join(dir, "nowhere")).map((r) => r.id), seven, "a repo with no protected.txt: no rule");
});

// Ruling A15: the hold agrees with every vector of the shared file (board/improve_class.py and improve.isProtected do too).
// The one exception (final review I3): a file protected only in a section (`bin/tmux-ctl#improve`) is never held as a
// whole; the improve merge entry refuses a hunk in that section.
test("every glob vector: an Edit inside the worktree is held by an improve_protected rule exactly when the vector is protected as a whole file", () => {
  const sectionOnly = improve.protectedGlobs(path.join(REPO, PROTECTED_REL)).filter((g) => g.includes("#")).map((g) => g.slice(0, g.indexOf("#")));
  assert.deepEqual(sectionOnly, ["bin/tmux-ctl"]);
  const all = [...VECTORS.protected.map((v) => [v, true]), ...VECTORS.not_protected.map((v) => [v, false])];
  assert.ok(VECTORS.protected.length >= 21 && VECTORS.not_protected.length >= 8, "the vector file is not empty");
  const own = improve.protectedHolds(REPO);
  assert.equal(own.length, improve.protectedGlobs(path.join(REPO, PROTECTED_REL)).length - sectionOnly.length, "one rule per whole-file line");
  const rules = hold.rulesFor({}, REPO);
  const wt = "/nowhere/wt";
  for (const [v, prot] of all) {
    assert.equal(improve.isProtected(v), prot, `isProtected agrees on ${v}`);
    const want = prot && !sectionOnly.includes(v);
    assert.equal(own.some((r) => new RegExp(r.pattern).test(v)), want, `protectedHolds on ${v}`);
    for (const file of [path.join(wt, v), v]) { // an absolute path and one relative to the worker's cwd
      const m = hold.match(rules, { ...edit("Edit", file), cwd: wt }, wt);
      assert.equal(m ? m.id : null, want ? m && IMPROVE_ID.test(m.id) && m.id : null, `${file}: ${m && m.id}`);
      assert.equal(!!m, want, `${file} held`);
    }
  }
});

test("a protected file reached through a symlinked spelling of the worktree is held", (t) => {
  const real = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "iph-")));
  t.after(() => fs.rmSync(real, { recursive: true, force: true }));
  const wt = path.join(real, "wt");
  fs.mkdirSync(path.join(wt, "claude"), { recursive: true });
  fs.symlinkSync(wt, path.join(real, "alias"));
  const rules = hold.rulesFor({}, REPO);
  const m = hold.match(rules, { ...edit("Edit", path.join(real, "alias", "claude/orchestrator.md")), cwd: wt }, wt);
  assert.match(m ? m.id : "", IMPROVE_ID);
  assert.equal(hold.match(rules, { ...edit("Edit", path.join(real, "alias", "claude/skills/x/SKILL.md")), cwd: wt }, wt), null);
});

// ---- a fake worker's call through the real hook ---------------------------------------------------------------------

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const task = (subject) => ({ subject, description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: "standard", files: ["a.js"] })}\n\`\`\`` });
const git = (dir, ...a) => cp.execFileSync("git", ["-C", dir, ...a], { encoding: "utf8" });

// A scratch main checkout holding the real protected.txt, a spec worktree of it, and an engine whose implement job is running.
function holdWorld(t) {
  const env = tmpEnv();
  const repo = gitRepo();
  write(repo.dir, `${PLAN}.tasks.json`, JSON.stringify({ tasks: [task("T1")] }));
  write(repo.dir, SPEC, "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
  write(repo.dir, PROTECTED_REL, fs.readFileSync(path.join(REPO, PROTECTED_REL), "utf8"));
  write(repo.dir, "claude/orchestrator.md", "a\n");
  write(repo.dir, "claude/skills/x/SKILL.md", "a\n");
  git(repo.dir, "add", "-A"); git(repo.dir, "commit", "-q", "-m", "fixtures");
  const wt = path.join(fs.realpathSync(env.root), "wt");
  git(repo.dir, "worktree", "add", "-q", "-b", "spec-demo", wt);
  const ctl = path.join(env.root, "tmux-ctl");
  fs.writeFileSync(ctl, "#!/bin/sh\necho fresh\nexit 0\n", { mode: 0o755 });
  const clock = { t: Math.floor(Date.now() / 1000) }; // the hook child reads the real clock
  const backend = fake.createBackend({ script: { implement1: [{ status: "busy", at: 1 }] }, now: () => clock.t });
  const eng = core.start({
    project: PROJECT, repo: repo.dir, backend, tmuxCtl: ctl, now: () => clock.t,
    integrate: async () => ({ outcome: "merged" }), revert: async () => {}, finalize: async () => {},
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const h = {
    env, repo, wt, eng, db: eng.db,
    q: (sql, ...a) => eng.db.prepare(sql).all(...a),
    async step() { clock.t += 5; await eng.tick(); },
    async until(pred, max = 200) { for (let i = 0; i < max; i++) { if (pred()) return; await h.step(); } assert.fail("not reached"); },
    approvals: () => h.q("SELECT * FROM inbox WHERE source='approval' ORDER BY id").map((r) => ({ ...r, p: JSON.parse(r.payload) })),
    // The worker's tool call reaching the PreToolUse hook: engine/bin/hold.js with the job's environment.
    hook(call) {
      const r = cp.spawnSync(process.execPath, [HOLD_BIN], {
        input: JSON.stringify({ ...call, cwd: wt, session_id: "s1" }), encoding: "utf8",
        env: { PATH: process.env.PATH, HOME: env.root, ENGINE_JOB: HELD, ENGINE_PROJECT: PROJECT, ENGINE_DIR: env.engineDir, ENGINE_WORKTREE: wt },
      });
      assert.equal(r.status, 0, r.stderr);
      if (!r.stdout.trim()) return { decision: "none" };
      const o = JSON.parse(r.stdout).hookSpecificOutput;
      return { decision: o.permissionDecision, reason: o.permissionDecisionReason, id: (/approval ([0-9a-f-]{36})/.exec(o.permissionDecisionReason) || [])[1] };
    },
  };
  t.after(() => { eng.stop(); repo.cleanup(); env.restore(); });
  eng.addSpec({ id: SPEC, plan: PLAN, worktree: wt, branch: "spec-demo", integration: "keep", push: 0, batch: "b1" });
  return h;
}

for (const tool of ["Edit", "MultiEdit"]) {
  test(`a fake worker's ${tool} of claude/orchestrator.md in its worktree is held for approval; an Edit of a skill file is not`, async (t) => {
    const h = holdWorld(t);
    await h.until(() => h.q("SELECT 1 FROM jobs WHERE id=? AND state='running'", HELD).length === 1);
    assert.deepEqual(h.hook(edit("Edit", path.join(h.wt, "claude/skills/x/SKILL.md"))), { decision: "none" });
    assert.equal(h.approvals().length, 0, "an unprotected path writes no hold row");

    const r = h.hook(edit(tool, path.join(h.wt, "claude/orchestrator.md")));
    assert.equal(r.decision, "deny");
    assert.match(r.reason, /^held for approval [0-9a-f-]{36}: report status blocked/, "it asks: an approval wait, not an outright refusal");
    const rows = h.approvals();
    assert.equal(rows.length, 1);
    assert.equal(rows[0].source_id, r.id);
    assert.match(rows[0].p.rule, IMPROVE_ID);
    assert.equal(rows[0].p.tool, tool);
    await h.step(); // the engine drains the row: the spec waits for the user
    const wait = inbox.openWaitFor(h.db, SPEC);
    assert.ok(wait, "an open wait");
    assert.equal(wait.options, "approve|deny|fail");
    assert.equal(wait.question, `${tool}: ${path.join(h.wt, "claude/orchestrator.md")}`);
    const held = h.q("SELECT detail FROM events WHERE kind='held'").map((e) => JSON.parse(e.detail));
    assert.equal(held.length, 1);
    assert.match(held[0].rule, IMPROVE_ID);
    assert.equal(held[0].hold, r.id);
  });
}

// ---- the weekly schedule ---------------------------------------------------------------------------------------------

// The real bin/tmux-ctl of this checkout on a temp engine dir. It never reaches a tmux server: TMUX is unset and the
// fallback socket is a scratch name under a temp TMUX_TMPDIR. Outside tmux `tmux-ctl engine` wants --project.
function ctlWorld(t) {
  const env = tmpEnv();
  t.after(() => env.restore());
  const base = { ...process.env, TC_ENGINE_DIR: env.engineDir, TC_STATE: env.state, TC_PROJECT: PROJECT, TC_IMPROVE_PROJECT: PROJECT,
    TMUX_TMPDIR: env.root, TMUX_DASH_TMUX_ARGS: "-L impt-none -f /dev/null" };
  for (const k of ["TMUX", "TMUX_PANE", "TC_SESSION", "TC_TMUX_CTL"]) delete base[k];
  return { env, run: (...args) => cp.spawnSync(path.join(REPO, "bin/tmux-ctl"), args, { cwd: REPO, env: base, encoding: "utf8", timeout: 60000 }) };
}
const improveLines = (r) => r.stdout.split("\n").filter((l) => l.startsWith("improve "));

test("improve schedule install: `engine schedule list` shows improve weekly Sun 08:00; a second run leaves one row", (t) => {
  const w = ctlWorld(t);
  const a = w.run("improve", "schedule", "install");
  assert.equal(a.status, 0, a.stderr);
  assert.match(a.stdout, /^added improve: weekly Sun 08:00, next /);
  const b = w.run("improve", "schedule", "install");
  assert.equal(b.status, 0, b.stderr);
  assert.equal(b.stdout.trim(), "unchanged improve");
  const l = w.run("engine", "schedule", "list", "--project", PROJECT);
  assert.equal(l.status, 0, l.stderr);
  assert.equal(improveLines(l).length, 1, l.stdout);
  assert.match(improveLines(l)[0], /^improve {2}weekly Sun 08:00 {2}next \S+ \S+ {2}tmux-ctl improve tick$/);
  const d = dbm.open(PROJECT);
  t.after(() => d.close());
  const rows = d.prepare("SELECT * FROM timers WHERE kind='schedule'").all();
  assert.equal(rows.length, 1);
  const p = JSON.parse(rows[0].payload);
  assert.deepEqual([p.name, p.rule, p.command, p.skip_if_weekly_usage], ["improve", "weekly Sun 08:00", "tmux-ctl improve tick", 85]);
  assert.equal(fs.realpathSync(p.cwd), fs.realpathSync(REPO), "the tick runs in the checkout");
});

test("improve schedule install: an improve row with another rule is left as it is and reported, exit 1", (t) => {
  const w = ctlWorld(t);
  const a = w.run("engine", "schedule", "add", "improve", "--rule", "daily 03:30", "--project", PROJECT, "--", "echo", "other");
  assert.equal(a.status, 0, a.stderr);
  const b = w.run("improve", "schedule", "install");
  assert.equal(b.status, 1);
  assert.match(b.stderr, /^improve: schedule: .*schedule improve exists: rm it first/);
  const l = w.run("engine", "schedule", "list", "--project", PROJECT);
  assert.deepEqual(improveLines(l).map((x) => x.replace(/next \S+ \S+/, "next T")), ["improve  daily 03:30  next T  echo other"]);
});

test("improve schedule: anything but `install` is a usage error", (t) => {
  const w = ctlWorld(t);
  const r = w.run("improve", "schedule", "remove");
  assert.equal(r.status, 1);
  assert.equal(fs.existsSync(path.join(w.env.engineDir, `${PROJECT}.sqlite`)), false, "nothing was written");
});

// ---- the morning report ----------------------------------------------------------------------------------------------

const NOW = Date.UTC(2026, 0, 1, 23, 50, 0) / 1000;
const REPORT = "docs/superpowers/reports/2026-01-01-queue.md";
const SCHED = "SELECT * FROM inbox WHERE source='schedule' ORDER BY id";
const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

// A scratch live checkout on main and an engine on it. Should a schedule row ever run (the mutation of the 85% rule), its
// window opens on a scratch tmux server, and `tmux-ctl` on PATH is a stub.
function reportWorld(o = {}) {
  const env = tmpEnv(); // sets TC_IMPROVE_TICK=0 for every engine test; these tests are the ones that want the row
  if (!o.tickOff) delete process.env.TC_IMPROVE_TICK;
  const repo = gitRepo();
  // the scratch server: its socket dir is the TMUX_TMPDIR the engine's own tmux calls see, so the cleanup finds it
  const old = { TMUX_TMPDIR: process.env.TMUX_TMPDIR, PATH: process.env.PATH, TC_IMPROVE_REPO: process.env.TC_IMPROVE_REPO };
  // the loop's repo (improve.isLoopRepo): this scratch checkout with its protected.txt, unless the test says otherwise
  process.env.TC_IMPROVE_REPO = o.loopRepo || repo.dir;
  if (!o.noProtected) write(repo.dir, PROTECTED_REL, "docs/superpowers/improve/**\n");
  const tmp = fs.mkdtempSync("/tmp/ih-");
  process.env.TMUX_TMPDIR = tmp;
  const tmuxArgs = ["-L", `ih${process.pid}${Math.random().toString(36).slice(2, 7)}`, "-f", "/dev/null"];
  const tmux = (...a) => cp.spawnSync("tmux", [...tmuxArgs, ...a], { encoding: "utf8", env: { ...process.env, TMUX_TMPDIR: tmp, TMUX: "" } });
  const bin = path.join(env.root, "bin");
  fs.mkdirSync(bin);
  const ctl = path.join(bin, "tmux-ctl");
  fs.writeFileSync(ctl, `#!/bin/sh\necho "$@" >> "${env.root}/ctl.log"\nexit 0\n`, { mode: 0o755 });
  process.env.PATH = `${bin}:${old.PATH}`;
  write(repo.dir, ".gitignore", ".superpowers/\n");
  for (const f of ["runs.jsonl", "tasks.jsonl"]) write(repo.dir, `docs/superpowers/metrics/${f}`, "{}\n");
  git(repo.dir, "add", "-A"); git(repo.dir, "commit", "-q", "-m", "fixtures");
  const clock = { t: NOW };
  const backend = fake.createBackend({ script: {}, now: () => clock.t });
  const eng = core.start({
    project: PROJECT, repo: repo.dir, backend, tmuxCtl: ctl, tmuxArgs, now: () => clock.t,
    integrate: async () => ({ outcome: "merged" }), revert: async () => {}, finalize: async () => {},
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const w = {
    env, repo, eng, db: eng.db, clock,
    q: (sql, ...a) => eng.db.prepare(sql).all(...a),
    write: () => qr.write({ db: eng.db, repo: repo.dir, project: PROJECT, tmuxCtl: ctl, env: {}, now: () => clock.t }),
    md: () => fs.readFileSync(path.join(repo.dir, REPORT), "utf8"),
    section: () => { const md = w.md(); return md.slice(md.indexOf("## Improve"), md.indexOf("<!-- engine-queue:")).trim().split("\n"); },
    commits: () => git(repo.dir, "log", "--format=%s", "main").split("\n").filter((s) => s.startsWith("docs(report)")),
    windows: () => (tmux("list-windows", "-a", "-F", "#{window_name}").stdout || "").split("\n").filter(Boolean),
  };
  cleanups.push(() => {
    try { eng.stop(); } catch (_) { /* stopped */ }
    tmux("kill-server");
    for (const [k, v] of Object.entries(old)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
    fs.rmSync(tmp, { recursive: true, force: true });
    repo.cleanup();
    env.restore();
  });
  return w;
}

test("a committed report inserts one schedule row improve@<date>; a second write the same day adds none", () => {
  const w = reportWorld();
  assert.equal(w.write(), REPORT);
  assert.equal(w.commits().length, 1);
  assert.equal(w.q("SELECT state FROM steps WHERE key=?", `commit_report:${REPORT}`)[0].state, "done");
  let rows = w.q(SCHED);
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].source, rows[0].source_id, rows[0].kind, rows[0].state], ["schedule", "improve@2026-01-01", "run", "new"]);
  assert.deepEqual(JSON.parse(rows[0].payload), { command: "tmux-ctl improve tick", skip_if_weekly_usage: 85, cwd: w.repo.dir });
  w.clock.t += 300; // later the same day: the hook runs again
  assert.equal(w.write(), REPORT);
  rows = w.q(SCHED);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].received_at, NOW, "the first row stands");
  assert.equal(w.commits().length, 1);
});

test("an uncommitted report writes no row", () => {
  const w = reportWorld();
  write(w.repo.dir, "someone.txt", "work in progress\n"); // a dirty live checkout: the report is written, not committed
  assert.equal(w.write(), REPORT);
  assert.ok(fs.existsSync(path.join(w.repo.dir, REPORT)));
  assert.equal(w.commits().length, 0);
  assert.equal(w.q("SELECT 1 FROM events WHERE kind='report_uncommitted'").length, 1);
  assert.deepEqual(w.q(SCHED), []);
});

// The loop is agent-board's own (final review I1): another project's queue schedules no tick.
test("a committed report for a repo without protected.txt writes no row", () => {
  const w = reportWorld({ noProtected: true });
  assert.equal(w.write(), REPORT);
  assert.equal(w.commits().length, 1);
  assert.deepEqual(w.q(SCHED), []);
});

test("a committed report for a repo that is not the loop's repo writes no row, protected.txt or not", (t) => {
  const other = fs.mkdtempSync(path.join(os.tmpdir(), "iph-"));
  t.after(() => fs.rmSync(other, { recursive: true, force: true }));
  write(other, PROTECTED_REL, "x\n");
  const w = reportWorld({ loopRepo: other });
  assert.equal(w.write(), REPORT);
  assert.equal(w.commits().length, 1);
  assert.deepEqual(w.q(SCHED), []);
});

test("isLoopRepo: the main checkout of this code by default; TC_IMPROVE_REPO for tests; a symlinked path is the same repo", (t) => {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "iph-")));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  write(dir, PROTECTED_REL, "x\n");
  fs.symlinkSync(dir, `${dir}-link`);
  t.after(() => fs.rmSync(`${dir}-link`, { force: true }));
  assert.equal(improve.isLoopRepo(dir, { TC_IMPROVE_REPO: dir }), true);
  assert.equal(improve.isLoopRepo(`${dir}-link`, { TC_IMPROVE_REPO: dir }), true);
  assert.equal(improve.isLoopRepo(dir, {}), false, "a scratch repo is not this code's checkout");
  assert.equal(improve.isLoopRepo(path.join(dir, "nope"), { TC_IMPROVE_REPO: path.join(dir, "nope") }), false);
  // unpatched: git names the main checkout of this code, also from a linked worktree
  const common = cp.spawnSync("git", ["-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).stdout.trim();
  const main = path.dirname(common);
  assert.equal(improve.loopRepo({}), fs.realpathSync(main));
  assert.equal(improve.isLoopRepo(main, {}), fs.existsSync(path.join(main, PROTECTED_REL)));
});

// The switch engine_helpers.tmpEnv sets: without it every engine test that restarts an engine after a committed report
// would drain the row and open a window on the default tmux server.
test("TC_IMPROVE_TICK=0: a committed report writes no row", () => {
  const w = reportWorld({ tickOff: true });
  assert.equal(process.env.TC_IMPROVE_TICK, "0", "tmpEnv turns the post-report tick off");
  assert.equal(w.write(), REPORT);
  assert.equal(w.commits().length, 1);
  assert.deepEqual(w.q(SCHED), []);
});

test("the row of a committed report is skipped at 85% weekly usage, with a schedule_skipped event and no run", async () => {
  const w = reportWorld();
  w.write();
  write(w.env.state, "statusline/tap.json", JSON.stringify({ received_at: NOW, rate_limits: { seven_day: { used_percentage: 85 } } }));
  w.clock.t += 5;
  await w.eng.tick();
  const skipped = w.q("SELECT detail FROM events WHERE kind='schedule_skipped'").map((e) => JSON.parse(e.detail));
  assert.equal(skipped.length, 1);
  assert.deepEqual([skipped[0].name, skipped[0].reason, skipped[0].usage], ["improve", "weekly usage 85% >= 85%", 85]);
  assert.equal(w.q("SELECT 1 FROM steps WHERE kind='schedule_run'").length, 0);
  assert.equal(w.q("SELECT state FROM inbox WHERE source='schedule'")[0].state !== "new", true, "the row was drained");
  assert.deepEqual(w.windows().filter((n) => n.startsWith("sched")), [], "no window was opened");
  assert.equal(fs.existsSync(path.join(w.env.root, "ctl.log")) && /improve tick/.test(fs.readFileSync(path.join(w.env.root, "ctl.log"), "utf8")), false);
  const r = rebuild.check(PROJECT);
  assert.deepEqual(r.diffs, []);
});

const proposal = (id, state, extra = {}) => ({ id, source: "manual", kind: "brief", target: "claude/skills/x/SKILL.md", patch: "p", evidence: "[]",
  class: "low", state, outcome: null, created_at: 1, updated_at: 1, trial_started_at: 1, trial_len: 5, commit_sha: null, dedupe_key: id,
  title: `title ${id}`, shrinks_reads: 0, reason: null, ...extra });
const variantsOf = (d, spec, ids) => dbm.event(d, { spec, kind: "improve_variants", ts: NOW - 50, variants: ids.map((id) => ({ id })), dropped: [] });

test("the report's Improve section: `no trials` with no proposal; `trial: 2/5 specs` for a trial with two specs; the last tick's line", () => {
  const empty = reportWorld();
  empty.write();
  assert.deepEqual(empty.md().split("\n").filter((l) => l.startsWith("## ")), ["## Specs", "## Awaiting you", "## Metrics", "## Sleep", "## Improve"]);
  assert.deepEqual(empty.section(), ["## Improve", "", "no trials"]);

  const w = reportWorld();
  dbm.put(w.db, "proposals", proposal("P1", "trial"));
  dbm.put(w.db, "proposals", proposal("P2", "trial", { trial_len: 3 }));
  dbm.put(w.db, "proposals", proposal("P3", "kept"));
  variantsOf(w.db, "docs/a.md", ["P1"]);
  variantsOf(w.db, "docs/b.md", ["P1", "P3"]);
  variantsOf(w.db, "docs/c.md", ["P3"]);
  variantsOf(w.db, "docs/c.md", ["P10"]); // P10 is not P1
  // an older tick, then the latest one: the section shows only the latest
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 900, step: "start", counts: {} });
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 900, step: "trials", counts: { kept: 9 }, tick: 1 });
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 300, step: "start", counts: {} });
  const tid = w.q("SELECT MAX(seq) AS s FROM events WHERE kind='improve_step'")[0].s;
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 299, step: "observe", counts: { records: 4, engine_run: 2 }, tick: tid });
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 298, step: "trials", counts: { evaluated: 0, kept: 0, too_early: 2 }, tick: tid });
  dbm.event(w.db, { kind: "improve_step", ts: NOW - 297, step: "pick", counts: { started: 1 }, tick: tid });
  w.write();
  assert.deepEqual(w.section(), ["## Improve", "",
    "Last tick 2026-01-01T23:45:00.000Z: observe records 4, engine_run 2; trials evaluated 0, kept 0, too_early 2; pick started 1", "",
    "- P1 trial: 2/5 specs", "- P2 trial: 0/3 specs"]);
  assert.equal(qr.render({ db: w.db, project: PROJECT, outputs: {}, now: () => NOW }), qr.render({ db: w.db, project: PROJECT, outputs: {}, now: () => NOW }), "render is deterministic");
});
