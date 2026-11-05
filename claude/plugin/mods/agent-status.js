// agent-status: writes this session's state (ready | busy | needs-you) to
// <state dir>/agent-status/<session_id>.json so the board reads events, not pane text.
// State dir = $TC_STATE, else ($TMPDIR minus a trailing "/", default /tmp) + /tmux-ctl-<uid>: the same rule as tc_env.state_dir().
//
// `claude plugin validate` forces literal $.env.get names and literal on() event names. It accepts a module-level
// helper that takes $ as a parameter (flush below; reported as "via flush"), so the write block exists once.
// Writes: $.fs.write to <file>.tmp, then `mv` (there is no $.fs rename or delete); a failing mv falls back to a
// direct write. All writes of this session run one after another (st.q) and render st at write time, so a
// heartbeat can never put an older state back. Events with e.agentId (an in-process teammate's) are skipped:
// the file describes the session's own main agent only. Every I/O is wrapped: an error never blocks a tool or a turn.
//
// needs-you means a dialog is on screen. A permission dialog is signalled by classic.PermissionRequest (the settings
// hook event, which fires only when the dialog is about to show), not by tool.check resolving `ask`: tool.check runs
// before auto mode's classifier, which approves most `ask`s with no dialog. Where the built-in guard loads (Team or
// Enterprise login, managed settings), no classic.* hook of this mod runs; the session is then recognised by the absence
// of classic.SessionStart and classic.PreToolUse, and an `ask` counts as a dialog unless the settings' default mode
// never prompts (the mode set by a flag or shift+tab is not readable from a mod).

const HEARTBEAT_MS = 15000
const NO_PROMPT_MODES = ['auto', 'bypassPermissions', 'dontAsk']

// the one record of this session; null until session.start has resolved the state dir
let st = null
// true once any classic.* hook of this mod has run: classic hooks reach this mod in this session
let classicLive = false

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

// the pending ask (tool.check resolved `ask`, tool.call not yet returned) a PermissionRequest is for: same tool and
// input, else the oldest with that tool (the event carries no tool_use_id)
const askFor = (tool, input) => {
  const body = JSON.stringify(input)
  return st.asks.find((a) => a.tool === tool && a.input === body) || st.asks.find((a) => a.tool === tool) || null
}

// needs-you for the dialog of ask `a`
const dialogOpen = async ($, a) => {
  if (setState('needs-you', await $.clock.now())) {
    st.askId = a.id
    await flush($)
  }
}

const render = () =>
  JSON.stringify({ session_id: st.sid, pane: st.pane, state: st.state, since: st.since, updatedAt: st.updatedAt })

