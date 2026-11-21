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
  assert.deepStrictEqual(state.read(d), { card_message_id: null, threads: {}, guild_id: null, connected: false, prompts: {}, posts: {}, approvals: {}, dialogs: {}, reply_armed: {} });
  state.write(d, { card_message_id: 'm1', threads: { k: 't1' }, guild_id: 'G', connected: true }, 123);
  const s = JSON.parse(fs.readFileSync(path.join(d, 'bridge-state.json'), 'utf8'));
  assert.strictEqual(s.card_message_id, 'm1'); assert.strictEqual(s.ts, 123);
  assert.ok(!fs.existsSync(path.join(d, 'bridge-state.json.tmp')));
});

// Post ops through the real bridge tick, on the fake client (a plain home-channel bridge, as in bridge.test.js).
const { createBridge } = require('../bridge');
const { FakeClient } = require('./fake-client');

function postSetup() {
  const dir = tmp();
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc123.SECRETSECRETSECRET\n');
  const client = new FakeClient({ guildId: 'G1' });
  const bridge = createBridge({ dir, client, ops: false, log: () => {}, now: () => 1700000000000, sleep: async () => {} });
  const put = (name, op) => fs.writeFileSync(path.join(dir, 'outbox', name), JSON.stringify(op));
  return { dir, client, bridge, put };
}
const postOp = (extra) => ({ op: 'post', text: 'group', tier: 'progress', mention_user: false, ...extra });
const btn = (n, style = 1) => ({ label: `Item ${n}`, style, custom_id: `ab:discover:file:proj:k${n}` });

test('post with rows sends toRows(rows): one action row per row, a button per entry', async () => {
  const s = postSetup();
  const rows = [[btn(1), btn(2, 2)], [btn(3)]];
  s.put('1700000000001-00000001.json', postOp({ rows }));
  await s.bridge.tick();
  const [c] = s.client.callsOf('send');
  assert.deepStrictEqual(c.payload.components, [
    { type: 1, components: [{ type: 2, style: 1, label: 'Item 1', custom_id: 'ab:discover:file:proj:k1' }, { type: 2, style: 2, label: 'Item 2', custom_id: 'ab:discover:file:proj:k2' }] },
    { type: 1, components: [{ type: 2, style: 1, label: 'Item 3', custom_id: 'ab:discover:file:proj:k3' }] },
  ]);
});

test('post with buttons still sends one action row', async () => {
  const s = postSetup();
  s.put('1700000000002-00000002.json', postOp({ buttons: [btn(1), btn(2, 2)] }));
  await s.bridge.tick();
  const [c] = s.client.callsOf('send');
  assert.deepStrictEqual(c.payload.components, [{ type: 1, components: [
    { type: 2, style: 1, label: 'Item 1', custom_id: 'ab:discover:file:proj:k1' },
    { type: 2, style: 2, label: 'Item 2', custom_id: 'ab:discover:file:proj:k2' }] }]);
});

test('post with rows and a select: the select row comes after the button rows', async () => {
  const s = postSetup();
  const select = { custom_id: 'ab:ops:spec:alpha', placeholder: 'Pick', options: [{ label: 'three', value: '3' }] };
  s.put('1700000000003-00000003.json', postOp({ rows: [[btn(1)], [btn(2)]], select }));
  await s.bridge.tick();
  const [c] = s.client.callsOf('send');
  assert.strictEqual(c.payload.components.length, 3);
  assert.deepStrictEqual(c.payload.components[2], { type: 1, components: [{ type: 3, custom_id: 'ab:ops:spec:alpha', placeholder: 'Pick', options: select.options }] });
  assert.deepStrictEqual(c.payload.components.slice(0, 2).map((r) => r.components[0].custom_id), ['ab:discover:file:proj:k1', 'ab:discover:file:proj:k2']);
});
