'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const { FakeClient, fakeInteraction, fakeMessage, fakeReaction } = require('./fake-client');

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

test('a request timeout (AbortError/TimeoutError, on the error or its cause) is retried, not failed', async () => {
  for (const f of [{ plain: true, name: 'AbortError', message: 'This operation was aborted' }, { plain: true, name: 'TimeoutError', message: 'x' },
    { plain: true, message: 'boom', cause: Object.assign(new Error('c'), { name: 'AbortError' }) }]) {
    const s = setup(); s.put(post('x')); s.client.failNext('send', f);
    await s.bridge.tick();
    assert.deepStrictEqual(s.sleeps, [1000], JSON.stringify(f)); assert.deepStrictEqual(s.failed(), []);
  }
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
  const fd = fs.mkdtempSync(path.join(os.tmpdir(), 'dbf-'));
  const a = path.join(fd, 'a.txt'); const b = path.join(fd, 'b.txt');
  fs.writeFileSync(a, 'a'); fs.writeFileSync(b, 'b');
  s.put({ op: 'thread', key: 'k', title: 'K' });
  s.put(post('see', { link_thread_key: 'k', files: [a, b] }));
  await s.bridge.tick();
  const tid = s.st().threads.k;
  const p = s.client.callsOf('send')[0].payload;
  assert.ok(p.content.endsWith(`https://discord.com/channels/G1/${tid}`), p.content);
  assert.deepStrictEqual(p.files, [a, b]);
});

function mkfiles(names) {
  const fd = fs.mkdtempSync(path.join(os.tmpdir(), 'dbf-'));
  return names.map((n) => { const p = path.join(fd, n); fs.writeFileSync(p, n); return p; });
}

test('files: over 25 MB is not attached and the text names it', async () => {
  // Mutation: remove the size check -> big.bin is attached.
  const s = setup();
  const [ok] = mkfiles(['ok.txt']);
  const big = path.join(path.dirname(ok), 'big.bin');
  fs.writeFileSync(big, ''); fs.truncateSync(big, 26 * 1024 * 1024);
  s.put(post('hi', { files: [ok, big] }));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  assert.deepStrictEqual(p.files, [ok]);
  assert.ok(p.content.includes('big.bin too large (26.0 MB)'), p.content);
});

test('files: a missing path is dropped with a line and the op is still sent', async () => {
  const s = setup();
  const [ok] = mkfiles(['ok.txt']);
  s.put(post('hi', { files: [path.join(path.dirname(ok), 'gone.log'), ok] }));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  assert.deepStrictEqual(p.files, [ok]);
  assert.ok(p.content.includes('gone.log not found'), p.content);
  assert.deepStrictEqual(s.files(), []);
  assert.deepStrictEqual(s.failed(), []);
});

test('files: 12 files send the first 10 and a line for the rest', async () => {
  const s = setup();
  const all = mkfiles(Array.from({ length: 12 }, (_, i) => `f${i}.txt`));
  s.put(post('hi', { files: all }));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  assert.deepStrictEqual(p.files, all.slice(0, 10));
  assert.ok(p.content.includes('2 more files not sent (10 max)'), p.content);
});

test('files: content stays within 2000 chars with the added lines', async () => {
  const s = setup();
  const all = mkfiles(Array.from({ length: 12 }, (_, i) => `f${i}.txt`));
  s.put(post('x'.repeat(3000), { files: all }));
  await s.bridge.tick();
  assert.ok(s.client.callsOf('send')[0].payload.content.length <= 2000);
});

function tmpFile(s, name, sub = 'tmp') {
  const d = path.join(s.dir, sub); fs.mkdirSync(d, { recursive: true });
  const p = path.join(d, name); fs.writeFileSync(p, 'x'); return p;
}

test('delete_files removes a file under <dir>/tmp/ after a successful send', async () => {
  const s = setup();
  const p = tmpFile(s, 'snap.png');
  s.put(post('pic', { files: [p], delete_files: true }));
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('send').length, 1);
  assert.ok(!fs.existsSync(p));
});

test('delete_files keeps a file outside <dir>/tmp/ and logs it', async () => {
  // Mutation: remove the tmp/ containment check -> the outside file is deleted.
  const s = setup();
  const [out] = mkfiles(['keep.txt']);
  const sib = tmpFile(s, 'sib.txt', 'tmpx'); // prefix-sibling of tmp/
  s.put(post('pic', { files: [out, sib], delete_files: true }));
  await s.bridge.tick();
  assert.ok(fs.existsSync(out));
  assert.ok(fs.existsSync(sib));
  assert.ok(s.logs.some((l) => l.includes('kept') && l.includes(out)), s.logs.join('\n'));
});

