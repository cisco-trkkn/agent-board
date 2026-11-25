'use strict';
// /new-project on the ops bridge (spec 2026-11-23-new-project-remote §2 Ops bridge): registration, the two forms, the token
// file, the create_channel and channel_overwrite outbox ops against the fake REST client, and the allowlist on every new interaction.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const commands = require('../lib/commands');
const { FakeClient, fakeCommand, fakeModal, fakeInteraction } = require('./fake-client');

const TOKEN = 'NEWBOT.tok3n.SECRETSECRETSECRETSECRETSECRET';

function setup({ ops = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbnp-'));
  const dir = path.join(root, ops ? '_ops' : 'myproj');
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify(ops ? { command_center: 'CC', approvals: 'AP', user: 'U1' } : { channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=OPS.abc.SECRETSECRETSECRET\n');
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  const client = new FakeClient({ guildId: 'G1' });
  const logs = []; let t = 0;
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => 1700000000000 + (t += 1), sleep: async () => {} });
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  const tokFiles = () => { try { return fs.readdirSync(path.join(dir, 'np-token')); } catch { return []; } };
  const op = (o) => fs.writeFileSync(path.join(dir, 'outbox', `${String(Date.now()).padStart(13, '0')}-${Math.random().toString(16).slice(2, 10)}.json`), JSON.stringify(o));
  const failed = () => { try { return fs.readdirSync(path.join(dir, 'outbox', 'failed')).filter((n) => n.endsWith('.json')); } catch { return []; } };
  return { dir, client, logs, bridge, events, tokFiles, op, failed, run: async (i) => { await bridge.onInteraction(i); return i; } };
}
const shape = (evs) => evs.map(({ ts, ...r }) => r);

test('payload: /new-project on the ops bot only, with one optional name option', () => {
  const o = commands.payload(true).find((c) => c.name === 'new-project');
  assert.deepStrictEqual(o.options, [{ name: 'name', description: 'Resume the unfinished setup of this project', type: 3, max_length: 60, required: false }]);
  assert.strictEqual(commands.payload(false).find((c) => c.name === 'new-project'), undefined);
});

test('/new-project in the command center opens the form with name, source and target', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC' }));
  assert.strictEqual(i.modals.length, 1);
  assert.strictEqual(i.modals[0].custom_id, 'ab:modal:new-project');
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].custom_id), ['name', 'source', 'target']);
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].required), [true, true, false]);
  assert.deepStrictEqual(s.events(), []);
});

test('/new-project outside the command center is refused with one line and audited as rejected', async () => {
  // mutation: drop the command-center check -> the form opens and modals.length is 1
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'AP' }));
  assert.strictEqual(i.modals.length, 0);
  assert.strictEqual(i.replies[0].content, 'Use /new-project in the command center.');
  assert.deepStrictEqual(shape(s.events()), [{ type: 'rejected', what: '/new-project', project: null, user: 'U1' }]);
});

test('/new-project <name> defers privately and hands the resume to the board', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', options: { name: 'np1' }, id: 'I7' }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'slash', command: 'new-project', name: 'np1', channel_id: 'CC', iid: 'I7', user: 'U1' }]);
});

test('/new-project <name> with a bad name answers one line and writes nothing', async () => {
  const s = setup();
  for (const nm of ['bad.name', '-x', 'a'.repeat(61)]) {
    const i = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', options: { name: nm } }));
    assert.match(i.replies[0].content, /^Bad name/);
  }
  assert.deepStrictEqual(s.events(), []);
});

test('the new-project form: a valid submit defers and writes one modal event; target is dropped for new', async () => {
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId: 'CC', id: 'I8', fields: { name: 'np1', source: 'New', target: 'ignored' } }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'modal', form: 'new-project', fields: { name: 'np1', source: 'new', target: '' }, user: 'U1', channel_id: 'CC', iid: 'I8' }]);
});

