#!/usr/bin/env node
"use strict";
// PreToolUse hook for an engine worker (spec 13): reads the hook input on stdin, prints a deny or allow, or nothing.
const hold = require("../lib/engine/hold");

const out = (decision, reason) => process.stdout.write(JSON.stringify({ hookSpecificOutput: {
  hookEventName: "PreToolUse", permissionDecision: decision, permissionDecisionReason: reason } }) + "\n");

let text = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { text += c; });
process.stdin.on("end", () => {
  let input;
  try { input = JSON.parse(text); } catch { return; }
  try {
    const r = hold.decide(null, input, process.env);
    if (r.decision === "deny") out("deny", r.reason);
    else if (r.decision === "allow") out("allow", `approval ${r.hold_id} used`);
  } catch (e) {
    if (e && e.matched) out("deny", `engine hold check failed: ${e.message}; report status blocked`);
  }
});
