# test_install.zsh — install.sh: --check, install, --dry-run, --uninstall, --migrate. Every run uses a scratch HOME and
# stub tools on PATH (inst refuses to run with a HOME outside the scratch dir); the real ~/.claude, ~/.tmux.conf and
# ~/.local are never read or written.
source "${0:A:h}/lib.zsh"
R="$TT_REPO"; FIX="$R/tools/tests/fixtures/migrate"
SCR="$(mktemp -d "${TMPDIR:-/tmp}/instt.XXXXXX")"; SCR="${SCR:A}"
trap 'rm -rf "$SCR"; tt_teardown' EXIT INT TERM
STUB="$SCR/stubs"; mkdir -p "$STUB"
for t in tmux ttyd fzf jq; do print -r -- '#!/bin/sh
[ "$1" = "-V" ] && echo "tmux 3.4"
exit 0' > "$STUB/$t"; done
print -r -- '#!/bin/sh
case "$1" in
  --version) echo "${STUB_CLAUDE_VERSION:-2.1.303} (Claude Code)" ;;
  --help) echo "Options:"; [ -z "$STUB_CLAUDE_NOFLAG" ] && echo "  --settings <file>  --plugin-dir <path>" ;;
esac
exit 0' > "$STUB/claude"
chmod +x "$STUB"/*
# system tools without the ones --check looks for: CI runners keep fzf/jq/tmux in /usr/bin, which would hide a "missing" stub
SYSBIN="$SCR/sysbin"; mkdir -p "$SYSBIN"
for f in /usr/bin/*(N) /bin/*(N); do [[ ${f:t} == (fzf|jq|tmux|ttyd|claude) || -e $SYSBIN/${f:t} ]] || ln -s "$f" "$SYSBIN/${f:t}"; done
BASEPATH="$SYSBIN"; [[ "${commands[python3]:h}" == (/usr/bin|/bin) ]] || BASEPATH="${commands[python3]:h}:$SYSBIN"   # /usr/bin is already in SYSBIN, minus fzf

rc1_same() { [[ "$1" -eq 1 ]] && cmp -s "$2" "$3" }
newhome() { H="$SCR/h$RANDOM"; mkdir -p "$H"; }
inst() {   # inst args… : install.sh from this checkout with the scratch HOME
  [[ "$H" == "$SCR"/* ]] || { print -u2 "inst: HOME outside scratch"; return 99 }
  HOME="$H" PATH="$STUB:$BASEPATH" zsh "$R/install.sh" "$@"
}
# the author's layout, with the repo at $1 (links) and an unrelated superpowers path inside settings
seed_global() {
  local repo="$1" n
  mkdir -p "$H/.local/bin" "$H/.claude/hooks" "$H/.claude/skills/tmux-orchestrator" "$H/.claude/agents" "$H/.agents/skills/handoff"
  for n in claude-orchestrator dev tmux-agent-cleanup tmux-ctl tmux-dash tmux-dev-layout tmux-jump tmux-session-closed tmux-teammate-window tmux-web-attach; do
    ln -s "$repo/bin/$n" "$H/.local/bin/$n"; done
  for n in bash-mirror artifact-register kill-guard; do ln -s "$repo/claude/hooks/$n.sh" "$H/.claude/hooks/$n.sh"; done
  ln -s "$repo/claude/orchestrator.md" "$H/.claude/orchestrator.md"; ln -s "$repo/claude/worker.md" "$H/.claude/worker.md"
  print "# own hook" > "$H/.claude/hooks/context-size-guard.sh"
  print "skill" > "$H/.claude/skills/tmux-orchestrator/SKILL.md"
  print "handoff skill" > "$H/.agents/skills/handoff/SKILL.md"
  ln -s ../../.agents/skills/handoff "$H/.claude/skills/handoff"
  for n in low medium high; do print "effort $n" > "$H/.claude/agents/effort-$n.md"; done
  print "keep" > "$H/.claude/agents/mine.md"
  cp "$FIX/settings.seed.json" "$H/.claude/settings.json"; cp "$FIX/tmux.seed.conf" "$H/.tmux.conf"
}
FAKE="$SCR/fakerepo"; mkdir -p "$FAKE/bin" "$FAKE/claude/hooks"
for n in agent-board claude-orchestrator dev tmux-agent-cleanup tmux-ctl tmux-dash tmux-dev-layout tmux-jump tmux-session-closed tmux-teammate-window tmux-web-attach; do print "#!/bin/sh" > "$FAKE/bin/$n"; done
STAMP="$(date +%Y%m%d)"

# --- --check
newhome
out="$(inst --check 2>&1)"; rc=$?
check "check: exit 0 with all deps" test $rc -eq 0
check "check: one ok line per dependency (8)" test "$(print -r -- "$out" | grep -c '^ok ')" -eq 8
check "check: ok line carries the path" test -n "$(print -r -- "$out" | grep -F "ok $STUB/tmux")"
rm "$STUB/fzf"; mv "$STUB/jq" "$STUB/jq.off"
out="$(inst --check 2>&1)"; rc=$?
check "check: exit 1 when fzf is missing" test $rc -eq 1
check "check: MISSING fzf" test -n "$(print -r -- "$out" | grep -x 'MISSING fzf')"
check "check: other deps still listed" test -n "$(print -r -- "$out" | grep -F "ok $STUB/tmux")"
print -r -- '#!/bin/sh
exit 0' > "$STUB/fzf"; chmod +x "$STUB/fzf"; mv "$STUB/jq.off" "$STUB/jq"
out="$(STUB_CLAUDE_VERSION=2.1.200 inst --check 2>&1)"; rc=$?
check "check: old claude is MISSING claude" test $rc -eq 1 -a -n "$(print -r -- "$out" | grep '^MISSING claude')"
out="$(STUB_CLAUDE_NOFLAG=1 inst --check 2>&1)"; rc=$?
check "check: claude without --settings/--plugin-dir is MISSING" test $rc -eq 1 -a -n "$(print -r -- "$out" | grep '^MISSING claude')"
check "check writes nothing" test -z "$(ls -A "$H")"

# --- install
newhome
out="$(inst 2>&1)"; rc=$?
check "install: exit 0" test $rc -eq 0
check "install: link points at this checkout's bin/agent-board" test "$(readlink "$H/.local/bin/agent-board")" = "$R/bin/agent-board"
check "install: exactly one entry under ~/.local" test "$(find "$H" -mindepth 1 | sort | tr '\n' ' ')" = "$H/.local $H/.local/bin $H/.local/bin/agent-board "
check "install: nothing under ~/.claude" test ! -e "$H/.claude"
out="$(inst 2>&1)"; rc=$?
check "install again: unchanged, exit 0" test $rc -eq 0 -a -n "$(print -r -- "$out" | grep -F unchanged)"
rm "$H/.local/bin/agent-board"; ln -s "$SCR/other/bin/agent-board" "$H/.local/bin/agent-board"
out="$(inst 2>&1)"; rc=$?
check "install: other checkout -> would repoint, exit 1" test $rc -eq 1 -a -n "$(print -r -- "$out" | grep -F 'would repoint')"
check "install: other checkout link untouched" test "$(readlink "$H/.local/bin/agent-board")" = "$SCR/other/bin/agent-board"
out="$(inst --force-relink 2>&1)"; rc=$?
check "install --force-relink repoints" test $rc -eq 0 -a "$(readlink "$H/.local/bin/agent-board")" = "$R/bin/agent-board"
rm "$H/.local/bin/agent-board"; print "mine" > "$H/.local/bin/agent-board"
out="$(inst --force-relink 2>&1)"; rc=$?
check "install: a real file there -> exit 1, untouched" test $rc -eq 1 -a "$(<$H/.local/bin/agent-board)" = mine -a ! -L "$H/.local/bin/agent-board"

# --- --repo
newhome
inst --repo "$FAKE" >/dev/null 2>&1
check "install --repo links into DIR" test "$(readlink "$H/.local/bin/agent-board")" = "$FAKE/bin/agent-board"

# --- --dry-run writes nothing
newhome
marker="$SCR/marker$RANDOM"; sleep 1; touch "$marker"
out="$(inst --dry-run 2>&1)"; rc=$?
check "dry-run install: exit 0, prints the plan" test $rc -eq 0 -a -n "$(print -r -- "$out" | grep -F 'agent-board')"
check "dry-run install: nothing newer than the marker" test -z "$(find "$H" -newer "$marker" 2>/dev/null)"
check "dry-run install: HOME still empty" test -z "$(ls -A "$H")"
newhome; seed_global "$FAKE"
before="$(find "$H" | sort | xargs ls -ld 2>/dev/null | shasum; shasum "$H/.claude/settings.json" "$H/.tmux.conf")"
sleep 1; marker="$SCR/marker$RANDOM"; touch "$marker"
out="$(inst --repo "$FAKE" --migrate --dry-run 2>&1)"; rc=$?
check "dry-run migrate: exit 0" test $rc -eq 0
check "dry-run migrate: nothing newer than the marker" test -z "$(find "$H" -newer "$marker" 2>/dev/null)"
check "dry-run migrate: tree and files identical" test "$before" = "$(find "$H" | sort | xargs ls -ld 2>/dev/null | shasum; shasum "$H/.claude/settings.json" "$H/.tmux.conf")"
check "dry-run migrate: says what it would remove" test -n "$(print -r -- "$out" | grep -F 'kill-guard.sh')" -a -n "$(print -r -- "$out" | grep -F 'tmux-teammate-window')"

# --- --uninstall
newhome; inst >/dev/null 2>&1
mkdir -p "$H/.local/bin"; print x > "$H/.local/bin/other-tool"
out="$(inst --uninstall 2>&1)"; rc=$?
check "uninstall: removes the agent-board link" test $rc -eq 0 -a ! -e "$H/.local/bin/agent-board" -a ! -L "$H/.local/bin/agent-board"
check "uninstall: leaves other files" test -f "$H/.local/bin/other-tool"
ln -s "$SCR/other/bin/agent-board" "$H/.local/bin/agent-board"
out="$(inst --uninstall 2>&1)"
check "uninstall: leaves a link into another checkout" test "$(readlink "$H/.local/bin/agent-board")" = "$SCR/other/bin/agent-board"
newhome; seed_global "$FAKE"
inst --repo "$FAKE" --uninstall >/dev/null 2>&1
check "uninstall: touches nothing else (old links, ~/.claude)" test -L "$H/.local/bin/dev" -a -L "$H/.claude/orchestrator.md" -a -f "$H/.tmux.conf"

# --- --migrate
newhome; seed_global "$FAKE"
ln -sfn "$SCR/elsewhere/tmux-ctl" "$H/.local/bin/tmux-ctl"           # points outside this repo: stays
out="$(inst --repo "$FAKE" --migrate 2>&1)"; rc=$?
print -r -- "$out" > "$SCR/migrate.out"
check "migrate: exit 0" test $rc -eq 0
check "migrate: settings.json = seed minus the agent-board hooks" cmp -s "$H/.claude/settings.json" "$FIX/settings.expected.json"
check "migrate: .tmux.conf = seed minus the 2 hook and 3 binding lines" cmp -s "$H/.tmux.conf" "$FIX/tmux.expected.conf"
check "migrate: settings backup is the seed" cmp -s "$H/.claude/settings.json.bak-$STAMP" "$FIX/settings.seed.json"
check "migrate: tmux.conf backup is the seed" cmp -s "$H/.tmux.conf.bak-$STAMP" "$FIX/tmux.seed.conf"
left="$(ls "$H/.local/bin" | tr '\n' ' ')"
check "migrate: old links gone, agent-board link made, foreign link kept" test "$left" = "agent-board tmux-ctl "
check "migrate: agent-board link points into DIR" test "$(readlink "$H/.local/bin/agent-board")" = "$FAKE/bin/agent-board"
check "migrate: hook and rules links gone" test ! -L "$H/.claude/hooks/bash-mirror.sh" -a ! -L "$H/.claude/hooks/artifact-register.sh" -a ! -L "$H/.claude/hooks/kill-guard.sh" -a ! -L "$H/.claude/orchestrator.md" -a ! -L "$H/.claude/worker.md"
check "migrate: unrelated hook file kept" test -f "$H/.claude/hooks/context-size-guard.sh"
M="$H/.local/state/agent-board/migrated-$STAMP"
check "migrate: tmux-orchestrator skill moved" test -f "$M/tmux-orchestrator/SKILL.md" -a ! -e "$H/.claude/skills/tmux-orchestrator"
check "migrate: handoff skill link moved, target kept" test -L "$M/handoff" -a ! -L "$H/.claude/skills/handoff" -a -f "$H/.agents/skills/handoff/SKILL.md"
check "migrate: effort-* moved" test -f "$M/effort-low.md" -a -f "$M/effort-medium.md" -a -f "$M/effort-high.md" -a ! -e "$H/.claude/agents/effort-low.md"
check "migrate: other agents untouched" test -f "$H/.claude/agents/mine.md"
check "migrate: output names each removed hook" test "$(print -r -- "$out" | grep -cF 'hooks/bash-mirror.sh')" -ge 2 -a -n "$(print -r -- "$out" | grep -F 'hooks/kill-guard.sh')" -a -n "$(print -r -- "$out" | grep -F 'hooks/artifact-register.sh')"
check "migrate: output prints each removed tmux line" test -n "$(print -r -- "$out" | grep -F 'tmux-agent-cleanup')" -a -n "$(print -r -- "$out" | grep -F 'tmux-jump')" -a -n "$(print -r -- "$out" | grep -F 'DEV_CLIENT')" -a -n "$(print -r -- "$out" | grep -F 'tmux-session-closed')"
check "migrate: output says which tmux commands to run" test -n "$(print -r -- "$out" | grep -F 'tmux set-hook -gu after-split-window')" -a -n "$(print -r -- "$out" | grep -F 'tmux set-hook -gu session-closed')" -a -n "$(print -r -- "$out" | grep -F 'unbind')"
check "migrate: output says dev now uses the dedicated server" test -n "$(print -r -- "$out" | grep -i 'dedicated')"
check "migrate: output warns plain claude loses effort-* and names --keep-agents" test -n "$(print -r -- "$out" | grep -F 'plain `claude`')" -a -n "$(print -r -- "$out" | grep -F -e '--keep-agents')"
sum1="$(find "$H" | sort | xargs ls -ld 2>/dev/null | shasum)"
out2="$(inst --repo "$FAKE" --migrate 2>&1)"; rc=$?
check "migrate again: exit 0, nothing more changed" test $rc -eq 0 -a "$sum1" = "$(find "$H" | sort | xargs ls -ld 2>/dev/null | shasum)"
check "migrate: no hard-coded real-HOME paths leaked" test -z "$(print -r -- "$out" | grep -F "$HOME/.claude")"

newhome; seed_global "$FAKE"
out="$(inst --repo "$FAKE" --migrate --keep-agents 2>&1)"
check "migrate --keep-agents: effort-* stay" test -f "$H/.claude/agents/effort-low.md" -a -f "$H/.claude/agents/effort-high.md" -a ! -e "$H/.local/state/agent-board/migrated-$STAMP/effort-low.md"
check "migrate --keep-agents: skills still moved" test -d "$H/.local/state/agent-board/migrated-$STAMP/tmux-orchestrator"

# a settings.json that cannot be rewritten: its hook links stay, the tmux part still goes ahead
newhome; seed_global "$FAKE"
{ print '// my notes'; cat "$FIX/settings.seed.json" } > "$H/.claude/settings.json"; cp "$H/.claude/settings.json" "$SCR/bad-settings"
out="$(inst --repo "$FAKE" --migrate 2>&1)"; rc=$?
check "bad settings: exit 1, file untouched" rc1_same $rc "$H/.claude/settings.json" "$SCR/bad-settings"
check "bad settings: hook links kept (settings still names them)" test -L "$H/.claude/hooks/kill-guard.sh" -a -L "$H/.claude/hooks/bash-mirror.sh" -a -L "$H/.claude/hooks/artifact-register.sh"
check "bad settings: says what was kept and why" test -n "$(print -r -- "$out" | grep -F 'kept' | grep -F 'kill-guard.sh')"
check "bad settings: tmux lines still migrated" cmp -s "$H/.tmux.conf" "$FIX/tmux.expected.conf"
check "bad settings: ~/.local/bin links still migrated" test ! -L "$H/.local/bin/dev"
# valid JSON, not in json.dumps layout (inline array): left byte-identical, entries printed for hand removal
newhome; seed_global "$FAKE"
python3 - "$FIX/settings.seed.json" "$H/.claude/settings.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["permissions"]["allow"] = ["Bash(ls:*)"]
t = json.dumps(d, indent=2, ensure_ascii=False).replace('"allow": [\n      "Bash(ls:*)"\n    ]', '"allow": ["Bash(ls:*)"]')
assert '"allow": ["Bash' in t
open(sys.argv[2], "w").write(t + "\n")
PY
cp "$H/.claude/settings.json" "$SCR/noncanon"
out="$(inst --repo "$FAKE" --migrate 2>&1)"; rc=$?
check "non-canonical settings: exit 1, file byte-identical" rc1_same $rc "$H/.claude/settings.json" "$SCR/noncanon"
check "non-canonical settings: no backup written" test ! -e "$H/.claude/settings.json.bak-$STAMP"
check "non-canonical settings: prints the entries to remove by hand" test -n "$(print -r -- "$out" | grep -F 'by hand' )" -a -n "$(print -r -- "$out" | grep -F 'hooks/kill-guard.sh')"
check "non-canonical settings: hook links kept" test -L "$H/.claude/hooks/kill-guard.sh" -a -L "$H/.claude/hooks/bash-mirror.sh"
check "non-canonical settings: the reason is the message, not one character" test -n "$(print -r -- "$out" | grep -xF 'settings.json left as is: settings.json is not laid out the way json.dumps writes it (or has duplicate keys), so it is left untouched')"
# a .tmux.conf that cannot be read: the ~/.local/bin links stay, settings still migrated
newhome; seed_global "$FAKE"
printf '\377\376 bind D run-shell "~/.local/bin/dev"\n' > "$H/.tmux.conf"; cp "$H/.tmux.conf" "$SCR/badtmux"
out="$(inst --repo "$FAKE" --migrate 2>&1)"; rc=$?
check "bad tmux.conf: exit 1, file untouched" rc1_same $rc "$H/.tmux.conf" "$SCR/badtmux"
check "bad tmux.conf: ~/.local/bin links kept" test -L "$H/.local/bin/dev" -a -L "$H/.local/bin/tmux-teammate-window" -a -L "$H/.local/bin/tmux-jump"
check "bad tmux.conf: says what was kept and why" test -n "$(print -r -- "$out" | grep -F 'kept' | grep -F '.local/bin/dev')"
check "bad tmux.conf: settings still migrated" cmp -s "$H/.claude/settings.json" "$FIX/settings.expected.json"
check "bad tmux.conf: hook links still migrated" test ! -L "$H/.claude/hooks/kill-guard.sh"
# a real directory at skills/handoff is not ours to move
newhome; seed_global "$FAKE"
rm "$H/.claude/skills/handoff"; mkdir "$H/.claude/skills/handoff"; print mine > "$H/.claude/skills/handoff/SKILL.md"
out="$(inst --repo "$FAKE" --migrate 2>&1)"
check "migrate: a real skills/handoff directory is left alone and reported" test -f "$H/.claude/skills/handoff/SKILL.md" -a -n "$(print -r -- "$out" | grep -F 'skills/handoff' | grep -i 'not a link')"

# links into some other repo are not ours
newhome; seed_global "$SCR/not-this-repo"
inst --repo "$FAKE" --migrate >/dev/null 2>&1
check "migrate: links into another checkout stay" test -L "$H/.local/bin/dev" -a -L "$H/.local/bin/tmux-ctl" -a -L "$H/.claude/orchestrator.md"

# --migrate-team-settings drops the team keys, plain --migrate keeps them (the fixture seeds both)
newhome; seed_global "$FAKE"
inst --repo "$FAKE" --migrate --migrate-team-settings >/dev/null 2>&1
check "migrate-team-settings: teammateMode and the team env var are gone" test "$(jq -r '.teammateMode // "none"' "$H/.claude/settings.json")" = none -a "$(jq -r '.env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS // "none"' "$H/.claude/settings.json")" = none
check "migrate-team-settings: other env kept" test "$(jq -r '.env.NODE_EXTRA_CA_CERTS' "$H/.claude/settings.json")" = /home/u/.certs/ca.pem

# no ~/.claude/ idea without a migrate: install/uninstall/check never created it (see install and check cases above)
tt_done
# a same-day backup that already exists is never reused or overwritten: the new one gets a free name
newhome; seed_global "$FAKE"
print "older hand backup" > "$H/.claude/settings.json.bak-$STAMP"; print "older tmux backup" > "$H/.tmux.conf.bak-$STAMP"
inst --repo "$FAKE" --migrate >/dev/null 2>&1
check "backup: existing same-day .bak is left untouched" test "$(<$H/.claude/settings.json.bak-$STAMP)" = "older hand backup" -a "$(<$H/.tmux.conf.bak-$STAMP)" = "older tmux backup"
check "backup: the pre-migrate settings.json is saved under a free name" test "$(cat "$H"/.claude/settings.json.bak-$STAMP.1 2>/dev/null | shasum)" = "$(shasum < "$FIX/settings.seed.json")"
check "backup: the pre-migrate .tmux.conf is saved under a free name" test "$(cat "$H"/.tmux.conf.bak-$STAMP.1 2>/dev/null | shasum)" = "$(shasum < "$FIX/tmux.seed.conf")"
newhome; seed_global "$FAKE"
print "older" > "$H/.tmux.conf.bak-$STAMP"; print "older" > "$H/.tmux.conf.bak-$STAMP.1"
out="$(inst --repo "$FAKE" --migrate --dry-run 2>&1)"
check "backup dry-run: names the free backup (.2), not an existing one" test -n "$(print -r -- "$out" | grep -F "would back up $H/.tmux.conf to $H/.tmux.conf.bak-$STAMP.2")"

