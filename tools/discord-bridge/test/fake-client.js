'use strict';
// Fake discord.js client for tests: records every call in calls[], injects failures.
const { EventEmitter } = require('node:events');

class FakeClient extends EventEmitter {
  constructor({ guildId = 'G1' } = {}) {
    super();
    this.guildId = guildId;
    this.calls = [];
    this.failures = {};
    this.seq = 0;
    this.chans = new Map();
    this.messages = new Map();
    this.presences = [];
    this.presenceError = null;
    this.user = { id: 'BOT', setPresence: (p) => { this.presences.push(p); if (this.presenceError) throw this.presenceError; return {}; } };
    this.channels = { fetch: (id) => this._fetchChannel(id) };
    this.application = { commands: { set: async (payload, guildId) => { this._record('setCommands', guildId, payload); this._maybeFail('setCommands'); return payload; } } };
  }

  // failNext('send', {status: 500}) fails the next call of that method; count repeats it.
  failNext(method, { status, code, message, plain, name, cause } = {}, count = 1) {
    (this.failures[method] ||= []).push(...Array.from({ length: count }, () => ({ status, code, message, plain, name, cause })));
  }

  _maybeFail(method) {
    const f = (this.failures[method] || []).shift();
    if (!f) return;
    const err = new Error(f.message || `fake ${method} failure`);
    if (f.status !== undefined) err.status = f.status; else if (!f.plain) err.code = 'ECONNRESET'; // plain: a bare Error, no status or code
    if (f.code !== undefined) err.code = f.code;
    if (f.name) err.name = f.name;
    if (f.cause) err.cause = f.cause;
    throw err;
  }

  _record(method, target, payload) { this.calls.push({ method, target, payload }); }

  callsOf(method) { return this.calls.filter((c) => c.method === method); }

  _newId(prefix) { return `${prefix}${++this.seq}`; }

  _makeMessage(channelId, payload) {
    const msg = {
      id: this._newId('m'), channelId, payload, pinned: false,
      author: { id: this.user.id }, content: payload?.content ?? '',
      channel: { id: channelId, parentId: this.chans.get(channelId)?.parentId ?? null },
      reactions: { cache: new Map() },
      react: async (e) => { this._record('react', msg.id, e); msg.reactions.cache.set(e, { me: true }); },
      edit: async (p) => { this._record('edit', msg.id, p); this._maybeFail('edit'); this._gone(msg); msg.payload = p; if (p?.content !== undefined) msg.content = p.content; return msg; },
      pin: async () => { this._record('pin', msg.id); this._maybeFail('pin'); msg.pinned = true; },
    };
    this.messages.set(msg.id, msg);
    return msg;
  }

  _gone(msg) {
    if (msg.deleted) { const e = new Error('Unknown Message'); e.status = 404; e.code = 10008; throw e; }
  }

  _makeChannel(id, isThread = false, parentId = null) {
    const ch = {
      id, guildId: this.guildId, isThread, parentId,
      send: async (p) => { this._record('send', id, p); this._maybeFail('send'); return this._makeMessage(id, p); },
      messages: {
        fetch: async (mid) => {
          this._record('fetchMessage', mid); this._maybeFail('fetchMessage');
          const m = this.messages.get(mid);
          if (!m || m.deleted) { const e = new Error('Unknown Message'); e.status = 404; e.code = 10008; throw e; }
          return m;
        },
      },
    };
    if (isThread) {
      ch.setArchived = async (v) => { this._record('setArchived', id, v); this._maybeFail('setArchived'); ch.archived = v; };
    } else {
      ch.threads = {
        create: async (o) => {
          this._record('createThread', id, o); this._maybeFail('createThread');
          const t = this._makeChannel(this._newId('t'), true);
          t.name = o.name;
          this.chans.set(t.id, t);
          return t;
        },
      };
    }
    this.chans.set(id, ch);
    return ch;
  }

  async _fetchChannel(id) {
    this._record('fetchChannel', id); this._maybeFail('fetchChannel');
    return this.chans.get(id) || this._makeChannel(id);
  }
}

// A standalone message (any author/channel); react() records into .reacted.
function fakeMessage({ id = 'mx', authorId = 'BOT', content = '', channelId = 'C1', parentId = null, partial = false, hasEyes = false } = {}) {
  const m = { id, author: { id: authorId }, content, channel: { id: channelId, parentId }, partial, reacted: [], reactions: { cache: new Map() } };
  if (hasEyes) m.reactions.cache.set('👀', { me: true });
  m.react = async (e) => { m.reacted.push(e); m.reactions.cache.set(e, { me: true }); };
  m.fetch = async () => { m.partial = false; return m; };
  return m;
}

// A fake reaction; fetch() resolves a partial one. user is {id, bot?}.
function fakeReaction({ emoji, message, partial = false }) {
  const r = { emoji: { name: emoji }, message, partial };
  r.fetch = async () => { r.partial = false; return r; };
  return r;
}

// A fake interaction: a component click or other. ephemeral: the clicked message is an ephemeral reply
// (flags 64); values: the picked options of a select menu. reply/followUp/update are recorded in replies.
function fakeInteraction({ customId, user = 'U9', messageId = 'm1', channelId = 'C1', onDefer, values, ephemeral = false } = {}) {
  const i = { customId, user: { id: user }, message: { id: messageId, flags: ephemeral ? 64 : 0 }, channelId, replies: [], updates: [], followUps: [], deferred: 0 };
  if (values) i.values = values;
  i.deferUpdate = async () => { if (onDefer) onDefer(); i.deferred++; };
  i.reply = async (x) => { i.replies.push(x); };
  i.followUp = async (x) => { i.followUps.push(x); };
  i.update = async (x) => { i.updates.push(x); };
  return i;
}

// A chat-input command; options is {name: value}.
function fakeCommand({ name, options = {}, user = 'U1', channelId = 'C1' } = {}) {
  const i = { commandName: name, user: { id: user }, channelId, replies: [], updates: [], modals: [], deferred: 0 };
  i.isChatInputCommand = () => true;
  i.isModalSubmit = () => false;
  i.options = { getString: (n) => (n in options ? options[n] : null) };
  i.reply = async (x) => { i.replies.push(x); };
  i.showModal = async (m) => { i.modals.push(m); };
  return i;
}

// A modal submit; fields is {inputId: value}.
function fakeModal({ customId, fields = {}, user = 'U1' } = {}) {
  const i = { customId, user: { id: user }, replies: [], updates: [] };
  i.isChatInputCommand = () => false;
  i.isModalSubmit = () => true;
  i.fields = { getTextInputValue: (n) => String(fields[n] ?? '') };
  i.reply = async (x) => { i.replies.push(x); };
  return i;
}

module.exports = { fakeCommand, fakeModal, FakeClient, fakeInteraction, fakeMessage, fakeReaction };
