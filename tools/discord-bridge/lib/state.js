'use strict';
const fs = require('node:fs');
const path = require('node:path');

const file = (dir) => path.join(dir, 'bridge-state.json');
const defaults = () => ({ card_message_id: null, threads: {}, guild_id: null, connected: false, prompts: {}, posts: {}, approvals: {}, dialogs: {}, reply_armed: {} });

function read(dir) {
  try { return { ...defaults(), ...JSON.parse(fs.readFileSync(file(dir), 'utf8')) }; } catch { return defaults(); }
}

// Atomic: write .tmp then rename.
function write(dir, st, ts = Date.now()) {
  const tmp = `${file(dir)}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ ...st, ts }));
  fs.renameSync(tmp, file(dir));
}

module.exports = { read, write, defaults };
