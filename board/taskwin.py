#!/usr/bin/env python3
"""taskwin: the tasks window renderer (the `tasks` window of a dev session).

render(view, timing, width, height, now, frame, color, session="") -> str
  view    planview.view() output: {"name", "active", "tasks": [{"id","subject","status","owner","state","tier","blockedBy"}]}
  timing  taskwin_state state ({} when unknown): {"tasks": {id: {"since","started",…}}, "events": [...]}
  color   "truecolor" | "256" | "none" (color_mode(env) picks one from NO_COLOR / COLORTERM)
Pure: no I/O, no clock, no tmux. Lines joined by "\\n", at most `height` of them, each at most `width` display cells.

Width ≥ 80: cards in columns by dependency depth, box-drawing connectors from blocker to dependent, the critical
path (longest unfinished chain) in the accent colour; when too tall, all-completed columns collapse to a one-line
`● first–last done` summary, and if it still does not fit the list layout is used. Width < 80: one line per task
with `⇠ 2,3` blocker hints. No ✗ anywhere.
"""
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir

HEADER_ROWS = 3
CARD_H, GAP, GUTTER = 4, 1, 4
CARD_MAX, CARD_MIN = 32, 16
GRAPH_MIN_WIDTH = 80
DONE_TTL, PLAN_DONE_TTL = 2.0, 5.0

SPIN = "◐◓◑◒"
GLYPH = {"completed": "●", "pending": "○", "blocked": "◌ 🔒"}
STATUS_STYLE = {"completed": "green", "in_progress": "amber", "pending": "grey", "blocked": "dim"}
TIER_STYLE = {"haiku": "cyan", "sonnet": "blue", "fable": "violet"}
TIER_MODEL = {"mechanical": "haiku", "standard": "sonnet", "frontier": "fable"}  # plan modelTier -> badge
STATE_WORD = {"waiting": "needs you", "ready": "idle", "gone": "gone"}
STATE_STYLE = {"working": "amber", "waiting": "red", "ready": "grey", "gone": "dim"}
IDLE_LINE = "No tasks yet — the lead's list shows up here"
CONFETTI = "✦✧∘⁘✺❋"
CONFETTI_STYLES = ("amber", "violet", "green", "cyan", "red", "blue")

# style name -> (truecolor params, 256-colour params); tuned to read on dark and light backgrounds
SGR = {
    "green": ("38;2;63;185;80", "38;5;71"),
    "amber": ("38;2;219;154;4", "38;5;178"),
    "red": ("38;2;229;83;75", "38;5;167"),
    "grey": ("38;2;139;148;158", "38;5;245"),
    "dim": ("2;38;2;139;148;158", "2;38;5;245"),
    "accent": ("1;38;2;197;112;236", "1;38;5;171"),
    "cyan": ("38;2;57;186;200", "38;5;44"),
    "blue": ("38;2;88;140;255", "38;5;75"),
    "violet": ("38;2;160;118;249", "38;5;141"),
    "bold": ("1", "1"),
    "inverse": ("7", "7"),
}

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------- text measuring

def cells(s):
    """Display cells of `s`: East Asian Wide/Fullwidth and emoji count 2, combining marks and selectors 0."""
    n = 0
    for ch in s:
        if unicodedata.combining(ch) or ch in ("​", "‌", "‍") or "︀" <= ch <= "️":
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def _cw(ch):
    if unicodedata.combining(ch) or ch in ("​", "‌", "‍") or "︀" <= ch <= "️":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def truncate(s, room):
    """`s` cut to `room` cells with a trailing `…` when something was cut."""
    if room <= 0:
        return ""
    if cells(s) <= room:
        return s
    out, used = [], 0
    for ch in s:
        w = _cw(ch)
        if used + w > room - 1:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def strip(s):
    """`s` without SGR escape sequences."""
    return _SGR_RE.sub("", s)