// Writes st to <file>.tmp then mv (direct write if mv fails). The session id is read here, so after a /clear or a
// resume the next write goes to the new id's file and the old one is removed. Writes of the session run in a chain.
async function flush($) {
  let sid = st.sid
  try { sid = await $.session.id() } catch (x) { /* keep the current file */ }
  if (st.ended) return
  st.q = st.q.then(async () => {
    if (st.ended) return
    if (sid !== st.sid) {
      const old = st.file
      st.sid = sid
      st.file = st.dir + '/' + sid + '.json'
      st.tmp = st.file + '.tmp'
      if (old) await $.process.run(['rm', '-f', old])
    }
    if (!st.file) return
    const body = render()
    try {
      await $.fs.write(st.tmp, body)
      const r = await $.process.run(['mv', st.tmp, st.file])
      if (r.exitCode !== 0) throw new Error('mv failed')
    } catch (x) { await $.fs.write(st.file, body) }
  }).catch(() => {})
  await st.q
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    try {
      const sid = await $.session.id()
      const pane = (await $.env.get('TMUX_PANE')) || null
      const tcState = await $.env.get('TC_STATE')
      const tmpdir = await $.env.get('TMPDIR')
      let uid = ''
      if (!tcState) uid = (await $.process.run(['id', '-u'])).stdout.trim()
      const dir = stateDir(tcState, tmpdir, uid)
      let mode = 'default'
      try {
        const all = await $.settings.read()
        if (all && all.permissions && all.permissions.defaultMode) mode = all.permissions.defaultMode
      } catch (x) { /* unknown mode prompts */ }
      const now = await $.clock.now()
      st = { sid, pane, dir, file: dir + '/' + sid + '.json', tmp: dir + '/' + sid + '.json.tmp', state: 'ready', since: secs(now), updatedAt: secs(now), askId: null, asks: [], mode, ended: false, q: Promise.resolve(), tick: null }
      await flush($)
      st.tick = $.clock.every(HEARTBEAT_MS, async () => {
        try {
          if (setState(st.state, await $.clock.now())) await flush($)
        } catch (x) { /* a heartbeat never throws */ }
      })
    } catch (x) { /* never block the session */ }
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (e && e.agentId) return next(e)
    try {
      if (setState('busy', await $.clock.now())) await flush($)
    } catch (x) { /* ignore */ }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    if (e && e.agentId) return out
    try {
      if (setState('ready', await $.clock.now())) await flush($)
    } catch (x) { /* ignore */ }
    return out
  })

  // tool.call is entered before tool.check; its next() returns only once the user answered a prompt and the tool ran.
  on('tool.call', async ($, e, next) => {
    if (e && e.agentId) return next(e)
    const ask = e && e.tool === 'AskUserQuestion'
    try {
      if (ask) await dialogOpen($, { id: (e && e.tool_use_id) || null })
    } catch (x) { /* ignore */ }
    const out = await next(e)
    try {
      const id = e && e.tool_use_id
      if (st) st.asks = st.asks.filter((a) => a.id !== id)
      const mine = st && st.state === 'needs-you' && (ask || st.askId === null || st.askId === id)
      if (mine && setState('busy', await $.clock.now())) await flush($)
    } catch (x) { /* ignore */ }
    return out
  })

  // `ask` here means a rule or the mode would prompt; auto mode's classifier runs after this and approves most of
  // them with no dialog. The dialog itself is classic.PermissionRequest below; the ask is kept so the two can be paired.
  on('tool.check', async ($, e, next) => {
    const out = await next(e)
    if (e && e.agentId) return out
    try {
      if (st && out && out.decision === 'ask') {
        const a = { id: (e && e.tool_use_id) || null, tool: e && e.tool, input: JSON.stringify(e && e.input) }
        st.asks.push(a)
        if (!classicLive && !NO_PROMPT_MODES.includes(st.mode)) await dialogOpen($, a)
      }
    } catch (x) { /* ignore */ }
    return out
  })

  // fires when a permission dialog is about to show (after the classifier; carries tool_name and tool_input, no id)
  on('classic.PermissionRequest', async ($, e, next) => {
    classicLive = true
    try {
      const a = st && e ? askFor(e.tool_name, e.tool_input) : null
      if (a) await dialogOpen($, a)
    } catch (x) { /* ignore */ }
    return next(e)
  })

  // these two only say that classic hooks run here (the guard is not loaded): SessionStart at startup, PreToolUse
  // before every tool.check
  on('classic.SessionStart', async ($, e, next) => { classicLive = true; return next(e) })
  on('classic.PreToolUse', async ($, e, next) => { classicLive = true; return next(e) })

  // session.end also fires on /clear, /resume and /branch (reason `resume`) with no new session.start: the process
  // goes on, possibly under another session id. Drop the old file, reset to ready, keep the heartbeat; the next write
  // goes under the id then current. Any other reason ends the mod's work for good.
  on('session.end', async ($, e, next) => {
    try {
      if (st && !st.ended) {
        const goesOn = e && (e.reason === 'clear' || e.reason === 'resume')
        await st.q
        if (goesOn) {
          const old = st.file
          const now = await $.clock.now()
          st.state = 'ready'; st.since = secs(now); st.updatedAt = secs(now); st.askId = null; st.asks = []
          st.sid = null; st.file = null; st.tmp = null
          if (old) await $.process.run(['rm', '-f', old])
        } else {
          st.ended = true
          if (st.tick) st.tick.cancel()
          if (st.file) await $.process.run(['rm', '-f', st.file])
        }
      }
    } catch (x) { /* ignore */ }
    return next(e)
  })
}
