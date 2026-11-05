// Tests for the agent-status mod. The world beneath the mod (files, processes, env, clock, session id) is
// answered from memory: nothing here touches the real state dir.
import { expect, test, mock } from 'claude-code/testing'

type World = { files: Map<string, string>; runs: string[][]; failWrite: boolean; failMv: boolean; sid: string; gate: Promise<void> | null }

// Registers the stubs; call before the first `$` call. Returns the in-memory file system.
function world(on: any, env: Record<string, string>, under: { call?: any; check?: any } = {}, now = 1_000_000): { w: World; clock: any } {
  const w: World = { files: new Map(), runs: [], failWrite: false, failMv: false, sid: 'sid1', gate: null }
  mock.env(on, env)
  const clock = mock.clock(on, { now })
  on('session.id', async () => {
    if (w.gate) await w.gate
    return { value: w.sid }
  })
  on('fs.write', ($: any, e: any) => {
    if (w.failWrite) throw new Error('disk full')
    w.files.set(e.path, e.text)
    return { value: undefined }
  })
  on('process.run', ($: any, e: any) => {
    w.runs.push([...e.argv])
    const [cmd, a, b] = e.argv
    if (cmd === 'id') return { value: { exitCode: 0, stdout: '503\n', stderr: '' } }
    if (cmd === 'mv') {
      if (w.failMv) return { value: { exitCode: 1, stdout: '', stderr: 'nope' } }
      w.files.set(b, w.files.get(a) as string)
      w.files.delete(a)
      return { value: { exitCode: 0, stdout: '', stderr: '' } }
    }
    if (cmd === 'rm') {
      w.files.delete(e.argv[2])
      return { value: { exitCode: 0, stdout: '', stderr: '' } }
    }
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  // what answers each event beneath the mod (the engine's own side)
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'sid1' }))
  on('turn.start', () => ({ turnId: 't1' }))
  on('turn.complete', () => ({ text: 'done' }))
  on('tool.call', under.call ?? (() => ({ result: 'ok' })))
  on('tool.check', under.check ?? (() => ({ decision: 'allow' })))
  return { w, clock }
}

const FILE = '/s/agent-status/sid1.json'
const read = (w: World, f = FILE) => JSON.parse(w.files.get(f) as string)
const START = { surface: 'terminal', isInteractive: true, cwd: '/work' } as const

test('session.start writes a ready file with all five keys and the pane', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s', TMUX_PANE: '%3' })
  await $.session.start(START)
  expect(read(w)).toEqual({ session_id: 'sid1', pane: '%3', state: 'ready', since: 1000, updatedAt: 1000 })
})

test('pane is null when TMUX_PANE is unset', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  expect(read(w)).toEqual({ session_id: 'sid1', pane: null, state: 'ready', since: 1000, updatedAt: 1000 })
})

test('state dir: TC_STATE wins; else TMPDIR minus trailing slash + /tmux-ctl-<uid>', async ($, on) => {
  const { w } = world(on, { TMPDIR: '/x/' })
  await $.session.start(START)
  expect(read(w, '/x/tmux-ctl-503/agent-status/sid1.json').state).toBe('ready')
  expect([...w.files.keys()]).toEqual(['/x/tmux-ctl-503/agent-status/sid1.json'])
})

test('state dir falls back to /tmp when TMPDIR is unset', async ($, on) => {
  const { w } = world(on, {})
  await $.session.start(START)
  expect(read(w, '/tmp/tmux-ctl-503/agent-status/sid1.json').state).toBe('ready')
})

test('writes go to a .tmp file, then mv', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  expect(w.runs).toContainEqual(['mv', FILE + '.tmp', FILE])
  expect(w.files.has(FILE + '.tmp')).toBe(false)
})

test('a failing mv falls back to a direct write', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  w.failMv = true
  await $.session.start(START)
  expect(read(w).state).toBe('ready')
})

test('turn.start -> busy, turn.complete -> ready', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await clock.advance(5000)
  await $.turn.start({ text: 'hi', turnId: 't1' })
  expect(read(w)).toMatchObject({ state: 'busy', since: 1005, updatedAt: 1005 })
  await clock.advance(2000)
  await $.turn.complete({ answer: 'ok', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(read(w)).toMatchObject({ state: 'ready', since: 1007 })
})

test('since changes only when state changes', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.turn.start({ text: 'a', turnId: 't1' })
  await clock.advance(3000)
  await $.turn.start({ text: 'b', turnId: 't1' })
  expect(read(w)).toMatchObject({ state: 'busy', since: 1000, updatedAt: 1003 })
})

test('AskUserQuestion tool.call is needs-you during next(), busy after', async ($, on) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => (release = r))
  const { w, clock } = world(on, { TC_STATE: '/s' }, { call: async () => { await gate; return { result: 'answered' } } })
  await $.session.start(START)
  await $.turn.start({ text: 'q', turnId: 't1' })
  const p = $.tool.call({ tool: 'AskUserQuestion', questions: [] } as any)
  await clock.settle()
  expect(read(w).state).toBe('needs-you')
  release()
  await p
  expect(read(w).state).toBe('busy')
})

