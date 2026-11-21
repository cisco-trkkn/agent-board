'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const { FakeClient, fakeInteraction, fakeReply } = require('./fake-client');

let seq = 0;
function setup() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dbs-'));
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc123.SECRETSECRETSECRET\n');
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: 1700000000000 };
  const bridge = createBridge({ dir, client, ops: false, log: () => {}, now: () => clock.t, sleep: async (ms) => { clock.t += ms; } });
  const put = (op) => fs.writeFileSync(path.join(dir, 'outbox', `${String(1700000000000 + ++seq).padStart(13, '0')}-${String(seq).padStart(8, '0')}.json`), JSON.stringify(op));
  const st = () => { try { return JSON.parse(fs.readFileSync(path.join(dir, 'bridge-state.json'), 'utf8')); } catch { return { reply_armed: {} }; } };   // no file = nothing ever saved
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  return { bridge, put, st, events, client };
}
const WEEK = '2026-w47';
const REJECT = 'ab:scout:reject:agent-board:abc123';
const REVISE = 'ab:scout:revise:agent-board:abc123';
const click = (s, id, messageId = 'm1') => s.bridge.onInteraction(fakeInteraction({ customId: id, user: 'U1', messageId }));

test('scout reject click then a reply: one reply event keyed by the custom id, then disarmed', async () => {
  // Mutation: drop the arm in onInteraction -> the reply writes no event.
  const s = setup();
  await click(s, REJECT);
  assert.deepStrictEqual(s.st().reply_armed, { m1: REJECT });
  await s.bridge.onMessage(fakeReply({ id: 'r1', content: ' too noisy ', ref: 'm1' }));
  const reps = s.events().filter((e) => e.type === 'reply');
  assert.strictEqual(reps.length, 1);
  assert.deepStrictEqual([reps[0].key, reps[0].text, reps[0].user, reps[0].message_id], [REJECT, 'too noisy', 'U1', 'm1']);
  assert.deepStrictEqual(s.st().reply_armed, {});
});

test('a reply with no click writes no event', async () => {
  const s = setup();
  await s.bridge.onMessage(fakeReply({ id: 'r1', content: 'hello', ref: 'm1' }));
  assert.deepStrictEqual(s.events(), []);
});

test('an approve click does not arm the message', async () => {
  // Mutation: widen the regex to any ab:scout: id -> approve arms.
  const s = setup();
  await click(s, 'ab:scout:approve:agent-board:abc123');
  assert.strictEqual(s.events().length, 1);
  assert.deepStrictEqual(s.st().reply_armed, {});
  await s.bridge.onMessage(fakeReply({ id: 'r1', content: 'x', ref: 'm1' }));
  assert.strictEqual(s.events().filter((e) => e.type === 'reply').length, 0);
});

test('a later revise click on the same message replaces the key', async () => {
  const s = setup();
  await click(s, REJECT);
  await click(s, REVISE);
  assert.deepStrictEqual(s.st().reply_armed, { m1: REVISE });
  await s.bridge.onMessage(fakeReply({ id: 'r1', content: 'shorter', ref: 'm1' }));
  assert.strictEqual(s.events().find((e) => e.type === 'reply').key, REVISE);
});

test('an unauthorised scout click does not arm', async () => {
  const s = setup();
  await s.bridge.onInteraction(fakeInteraction({ customId: REJECT, user: 'U9', messageId: 'm1' }));
  assert.deepStrictEqual(s.st().reply_armed, {});
});

test('an edit of the scout digest post keeps the scout arm', async () => {
  // Mutation: make opEdit clear arms by message instead of by value -> the reply is lost.
  const s = setup();
  s.put({ op: 'post', key: `scout-agent-board-${WEEK}`, text: 'digest', tier: 'progress', mention_user: false });
  await s.bridge.tick();
  const mid = 'm1';
  await click(s, REJECT, mid);
  s.put({ op: 'edit', key: `scout-agent-board-${WEEK}`, text: 'digest, updated' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.st().reply_armed, { [mid]: REJECT });
  await s.bridge.onMessage(fakeReply({ id: 'r1', content: 'still here', ref: mid }));
  assert.strictEqual(s.events().filter((e) => e.type === 'reply').length, 1);
});