def fmt_dur(secs):
    secs = max(0, int(secs))
    if secs < 60:
        return "<1m"
    m, h, d = (secs // 60) % 60, (secs // 3600) % 24, secs // 86400
    if secs < 3600:
        return f"{m}m"
    if secs < 86400:
        return f"{h}h" + (f" {m}m" if m else "")
    return f"{d}d" + (f" {h}h" if h else "")


def color_mode(env):
    if "NO_COLOR" in env:
        return "none"
    if str(env.get("COLORTERM", "")).lower() in ("truecolor", "24bit"):
        return "truecolor"
    return "256"


# ---------------------------------------------------------------- canvas

class Canvas:
    """A width×height grid of (char, style); a wide char owns its cell and a "" placeholder to its right."""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.ch = [[" "] * width for _ in range(height)]
        self.st = [[()] * width for _ in range(height)]

    def put(self, x, y, text, style=()):
        """Write `text` at (x, y); returns the x after it. Clipped to the canvas."""
        if not (0 <= y < self.h):
            return x + cells(text)
        for c in text:
            w = _cw(c)
            if w == 0:
                continue  # combining marks and selectors are dropped: one cell, one char
            if x + w > self.w:
                break
            if x >= 0:
                self.ch[y][x], self.st[y][x] = c, tuple(style)
                if w == 2:
                    self.ch[y][x + 1], self.st[y][x + 1] = "", tuple(style)
            x += w
        return x

    def put_segs(self, x, y, segs, room, extra=()):
        """Write (text, style) segments at (x, y) within `room` cells, ending with `…` when cut."""
        total = sum(cells(t) for t, _ in segs)
        if total <= room:
            for t, s in segs:
                x = self.put(x, y, t, s + extra)
            return x
        used = 0
        for t, s in segs:
            for c in t:
                w = _cw(c)
                if used + w > room - 1:
                    return self.put(x, y, "…", s + extra)
                x = self.put(x, y, c, s + extra)
                used += w
        return x

    def get(self, x, y):
        return self.ch[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def lines(self, color):
        out = []
        for y in range(self.h):
            row, sty = self.ch[y], self.st[y]
            end = self.w
            while end > 0 and row[end - 1] in (" ", "") and not (row[end - 1] == "" and row[end - 2] != " "):
                end -= 1
            if color == "none":
                out.append("".join(row[:end]))
                continue
            parts, cur, seen = [], (), False
            for x in range(end):
                c = row[x]
                if c == "":
                    continue
                s = sty[x]
                if s != cur:
                    if cur:
                        parts.append("\x1b[0m")
                    if s:
                        parts.append("\x1b[" + _sgr(s, color) + "m")
                        seen = True
                    cur = s
                parts.append(c)
            if seen:
                parts.append("\x1b[0m")
            out.append("".join(parts))
        return out


def _sgr(style, color):
    i = 0 if color == "truecolor" else 1
    names = sorted(style, key=lambda n: n != "inverse")  # inverse first: \x1b[7;38;…m
    return ";".join(p for p in (SGR[n][i] for n in names) if p)


# ---------------------------------------------------------------- graph helpers

def _known_blockers(tasks):
    ids = {t["id"] for t in tasks}
    return {t["id"]: [b for b in t.get("blockedBy") or [] if b in ids and b != t["id"]] for t in tasks}


def _longest(ids, edges):
    """Longest chain ending at each id over `edges` (id -> blockers); a cycle's back edge counts 0."""
    memo = {}

    def go(i, stack):
        if i in memo:
            return memo[i]
        if i in stack:
            return 0
        stack.add(i)
        v = max((go(b, stack) + 1 for b in edges[i]), default=0)
        stack.discard(i)
        memo[i] = v
        return v

    for i in ids:
        go(i, set())
    return memo


def depths(tasks):
    """{id: depth}: the longest blockedBy chain to a root; unknown blocker ids ignored, cycles broken."""
    edges = _known_blockers(tasks)
    return _longest([t["id"] for t in tasks], edges)


def critical_path(tasks):
    """Ids of the longest chain of unfinished tasks, blocker first; [] when no chain has two tasks."""
    unfinished = [t["id"] for t in tasks if t["status"] != "completed"]
    us = set(unfinished)
    edges = {i: [b for b in bs if b in us] for i, bs in _known_blockers(tasks).items() if i in us}
    best = _longest(unfinished, edges)
    if not best:
        return []
    end = max(unfinished, key=lambda i: best[i])
    if best[end] < 1:
        return []
    path, cur, seen = [end], end, {end}
    while best[cur] > 0:
        nxt = next((b for b in edges[cur] if best[b] == best[cur] - 1 and b not in seen), None)
        if nxt is None:
            break
        path.append(nxt)
        seen.add(nxt)
        cur = nxt
    path.reverse()
    return path if len(path) >= 2 else []


# ---------------------------------------------------------------- pieces

def _badge(t):
    """(model name, style) for the task's tier: a modelTier name or a model name; None when there is no badge."""
    tier = TIER_MODEL.get(t.get("tier") or "", t.get("tier") or "")
    return (tier, (TIER_STYLE[tier],)) if tier in TIER_STYLE else None


def _status_glyph(t, frame):
    return SPIN[frame % 4] if t["status"] == "in_progress" else GLYPH.get(t["status"], "○")


def _owner_segs(t, frame):
    if not t.get("owner"):
        return []
    state = t.get("state") or ""
    style = (STATE_STYLE.get(state, "grey"),)
    star = "✦" if (state != "working" or frame % 2 == 0) else "✧"
    segs = [(f"{star} {t['owner']}", style)]
    if state in STATE_WORD:
        segs.append((" " + STATE_WORD[state], style))
    return segs


def _since(timing, t, now):
    k = ((timing or {}).get("tasks") or {}).get(t["id"]) or {}
    s = k.get("since")
    return fmt_dur(now - s) if isinstance(s, (int, float)) else ""


def _young(timing, kind, now, ttl):
    for e in (timing or {}).get("events") or []:
        if isinstance(e, dict) and e.get("kind") == kind and 0 <= now - (e.get("at") or 0) < ttl:
            return e
    return None


def _summary(tasks):
    return f"● {tasks[0]['id']}–{tasks[-1]['id']} done" if len(tasks) > 1 else f"● {tasks[0]['id']} done"


# ---------------------------------------------------------------- header

def _header(cv, view, tasks, timing, width, now, frame):
    name = view.get("name") or "Tasks"
    done, total = sum(t["status"] == "completed" for t in tasks), len(tasks)
    starts = [k.get("started") for k in ((timing or {}).get("tasks") or {}).values()
              if isinstance(k, dict) and isinstance(k.get("started"), (int, float))]
    elapsed = fmt_dur(now - min(starts)) if starts else "—"
    right = f"{done}/{total} done   elapsed {elapsed}"
    room = width - cells(right) - 2
    if room >= 6:
        cv.put(0, 0, truncate(name, room), ("bold",))
        cv.put(width - cells(right), 0, right, ("grey",))
    else:
        cv.put(0, 0, truncate(name, width), ("bold",))
    filled = round(width * done / total) if total else 0
    cv.put(0, 1, "━" * filled, ("green",))
    cv.put(filled, 1, "─" * (width - filled), ("grey",))
    plan_done = _young(timing, "plan_done", now, PLAN_DONE_TTL)
    done_ev = _young(timing, "done", now, DONE_TTL)
    if plan_done:
        _confetti(cv, 2, width, total, frame)
    elif done_ev:
        line = f"✦ Task {done_ev.get('id')} done ✦"
        cv.put(max(0, (width - cells(line)) // 2), 2, line, ("amber", "bold"))
    elif total and done == total:
        line = "Plan done ✓"
        cv.put(max(0, (width - cells(line)) // 2), 2, line, ("green", "bold"))
    return done_ev


def _confetti(cv, y, width, total, frame):
    text = f" ✺ Plan done ✺ all {total} tasks completed ✺ "
    x0 = max(0, (width - cells(text)) // 2)
    for x in range(width):
        if x0 <= x < x0 + cells(text):
            continue
        if (x * 7 + frame * 3) % 4 == 0:
            k = (x * 5 + frame) % len(CONFETTI)
            cv.put(x, y, CONFETTI[k], (CONFETTI_STYLES[(x + frame) % len(CONFETTI_STYLES)],))
    cv.put(x0, y, text, ("green", "bold"))


# ---------------------------------------------------------------- graph layout

def _plan_graph(tasks, width, avail):
    """Column layout: (cols, collapsed, card width) or None when the graph cannot fit."""
    dep = depths(tasks)
    ncol = max(dep.values(), default=0) + 1
    cw = min(CARD_MAX, (width - GUTTER * (ncol - 1)) // ncol)
    if cw < CARD_MIN:
        return None
    cols = [[] for _ in range(ncol)]
    for t in tasks:
        cols[dep[t["id"]]].append(t)
    collapsed = set()

    def need(c):
        return 1 if c in collapsed else len(cols[c]) * (CARD_H + GAP) - GAP

    while max(need(c) for c in range(ncol)) > avail:
        cands = [c for c in range(ncol) if c not in collapsed and cols[c]
                 and all(t["status"] == "completed" for t in cols[c])]
        if not cands:
            return None
        collapsed.add(max(cands, key=lambda c: (need(c), -c)))
    return cols, collapsed, cw


def _draw_card(cv, x, y, cw, t, timing, now, frame, accent, flash):
    border = ("accent",) if accent else ("grey",)
    extra = ("inverse",) if flash else ()
    inner = cw - 2
    st = t["status"]
    # top: ╭─ ◐ 3 ─────╮
    cv.put(x, y, "╭─ ", border + extra)
    xx = cv.put(x + 3, y, _status_glyph(t, frame), (STATUS_STYLE.get(st, "grey"),) + extra)
    xx = cv.put(xx, y, " " + t["id"] + " ", ("bold",) + extra)
    cv.put(xx, y, "─" * max(0, x + cw - 1 - xx), border + extra)
    cv.put(x + cw - 1, y, "╮", border + extra)
    # subject
    cv.put(x, y + 1, "│ ", border + extra)
    sub_style = ("grey",) if st == "completed" else ("dim",) if st == "blocked" else ()
    cv.put(x + 2, y + 1, truncate(t["subject"], inner - 2), sub_style + extra)
    cv.put(x + cw - 1, y + 1, "│", border + extra)
    # tier and owner
    cv.put(x, y + 2, "│ ", border + extra)
    segs = []
    badge = _badge(t)
    if badge:
        segs.append(badge)
    owner = _owner_segs(t, frame)
    if segs and owner:
        segs.append(("  ", ()))
        if sum(cells(t) for t, _ in segs + owner) > inner - 2:
            segs = []  # the owner's state matters more than the badge
    segs += owner
    cv.put_segs(x + 2, y + 2, segs, inner - 2, extra)
    cv.put(x + cw - 1, y + 2, "│", border + extra)
    # bottom: ╰──── 12m ─╯
    dur = _since(timing, t, now)
    tail = f" {dur} ─╯" if dur else "╯"
    cv.put(x, y + 3, "╰" + "─" * (cw - 1 - cells(tail)), border + extra)
    cv.put(x + cw - cells(tail), y + 3, tail, border + extra)
    if dur:
        cv.put(x + cw - cells(tail) + 1, y + 3, dur, ("grey",) + extra)
    # pad the inner rows so an inverse card is a solid block
    for yy in (y + 1, y + 2):
        for xx in range(x + 1, x + cw - 1):
            if cv.ch[yy][xx] == " " and not cv.st[yy][xx]:
                cv.st[yy][xx] = extra


_L, _R, _U, _D = 1, 2, 4, 8
_LINE = {3: "─", 12: "│", 10: "╭", 9: "╮", 6: "╰", 5: "╯", 11: "┬", 7: "┴", 14: "├", 13: "┤", 15: "┼",
         1: "─", 2: "─", 4: "│", 8: "│"}


def _segment(bits, a, b):
    (x1, y1), (x2, y2) = a, b
    if y1 == y2:
        lo, hi = sorted((x1, x2))
        for x in range(lo, hi + 1):
            v = (0 if x == lo else _L) | (0 if x == hi else _R)
            bits[(x, y1)] = bits.get((x, y1), 0) | v
    else:
        lo, hi = sorted((y1, y2))
        for y in range(lo, hi + 1):
            v = (0 if y == lo else _U) | (0 if y == hi else _D)
            bits[(x1, y)] = bits.get((x1, y), 0) | v


def _draw_edges(cv, cols, collapsed, cw, pos):
    """Connectors blocker → dependent through the gutters; spanning edges travel along a gap row."""
    bits = {}
    for c, col in enumerate(cols):
        if c in collapsed:
            continue
        for t in col:
            for b in t.get("blockedBy") or []:
                if b not in pos or pos[b][0] in collapsed or pos[b][0] >= c:
                    continue
                a, ra = pos[b]
                rb = pos[t["id"]][1]
                xs, ys = a * (cw + GUTTER) + cw - 1, ra * (CARD_H + GAP) + 1
                xd, yd = c * (cw + GUTTER), rb * (CARD_H + GAP) + 1
                bus_a, bus_b = xs + 2, xd - GUTTER + 1
                if c == a + 1:
                    pts = [(xs, ys), (bus_a, ys), (bus_a, yd), (xd, yd)]
                else:
                    top = rb * (CARD_H + GAP)
                    g = top - 1 if top > 0 else top + CARD_H
                    pts = [(xs, ys), (bus_a, ys), (bus_a, g), (bus_b, g), (bus_b, yd), (xd, yd)]
                for p, q in zip(pts, pts[1:]):
                    _segment(bits, p, q)
    for (x, y), v in bits.items():
        cur = cv.get(x, y)
        if cur is None:
            continue
        if cur == " ":
            cv.put(x, y, _LINE[v], ("grey",))
        elif cur == "│" and v & _R and not v & _L:
            cv.ch[y][x] = "├"
        elif cur == "│" and v & _L and not v & _R:
            cv.ch[y][x] = "┤"


def _graph_lines(tasks, timing, width, avail, now, frame, color, flash_id):
    plan = _plan_graph(tasks, width, avail)
    if plan is None:
        return None
    cols, collapsed, cw = plan
    rows = max(1 if c in collapsed else len(col) * (CARD_H + GAP) - GAP for c, col in enumerate(cols))
    pos = {t["id"]: (c, r) for c, col in enumerate(cols) for r, t in enumerate(col)}
    spans_top = any(pos[b][0] < c - 1 and pos[b][0] not in collapsed for c, col in enumerate(cols)
                    if c not in collapsed for t in col[:1] for b in t.get("blockedBy") or [] if b in pos)
    if spans_top and rows + 1 <= avail:
        rows += 1
    cv = Canvas(width, rows)
    crit = set(critical_path(tasks))
    for c, col in enumerate(cols):
        x = c * (cw + GUTTER)
        if c in collapsed:
            cv.put(x, 0, truncate(_summary(col), cw), ("green",))
            continue
        for r, t in enumerate(col):
            _draw_card(cv, x, r * (CARD_H + GAP), cw, t, timing, now, frame, t["id"] in crit, t["id"] == flash_id)
    _draw_edges(cv, cols, collapsed, cw, pos)
    return cv.lines(color)


# ---------------------------------------------------------------- list layout

def _list_line(cv, y, width, t, timing, now, frame, flash):
    extra = ("inverse",) if flash else ()
    st = t["status"]
    head = [(_status_glyph(t, frame), (STATUS_STYLE.get(st, "grey"),)), (" " + t["id"] + "  ", ("bold",))]
    # tail pieces in display order; `drop` is the order they go when the line is too narrow
    parts = {}
    badge = _badge(t)
    if badge:
        parts["tier"] = [badge]
    owner = _owner_segs(t, frame)
    if owner:
        parts["owner"] = owner
    dur = _since(timing, t, now)
    if dur:
        parts["time"] = [(dur, ("grey",))]
    if t.get("blockedBy"):
        parts["hint"] = [("⇠ " + ",".join(t["blockedBy"]), ("dim",) if st == "blocked" else ("grey",))]
    hw = sum(cells(s) for s, _ in head)

    def tail_of():
        segs = []
        for k in ("tier", "owner", "time", "hint"):
            if k in parts:
                segs.append(("  ", ()))
                segs.extend(parts[k])
        return segs

    tail = tail_of()
    for k in ("tier", "time", "owner", "hint"):
        if width - hw - sum(cells(s) for s, _ in tail) >= 8:
            break
        parts.pop(k, None)
        tail = tail_of()
    tw = sum(cells(s) for s, _ in tail)
    room = width - hw - tw
    sub_style = ("grey",) if st == "completed" else ("dim",) if st == "blocked" else ()
    x = cv.put_segs(0, y, head, width, extra)
    cv.put(x, y, truncate(t["subject"], room), sub_style + extra)
    cv.put_segs(width - tw, y, tail, tw, extra)  # right-aligned, so the hints line up at the edge


def _list_lines(tasks, timing, width, avail, now, frame, color, flash_id):
    rows = list(tasks)
    summary = None
    if len(rows) > avail:
        done = [t for t in tasks if t["status"] == "completed"]
        if done:
            summary = _summary(done)
            rows = [t for t in tasks if t["status"] != "completed"]
    n = min(avail, len(rows) + (1 if summary else 0))
    cv = Canvas(width, max(0, n))
    y = 0
    if summary and y < n:
        cv.put(0, y, truncate(summary, width), ("green",))
        y += 1
    for t in rows:
        if y >= n:
            break
        _list_line(cv, y, width, t, timing, now, frame, t["id"] == flash_id)
        y += 1
    return cv.lines(color)


# ---------------------------------------------------------------- idle

def _idle(view, width, height, color, session):
    cv = Canvas(width, max(1, min(height, max(6, height))))
    cv.put(0, 0, truncate(view.get("name") or "Tasks", width), ("bold",))
    y = max(2, height // 2 - 1)
    cv.put(max(0, (width - cells(IDLE_LINE)) // 2), y, truncate(IDLE_LINE, width), ())
    sub = f"watching session {session}" if session else "waiting for a session"
    cv.put(max(0, (width - cells(sub)) // 2), y + 1, truncate(sub, width), ("grey",))
    return _trim(cv.lines(color), height)


def _trim(lines, height):
    while lines and strip(lines[-1]) == "":
        lines.pop()
    return lines[:height]


# ---------------------------------------------------------------- entry point

def render(view, timing, width, height, now, frame, color, session=""):
    width, height = max(1, int(width)), max(1, int(height))
    tasks = list((view or {}).get("tasks") or [])
    if not tasks:
        return "\n".join(_idle(view or {}, width, height, color, session))
    cv = Canvas(width, HEADER_ROWS)
    done_ev = _header(cv, view, tasks, timing, width, now, frame)
    flash_id = str(done_ev.get("id")) if done_ev else None
    avail = max(0, height - HEADER_ROWS)
    body = None
    if width >= GRAPH_MIN_WIDTH:
        body = _graph_lines(tasks, timing, width, avail, now, frame, color, flash_id)
    if body is None:
        body = _list_lines(tasks, timing, width, avail, now, frame, color, flash_id)
    return "\n".join(_trim(cv.lines(color) + body, height))
