# tmux-ctl agent --dir / --resume / TC_AGENT_CMD: launch-line checks through the TC_AGENT_DRYRUN seam (no window, no worker).
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"
tt_setup
work="$(mktemp -d)"; work="${work:A}"; trap 'rm -rf "$work"; tt_teardown' EXIT INT TERM
repo="$work/repo"; mkdir -p "$repo"; git -C "$repo" init -q
git -C "$repo" -c user.email=t@e -c user.name=T commit -q --allow-empty -m init
git -C "$repo" worktree add -q "$work/wt" -b wtb
mkdir -p "$work/plain"
brief="$work/brief.md"; print -r -- "Goal: do the thing.
Second line." > "$brief"
dry() { ( cd "$repo" && TC_STATE="$work/st" TC_SESSION=tt TC_AGENT_DRYRUN=1 "$@" 2>&1 ) }
new="$R/bin/tmux-ctl"

# golden: the pre-change no---dir launch line (6b9394c), variable parts normalised; byte-identical intent, no git-history dependency
line="$(dry "$new" agent same --model opus --effort high --brief "$brief" | grep '^DRYRUN line:')"
norm="$line"
norm="${norm//${repo:A}/ROOT}"; norm="${norm//$repo/ROOT}"
norm="$(sed -E -e 's# PATH=[^ ]+# PATH=PATHV#' -e 's# AGENT_BOARD_REPO=[^ ]+# AGENT_BOARD_REPO=REPOV#' -e 's# --settings [^ ]+# --settings SETTINGSV#' -e 's# --plugin-dir [^ ]+# --plugin-dir PLUGINV#' -e 's# --append-system-prompt-file [^ ]+# --append-system-prompt-file RULESV#' <<< "$norm")"
golden='DRYRUN line: cd -- ROOT && CLAUDE_MD_REVISE_HOOK=0 TC_ROLE=worker PATH=PATHV AGENT_BOARD_REPO=REPOV claude --model opus --effort high -w same -n same --settings SETTINGSV --plugin-dir PLUGINV --append-system-prompt-file RULESV Goal:\ do\ the\ thing.$'"'"'\n'"'"'Second\ line.'
check "no --dir: launch line equals the pre-change golden line" test "$norm" = "$golden"
b="$line"
check "no --dir: line still has -w same"  grep -q ' -w same ' <<< "$b"

out="$(dry "$new" agent w1 --dir "$work/wt" --model sonnet --effort low --brief "$brief")"; rc=$?
line="$(grep '^DRYRUN line:' <<< "$out")"
check "--dir: line cds into the worktree"   grep -qF "cd -- $work/wt " <<< "$line"
check "--dir: no -w"                        test -n "$line" -a -z "$(grep -F ' -w ' <<< "$line")"
check "--dir: keeps -n w1 and the model"    grep -qE -- '--model sonnet --effort low .*-n w1 ' <<< "$line"
check "--dir: brief text is in the line"    grep -qF 'Goal:' <<< "$line"
check "--dir: no --resume without --resume" test -z "$(grep -F -- '--resume' <<< "$line")"

out="$(dry "$new" agent w2 --dir "$work/wt" --resume sess-123 --brief "$brief")"
line="$(grep '^DRYRUN line:' <<< "$out")"
check "--resume: claude --resume <id>"      grep -qF -- '--resume sess-123' <<< "$line"
check "--resume: brief is the first message (last word group)" grep -qF 'Goal:' <<< "$line"

out="$(dry "$new" agent w3 --dir "$work/plain" --brief "$brief")"; rc=$?
check "--dir not in a git worktree: refused" test $rc -ne 0 -a -z "$(grep '^DRYRUN' <<< "$out")"
out="$(dry "$new" agent w4 --dir "$work/nope" --brief "$brief")"; rc=$?
check "--dir missing: refused"               test $rc -ne 0
out="$(dry "$new" agent w5 --resume x --brief "$brief")"; rc=$?
check "--resume without --dir: refused"      test $rc -ne 0

out="$(TC_AGENT_CMD='echo FAKECMD' dry "$new" agent w6 --dir "$work/wt" --brief "$brief")"
line="$(grep '^DRYRUN line:' <<< "$out")"
check "TC_AGENT_CMD replaces claude ..."     grep -qF 'echo FAKECMD' <<< "$line"
check "TC_AGENT_CMD: no claude --model left" test -z "$(grep -F 'claude --model' <<< "$line")"
check "TC_AGENT_CMD: env prefix kept"        grep -qF 'TC_ROLE=worker' <<< "$line"

check "agent usage header line documents --dir" grep -qxF '#   tmux-ctl agent <name> [--force] [--dir WT [--resume ID]] [--model M] [--effort E] <task> | --brief FILE' "$new"
out="$(dry "$new" agent 'my-spec-p1·implement3' --dir "$work/wt" --brief "$brief")"; rc=$?
check "--dir: window name <slug>·<kind><task> accepted" test $rc -eq 0 -a -n "$(grep -F 'DRYRUN line:' <<< "$out")"
out="$(dry "$new" agent 'a·b' --brief "$brief")"; rc=$?
check "without --dir the name rule is unchanged (· refused)" test $rc -ne 0
tt_done
