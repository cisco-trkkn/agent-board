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


def _usage(doc):
    u = doc.get("usage") if isinstance(doc, dict) else None
    tokens = None
    if isinstance(u, dict):
        tokens = {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
                  "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens")}
    cost = doc.get("total_cost_usd") if isinstance(doc, dict) else None
    return {"cost_usd": cost if isinstance(cost, (int, float)) else None, "tokens": tokens}


def run_claude(stats_path):
    """(the model's `result` text, usage {cost_usd, tokens}). Raises Unavailable(reason) on a timeout, a non-zero exit or an unreadable answer."""
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
        doc = json.loads(p.stdout)
        text = doc["result"]
    except (ValueError, KeyError, TypeError):
        raise Unavailable("no JSON result")
    if not isinstance(text, str):
        raise Unavailable("no JSON result")
    return text, _usage(doc)


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
    # a number inside a cited string value ('Task 5: …', a dated spec name) is part of that cited string, not an uncited number
    cited_strings = sorted({e["value"] for e in ev if isinstance(e["value"], str) and e["value"]}, key=len, reverse=True)
    for field in PROSE:
        text = item[field] if isinstance(item[field], str) else ""
        text = LIST_MARK.sub("", text, count=1)
        for cs in cited_strings:
            text = text.replace(cs, " ")
        for m in NUMBER.finditer(text):
            if not _cited(m.group(0), actuals):
                return f"uncited number {m.group(0)} in {field}"
    return None


def recommend(stats_path):
    """The recommend.json content: {items, dropped, passed, asked, usage}, or {items: [], unavailable, usage}."""
    stats_path = Path(stats_path).resolve()
    stats = json.loads(stats_path.read_text())
    usage = {"cost_usd": None, "tokens": None}
    try:
        text, usage = run_claude(stats_path)
        parsed = parse_items(text)
    except Unavailable as e:
        return {"items": [], "unavailable": str(e), "usage": usage}
    kept, dropped = [], []
    for n, it in enumerate(parsed):
        title = it.get("title") if isinstance(it, dict) and isinstance(it.get("title"), str) else f"item {n + 1}"
        reason = "beyond three" if n >= ASKED else check_item(it, stats)
        if reason:
            dropped.append({"title": title, "reason": reason, "item": it})
        else:
            kept.append(it)
    return {"items": kept, "dropped": dropped, "passed": len(kept), "asked": ASKED, "usage": usage}


# ---- the weekly report text ------------------------------------------------------------------------------------------

MAX_LINE = 160


def _one_line(v):
    return re.sub(r"\s*\n\s*", " ", str(v)).strip()


def _cell(v):
    return "–" if v is None else str(v)


def _signed(v):
    return "–" if v is None else "0" if v == 0 else f"{v:+}"


def _cap(line):
    return line if len(line) <= MAX_LINE else line[:MAX_LINE - 1] + "…"


def _flag_lines(flags):
    short = lambda spec: Path(str(spec)).name   # noqa: E731
    out = []
    for r in flags["overpowered"]:
        out.append(f"- overpowered: {short(r['spec'])} task {r['task_id']} {_one_line(r['subject'])} ({r['model_used']}, 0 fix rounds)")
    for r in flags["underpowered"]:
        out.append(f"- underpowered: {r['tier_model']}: {r['reason']}")
    for r in flags["costly_steps"]:
        out.append(f"- costly_steps: {short(r['spec'])} task {r['task_id']} {_one_line(r['subject'])} ${r['usd']}")
    for r in flags["handoffs"]:
        out.append(f"- handoffs: {short(r['spec'])} {r['handoffs']} handoffs, ${r['usd_per_active_hour']}/h vs median "
                   f"${r['median_usd_per_active_hour']}/h")
    fc = flags["forecast"]
    for r in fc["below_half"]:
        out.append(f"- forecast: {short(r['spec'])} recall {r['recall']} (below 0.5; medians: precision {_cell(fc['median_precision'])}, "
                   f"recall {_cell(fc['median_recall'])})")
    return [_cap(l) for l in out]


def trends_table(stats):
    """The trends code block as lines, both ``` fences included."""
    lines = ["```"]
    names = list(stats["trends"])
    width = max(len(n) for n in names + ["metric"])
    cells = [("metric", "last week", "this week", "change")] + \
            [(n, _cell(t["previous"]), _cell(t["current"]), _signed(t["change"])) for n, t in stats["trends"].items()]
    cw = [max(len(r[i]) for r in cells) for i in (1, 2, 3)]
    for r in cells:
        lines.append(f"{r[0]:<{width}} | {r[1]:<{cw[0]}} | {r[2]:<{cw[1]}} | {r[3]:<{cw[2]}}".rstrip())
    lines.append("```")
    return lines


def weekly_text(stats, rec, stats_path=None):
    """The weekly report: header, trends table, flags, recommendations, coverage, stats path. Model-written strings go in
    as they are, newlines collapsed to spaces."""
    w = stats["window"]
    lines = [f"Execution analytics, {w['since'][:10]} → {w['until'][:10]}", ""] + trends_table(stats)
    flag_lines = _flag_lines(stats["flags"])
    lines += ["Flags:"] + flag_lines if flag_lines else ["Flags: none"]
    lines.append("Recommendations:")
    for n, it in enumerate(rec.get("items") or [], 1):
        ev = "; ".join(f"{e['key']} = {_one_line(e['value'])}" for e in it["evidence"])
        lines += [f"{n}. {_one_line(it['title'])}", f"   change: {_one_line(it['change'])}",
                  f"   expected: {_one_line(it['expected_effect'])}", f"   risk: {_one_line(it['risk'])}", f"   evidence: {ev}"]
    if "unavailable" in rec:
        lines.append(f"recommendations unavailable: {_one_line(rec['unavailable'])}")
    else:
        lines.append(f"({rec['passed']} of {rec['asked']} passed the evidence check)")
    c = stats["coverage"]
    lines.append(f"coverage: {c['with_cost']}/{c['tasks']} tasks with cost data")
    if stats_path is not None:
        lines.append(f"stats: {stats_path}")
    return "\n".join(lines) + "\n"
