// Tests for the team-band mod. The world beneath both mods of the plugin (agent-status loads in every test file too)
// is answered from memory: no real tmux, no real state dir.
import { expect, test, mock } from 'claude-code/testing'
import { bandLine } from './team-band.js'

type World = {
  files: Map<string, string>
  runs: string[][]
  window: string
  session: string
  panes: string
  tmuxFail: boolean
  listOnlyPane: boolean
  failList: boolean
  invalidations: number
  listCalls: number
}

const DIR = '/s/agent-status'
const NOW = 1_000_000 // ms; the mod sees 1000 s

// Registers the stubs for agent-status (session id, settings, fs.write, id/mv/rm) and for team-band
// (tmux display / list-panes, fs.list, fs.read). Call before the first `$` call.
function world(on: any, env: Record<string, string>): { w: World; clock: any } {
  const w: World = {
    files: new Map(), runs: [], window: 'claude', session: 'dev',
    panes: '%1 claude\n%2 ✦ qrev\n%3 ✦ impl\n%4 tasks\n', tmuxFail: false, listOnlyPane: false, failList: false, invalidations: 0, listCalls: 0,
  }
  mock.env(on, env)
  const clock = mock.clock(on, { now: NOW })
  on('session.id', async () => ({ value: 'sid1' }))
  on('settings.read', () => ({ value: { permissions: {} } }))
  on('fs.write', ($: any, e: any) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('fs.list', ($: any, e: any) => {
    w.listCalls++
    if (w.failList) throw new Error('denied')
    const dir = e.path.replace(/\/+$/, '') + '/'
    const out = [...w.files.keys()].filter((k) => k.startsWith(dir) && !k.slice(dir.length).includes('/'))
      .map((k) => ({ name: k.slice(dir.length), kind: 'file', size: 1, isLink: false }))
    return { value: out }
  })
  on('fs.read', ($: any, e: any) => {
    if (!w.files.has(e.path)) throw new Error('ENOENT')
    return { value: w.files.get(e.path) }
  })
  on('process.run', ($: any, e: any) => {
    w.runs.push([...e.argv])
    const [cmd, a, b] = e.argv
    const ok = (stdout = '') => ({ value: { exitCode: 0, stdout, stderr: '' } })
    if (cmd === 'id') return ok('503\n')
    if (cmd === 'mv') { w.files.set(b, w.files.get(a) as string); w.files.delete(a); return ok() }
    if (cmd === 'rm') { w.files.delete(e.argv[2]); return ok() }
    if (cmd === 'tmux') {
      if (w.tmuxFail) return { value: { exitCode: 1, stdout: 'claude\tdev\n', stderr: 'no server' } }
      if (a === 'display') return ok(w.window + '\t' + w.session + '\n')
      if (a === 'list-panes') {
        // a grouped _web-* view session is gone: the saved session name no longer resolves, a pane id does
        if (w.listOnlyPane && !String(e.argv[4]).startsWith('%')) return { value: { exitCode: 1, stdout: '', stderr: "can't find window: " + e.argv[4] } }
        return ok(w.panes)
      }
    }
    return ok()
  })
  on('ui.invalidate', () => { w.invalidations++; return { value: undefined } })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'sid1' }))
  on('turn.start', () => ({ turnId: 't1' }))
  on('turn.complete', () => ({ text: 'done' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('tool.check', () => ({ decision: 'allow' }))
  on('classic.PreToolUse', () => ({}))
  on('classic.PermissionRequest', () => ({}))
  on('classic.SessionStart', () => ({}))
  // stands for what is drawn below this mod
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['below'] }))
  return { w, clock }
}

const START = { surface: 'terminal', isInteractive: true, cwd: '/work' } as const
const BAND = {
  plugin: 'agent-board', component: 'AbovePrompt', viewport: { columns: 120, rows: 30 },
  props: { hasSurvey: false, isWorking: false, maxRows: 4, bodyColumns: 120, scroll: { offset: 0, bodyRows: 4 }, view: {} },
} as const

const put = (w: World, name: string, pane: string | null, state: string, updatedAt = 1000) =>
  w.files.set(DIR + '/' + name + '.json', JSON.stringify({ session_id: name, pane, state, since: updatedAt, updatedAt }))
const BAND_TEXT = /^(Needs you|busy|ready|\?)/

// ---- bandLine -------------------------------------------------------------------------------------------------

const P = (...names: string[]) => new Map(names.map((n, i) => ['%' + (i + 1), n] as [string, string]))
const F = (pane: string, state: string, updatedAt = 1000) => ({ pane, state, updatedAt })

// mutation: sort busy/ready before needs-you (drop the unshift) -> 'needs-you first with names' fails
test('bandLine: needs-you first with names, then counts', () => {
  const panes = P('claude', '✦ qrev', '✦ impl', '✦ docs', '✦ x')
  const files = [F('%2', 'needs-you'), F('%3', 'busy'), F('%4', 'busy'), F('%5', 'ready')]
  expect(bandLine(panes, files, '%1', 1000)).toBe('Needs you: ✦ qrev · busy 2 · ready 1')
})