test('tool.check ask -> needs-you; that tool.call returning -> busy', async ($, on) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => (release = r))
  // the kit's own permission check also runs once the call proceeds; only our explicit check (marked) asks
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: async () => { await gate; return { result: 'ran' } },
    check: (_$: any, e: any) => (e.input.explicit ? { decision: 'ask', reason: 'needs approval' } : { decision: 'allow' }),
  })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  // the order Claude Code uses: tool.call is entered first, then tool.check, and next() returns after the answer
  const p = $.tool.call({ tool: 'Bash', command: 'touch /x' } as any)
  await clock.settle()
  expect(read(w).state).toBe('busy')
  await $.tool.check({ tool: 'Bash', input: { command: 'touch /x', explicit: true } })
  expect(read(w).state).toBe('needs-you')
  release()
  await p
  expect(read(w).state).toBe('busy')
})

test('tool.check allow leaves the state alone', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'ls' } })
  expect(read(w).state).toBe('busy')
})

test('tool.check ask then turn.complete -> ready', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' }, { check: () => ({ decision: 'ask', reason: 'r' }) })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'rm x' } })
  expect(read(w).state).toBe('needs-you')
  await $.turn.complete({ answer: 'denied', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' })
  expect(read(w).state).toBe('ready')
})

test('heartbeat every 15 s rewrites updatedAt only', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const before = read(w)
  await clock.advance(15000)
  expect(read(w)).toEqual({ ...before, updatedAt: before.updatedAt + 15 })
  await clock.advance(15000)
  expect(read(w)).toEqual({ ...before, updatedAt: before.updatedAt + 30 })
})

test('session.end deletes the file and stops the heartbeat', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.session.end({ reason: 'other', sessionId: 'sid1', resume: {} } as any)
  expect(w.files.has(FILE)).toBe(false)
  expect(w.runs).toContainEqual(['rm', '-f', FILE])
  await clock.advance(30000)
  expect(w.files.has(FILE)).toBe(false)
})

test('a throwing write does not propagate and the hook still returns next()', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' }, { call: () => ({ result: 'ran' }) })
  await $.session.start(START)
  w.failWrite = true
  await $.turn.start({ text: 'go', turnId: 't1' })
  const out: any = await $.tool.call({ tool: 'Bash', command: 'ls' } as any)
  expect(JSON.stringify(out)).toContain('ran')
  await $.turn.complete({ answer: 'ok', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' })
})

test('events carrying agentId (an in-process teammate) leave the file untouched', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    check: (_$: any, e: any) => (e.input.sub ? { decision: 'ask', reason: 'r' } : { decision: 'allow' }),
  })
  await $.session.start(START)
  await clock.advance(2000)
  await $.turn.start({ text: 'x', turnId: 't2', agentId: 'mate' } as any)
  expect(read(w)).toMatchObject({ state: 'ready', since: 1000 })
  await $.tool.call({ tool: 'AskUserQuestion', questions: [], agentId: 'mate' } as any)
  expect(read(w)).toMatchObject({ state: 'ready', since: 1000 })
  await $.tool.check({ tool: 'Bash', input: { command: 'x', sub: true }, agentId: 'mate' } as any)
  expect(read(w)).toMatchObject({ state: 'ready', since: 1000 })
  // main agent busy: a teammate's turn.complete must not make it ready
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.turn.complete({ answer: 'm', durationMs: 5, isAborted: false, turnId: 't2', reason: 'answer', agentId: 'mate' } as any)
  expect(read(w).state).toBe('busy')
})

for (const reason of ['clear', 'resume', 'branch']) {
  test(`session.end (${reason}) drops the old file, resets to ready, and the next event writes under the new id`, async ($, on) => {
    const { w, clock } = world(on, { TC_STATE: '/s' })
    await $.session.start(START)
    await $.turn.start({ text: 'a', turnId: 't1' })
    await $.session.end({ reason, sessionId: 'sid1', resume: {} } as any)
    expect(w.files.has(FILE)).toBe(false)
    w.sid = 'sid2'
    await clock.advance(1000)
    await $.turn.start({ text: 'b', turnId: 't2' })
    expect(w.files.has(FILE)).toBe(false)
    expect(read(w, '/s/agent-status/sid2.json')).toMatchObject({ session_id: 'sid2', state: 'busy' })
    await $.turn.complete({ answer: 'm', durationMs: 5, isAborted: false, turnId: 't2', reason: 'answer' })
    expect(read(w, '/s/agent-status/sid2.json').state).toBe('ready')
  })
}

test('after a clear the heartbeat writes a ready file for the new id', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.turn.start({ text: 'a', turnId: 't1' })
  await $.session.end({ reason: 'clear', sessionId: 'sid1', resume: {} } as any)
  w.sid = 'sid2'
  await clock.advance(15000)
  expect(read(w, '/s/agent-status/sid2.json')).toMatchObject({ session_id: 'sid2', state: 'ready' })
  expect(w.files.has(FILE)).toBe(false)
})

test('a write waiting on session.id when session.end (other) runs leaves no file behind', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  let open: () => void = () => {}
  w.gate = new Promise<void>((r) => (open = r))
  const p = $.turn.start({ text: 'a', turnId: 't1' })
  await clock.settle()
  await $.session.end({ reason: 'other', sessionId: 'sid1', resume: {} } as any)
  expect(w.files.has(FILE)).toBe(false)
  w.gate = null
  open()
  await p
  await clock.advance(15000)
  expect([...w.files.keys()]).toEqual([])
})

test('an id change without session.end moves the file: old gone, new present', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  w.sid = 'sid2'
  await $.turn.start({ text: 'a', turnId: 't1' })
  expect(w.files.has(FILE)).toBe(false)
  expect(read(w, '/s/agent-status/sid2.json')).toMatchObject({ session_id: 'sid2', state: 'busy' })
})
