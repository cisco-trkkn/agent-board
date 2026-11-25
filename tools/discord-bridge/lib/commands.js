'use strict';
// Slash commands and idea/new-spec forms, shared by the ops bridge and the project bridges.
// Exports: payload(ops), handle(i, ctx), inboxText(data), fence(text) (escapes ``` for code blocks).
// handle(i, ctx) gets the bridge's ctx: {dir, ops, views, allowFrom, writeEvent, now, say, snip, answer}.
const path = require('node:path');

const REPLY_MAX = 2000;
const PROJECT_MAX = 60; // ab:modal:new-spec:<project> stays under Discord's 100-char custom_id limit
const ACTIONS = new Set(['pause', 'resume', 'idea', 'new-spec', 'ideas', 'lead', 'gauth']); // rejected up front; read commands answer it and still write their read event
const NEEDS_PROJECT = new Set(['queue', 'pause', 'resume', 'idea', 'new-spec', 'lead', 'gauth']);
const LEAD_ACTIONS = ['status', 'restart', 'handoff'];
const CONFIRM_TTL_MS = 5 * 60 * 1000; // a /lead Confirm older than this has expired
const COMPONENT_RE = /^ab:(?:lead:(restart|handoff|cancel):(.+):([0-9]+)|(tasks:pick)|gauth:code:(.+)|np:token:([A-Za-z0-9][A-Za-z0-9_-]{0,59}))$/;
// /new-project names: today's project-name rule without '.', at most 60 chars (dev maps '.' to '_' in the session name;
// ab:np:retry:<name>:<step> stays under Discord's 100-char custom_id limit)
const NP_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$/;
const NP_SOURCES = ['new', 'clone', 'folder'];
const NP_BAD_NAME = "Bad name: letters, digits, '_' and '-', starting with a letter or digit, at most 60.";
const DESCRIPTIONS = {
  status: 'Show the board status', queue: 'Show a project queue', pause: "Pause a project's queue",
  resume: "Resume a project's queue", idea: 'Add an idea', 'new-spec': 'Ask the lead for a new spec', ideas: 'Group the open ideas', approvals: 'List open decisions',
  tasks: "Show a project's task list", lead: "Check, restart or hand off a project's lead", gauth: 'Re-authenticate Google for a project',
  'new-project': 'Set up a new project and its own bot',
};
const NOT_SET_UP = 'Ops bot not set up (tmux-ctl discord ops-channels).';
const FORMS = {
  idea: { title: 'New idea', inputs: [['title', 'Title', 1, 100], ['text', 'Text', 2, 1000]], ack: (p) => `💡 noted for ${p}` },
  'new-spec': { title: 'New spec request', inputs: [['what', 'What', 1, 100], ['why', 'Why', 2, 1000]], ack: (p) => `Sent to ${p}'s lead.` },
};

