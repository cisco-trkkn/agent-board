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
  tasks: { alpha: 'T1 do it\nT2 done' },
  leads: {
    alpha: { window: 'claude', pane: '%3', pid: 4242, state: 'idle', holds_bot: true, context_pct: 41, session_id: 'sess-abc', doc: '/h/2026-handoff-a.md', doc_age_s: 540 },
    beta: { window: null, pane: null, pid: null, state: null, holds_bot: false, context_pct: null, session_id: null, doc: null, doc_age_s: null },
  },
};

// ops: dir is <root>/_ops with command_center; project: dir is <root>/myproj with channel and ../_ops/views.json when opsViews.
function setup({ ops = true, views = VIEWS, opsViews = true, clock } = {}) {
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
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: clock || (() => 1700000000000 + (tick += 1)), sleep: async () => {} });
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  const run = async (i) => { await bridge.onInteraction(i); return i; };
  return { dir, client, logs, bridge, events, run };
}
const evShape = (s) => s.events().map((e) => { const { ts, ...r } = e; return r; });

test('payload: 8 chat-input commands; project option required per mode', () => {
  const names = ['status', 'queue', 'pause', 'resume', 'idea', 'new-spec', 'ideas', 'approvals', 'tasks', 'lead', 'gauth'];
  const o = commands.payload(true), p = commands.payload(false);
  assert.deepStrictEqual(o.map((c) => c.name), names);
  assert.ok(o.every((c) => c.type === 1));
  const req = (list) => Object.fromEntries(list.map((c) => [c.name, c.options?.find((x) => x.name === 'project')?.required ?? null]));
  assert.deepStrictEqual(req(o), { status: false, queue: true, pause: true, resume: true, idea: true, 'new-spec': true, ideas: false, approvals: null, tasks: false, lead: true, gauth: true });
  assert.deepStrictEqual(req(p), { status: false, queue: false, pause: false, resume: false, idea: false, 'new-spec': false, ideas: false, approvals: null, tasks: false, lead: false, gauth: false });
  const act = o.find((c) => c.name === 'lead').options.find((x) => x.name === 'action');
  assert.deepStrictEqual([act.type, act.required, act.choices.map((c) => c.value)], [3, true, ['status', 'restart', 'handoff']]);
  assert.ok(o.every((c) => (c.options || []).every((x) => x.type === 3)));
});

test('ready registers the commands once for the guild; a resume after disconnect registers again', async () => {
  const s = setup();
  await s.bridge.onReady(); await s.bridge.onReady();
  const c = s.client.callsOf('setCommands');
  assert.strictEqual(c.length, 1);
  assert.strictEqual(c[0].target, 'G1');
  assert.strictEqual(c[0].payload.length, 11);
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
    for (const c of commands.payload(ops).filter((x) => x.options)) assert.strictEqual(c.options.find((x) => x.name === 'project').max_length, 60, c.name); // lead: action comes first (required before optional)
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

test('/status with an unknown project answers Unknown project and still writes exactly one read event', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'status', options: { project: 'nope' } }));
  assert.strictEqual(i.replies[0].content, 'Unknown project: nope');
  assert.deepStrictEqual(evShape(s), [{ type: 'read', what: '/status', user: 'U1' }]);
});

const ACK = 'asked the overseer, about 1 min';

test('/ideas with no project: ephemeral ack, slash event with project null and bridge _ops (ops mode)', async () => {
  const s = setup();
  const i = await s.run(fakeCommand({ name: 'ideas' }));
  assert.deepStrictEqual([i.replies[0].content, i.replies[0].flags], [ACK, 64]);
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'ideas', project: null, bridge: '_ops', user: 'U1' }]);
});

test('/ideas with no project in a project channel takes no default project (R2)', async () => {
  const s = setup({ ops: false });
  const i = await s.run(fakeCommand({ name: 'ideas' }));
  assert.strictEqual(i.replies[0].content, ACK);
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'ideas', project: null, bridge: 'myproj', user: 'U1' }]);
});

