"use strict";
// Trials on engine-run specs (improve spec 2026-11-16 section 4). The engine asks `tmux-ctl improve variants <spec> --json`
// once per spec and keeps the answer in one `improve_variants` event; everything here is derived from that list:
// the brief overlays, the challenger skill copies, the per-spec routing map and the env of a job.
// It never opens the proposals table and never writes a champion file. Protected (docs/superpowers/improve/protected.txt).
// Test: engine/test/improve.test.js.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");

const SKILLS_DIR = path.join(".superpowers", "improve", "skills"); // git-ignored, inside the spec's worktree
const CHAMPIONS = path.join("claude", "skills");

// {variants: [...]} or {error}. A non-zero exit or a spawn error is the error; an exit 0 whose output is not the variants
// JSON gives no variants (the spec then runs as a control spec).
function fetch({ tmuxCtl, spec, cwd, env }) {
  const r = cp.spawnSync(tmuxCtl, ["improve", "variants", spec, "--json"], { cwd, env, encoding: "utf8", timeout: 120000 });
  if (r.error || r.status !== 0) {
    const line = `${r.stderr || ""}\n${(r.error && r.error.message) || ""}`.split("\n").map((l) => l.trim()).find(Boolean);
    return { error: `improve variants: ${line || `exit ${r.status}`}` };
  }
  let doc = null;
  try { doc = JSON.parse(r.stdout); } catch (_) { /* not JSON */ }
  if (!doc || !Array.isArray(doc.variants)) return { variants: [] };
  return { variants: doc.variants.filter((v) => v && typeof v === "object" && typeof v.id === "string") };
}

const under = (dir, p) => p.startsWith(dir + path.sep);

// Builds one challenger copy: the champion skill folder of the main checkout, patched in a temp dir, then moved to
// <worktree>/.superpowers/improve/skills/<skill>@<id>. Returns null, or the reason nothing was created.
function skillCopy({ repo, worktree, variant }) {
  const sc = variant.skill_copy || {};
  if (![sc.from, sc.to, sc.patch].every((x) => typeof x === "string" && x)) return "skill_copy needs from, to and patch";
  const from = path.resolve(repo, sc.from);
  const dest = path.resolve(worktree, sc.to);
  if (!under(path.resolve(repo, CHAMPIONS), from)) return `not a skill folder: ${sc.from}`;
  if (!under(path.resolve(worktree, SKILLS_DIR), dest)) return `not under ${SKILLS_DIR}: ${sc.to}`;
  if (!fs.existsSync(from)) return `no champion skill at ${sc.from}`;
  const inRepo = cp.spawnSync("git", ["-C", worktree, "rev-parse", "--is-inside-work-tree"], { encoding: "utf8" });
  if (inRepo.status === 0 && cp.spawnSync("git", ["-C", worktree, "check-ignore", "-q", dest]).status !== 0) return `${sc.to} is not git-ignored`;
  let patch;
  try { patch = fs.readFileSync(sc.patch, "utf8"); } catch (e) { return `unreadable patch: ${e.message}`; }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "improve-skill-"));
  try {
    const rel = path.relative(repo, from);
    fs.cpSync(from, path.join(tmp, rel), { recursive: true });
    // outside any repository (the ceiling stops discovery), so the patch's a/ b/ paths are read from the temp root
    const r = cp.spawnSync("git", ["apply", "-"], { cwd: tmp, input: patch, encoding: "utf8", env: { ...process.env, GIT_CEILING_DIRECTORIES: path.dirname(tmp) } });
    if (r.error || r.status !== 0) return `patch does not apply: ${((r.stderr || (r.error && r.error.message) || "").trim().split("\n")[0]) || "git apply failed"}`;
    fs.rmSync(dest, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.cpSync(path.join(tmp, rel), dest, { recursive: true });
    return null;
  } catch (e) {
    return String((e && e.message) || e);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

// Makes the spec's variants real in its worktree (null when the spec has none of its own: its skill variants are dropped). A skill variant whose copy cannot be built is dropped: the spec
// then runs without it, so it is not one of the spec's variants.
function apply({ repo, worktree, variants }) {
  const kept = [];
  const dropped = [];
  for (const v of variants) {
    const reason = !v.skill_copy ? null : worktree ? skillCopy({ repo, worktree, variant: v }) : "no worktree";
    if (reason) dropped.push({ id: v.id, reason }); else kept.push(v);
  }
  return { variants: kept, dropped };
}

const ids = (variants) => variants.map((v) => v.id);

// The brief blocks of a worker or reviewer brief, "" when the spec has none.
function overlay(variants) {
  const out = [];
  for (const v of variants) {
    if (typeof v.overlay === "string" && v.overlay) out.push(v.overlay, "");
    if (v.skill_copy) {
      const name = path.basename(v.skill_copy.to);
      const champion = path.basename(v.skill_copy.from);
      out.push(`## Trial ${v.id}`, `Use the skill \`${name}\` instead of \`${champion}\`: wherever you would load \`${champion}\`, read `
        + `\`${path.join(v.skill_copy.to, "SKILL.md")}\` in this worktree and follow it instead.`, "");
    }
  }
  return out.join("\n");
}

// The tier-to-model map of the spec's jobs: the patched copy of its routing variant (the last one when several), else the engine's.
function routing(variants, base) {
  const own = variants.filter((v) => v.routing && typeof v.routing === "object").pop();
  return own ? own.routing : base;
}

// Extra environment of one job, or null: a variant's env goes only to the jobs its applies_to names.
function envFor(variants, job) {
  let env = null;
  for (const v of variants) {
    const a = v.applies_to;
    if (!v.env || typeof v.env !== "object" || !a || a.tier !== job.tier || a.kind !== job.kind) continue;
    env = { ...(env || {}), ...v.env };
  }
  return env;
}

module.exports = { fetch, apply, skillCopy, overlay, routing, envFor, ids };
