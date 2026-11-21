"use strict";

const MODES = ["create", "modify", "append"];
const KINDS = ["hard", "soft"];
const FENCE_RE = /```json:manifest[ \t]*\n(.*?)\n```/s;
const META_RE = /```json:metadata[ \t]*\n(.*?)\n```/s;

// parseManifest(text) -> {manifest} | {error}
function parseManifest(text) {
  const m = FENCE_RE.exec(text);
  if (!m) return { error: "no manifest" };
  let mf;
  try { mf = JSON.parse(m[1]); } catch (_) { return { error: "manifest: bad JSON" }; }
  if (mf === null || typeof mf !== "object" || Array.isArray(mf)) return { error: "manifest: bad JSON" };
  for (const key of ["spec", "base", "writes"]) {
    if (mf[key] === undefined) return { error: `manifest: ${key} missing` };
  }
  if (!Array.isArray(mf.writes)) return { error: "manifest: writes missing" };
  for (const w of mf.writes) {
    if (!w || typeof w.path !== "string") return { error: "manifest: writes missing" };
    if (!MODES.includes(w.mode)) return { error: `manifest: bad mode ${w.mode} for ${w.path}` };
  }
  for (const d of mf.depends_on || []) {
    if (!d || !KINDS.includes(d.kind)) return { error: `manifest: bad kind ${d && d.kind}` };
  }
  return { manifest: mf };
}

// taskFiles(tasksJsonText) -> the union of each task's json:metadata `files`
function taskFiles(tasksJsonText) {
  const out = new Set();
  for (const t of JSON.parse(tasksJsonText).tasks || []) {
    const m = META_RE.exec(t.description || "");
    if (!m) continue;
    let meta;
    try { meta = JSON.parse(m[1]); } catch (_) { continue; }
    for (const f of meta.files || []) if (typeof f === "string") out.add(f);
  }
  return [...out];
}

module.exports = { parseManifest, taskFiles };
