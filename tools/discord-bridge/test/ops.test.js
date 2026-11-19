'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const { FakeClient, fakeInteraction } = require('./fake-client');

const TOKEN = 'OPSTOKEN.abc123.SECRETSECRETSECRET';
let seq = 0;

const FILES = Array.from({ length: 23 }, (_, n) => ({ path: `src/dir/file${String(n).padStart(2, '0')}.py`, add: n + 1, del: n }));
const VIEWS = {
  ts: 1700000000, projects: ['alpha', 'beta'],
  status: { _all: 'card', alpha: 'a', beta: 'b' }, queue: { alpha: 'q' },
  approvals: [
    { key: 'k1', project: 'alpha', kind: 'merge', title: 'Merge spec-x', link: 'https://discord.com/channels/G/1' },
    { key: 'k2', project: 'beta', kind: 'perm', title: 'Run rm', link: 'https://discord.com/channels/G/2' },
  ],
  evidence: { k1: { files: FILES, diffs: { [FILES[0].path]: '-old\n+new' } } },
};

function setup({ views = VIEWS, ops = true } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dbo-'));
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify(ops ? { command_center: 'CC', approvals: 'AP', user: 'U1' } : { channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), `DISCORD_BOT_TOKEN=${TOKEN}\n`);
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  if (views) fs.writeFileSync(path.join(dir, 'views.json'), JSON.stringify(views));
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: 1700000000000 };
  const logs = [];
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => clock.t, sleep: async () => {} });
  const put = (op) => {
    const name = `${String(1700000000000 + ++seq).padStart(13, '0')}-${String(seq).padStart(8, '0')}.json`;
    fs.writeFileSync(path.join(dir, 'outbox', name), JSON.stringify(op));
    return name;
  };
  const st = () => JSON.parse(fs.readFileSync(path.join(dir, 'bridge-state.json'), 'utf8'));
  const events = () => { try { return fs.readdirSync(path.join(dir, 'events')).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, 'events', n), 'utf8'))); } catch { return []; } };
  const files = () => fs.readdirSync(path.join(dir, 'outbox')).filter((n) => n.endsWith('.json'));
  return { dir, client, clock, logs, bridge, put, st, events, files };
}
const ids = (rows) => rows.map((r) => r.components.map((c) => c.custom_id || c.url));
const sentTo = (s, ch) => s.client.callsOf('send').filter((c) => c.target === ch);

test('ops card goes to command_center with the three exact buttons', async () => {
  const s = setup();
  s.put({ op: 'card', text: 'status' });
  await s.bridge.tick();
  const [c] = s.client.callsOf('send');
  assert.strictEqual(c.target, 'CC');
  assert.deepStrictEqual(ids(c.payload.components), [['ab:ops:pause-all', 'ab:ops:resume-all', 'ab:ops:inbox']]);
  assert.deepStrictEqual(s.files(), []);
});

