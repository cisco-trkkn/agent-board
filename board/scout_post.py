"""scout_post: the trend scout's weekly digest post, its two state files and the `ab:scout:` clicks and replies.

drafts.json ({"drafts": {id: Draft}, "pending_copies": [...]}) and findings.json (the shared findings schema: the digest post
lives in posts[week], other findings in reported/filed/dismissed) are both findings.Store files in scout_dir(). Lock order is
always drafts first, findings second. publish() writes the post op, then both states; click() applies one decision and edits
the post (same key) so a decided draft shows its mark and loses its buttons. An approval calls approve_fn after the locks are
released (scout_decisions.approve takes the drafts lock itself). Test: tests/test_scout_post.py."""
import contextlib
import hashlib
import os
import re
import shutil
import time
from pathlib import Path

import discord_feed
import dream
import findings
import ideas
import tc_env

PROJECT = "agent-board"
LIMIT = 1900
MARK_ROOM = 40
ROWS_MAX = 5
NOTE_MAX = 500
HEALTH_FAILURES = 3
STATUS_MARKS = {"approved": "✅ approved", "rejected": "✖ rejected", "revise": "✏ revise", "expired": "⌛ expired",
                "superseded": "♻ superseded"}
_CID = re.compile(r"^ab:scout:(approve|reject|revise|file|dismiss):([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)$")
_REPLY = re.compile(r"^ab:scout:(reject|revise):([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)$")
_C0 = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def scout_dir():
    import scout_sources  # the canonical definition; imported here to avoid an import cycle
    return scout_sources.scout_dir()


def _drafts():
    return findings.Store(scout_dir() / "drafts.json", extra={"drafts": {}, "pending_copies": []})


def _findings():
    return findings.Store(scout_dir() / "findings.json")


@contextlib.contextmanager
def _both():
    d, f = _drafts(), _findings()
    with d.locked(), f.locked():
        yield d, f


