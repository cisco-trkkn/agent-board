"""discord_digest: one daily digest post in #command-center (tier progress, no mention).

tick() is called by the board's feed tick after the ops tick. When TC_DISCORD_DIGEST_AT (HH:MM local, default 08:00,
'off' disables) has passed and no digest went out today, it summarises every project's feed events since the last digest,
the open approvals in <_ops>/ops-state.json and today's spend, and enqueues one ops `post`. State: <_ops>/digest-state.json
{"last_ts", "last_day"}. Critical events are posted by discord_ops.tick as before; the digest never holds them. Test: tests/test_discord_digest.py."""
import json
import os
import re
import sys
import time

import discord_feed
import discord_ops
import tc_env

DEFAULT_AT = "08:00"
MAX = 1900
SPEC_SHOW = 3
_warned = False


def _parse(at):
    """(hour, minute) for 'HH:MM', None for 'off'; an unparsable value warns once per process and gives the default."""
    global _warned
    at = (at if at is not None else DEFAULT_AT).strip().lower()
    if at == "off":
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", at)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)), int(m.group(2))
    if not _warned:
        _warned = True
        print(f"tmux-dash: TC_DISCORD_DIGEST_AT {at!r} is not HH:MM or 'off'; using {DEFAULT_AT}", file=sys.stderr, flush=True)
    h, mi = DEFAULT_AT.split(":")
    return int(h), int(mi)


def _day(now):
    return time.strftime("%Y-%m-%d", time.localtime(now))


def due(state, now, at):
    """True once per local day, at or after `at`."""
    hm = _parse(at)
    if hm is None:
        return False
    lt = time.localtime(now)
    if (lt.tm_hour, lt.tm_min) < hm:
        return False
    return (state or {}).get("last_day") != _day(now)


def _specs(names):
    shown = ", ".join(names[:SPEC_SHOW]) + (", …" if len(names) > SPEC_SHOW else "")
    return f"({shown})" if names else ""


def _project_block(project, events, approvals, since):
    evs = [e for e in events if isinstance(e, dict) and isinstance(e.get("ts"), (int, float)) and e["ts"] >= since]
    evs.sort(key=lambda e: e["ts"])
    merged = [str(e.get("spec") or "?") for e in evs if e.get("kind") == "spec_outcome" and str(e.get("text", "")).startswith("merged")]
    failed = [str(e.get("spec") or "?") for e in evs if e.get("kind") == "spec_outcome" and str(e.get("text", "")).startswith("failed")]
    tests = sum(1 for e in evs if e.get("kind") == "test_failed")
    running = None
    for e in evs:
        s = str(e.get("spec") or "?")
        if e.get("kind") == "spec_started":
            running = s
        elif e.get("kind") == "spec_outcome" and running == s:
            running = None
    mine = [a for a in approvals if a.get("project") == project]
    if not (merged or failed or tests or running or mine):
        return [f"{project}: quiet"]
    lines = [f"{project}: merged {len(merged)} {_specs(merged)}".replace("  ", " ").rstrip() +
             f" · failed {len(failed)} {_specs(failed)}".replace("  ", " ").rstrip() +
             f" · running {running or 'none'} · decisions {len(mine)} · test runs failed {tests}"]
    for a in mine:
        if a.get("link"):
            lines.append(f"  {str(a.get('title') or '')[:100]} {a['link']}")
    return lines


def build(projects, feeds, approvals, records, limits, since, now):
    limits = limits or {}
    spends = [r["spend_today"] for r in records if isinstance(r, dict) and isinstance(r.get("spend_today"), (int, float))]
    spend = f"${sum(spends):.2f}" if spends else "$—"
    head = f"digest {_day(now)} · 5h {discord_ops._pct(limits.get('five_hour'))} · week {discord_ops._pct(limits.get('seven_day'))} · spend {spend}"
    blocks = ["\n".join(_project_block(p, (feeds or {}).get(p) or [], approvals or [], since)) for p in projects]
    keep = len(blocks)
    while True:
        more = [f"… {len(blocks) - keep} more projects"] if keep < len(blocks) else []
        text = "\n".join([head] + blocks[:keep] + more)
        if len(text) <= MAX or keep == 0:
            return text[:MAX]
        keep -= 1


def _read_feed(project, since):
    out = []
    try:
        with open(tc_env.feed_path(project), "rb") as f:
            for raw in f:
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("ts"), (int, float)) and e["ts"] >= since:
                    out.append(e)
    except OSError:
        pass
    return out


def tick(records, limits, now):
    """Post the digest when due. None when ops is not configured, off, or not due; the post's text otherwise."""
    if not discord_ops.configured():
        return None
    d = tc_env.ops_dir()
    sp = d / "digest-state.json"
    state = discord_ops._load(sp)
    if not due(state, now, os.environ.get("TC_DISCORD_DIGEST_AT")):
        return None
    since = state.get("last_ts") if isinstance(state.get("last_ts"), (int, float)) else now - 86400
    records = [r for r in records if isinstance(r, dict) and r.get("project")]
    projects = sorted(r["project"] for r in records)
    feeds = {p: _read_feed(p, since) for p in projects}
    approvals = list((discord_ops._load(d / "ops-state.json").get("approvals") or {}).values())
    text = build(projects, feeds, [a for a in approvals if isinstance(a, dict)], records, limits, since, now)
    discord_feed.outbox_write(d, {"op": "post", "text": text, "tier": "progress", "mention_user": False})
    discord_ops._write_json(sp, {"last_ts": now, "last_day": _day(now)})
    return text