test('ops card edit keeps the buttons and the 30 s throttle', async () => {
  const s = setup();
  s.put({ op: 'card', text: 'one' });
  await s.bridge.tick();
  s.put({ op: 'card', text: 'two' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('edit').length, 0); // throttled
  s.clock.t += 31000;
  await s.bridge.tick();
  const e = s.client.callsOf('edit');
  assert.strictEqual(e.length, 1);
  assert.deepStrictEqual(ids(e[0].payload.components), [['ab:ops:pause-all', 'ab:ops:resume-all', 'ab:ops:inbox']]);
});

test('project mode card has no components', async () => {
  const s = setup({ ops: false });
  s.put({ op: 'card', text: 'status' });
  await s.bridge.tick();
  assert.strictEqual(s.client.callsOf('send')[0].payload.components, undefined);
});

test('ops post goes to command_center and key is recorded in posts', async () => {
  const s = setup();
  s.put({ op: 'post', text: 'hello', tier: 'progress', mention_user: false, key: 'pk' });
  await s.bridge.tick();
  assert.strictEqual(sentTo(s, 'CC').length, 1);
  assert.ok(s.st().posts.pk);
});

test('approval perm: Allow once green, Deny red, in the approvals channel', async () => {
  const s = setup();
  s.put({ op: 'approval', key: 'ak', kind: 'perm', text: 'run it', mention_user: true });
  await s.bridge.tick();
  const [c] = sentTo(s, 'AP');
  const row = c.payload.components[0].components;
  assert.deepStrictEqual(row.map((b) => [b.label, b.style, b.custom_id]), [['Allow once', 3, 'ab:ops:allow:ak'], ['Deny', 4, 'ab:ops:deny:ak']]);
  assert.ok(s.st().approvals.ak);
});

test('approval merge: three buttons plus a select of at most 25 files, value cut to 100', async () => {
  const long = 'x'.repeat(150);
  const views = { ...VIEWS, evidence: { k1: { files: [...FILES, { path: long, add: 1, del: 1 }, ...FILES.slice(0, 5)], diffs: {} } } };
  const s = setup({ views });
  s.put({ op: 'approval', key: 'k1', kind: 'merge', text: 'merge?', mention_user: false });
  await s.bridge.tick();
  const comps = sentTo(s, 'AP')[0].payload.components;
  assert.deepStrictEqual(comps[0].components.map((b) => [b.label, b.custom_id]),
    [['Merge', 'ab:ops:merge:k1'], ['Keep branch', 'ab:ops:keep:k1'], ['Show files', 'ab:ops:files:k1:0']]);
  const sel = comps[1].components[0];
  assert.strictEqual(sel.type, 3); assert.strictEqual(sel.custom_id, 'ab:ops:diff:k1');
  assert.strictEqual(sel.options.length, 25);
  assert.ok(sel.options.every((o) => o.value.length <= 100 && o.label.length <= 100));
  assert.strictEqual(sel.options[0].value, FILES[0].path);
});

test('approval merge without evidence files has no select row', async () => {
  const s = setup();
  s.put({ op: 'approval', key: 'zz', kind: 'merge', text: 'merge?', mention_user: false });
  await s.bridge.tick();
  assert.strictEqual(sentTo(s, 'AP')[0].payload.components.length, 1);
});

test('approval question: link button when link set, else no components', async () => {
  const s = setup();
  s.put({ op: 'approval', key: 'q1', kind: 'question', text: 'which?', mention_user: false, link: 'https://discord.com/channels/G/9', project: 'alpha' });
  s.put({ op: 'approval', key: 'q2', kind: 'other', text: 'hm', mention_user: false });
  await s.bridge.tick();
  const [a, b] = sentTo(s, 'AP');
  const btn = a.payload.components[0].components[0];
  assert.strictEqual(btn.style, 5); assert.strictEqual(btn.url, 'https://discord.com/channels/G/9');
  assert.strictEqual(btn.custom_id, undefined); assert.match(btn.label, /^Reply in /);
  assert.ok(!b.payload.components || b.payload.components.length === 0);
});

test('approvals state keeps the newest 500', async () => {
  const s = setup();
  for (let n = 0; n < 503; n++) s.put({ op: 'approval', key: `a${n}`, kind: 'other', text: 't', mention_user: false });
  await s.bridge.tick();
  const keys = Object.keys(s.st().approvals);
  assert.strictEqual(keys.length, 500);
  assert.ok(!keys.includes('a0') && keys.includes('a502'));
});

test('edit finds a key in posts and approvals and drops the components', async () => {
  const s = setup();
  s.put({ op: 'post', text: 'p', tier: 'progress', mention_user: false, key: 'pk' });
  s.put({ op: 'approval', key: 'ak', kind: 'perm', text: 'a', mention_user: false });
  await s.bridge.tick();
  s.put({ op: 'edit', key: 'pk', text: 'P done' });
  s.put({ op: 'edit', key: 'ak', text: 'A done' });
  await s.bridge.tick();
  const e = s.client.callsOf('edit');
  assert.deepStrictEqual(e.map((c) => [c.payload.content, c.payload.components]), [['P done', []], ['A done', []]]);
});

test('edit of a prompt key still works; unknown key logs and the op is removed', async () => {
  const s = setup();
  s.put({ op: 'edit', key: 'nope', text: 'x' });
  await s.bridge.tick();
  assert.ok(s.logs.some((l) => l.includes('edit nope: no message')));
  assert.deepStrictEqual(s.files(), []);
});

test('edit of an approval looks in the approvals channel', async () => {
  const s = setup();
  s.put({ op: 'approval', key: 'ak', kind: 'perm', text: 'a', mention_user: false });
  await s.bridge.tick();
  const mid = s.st().approvals.ak;
  s.put({ op: 'edit', key: 'ak', text: 'done' });
  await s.bridge.tick();
  assert.strictEqual(s.client.messages.get(mid).content, 'done');
});

const click = async (s, opts) => { const i = fakeInteraction({ user: 'U1', ...opts }); await s.bridge.onInteraction(i); return i; };

test('non-allowlisted user: ephemeral Not authorized. and a rejected event', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:inbox', user: 'U7' });
  assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Not authorized.', 64]]);
  const evs = s.events();
  assert.strictEqual(evs.length, 1);
  assert.deepStrictEqual([evs[0].type, evs[0].what, evs[0].user], ['rejected', 'ab:ops:inbox', 'U7']);
});

