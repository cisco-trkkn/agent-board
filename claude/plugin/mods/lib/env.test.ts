// Tests for the pure path rules and the $-taking helpers of lib/env.js. The world is answered from memory.
// The $-taking helpers (readEnv, writeMarker, removeMarker) cannot be driven from a test file (an inline test mod
// is serialized and cannot import them), so the kill-guard, bash-mirror and artifact-register mod tests exercise them.
import { expect, test } from 'claude-code/testing'
import { stateDir, lineageDir, markerPath } from './env.js'

test('TC_STATE wins over TMPDIR', () => {
  expect(stateDir('/s', '/tmp/x', '503')).toBe('/s')
})
test('TMPDIR with a trailing slash is trimmed', () => {
  expect(stateDir('', '/var/T/', '503')).toBe('/var/T/tmux-ctl-503')
})
test('TMPDIR without a trailing slash', () => {
  expect(stateDir(undefined, '/var/T', '503')).toBe('/var/T/tmux-ctl-503')
})
test('TMPDIR unset falls back to /tmp', () => {
  expect(stateDir('', '', '503')).toBe('/tmp/tmux-ctl-503')
  expect(stateDir(null, undefined, '7')).toBe('/tmp/tmux-ctl-7')
})
test('lineage: TC_LINEAGE, then XDG_STATE_HOME, then $HOME/.local/state', () => {
  expect(lineageDir('/l', '/x', '/h')).toBe('/l')
  expect(lineageDir('', '/x', '/h')).toBe('/x/agent-board/lineage')
  expect(lineageDir('', '', '/h')).toBe('/h/.local/state/agent-board/lineage')
})
test('marker path shape', () => {
  expect(markerPath('/s', 'sid1', 'kill-guard')).toBe('/s/mods-active/sid1.kill-guard')
})