test('/ideas <project> writes that project; an unknown one is answered and writes no event', async () => {
  const s = setup();
  await s.run(fakeCommand({ name: 'ideas', options: { project: 'alpha' } }));
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'ideas', project: 'alpha', bridge: '_ops', user: 'U1' }]);
  const u = await s.run(fakeCommand({ name: 'ideas', options: { project: 'nope' } }));
  assert.strictEqual(u.replies[0].content, 'Unknown project: nope');
  assert.strictEqual(s.events().length, 1);
});

// ---- /tasks, /lead, /gauth, ireply (lead recovery) ----
const reply0 = (i) => i.replies[0];
const btns = (r) => r.components.flatMap((row) => row.components);

test('strangers are refused for every new command, button, select and modal', async () => {
  const s = setup();
  const items = [
    fakeCommand({ name: 'tasks', options: { project: 'alpha' }, user: 'U7' }),
    fakeCommand({ name: 'lead', options: { action: 'status', project: 'alpha' }, user: 'U7' }),
    fakeCommand({ name: 'gauth', options: { project: 'alpha' }, user: 'U7' }),
    fakeInteraction({ customId: 'ab:lead:restart:alpha:1700000000000', user: 'U7' }),
    fakeInteraction({ customId: 'ab:lead:cancel:alpha:1700000000000', user: 'U7' }),
    fakeInteraction({ customId: 'ab:tasks:pick', user: 'U7', values: ['alpha'] }),
    fakeInteraction({ customId: 'ab:gauth:code:alpha', user: 'U7' }),
    fakeModal({ customId: 'ab:modal:gauth:alpha', fields: { code: 'x' }, user: 'U7' }),
  ];
  for (const i of items) {
    await s.run(i);
    assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Not authorized.', 64]]);
  }
  const ev = evShape(s);
  assert.strictEqual(ev.length, 8);
  assert.ok(ev.every((e) => e.type === 'rejected' && e.user === 'U7'));
  assert.deepStrictEqual(items.map((i) => (i.deferredReplies?.length || 0) + (i.modals?.length || 0) + (i.edits?.length || 0) + (i.updates?.length || 0)), items.map(() => 0));
});

test('/tasks <p>: private fenced reply from views.tasks, or no task list', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'tasks', options: { project: 'alpha' } }));
  assert.deepStrictEqual([reply0(a).content, reply0(a).flags], ['```\nT1 do it\nT2 done\n```', 64]);
  const b = await s.run(fakeCommand({ name: 'tasks', options: { project: 'beta' } }));
  assert.strictEqual(reply0(b).content, '```\nno task list for beta\n```');
});

test('/tasks alone: a select of projects with tasks; picking one gives the same reply', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'tasks' }));
  const sel = reply0(a).components[0].components[0];
  assert.deepStrictEqual([reply0(a).flags, sel.type, sel.custom_id, sel.options.map((o) => o.value)], [64, 3, 'ab:tasks:pick', ['alpha']]);
  const p = await s.run(fakeInteraction({ customId: 'ab:tasks:pick', user: 'U1', values: ['alpha'], ephemeral: true }));
  assert.strictEqual(p.updates[0].content, '```\nT1 do it\nT2 done\n```');
});

test('/tasks alone with no task lists says so', async () => {
  const s = setup({ views: { ...VIEWS, tasks: {} } });
  const a = await s.run(fakeCommand({ name: 'tasks' }));
  assert.strictEqual(reply0(a).content, 'no task lists');
  assert.ok(!reply0(a).components);
});

test('/lead status: private fenced block from views.leads', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'lead', options: { action: 'status', project: 'alpha' } }));
  assert.strictEqual(reply0(a).flags, 64);
  assert.strictEqual(reply0(a).content, '```\nwindow claude · pane %3 · pid 4242\nstate idle · bot held\ncontext 41%\nnewest handoff 2026-handoff-a.md (9m ago)\n```');
  const b = await s.run(fakeCommand({ name: 'lead', options: { action: 'status', project: 'beta' } }));
  assert.match(reply0(b).content, /context unknown\nnewest handoff none/);
  assert.match(reply0(b).content, /bot not held/);
});

