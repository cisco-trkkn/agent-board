# test_plugin.zsh — the session-only agent-board plugin in claude/plugin/.
# Probe: a temp copy of the repo's bin/_ab_claude.zsh + claude/ gets one extra UserPromptSubmit hook that
# touches $AB_PROBE_MARKER. The real hooks never write markers. Nothing is written to ~/.claude or this repo.
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"; P="$R/claude/plugin"
tt_setup claude
export AB_PROBE_MARKER=

# 1. manifests load (plugin validate when available)
manifests() {
  if command -v claude >/dev/null 2>&1 && claude plugin validate --help >/dev/null 2>&1; then
    claude plugin validate "$P" >/dev/null 2>&1
  else
    python3 -c 'import json,sys; [json.load(open(f)) for f in sys.argv[1:]]' "$P/.claude-plugin/plugin.json" "$P/hooks/hooks.json"
  fi
}
check "plugin manifests valid" manifests
check "plugin.json name is agent-board" test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$P/.claude-plugin/plugin.json" 2>/dev/null)" = agent-board
check "hooks.json uses CLAUDE_PLUGIN_ROOT/scripts for all four hooks" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]
cmds = [h["command"] for v in d.values() for e in v for h in e["hooks"]]
want = {n: 0 for n in ("kill-guard", "bash-mirror", "artifact-register", "worktree-sweep")}
for c in cmds:
    assert c.startswith('"${CLAUDE_PLUGIN_ROOT}/scripts/') and c.endswith('.sh" --scoped'), c
    for n in want:
        if "/" + n + ".sh" in c: want[n] += 1
assert all(want.values()), want
PY
check "settings.json no longer registers hooks (no double run)" python3 -c 'import json,sys; assert "hooks" not in json.load(open(sys.argv[1]))' "$R/claude/session-settings.json"
check "legacy hook paths are symlinks into the plugin" zsh -c 'cd "$1/claude/hooks" && for n in kill-guard bash-mirror artifact-register worktree-sweep; do [[ -L $n.sh && $(readlink $n.sh) == ../plugin/scripts/$n.sh && -x $n.sh ]] || exit 1; done' _ "$R"
check "superpowers-hook.sh stays in claude/hooks (regular file)" test -f "$R/claude/hooks/superpowers-hook.sh" -a ! -L "$R/claude/hooks/superpowers-hook.sh"
check "plugin ships skills and agents" zsh -c 'cd "$1" && for f in skills/tmux-orchestrator/SKILL.md skills/handoff/SKILL.md skills/handoff/agents/openai.yaml agents/effort-low.md agents/effort-medium.md agents/effort-high.md; do [[ -s $f ]] || exit 1; done' _ "$P"

# the per-session file must not share a name with main's tracked mirror of the user's global settings (claude/settings.json):
# the launcher loads session-settings.json and never the mirror
check "session settings file is session-settings.json; claude/settings.json (the global mirror) is not used" zsh -c 'source "$1/bin/_ab_claude.zsh"; [[ -f $1/claude/session-settings.json && "$(ab_claude_args)" == *"--settings ${(q)AB_REPO}/claude/session-settings.json "* && "$(ab_claude_args)" != *claude/settings.json* ]]' _ "$R"

# 2. no absolute home paths
# (claude/settings.json and claude/staged/ are the author's own global config mirror, not shipped to agent-board sessions)
check "no /Users/ under claude/" test -z "$(grep -rn '/Users/' "$R/claude/" --exclude=settings.json --exclude-dir=staged --exclude-dir=__pycache__ 2>/dev/null)"
check "ab_claude_args loads the plugin" zsh -c 'source "$1/bin/_ab_claude.zsh"; [[ "$(ab_claude_args)" == *"--plugin-dir ${(q)AB_REPO}/claude/plugin"* ]]' _ "$R"

