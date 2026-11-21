"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// git(repo, args) -> {rc, out}: never throws; out is stdout as utf8.
function git(repo, args) {
  const r = spawnSync("git", ["-C", repo, ...args], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return { rc: r.status === null ? 1 : r.status, out: r.stdout || "" };
}

function existsAt(repo, ref, rel) {
  return git(repo, ["cat-file", "-e", `${ref}:${rel}`]).rc === 0;
}

function show(repo, ref, rel) {
  const r = git(repo, ["show", `${ref}:${rel}`]);
  return r.rc === 0 ? r.out : null;
}

// The main checkout's root, also from inside a worktree (as board/metrics.py main_root).
function mainRoot(repo) {
  const r = git(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  const common = r.rc === 0 ? r.out.trim() : "";
  if (common && path.basename(common) === ".git") return path.dirname(common);
  return repo;
}

// findPlan(repo, spec) -> {path, text, ref}|null, the rule of board/metrics.py find_plan: plans in the
// working tree first, then every refs/heads branch; a plan matches when a `**Spec:**` line in its first
// 40 lines contains the spec without `#part-N`; a line carrying the full spec (with `#part-N`) wins.
function findPlan(repo, spec) {
  const core = spec.replace(/#part-\d+$/, "");
  const sources = [];
  const dir = path.join(repo, "docs/superpowers/plans");
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith(".md")).sort(); } catch (_) { /* no plans dir */ }
  for (const n of names) sources.push({ ref: "", path: `docs/superpowers/plans/${n}`, text: fs.readFileSync(path.join(dir, n), "utf8") });
  const refs = git(repo, ["for-each-ref", "--format=%(refname)", "refs/heads"]);
  for (const ref of refs.rc === 0 ? refs.out.split(/\s+/).filter(Boolean) : []) {
    const ls = git(repo, ["ls-tree", "--name-only", ref, "docs/superpowers/plans/"]);
    for (const n of ls.rc === 0 ? ls.out.split(/\s+/).filter(Boolean) : []) {
      if (!n.endsWith(".md")) continue;
      const t = git(repo, ["show", `${ref}:${n}`]);
      if (t.rc === 0) sources.push({ ref, path: n, text: t.out });
    }
  }
  const hits = [];
  for (const s of sources) {
    for (const line of s.text.split("\n").slice(0, 40)) {
      if (line.includes("**Spec:**") && line.includes(core)) { hits.push({ ...s, exact: line.includes(spec) }); break; }
    }
  }
  if (!hits.length) return null;
  const rank = (h) => (h.exact ? 0 : 2) + (h.ref === "" ? 0 : 1);
  hits.sort((a, b) => rank(a) - rank(b)); // stable: exact line first, then working tree first
  const h = hits[0];
  return { path: h.path, text: h.text, ref: h.ref || null };
}

module.exports = { git, existsAt, show, mainRoot, findPlan };
