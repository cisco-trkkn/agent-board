"use strict";
// Trials on engine-run specs (improve spec 2026-11-16 section 4): overlays in the briefs, challenger skill copies,
// per-spec routing, the Code Mode env and `--variants` on metrics start, all from `tmux-ctl improve variants`.
// Every test runs the fake backend against scratch git repos; TC_ENGINE_DIR, TC_STATE and TC_OBSERVER_DIR are temp dirs.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const crypto = require("node:crypto");
const { tmpEnv, gitRepo } = require("./engine_helpers");
const core = require("../lib/engine/core");
const fake = require("../lib/engine/backend/fake");
const rebuild = require("../lib/engine/rebuild");

const REPO_ROOT = path.resolve(__dirname, "../..");
const SPEC_A = "docs/superpowers/specs/2026-01-01-alpha-design.md";
const SPEC_B = "docs/superpowers/specs/2026-01-01-beta-design.md";
const PLAN_A = "docs/superpowers/plans/2026-01-01-alpha.md";
const PLAN_B = "docs/superpowers/plans/2026-01-01-beta.md";
const SKILL = "claude/skills/demo-skill/SKILL.md";
const SKILL_TEXT = "# Demo skill\n\n## Steps\n\n- old step\n";
const SKILL_PATCH = [`--- a/${SKILL}`, `+++ b/${SKILL}`, "@@ -2,4 +2,4 @@", " ", " ## Steps", " ", "-- old step", "+- new step", ""].join("\n");
const ROUTING = { mechanical: "haiku", standard: "sonnet", frontier: "fable" };

const report = (o) => "notes\n\n```json:status\n" + JSON.stringify(o) + "\n```\n";
const DONE = report({ status: "done", commits: ["abc1234"], concerns: [] });
const BLOCKED = report({ status: "blocked", commits: [], concerns: ["needs a secret"] });
const PASS = report({ verdict: "pass", findings: [] });
const DECIDE = report({ decision: "fail_spec", ruling: "ruling", cost_if_wrong: "cost" });
const worker = (text) => [{ status: "busy", at: 1 }, { report: text, at: 2 }, { status: "ready", at: 3 }];
const GREEN = { implement1: worker(DONE), review1: worker(PASS), review: worker(PASS), final_review: worker(PASS) };
const task = (subject, tier) => ({
  subject,
  description: `Do ${subject}.\n\n\`\`\`json:metadata\n${JSON.stringify({ verifyCommand: "true", modelTier: tier, files: ["a.js"] })}\n\`\`\``,
});
const sha = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");

const P1 = { id: "P1", kind: "rule", target: "claude/worker.md",
  overlay: "## Trial P1\n## Finish\nAlways run the linter.\n(This replaces the section ## Finish of claude/worker.md.)" };
const P2 = (patch) => ({ id: "P2", kind: "skill", target: SKILL,
  skill_copy: { from: "claude/skills/demo-skill", to: ".superpowers/improve/skills/demo-skill@P2", patch } });
const P3 = { id: "P3", kind: "routing", target: "docs/superpowers/model-routing.json", routing: { ...ROUTING, mechanical: "opus" } };
const P4 = { id: "P4", kind: "routing", target: "docs/superpowers/model-routing.json", routing: { ...ROUTING, codeMode: true },
  env: { CLAUDE_CODE_EXPERIMENTAL_CODE_MODE: "1" }, applies_to: { tier: "mechanical", kind: "implement" } };

