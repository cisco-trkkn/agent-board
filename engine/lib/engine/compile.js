"use strict";

const META = /```json:metadata[ \t]*\r?\n([\s\S]*?)```/g;

function metadata(description) {
  if (typeof description !== "string") return {};
  let last = null; // the LAST json:metadata fence wins, whatever follows it
  for (const m of description.matchAll(META)) last = m[1];
  if (last === null) return {};
  try {
    const o = JSON.parse(last);
    return o && typeof o === "object" && !Array.isArray(o) ? o : {};
  } catch { return {}; }
}

// .tasks.json text -> {tasks: [{n, subject, tier, files, verifyCommand}]} | {error}
function compile(tasksJsonText) {
  if (tasksJsonText === null || tasksJsonText === undefined) return { error: "no .tasks.json" };
  let doc;
  try { doc = JSON.parse(tasksJsonText); } catch { return { error: "no .tasks.json" }; }
  const list = Array.isArray(doc) ? doc : doc && doc.tasks;
  if (!Array.isArray(list)) return { error: "no .tasks.json" };
  const tasks = [];
  for (let i = 0; i < list.length; i++) {
    const t = list[i] || {};
    const meta = metadata(t.description);
    const verifyCommand = meta.verifyCommand;
    if (typeof verifyCommand !== "string" || verifyCommand === "") return { error: `no verifyCommand: task ${i + 1}` };
    tasks.push({
      n: i + 1,
      subject: t.subject,
      tier: meta.modelTier,
      files: Array.isArray(meta.files) ? meta.files : [],
      verifyCommand,
    });
  }
  return { tasks };
}

module.exports = { compile };
