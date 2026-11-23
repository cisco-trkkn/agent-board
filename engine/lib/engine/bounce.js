"use strict";

// Task 3 moves this constant to strategy/spec_driven.js and re-exports it here.
const BOUNCE_MAX_LINES = 60;

const FAIL_LINE = /^(not ok|FAIL|ERROR|✗|AssertionError|Error:)/;
const DETAIL_LINE = /^\s+(at |expected|actual)/;
const SUMMARY_LINE = /^(# (pass|fail)|Ran \d+|FAILED|OK|ALL PASS|\d+ (passing|failing))/;
const DETAIL_PER_FAILURE = 3;

// A red check's output -> the short text a worker is bounced with: failing test names, their error
// lines, the runner's last summary line, then the log path; at most BOUNCE_MAX_LINES lines.
function text(output, logPath) {
  const lines = String(output === null || output === undefined ? "" : output).split(/\r?\n/);
  let summary = -1;
  for (let i = lines.length - 1; i >= 0; i--) if (SUMMARY_LINE.test(lines[i])) { summary = i; break; }
  const kept = [];
  let detail = 0;
  lines.forEach((line, i) => {
    if (i === summary) return;
    if (FAIL_LINE.test(line)) { kept.push(line); detail = 0; }
    else if (DETAIL_LINE.test(line) && detail < DETAIL_PER_FAILURE) { kept.push(line); detail++; }
  });
  const tail = [];
  if (summary >= 0) tail.push(lines[summary]);
  tail.push(`full log: ${logPath}`);
  const out = kept.slice(0, Math.max(0, BOUNCE_MAX_LINES - tail.length)).concat(tail).join("\n");
  return { text: out, bytes: Buffer.byteLength(out) };
}

module.exports = { text, BOUNCE_MAX_LINES };
