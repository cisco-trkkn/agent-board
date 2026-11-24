'use strict';
// Night watch, board side down: the board writes <state>/watch/heartbeat {"at": ISO, "queue": [projects]} on every
// overview (board/watch.py). While this bridge's project was in queue mode in the last heartbeat read, a heartbeat older
// than STALE_MS gets one "board down" post, and the next fresh one one "board back" post.
// Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §5.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const STALE_MS = 5 * 60 * 1000;
const CHECK_MS = 60 * 1000;

// Same rule as board/tc_env.py state_dir() and tc_state_dir in tools/lib/tc-env.zsh.
function stateDir(env = process.env) {
  if (env.TC_STATE) return env.TC_STATE;
  return `${String(env.TMPDIR || '/tmp').replace(/\/+$/, '')}/tmux-ctl-${os.userInfo().uid}`;
}

const heartbeatFile = (env = process.env) => path.join(stateDir(env), 'watch', 'heartbeat');

function readHeartbeat(file) {
  try {
    const hb = JSON.parse(fs.readFileSync(file, 'utf8'));
    const at = Date.parse(hb?.at);
    if (!Number.isFinite(at)) return null;
    return { at, atText: String(hb.at), queue: Array.isArray(hb.queue) ? hb.queue.map(String) : [] };
  } catch { return null; }
}

// decide(prev, hb, project, nowMs) -> { next, text }. prev/next: { armed, down, last }.
// armed: the project was in queue mode in the last heartbeat read; down: the down post was made; last: that heartbeat's at text.
// A missing or unreadable file reads as "no new heartbeat": stale once armed.
function decide(prev, hb, project, nowMs) {
  const st = { armed: false, down: false, last: null, ...(prev || {}) };
  if (hb) { st.armed = hb.queue.includes(project); st.last = hb.atText; }
  const fresh = hb && nowMs - hb.at <= STALE_MS;
  if (fresh && st.down) return { next: { ...st, down: false }, text: `${project}: board back, night watch on` };
  if (!fresh && st.armed && !st.down) {
    return { next: { ...st, down: true }, text: `⚠️ ${project}: board down, night watch off (last heartbeat ${st.last || 'unknown'})` };
  }
  return { next: st, text: null };
}

module.exports = { STALE_MS, CHECK_MS, stateDir, heartbeatFile, readHeartbeat, decide };