test('/lead restart: preview with Confirm and Cancel; busy suffix; no events yet', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'lead', options: { action: 'restart', project: 'alpha' } }));
  assert.strictEqual(reply0(a).content, 'restart the alpha lead in window claude with --resume sess-abc');
  const [c, x] = btns(reply0(a));
  assert.match(c.custom_id, /^ab:lead:restart:alpha:17000000000\d+$/);
  assert.match(x.custom_id, /^ab:lead:cancel:alpha:17000000000\d+$/);
  assert.deepStrictEqual([c.label, x.label], ['Confirm', 'Cancel']);
  assert.strictEqual(evShape(s).length, 0);
  const views = { ...VIEWS, leads: { alpha: { ...VIEWS.leads.alpha, state: 'working' } } };
  const s2 = setup({ views });
  const b = await s2.run(fakeCommand({ name: 'lead', options: { action: 'restart', project: 'alpha' } }));
  assert.strictEqual(reply0(b).content, 'restart the alpha lead in window claude with --resume sess-abc; it is working right now');
  const v3 = { ...VIEWS, leads: { alpha: { ...VIEWS.leads.alpha, state: 'waiting' } } };
  const c3 = await setup({ views: v3 }).run(fakeCommand({ name: 'lead', options: { action: 'restart', project: 'alpha' } }));
  assert.strictEqual(reply0(c3).content, 'restart the alpha lead in window claude with --resume sess-abc; it is waiting right now');
});

test('/lead handoff: preview names the doc and its age', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'lead', options: { action: 'handoff', project: 'alpha' } }));
  assert.strictEqual(reply0(a).content, 'start a fresh lead from 2026-handoff-a.md, written 9 min ago');
  assert.match(btns(reply0(a))[0].custom_id, /^ab:lead:handoff:alpha:/);
});

test('/lead restart|handoff with a missing field: cannot <action> <p>, no buttons', async () => {
  const s = setup();
  const a = await s.run(fakeCommand({ name: 'lead', options: { action: 'restart', project: 'beta' } }));
  assert.deepStrictEqual([reply0(a).content, reply0(a).components], ['cannot restart beta: no lead pane', undefined]);
  const noSess = setup({ views: { ...VIEWS, leads: { alpha: { ...VIEWS.leads.alpha, session_id: null } } } });
  const b = await noSess.run(fakeCommand({ name: 'lead', options: { action: 'restart', project: 'alpha' } }));
  assert.strictEqual(reply0(b).content, 'cannot restart alpha: no session id');
  const c = await s.run(fakeCommand({ name: 'lead', options: { action: 'handoff', project: 'beta' } }));
  assert.strictEqual(reply0(c).content, 'cannot handoff beta: no handoff doc');
  assert.ok(!reply0(c).components);
});

test('/lead Cancel answers cancelled and writes no event', async () => {
  const s = setup();
  const i = await s.run(fakeInteraction({ customId: 'ab:lead:cancel:alpha:1700000000000', user: 'U1', ephemeral: true }));
  assert.strictEqual(i.updates[0].content, 'cancelled');
  assert.deepStrictEqual(i.updates[0].components, []);
  assert.strictEqual(evShape(s).length, 0);
});

test('/lead Confirm older than 5 minutes: expired, no event', async () => {
  const t0 = 1700000000000;
  const s = setup({ clock: () => t0 + 5 * 60 * 1000 + 1 });
  const i = await s.run(fakeInteraction({ customId: `ab:lead:restart:alpha:${t0}`, user: 'U1', ephemeral: true }));
  assert.strictEqual(i.updates[0].content, 'expired; run /lead again');
  assert.strictEqual(i.deferred, 0);
  assert.strictEqual(evShape(s).length, 0);
});