test('the new-project form refuses up front with one line: bad name, bad source, missing url or path, outside the command center', async () => {
  const s = setup();
  const cases = [
    [{ name: 'a.b', source: 'new' }, 'CC', /^Bad name/],
    [{ name: 'np1', source: 'zip' }, 'CC', /^Source must be new, clone or folder\.$/],
    [{ name: 'np1', source: 'clone' }, 'CC', /^Source clone needs a git URL\.$/],
    [{ name: 'np1', source: 'folder' }, 'CC', /^Source folder needs a path\.$/],
    [{ name: 'np1', source: 'new' }, 'AP', /^Use \/new-project in the command center\.$/],
  ];
  for (const [fields, channelId, re] of cases) {
    const i = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId, fields }));
    assert.match(i.replies[0].content, re);
    assert.deepStrictEqual(i.deferredReplies, []);
  }
  assert.deepStrictEqual(shape(s.events()), [{ type: 'rejected', what: 'ab:modal:new-project', user: 'U1' }]);
});

test('Paste token opens the one-field private form', async () => {
  const s = setup();
  const i = await s.run(fakeInteraction({ customId: 'ab:np:token:np1', user: 'U1' }));
  assert.strictEqual(i.modals[0].custom_id, 'ab:modal:np-token:np1');
  assert.deepStrictEqual(i.modals[0].components.map((r) => r.components[0].custom_id), ['token']);
  assert.deepStrictEqual(s.events(), []);
});

test('the token form writes a mode-600 one-shot file and an event naming it; the token is in no event and no log line', async () => {
  // mutation: put the token into the event (text: tok) -> the leak assertion on events fails
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', channelId: 'CC', id: 'I9', fields: { token: ` ${TOKEN} ` } }));
  assert.deepStrictEqual(i.deferredReplies, [{ flags: 64 }]);
  const files = s.tokFiles();
  assert.strictEqual(files.length, 1);
  assert.match(files[0], /^[0-9]+-[0-9a-f]{8}\.tok$/);
  const f = path.join(s.dir, 'np-token', files[0]);
  assert.strictEqual(fs.readFileSync(f, 'utf8'), TOKEN);
  assert.strictEqual(fs.statSync(f).mode & 0o777, 0o600);
  assert.strictEqual(fs.statSync(path.dirname(f)).mode & 0o777, 0o700);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_token', name: 'np1', file: files[0], user: 'U1', iid: 'I9' }]);
  const evText = fs.readdirSync(path.join(s.dir, 'events')).map((n) => fs.readFileSync(path.join(s.dir, 'events', n), 'utf8')).join('\n');
  assert.ok(!evText.includes(TOKEN));
  assert.ok(!s.logs.join('\n').includes(TOKEN));
});

test('the token form refuses an empty or spaced token and writes no file', async () => {
  const s = setup();
  for (const token of ['', 'a b']) {
    const i = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', fields: { token } }));
    assert.match(i.replies[0].content, /does not look like a bot token/);
  }
  assert.deepStrictEqual(s.tokFiles(), []);
  assert.deepStrictEqual(s.events(), []);
});

test('every new interaction is refused for a non-allowlisted user: nothing opens, no file, a rejected event', async () => {
  // mutation: skip the allowlist check in commands.handle -> the form opens or the token file is written
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', user: 'EVIL' }));
  const b = await s.run(fakeCommand({ name: 'new-project', channelId: 'CC', user: 'EVIL', options: { name: 'np1' } }));
  const c = await s.run(fakeModal({ customId: 'ab:modal:new-project', channelId: 'CC', user: 'EVIL', fields: { name: 'np1', source: 'new' } }));
  const d = await s.run(fakeInteraction({ customId: 'ab:np:token:np1', user: 'EVIL' }));
  const e = await s.run(fakeModal({ customId: 'ab:modal:np-token:np1', user: 'EVIL', fields: { token: TOKEN } }));
  const f = await s.run(fakeInteraction({ customId: 'ab:np:retry:np1:disk', user: 'EVIL' }));
  for (const i of [a, b, c, d, e, f]) {
    assert.strictEqual(i.replies[0].content, 'Not authorized.');
    assert.strictEqual((i.modals || []).length, 0);
  }
  assert.deepStrictEqual(s.tokFiles(), []);
  assert.deepStrictEqual(shape(s.events()).map((x) => [x.type, x.what]), [
    ['rejected', '/new-project'], ['rejected', '/new-project'], ['rejected', 'ab:modal:new-project'],
    ['rejected', 'ab:np:token:np1'], ['rejected', 'ab:modal:np-token:np1'],
  ]); // the Retry click is refused by onInteraction, which audits only ab:ops: ids (as today)
});

