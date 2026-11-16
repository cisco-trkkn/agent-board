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
    this.channels = { fetch: (id) => this._fetchChannel(id) };
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
      edit: async (p) => { this._record('edit', msg.id, p); this._maybeFail('edit'); this._gone(msg); msg.payload = p; return msg; },
      pin: async () => { this._record('pin', msg.id); this._maybeFail('pin'); msg.pinned = true; },
    };
    this.messages.set(msg.id, msg);
    return msg;
  }

  _gone(msg) {
    if (msg.deleted) { const e = new Error('Unknown Message'); e.status = 404; e.code = 10008; throw e; }
  }

  _makeChannel(id, isThread = false) {
    const ch = {
      id, guildId: this.guildId, isThread,
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

// A fake interaction: a component click or other.
function fakeInteraction({ customId, user = 'U9', messageId = 'm1', channelId = 'C1' } = {}) {
  const i = { customId, user: { id: user }, message: { id: messageId }, channelId, replies: [], deferred: 0 };
  i.deferUpdate = async () => { i.deferred++; };
  i.reply = async (x) => { i.replies.push(x); };
  return i;
}

module.exports = { FakeClient, fakeInteraction };
