'use strict';
// Night watch, board down (spec docs/superpowers/specs/2026-11-23-night-watch-design.md §5): lib/watch.js and the
// bridge's watchTick on a fake client. Every heartbeat lives in a temp dir; nothing reads the real state dir.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const watch = require('../lib/watch');
const { createBridge } = require('../bridge');
const { FakeClient } = require('./fake-client');

const T0 = Date.parse('2026-11-24T01:00:00Z');
const MIN = 60 * 1000;

function setup({ project = 'proj' } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbw-'));
  const dir = path.join(root, 'discord', project);
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc.SECRET\n');
  const hbFile = path.join(root, 'state', 'watch', 'heartbeat');
  fs.mkdirSync(path.dirname(hbFile), { recursive: true });
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: T0 };
  const bridge = createBridge({ dir, client, log: () => {}, now: () => clock.t, sleep: async () => {}, heartbeat: hbFile });
  const beat = (atMs, queue) => fs.writeFileSync(hbFile, JSON.stringify({ at: new Date(atMs).toISOString().replace(/\.\d{3}Z$/, 'Z'), queue }));
  const sent = () => client.callsOf('send').map((c) => c.payload.content);
  return { dir, client, clock, bridge, beat, sent, hbFile };
}

test('decide: stale heartbeat while armed posts down once, fresh again posts back once', () => {
  const hb = (atMs, queue) => ({ at: atMs, atText: new Date(atMs).toISOString(), queue });
  let r = watch.decide(null, hb(T0, ['proj']), 'proj', T0 + MIN);
  assert.strictEqual(r.text, null);
  // mutation: compare with >= STALE_MS instead of > -> the 5-minute case posts, this fails
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + watch.STALE_MS);
  assert.strictEqual(r.text, null);
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + watch.STALE_MS + 1);
  assert.match(r.text, /^⚠️ proj: board down, night watch off \(last heartbeat 2026-11-24T01:00:00.000Z\)$/);
  // mutation: drop the !st.down check -> a second down post, this fails
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + 20 * MIN);
  assert.strictEqual(r.text, null);
  r = watch.decide(r.next, hb(T0 + 21 * MIN, ['proj']), 'proj', T0 + 21 * MIN);
  assert.strictEqual(r.text, 'proj: board back, night watch on');
  r = watch.decide(r.next, hb(T0 + 22 * MIN, ['proj']), 'proj', T0 + 22 * MIN);
  assert.strictEqual(r.text, null);
});

test('decide: a project not in queue mode in the last heartbeat gets nothing', () => {
  // mutation: drop the st.armed check -> a down post, this fails
  const r = watch.decide(null, { at: T0, atText: 'x', queue: ['other'] }, 'proj', T0 + 60 * MIN);
  assert.strictEqual(r.text, null);
});

test('decide: a heartbeat file that disappears after one was read counts as stale', () => {
  let r = watch.decide(null, { at: T0, atText: '2026-11-24T01:00:00Z', queue: ['proj'] }, 'proj', T0);
  r = watch.decide(r.next, null, 'proj', T0 + 10 * MIN);
  assert.match(r.text, /board down, night watch off \(last heartbeat 2026-11-24T01:00:00Z\)/);
});

test('stateDir follows TC_STATE, else TMPDIR/tmux-ctl-<uid>', () => {
  assert.strictEqual(watch.stateDir({ TC_STATE: '/x/s' }), '/x/s');
  assert.strictEqual(watch.stateDir({ TMPDIR: '/var/t/' }), `/var/t/tmux-ctl-${os.userInfo().uid}`);
  assert.strictEqual(watch.heartbeatFile({ TC_STATE: '/x/s' }), '/x/s/watch/heartbeat');
});

test('watchTick: stale heartbeat in queue mode -> one down post in the home channel; fresh -> one back post', async () => {
  const s = setup();
  s.beat(T0, ['proj']);
  assert.strictEqual(await s.bridge.watchTick(), null);
  s.clock.t = T0 + 6 * MIN;
  await s.bridge.watchTick();
  s.clock.t = T0 + 7 * MIN;
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent(), ['<@U1> ⚠️ proj: board down, night watch off (last heartbeat 2026-11-24T01:00:00Z)']);
  assert.strictEqual(s.client.callsOf('send')[0].target, 'C1');
  s.beat(s.clock.t, ['proj']);
  await s.bridge.watchTick();
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent().slice(1), ['proj: board back, night watch on']);
});

test('watchTick: queue mode off -> nothing, however old the heartbeat', async () => {
  const s = setup();
  s.beat(T0, []);
  s.clock.t = T0 + 60 * MIN;
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent(), []);
});

test('watchTick: a restarted bridge does not repeat the down post', async () => {
  const s = setup();
  s.beat(T0, ['proj']);
  await s.bridge.watchTick();
  s.clock.t = T0 + 6 * MIN;
  await s.bridge.watchTick();
  // mutation: keep the state in memory only -> the second bridge posts again, this fails
  const again = createBridge({ dir: s.dir, client: s.client, log: () => {}, now: () => s.clock.t, sleep: async () => {}, heartbeat: s.hbFile });
  await again.watchTick();
  assert.strictEqual(s.sent().length, 1);
});

test('watchTick: an ops bridge never checks', async () => {
  const s = setup();
  const ops = createBridge({ dir: s.dir, client: s.client, ops: true, log: () => {}, now: () => T0 + 60 * MIN, heartbeat: s.hbFile });
  s.beat(T0, ['proj']);
  assert.strictEqual(await ops.watchTick(), null);
  assert.deepStrictEqual(s.sent(), []);
});

test('watchTick: a tick while the previous send is still pending does nothing', async () => {
  const s = setup();
  s.beat(T0, ['proj']);
  await s.bridge.watchTick();
  s.clock.t = T0 + 6 * MIN;
  let release;
  const gate = new Promise((r) => { release = r; });
  const fetch = s.client.channels.fetch;
  s.client.channels.fetch = async (id) => { const ch = await fetch(id); const send = ch.send; return { ...ch, send: async (p) => { await gate; return send(p); } }; };
  const first = s.bridge.watchTick();
  // mutation: drop the watching guard -> the second tick also decides "down" and queues a send, this fails
  assert.strictEqual(await s.bridge.watchTick(), null);
  release();
  assert.match(await first, /board down/);
  assert.strictEqual(s.sent().length, 1);
});
