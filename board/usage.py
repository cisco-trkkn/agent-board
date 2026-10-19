"""usage: index Claude Code transcripts into sqlite and report API-equivalent cost per project."""
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from artifacts import state_dir

HERE = Path(__file__).resolve().parent
SCHEMA = """
create table if not exists calls (request_id text primary key, session_id text, ts real, model text, effort text,
  agent_name text, team_name text, git_branch text, cwd text, sidechain int, subagent_file int,
  input int, output int, cache_read int, cache_write_5m int, cache_write_1h int);
create index if not exists calls_ts on calls(ts);
create index if not exists calls_session on calls(session_id, ts);
create table if not exists cost_state (session_id text primary key, ts real, total_usd real, model_usage text, unknown_model int);
create table if not exists files (path text primary key, inode int, size int, offset int, bad_lines int);
"""


def root():
    return Path(os.environ.get("USAGE_ROOT") or Path.home() / ".claude" / "projects")


def db_path():
    return state_dir() / "usage.sqlite"


def connect(path=None):
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10, check_same_thread=False)
    conn.execute("pragma journal_mode=wal")
    conn.executescript(SCHEMA)
    return conn


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


COLS = ["request_id", "session_id", "ts", "model", "effort", "agent_name", "team_name", "git_branch", "cwd",
        "sidechain", "subagent_file", "input", "output", "cache_read", "cache_write_5m", "cache_write_1h"]


def ingest(conn, path):
    """Read new complete lines of one transcript file; returns how many usage rows it upserted."""
    p = Path(path)
    st = p.stat()
    prev = conn.execute("select inode, size, offset, bad_lines from files where path=?", (str(p),)).fetchone()
    offset, bad = 0, 0
    if prev and prev[0] == st.st_ino and st.st_size >= prev[2]:
        if st.st_size == prev[1]:
            return 0
        offset, bad = prev[2], prev[3]
    with p.open("rb") as h:
        h.seek(offset)
        data = h.read(st.st_size - offset)
    end = data.rfind(b"\n") + 1
    sub = "/subagents/" in str(p)
    rows, costs, pos = [], [], offset
    for raw in data[:end].splitlines(keepends=True):
        try:
            d = json.loads(raw)
        except ValueError:
            bad += 1
            pos += len(raw)
            continue
        if d.get("type") == "cost-state" and d.get("sessionId"):
            costs.append((d["sessionId"], (d.get("startTime") or 0) / 1000, d.get("totalCostUSD"),
                          json.dumps(d.get("modelUsage") or {}), int(bool(d.get("hasUnknownModelCost")))))
        else:
            r = row_from_line(d, sub)
            if r:
                r["request_id"] = r["request_id"] or f"{r['session_id']}:{pos}"
                rows.append(tuple(r[c] for c in COLS))
        pos += len(raw)
    with conn:
        conn.executemany(f"insert or replace into calls ({','.join(COLS)}) values ({','.join('?' * len(COLS))})", rows)
        conn.executemany("insert or replace into cost_state values (?,?,?,?,?)", costs)
        conn.execute("insert or replace into files values (?,?,?,?,?)", (str(p), st.st_ino, st.st_size, offset + end, bad))
    return len(rows)


def load_prices():
    return json.loads((HERE / "prices.json").read_text())


def call_cost(r, prices):
    p = prices["models"].get(norm_model(r["model"]))
    if not p:
        return None
    return sum(r[k] * (p[k] or 0) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")) / 1e6


def context_tokens(r):
    return r["input"] + r["cache_read"] + r["cache_write_5m"] + r["cache_write_1h"]


def context_window(model, prices):
    p = prices["models"].get(norm_model(model))
    return p["context"] if p else prices.get("default_context", 200000)


def role(r):
    if r["agent_name"]:
        return "teammate"
    if r["sidechain"] or r["subagent_file"]:
        return "subagent"
    if "/.claude/worktrees/" in (r["cwd"] or ""):
        return "worker"
    return "lead"


def in_project(cwd, repo):
    repo = repo.rstrip("/")
    return cwd == repo or (cwd or "").startswith(repo + "/.claude/worktrees/")
