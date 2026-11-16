#!/bin/sh
# Fake `claude -p` for the metrics recommend tests (TC_CLAUDE_BIN). Records what it was called with, prints a canned result.
#   FAKE_ARGV    file: its argv, one per line        FAKE_STDIN  file: the prompt it was given
#   FAKE_CWD     file: its working directory         FAKE_SLEEP  seconds to sleep instead of answering
#   FAKE_RECOMMEND_OUT  file whose contents it prints   FAKE_RECOMMEND_RC  exit code (default 0)
[ -n "$FAKE_ARGV" ] && printf '%s\n' "$@" > "$FAKE_ARGV"
[ -n "$FAKE_STDIN" ] && cat > "$FAKE_STDIN"
[ -n "$FAKE_CWD" ] && pwd -P > "$FAKE_CWD"
[ -n "$FAKE_SLEEP" ] && exec sleep "$FAKE_SLEEP"
[ -n "$FAKE_RECOMMEND_OUT" ] && cat "$FAKE_RECOMMEND_OUT"
exit "${FAKE_RECOMMEND_RC:-0}"