test('bandLine: several needing you are joined with ", " in tmux order', () => {
  const panes = P('claude', '✦ a', '✦ b')
  expect(bandLine(panes, [F('%3', 'needs-you'), F('%2', 'needs-you')], '%1', 1000)).toBe('Needs you: ✦ a, ✦ b')
})

// mutation: change the ' · ' separator (or the counts' order busy, ready, ?) -> 'exact separator format' fails
test('bandLine: exact separator format and count order busy, ready, ?', () => {
  const panes = P('claude', '✦ a', '✦ b', '✦ c', '✦ d')
  const files = [F('%2', 'ready'), F('%3', 'busy'), F('%4', 'weird')]
  expect(bandLine(panes, files, '%1', 1000)).toBe('busy 1 · ready 1 · ? 2')
})

// mutation: always push every part (drop the `if (busy)` style guards) -> 'zero counts are left out' fails
test('bandLine: zero counts are left out', () => {
  const panes = P('claude', '✦ a')
  expect(bandLine(panes, [F('%2', 'busy')], '%1', 1000)).toBe('busy 1')
  expect(bandLine(panes, [F('%2', 'ready')], '%1', 1000)).toBe('ready 1')
})

// mutation: treat stale as ready (drop the age check) -> 'stale file counts as ?' fails
test('bandLine: stale file counts as ?, never as ready', () => {
  const panes = P('claude', '✦ a', '✦ b')
  expect(bandLine(panes, [F('%2', 'ready', 954), F('%3', 'needs-you', 954)], '%1', 1000)).toBe('? 2')
  // exactly 45 s old is still fresh
  expect(bandLine(P('claude', '✦ a'), [F('%2', 'ready', 955)], '%1', 1000)).toBe('ready 1')
})

// mutation: drop the `✦ ` prefix test (count nothing, or count every window) -> '✦ window with no file' fails
test('bandLine: a ✦ window with no file counts as ?', () => {
  expect(bandLine(P('claude', '✦ a'), [], '%1', 1000)).toBe('? 1')
})

// mutation: count every window with no file as ? -> 'non-✦ window with no file is left out' fails
test('bandLine: a non-✦ window with no file is left out', () => {
  expect(bandLine(P('claude', 'tasks', 'shell'), [], '%1', 1000)).toBe('')
})

// mutation: drop BOTH own-pane skips (`f.pane === own ||` and `if (id === own) continue`) -> 'own pane is left out' fails
test('bandLine: own pane is left out', () => {
  const panes = P('claude', '✦ a')
  expect(bandLine(P('claude', 'tasks'), [F('%1', 'needs-you')], '%1', 1000)).toBe('')
  expect(bandLine(panes, [F('%1', 'needs-you'), F('%2', 'busy')], '%1', 1000)).toBe('busy 1')
})

// mutation: first file wins instead of the largest updatedAt -> 'the freshest of two files wins' fails
test('bandLine: the freshest of two files for one pane wins', () => {
  const panes = P('claude', '✦ a')
  expect(bandLine(panes, [F('%2', 'busy', 990), F('%2', 'ready', 998)], '%1', 1000)).toBe('ready 1')
  expect(bandLine(panes, [F('%2', 'ready', 998), F('%2', 'busy', 990)], '%1', 1000)).toBe('ready 1')
})

// mutation: drop the `!panes.has(f.pane)` skip AND count best-file panes the pane list lacks -> this fails
// (the guard alone is shadowed by the loop over `panes`; it matters once a file's pane is counted by itself)
test('bandLine: a file for a pane not in the session is left out', () => {
  expect(bandLine(P('claude', 'tasks'), [F('%9', 'needs-you')], '%1', 1000)).toBe('')
})

test('bandLine: nothing at all is an empty string', () => {
  expect(bandLine(new Map(), [], '%1', 1000)).toBe('')
  expect(bandLine(P('claude'), [null as any, { pane: 5 } as any], '%1', 1000)).toBe('')
})

// ---- mounted ---------------------------------------------------------------------------------------------------

test('lead draws the line from fixture files above what is drawn below', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  put(w, 'a', '%2', 'needs-you')
  put(w, 'b', '%3', 'busy')
  await $.session.start(START)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'Needs you: ✦ qrev · busy 1' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'below' })).toBeDefined()
})

// mutation: return our Text without next(e)'s result -> the 'below' check fails
// mutation: draw the Box even when the line is empty -> 'no agents draws only below' fails
test('with no agents there is no band and what is drawn below is drawn', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  w.panes = '%1 claude\n%4 tasks\n'
  await $.session.start(START)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: BAND_TEXT })).toBeUndefined()
  expect(await ui.find({ type: 'Box' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'below' })).toBeDefined()
})

