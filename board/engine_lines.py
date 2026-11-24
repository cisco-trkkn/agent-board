"""Deliver the engine's lead lines (<engine dir>/<project>.lead.jsonl) to the lead's window through the board's queue.

One line is in flight at a time. The cursor file (<project>.lead.cursor) holds the last delivered seq and moves only
after the line is no longer waiting in the queue, so a board restart while a line waits hands it over again.
Standard library only; the server passes add_line and pending."""
import json
import os
import re
from pathlib import Path


def engine_dir():
    return Path(os.environ.get("TC_ENGINE_DIR") or f"{os.environ.get('HOME', '')}/.local/state/agent-board/engine")


def _flat(text):
    """Same flattening as CommentQueue.add_line (artifacts._flat, limit 2000), so waiting text compares equal."""
    return re.sub(r"\s+", " ", str(text)).strip()[:2000]


def _cursor(path):
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _lines(path):
    """(good [(seq, text)], bad count)."""
    good, bad = [], 0
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return good, bad
    for r in raw:
        if not r.strip():
            continue
        try:
            o = json.loads(r)
            seq, text = o["seq"], o["text"]
            if isinstance(seq, bool) or not isinstance(seq, int) or not isinstance(text, str) or not text.strip():
                raise ValueError("bad line")
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        good.append((seq, text))
    return good, bad


def tick(project, add_line, pending, state, engine_dir=None, dry_run=False):
    """One pass. `state` is the caller's dict (state["flight"] = (seq, flat text) of the line in flight).
    Returns {"lines": lines read, "bad": malformed lines skipped, "delivered": seq moved to the cursor or None, "handed": seq handed over or None}.
    dry_run reads only: no cursor write, nothing handed over."""
    d = Path(engine_dir) if engine_dir else globals()["engine_dir"]()
    cur_path = d / f"{project}.lead.cursor"
    good, bad = _lines(d / f"{project}.lead.jsonl")
    out = {"lines": len(good), "bad": bad, "delivered": None, "handed": None}
    if dry_run:
        return out
    cursor = _cursor(cur_path)
    flight = state.get("flight")
    if flight:
        seq, text = flight
        if text in [_flat(t) for t in pending()]:
            add_line(text)   # still waiting (add_line dedupes); nothing advances
            return out
        if seq > cursor:
            tmp = cur_path.with_name(cur_path.name + ".next")
            d.mkdir(parents=True, exist_ok=True)
            tmp.write_text(str(seq), encoding="utf-8")
            os.replace(tmp, cur_path)
            cursor = seq
            out["delivered"] = seq
        state["flight"] = None
    nxt = next(((s, t) for s, t in good if s > cursor), None)
    if nxt:
        # the first line above the cursor in file order; seqs are in order, so an out-of-order line is not picked first
        add_line(nxt[1])
        state["flight"] = (nxt[0], _flat(nxt[1]))
        out["handed"] = nxt[0]
    return out
