#!/usr/bin/env zsh
# check_real_migrate_plan.zsh — run by hand, not by run-all (CI has no such HOME): the migrate plan for the REAL
# install (the author's ~/.claude, ~/.tmux.conf, ~/.local/bin) must equal fixtures/expected-migrate-plan.txt.
# The fixture pins the pre-migration install: after you migrate, regenerate or retire this check.
# Read-only: install.sh --dry-run changes nothing. The home path becomes ~ and the date YYYYMMDD before comparing.
#   zsh tools/tests/check_real_migrate_plan.zsh [--repo DIR]     (default repo: ~/agent-board)
emulate -L zsh
R="${0:A:h:h:h}"; EXP="${0:A:h}/fixtures/expected-migrate-plan.txt"
repo="$HOME/agent-board"; [[ "$1" == --repo ]] && repo="$2"
norm() { sed -e "s|$HOME|~|g" -E -e 's/(migrated-|\.bak-)[0-9]{8}/\1YYYYMMDD/g'; }
[[ -f "$EXP" ]] || { print -u2 "missing $EXP"; exit 1 }
"$R/install.sh" --repo "$repo" --migrate --dry-run 2>&1 | norm | diff - "$EXP"
rc=${pipestatus[3]}
(( rc )) && print -u2 "the fixture pins the pre-migration install; if the real install changed (a migrate, or settings.json no longer in json.dumps layout), regenerate or retire this check"
(( rc == 0 )) && print "real migrate plan matches"
exit $rc
