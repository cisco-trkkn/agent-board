// bash-mirror: after each Bash tool.call resolves or rejects, appends one entry to the session's tests/shell feed log
// (<state dir>/feed-<project>-<tests|shell>.log), the same entry scripts/bash-mirror.sh writes:
//   `── HH:MM:SS · <caller> · <cwd> · exit N · @<epoch>` / `$ <first line>` / last 12 lines of output / blank line.
// Differences from the shell: it does not source bin/_tc_bins.zsh; the tmux binary is chosen by lib/env.js tmuxBin
// ($TC_TMUX, else $HOME/.local/bin/tmux when it exists, else `tmux`), always with `-S ${TMUX%%,*}`. The cwd is read from the
// session after the call (the shell hook was handed it in the payload). A call refused by a guard is not mirrored.
//
// Appending: there is no $.fs append, so each entry is read-modify-write through $.fs (read the log, trim it when it is
// over the limit, write it back with the entry). Spawning `tee -a`/`sh -c` would need a shell per call, which is what
// the mod replaces. The writes of one session are chained (q), so two calls of this session never interleave; another
// session's shell or mod writing the same log at the same moment could still lose an entry, the same race the two
// shell hooks had.
// The mod writes <state dir>/mods-active/<session_id>.bash-mirror at session start so the shell script defers.
import { stateDir, markerPath, readEnv, writeMarker, removeMarker, tmuxRun } from './lib/env.js'

const MAX_BYTES = 2097152
const KEEP_BYTES = 1048576

// classify(): the regexes are the shell's Python ones, JS-compatible as written
const SEP = String.raw`(?:^|&&|\|\||;|\||\()\s*`
const WRAP = String.raw`(?:(?:time|env|sudo|nohup|npx|pnpx|bunx|uv\s+run|poetry\s+run|pipenv\s+run|python3?\s+-m)\s+(?:\w+=\S+\s+)*)*`
const TOOL =
  String.raw`(?:pytest|py\.test|tox|nox|jest|vitest|make|ruff|mypy|eslint|tsc|tflint|shellcheck|bats|agent-ci|gradle|mvn` +
  String.raw`|(?:\./)?(?:gradlew|mvnw)|unittest|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build|lint)|go\s+(?:test|build|vet)` +
  String.raw`|cargo\s+(?:test|build|clippy)|terraform\s+(?:plan|validate|fmt))(?![\w-])`
const PAT = new RegExp(SEP + String.raw`(?:\w+=\S+\s+)*` + WRAP + TOOL)
const TMUXCTL = /^(~\/\.local\/bin\/|\S*\/)?tmux-ctl(\s|$)/