test('inbox lists the open decisions and writes a read event', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:inbox' });
  const r = i.replies[0];
  assert.strictEqual(r.flags, 64); assert.deepStrictEqual(r.allowedMentions, { parse: [] });
  assert.strictEqual(r.content, 'alpha · Merge spec-x https://discord.com/channels/G/1\nbeta · Run rm https://discord.com/channels/G/2');
  const evs = s.events();
  assert.deepStrictEqual(evs.map((e) => [e.type, e.what, e.user]), [['read', 'ab:ops:inbox', 'U1']]);
});

test('inbox with no approvals says No open decisions.', async () => {
  const s = setup({ views: { ...VIEWS, approvals: [] } });
  const i = await click(s, { customId: 'ab:ops:inbox' });
  assert.strictEqual(i.replies[0].content, 'No open decisions.');
});

test('missing or unreadable views.json: Board data not available yet.', async () => {
  for (const views of [null]) {
    const s = setup({ views });
    const i = await click(s, { customId: 'ab:ops:inbox' });
    assert.deepStrictEqual([i.replies[0].content, i.replies[0].flags], ['Board data not available yet.', 64]);
  }
  const s = setup();
  fs.writeFileSync(path.join(s.dir, 'views.json'), '{not json');
  const i = await click(s, { customId: 'ab:ops:files:k1:0' });
  assert.strictEqual(i.replies[0].content, 'Board data not available yet.');
});

test('files page 0: 10 files with +add -del, page 1/3, only Next', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:files:k1:0' });
  const r = i.replies[0];
  assert.strictEqual(r.flags, 64);
  const lines = r.content.split('\n');
  assert.ok(lines.includes(`${FILES[0].path} +1 -0`));
  assert.ok(lines.includes(`${FILES[9].path} +10 -9`));
  assert.ok(!r.content.includes(FILES[10].path));
  assert.match(r.content, /page 1\/3/);
  assert.deepStrictEqual(r.components[0].components.map((b) => [b.label, b.custom_id]), [['Next', 'ab:ops:files:k1:1']]);
  assert.deepStrictEqual(s.events().map((e) => e.type), ['read']);
});

test('files last page: only Prev; middle page has both; ephemeral clicks update the message', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:files:k1:1', ephemeral: true });
  assert.strictEqual(i.replies.length, 0);
  const u = i.updates[0];
  assert.match(u.content, /page 2\/3/);
  assert.deepStrictEqual(u.components[0].components.map((b) => b.custom_id), ['ab:ops:files:k1:0', 'ab:ops:files:k1:2']);
  const j = await click(s, { customId: 'ab:ops:files:k1:2', ephemeral: true });
  assert.ok(j.updates[0].content.includes(`${FILES[22].path} +23 -22`));
  assert.deepStrictEqual(j.updates[0].components[0].components.map((b) => b.label), ['Prev']);
});

test('files with an out-of-range page clamps; unknown key says no evidence', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:files:k1:99' });
  assert.match(i.replies[0].content, /page 3\/3/);
  const j = await click(s, { customId: 'ab:ops:files:nokey:0' });
  assert.strictEqual(j.replies[0].flags, 64);
  assert.match(j.replies[0].content, /No file list/);
});

test('diff select replies with the diff in a diff block and writes a read event', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:diff:k1', values: [FILES[0].path] });
  const r = i.replies[0];
  assert.strictEqual(r.flags, 64);
  assert.strictEqual(r.content, '```diff\n-old\n+new\n```');
  assert.deepStrictEqual(s.events().map((e) => [e.type, e.what]), [['read', 'ab:ops:diff:k1']]);
});

test('diff select for a path without a stored diff says so; long diff stays under 2000', async () => {
  const big = '+' + 'y'.repeat(1790) + '\n… too long, see board';
  const views = { ...VIEWS, evidence: { k1: { files: FILES, diffs: { [FILES[1].path]: big } } } };
  const s = setup({ views });
  const i = await click(s, { customId: 'ab:ops:diff:k1', values: [FILES[2].path] });
  assert.match(i.replies[0].content, /No diff/);
  const j = await click(s, { customId: 'ab:ops:diff:k1', values: [FILES[1].path] });
  assert.ok(j.replies[0].content.length <= 2000);
  assert.ok(j.replies[0].content.includes('too long, see board'));
});

test('pause-all asks for confirmation with the bridge clock in the button id and writes only a read event', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:pause-all' });
  const r = i.replies[0];
  assert.strictEqual(r.content, 'Pause every running queue?'); assert.strictEqual(r.flags, 64);
  const b = r.components[0].components;
  assert.deepStrictEqual(b.map((x) => [x.label, x.custom_id]), [['Confirm pause all', `ab:ops:pause-all-confirm:${s.clock.t}`]]);
  assert.deepStrictEqual(s.events().map((e) => e.type), ['read']);
  assert.strictEqual(i.deferred, 0);
});

