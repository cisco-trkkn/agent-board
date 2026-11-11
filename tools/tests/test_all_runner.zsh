#!/usr/bin/env zsh
# test_all_runner.zsh — all.zsh on a fake repo layout (TC_TEST_ROOT) of stub jobs. No tmux server needed.
# Stubs append "S <name>" at start and "E <name>" at end to one shared $STUB_LOG; line order is the event order.
# TC_ALL_RUNNER overrides the runner under test (used to run the mutations named in the comments below).
source "${0:A:h}/lib.zsh"
ALL="${TC_ALL_RUNNER:-${0:A:h}/all.zsh}"
SCR="$(mktemp -d "${TMPDIR:-/tmp}/test-all-runner.XXXXXX")"; SCR="${SCR:A}"
trap 'rm -rf "$SCR"; tt_teardown' EXIT INT TERM

# stub <root> <relpath> <sleep> <rc> [extra first-lines]: a job file that logs S/E around a sleep and exits <rc>.
stub() {
  local root=$1 rel=$2 sl=$3 rc=$4 hdr=$5 n=${2:t}; mkdir -p "$root/${rel:h}"
  case $rel in
  *.py) cat > "$root/$rel" <<EOF
${hdr:+# $hdr}
import os, time, unittest
def log(m):
    with open(os.environ["STUB_LOG"], "a") as f: f.write(m + "\n")
class T(unittest.TestCase):
    def test(self):
        log("S $n"); log("ENV $n " + os.environ.get("TMPDIR", "") + " " + os.environ.get("TC_STATE", "") + " " + os.getcwd())
        time.sleep($sl); log("E $n")
        self.assertEqual($rc, 0)
EOF
    ;;
  *) cat > "$root/$rel" <<EOF
${hdr:+# $hdr}
printf 'S %s\n' $n >> "\$STUB_LOG"
printf 'ENV %s %s %s %s\n' $n "\$TMPDIR" "\$TC_STATE" "\$PWD" >> "\$STUB_LOG"
if [ $n = test_bad.zsh ]; then i=1; while [ \$i -le 40 ]; do echo "noise \$i"; i=\$((i+1)); done; echo LAST-LINE; fi
sleep $sl
printf 'E %s\n' $n >> "\$STUB_LOG"
exit $rc
EOF
    ;;
  esac
}
mkroot() {   # mkroot <dir>: 12 jobs, all passing
  local r=$1
  stub $r board/tests/test_slow.py 0.5 0
  stub $r board/tests/test_mid.py 0.3 0
  stub $r board/tests/test_quick.py 0.1 0
  stub $r tools/tests/test_z1.zsh 0.3 0
  stub $r tools/tests/test_z2.zsh 0.3 0
  stub $r tools/tests/test_z3.zsh 0.1 0
  stub $r tools/tests/test_ser1.zsh 0.3 0 '# serial: shares a port'
  stub $r tools/tests/test_ser2.zsh 0.3 0 '# serial'
  stub $r tools/tests/test_t.py 0.1 0
  stub $r claude/skills/docs-compose/tests/test_s.py 0.2 0
  stub $r claude/statusline/tests/test_st.py 0.1 0
  stub $r claude/hooks/tests/test-h.sh 0.2 0
}
ROOT="$SCR/root"; mkroot $ROOT
export STUB_LOG="$SCR/stub.log"

# run <args…>: run the runner on $ROOT; $out is its output, $rc its exit code; the stub log starts empty.
run() { : > "$STUB_LOG"; out=$(env TC_TEST_ROOT="$ROOT" TMPDIR="$SCR" TC_STATE="$SCR/st" "$@" 2>&1); rc=$? }
slog() { awk '$1=="S"{printf "%s ", $2}' "$STUB_LOG" }   # start order, space separated

# --- RED guard: with no runner every check below fails; with one it must exist
[[ -f $ALL ]] || print -u2 "note: $ALL missing"

# --- verdict, exit 0, run dir removed
run zsh $ALL -j 4
# mutation: print another verdict format (e.g. drop "jobs") → fails
check "pass: verdict ALL PASS 12 jobs in NmNs" grep -Eq '^ALL PASS 12 jobs in [0-9]+m[0-9]+s$' <<<"$out"
check "pass: verdict is the last line" [ "$(tail -1 <<<"$out" | cut -c1-8)" = "ALL PASS" ]
check "pass: exit 0" [ $rc -eq 0 ]
# mutation: never rm the run dir → fails
check "pass: run dir removed" [ -z "$(print -l $SCR/tc-all.*(N))" ]
check "pass: 5 slowest listed before the verdict" [ "$(grep -c '^  .* [0-9]*s$' <<<"$out")" = 5 ]
rm -rf $SCR/tc-all.*(N)

