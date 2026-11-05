// Tests for index.js: runAll, and the plugin's one session.start / session.end hook over every mod.
import { expect, test, mock } from 'claude-code/testing'
import { runAll } from './index.js'

test('steps run in the order given', async () => {
  const seen: string[] = []
  await runAll([async () => { seen.push('a') }, async () => { seen.push('b') }, async () => { seen.push('c') }])
  expect(seen).toEqual(['a', 'b', 'c'])
})

test('a throwing mod does not stop the next', async () => {
  const seen: string[] = []
  await runAll([async () => { seen.push('a'); throw new Error('boom') }, async () => { seen.push('b') }])
  expect(seen).toEqual(['a', 'b'])
})

test("a throwing step's error does not reach next(e)", async ($, on) => {
  mock.env(on, { TC_STATE: '/s' })
  mock.clock(on, { now: 1_000_000 })
  // the first mod's start throws past its own catch: session.id, fs.write and process.run all fail
  on('session.id', async () => { throw new Error('no id') })
  on('fs.write', () => { throw new Error('disk full') })
  on('process.run', () => { throw new Error('no process') })
  on('settings.read', () => { throw new Error('no settings') })
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'sid1' }))
  const started = await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
  expect(started).toEqual({ cwd: '/work' })
  const ended = await $.session.end({ reason: 'other', sessionId: 'sid1', resume: {} } as any)
  expect(ended).toEqual({ sessionId: 'sid1' })
})
