"""scout_pack: the weekly context pack (spec §3 step 1), at most 30 KB, plus the spec state rule."""
import json
import os
import re
import subprocess
from pathlib import Path

import context
import ideas

PROJECT = "agent-board"
CAP = 30720
SPECS_KEEP, IDEAS_KEEP, CONTEXT_KEEP = 60, 40, 12 * 1024
NONE = "(none)"
SPEC_DIR = "docs/superpowers/specs"
STATUS_RE = re.compile(r"^Status:(.*)$", re.I | re.M)


def _slug(name):
    s = re.sub(r"\.md$", "", name)
    s = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", s)
    return re.sub(r"-design$", "", s)


def _specs(root):
    d = Path(root) / SPEC_DIR
    return sorted(d.glob("*.md")) if d.is_dir() else []


def _read(p):
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return ""


def spec_states(root):
    """{spec path relative to root: "merged" | "superseded" | "queued"}; one git log for all specs."""
    root = Path(root)
    try:
        r = subprocess.run(["git", "-C", str(root), "log", "main", "--format=%s"], capture_output=True, text=True, timeout=30)
        subjects = set(r.stdout.splitlines()) if r.returncode == 0 else set()
    except (OSError, subprocess.SubprocessError):
        subjects = set()
    led = root / "docs/superpowers/ledgers"
    ledgers = [p.name for p in led.iterdir() if p.is_dir()] if led.is_dir() else []
    out = {}
    for p in _specs(root):
        base = p.name[:-3]
        status = " ".join(m.lower() for m in STATUS_RE.findall(_read(p)))
        if "superseded" in status:
            state = "superseded"
        elif (f"docs(metrics): {base}" in subjects or any(_slug(p.name) in n for n in ledgers)
              or re.search(r"merged|done|implemented", status)):
            state = "merged"
        else:
            state = "queued"
        out[str(p.relative_to(root))] = state
    return out


def _title(p):
    for line in _read(p).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return p.stem


def _layout(root):
    text = _read(Path(root) / "README.md")
    m = re.search(r"^## Layout[ \t]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    body = m.group(1).strip() if m else ""
    return body or NONE


def _claude_version():
    try:
        r = subprocess.run([os.environ.get("TC_SCOUT_CLAUDE") or "claude", "--version"], capture_output=True, text=True, timeout=20)
        line = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        line = ""
    return line or "claude: unknown"


def _plugins():
    try:
        data = json.loads(_read(Path.home() / ".claude/plugins/installed_plugins.json"))
        rows = []
        for name, vs in sorted(data.get("plugins", {}).items()):
            ver = (vs[0].get("version") if vs and isinstance(vs[0], dict) else None) or "?"
            rows.append(f"{name} {ver}")
        return rows
    except (ValueError, AttributeError):
        return []


def _features(root):
    root = Path(root)
    lines = []
    try:
        hooks = sorted(json.loads(_read(root / "claude/plugin/hooks/hooks.json"))["hooks"])
    except (ValueError, KeyError, TypeError):
        hooks = []
    lines.append("hook events: " + (", ".join(hooks) if hooks else NONE))
    mods = root / "claude/plugin/mods"
    names = sorted(p.name for p in mods.glob("*.js")) if mods.is_dir() else []
    lines.append("mods: " + (", ".join(names) if names else NONE))
    try:
        keys = list(json.loads(_read(root / "claude/session-settings.json")))
    except (ValueError, TypeError):
        keys = []
    lines.append("session-settings keys: " + (", ".join(keys) if keys else NONE))
    return "\n".join(f"- {l}" for l in lines)


def _cut_lines(text, limit):
    if len(text.encode()) <= limit:
        return text
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        n += len(line.encode())
        if n > limit:
            break
        out.append(line)
    return "".join(out)


def _render(shared, layout, spec_lines, idea_lines, versions, features):
    def sec(h, body):
        return f"## {h}\n{body.rstrip() or NONE}\n"
    return "\n".join([sec("Shared context", shared), sec("Layout", layout), sec("Specs", "\n".join(spec_lines)),
                      sec("Open ideas", "\n".join(idea_lines)), sec("Versions", versions),
                      sec("Claude Code features in use", features)])


def build(root, now=None):
    root = Path(root)
    try:
        shared = _read(context.context_path(PROJECT)).strip()
    except ValueError:
        shared = ""
    states = spec_states(root)
    spec_lines = [f"{rel} — {_title(root / rel)} — {st}" for rel, st in sorted(states.items(), reverse=True)]
    try:
        idea_lines = [f"- {i['text']}" for i in ideas.load(PROJECT) if i["status"] == "open"]
    except OSError:
        idea_lines = []
    plugins = _plugins()
    versions = f"- {_claude_version()}\n" + "\n".join(f"- {p}" for p in plugins) if plugins else f"- {_claude_version()}\n- plugins: {NONE}"
    layout, features = _layout(root), _features(root)

    def more(lines, n):
        return lines[:n] + ([f"(… {len(lines) - n} more not shown)"] if n < len(lines) else [])

    def make(ns, ni, nc, nl=None):
        sh = _cut_lines(shared, nc) if shared else ""
        if shared and sh != shared:
            sh = sh.rstrip("\n") + "\n(cut)"
        lay = layout
        if nl is not None and nl < len(layout.splitlines()):
            lay = "\n".join(layout.splitlines()[:nl] + ["(cut)"])
        return _render(sh, lay, more(spec_lines, ns), more(idea_lines, ni), versions, features)

    def fits(pack):
        return len(pack.encode()) <= CAP

    full_c = len(shared.encode()) + 1
    for args in ((len(spec_lines), len(idea_lines), full_c),
                 (SPECS_KEEP, len(idea_lines), full_c),
                 (SPECS_KEEP, IDEAS_KEEP, full_c),
                 (SPECS_KEEP, IDEAS_KEEP, CONTEXT_KEEP)):
        pack = make(*args)
        if fits(pack):
            return pack
    # Hard cut: Layout, Versions and Features stay; shrink ideas, then specs, then context.
    ns, ni, nc = min(SPECS_KEEP, len(spec_lines)), min(IDEAS_KEEP, len(idea_lines)), CONTEXT_KEEP
    while ni > 0:
        ni -= 1
        if fits(make(ns, ni, nc)):
            return make(ns, ni, nc)
    while ns > 0:
        ns -= 1
        if fits(make(ns, ni, nc)):
            return make(ns, ni, nc)
    while nc > 0:
        nc = max(0, nc - 1024)
        if fits(make(ns, ni, nc)):
            return make(ns, ni, nc)
    nl = len(layout.splitlines())
    while nl > 0:
        nl -= 1
        if fits(make(ns, ni, nc, nl)):
            break
    return make(ns, ni, nc, nl)
