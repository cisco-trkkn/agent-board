"use strict";
// The lead lines (spec section 6): everything the lead must hear is one JSON line in <engineDir>/<project>.lead.jsonl,
// derived from the events. The board (board/engine_lines.py) is the only reader and types them into the lead's window;
// the engine never types there itself. The queue loop calls publish after every tick; `engine run` does not.
const fs = require("node:fs");
const path = require("node:path");
const paths = require("./paths");

const iso = (s) => new Date(s * 1000).toISOString();
// event kind -> the line's text, exactly as Global Constraints gives it
const TEXT = {
  lead_turn: (e) => `[Engine] your turn: ${e.spec}`,
  awaiting_you: (e, d) => `[Engine] awaiting you: ${e.spec}: ${d.question}`,
  usage_limit: (e, d) => `[Engine] paused: usage limit until ${iso(d.until)}`,
  engine_error: (e, d) => `[Engine] stopped: ${d.error}`,
  queue_finished: (e, d) => `[Engine] queue finished: ${typeof d.report === "string" && d.report ? d.report : "(no report)"}`, // R15
};
const KINDS = Object.keys(TEXT);

const leadPath = (project) => path.join(paths.engineDir(), `${project}.lead.jsonl`);

function parseLine(s) {
  try {
    const o = JSON.parse(s);
    return o && Number.isInteger(o.seq) ? o : null;
  } catch (_) { return null; }
}

// The cursor is the file's own last whole line, so it survives the engine's death with nothing else to keep.
// A torn last line (a crash mid-append) is skipped; `torn` says the next append must start on a new row.
function tail(file) {
  let text;
  try { text = fs.readFileSync(file, "utf8"); } catch (_) { return { seq: 0, torn: false }; }
  const rows = text.split("\n").filter(Boolean);
  for (let i = rows.length - 1; i >= 0; i--) {
    const o = parseLine(rows[i]);
    if (o) return { seq: o.seq, torn: !text.endsWith("\n") };
  }
  return { seq: 0, torn: text !== "" && !text.endsWith("\n") };
}

// The floor: the database's highest seq when the first `engine start` found no lead file. Nothing at or below it is
// published, so a database with history (earlier `engine run`s) does not replay its old lines; it is kept in
// <project>.lead.start until the file has a line of its own, so a start that died before publishing loses nothing.
const floorPath = (project) => path.join(paths.engineDir(), `${project}.lead.start`);
const maxSeq = (db) => db.prepare("SELECT MAX(seq) AS s FROM events").get().s || 0;
function floorOf(project, max) {
  let n;
  try { n = parseInt(fs.readFileSync(floorPath(project), "utf8").trim(), 10); } catch (_) { return null; }
  return Number.isInteger(n) && n >= 0 && n <= max ? n : null; // a floor above the database's highest seq is another database's
}

// Called once when `engine start` begins, before resume and the first drain.
function begin(project, db) {
  if (fs.existsSync(leadPath(project))) return;
  const max = maxSeq(db);
  if (floorOf(project, max) !== null) return; // an earlier start already set it and published nothing yet
  fs.mkdirSync(paths.engineDir(), { recursive: true });
  fs.writeFileSync(floorPath(project), `${max}\n`);
}

function line(e) {
  let d = {};
  try { d = JSON.parse(e.detail) || {}; } catch (_) { d = {}; }
  return { seq: e.seq, ts: e.ts, text: String(TEXT[e.kind](e, d)).replace(/\s+/g, " ").trim() };
}

// Appends one line per qualifying event after the cursor, in seq order, never twice for one seq. Returns how many.
function publish(project, db) {
  const file = leadPath(project);
  let { seq: cursor, torn } = tail(file);
  const max = maxSeq(db);
  if (cursor > max) { // the file is from another database: set it aside and start over
    fs.renameSync(file, `${file}.old`);
    cursor = 0;
    torn = false;
  }
  cursor = Math.max(cursor, floorOf(project, max) || 0);
  const marks = KINDS.map(() => "?").join(",");
  const rows = db.prepare(`SELECT * FROM events WHERE seq>? AND kind IN (${marks}) ORDER BY seq`).all(cursor, ...KINDS);
  if (!rows.length) return 0;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, (torn ? "\n" : "") + rows.map((e) => JSON.stringify(line(e)) + "\n").join(""));
  return rows.length;
}

module.exports = { publish, begin, leadPath, line, KINDS };
