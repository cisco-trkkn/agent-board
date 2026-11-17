'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const commands = require('../lib/commands');
const { FakeClient, fakeCommand, fakeModal, fakeInteraction } = require('./fake-client');

const VIEWS = {
  ts: 1, projects: ['alpha', 'beta'],
  status: { _all: 'ALL CARD', alpha: 'alpha block' }, queue: { alpha: 'running x (1/2)' },
  approvals: [{ key: 'k1', project: 'alpha', kind: 'merge', title: 'Merge spec-x', link: 'https://d/1' }],
  evidence: {},
};

// ops: dir is <root>/_ops with command_center; project: dir is <root>/myproj with channel and ../_ops/views.json when opsViews.
function setup({ ops = true, views = VIEWS, opsViews = true } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbc-'));
  const dir = path.join(root, ops ? '_ops' : 'myproj');
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify(ops ? { command_center: 'CC', approvals: 'AP', user: 'U1' } : { channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TOK.abc.SECRETSECRETSECRET\n');
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  if (views && (ops || opsViews)) {
    const vdir = ops ? dir : path.join(root, '_ops');
    fs.mkdirSync(vdir, { recursive: true });
    fs.writeFileSync(path.join(vdir, 'views.json'), JSON.stringify(views));
  }
  const client = new FakeClient({ guildId: 'G1' });
  const logs = []; let tick = 0;
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => 1700000000000 + (tick += 1), sleep: async () => {} });
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  const run = async (i) => { await bridge.onInteraction(i); return i; };
  return { dir, client, logs, bridge, events, run };
}
const evShape = (s) => s.events().map((e) => { const { ts, ...r } = e; return r; });

test('payload: 7 chat-input commands; project option required per mode', () => {
  const names = ['status', 'queue', 'pause', 'resume', 'idea', 'new-spec', 'approvals'];
  const o = commands.payload(true), p = commands.payload(false);
  assert.deepStrictEqual(o.map((c) => c.name), names);
  assert.ok(o.every((c) => c.type === 1));
  const req = (list) => Object.fromEntries(list.map((c) => [c.name, c.options?.find((x) => x.name === 'project')?.required ?? null]));
  assert.deepStrictEqual(req(o), { status: false, queue: true, pause: true, resume: true, idea: true, 'new-spec': true, approvals: null });
  assert.deepStrictEqual(req(p), { status: false, queue: false, pause: false, resume: false, idea: false, 'new-spec': false, approvals: null });
  assert.ok(o.every((c) => (c.options || []).every((x) => x.type === 3)));
});

test('ready registers the commands once for the guild; a resume after disconnect registers again', async () => {
  const s = setup();
  await s.bridge.onReady(); await s.bridge.onReady();
  const c = s.client.callsOf('setCommands');
  assert.strictEqual(c.length, 1);
  assert.strictEqual(c[0].target, 'G1');
  assert.strictEqual(c[0].payload.length, 7);
  s.bridge.onDisconnect();
  await s.bridge.onReady();
  assert.strictEqual(s.client.callsOf('setCommands').length, 2);
});

test('registration failure is logged and onReady still completes', async () => {
  const s = setup();
  s.client.failNext('setCommands', { status: 403, message: 'Missing Access' });
  await s.bridge.onReady();
  assert.ok(s.logs.some((l) => /commands/.test(l) && /Missing Access/.test(l)));
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(s.dir, 'bridge-state.json'), 'utf8')).connected, true);
});

test('non-allowlisted command: ephemeral Not authorized. and a rejected event, nothing else', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'pause', options: { project: 'alpha' }, user: 'U7' }));
  assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Not authorized.', 64]]);
  assert.deepStrictEqual(evShape(s), [{ type: 'rejected', what: '/pause', user: 'U7' }]);
});

test('non-allowlisted modal submit is rejected too', async () => {
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:idea:alpha', fields: { title: 't', text: 'x' }, user: 'U7' }));
  assert.strictEqual(i.replies[0].content, 'Not authorized.');
  assert.deepStrictEqual(evShape(s), [{ type: 'rejected', what: 'ab:modal:idea:alpha', user: 'U7' }]);
});