function payload(ops) {
  return Object.keys(DESCRIPTIONS).filter((name) => ops || name !== 'new-project').map((name) => { // /new-project runs in the command center: project bots do not register it
    const c = { name, description: DESCRIPTIONS[name], type: 1 };
    if (name === 'new-project') {
      c.options = [{ name: 'name', description: 'Resume the unfinished setup of this project', type: 3, max_length: PROJECT_MAX, required: false }];
    } else if (name !== 'approvals') {
      c.options = [{ name: 'project', description: 'Project name', type: 3, max_length: PROJECT_MAX, required: ops && NEEDS_PROJECT.has(name) && name !== 'queue' }];
    }
    if (name === 'lead') {
      c.options.unshift({ name: 'action', description: 'What to do', type: 3, required: true, choices: LEAD_ACTIONS.map((v) => ({ name: v, value: v })) });
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

const TASKS_NONE = (p) => `no task list for ${p}`;
const tasksReply = (data, p, ctx) => fenced(data?.tasks?.[p] ?? TASKS_NONE(p), ctx);
const base = (f) => path.basename(String(f));
const age = (s) => (s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`);
const btn = (style, label, custom_id) => ({ type: 2, style, label, custom_id });

function leadStatus(l) {
  const dash = (v) => (v ?? '?');
  return [
    `window ${dash(l.window)} · pane ${dash(l.pane)} · pid ${dash(l.pid)}`,
    `state ${dash(l.state)} · bot ${l.holds_bot ? 'held' : 'not held'}`,
    `context ${l.context_pct == null ? 'unknown' : `${l.context_pct}%`}`,
    `newest handoff ${l.doc ? `${base(l.doc)} (${age(l.doc_age_s ?? 0)} ago)` : 'none'}`,
  ].join('\n');
}

// restart|handoff: a private preview with Confirm and Cancel, or why it cannot be done.
async function leadPreview(i, ctx, action, project, l) {
  const miss = action === 'restart' ? (!l.pane ? 'no lead pane' : !l.session_id ? 'no session id' : null) : (!l.doc ? 'no handoff doc' : null);
  if (miss) { await ctx.answer(i, `cannot ${action} ${project}: ${miss}`); return; }
  const text = action === 'restart'
    ? `restart the ${project} lead in window ${l.window} with --resume ${l.session_id}${l.state && l.state !== 'idle' ? `; it is ${l.state} right now` : ''}`
    : `start a fresh lead from ${base(l.doc)}, written ${Math.round((l.doc_age_s ?? 0) / 60)} min ago`;
  const ms = ctx.now();
  await ctx.answer(i, text, [{ type: 1, components: [btn(3, 'Confirm', `ab:lead:${action}:${project}:${ms}`), btn(2, 'Cancel', `ab:lead:cancel:${project}:${ms}`)] }]);
}

// A project bot acting on a project that is not its own needs the user in the ops bot's allowlist too (missing file: nobody).
function crossDenied(ctx, project, user) {
  return !ctx.ops && !!project && project !== path.basename(ctx.dir) && !(ctx.opsAllow?.() ?? new Set()).has(user);
}

async function handleCommand(i, ctx) {
  const name = i.commandName;
  const what = `/${name}`;
  const user = String(i.user?.id);
  const event = (e) => ctx.writeEvent({ ...e, user, ts: ctx.now() });
  const own = path.basename(ctx.dir);
  const given = i.options?.getString?.('project') || null;
  // a project bot defaults to its own project only in its home channel (or a thread of it); elsewhere it acts like the ops bot
  const homeId = ctx.ops ? null : ctx.homeChannel?.();
  const inHome = !ctx.ops && !!homeId && (i.channelId === homeId || i.channel?.parentId === homeId); // an unknown home channel means no default
  const project = name === 'ideas' ? (ctx.ops ? given : own) : (given || (inHome ? own : null)); // /ideas: the ops bot covers every project unless one is given (R2); a project bot covers only its own

  if (name === 'new-project') {
    if (!ctx.ops) { await ctx.answer(i, 'Use /new-project on the ops bot.'); return; }
    if (String(i.channelId ?? '') !== String(ctx.commandCenter() ?? '')) {
      await ctx.answer(i, 'Use /new-project in the command center.');
      event({ type: 'rejected', what, project: null });
      return;
    }
    const nm = i.options?.getString?.('name');
    if (nm) { // resume an unfinished setup: the board answers
      if (!NP_NAME_RE.test(nm)) { await ctx.answer(i, NP_BAD_NAME); return; }
      await i.deferReply({ flags: 64 });
      ctx.keep(i);
      event({ type: 'slash', command: 'new-project', name: nm, channel_id: String(i.channelId), iid: String(i.id) });
      return;
    }
    const input = (id, label, style, max, required, placeholder) => ({ type: 1, components: [{ type: 4, custom_id: id, label, style, max_length: max, required, ...(placeholder ? { placeholder } : {}) }] });
    await i.showModal({
      custom_id: 'ab:modal:new-project', title: 'New project',
      components: [input('name', 'Name', 1, PROJECT_MAX, true), input('source', 'Source: new, clone or folder', 1, 6, true, 'new'),
        input('target', 'Git URL (clone) or path (folder)', 1, 400, false)],
    });
    return;
  }
  if (name === 'queue' && ctx.ops && !project) { // one card per lead, posted by the board
    const n = Object.keys(ctx.views()?.leads || {}).filter((p) => p in (ctx.views()?.queue || {})).length;
    await ctx.answer(i, `posting ${n} queue cards`);
    event({ type: 'slash', command: 'queue', project: null });
    return;
  }
  if (NEEDS_PROJECT.has(name) && !project) { await ctx.answer(i, 'Pick a project.'); return; }
  if (name === 'ideas' && !ctx.ops && given && given !== own) { await ctx.answer(i, `/ideas here covers only ${own}; use the ops bot for ${given}`); return; }
  if (crossDenied(ctx, project, user)) {
    await ctx.answer(i, `Not allowed for ${project}.`);
    event({ type: 'rejected', what, project });
    return;
  }
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
  if (name === 'tasks') {
    if (project) { await ctx.answer(i, tasksReply(data, project, ctx)); event({ type: 'read', what }); return; }
    const withTasks = Object.keys(data?.tasks || {}).filter((p) => data.tasks[p]).slice(0, 25);
    if (!withTasks.length) { await ctx.answer(i, 'no task lists'); event({ type: 'read', what }); return; }
    await ctx.answer(i, 'Pick a project', [{ type: 1, components: [{ type: 3, custom_id: 'ab:tasks:pick', placeholder: 'Project', options: withTasks.map((p) => ({ label: p.slice(0, 100), value: p })) }] }]);
    event({ type: 'read', what });
    return;
  }
  if (name === 'lead') {
    const action = i.options?.getString?.('action');
    if (!LEAD_ACTIONS.includes(action)) { await ctx.answer(i, 'Pick status, restart or handoff.'); return; }
    const l = data?.leads?.[project];
    if (action === 'status') {
      await ctx.answer(i, l ? fenced(leadStatus(l), ctx) : `no lead info for ${project}`);
      event({ type: 'read', what: `/lead status` });
    } else await leadPreview(i, ctx, action, project, l || {});
    return;
  }
  if (name === 'gauth') {
    await i.deferReply({ flags: 64 });
    ctx.keep(i);
    event({ type: 'slash', command: 'gauth', project, iid: String(i.id) });
    return;
  }
  if (name === 'pause' || name === 'resume') {
    await ctx.answer(i, `Sent to ${project}.`);
    event({ type: 'slash', command: name, project });
    return;
  }
  if (name === 'ideas') {
    await ctx.answer(i, 'asked the overseer, about 1 min');
    event({ type: 'slash', command: 'ideas', project, bridge: own });
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
  const user = String(i.user?.id);
  if (form === 'new-project') {
    if (!ctx.ops || String(i.channelId ?? '') !== String(ctx.commandCenter() ?? '')) {
      await ctx.answer(i, 'Use /new-project in the command center.');
      ctx.writeEvent({ type: 'rejected', what: 'ab:modal:new-project', user, ts: ctx.now() });
      return;
    }
    const v = (id) => String(i.fields.getTextInputValue(id) ?? '').trim();
    const name = v('name'), source = v('source').toLowerCase(), target = v('target');
    const why = !NP_NAME_RE.test(name) ? NP_BAD_NAME
      : !NP_SOURCES.includes(source) ? 'Source must be new, clone or folder.'
        : source !== 'new' && !target ? `Source ${source} needs a ${source === 'clone' ? 'git URL' : 'path'}.` : null;
    if (why) { await ctx.answer(i, why); return; }
    await i.deferReply({ flags: 64 });
    ctx.keep(i);
    ctx.writeEvent({ type: 'modal', form: 'new-project', fields: { name, source, target: source === 'new' ? '' : target }, user, channel_id: String(i.channelId), iid: String(i.id), ts: ctx.now() });
    ctx.say(`modal new-project ${ctx.snip(name)} from ${ctx.snip(user)}`);
    return;
  }
  if (form === 'np-token') {
    const tok = String(i.fields.getTextInputValue('token') ?? '').trim();
    if (!ctx.ops || !NP_NAME_RE.test(project)) { await ctx.answer(i, 'Not available here.'); return; }
    if (!tok || /\s/.test(tok)) { await ctx.answer(i, 'That does not look like a bot token; Paste token again.'); return; }
    let file;
    try { file = ctx.writeTokenFile(tok); } catch { ctx.say(`modal np-token ${ctx.snip(project)}: could not write the token file`); await ctx.answer(i, 'Could not take the token; Paste token again.'); return; }
    try {
      await i.deferReply({ flags: 64 });
      ctx.keep(i);
      ctx.writeEvent({ type: 'np_token', name: project, file, user, iid: String(i.id), ts: ctx.now() });
    } catch { ctx.dropTokenFile(file); ctx.say(`modal np-token ${ctx.snip(project)}: event write failed`); return; }
    ctx.say(`modal np-token ${ctx.snip(project)} from ${ctx.snip(user)}`); // never the token itself
    return;
  }
  if (form === 'gauth') {
    const code = String(i.fields.getTextInputValue('code') ?? '').trim();
    if (!code) { await ctx.answer(i, 'Empty code.'); return; }
    try { ctx.writeEvent({ type: 'modal', form: 'gauth', project, user: String(i.user?.id), text: code, ts: ctx.now() }); }
    catch (e) { ctx.say(`modal gauth write failed: ${ctx.snip(e?.message)}`); await ctx.answer(i, 'could not send the code; run /gauth again'); return; }
    await ctx.answer(i, 'Code sent.');
    ctx.say(`modal gauth ${ctx.snip(project)} from ${ctx.snip(String(i.user?.id))}`); // never the code itself
    return;
  }
  const f = FORMS[form];
  const val = (id) => String(i.fields.getTextInputValue(id) ?? '').trim();
  const fields = Object.fromEntries(f.inputs.map(([id]) => [id, val(id)]));
  const empty = f.inputs.find(([id]) => !fields[id]);
  if (empty) { await ctx.answer(i, `Empty ${empty[0]}.`); return; }
  await ctx.answer(i, f.ack(project));
  ctx.writeEvent({ type: 'modal', form, project, fields, user: String(i.user?.id), ts: ctx.now() });
}

const consumedByCtx = new WeakMap(); // ctx -> Set of /lead Confirm and Cancel custom ids already clicked (a second click is a no-op)

// A click on a /lead Confirm or Cancel, the /tasks select, or the /gauth Enter code button.
async function handleComponent(i, ctx, c) {
  const user = String(i.user?.id);
  if (c[4]) { // ab:tasks:pick
    const p = String(i.values?.[0] ?? '');
    if (crossDenied(ctx, p, user)) { await ctx.answer(i, `Not allowed for ${p}.`, []); ctx.writeEvent({ type: 'rejected', what: 'ab:tasks:pick', project: p, user, ts: ctx.now() }); return; }
    await ctx.answer(i, tasksReply(ctx.views(), p, ctx), []);
    ctx.writeEvent({ type: 'read', what: 'ab:tasks:pick', user, ts: ctx.now() });
    return;
  }
  if (c[6]) { // ab:np:token:<name>: the one-field private token form
    await i.showModal({ custom_id: `ab:modal:np-token:${c[6]}`, title: `Bot token for ${c[6]}`.slice(0, 45), components: [{ type: 1, components: [{ type: 4, custom_id: 'token', label: 'Bot token (Reset Token in the portal)', style: 1, max_length: 100, required: true }] }] });
    return;
  }
  if (c[5]) { // ab:gauth:code:<project>
    await i.showModal({ custom_id: `ab:modal:gauth:${c[5]}`, title: 'Google auth code', components: [{ type: 1, components: [{ type: 4, custom_id: 'code', label: 'Code', style: 1, max_length: 400, required: true }] }] });
    return;
  }
  const [, action, project, ms] = c;
  if (!consumedByCtx.has(ctx)) consumedByCtx.set(ctx, new Set());
  const consumed = consumedByCtx.get(ctx);
  if (consumed.has(i.customId)) { await ctx.answer(i, 'already confirmed', []); return; }
  consumed.add(i.customId);
  if (action === 'cancel') {
    consumed.add(`ab:lead:restart:${project}:${ms}`); consumed.add(`ab:lead:handoff:${project}:${ms}`);
    await ctx.answer(i, 'cancelled', []); return;
  }
  consumed.add(`ab:lead:cancel:${project}:${ms}`);
  if (ctx.now() - Number(ms) > CONFIRM_TTL_MS) { await ctx.answer(i, 'expired; run /lead again', []); return; }
  await ctx.answer(i, 'running…', []); // drops the buttons at once
  ctx.keep(i);
  ctx.writeEvent({ type: 'slash', command: 'lead', action, project, user, iid: String(i.id), ts: ctx.now() });
}

// True when the interaction was a command, modal or one of our components (handled here).
async function handle(i, ctx) {
  const isCmd = i?.isChatInputCommand?.();
  const m = i?.isModalSubmit?.() ? (/^ab:modal:(idea|new-spec|gauth|np-token):(.+)$/.exec(String(i.customId)) || /^ab:modal:(new-project)()$/.exec(String(i.customId))) : null;
  const c = !isCmd && !m && typeof i?.customId === 'string' ? COMPONENT_RE.exec(i.customId) : null;
  if (!isCmd && !m && !c) return false;
  const what = isCmd ? `/${i.commandName}` : i.customId;
  if (!ctx.allowFrom().has(String(i.user?.id))) {
    try { await i.reply({ content: 'Not authorized.', flags: 64 }); } catch (e) { ctx.say(`reply failed: ${ctx.snip(e?.message)}`); }
    ctx.writeEvent({ type: 'rejected', what, user: String(i.user?.id), ts: ctx.now() });
    ctx.say(`${ctx.snip(what)}: not authorized`);
    return true;
  }
  if (isCmd) await handleCommand(i, ctx); else if (m) await handleModal(i, ctx, m); else await handleComponent(i, ctx, c);
  ctx.say(`command ${ctx.snip(what)}`);
  return true;
}

module.exports = { payload, handle, inboxText, fence };
