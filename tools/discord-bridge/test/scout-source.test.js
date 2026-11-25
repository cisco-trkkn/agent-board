'use strict';
// Scout source requests in the bridge (plan 2026-11-24-hardening, Task 5). The bridge only forwards: /source (the agent-board
// project bot only), a `source:` message outside the home channel, and a ✅ on a recorded source prompt in any channel each
// become one event. detect, the add and the first fetch run in the board, which answers through ireply ops or REST in #scout.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createBridge } = require('../bridge');
const commands = require('../lib/commands');
const { FakeClient, fakeCommand, fakeMessage, fakeReaction } = require('./fake-client');

const T0 = Date.parse('2026-11-24T21:00:00Z');
let seq = 0;

// project: the bridge dir's base name; prompts: the board's <dir>/scout-prompts.json ({prompt message id: channel id}).
function setup({ project = 'agent-board', ops = false, prompts } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbsrc-'));
  const dir = path.join(root, ops ? '_ops' : project);
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify(ops ? { command_center: 'CC', approvals: 'AP' } : { channel: 'C1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc.SECRET\n');
  fs.writeFileSync(path.join(dir, 'access.json'), JSON.stringify({ allowFrom: ['U1'] }));
  if (prompts) fs.writeFileSync(path.join(dir, 'scout-prompts.json'), JSON.stringify(prompts));
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: T0 };
  const logs = [];
  const bridge = createBridge({ dir, client, ops, log: (l) => logs.push(l), now: () => clock.t, sleep: async () => {} });
  const readDir = (sub) => { try { return fs.readdirSync(path.join(dir, sub)).filter((n) => n.endsWith('.json')).sort().map((n) => JSON.parse(fs.readFileSync(path.join(dir, sub, n), 'utf8'))); } catch { return []; } };
  const events = () => readDir('events').map((e) => { const { ts, ...r } = e; return r; });
  const outbox = () => readDir('outbox');
  const put = (op) => fs.writeFileSync(path.join(dir, 'outbox', `${String(T0 + ++seq).padStart(13, '0')}-${String(seq).padStart(8, '0')}.json`), JSON.stringify(op));
  const state = () => { try { return JSON.parse(fs.readFileSync(path.join(dir, 'bridge-state.json'), 'utf8')); } catch { return {}; } }; // no file: nothing was ever saved
  return { dir, client, clock, logs, bridge, events, outbox, put, state };
}

// A /source command; fetchReply gives the id of the interaction's own reply message.
function sourceCmd({ url = 'https://example.com/feed', name, user = 'U1', channelId = 'C1', replyId = '7001', id = 'iid-s' } = {}) {
  const i = fakeCommand({ name: 'source', options: { ...(url === null ? {} : { url }), ...(name ? { name } : {}) }, user, channelId, id });
  i.fetchReply = async () => { if (replyId === null) throw new Error('Unknown Webhook'); return { id: replyId }; };
  return i;
}
const react = (s, message, { emoji = '✅', user = { id: 'U1' } } = {}) => s.bridge.onReaction(fakeReaction({ emoji, message }), user);

test('/source is in the agent-board project bot\'s payload and in no other', () => {
  const names = (ops, p) => commands.payload(ops, p).map((c) => c.name);
  assert.ok(names(false, 'agent-board').includes('source'));
  for (const [ops, p] of [[true, undefined], [true, 'agent-board'], [true, '_ops'], [false, undefined], [false, 'interiors']]) {
    assert.ok(!names(ops, p).includes('source'), `ops=${ops} project=${p}`);
  }
  const c = commands.payload(false, 'agent-board').find((x) => x.name === 'source');
  assert.deepStrictEqual([c.type, c.options.map((o) => [o.name, o.type, o.required, o.max_length])], [1, [['url', 3, true, 500], ['name', 3, false, 40]]]);
});

test('only the agent-board bridge registers /source with Discord', async () => {
  // Mutation: register(ch) calls commands.payload(ops) without the project -> no bridge registers it.
  for (const [opt, want] of [[{}, true], [{ project: 'interiors' }, false], [{ ops: true }, false]]) {
    const s = setup(opt);
    await s.bridge.onReady();
    const c = s.client.callsOf('setCommands');
    assert.strictEqual(c.length, 1);
    assert.strictEqual(c[0].payload.some((x) => x.name === 'source'), want, JSON.stringify(opt));
  }
});

test('/source from an allowed user: a public deferred reply and one source event carrying the URL and name', async () => {
  const s = setup();
  const i = sourceCmd({ url: ' https://example.com/feed ', name: 'my-feed', channelId: 'C9' });
  await s.bridge.onInteraction(i);
  assert.deepStrictEqual(i.deferredReplies, [undefined]); // no ephemeral flag: the reply has to take a ✅
  assert.deepStrictEqual(i.replies, []);
  assert.deepStrictEqual(s.events(), [{ type: 'source', via: 'slash', url: 'https://example.com/feed', name: 'my-feed', iid: 'iid-s', channel_id: 'C9', message_id: '7001', user: 'U1' }]);
  // the board's answer edits that reply: nothing is sent to a channel
  s.put({ op: 'ireply', iid: 'iid-s', content: '```\nmy-feed · rss · https://example.com/feed\n```\nreact ✅ to add' });
  await s.bridge.tick();
  assert.deepStrictEqual(i.edits.map((e) => [e.content, e.allowedMentions]), [['```\nmy-feed · rss · https://example.com/feed\n```\nreact ✅ to add', { parse: [] }]]);
  assert.deepStrictEqual(s.client.callsOf('send'), []);
});

