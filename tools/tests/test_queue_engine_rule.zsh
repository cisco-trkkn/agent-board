#!/usr/bin/env zsh
# test_queue_engine_rule.zsh — the lead rules (claude/orchestrator.md § Queue mode) hand the queue to the engine:
# enqueue, start, the five [Engine] lines, engine done, the TC_ENGINE=0 fallback. Reads files only.
DOC="${1:-${0:A:h:h:h}/claude/orchestrator.md}"
HANDOFF="${2:-${0:A:h:h:h}/claude/plugin/skills/handoff/SKILL.md}"
fail=0; n=0
ok()  { n=$((n+1)); print -r -- "ok   $1" }
bad() { n=$((n+1)); fail=1; print -r -- "FAIL $1" }
has() { if grep -qF -- "$2" <<< "$block"; then ok "$1"; else bad "$1"; fi }

# the Queue mode bullet, up to the next top-level bullet
queue="$(awk '/^- \*\*Queue mode\.\*\*/{f=1; print; next} f && /^- \*\*/{exit} f' "$DOC")"
block="$(awk '/^     \*\*Engine queue\.\*\*/{f=1} f && /^  [0-9]\. /{exit} f' <<< "$queue")"

[[ -n "$block" ]] && ok "Queue mode has an Engine queue block" || bad "Queue mode has an Engine queue block"
steps="$(grep -cE '^  [0-9]\. ' <<< "$queue")"
[[ "$steps" == 5 ]] && ok "Queue mode still has 5 numbered steps (found $steps)" || bad "Queue mode still has 5 numbered steps (found $steps)"
has "names the engine-c1 config file"        'docs/superpowers/metrics/configs/engine-c1.md'
has "batch start with both configs"          'tmux-ctl metrics batch start --config upfront-seq --config engine-c1'
has "enqueue command"                        'tmux-ctl engine enqueue <spec> --runner lead|engine'
has "gated specs run under the lead"         '--runner lead --gate <id>'
has "start command"                          'tmux-ctl engine start'
has "TC_ENGINE=0 fallback"                   'TC_ENGINE=0'
has "line: your turn"                        '[Engine] your turn: <spec>'
has "line: queue finished"                   '[Engine] queue finished: <report path>'
has "line: stopped"                          '[Engine] stopped: <reason>'
has "line: paused"                           '[Engine] paused: usage limit until <time>'
has "line: awaiting you"                     '[Engine] awaiting you: <spec>: <question>'
has "engine done after a lead-run spec"      'tmux-ctl engine done <spec> --outcome'
has "the lead never answers a parked spec"   'never answer it'
has "the lead does not write the report"     'does not write the morning report'
block="$(cat "$HANDOFF")"
has "handoff doc says Engine: running"       'Engine: running'
has "handoff doc lists engine status"        'tmux-ctl engine status'

print -r -- "checked $n"
(( fail )) && { print "FAILED"; exit 1 }
print "ALL PASS"
