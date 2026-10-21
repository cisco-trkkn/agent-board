# `tmux-ctl agent --model M --effort E` puts the claude flags on the launch line (default sonnet/medium).
# Seam: isolated tmux server (lib.zsh, -f /dev/null) + a stub `claude` first on the panes' PATH that
# records its argv instead of starting a session (first on tmux-ctl's PATH too: the launch line pins PATH to the repo's bin: plus the caller's). Bad values are refused before any window exists.
here="${0:A:h}"; root="${here:h:h}"
source "$here/lib.zsh"
C="${TC_CTL:-$root/bin/tmux-ctl}"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
tt_setup
stub="$TT_DIR/stub"; mkdir -p "$stub"
print -r -- '#!/bin/sh
printf "%s\n" "$@" > "$TT_DIR/argv.$$"; mv "$TT_DIR/argv.$$" "$TT_DIR/argv"' > "$stub/claude"; chmod +x "$stub/claude"
tt set-environment -g TT_DIR "$TT_DIR"
tt set-option -g default-command "env PATH=$stub:/usr/bin:/bin /bin/sh -i"
repo="$TT_DIR/repo"; mkdir -p "$repo"; git -C "$repo" init -qb main; git -C "$repo" commit -q --allow-empty -m init
brief="Goal: say hi. Scope: nothing at all here. Done: the stub saw its flags."

# refusals happen before any window is created
for bad in "--model gpt" "--effort max" "--model" "--effort"; do
  out="$(cd "$repo" && $C agent bad1 ${=bad} "$brief" 2>&1)"; rc=$?
  check "refuses '$bad'" test $rc -ne 0
  check "no window after '$bad'" test -z "$(tt list-windows -F '#{window_name}' | grep -x bad1)"
done

(cd "$repo" && PATH="$stub:$PATH" $C agent w1 --model haiku --effort low "$brief") >/dev/null 2>&1
tt_wait 8 test -s "$TT_DIR/argv"
line="$(tt capture-pane -p -J -t '=tt:w1' -S -20 | grep -F 'claude ' | head -1)"
check "launch line has --model haiku"  grep -qF -- '--model haiku' <<<"$line"
check "launch line has --effort low"   grep -qF -- '--effort low' <<<"$line"
check "argv: --model haiku"  grep -qx -- 'haiku' "$TT_DIR/argv"
check "argv: --effort low"   grep -qx -- 'low' "$TT_DIR/argv"
rm -f "$TT_DIR/argv"

(cd "$repo" && PATH="$stub:$PATH" $C agent w2 "$brief") >/dev/null 2>&1
tt_wait 8 test -s "$TT_DIR/argv"
line="$(tt capture-pane -p -J -t '=tt:w2' -S -20 | grep -F 'claude ' | head -1)"
check "default --model sonnet"  grep -qF -- '--model sonnet' <<<"$line"
check "default --effort medium" grep -qF -- '--effort medium' <<<"$line"
check "brief still last arg"    grep -qxF -- "$brief" "$TT_DIR/argv"
leaks="$(tt list-windows -a -F '#{window_name}' | grep -vxE 'claude|shell|tests|w1|w2')"
check "no stray windows" test -z "$leaks"
tt_done
