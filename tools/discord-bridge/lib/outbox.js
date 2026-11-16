'use strict';
const fs = require('node:fs');
const path = require('node:path');

const dirOf = (dir) => path.join(dir, 'outbox');

// Outbox file names in send order (13-digit ts prefix sorts lexically).
function list(dir) {
  let names;
  try { names = fs.readdirSync(dirOf(dir), { withFileTypes: true }); } catch { return []; }
  return names.filter((e) => e.isFile() && e.name.endsWith('.json')).map((e) => e.name).sort();
}

function read(dir, name) {
  return JSON.parse(fs.readFileSync(path.join(dirOf(dir), name), 'utf8'));
}

function remove(dir, name) {
  fs.rmSync(path.join(dirOf(dir), name), { force: true });
}

function moveToFailed(dir, name, reason) {
  const failed = path.join(dirOf(dir), 'failed');
  fs.mkdirSync(failed, { recursive: true });
  fs.writeFileSync(path.join(failed, `${name}.err`), `${reason}\n`);
  fs.renameSync(path.join(dirOf(dir), name), path.join(failed, name));
}

module.exports = { list, read, remove, moveToFailed };
