"use strict";
const { git, existsAt, findPlan } = require("./git.js");
const { parseManifest } = require("./manifest.js");

// computeStale(repo, spec, mainRef) -> {state: "fresh"|"stale"|"no manifest", paths}
function computeStale(repo, spec, mainRef) {
  const plan = findPlan(repo, spec);
  const parsed = plan ? parseManifest(plan.text) : { error: "no manifest" };
  if (parsed.error) return { state: "no manifest", paths: [] };
  const mf = parsed.manifest;
  const d = git(repo, ["diff", "--name-only", mf.base, mainRef]);
  if (d.rc !== 0) throw new Error(`cannot diff ${mf.base} ${mainRef}`);
  const changed = new Set(d.out.split("\n").filter(Boolean));
  const watched = new Set([...mf.writes.filter((w) => w.mode !== "create").map((w) => w.path), ...(mf.reads || [])]);
  const paths = new Set([...watched].filter((p) => changed.has(p)));
  for (const w of mf.writes) if (w.mode === "create" && existsAt(repo, mainRef, w.path)) paths.add(w.path);
  const sorted = [...paths].sort();
  return { state: sorted.length ? "stale" : "fresh", paths: sorted };
}

// stale <spec> [--main <ref>]: 0 fresh, 1 stale (paths follow), 3 no manifest.
function main(args, ctx) {
  const spec = args[0];
  if (!spec) throw new Error("usage: registry stale <spec> [--main <ref>]");
  const i = args.indexOf("--main");
  const mainRef = i >= 0 && args[i + 1] ? args[i + 1] : "main";
  const top = git(ctx.cwd, ["rev-parse", "--show-toplevel"]);
  if (top.rc !== 0) throw new Error("not in a git repo");
  const r = computeStale(top.out.trim(), spec, mainRef);
  if (r.state === "no manifest") { ctx.out("no manifest"); return 3; }
  ctx.out(r.state);
  for (const p of r.paths) ctx.out(p);
  return r.state === "stale" ? 1 : 0;
}

module.exports = { main, computeStale };
