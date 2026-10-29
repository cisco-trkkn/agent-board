#!/usr/bin/env zsh
# rules.zsh — structural checks for Task 8; prints 'rules ok' or the failing check.
emulate -L zsh
cd "${0:A:h}/../../../.." || exit 2
o=claude/orchestrator.md; w=claude/worker.md; bad=0
one() { local n=$(( $(grep -cF -- "$1" $o) + $(grep -cF -- "$1" $w) )); print -r -- "$n  $1"; (( n == 1 )) || bad=1 }
one '120s'; one 'Never stop processes with'; one 'shutdown_response'; one 'agent-ci check'; one 'write to its log'
grep -q '^## If you are a teammate' $w || { print 'no teammate section'; bad=1 }
grep -qF 'claude/worker.md' $o || { print 'orchestrator does not point to worker.md'; bad=1 }
for s in 'Decided' 'Reason: fable-limit' 'end your turn' ; do grep -qF -- "$s" $o $w || { print "missing: $s"; bad=1 }; done
grep -qiE 'before (you )?set(ting)? .*owner' $o || { print 'owner-after-brief rule missing'; bad=1 }
(( bad == 0 )) && print 'rules ok'
exit $bad
