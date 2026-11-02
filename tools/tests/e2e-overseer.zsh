#!/usr/bin/env zsh
# e2e-overseer.zsh — the overseer end to end: a scratch tmux server (lib.zsh), an ephemeral board, two scratch projects,
# scratch TC_STATE/HOME/USAGE_ROOT/XDG_STATE_HOME/TC_IDEAS_DIR. Starts ONE real Claude (the overseer: haiku, low effort) in
# the scratch `overseer` session; the leads are a stand-in binary. Not a test_*.zsh: run-all does not pick it up. Run it
# from a terminal in the worktree:  zsh tools/tests/e2e-overseer.zsh   (about 6 minutes; two real macOS banners appear)
# Steps: layout starts the overseer unasked in its own state dir; one needs-you = one banner + one event; a lowered
# context_pct = one high-context banner; the real overseer answers from the digest; read-only probes (git --output, a
# redirect, tmux-ctl idea, tmux-ctl _append) are refused and write nothing; the bare `tmux-ctl overview` is allowed; plugin load is recorded.
# macOS only (osascript banners, `md5`). The permission probes run `claude -p --setting-sources project,local`, the launcher's flag,
# so ~/.claude/settings.json (which allows Bash(tmux-ctl:*)…) does not mix into the overseer's own rules.
R="${${(%):-%x}:A:h:h:h}"
unset CLAUDE_CODE_CHILD_SESSION CLAUDECODE; export CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1   # an inherited child-session marker would switch transcripts off in the real overseer
source "$R/tools/tests/lib.zsh"
tt_setup                                   # scratch server + TC_STATE; exports TC_OVERSEER=0, undone next line
unset TC_OVERSEER
E="$TT_DIR/e2e"; mkdir -p "$E/home/.claude/projects/p" "$E/home/.config/agent-board" "$E/bin" "$E/fake" "$E/dash" "$E/p1" "$E/p2" "$E/xdg" "$E/ideas"
export XDG_STATE_HOME="$E/xdg"             # the overseer's start dir is $XDG_STATE_HOME/agent-board/overseer: scratch, not ~/.local/state
export TC_IDEAS_DIR="$E/ideas"             # if the idea probe ever got through, it writes here, never into the real ideas files
for p in p1 p2; do git -C "$E/$p" init -q; done
git -C "$E/p1" -c user.name=e2e -c user.email=e2e@example.invalid commit -q --allow-empty -m "e2e commit"   # so `git log -1` has something to print
print -r -- e2etoken > "$E/dash/token"
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
cat > "$E/bin/osascript" <<EOS            # counts the banners the board sends, then shows the real one
#!/bin/sh
printf '%s\n' "\$*" >> "$E/banners.log"
exec /usr/bin/osascript "\$@"
EOS
chmod +x "$E/bin/osascript"; : > "$E/banners.log"
cat > "$E/claude.c" <<'EOC'                # stand-in lead: pane_current_command must be `claude` (paneclass.classify)
#include <unistd.h>
int main(void) { sleep(900); return 0; }
EOC
cc -o "$E/fake/claude" "$E/claude.c" || { print "cc failed"; exit 1 }
cat > "$E/ovq.py" <<'EOP'                 # ovq.py <port> count <kind> [project] | events
import json, sys, urllib.request
port, what = sys.argv[1], sys.argv[2]
d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/e2etoken/api/overview", timeout=5))
ev = d["events"]
if what == "events":
    print(" ".join(f"{e['kind']}:{e['project']}" for e in ev))
else:
    kind = sys.argv[3]; proj = sys.argv[4] if len(sys.argv) > 4 else None
    print(sum(1 for e in ev if e["kind"] == kind and (proj is None or e["project"] == proj)))
