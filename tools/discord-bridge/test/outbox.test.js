'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const outbox = require('../lib/outbox');
const state = require('../lib/state');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'dbo-'));

test('list returns .json files in name order, skipping .tmp and failed/', () => {
  const d = tmp();
  const ob = path.join(d, 'outbox'); fs.mkdirSync(path.join(ob, 'failed'), { recursive: true });
  for (const n of ['1700000000002-bbbbbbbb.json', '1700000000001-aaaaaaaa.json', '1700000000003-cccccccc.json.tmp']) fs.writeFileSync(path.join(ob, n), '{}');
  assert.deepStrictEqual(outbox.list(d), ['1700000000001-aaaaaaaa.json', '1700000000002-bbbbbbbb.json']);
});

test('list on a missing outbox is empty', () => {
  assert.deepStrictEqual(outbox.list(path.join(tmp(), 'nope')), []);
});

test('read parses a file; an unparsable file throws', () => {
  const d = tmp(); const ob = path.join(d, 'outbox'); fs.mkdirSync(ob);
  fs.writeFileSync(path.join(ob, 'a.json'), '{"op":"card","text":"x"}');
  fs.writeFileSync(path.join(ob, 'b.json'), '{not json');
  assert.deepStrictEqual(outbox.read(d, 'a.json'), { op: 'card', text: 'x' });
  assert.throws(() => outbox.read(d, 'b.json'));
});

test('moveToFailed moves the file and writes <name>.err with the reason', () => {
  const d = tmp(); const ob = path.join(d, 'outbox'); fs.mkdirSync(ob);
  fs.writeFileSync(path.join(ob, 'a.json'), 'x');
  outbox.moveToFailed(d, 'a.json', 'status 403: Missing Access');
  assert.ok(!fs.existsSync(path.join(ob, 'a.json')));
  assert.ok(fs.existsSync(path.join(ob, 'failed', 'a.json')));
  assert.strictEqual(fs.readFileSync(path.join(ob, 'failed', 'a.json.err'), 'utf8').trim(), 'status 403: Missing Access');
});

test('state.write is atomic (tmp + rename) and state.read defaults when absent', () => {
  const d = tmp();
  assert.deepStrictEqual(state.read(d), { card_message_id: null, threads: {}, guild_id: null, connected: false, prompts: {}, posts: {}, approvals: {} });
  state.write(d, { card_message_id: 'm1', threads: { k: 't1' }, guild_id: 'G', connected: true }, 123);
  const s = JSON.parse(fs.readFileSync(path.join(d, 'bridge-state.json'), 'utf8'));
  assert.strictEqual(s.card_message_id, 'm1'); assert.strictEqual(s.ts, 123);
  assert.ok(!fs.existsSync(path.join(d, 'bridge-state.json.tmp')));
});
