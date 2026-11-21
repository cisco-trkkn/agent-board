source "${0:A:h}/lib.zsh"
# tmux-ctl registry: the engine CLI (engine/bin/registry.js) through the wrapper, outside tmux.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
out="$(env -u TMUX $C registry 2>&1)"; rc=$?
check "registry alone prints the usage line"     zsh -c '[[ $1 == "registry: usage: registry <validate|analyse|stale|report|facts> ..." ]]' _ "$out"
check "registry alone exits 2"                   test $rc -eq 2
err="$(env -u TMUX $C registry facts x 2>&1 >/dev/null)"; rc=$?
check "registry facts x reaches node (error line)" test "$err" = "registry: facts: not built"
check "registry facts x exits 1"                 test $rc -eq 1
check "--help lists the registry subcommands"    zsh -c '"$1" --help | grep -q "tmux-ctl registry <validate|analyse|stale|report|facts>"' _ "$C"
tt_done