// o.variants: {[spec id]: [variant…]} answered by the stubbed `tmux-ctl improve variants <spec> --json` (default: none);
// o.variantsRc: its exit code; o.realImprove: `improve` goes to the real bin/tmux-ctl; o.tier: the one task's tier.
function mk(t, o = {}) {
  const env = tmpEnv();
  const oldObs = process.env.TC_OBSERVER_DIR;
  process.env.TC_OBSERVER_DIR = path.join(env.root, "observer");
  const repo = gitRepo();
  const put = (rel, text) => { fs.mkdirSync(path.dirname(path.join(repo.dir, rel)), { recursive: true }); fs.writeFileSync(path.join(repo.dir, rel), text); };
  put(".gitignore", ".superpowers/\n");
  // the loop's repo (improve.isLoopRepo) is this scratch checkout, unless o.notLoop: then it is some other project's
  if (!o.notLoop) put("docs/superpowers/improve/protected.txt", "docs/superpowers/improve/**\n");
  const oldLoop = process.env.TC_IMPROVE_REPO;
  process.env.TC_IMPROVE_REPO = repo.dir;
  const oldProj = process.env.TC_IMPROVE_PROJECT;
  process.env.TC_IMPROVE_PROJECT = "demo"; // the real board/improve.py (o.realImprove) runs for the loop's project only
  put(SKILL, SKILL_TEXT);
  put("docs/superpowers/model-routing.json", JSON.stringify(ROUTING));
  for (const [spec, plan] of [[SPEC_A, PLAN_A], [SPEC_B, PLAN_B]]) {
    put(spec, "# Demo\n\n## Decisions\n\n- D1: keep it small.\n");
    put(`${plan}.tasks.json`, JSON.stringify({ tasks: [task("T1", o.tier || "mechanical")] }));
  }
  repo.git("add", "-A");
  repo.git("commit", "-q", "-m", "fixture");
  const wt = { [SPEC_A]: path.join(env.root, "wt-a"), [SPEC_B]: path.join(env.root, "wt-b") };
  repo.git("worktree", "add", "-q", "-b", "spec-a", wt[SPEC_A]);
  repo.git("worktree", "add", "-q", "-b", "spec-b", wt[SPEC_B]);

  const patch = path.join(env.root, "P2.diff");
  fs.writeFileSync(patch, o.patch === undefined ? SKILL_PATCH : o.patch);
  const vdir = path.join(env.root, "variants");
  fs.mkdirSync(vdir);
  for (const [spec, list] of Object.entries(typeof o.variants === "function" ? o.variants(patch) : o.variants || {})) {
    fs.writeFileSync(path.join(vdir, `${path.basename(spec)}.json`), JSON.stringify({ spec, variants: list }));
  }
  const ctl = path.join(env.root, "tmux-ctl");
  const log = path.join(env.root, "ctl.log");
  const improve = o.realImprove
    ? `if [ "$1" = improve ]; then exec zsh "${path.join(REPO_ROOT, "bin/tmux-ctl")}" "$@"; fi\n`
    : `if [ "$1 $2" = "improve variants" ]; then\n`
      + (o.variantsRc ? `  echo "improve: variants: boom" >&2; exit ${o.variantsRc}\n` : "")
      + `  f="${vdir}/$(basename "$3").json"\n  if [ -f "$f" ]; then cat "$f"; else printf '{"spec":"%s","variants":[]}\\n' "$3"; fi\n  exit 0\nfi\n`;
  fs.writeFileSync(ctl, `#!/bin/sh\n( IFS=$(printf '\\037'); printf '%s\\n' "$*" ) >> "${log}"\n${improve}`
    + `if [ "$1 $2" = "metrics start" ]; then exit 0; fi\nif [ "$1 $2" = "metrics has" ]; then exit 0; fi\necho fresh\nexit 0\n`, { mode: 0o755 });

  const clock = { t: 1000 };
  const backend = fake.createBackend({ script: o.script || GREEN, now: () => clock.t });
  const eng = core.start({
    project: "demo", repo: repo.dir, backend, now: () => clock.t, tmuxCtl: ctl,
    integrate: async () => ({ outcome: "merged" }), revert: async () => {}, finalize: async () => {},
    tell: () => {}, notify: () => {}, transcriptRoot: path.join(env.root, "transcripts"), sleep: async () => { clock.t += 5; },
  });
  const specOf = (id) => eng.db.prepare("SELECT * FROM specs WHERE id=?").get(id);
  const h = {
    env, repo, wt, eng, backend, clock, patch,
    add: (id, extra = {}) => eng.addSpec({ id, plan: id === SPEC_A ? PLAN_A : PLAN_B, worktree: wt[id], branch: id === SPEC_A ? "spec-a" : "spec-b",
      integration: "keep", push: 0, batch: "b1", ...extra }),
    async run(ids = [SPEC_A, SPEC_B]) {
      for (const id of ids) h.add(id);
      for (let i = 0; i < 600; i++) {
        if (ids.every((id) => specOf(id).state === "done")) return;
        clock.t += 5;
        await eng.tick();
      }
      assert.fail(`not done; events: ${h.events().map((e) => e.kind).join(" ")}`);
    },
    spec: specOf,
    events: (kind, spec) => eng.db.prepare("SELECT * FROM events ORDER BY seq").all().map((e) => ({ ...e, detail: JSON.parse(e.detail) }))
      .filter((e) => (!kind || e.kind === kind) && (!spec || e.spec === spec)),
    jobs: (spec) => eng.db.prepare("SELECT * FROM jobs WHERE spec=? ORDER BY rowid").all(spec),
    brief: (spec, kind) => fs.readFileSync(h.jobs(spec).find((j) => j.kind === kind).brief, "utf8"),
    starts: (spec) => backend.calls.filter((c) => c.method === "start" && c.job.worktree === wt[spec]).map((c) => c.job),
    ctl: () => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter(Boolean).map((l) => l.split("\x1f")) : []),
    metricsStart: (spec) => h.ctl().find((a) => a[0] === "metrics" && a[1] === "start" && a[2] === spec),
  };
  t.after(() => {
    eng.stop();
    if (oldObs === undefined) delete process.env.TC_OBSERVER_DIR; else process.env.TC_OBSERVER_DIR = oldObs;
    if (oldLoop === undefined) delete process.env.TC_IMPROVE_REPO; else process.env.TC_IMPROVE_REPO = oldLoop;
    if (oldProj === undefined) delete process.env.TC_IMPROVE_PROJECT; else process.env.TC_IMPROVE_PROJECT = oldProj;
    env.restore();
    repo.cleanup();
  });
  return h;
}

