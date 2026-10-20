#!/usr/bin/env bash
# PreToolUse(Bash): refuse pkill/killall whose pattern matches a running Claude Code process.
# A broad `pkill -f` once killed the dev orchestrator and its whole team. Fail-open on any error.
# dedupe: the scoped registration (--scoped) covers agent-board sessions; the legacy global one defers to it
[[ "$1" == --scoped || "$AGENT_BOARD" != 1 ]] || exit 0
input=$(cat) || exit 0
exec python3 -I - "$input" <<'PY'
import json, os, re, shlex, subprocess, sys
try:
    d = json.loads(sys.argv[1])
    if d.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (d.get("tool_input") or {}).get("command") or ""
except Exception:
    sys.exit(0)
if not re.search(r"\b(pkill|killall)\b", cmd):
    sys.exit(0)

def is_claude(pid, comm):
    exe = comm
    try:  # Linux ps prints comm as the bare name, not the path; /proc/<pid>/exe has the path
        exe = os.readlink("/proc/%d/exe" % pid)
    except OSError:
        pass
    return "/claude/versions/" in exe or os.path.basename(exe) == "claude"

def matches(tool, args):
    full = tool == "pkill" and any(a.startswith("-") and "f" in a[1:] and not a.startswith("--") for a in args)
    pats = [a for a in args if not a.startswith("-")]
    if not pats: return []
    pat = pats[-1]
    hits = []
    me = os.getpid()
    def ps(col):  # comm= is truncated to 16 chars unless it is the last column, so one call per column
        out = subprocess.run(["ps", "-axww", "-o", "pid=," + col + "="], capture_output=True, text=True).stdout
        return {int(m[1]): m[2] for m in (re.match(r"\s*(\d+)\s+(.*)", l) for l in out.splitlines()) if m}
    comms, argvs = ps("comm"), ps("args")
    for pid, comm in comms.items():
        argv = argvs.get(pid, "")
        if pid == me or not is_claude(pid, comm): continue
        hay = argv if full else os.path.basename(comm)
        try:
            ok = re.search(pat, hay) if tool == "pkill" else os.path.basename(comm) == pat
        except re.error:
            ok = pat in hay
        if ok: hits.append(pid)
    return hits

TOOLS = ("pkill", "killall")
PUNCT = set("();&|<>")

def tokens(text):
    lx = shlex.shlex(text, posix=True, punctuation_chars=True)
    lx.whitespace_split = True
    return list(lx)

def scan(text, depth=0):
    """Return (tool, args) for each pkill/killall occurrence anywhere in text, incl. nested -c strings."""
    found = []
    try:
        toks = tokens(text)
    except ValueError:  # unbalanced quotes etc: regex over the raw text instead of skipping
        for m in re.finditer(r"\b(pkill|killall)\b([^;&|()\n]*)", text):
            found.append((m[1], [a.strip("'\"") for a in m[2].split()]))
        return found
    for i, t in enumerate(toks):
        if os.path.basename(t) in TOOLS:
            args = []
            for a in toks[i + 1:]:
                if a and set(a) <= PUNCT: break
                args.append(a)
            found.append((os.path.basename(t), args))
        elif depth < 3 and re.search(r"\b(pkill|killall)\b", t) and len(t.split()) > 1:
            found += scan(t, depth + 1)  # e.g. bash -c "pkill ..."
    return found

try:
    for tool, args in scan(cmd):
        hits = matches(tool, args)
        if hits:
            sys.stderr.write(
                f"BLOCKED: `{tool} {' '.join(args)}` would also kill Claude Code process(es) {hits} "
                "(the lead, a teammate, or you). Patterns match full command lines, which include "
                "session names and prompts. kill by PID instead: the PID you started ($!), "
                "or `pgrep -P <your shell pid>` / `pgrep -f <pattern>` checked by hand first.\n")
            sys.exit(2)
except SystemExit:
    raise
except Exception:
    sys.exit(0)
sys.exit(0)
PY
