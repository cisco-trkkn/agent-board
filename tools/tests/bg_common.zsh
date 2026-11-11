# bg_common.zsh — shared setup of the test_bg*.zsh files (tmux-ctl run/send in the hidden bg session). Source it, then check.
source "${0:A:h}/lib.zsh"
zmodload zsh/datetime
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude shell
r="$TC_STATE/runs-tt.jsonl"   # tmux-ctl's run records for this file's scratch server
