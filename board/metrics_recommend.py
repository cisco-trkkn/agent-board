"""metrics recommend: ask `claude -p` for exactly three recommendations over stats.json alone, keep only the items whose
evidence matches stats.json.

Imports nothing from `metrics` (lookup comes from metrics_analyze). The claude binary is $TC_CLAUDE_BIN, else `claude`.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import metrics_analyze

PROMPT = Path(__file__).resolve().parent.parent / "claude" / "analytics.md"
TIMEOUT_S = 600
ASKED = 3
FIELDS = ("title", "change", "expected_effect", "evidence", "risk")
PROSE = ("title", "change", "expected_effect")   # numbers in these must be cited by the item's own evidence
# a number not part of a token (key path, model name, p90): nothing word-like, `.`, `|`, `,` or `-` before it or after it
NUMBER = re.compile(r"(?<![\w.|,\-])-?\d+(?:\.\d+)?%?(?![\w|])")
LIST_MARK = re.compile(r"^\s*\d+[.)]\s")
ARGV = ["-p", "--model", "sonnet", "--effort", "medium", "--tools", "Read", "--allowedTools", "Read", "--permission-mode",
        "dontAsk", "--no-session-persistence", "--strict-mcp-config", "--output-format", "json"]


class Unavailable(Exception):
    pass


def run_claude(stats_path):
    """The model's `result` text. Raises Unavailable(reason) on a timeout, a non-zero exit or an unreadable answer."""
    stats_path = Path(stats_path).resolve()
    prompt = PROMPT.read_text().rstrip("\n") + f"\n\nStats file: {stats_path}\n"
    try:
        p = subprocess.run([os.environ.get("TC_CLAUDE_BIN") or "claude", *ARGV], input=prompt, capture_output=True, text=True,
                           cwd=str(stats_path.parent), timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"timeout after {TIMEOUT_S} s")
    except OSError:
        raise Unavailable("claude not found")
    if p.returncode != 0:
        raise Unavailable(f"claude exited {p.returncode}")
    try:
        text = json.loads(p.stdout)["result"]
    except (ValueError, KeyError, TypeError):
        raise Unavailable("no JSON result")
    if not isinstance(text, str):
        raise Unavailable("no JSON result")
    return text


def _items_of(v):
    """A list of objects, or the `items` list of an object; None for anything else (so prose like `[1]` never wins)."""
    items = v if isinstance(v, list) else v.get("items") if isinstance(v, dict) else None
    return items if isinstance(items, list) and all(isinstance(i, dict) for i in items) else None


def parse_items(text):
    """The first fenced json block's list, else the first list of objects or {"items": [...]} in the text. An empty list
    counts only when nothing better is found."""
    dec = json.JSONDecoder()
    spans = []
    fence = text.find("```json")
    if fence >= 0:
        start = text.find("\n", fence) + 1
        end = text.find("```", start)
        if end > start:
            spans.append(text[start:end])
    spans.append(text)
    empty = None
    for s in spans:
        i = 0
        while i < len(s):
            if s[i] in "[{":
                try:
                    v, n = dec.raw_decode(s[i:])
                except ValueError:
                    i += 1
                    continue
                items = _items_of(v)
                if items:
                    return items
                if items is not None and empty is None:
                    empty = items
                i += n
            else:
                i += 1
    if empty is not None:
        return empty
    raise Unavailable("no JSON result")


def _decimals(v):
    if isinstance(v, int):
        return 0
    r = repr(v)
    if "e" in r or "E" in r:
        r = format(v, ".12f").rstrip("0")
    return len(r.split(".")[1]) if "." in r else 0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _matches(model, actual):
    """A number compares after rounding to the stats value's decimals; a string or bool compares exactly; null never matches."""
    if actual is None or isinstance(actual, (dict, list)):
        return False
    if _num(actual):
        return _num(model) and round(model, _decimals(actual)) == round(actual, _decimals(actual))
    return type(model) is type(actual) and model == actual


def _cited(text, actuals):
    """Whether a number written in prose (`3.46`, `33%`) equals one of the item's stats values: after rounding to the
    stats value's decimals, a percent against the ratio it stands for."""
    n = float(text.rstrip("%"))
    for a in actuals:
        if text.endswith("%"):
            d = len(text.rstrip("%").split(".")[1]) if "." in text else 0
            if round(a * 100, d) == n:
                return True
        elif _matches(n, a):
            return True
    return False


def check_item(item, stats):
    """None when the item passes, else the reason it is dropped."""
    if not isinstance(item, dict):
        return "not an object"
    for f in FIELDS:
        if f not in item:
            return f"missing field {f}"
    ev = item["evidence"]
    if not isinstance(ev, list) or not ev:
        return "no evidence"
    for e in ev:
        if not isinstance(e, dict) or "key" not in e or "value" not in e or not isinstance(e["key"], str):
            return "bad evidence entry"
        try:
            actual = metrics_analyze.lookup(stats, e["key"])
        except KeyError:
            return f"unknown key {e['key']}"
        if not _matches(e["value"], actual):
            return f"{e['key']} is {json.dumps(actual)}, not {json.dumps(e['value'])}"
    actuals = [metrics_analyze.lookup(stats, e["key"]) for e in ev]
    actuals = [a for a in actuals if _num(a)]
    for field in PROSE:
        text = item[field] if isinstance(item[field], str) else ""
        text = LIST_MARK.sub("", text, count=1)
        for m in NUMBER.finditer(text):
            if not _cited(m.group(0), actuals):
                return f"uncited number {m.group(0)} in {field}"
    return None


def recommend(stats_path):
    """The recommend.json content: {items, dropped, passed, asked}, or {items: [], unavailable}."""
    stats_path = Path(stats_path).resolve()
    stats = json.loads(stats_path.read_text())
    try:
        parsed = parse_items(run_claude(stats_path))
    except Unavailable as e:
        return {"items": [], "unavailable": str(e)}
    kept, dropped = [], []
    for n, it in enumerate(parsed):
        title = it.get("title") if isinstance(it, dict) and isinstance(it.get("title"), str) else f"item {n + 1}"
        reason = "beyond three" if n >= ASKED else check_item(it, stats)
        if reason:
            dropped.append({"title": title, "reason": reason})
        else:
            kept.append(it)
    return {"items": kept, "dropped": dropped, "passed": len(kept), "asked": ASKED}