test('/source without a name sends an empty name', async () => {
  const s = setup();
  await s.bridge.onInteraction(sourceCmd());
  assert.deepStrictEqual(s.events().map((e) => [e.url, e.name]), [['https://example.com/feed', '']]);
});

test('/source from a user outside allowFrom: Not authorized. and no source event', async () => {
  const s = setup();
  const i = sourceCmd({ user: 'U7' });
  await s.bridge.onInteraction(i);
  assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Not authorized.', 64]]);
  assert.deepStrictEqual(i.deferredReplies, []);
  assert.deepStrictEqual(s.events(), [{ type: 'rejected', what: '/source', user: 'U7' }]);
});

test('/source on another project\'s bot or the ops bot (a stale registration) is refused with no event', async () => {
  for (const opt of [{ project: 'interiors' }, { ops: true }]) {
    const s = setup(opt);
    const i = sourceCmd();
    await s.bridge.onInteraction(i);
    assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Not available here.', 64]]);
    assert.deepStrictEqual(s.events(), []);
  }
});

test('/source with no URL, or with spaces in it, asks for one URL and writes no event', async () => {
  const s = setup();
  for (const url of [null, '   ', 'https://a.example/x and more']) {
    const i = sourceCmd({ url });
    await s.bridge.onInteraction(i);
    assert.deepStrictEqual(i.replies.map((r) => [r.content, r.flags]), [['Give one URL.', 64]]);
  }
  assert.deepStrictEqual(s.events(), []);
});

test('/source whose reply cannot be read back writes no event and says so', async () => {
  const s = setup();
  const i = sourceCmd({ replyId: null });
  await s.bridge.onInteraction(i);
  assert.deepStrictEqual(s.events(), []);
  assert.deepStrictEqual(i.edits.map((e) => e.content), ['Could not set up the prompt; run /source again.']);
  assert.ok(s.logs.some((l) => /source: reply not readable/.test(l)));
});

test('✅ on a recorded scout prompt outside the home channel writes one react event; on any other non-home message none', async () => {
  // Mutation: drop the scout branch in onReaction -> no event (the home-channel test stops the reaction).
  const s = setup({ prompts: { 9001: 'C7' } });
  await react(s, fakeMessage({ id: '9002', channelId: 'C7', content: 'not a prompt' }));
  assert.deepStrictEqual(s.events(), []);
  const m = fakeMessage({ id: '9001', channelId: 'C7', content: 'x · rss · https://example.com/feed' });
  await react(s, m);
  assert.deepStrictEqual(s.events(), [{ type: 'react', emoji: '✅', message_id: '9001', channel_id: 'C7', scout: true, user: 'U1' }]);
  assert.deepStrictEqual(m.reacted, []);
});

test('the scout ✅ needs an allowFrom user, a human and the ✅ itself; an uncached (partial) prompt still counts', async () => {
  const s = setup({ prompts: { 9001: 'C7' } });
  const m = () => fakeMessage({ id: '9001', channelId: 'C7' });
  await react(s, m(), { user: { id: 'U7' } });
  await react(s, m(), { user: { id: 'U1', bot: true } });
  await react(s, m(), { emoji: '❌' });
  assert.deepStrictEqual(s.events(), []);
  await react(s, fakeMessage({ id: '9001', channelId: 'C7', partial: true }));
  assert.deepStrictEqual(s.events().map((e) => [e.type, e.message_id, e.scout]), [['react', '9001', true]]);
});

test('a bridge with no scout-prompts.json, or an unreadable one, forwards no ✅ from outside the home channel', async () => {
  const s = setup();
  await react(s, fakeMessage({ id: '9001', channelId: 'C7' }));
  fs.writeFileSync(path.join(s.dir, 'scout-prompts.json'), '{not json');
  await react(s, fakeMessage({ id: '9001', channelId: 'C7' }));
  fs.writeFileSync(path.join(s.dir, 'scout-prompts.json'), '["9001"]');
  await react(s, fakeMessage({ id: '0', channelId: 'C7' }));
  assert.deepStrictEqual(s.events(), []);
});

