// Tests for the artifact-register mod. Replays the hook-mode cases of tools/tests/test_artifact_hook.zsh against an
// in-memory world: tmux, the manifest and lineage files, realpath and shasum are answered by stubs.
// Artifact and Claude Docs calls are not the mod's (they stay on artifact-register.sh), so they are not replayed here.
import { expect, test, mock } from 'claude-code/testing'

type World = {
  files: Map<string, string>
  runs: string[][]
  result: any
  caller: string
  project: string
  sid: string
  failRead: boolean
  failWrite: boolean
  noShasum: boolean
  noSha256sum: boolean
}

const APPEND = 'printf %s "$1" >> "$2"'
const HOME = '/home/me'
const MANIFEST = '/s/artifacts-tt.jsonl'
const HASH = 'ab'.repeat(32)
const PLAN = '/work/r/docs/superpowers/plans/p.md'

function world(on: any, env: Record<string, string> = {}, init: Partial<World> = {}): World {
  const w: World = { files: new Map(), runs: [], result: 'ok', caller: '✦ impl', project: 'tt', sid: 'S1', failRead: false, failWrite: false, noShasum: false, noSha256sum: false, ...init }
  mock.env(on, { TC_STATE: '/s', TC_LINEAGE: '/s/lineage', HOME, TMPDIR: '/tmp/', TMUX: '/tmp/sock,1,0', TMUX_PANE: '%3', TC_TMUX: '/fake/tmux', ...env })
  mock.clock(on, { now: 5_000_000 })
  on('session.id', () => ({ value: w.sid }))
  on('settings.read', () => ({ value: { permissions: {} } }))
  on('fs.exists', ($: any, e: any) => ({ value: w.files.has(e.path) }))
  on('fs.read', ($: any, e: any) => {
    if (w.failRead || !w.files.has(e.path)) throw new Error('ENOENT')
    return { value: w.files.get(e.path) }
  })
  on('fs.write', ($: any, e: any) => {
    w.files.set(e.path, e.text)
    return { value: undefined }
  })
  on('process.run', ($: any, e: any) => {
    w.runs.push([...e.argv])
    const a: string[] = e.argv
    const out = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '' } })
    if (a.includes('display')) return out(`${w.project}\t${w.caller}\n`)
    if (a[0] === 'realpath') return w.files.has(a[1]) || a[1] === HOME || a[1] === '/tmp' ? out(a[1] + '\n') : out('', 1)
    if (a[0] === 'shasum') return w.noShasum || !w.files.has(a[3]) ? out('', 1) : out(`${HASH}  ${a[3]}\n`)
    if (a[0] === 'sha256sum') return w.noSha256sum || !w.files.has(a[1]) ? out('', 1) : out(`${HASH}  ${a[1]}\n`)
    if (a[0] === 'rm') { w.files.delete(a[2]); return out('') }
    if (a[0] === 'mkdir') return out('')
    // the manifest is appended by `sh -c` (the stub does what the script does)
    if (a[0] === 'sh' && a[2] === APPEND) {
      if (w.failWrite) return out('', 1)
      w.files.set(a[5], (w.files.get(a[5]) || '') + a[4])
      return out('')
    }
    return out('503\n')
  })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: w.sid }))
  on('tool.check', () => ({ decision: 'allow' }))
  on('tool.call', () => (typeof w.result === 'function' ? w.result() : { result: w.result }))
  on('classic.PreToolUse', () => ({}))
  on('classic.PermissionRequest', () => ({}))
  on('classic.SessionStart', () => ({}))
  return w
}

const START = { surface: 'terminal', isInteractive: true, cwd: '/work' } as const
const lines = (w: World) => ((w.files.get(MANIFEST) as string) || '').split('\n').filter(Boolean).map((l) => JSON.parse(l))
const last = (w: World) => lines(w).slice(-1)[0]

async function write($: any, file: string, tool = 'Write') {
  return $.tool.call({ tool, file_path: file })
}

test('a plan write is recorded with kind, agent, hash, session id and epoch 0', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(lines(w).length).toBe(1)
  const r = last(w)
  expect(Object.keys(r)).toEqual(['ts', 'path', 'kind', 'agent', 'hash', 'url', 'title', 'slug', 'session_id', 'epoch'])
  expect(r).toEqual({ ts: 5000, path: PLAN, kind: 'plan', agent: 'impl', hash: HASH, url: '', title: '', slug: '', session_id: 'S1', epoch: 0 })
})

