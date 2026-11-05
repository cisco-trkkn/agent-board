// Tests for the agent-status mod. The world beneath the mod (files, processes, env, clock, session id) is
// answered from memory: nothing here touches the real state dir.
import { expect, test, mock } from 'claude-code/testing'

type World = { files: Map<string, string>; runs: string[][]; failWrite: boolean; failMv: boolean; sid: string; gate: Promise<void> | null; perms: any }

// Registers the stubs; call before the first `$` call. Returns the in-memory file system.
function world(on: any, env: Record<string, string>, under: { call?: any; check?: any; dialog?: any } = {}, now = 1_000_000): { w: World; clock: any } {
  const w: World = { files: new Map(), runs: [], failWrite: false, failMv: false, sid: 'sid1', gate: null, perms: {} }
  mock.env(on, env)
  const clock = mock.clock(on, { now })
  on('session.id', async () => {
    if (w.gate) await w.gate
    if (w.sid === 'THROW') throw new Error('no id')
    return { value: w.sid }
  })
  on('settings.read', () => ({ value: { permissions: w.perms } }))
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
  // The kit runs Claude Code's chain inside $.tool.call: classic.PreToolUse, tool.check, and, when the check says ask,
  // classic.PermissionRequest (the dialog; its stub's answer is the user's). `under.dialog` plays the user.
  on('classic.PreToolUse', () => ({}))
  on('classic.PermissionRequest', under.dialog ?? (() => ({})))
  on('classic.SessionStart', () => ({}))
  return { w, clock }
}

const ANSWER = { answer: 'ok', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' } as const
const ALLOW = { decision: { behavior: 'allow' } }
// a dialog the test releases: `open` resolves once it is on screen, `answer` closes it
function gatedDialog() {
  let answer: (v?: any) => void = () => {}
  let open: () => void = () => {}
  const opened = new Promise<void>((r) => (open = r))
  const answered = new Promise<any>((r) => (answer = r))
  const dialog = async () => { open(); return (await answered) ?? ALLOW }
  return { dialog, opened, answer }
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
  const d = gatedDialog()
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: () => ({ result: 'answered' }),
    check: () => ({ decision: 'ask', reason: 'Answer questions?' }),
    dialog: d.dialog,
  })
  await $.session.start(START)
  await $.turn.start({ text: 'q', turnId: 't1' })
  const p = $.tool.call({ tool: 'AskUserQuestion', questions: [], tool_use_id: 'q1' } as any)
  await d.opened
  await clock.settle()
  expect(read(w)).toMatchObject({ state: 'needs-you', since: 1000 })
  d.answer()
  await p
  expect(read(w).state).toBe('busy')
})

// A tool call in Claude Code: tool.call is entered, classic.PreToolUse fires, tool.check resolves (ask = a rule or the mode
// would prompt), then, only when a dialog really opens, classic.PermissionRequest fires; tool.call's next() returns after
// the answer and the tool. In auto mode the classifier approves an `ask` on its own and no PermissionRequest fires.
test('auto mode: tool.check ask with no dialog stays busy while the tool runs', async ($, on) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => (release = r))
  // the kit's own check (inside tool.call) allows; the explicit check below is the real one, which says ask in auto mode
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: async () => { await gate; return { result: 'ran' } },
    check: (_$: any, e: any) => (e.input.real ? { decision: 'ask', reason: "Claude requested permissions to use Bash, but you haven't granted it yet." } : { decision: 'allow' }),
  })
  w.perms = { defaultMode: 'auto' }
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const p = $.tool.call({ tool: 'Bash', command: 'sleep 20', tool_use_id: 'a1' } as any)
  await clock.settle()
  await $.tool.check({ tool: 'Bash', input: { command: 'sleep 20', real: true }, tool_use_id: 'a1' } as any)
  await clock.advance(5000)
  expect(read(w)).toMatchObject({ state: 'busy', since: 1000 })
  release()
  await p
  expect(read(w)).toMatchObject({ state: 'busy', since: 1000 })
})

test('a permission dialog: PermissionRequest -> needs-you; the answer and the tool -> busy', async ($, on) => {
  const d = gatedDialog()
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: () => ({ result: 'ran' }),
    check: () => ({ decision: 'ask', reason: 'touch needs approval' }),
    dialog: d.dialog,
  })
  w.perms = { defaultMode: 'auto' }   // started with --permission-mode default: the settings do not say so
  await $.session.start(START)
  await clock.advance(1000)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const p = $.tool.call({ tool: 'Bash', command: 'touch /x', tool_use_id: 'a1' } as any)
  await d.opened
  await clock.settle()
  expect(read(w)).toMatchObject({ state: 'needs-you', since: 1001 })
  await clock.advance(1000)
  d.answer()
  const out: any = await p
  expect(JSON.stringify(out)).toContain('ran')
  expect(read(w)).toMatchObject({ state: 'busy', since: 1002 })
})

