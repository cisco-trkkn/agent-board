// Tests for the kill-guard mod. Replays every case of tools/tests/test_kill_guard.zsh: the process table (`ps`) and
// `readlink /proc/<pid>/exe` are answered from memory by a process.run stub, so no real process is looked at or killed.
import { expect, test, mock } from 'claude-code/testing'

type Proc = { pid: number; comm: string; args: string; exe?: string }
type World = { files: Map<string, string>; runs: string[][]; procs: Proc[]; throwRun: boolean; sid: string }

const P = 4242 // stands in for $$ of the zsh test: a unique suffix in every pattern
const CLAUDE: Proc = { pid: 100, comm: '/x/claude/versions/9.9.9', args: `/x/claude/versions/9.9.9 -c sleep 300; : GUARDPAT-${P}` }
const DECOY: Proc = { pid: 101, comm: '/bin/sh', args: `/bin/sh -c sleep 300 DECOYPAT-${P}` }
// npm install: the executable is node, the process calls itself claude (argv[0]); /proc/<pid>/exe is node
const NPM: Proc = { pid: 102, comm: '/x/npm/node', args: `claude -c sleep 300; : NPMPAT-${P}`, exe: '/usr/bin/node' }

function world(on: any, procs: Proc[], env: Record<string, string> = { TC_STATE: '/s' }): World {
  const w: World = { files: new Map(), runs: [], procs, throwRun: false, sid: 'sid1' }
  mock.env(on, env)
  mock.clock(on, { now: 1_000_000 })
  on('session.id', () => ({ value: w.sid }))
  on('settings.read', () => ({ value: { permissions: {} } }))
  on('fs.write', ($: any, e: any) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('process.run', ($: any, e: any) => {
    if (w.throwRun) throw new Error('no process')
    w.runs.push([...e.argv])
    const [cmd, a, b, c] = e.argv
    const out = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '' } })
    if (cmd === 'ps') {
      const col = c === 'pid=,comm=' ? 'comm' : 'args'
      return out(w.procs.map((p) => `${String(p.pid).padStart(6)} ${p[col as 'comm' | 'args']}`).join('\n') + '\n')
    }
    if (cmd === 'readlink') {
      const pid = Number(String(a).split('/')[2])
      const p = w.procs.find((x) => x.pid === pid)
      return p && p.exe ? out(p.exe + '\n') : out('', 1)
    }
    if (cmd === 'rm') { w.files.delete(b === '-f' ? c : b); return out('') }
    return out('503\n')
  })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'sid1' }))
  on('tool.call', () => ({ result: 'ran' }))
  on('tool.check', () => ({ decision: 'allow' }))
  on('classic.PreToolUse', () => ({}))
  on('classic.PermissionRequest', () => ({}))
  on('classic.SessionStart', () => ({}))
  return w
}

const text = (r: any) => JSON.stringify(r)
const blocked = (r: any) => text(r).includes('would also kill Claude Code process')
const base = [CLAUDE, DECOY, NPM]

async function decide($: any, cmd: string, tool = 'Bash') {
  return $.tool.call({ tool, command: cmd })
}

const BLOCK: [string, string][] = [
  ['pkill -f matching fake claude', `pkill -f 'GUARDPAT-${P}'`],
  ['killall claude binary name', 'killall 9.9.9'],
  ['compound segment', `echo hi; pkill -f GUARDPAT-${P} && true`],
  ['sudo pkill', `sudo pkill -f GUARDPAT-${P}`],
  ['single & separator', `echo x & pkill -f GUARDPAT-${P}`],
  ['bash -c nested', `bash -c "pkill -f GUARDPAT-${P}"`],
  ['VAR=1 prefix', `VAR=1 pkill -f GUARDPAT-${P}`],
  ['xargs/env/subshell', `echo | xargs pkill -f GUARDPAT-${P}; (env pkill -f GUARDPAT-${P})`],
  ['quoted ; pattern', `pkill -f "GUARDPAT-${P}|a;b"`],
  ['unbalanced quote falls back to regex', `pkill -f 'GUARDPAT-${P}`],
  ['npm-style claude (exe is node, name claude)', `pkill -f 'NPMPAT-${P}'`],
  ['flag cluster containing f', `pkill -xf 'GUARDPAT-${P}'`],
  ['nested two deep', `bash -c "sh -c 'pkill -f GUARDPAT-${P}'"`],
]
for (const [name, cmd] of BLOCK) {
  test(`blocked: ${name}`, async ($, on) => {
    world(on, base)
    expect(blocked(await decide($, cmd))).toBe(true)
  })
}

const ALLOW: [string, string][] = [
  ['pkill -f matching decoy', `pkill -f 'DECOYPAT-${P}'`],
  ['killall sleep', 'killall sleep'],
  ['kill by pid', 'kill 1234'],
  ['pkill without -f matches name only', `pkill GUARDPAT-${P}`],
  ['decoy via bash -c', `bash -c 'pkill -f DECOYPAT-${P}'`],
  ['no pkill at all', 'ls -la'],
  ['pkill with no pattern', 'pkill -f'],
  ['long option is not a -f cluster', `pkill --full GUARDPAT-${P}`],
  ['too deep (4 levels) is not scanned', `bash -c "bash -c \\"bash -c 'bash -c \\\\\\"pkill -f GUARDPAT-${P}\\\\\\"'\\"\\""`],
]
for (const [name, cmd] of ALLOW) {
  test(`allowed: ${name}`, async ($, on) => {
    world(on, base)
    expect(blocked(await decide($, cmd))).toBe(false)
  })
}