def draft_id(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _post_key(week):
    return f"scout-agent-board-{week}"


# ---- the post --------------------------------------------------------------------------------------------------------

def _parts(evidence):
    return [(str(e.get("quote") or ""), e.get("url")) for e in evidence or [] if isinstance(e, dict)][:2]


def _item_line(it, cap, links):
    if it["kind"] == "draft":
        # the draft's one source link, through value_line (its "evidence:" label reads "source:" here)
        line = findings.value_line(it["_v"], it["_e"], it["_r"], [("link", it["url"])], cap, links)
        return line.replace(" · evidence: ", " · source: ", 1)
    return findings.value_line(it["_v"], it["_e"], it["_r"], it["_parts"], cap, links)


def _names(strs, cap):
    shown = [findings.escape(findings.cut(s, cap)) for s in strs[:3]]
    return "; ".join(shown) + (f" (+{len(strs) - 3} more)" if len(strs) > 3 else "")


def _health_names(health):
    health = health if isinstance(health, dict) else {}
    srcs = health.get("sources") or []
    out = [f"{n} ({h['failures']} failures)" for n, h in sorted((health.get("health") or {}).items())
           if isinstance(h, dict) and isinstance(h.get("failures"), int) and h["failures"] >= HEALTH_FAILURES]
    if not any(isinstance(s, dict) and s.get("kind") == "discord_channel" for s in srcs):
        out.append("#scout not set")
    return out


def _footer(post, cap):
    out = []
    if post["overlaps"]:
        out.append("Overlaps: " + _names(post["overlaps"], cap))
    if post["dropped"]:
        out.append("Dropped: " + _names(post["dropped"], cap))
    if post["health"]:
        out.append("Source health: " + findings.escape("; ".join(post["health"])))
    out.append(f"tokens: {post['tokens']}")
    return out


def _render(week, post, statuses):
    items = post["items"]
    nd = sum(1 for i in items if i["kind"] == "draft")
    lines = [f"🛰 scout {PROJECT} {week}: {nd} drafted, {len(items) - nd} other"]
    seen_other = False
    for i in items:
        if i["kind"] == "other" and not seen_other:
            lines.append("Other findings:")
            seen_other = True
        dec = statuses.get(i["id"]) if i["kind"] == "draft" else i.get("decision")
        if i["kind"] == "draft":
            mark = f" — {STATUS_MARKS[dec]}" if dec in STATUS_MARKS else ""
        else:
            mark = f" — {findings.MARKS[dec]}" if dec in findings.MARKS else ""
        lines += [f"{i['n']}. {findings.escape(i['shown_title'])} — {findings.escape(i['shown_why'])}{mark}", f"   {i['line']}"]
        if i["kind"] == "draft" and i.get("protected"):
            lines.append("   ⚠ touches protected files")
    return "\n".join(lines + post["footer"])


def _undecided(i, statuses):
    return (statuses.get(i["id"]) == "pending") if i["kind"] == "draft" else not i.get("decision")


def _rows(post, statuses):
    rows = []
    for i in post["items"]:
        if not i.get("buttons") or not _undecided(i, statuses):
            continue
        cid = lambda act, ident: f"ab:scout:{act}:{PROJECT}:{ident}"  # noqa: E731
        if i["kind"] == "draft":
            rows.append([{"label": f"Approve {i['n']}", "style": 3, "custom_id": cid("approve", i["id"])},
                         {"label": f"Reject {i['n']}", "style": 4, "custom_id": cid("reject", i["id"])},
                         {"label": f"Revise {i['n']}", "style": 2, "custom_id": cid("revise", i["id"])}])
        else:
            rows.append([{"label": f"File as idea {i['n']}", "style": 1, "custom_id": cid("file", i["kid"])},
                         {"label": f"Dismiss {i['n']}", "style": 2, "custom_id": cid("dismiss", i["kid"])}])
    return rows


def _items(drafts, others):
    out = []
    for d in drafts:
        out.append({"kind": "draft", "n": len(out) + 1, "id": d.get("id") or draft_id(d["key"]), "key": d["key"], "title": d["title"],
                    "why": d["why"], "protected": bool(d.get("protected")), "url": d.get("url") or "", "buttons": len(out) < ROWS_MAX,
                    "_v": d["value"], "_e": d["effort"], "_r": d["risk"]})
    for o in others:
        out.append({"kind": "other", "n": len(out) + 1, "key": o["key"], "kid": findings.kid(o["key"]), "title": o["title"], "why": o["why"],
                    "what_it_enables": o.get("what_it_enables") or "", "url": o.get("url") or "", "count": len(o.get("evidence") or []),
                    "decision": None, "buttons": len(out) < ROWS_MAX, "_v": o["value"], "_e": o["effort"], "_r": o["risk"],
                    "_parts": _parts(o.get("evidence"))})
    return out


def _fit(week, post):
    """Cut every model string to one common cap, shrinking, until the text (with room for the marks) fits LIMIT; at the smallest
    cap the links go, item by item from the last. Raises ValueError when it still does not fit."""
    items = post["items"]
    statuses = {i["id"]: "pending" for i in items if i["kind"] == "draft"}
    cap, nolink = 900, 0
    while True:
        for k, i in enumerate(items):
            i["shown_title"], i["shown_why"] = findings.cut(i["title"], cap), findings.cut(i["why"], cap)
            i["line"] = _item_line(i, cap, k < len(items) - nolink)
        post["footer"] = _footer(post, max(cap // 2, 10))
        if len(_render(week, post, statuses)) + MARK_ROOM * len(items) <= LIMIT:
            return
        if cap > 10:
            cap = max(int(cap * 0.8), 10) if cap > 100 else max(cap - 10, 10)
        elif nolink < len(items):
            nolink += 1
        else:
            raise ValueError("scout post does not fit in %d chars" % LIMIT)


def _copy_files(week, drafts):
    out = []
    for d in drafts:
        src = Path(str(d.get("path") or ""))
        if src.is_file():
            dst = scout_dir() / "runs" / week / "files" / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            out.append(str(dst))
    return out


def _built(week, drafts, others, overlaps, dropped, health, tokens):
    post = {"key": _post_key(week), "items": _items(drafts, others), "overlaps": [str(s) for s in overlaps],
            "dropped": [str(s) for s in dropped], "health": _health_names(health), "tokens": tokens}
    _fit(week, post)
    statuses = {i["id"]: "pending" for i in post["items"] if i["kind"] == "draft"}
    op = {"op": "post", "text": _render(week, post, statuses), "tier": "progress", "mention_user": False, "key": post["key"],
          "rows": _rows(post, statuses)}
    files = _copy_files(week, drafts)
    if files:
        op["files"] = files
    if len(op["text"]) > LIMIT:
        raise ValueError("scout post text over %d chars" % LIMIT)
    discord_feed._check(op)
    for i in post["items"]:
        for k in [k for k in i if k.startswith("_")]:
            del i[k]
    return op, post


def build_op(week, drafts, others, overlaps, dropped, health, tokens):
    return _built(week, drafts, others, overlaps, dropped, health, tokens)[0]


def publish(week, drafts, others, overlaps, dropped, health, tokens, now):
    """Write the post op, then both states under the two locks: a failed outbox write leaves them as they were."""
    op, post = _built(week, drafts, others, overlaps, dropped, health, tokens)
    with _both() as (ds, fs):
        dst, fst = ds.read(), fs.read()
        for d in drafts:
            rec = dict(d)
            rec["id"] = d.get("id") or draft_id(d["key"])
            rec.update(status="pending", post_key=op["key"], week=week)
            rec.setdefault("created_at", findings.iso(now))
            for k in ("note", "reason", "decided_at", "decided_by"):
                rec.setdefault(k, None)
            dst["drafts"][rec["id"]] = rec
        for i in post["items"]:
            if i["kind"] == "other":
                old = fst["reported"].get(i["key"])
                fst["reported"][i["key"]] = {"first_reported": old["first_reported"] if old else findings.iso(now),
                                             "last_evidence_count": i["count"]}
        fst["posts"][week] = post
        discord_feed.outbox_write(tc_env.discord_dir(PROJECT), op)
        ds.write(dst)
        fs.write(fst)
    return 1


def _edit(week, dst, fst):
    post = fst["posts"].get(week)
    if not post:
        return
    statuses = {k: v.get("status") for k, v in dst["drafts"].items()}
    op = {"op": "edit", "key": post["key"], "text": _render(week, post, statuses), "rows": _rows(post, statuses)}
    discord_feed._check(op)
    discord_feed.outbox_write(tc_env.discord_dir(PROJECT), op)


def refresh(week):
    """Re-render the week's post from the states (after a status changed outside a click, e.g. expiry)."""
    with _both() as (ds, fs):
        _edit(week, ds.read(), fs.read())


# ---- clicks and replies ----------------------------------------------------------------------------------------------

def _find(fst, k):
    hits = [(n, i) for n in sorted(fst["posts"], reverse=True) for i in fst["posts"][n].get("items") or []
            if i.get("kind") == "other" and i.get("kid") == k]
    return next((h for h in hits if not h[1].get("decision")), hits[0] if hits else None)


def click(user, cid, now, add_line=None, approve_fn=None):
    m = _CID.match(str(cid or ""))
    if not m:
        return "unknown"
    act, project, ident = m.groups()
    if project != PROJECT:
        return "ignored"
    approved = None
    try:
        with _both() as (ds, fs):
            dst, fst = ds.read(), fs.read()
            if act in ("approve", "reject", "revise"):
                dr = dst["drafts"].get(ident)
                if not dr:
                    return "unknown"
                if dr.get("status") != "pending":
                    return "already " + str(dr.get("status"))
                dr["status"] = {"approve": "approved", "reject": "rejected", "revise": "revise"}[act]
                dr["decided_at"], dr["decided_by"] = findings.iso(now), user
                if act == "reject":
                    fst["dismissed"][dr["key"]] = {"at": findings.iso(now), "evidence_count": len(dr.get("evidence") or [])}
                done, week = dr["status"], dr.get("week")
                approved = dr if act == "approve" else None
            else:
                hit = _find(fst, ident)
                if not hit:
                    return "unknown"
                week, it = hit
                done = findings.decide(fst, it, act, now, lambda it: ideas.add(
                    PROJECT, f"scout: {it['title']} — {it['what_it_enables']} ({it['url']})"))
                if done.startswith("already"):
                    return done
            ds.write(dst)
            fs.write(fst)
            if week:
                _edit(week, dst, fst)
    except Exception as e:  # noqa: BLE001 -- one bad click is audited, never raised into the controls loop
        return f"error: {type(e).__name__}"
    if approved is not None:
        try:
            if approve_fn is None:
                import scout_decisions
                root = dream.resolve_root(PROJECT, {}, None)
                scout_decisions.approve(approved, root, time.time(), add_line)
            else:
                approve_fn(approved, add_line)
        except Exception as e:  # noqa: BLE001 -- the approval is stored; the failure is audited
            return f"error: {type(e).__name__}"
    return done


def reply(user, key, text, now):
    """Store the reason (reject) or note (revise) a user typed as a reply to the digest. "noted", or "ignored" for any other key."""
    m = _REPLY.match(str(key or ""))
    if not m or m.group(2) != PROJECT:
        return "ignored"
    kind, ident = m.group(1), m.group(3)
    text = _C0.sub(" ", str(text or "")).strip()[:NOTE_MAX]
    with _drafts().locked():
        ds = _drafts()
        st = ds.read()
        dr = st["drafts"].get(ident)
        if not dr:
            return "ignored"
        dr["reason" if kind == "reject" else "note"] = text
        ds.write(st)
    return "noted"