# --- concurrency cap (6 jobs of 1 s each: two are alive together unless the runner starts them one by one, whatever the load)
CAPROOT="$SCR/caproot"; for n in 1 2 3 4 5 6; do stub $CAPROOT tools/tests/test_cap$n.zsh 1 0; done
ROOT_SAVE=$ROOT; ROOT=$CAPROOT
run zsh $ALL -j 2
ROOT=$ROOT_SAVE
maxc=$(awk '$1=="S"{r++; if(r>m)m=r} $1=="E"{r--} END{print m+0}' "$STUB_LOG")
# mutation: drop the -j cap (no running-count wait) → max concurrency is 6
check "-j 2: never more than 2 jobs at once" [ "$maxc" -le 2 ]
check "-j 2: does use 2 at once" [ "$maxc" -eq 2 ]
rm -rf $SCR/tc-all.*(N)

# --- serial jobs run alone, after every parallel job
run zsh $ALL -j 4
serbad=$(awk '$1=="S" && $2 ~ /^test_ser/ {if (r!=0) bad=1; seen=1}
              $1=="S" && $2 !~ /^test_ser/ && seen {bad=1}
              $1=="S"{r++} $1=="E"{r--} END{print bad+0 seen*10}' "$STUB_LOG")
# mutation: schedule "# serial" jobs in the parallel phase → one starts while others run (bad=1)
check "serial: '# serial' jobs start only after every parallel job ended, one at a time" [ "$serbad" = "010" ]
rm -rf $SCR/tc-all.*(N)

# --- order: untimed first (suite order), then slowest first by the timings file; serial last
mkdir -p $SCR/st
printf 'board/test_slow\t5\nboard/test_mid\t3\nboard/test_quick\t1\nzsh/test_z1.zsh\t4\n' > $SCR/st/test-timings.tsv
run zsh $ALL -j 1
want="test_z2.zsh test_z3.zsh test_t.py test_s.py test_st.py test-h.sh test_slow.py test_z1.zsh test_mid.py test_quick.py test_ser1.zsh test_ser2.zsh "
# mutation: sort ascending, or untimed last, or ignore the timings file → order differs
check "order: untimed first, then slowest first (from seeded timings)" [ "$(slog)" = "$want" ]
rm -rf $SCR/tc-all.*(N)

# --- timings: rewritten after a full run, untouched by a --suite run
printf 'bogus\t99\n' > $SCR/st/test-timings.tsv
run zsh $ALL -j 4
# mutation: skip the rewrite → bogus stays and board/test_slow is missing
check "timings: rewritten after a full run (job TAB seconds)" grep -Eq '^board/test_slow	[0-9.]+$' $SCR/st/test-timings.tsv
check "timings: old entries dropped" [ -z "$(grep bogus $SCR/st/test-timings.tsv)" ]
check "timings: one line per job (12)" [ "$(wc -l < $SCR/st/test-timings.tsv | tr -d ' ')" = 12 ]
printf 'bogus\t99\n' > $SCR/st/test-timings.tsv; cp $SCR/st/test-timings.tsv $SCR/st/before
run zsh $ALL --suite zsh
# mutation: rewrite after --suite runs too → file differs
check "timings: not rewritten after a --suite run" cmp -s $SCR/st/test-timings.tsv $SCR/st/before
rm -rf $SCR/tc-all.*(N)
# default path, resolved from TMPDIR when TC_STATE is unset
: > "$STUB_LOG"; env -u TC_STATE TC_TEST_ROOT="$ROOT" TMPDIR="$SCR" zsh $ALL -j 4 >/dev/null 2>&1
check "timings: default path \${TMPDIR}/tmux-ctl-\$UID/test-timings.tsv" [ -s "$SCR/tmux-ctl-$UID/test-timings.tsv" ]
rm -rf $SCR/tc-all.*(N)

# --- --suite zsh
run zsh $ALL --suite zsh -j 4
# mutation: ignore --suite → board/tools/skill/hook stubs start too
check "--suite zsh: only zsh jobs ran" [ "$(slog | tr ' ' '\n' | grep -v '^$' | grep -vc '^test_\(z[0-9]\|ser[0-9]\)\.zsh$')" = 0 ]
check "--suite zsh: all 5 zsh jobs ran" grep -q '^ALL PASS 5 jobs' <<<"$out"
run zsh $ALL --suite hooks --suite statusline -j 4
check "--suite is repeatable" grep -q '^ALL PASS 2 jobs' <<<"$out"
rm -rf $SCR/tc-all.*(N)

# --- --list runs nothing and prints name + command
run zsh $ALL --list
# mutation: run the jobs under --list → stamps appear
check "--list: runs nothing (no stamps)" [ ! -s "$STUB_LOG" ]
check "--list: prints 12 lines" [ "$(wc -l <<<"$out" | tr -d ' ')" = 12 ]
check "--list: board job with its command" grep -q "^board/test_slow.*python3 -m unittest board.tests.test_slow" <<<"$out"
check "--list: zsh job with its command" grep -q "^zsh/test_z1.zsh.*zsh tools/tests/test_z1.zsh" <<<"$out"
check "--list: tools py job" grep -q "^tools/test_t.py.*unittest discover -s tools/tests -p 'test_t.py'" <<<"$out"
check "--list: skill job" grep -q "^skill/docs-compose.*unittest discover -s claude/skills/docs-compose/tests" <<<"$out"
check "--list: statusline job" grep -q "^statusline.*unittest discover -s claude/statusline/tests" <<<"$out"
check "--list: hooks job" grep -q "^hooks/test-h.sh.*bash claude/hooks/tests/test-h.sh" <<<"$out"

# --- --serial: suite order, one at a time (timings file present and must be ignored)
printf 'board/test_slow\t5\n' > $SCR/st/test-timings.tsv
run zsh $ALL --serial
maxc=$(awk '$1=="S"{r++; if(r>m)m=r} $1=="E"{r--} END{print m+0}' "$STUB_LOG")
want="test_mid.py test_quick.py test_slow.py test_ser1.zsh test_ser2.zsh test_z1.zsh test_z2.zsh test_z3.zsh test_t.py test_s.py test_st.py test-h.sh "
# mutation: --serial keeps the timing sort or -j default → order or concurrency check fails
check "--serial: suite order (board, zsh, tools, skills, statusline, hooks)" [ "$(slog)" = "$want" ]
check "--serial: one job at a time" [ "$maxc" -eq 1 ]
rm -rf $SCR/tc-all.*(N)

# --- per-job TMPDIR and TC_STATE, cwd = repo root
run zsh $ALL -j 4
envs=("${(@f)$(grep '^ENV ' "$STUB_LOG")}")
bad=0; typeset -A seen
for l in $envs; do
  w=(${=l}); [[ $w[3] == $SCR/* && $w[4] == $w[3]/state && $w[5] == $ROOT && -z $seen[$w[3]] ]] || bad=1; seen[$w[3]]=1
done
# mutation: share one TMPDIR, or leave TC_STATE unset → a line breaks the rule
check "env: every job (zsh, sh and python stubs) has its own TMPDIR, TC_STATE=\$TMPDIR/state, cwd = root" [ $bad -eq 0 -a ${#envs} -eq 12 ]
rm -rf $SCR/tc-all.*(N)

# --- budget: rc 4 and SLOW line
run env TC_TEST_BUDGET=0 zsh $ALL -j 4
# mutation: ignore TC_TEST_BUDGET → rc 0
check "budget 0: exit 4" [ $rc -eq 4 ]
check "budget 0: verdict still ALL PASS" grep -Eq '^ALL PASS 12 jobs in ' <<<"$out"
check "budget 0: SLOW line is last" grep -Eq '^SLOW: [0-9]+m[0-9]+s over the ' <(tail -1 <<<"$out")
rm -rf $SCR/tc-all.*(N)

# --- failure
FROOT="$SCR/froot"; mkroot $FROOT; stub $FROOT tools/tests/test_bad.zsh 0.1 1
ROOT_SAVE=$ROOT; ROOT=$FROOT
run zsh $ALL -j 4
ROOT=$ROOT_SAVE
# mutation: exit 0 on failure, or list no names → fails
check "fail: verdict FAIL 1/13: zsh/test_bad.zsh" grep -q '^FAIL 1/13: zsh/test_bad.zsh$' <<<"$out"
check "fail: verdict is the last line" [ "$(tail -1 <<<"$out" | cut -c1-4)" = FAIL ]
check "fail: exit 1" [ $rc -eq 1 ]
check "fail: FAIL <job> (<s>s) line" grep -Eq '^FAIL zsh/test_bad.zsh \([0-9]+s\)$' <<<"$out"
# mutation: print the whole log, or none → LAST-LINE missing / "noise 1" present
check "fail: failed log tail printed (last line present)" grep -q '^LAST-LINE$' <<<"$out"
check "fail: only the last 30 lines (noise 1 absent, noise 12 present)" [ -n "$(grep -x 'noise 12' <<<"$out")" -a -z "$(grep -x 'noise 11' <<<"$out")" ]
dk=$(sed -n 's/^run dir kept: //p' <<<"$out")
# mutation: remove the run dir on failure too → fails
check "fail: run dir kept and its path printed" [ -n "$dk" -a -d "$dk" -a -f "$dk/zsh/test_bad.zsh.log" ]
rm -rf $SCR/tc-all.*(N)

# --- M2: a non-numeric -j is a usage error
run zsh $ALL -j abc
# mutation: ignore a bad -j (fall back to the cpu count) → rc 0 and the jobs run
check "-j abc: usage error, exit 2, nothing ran" [ $rc -eq 2 -a ! -s "$STUB_LOG" ]

# --- M5: nproc fallback, with sysctl failing and nproc printing 1 (PATH stubs): concurrency must be 1
mkdir -p $SCR/bin; printf '#!/bin/sh\nexit 1\n' > $SCR/bin/sysctl; printf '#!/bin/sh\necho 1\n' > $SCR/bin/nproc; chmod +x $SCR/bin/*
: > "$STUB_LOG"; out=$(env PATH="$SCR/bin:$PATH" TC_TEST_ROOT="$ROOT" TMPDIR="$SCR" TC_STATE="$SCR/st" zsh $ALL 2>&1); rc=$?
maxc=$(awk '$1=="S"{r++; if(r>m)m=r} $1=="E"{r--} END{print m+0}' "$STUB_LOG")
# mutation: drop the nproc fallback (or ignore the sysctl failure) → the default job count is 4 and the max is above 1
check "nproc fallback: sysctl fails, nproc says 1 → one job at a time" [ $maxc -eq 1 -a $rc -eq 0 ]
rm -rf $SCR/tc-all.*(N)

# --- Important 1: TERM to the runner kills every job's whole process tree
KROOT="$SCR/kroot"; mkdir -p $KROOT/tools/tests
for n in 1 2 3; do cat > $KROOT/tools/tests/test_hang$n.zsh <<STUBEND
echo \$\$ >> "$SCR/pids"
sleep 60 &
echo \$! >> "$SCR/pids"
wait
STUBEND
done
: > $SCR/pids
env TC_TEST_ROOT="$KROOT" TMPDIR="$SCR" TC_STATE="$SCR/st" zsh $ALL -j 3 > $SCR/term.out 2>&1 &
rp=$!
pids_n() { [ "$(wc -l < $SCR/pids | tr -d ' ')" -ge 6 ] }
tt_wait 10 pids_n
kill -TERM $rp; wait $rp 2>/dev/null
sleep 0.5
alive=0; for p in $(<$SCR/pids); do kill -0 $p 2>/dev/null && { alive=$((alive+1)); kill $p 2>/dev/null }; done   # by PID: only processes this test started
# mutation: kill only the job subshells (kill $(jobs -p)) → the stub shells and their sleep children stay alive
check "TERM to the runner: no job process (shell or child) is left alive" [ "$(wc -l < $SCR/pids | tr -d ' ')" -ge 6 -a $alive -eq 0 ]
rm -rf $SCR/tc-all.*(N)

# --- M1: a job subshell killed without writing its .res must not hang the runner
DROOT="$SCR/droot"; mkdir -p $DROOT/tools/tests
cat > $DROOT/tools/tests/test_die.zsh <<STUBEND
sleep 0.3
rd=\${TMPDIR%/tmp/*}
cp=\$(cat \$rd/zsh/test_die.zsh.pid)
kill -9 \$(ps -o ppid= -p \$cp)
sleep 2
STUBEND
env TC_TEST_ROOT="$DROOT" TMPDIR="$SCR" TC_STATE="$SCR/st" zsh $ALL > $SCR/die.out 2>&1 &
dp=$!
gone() { ! kill -0 $dp 2>/dev/null }
tt_wait 20 gone
if kill -0 $dp 2>/dev/null; then dead=0; kill $dp; else dead=1; fi
wait $dp 2>/dev/null; drc=$?
# mutation: drop the dead-PID check in reap → the runner waits forever (killed here after 20 s)
dieok() { [ $dead -eq 1 -a $drc -eq 1 ] && grep -q '^FAIL 1/1: zsh/test_die.zsh$' $SCR/die.out }
check "dead job subshell: runner finishes and reports FAIL 1/1" dieok
rm -rf $SCR/tc-all.*(N)

# --- two failing jobs: the verdict names both (the failed-job list is indexed by two numbers)
F2ROOT="$SCR/f2root"; mkroot $F2ROOT; stub $F2ROOT tools/tests/test_bad.zsh 0.1 1; stub $F2ROOT tools/tests/test_bad2.zsh 0.1 1
ROOT_SAVE=$ROOT; ROOT=$F2ROOT
run zsh $ALL -j 4
ROOT=$ROOT_SAVE
# mutation: index the job names with the failed list ("J_name[$failed]") → bad math expression, no verdict
check "two failures: exit 1" [ $rc -eq 1 ]
check "two failures: verdict FAIL 2/14 names both" grep -q '^FAIL 2/14: zsh/test_bad.zsh, zsh/test_bad2.zsh$' <<<"$out"
rm -rf $SCR/tc-all.*(N)

tt_done
