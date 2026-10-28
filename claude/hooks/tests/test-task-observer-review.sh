#!/bin/bash
# Test for task-observer-review.sh classify_run: sources the script via the source-only seam (never runs the review).
set -u
D=$(cd "$(dirname "$0")" && pwd)
S="${SCRIPT:-$D/../task-observer-review.sh}"
FX="$D/fixtures"
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
# shellcheck disable=SC1090
TO_REVIEW_SOURCE_ONLY=1 source "$S"
check seam-no-review-ran "$(type -t classify_run)" function
check limit "$(classify_run "$FX/review-out-limit.txt" 1)" limit-hit
check budget "$(classify_run "$FX/review-out-budget.txt" 1)" budget-hit
check ok "$(classify_run "$FX/review-out-ok.txt" 0)" ok
check ok-nonzero-unmatched "$(classify_run "$FX/review-out-ok.txt" 1)" ok
check limit-text-exit0-is-ok "$(classify_run "$FX/review-out-limit.txt" 0)" ok
check budget-default "$REVIEW_BUDGET_USD" 5
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
