#!/usr/bin/env node
"use strict";
const SUBS = ["validate", "analyse", "stale", "report", "facts"];
const notBuilt = () => { throw new Error("not built"); };
function load(sub) {
  try { return require(`../lib/registry/${sub}.js`).main; } catch (e) {
    if (e.code === "MODULE_NOT_FOUND" && String(e.message).includes(`registry/${sub}.js`)) return notBuilt;
    throw e;
  }
}
function main(argv, io) {
  const lo = (io && io.load) || load;
  const err = (io && io.err) || ((s) => process.stderr.write(s));
  const sub = argv[0];
  if (!SUBS.includes(sub)) {
    err("registry: usage: registry <" + SUBS.join("|") + "> ...\n");
    return 2;
  }
  try {
    const rc = lo(sub)(argv.slice(1), {cwd: process.cwd(), out: (s) => process.stdout.write(s + "\n")});
    return typeof rc === "number" ? rc : 0;
  } catch (e) {
    const msg = String(e && e.message ? e.message : e).split("\n")[0];
    err(`registry: ${sub}: ${msg}\n`);
    return e && typeof e.code === "number" ? e.code : 1;
  }
}
module.exports = { main };
if (require.main === module) process.exitCode = main(process.argv.slice(2));