test('non-Bash tool is ignored', async ($, on) => {
  world(on, base)
  expect(blocked(await $.tool.call({ tool: 'Edit', command: `pkill -f GUARDPAT-${P}` }))).toBe(false)
})

test('an invalid regex matches as a substring', async ($, on) => {
  world(on, [{ pid: 100, comm: '/x/claude/versions/9.9.9', args: '/x/claude/versions/9.9.9 a[b' }])
  expect(blocked(await decide($, "pkill -f 'a[b'"))).toBe(true)
})

test('a subagent call (agentId) is guarded too', async ($, on) => {
  world(on, base)
  expect(blocked(await $.tool.call({ tool: 'Bash', command: `pkill -f GUARDPAT-${P}`, agentId: 'a1' }))).toBe(true)
})

test('no /proc: the versions-path and npm-style claude are still blocked, the decoy allowed', async ($, on) => {
  world(on, [CLAUDE, DECOY, { ...NPM, exe: undefined }])
  expect(blocked(await decide($, `pkill -f 'GUARDPAT-${P}'`))).toBe(true)
  expect(blocked(await decide($, `pkill -f 'NPMPAT-${P}'`))).toBe(true)
  expect(blocked(await decide($, `pkill -f 'DECOYPAT-${P}'`))).toBe(false)
})

test('exe is node but comm/args say claude: still blocked (fail closed)', async ($, on) => {
  world(on, [{ pid: 100, comm: 'claude', args: `claude x GUARDPAT-${P}`, exe: '/usr/bin/node' }])
  expect(blocked(await decide($, `pkill -f GUARDPAT-${P}`))).toBe(true)
})

test('only /proc/<pid>/exe says claude: blocked', async ($, on) => {
  world(on, [{ pid: 100, comm: '/usr/bin/node', args: `node x GUARDPAT-${P}`, exe: '/x/claude/versions/9.9.9' }])
  expect(blocked(await decide($, `pkill -f GUARDPAT-${P}`))).toBe(true)
})

test('the denial lists the non-Claude PIDs the pattern also matches, ascending, with the kill line', async ($, on) => {
  world(on, [
    CLAUDE,
    { pid: 105, comm: '/bin/sh', args: `/bin/sh GUARDPAT-${P} b` },
    { pid: 103, comm: '/bin/sh', args: `/bin/sh GUARDPAT-${P} a` },
    DECOY,
  ])
  const r = text(await decide($, `pkill -f GUARDPAT-${P}`))
  expect(r).toContain('BLOCKED:')
  expect(r).toContain('would also kill Claude Code process(es) [100]')
  expect(r).toContain('Instead run: kill 103 105')
  expect(r).not.toContain('101')
})

test('"No other processes match." when only Claude processes match', async ($, on) => {
  world(on, base)
  const r = text(await decide($, `pkill -f GUARDPAT-${P}`))
  expect(r).toContain('No other processes match.')
  expect(r).not.toContain('Instead run')
})

test('a throwing process.run lets the call through (fail open)', async ($, on) => {
  const w = world(on, base)
  w.throwRun = true
  expect(blocked(await decide($, `pkill -f GUARDPAT-${P}`))).toBe(false)
})

test('session.start writes the kill-guard marker; session.end removes it', async ($, on) => {
  const w = world(on, base)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(w.files.get('/s/mods-active/sid1.kill-guard')).toBe('sid1\n')
  await $.session.end({ sessionId: 'sid1', reason: 'exit' })
  expect(w.runs).toContainEqual(['rm', '-f', '/s/mods-active/sid1.kill-guard'])
  expect(w.files.has('/s/mods-active/sid1.kill-guard')).toBe(false)
})

test('the marker path follows the state dir rule: TMPDIR minus the trailing slash, /tmux-ctl-<uid>; an empty TMPDIR is /tmp', async ($, on) => {
  const w = world(on, base, { TMPDIR: '/x/' })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect([...w.files.keys()].filter((k) => k.endsWith('.kill-guard'))).toEqual(['/x/tmux-ctl-503/mods-active/sid1.kill-guard'])
  await $.session.end({ sessionId: 'sid1', reason: 'exit' })
  expect(w.files.has('/x/tmux-ctl-503/mods-active/sid1.kill-guard')).toBe(false)
})

test('an empty TMPDIR writes the marker under /tmp', async ($, on) => {
  const w = world(on, base, { TMPDIR: '' })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(w.files.get('/tmp/tmux-ctl-503/mods-active/sid1.kill-guard')).toBe('sid1\n')
})

test('after a clear the next Bash check re-keys the marker: the old one is removed, one for the new id is written', async ($, on) => {
  const w = world(on, base)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
  await $.session.end({ sessionId: 'sid1', reason: 'clear' } as any)
  w.sid = 'sid2'
  await decide($, 'ls')
  expect([...w.files.keys()].filter((k) => k.includes('/mods-active/') && k.endsWith('.kill-guard')).sort()).toEqual(['/s/mods-active/sid2.kill-guard'])
  await decide($, 'ls') // a second call does not write again
  expect(w.files.get('/s/mods-active/sid2.kill-guard')).toBe('sid2\n')
})