test('/lead Confirm in time: deferUpdate, event with iid, the interaction is kept for ireply', async () => {
  const t0 = 1700000000000;
  const s = setup({ clock: () => t0 + 1000 });
  const i = await s.run(fakeInteraction({ customId: `ab:lead:restart:alpha:${t0}`, user: 'U1', ephemeral: true, id: 'iid-77' }));
  assert.deepStrictEqual(i.updates.map((u) => [u.content, u.components]), [['running…', []]]);
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'lead', action: 'restart', project: 'alpha', user: 'U1', iid: 'iid-77' }]);
  fs.writeFileSync(path.join(s.dir, 'outbox', '1.json'), JSON.stringify({ op: 'ireply', iid: 'iid-77', content: 'restarted' }));
  await s.bridge.tick();
  assert.strictEqual(i.edits[0].content, 'restarted');
  assert.strictEqual(s.client.callsOf('send').length, 0);
});

test('/gauth: deferReply private, kept, event; Enter code button opens the modal; submit sends the event', async () => {
  const s = setup();
  const g = await s.run(fakeCommand({ name: 'gauth', options: { project: 'alpha' }, id: 'iid-g' }));
  assert.deepStrictEqual(g.deferredReplies.map((d) => d.flags), [64]);
  assert.deepStrictEqual(evShape(s), [{ type: 'slash', command: 'gauth', project: 'alpha', user: 'U1', iid: 'iid-g' }]);
  const b = await s.run(fakeInteraction({ customId: 'ab:gauth:code:alpha', user: 'U1' }));
  const m = b.modals[0];
  assert.strictEqual(m.custom_id, 'ab:modal:gauth:alpha');
  const inputs = m.components.flatMap((r) => r.components);
  assert.deepStrictEqual(inputs.map((x) => [x.type, x.custom_id, x.style]), [[4, 'code', 1]]);
  const sub = await s.run(fakeModal({ customId: 'ab:modal:gauth:alpha', fields: { code: '  4/0AbC-secret ' }, user: 'U1' }));
  assert.strictEqual(sub.replies[0].content, 'Code sent.');
  assert.strictEqual(sub.replies[0].flags, 64);
  assert.deepStrictEqual(evShape(s)[1], { type: 'modal', form: 'gauth', project: 'alpha', user: 'U1', text: '4/0AbC-secret' });
  assert.ok(s.logs.some((l) => l.includes('modal gauth alpha from U1')));
  assert.ok(!s.logs.some((l) => l.includes('4/0AbC')));
});

test('/gauth modal with an empty code sends no event', async () => {
  const s = setup();
  const sub = await s.run(fakeModal({ customId: 'ab:modal:gauth:alpha', fields: { code: '  ' }, user: 'U1' }));
  assert.strictEqual(sub.replies[0].content, 'Empty code.');
  assert.strictEqual(evShape(s).length, 0);
});

test('ireply: components become rows; unknown iid falls back to a channel post and logs it', async () => {
  const s = setup();
  const g = await s.run(fakeCommand({ name: 'gauth', options: { project: 'alpha' }, id: 'iid-g' }));
  const put = (n, op) => fs.writeFileSync(path.join(s.dir, 'outbox', `${n}.json`), JSON.stringify(op));
  put(1, { op: 'ireply', iid: 'iid-g', content: 'open the link', components: [[{ label: 'Enter code', style: 1, custom_id: 'ab:gauth:code:alpha' }]] });
  put(2, { op: 'ireply', iid: 'nope', content: 'lost reply' });
  await s.bridge.tick();
  assert.strictEqual(g.edits[0].content, 'open the link');
  assert.deepStrictEqual(g.edits[0].components[0].components.map((b) => [b.label, b.custom_id]), [['Enter code', 'ab:gauth:code:alpha']]);
  const sent = s.client.callsOf('send');
  assert.deepStrictEqual(sent.map((c) => [c.target, c.payload.content]), [['CC', 'lost reply']]);
  assert.ok(s.logs.some((l) => l.includes('ireply nope fell back to post')));
});

