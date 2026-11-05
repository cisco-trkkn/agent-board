// Entry module: Claude Code loads one hooks module per plugin, so this one registers every mod of the plugin.
// It also owns the plugin's only session.start and session.end hooks and calls each mod's start/end in order.
import { register as registerAgentStatus, start as startAgentStatus, end as endAgentStatus } from './agent-status.js'
import { register as registerTeamBand, start as startTeamBand, end as endTeamBand } from './team-band.js'

// claude plugin validate allows $ only as an argument to a named function of this module or an imported one, so the
// per-mod calls are thunks and runAll never sees $.
export async function runAll(steps) {
  for (const step of steps) {
    try { await step() } catch (x) { /* one mod never stops another */ }
  }
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    await runAll([() => startAgentStatus($, e), () => startTeamBand($, e)])
    return next(e)
  })
  on('session.end', async ($, e, next) => {
    await runAll([() => endAgentStatus($, e), () => endTeamBand($, e)])
    return next(e)
  })
  registerAgentStatus(on)
  registerTeamBand(on)
}
