// kill-guard: a tool.check hook that denies a Bash `pkill`/`killall` whose pattern also matches a Claude Code process
// (a broad `pkill -f` once killed the dev orchestrator and its whole team). A JS port of scripts/kill-guard.sh; the
// denial also lists the non-Claude processes the same pattern matches and the `kill` line to run instead.
//
// Regex dialect: patterns are JS RegExp, the shell script used Python `re`. The common syntax is the same; a pattern
// valid in one and not the other (an invalid JS regex) is matched as a plain substring, like Python's re.error case.
// Fails open: any error in this mod's own work lets the call through. Calls with e.agentId (a subagent's) are guarded.
// The mod writes <state dir>/mods-active/<session_id>.kill-guard at session start so the shell script defers.
import { stateDir, markerPath, readEnv, writeMarker, removeMarker, rekeyMarker } from './lib/env.js'

const TOOLS = ['pkill', 'killall']
const PUNCT = '();&|<>'
const WS = ' \t\r\n'

const base = (p) => p.slice(p.lastIndexOf('/') + 1)

// Python shlex.shlex(text, posix=True, punctuation_chars=True) with whitespace_split=True, '#' commenting, the quote
// and escape rules included. Throws on an unclosed quote or a trailing backslash (shlex's ValueError).
export function tokens(text) {
  const out = []
  let i = 0
  const push = []
  let state = ' '
  let token = ''
  let quoted = false
  let esc = ' '
  const next = () => (push.length ? push.pop() : i < text.length ? text[i++] : '')
  const skipLine = () => { while (i < text.length && text[i] !== '\n') i++; if (i < text.length) i++ }
  for (;;) {
    const c = next()
    if (state === ' ') {
      if (!c) break
      if (WS.includes(c)) continue
      if (c === '#') skipLine()
      else if (c === '\\') { esc = 'a'; state = c }
      else if (PUNCT.includes(c)) { token = c; state = 'c' }
      else if (c === "'" || c === '"') { state = c; quoted = true }
      else { token = c; state = 'a' }
    } else if (state === "'" || state === '"') {
      quoted = true
      if (!c) throw new Error('No closing quotation')
      if (c === state) state = 'a'
      else if (c === '\\' && state === '"') { esc = state; state = c }
      else token += c
    } else if (state === '\\') {
      if (!c) throw new Error('No escaped character')
      if ((esc === "'" || esc === '"') && c !== state && c !== esc) token += state
      token += c
      state = esc
    } else {
      // state 'a' (word) or 'c' (punctuation run)
      let emit = false
      if (!c) { emit = token !== '' || quoted; state = ' ' }
      else if (WS.includes(c)) { state = ' '; emit = token !== '' || quoted }
      else if (c === '#') { skipLine(); state = ' '; emit = token !== '' || quoted }
      else if (state === 'c') {
        if (PUNCT.includes(c)) token += c
        else { push.push(c); state = ' '; emit = true }
      } else if (c === "'" || c === '"') state = c
      else if (c === '\\') { esc = 'a'; state = c }
      else if (!PUNCT.includes(c)) token += c
      else { push.push(c); state = ' '; emit = token !== '' || quoted }
      if (emit) {
        out.push(token)
        token = ''; quoted = false
      }
      if (!c) break
    }
  }
  return out
}