test('/status without project is the card; with project its block; one read event each', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'status' }));
  const b = await s.run(fakeCommand({ name: 'status', options: { project: 'alpha' } }));
  assert.deepStrictEqual([a.replies[0].content, a.replies[0].flags], ['ALL CARD', 64]);
  assert.strictEqual(b.replies[0].content, 'alpha block');
  assert.deepStrictEqual(a.replies[0].allowedMentions, { parse: [] });
  assert.deepStrictEqual(evShape(s), [{ type: 'read', what: '/status', user: 'U1' }, { type: 'read', what: '/status', user: 'U1' }]);
});

test('/queue answers in a code block; unknown project says so with only the read event', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'queue', options: { project: 'alpha' } }));
  assert.strictEqual(a.replies[0].content, '```\nrunning x (1/2)\n```');
  const b = await s.run(fakeCommand({ name: 'queue', options: { project: 'nope' } }));
  assert.deepStrictEqual([b.replies[0].content, b.replies[0].flags], ['Unknown project: nope', 64]);
  assert.deepStrictEqual(evShape(s).map((e) => e.type), ['read', 'read']);
});

test('/approvals gives the very text of the Inbox button', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'approvals' }));
  const b = await s.run(fakeInteraction({ customId: 'ab:ops:inbox', user: 'U1' }));
  assert.strictEqual(a.replies[0].content, 'alpha · Merge spec-x https://d/1');
  assert.strictEqual(a.replies[0].content, b.replies[0].content);
});

test('read commands without views.json (ops): Board data not available yet.', async () => {
  const s = setup({ views: null });
  const i = await s.run(fakeCommand({ name: 'status' }));
  assert.strictEqual(i.replies[0].content, 'Board data not available yet.');
});

test('/pause and /resume reply Sent to <project>. and write a slash event', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'pause', options: { project: 'alpha' } }));
  const b = await s.run(fakeCommand({ name: 'resume', options: { project: 'beta' } }));
  assert.deepStrictEqual([a.replies[0].content, a.replies[0].flags], ['Sent to alpha.', 64]);
  assert.strictEqual(b.replies[0].content, 'Sent to beta.');
  assert.deepStrictEqual(evShape(s), [
    { type: 'slash', command: 'pause', project: 'alpha', user: 'U1' },
    { type: 'slash', command: 'resume', project: 'beta', user: 'U1' },
  ]);
});

test('/idea and /new-spec open the modals with the field limits', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'idea', options: { project: 'alpha' } }));
  const m = a.modals[0];
  assert.strictEqual(m.custom_id, 'ab:modal:idea:alpha');
  const inputs = m.components.map((r) => r.components[0]);
  assert.deepStrictEqual(inputs.map((x) => [x.custom_id, x.style, x.max_length, x.type]), [['title', 1, 100, 4], ['text', 2, 1000, 4]]);
  const b = await s.run(fakeCommand({ name: 'new-spec', options: { project: 'beta' } }));
  assert.strictEqual(b.modals[0].custom_id, 'ab:modal:new-spec:beta');
  assert.deepStrictEqual(b.modals[0].components.map((r) => [r.components[0].custom_id, r.components[0].style, r.components[0].max_length]), [['what', 1, 100], ['why', 2, 1000]]);
  assert.deepStrictEqual(s.events(), []);
});

test('idea submit: modal event with trimmed fields and the ephemeral ack', async () => {
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:idea:alpha', fields: { title: '  A title ', text: ' body\n' } }));
  assert.deepStrictEqual([i.replies[0].content, i.replies[0].flags], ['💡 noted for alpha', 64]);
  assert.deepStrictEqual(evShape(s), [{ type: 'modal', form: 'idea', project: 'alpha', fields: { title: 'A title', text: 'body' }, user: 'U1' }]);
});

test('new-spec submit: modal event and Sent to <project>\'s lead.', async () => {
  const s = setup();
  const i = await s.run(fakeModal({ customId: 'ab:modal:new-spec:my.proj-1', fields: { what: ' W ', why: ' Y ' } }));
  assert.strictEqual(i.replies[0].content, "Sent to my.proj-1's lead.");
  assert.deepStrictEqual(evShape(s)[0].fields, { what: 'W', why: 'Y' });
  assert.strictEqual(evShape(s)[0].project, 'my.proj-1');
});

