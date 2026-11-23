"use strict";
const path = require("node:path");

const home = () => process.env.HOME || require("node:os").homedir();

function engineDir() {
  return process.env.TC_ENGINE_DIR || path.join(home(), ".local/state/agent-board/engine");
}
const dbPath = (project) => path.join(engineDir(), `${project}.sqlite`);
const lockPath = (project) => path.join(engineDir(), `${project}.lock`);
function stateDir() {
  if (process.env.TC_STATE) return process.env.TC_STATE;
  const tmp = (process.env.TMPDIR || "/tmp").replace(/\/+$/, "");
  return `${tmp}/tmux-ctl-${process.getuid()}`;
}
const statusDir = () => path.join(stateDir(), "agent-status");
function feedPath(project) {
  const base = process.env.TC_STATE || path.join(home(), ".local/state/agent-board");
  return path.join(base, "feed", `${project}.jsonl`);
}
const workspace = (worktree) => path.join(worktree, ".superpowers", "engine");

function specSlug(spec) {
  const [file, frag] = String(spec).split("#");
  let s = path.basename(file).replace(/\.md$/, "").replace(/^\d{4}-\d{2}-\d{2}-/, "").replace(/-design$/, "");
  const m = frag && /^part-(\d+)$/.exec(frag);
  if (m) s += `-p${m[1]}`;
  return s;
}

module.exports = { engineDir, dbPath, lockPath, stateDir, statusDir, feedPath, workspace, specSlug };