test('Edit and MultiEdit are recorded like Write', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN, 'Edit')
  await write($, PLAN, 'MultiEdit')
  expect(lines(w).map((r) => r.kind)).toEqual(['plan', 'plan'])
})

test('the session id comes from $.session.id()', async ($, on) => {
  const w = world(on, {}, { sid: 'S9' })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(last(w).session_id).toBe('S9')
})

test('an .md file of no known kind is ignored; a non-.md file too', async ($, on) => {
  const w = world(on)
  w.files.set('/work/r/notes.md', 'x')
  w.files.set('/work/r/a.txt', 'x')
  await $.session.start(START)
  await write($, '/work/r/notes.md', 'Edit')
  await write($, '/work/r/a.txt')
  expect(lines(w).length).toBe(0)
})

test('epoch is the line count of the lineage file', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  w.files.set('/s/lineage/tt.jsonl', '{}\n')
  await $.session.start(START)
  await write($, PLAN, 'Edit')
  expect(last(w).epoch).toBe(1)
})

test('lineage dir follows XDG_STATE_HOME / $HOME/.local/state when TC_LINEAGE is unset', async ($, on) => {
  const w = world(on, { TC_LINEAGE: '', XDG_STATE_HOME: '/xdg' })
  w.files.set(PLAN, '# P')
  w.files.set('/xdg/agent-board/lineage/tt.jsonl', '{}\n{}\n')
  await $.session.start(START)
  await write($, PLAN)
  expect(last(w).epoch).toBe(2)
})

test('report kind: a scratchpad *report*.md', async ($, on) => {
  const w = world(on)
  const f = '/work/sp/scratchpad/e2e-report.md'
  w.files.set(f, 'r')
  await $.session.start(START)
  await write($, f)
  expect(last(w).kind).toBe('report')
})

test('handoff kinds: a tmp handoff, the state dir handoffs, the legacy ~/.claude/handoffs', async ($, on) => {
  const w = world(on)
  const files = ['/tmp/tt-handoff-1.md', HOME + '/.local/state/agent-board/handoffs/new.md', HOME + '/.claude/handoffs/old.md']
  for (const f of files) w.files.set(f, 'h')
  await $.session.start(START)
  for (const f of files) await write($, f)
  expect(lines(w).map((r) => [r.path, r.kind])).toEqual(files.map((f) => [f, 'handoff']))
})

test('file lines carry a title key', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect('title' in last(w)).toBe(true)
})

test('the manifest is never read: one that cannot be read keeps its lines and gets the record appended', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  w.files.set(MANIFEST, '{"old":1}\n')
  await $.session.start(START)
  w.failRead = true
  await write($, PLAN)
  w.failRead = false
  const ls = (w.files.get(MANIFEST) as string).split('\n')
  expect(ls[0]).toBe('{"old":1}')
  expect(JSON.parse(ls[1]).kind).toBe('plan')
})

test('the record is appended with one sh -c printf >> call: the JSON line and the manifest as argv', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  const calls = w.runs.filter((r) => r[0] === 'sh')
  expect(calls.length).toBe(1)
  expect(calls[0].slice(0, 3)).toEqual(['sh', '-c', APPEND])
  expect(calls[0].length).toBe(6)
  expect(calls[0][3]).toBe('sh')
  expect(calls[0][4]).toBe(JSON.stringify(last(w)) + '\n')
  expect(calls[0][5]).toBe(MANIFEST)
  expect(w.runs).toContainEqual(['mkdir', '-p', '/s'])
})

test('records append to the existing manifest in order', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  w.files.set(MANIFEST, '{"old":1}\n')
  await $.session.start(START)
  await write($, PLAN)
  const ls = (w.files.get(MANIFEST) as string).split('\n')
  expect(ls[0]).toBe('{"old":1}')
  expect(JSON.parse(ls[1]).kind).toBe('plan')
  expect(ls[2]).toBe('')
})

test('outside tmux nothing is recorded', async ($, on) => {
  const w = world(on, { TMUX: '', TMUX_PANE: '' })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(w.files.has(MANIFEST)).toBe(false)
})

test('a project name that is not [A-Za-z0-9._-]+ records nothing', async ($, on) => {
  const w = world(on, {}, { project: 'bad name' })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect([...w.files.keys()].filter((k) => k.includes('artifacts-'))).toEqual([])
})

