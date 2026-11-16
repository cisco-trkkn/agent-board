'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const { FakeClient, fakeInteraction } = require('./fake-client');

const TOKEN = 'TESTTOKEN.abc123.SECRETSECRETSECRET';
let seq = 0;

function setup({ t0 = 1700000000000 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dbb-'));
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), `DISCORD_BOT_TOKEN=${TOKEN}\n`);
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: t0 };
  const sleeps = [];
  const logs = [];
  const bridge = createBridge({
    dir, client, log: (l) => logs.push(l), now: () => clock.t,
    sleep: async (ms) => { sleeps.push(ms); clock.t += ms; },
  });
  const put = (op) => {
    const name = `${String(1700000000000 + ++seq).padStart(13, '0')}-${String(seq).padStart(8, '0')}.json`;
    fs.writeFileSync(path.join(dir, 'outbox', name), typeof op === 'string' ? op : JSON.stringify(op));
    return name;
  };
  const files = () => fs.readdirSync(path.join(dir, 'outbox')).filter((n) => n.endsWith('.json')).sort();
  const failed = () => { try { return fs.readdirSync(path.join(dir, 'outbox', 'failed')).sort(); } catch { return []; } };
  const st = () => JSON.parse(fs.readFileSync(path.join(dir, 'bridge-state.json'), 'utf8'));
  return { dir, client, clock, sleeps, logs, bridge, put, files, failed, st };
}
const post = (text, extra = {}) => ({ op: 'post', text, tier: 'progress', mention_user: false, ...extra });

test('outbox files are sent in name order', async () => {
  const s = setup();
  s.put(post('one')); s.put(post('two')); s.put(post('three'));
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('send').map((c) => c.payload.content), ['one', 'two', 'three']);
  assert.deepStrictEqual(s.files(), []);
});

test('a file is deleted only after success', async () => {
  // Mutation: delete before send -> the file is gone while send is still pending.
  const s = setup();
  s.put(post('one'));
  let seenDuringSend;
  const ch = await s.client.channels.fetch('C1');
  const orig = ch.send;
  ch.send = async (p) => { seenDuringSend = s.files().length; return orig(p); };
  await s.bridge.tick();
  assert.strictEqual(seenDuringSend, 1);
  assert.deepStrictEqual(s.files(), []);
});

