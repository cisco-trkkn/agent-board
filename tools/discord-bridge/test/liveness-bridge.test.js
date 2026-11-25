'use strict';
// Lead liveness in the bridge (spec 2026-11-23-remote-lead-liveness §2, plan Task 4): the newest allowlisted home-channel
// message is the target; every 10 s the bridge swaps ONE bot reaction on it through its own outbox. Fake client, fake clock.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const { FakeClient, fakeMessage } = require('./fake-client');

const T0 = Date.parse('2026-11-24T21:00:00Z');
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

function setup({ ops = false, heartbeat } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbl-'));
  const dir = path.join(root, 'discord', 'proj');
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1' }));
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc.SECRET\n');
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: T0 };
  const logs = [];
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => clock.t, sleep: async () => {}, ...(heartbeat ? { heartbeat } : {}) });
  const leadState = (obj) => fs.writeFileSync(path.join(dir, 'lead-state.json'), JSON.stringify({
    at: iso(clock.t), state: 'ready', since: iso(clock.t), tool: null, queued: 0, last_read_text: null, last_read_message_id: null, holder: true, reason: null, window: 'claude', ...obj,
  }));
  // A message as the gateway delivers it, also fetchable from the home channel.
  const msg = (id, o = {}) => {
    const m = fakeMessage({ id, authorId: 'U1', content: `text ${id}`, createdTimestamp: T0 + Number(id), ...o });
    client.messages.set(id, m);
    return m;
  };
  const tick = async () => { await bridge.tick(); };
  // the first tick evaluates and enqueues, the second one runs the op; the 10 s throttle skips an evaluation in between
  const settle = async () => { clock.t += 10000; await tick(); await tick(); };
  const lastFile = () => JSON.parse(fs.readFileSync(path.join(dir, 'last-user-message.json'), 'utf8'));
  const ownSent = () => JSON.parse(fs.readFileSync(path.join(dir, 'bridge-state.json'), 'utf8')).own_sent || [];
  return { dir, client, clock, logs, bridge, leadState, msg, tick, settle, lastFile, ownSent };
}
const mine = (m) => [...m.reactions.cache.values()].filter((e) => e.me).map((e) => e.emoji.name);

test('an allowlisted home-channel message becomes the target, last-user-message.json is written, 📨 within two ticks', async () => {
  const s = setup();
  s.leadState({});
  const m = s.msg('1001');
  await s.bridge.onMessage(m);
  assert.deepStrictEqual(s.lastFile(), { ts: new Date(T0 + 1001).toISOString(), message_id: '1001' });
  await s.tick(); s.clock.t += 2000; await s.tick();
  assert.deepStrictEqual(mine(m), ['📨']);
});

test('each state shows after a state-file change, a swap removes the previous reaction', async () => {
  const s = setup();
  const m = s.msg('1001', { content: 'do it' });
  s.leadState({});
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['📨']);
  s.leadState({ state: 'busy', tool: 'Bash' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['⏳']);
  s.leadState({ state: 'busy', last_read_message_id: '1001' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['👀']);
  s.leadState({ state: 'needs_you' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['🙋']);
  // the lead's own reply: a bot message the bridge did not send, newer than the target
  await s.bridge.onMessage(fakeMessage({ id: '1500', authorId: 'BOT', authorBot: true }));
  s.leadState({ state: 'ready' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['✅']);
  s.leadState({ state: 'down', reason: 'no pane' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['⚠️']);
  const removed = m.unreacted.filter((u) => u.user === 'BOT').map((u) => u.emoji);
  assert.deepStrictEqual(removed, ['📨', '⏳', '👀', '🙋', '✅']);
});

test('stale at and a missing state file show ⚠️', async () => {
  const s = setup();
  const m = s.msg('1001');
  s.leadState({ at: iso(T0 - 181000) });
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['⚠️']);
  const s2 = setup();
  const m2 = s2.msg('1001');
  await s2.bridge.onMessage(m2); await s2.tick(); await s2.tick();
  assert.deepStrictEqual(mine(m2), ['⚠️']);
});

test('a lead-state.json captured from the real writer (busy) shows ⏳', async () => {
  const s = setup();
  // real `python3 board/lead_state.py --dry-run` output, `at` moved to the fake clock
  const real = { at: '2026-11-25T00:01:10Z', state: 'busy', since: '2026-11-25T00:01:10Z', tool: 'Bash: tmux-ctl wait-gone rerev2 impl2 >/dev/null; cat /Users/francisco.ruiz/agent-boar', queued: 0, last_read_text: null, last_read_message_id: null, holder: true, reason: null, window: 'claude' };
  fs.writeFileSync(path.join(s.dir, 'lead-state.json'), JSON.stringify({ ...real, at: iso(T0), since: iso(T0) }));
  const m = s.msg('1001');
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['⏳']);
});

test('unchanged state is a no-op: five ticks over 50 s make one react call', async () => {
  const s = setup();
  s.leadState({ state: 'busy' });
  const m = s.msg('1001');
  await s.bridge.onMessage(m);
  for (let i = 0; i < 5; i++) { await s.tick(); await s.tick(); s.clock.t += 10000; s.leadState({ state: 'busy' }); }
  assert.deepStrictEqual(m.reacted, ['⏳']);
  assert.deepStrictEqual(m.unreacted, []);
});

test('the state is read at most every 10 s: a change 2 s later is not seen, one 10 s later is', async () => {
  const s = setup();
  s.leadState({ state: 'busy' });
  const m = s.msg('1001');
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['⏳']);
  s.clock.t += 2000; s.leadState({ state: 'needs_you' }); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['⏳']);
  s.clock.t += 8000; s.leadState({ state: 'needs_you' }); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), ['🙋']);
});