# the agent-facing rules name the ideas path board/ideas.py writes, not the old ~/.claude one
check "lead and handoff rules name ~/.local/state/agent-board/ideas" test "$(grep -lF '~/.local/state/agent-board/ideas/<project>.md' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | wc -l)" -eq 2
check "no rule or doc outside docs/superpowers history points at ~/.claude/ideas as THE path" test -z "$(grep -rn '~/.claude/ideas' "$R/claude" "$R/CLAUDE.md" "$R/README.md" "$R/docs/INSTALL.md" "$R/docs/CUSTOMIZATION.md" 2>/dev/null | grep -v 'older\|old ')"

# 3. headless probe
if ! command -v claude >/dev/null 2>&1; then
  print -r -- "skip - no claude (headless probe)"
else
  mkprobe() {   # mkprobe <dest>: a repo copy whose plugin has the probe hook
    mkdir -p "$1/bin" && cp "$R/bin/_ab_claude.zsh" "$1/bin/" && cp -R "$R/claude" "$1/claude" || return 1
    python3 - "$1/claude/plugin/hooks/hooks.json" <<'PY'
import json, sys
f = sys.argv[1]; d = json.load(open(f))
d["hooks"]["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": "touch \"$AB_PROBE_MARKER\"", "timeout": 5}]}]
json.dump(d, open(f, "w"))
PY
  }
  work="$TT_DIR/work"; mkdir -p "$work" && git -C "$work" init -q
  runclaude() {   # runclaude <marker> <extra args...>
    local m="$1"; shift; rm -f "$m"
    ( cd "$work" && AB_PROBE_MARKER="$m" claude -p --model haiku "$@" "Reply with the single word ok." </dev/null >/dev/null 2>&1 )
  }
  mkprobe "$TT_DIR/repoA" || fail "probe: build copy"
  ( source "$TT_DIR/repoA/bin/_ab_claude.zsh"; print -r -- "$(ab_claude_args)" ) > "$TT_DIR/argsA"
  runclaude "$TT_DIR/mA" ${(Q)${(z)"$(<$TT_DIR/argsA)"}}
  check "probe: hook fires with ab_claude_args" test -e "$TT_DIR/mA"
  runclaude "$TT_DIR/mP"
  check "probe: plain claude -p does not fire it" test ! -e "$TT_DIR/mP"
  mv "$TT_DIR/repoA" "$TT_DIR/moved dir"
  ( source "$TT_DIR/moved dir/bin/_ab_claude.zsh"; print -r -- "$(ab_claude_args)" ) > "$TT_DIR/argsB"
  runclaude "$TT_DIR/mB" ${(Q)${(z)"$(<$TT_DIR/argsB)"}}
  check "probe: plugin copied elsewhere still fires (no .. paths)" test -e "$TT_DIR/mB"
fi

# 4. every skill/agent named in the lead and worker rules is shipped, superpowers, or marked "If installed"
check "orchestrator.md / worker.md skill names resolve" python3 - "$R" <<'PY'
import os, re, sys
r = sys.argv[1]; p = os.path.join(r, "claude/plugin")
bad = []
for f in ("orchestrator.md", "worker.md"):
    for n, line in enumerate(open(os.path.join(r, "claude", f)), 1):
        for ns, name in re.findall(r"`([a-z][a-z-]*):([a-z][a-z-]*)`", line):
            if ns == "superpowers-extended-cc": continue
            if ns == "agent-board" and os.path.exists(os.path.join(p, "skills", name, "SKILL.md")): continue
            if "If installed" in line: continue
            bad.append((f, n, ns + ":" + name))
        for name in ("task-observer", "gitlab-ci-loop", "subagent-driven-development-extras"):
            if "`" + name in line and "If installed" not in line and not re.search(r"(?i)(do not|don't) invoke", line): bad.append((f, n, name))
        if re.search(r"tmux-orchestrator|`/?handoff`", line) and "agent-board:" not in line:
            bad.append((f, n, "unprefixed plugin skill"))
        for name in re.findall(r"effort-(?:low|medium|high)", line):
            if not os.path.exists(os.path.join(p, "agents", name + ".md")): bad.append((f, n, name))
for b in bad: print("unresolved:", *b)
sys.exit(1 if bad else 0)
PY
tt_done