test('4xx moves the file to failed/ with an .err of status and message; later files still go', async () => {
  const s = setup();
  const n = s.put(post('bad')); s.put(post('good'));
  s.client.failNext('send', { status: 403, message: 'Missing Access' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.failed().sort(), [n, `${n}.err`].sort());
  const err = fs.readFileSync(path.join(s.dir, 'outbox', 'failed', `${n}.err`), 'utf8');
  assert.match(err, /403/); assert.match(err, /Missing Access/);
  assert.deepStrictEqual(s.client.callsOf('send').slice(-1)[0].payload.content, 'good');
});

test('5xx/network retries with backoff 1s,2s and keeps order', async () => {
  const s = setup();
  s.put(post('first')); s.put(post('second'));
  s.client.failNext('send', { status: 502 });
  s.client.failNext('send', {}); // network error: no status
  await s.bridge.tick();
  assert.deepStrictEqual(s.sleeps, [1000, 2000]);
  const sent = s.client.callsOf('send').map((c) => c.payload.content);
  assert.deepStrictEqual(sent, ['first', 'first', 'first', 'second']);
  assert.deepStrictEqual(s.files(), []);
});

test('backoff doubles and caps at 60s', async () => {
  const s = setup();
  s.put(post('x'));
  s.client.failNext('send', { status: 500 }, 9);
  await s.bridge.tick();
  assert.deepStrictEqual(s.sleeps, [1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000]);
});

test('a non-network error without a status goes to failed/ and later files still go', async () => {
  const s = setup();
  const n = s.put(post('bug')); s.put(post('after'));
  s.client.failNext('send', { plain: true, message: 'ENOENT: no such file' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.sleeps, []);
  assert.ok(s.failed().includes(n));
  assert.strictEqual(s.client.callsOf('send').slice(-1)[0].payload.content, 'after');
});

test('retryable: 429, 503 and each named network code retry; ENOENT code does not', async () => {
  for (const f of [{ status: 429 }, { status: 503 }, { code: 'ETIMEDOUT' }, { code: 'ENOTFOUND' }, { code: 'EAI_AGAIN' }, { code: 'ECONNREFUSED' }, { code: 'UND_ERR_SOCKET' }, { plain: true, message: 'socket hang up' }]) {
    const s = setup(); const n = s.put(post('x')); s.client.failNext('send', f);
    await s.bridge.tick();
    assert.deepStrictEqual(s.sleeps, [1000], JSON.stringify(f)); assert.deepStrictEqual(s.files(), [], n);
  }
  const s = setup(); s.put(post('x')); s.client.failNext('send', { code: 'ENOENT' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.sleeps, []); assert.strictEqual(s.failed().length, 2);
});

test('a missing bridge.json channel fails the op instead of retrying forever', async () => {
  const s = setup();
  fs.writeFileSync(path.join(s.dir, 'bridge.json'), '{}');
  s.put(post('x'));
  await s.bridge.tick();
  assert.deepStrictEqual(s.sleeps, []);
  assert.strictEqual(s.failed().length, 2);
});

test('an unparsable file goes to failed/', async () => {
  const s = setup();
  const n = s.put('{not json'); s.put(post('after'));
  await s.bridge.tick();
  assert.ok(s.failed().includes(n));
  assert.strictEqual(s.client.callsOf('send').length, 1);
});

test('card: first op creates, pins, records id; later ops edit', async () => {
  const s = setup();
  s.put({ op: 'card', text: 'v1' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('send')[0].target, 'C1');
  assert.strictEqual(s.client.callsOf('send')[0].payload.content, 'v1');
  assert.strictEqual(s.client.callsOf('pin').length, 1);
  const id = s.st().card_message_id; assert.ok(id);
  s.clock.t += 31000;
  s.put({ op: 'card', text: 'v2' });
  await s.bridge.tick();
  const edits = s.client.callsOf('edit');
  assert.strictEqual(edits.length, 1); assert.strictEqual(edits[0].target, id);
  assert.strictEqual(edits[0].payload.content, 'v2');
});

test('card: Unknown Message (10008) on edit creates and pins a new card', async () => {
  const s = setup();
  s.put({ op: 'card', text: 'v1' }); await s.bridge.tick();
  const old = s.st().card_message_id;
  s.clock.t += 31000;
  s.put({ op: 'card', text: 'v2' });
  s.client.failNext('edit', { status: 404, code: 10008 });
  await s.bridge.tick();
  assert.notStrictEqual(s.st().card_message_id, old);
  assert.strictEqual(s.client.callsOf('pin').length, 2);
  assert.strictEqual(s.client.callsOf('send').slice(-1)[0].payload.content, 'v2');
  assert.deepStrictEqual(s.files(), []);
});

test('card: two ops within 30s send one edit with the later text', async () => {
  // Mutation: remove the throttle -> two edits.
  const s = setup();
  s.put({ op: 'card', text: 'v1' }); await s.bridge.tick();
  s.clock.t += 5000; s.put({ op: 'card', text: 'v2' }); await s.bridge.tick();
  s.clock.t += 5000; s.put({ op: 'card', text: 'v3' }); await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('edit').length, 0);
  s.clock.t += 31000; await s.bridge.tick();
  const edits = s.client.callsOf('edit');
  assert.strictEqual(edits.length, 1); assert.strictEqual(edits[0].payload.content, 'v3');
});

test('card: held card files stay in the outbox until the coalesced edit is accepted', async () => {
  // Mutation: delete a throttled card file at once -> files() is empty after the held ticks.
  const s = setup();
  s.put({ op: 'card', text: 'v1' }); await s.bridge.tick();
  s.clock.t += 5000; s.put({ op: 'card', text: 'v2' }); await s.bridge.tick();
  s.clock.t += 5000; s.put({ op: 'card', text: 'v3' }); await s.bridge.tick();
  assert.strictEqual(s.files().length, 2);
  s.clock.t += 31000; s.client.failNext('edit', { status: 500 });
  await s.bridge.tick(); // edit fails once, is retried, then accepted
  assert.strictEqual(s.client.callsOf('edit').length, 2);
  assert.deepStrictEqual(s.files(), []);
});

test('card: a held card whose edit gets a 4xx moves every held file to failed/', async () => {
  const s = setup();
  s.put({ op: 'card', text: 'v1' }); await s.bridge.tick();
  s.clock.t += 5000; s.put({ op: 'card', text: 'v2' }); await s.bridge.tick();
  s.clock.t += 31000; s.client.failNext('edit', { status: 403, message: 'Missing Permissions' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.files(), []);
  assert.strictEqual(s.failed().filter((n) => n.endsWith('.err')).length, 1);
});

test('threads: one per key; second op is a no-op; recorded in state', async () => {
  const s = setup();
  s.put({ op: 'thread', key: 'spec-a', title: 'Spec A' });
  s.put({ op: 'thread', key: 'spec-a', title: 'Spec A again' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('createThread').length, 1);
  assert.strictEqual(s.client.callsOf('createThread')[0].payload.name, 'Spec A');
  assert.ok(s.st().threads['spec-a']);
});

test('threads: post with thread_key goes to the thread; unknown key goes home with a suffix', async () => {
  const s = setup();
  s.put({ op: 'thread', key: 'k', title: 'K' });
  s.put(post('in thread', { thread_key: 'k' }));
  s.put(post('lost', { thread_key: 'nokey' }));
  await s.bridge.tick();
  const tid = s.st().threads.k;
  const sends = s.client.callsOf('send');
  assert.strictEqual(sends[0].target, tid); assert.strictEqual(sends[0].payload.content, 'in thread');
  assert.strictEqual(sends[1].target, 'C1'); assert.strictEqual(sends[1].payload.content, 'lost (thread nokey missing)');
});

test('threads: archive archives the thread', async () => {
  const s = setup();
  s.put({ op: 'thread', key: 'k', title: 'K' });
  s.put({ op: 'archive', key: 'k' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('setArchived').map((c) => [c.target, c.payload]), [[s.st().threads.k, true]]);
});

test('posts: mention_user prefixes the user and allows only that user', async () => {
  const s = setup();
  s.put(post('hey', { mention_user: true }));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  assert.strictEqual(p.content, '<@U1> hey');
  assert.deepStrictEqual(p.allowedMentions, { users: ['U1'] });
});

test('posts: no mention sets allowedMentions parse []', async () => {
  const s = setup();
  s.put(post('hey'));
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('send')[0].payload.allowedMentions, { parse: [] });
});

test('posts: link_thread_key appends the deep link; files attach', async () => {
  const s = setup();
  s.put({ op: 'thread', key: 'k', title: 'K' });
  s.put(post('see', { link_thread_key: 'k', files: ['/tmp/a.txt'] }));
  await s.bridge.tick();
  const tid = s.st().threads.k;
  const p = s.client.callsOf('send')[0].payload;
  assert.ok(p.content.endsWith(`https://discord.com/channels/G1/${tid}`), p.content);
  assert.deepStrictEqual(p.files, ['/tmp/a.txt']);
});

test('bridge-state: connected true on ready, false on disconnect, with guild_id, atomic', async () => {
  const s = setup();
  await s.bridge.onReady();
  assert.deepStrictEqual([s.st().connected, s.st().guild_id], [true, 'G1']);
  assert.ok(!fs.existsSync(path.join(s.dir, 'bridge-state.json.tmp')));
  s.bridge.onDisconnect();
  assert.strictEqual(s.st().connected, false);
});

test('interactions: ab: component is written to events/ and acked', async () => {
  const s = setup();
  const i = fakeInteraction({ customId: 'ab:approve:7', user: 'U1', messageId: 'm5', channelId: 'C1' });
  await s.bridge.onInteraction(i);
  const evs = fs.readdirSync(path.join(s.dir, 'events'));
  assert.strictEqual(evs.length, 1); assert.match(evs[0], /^\d{13}-[0-9a-f]{8}\.json$/);
  const e = JSON.parse(fs.readFileSync(path.join(s.dir, 'events', evs[0]), 'utf8'));
  assert.deepStrictEqual(e, { ts: s.clock.t, user: 'U1', custom_id: 'ab:approve:7', message_id: 'm5', channel_id: 'C1' });
  assert.strictEqual(i.deferred, 1);
});

test('interactions: other customId is ignored (no file, no reply)', async () => {
  // Mutation: drop the ab: prefix check -> a file and a deferUpdate appear.
  const s = setup();
  const i = fakeInteraction({ customId: 'other:1' });
  await s.bridge.onInteraction(i);
  assert.ok(!fs.existsSync(path.join(s.dir, 'events')) || fs.readdirSync(path.join(s.dir, 'events')).length === 0);
  assert.strictEqual(i.deferred, 0); assert.deepStrictEqual(i.replies, []);
});

test('messages are ignored: the bridge registers no message listener', () => {
  const s = setup();
  s.bridge.attach();
  assert.strictEqual(s.client.listenerCount('messageCreate'), 0);
  assert.strictEqual(s.client.listenerCount('interactionCreate'), 1);
});

test('log never holds the token or more than 80 chars of a body', async () => {
  const s = setup();
  const body = `${TOKEN} ` + 'abcdefghij'.repeat(20); // 200+ chars, token inside
  s.put(post(body));
  s.put(post('b'.repeat(200)));
  s.client.failNext('send', { status: 400, message: `bad ${TOKEN} ` + 'z'.repeat(200) });
  s.put(post('c'.repeat(200)));
  await s.bridge.tick();
  const all = s.logs.join('\n');
  assert.ok(!all.includes(TOKEN));
  assert.ok(!all.includes('SECRETSECRET'));
  assert.ok(!/[a-z]{81}/.test(all.replace(/\*\*\*/g, '')), 'a run of 81+ body chars is logged');
  assert.ok(all.length > 0);
});
