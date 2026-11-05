// artifact-register: after a Write/Edit/MultiEdit/Artifact/Claude Docs tool.call succeeds, appends one JSONL record
// {ts,path,kind,agent,hash,url,title,slug,session_id,epoch} to <state dir>/artifacts-<project>.jsonl, the same record
// scripts/artifact-register.sh writes in hook mode (manual mode, --path, stays shell-only). The record is serialised with
// JSON.stringify (no spaces after , and :); readers parse it.
//
// The shell's tool_response is the tool's own result here: next(e)'s `result` (for Claude Docs a list of
// {type:'text', text} items, for Artifact a string or object, whose JSON text is searched for the claude.ai URL).
// Nothing is recorded when the call was refused (out.deny), failed (out.isError) or rejected (the rejection is rethrown).
// realpath and sha256 go through $.process.run (`realpath`, `shasum -a 256`): $.fs has no realpath or hash, and a
// non-zero exit of either means the shell's isfile check failed, so the file is skipped.
// The manifest is appended with read-modify-write through $.fs (no append API), chained per session; a manifest that
// exists but cannot be read is left alone rather than overwritten. The tmux binary comes from lib/env.js tmuxBin
// (the shell sources bin/_tc_bins.zsh when present; the mod does not).
// The mod writes <state dir>/mods-active/<session_id>.artifact-register at session start so the shell script defers.
import { stateDir, lineageDir, markerPath, readEnv, writeMarker, removeMarker, tmuxRun } from './lib/env.js'

let ctx = null // { dir, lineage, home, tmpdir, tmux, pane, tcTmux, marker }
let q = Promise.resolve()

export async function start($, e) {
  try {
    const env = await readEnv($)
    const sid = await $.session.id()
    const dir = stateDir(env.tcState, env.tmpdir, env.uid)
    ctx = {
      dir, lineage: lineageDir(env.tcLineage, env.xdgStateHome, env.home), home: env.home, tmpdir: env.tmpdir || '/tmp',
      tmux: env.tmux, pane: env.tmuxPane, tcTmux: env.tcTmux, marker: markerPath(dir, sid, 'artifact-register'),
    }
    await writeMarker($, ctx.marker, sid)
  } catch (x) { /* never block the session */ }
}

export async function end($, e) {
  try {
    const goesOn = e && (e.reason === 'clear' || e.reason === 'resume')
    await q
    if (ctx && ctx.marker) await removeMarker($, ctx.marker)
    if (ctx) ctx.marker = null
    if (goesOn) await start($, e)
  } catch (x) { /* never block the session */ }
}

const isObj = (x) => x !== null && typeof x === 'object' && !Array.isArray(x)
const onClaude = (u) => typeof u === 'string' && u.startsWith('https://claude.ai/')

// the result as the list/blob the shell's rules expect
const respOf = (out) => {
  const r = out && out.result !== undefined ? out.result : out && out.text
  return typeof r === 'string' && out && typeof out.text === 'string' && r === '' ? out.text : r
}

async function realpath($, p) {
  const r = await $.process.run(['realpath', p])
  if (r.exitCode !== 0) throw new Error('no such file')
  return r.stdout.trim()
}

async function realpathOr($, p) {
  try { return await realpath($, p) } catch (x) { return p }
}

async function kindOf($, p) {
  if (!p.endsWith('.md')) return ''
  const h = await realpathOr($, ctx.home)
  const t = await realpathOr($, ctx.tmpdir.replace(/\/+$/, '') || '/tmp')
  const base = p.slice(p.lastIndexOf('/') + 1)
  if (p.includes('/docs/superpowers/plans/')) return 'plan'
  if (p.includes('/docs/superpowers/specs/')) return 'spec'
  for (const hd of ['.local/state/agent-board/handoffs', '.claude/handoffs']) {
    if (p.startsWith(h + '/' + hd + '/')) return 'handoff'
  }
  if (p.startsWith(t + '/') && base.includes('handoff')) return 'handoff'
  if (p.includes('/scratchpad/') && base.includes('report')) return 'report'
  return ''
}