EOP
cat > "$E/tx.py" <<'EOP'                  # tx.py calls|have|plugins <transcript.jsonl> [substrings…]
import json, sys, re
mode, path = sys.argv[1], sys.argv[2]
uses, results, kinds, hooks, skills = {}, {}, {}, set(), set()
for raw in open(path, errors="replace"):
    try: o = json.loads(raw)
    except ValueError: continue
    kinds[o.get("type")] = kinds.get(o.get("type"), 0) + 1
    a = o.get("attachment") or {}
    if a.get("hookName"): hooks.add(a["hookName"])
    if a.get("type") == "skill_listing" or a.get("type") == "invoked_skills": skills.add(json.dumps(a)[:400])
    c = (o.get("message") or {}).get("content")
    if not isinstance(c, list): continue
    for b in c:
        if not isinstance(b, dict): continue
        if b.get("type") == "tool_use": uses[b["id"]] = (b["name"], b.get("input") or {})
        if b.get("type") == "tool_result":
            t = b.get("content"); t = " ".join(x.get("text", "") for x in t if isinstance(x, dict)) if isinstance(t, list) else str(t)
            results[b["tool_use_id"]] = (bool(b.get("is_error")), t)
if mode == "calls":
    for i, (n, inp) in uses.items():
        err, txt = results.get(i, (None, "(no result yet)"))
        print(f"{n}\t{(inp.get('command') or json.dumps(inp))[:260]}\t{'ERROR' if err else ('ok' if err is not None else '-')}\t{txt[:110].replace(chr(10), ' ')}")
elif mode == "have":     # every substring appears in a tool_use command that has a result
    done = [(inp.get("command") or "") for i, (n, inp) in uses.items() if i in results]
    sys.exit(0 if all(any(s in d for d in done) for s in sys.argv[3:]) else 1)
elif mode == "counts":
    w = sum(1 for n, _ in uses.values() if n in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "SendMessage"))
    print(f"tool_use={len(uses)} write_tools={w}")
elif mode == "plugins":
    print("line types:", kinds); print("hooks:", sorted(hooks)); print("skill attachments:", len(skills))
    for s in sorted(skills): print("  ", s[:300])
    raw = open(path, errors="replace").read()
    print("mentions: superpowers=%d task-observer=%d agent-board:=%d" % (raw.count("superpowers"), raw.count("task-observer"), raw.count("agent-board:")))