// ---- overlays ------------------------------------------------------------------------------------------------

test("a trial spec's implementer and reviewer briefs carry the overlay; the control spec's briefs do not", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1] } });
  await h.run();
  assert.match(h.brief(SPEC_A, "implement"), /^## Trial P1$/m);
  assert.ok(h.brief(SPEC_A, "implement").includes(P1.overlay));
  assert.match(h.brief(SPEC_A, "final_review"), /^## Trial P1$/m);
  for (const j of h.jobs(SPEC_B)) assert.doesNotMatch(fs.readFileSync(j.brief, "utf8"), /## Trial/, j.id);
  assert.equal(h.jobs(SPEC_B).length >= 2, true);
});

test("an architect brief never carries the overlay (ruling A13)", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1] }, script: { implement1: worker(BLOCKED), architect: worker(DECIDE) } });
  await h.run([SPEC_A]);
  assert.match(h.brief(SPEC_A, "implement"), /## Trial P1/);
  assert.doesNotMatch(h.brief(SPEC_A, "architect"), /## Trial/);
});

// ---- challenger skill copies ---------------------------------------------------------------------------------

test("a skill trial builds the patched copy in the trial worktree only; git stays clean and the champion is unchanged", async (t) => {
  const h = mk(t, { variants: (patch) => ({ [SPEC_A]: [P2(patch)] }) });
  const champion = path.join(h.repo.dir, SKILL);
  const before = sha(champion);
  await h.run();
  const copy = path.join(h.wt[SPEC_A], ".superpowers/improve/skills/demo-skill@P2/SKILL.md");
  assert.equal(fs.readFileSync(copy, "utf8"), SKILL_TEXT.replace("old step", "new step"));
  assert.equal(fs.existsSync(path.join(h.wt[SPEC_B], ".superpowers/improve")), false);
  assert.equal(fs.existsSync(path.join(h.repo.dir, ".superpowers/improve")), false);
  for (const dir of [h.wt[SPEC_A], h.wt[SPEC_B], h.repo.dir]) {
    assert.equal(cp.execFileSync("git", ["-C", dir, "status", "--porcelain"], { encoding: "utf8" }), "", dir);
  }
  assert.equal(sha(champion), before);
  assert.equal(fs.readFileSync(path.join(h.wt[SPEC_A], SKILL), "utf8"), SKILL_TEXT); // the worktree's own champion copy too
  const brief = h.brief(SPEC_A, "implement");
  assert.match(brief, /^## Trial P2$/m);
  assert.ok(brief.includes("demo-skill@P2"));
  assert.ok(brief.includes(".superpowers/improve/skills/demo-skill@P2/SKILL.md"));
  assert.doesNotMatch(h.brief(SPEC_B, "implement"), /demo-skill@P2/);
});

test("a skill patch that does not apply drops that variant: no copy, no brief block, not in --variants, the spec runs", async (t) => {
  const h = mk(t, { variants: (patch) => ({ [SPEC_A]: [P1, P2(patch)] }), patch: SKILL_PATCH.replace("-- old step", "-- another step") });
  await h.run([SPEC_A]);
  assert.equal(h.spec(SPEC_A).outcome, "merged");
  assert.equal(fs.existsSync(path.join(h.wt[SPEC_A], ".superpowers/improve")), false);
  assert.doesNotMatch(h.brief(SPEC_A, "implement"), /Trial P2/);
  const ev = h.events("improve_variants", SPEC_A);
  assert.equal(ev.length, 1);
  assert.deepEqual(ev[0].detail.variants.map((v) => v.id), ["P1"]);
  assert.deepEqual(ev[0].detail.dropped.map((d) => d.id), ["P2"]);
  const argv = h.metricsStart(SPEC_A);
  assert.equal(argv[argv.indexOf("--variants") + 1], "P1");
});

test("a spec with no worktree of its own drops its skill variants: nothing lands in the main checkout, other variants stay", async (t) => {
  const h = mk(t, { variants: (patch) => ({ [SPEC_A]: [P1, P2(patch)] }) });
  h.add(SPEC_A, { worktree: h.repo.dir }); // the spec runs in the main checkout
  for (let i = 0; i < 600 && h.spec(SPEC_A).state !== "done"; i++) { h.clock.t += 5; await h.eng.tick(); }
  assert.equal(h.spec(SPEC_A).outcome, "merged");
  assert.equal(fs.existsSync(path.join(h.repo.dir, ".superpowers/improve")), false);
  const ev = h.events("improve_variants", SPEC_A);
  assert.equal(ev.length, 1);
  assert.deepEqual(ev[0].detail.variants.map((v) => v.id), ["P1"]);
  assert.deepEqual(ev[0].detail.dropped, [{ id: "P2", reason: "no worktree" }]);
  assert.match(h.brief(SPEC_A, "implement"), /## Trial P1/);
  assert.doesNotMatch(h.brief(SPEC_A, "implement"), /Trial P2/);
});

test("skill copy paths outside the trial folder or the skills folder are refused", () => {
  const improve = require("../lib/improve");
  const env = tmpEnv();
  try {
    const patch = path.join(env.root, "p.diff");
    fs.writeFileSync(patch, SKILL_PATCH);
    const wt = path.join(env.root, "wt");
    fs.mkdirSync(path.join(env.root, "repo/claude/skills/demo-skill"), { recursive: true });
    fs.writeFileSync(path.join(env.root, "repo", SKILL), SKILL_TEXT);
    fs.mkdirSync(wt);
    for (const sc of [
      { from: "claude/skills/demo-skill", to: "../escape/demo-skill@P2", patch },
      { from: "claude/skills/demo-skill", to: "claude/skills/demo-skill", patch },
      { from: "../outside", to: ".superpowers/improve/skills/demo-skill@P2", patch },
      { from: "claude/skills/demo-skill", to: ".superpowers/improve/skills", patch },
    ]) {
      const r = improve.apply({ repo: path.join(env.root, "repo"), worktree: wt, variants: [{ id: "P2", kind: "skill", skill_copy: sc }] });
      assert.deepEqual(r.variants, [], JSON.stringify(sc));
      assert.equal(r.dropped.length, 1);
    }
    assert.deepEqual(fs.readdirSync(wt), []);
    assert.equal(fs.existsSync(path.join(env.root, "escape")), false);
  } finally { env.restore(); }
});

// ---- routing -------------------------------------------------------------------------------------------------

test("a routing trial starts the trial spec's mechanical jobs on the patched model; the control spec's on the champion model", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P3] } });
  await h.run();
  const impl = (spec) => h.starts(spec).find((j) => j.kind === "implement");
  assert.equal(impl(SPEC_A).model, "opus");
  assert.equal(impl(SPEC_B).model, "haiku");
  assert.equal(h.jobs(SPEC_A).find((j) => j.kind === "implement").model, "opus");
  assert.equal(h.starts(SPEC_A).find((j) => j.kind === "final_review").model, "fable"); // other tiers keep the patched copy's own values
  assert.doesNotMatch(h.brief(SPEC_A, "implement"), /## Trial/); // a routing variant has no brief text
});