// the doc rules: [url, slug, title] or null (nothing to record)
async function docFields($, e, resp, manifest) {
  const cont = isObj(e.container) ? e.container : {}
  let frame = null
  for (const it of Array.isArray(resp) ? resp : []) { // first item whose first line is the frame JSON
    let fr
    try { fr = JSON.parse(String(it.text).split('\n')[0]).frame } catch (x) { continue }
    if (isObj(fr)) {
      const fu = [fr.url, fr.artifactUrl].find(onClaude)
      if (fu) { frame = { ...fr, url: fu }; break }
    }
  }
  let url = ''
  let slug = ''
  let title = ''
  if (frame) {
    url = frame.url || frame.artifactUrl
    slug = frame.slug || cont.id || ''
    title = (cont.create && cont.create.name) || ''
  } else if (cont.id) { // edit: reuse the URL of the last line for this doc
    slug = cont.id
    const text = await $.fs.read(manifest)
    for (const ln of String(text).split('\n')) {
      let rec
      try { rec = JSON.parse(ln) } catch (x) { continue }
      if (isObj(rec) && rec.kind === 'doc' && rec.slug === slug && rec.url) url = rec.url
    }
  } else {
    const m = /https:\/\/claude\.ai\/[\w/.-]*[\w/]/.exec(JSON.stringify(resp || ''))
    if (m) url = m[0]
  }
  if (!url) return null
  return [url, slug, typeof title === 'string' ? title : '']
}

async function project($) {
  const info = await tmuxRun($, ctx.tcTmux, ctx.home, ctx.tmux, ['display', '-p', '-t', ctx.pane, '#{?session_group,#{session_group},#{session_name}}\t#{window_name}'])
  const [proj, win] = info.replace(/\n$/, '').split('\t')
  return [proj, (win || '').replace(/^✦ /, '') || 'claude']
}

// builds and appends the record; throws on any failure (the caller swallows)
async function append($, e, out) {
  if (!ctx || !ctx.tmux || !ctx.pane) return
  const tool = String(e.tool || '')
  const resp = respOf(out)
  const [proj, agent] = await project($)
  if (!/^[A-Za-z0-9._-]+$/.test(proj)) return
  const manifest = ctx.dir + '/artifacts-' + proj + '.jsonl'
  let lin = ''
  try { lin = await $.fs.read(ctx.lineage + '/' + proj + '.jsonl') } catch (x) { lin = '' }
  const epoch = (String(lin).match(/\n/g) || []).length
  const sid = (await $.session.id()) || ''
  let url = ''
  let title = ''
  let slug = ''
  let kind = ''
  let path = ''
  if (tool === 'Artifact') {
    const m = /https:\/\/claude\.ai\/[\w/.-]+/.exec(JSON.stringify(resp || ''))
    if (!m) return
    url = m[0]
    kind = 'published'
    path = e.file_path || url
  } else if (tool.startsWith('mcp__claude_ai_Claude_Docs__') && ['batch', 'create', 'update'].includes(tool.split('__').pop())) {
    const f = await docFields($, e, resp, manifest)
    if (!f) return
    ;[url, slug, title] = f
    kind = 'doc'
    path = url
  } else if (tool === 'Write' || tool === 'Edit' || tool === 'MultiEdit') {
    path = e.file_path || ''
  } else {
    return
  }
  if (!path) return
  let hash = ''
  if (!url) {
    if (path === '~' || path.startsWith('~/')) path = ctx.home + path.slice(1)
    path = await realpath($, path) // a missing file throws: skipped, like the shell's isfile check
    kind = await kindOf($, path)
    if (!kind) return
    const r = await $.process.run(['shasum', '-a', '256', path])
    if (r.exitCode !== 0) return // a directory or an unreadable file
    hash = r.stdout.trim().split(/\s+/)[0]
  }
  const rec = { ts: (await $.clock.now()) / 1000, path, kind, agent, hash, url, title, slug, session_id: sid, epoch }
  let cur = ''
  if (await $.fs.exists(manifest)) cur = await $.fs.read(manifest) // unreadable: throws, the manifest is left alone
  await $.fs.write(manifest, String(cur) + JSON.stringify(rec) + '\n')
}

async function record($, e, out) {
  q = q.then(() => append($, e, out)).catch(() => {})
  await q
}

export function register(on) {
  const tools = ['Write', 'Edit', 'MultiEdit', 'Artifact', 'mcp__claude_ai_Claude_Docs__batch', 'mcp__claude_ai_Claude_Docs__create', 'mcp__claude_ai_Claude_Docs__update']
  on('tool.call', { tool: tools }, async ($, e, next) => {
    const out = await next(e) // a rejection propagates: nothing is recorded
    if (out && !out.deny && !out.isError) {
      try { await record($, e, out) } catch (x) { /* never fails the call */ }
    }
    return out
  })
}
