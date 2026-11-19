#!/usr/bin/env python3
"""discord_ideas: the /ideas command's board side. Idea ids, requests, group posts with buttons, time-out, clicks.

State lives under <ops dir>/ideas/ (req-<id>.json, post-<id>.json) behind its own flock: never the ops-state lock,
because discord_ops.consume already holds that while it calls click. Test: tests/test_discord_ideas.py.

  discord_ideas.py list [project]          rows "<id>\\t<project>\\t<text>"
  discord_ideas.py post <file|-> [--dry-run]   rc 0 ok, 1 refused (reason on stderr), 2 bad argv"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_feed  # noqa: E402
import ideas  # noqa: E402
import tc_env  # noqa: E402

PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")   # same as discord_ops.PROJECT_RE
TIER = "progress"          # the tier discord_feed gives its plain informational posts
ANSWER_WINDOW = 600
TIMEOUT = 180
MAX_GROUPS = 10
IDEA_MAX = 120
GROUP_MAX = 1900
BUTTONS = (("next", "Brainstorm next", 1), ("park", "Park", 2), ("drop", "Drop", 4))
CID_RE = re.compile(r"^ab:ideas:(next|park|drop):([0-9a-f]{8}):(\d+)$")


@contextlib.contextmanager
def _locked():
    d = tc_env.ops_dir() / "ideas"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "state.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        yield d


def _read(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _write(p, obj):
    tmp = Path(f"{p}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def idea_id(project, key):
    return hashlib.sha1(f"{project}\0{key}".encode()).hexdigest()[:10]


def _projects():
    d = ideas.ideas_dir()
    return sorted(p.stem for p in d.glob("*.md") if PROJECT_RE.match(p.stem)) if d.is_dir() else []


def _open(project):
    """[(id, project, text, key)] for the open ideas of one project, or of every project in sorted order."""
    out = []
    for p in ([project] if project else _projects()):
        try:
            entries = ideas.load(p)
        except ValueError:
            continue
        out += [(idea_id(p, e["key"]), p, e["text"], e["key"]) for e in entries if e["status"] == "open"]
    return out


def open_ideas(project):
    return [r[:3] for r in _open(project)]


def _box(bridge):
    return tc_env.ops_dir() if bridge == "_ops" else tc_env.discord_dir(bridge)


def _known_project(project):
    if not PROJECT_RE.match(project or ""):
        return False
    if project in _projects():
        return True
    import discord_ops
    return discord_ops._known(project)


def _valid_bridge(bridge):
    return bridge == "_ops" or (isinstance(bridge, str) and PROJECT_RE.match(bridge) is not None and tc_env.discord_dir(bridge).is_dir())


def request(project, bridge, add_line, now):
    if project is not None and not _known_project(project):
        return "unknown project"
    if not _valid_bridge(bridge):
        return "invalid bridge"
    rid = secrets.token_hex(4)
    with _locked() as d:
        _write(d / f"req-{rid}.json", {"id": rid, "project": project, "bridge": bridge, "ts": now, "state": "open"})
    add_line("overseer", f"[Discord] /ideas {rid}: group the open ideas of {project or 'all projects'}, "
                         "then run tmux-ctl discord ideas-post with the groups JSON")
    return "asked"


def _plain(bridge, key, text):
    discord_feed.outbox_write(_box(bridge), {"op": "post", "text": text, "tier": TIER, "mention_user": False, "key": key})


def _render(header, texts):
    lines = [f"• {t[:IDEA_MAX]}" for t in texts]
    text = "\n".join([header] + lines)
    if len(text) <= GROUP_MAX:
        return text
    while lines:
        lines.pop()
        more = f"… {len(texts) - len(lines)} more"
        text = "\n".join([header] + lines + [more])
        if len(text) <= GROUP_MAX:
            return text
    return header[:GROUP_MAX]


def _buttons(req, g):
    return [{"label": label, "style": style, "custom_id": f"ab:ideas:{act}:{req}:{g}"} for act, label, style in BUTTONS]


def post(doc, now, dry_run=False):
    if not (isinstance(doc, dict) and isinstance(doc.get("request"), str) and isinstance(doc.get("groups"), list)):
        return 1, "bad document: need request and groups"
    req = doc["request"]
    if not re.fullmatch(r"[0-9a-f]{8}", req):
        return 1, "unknown request"
    with _locked() as d:
        rf = d / f"req-{req}.json"
        r = _read(rf)
        if r is None:
            return 1, "unknown request"
        if r.get("state") != "open":
            return 1, f"request is {r.get('state')}"
        if now - float(r.get("ts", 0)) >= ANSWER_WINDOW:
            return 1, "request too old"
        avail = {row[0]: row for row in _open(r.get("project"))}
        skipped, seen, groups = 0, set(), []
        for gi, g in enumerate(doc["groups"]):
            raw = g.get("ideas") if isinstance(g, dict) else None
            raw = raw if isinstance(raw, list) else []
            if gi >= MAX_GROUPS:
                skipped += len(raw)
                continue
            if not (isinstance(g, dict) and all(isinstance(g.get(k), str) for k in ("title", "emoji", "project"))):
                skipped += len(raw)
                continue
            rows = []
            for i in raw:
                row = avail.get(i) if isinstance(i, str) else None
                if row is None or i in seen or row[1] != g["project"]:
                    skipped += 1
                    continue
                seen.add(i)
                rows.append(row)
            if rows:
                groups.append((g, rows))
        if dry_run:
            return 0, f"would post {len(groups)} groups, skipped {skipped}"
        bridge = r.get("bridge", "_ops")
        state, ops = [], []
        for n, (g, rows) in enumerate(groups):
            header = f"{g['emoji']} **{g['title']}** · {g['project']} · {len(rows)}"
            ops.append({"op": "post", "text": _render(header, [x[2] for x in rows]), "tier": TIER, "mention_user": False,
                        "key": f"ideas-{req}-{n}", "buttons": _buttons(req, n)})
            state.append({"title": g["title"], "emoji": g["emoji"], "project": g["project"], "ids": [x[0] for x in rows],
                          "keys": [x[3] for x in rows], "texts": [x[2] for x in rows], "header": header, "done": None})
        if not groups:
            ops.append({"op": "post", "text": "no open ideas", "tier": TIER, "mention_user": False, "key": f"ideas-{req}-none"})
        if skipped:
            ops.append({"op": "post", "text": f"skipped: {skipped} ids", "tier": TIER, "mention_user": False, "key": f"ideas-{req}-skipped"})
        try:
            for op in ops:
                discord_feed._check(op)   # a bad op fails here, before anything is written
        except ValueError as e:
            return 1, f"invalid group: {e}"
        _write(d / f"post-{req}.json", {"request": req, "bridge": bridge, "groups": state})
        r["state"] = "answered"
        _write(rf, r)   # answered before the ops go out: a failed write must not let a retry duplicate posts
        try:
            for op in ops:
                discord_feed.outbox_write(_box(bridge), op)
        except (OSError, ValueError) as e:
            return 1, f"error writing posts (request stays answered): {e}"
    return 0, f"posted {len(groups)} groups, skipped {skipped}"


def expire(now):
    n = 0
    with _locked() as d:
        for rf in sorted(d.glob("req-*.json")):
            r = _read(rf)
            if not r or r.get("state") != "open" or now - float(r.get("ts", now)) < TIMEOUT:
                continue
            try:
                _plain(r.get("bridge", "_ops"), f"ideas-{r['id']}-timeout", "overseer didn't answer /ideas")
            except (OSError, ValueError):
                continue
            r["state"] = "closed"
            _write(rf, r)
            n += 1
    return n


def click(user, cid, add_line, now):
    m = CID_RE.match(cid or "")
    if not m:
        return "unknown"
    act, req, gi = m[1], m[2], int(m[3])
    with _locked() as d:
        st = _read(d / f"post-{req}.json")
        rq = _read(d / f"req-{req}.json")
        if not st or not rq or rq.get("state") == "closed" or gi >= len(st.get("groups", [])):
            return "unknown"
        g = st["groups"][gi]
        if g.get("done"):
            return "unknown"
        try:
            discord_feed._check({"op": "edit", "key": f"ideas-{req}-{gi}", "text": g["header"]})   # fail before acting
        except ValueError:
            return "error: edit failed"
        if act == "next":
            add_line(g["project"], f"regroup: {g['title']} — ideas: {', '.join(g['ids'])}")
            second, result = f"→ sent to {g['project']}'s lead to brainstorm", "queued"
        elif act == "park":
            second, result = "→ parked", "parked"
        else:
            done = changed = 0
            for key in g["keys"]:
                try:   # set_status refuses a line that is no longer open (dropped, taken, changed text)
                    ideas.set_status(g["project"], key, "dropped")
                    done += 1
                except ValueError:
                    changed += 1
            second = f"dropped {done}" + (f", {changed} already changed" if changed else "")
            result = f"dropped {done}"
        edit = {"op": "edit", "key": f"ideas-{req}-{gi}", "text": f"{g['header']}\n{second}"}
        g["done"] = act   # the action ran: a re-tap must never repeat it, even if the edit below fails
        _write(d / f"post-{req}.json", st)
        try:
            discord_feed.outbox_write(_box(st.get("bridge", "_ops")), edit)
        except (OSError, ValueError):
            return "error: edit failed"
    return result


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if a[:1] == ["list"] and len(a) <= 2:
        for i, p, t in open_ideas(a[1] if len(a) == 2 else None):
            print(f"{i}\t{p}\t{t}")
        return 0
    if a[:1] == ["post"] and len(a) in (2, 3) and (len(a) == 2 or a[2] == "--dry-run"):
        try:
            raw = sys.stdin.read() if a[1] == "-" else Path(a[1]).read_text(encoding="utf-8")
            doc = json.loads(raw)
        except (OSError, ValueError) as e:
            print(f"cannot read the groups document: {e}", file=sys.stderr)
            return 1
        rc, msg = post(doc, time.time(), dry_run=len(a) == 3)
        print(msg, file=sys.stdout if rc == 0 else sys.stderr)
        return rc
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
