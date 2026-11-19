'use strict';
// Agent Board discord bridge: consumes <dir>/outbox, keeps the pinned card and threads,
// writes <dir>/bridge-state.json, turns ab: component clicks into <dir>/events/*.json.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const outbox = require('./lib/outbox');
const stateLib = require('./lib/state');
const commands = require('./lib/commands');

const CARD_MIN_MS = 30000;
const BACKOFF_START = 1000;
const BACKOFF_CAP = 60000;
const TICK_MS = 2000;
const BODY_MAX = 80;
const UNKNOWN_MESSAGE = 10008;
const HELD = Symbol('held');
const PROMPT_MAX = 1500;
const PROMPTS_KEEP = 200;
const APPROVALS_KEEP = 500;
const FILES_PAGE = 10;
const SELECT_MAX = 25;
const REPLY_MAX = 2000;
const REPLY_TEXT_MAX = 1000;
const DIALOGS_KEEP = 200;
// The dialog custom-id grammar: ab:dlg:<key>:<n>, :<n>:confirm|cancel, :t<n>, :submit, :reply.
const DLG_RE = /^ab:dlg:(p[0-9]+-[0-9a-f]{16}):(?:(t)?([0-9]{1,2})(?::(confirm|cancel))?|(submit|reply))$/;
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