test('two tools in parallel: a dialog for one, the other finishing -> still needs-you', async ($, on) => {
  const d = gatedDialog()
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: () => ({ result: 'ran' }),
    // only the first call prompts; the second is approved (in auto mode its check also says ask, with no dialog)
    check: (_$: any, e: any) => (e.input.command === 'touch /x' ? { decision: 'ask', reason: 'r' } : { decision: 'allow' }),
    dialog: d.dialog,
  })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const pa = $.tool.call({ tool: 'Bash', command: 'touch /x', tool_use_id: 'a1' } as any)
  await d.opened
  await clock.settle()
  expect(read(w).state).toBe('needs-you')
  await $.tool.check({ tool: 'Bash', input: { command: 'sleep 1', auto: true }, tool_use_id: 'b2' } as any)
  await $.tool.call({ tool: 'Bash', command: 'sleep 1', tool_use_id: 'b2' } as any)
  expect(read(w).state).toBe('needs-you')
  d.answer()
  await pa
  expect(read(w).state).toBe('busy')
})

test('a dialog answered No: tool.call returns a refusal -> busy', async ($, on) => {
  const d = gatedDialog()
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: () => ({ result: 'ran' }),
    check: () => ({ decision: 'ask', reason: 'r' }),
    dialog: d.dialog,
  })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const p = $.tool.call({ tool: 'Bash', command: 'rm x', tool_use_id: 'a1' } as any)
  await d.opened
  await clock.settle()
  expect(read(w).state).toBe('needs-you')
  d.answer({})   // no decision from the dialog: the kit denies the call
  const out: any = await p
  expect(JSON.stringify(out)).toContain('denied')
  expect(read(w).state).toBe('busy')
  await $.turn.complete(ANSWER)
  expect(read(w).state).toBe('ready')
})

test('tool.check allow leaves the state alone', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({ tool: 'Bash', command: 'ls', tool_use_id: 'a1' } as any)
  expect(read(w).state).toBe('busy')
})

test("a PermissionRequest with no matching ask of the main agent (a teammate's) leaves the state alone", async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' }, { check: () => ({ decision: 'ask', reason: 'r' }) })
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'startup' } as any)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'x' }, tool_use_id: 'm1', agentId: 'mate' } as any)
  await $.classic.PermissionRequest({ tool_name: 'Bash', tool_input: { command: 'x' }, permission_mode: 'default' } as any)
  expect(read(w).state).toBe('busy')
})

// Where the built-in guard loads (Team/Enterprise login or managed settings), no classic.* hook of this mod runs: no
// classic.SessionStart at startup, no classic.PreToolUse before tool.check. There an `ask` counts as a dialog unless
// the settings' default mode never prompts (the mode a flag or shift+tab set is not readable).
test('guarded session (no classic events), default mode: tool.check ask -> needs-you, busy when the call returns', async ($, on) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => (release = r))
  const { w, clock } = world(on, { TC_STATE: '/s' }, {
    call: async () => { await gate; return { result: 'ran' } },
    check: (_$: any, e: any) => (e.input.real ? { decision: 'ask', reason: 'r' } : { decision: 'allow' }),
  })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'touch /x', real: true }, tool_use_id: 'a1' } as any)
  expect(read(w).state).toBe('needs-you')
  const p = $.tool.call({ tool: 'Bash', command: 'touch /x', tool_use_id: 'a1' } as any)
  await clock.settle()
  expect(read(w).state).toBe('needs-you')
  release()
  await p
  expect(read(w).state).toBe('busy')
})

for (const mode of ['auto', 'bypassPermissions', 'dontAsk']) {
  test(`guarded session, settings defaultMode ${mode}: tool.check ask stays busy`, async ($, on) => {
    const { w } = world(on, { TC_STATE: '/s' }, { check: () => ({ decision: 'ask', reason: 'r' }) })
    w.perms = { defaultMode: mode }
    await $.session.start(START)
    await $.turn.start({ text: 'go', turnId: 't1' })
    await $.tool.check({ tool: 'Bash', input: { command: 'sleep 20' }, tool_use_id: 'a1' } as any)
    expect(read(w).state).toBe('busy')
  })
}

test('classic.SessionStart alone marks classic hooks live: a later ask with no dialog stays busy', async ($, on) => {
  const { w } = world(on, { TC_STATE: '/s' }, { check: () => ({ decision: 'ask', reason: 'r' }) })
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'startup' } as any)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.check({ tool: 'Bash', input: { command: 'sleep 20' }, tool_use_id: 'a1' } as any)
  expect(read(w).state).toBe('busy')
})

test('a dialog open at turn.complete -> ready', async ($, on) => {
  const d = gatedDialog()
  const { w, clock } = world(on, { TC_STATE: '/s' }, { check: () => ({ decision: 'ask', reason: 'r' }), dialog: d.dialog })
  await $.session.start(START)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const p = $.tool.call({ tool: 'Bash', command: 'rm x', tool_use_id: 'a1' } as any)
  await d.opened
  await clock.settle()
  expect(read(w).state).toBe('needs-you')
  await $.turn.complete({ ...ANSWER, answer: 'aborted', isAborted: true })
  expect(read(w).state).toBe('ready')
  d.answer({})
  await p
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

for (const reason of ['clear', 'resume']) {
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

test('after a clear, a failing session.id writes nothing (no file named null)', async ($, on) => {
  const { w, clock } = world(on, { TC_STATE: '/s' })
  await $.session.start(START)
  await $.session.end({ reason: 'clear', sessionId: 'sid1', resume: {} } as any)
  const before = w.runs.length
  w.sid = 'THROW'
  await $.turn.start({ text: 'a', turnId: 't1' })
  await clock.advance(15000)
  expect([...w.files.keys()]).toEqual([])
  expect(w.runs.slice(before)).toEqual([])
})