test('pause-all-confirm replies Sent. and writes a click event', async () => {
  const s = setup();
  const id = `ab:ops:pause-all-confirm:${s.clock.t}`;
  const i = await click(s, { customId: id, ephemeral: true });
  assert.deepStrictEqual(i.replies.length + i.updates.length, 1);
  const r = i.replies[0] || i.updates[0];
  assert.strictEqual(r.content, 'Sent.');
  const evs = s.events();
  assert.deepStrictEqual(evs.map((e) => [e.type, e.custom_id]), [['click', id]]);
});

test('resume-all replies Sent. and writes a click event', async () => {
  const s = setup();
  const i = await click(s, { customId: 'ab:ops:resume-all', ephemeral: true });
  assert.deepStrictEqual(i.replies.length + i.updates.length, 1);
  assert.strictEqual((i.replies[0] || i.updates[0]).content, 'Sent.');
  assert.deepStrictEqual(s.events().map((e) => [e.type, e.custom_id]), [['click', 'ab:ops:resume-all']]);
});

test('allow, deny, merge, keep: deferUpdate and one click event with the custom_id', async () => {
  const s = setup();
  const idsClicked = ['ab:ops:allow:ak', 'ab:ops:deny:ak', 'ab:ops:merge:k1', 'ab:ops:keep:k1'];
  for (const id of idsClicked) {
    const i = await click(s, { customId: id });
    assert.strictEqual(i.deferred, 1, id);
    assert.strictEqual(i.replies.length, 0, id);
  }
  assert.deepStrictEqual(s.events().map((e) => [e.type, e.custom_id]).sort(), idsClicked.map((id) => ['click', id]).sort());
});

test('action click is deferred before its event is written', async () => {
  const s = setup();
  let atDefer = -1;
  const i = fakeInteraction({ customId: 'ab:ops:merge:k1', user: 'U1', onDefer: () => { atDefer = s.events().length; } });
  await s.bridge.onInteraction(i);
  assert.strictEqual(atDefer, 0);
  assert.strictEqual(s.events().length, 1);
});

test('project mode: an ab:ops click takes the generic path, not the ops one', async () => {
  const s = setup({ ops: false });
  const i = await click(s, { customId: 'ab:ops:inbox' });
  assert.strictEqual(i.deferred, 1);
  assert.deepStrictEqual(s.events().map((e) => e.type), ['click']);
});

test('ops mode edit of a prompt key is unaffected (prompts looked up first)', async () => {
  const s = setup();
  s.put({ op: 'prompt', key: 'pr', window: 'w', tool: 'Bash', lines: ['ls'] });
  await s.bridge.tick();
  assert.strictEqual(sentTo(s, 'CC').length, 1);
  s.put({ op: 'edit', key: 'pr', text: 'gone' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('edit').map((c) => c.payload.content), ['gone']);
});

test('post with buttons sends one action row; the keyed post is editable and the edit clears it', async () => {
  const s = setup();
  const buttons = [
    { label: 'Brainstorm next', style: 1, custom_id: 'ab:ideas:next:r1:0' },
    { label: 'Park', style: 2, custom_id: 'ab:ideas:park:r1:0' },
    { label: 'Drop', style: 4, custom_id: 'ab:ideas:drop:r1:0' },
  ];
  s.put({ op: 'post', text: 'group', tier: 'progress', mention_user: false, key: 'ideas-r1-0', buttons });
  await s.bridge.tick();
  const [c] = sentTo(s, 'CC');
  assert.strictEqual(c.payload.components.length, 1);
  assert.strictEqual(c.payload.components[0].type, 1);
  assert.deepStrictEqual(c.payload.components[0].components.map((b) => [b.type, b.style, b.label, b.custom_id]),
    buttons.map((b) => [2, b.style, b.label, b.custom_id]));
  assert.ok(s.st().posts['ideas-r1-0']);
  s.put({ op: 'edit', key: 'ideas-r1-0', text: 'group\ndone' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('edit').map((e) => e.payload.components), [[]]);
});

test('post buttons: at most 5, label cut to 80', async () => {
  const s = setup();
  const buttons = Array.from({ length: 7 }, (_, n) => ({ label: 'L'.repeat(100), style: 2, custom_id: `ab:ideas:x:${n}` }));
  s.put({ op: 'post', text: 'g', tier: 'progress', mention_user: false, buttons });
  await s.bridge.tick();
  const row = sentTo(s, 'CC')[0].payload.components[0].components;
  assert.strictEqual(row.length, 5);
  assert.strictEqual(row[0].label.length, 80);
});
