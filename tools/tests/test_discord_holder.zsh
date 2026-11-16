source "${0:A:h}/lib.zsh"
# dc_holder <dir>: "<claude pid> <pane>" for a live holder of the discord channel state dir, else nothing.
# Real process trees: a fake `claude` (node under that name) starts a child whose args look like the discord server
# (`bun run --cwd /fake/discord/0.0.4 start`) and whose environment carries DISCORD_STATE_DIR. Every pid is killed on exit.
export TC_TMUX="$TT_BIN"
tt_setup claude
if (( ! $+commands[node] )); then print "skip - no node"; tt_done; exit 0; fi
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdh.XXXXXX"):A}"
mkdir -p "$S/bin"
# node, not zsh: macOS hides the environment of platform binaries (/bin/zsh, sleep) from `ps -E`, as it does not for claude/bun
ln -sf "${commands[node]:A}" "$S/bin/claude"   # a process whose argv[0] is .../claude
cat > "$S/fc.js" <<'FC'
const { spawn } = require('child_process')
require('fs').writeFileSync(process.argv[3], String(process.pid))
const k = spawn(process.execPath, ['-e', 'setTimeout(()=>{},120000)', 'bun', 'run', '--cwd', '/fake/discord/0.0.4', 'start'],
  { env: { ...process.env, DISCORD_STATE_DIR: process.argv[2] }, stdio: 'ignore' })
k.on('exit', () => process.exit(0))
FC
typeset -a PIDS=()
cleanup() { local p; for p in $PIDS; do kill $p 2>/dev/null; done; rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
source "$TT_REPO/tools/lib/discord.zsh"
N=0
kids() { ps -A -o pid=,ppid= | awk -v p=$1 '$2==p{print $1}' }
spawn() {   # spawn <state dir> [detached] [pane]: sets CP (the fake claude's pid) and KID; detached = double fork, so claude's ppid is 1
  local f="$S/pid.$((++N))" pane="${3:-%99}"
  if [[ "$2" == detached ]]; then ( env TMUX_PANE="$pane" "$S/bin/claude" "$S/fc.js" "$1" "$f" >/dev/null 2>&1 & )
  else env TMUX_PANE="$pane" "$S/bin/claude" "$S/fc.js" "$1" "$f" >/dev/null 2>&1 &
  fi
  local i; for i in {1..50}; do [[ -s "$f" ]] && break; sleep 0.1; done
  CP="$(<$f)"; PIDS+=($CP)
  for i in {1..50}; do [[ -n "$(kids $CP)" ]] && break; sleep 0.1; done
  KID="$(kids $CP | head -1)"; PIDS+=($KID); sleep 0.3
}
SD="$S/state/p"; SD2="$S/state/p2"

# sanity: the fake really looks like the server and like claude to ps
spawn "$SD"; CP1=$CP; KID1=$KID
check "fake: claude args start with the claude path"  test "$(ps -o args= -p $CP | awk '{print $1}')" = "$S/bin/claude"
check "fake: child args show bun run --cwd /fake/discord"  test -n "$(ps -o args= -p $KID | grep -F 'bun run --cwd /fake/discord/0.0.4 start')"
check "fake: child env carries DISCORD_STATE_DIR"  test -n "$(ps -Eww -o command= -p $KID | grep -F "DISCORD_STATE_DIR=$SD")"

check "live holder: '<claude pid> %99'"   test "$(dc_holder "$SD")" = "$CP1 %99"
check "other dir: nothing"                test -z "$(dc_holder "$S/state/other")"
check "prefix dir is not held (p vs p2)"  test -z "$(dc_holder "$SD2")" -a -z "$(dc_holder "$S/state")"
spawn "$SD2"; CP2=$CP
check "p2 holder does not change p's answer"  test "$(dc_holder "$SD")" = "$CP1 %99"
check "p2 is held by its own claude"      test "$(dc_holder "$SD2")" = "$CP2 %99"
# orphan: claude killed, the child is re-parented to 1
kill $CP1
for i in {1..50}; do [[ "$(ps -o ppid= -p $KID1 2>/dev/null | tr -d ' ')" == 1 ]] && break; sleep 0.1; done
check "orphan: child ppid is 1"           test "$(ps -o ppid= -p $KID1 | tr -d ' ')" = 1
check "orphan holder: nothing"            test -z "$(dc_holder "$SD")"
# a claude alive with ppid 1 is not live either
spawn "$S/state/d" detached
for i in {1..30}; do [[ "$(ps -o ppid= -p $CP 2>/dev/null | tr -d ' ')" == 1 ]] && break; sleep 0.1; done
check "detached claude: its ppid is 1"    test "$(ps -o ppid= -p $CP | tr -d ' ')" = 1
# mutation: drop the parent-is-not-1 check → this fails
check "claude whose parent is 1: nothing" test -z "$(dc_holder "$S/state/d")"
# no pane in claude's env → "-"
f="$S/pid.nopane"; env -u TMUX_PANE "$S/bin/claude" "$S/fc.js" "$S/state/np" "$f" >/dev/null 2>&1 &
for i in {1..50}; do [[ -s "$f" ]] && break; sleep 0.1; done; NP="$(<$f)"; PIDS+=($NP); sleep 0.5; PIDS+=($(kids $NP))
check "no TMUX_PANE: pane is '-'"         test "$(dc_holder "$S/state/np")" = "$NP -"
# the stub is not a holder
env DISCORD_STATE_DIR="$S/state/stub" node -e 'setTimeout(()=>{},120000)' /x/discord/0.0.4/discord-mcp-stub.js >/dev/null 2>&1 &
PIDS+=($!); sleep 0.3
check "stub is never a holder"            test -z "$(dc_holder "$S/state/stub")"

# status: the held-by line, resolved through tmux
C="$TT_REPO/bin/tmux-ctl"
SDH="$TC_STATE/discord/hp"
REALPANE="$(tt list-panes -a -F '#{pane_id}' | head -1)"
tt new-session -d -s _web-view -t tt -c "$TT_DIR"   # a grouped view: status must name the group
WANT="$(tt display -p -t "$REALPANE" '#{?session_group,#{session_group},#{session_name}}:#{window_name}')"
check "sanity: the grouped label names the group, not the view" test "${WANT%%:*}" = tt
check "status held by: nobody when no holder"  test "$($C discord status --project hp | grep '^held')" = "held by: nobody"
spawn "$SDH" attached "$REALPANE"; HP=$CP
check "status held by: <session>:<window> pid <n>"  test "$($C discord status --project hp | grep '^held')" = "held by: $WANT pid $HP"
check "status held by outside tmux: still a held-by line with the pid"  test -n "$(env -u TMUX -u TMUX_PANE $C discord status --project hp | grep -E "^held by: .* pid $HP\$")"
kill $HP ${=$(kids $HP)} 2>/dev/null; sleep 0.3
spawn "$SDH" attached %98; HP=$CP
check "status held by: another process pid <n> when no pane matches"  test "$($C discord status --project hp | grep '^held')" = "held by: another process pid $HP"

for p in $PIDS; do kill $p 2>/dev/null; done; sleep 0.5
left=0; for p in $PIDS; do kill -0 $p 2>/dev/null && left=1; done
check "every spawned pid is gone"         test $left = 0
check "no process still carries the scratch dir" test -z "$(ps -A -o args= | grep -F "$S" | grep -v grep)"
tt_done
