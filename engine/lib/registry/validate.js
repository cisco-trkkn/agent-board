"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { git, existsAt } = require("./git.js");
const { parseManifest, taskFiles } = require("./manifest.js");

// validate <plan>: one stdout line per defect; 0 when none, else 1.
function main(args, ctx) {
  if (!args[0]) throw new Error("usage: registry validate <plan>");
  const top = git(ctx.cwd, ["rev-parse", "--show-toplevel"]);
  if (top.rc !== 0) throw new Error("not in a git repo");
  const repo = top.out.trim();
  const planPath = path.resolve(ctx.cwd, args[0]);
  if (!fs.existsSync(planPath)) throw new Error(`no such plan ${args[0]}`);
  const defects = [];
  const parsed = parseManifest(fs.readFileSync(planPath, "utf8"));
  const mf = parsed.manifest;
  if (parsed.error) defects.push(parsed.error);
  if (mf) {
    const baseOk = git(repo, ["cat-file", "-e", `${mf.base}^{commit}`]).rc === 0;
    if (!baseOk) defects.push(`base not found: ${mf.base}`);
    else {
      for (const w of mf.writes) {
        const there = existsAt(repo, mf.base, w.path);
        if (w.mode === "create" && there) defects.push(`create path exists at base: ${w.path}`);
        if (w.mode !== "create" && !there) defects.push(`${w.mode} path missing at base: ${w.path}`);
      }
    }
  }
  const tasksPath = planPath + ".tasks.json";
  if (!fs.existsSync(tasksPath)) defects.push("no .tasks.json");
  else if (mf) {
    const covered = new Set([...mf.writes.map((w) => w.path), ...(mf.reads || [])]);
    for (const f of taskFiles(fs.readFileSync(tasksPath, "utf8")).sort()) {
      if (!covered.has(f)) defects.push(`task file not covered: ${f}`);
    }
  }
  for (const d of defects) ctx.out(d);
  return defects.length ? 1 : 0;
}

module.exports = { main };
