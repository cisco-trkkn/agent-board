// agent-status: writes this session's state (ready | busy | needs-you) to
// <state dir>/agent-status/<session_id>.json so the board reads events, not pane text.
// State dir = $TC_STATE, else ($TMPDIR minus a trailing "/", default /tmp) + /tmux-ctl-<uid>: the same rule as tc_env.state_dir().
//
// `claude plugin validate` forces the style: literal $.env.get names, literal on() event names, and every
// $ call spelled inline in the handler (no helper takes $). The helpers below work on plain values only.
// Writes: $.fs.write to <file>.tmp, then `mv` (there is no $.fs rename or delete); a failing mv falls back to a
// direct write. All writes of this session run one after another (st.q) and render st at write time, so a
// heartbeat can never put an older state back. Events with e.agentId (an in-process teammate's) are skipped:
// the file describes the session's own main agent only. Every I/O is wrapped: an error never blocks a tool or a turn.

const HEARTBEAT_MS = 15000

// the one record of this session; null until session.start has resolved the file
let st = null

const stateDir = (tcState, tmpdir, uid) =>
  (tcState || (tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid) + '/agent-status'

const secs = (ms) => Math.floor(ms / 1000)

// moves st to `state` at `ms`; `since` changes only with the state
const setState = (state, ms) => {
  if (!st || st.ended) return false
  if (st.state !== state) { st.state = state; st.since = secs(ms) }
  st.updatedAt = secs(ms)
  if (state !== 'needs-you') st.askId = null
  return true
}

const render = () =>
  JSON.stringify({ session_id: st.sid, pane: st.pane, state: st.state, since: st.since, updatedAt: st.updatedAt })

export function register(on) {
  on('session.start', async ($, e, next) => {
    try {
      const sid = await $.session.id()
      const pane = (await $.env.get('TMUX_PANE')) || null
      const tcState = await $.env.get('TC_STATE')
      const tmpdir = await $.env.get('TMPDIR')
      let uid = ''
      if (!tcState) uid = (await $.process.run(['id', '-u'])).stdout.trim()
      const file = stateDir(tcState, tmpdir, uid) + '/' + sid + '.json'
      const now = await $.clock.now()
      st = { sid, pane, file, tmp: file + '.tmp', state: 'ready', since: secs(now), updatedAt: secs(now), askId: null, ended: false, q: Promise.resolve(), tick: null }
      st.q = st.q.then(async () => {
        const body = render()
        try {
          await $.fs.write(st.tmp, body)
          const r = await $.process.run(['mv', st.tmp, st.file])
          if (r.exitCode !== 0) throw new Error('mv failed')
        } catch (x) { await $.fs.write(st.file, body) }
      }).catch(() => {})
      await st.q
      st.tick = $.clock.every(HEARTBEAT_MS, async () => {
        try {
          if (!setState(st.state, await $.clock.now())) return
          st.q = st.q.then(async () => {
            const body = render()
            try {
              await $.fs.write(st.tmp, body)
              const r = await $.process.run(['mv', st.tmp, st.file])
              if (r.exitCode !== 0) throw new Error('mv failed')
            } catch (x) { await $.fs.write(st.file, body) }
          }).catch(() => {})
          await st.q
        } catch (x) { /* a heartbeat never throws */ }
      })
    } catch (x) { /* never block the session */ }
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (e && e.agentId) return next(e)
    try {
      if (setState('busy', await $.clock.now())) {
        st.q = st.q.then(async () => {
          const body = render()
          try {
            await $.fs.write(st.tmp, body)
            const r = await $.process.run(['mv', st.tmp, st.file])
            if (r.exitCode !== 0) throw new Error('mv failed')
          } catch (x) { await $.fs.write(st.file, body) }
        }).catch(() => {})
        await st.q
      }
    } catch (x) { /* ignore */ }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    if (e && e.agentId) return out
    try {
      if (setState('ready', await $.clock.now())) {
        st.q = st.q.then(async () => {
          const body = render()
          try {
            await $.fs.write(st.tmp, body)
            const r = await $.process.run(['mv', st.tmp, st.file])
            if (r.exitCode !== 0) throw new Error('mv failed')
          } catch (x) { await $.fs.write(st.file, body) }
        }).catch(() => {})
        await st.q
      }
    } catch (x) { /* ignore */ }
    return out
  })

  // tool.call is entered before tool.check; its next() returns only once the user answered a prompt.
  on('tool.call', async ($, e, next) => {
    if (e && e.agentId) return next(e)
    const ask = e && e.tool === 'AskUserQuestion'
    try {
      if (ask && setState('needs-you', await $.clock.now())) {
        st.askId = (e && e.tool_use_id) || null
        st.q = st.q.then(async () => {
          const body = render()
          try {
            await $.fs.write(st.tmp, body)
            const r = await $.process.run(['mv', st.tmp, st.file])
            if (r.exitCode !== 0) throw new Error('mv failed')
          } catch (x) { await $.fs.write(st.file, body) }
        }).catch(() => {})
        await st.q
      }
    } catch (x) { /* ignore */ }
    const out = await next(e)
    try {
      const mine = st && st.state === 'needs-you' && (ask || st.askId === null || st.askId === (e && e.tool_use_id))
      if (mine && setState('busy', await $.clock.now())) {
        st.q = st.q.then(async () => {
          const body = render()
          try {
            await $.fs.write(st.tmp, body)
            const r = await $.process.run(['mv', st.tmp, st.file])
            if (r.exitCode !== 0) throw new Error('mv failed')
          } catch (x) { await $.fs.write(st.file, body) }
        }).catch(() => {})
        await st.q
      }
    } catch (x) { /* ignore */ }
    return out
  })

  on('tool.check', async ($, e, next) => {
    const out = await next(e)
    if (e && e.agentId) return out
    try {
      if (out && out.decision === 'ask' && setState('needs-you', await $.clock.now())) {
        st.askId = (e && e.tool_use_id) || null
        st.q = st.q.then(async () => {
          const body = render()
          try {
            await $.fs.write(st.tmp, body)
            const r = await $.process.run(['mv', st.tmp, st.file])
            if (r.exitCode !== 0) throw new Error('mv failed')
          } catch (x) { await $.fs.write(st.file, body) }
        }).catch(() => {})
        await st.q
      }
    } catch (x) { /* ignore */ }
    return out
  })

  on('session.end', async ($, e, next) => {
    try {
      if (st && !st.ended) {
        st.ended = true
        if (st.tick) st.tick.cancel()
        await st.q
        await $.process.run(['rm', '-f', st.file])
      }
    } catch (x) { /* ignore */ }
    return next(e)
  })
}
