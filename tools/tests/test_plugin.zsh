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
check "hooks.json registers the one entry module, which registers agent-status, team-band and usage-gauges" python3 - "$P/hooks/hooks.json" "$P" <<'PY'
import json, os, sys
d = json.load(open(sys.argv[1]))
assert d["modules"] == ["../mods/index.js"], d.get("modules")
mods = os.path.join(os.path.dirname(sys.argv[1]), "..", "mods")
for m in ("index.js", "agent-status.js", "team-band.js", "usage-gauges.js"):
    assert os.path.isfile(os.path.join(mods, m)), m
idx = open(os.path.join(mods, "index.js")).read()
assert "./agent-status.js" in idx and "./team-band.js" in idx and "./usage-gauges.js" in idx
PY
check "plugin.json description names agent-status" zsh -c 'python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"description\"])" "$1" | grep -qF agent-status' _ "$P/.claude-plugin/plugin.json"
check "plugin.json description names team-band" zsh -c 'python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"description\"])" "$1" | grep -qF team-band' _ "$P/.claude-plugin/plugin.json"
check "plugin.json description names usage-gauges" zsh -c 'python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"description\"])" "$1" | grep -qF usage-gauges' _ "$P/.claude-plugin/plugin.json"
check "hooks.json registers sdd-call-guard on PreToolUse Agent, --scoped, timeout 10" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PreToolUse"]
hit = [(e["matcher"], h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/sdd-call-guard.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] == "Agent" and hit[0][1]["timeout"] == 10, hit
PY
check "hooks.json registers context-inject on SessionStart (no matcher: every source), --scoped, timeout 5" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["SessionStart"]
hit = [(e.get("matcher"), h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/context-inject.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] is None and hit[0][1]["timeout"] == 5, hit
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

# the agent-facing rules name the ideas path board/ideas.py writes (TC_IDEAS_DIR first), not the old ~/.claude one
check "lead and handoff rules name \${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}" test "$(grep -lF '${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | wc -l)" -eq 2
check "no rule names the ideas dir without TC_IDEAS_DIR" test -z "$(grep -n '~/.local/state/agent-board/ideas' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | grep -vF '${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}')"
# the shared context file (spec 2026-10-28-shared-project-context): the teammate rule, the lead's merge duty and the handoff line
check "orchestrator.md names Context learned" grep -qF 'Context learned' "$R/claude/orchestrator.md"
check "worker.md names Context learned" grep -qF 'Context learned' "$R/claude/worker.md"
check "orchestrator.md tells the lead to merge with tmux-ctl context add" grep -qF 'tmux-ctl context add' "$R/claude/orchestrator.md"
check "lead and handoff rules name \${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}" test "$(grep -lF '${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md' "$R/claude/orchestrator.md" "$P/skills/handoff/SKILL.md" | wc -l)" -eq 2
check "no rule names the context dir without TC_CONTEXT_DIR" test -z "$(grep -n '~/.local/state/agent-board/context' "$R/claude/orchestrator.md" "$R/claude/worker.md" "$P/skills/handoff/SKILL.md" | grep -vF '${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}')"
check "handoff skill merges Context learned before relaying" grep -qF 'Context learned' "$P/skills/handoff/SKILL.md"
H="$P/skills/handoff/SKILL.md"
check "handoff skill is model-invocable (no disable-model-invocation)" zsh -c '! sed -n "1,/^---$/{/^---$/!p;}" "$1" | grep -q "^disable-model-invocation"' _ "$H"
check "handoff skill has a Teammate mode section with teammate <name>" zsh -c 'grep -q "^## Teammate mode" "$1" && grep -qF "teammate <name>" "$1"' _ "$H"
check "handoff self-started relay prints its line" grep -qF 'Handing off to a fresh orchestrator: <doc>' "$H"
check "handoff asks only when the user started it" grep -qF 'When the user started the handoff, never run the relay without a Yes from this question.' "$H"
check "lead rules: Handing off on your own, with teammate <name>" zsh -c 'awk "/^## Handing off on your own/{f=1;next} /^## /{f=0} f" "$1" | grep -qF "teammate <name>"' _ "$R/claude/orchestrator.md"
check "handoff Not yet sticks for the session" grep -qF 'A Not yet earlier in this session makes every later handoff user-started: ask.' "$H"
check "handoff skill is lead-only" grep -qF 'Lead only. A teammate or worker never runs this skill in either mode: tell the lead.' "$H"
check "lead rules: no self-started handoff after Not yet" zsh -c 'awk "/^## Handing off on your own/{f=1;next} /^## /{f=0} f" "$1" | grep -qF "answered Not yet"' _ "$R/claude/orchestrator.md"
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
O="$R/claude/orchestrator.md"
check "lead rules: Queue mode bullet" grep -qF -- '- **Queue mode.**' "$O"
check "lead rules: queue answers in metadata.queue" grep -qF 'metadata.queue' "$O"
check "lead rules: queue starts at two or more Plan & run tasks" grep -qF 'two or more pending `Plan & run:` tasks' "$O"
check "lead rules: morning report path" grep -qF 'docs/superpowers/reports/YYYY-MM-DD-queue.md' "$O"
check "lead rules: finishing row points at Queue mode" zsh -c 'grep "^| Finishing a branch" "$1" | grep -qF "Queue mode"' _ "$O"
check "lead rules: queue asks nothing after the batch" grep -qF 'asks the user nothing until the morning report' "$O"
check "handoff doc records Queue mode: on" grep -qF 'Queue mode: on' "$P/skills/handoff/SKILL.md"
check "lead rules: running plan's integration stored as metadata.queue.current" grep -qF 'metadata.queue.current' "$O"
check "handoff doc carries each queued spec's metadata.queue" grep -qF 'metadata.queue' "$P/skills/handoff/SKILL.md"
check "lead rules: Next steps round queues two or more picked groups" grep -qF 'queue each approved spec as a `Plan & run:` task' "$O"
check "lead rules: push/merge rule mentions Queue mode" zsh -c 'grep "^- Don.t push, merge" "$1" | grep -qF "Queue mode"' _ "$O"
check "lead rules: answeredAt read from the clock" grep -qF 'date -u +%Y-%m-%dT%H:%M:%SZ' "$O"
check "lead rules: ideas are marked when queued" grep -qF 'ideas are marked when queued' "$O"
check "lead rules: running plan is the first exceptions item" grep -qF '`Running plan: <title>`' "$O"
check "lead rules: metadata.queue.current shape names the plan" grep -qF 'metadata.queue.current = {"plan": "<plan path>"' "$O"
tt_done
