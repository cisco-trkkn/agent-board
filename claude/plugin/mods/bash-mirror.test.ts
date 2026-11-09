// Tests for the bash-mirror mod. Replays the cases of tools/tests/test_mirror.zsh against an in-memory world: tmux
// (display / list-windows / has-session), the feed log files and the session's cwd are answered by stubs.
import { expect, test, mock } from 'claude-code/testing'
import { outcome } from './bash-mirror.js'

type World = {
  files: Map<string, string>
  runs: string[][]
  cwd: string
  windows: string[]
  hasBg: boolean
  caller: string
  failWrite: boolean
  failRead: boolean
  gate: Promise<void> | null
  sid: string
}

const SOCK = '/tmp/sock'
const LOG = (kind: string) => `/s/feed-tt-${kind}.log`
const HOME = '/home/me'
const HEADER = /^── \d{2}:\d{2}:\d{2} · (.*?) · (.*?) · exit (\d+) · @(\d+)$/

function world(on: any, env: Record<string, string> = {}, init: Partial<World> = {}): World {
  const w: World = { files: new Map(), runs: [], cwd: HOME + '/proj', windows: ['claude', 'shell', 'tests'], hasBg: false, caller: 'claude', failWrite: false, failRead: false, gate: null, sid: 'sid1', ...init }
  mock.env(on, { TC_STATE: '/s', HOME, TMUX: SOCK + ',123,0', TMUX_PANE: '%3', TC_TMUX: '/fake/tmux', ...env })
  mock.clock(on, { now: 1_000_000 })
  on('session.id', () => ({ value: w.sid }))
  on('session.cwd', () => ({ value: w.cwd }))
  on('settings.read', () => ({ value: { permissions: {} } }))
  on('fs.exists', ($: any, e: any) => ({ value: w.files.has(e.path) }))
  on('fs.read', ($: any, e: any) => {
    if (w.failRead && e.path.includes('/feed-')) throw new Error('too large')
    if (!w.files.has(e.path)) throw new Error('ENOENT')
    return { value: w.files.get(e.path) }
  })
  on('fs.write', async ($: any, e: any) => {
    if (w.gate && e.path.includes('/feed-')) await w.gate
    if (w.failWrite && e.path.includes('/feed-')) throw new Error('disk full')
    w.files.set(e.path, e.text)
    return { value: undefined }
  })
  on('process.run', ($: any, e: any) => {
    w.runs.push([...e.argv])
    const a: string[] = e.argv
    const out = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '' } })
    if (a.includes('display')) return out(`tt\t${w.caller}\ttt\n`)
    if (a.includes('list-windows')) return out(w.windows.join('\n') + '\n')
    if (a.includes('has-session')) return out('', w.hasBg ? 0 : 1)
    if (a[0] === 'rm') { w.files.delete(a[2]); return out('') }
    return out('503\n')
  })
  on('session.start', () => ({ cwd: HOME + '/proj' }))
  on('session.end', () => ({ sessionId: 'sid1' }))
  on('tool.check', () => ({ decision: 'allow' }))
  on('classic.PreToolUse', () => ({}))
  on('classic.PermissionRequest', () => ({}))
  on('classic.SessionStart', () => ({}))
  return w
}

const START = { surface: 'terminal', isInteractive: true, cwd: HOME + '/proj' } as const
const lines50 = Array.from({ length: 50 }, (_, i) => `line ${i + 1}`).join('\n')
const okResult = (stdout: string, stderr = '') => ({ result: { stdout, stderr, interrupted: false, isImage: false, noOutputExpected: false }, text: stdout })
const failResult = (code: number, body = '') => ({ result: `Error: Exit code ${code}${body ? '\n' + body : ''}`, text: `Exit code ${code}${body ? '\n' + body : ''}`, isError: true })

// the feed write runs after the tool returns: wait for it to settle
const settle = () => new Promise((r) => setTimeout(r, 40))
async function bash($: any, command: string) {
  const r = await $.tool.call({ tool: 'Bash', command })
  await settle()
  return r
}

// the feed with the time and epoch of each header replaced by fixed words
const norm = (s: string) => s.replace(/^── \d{2}:\d{2}:\d{2} · /gm, '── T · ').replace(/ · @\d+$/gm, ' · @E')

