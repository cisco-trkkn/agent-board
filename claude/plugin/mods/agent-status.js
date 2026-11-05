// SPIKE version (Task 1): on session.start write {session_id, pane, env_ok} to
// <state dir>/agent-status/<session_id>.json, plus probe files for the notes
// (<state dir>/agent-status-probe/). Task 2 replaces this with the real mod.
// The validator forbids passing $ to helpers and non-literal $.env.get names,
// so every handler spells its calls inline.
const msg = (x) => String((x && x.message) || x)

export function register(on) {
  on('session.start', async ($, e, next) => {
    const probe = { event: 'session.start', eventKeys: Object.keys(e || {}) }
    try {
      const pane = (await $.env.get('TMUX_PANE')) ?? null
      const tcState = (await $.env.get('TC_STATE')) ?? null
      const tmpdir = (await $.env.get('TMPDIR')) ?? null
      let uid = null
      try { uid = (await $.process.run(['id', '-u'])).stdout.trim() } catch (x) { uid = 'ERR:' + msg(x) }
      let sid = null
      try { sid = await $.session.id() } catch (x) { sid = 'ERR:' + msg(x) }
      const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
      const dir = base + '/agent-status'
      Object.assign(probe, { pane, tcState, tmpdir, uid, sid, dir })
      const body = JSON.stringify({ session_id: sid, pane, env_ok: pane !== null })
      try { await $.fs.write(dir + '/' + sid + '.json', body); probe.writeDirect = 'ok' } catch (x) { probe.writeDirect = 'ERR:' + msg(x) }
      if (probe.writeDirect !== 'ok') {
        try { await $.process.run(['mkdir', '-p', dir]); probe.mkdirViaProcess = 'ok' } catch (x) { probe.mkdirViaProcess = 'ERR:' + msg(x) }
        try { await $.fs.write(dir + '/' + sid + '.json', body); probe.writeAfterMkdir = 'ok' } catch (x) { probe.writeAfterMkdir = 'ERR:' + msg(x) }
      }
      try {
        await $.process.run(['mv', dir + '/' + sid + '.json', dir + '/' + sid + '.tmp'])
        await $.process.run(['mv', dir + '/' + sid + '.tmp', dir + '/' + sid + '.json'])
        probe.mvViaProcess = 'ok'
      } catch (x) { probe.mvViaProcess = 'ERR:' + msg(x) }
      await $.process.run(['mkdir', '-p', base + '/agent-status-probe'])
      await $.fs.write(base + '/agent-status-probe/' + sid + '.session.start.json', JSON.stringify(probe, null, 1))
    } catch (x) { /* never block the session */ }
    return next(e)
  })

  // payload probes: event keys, tool names, the tool.check decision shape
  const seen = new Set()
  on('turn.start', async ($, e, next) => {
    const t0 = Date.now()
    const out = await next(e)
    const t1 = Date.now()
    const name = 'turn.start' + (e && e.tool ? '.' + e.tool : '')
    if (!seen.has(name)) {
      seen.add(name)
      try {
        const tcState = await $.env.get('TC_STATE')
        const tmpdir = await $.env.get('TMPDIR')
        const uid = (await $.process.run(['id', '-u'])).stdout.trim()
        const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
        const sid = await $.session.id()
        await $.fs.write(base + '/agent-status-probe/' + sid + '.' + name + '.json',
          JSON.stringify({ name, keys: Object.keys(e || {}), tool: e && e.tool, agentId: e && e.agentId, enteredAt: t0, returnedAt: t1, result: out }, null, 1))
      } catch (x) { /* ignore */ }
    }
    return out
  })
  on('turn.complete', async ($, e, next) => {
    const t0 = Date.now()
    const out = await next(e)
    const t1 = Date.now()
    const name = 'turn.complete' + (e && e.tool ? '.' + e.tool : '')
    if (!seen.has(name)) {
      seen.add(name)
      try {
        const tcState = await $.env.get('TC_STATE')
        const tmpdir = await $.env.get('TMPDIR')
        const uid = (await $.process.run(['id', '-u'])).stdout.trim()
        const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
        const sid = await $.session.id()
        await $.fs.write(base + '/agent-status-probe/' + sid + '.' + name + '.json',
          JSON.stringify({ name, keys: Object.keys(e || {}), tool: e && e.tool, agentId: e && e.agentId, enteredAt: t0, returnedAt: t1, result: out }, null, 1))
      } catch (x) { /* ignore */ }
    }
    return out
  })
  on('tool.check', async ($, e, next) => {
    const t0 = Date.now()
    const out = await next(e)
    const t1 = Date.now()
    const name = 'tool.check' + (e && e.tool ? '.' + e.tool : '')
    if (!seen.has(name)) {
      seen.add(name)
      try {
        const tcState = await $.env.get('TC_STATE')
        const tmpdir = await $.env.get('TMPDIR')
        const uid = (await $.process.run(['id', '-u'])).stdout.trim()
        const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
        const sid = await $.session.id()
        await $.fs.write(base + '/agent-status-probe/' + sid + '.' + name + '.json',
          JSON.stringify({ name, keys: Object.keys(e || {}), tool: e && e.tool, agentId: e && e.agentId, enteredAt: t0, returnedAt: t1, result: out }, null, 1))
      } catch (x) { /* ignore */ }
    }
    return out
  })
  on('tool.call', async ($, e, next) => {
    const t0 = Date.now()
    const out = await next(e)
    const t1 = Date.now()
    const name = 'tool.call' + (e && e.tool ? '.' + e.tool : '')
    if (!seen.has(name)) {
      seen.add(name)
      try {
        const tcState = await $.env.get('TC_STATE')
        const tmpdir = await $.env.get('TMPDIR')
        const uid = (await $.process.run(['id', '-u'])).stdout.trim()
        const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
        const sid = await $.session.id()
        await $.fs.write(base + '/agent-status-probe/' + sid + '.' + name + '.json',
          JSON.stringify({ name, keys: Object.keys(e || {}), tool: e && e.tool, agentId: e && e.agentId, enteredAt: t0, returnedAt: t1, result: out }, null, 1))
      } catch (x) { /* ignore */ }
    }
    return out
  })
  on('session.end', async ($, e, next) => {
    const t0 = Date.now()
    const out = await next(e)
    const t1 = Date.now()
    const name = 'session.end' + (e && e.tool ? '.' + e.tool : '')
    if (!seen.has(name)) {
      seen.add(name)
      try {
        const tcState = await $.env.get('TC_STATE')
        const tmpdir = await $.env.get('TMPDIR')
        const uid = (await $.process.run(['id', '-u'])).stdout.trim()
        const base = tcState || ((tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid)
        const sid = await $.session.id()
        await $.fs.write(base + '/agent-status-probe/' + sid + '.' + name + '.json',
          JSON.stringify({ name, keys: Object.keys(e || {}), tool: e && e.tool, agentId: e && e.agentId, enteredAt: t0, returnedAt: t1, result: out }, null, 1))
      } catch (x) { /* ignore */ }
    }
    return out
  })
}