test("Code Mode env goes only to the trial spec's mechanical-tier implement jobs", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P4] } });
  await h.run();
  const a = h.starts(SPEC_A);
  assert.deepEqual(a.find((j) => j.kind === "implement").env, { CLAUDE_CODE_EXPERIMENTAL_CODE_MODE: "1" });
  for (const j of a.filter((x) => x.kind !== "implement")) assert.equal(j.env, undefined, j.id);
  for (const j of h.starts(SPEC_B)) assert.equal(j.env, undefined, j.id);
  assert.equal(a.find((j) => j.kind === "implement").model, "haiku"); // a non-tier key in the patched map is no model
});

test("Code Mode env is not given to a standard-tier implement job", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P4] }, tier: "standard" });
  await h.run([SPEC_A]);
  assert.equal(h.starts(SPEC_A).find((j) => j.kind === "implement").env, undefined);
});

// ---- metrics start, the one call, failure, replay ---------------------------------------------------------------

test("metrics start carries --variants for a trial spec and not for a control spec; one variants call per spec", async (t) => {
  const h = mk(t, { variants: (patch) => ({ [SPEC_A]: [P1, P2(patch)] }) });
  await h.run();
  const a = h.metricsStart(SPEC_A);
  assert.deepEqual(a.slice(a.indexOf("--variants"), a.indexOf("--variants") + 2), ["--variants", "P1,P2"]);
  assert.deepEqual(a.slice(0, 7), ["metrics", "start", SPEC_A, "--batch", "b1", "--worktree", h.wt[SPEC_A]]);
  assert.equal(h.metricsStart(SPEC_B).includes("--variants"), false);
  for (const spec of [SPEC_A, SPEC_B]) {
    assert.deepEqual(h.ctl().filter((x) => x[0] === "improve" && x[2] === spec), [["improve", "variants", spec, "--json"]]);
  }
  assert.equal(h.events("improve_variants", SPEC_A).length, 1);
  assert.equal(h.events("improve_variants", SPEC_B).length, 0); // a spec in no trial stores nothing
});

