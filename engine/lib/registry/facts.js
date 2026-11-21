"use strict";
const { git, existsAt, show, findPlan } = require("./git.js");
const { parseManifest } = require("./manifest.js");

const EXCLUDED = "docs/superpowers/";
const ratio = (n, d) => (d ? n / d : null);

// An append is verified when its diff has no `-` content line and exactly one hunk.
function appendViolation(repo, base, head, p) {
  const d = git(repo, ["diff", "-U0", `${base}..${head}`, "--", p]);
  const lines = d.out.split("\n");
  const first = lines.findIndex((l) => l.startsWith("@@"));
  if (first < 0) return false; // untouched
  const body = lines.slice(first); // file headers (--- a/x) precede the first hunk
  return body.filter((l) => l.startsWith("@@")).length !== 1 || body.some((l) => l.startsWith("-"));
}

// computeFacts(repo, spec, base, head) -> the manifest fields of one run; throws code 3 `no manifest`.
function computeFacts(repo, spec, base, head) {
  const plan = findPlan(repo, spec);
  const noManifest = () => Object.assign(new Error("no manifest"), { code: 3 });
  if (!plan) throw noManifest();
  const text = show(repo, head, plan.path) ?? plan.text;
  const parsed = parseManifest(text);
  if (parsed.error) throw noManifest();
  const mf = parsed.manifest;
  const d = git(repo, ["diff", "--name-only", `${base}..${head}`]);
  if (d.rc !== 0) throw new Error(`cannot diff ${base}..${head}`);
  const touched = d.out.split("\n").filter((p) => p && !p.startsWith(EXCLUDED));
  const writes = mf.writes.filter((w) => !w.path.startsWith(EXCLUDED));
  const touchedSet = new Set(touched);
  const violations = writes.filter((w) => w.mode === "append" && touchedSet.has(w.path) && appendViolation(repo, base, head, w.path)).map((w) => w.path);
  const mode = new Map(writes.map((w) => [w.path, w.mode]));
  const existed = touched.filter((p) => existsAt(repo, base, p));
  const created = touched.filter((p) => !existsAt(repo, base, p));
  const okExisting = existed.filter((p) => ["modify", "append"].includes(mode.get(p)) && !violations.includes(p));
  const okCreated = created.filter((p) => mode.get(p) === "create");
  const declared = new Set(writes.map((w) => w.path).filter((p) => !violations.includes(p)));
  const both = touched.filter((p) => declared.has(p));
  const rf = mf.refreshed_from;
  return {
    recall_existing: ratio(okExisting.length, existed.length),
    recall_created: ratio(okCreated.length, created.length),
    precision: ratio(writes.filter((w) => touchedSet.has(w.path)).length, writes.length),
    append_violations: violations.sort(),
    refreshes: rf ? 1 : 0,
    stale_paths: rf && Array.isArray(rf.stale_paths) ? rf.stale_paths.length : 0,
    writes: mf.writes,
    declared: writes.length,
    touched: touched.length,
    both: both.length,
    missed: touched.filter((p) => !declared.has(p)).sort(),
  };
}

// facts <spec> --base <sha> --head <sha>: one JSON line.
function main(args, ctx) {
  const spec = args[0];
  const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
  const base = opt("--base"), head = opt("--head");
  if (!spec || !base || !head) throw new Error("usage: registry facts <spec> --base <sha> --head <sha>");
  const top = git(ctx.cwd, ["rev-parse", "--show-toplevel"]);
  if (top.rc !== 0) throw new Error("not in a git repo");
  ctx.out(JSON.stringify(computeFacts(top.out.trim(), spec, base, head)));
  return 0;
}

module.exports = { main, computeFacts };