test('a successful call writes the tests entry: header, command, last 12 lines, blank line', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult(lines50))
  await $.session.start(START)
  await bash($, 'pytest -q tests/unit')
  const tail = Array.from({ length: 12 }, (_, i) => `line ${i + 39}`).join('\n')
  expect(norm(w.files.get(LOG('tests')) as string)).toBe(`── T · claude · ~/proj · exit 0 · @E\n$ pytest -q tests/unit\n${tail}\n\n`)
  expect(w.files.has(LOG('shell'))).toBe(false)
  expect((w.files.get(LOG('tests')) as string).split('\n')[0]).toMatch(HEADER)
  expect(w.files.get(LOG('tests'))!.split('\n')[0]).toMatch(/ · @1000$/)
})

test('a failed call: exit code from "Exit code N", body without that line, in the shell log', async ($, on) => {
  const w = world(on)
  on('tool.call', () => failResult(2, 'ls: /nope: No such file or directory'))
  await $.session.start(START)
  await bash($, 'ls -la /nope')
  expect(norm(w.files.get(LOG('shell')) as string)).toBe('── T · claude · ~/proj · exit 2 · @E\n$ ls -la /nope\nls: /nope: No such file or directory\n\n')
})

test('a failure with no number is exit 1', async ($, on) => {
  const w = world(on)
  on('tool.call', () => ({ result: 'Error: boom', text: 'boom', isError: true }))
  await $.session.start(START)
  await bash($, 'ls')
  expect(norm(w.files.get(LOG('shell')) as string)).toBe('── T · claude · ~/proj · exit 1 · @E\n$ ls\nboom\n\n')
})

test('a multiline command shows its first line and " …"', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('a\nb'))
  await $.session.start(START)
  await bash($, 'echo a\necho b')
  expect(w.files.get(LOG('shell'))).toContain('\n$ echo a …\na\nb\n')
})

test('stdout and stderr are joined with no separator, a call with no output has no body', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('out', 'err'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.files.get(LOG('shell'))).toContain('\n$ ls\nouterr\n')
})

test('no output: header and command only', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult(''))
  await $.session.start(START)
  await bash($, 'true')
  expect(norm(w.files.get(LOG('shell')) as string)).toBe('── T · claude · ~/proj · exit 0 · @E\n$ true\n\n')
})

test('a cwd outside the home is shown as is; the cwd is read after the call', async ($, on) => {
  const w = world(on, {}, { cwd: HOME + '/proj' })
  on('tool.call', () => { w.cwd = '/tmp/elsewhere'; return okResult('x') })
  await $.session.start(START)
  await bash($, 'cd /tmp/elsewhere')
  expect(w.files.get(LOG('shell'))).toContain(' · /tmp/elsewhere · exit 0')
})

test('the caller is the window name without the ✦ prefix', async ($, on) => {
  const w = world(on, {}, { caller: '✦ tester' })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.files.get(LOG('shell'))).toContain(' · tester · ')
})

test('entries append to the same log in order', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls one')
  await bash($, 'ls two')
  const t = norm(w.files.get(LOG('shell')) as string)
  expect(t).toBe('── T · claude · ~/proj · exit 0 · @E\n$ ls one\nx\n\n── T · claude · ~/proj · exit 0 · @E\n$ ls two\nx\n\n')
})

test('a log over 2097152 bytes is trimmed to its last 1048576 bytes before the entry is added', async ($, on) => {
  const w = world(on)
  w.files.set(LOG('tests'), 'x'.repeat(2_200_000))
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'pytest -q')
  const n = (w.files.get(LOG('tests')) as string).length
  expect(n).toBeLessThan(1_100_000)
  expect(n).toBeGreaterThan(1_048_576)
})

test('a log under the limit is not trimmed', async ($, on) => {
  const w = world(on)
  w.files.set(LOG('tests'), 'x'.repeat(2_000_000))
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'pytest -q')
  expect((w.files.get(LOG('tests')) as string).length).toBeGreaterThan(2_000_000)
})

