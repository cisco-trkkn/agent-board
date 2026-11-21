"""analytics_post: the weekly analytics Discord post for one destination dir.

build_ops(stats, rec, week, stats_path, multi_project) -> [post A (header, trends, flags), post B (recommendations, buttons,
stats.json attached)]. publish() writes the state file the "File as idea" button reads, then the ops through
discord_feed.outbox_write. Model-written strings and task subjects go through escape(); spec names, projects, numbers do not.
"""
import calendar
import fcntl
import json
import os
import re
import time
from pathlib import Path

import discord_feed
import ideas
import metrics_recommend
import tc_env

LIMIT = 1900
FLAG_ROOM = 60          # kept free in post A for the "… and k more" line
ZWSP = "​"
_SPECIAL = re.compile(r"([\\*_~|>#`])")


def escape(s):
    """Backslash-escape Discord markdown characters and defuse @ mentions."""
    return _SPECIAL.sub(r"\\\1", str(s)).replace("@", "@" + ZWSP)


def week_id(until_iso):
    ts = calendar.timegm(time.strptime(until_iso, "%Y-%m-%dT%H:%M:%SZ"))
    return time.strftime("%G-W%V", time.localtime(ts))


def validate_buttons(buttons):
    if len(buttons) > 5:
        raise ValueError("at most 5 buttons")
    for b in buttons:
        if len(b["label"]) > 80:
            raise ValueError("button label over 80 chars")
        if len(b["custom_id"]) > 100:
            raise ValueError("button custom_id over 100 chars")


# ---- spec-thread links -----------------------------------------------------------------------------------------------

def _base(spec):
    n = Path(str(spec)).name
    return n.replace(".md#", "#") if ".md#" in n else (n[:-3] if n.endswith(".md") else n)


def _same_spec(a, b):
    return a == b or a.startswith(b + "#") or b.startswith(a + "#")


def _json(path):
    try:
        v = json.loads(Path(path).read_text())
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def thread_link(project, spec):
    """<https://discord.com/channels/G/T> of the spec's thread, or None when anything is missing."""
    if not spec:
        return None
    name = _base(spec)
    key = None
    try:
        lines = tc_env.feed_path(project).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("kind") == "spec_started" and _same_spec(_base(ev.get("spec") or ""), name):
            refs = ev.get("refs")
            tk = refs.get("thread_key") if isinstance(refs, dict) else None
            if tk:
                key = tk
    if not key:
        return None
    state = _json(tc_env.discord_dir(project) / "bridge-state.json")
    tid = (state.get("threads") or {}).get(key) if isinstance(state.get("threads"), dict) else None
    if not tid or not state.get("guild_id"):
        return None
    return f"<https://discord.com/channels/{state['guild_id']}/{tid}>"


# ---- post A ----------------------------------------------------------------------------------------------------------

