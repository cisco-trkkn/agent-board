#!/usr/bin/env python3
"""taskwin_ui: key handling for the tasks window (board/taskwin.py watch). Pure: no I/O.

ui = {"view": "queue"|"plan"|"history", "cursor": {view: int}, "filter": "all"|"hide_done"|"active",
      "collapsed": {row key: bool}, "help": bool}
model = taskwin_views.model(...): {"rows": {view: [row key]}, "toggle": {view: {row key: collapse key | OPEN_PLAN}},
         "finished": {view: [collapse key]}}
decode(text) -> [key]; handle_key(ui, key, model) -> new ui (the argument is not changed).
"""
import copy

VIEWS = ("queue", "plan", "history")
FILTERS = ("all", "hide_done", "active")
QUEUE_PREFIX = "Plan & run: "
OPEN_PLAN = "@plan"                      # toggle target of the running queue row: Enter switches to the plan view
_ARROWS = {"A": "up", "B": "down"}


def decode(text):
    """Keys from one read of the terminal: ESC [ A/B -> up/down, any other ESC sequence and a lone ESC dropped,
    Tab -> "tab", CR/LF -> "enter", every other character as itself."""
    keys, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\x1b":
            if text[i + 1:i + 2] in ("[", "O"):
                j = i + 2
                while j < len(text) and not ("@" <= text[j] <= "~"):
                    j += 1                   # parameter bytes up to the final byte
                if j < len(text) and text[j] in _ARROWS and j == i + 2:
                    keys.append(_ARROWS[text[j]])
                i = j + 1
            else:
                i += 1
            continue
        keys.append("tab" if c == "\t" else "enter" if c in "\r\n" else c)
        i += 1
    return keys


def is_collapsed(ui, key):
    """History rows start collapsed; every other row starts expanded."""
    v = (ui.get("collapsed") or {}).get(key)
    return v if isinstance(v, bool) else key.startswith("h:")


def default_ui(tasks):
    queue = any(str(t.get("subject", "")).startswith(QUEUE_PREFIX) for t in tasks or [])
    return {"view": "queue" if queue else "plan", "cursor": {v: 0 for v in VIEWS}, "filter": "all",
            "collapsed": {}, "help": False}


def normalize(ui, tasks):
    """A copy of `ui` with every missing or invalid field taken from default_ui(tasks)."""
    d = default_ui(tasks)
    if not isinstance(ui, dict):
        return d
    out = copy.deepcopy(ui)
    if out.get("view") not in VIEWS:
        out["view"] = d["view"]
    if out.get("filter") not in FILTERS:
        out["filter"] = "all"
    cur = out.get("cursor") if isinstance(out.get("cursor"), dict) else {}
    out["cursor"] = {v: cur[v] if isinstance(cur.get(v), int) and cur[v] >= 0 else 0 for v in VIEWS}
    col = out.get("collapsed") if isinstance(out.get("collapsed"), dict) else {}
    out["collapsed"] = {str(k): v for k, v in col.items() if isinstance(v, bool)}
    out["help"] = out.get("help") is True
    return out


def clamp(ui, model):
    """Each view's cursor within its rows (0 when it has none)."""
    for v in VIEWS:
        n = len(((model or {}).get("rows") or {}).get(v) or [])
        ui["cursor"][v] = max(0, min(ui["cursor"].get(v, 0), n - 1))
    return ui


def handle_key(ui, key, model):
    ui = normalize(ui, [])
    v = ui["view"]
    rows = ((model or {}).get("rows") or {}).get(v) or []
    cur = ui["cursor"][v]
    if key == "tab":
        ui["view"] = VIEWS[(VIEWS.index(v) + 1) % len(VIEWS)]
    elif key in ("1", "2", "3"):
        ui["view"] = VIEWS[int(key) - 1]
    elif key == "q":
        ui["view"] = "queue"
    elif key in ("j", "down"):
        ui["cursor"][v] = cur + 1
    elif key in ("k", "up"):
        ui["cursor"][v] = cur - 1
    elif key == "enter" and rows:
        target = (((model or {}).get("toggle") or {}).get(v) or {}).get(rows[min(cur, len(rows) - 1)])
        if target == OPEN_PLAN:
            ui["view"] = "plan"
        elif target:
            ui["collapsed"][target] = not is_collapsed(ui, target)
    elif key == "f":
        ui["filter"] = FILTERS[(FILTERS.index(ui["filter"]) + 1) % len(FILTERS)]
    elif key == "c":
        keys = ((model or {}).get("finished") or {}).get(v) or []
        if keys:
            fold = not all(is_collapsed(ui, k) for k in keys)
            for k in keys:
                ui["collapsed"][k] = fold
    elif key == "?":
        ui["help"] = not ui["help"]
    return clamp(ui, model)