test('a newer message moves the target and removes the old message\'s reaction', async () => {
  const s = setup();
  s.leadState({});
  const a = s.msg('1001'); const b = s.msg('1002');
  await s.bridge.onMessage(a); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(a), ['📨']);
  await s.bridge.onMessage(b); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(a), []);
  assert.deepStrictEqual(mine(b), ['📨']);
  assert.strictEqual(s.lastFile().message_id, '1002');
});

test('an older snowflake delivered late and a repeat of the current message change nothing', async () => {
  const s = setup();
  s.leadState({});
  const a = s.msg('1001'); const b = s.msg('1002');
  await s.bridge.onMessage(b); await s.tick(); await s.tick();
  const ino = fs.statSync(path.join(s.dir, 'last-user-message.json')).ino;
  await s.bridge.onMessage(a);
  await s.bridge.onMessage(b);
  assert.strictEqual(s.lastFile().message_id, '1002');
  assert.strictEqual(fs.statSync(path.join(s.dir, 'last-user-message.json')).ino, ino, 'no new file write');
  await s.tick(); await s.tick();
  assert.deepStrictEqual(b.reacted, ['📨'], 'no reset: the shown reaction is not re-added');
  assert.deepStrictEqual(a.reacted, []);
});

test('the plugin\'s own 👀 ack stays: the bridge adds nothing and a later swap does not remove it', async () => {
  const s = setup();
  s.leadState({ state: 'busy' });
  const m = s.msg('1001', { hasEyes: true });
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(m.reacted, ['⏳']);        // ⏳ first; 👀 is not wanted yet
  s.leadState({ state: 'busy', last_read_message_id: '1001' }); await s.settle();
  assert.deepStrictEqual(m.reacted, ['⏳'], 'nothing added for 👀: the plugin\'s is already there');
  await s.bridge.onMessage(fakeMessage({ id: '1500', authorId: 'BOT', authorBot: true }));
  s.leadState({ state: 'ready' }); await s.settle();
  assert.deepStrictEqual(m.reacted, ['⏳', '✅']);
  assert.ok(!m.unreacted.some((u) => u.emoji === '👀'), 'the plugin 👀 is never removed');
  assert.ok(mine(m).includes('👀'));
});

test('the bridge\'s own post is not the lead\'s answer; neither is an interaction response', async () => {
  const s = setup();
  s.leadState({ state: 'busy' });
  const m = s.msg('1001');
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  fs.writeFileSync(path.join(s.dir, 'outbox', '1700000000001-aaaaaaaa.json'), JSON.stringify({ op: 'post', text: 'board says hi', tier: 'progress', mention_user: false }));
  await s.tick();
  const own = [...s.client.messages.values()].find((x) => x.content === 'board says hi');
  assert.ok(own, 'the post was sent');
  assert.ok(s.ownSent().includes(own.id));
  own.createdTimestamp = T0 + 5000;
  await s.bridge.onMessage(own);
  await s.bridge.onMessage(fakeMessage({ id: '1600', authorId: 'BOT', authorBot: true, interactionMetadata: { id: 'x' } }));
  const legacy = fakeMessage({ id: '1601', authorId: 'BOT', authorBot: true }); legacy.interaction = { id: 'y' };
  await s.bridge.onMessage(legacy);
  s.leadState({ state: 'busy' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['⏳']);
});

test('a watch post (board down) after the target leaves the target at its non-✅ reaction', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dblw-'));
  const hb = path.join(root, 'heartbeat');
  const s = setup({ heartbeat: hb });
  const beat = (at) => fs.writeFileSync(hb, JSON.stringify({ at: iso(at), queue: ['proj'] }));
  s.leadState({ state: 'busy' });
  const m = s.msg('1001');
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  beat(s.clock.t); await s.bridge.watchTick();
  s.clock.t += 6 * 60 * 1000; s.leadState({ state: 'busy' });
  const text = await s.bridge.watchTick();
  assert.match(String(text), /board down/);
  const post = [...s.client.messages.values()].find((x) => String(x.content).includes('board down'));
  assert.ok(post && s.ownSent().includes(post.id), 'the watch post is recorded as the bridge\'s own');
  post.createdTimestamp = s.clock.t;
  await s.bridge.onMessage(post);
  await s.settle();
  assert.deepStrictEqual(mine(m), ['⏳']);
});