function createBridge({ dir, client, ops = false, log = () => {}, now = Date.now, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
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
  // The channel a bridge.json key names: `channel` in project mode, `command_center` / `approvals` in ops mode.
  const chan = async (field) => {
    const channel = cfg()[field];
    if (!channel) throw new Error(`bridge.json has no ${field}`);
    const ch = await client.channels.fetch(channel);
    if (ch?.guildId && st.guild_id !== ch.guildId) { st.guild_id = ch.guildId; save(); }
    return ch;
  };
  const home = () => chan(ops ? 'command_center' : 'channel');
  const CARD_ROW = [{ type: 1, components: [
    { type: 2, style: 4, label: 'Pause all', custom_id: 'ab:ops:pause-all' },
    { type: 2, style: 3, label: 'Resume all', custom_id: 'ab:ops:resume-all' },
    { type: 2, style: 2, label: 'Inbox', custom_id: 'ab:ops:inbox' },
  ] }];
  const cardPayload = (text) => ({ content: text, allowedMentions: { parse: [] }, ...(ops ? { components: CARD_ROW } : {}) });

  async function createCard(text) {
    const ch = await home();
    const msg = await ch.send(cardPayload(text));
    st.card_message_id = msg.id; save();
    lastCardAt = now();
    await msg.pin();
  }

  async function doCard(text) {
    if (!st.card_message_id) return createCard(text);
    const ch = await home();
    try {
      const msg = await ch.messages.fetch(st.card_message_id);
      await msg.edit(cardPayload(text));
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

  // Keep only the newest `keep` entries of a key -> message id map (insertion order).
  function trim(map, keep) {
    for (const k of Object.keys(map).slice(0, Math.max(0, Object.keys(map).length - keep))) delete map[k];
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
    if (Array.isArray(op.buttons) && op.buttons.length) {
      payload.components = [{ type: 1, components: op.buttons.slice(0, 5).map((b) => ({ type: 2, style: Number(b.style) || 2, label: String(b.label).slice(0, 80), custom_id: String(b.custom_id) })) }];
    }
    const sent = await target.send(payload);
    if (op.key) { st.posts[op.key] = sent.id; trim(st.posts, PROMPTS_KEEP); save(); }
    if (op.delete_files === true) {
      let tmpRoot = null;
      try { tmpRoot = fs.realpathSync(path.join(dir, 'tmp')) + path.sep; } catch { /* no tmp/ */ }
      for (const p of paths) {
        let r;
        try { r = fs.realpathSync(p); } catch { continue; } // already gone
        if (tmpRoot && r.startsWith(tmpRoot)) { try { fs.unlinkSync(r); } catch { /* already gone */ } }
        else say(`delete_files: kept ${r} (outside tmp/)`);
      }
    }
    say(`post ${op.thread_key || 'home'} ${snip(op.text)}`);
  }

  const toRows = (rows) => rows.map((r) => ({ type: 1, components: r.map((b) => ({ type: 2, style: Number(b.style) || 2, label: String(b.label).slice(0, 80), custom_id: String(b.custom_id) })) }));

  async function opDialog(op) {
    const c = cfg();
    let text = String(op.text ?? '');
    const payload = { content: '', allowedMentions: { parse: [] }, components: toRows(Array.isArray(op.rows) ? op.rows : []) };
    if (op.mention_user && c.user) {
      text = `<@${c.user}> ${text}`;
      payload.allowedMentions = { users: [String(c.user)] };
    }
    payload.content = text.slice(0, 2000);
    const ch = await (ops ? chan('approvals') : home());
    const sent = await ch.send(payload);
    st.dialogs[op.key] = sent.id;
    trim(st.dialogs, DIALOGS_KEEP);
    save();
    say(`dialog ${snip(op.key)}`);
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
    trim(st.prompts, PROMPTS_KEEP);
    save();
    say(`prompt ${snip(op.key)} ${snip(op.tool)}`);
  }

  const cut = (t, n) => (t.length > n ? t.slice(0, n - 1) + '…' : t);

  async function opApproval(op) {
    if (!ops) throw new Error('approval op needs ops mode');
    const c = cfg();
    const key = String(op.key);
    const row = (buttons) => ({ type: 1, components: buttons });
    const comps = [];
    if (op.kind === 'perm') {
      comps.push(row([
        { type: 2, style: 3, label: 'Allow once', custom_id: `ab:ops:allow:${key}` },
        { type: 2, style: 4, label: 'Deny', custom_id: `ab:ops:deny:${key}` },
      ]));
    } else if (op.kind === 'merge') {
      comps.push(row([
        { type: 2, style: 3, label: 'Merge', custom_id: `ab:ops:merge:${key}` },
        { type: 2, style: 2, label: 'Keep branch', custom_id: `ab:ops:keep:${key}` },
        { type: 2, style: 1, label: 'Show files', custom_id: `ab:ops:files:${key}:0` },
      ]));
      const files = views()?.evidence?.[key]?.files;
      if (Array.isArray(files) && files.length) {
        comps.push(row([{
          type: 3, custom_id: `ab:ops:diff:${key}`, placeholder: 'Show a diff',
          options: files.slice(0, SELECT_MAX).map((f) => ({ label: cut(String(f.path), 100), value: String(f.path).slice(0, 100) })),
        }]));
      }
    } else if (op.link) {
      const project = op.project || views()?.approvals?.find((a) => a.key === key)?.project || 'project';
      comps.push(row([{ type: 2, style: 5, label: cut(`Reply in ${project}`, 80), url: String(op.link) }]));
    }
    let text = String(op.text ?? '');
    const payload = { allowedMentions: { parse: [] } };
    if (op.mention_user && c.user) {
      text = `<@${c.user}> ${text}`;
      payload.allowedMentions = { users: [String(c.user)] };
    }
    payload.content = text.slice(0, REPLY_MAX);
    if (comps.length) payload.components = comps;
    const ch = await chan('approvals');
    const msg = await ch.send(payload);
    st.approvals[key] = msg.id;
    trim(st.approvals, APPROVALS_KEEP);
    save();
    say(`approval ${snip(key)} ${snip(op.kind)}`);
  }

  async function opEdit(op) {
    const key = op.key;
    const where = [[st.prompts, home], [st.posts, home], [st.approvals, () => chan('approvals')], [st.dialogs, () => (ops ? chan('approvals') : home())]].find(([m]) => m[key]);
    if (!where) { say(`edit ${snip(key)}: no message`); return; }
    const ch = await where[1]();
    try {
      const msg = await ch.messages.fetch(where[0][key]);
      await msg.edit({ content: String(op.text ?? '').slice(0, 2000), components: Array.isArray(op.rows) ? toRows(op.rows) : [] });
    } catch (e) {
      if (e?.code !== UNKNOWN_MESSAGE) throw e;
      say(`edit ${snip(key)}: no message`);
    }
  }

  // Presence: the bot's custom status. The last text is re-applied on every (re)connect.
  const PRESENCE_MAX = 128;
  let presenceText = typeof st.presence === 'string' && st.presence ? st.presence : null;
  function applyPresence() {
    if (presenceText === null || !client.user?.setPresence) return;
    client.user.setPresence({ activities: [{ type: 4, name: 'custom', state: presenceText }], status: 'online' });
  }
  async function opPresence(op) {
    if (typeof op.text !== 'string' || !op.text) throw new Error('presence text must be a non-empty string');
    presenceText = op.text.slice(0, PRESENCE_MAX);
    st.presence = presenceText; save();   // a restarted process re-applies it on ready
    try { applyPresence(); say(`presence ${snip(presenceText)}`); } catch (e) { say(`presence failed: ${snip(e?.message)}`); }
  }
  const handlers = { presence: opPresence, approval: opApproval, dialog: opDialog, prompt: opPrompt, edit: opEdit, post: opPost, card: opCard, thread: opThread, archive: opArchive };

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

  // Slash commands: once per connection, in the guild of the home channel. Failure is logged only.
  let registered = false;
  async function register(ch) {
    if (registered || !ch?.guildId) return;
    registered = true;
    try { await client.application.commands.set(commands.payload(ops), ch.guildId); say('commands registered'); } catch (e) {
      registered = false;
      say(`commands registration failed: ${snip(e?.message)}`);
    }
  }

  async function onReady() {
    let ch = null;
    try { ch = await home(); } catch (e) { say(`ready: home channel fetch failed: ${snip(e?.message)}`); }
    st.connected = true; save();
    await register(ch);
    try { applyPresence(); } catch (e) { say(`presence failed: ${snip(e?.message)}`); }
    say('connected');
  }

  function onDisconnect() { registered = false; st.connected = false; save(); say('disconnected'); }

  // access.json is re-read on every click/reaction; missing or unreadable means nobody.
  function allowFrom() {
    const a = readJson(path.join(dir, 'access.json'), null)?.allowFrom;
    return new Set(Array.isArray(a) ? a.map(String) : []);
  }

  // views.json: the ops dir's own, or from a project dir the sibling _ops dir's.
  const views = () => {
    const v = readJson(ops ? path.join(dir, 'views.json') : path.join(path.dirname(dir), '_ops', 'views.json'), null);
    return v && typeof v === 'object' ? v : null;
  };

  function writeEvent(ev) {
    const evDir = path.join(dir, 'events');
    fs.mkdirSync(evDir, { recursive: true });
    const name = `${ev.ts}-${crypto.randomBytes(4).toString('hex')}.json`;
    fs.writeFileSync(path.join(evDir, `${name}.tmp`), JSON.stringify(ev));
    fs.renameSync(path.join(evDir, `${name}.tmp`), path.join(evDir, name));
  }

  const EPHEMERAL = 64;
  const isEphemeral = (i) => { const f = i.message?.flags; return typeof f === 'number' ? (f & EPHEMERAL) !== 0 : !!f?.has?.(EPHEMERAL); };
  const NO_MENTIONS = { parse: [] };
  // Ephemeral answer to a click: a new reply, or an update of the ephemeral message the click came from.
  async function answer(i, content, components) {
    const body = { content: cut(content, REPLY_MAX), allowedMentions: NO_MENTIONS, ...(components ? { components } : {}) };
    try {
      if (isEphemeral(i)) await i.update({ ...body, components: components || [] });
      else await i.reply({ ...body, flags: EPHEMERAL });
    } catch (e) { say(`reply failed: ${snip(e?.message)}`); }
  }

  const fence = commands.fence;

  function filesPage(key, page, data) {
    const files = data?.evidence?.[key]?.files;
    if (!Array.isArray(files) || !files.length) return { content: 'No file list for this approval.' };
    const pages = Math.ceil(files.length / FILES_PAGE);
    const p = Math.min(Math.max(page, 0), pages - 1);
    let body = files.slice(p * FILES_PAGE, (p + 1) * FILES_PAGE).map((f) => `${f.path} +${f.add} -${f.del}`).join('\n');
    body = cut(body, REPLY_MAX - 30);
    const btns = [];
    if (p > 0) btns.push({ type: 2, style: 2, label: 'Prev', custom_id: `ab:ops:files:${key}:${p - 1}` });
    if (p < pages - 1) btns.push({ type: 2, style: 2, label: 'Next', custom_id: `ab:ops:files:${key}:${p + 1}` });
    return { content: `${body}\npage ${p + 1}/${pages}`, components: btns.length ? [{ type: 1, components: btns }] : [] };
  }

  // ab:ops:* clicks in ops mode. Read-only buttons are answered here from views.json; actions become click events.
  async function onOpsInteraction(i, id) {
    const user = String(i.user?.id);
    const ev = (e) => writeEvent({ ...e, user, ts: now() });
    const read = (what) => { ev({ type: 'read', what }); say(`read ${snip(what)}`); };
    let m;
    if (id === 'ab:ops:inbox' || (m = /^ab:ops:files:([^:]+):(\d+)$/.exec(id)) || (m = /^ab:ops:diff:([^:]+)$/.exec(id))) {
      const data = views();
      if (!data || typeof data !== 'object') { await answer(i, 'Board data not available yet.'); read(id); return; }
      if (id === 'ab:ops:inbox') await answer(i, commands.inboxText(data));
      else if (id.startsWith('ab:ops:files:')) { const r = filesPage(m[1], Number(m[2]), data); await answer(i, r.content, r.components); }
      else {
        const ev0 = data.evidence?.[m[1]];
        const want = String(i.values?.[0] ?? '');
        const file = ev0?.files?.find((f) => String(f.path).slice(0, 100) === want);
        const d = ev0?.diffs?.[file ? file.path : want];
        await answer(i, typeof d === 'string' ? `\`\`\`diff\n${fence(d).slice(0, 1850)}\n\`\`\`` : `No diff stored for ${cut(want, 200)}.`);
      }
      read(id);
      return;
    }
    if (id === 'ab:ops:pause-all') {
      await answer(i, 'Pause every running queue?', [{ type: 1, components: [
        { type: 2, style: 4, label: 'Confirm pause all', custom_id: `ab:ops:pause-all-confirm:${now()}` },
      ] }]);
      read(id);
      return;
    }
    if (id.startsWith('ab:ops:pause-all-confirm:') || id === 'ab:ops:resume-all') await answer(i, 'Sent.', []);
    else { try { await i.deferUpdate(); } catch (e) { say(`ack failed: ${snip(e?.message)}`); } }
    ev({ type: 'click', custom_id: id, message_id: i.message?.id, channel_id: i.channelId });
    say(`event ${snip(id)}`);
  }

  // A plain {type:2,...} button of the clicked message's rows, from a discord.js component or a plain object.
  const rowsOf = (i) => (i.message?.components || []).map((r) => {
    const j = typeof r.toJSON === 'function' ? r.toJSON() : r;
    return { ...j, components: (j.components || []).map((c) => (typeof c.toJSON === 'function' ? c.toJSON() : { ...c })) };
  });

  // ab:dlg:* clicks. A style-4 option asks for confirmation; toggles flip in place; submit carries the picks;
  // reply arms the message for one reply. Everything else is deferred and written as a click event.
  async function onDialogInteraction(i, id, m) {
    const [, key, isToggle, num, confirm, word] = m;
    const user = String(i.user?.id);
    const ts = now();
    if (word === 'reply') {
      const mid = String(i.message?.id);
      st.reply_armed[mid] = key;
      trim(st.reply_armed, DIALOGS_KEEP);
      save();
      await answer(i, 'Reply to that message with your answer.');
      say(`reply armed ${snip(key)}`);
      return;
    }
    if (isToggle && !confirm) {
      const rows = rowsOf(i);
      for (const r of rows) for (const c of r.components) {
        if (c.custom_id === id) c.style = c.style === 3 ? 2 : 3;
      }
      try { await i.update({ components: rows }); } catch (e) { say(`update failed: ${snip(e?.message)}`); }
      return;
    }
    if (!isToggle && num !== undefined && confirm === 'cancel') { await answer(i, 'Cancelled.', []); return; }
    if (!isToggle && num !== undefined && confirm === 'confirm') {
      await answer(i, 'Sent.', []);
      writeEvent({ type: 'click', custom_id: id, user, message_id: i.message?.id, channel_id: i.channelId, ts });
      say(`event ${snip(id)}`);
      return;
    }
    if (!isToggle && num !== undefined && i.component?.style === 4) {
      const label = String(i.component.label ?? '').replace(/^\d+\. /, '');
      await answer(i, `this allows ${label} from now on`, [{ type: 1, components: [
        { type: 2, style: 4, label: 'Confirm', custom_id: `${id}:confirm` },
        { type: 2, style: 2, label: 'Cancel', custom_id: `${id}:cancel` },
      ] }]);
      return;
    }
    try { await i.deferUpdate(); } catch (e) { say(`ack failed: ${snip(e?.message)}`); }
    const ev = { type: 'click', custom_id: id, user, message_id: i.message?.id, channel_id: i.channelId, ts };
    if (word === 'submit') {
      ev.picks = rowsOf(i).flatMap((r) => r.components)
        .filter((c) => c.style === 3 && /:t[0-9]{1,2}$/.test(String(c.custom_id)))
        .map((c) => Number(/:t([0-9]{1,2})$/.exec(c.custom_id)[1])).sort((a, b) => a - b);
    }
    writeEvent(ev);
    say(`event ${snip(id)}`);
  }

  // A reply to an armed dialog message by an allowlisted user becomes one reply event; the message is disarmed.
  async function onMessage(msg) {
    if (!msg || msg.author?.bot) return;
    const ref = msg.reference?.messageId;
    if (!ref || !Object.hasOwn(st.reply_armed, ref)) return;
    const uid = String(msg.author?.id);
    if (!allowFrom().has(uid)) return;
    const text = String(msg.content ?? '').trim().slice(0, REPLY_TEXT_MAX);
    if (!text) return;
    const key = st.reply_armed[ref];
    delete st.reply_armed[ref]; save();
    writeEvent({ type: 'reply', key, text, user: uid, message_id: String(ref), ts: now() });
    say(`reply ${snip(key)}`);
  }

  async function onInteraction(i) {
    if (await commands.handle(i, ctx)) return;
    const id = i?.customId;
    if (typeof id !== 'string' || !id.startsWith('ab:')) return;
    if (!allowFrom().has(String(i.user?.id))) {
      try { await i.reply({ content: 'Not authorized.', flags: 64 }); } catch (e) { say(`reply failed: ${snip(e?.message)}`); }
      say(`click ${snip(id)}: not authorized`);
      if (ops && id.startsWith('ab:ops:')) writeEvent({ type: 'rejected', what: id, user: String(i.user?.id), ts: now() });
      return;
    }
    const dm = DLG_RE.exec(id);
    if (dm) return onDialogInteraction(i, id, dm);
    if (ops && id.startsWith('ab:ops:')) return onOpsInteraction(i, id);
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

  // Wire the client: components, reactions and messages (replies to armed dialogs).
  function attach() {
    client.on('interactionCreate', (i) => { onInteraction(i).catch((e) => say(`interaction: ${snip(e?.message)}`)); });
    client.on('messageCreate', (m) => { onMessage(m).catch((e) => say(`message: ${snip(e?.message)}`)); });
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

  const ctx = { dir, ops, views, allowFrom, writeEvent, now, say, snip, answer, fence, NO_MENTIONS };
  return { ctx, tick, onInteraction, onReaction, onMessage, onReady, onDisconnect, attach, close, TICK_MS };
}

function main() {
  const dir = process.argv[2];
  if (!dir) { console.error('usage: node bridge.js <dir> [--ops]'); process.exit(2); }
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
    intents: [I.Guilds, I.GuildMessages, I.GuildMessageReactions, I.DirectMessages, I.DirectMessageReactions, I.MessageContent],
    partials: [Partials.Message, Partials.Channel, Partials.Reaction, Partials.User],
  });
  bridge = createBridge({ dir, client, ops: process.argv.includes('--ops'), log });
  bridge.attach();
  timer = setInterval(() => { bridge.tick().catch((e) => log(`tick error: ${scrub(e?.message)}`)); }, TICK_MS);
  client.login(token).catch((e) => { log(`login failed: ${scrub(e?.message)}`); process.exit(1); });
}

module.exports = { createBridge, readToken, DLG_RE };
if (require.main === module) main();
