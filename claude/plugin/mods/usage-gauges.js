// usage-gauges: shows `5h <n>% · 7d <n>% · ctx <n>% · $<x.xx>` under the prompt ($.ui.status) from this session's own
// statusLine tap file (<state dir>/statusline/<session_id>.json), read every 10 s. The line is cleared when the file is
// missing, unparsable, older than 300 s or another session's. Every timer body is wrapped: an error never throws out.

const POLL_MS = 10000
const STALE_S = 300

const secs = (ms) => Math.floor(ms / 1000)
const pct = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) + '%' : null)

export function gaugeLine(p) {
  if (!p || typeof p !== 'object') return ''
  const rl = p.rate_limits || {}
  const cost = p.cost && p.cost.total_cost_usd
  const parts = [
    pct(rl.five_hour && rl.five_hour.used_percentage) && '5h ' + pct(rl.five_hour.used_percentage),
    pct(rl.seven_day && rl.seven_day.used_percentage) && '7d ' + pct(rl.seven_day.used_percentage),
    pct(p.context_window && p.context_window.used_percentage) && 'ctx ' + pct(p.context_window.used_percentage),
    typeof cost === 'number' && Number.isFinite(cost) ? '$' + cost.toFixed(2) : null,
  ]
  return parts.filter(Boolean).join(' · ')
}

// the one record of this session; null until session.start has resolved the state dir
let gg = null

function stop() {
  if (gg && gg.tick) gg.tick.cancel()
  gg = null
}

async function textFor($, rec) {
  try {
    const sid = await $.session.id()
    const p = JSON.parse(await $.fs.read(rec.dir + '/statusline/' + sid + '.json'))
    if (!p || p.session_id !== sid) return ''
    if (secs(await $.clock.now()) - p.received_at > STALE_S) return ''
    return gaugeLine(p)
  } catch (x) {
    return ''
  }
}

async function poll($, rec) {
  const text = await textFor($, rec)
  if (rec.ended || text === rec.shown) return
  rec.shown = text
  // '' would leave an empty `⚠ agent-board:` row; undefined removes the row (real run: tools/tests/e2e-usage-gauges.md)
  await $.ui.status(text === '' ? undefined : text)
}

// Called by index.js, the plugin's only session.start / session.end hook.
export async function start($, e) {
  try {
    stop()
    const tcState = await $.env.get('TC_STATE')
    const tmpdir = await $.env.get('TMPDIR')
    let uid = ''
    if (!tcState) uid = (await $.process.run(['id', '-u'])).stdout.trim()
    const dir = tcState || (tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid
    const rec = { dir, shown: '', ended: false, tick: null }
    gg = rec
    rec.tick = $.clock.every(POLL_MS, async () => {
      try { await poll($, rec) } catch (x) { /* keep the last line */ }
    })
  } catch (x) { /* never block the session */ }
}

// /clear, /resume and /branch end the session without a new session.start: the process goes on, so the timer stays
export async function end($, e) {
  try {
    if (!(e && (e.reason === 'clear' || e.reason === 'resume'))) {
      if (gg) gg.ended = true
      stop()
    }
  } catch (x) { /* ignore */ }
}

export function register(on) {}
