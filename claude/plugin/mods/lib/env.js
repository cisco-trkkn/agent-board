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

// The environment the hooks need; an unreadable variable is ''. uid (`id -u`) is looked up only when TC_STATE is
// unset, the one case that needs it. (`claude plugin validate` accepts $ only as an argument to a function
// declaration and wants each $.env.get name literal, so each variable is read inline.)
export async function readEnv($) {
  const r = { tcState: '', tmpdir: '', tcLineage: '', xdgStateHome: '', home: '', tmux: '', tmuxPane: '', tcTmux: '', uid: '' }
  try { r.tcState = (await $.env.get('TC_STATE')) || '' } catch (x) { /* '' */ }
  try { r.tmpdir = (await $.env.get('TMPDIR')) || '' } catch (x) { /* '' */ }
  try { r.tcLineage = (await $.env.get('TC_LINEAGE')) || '' } catch (x) { /* '' */ }
  try { r.xdgStateHome = (await $.env.get('XDG_STATE_HOME')) || '' } catch (x) { /* '' */ }
  try { r.home = (await $.env.get('HOME')) || '' } catch (x) { /* '' */ }
  try { r.tmux = (await $.env.get('TMUX')) || '' } catch (x) { /* '' */ }
  try { r.tmuxPane = (await $.env.get('TMUX_PANE')) || '' } catch (x) { /* '' */ }
  try { r.tcTmux = (await $.env.get('TC_TMUX')) || '' } catch (x) { /* '' */ }
  if (!r.tcState) {
    try { r.uid = ((await $.process.run(['id', '-u'])).stdout || '').trim() } catch (x) { /* uid stays '' */ }
  }
  return r
}

// Content is the session id and a newline; only the file's existence is read. $.fs.write makes the parent dirs.
export async function writeMarker($, path, sid) {
  try { await $.fs.write(path, (sid || '') + '\n') } catch (x) { /* never fails the session */ }
}

export async function removeMarker($, path) {
  try { await $.process.run(['rm', '-f', path]) } catch (x) { /* never fails the session */ }
}

// The tmux binary: $TC_TMUX, else $HOME/.local/bin/tmux when it exists, else `tmux` on PATH. (The shell hooks source
// bin/_tc_bins.zsh when it is present; the mods use only this chain.)
export async function tmuxBin($, tcTmux, home) {
  if (tcTmux) return tcTmux
  const mine = home + '/.local/bin/tmux'
  try { if (home && (await $.fs.exists(mine))) return mine } catch (x) { /* fall through */ }
  return 'tmux'
}

// runs `tmux -S ${TMUX%%,*} <args>`; throws when tmux exits non-zero
export async function tmuxRun($, tcTmux, home, tmuxEnv, args) {
  const r = await $.process.run([await tmuxBin($, tcTmux, home), '-S', tmuxEnv.split(',')[0], ...args])
  if (r.exitCode !== 0) throw new Error('tmux ' + args[0] + ' failed')
  return r.stdout
}