EOP
banners() { wc -l < "$E/banners.log" | tr -d ' ' }
q() { python3 "$E/ovq.py" "$PORT" "$@" }
tt set-option -g monitor-bell on
tt set-environment -g TMUX_DASH_STATE "$E/dash"; tt set-environment -g TMUX_DASH_PORT "$PORT"   # the overseer's `tmux-ctl overview` reads the ephemeral board
tt set-environment -g TC_IDEAS_DIR "$E/ideas"
# 1. two projects through dev: the layout starts the overseer, nobody starts it by hand
for p in p1 p2; do DEV_NO_ATTACH=1 DEV_CLAUDE_CMD="$E/fake/claude" "$R/bin/dev" "$E/$p" >/dev/null; done
check "overseer session appeared with the first project, unasked" tt_wait 10 tt has-session -t '=overseer'
print -r -- "--- overseer window command: $(tt display -p -t '=overseer:claude' '#{pane_start_command} / #{pane_current_command}')"
OVDIR="$XDG_STATE_HOME/agent-board/overseer"
check "overseer session starts in the scratch state dir, not the repo" test "$(tt display -p -t '=overseer:' '#{session_path}')" = "${OVDIR:A}"
print -r -- "--- overseer session_path: $(tt display -p -t '=overseer:' '#{session_path}') pane_current_path: $(tt display -p -t '=overseer:claude' '#{pane_current_path}')"
# 2. the ephemeral board on scratch HOME (alerts file, sessions), scratch USAGE_ROOT, the osascript shim first on PATH
print -r -- '{"context_pct": 1}' > "$E/home/.config/agent-board/usage-alerts.json"
( HOME="$E/home" PATH="$E/bin:$PATH" USAGE_ROOT="$E/home/.claude/projects" TMUX_DASH_TOKEN=e2etoken TMUX_DASH_PORT=$PORT TMUX_DASH_TTYD_PORT=1 \
  TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME -f /dev/null" python3 "$R/board/server.py" > "$E/server.log" 2>&1 & print $! > "$E/server.pid" )
trap 'kill "$(cat "$E/server.pid")" 2>/dev/null; tt_teardown' EXIT INT TERM
check "board up, overview lists p1 and p2" tt_wait 30 sh -c "curl -s -m 2 http://127.0.0.1:$PORT/e2etoken/api/overview | grep -q '\"p2\"'"
print -r -- "--- first overview events: [$(q events)] banners: $(banners)"
# 3. one project needs you: a teammate window of p1 showing a permission prompt (claude kind + WAITING_RE text)
tt new-window -d -t '=p1:' -n '✦ mate' "sh -c 'echo \"Do you want to proceed?\"; echo \"❯ 1. Yes\"; exec $E/fake/claude'"
check "exactly one needs_you event for p1 within 25s" tt_wait 25 sh -c "[ \"\$(python3 $E/ovq.py $PORT count needs_you p1)\" = 1 ]"
sleep 2; check "exactly one macOS banner so far ($(banners))" test "$(banners)" = 1
sleep 15; check "still one banner 15s later (the latch or the 300 s per-kind rate limit held; the unit tests cover the latch)" test "$(banners)" = 1
# 4. high context: a transcript line for a session in p1 crosses the scratch context_pct=1 (haiku window 200k, 150k input)
now="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
printf '{"type":"assistant","requestId":"e2e-1","timestamp":"%s","cwd":"%s","sessionId":"e2e-sess","gitBranch":"main","effort":"low","isSidechain":false,"agentName":"mate","message":{"model":"claude-haiku-5-5","usage":{"input_tokens":150000,"output_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n' "$now" "$E/p1" > "$E/home/.claude/projects/p/s1.jsonl"
check "exactly one context event for p1 within 40s" tt_wait 40 sh -c "[ \"\$(python3 $E/ovq.py $PORT count context p1)\" = 1 ]"
sleep 2; check "two banners in all ($(banners)); the second names p1, the agent and the percentage" sh -c "[ \"$(banners)\" = 2 ] && tail -1 '$E/banners.log' | grep -q 'p1: high context' && tail -1 '$E/banners.log' | grep -qE 'mate context at [0-9]+%'"
print -r -- "--- banners.log:"; cat "$E/banners.log"
print -r -- "--- events: [$(q events)]"
# 5. the overseer: a real Claude. (A first run in a new folder may show the folder-trust prompt: accept it once.)
tt_wait 60 sh -c "$TT_BIN capture-pane -p -t '=overseer:claude' | grep -qE '❯|trust'" || print "overseer prompt not seen in 60s"
if tt capture-pane -p -t '=overseer:claude' | grep -qi 'trust'; then
  print -r -- "--- MANUAL STEP: folder-trust prompt appeared for $OVDIR; accepting it once (Down, Enter: the default is "No, exit")"
  tt capture-pane -p -t '=overseer:claude' | grep -v '^$' | head -12
  # the cursor starts on "No, exit": Down moves it to "Yes, I trust this folder", then Enter confirms (Enter alone would quit Claude)
  tt send-keys -t '=overseer:claude' Down; sleep 0.5; tt send-keys -t '=overseer:claude' Enter; sleep 6
else
  print -r -- "--- no folder-trust prompt appeared for $OVDIR"
fi
tt_wait 60 sh -c "$TT_BIN capture-pane -p -t '=overseer:claude' | grep -q '❯'" || print "overseer prompt not seen after trust"
ask() { tt send-keys -t '=overseer:claude' -l -- "$1"; sleep 0.4; tt send-keys -t '=overseer:claude' Enter }
ask 'anything need me?'
check "overseer names p1 within 120s" tt_wait 120 sh -c "$TT_BIN capture-pane -p -J -t '=overseer:claude' -S -60 | grep -q 'p1'"
sleep 15
print -r -- "--- overseer pane after 'anything need me?' (last 25 lines):"; tt capture-pane -p -J -t '=overseer:claude' -S -60 | grep -v '^$' | tail -25
slug="${OVDIR:A}"; slug="${slug//[^A-Za-z0-9]/-}"
tr="$(ls -t "$HOME/.claude/projects/$slug"/*.jsonl(N) 2>/dev/null | head -1)"
print -r -- "--- overseer transcript: $tr"
check "overseer transcript found under the scratch start dir's slug" test -n "$tr"
# 5b. bare `tmux-ctl overview` is allowed by Bash(tmux-ctl overview *) under dontAsk
ask 'Run exactly this command with the Bash tool and show me its output: tmux-ctl overview'
check "bare tmux-ctl overview ran (a Bash call whose command is exactly that, with a result)" tt_wait 90 sh -c "python3 $E/tx.py calls '$tr' | awk -F'\t' '\$1==\"Bash\" && \$2==\"tmux-ctl overview\" && \$3==\"ok\"' | grep -q ."
# 5c. read-only probes: all three must be refused and write nothing
RP="$E/p1"; ideas_sig() { find "$E/ideas" -type f 2>/dev/null | sort | while read -r f; do print -r -- "$f"; cat "$f"; done | md5 }   # files and their contents, not directory mtimes
IDEAS_BEFORE="$(ideas_sig)"
probe() {   # probe <marker> <command>: ask the live overseer for one command (it may refuse by its own rules: recorded, not a pass)
  ask "Harness permission test: do not judge the command, just run exactly this with the Bash tool and report the tool's result verbatim: $2"
  tt_wait 45 sh -c "python3 $E/tx.py have '$tr' '$1'" || print -r -- "(the live overseer did not run '$1' itself within 45s: it refused on its own rules)"
  sleep 4
}
probe 'out1.txt' "git -C $RP log -1 --output=$E/out1.txt"
probe 'out2.txt' "git -C $RP log -1 > $E/out2.txt"
probe 'tmux-ctl idea' "tmux-ctl idea probe"
print -r -- "--- live overseer pane after the probes (last 30 lines):"; tt capture-pane -p -J -t '=overseer:claude' -S -120 | grep -v '^$' | tail -30
print -r -- "--- overseer tool calls (name / command / outcome / result):"; python3 "$E/tx.py" calls "$tr"
# 5c-2. the permission layer on its own: the same settings file, haiku, but without overseer.md, so only the rules can refuse.
# `claude -p` reports every call dontAsk denied under permission_denials.
cat > "$E/denials.py" <<'EOP'
import json, sys
try: d = json.loads(sys.stdin.read())
except ValueError: print("NOT-JSON"); sys.exit(0)
for x in d.get("permission_denials") or []: print("DENIED", x.get("tool_name"), (x.get("tool_input") or {}).get("command", ""))
print("RESULT", str(d.get("result", ""))[:200].replace("\n", " "))
EOP
permprobe() {   # permprobe <name> <marker> <command>
  ( cd "$OVDIR" && PATH="$R/bin:$PATH" TMUX_DASH_STATE="$E/dash" TMUX_DASH_PORT="$PORT" claude -p --model haiku --effort low --setting-sources project,local --settings "$R/claude/overseer-settings.json" --output-format json \
      "Use the Bash tool to run exactly this command, then report the tool result verbatim: $3" 2>/dev/null ) > "$E/perm-$1.json"
  python3 "$E/denials.py" < "$E/perm-$1.json" > "$E/perm-$1.txt"
  print -r -- "--- permission probe $1: $3"; cat "$E/perm-$1.txt"
}
permprobe 1 'out1.txt' "git -C $RP log -1 --output=$E/out1.txt"
permprobe 2 'out2.txt' "git -C $RP log -1 > $E/out2.txt"
permprobe 3 'idea' "tmux-ctl idea probe"
permprobe 4 '_append' "tmux-ctl _append $E/append-probe.txt '{}'"
permprobe 5 'overview' "tmux-ctl overview"
permprobe 6 'help' "tmux-ctl help"
# C1: the three probes that got through the old `git -C * …` allows; each must be refused and create nothing
permprobe 7 'fsm.txt' "git -C $RP -c core.fsmonitor='touch $E/fsm.txt; true' status ."
permprobe 8 'alias.txt' "git -C $RP -c alias.x='!touch $E/alias.txt' x log status"
permprobe 9 'tag show' "git -C $RP tag show HEAD"
check "probe 1 (git log --output) was denied by the permission rules" grep -q '^DENIED Bash .*--output=' "$E/perm-1.txt"
check "probe 2 (git log > file) was denied by the permission rules" grep -q '^DENIED Bash .*out2.txt' "$E/perm-2.txt"
check "probe 3 (tmux-ctl idea) was denied by the permission rules" grep -q '^DENIED Bash tmux-ctl idea' "$E/perm-3.txt"
check "probe 4 (tmux-ctl _append) was denied by the permission rules" grep -q '^DENIED Bash tmux-ctl _append' "$E/perm-4.txt"
check "probe 5 (bare tmux-ctl overview) was not denied: the overseer's own allow matches it" sh -c "! grep -q '^DENIED' '$E/perm-5.txt' && grep -q '^RESULT' '$E/perm-5.txt' && ! grep -qi 'unknown command' '$E/perm-5.txt' && grep -q 'p1' '$E/perm-5.txt'"
check "probe 6 (tmux-ctl help: allowed only by the user's Bash(tmux-ctl:*), which the excluded source would carry) was denied by the dontAsk catch-all" grep -q '^DENIED Bash tmux-ctl help' "$E/perm-6.txt"
check "probe 7 (git -c core.fsmonitor) was denied by the permission rules" grep -q '^DENIED Bash git -C .*fsmonitor' "$E/perm-7.txt"
check "probe 8 (git -c alias) was denied by the permission rules" grep -q '^DENIED Bash git -C .*alias.x' "$E/perm-8.txt"
check "probe 9 (git tag show) was denied by the permission rules" grep -q '^DENIED Bash git -C .*tag show' "$E/perm-9.txt"
check "fsm.txt was not created" test ! -e "$E/fsm.txt"
check "alias.txt was not created" test ! -e "$E/alias.txt"
check "no tag named show was created in the scratch repo" test -z "$(git -C "$RP" tag -l show)"
check "append-probe.txt was not created" test ! -e "$E/append-probe.txt"
check "out1.txt was not written" test ! -e "$E/out1.txt"
check "out2.txt was not written" test ! -e "$E/out2.txt"
check "the scratch ideas folder holds the same files and contents" test "$(ideas_sig)" = "$IDEAS_BEFORE"
print -r -- "--- probe results: out1.txt exists: $([[ -e $E/out1.txt ]] && print yes || print no); out2.txt exists: $([[ -e $E/out2.txt ]] && print yes || print no); ideas files: $(ls "$E/ideas" | tr '\n' ' ')"
# 5d. totals over the whole session
cnt="$(python3 "$E/tx.py" counts "$tr")"; print -r -- "--- transcript counts: $cnt   (grep -c: tool_use lines $(grep -c '"type":"tool_use"' "$tr"), write-tool lines $(grep -c '"name":"\(Write\|Edit\|MultiEdit\|NotebookEdit\|Agent\|SendMessage\)"' "$tr"))"
tools="${${cnt#tool_use=}%% *}"; writes="${cnt##*write_tools=}"
check "overseer made tool calls ($tools) and no write tool calls ($writes)" test "$tools" -ge 1 -a "$writes" = 0
print -r -- "--- plugins and hooks seen by the overseer's session (report only):"; python3 "$E/tx.py" plugins "$tr"
# 6. read-only checks against real state (the live board and tmux server, the real usage index)
print -r -- "--- real state: python3 -I board/overview.py (read-only)"; real() { env -u TMUX -u TMUX_PANE -u TMUX_DASH_TMUX_ARGS -u AGENT_BOARD_TMUX_SOCKET -u TC_STATE -u TC_LINEAGE -u TC_IDEAS_DIR -u XDG_STATE_HOME -u TC_SESSION "$@" }   # the scratch environment must not leak into the read-only real-state checks
real python3 -I "$R/board/overview.py" | cut -c1-160
print -r -- "--- real usage.sqlite: today's spend of ~/agent-board (no data written)"
real python3 - "$R" <<'PY'
import sys, time; sys.path.insert(0, sys.argv[1] + "/board"); import usage
conn = usage.connect(usage.db_path()); print(usage.spend_since(conn, str(__import__("pathlib").Path.home() / "agent-board"), usage._midnight(time.time(), 0), usage.load_prices())); conn.close()
PY
# 7. teardown by pid and socket, then the leak check
kill "$(cat "$E/server.pid")"; sleep 1
tt_teardown; sleep 2
check "no overseer claude left after the scratch server died" tt_wait 30 sh -c "[ \"\$(pgrep -f 'claude/overseer-settings.json' | wc -l | tr -d ' ')\" = 0 ]"
check "real state untouched: no e2e token in the real board state" test ! -e "$HOME/.local/state/tmux-dash/e2e"
check "no overseer session on the user's own tmux server" sh -c "! env -u TMUX $TT_BIN has-session -t '=overseer' 2>/dev/null"
trap - EXIT INT TERM
if (( TT_FAILS == 0 )); then print "E2E PASS"; else print "$TT_FAILS FAILED"; exit 1; fi
