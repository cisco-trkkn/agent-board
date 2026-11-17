'use strict';
// Slash commands and idea/new-spec forms, shared by the ops bridge and the project bridges.
// Exports: payload(ops), handle(i, ctx), inboxText(data), fence(text) (escapes ``` for code blocks).
// handle(i, ctx) gets the bridge's ctx: {dir, ops, views, allowFrom, writeEvent, now, say, snip, answer}.
const path = require('node:path');

const REPLY_MAX = 2000;
const PROJECT_MAX = 60; // ab:modal:new-spec:<project> stays under Discord's 100-char custom_id limit
const ACTIONS = new Set(['pause', 'resume', 'idea', 'new-spec']); // rejected up front; read commands answer it and still write their read event
const NEEDS_PROJECT = new Set(['queue', 'pause', 'resume', 'idea', 'new-spec']);
const DESCRIPTIONS = {
  status: 'Show the board status', queue: 'Show a project queue', pause: "Pause a project's queue",
  resume: "Resume a project's queue", idea: 'Add an idea', 'new-spec': 'Ask the lead for a new spec', approvals: 'List open decisions',
};
const NOT_SET_UP = 'Ops bot not set up (tmux-ctl discord ops-channels).';
const FORMS = {
  idea: { title: 'New idea', inputs: [['title', 'Title', 1, 100], ['text', 'Text', 2, 1000]], ack: (p) => `💡 noted for ${p}` },
  'new-spec': { title: 'New spec request', inputs: [['what', 'What', 1, 100], ['why', 'Why', 2, 1000]], ack: (p) => `Sent to ${p}'s lead.` },
};

function payload(ops) {
  return Object.keys(DESCRIPTIONS).map((name) => {
    const c = { name, description: DESCRIPTIONS[name], type: 1 };
    if (name !== 'approvals') {
      c.options = [{ name: 'project', description: 'Project name', type: 3, max_length: PROJECT_MAX, required: ops && NEEDS_PROJECT.has(name) }];
    }
    return c;
  });
}

// The list behind the Inbox button and /approvals.
function inboxText(data) {
  const list = Array.isArray(data.approvals) ? data.approvals : [];
  if (!list.length) return 'No open decisions.';
  const lines = []; let total = 0;
  for (const a of list) {
    const l = `${a.project} · ${a.title}${a.link ? ` ${a.link}` : ''}`;
    if (total + l.length + 1 > REPLY_MAX - 30) { lines.push(`… ${list.length - lines.length} more, see board`); break; }
    lines.push(l); total += l.length + 1;
  }
  return lines.join('\n');
}

// Escape ``` inside text that goes in a code block.
const fence = (t) => String(t).replace(/`{3,}/g, (m) => `\`\u200b${m.slice(1).match(/`{1,2}/g).join('\u200b')}`);
const fenced = (t, ctx) => `\`\`\`\n${ctx.fence(t).slice(0, 1900)}\n\`\`\``;

async function handleCommand(i, ctx) {
  const name = i.commandName;
  const what = `/${name}`;
  const user = String(i.user?.id);
  const event = (e) => ctx.writeEvent({ ...e, user, ts: ctx.now() });
  const own = path.basename(ctx.dir);
  const given = i.options?.getString?.('project') || null;
  const project = given || (ctx.ops ? null : own);

  if (NEEDS_PROJECT.has(name) && !project) { await ctx.answer(i, 'Pick a project.'); return; }
  const data = ctx.views();
  const unknown = project && (ctx.ops || given) && Array.isArray(data?.projects) && !data.projects.includes(project);
  if (unknown && ACTIONS.has(name)) { await ctx.answer(i, `Unknown project: ${project}`); return; }

  if (name === 'idea' || name === 'new-spec') {
    const f = FORMS[name];
    await i.showModal({
      custom_id: `ab:modal:${name}:${project}`, title: f.title,
      components: f.inputs.map(([id, label, style, max]) => ({ type: 1, components: [{ type: 4, custom_id: id, label, style, max_length: max, required: true }] })),
    });
    return;
  }
  if (name === 'pause' || name === 'resume') {
    await ctx.answer(i, `Sent to ${project}.`);
    event({ type: 'slash', command: name, project });
    return;
  }
  // Read-only: answered from views.json.
  if (!data) { await ctx.answer(i, ctx.ops ? 'Board data not available yet.' : NOT_SET_UP); event({ type: 'read', what }); return; }
  if (name === 'approvals') await ctx.answer(i, inboxText(data));
  else if (unknown) await ctx.answer(i, `Unknown project: ${project}`);
  else if (name === 'status') await ctx.answer(i, project ? (data.status?.[project] ?? `No status for ${project}.`) : (data.status?._all ?? 'No status yet.'));
  else await ctx.answer(i, fenced(data.queue?.[project] ?? `No queue for ${project}.`, ctx)); // queue
  event({ type: 'read', what });
}

async function handleModal(i, ctx, m) {
  const [, form, project] = m;
  const f = FORMS[form];
  const val = (id) => String(i.fields.getTextInputValue(id) ?? '').trim();
  const fields = Object.fromEntries(f.inputs.map(([id]) => [id, val(id)]));
  const empty = f.inputs.find(([id]) => !fields[id]);
  if (empty) { await ctx.answer(i, `Empty ${empty[0]}.`); return; }
  await ctx.answer(i, f.ack(project));
  ctx.writeEvent({ type: 'modal', form, project, fields, user: String(i.user?.id), ts: ctx.now() });
}

// True when the interaction was a command or modal (handled here).
async function handle(i, ctx) {
  const isCmd = i?.isChatInputCommand?.();
  const m = i?.isModalSubmit?.() ? /^ab:modal:(idea|new-spec):(.+)$/.exec(String(i.customId)) : null;
  if (!isCmd && !m) return false;
  const what = isCmd ? `/${i.commandName}` : i.customId;
  if (!ctx.allowFrom().has(String(i.user?.id))) {
    try { await i.reply({ content: 'Not authorized.', flags: 64 }); } catch (e) { ctx.say(`reply failed: ${ctx.snip(e?.message)}`); }
    ctx.writeEvent({ type: 'rejected', what, user: String(i.user?.id), ts: ctx.now() });
    ctx.say(`${ctx.snip(what)}: not authorized`);
    return true;
  }
  if (isCmd) await handleCommand(i, ctx); else await handleModal(i, ctx, m);
  ctx.say(`command ${ctx.snip(what)}`);
  return true;
}

module.exports = { payload, handle, inboxText, fence };
