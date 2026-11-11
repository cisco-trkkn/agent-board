# bg_common.zsh — shared setup of the test_bg*.zsh files (tmux-ctl run/send in the hidden bg session). Source it, then check.
source "${0:A:h}/lib.zsh"
zmodload zsh/datetime
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude shell
r="$TC_STATE/runs-tt.jsonl"   # tmux-ctl's run records for this file's scratch server
# no_stuck: every run record in $r ends with an exit code. A failure line only (no ok line), so the ok count per file is unchanged.
no_stuck() { [ "$(jq -sr '[group_by(.id)[]|select(last.exit==null)]|length' "$r")" = 0 ] || fail "no stuck records"; }
