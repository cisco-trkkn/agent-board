"""Handoffs and compactions, and what the session after a handoff spends before its first edit.

Findings that shape the detection rules (checked 2026-10-25):
- Real transcripts carry NO compaction system subtype and no isCompactSummary, so compaction is detected two ways:
  (a) rule `context_drop`: a main-agent request whose context (input + cache_read + cache_creation) is
      < 50% of the previous main request's in the same session (derived);
  (b) rule `continued_prompt`: a prompt whose text_head starts with "This session is being continued";
      context_before = the last main request's context at or before that prompt (derived).
- agent-board's handoff trigger: claude/hooks/context-size-guard.sh (UserPromptSubmit) warns once main context
  >= CLAUDE_CONTEXT_WARN_TOKENS (default 300000) and recommends /handoff. The /handoff skill writes a doc to
  ~/.local/state/agent-board/handoffs/ (older: ~/.claude/handoffs/) and `tmux-ctl relay` restarts the window with the prompt
  "Read <doc> and continue from where the previous session left off.". The marker in the new transcript is therefore
  a first prompt whose text_head contains "handoff" (path contains /handoffs/).
- A session's repo is its transcript's project directory (dirname of the .jsonl, above any /subagents/); events carry
  no cwd. Worktrees therefore count as separate repos for linking.
- Usage events are emitted after line events, so they are ordered by ts; tool_use events keep stream order.
Every metric carries source measured|derived; unavailable values are null with <field>_reason.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcripts as T  # noqa: E402

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
CONTINUED = "This session is being continued"


def _ctx(e):
    return e["input"] + e["cache_read"] + e["cache_creation"]


def _m(value, source, reason=None):
    return {"value": value, "source": source} if value is not None else {"value": None, "value_reason": reason, "source": source}


def _project(f):
    return os.path.dirname(f.split("/subagents/")[0])


def _main_usage(evs):
    u = [e for e in evs if e["kind"] == "usage" and e["agent"] == "main" and e["ts"] is not None]
    return sorted(u, key=lambda e: e["ts"])


def _before(usages, ts):
    prior = [u for u in usages if ts is None or u["ts"] <= ts]
    return _ctx(prior[-1]) if prior else None


def _resumed(evs, prev_reads, has_prev):
    mains = [e for e in evs if e["agent"] == "main"]
    uses = [e for e in mains if e["kind"] == "tool_use"]
    idx = next((i for i, u in enumerate(uses) if u["tool"] in EDIT_TOOLS), None)
    if idx is None:
        r = "no Edit/Write/NotebookEdit in session"
        return {"tokens_to_first_edit": _m(None, "measured", r), "seconds_to_first_edit": _m(None, "measured", r),
                "reads_before_first_edit": _m(None, "measured", r), "reread_overlap": _m(None, "derived", r)}
    edit = uses[idx]
    reads = [u["target"] for u in uses[:idx] if u["tool"] == "Read"]
    tss = [e["ts"] for e in mains if e["ts"] is not None]
    if edit["ts"] is None or not tss:
        tok = sec = _m(None, "measured", "first edit has no timestamp")
    else:
        tok = _m(sum(u["input"] + u["output"] + u["cache_read"] + u["cache_creation"]
                     for u in _main_usage(evs) if u["ts"] <= edit["ts"]), "measured")
        sec = _m(edit["ts"] - min(tss), "measured")
    if not has_prev:
        ov = _m(None, "derived", "no previous session linked")
    elif not reads:
        ov = _m(None, "derived", "no Read before first edit")
    else:
        uniq = set(reads)
        ov = _m(len(uniq & prev_reads) / len(uniq), "derived")
    return {"tokens_to_first_edit": tok, "seconds_to_first_edit": sec,
            "reads_before_first_edit": _m(len(reads), "measured"), "reread_overlap": ov}


def trace(events):
    by = {}
    for e in events:
        by.setdefault(e["session"], []).append(e)
    info = {}
    for sid, evs in by.items():
        tss = [e["ts"] for e in evs if e["ts"] is not None]
        info[sid] = {"evs": evs, "project": _project(evs[0]["file"]),
                     "first": min(tss) if tss else None, "last": max(tss) if tss else None}
    compactions, handoffs, sessions = [], [], []
    for sid in sorted(by):
        evs = info[sid]["evs"]
        mu = _main_usage(evs)
        for a, b in zip(mu, mu[1:]):
            if _ctx(b) < 0.5 * _ctx(a):
                compactions.append({"session": sid, "rule": "context_drop", "ts": b["ts"], "context_before": _ctx(a),
                                    "context_after": _ctx(b), "source": "derived"})
        for p in evs:
            if p["kind"] == "prompt" and p["agent"] == "main" and p["text_head"].startswith(CONTINUED):
                compactions.append({"session": sid, "rule": "continued_prompt", "ts": p["ts"],
                                    "context_before": _before(mu, p["ts"]), "source": "derived"})
        first = next((e for e in evs if e["kind"] == "prompt" and e["agent"] == "main"), None)
        row = {"session": sid}
        if first is not None and "handoff" in first["text_head"].lower():
            h = {"session": sid, "source": "derived"}
            prev = None
            if info[sid]["first"] is None:
                h["previous_session"] = None; h["previous_session_reason"] = "session has no timestamps"
            else:
                cands = [(i["last"], s) for s, i in info.items()
                         if s != sid and i["project"] == info[sid]["project"] and i["last"] is not None and i["last"] < info[sid]["first"]]
                if cands:
                    prev = max(cands)[1]
                    h["previous_session"] = prev
                    h["previous_context"] = _before(_main_usage(info[prev]["evs"]), None)
                else:
                    h["previous_session"] = None; h["previous_session_reason"] = "no earlier session in same project directory"
            handoffs.append(h)
            prev_reads = {e["target"] for e in info[prev]["evs"] if e["kind"] == "tool_use" and e["tool"] == "Read"} if prev else set()
            row["resumed"] = _resumed(evs, prev_reads, prev is not None)
        sessions.append(row)
    ctxs = [c["context_before"] for c in compactions if c["context_before"] is not None]
    ctxs += [h["previous_context"] for h in handoffs if h.get("previous_context") is not None]
    if ctxs:
        dist = {"min": min(ctxs), "median": statistics.median(ctxs), "max": max(ctxs), "n": len(ctxs), "source": "derived"}
    else:
        r = "no compaction or linked handoff with a known context size"
        dist = {"min": None, "min_reason": r, "median": None, "median_reason": r, "max": None, "max_reason": r, "n": 0, "source": "derived"}
    return {"compactions": compactions, "handoffs": handoffs, "context_at_handoff": dist, "sessions": sessions}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = trace(T.iter_events(a.root, a.repo, a.days))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