// mutation: accept any window name (`window === 'claude'` -> true) so the timers start in a non-lead -> 'non-lead runs no list-panes' fails
test('non-lead session draws nothing and runs no list-panes', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%2' })
  w.window = '✦ qrev'
  put(w, 'b', '%3', 'needs-you')
  await $.session.start(START)
  await clock.advance(30000)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: BAND_TEXT })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'below' })).toBeDefined()
  const tmux = w.runs.filter((r) => r[0] === 'tmux')
  expect(tmux.map((r) => r[1])).toEqual(['display'])
  expect(w.listCalls).toBe(0)
})

test('TMUX_PANE unset: no tmux call, no timers, nothing drawn', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  put(w, 'b', '%3', 'needs-you')
  await $.session.start(START)
  await clock.advance(30000)
  expect(w.runs.filter((r) => r[0] === 'tmux')).toEqual([])
  expect(w.listCalls).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: BAND_TEXT })).toBeUndefined()
})

test('pane list is read once at start with the session, files polled every 2 s', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  await $.session.start(START)
  expect(w.runs).toContainEqual(['tmux', 'display', '-p', '-t', '%1', '#{window_name}\t#{session_name}'])
  expect(w.runs).toContainEqual(['tmux', 'list-panes', '-s', '-t', '%1', '-F', '#{pane_id} #{window_name}'])
  const at0 = w.listCalls
  expect(at0).toBe(1)
  await clock.advance(2000)
  expect(w.listCalls).toBe(at0 + 1)
  const lp = () => w.runs.filter((r) => r[1] === 'list-panes').length
  expect(lp()).toBe(1)
  await clock.advance(8000)
  expect(lp()).toBe(2)
})

// mutation: target the saved session name again (`loadPanes($, session)`) -> the session name no longer resolves, the pane list
// stays frozen and the teammate window added after start is never counted -> this test fails
test('pane list is read by the lead pane id: a window added after start is counted though the session name stops resolving', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  w.listOnlyPane = true
  await $.session.start(START)
  w.panes += '%5 ✦ late\n'
  put(w, 'late', '%5', 'needs-you', 1000)
  await clock.advance(10000)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'Needs you: ✦ late' })).toBeDefined()
})

test('a changed file is drawn after the next poll, with ui.render invalidated', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  put(w, 'b', '%3', 'busy', 1000)
  await $.session.start(START)
  const before = w.invalidations
  put(w, 'b', '%3', 'needs-you', 1000)
  await clock.advance(2000)
  expect(w.invalidations).toBeGreaterThan(before)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'Needs you: ✦ impl' })).toBeDefined()
})

test('an unchanged line does not invalidate again', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  put(w, 'b', '%3', 'busy', 1000)
  await $.session.start(START)
  // keep the file fresh against the 45 s limit while the mock clock moves
  const before = w.invalidations
  await clock.advance(2000)
  await clock.advance(2000)
  expect(w.invalidations).toBe(before)
})

// ---- errors ----------------------------------------------------------------------------------------------------

// mutation: reset `line` to '' when a poll throws -> 'failed poll keeps the last line' fails
test('failed poll keeps the last line', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  put(w, 'a', '%2', 'needs-you')
  await $.session.start(START)
  w.failList = true
  await clock.advance(2000)
  await clock.advance(2000)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'Needs you: ✦ qrev' })).toBeDefined()
})

// mutation: drop the per-file try/catch around JSON.parse -> 'one unparsable file is skipped' fails
test('one unparsable file is skipped while the others count', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  put(w, 'a', '%2', 'busy')
  w.files.set(DIR + '/bad.json', '{not json')
  put(w, 'c', '%3', 'ready')
  w.files.set(DIR + '/note.txt', 'ignored')
  await $.session.start(START)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'busy 1 · ready 1' })).toBeDefined()
})

// mutation: drop the `d.exitCode === 0 &&` check (the failing tmux here still prints a lead answer) -> 'no timers' fails
test('failing tmux at start leaves no band and no timers', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  w.tmuxFail = true
  put(w, 'a', '%2', 'needs-you')
  await $.session.start(START)
  await clock.advance(60000)
  expect(w.listCalls).toBe(0)
  expect(w.runs.filter((r) => r[0] === 'tmux').length).toBe(1)
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: BAND_TEXT })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: 'below' })).toBeDefined()
})

// mutation: do not cancel the timers on session.end -> 'session.end stops the polling' fails
test('session.end stops the polling; /clear does not', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s', TMUX_PANE: '%1' })
  await $.session.start(START)
  await $.session.end({ reason: 'clear', sessionId: 'sid1', resume: {} } as any)
  const n = w.listCalls
  await clock.advance(2000)
  expect(w.listCalls).toBe(n + 1)
  await $.session.end({ reason: 'other', sessionId: 'sid1', resume: {} } as any)
  const m = w.listCalls
  await clock.advance(30000)
  expect(w.listCalls).toBe(m)
})