test('delete_files keeps the tmp file when the send fails', async () => {
  const s = setup();
  const p = tmpFile(s, 'snap.png');
  s.client.failNext('send', { status: 400 });
  s.put(post('pic', { files: [p], delete_files: true }));
  await s.bridge.tick();
  assert.ok(fs.existsSync(p));
  assert.strictEqual(s.failed().length > 0, true);
});

test('bridge-state: connected true on ready, false on disconnect, with guild_id, atomic', async () => {
  const s = setup();
  await s.bridge.onReady();
  assert.deepStrictEqual([s.st().connected, s.st().guild_id], [true, 'G1']);
  assert.ok(!fs.existsSync(path.join(s.dir, 'bridge-state.json.tmp')));
  s.bridge.onDisconnect();
  assert.strictEqual(s.st().connected, false);
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

// ---- discord controls: prompt/edit ops, authorized clicks, reactions ----
const allow = (s, ids) => fs.writeFileSync(path.join(s.dir, 'access.json'), JSON.stringify({ allowFrom: ids }));
const events = (s) => { try { return fs.readdirSync(path.join(s.dir, 'events')).filter((n) => n.endsWith('.json')).sort(); } catch { return []; } };
const readEv = (s, n) => JSON.parse(fs.readFileSync(path.join(s.dir, 'events', n), 'utf8'));
const prompt = (lines, extra = {}) => ({ op: 'prompt', key: '%3:abc', window: 'w1', tool: 'Bash command', lines, tier: 'decision', mention_user: true, ...extra });

test('prompt op: one home send with mention, code block, Allow/Deny row; id kept in state', async () => {
  const s = setup();
  s.put(prompt(['echo a', 'echo b']));
  await s.bridge.tick();
  const sends = s.client.callsOf('send');
  assert.strictEqual(sends.length, 1);
  assert.strictEqual(sends[0].target, 'C1');
  const p = sends[0].payload;
  assert.ok(p.content.startsWith('<@U1> 🔐 w1 wants to run Bash command'));
  assert.ok(p.content.includes('```\necho a\necho b\n```'));
  assert.deepStrictEqual(p.allowedMentions, { users: ['U1'] });
  assert.deepStrictEqual(p.components, [{ type: 1, components: [
    { type: 2, style: 3, label: 'Allow once', custom_id: 'ab:perm:%3:abc:allow' },
    { type: 2, style: 4, label: 'Deny', custom_id: 'ab:perm:%3:abc:deny' },
  ] }]);
  assert.strictEqual(s.st().prompts['%3:abc'], 'm1');
  assert.deepStrictEqual(s.files(), []);
});

test('prompt over 1500 chars is cut on a line boundary, notes the rest, Deny only', async () => {
  const s = setup();
  const lines = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0').repeat(20));
  s.put(prompt(lines));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  const kept = Math.floor(1501 / 41); // 36 lines of 40 plus newlines: 36*41-1 = 1475 <= 1500
  assert.ok(p.content.includes(`… (${60 - kept} more lines)`), p.content);
  assert.ok(p.content.includes('Open on the board to see all of it.'));
  assert.ok(p.content.length <= 2000);
  const btns = p.components[0].components;
  assert.deepStrictEqual(btns.map((b) => b.label), ['Deny']);
  assert.ok(!p.content.includes(lines[kept]) || kept === 59);
});

test('a ``` inside a prompt line cannot close the block early', async () => {
  const s = setup();
  s.put(prompt(['echo ```hi```', 'next']));
  await s.bridge.tick();
  const c = s.client.callsOf('send')[0].payload.content;
  assert.strictEqual(c.split('```').length - 1, 2, c);
  assert.ok(c.includes('echo `​``hi`​``'));
});

test('edit op: fetches prompts[key], edits text and clears buttons', async () => {
  const s = setup();
  s.put(prompt(['x']));
  await s.bridge.tick();
  s.put({ op: 'edit', key: '%3:abc', text: '🔐 w1 wants to run Bash command: ⛔ denied' });
  await s.bridge.tick();
  const e = s.client.callsOf('edit');
  assert.strictEqual(e.length, 1);
  assert.deepStrictEqual(e[0].payload, { content: '🔐 w1 wants to run Bash command: ⛔ denied', components: [] });
  assert.deepStrictEqual(s.files(), []); assert.deepStrictEqual(s.failed(), []);
});

test('edit op with an unknown key is removed with a log line, not failed', async () => {
  const s = setup();
  s.put({ op: 'edit', key: 'nope', text: 't' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.files(), []); assert.deepStrictEqual(s.failed(), []);
  assert.ok(s.logs.some((l) => l.includes('edit nope: no message')));
  assert.strictEqual(s.client.callsOf('edit').length, 0);
});

test('edit op whose message is gone (10008) is removed with a log line, not failed', async () => {
  const s = setup();
  s.put(prompt(['x']));
  await s.bridge.tick();
  s.client.messages.get('m1').deleted = true;
  s.put({ op: 'edit', key: '%3:abc', text: 't' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.files(), []); assert.deepStrictEqual(s.failed(), []);
  assert.ok(s.logs.some((l) => l.includes('edit %3:abc: no message')));
});

test('prompts in state keep only the newest 200 by insertion', async () => {
  const s = setup();
  for (let i = 0; i < 202; i++) s.put(prompt(['x'], { key: `k${i}` }));
  await s.bridge.tick();
  const keys = Object.keys(s.st().prompts);
  assert.strictEqual(keys.length, 200);
  assert.ok(!keys.includes('k0') && !keys.includes('k1') && keys.includes('k201'));
});

test('state read defaults prompts to {} for old state files', () => {
  const s = setup();
  fs.writeFileSync(path.join(s.dir, 'bridge-state.json'), JSON.stringify({ card_message_id: 'm9', threads: {} }));
  const b = createBridge({ dir: s.dir, client: s.client, log: () => {} });
  return b.onReady().then(() => assert.deepStrictEqual(s.st().prompts, {}));
});

test('click by a user outside allowFrom: ephemeral reply, no defer, no event', async () => {
  // Mutation: drop the allowFrom check -> defer happens and an event is written.
  const s = setup();
  allow(s, ['U1']);
  const i = fakeInteraction({ customId: 'ab:perm:%3:abc:allow', user: 'U9' });
  await s.bridge.onInteraction(i);
  assert.deepStrictEqual(i.replies, [{ content: 'Not authorized.', flags: 64 }]);
  assert.strictEqual(i.deferred, 0);
  assert.deepStrictEqual(events(s), []);
});

test('click with a missing access.json: nobody is allowed', async () => {
  const s = setup();
  const i = fakeInteraction({ customId: 'ab:perm:k:allow', user: 'U1' });
  await s.bridge.onInteraction(i);
  assert.strictEqual(i.deferred, 0); assert.deepStrictEqual(events(s), []);
  assert.strictEqual(i.replies.length, 1);
});

test('allowlist is re-read on every click', async () => {
  const s = setup();
  allow(s, []);
  const i1 = fakeInteraction({ customId: 'ab:perm:k:allow', user: 'U1' });
  await s.bridge.onInteraction(i1);
  allow(s, ['U1']);
  const i2 = fakeInteraction({ customId: 'ab:perm:k:allow', user: 'U1' });
  await s.bridge.onInteraction(i2);
  assert.strictEqual(i1.deferred, 0); assert.strictEqual(i2.deferred, 1);
});

test('authorized perm click defers before the event file exists; event shape', async () => {
  // Mutation: write the event before deferUpdate -> events/ is not empty at defer time.
  const s = setup();
  allow(s, ['U1']);
  let atDefer;
  const i = fakeInteraction({ customId: 'ab:perm:%3:abc:allow', user: 'U1', messageId: 'm5', onDefer: () => { atDefer = events(s).length; } });
  await s.bridge.onInteraction(i);
  assert.strictEqual(atDefer, 0);
  assert.strictEqual(i.deferred, 1);
  const evs = events(s);
  assert.strictEqual(evs.length, 1); assert.match(evs[0], /^\d{13}-[0-9a-f]{8}\.json$/);
  assert.deepStrictEqual(readEv(s, evs[0]), { type: 'perm', key: '%3:abc', choice: 'allow', user: 'U1', message_id: 'm5', ts: s.clock.t });
  assert.deepStrictEqual(fs.readdirSync(path.join(s.dir, 'events')).filter((n) => n.endsWith('.tmp')), []);
});

test('deny click: choice deny', async () => {
  const s = setup();
  allow(s, ['U1']);
  await s.bridge.onInteraction(fakeInteraction({ customId: 'ab:perm:%3:abc:deny', user: 'U1' }));
  assert.strictEqual(readEv(s, events(s)[0]).choice, 'deny');
});

test('other ab: click becomes a click event', async () => {
  const s = setup();
  allow(s, ['U1']);
  const i = fakeInteraction({ customId: 'ab:approve:7', user: 'U1', messageId: 'm5', channelId: 'C1' });
  await s.bridge.onInteraction(i);
  assert.deepStrictEqual(readEv(s, events(s)[0]), { type: 'click', custom_id: 'ab:approve:7', user: 'U1', message_id: 'm5', channel_id: 'C1', ts: s.clock.t });
  assert.strictEqual(i.deferred, 1);
});

test('non-ab: id (plugin perm:x) does nothing at all', async () => {
  const s = setup();
  allow(s, ['U1']);
  const i = fakeInteraction({ customId: 'perm:x', user: 'U1' });
  await s.bridge.onInteraction(i);
  assert.strictEqual(i.deferred, 0); assert.deepStrictEqual(i.replies, []); assert.deepStrictEqual(events(s), []);
});

async function react(s, { emoji = '✅', user = { id: 'U1' }, msg = {}, reaction = {} } = {}) {
  const message = fakeMessage({ content: '  hello \n  world ', ...msg });
  const r = fakeReaction({ emoji, message, ...reaction });
  await s.bridge.onReaction(r, user);
  return message;
}

test('✅ by an allowlisted user on a bot message: react event with excerpt, bot adds 👀', async () => {
  const s = setup(); allow(s, ['U1']);
  const m = await react(s, { msg: { id: 'm7', content: 'x'.repeat(100) } });
  const evs = events(s);
  assert.strictEqual(evs.length, 1);
  assert.deepStrictEqual(readEv(s, evs[0]), { type: 'react', emoji: '✅', message_id: 'm7', excerpt: 'x'.repeat(80), user: 'U1', ts: s.clock.t });
  assert.deepStrictEqual(m.reacted, ['👀']);
});

test('excerpt collapses whitespace', async () => {
  const s = setup(); allow(s, ['U1']);
  await react(s);
  assert.strictEqual(readEv(s, events(s)[0]).excerpt, 'hello world');
});

test('▶️ and ▶ both give ▶️; ⏭ gives ⏭️; ❌ and 🛑 pass', async () => {
  const s = setup(); allow(s, ['U1']);
  for (const e of ['▶️', '▶', '⏭', '❌', '🛑']) await react(s, { emoji: e });
  const got = events(s).map((n) => readEv(s, n).emoji).sort();
  assert.deepStrictEqual(got, ['▶️', '▶️', '⏭️', '❌', '🛑'].sort());
});

for (const [name, opts] of [
  ['non-allowlisted user', { user: { id: 'U9' } }],
  ['a bot user', { user: { id: 'U1', bot: true } }],
  ['a message by another author', { msg: { authorId: 'OTHER' } }],
  ['a channel outside home', { msg: { channelId: 'C2' } }],
  ['a thread of another channel', { msg: { channelId: 'T9', parentId: 'C2' } }],
  ['an unknown emoji', { emoji: '👍' }],
]) {
  test(`reaction ignored: ${name}`, async () => {
    // Mutation (author case): drop the author check -> an event appears.
    const s = setup(); allow(s, ['U1']);
    const m = await react(s, opts);
    assert.deepStrictEqual(events(s), []); assert.deepStrictEqual(m.reacted, []);
  });
}

test('a message that already has the bot 👀 gets no second one', async () => {
  const s = setup(); allow(s, ['U1']);
  const m = await react(s, { msg: { hasEyes: true } });
  assert.strictEqual(events(s).length, 1); assert.deepStrictEqual(m.reacted, []);
});

test('a thread message whose parentId is home is accepted', async () => {
  const s = setup(); allow(s, ['U1']);
  await react(s, { msg: { channelId: 'T1', parentId: 'C1' } });
  assert.strictEqual(events(s).length, 1);
});

test('partial reaction and message are fetched before reading', async () => {
  const s = setup(); allow(s, ['U1']);
  const m = await react(s, { msg: { partial: true }, reaction: { partial: true } });
  assert.strictEqual(events(s).length, 1); assert.strictEqual(m.partial, false);
});

test('attach registers messageReactionAdd', () => {
  const s = setup();
  s.bridge.attach();
  assert.strictEqual(s.client.listenerCount('messageReactionAdd'), 1);
});

test('main builds the client with the four partials', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'bridge.js'), 'utf8');
  assert.match(src, /partials:\s*\[\s*Partials\.Message,\s*Partials\.Channel,\s*Partials\.Reaction,\s*Partials\.User\s*\]/);
});

test('runs of 4 and 6 backticks cannot close the block early', async () => {
  const s = setup();
  s.put(prompt(['a ```` b', 'c `````` d', 'e']));
  await s.bridge.tick();
  const c = s.client.callsOf('send')[0].payload.content;
  const inner = c.slice(c.indexOf('```\n') + 4, c.lastIndexOf('\n```'));
  assert.ok(!inner.includes('```'), inner);
  assert.strictEqual(c.split('```').length - 1, 2, c);
});

test('prompt without a configured user: no mention prefix and no <@undefined>', async () => {
  const s = setup();
  fs.writeFileSync(path.join(s.dir, 'bridge.json'), JSON.stringify({ channel: 'C1' }));
  s.put(prompt(['x']));
  await s.bridge.tick();
  const p = s.client.callsOf('send')[0].payload;
  assert.ok(p.content.startsWith('🔐 w1 wants to run Bash command'), p.content);
  assert.ok(!p.content.includes('undefined'));
  assert.deepStrictEqual(p.allowedMentions, { parse: [] });
});
