"""discover_post: the nightly opportunity-discovery post for one project, its state file and the File / Dismiss clicks.

load_state/save_state own <agent_base>/discover/<project>.json (flock on <project>.lock, atomic write). select() applies the
spec §3 rule, build_op() renders the post op, publish() writes it and records what was reported, click() handles
`ab:discover:(file|dismiss):<project>:<kid>` and rewrites the post with an `edit` op. Differences from analytics_post that change
behaviour: the state is not in the destination dir, the id carries a project and sha1(key)[:12], and a decision edits the original
post instead of adding one. Does not import discover.py (it imports this module). Test: tests/test_discover_post.py."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

import analytics_post
import discord_feed
import dream_paths
import ideas
import tc_env

LIMIT = 1900
KEEP_NIGHTS = 14
REGROWTH = 1.5
URL_MAX = 150       # a longer url is rendered as plain text
MARK_ROOM = 40      # kept free per item for "— 💡 filed" / "— ✖ dismissed" (and the longest mark)
MARKS = {"filed": "💡 filed", "dismissed": "✖ dismissed"}
_CID = re.compile(r"^ab:discover:(file|dismiss):([A-Za-z0-9._-]+):([0-9a-f]{12})$")
_LEDGER = re.compile(r"ledgers/([^/\s:]+)/progress\.md")
escape = analytics_post.escape


def kid(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# ---- state -----------------------------------------------------------------------------------------------------------

def _paths(project):
    d = tc_env.agent_base() / "discover"
    return d / f"{project}.json", d / f"{project}.lock"


@contextlib.contextmanager
def _locked(project):
    p, lock = _paths(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _read(project):
    try:
        st = json.loads(_paths(project)[0].read_text())
        st = st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        st = {}
    out = {"root": "", "failures": 0, "reported": {}, "dismissed": {}, "filed": {}, "posts": {}}
    for k, dflt in out.items():
        v = st.get(k)
        if isinstance(v, type(dflt)):
            out[k] = v
    return out


def _write(project, st):
    st = dict(st)
    st["posts"] = {n: st["posts"][n] for n in sorted(st["posts"])[-KEEP_NIGHTS:]}
    p = _paths(project)[0]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1) + "\n")
    os.replace(tmp, p)


def load_state(project):
    return _read(project)


def save_state(project, st):
    with _locked(project):
        _write(project, st)


# ---- selection -------------------------------------------------------------------------------------------------------

def memory_dirs(project):
    """One set of ledger dir names per proposal of the newest memory run that has out/report.json; [] when none."""
    root = dream_paths.project_dir(project)
    try:
        runs = sorted((r for r in root.iterdir() if (r / "out" / "report.json").is_file()), key=lambda r: r.name, reverse=True)
        props = json.loads((runs[0] / "out" / "report.json").read_text()).get("proposals") if runs else None
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for p in props or []:
        ev = p.get("evidence") if isinstance(p, dict) else None
        out.append({m.group(1) for e in ev or [] for m in [_LEDGER.search(str(e))] if m})
    return out


def _ledger_dirs(c):
    return {m.group(1) for e in c.get("evidence") or [] for s in (e.get("path"), e.get("text")) for m in [_LEDGER.search(str(s or ""))] if m}


def select(items, cands, st, memory):
    new, also, still = [], [], 0
    for it in items:
        key, c = it["key"], cands[it["key"]]
        count = c["count"]
        if key in st["filed"]:
            continue
        if key in st["dismissed"] and count < REGROWTH * st["dismissed"][key]["evidence_count"]:
            continue
        if c.get("signal") == "repeated_ruling" and any(len(_ledger_dirs(c) & m) >= 3 for m in memory):
            also.append(it)
            continue
        rep = st["reported"].get(key)
        if rep and rep.get("last_evidence_count") == count:
            still += 1
            continue
        new.append(dict(it, count=count))
    return {"new": new, "still_open": still, "also_memory": also}


# ---- the post --------------------------------------------------------------------------------------------------------

def _evidence(c, it):
    ev = c.get("evidence") or []
    refs = [r for r in it.get("evidence_refs") or [] if isinstance(r, int) and 0 <= r < len(ev)]
    return [ev[r] for r in refs[:2]] if refs else ev[:2]


def _summary(c, it):
    return "; ".join(str(e["text"]) for e in _evidence(c, it))


def _parts(c, it):
    return [(str(e["text"]), e.get("url")) for e in _evidence(c, it)]


def _line(it, parts, cap, links=True):
    """The value line. A link whose text had to be cut is dropped (plain cut text), so a link is never cut in half."""
    ev = []
    for text, url in parts:
        if links and url and len(text) <= cap and len(str(url)) <= URL_MAX:
            ev.append(f"[{escape(text)}]({str(url).replace(')', '%29')})")
        else:
            ev.append(escape(_cut(text, cap)))
    c = max(cap // 4, 10)
    return (f"value {escape(_cut(it['expected_value'], c))} · effort {escape(_cut(it['effort'], c))} · "
            f"risk {escape(_cut(it['risk'], c))} · evidence: " + "; ".join(ev))


def _cut(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:max(n - 1, 0)] + "…"


def _render(project, night, items, footer):
    """items: stored post items; the text shows `shown_title`, `shown_why` and `line` (already cut to fit)."""
    lines = [f"🔎 discover {project}: {len(items)} new"]
    for i in items:
        mark = f" — {MARKS[i['decision']]}" if i.get("decision") in MARKS else ""
        lines += [f"{i['n']}. {escape(i['shown_title'])} — {escape(i['shown_why'])}{mark}", f"   {i['line']}"]
    return "\n".join(lines + footer)


def _rows(project, items):
    return [[{"label": f"File as idea {i['n']}", "style": 1, "custom_id": f"ab:discover:file:{project}:{i['kid']}"},
             {"label": f"Dismiss {i['n']}", "style": 2, "custom_id": f"ab:discover:dismiss:{project}:{i['kid']}"}]
            for i in items if not i.get("decision")]


def _footer(still_open, also_memory, cap):
    out = [f"still open: {still_open}"] if still_open > 0 else []
    if also_memory:
        shown = also_memory[:3]
        names = ", ".join(escape(_cut(i["title"], cap)) for i in shown)
        out.append("also proposed by the memory run: " + names + (f" (+{len(also_memory) - 3} more)" if len(also_memory) > 3 else ""))
    return out


def _stored(project, new, cands):
    out = []
    for n, it in enumerate(new[:5], 1):
        c = cands[it["key"]]
        out.append({"n": n, "key": it["key"], "kid": kid(it["key"]), "title": it["title"], "why": it["why"],
                    "summary": _summary(c, it), "count": it["count"], "decision": None, "_it": it, "_parts": _parts(c, it)})
    return out


def _fit(project, night, stored, still_open, also_memory):
    """Cut every item's title, why and evidence texts to one common cap (shrinking) until the text, with room for the
    marks, fits LIMIT. Never slices the whole text, so every item and the footer survive. At the smallest cap the links
    are dropped item by item from the last. Raises ValueError if it still does not fit."""
    cap, nolink = 900, 0
    while True:
        for k, i in enumerate(stored):
            i["shown_title"], i["shown_why"] = _cut(i["title"], cap), _cut(i["why"], cap)
            i["line"] = _line(i["_it"], i["_parts"], cap, links=k < len(stored) - nolink)
        footer = _footer(still_open, also_memory, max(cap // 2, 10))
        if len(_render(project, night, stored, footer)) + MARK_ROOM * len(stored) <= LIMIT:
            return footer
        if cap > 10:
            cap = max(int(cap * 0.8), 10) if cap > 100 else max(cap - 10, 10)
        elif nolink < len(stored):
            nolink += 1
        else:
            raise ValueError("discover post does not fit in %d chars" % LIMIT)


def _built(project, night, new, still_open, also_memory, cands):
    stored = _stored(project, new, cands)
    footer = _fit(project, night, stored, still_open, also_memory)
    op = {"op": "post", "text": _render(project, night, stored, footer), "tier": "progress", "mention_user": False,
          "key": f"discover-{project}-{night}", "rows": _rows(project, stored)}
    if len(op["text"]) > LIMIT:
        raise ValueError("discover post text over %d chars" % LIMIT)
    discord_feed._check(op)
    for i in stored:
        del i["_it"], i["_parts"]
    return op, stored, footer


def build_op(project, night, new, still_open, also_memory, cands):
    return _built(project, night, new, still_open, also_memory, cands)[0]


def publish(project, night, new, still_open, also_memory, cands, now):
    """Write the post op, then the state, both under the lock: a failed write leaves the state as it was. 0 and nothing
    written when there is nothing new."""
    if not new:
        return 0
    op, stored, footer = _built(project, night, new, still_open, also_memory, cands)
    with _locked(project):
        st = _read(project)
        for i in stored:
            old = st["reported"].get(i["key"])
            st["reported"][i["key"]] = {"first_reported": old["first_reported"] if old else _iso(now), "last_evidence_count": i["count"]}
        st["posts"][night] = {"key": op["key"], "items": stored, "footer": footer}
        discord_feed.outbox_write(tc_env.discord_dir(project), op)
        _write(project, st)
    return 1


# ---- clicks ----------------------------------------------------------------------------------------------------------

def _find(st, k):
    """The (night, item) for a kid: the newest post where it is undecided, else the newest post that has it."""
    hits = [(n, i) for n in sorted(st["posts"], reverse=True) for i in st["posts"][n].get("items") or [] if i.get("kid") == k]
    return next((h for h in hits if not h[1].get("decision")), hits[0] if hits else None)


def _edit(project, post):
    items = post["items"]
    op = {"op": "edit", "key": post["key"], "text": _render(project, post["key"].rsplit("-", 1)[-1], items, post.get("footer") or []),
          "rows": _rows(project, items)}
    discord_feed._check(op)
    discord_feed.outbox_write(tc_env.discord_dir(project), op)


def click(project, user, cid, now):
    m = _CID.match(str(cid or ""))
    if not m:
        return "unknown"
    act, p, k = m.groups()
    if p != project:
        return "ignored"
    try:
        with _locked(project):
            st = _read(project)
            hit = _find(st, k)
            if not hit:
                return "unknown"
            night, it = hit
            key = it["key"]
            done = "filed" if act == "file" else "dismissed"
            if key in st["filed"]:
                return "already filed"
            if key in st["dismissed"] and st["dismissed"][key]["evidence_count"] == it["count"]:
                return "already dismissed"
            if it.get("decision"):
                return "already " + it["decision"]
            if act == "file":
                line = f"{it['title']}: {it['why']} (evidence: {it['summary']})"
                st["filed"][key] = {"at": _iso(now), "idea_line": ideas.add(project, line)}
            else:
                st["dismissed"][key] = {"at": _iso(now), "evidence_count": it["count"]}
            it["decision"] = done
            _write(project, st)
            _edit(project, st["posts"][night])
            return done
    except Exception as e:  # noqa: BLE001 -- one bad click is audited, never raised into the controls loop
        return f"error: {type(e).__name__}"
