'use strict';
// Agent Board discord bridge: consumes <dir>/outbox, keeps the pinned card and threads,
// writes <dir>/bridge-state.json, turns ab: component clicks into <dir>/events/*.json.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const outbox = require('./lib/outbox');
const stateLib = require('./lib/state');

const CARD_MIN_MS = 30000;
const BACKOFF_START = 1000;
const BACKOFF_CAP = 60000;
const TICK_MS = 2000;
const BODY_MAX = 80;
const UNKNOWN_MESSAGE = 10008;
const HELD = Symbol('held');
const PROMPT_MAX = 1500;
const PROMPTS_KEEP = 200;
const REACT_EMOJI = new Set(['✅', '❌', '🛑', '▶', '⏭']);

const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return d; } };

function readToken(dir) {
  let txt;
  try { txt = fs.readFileSync(path.join(dir, '.env'), 'utf8'); } catch { return null; }
  const m = txt.match(/^DISCORD_BOT_TOKEN=(.*)$/m);
  return m ? m[1].trim().replace(/^["']|["']$/g, '') : null;
}

const statusOf = (e) => (typeof e?.status === 'number' ? e.status : undefined);
const NET_CODES = new Set(['ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED', 'EPIPE', 'ECONNABORTED', 'ENETUNREACH', 'EHOSTUNREACH']);
// Retry only 5xx, 429 and network failures; everything else (4xx, bad file path, bad config, bugs) is permanent.
function isRetryable(e) {
  const s = statusOf(e);
  if (s !== undefined) return s >= 500 || s === 429;
  if (['AbortError', 'TimeoutError'].includes(e?.name) || ['AbortError', 'TimeoutError'].includes(e?.cause?.name)) return true;
  const c = e?.code ?? e?.cause?.code;
  if (typeof c === 'string' && (NET_CODES.has(c) || c.startsWith('UND_ERR'))) return true;
  return /socket hang up|fetch failed|network|timed? ?out/i.test(String(e?.message));
}

function createBridge({ dir, client, log = () => {}, now = Date.now, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  const token = readToken(dir);
  let st = stateLib.read(dir);
  let pendingCard = null; // {text} held back by the 30 s throttle
  let lastCardAt = -Infinity;
  let busy = false;
  let closed = false;

  // Every log line: token replaced by ***, bodies cut to 80 chars.
  const say = (msg) => {
    let line = String(msg);
    if (token) line = line.split(token).join('***');
    log(line);
  };
  const snip = (t) => {
    let s = String(t ?? '');
    if (token) s = s.split(token).join('***');
    s = s.replace(/\s+/g, ' ');
    return s.length > BODY_MAX ? `${s.slice(0, BODY_MAX)}…` : s;
  };

  const cfg = () => readJson(path.join(dir, 'bridge.json'), {});
  const save = () => stateLib.write(dir, st, now());
  const home = async () => {
    const channel = cfg().channel;
    if (!channel) throw new Error('bridge.json has no channel');
    const ch = await client.channels.fetch(channel);
    if (ch?.guildId && st.guild_id !== ch.guildId) { st.guild_id = ch.guildId; save(); }
    return ch;
  };

  async function createCard(text) {
    const ch = await home();
    const msg = await ch.send({ content: text, allowedMentions: { parse: [] } });
    st.card_message_id = msg.id; save();
    lastCardAt = now();
    await msg.pin();
  }

  async function doCard(text) {
    if (!st.card_message_id) return createCard(text);
    const ch = await home();
    try {
      const msg = await ch.messages.fetch(st.card_message_id);
      await msg.edit({ content: text, allowedMentions: { parse: [] } });
      lastCardAt = now();
    } catch (e) {
      if (e?.code !== UNKNOWN_MESSAGE) throw e;
      st.card_message_id = null;
      await createCard(text);
    }
  }

  // Delete the held card files (superseded ops) once an edit has been accepted.
  function release() {
    for (const n of pendingCard?.names || []) outbox.remove(dir, n);
    pendingCard = null;
  }

  async function opCard(op, name) {
    if (st.card_message_id && now() - lastCardAt < CARD_MIN_MS) {
      pendingCard = { text: op.text, names: [...(pendingCard?.names || []), name] };
      return HELD; // files stay in the outbox until the coalesced edit is accepted
    }
    await doCard(op.text);
    release(); // this op and any held, superseded card ops were accepted
  }

  async function flushCard() {
    if (pendingCard && now() - lastCardAt >= CARD_MIN_MS) {
      await doCard(pendingCard.text);
      release();
    }
  }

  async function opThread(op) {
    if (st.threads[op.key]) return;
    const ch = await home();
    const t = await ch.threads.create({ name: String(op.title).slice(0, 100), type: 11, autoArchiveDuration: 1440 });
    st.threads[op.key] = t.id; save();
  }

  async function opArchive(op) {
    const id = st.threads[op.key];
    if (!id) return;
    const t = await client.channels.fetch(id);
    await t.setArchived(true);
  }

  const MAX_FILES = 10, MAX_BYTES = 25 * 1024 * 1024;
  const fmtSize = (n) => (n / (1024 * 1024)).toFixed(1) + ' MB';
  function pickFiles(paths) {
    const ok = [], notes = [];
    for (const p of paths.slice(0, MAX_FILES)) {
      let st; try { st = fs.statSync(p); } catch { notes.push(`${path.basename(p)} not found`); continue; }
      if (st.size > MAX_BYTES) notes.push(`${path.basename(p)} too large (${fmtSize(st.size)})`);
      else ok.push(p);
    }
    if (paths.length > MAX_FILES) notes.push(`${paths.length - MAX_FILES} more files not sent (${MAX_FILES} max)`);
    return { ok, notes };
  }

  async function opPost(op) {
    const c = cfg();
    let text = String(op.text ?? '');
    if (op.link_thread_key && st.threads[op.link_thread_key]) {
      if (!st.guild_id) await home();
      text += `\nhttps://discord.com/channels/${st.guild_id}/${st.threads[op.link_thread_key]}`;
    }
    let target;
    if (op.thread_key && st.threads[op.thread_key]) target = await client.channels.fetch(st.threads[op.thread_key]);
    else {
      target = await home();
      if (op.thread_key) text += ` (thread ${op.thread_key} missing)`;
    }
    const payload = { content: '', allowedMentions: { parse: [] } };
    if (op.mention_user && c.user) {
      text = `<@${c.user}> ${text}`;
      payload.allowedMentions = { users: [String(c.user)] };
    }
    const paths = Array.isArray(op.files) ? op.files.map(String) : [];
    const { ok, notes } = pickFiles(paths);
    if (notes.length) text += '\n' + notes.join('\n');
    payload.content = text.slice(0, 2000);
    if (ok.length) payload.files = ok;
    await target.send(payload);
    if (op.delete_files === true) {
      const tmpRoot = path.join(dir, 'tmp') + path.sep;
      for (const p of paths) {
        const r = path.resolve(p);
        if (r.startsWith(tmpRoot)) { try { fs.unlinkSync(r); } catch { /* already gone */ } }
        else say(`delete_files: kept ${r} (outside tmp/)`);
      }
    }
    say(`post ${op.thread_key || 'home'} ${snip(op.text)}`);
  }

  async function opPrompt(op) {
    const c = cfg();
    const lines = (Array.isArray(op.lines) ? op.lines : []).map(String);
    let shown = lines;
    let cut = false;
    if (lines.join('\n').length > PROMPT_MAX) {
      let n = 0; let total = 0;
      for (const l of lines) {
        const next = total + (n ? 1 : 0) + l.length;
        if (next > PROMPT_MAX) break;
        total = next; n++;
      }
      shown = [...lines.slice(0, n), `… (${lines.length - n} more lines)`];
      cut = true;
    }
    const body = shown.map((l) => l.replace(/`{3,}/g, (m) => `\`\u200b${m.slice(1).match(/`{1,2}/g).join('\u200b')}`)).join('\n');
    const head = `${c.user ? `<@${c.user}> ` : ''}🔐 ${op.window} wants to run ${op.tool}`;
    const content = `${head}\n\`\`\`\n${body}\n\`\`\`${cut ? '\nOpen on the board to see all of it.' : ''}`;
    const id = (a) => `ab:perm:${op.key}:${a}`;
    const buttons = [];
    if (!cut) buttons.push({ type: 2, style: 3, label: 'Allow once', custom_id: id('allow') });
    buttons.push({ type: 2, style: 4, label: 'Deny', custom_id: id('deny') });
    const ch = await home();
    const msg = await ch.send({
      content: content.slice(0, 2000),
      allowedMentions: c.user ? { users: [String(c.user)] } : { parse: [] },
      components: [{ type: 1, components: buttons }],
    });
    st.prompts[op.key] = msg.id;
    for (const k of Object.keys(st.prompts).slice(0, Math.max(0, Object.keys(st.prompts).length - PROMPTS_KEEP))) delete st.prompts[k];
    save();
    say(`prompt ${snip(op.key)} ${snip(op.tool)}`);
  }

  async function opEdit(op) {
    const id = st.prompts[op.key];
    if (!id) { say(`edit ${snip(op.key)}: no message`); return; }
    const ch = await home();
    try {
      const msg = await ch.messages.fetch(id);
      await msg.edit({ content: String(op.text ?? '').slice(0, 2000), components: [] });
    } catch (e) {
      if (e?.code !== UNKNOWN_MESSAGE) throw e;
      say(`edit ${snip(op.key)}: no message`);
    }
  }

  const handlers = { prompt: opPrompt, edit: opEdit, post: opPost, card: opCard, thread: opThread, archive: opArchive };

  // Run fn until it succeeds; 5xx/network backs off 1s,2s,4s… capped at 60s. Throws on 4xx.
  async function withRetry(fn) {
    let delay = BACKOFF_START;
    for (;;) {
      try { return await fn(); } catch (e) {
        if (!isRetryable(e) || closed) throw e;
        say(`retry in ${delay}ms: ${snip(e?.message)}`);
        await sleep(delay);
        delay = Math.min(delay * 2, BACKOFF_CAP);
      }
    }
  }

  const reasonOf = (e) => `status ${statusOf(e) ?? '?'}: ${snip(e?.message)}`;

  async function tick() {
    if (busy) return;
    busy = true;
    try {
      try { await withRetry(flushCard); } catch (e) {
        say(`card flush failed: ${snip(e?.message)}`);
        for (const n of pendingCard?.names || []) { try { outbox.moveToFailed(dir, n, reasonOf(e)); } catch { /* already gone */ } }
        pendingCard = null;
      }
      for (const name of outbox.list(dir)) {
        if (closed) break;
        let op;
        try { op = outbox.read(dir, name); } catch (e) {
          outbox.moveToFailed(dir, name, `unparsable: ${snip(e.message)}`); say(`failed ${name}: unparsable`); continue;
        }
        const h = op && handlers[op.op];
        if (!h) { outbox.moveToFailed(dir, name, `invalid op: ${snip(op?.op)}`); say(`failed ${name}: invalid op`); continue; }
        try {
          const r = await withRetry(() => h(op, name));
          if (r !== HELD) outbox.remove(dir, name);
        } catch (e) {
          if (closed && isRetryable(e)) break; // shutting down: leave the file for the next run
          outbox.moveToFailed(dir, name, reasonOf(e));
          say(`failed ${name}: ${snip(reasonOf(e))}`);
        }
      }
    } finally { busy = false; }
  }

  async function onReady() {
    try { await home(); } catch (e) { say(`ready: home channel fetch failed: ${snip(e?.message)}`); }
    st.connected = true; save();
    say('connected');
  }

  function onDisconnect() { st.connected = false; save(); say('disconnected'); }

  // access.json is re-read on every click/reaction; missing or unreadable means nobody.
  function allowFrom() {
    const a = readJson(path.join(dir, 'access.json'), null)?.allowFrom;
    return new Set(Array.isArray(a) ? a.map(String) : []);
  }

  function writeEvent(ev) {
    const evDir = path.join(dir, 'events');
    fs.mkdirSync(evDir, { recursive: true });
    const name = `${ev.ts}-${crypto.randomBytes(4).toString('hex')}.json`;
    fs.writeFileSync(path.join(evDir, `${name}.tmp`), JSON.stringify(ev));
    fs.renameSync(path.join(evDir, `${name}.tmp`), path.join(evDir, name));
  }

  async function onInteraction(i) {
    const id = i?.customId;
    if (typeof id !== 'string' || !id.startsWith('ab:')) return;
    if (!allowFrom().has(String(i.user?.id))) {
      try { await i.reply({ content: 'Not authorized.', flags: 64 }); } catch (e) { say(`reply failed: ${snip(e?.message)}`); }
      say(`click ${snip(id)}: not authorized`);
      return;
    }
    try { await i.deferUpdate(); } catch (e) { say(`ack failed: ${snip(e?.message)}`); }
    const ts = now();
    const base = { user: i.user?.id, message_id: i.message?.id, ts };
    const m = /^ab:perm:(.+):(allow|deny)$/.exec(id);
    if (m) writeEvent({ type: 'perm', key: m[1], choice: m[2], ...base });
    else writeEvent({ type: 'click', custom_id: id, user: base.user, message_id: base.message_id, channel_id: i.channelId, ts });
    say(`event ${snip(id)}`);
  }

  async function onReaction(reaction, user) {
    if (reaction?.partial) reaction = await reaction.fetch();
    if (user?.partial) user = await user.fetch();
    if (!user || user.bot || !allowFrom().has(String(user.id))) return;
    const emoji = String(reaction.emoji?.name ?? '').replace(/\uFE0F/g, '');
    if (!REACT_EMOJI.has(emoji)) return;
    let msg = reaction.message;
    if (msg?.partial) msg = await msg.fetch();
    if (!msg || msg.author?.id !== client.user?.id) return;
    const home = cfg().channel;
    if (!home || (msg.channel?.id !== home && msg.channel?.parentId !== home)) return;
    const excerpt = String(msg.content ?? '').replace(/\s+/g, ' ').trim().slice(0, 80);
    writeEvent({ type: 'react', emoji: emoji === '▶' || emoji === '⏭' ? `${emoji}\uFE0F` : emoji, message_id: msg.id, excerpt, user: String(user.id), ts: now() });
    say(`react ${emoji}`);
    if (!msg.reactions?.cache?.get('👀')?.me) {
      try { await msg.react('👀'); } catch (e) { say(`react failed: ${snip(e?.message)}`); }
    }
  }

  // Wire the client: components and reactions; no message listener.
  function attach() {
    client.on('interactionCreate', (i) => { onInteraction(i).catch((e) => say(`interaction: ${snip(e?.message)}`)); });
    client.on('messageReactionAdd', (r, u) => { onReaction(r, u).catch((e) => say(`reaction: ${snip(e?.message)}`)); });
    const ready = () => { onReady().catch(() => {}); };
    client.on('clientReady', ready);
    client.on('ready', ready);
    client.on('shardReady', ready);
    client.on('shardResume', ready);
    client.on('shardDisconnect', onDisconnect);
    client.on('error', (e) => say(`client error: ${snip(e?.message)}`));
  }

  function close() { closed = true; }

  return { tick, onInteraction, onReaction, onReady, onDisconnect, attach, close, TICK_MS };
}

function main() {
  const dir = process.argv[2];
  if (!dir) { console.error('usage: node bridge.js <dir>'); process.exit(2); }
  fs.mkdirSync(dir, { recursive: true });
  const token = readToken(dir);
  if (!token) { console.error('no DISCORD_BOT_TOKEN in <dir>/.env'); process.exit(2); }

  const scrub = (m) => String(m ?? '').split(token).join('***').replace(/\s+/g, ' ').slice(0, BODY_MAX);
  const logFile = path.join(dir, 'bridge.log');
  const log = (line) => { try { fs.appendFileSync(logFile, `${new Date().toISOString()} ${line}\n`); } catch { /* log is best effort */ } };
  const pidFile = path.join(dir, 'bridge.pid');
  fs.writeFileSync(pidFile, String(process.pid));
  let timer;
  let bridge;
  const cleanup = () => { try { fs.rmSync(pidFile, { force: true }); } catch { /* gone */ } };
  process.on('exit', cleanup);
  for (const sig of ['SIGTERM', 'SIGINT']) {
    process.on(sig, () => { clearInterval(timer); bridge?.close(); try { stateLib.write(dir, { ...stateLib.read(dir), connected: false }); } catch { /* ok */ } process.exit(0); });
  }

  const { Client, GatewayIntentBits: I, Partials } = require('discord.js');
  const client = new Client({
    intents: [I.Guilds, I.GuildMessages, I.GuildMessageReactions, I.DirectMessages, I.DirectMessageReactions],
    partials: [Partials.Message, Partials.Channel, Partials.Reaction, Partials.User],
  });
  bridge = createBridge({ dir, client, log });
  bridge.attach();
  timer = setInterval(() => { bridge.tick().catch((e) => log(`tick error: ${scrub(e?.message)}`)); }, TICK_MS);
  client.login(token).catch((e) => { log(`login failed: ${scrub(e?.message)}`); process.exit(1); });
}

module.exports = { createBridge, readToken };
if (require.main === module) main();