test('project mode: project defaults to the dir name; actions go to its own events dir', async () => {
  const s = setup({ ops: false });
  const i = await s.run(fakeCommand({ name: 'pause' }));
  assert.strictEqual(i.replies[0].content, 'Sent to myproj.');
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'pause', project: 'myproj', user: 'U1' }]);
  const m = await s.run(fakeCommand({ name: 'idea' }));
  assert.strictEqual(m.modals[0].custom_id, 'ab:modal:idea:myproj');
});

test('project mode reads ../_ops/views.json; absent -> setup message; actions still work', async () => {
  const s = setup({ ops: false });
  const a = await s.run(fakeCommand({ name: 'status', options: { project: 'alpha' } }));
  assert.strictEqual(a.replies[0].content, 'alpha block');
  const none = setup({ ops: false, opsViews: false });
  const b = await none.run(fakeCommand({ name: 'queue', options: { project: 'alpha' } }));
  assert.strictEqual(b.replies[0].content, 'Ops bot not set up (tmux-ctl discord ops-channels).');
  const c = await none.run(fakeCommand({ name: 'resume' }));
  assert.strictEqual(c.replies[0].content, 'Sent to myproj.');
});

test('a command whose reply would exceed 2000 chars is cut', async () => {
  const s = setup({ views: { ...VIEWS, queue: { alpha: 'q'.repeat(5000) } } });
  const i = await s.run(fakeCommand({ name: 'queue', options: { project: 'alpha' } }));
  assert.ok(i.replies[0].content.length <= 2000);
  assert.ok(i.replies[0].content.endsWith('```'));
});

test('attach wires command and modal interactions through the same handler', async () => {
  const s = setup();
  s.bridge.attach();
  const i = fakeCommand({ name: 'status' });
  s.client.emit('interactionCreate', i);
  await new Promise((r) => setTimeout(r, 20));
  assert.strictEqual(i.replies[0].content, 'ALL CARD');
});

test('project option has max_length 60 so the modal custom_id stays under 100 chars', () => {
  for (const ops of [true, false]) {
    for (const c of commands.payload(ops).filter((x) => x.options)) assert.strictEqual(c.options[0].max_length, 60, c.name);
  }
  assert.ok(`ab:modal:new-spec:${'p'.repeat(60)}`.length <= 100);
});

test('ops mode with no project: Pick a project. for pause/resume/idea/new-spec/queue; no event, no modal', async () => {
  const s = setup();
  for (const name of ['pause', 'resume', 'idea', 'new-spec', 'queue']) {
    const i = await s.run(fakeCommand({ name }));
    assert.deepStrictEqual([i.replies[0]?.content, i.replies[0]?.flags, i.modals.length], ['Pick a project.', 64, 0], name);
  }
  assert.deepStrictEqual(s.events(), []);
});

test('pause/resume/idea/new-spec reject an unknown project when views.projects exists', async () => {
  const s = setup();
  for (const name of ['pause', 'resume', 'idea', 'new-spec']) {
    const i = await s.run(fakeCommand({ name, options: { project: 'nope' } }));
    assert.strictEqual(i.replies[0].content, 'Unknown project: nope', name);
    assert.strictEqual(i.modals.length, 0);
  }
  assert.deepStrictEqual(s.events(), []);
});

test('a whitespace-only required modal field: Empty <field>. and no event', async () => {
  const s = setup();
  const a = await s.run(fakeModal({ customId: 'ab:modal:idea:alpha', fields: { title: '   ', text: 'x' } }));
  assert.deepStrictEqual([a.replies[0].content, a.replies[0].flags], ['Empty title.', 64]);
  const b = await s.run(fakeModal({ customId: 'ab:modal:new-spec:alpha', fields: { what: 'w', why: ' \n ' } }));
  assert.strictEqual(b.replies[0].content, 'Empty why.');
  assert.deepStrictEqual(s.events(), []);
});

test('ctx.views is the one reader: project mode ctx.views reads ../_ops/views.json', () => {
  const s = setup({ ops: false });
  assert.strictEqual(s.bridge.ctx.views().status._all, 'ALL CARD');
  assert.strictEqual(typeof s.bridge.ctx.fence, 'function');
});