const TESTS = ['pytest -q', 'X=1 pytest', 'cd x && make test', 'pnpm test', 'time pytest', 'env X=1 pytest', 'uv run pytest',
  'poetry run pytest', 'python -m pytest', 'python3 -m pytest', 'npx jest', 'sudo make', './gradlew test', "bash -c 'pytest'", 'sh -c "make test"']
const SHELL = ['ls -la', 'git status', "git commit -m 'fix; make it'", 'echo "pytest"']
for (const c of TESTS) {
  test(`tests: ${c}`, async ($, on) => {
    const w = world(on)
    on('tool.call', () => okResult('x'))
    await $.session.start(START)
    await bash($, c)
    expect(w.files.has(LOG('tests'))).toBe(true)
    expect(w.files.has(LOG('shell'))).toBe(false)
  })
}
for (const c of SHELL) {
  test(`shell: ${c}`, async ($, on) => {
    const w = world(on)
    on('tool.call', () => okResult('x'))
    await $.session.start(START)
    await bash($, c)
    expect(w.files.has(LOG('shell'))).toBe(true)
    expect(w.files.has(LOG('tests'))).toBe(false)
  })
}

test('a tmux-ctl command is skipped', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'tmux-ctl run tests "pytest"')
  await bash($, '  ~/.local/bin/tmux-ctl run tests x')
  await bash($, '/abs/path/tmux-ctl x')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
})

test('without TMUX or TMUX_PANE nothing is written and no tmux runs', async ($, on) => {
  const w = world(on, { TMUX: '' })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
  expect(w.runs.filter((a) => a[0] === '/fake/tmux')).toEqual([])
})

test('without TMUX_PANE nothing is written', async ($, on) => {
  const w = world(on, { TMUX_PANE: '' })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
})

test('no <project>-bg session and no window of that kind: nothing is written', async ($, on) => {
  const w = world(on, {}, { windows: ['claude'], hasBg: false })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
})

test('a <project>-bg session is enough: the entry is written without a local window of that kind', async ($, on) => {
  const w = world(on, {}, { windows: ['claude'], hasBg: true })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.files.has(LOG('shell'))).toBe(true)
  expect(w.runs).toContainEqual(['/fake/tmux', '-S', SOCK, 'has-session', '-t', '=tt-bg'])
})

test('the tmux calls: socket from TMUX, pane target, session target', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  const tm = w.runs.filter((a) => a[0] === '/fake/tmux')
  expect(tm[0].slice(0, 6)).toEqual(['/fake/tmux', '-S', SOCK, 'display', '-p', '-t'])
  expect(tm[0][6]).toBe('%3')
  expect(tm.find((a) => a.includes('list-windows'))).toEqual(['/fake/tmux', '-S', SOCK, 'list-windows', '-t', '=tt', '-F', '#{window_name}'])
})

test('tmux binary: $HOME/.local/bin/tmux when it exists, else tmux', async ($, on) => {
  const w = world(on, { TC_TMUX: '' })
  w.files.set(HOME + '/.local/bin/tmux', '')
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.runs.some((a) => a[0] === HOME + '/.local/bin/tmux' && a.includes('display'))).toBe(true)
})

test('tmux binary: plain tmux when there is no $HOME/.local/bin/tmux', async ($, on) => {
  const w = world(on, { TC_TMUX: '' })
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.runs.some((a) => a[0] === 'tmux' && a.includes('display'))).toBe(true)
})

test('a rejected next writes the entry with exit 1, then rethrows', async ($, on) => {
  const w = world(on)
  on('tool.call', () => { throw new Error('interrupted') })
  await $.session.start(START)
  let threw = false
  try { await $.tool.call({ tool: 'Bash', command: 'sleep 100' }) } catch (x) { threw = true }
  await settle()
  expect(threw).toBe(true)
  expect(norm(w.files.get(LOG('shell')) as string)).toContain('── T · claude · ~/proj · exit 1 · @E\n$ sleep 100\n')
})

test('a call a guard refused is not mirrored', async ($, on) => {
  const w = world(on)
  on('tool.call', () => ({ result: 'Error: Permission to use Bash denied by plugins agent-board: BLOCKED', text: 'Permission to use Bash denied by plugins agent-board: BLOCKED', isError: true }))
  await $.session.start(START)
  await bash($, 'pkill x')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
})

