"""Deterministic duplication and stagnation signals per session.

Input: normalised events from transcripts.iter_events. Output: {"sessions": [...]}.
Every metric object carries source measured|derived; unavailable values are null with value_reason.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcripts as T  # noqa: E402

BASH_READ_PREFIXES = ("cat ", "sed -n", "head ", "grep ")
READ_TOOLS = ("Read", "Grep", "Glob")


def _is_read(e):
    if e["tool"] in READ_TOOLS:
        return True
    t = e.get("target")
    return e["tool"] == "Bash" and isinstance(t, str) and t.startswith(BASH_READ_PREFIXES)


def _metric(value, source, reason=None):
    if value is None:
        return {"value": None, "value_reason": reason, "source": source}
    return {"value": value, "source": source}


def _session(evs):
    uses = [e for e in evs if e["kind"] == "tool_use"]
    results = {e["tool_use_id"]: e for e in evs if e["kind"] == "tool_result"}

    reads = {}
    for u in uses:
        if _is_read(u):
            ak = reads.setdefault((u["agent"], u["target"]), {})
            ak[u["args_key"]] = ak.get(u["args_key"], 0) + 1
    repeat_reads = [{"agent": a, "target": t, "count": sum(ak.values()), "distinct_args": len(ak),
                     "identical_count": max(ak.values())}
                    for (a, t), ak in sorted(reads.items(), key=lambda kv: (-sum(kv[1].values()), str(kv[0])))
                    if sum(ak.values()) >= 3]

    cmds, fails = {}, {}
    for u in uses:
        r = results.get(u["tool_use_id"])
        if r is None:
            continue
        if u["tool"] == "Bash":
            c = cmds.setdefault((u["args_key"], r["size"], bool(r["is_error"])), {"target": u["target"], "count": 0})
            c["count"] += 1
        if r["is_error"]:
            f = fails.setdefault((u["tool"], u["args_key"]), {"tool": u["tool"], "target": u["target"], "count": 0})
            f["count"] += 1
    repeat_commands = [dict(args_key=k[0], size=k[1], is_error=k[2], **v) for k, v in sorted(cmds.items(), key=lambda kv: (-kv[1]["count"], kv[0][0])) if v["count"] >= 2]
    repeat_failures = [dict(args_key=k[1], **v) for k, v in sorted(fails.items(), key=lambda kv: (-kv[1]["count"], kv[0])) if v["count"] >= 2]

    tool_sz = sum(e["size"] for e in evs if e["kind"] == "tool_result")
    other_sz = sum(e["size"] for e in evs if e["kind"] in ("prompt", "injection"))
    denom = tool_sz + other_sz
    share = _metric(tool_sz / denom if denom else None, "derived", "no tool_result, prompt or injection text in session")

    by_target = {}
    for u in uses:
        if u["tool"] == "Read":
            by_target.setdefault(u["target"], set()).add(u["agent"])
    cross = [{"target": t, "agents": sorted(a)} for t, a in sorted(by_target.items(), key=lambda kv: str(kv[0])) if len(a) >= 2]

    agents = sorted({e["agent"] for e in evs if not e["agent"] == "main" and e["agent"].split(":", 1)[0] in ("sub", "team")})
    idle = []
    for ag in agents:
        tss = [e["ts"] for e in evs if e["agent"] == ag and e["ts"] is not None]
        tu = [e["ts"] for e in uses if e["agent"] == ag and e["ts"] is not None]
        if not tss:
            m = _metric(None, "derived", "no timestamps for agent")
        elif not tu:
            m = _metric(None, "derived", "agent has no timestamped tool_use")
        else:
            m = _metric(max(tss) - max(tu), "derived")
        m["agent"] = ag
        idle.append(m)

    return {
        "session": evs[0]["session"],
        "repeat_reads": {"value": repeat_reads, "source": "measured"},
        "repeat_commands": {"value": repeat_commands, "source": "derived"},
        "repeat_failures": {"value": repeat_failures, "source": "measured"},
        "tool_output_share": share,
        "cross_agent_duplicate_reads": {"value": cross, "source": "measured"},
        "idle_tail_s": {"value": idle, "source": "derived"},
    }


def signals(events):
    by = {}
    for e in events:
        by.setdefault(e["session"], []).append(e)
    return {"sessions": [_session(by[s]) for s in sorted(by)]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = signals(T.iter_events(a.root, a.repo, a.days))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