test('the agent defaults to claude when the window name is empty', async ($, on) => {
  const w = world(on, {}, { caller: '' })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(last(w).agent).toBe('claude')
})

test('a file that does not exist records nothing', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await write($, PLAN)
  expect(lines(w).length).toBe(0)
})

test('a failed or refused write records nothing', async ($, on) => {
  const w = world(on, {}, { result: () => ({ result: 'Error: nope', text: 'nope', isError: true }) })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  w.result = () => ({ deny: 'no' })
  await write($, PLAN)
  expect(lines(w).length).toBe(0)
})

test('a rejected next records nothing and rethrows', async ($, on) => {
  const w = world(on, {}, { result: () => { throw new Error('interrupted') } })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  let threw = false
  try { await write($, PLAN) } catch (x) { threw = true }
  expect(threw).toBe(true)
  expect(lines(w).length).toBe(0)
})

test('a subagent call (agentId) is recorded too', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await $.tool.call({ tool: 'Write', file_path: PLAN, agentId: 'a1' })
  expect(lines(w).length).toBe(1)
})

test('a failing manifest write does not fail the call', async ($, on) => {
  const w = world(on, {}, { failWrite: true })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  const r = await write($, PLAN)
  expect(JSON.stringify(r)).toContain('ok')
})

test('session.start writes the artifact-register marker; session.end removes it', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  expect(w.files.get('/s/mods-active/S1.artifact-register')).toBe('S1\n')
  await $.session.end({ sessionId: 'S1', reason: 'exit' })
  expect(w.runs).toContainEqual(['rm', '-f', '/s/mods-active/S1.artifact-register'])
  expect(w.files.has('/s/mods-active/S1.artifact-register')).toBe(false)
})

test('Artifact and Claude Docs calls are not handled by the mod', async ($, on) => {
  const w = world(on, {}, { result: 'Published https://claude.ai/code/artifact/abc-123 ok' })
  await $.session.start(START)
  await $.tool.call({ tool: 'Artifact', file_path: '/x/page.html' })
  await $.tool.call({ tool: 'mcp__claude_ai_Claude_Docs__batch', container: { kind: 'project', id: 'x' }, batch: [] })
  expect(w.files.has(MANIFEST)).toBe(false)
  expect(w.runs.filter((a) => a[0] === 'realpath' || a[0] === '/fake/tmux')).toEqual([])
})

test('an edit with no kind costs only the realpath: no tmux, shasum, lineage read or session lookup', async ($, on) => {
  const w = world(on)
  w.files.set('/work/r/src.ts', 'x')
  w.files.set('/work/r/notes.md', 'x')
  await $.session.start(START)
  w.runs.length = 0
  await write($, '/work/r/src.ts', 'Edit')
  await write($, '/work/r/notes.md', 'Edit')
  // agent-status (same plugin, same world) writes its status file with `mv` on every tool call: not this mod's cost
  const runs = w.runs.filter((a) => !(a[0] === 'mv' && a[1].includes('/agent-status/')))
  expect(runs.length).toBeGreaterThan(0)
  expect(runs.every((a) => a[0] === 'realpath')).toBe(true)
  expect(runs.some((a) => a[0] === '/fake/tmux' || a[0] === 'shasum' || a[0] === 'sha256sum')).toBe(false)
  expect(w.files.has(MANIFEST)).toBe(false)
})

test('sha256sum is tried when shasum fails', async ($, on) => {
  const w = world(on, {}, { noShasum: true })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(last(w).hash).toBe(HASH)
  expect(w.runs.some((a) => a[0] === 'sha256sum')).toBe(true)
})

test('no hash tool works: nothing is recorded', async ($, on) => {
  const w = world(on, {}, { noShasum: true, noSha256sum: true })
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await write($, PLAN)
  expect(lines(w).length).toBe(0)
})

test('after a clear the next file tool call re-keys the marker: the old one is removed, one for the new id is written', async ($, on) => {
  const w = world(on)
  w.files.set(PLAN, '# P')
  await $.session.start(START)
  await $.session.end({ sessionId: 'S1', reason: 'clear' } as any)
  w.sid = 'S2'
  await write($, PLAN)
  expect([...w.files.keys()].filter((k) => k.endsWith('.artifact-register')).sort()).toEqual(['/s/mods-active/S2.artifact-register'])
  expect(last(w).session_id).toBe('S2')
})