test('ireply: an interaction kept more than 14 minutes is expired and falls back', async () => {
  let t = 1700000000000;
  const s = setup({ clock: () => t });
  const g = await s.run(fakeCommand({ name: 'gauth', options: { project: 'alpha' }, id: 'iid-old' }));
  t += 840 * 1000 + 1;
  fs.writeFileSync(path.join(s.dir, 'outbox', '1.json'), JSON.stringify({ op: 'ireply', iid: 'iid-old', content: 'late' }));
  await s.bridge.tick();
  assert.strictEqual(g.edits.length, 0);
  assert.deepStrictEqual(s.client.callsOf('send').map((c) => c.payload.content), ['late']);
  assert.ok(s.logs.some((l) => l.includes('ireply iid-old fell back to post')));
});

test('/lead Confirm twice on the same custom id: one event, the second says already confirmed; the first click is kept', async () => {
  const t0 = 1700000000000;
  const s = setup({ clock: () => t0 + 1000 });
  const cid = `ab:lead:restart:alpha:${t0}`;
  const a = await s.run(fakeInteraction({ customId: cid, user: 'U1', ephemeral: true, id: 'iid-a' }));
  const b = await s.run(fakeInteraction({ customId: cid, user: 'U1', ephemeral: true, id: 'iid-b' }));
  assert.strictEqual(evShape(s).length, 1);
  assert.strictEqual(b.updates[0].content, 'already confirmed');
  assert.deepStrictEqual(b.updates[0].components, []);
  fs.writeFileSync(path.join(s.dir, 'outbox', '1.json'), JSON.stringify({ op: 'ireply', iid: 'iid-a', content: 'restarted' }));
  await s.bridge.tick();
  assert.strictEqual(a.edits[0].content, 'restarted');
  assert.strictEqual(b.edits.length, 0);
});

test('/lead Cancel consumes the id: a later Confirm on it writes no event', async () => {
  const t0 = 1700000000000;
  const s = setup({ clock: () => t0 + 1000 });
  await s.run(fakeInteraction({ customId: `ab:lead:cancel:alpha:${t0}`, user: 'U1', ephemeral: true }));
  const c = await s.run(fakeInteraction({ customId: `ab:lead:restart:alpha:${t0}`, user: 'U1', ephemeral: true }));
  assert.strictEqual(c.updates[0].content, 'already confirmed');
  assert.strictEqual(evShape(s).length, 0);
});

test('ireply with private: true and an unknown iid posts nothing and logs dropped (private)', async () => {
  const s = setup();
  fs.writeFileSync(path.join(s.dir, 'outbox', '1.json'), JSON.stringify({ op: 'ireply', iid: 'nope', content: 'secret link', private: true }));
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('send').length, 0);
  assert.ok(s.logs.some((l) => l.includes('ireply nope dropped (private)')));
});

test('ireply: editReply throws -> no channel post, logs the failure', async () => {
  const s = setup();
  const g = await s.run(fakeCommand({ name: 'gauth', options: { project: 'alpha' }, id: 'iid-t' }));
  g.editReply = async () => { throw new Error('boom 503'); };
  fs.writeFileSync(path.join(s.dir, 'outbox', '1.json'), JSON.stringify({ op: 'ireply', iid: 'iid-t', content: 'x' }));
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('send').length, 0);
  assert.ok(s.logs.some((l) => l.includes('ireply iid-t failed: boom 503')));
});

test('/gauth modal: the answer follows the write; a failed write answers could not send', async () => {
  const s = setup();
  const sub = await s.run(fakeModal({ customId: 'ab:modal:gauth:alpha', fields: { code: 'abc' }, user: 'U1' }));
  assert.strictEqual(sub.replies[0].content, 'Code sent.');
  const s2 = setup();
  fs.rmSync(path.join(s2.dir, 'events'), { recursive: true, force: true });
  fs.writeFileSync(path.join(s2.dir, 'events'), 'not a dir');
  const bad = await s2.run(fakeModal({ customId: 'ab:modal:gauth:alpha', fields: { code: 'abc' }, user: 'U1' }));
  assert.strictEqual(bad.replies[0].content, 'could not send the code; run /gauth again');
});
