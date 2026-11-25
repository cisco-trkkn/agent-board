'use strict';
process.env.TZ = 'UTC'; // hhmm is local time: pin it before any Date is built
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const lv = require('../lib/liveness');

const NOW = Date.parse('2026-11-24T21:46:26Z');
const iso = (ms) => new Date(ms).toISOString();
const st = (o = {}) => ({ at: iso(NOW - 5000), state: 'ready', since: iso(NOW - 60000), tool: null, queued: 0, last_read_text: null, holder: true, ...o });
const msg = (o = {}) => ({ id: '100', text: 'deploy it?', answered: false, ...o });

test('each reaction of the table', () => {
  assert.strictEqual(lv.pick(st(), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(st({ state: 'busy' }), msg(), NOW), '⏳');
  assert.strictEqual(lv.pick(st({ last_read_text: 'deploy it?' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st(), msg({ answered: true }), NOW), '✅');
  assert.strictEqual(lv.pick(st({ state: 'needs_you' }), msg(), NOW), '🙋');
  assert.strictEqual(lv.pick(st({ state: 'down' }), msg(), NOW), '⚠️');
});

test('precedence: ⚠️ > 🙋 > ✅ > 👀 > ⏳ > 📨', () => {
  const read = { last_read_text: 'deploy it?' };
  assert.strictEqual(lv.pick(st({ state: 'down', ...read }), msg({ answered: true }), NOW), '⚠️');
  assert.strictEqual(lv.pick(st({ state: 'needs_you', ...read }), msg({ answered: true }), NOW), '🙋'); // mutation: answered checked before needs_you -> fails
  assert.strictEqual(lv.pick(st({ state: 'busy', ...read }), msg({ answered: true }), NOW), '✅');
  assert.strictEqual(lv.pick(st({ state: 'busy', ...read }), msg(), NOW), '👀'); // mutation: busy checked before read -> fails
});

test('a stale or missing state file is ⚠️', () => {
  assert.strictEqual(lv.pick(st({ at: iso(NOW - 181000) }), msg(), NOW), '⚠️'); // mutation: STALE_MS 300 s -> fails
  assert.strictEqual(lv.pick(st({ at: iso(NOW - 179000) }), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(null, msg(), NOW), '⚠️');
  assert.strictEqual(lv.pick(st({ at: 'garbage' }), msg(), NOW), '⚠️');
});

test('read: by message id, or first 200 chars after trim; a different text is not read', () => {
  const long = 'x'.repeat(250);
  assert.strictEqual(lv.pick(st({ last_read_text: long.slice(0, 200) }), msg({ text: long }), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_text: '  deploy it?\n' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_message_id: '100', last_read_text: 'other' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_text: 'other' }), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(st({ last_read_text: '' }), msg({ text: '' }), NOW), '📨'); // an empty text never counts as read
});

test('no target: null', () => { assert.strictEqual(lv.pick(st(), null, NOW), null); });

test('❓ reply lines', () => {
  assert.strictEqual(lv.replyLine(st({ state: 'busy', since: iso(NOW - 386000), tool: 'Bash: npm test', queued: 2 }), NOW), 'busy 6m26s: Bash: npm test; 2 message(s) queued');
  assert.strictEqual(lv.replyLine(st({ state: 'busy', since: iso(NOW - 42000) }), NOW), 'busy 42s; 0 message(s) queued');
  assert.strictEqual(lv.replyLine(st({ state: 'ready', since: '2026-11-24T21:40:00Z' }), NOW), 'ready since 21:40');
  assert.strictEqual(lv.replyLine(st({ state: 'needs_you' }), NOW), 'needs you: a dialog is waiting in claude');
  assert.strictEqual(lv.replyLine(st({ state: 'down', reason: 'bot not held', since: '2026-11-24T20:05:00Z' }), NOW), 'down: bot not held since 20:05');
  assert.strictEqual(lv.replyLine(null, NOW), 'no lead state (board not running?)');
  assert.strictEqual(lv.replyLine(st({ at: iso(NOW - 181000) }), NOW), 'no lead state (board not running?)');
});

test('dur', () => { assert.deepStrictEqual([0, 59999, 60000, 3600000, 3900000].map(lv.dur), ['0s', '59s', '1m00s', '1h00m', '1h05m']); });

test('readState: missing, garbage and an array are null; an object is returned', () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'lv-'));
  const f = path.join(d, 'lead-state.json');
  assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, 'nope'); assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, '[1]'); assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, JSON.stringify(st())); assert.strictEqual(lv.readState(f).state, 'ready');
});
