// Shared by the shell-hook mods: the state and lineage directory rules, the mods-active marker path, and the helpers
// that read the environment and write or remove a marker. The rules match tc-env.zsh / tc_env.py.
//
// `claude plugin validate` forces literal $.env.get names, and accepts $ only as an argument to a named module-level
// function, so every helper that needs $ takes it as a parameter. Every $-taking helper swallows its errors: a hook
// never fails a tool call.

// <state dir>: $TC_STATE, else ($TMPDIR minus a trailing "/", default /tmp) + /tmux-ctl-<uid>
export const stateDir = (tcState, tmpdir, uid) =>
  tcState || (tmpdir || '/tmp').replace(/\/+$/, '') + '/tmux-ctl-' + uid

// <lineage dir>: $TC_LINEAGE, else ($XDG_STATE_HOME, default $HOME/.local/state) + /agent-board/lineage
export const lineageDir = (tcLineage, xdgStateHome, home) =>
  tcLineage || (xdgStateHome || home + '/.local/state') + '/agent-board/lineage'

// the file whose existence tells the shell script <hook> that its mod is live for session <sid>
export const markerPath = (stateDirPath, sid, hook) => stateDirPath + '/mods-active/' + sid + '.' + hook

const get = async ($, name) => {
  try { return (await name) || '' } catch (x) { return '' }
}

// The environment the hooks need. uid (`id -u`) is looked up only when TC_STATE is unset, the one case that needs it.
export async function readEnv($) {
  const tcState = await get($, $.env.get('TC_STATE'))
  const tmpdir = await get($, $.env.get('TMPDIR'))
  const tcLineage = await get($, $.env.get('TC_LINEAGE'))
  const xdgStateHome = await get($, $.env.get('XDG_STATE_HOME'))
  const home = await get($, $.env.get('HOME'))
  const tmux = await get($, $.env.get('TMUX'))
  const tmuxPane = await get($, $.env.get('TMUX_PANE'))
  let uid = ''
  if (!tcState) {
    try { uid = ((await $.process.run(['id', '-u'])).stdout || '').trim() } catch (x) { /* uid stays '' */ }
  }
  return { tcState, tmpdir, tcLineage, xdgStateHome, home, tmux, tmuxPane, uid }
}

// Content is the session id and a newline; only the file's existence is read. $.fs.write makes the parent dirs.
export async function writeMarker($, path, sid) {
  try { await $.fs.write(path, (sid || '') + '\n') } catch (x) { /* never fails the session */ }
}

export async function removeMarker($, path) {
  try { await $.process.run(['rm', '-f', path]) } catch (x) { /* never fails the session */ }
}
