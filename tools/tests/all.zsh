#!/usr/bin/env zsh
# all.zsh — run every test suite of the repo in parallel and print one verdict line.
#   zsh tools/tests/all.zsh [--suite board|zsh|tools|skills|statusline|hooks]… [--serial] [-j N] [--list]
# One job per test file (board, zsh, tools, hooks) or per suite dir (3 docs skills, statusline). A file whose first 5
# lines contain "# serial" runs alone after the parallel phase. Timings: <TC_STATE>/test-timings.tsv.
# Exit: 0 all pass, 1 any failure, 4 all pass but over TC_TEST_BUDGET seconds (default 300).
emulate -L zsh
zmodload zsh/datetime zsh/mathfunc
root="${TC_TEST_ROOT:-${0:A:h:h:h}}"
tfile="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}/test-timings.tsv"   # resolved now: jobs get their own TC_STATE
budget="${TC_TEST_BUDGET:-300}"

suites=(); serial=0; jn=; list=0
while (( $# )); do
  case $1 in
    --suite)   [[ -n $2 ]] || { print -u2 "all.zsh: --suite needs a value"; exit 2 }; suites+=("$2"); shift 2 ;;
    --suite=*) suites+=("${1#--suite=}"); shift ;;
    --serial)  serial=1; shift ;;
    -j)        jn="$2"; shift 2 ;;
    -j*)       jn="${1#-j}"; shift ;;
    --list)    list=1; shift ;;
    *) print -u2 "usage: all.zsh [--suite board|zsh|tools|skills|statusline|hooks]… [--serial] [-j N] [--list]"; exit 2 ;;
  esac
done
for s in $suites; do
  [[ $s == (board|zsh|tools|skills|statusline|hooks) ]] || { print -u2 "all.zsh: unknown suite '$s'"; exit 2 }
done
want() { (( ${#suites} == 0 || ${suites[(Ie)$1]} )) }

cd "$root" || { print -u2 "all.zsh: no such root $root"; exit 2 }
J_name=(); J_cmd=(); J_ser=()
add() { J_name+=("$1"); J_cmd+=("$2"); [[ -n $3 && -f $3 ]] && head -5 "$3" | grep -q '# serial' && J_ser+=1 || J_ser+=0 }
f=
if want board;  then for f in board/tests/test_*.py(N);  do add "board/${f:t:r}" "python3 -m unittest board.tests.${f:t:r}" $f; done; fi
if want zsh;    then for f in tools/tests/test_*.zsh(N); do add "zsh/${f:t}" "zsh $f" $f; done; fi
if want tools;  then for f in tools/tests/test_*.py(N);  do add "tools/${f:t}" "python3 -m unittest discover -s tools/tests -p '${f:t}'" $f; done; fi
if want skills; then for d in docs-architecture docs-compose docs-report; do
  [[ -d claude/skills/$d/tests ]] && add "skill/$d" "python3 -m unittest discover -s claude/skills/$d/tests"
done; fi
if want statusline && [[ -d claude/statusline/tests ]]; then add statusline "python3 -m unittest discover -s claude/statusline/tests"; fi
if want hooks;  then for f in claude/hooks/tests/test-*.sh(N); do add "hooks/${f:t}" "bash $f" $f; done; fi
n=${#J_name}

if (( list )); then
  for (( i=1; i<=n; i++ )); do print -r -- "$J_name[$i]"$'\t'"$J_cmd[$i]"; done
  exit 0
fi
(( n )) || { print -u2 "all.zsh: no jobs"; exit 2 }

if (( serial )); then jn=1
elif [[ $jn != <1-> ]]; then jn="$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null)"; [[ $jn == <1-> ]] || jn=4
fi

# order: parallel jobs with no timing first (suite order), then slowest first; "# serial" jobs last, alone
typeset -A tm
if [[ -r $tfile ]]; then while IFS=$'\t' read -r k v; do [[ -n $k && -n $v ]] && tm[$k]=$v; done < "$tfile"; fi
par=(); ser=()
for (( i=1; i<=n; i++ )); do
  if (( serial )) || [[ $J_ser[$i] == 0 ]]; then par+=$i; else ser+=$i; fi
done
if (( serial )); then order=($par)
else
  lines=(); for i in $par; do lines+=("${tm[$J_name[$i]]:-1000000000}"$'\t'"$i"); done
  order=(${${(f)"$(print -rl -- $lines | sort -t$'\t' -k1,1gr -k2,2n)"}##*$'\t'})
fi

rundir="$(mktemp -d "${TMPDIR:-/tmp}/tc-all.XXXXXX")"; rundir="${rundir:A}"
T0=$EPOCHREALTIME

run_job() {   # run_job <index>: log, then <name>.res = "rc seconds" (written last, so its existence means done)
  local i=$1 name=$J_name[$i] jt t0 rc
  jt="$rundir/tmp/${name//\//_}"; mkdir -p "$jt/state" "$rundir/${name:h}"
  t0=$EPOCHREALTIME
  env TMPDIR="$jt" TC_STATE="$jt/state" sh -c "$J_cmd[$i]" > "$rundir/$name.log" 2>&1; rc=$?
  print -r -- "$rc $(( EPOCHREALTIME - t0 ))" > "$rundir/$name.res.tmp" && mv "$rundir/$name.res.tmp" "$rundir/$name.res"
}
running=()
reap() { local k; local -a still; for k in $running; do [[ -e "$rundir/$J_name[$k].res" ]] || still+=$k; done; running=($still) }
trap 'kill $(jobs -p) 2>/dev/null; print -u2 "all.zsh: interrupted, run dir $rundir"; exit 130' INT TERM

for i in $order; do
  while (( ${#running} >= jn )); do sleep 0.05; reap; done
  run_job $i &
  running+=$i
done
while (( ${#running} )); do sleep 0.05; reap; done
wait
for i in $ser; do run_job $i; done

# summary
failed=(); rows=()
for (( i=1; i<=n; i++ )); do
  read -r rc secs < "$rundir/$J_name[$i].res"
  rows+=("$secs"$'\t'"$J_name[$i]")
  if [[ $rc != 0 ]]; then
    failed+=$i
    print -r -- "FAIL $J_name[$i] ($(( int(secs) ))s)"
    tail -30 "$rundir/$J_name[$i].log"
  fi
done
print "slowest:"
for r in ${(f)"$(print -rl -- $rows | sort -t$'\t' -k1,1gr | head -5)"}; do print -r -- "  ${r#*$'\t'} $(( int(${r%%$'\t'*}) ))s"; done

if (( ${#suites} == 0 )); then   # full run: rewrite the timings
  mkdir -p "${tfile:h}" && { for r in $rows; do print -r -- "${r#*$'\t'}"$'\t'"${r%%$'\t'*}"; done > "$tfile.tmp" && mv "$tfile.tmp" "$tfile" }
fi

total=$(( EPOCHREALTIME - T0 )); ts=$(( int(total) ))
fmt="$(( ts / 60 ))m$(( ts % 60 ))s"
if (( ${#failed} )); then
  print "run dir kept: $rundir"
  print -r -- "FAIL ${#failed}/$n: ${(j:, :)J_name[$failed]}"
  exit 1
fi
rm -rf "$rundir"
print "ALL PASS $n jobs in $fmt"
if (( total > budget )); then
  (( budget == 300 )) && bl="5 min" || bl="${budget}s"
  print "SLOW: $fmt over the $bl budget"
  exit 4
fi
exit 0