test('Retry is a click event for the board', async () => {
  const s = setup();
  await s.run(fakeInteraction({ customId: 'ab:np:retry:np1:disk', user: 'U1', messageId: 'm5', channelId: 'CC' }));
  assert.deepStrictEqual(shape(s.events()), [{ type: 'click', custom_id: 'ab:np:retry:np1:disk', user: 'U1', message_id: 'm5', channel_id: 'CC' }]);
});

test('create_channel creates #<name> in lower case and answers with the channel id', async () => {
  const s = setup();
  s.op({ op: 'create_channel', guild: '999', name: 'Np1', req: 'r1' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('restPost').map((c) => [c.target, c.payload]), [['/guilds/999/channels', { name: 'np1', type: 0 }]]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'create_channel', name: 'Np1', req: 'r1', ok: true, channel_id: 'ch1', existed: false }]);
});

test('create_channel run twice reuses the channel: no second channel', async () => {
  // mutation: drop the lookup of an existing channel -> two restPost calls
  const s = setup();
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r2' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('restPost').length, 1);
  assert.deepStrictEqual(shape(s.events()).map((e) => [e.req, e.channel_id, e.existed]), [['r1', 'ch1', false], ['r2', 'ch1', true]]);
});

test('create_channel without Manage Channels answers ok false, missing permissions; the op is not retried or failed', async () => {
  const s = setup();
  s.client.failNext('restPost', { status: 403, code: 50013, message: 'Missing Permissions' });
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'create_channel', name: 'np1', req: 'r1', ok: false, error: 'missing permissions' }]);
  assert.deepStrictEqual(s.failed(), []);
  assert.strictEqual(s.client.callsOf('restPost').length, 1);
});

test('create_channel retries a 500 and then answers once', async () => {
  const s = setup();
  s.client.failNext('restPost', { status: 500 });
  s.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('restPost').length, 2);
  assert.deepStrictEqual(shape(s.events()).map((e) => e.ok), [true]);
});

test('channel_overwrite puts a member overwrite with exactly the allow bits', async () => {
  const s = setup();
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '2252109051432000', name: 'np1', req: 'r3' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('restPut').map((c) => [c.target, c.payload]), [['/channels/555/permissions/777', { type: 1, allow: '2252109051432000', deny: '0' }]]);
  assert.deepStrictEqual(shape(s.events()), [{ type: 'np_result', action: 'channel_overwrite', name: 'np1', req: 'r3', ok: true }]);
});

test('channel_overwrite refused by Discord answers ok false', async () => {
  const s = setup();
  s.client.failNext('restPut', { status: 403, code: 50013 });
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '1024', name: 'np1', req: 'r3' });
  await s.bridge.tick();
  assert.deepStrictEqual(shape(s.events()).map((e) => [e.ok, e.error]), [[false, 'missing permissions']]);
});

test('malformed channel ops go to failed/ and answer nothing; a project bridge refuses both ops', async () => {
  const s = setup();
  s.op({ op: 'create_channel', guild: 'abc', name: 'np1', req: 'r1' });
  s.op({ op: 'channel_overwrite', channel: '555', user: '777', allow: '1e3', name: 'np1', req: 'r2' });
  await s.bridge.tick();
  assert.strictEqual(s.failed().length, 2);
  assert.deepStrictEqual(s.events(), []);
  const p = setup({ ops: false });
  p.op({ op: 'create_channel', guild: '999', name: 'np1', req: 'r1' });
  await p.bridge.tick();
  assert.strictEqual(p.failed().length, 1);
  assert.strictEqual(p.client.callsOf('restGet').length, 0);
});
