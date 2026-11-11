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
    -j)        [[ -n $2 ]] || { print -u2 "all.zsh: -j needs a positive number"; exit 2 }; jn="$2"; shift 2 ;;
    -j*)       jn="${1#-j}"; shift ;;
    --list)    list=1; shift ;;
    *) print -u2 "usage: all.zsh [--suite board|zsh|tools|skills|statusline|hooks]… [--serial] [-j N] [--list]"; exit 2 ;;
  esac
done
[[ -z $jn || $jn == <1-> ]] || { print -u2 "all.zsh: -j needs a positive number, got '$jn'"; exit 2 }
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
  order=(${${(f)"$(print -rl -- $lines | LC_ALL=C sort -t$'\t' -k1,1gr -k2,2n)"}##*$'\t'})
fi

rundir="$(mktemp -d "${TMPDIR:-/tmp}/tc-all.XXXXXX")"; rundir="${rundir:A}"
T0=$EPOCHREALTIME

run_job() {   # run_job <index>: log, then <name>.res = "rc seconds" (written last, so its existence means done)
  local i=$1 name=$J_name[$i] jt t0 rc
  # short dir name: a unix socket path under TMPDIR is limited to 104 bytes on macOS
  jt="$rundir/tmp/$i"; mkdir -p "$jt/state" "$rundir/${name:h}"
  t0=$EPOCHREALTIME
  if (( $+commands[perl] )); then
    env TMPDIR="$jt" TC_STATE="$jt/state" perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' sh -c "$J_cmd[$i]" > "$rundir/$name.log" 2>&1 &
  else
    env TMPDIR="$jt" TC_STATE="$jt/state" sh -c "$J_cmd[$i]" > "$rundir/$name.log" 2>&1 &
  fi
  print -r -- $! > "$rundir/$name.pid"
  wait $!; rc=$?
  print -r -- "$rc $(( EPOCHREALTIME - t0 ))" > "$rundir/$name.res.tmp" && mv "$rundir/$name.res.tmp" "$rundir/$name.res"
}
typeset -A jpid
running=(); polls=0
reap() {
  local k st; local -a still
  (( polls++ ))
  for k in $running; do
    [[ -e "$rundir/$J_name[$k].res" ]] && continue
    # a job subshell that died without writing its .res (SIGKILL, OOM) would be waited for forever: count it as failed.
    # Checked about once a second; a finished child that is not yet waited for shows as a zombie (Z).
    if (( polls % 20 == 0 )); then
      st="$(ps -o stat= -p ${jpid[$k]} 2>/dev/null)"
      if [[ -z $st || $st == Z* ]]; then
        [[ -e "$rundir/$J_name[$k].res" ]] || print -r -- "137 0" > "$rundir/$J_name[$k].res"
        continue
      fi
    fi
    still+=$k
  done
  running=($still)
}
# each job's command runs in its own session (setsid via perl; pgid = its pid, in <name>.pid), so an interrupt kills the whole
# tree (sh, the test, its tmux and board servers) and not only the job subshell
# Only jobs still running are signalled (no .res yet): a finished job's pid may be reused. INT then TERM to each live group,
# up to 3 s for them to go, then KILL what is left.
killjobs() {
  local k p i; local -a pids=() left=()
  for k in ${(k)jpid}; do
    [[ -e "$rundir/$J_name[$k].res" ]] && continue
    kill -TERM ${jpid[$k]} 2>/dev/null
    p="$(<"$rundir/$J_name[$k].pid" 2>/dev/null)"; [[ -n $p ]] && pids+=$p
  done
  for p in $pids; do kill -INT -- -$p 2>/dev/null; done
  sleep 0.2
  for p in $pids; do kill -TERM -- -$p 2>/dev/null; done
  for (( i=0; i<30; i++ )); do
    left=(); for p in $pids; do kill -0 -- -$p 2>/dev/null && left+=$p; done
    (( ${#left} )) || break
    sleep 0.1
  done
  for p in $left; do kill -KILL -- -$p 2>/dev/null; done
}
trap 'killjobs; print -u2 "all.zsh: interrupted, run dir $rundir"; exit 130' INT TERM

for i in $order; do
  while (( ${#running} >= jn )); do sleep 0.05; reap; done
  run_job $i &
  jp=$!; jpid[$i]=$jp
  running+=$i
done
while (( ${#running} )); do sleep 0.05; reap; done
wait
for i in $ser; do
  run_job $i &
  jp=$!; jpid[$i]=$jp
  wait $jpid[$i]
done

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
# tests run: unittest "Ran N tests" lines + zsh "ok" lines + hook "PASS" lines, summed over every job log (read before the run dir goes)
logs=(); for (( i=1; i<=n; i++ )); do logs+="$rundir/$J_name[$i].log"; done   # each job's own log, not logs a test left under its TMPDIR
print "tests: $(cat $logs 2>/dev/null | awk '/^Ran [0-9]+ tests? in /{n+=$2} /^(ok|PASS)( |$)/{n++} END{print n+0}')"
print "slowest:"
for r in ${(f)"$(print -rl -- $rows | LC_ALL=C sort -t$'\t' -k1,1gr | head -5)"}; do print -r -- "  ${r#*$'\t'} $(( int(${r%%$'\t'*}) ))s"; done

if (( ${#suites} == 0 )); then   # full run: rewrite the timings
  mkdir -p "${tfile:h}" && { for r in $rows; do print -r -- "${r#*$'\t'}"$'\t'"${r%%$'\t'*}"; done > "$tfile.tmp" && mv "$tfile.tmp" "$tfile" }
fi

total=$(( EPOCHREALTIME - T0 )); ts=$(( int(total) ))
fmt="$(( ts / 60 ))m$(( ts % 60 ))s"
if (( ${#failed} )); then
  print "run dir kept: $rundir"
  fnames=(); for i in $failed; do fnames+=$J_name[$i]; done   # not J_name[$failed]: with two failures the subscript is "22 33" (arithmetic)
  print -r -- "FAIL ${#failed}/$n: ${(j:, :)fnames}"
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
