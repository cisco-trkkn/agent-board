#!/usr/bin/env python3
"""dream_discord: the nightly memory run's Discord side (Task 5, G11): the changes post with Revert and File proposals,
the contradictions post, the critical line after three failed nights, and the click handler.

Structure follows discord_ideas. Differences that change behaviour: the outbox is always the project's own
(tc_env.discord_dir), results are new `post` ops (the bridge's `edit` would drop the other button), there is no request
file or separate lock (state lives in <p>.dream.json and filed.json, guarded by the context lock in dream_actions), and
click() refuses an id for another project. Test: tests/test_dream_discord.py."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_feed  # noqa: E402
import dream_actions  # noqa: E402
import tc_env  # noqa: E402

CID_RE = re.compile(r"^ab:dream:(revert|file):([A-Za-z0-9][A-Za-z0-9._-]*):(\d{8}-\d{4})$")
TEXT_MAX = 1900
CID_MAX = 100
PAIRS_MAX = 5


def _write(project, op):
    discord_feed.outbox_write(tc_env.discord_dir(project), op)


def _has_channel(project):
    return bool(discord_feed.channel_of(project))


def _post(text, tier, key, mention=False, **extra):
    return dict({"op": "post", "text": text[:TEXT_MAX], "tier": tier, "mention_user": mention, "key": key}, **extra)


def post_run(res):
    """The changes post and, with contradictions, the decision post. True when the changes post was written."""
    p, run = res["project"], res["run"]
    if res.get("outcome") != "ok" or res.get("dry_run") or not _has_channel(p):
        return False
    c = res.get("counts") or {}
    k, n = len(res.get("proposals") or []), len(res.get("contradictions") or [])
    if not (any(c.get(x, 0) for x in ("merged", "archived", "stale", "added")) or k or n):
        return False
    text = (f"🌙 memory: merged {c.get('merged', 0)}, archived {c.get('archived', 0)}, stale {c.get('stale', 0)}, "
            f"added {c.get('added', 0)}; {k} proposals; {n} contradictions\n{res.get('summary') or ''}")
    extra = {}
    diff = Path(res["run_dir"]) / "out" / "diff.txt" if res.get("run_dir") else None
    if diff and diff.is_file():
        extra["files"] = [os.path.abspath(diff)]
    ids = [("Revert", 4, f"ab:dream:revert:{p}:{run}")] + ([("File proposals", 1, f"ab:dream:file:{p}:{run}")] if k else [])
    if any(len(i[2]) > CID_MAX for i in ids):
        tail = f"\nrevert: tmux-ctl context dream-revert {p} {run}"
        text = text[:TEXT_MAX - len(tail)] + tail
    else:
        extra["buttons"] = [{"label": l, "style": s, "custom_id": i} for l, s, i in ids]
    changes = _post(text, "progress", f"dream-{p}-{run}", **extra)
    discord_feed._check(changes)
    ops = [changes]
    if n:
        body = "".join(f"{i}. A: {x.get('a')}\n   B: {x.get('b')}\n" for i, x in enumerate(res["contradictions"][:PAIRS_MAX], 1))
        ops.append(_post("🌙 memory: these entries contradict each other. Which is right?\n" + body.rstrip("\n"),
                         "decision", f"dream-{p}-{run}-contra", True))
        discord_feed._check(ops[1])
    for op in ops:
        _write(p, op)
    return True


def post_failure(res):
    """The critical line, only on the night `failures` becomes exactly 3."""
    p = res["project"]
    if res.get("outcome") != "failed" or res.get("failures") != 3 or res.get("dry_run") or not _has_channel(p):
        return False
    _write(p, _post(f"🌙 memory: {p} failed 3 nights running — {res.get('check')}", "critical", f"dream-{p}-fail-{res['run']}", True))
    return True


def notify(res):
    if res.get("outcome") == "failed":
        post_failure(res)
    elif res.get("outcome") == "ok":
        res["posted"] = post_run(res)


def click(project, user, cid, now):
    """The audit result of one `ab:dream:` click. Acting clicks write their result as a new post; others change nothing."""
    m = CID_RE.match(cid or "")
    if not m:
        return "unknown"
    act, p, run = m.groups()
    if p != project:
        return "ignored"
    try:
        if act == "revert":
            result = dream_actions.revert(p, run)
            note = (f"↩️ memory run {run} reverted", f"dream-{p}-{run}-reverted") if result == "reverted" else None
        else:
            result = dream_actions.file_proposals(p, run)
            n = re.match(r"filed (\d+)", result)
            note = (f"📌 filed {n.group(1)} proposals", f"dream-{p}-{run}-filed") if n and int(n.group(1)) > 0 else None
        if note and _has_channel(p):
            _write(p, _post(note[0], "progress", note[1]))
        return result
    except Exception as e:  # noqa: BLE001 -- one bad click is audited, never raised into the controls loop
        return f"error: {type(e).__name__}"
