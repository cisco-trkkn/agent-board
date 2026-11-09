// artifact-register: after a Write/Edit/MultiEdit tool.call succeeds, appends one JSONL record
// {ts,path,kind,agent,hash,url,title,slug,session_id,epoch} to <state dir>/artifacts-<project>.jsonl, the same record
// scripts/artifact-register.sh writes in hook mode. The record is serialised with JSON.stringify (no spaces after , and :);
// readers parse it.
//
// File tools only. The Artifact tool and the Claude Docs tools (batch, create, update) stay on artifact-register.sh: their
// URL rules read the tool's result, and the shape of that result inside a mod is unverified (the probe could not reach
// those tools; checking needs a real publish). The script's marker early exit applies to Write/Edit/MultiEdit only.
// Manual mode (--path) is shell-only too.
//
// Nothing is recorded when the call was refused (out.deny), failed (out.isError) or rejected (the rejection is rethrown).
// realpath and sha256 go through $.process.run (`realpath`, `shasum -a 256`, else `sha256sum`): $.fs has no realpath or
// hash, and a non-zero exit of realpath means the shell's isfile check failed, so the file is skipped. The path and kind
// are decided first, so a source-file edit with no kind costs no tmux call, lineage read or session lookup.
// The manifest is appended with read-modify-write through $.fs (no append API), chained per session; a manifest that
// exists but cannot be read is left alone rather than overwritten. The tmux binary comes from lib/env.js tmuxBin
// (the shell sources bin/_tc_bins.zsh when present; the mod does not).
// The mod writes <state dir>/mods-active/<session_id>.artifact-register at session start so the shell script defers.
import { stateDir, lineageDir, markerPath, readEnv, writeMarker, removeMarker, rekeyMarker, tmuxRun } from './lib/env.js'

let ctx = null // { dir, lineage, home, tmpdir, tmux, pane, tcTmux, sid, marker }
let q = Promise.resolve()

export async function start($, e) {
  try {
    const env = await readEnv($)
    const sid = await $.session.id()
    const dir = stateDir(env.tcState, env.tmpdir, env.uid)
    ctx = {
      dir, lineage: lineageDir(env.tcLineage, env.xdgStateHome, env.home), home: env.home, tmpdir: env.tmpdir || '/tmp',
      tmux: env.tmux, pane: env.tmuxPane, tcTmux: env.tcTmux, sid, marker: markerPath(dir, sid, 'artifact-register'),
    }
    await writeMarker($, ctx.marker, sid)
  } catch (x) { /* never block the session */ }
}

// /clear and /resume go on under another session id and session.start does not fire again: drop the marker and forget the
// id, and the next file tool call writes the new one (rekeyMarker). Other reasons: the session is over.
export async function end($, e) {
  try {
    await q
    if (ctx && ctx.marker) await removeMarker($, ctx.marker)
    if (ctx) { ctx.marker = null; ctx.sid = null }
  } catch (x) { /* never block the session */ }
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
  const base = p.slice(p.lastIndexOf('/') + 1)
  if (p.includes('/docs/superpowers/plans/')) return 'plan'
  if (p.includes('/docs/superpowers/specs/')) return 'spec'
  if (ctx.homeReal === undefined) ctx.homeReal = await realpathOr($, ctx.home)
  const h = ctx.homeReal
  for (const hd of ['.local/state/agent-board/handoffs', '.claude/handoffs']) {
    if (p.startsWith(h + '/' + hd + '/')) return 'handoff'
  }
  if (ctx.tmpReal === undefined) ctx.tmpReal = await realpathOr($, ctx.tmpdir.replace(/\/+$/, '') || '/tmp')
  const t = ctx.tmpReal
  if (p.startsWith(t + '/') && base.includes('handoff')) return 'handoff'
  if (p.includes('/scratchpad/') && base.includes('report')) return 'report'
  return ''
}

// sha256 of a file: `shasum -a 256`, else `sha256sum`; '' when neither works (a directory, an unreadable file)
async function sha256($, p) {
  for (const argv of [['shasum', '-a', '256', p], ['sha256sum', p]]) {
    try {
      const r = await $.process.run(argv)
      if (r.exitCode === 0) return r.stdout.trim().split(/\s+/)[0]
    } catch (x) { /* try the next */ }
  }
  return ''
}

async function projectAndAgent($) {
  const info = await tmuxRun($, ctx.tcTmux, ctx.home, ctx.tmux, ['display', '-p', '-t', ctx.pane, '#{?session_group,#{session_group},#{session_name}}\t#{window_name}'])
  const [proj, win] = info.replace(/\n$/, '').split('\t')
  return [proj, (win || '').replace(/^✦ /, '') || 'claude']
}

// builds and appends the record; throws on any failure (the caller swallows)
async function append($, e) {
  if (!ctx || !ctx.tmux || !ctx.pane) return
  let path = String(e.file_path || '')
  if (!path) return
  if (path === '~' || path.startsWith('~/')) path = ctx.home + path.slice(1)
  path = await realpath($, path) // a missing file throws: skipped, like the shell's isfile check
  const kind = await kindOf($, path)
  if (!kind) return
  const hash = await sha256($, path)
  if (!hash) return
  const [proj, agent] = await projectAndAgent($)
  if (!/^[A-Za-z0-9._-]+$/.test(proj)) return
  const manifest = ctx.dir + '/artifacts-' + proj + '.jsonl'
  let lin = ''
  try { lin = await $.fs.read(ctx.lineage + '/' + proj + '.jsonl') } catch (x) { lin = '' }
  const epoch = (String(lin).match(/\n/g) || []).length
  const sid = (await $.session.id()) || ''
  const rec = { ts: (await $.clock.now()) / 1000, path, kind, agent, hash, url: '', title: '', slug: '', session_id: sid, epoch }
  let cur = ''
  if (await $.fs.exists(manifest)) cur = await $.fs.read(manifest) // unreadable: throws, the manifest is left alone
  await $.fs.write(manifest, String(cur) + JSON.stringify(rec) + '\n')
}

async function record($, e) {
  q = q.then(() => append($, e)).catch(() => {})
  await q
}

export function register(on) {
  on('tool.call', { tool: ['Write', 'Edit', 'MultiEdit'] }, async ($, e, next) => {
    await rekeyMarker($, ctx, 'artifact-register')
    const out = await next(e) // a rejection propagates: nothing is recorded
    if (out && !out.deny && !out.isError) {
      try { await record($, e) } catch (x) { /* never fails the call */ }
    }
    return out
  })
}