test('in the home channel: ✅ on a recorded prompt is the scout\'s event alone; on any other bot message the react event is as before', async () => {
  const s = setup({ prompts: { 9001: 'C1' } });
  const prompt = fakeMessage({ id: '9001', channelId: 'C1', content: 'x · rss · https://example.com/feed' });
  await react(s, prompt);
  assert.deepStrictEqual(s.events(), [{ type: 'react', emoji: '✅', message_id: '9001', channel_id: 'C1', scout: true, user: 'U1' }]);
  assert.deepStrictEqual(prompt.reacted, []);
  const other = fakeMessage({ id: '9002', channelId: 'C1', content: 'ship  it?' });
  s.clock.t += 1; // event files sort by their timestamp
  await react(s, other);
  assert.deepStrictEqual(s.events()[1], { type: 'react', emoji: '✅', message_id: '9002', excerpt: 'ship it?', user: 'U1' });
  assert.deepStrictEqual(other.reacted, ['👀']);
});

test('❓ still goes to the status line, on a recorded prompt too', async () => {
  const s = setup({ prompts: { 9001: 'C1' } });
  await react(s, fakeMessage({ id: '9001', channelId: 'C1' }), { emoji: '❓' });
  assert.deepStrictEqual(s.events(), []);
  assert.deepStrictEqual(s.outbox().map((o) => o.op), ['liveness_reply', 'liveness']);
});

test('a source: message outside the home channel from an allowed user becomes one source event', async () => {
  const s = setup();
  await s.bridge.onMessage(fakeMessage({ id: '2001', authorId: 'U1', content: '  source: https://example.com/feed my-feed ', channelId: 'C7' }));
  assert.deepStrictEqual(s.events(), [{ type: 'source', via: 'message', text: 'source: https://example.com/feed my-feed', message_id: '2001', channel_id: 'C7', user: 'U1' }]);
  assert.strictEqual(s.state().liveness?.target ?? null, null); // not the home channel: no liveness target
});

test('no source event: another author, a bot, other text, the home channel, another project\'s bot, the ops bot', async () => {
  const s = setup();
  const msg = (o) => fakeMessage({ id: '2001', authorId: 'U1', content: 'source: https://example.com/feed', channelId: 'C7', ...o });
  await s.bridge.onMessage(msg({ authorId: 'U7' }));
  await s.bridge.onMessage(msg({ authorId: 'BOT', authorBot: true }));
  await s.bridge.onMessage(msg({ content: 'see source: https://example.com/feed' }));
  await s.bridge.onMessage(msg({ content: 'source:' }));
  await s.bridge.onMessage(msg({ channelId: 'C1' })); // the home channel: that message is the lead's
  assert.deepStrictEqual(s.events(), []);
  assert.strictEqual(s.state().liveness.target.id, '2001'); // and it is still tracked as the user's newest message
  for (const opt of [{ project: 'interiors' }, { ops: true }]) {
    const o = setup(opt);
    await o.bridge.onMessage(msg({}));
    assert.deepStrictEqual(o.events(), []);
  }
});

test('a source: text is cut to 600 characters in the event', async () => {
  const s = setup();
  await s.bridge.onMessage(fakeMessage({ id: '2001', authorId: 'U1', content: `source: https://example.com/${'a'.repeat(3000)}`, channelId: 'C7' }));
  assert.strictEqual(s.events()[0].text.length, 600);
});

test('a /source reply in the home channel never counts as the lead\'s answer', async () => {
  // Mutation: post the prompt with a raw channel send -> its id lands in bot_after without being in own_sent.
  const s = setup();
  const target = fakeMessage({ id: '1001', authorId: 'U1', content: 'hello', channelId: 'C1', createdTimestamp: T0 });
  s.client.messages.set('1001', target);
  await s.bridge.onMessage(target);
  await s.bridge.onInteraction(sourceCmd({ channelId: 'C1', replyId: '1002' }));
  // the gateway delivers the bot's own interaction reply as a message
  await s.bridge.onMessage(fakeMessage({ id: '1002', authorId: 'BOT', authorBot: true, channelId: 'C1', interactionMetadata: { id: 'iid-s' } }));
  s.put({ op: 'ireply', iid: 'iid-s', content: 'x · rss · https://example.com/feed' });
  await s.bridge.tick();
  assert.deepStrictEqual(s.client.callsOf('send'), []);
  assert.deepStrictEqual(s.state().liveness.bot_after, []);
  // 15 minutes later the interaction has expired: the board's edit falls back to a post, which is the bridge's own
  s.clock.t += 15 * 60 * 1000;
  s.put({ op: 'ireply', iid: 'iid-s', content: 'added: x (rss)' });
  await s.bridge.tick();
  const sent = [...s.client.messages.values()].filter((m) => m.payload?.content === 'added: x (rss)');
  assert.strictEqual(sent.length, 1);
  await s.bridge.onMessage(fakeMessage({ id: sent[0].id, authorId: 'BOT', authorBot: true, channelId: 'C1' }));
  const st = s.state();
  assert.deepStrictEqual(st.liveness.bot_after, [sent[0].id]);
  assert.deepStrictEqual(st.liveness.bot_after.filter((id) => !st.own_sent.includes(id)), []);
  assert.strictEqual(st.liveness.target.id, '1001');
});
