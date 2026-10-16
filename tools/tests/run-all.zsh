#!/usr/bin/env zsh
# run-all.zsh — run every test_*.zsh here; exit 1 if any fails.
emulate -L zsh
dir="${0:A:h}"; rc=0
for f in "$dir"/test_*.zsh(N); do
  print -r -- "### ${f:t}"
  zsh "$f" || rc=1
done
exit $rc