test('a subagent call (agentId) is mirrored too', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('sub'))
  await $.session.start(START)
  await $.tool.call({ tool: 'Bash', command: 'echo sub', agentId: 'a1' })
  await settle()
  expect(w.files.get(LOG('shell'))).toContain('$ echo sub\nsub\n')
})

test('a failing fs.write does not fail the call', async ($, on) => {
  const w = world(on, {}, { failWrite: true })
  on('tool.call', () => okResult('visible'))
  await $.session.start(START)
  const r = await bash($, 'ls')
  expect(JSON.stringify(r)).toContain('visible')
  expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
})

test('session.start writes the bash-mirror marker; session.end removes it', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  expect(w.files.get('/s/mods-active/sid1.bash-mirror')).toBe('sid1\n')
  await $.session.end({ sessionId: 'sid1', reason: 'exit' })
  expect(w.runs).toContainEqual(['rm', '-f', '/s/mods-active/sid1.bash-mirror'])
  expect(w.files.has('/s/mods-active/sid1.bash-mirror')).toBe(false)
})

const REFUSALS = [
  'Permission to use Bash denied by plugins agent-board: BLOCKED',
  "Claude requested permissions to use Bash, but you haven't granted it yet.",
  'The server-side auto mode classifier gave no verdict (it skipped this action), so auto mode cannot determine the safety of Bash.',
]
for (const text of REFUSALS) {
  test(`a refused call is not mirrored: ${text.slice(0, 30)}`, async ($, on) => {
    const w = world(on)
    on('tool.call', () => ({ result: 'Error: ' + text, text, isError: true }))
    await $.session.start(START)
    await bash($, 'ls')
    expect([...w.files.keys()].filter((k) => k.includes('/feed-'))).toEqual([])
  })
}

test('an interrupted or timed-out call is still mirrored as exit 1', async ($, on) => {
  const w = world(on)
  on('tool.call', () => ({ result: 'Error: Command timed out', text: 'Command timed out', isError: true }))
  await $.session.start(START)
  await bash($, 'sleep 999')
  expect(norm(w.files.get(LOG('shell')) as string)).toContain(' · exit 1 · @E\n$ sleep 999\nCommand timed out\n')
})

// the kit cannot make next() reject with a chosen message (a throwing stub is reported as a skipped hook), so the
// rejection rules are checked on outcome() itself
test('a rejection carrying "Exit code 3" is exit 3 with the rest as output; without a number it is exit 1', () => {
  expect(outcome(undefined, true, new Error('Exit code 3\nboom'))).toEqual([3, 'boom'])
  expect(outcome(undefined, true, new Error('interrupted'))).toEqual([1, 'interrupted'])
})

test('the tool result does not wait for the feed write', async ($, on) => {
  let release: () => void = () => {}
  const w = world(on, {}, { gate: new Promise<void>((r) => (release = r)) })
  on('tool.call', () => okResult('fast'))
  await $.session.start(START)
  const r = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(JSON.stringify(r)).toContain('fast')
  await settle()
  expect(w.files.has(LOG('shell'))).toBe(false) // the write is still pending
  release()
  await settle()
  expect(w.files.has(LOG('shell'))).toBe(true)
})

test('a log that exists but cannot be read is not replaced by a one-entry log', async ($, on) => {
  const w = world(on, {}, { failRead: true })
  w.files.set(LOG('shell'), 'old entries\n')
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await bash($, 'ls')
  expect(w.files.get(LOG('shell'))).toBe('old entries\n')
})

test('after a clear the next Bash call re-keys the marker: the old one is removed, one for the new id is written', async ($, on) => {
  const w = world(on)
  on('tool.call', () => okResult('x'))
  await $.session.start(START)
  await $.session.end({ sessionId: 'sid1', reason: 'clear' } as any)
  w.sid = 'sid2'
  await bash($, 'ls')
  expect([...w.files.keys()].filter((k) => k.endsWith('.bash-mirror')).sort()).toEqual(['/s/mods-active/sid2.bash-mirror'])
  expect(w.files.has(LOG('shell'))).toBe(true)
})
