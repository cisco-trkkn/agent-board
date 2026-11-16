"""metrics recommend: ask `claude -p` for exactly three recommendations over stats.json alone, keep only the items whose
evidence matches stats.json.

Imports nothing from `metrics` (lookup comes from metrics_analyze). The claude binary is $TC_CLAUDE_BIN, else `claude`.
"""
import json
import os
import subprocess
from pathlib import Path

import metrics_analyze

PROMPT = Path(__file__).resolve().parent.parent / "claude" / "analytics.md"
TIMEOUT_S = 600
ASKED = 3
FIELDS = ("title", "change", "expected_effect", "evidence", "risk")
ARGV = ["-p", "--model", "sonnet", "--effort", "medium", "--tools", "Read", "--allowedTools", "Read", "--permission-mode",
        "dontAsk", "--no-session-persistence", "--strict-mcp-config", "--output-format", "json"]


class Unavailable(Exception):
    pass


def run_claude(stats_path):
    """The model's `result` text. Raises Unavailable(reason) on a timeout, a non-zero exit or an unreadable answer."""
    stats_path = Path(stats_path)
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
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and isinstance(v.get("items"), list):
        return v["items"]
    return None


def parse_items(text):
    """The first fenced json block's list or {"items": [...]}, else the first [..] or {..} span of the text that is one."""
    dec = json.JSONDecoder()
    spans = []
    fence = text.find("```json")
    if fence >= 0:
        start = text.find("\n", fence) + 1
        end = text.find("```", start)
        if end > start:
            spans.append(text[start:end])
    spans.append(text)
    for s in spans:
        for i, ch in enumerate(s):
            if ch in "[{":
                try:
                    v, _ = dec.raw_decode(s[i:])
                except ValueError:
                    continue
                items = _items_of(v)
                if items is not None:
                    return items
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
    return None


def recommend(stats_path):
    """The recommend.json content: {items, dropped, passed, asked}, or {items: [], unavailable}."""
    stats = json.loads(Path(stats_path).read_text())
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
