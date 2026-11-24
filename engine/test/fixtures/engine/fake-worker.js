#!/usr/bin/env node
"use strict";
// Fake worker process: node fake-worker.js <report path> <status json path> <mode>
// modes: done blocked hang silent noreport. Pane from env FAKE_PANE or argv[5].
const fs = require("node:fs");
const path = require("node:path");

const [reportPath, statusPath, mode] = process.argv.slice(2);
const pane = process.env.FAKE_PANE || process.argv[5] || "%fake";
const sessionId = `fake-worker-${process.pid}`;
const started = Math.floor(Date.now() / 1000);
let timer = null;

function write(state) {
  const now = Math.floor(Date.now() / 1000);
  const doc = {
    session_id: sessionId, pane, state, updatedAt: now,
    tool: null, turnStartedAt: started, lastToolAt: null, waiting: null,
  };
  const tmp = statusPath + ".tmp";
  fs.mkdirSync(path.dirname(statusPath), { recursive: true });
  fs.writeFileSync(tmp, JSON.stringify(doc));
  fs.renameSync(tmp, statusPath);
}

function writeReport(status) {
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `Work ${status}.\n\n\`\`\`json:status\n${JSON.stringify({ status })}\n\`\`\`\n`);
}

if (mode === "silent") {
  setInterval(() => {}, 1000);
} else if (mode === "hang") {
  write("busy");
  timer = setInterval(() => write("busy"), 1000);
} else if (["done", "blocked", "noreport"].includes(mode)) {
  write("busy");
  setTimeout(() => {
    if (mode === "done") writeReport("DONE");
    if (mode === "blocked") writeReport("BLOCKED");
    write("ready");
    setTimeout(() => process.exit(0), 2000);
  }, 1000);
} else {
  console.error(`unknown mode: ${mode}`);
  process.exit(2);
}
process.on("SIGTERM", () => { if (timer) clearInterval(timer); process.exit(0); });