// every pkill/killall occurrence anywhere in text, nested -c strings included (depth < 3): [tool, args] pairs
export function scan(text, depth = 0) {
  const found = []
  let toks
  try {
    toks = tokens(text)
  } catch (x) { // unbalanced quotes etc: regex over the raw text instead of skipping
    for (const m of text.matchAll(/\b(pkill|killall)\b([^;&|()\n]*)/g)) {
      found.push([m[1], m[2].split(/\s+/).filter(Boolean).map((a) => a.replace(/^['"]+|['"]+$/g, ''))])
    }
    return found
  }
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i]
    if (TOOLS.includes(base(t))) {
      const args = []
      for (const a of toks.slice(i + 1)) {
        if (a && [...a].every((ch) => PUNCT.includes(ch))) break
        args.push(a)
      }
      found.push([base(t), args])
    } else if (depth < 3 && /\b(pkill|killall)\b/.test(t) && t.split(/\s+/).filter(Boolean).length > 1) {
      found.push(...scan(t, depth + 1))
    }
  }
  return found
}

const looks = (x) => x.includes('/claude/versions/') || base(x) === 'claude'

// Fail closed: a process is Claude if ANY of comm, argv[0] or /proc/<pid>/exe says so. exe is added, never swapped
// for them: an npm install runs /usr/bin/node, which only comm/args (process.title) call claude.
export async function isClaude($, pid, comm, argv) {
  if (looks(comm) || looks(argv.trim().split(/\s+/)[0] || '')) return true
  try {
    const r = await $.process.run(['readlink', '/proc/' + pid + '/exe'])
    if (r.exitCode === 0 && looks(r.stdout.trim())) return true
  } catch (x) { /* no readable /proc */ }
  return false
}

const column = async ($, col) => {
  const r = await $.process.run(['ps', '-axww', '-o', 'pid=,' + col + '='])
  const m = new Map()
  for (const line of r.stdout.split('\n')) {
    const g = /^\s*(\d+)\s+(.*)/.exec(line)
    if (g) m.set(Number(g[1]), g[2])
  }
  return m
}

// pids of the processes `tool args` would hit, split into Claude and other, each ascending
export async function matchPids($, tool, args) {
  const full = tool === 'pkill' && args.some((a) => a.startsWith('-') && a.slice(1).includes('f') && !a.startsWith('--'))
  const pats = args.filter((a) => !a.startsWith('-'))
  if (!pats.length) return { claude: [], other: [] }
  const pat = pats[pats.length - 1]
  const comms = await column($, 'comm')
  const argvs = await column($, 'args')
  let re = null
  try { re = new RegExp(pat) } catch (x) { re = null }
  const claude = []
  const other = []
  for (const [pid, comm] of comms) {
    const argv = argvs.get(pid) || ''
    if (argv.startsWith('ps -axww -o pid=,')) continue // this lookup's own ps
    const hay = full ? argv : base(comm)
    const ok = tool === 'pkill' ? (re ? re.test(hay) : hay.includes(pat)) : base(comm) === pat
    if (!ok) continue
    ;(await isClaude($, pid, comm, argv) ? claude : other).push(pid)
  }
  const asc = (a, b) => a - b
  return { claude: claude.sort(asc), other: other.sort(asc) }
}

// the denial reason for `cmd`, or null to let it through; never throws
async function verdict($, cmd) {
  try {
    if (!/\b(pkill|killall)\b/.test(cmd)) return null
    for (const [tool, args] of scan(cmd)) {
      const { claude, other } = await matchPids($, tool, args)
      if (claude.length) {
        return (
          'BLOCKED: `' + tool + ' ' + args.join(' ') + '` would also kill Claude Code process(es) [' + claude.join(', ') + '] ' +
          '(the lead, a teammate, or you). Patterns match full command lines, which include session names and prompts. ' +
          'kill by PID instead: the PID you started ($!), or `pgrep -P <your shell pid>` / `pgrep -f <pattern>` checked by hand first. ' +
          (other.length ? 'Instead run: kill ' + other.join(' ') : 'No other processes match.')
        )
      }
    }
  } catch (x) { /* fail open */ }
  return null
}

const mk = { dir: '', sid: null, marker: null } // the marker written for the session id mk.sid

// Called by index.js, the plugin's only session.start / session.end hook.
export async function start($, e) {
  try {
    const sid = await $.session.id()
    const env = await readEnv($)
    mk.dir = stateDir(env.tcState, env.tmpdir, env.uid)
    mk.sid = sid
    mk.marker = markerPath(mk.dir, sid, 'kill-guard')
    await writeMarker($, mk.marker, sid)
  } catch (x) { /* never block the session */ }
}

// /clear and /resume go on under another session id and session.start does not fire again: drop the marker and forget
// the id, and the next Bash check writes the new one (rekeyMarker). Other reasons: the session is over.
export async function end($, e) {
  try {
    if (mk.marker) await removeMarker($, mk.marker)
    mk.marker = null
    mk.sid = null
  } catch (x) { /* never block the session */ }
}

export function register(on) {
  on('tool.check', { tool: 'Bash' }, async ($, e, next) => {
    await rekeyMarker($, mk, 'kill-guard')
    const reason = await verdict($, (e && e.input && e.input.command) || '')
    if (reason) return { decision: 'deny', reason }
    return next(e)
  })
}