test('not tracked: a non-allowlisted author, another channel, a thread of the home channel, ops mode', async () => {
  const s = setup();
  s.leadState({});
  await s.bridge.onMessage(s.msg('1001', { authorId: 'U9' }));
  await s.bridge.onMessage(s.msg('1002', { channelId: 'C2' }));
  await s.bridge.onMessage(s.msg('1003', { channelId: 'T1', parentId: 'C1' }));
  await s.tick(); await s.tick();
  assert.ok(!fs.existsSync(path.join(s.dir, 'last-user-message.json')));
  assert.deepStrictEqual(s.client.callsOf('react'), []);
  const o = setup({ ops: true });
  o.leadState({});
  fs.writeFileSync(path.join(o.dir, 'bridge.json'), JSON.stringify({ channel: 'C1', command_center: 'C1' }));
  await o.bridge.onMessage(o.msg('1001')); await o.tick(); await o.tick();
  assert.ok(!fs.existsSync(path.join(o.dir, 'last-user-message.json')));
});

test('a rejected react leaves the shown state unchanged and the next evaluation enqueues again', async () => {
  const s = setup();
  s.leadState({ state: 'busy' });
  const m = s.msg('1001');
  m.failReact = 1;
  await s.bridge.onMessage(m); await s.tick(); await s.tick();
  assert.deepStrictEqual(mine(m), []);
  assert.deepStrictEqual(m.reacted, []);
  s.leadState({ state: 'busy' }); await s.settle();
  assert.deepStrictEqual(mine(m), ['⏳'], 'retried at the next evaluation');
});

test('the bridge\'s own home-channel sends are recorded in own_sent (card, post, dialog, edit reply, ireply fallback), capped at 200', async () => {
  const s = setup();
  s.leadState({});
  const put = (n, op) => fs.writeFileSync(path.join(s.dir, 'outbox', `17000000000${n}-aaaaaaa${n}.json`), JSON.stringify(op));
  put(10, { op: 'card', text: 'card' });
  put(11, { op: 'post', text: 'p', key: 'k1', tier: 'progress' });
  put(12, { op: 'dialog', key: 'd1', text: 'd', rows: [] });
  put(13, { op: 'edit', key: 'k1', text: 'p2', reply: 'edited' });
  put(14, { op: 'ireply', iid: 'nope', content: 'fallback' });
  await s.tick();
  const byText = (t) => [...s.client.messages.values()].find((x) => x.content === t || x.payload?.content === t);
  for (const t of ['card', 'p2', 'd', 'edited', 'fallback']) {
    const m = byText(t);
    assert.ok(m, `${t} was sent`);
    assert.ok(s.ownSent().includes(m.id), `${t} is in own_sent`);
  }
  for (let i = 0; i < 210; i++) {
    fs.writeFileSync(path.join(s.dir, 'outbox', `170000001${String(i).padStart(4, '0')}-bbbb${String(i).padStart(4, '0')}.json`), JSON.stringify({ op: 'post', text: `n${i}`, tier: 'progress' }));
  }
  await s.tick();
  assert.strictEqual(s.ownSent().length, 200);
});

test('guard: every home-channel send goes through the one noteOwn helper', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'bridge.js'), 'utf8');
  // a new `.send(` / message `.reply(` site must be routed through sendOwn/noteOwn, not written raw; interaction replies (`i.reply(`) are not channel sends
  assert.strictEqual((src.match(/\.send\(/g) || []).length, 1, 'only sendOwn calls .send(');
  assert.strictEqual((src.match(/(?<!\bi)\.reply\(/g) || []).length, 1, 'only opEdit calls a message .reply(, wrapped in noteOwn');
  assert.match(src, /noteOwn\(await msg\.reply\(/);
});

test('an outbox liveness op with unreact removes the named user\'s reaction', async () => {
  const s = setup();
  s.leadState({});
  const m = s.msg('1001');
  m.reactions.cache.set('❓', { emoji: { name: '❓' }, me: false, users: { remove: async (u) => { m.unreacted.push({ emoji: '❓', user: u }); } } });
  fs.writeFileSync(path.join(s.dir, 'outbox', '1700000000001-cccccccc.json'), JSON.stringify({ op: 'liveness', message_id: '1001', add: null, remove: null, unreact: { emoji: '❓', user: 'U1' } }));
  await s.tick();
  assert.deepStrictEqual(m.unreacted, [{ emoji: '❓', user: 'U1' }]);
});
