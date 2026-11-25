"""improve_class: the protected set and class derivation of the supervised improvement loop (spec §3, §6).
Test: tests/test_improve_class.py."""
import fnmatch
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROTECTED = REPO / "docs" / "superpowers" / "improve" / "protected.txt"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")
FILE_HEADERS = ("--- a/", "+++ b/", "--- /dev/null", "+++ /dev/null", "diff ", "index ")


def globs():
    return [g.strip() for g in PROTECTED.read_text().splitlines() if g.strip() and not g.startswith("#")]


def _match(target, glob):
    if glob.startswith("~/"):
        return fnmatch.fnmatchcase(os.path.expanduser(target), os.path.expanduser(glob))
    return fnmatch.fnmatchcase(target, glob)   # fnmatch's * already crosses "/", so ** works too


def _improve_range(src):
    lines = src.splitlines()
    try:
        lo = next(i for i, l in enumerate(lines, 1) if l.strip() == "improve)")
    except StopIteration:
        return None
    hi = next((i for i, l in enumerate(lines[lo - 1:], lo) if l.rstrip().endswith(";;")), len(lines))
    return lo, hi


def _hunks(patch):
    for line in (patch or "").splitlines():
        m = HUNK.match(line)
        if m:
            start, n = int(m.group(1)), int(m.group(2) or 1)
            yield start, start + max(n, 1) - 1


def is_protected(target, patch=None, tmux_ctl_src=None):
    for g in globs():
        if "#" in g:
            path_part, section = g.split("#", 1)
            if target != path_part or section != "improve":
                continue
            if patch is None:          # path-only check: the whole file is protected
                return True
            src = tmux_ctl_src if tmux_ctl_src is not None else (REPO / path_part).read_text()
            rng = _improve_range(src)
            if rng and any(a <= rng[1] and b >= rng[0] for a, b in _hunks(patch)):
                return True
        elif _match(target, g):
            return True
    return False


class _Target:
    """The target file at the patch's base: its leading frontmatter span and its fence state."""

    def __init__(self, text):
        lines = text.splitlines()
        self.k = 0                      # last line of a leading "---" block; 0 when there is none
        if lines and lines[0].strip() == "---":
            self.k = next((i for i in range(2, len(lines) + 1) if lines[i - 1].strip() == "---"), float("inf"))
        self.fences = []                # fences[n-1]: fence open before old line n
        state = False
        for line in lines:
            self.fences.append(state)
            if line.lstrip().startswith("```"):
                state = not state
        self.fences.append(state)

    def in_fence(self, n):
        return self.fences[min(n, len(self.fences)) - 1]


def prose_only(patch, target_text=None):
    """True when every changed line of the patch is prose (spec §3).

    With target_text, the fence state and the leading frontmatter span are read from the target file at each
    changed line's old-side position. Without it, only hunks that start at line 1 (or a new-file hunk, @@ -0,0)
    can be prose-only, and their fence and frontmatter state come from the patch's own lines.
    """
    if not patch:
        return False
    tgt = None if target_text is None else _Target(target_text)
    fence = front = first = leading = patch_mode = False
    cursor = 0                          # old-side line number of the next context or removed line
    for line in patch.splitlines():
        if line.startswith("@@"):
            m = HUNK.match(line)
            if not m:
                return False
            s = int(m.group(1))
            if tgt is None and s not in (0, 1):
                return False
            patch_mode = tgt is None or s == 0
            cursor = s
            first = True
            leading = s in (0, 1)
            front = fence = False
            continue
        if line.startswith(FILE_HEADERS):
            continue
        sign = line[:1]
        changed = sign in ("+", "-")    # "" (empty line) is context, not a change
        body = line[1:] if sign in ("+", "-", " ") else line
        at = cursor                     # old line of this line; for "+", the old line it goes before
        if sign != "+":
            cursor += 1
        if patch_mode:
            if first and leading and body.strip() == "---":
                front = True
                first = False
                if changed:
                    return False
                continue
            first = False
            if front:
                if body.strip() == "---":
                    front = False
                if changed:
                    return False
                continue
            if body.lstrip().startswith("```"):
                if changed:
                    return False
                fence = not fence
                continue
            if changed and (fence or body.startswith(("$ ", "    ", "`", "tmux-ctl "))):
                return False
        elif changed:
            if at <= tgt.k or tgt.in_fence(at):
                return False
            if body.lstrip().startswith(("```", "$ ", "    ", "`", "tmux-ctl ")):
                return False
    return True


def derive(kind, target, patch, source=None, tmux_ctl_src=None, target_text=None):
    if target and is_protected(target, patch, tmux_ctl_src):
        return "protected"
    if kind == "permission":
        return "protected"
    if kind == "memory":
        return "observation"
    if kind == "procedure" and prose_only(patch, target_text) and source not in ("dream", "observer"):
        return "low"
    return "high"