test("the --variants argv is accepted by the real board/metrics.py start parser", (t) => {
  const repo = gitRepo();
  const env = tmpEnv();
  t.after(() => { env.restore(); repo.cleanup(); });
  // A parse error exits 2 with "usage:"; an accepted argv gets as far as the log lookup of the scratch repo ("unknown batch").
  const r = cp.spawnSync("python3", [path.join(REPO_ROOT, "board/metrics.py"), "start", SPEC_A, "--batch", "b1",
    "--worktree", path.join(repo.dir, ".claude/worktrees/x"), "--variants", "P1,P2", "--repo", repo.dir], { encoding: "utf8" });
  assert.doesNotMatch(r.stderr, /usage:|unrecognized arguments/);
  assert.match(r.stderr + r.stdout, /unknown batch b1/);
});

test("improve variants exiting 1: the spec runs with no variants and one improve_variants_error event", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1] }, variantsRc: 1 });
  await h.run([SPEC_A]);
  assert.equal(h.spec(SPEC_A).outcome, "merged");
  const errs = h.events("improve_variants_error");
  assert.equal(errs.length, 1);
  assert.equal(errs[0].spec, SPEC_A);
  assert.match(errs[0].detail.error, /boom/);
  assert.equal(h.events("improve_variants").length, 0);
  assert.doesNotMatch(h.brief(SPEC_A, "implement"), /## Trial/);
  assert.equal(h.metricsStart(SPEC_A).includes("--variants"), false);
  assert.equal(h.ctl().filter((x) => x[0] === "improve").length, 1);
});

// The loop is agent-board's own (final review I1): another project's engine never asks for variants.
test("a spec of a repo that is not the loop's repo gets no variants call and no trial", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1] }, notLoop: true });
  await h.run([SPEC_A]);
  assert.equal(h.spec(SPEC_A).outcome, "merged");
  assert.deepEqual(h.ctl().filter((x) => x[0] === "improve"), []);
  assert.equal(h.events("improve_variants").length, 0);
  assert.equal(h.events("improve_variants_error").length, 0);
  assert.doesNotMatch(h.brief(SPEC_A, "implement"), /## Trial/);
});

test("a lead-run spec gets no variants call and no trial", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1] } });
  h.add(SPEC_A, { runner: "lead" });
  for (let i = 0; i < 5; i++) { h.clock.t += 5; await h.eng.tick(); }
  assert.equal(h.events("lead_turn", SPEC_A).length, 1);
  assert.deepEqual(h.ctl().filter((x) => x[0] === "improve"), []);
  assert.equal(h.events("improve_variants").length, 0);
});

test("rebuild --check is clean after a run with variants", async (t) => {
  const h = mk(t, { variants: (patch) => ({ [SPEC_A]: [P1, P2(patch), P3] }) });
  await h.run();
  assert.equal(h.events("improve_variants", SPEC_A)[0].detail.variants.length, 3);
  assert.deepEqual(rebuild.check("demo"), { rc: 0, diffs: [] });
});

