// team-band: in the lead's terminal (tmux window `claude`), one line above the prompt naming the teammates that need
// the user, then counts: `Needs you: ✦ qrev · busy 2 · ready 1`. It reads the files the agent-status mod writes
// (<state dir>/agent-status/*.json), kept to the panes of the lead's tmux session.
// State dir = the same expression as agent-status.js stateDir. Only the lead starts timers or draws; any other
// session (or no tmux) does one `tmux display` at most and nothing else. Every hook and timer body is wrapped:
// an error never throws out, and a failed poll leaves the last good line.

const STALE_S = 45
const POLL_MS = 2000
const PANES_MS = 10000

const stateDir = (tcState, tmpdir, uid) =>
  (tcState || (tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid) + '/agent-status'

const secs = (ms) => Math.floor(ms / 1000)

// panes: Map pane_id -> window name, in tmux order; files: parsed status objects; own: the lead's pane; now: epoch s
export function bandLine(panes, files, own, now) {
  const best = new Map()
  for (const f of files) {
    if (!f || typeof f.pane !== 'string' || f.pane === own || !panes.has(f.pane)) continue
    const b = best.get(f.pane)
    if (!b || (Number(f.updatedAt) || 0) > (Number(b.updatedAt) || 0)) best.set(f.pane, f)
  }
  const need = []
  let busy = 0, ready = 0, unknown = 0
  for (const [id, name] of panes) {
    if (id === own) continue
    const f = best.get(id)
    if (!f) { if (name.startsWith('✦ ')) unknown++; continue }
    const age = now - (Number(f.updatedAt) || 0)
    if (age > STALE_S) unknown++
    else if (f.state === 'needs-you') need.push(name)
    else if (f.state === 'busy') busy++
    else if (f.state === 'ready') ready++
    else unknown++
  }
  const parts = []
  if (busy) parts.push('busy ' + busy)
  if (ready) parts.push('ready ' + ready)
  if (unknown) parts.push('? ' + unknown)
  if (need.length) parts.unshift('Needs you: ' + need.join(', '))
  return parts.join(' · ')
}

// the one record of this session; null until session.start has found that this is the lead
let tb = null

const stop = () => {
  if (!tb) return
  tb.ended = true
  if (tb.paneTick) tb.paneTick.cancel()
  if (tb.pollTick) tb.pollTick.cancel()
  tb = null
}

// pane_id -> window name from `tmux list-panes`; null when tmux fails
async function loadPanes($, session) {
  const r = await $.process.run(['tmux', 'list-panes', '-s', '-t', session, '-F', '#{pane_id} #{window_name}'])
  if (r.exitCode !== 0) return null
  const panes = new Map()
  for (const l of r.stdout.split('\n')) {
    const i = l.indexOf(' ')
    if (i > 0) panes.set(l.slice(0, i), l.slice(i + 1))
  }
  return panes
}

// reads the status files and, if the line changed, stores it and asks for a redraw. A throw before bandLine keeps the line.
async function poll($, rec) {
  const entries = await $.fs.list(rec.dir)
  const files = []
  for (const en of entries) {
    if (en.kind !== 'file' || !en.name.endsWith('.json')) continue
    try { files.push(JSON.parse(await $.fs.read(rec.dir + '/' + en.name))) } catch (x) { /* skip this file */ }
  }
  const line = bandLine(rec.panes, files, rec.own, secs(await $.clock.now()))
  if (rec.ended || line === rec.line) return
  rec.line = line
  await $.ui.invalidate('ui.render')
}

export function register(on) {
  on('session.start', { surface: /.*/ }, async ($, e, next) => {
    try {
      stop()
      const pane = await $.env.get('TMUX_PANE')
      const tcState = await $.env.get('TC_STATE')
      const tmpdir = await $.env.get('TMPDIR')
      if (pane) {
        const d = await $.process.run(['tmux', 'display', '-p', '-t', pane, '#{window_name}\t#{session_name}'])
        const [window, session] = d.stdout.replace(/\n$/, '').split('\t')
        if (d.exitCode === 0 && window === 'claude' && session) {
          let uid = ''
          if (!tcState) uid = (await $.process.run(['id', '-u'])).stdout.trim()
          const rec = { own: pane, session, dir: stateDir(tcState, tmpdir, uid), panes: new Map(), line: '', ended: false, paneTick: null, pollTick: null }
          tb = rec
          try { rec.panes = (await loadPanes($, session)) || rec.panes } catch (x) { /* retried by the timer */ }
          try { await poll($, rec) } catch (x) { /* first poll failed: no band yet */ }
          if (tb === rec) {
            rec.paneTick = $.clock.every(PANES_MS, async () => {
              try {
                const p = await loadPanes($, session)
                if (p && !rec.ended) rec.panes = p
              } catch (x) { /* keep the last list */ }
            })
            rec.pollTick = $.clock.every(POLL_MS, async () => {
              try { await poll($, rec) } catch (x) { /* keep the last line */ }
            })
          }
        }
      }
    } catch (x) { /* never block the session */ }
    return next(e)
  })

  // /clear, /resume and /branch end the session without a new session.start: the process goes on, so the timers stay
  on('session.end', { reason: /.*/ }, async ($, e, next) => {
    try {
      if (!(e && (e.reason === 'clear' || e.reason === 'resume'))) stop()
    } catch (x) { /* ignore */ }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const line = tb && !tb.ended ? tb.line : ''
    if (!line) return next(e)
    try {
      const { Box, Text } = $.ui.resolve(e)
      const children = [Text({ children: [line] })]
      const below = await next(e)
      if (below) children.push(below)
      return Box({ flexDirection: 'column', children })
    } catch (x) {
      return next(e)
    }
  })
}
