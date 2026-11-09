// Entry module: Claude Code loads one hooks module per plugin, so this one registers every mod of the plugin.
// It also owns the plugin's only session.start and session.end hooks and calls each mod's start/end in order.
import { register as registerAgentStatus, start as startAgentStatus, end as endAgentStatus } from './agent-status.js'
import { register as registerTeamBand, start as startTeamBand, end as endTeamBand } from './team-band.js'
import { register as registerKillGuard, start as startKillGuard, end as endKillGuard } from './kill-guard.js'
import { register as registerBashMirror, start as startBashMirror, end as endBashMirror } from './bash-mirror.js'
import { register as registerArtifactRegister, start as startArtifactRegister, end as endArtifactRegister } from './artifact-register.js'
import { register as registerUsageGauges, start as startUsageGauges, end as endUsageGauges } from './usage-gauges.js'

// claude plugin validate allows $ only as an argument to a named function of this module or an imported one, so the
// per-mod calls are thunks and runAll never sees $.
export async function runAll(steps) {
  for (const step of steps) {
    try { await step() } catch (x) { /* one mod never stops another */ }
  }
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    await runAll([() => startAgentStatus($, e), () => startTeamBand($, e), () => startUsageGauges($, e), () => startKillGuard($, e), () => startBashMirror($, e), () => startArtifactRegister($, e)])
    return next(e)
  })
  on('session.end', async ($, e, next) => {
    await runAll([() => endAgentStatus($, e), () => endTeamBand($, e), () => endUsageGauges($, e), () => endKillGuard($, e), () => endBashMirror($, e), () => endArtifactRegister($, e)])
    return next(e)
  })
  registerAgentStatus(on)
  registerTeamBand(on)
  registerUsageGauges(on)
  registerKillGuard(on)
  registerBashMirror(on)
  registerArtifactRegister(on)
}