test("the engine CLI's rebuild --check exits 0 on that database", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1, P3] } });
  await h.run();
  assert.equal(h.events("improve_variants", SPEC_A).length, 1);
  h.eng.stop();
  const r = cp.spawnSync(process.execPath, [path.join(REPO_ROOT, "engine/bin/engine.js"), "rebuild", "--check", "--project", "demo"],
    { cwd: h.repo.dir, encoding: "utf8", env: { ...process.env, TC_PROJECT: "demo" } });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("a restarted engine keeps the stored variants and does not call improve variants again", async (t) => {
  const h = mk(t, { variants: { [SPEC_A]: [P1, P3] } });
  h.add(SPEC_A);
  for (let i = 0; i < 400 && !h.jobs(SPEC_A).some((j) => j.kind === "implement" && j.state === "done"); i++) { h.clock.t += 5; await h.eng.tick(); }
  h.eng.stop();
  fs.rmSync(path.join(h.env.root, "variants"), { recursive: true }); // the stub now answers "no variants"
  const backend = fake.createBackend({ script: GREEN, now: () => h.clock.t });
  const eng = core.start({ project: "demo", repo: h.repo.dir, backend, now: () => h.clock.t, tmuxCtl: path.join(h.env.root, "tmux-ctl"),
    integrate: async () => ({ outcome: "merged" }), revert: async () => {}, finalize: async () => {}, tell: () => {}, notify: () => {},
    transcriptRoot: path.join(h.env.root, "transcripts"), sleep: async () => { h.clock.t += 5; } });
  t.after(() => eng.stop());
  await eng.resume();
  for (let i = 0; i < 600 && eng.db.prepare("SELECT state FROM specs WHERE id=?").get(SPEC_A).state !== "done"; i++) { h.clock.t += 5; await eng.tick(); }
  const later = eng.db.prepare("SELECT * FROM jobs WHERE spec=? AND kind='final_review'").get(SPEC_A);
  assert.match(fs.readFileSync(later.brief, "utf8"), /## Trial P1/);
  assert.equal(h.ctl().filter((x) => x[0] === "improve").length, 1);
});

// ---- one real run of the deciding external command ---------------------------------------------------------------

test("the real tmux-ctl improve variants feeds the engine: a trial proposal's overlay reaches the trial spec's brief only", async (t) => {
  const h = mk(t, { realImprove: true });
  // a rule proposal against a champion file of this checkout, patched in a scratch copy only
  const target = "claude/worker.md";
  const live = fs.readFileSync(path.join(REPO_ROOT, target), "utf8");
  const marker = "- Trial marker line 7f3a: say so in the report.";
  const edited = path.join(h.env.root, "worker.edited.md");
  fs.writeFileSync(edited, `${live}${live.endsWith("\n") ? "" : "\n"}${marker}\n`);
  const d = cp.spawnSync("diff", ["-u", "--label", `a/${target}`, "--label", `b/${target}`, path.join(REPO_ROOT, target), edited], { encoding: "utf8" });
  assert.equal(d.status, 1, d.stderr);
  // an id whose hash split puts SPEC_A in the trial half and SPEC_B in the control half (improve_trials.in_trial)
  const inTrial = (spec, pid) => parseInt(crypto.createHash("sha256").update(spec + pid).digest("hex").slice(-1), 16) % 2 === 0;
  const pid = Array.from({ length: 200 }, (_, i) => `P${i + 1}`).find((p) => inTrial(SPEC_A, p) && !inTrial(SPEC_B, p));
  h.eng.db.prepare("INSERT INTO proposals(id, source, kind, target, patch, class, state, created_at, updated_at, title) VALUES (?,?,?,?,?,?,?,?,?,?)")
    .run(pid, "user", "rule", target, d.stdout, "low", "trial", 1000, 1000, "marker");
  const before = sha(path.join(REPO_ROOT, target));
  await h.run();
  assert.deepEqual(h.events("improve_variants_error"), []);
  const brief = h.brief(SPEC_A, "implement");
  assert.match(brief, new RegExp(`^## Trial ${pid}$`, "m"));
  assert.ok(brief.includes(marker));
  assert.doesNotMatch(h.brief(SPEC_B, "implement"), /## Trial/);
  const a = h.metricsStart(SPEC_A);
  assert.equal(a[a.indexOf("--variants") + 1], pid);
  assert.equal(sha(path.join(REPO_ROOT, target)), before);
  assert.equal(h.eng.db.prepare("SELECT state FROM proposals WHERE id=?").get(pid).state, "trial");
});
