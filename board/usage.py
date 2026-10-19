"""usage: index Claude Code transcripts into sqlite and report API-equivalent cost per project."""
import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm_model(m):
    return re.sub(r"-\d{8}$", "", re.sub(r"\[1m\]$", "", m or ""))


def _epoch(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def row_from_line(d, subagent_file):
    """A usage-bearing assistant line as a calls row (dict), or None."""
    m = d.get("message") or {}
    u = m.get("usage")
    if not u or m.get("model") in (None, "<synthetic>"):
        return None
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:   # no split: count it all as 5m
        w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
    return {"request_id": d.get("requestId"), "session_id": d.get("sessionId"), "ts": _epoch(d.get("timestamp")),
            "model": norm_model(m["model"]), "effort": d.get("effort"), "agent_name": d.get("agentName"),
            "team_name": d.get("teamName"), "git_branch": d.get("gitBranch"), "cwd": d.get("cwd") or "",
            "sidechain": int(bool(d.get("isSidechain"))), "subagent_file": int(bool(subagent_file)),
            "input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
            "cache_read": u.get("cache_read_input_tokens") or 0, "cache_write_5m": w5 or 0, "cache_write_1h": w1 or 0}


def load_prices():
    return json.loads((HERE / "prices.json").read_text())


def call_cost(r, prices):
    p = prices["models"].get(norm_model(r["model"]))
    if not p:
        return None
    return sum(r[k] * (p[k] or 0) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")) / 1e6
