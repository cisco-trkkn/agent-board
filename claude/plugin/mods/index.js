// Entry module: Claude Code loads one hooks module per plugin, so this one registers every mod of the plugin.
import { register as agentStatus } from './agent-status.js'
import { register as teamBand } from './team-band.js'

export function register(on) {
  agentStatus(on)
  teamBand(on)
}