def _cap(s, n):
    s = metrics_recommend._one_line(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def _flag_rows(flags):
    """(project, spec, text) per flag line, in the order of weekly_text; costly_steps top 3."""
    short = lambda spec: Path(str(spec)).name   # noqa: E731
    cell = metrics_recommend._cell
    out = []
    for r in flags["overpowered"]:
        out.append((r.get("project"), r.get("spec"), f"overpowered: {short(r['spec'])} task {r['task_id']} "
                    f"{escape(_cap(r['subject'], 80))} ({escape(r['model_used'])}, 0 fix rounds)"))
    for r in flags["underpowered"]:
        out.append((r.get("project"), None, f"underpowered: {escape(r['tier_model'])}: {escape(_cap(r['reason'], 100))}"))
    for r in flags["costly_steps"][:3]:
        out.append((r.get("project"), r.get("spec"), f"costly_steps: {short(r['spec'])} task {r['task_id']} "
                    f"{escape(_cap(r['subject'], 80))} ${r['usd']}"))
    for r in flags["handoffs"]:
        out.append((r.get("project"), r.get("spec"), f"handoffs: {short(r['spec'])} {r['handoffs']} handoffs, "
                    f"${r['usd_per_active_hour']}/h vs median ${r['median_usd_per_active_hour']}/h"))
    fc = flags["forecast"]
    for r in fc["below_half"]:
        out.append((r.get("project"), r.get("spec"), f"forecast: {short(r['spec'])} recall {r['recall']} (below 0.5; medians: "
                    f"precision {cell(fc['median_precision'])}, recall {cell(fc['median_recall'])})"))
    return out


def _post_a(stats, week, multi):
    w = stats["window"]
    head = [f"Execution analytics, {w['since'][:10]} → {w['until'][:10]}", ""] + metrics_recommend.trends_table(stats)
    rows = _flag_rows(stats["flags"])
    if not rows:
        return "\n".join(head + ["Flags: none"])
    lines = head + ["Flags:"]
    budget = LIMIT - FLAG_ROOM
    used = len("\n".join(lines))
    shown = 0
    for project, spec, text in rows:
        line = "- " + (f"[{project}] " if multi and project else "") + text
        link = thread_link(project, spec) if project and spec else None
        if link:
            line += " " + link
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    if shown < len(rows):
        lines.append(f"… and {len(rows) - shown} more flags in stats.json")
    return "\n".join(lines)


# ---- post B ----------------------------------------------------------------------------------------------------------

# (cap for change/expected/risk, cap for title, cap for the evidence line); None = no cap
_LEVELS = [(None, None, None), (200, None, None), (100, 120, 150), (60, 80, 100)]


def _post_b(stats, rec, level):
    cap_body, cap_title, cap_ev = level
    lim = lambda s, n: metrics_recommend._one_line(s) if n is None else _cap(s, n)   # noqa: E731
    lines = ["Recommendations:"]
    for n, it in enumerate(rec.get("items") or [], 1):
        ev = "; ".join(f"{escape(e['key'])} = {escape(metrics_recommend._one_line(e['value']))}" for e in it["evidence"])
        if cap_ev is not None and len(ev) > cap_ev:
            ev = ev[:cap_ev - 1] + "…"
        lines += [f"{n}. {escape(lim(it['title'], cap_title))}", f"   change: {escape(lim(it['change'], cap_body))}",
                  f"   expected: {escape(lim(it['expected_effect'], cap_body))}", f"   risk: {escape(lim(it['risk'], cap_body))}",
                  f"   evidence: {ev}"]
    if "unavailable" in rec:
        lines.append(f"recommendations unavailable: {escape(metrics_recommend._one_line(rec['unavailable']))}")
    else:
        lines.append(f"({rec['passed']} of {rec['asked']} passed the evidence check)")
    c = stats["coverage"]
    cov = f"coverage: {c['with_cost']}/{c['tasks']} tasks with cost data"
    return lines, cov


def _text_b(stats, rec):
    for level in _LEVELS:
        lines, cov = _post_b(stats, rec, level)
        text = "\n".join(lines + [cov])
        if len(text) <= LIMIT:
            return text
    text = "\n".join(lines)          # the coverage line goes last
    return text if len(text) <= LIMIT else text[:LIMIT - 1] + "…"


def build_ops(stats, rec, week, stats_path, multi_project):
    a = {"op": "post", "text": _post_a(stats, week, multi_project), "tier": "progress", "mention_user": False,
         "key": f"analytics-{week}-a"}
    b = {"op": "post", "text": _text_b(stats, rec), "tier": "progress", "mention_user": False,
         "key": f"analytics-{week}-b", "files": [str(stats_path)]}
    items = rec.get("items") or []
    if items:
        buttons = [{"label": f"File as idea {n}", "style": 1, "custom_id": f"ab:analytics:idea:{week}:{n}"}
                   for n in range(1, len(items) + 1)]
        validate_buttons(buttons)
        b["buttons"] = buttons
    return [a, b]


# ---- state file and publishing ---------------------------------------------------------------------------------------

def _write_state(d, week, project, items):
    p = Path(d) / "analytics" / f"post-{week}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    try:
        old = {i["title"]: i.get("done") for i in json.loads(p.read_text()).get("items", [])}
    except (OSError, ValueError):
        pass
    doc = {"week": week, "project": project,
           "items": [{"n": n, "title": it["title"], "change": it["change"], "evidence": it["evidence"],
                      "done": old.get(it["title"]) or False} for n, it in enumerate(items, 1)]}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, p)


def publish(d, project, stats, rec, stats_path, multi_project):
    """Write the state file, then the two ops into <d>/outbox. Returns the number of ops written."""
    week = week_id(stats["window"]["until"])
    ops = build_ops(stats, rec, week, stats_path, multi_project)
    adir = Path(d) / "analytics"
    adir.mkdir(parents=True, exist_ok=True)
    with open(adir / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _write_state(d, week, project, rec.get("items") or [])
    for op in ops:
        discord_feed.outbox_write(d, op)
    return len(ops)


# ---- the "File as idea" click ----------------------------------------------------------------------------------------

_CID = re.compile(r"^ab:analytics:idea:(\d{4}-W\d{2}):([1-5])$")


def click(d, user, cid, now):
    """File recommendation <n> of week <week> as an idea, once. Returns unknown | already filed | filed | error: <msg>."""
    m = _CID.match(str(cid))
    if not m:
        return "unknown"
    week, n = m.group(1), int(m.group(2))
    p = Path(d) / "analytics" / f"post-{week}.json"
    adir = p.parent
    adir.mkdir(parents=True, exist_ok=True)
    with open(adir / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError):
            return "unknown"
        item = next((i for i in doc.get("items") or [] if i.get("n") == n), None)
        if item is None:
            return "unknown"
        if item.get("done"):
            return "already filed"
        ev = "; ".join(f"{e['key']}={e['value']}" for e in item["evidence"])
        try:
            ideas.add(doc["project"], f"{item['title']}: {item['change']} (evidence: {ev})")
        except ValueError as e:
            return f"error: {e}"
        item["done"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1) + "\n")
        os.replace(tmp, p)
        title = item["title"]
    discord_feed.outbox_write(d, {"op": "post", "text": f"💡 filed as idea: {escape(title)}", "tier": "progress",
                                  "mention_user": False, "key": f"analytics-{week}-{n}-filed"})
    return "filed"