export function classify(c) {
  for (const m of c.matchAll(/(?:^|&&|\|\||;|\||\()\s*(?:bash|sh|zsh)\s+-c\s+(['"])(.*?)\1/g)) {
    if (classify(m[2]) === 'tests') return 'tests'
  }
  const plain = c.replace(/"(?:\\.|[^"\\])*"|'[^']*'/g, '""')
  return PAT.test(plain) ? 'tests' : 'shell'
}

const pad = (n) => String(n).padStart(2, '0')
const bytes = (s) => (typeof TextEncoder === 'function' ? new TextEncoder().encode(s).length : s.length)

// the last KEEP_BYTES bytes of s (a log over MAX_BYTES), like `tail -c`
function trimmed(s) {
  if (bytes(s) <= MAX_BYTES) return s
  if (typeof TextEncoder !== 'function' || typeof TextDecoder !== 'function') return s.slice(-KEEP_BYTES)
  return new TextDecoder().decode(new TextEncoder().encode(s).slice(-KEEP_BYTES))
}

// the entry text (header, command, tail, trailing newline) plus the blank line `print -r --` adds
export function entryText(first, tail, caller, cwd, code, ms) {
  const d = new Date(ms)
  const hms = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
  let entry = '── ' + hms + ' · ' + caller + ' · ' + cwd + ' · exit ' + code + ' · @' + Math.floor(ms / 1000) + '\n$ ' + first
  if (tail) entry += '\n' + tail
  return entry + '\n\n'
}

// a call that never ran: refused by a guard or a rule, or by auto mode's classifier (probe L1:11, L3:3, L4:3)
const REFUSED = /^(Permission to use |Claude requested permissions|The server-side auto mode classifier gave no verdict)/

// what the call's result says: [exit code, output text], or null for a call that never ran (refused)
export function outcome(out, failed, err) {
  if (failed) {
    const msg = String((err && err.message) || err || '')
    const m = /^Exit code (\d+)/m.exec(msg)
    return [m ? Number(m[1]) : 1, msg.replace(/^Exit code \d+\n?/, '')]
  }
  if (!out || out.deny) return null
  const r = out.result
  if (out.isError) {
    const text = typeof out.text === 'string' ? out.text : typeof r === 'string' ? r.replace(/^Error: /, '') : ''
    if (REFUSED.test(text)) return null
    const m = /^Exit code (\d+)/m.exec(text)
    return [m ? Number(m[1]) : 1, text.replace(/^Exit code \d+\n?/, '')]
  }
  if (r && typeof r === 'object') return [0, String(r.stdout || '') + String(r.stderr || '')]
  return [0, typeof r === 'string' ? r : String(out.text || '')]
}

let ctx = null // { dir, tmux, pane, tcTmux, home, marker } read at session.start
let q = Promise.resolve() // the session's writes, one after another
let startCwd = ''

export async function start($, e) {
  try {
    const env = await readEnv($)
    const sid = await $.session.id()
    startCwd = (e && e.cwd) || ''
    const dir = stateDir(env.tcState, env.tmpdir, env.uid)
    ctx = { dir, tmux: env.tmux, pane: env.tmuxPane, tcTmux: env.tcTmux, home: env.home, marker: markerPath(dir, sid, 'bash-mirror') }
    await writeMarker($, ctx.marker, sid)
  } catch (x) { /* never block the session */ }
}

export async function end($, e) {
  try {
    const goesOn = e && (e.reason === 'clear' || e.reason === 'resume')
    await q
    if (ctx && ctx.marker) await removeMarker($, ctx.marker)
    if (ctx) ctx.marker = null
    if (goesOn) await start($, e)
  } catch (x) { /* never block the session */ }
}

function tmux($, args) { return tmuxRun($, ctx.tcTmux, ctx.home, ctx.tmux, args) }

// writes one entry; throws on any failure (the caller swallows)
async function mirror($, e, out, failed, err) {
  if (!ctx || !ctx.tmux || !ctx.pane) return
  const cmd = String((e && e.command) || '')
  if (TMUXCTL.test(cmd.replace(/^\s+/, ''))) return
  const res = outcome(out, failed, err)
  if (!res) return
  const [code, text] = res
  const kind = classify(cmd)
  const tail = text.trim() ? text.replace(/\n+$/, '').split('\n').slice(-12).join('\n') : ''
  let first = cmd.trim() ? cmd.replace(/^\n+|\n+$/g, '').split('\n')[0] : ''
  if (cmd.trim().includes('\n')) first += ' …'
  let cwd = ''
  try { cwd = (await $.session.cwd()) || '' } catch (x) { /* fall back to the start cwd */ }
  cwd = cwd || startCwd
  if (ctx.home && (cwd === ctx.home || cwd.startsWith(ctx.home + '/'))) cwd = '~' + cwd.slice(ctx.home.length)
  const info = (await tmux($, ['display', '-p', '-t', ctx.pane, '#{session_name}\t#{window_name}\t#{?session_group,#{session_group},#{session_name}}'])).replace(/\n$/, '')
  const parts = info.split('\t')
  const session = parts[0]
  const caller = (parts[1] || '').replace(/^✦ /, '')
  const canon = parts[2]
  const wins = (await tmux($, ['list-windows', '-t', '=' + session, '-F', '#{window_name}'])).split('\n')
  // feeds are written for dev sessions: the agents' window lives in <project>-bg (or, before migration, here)
  let hasBg = true
  try { await tmux($, ['has-session', '-t', '=' + canon + '-bg']) } catch (x) { hasBg = false }
  if (!hasBg && !wins.includes(kind)) return
  const log = ctx.dir + '/feed-' + canon + '-' + kind + '.log'
  const ms = await $.clock.now()
  const entry = entryText(first, tail, caller, cwd, code, ms)
  let cur = ''
  // a log that exists but cannot be read (e.g. over the $.fs size limit) is not replaced by one holding a single entry
  if (await $.fs.exists(log)) cur = await $.fs.read(log)
  await $.fs.write(log, trimmed(typeof cur === 'string' ? cur : '') + entry)
}

// starts the chained write; the tool never waits for it
function record($, e, out, failed, err) {
  q = q.then(() => mirror($, e, out, failed, err)).catch(() => {})
}

export function register(on) {
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    let out
    let failed = false
    let err
    try { out = await next(e) } catch (x) { failed = true; err = x }
    try { record($, e, out, failed, err) } catch (x) { /* never fails the call */ }
    if (failed) throw err
    return out
  })
}
