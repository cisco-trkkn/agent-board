'use strict';
// Lead liveness (spec 2026-11-23-remote-lead-liveness §2): which reaction the newest allowlisted home-channel message
// carries, and the ❓ reply line. Pure: the bridge passes the parsed lead-state.json, the target message and the clock.
const fs = require('node:fs');

const STALE_MS = 180 * 1000;
const E = { posted: '📨', busy: '⏳', read: '👀', answered: '✅', needs: '🙋', down: '⚠️' };
const ALL = new Set(Object.values(E));
const READ_MAX = 200;

// lead-state.json parsed, or null when missing or unreadable.
function readState(file) {
  try {
    const s = JSON.parse(fs.readFileSync(file, 'utf8'));
    return s && typeof s === 'object' && !Array.isArray(s) ? s : null;
  } catch { return null; }
}

// Missing, without a parsable `at`, or `at` more than 180 s before nowMs.
function stale(state, nowMs) {
  const at = Date.parse(state?.at ?? '');
  return !Number.isFinite(at) || nowMs - at > STALE_MS;
}

const head = (t) => String(t ?? '').trim().slice(0, READ_MAX);

// The lead read the message: its id is the transcript's newest channel message id, or its first 200 chars equal last_read_text.
function isRead(state, target) {
  if (state?.last_read_message_id && String(state.last_read_message_id) === String(target.id)) return true;
  return typeof state?.last_read_text === 'string' && head(state.last_read_text) !== '' && head(state.last_read_text) === head(target.text);
}

// target {id, text, answered}; precedence ⚠️, 🙋, ✅, 👀, ⏳, 📨. null without a target.
function pick(state, target, nowMs) {
  if (!target) return null;
  if (stale(state, nowMs) || state.state === 'down') return E.down;
  if (state.state === 'needs_you') return E.needs;
  if (target.answered) return E.answered;
  if (isRead(state, target)) return E.read;
  if (state.state === 'busy') return E.busy;
  return E.posted;
}

const pad = (n) => String(n).padStart(2, '0');
// 42s, 6m26s, 1h05m
function dur(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${pad(s % 60)}s`;
  return `${Math.floor(s / 3600)}h${pad(Math.floor((s % 3600) / 60))}m`;
}
// local HH:MM
function hhmm(ms) { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }

// The one ❓ reply line, from lead-state.json only.
function replyLine(state, nowMs) {
  if (!state || stale(state, nowMs)) return 'no lead state (board not running?)';
  const since = Date.parse(state.since ?? '');
  const sinceMs = Number.isFinite(since) ? since : Date.parse(state.at);
  const n = Number.isInteger(state.queued) && state.queued > 0 ? state.queued : 0;
  if (state.state === 'busy') return `busy ${dur(nowMs - sinceMs)}${state.tool ? `: ${state.tool}` : ''}; ${n} message(s) queued`;
  if (state.state === 'ready') return `ready since ${hhmm(sinceMs)}`;
  if (state.state === 'needs_you') return `needs you: a dialog is waiting in ${state.window || 'claude'}`;
  return `down: ${state.reason || 'unknown'} since ${hhmm(sinceMs)}`;
}

module.exports = { E, ALL, STALE_MS, readState, stale, isRead, pick, replyLine, dur, hhmm };
