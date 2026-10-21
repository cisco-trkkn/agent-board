"""usage: index Claude Code transcripts into sqlite and report API-equivalent cost per project."""
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from artifacts import state_dir

HERE = Path(__file__).resolve().parent
DEFAULT_ALERTS = {"context_pct": 80, "burn_per_hour": 15, "burn_window_s": 900, "session_total": 25,
                  "mismatch_efforts": ["low", "medium"], "mismatch_models": ["opus", "fable"], "live_s": 1800}
ALERTS_PATH = None   # tests may point this at a file; None = alerts_path()


def alerts_path():
    """~/.config/agent-board/usage-alerts.json if it exists, else the legacy ~/.claude/usage-alerts.json."""
    new = Path.home() / ".config" / "agent-board" / "usage-alerts.json"
    return new if new.exists() else Path.home() / ".claude" / "usage-alerts.json"
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
    if prev and prev[0] == st.st_ino and st.st_size >= prev[1]:
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
            if not isinstance(d, dict):
                raise ValueError("not an object")
        except (ValueError, RecursionError):   # not JSON, or nested too deep to parse
            bad += 1
            pos += len(raw)
            continue
        if d.get("type") == "cost-state" and d.get("sessionId"):
            costs.append((d["sessionId"], (d.get("startTime") or 0) / 1000, d.get("totalCostUSD"),
                          json.dumps(d.get("modelUsage") or {}), int(bool(d.get("hasUnknownModelCost")))))
        else:
            r = row_from_line(d, sub)
            if r:
                r["request_id"] = r["request_id"] or f"{p}:{pos}"
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


def _valid_threshold(default, v):
    if isinstance(default, list):
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def thresholds(path=None):
    """(alert thresholds, warning or None). A missing file is the defaults; a bad one is the defaults plus a warning."""
    th = dict(DEFAULT_ALERTS)
    p = Path(path or ALERTS_PATH or alerts_path())
    if not p.exists():
        return th, None
    try:
        d = json.loads(p.read_text())
        if not isinstance(d, dict):
            raise ValueError("expected a JSON object")
    except (OSError, ValueError) as e:
        return th, f"{p.name} unreadable, using defaults: {str(e).splitlines()[0] if str(e) else type(e).__name__}"
    bad = []
    for k, v in d.items():
        if k not in DEFAULT_ALERTS:
            continue
        if _valid_threshold(DEFAULT_ALERTS[k], v):
            th[k] = v
        else:
            bad.append(k)
    return th, (f"{p.name}: ignoring invalid {', '.join(bad)}, using defaults" if bad else None)


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _usd(r, prices):
    return call_cost(r, prices) or 0.0


def _family(model):
    parts = norm_model(model).split("-")
    return parts[1] if len(parts) > 1 else ""


def _live_entry(conn, sid, prices, th, now):
    newest = _rows(conn, "select * from calls where session_id=? order by ts desc limit 1", (sid,))[0]
    window = max(th["burn_window_s"], 3600)
    recent = _rows(conn, "select * from calls where session_id=? and ts >= ?", (sid, now - window))
    last_hour = sum(_usd(r, prices) for r in recent if r["ts"] >= now - 3600)
    burn_spend = sum(_usd(r, prices) for r in recent if r["ts"] >= now - th["burn_window_s"])
    cs = conn.execute("select total_usd from cost_state where session_id=?", (sid,)).fetchone()
    if cs and cs[0] is not None:
        total = cs[0]
    else:
        total = sum(_usd(r, prices) for r in _rows(conn, "select * from calls where session_id=?", (sid,)))
    ctx = context_tokens(newest)
    pct = round(100 * ctx / context_window(newest["model"], prices))
    rl = role(newest)
    name = newest["agent_name"] or (os.path.basename(newest["cwd"].rstrip("/")) if rl == "worker" else None) or sid[:8]
    alerts = []
    if pct >= th["context_pct"]:
        alerts.append({"kind": "context", "label": f"ctx {pct}%",
                       "detail": f"Context is {pct}% of the model window (alert at {th['context_pct']}%)."})
    per_hour = burn_spend * 3600 / th["burn_window_s"]
    if per_hour > th["burn_per_hour"]:
        alerts.append({"kind": "burn", "label": f"${per_hour:.0f}/h",
                       "detail": f"Spending ${per_hour:.2f}/h over the last {th['burn_window_s'] // 60} min (alert above ${th['burn_per_hour']}/h)."})
    if total > th["session_total"]:
        alerts.append({"kind": "total", "label": f"${total:.0f} total",
                       "detail": f"Session total ${total:.2f} is over the ${th['session_total']} alert."})
    if (newest["agent_name"] and newest["effort"] in th["mismatch_efforts"]
            and _family(newest["model"]) in th["mismatch_models"]):
        alerts.append({"kind": "model_mismatch", "label": f"{_family(newest['model'])}@{newest['effort']}",
                       "detail": f"A teammate runs {_family(newest['model'])} at {newest['effort']} effort; "
                                 f"a cheaper model or higher effort may fit (alert on {'/'.join(th['mismatch_models'])} at {'/'.join(th['mismatch_efforts'])})."})
    return {"session_id": sid, "name": name, "role": rl, "model": newest["model"], "effort": newest["effort"],
            "agent_name": newest["agent_name"], "cwd": newest["cwd"], "context": ctx, "context_pct": pct,
            "last_hour": last_hour, "total": total, "alerts": alerts}


def live_sessions(conn, prices, th, now):
    """Every session whose newest call is less than live_s old, with its computed alerts."""
    sids = [r[0] for r in conn.execute("select session_id, max(ts) from calls where ts > ? group by session_id order by 2 desc",
                                       (now - th["live_s"],))]
    return [_live_entry(conn, sid, prices, th, now) for sid in sids]


def _midnight(now, days_back):
    d = datetime.fromtimestamp(now).date() - timedelta(days=days_back)
    return datetime.combine(d, dtime.min).timestamp()


def _breakdown(rows, keyfn, prices, extra=None):
    acc = {}
    for r in rows:
        e = acc.setdefault(keyfn(r), {"usd": 0.0, "calls": 0, "unpriced": 0, "cache": 0, "input_side": 0})
        c = call_cost(r, prices)
        if c is None:
            e["unpriced"] += 1
        else:
            e["usd"] += c
        e["calls"] += 1
        e["cache"] += r["cache_read"]
        e["input_side"] += context_tokens(r)
    out = []
    for k, e in acc.items():
        # an all-unpriced row is "unpriced", never $0
        item = {"key": k, "usd": None if e["unpriced"] == e["calls"] else e["usd"], "calls": e["calls"],
                "unpriced": e["unpriced"]}
        if extra:
            item["cache_share"] = e["cache"] / e["input_side"] if e["input_side"] else 0.0
        out.append(item)
    return sorted(out, key=lambda x: (x["usd"] is None, -(x["usd"] or 0)))


def report(conn, repo, prices, th, now):
    """The api/usage payload for one project (everything but the threshold warning)."""
    repo = repo.rstrip("/")
    prefix = repo + "/.claude/worktrees/"
    month_start = _midnight(now, 29)
    rows = _rows(conn, "select * from calls where ts >= ? and (cwd = ? or substr(cwd, 1, ?) = ?)",
                 (month_start, repo, len(prefix), prefix))
    today_start, week_start = _midnight(now, 0), _midnight(now, 6)
    headline = {"today": 0.0, "week": 0.0, "month": 0.0, "unpriced_calls": 0}
    days = {(datetime.fromtimestamp(now).date() - timedelta(days=i)).isoformat(): {} for i in range(29, -1, -1)}
    for r in rows:
        c = call_cost(r, prices)
        if c is None:
            headline["unpriced_calls"] += 1
            continue
        headline["month"] += c
        if r["ts"] >= week_start:
            headline["week"] += c
        if r["ts"] >= today_start:
            headline["today"] += c
        day = days.get(datetime.fromtimestamp(r["ts"]).date().isoformat())
        if day is not None:
            day[r["model"]] = day.get(r["model"], 0.0) + c
    live = [e for e in live_sessions(conn, prices, th, now) if in_project(e["cwd"], repo)]
    alerts = [dict(a, session=e["name"]) for e in live for a in e["alerts"]]
    return {"headline": headline, "alerts": alerts, "live": live,
            "daily": [{"date": d, "by_model": m} for d, m in days.items()],
            "by_role": _breakdown(rows, role, prices),
            "by_model": _breakdown(rows, lambda r: r["model"], prices, extra=True),
            "by_branch": _breakdown(rows, _branch_key, prices)}


def _branch_key(r):
    if r["git_branch"]:
        return r["git_branch"]
    cwd = r["cwd"] or ""
    if "/.claude/worktrees/" in cwd:
        return cwd.split("/.claude/worktrees/", 1)[1].split("/")[0]
    return "(none)"


class Indexer:
    """Keeps the sqlite index current and an in-memory snapshot of live sessions.

    One sqlite connection, created lazily and used only by the thread that scans.
    """

    def __init__(self, root, db, alerts_path=None, on_snapshot=None):
        self.root, self.db = Path(root), Path(db)
        self.alerts_path = alerts_path   # None: resolved on each pass
        self.on_snapshot = on_snapshot
        self.error = None
        self.warning = None
        self.thread = None
        self._conn = None
        self._lock = threading.Lock()
        self._snapshot = []
        self._progress = {"done": 0, "total": 0}
        self._stop = threading.Event()
        self._first_pass_done = False
        self._logged = set()

    def _log_once(self, where, e):
        key = (str(where), f"{type(e).__name__}: {e}")
        if key not in self._logged:   # a broken file must not repeat itself every 5 s
            self._logged.add(key)
            print(f"usage indexer: {where}: {key[1]}", file=sys.stderr, flush=True)

    def files(self):
        found = list(self.root.glob("*/*.jsonl")) + list(self.root.glob("*/*/subagents/*.jsonl"))
        stamped = []
        for p in found:
            try:
                st = p.stat()
            except OSError:   # vanished between glob and stat
                continue
            stamped.append((st.st_mtime, st.st_size, p))
        return sorted(stamped, key=lambda t: t[0], reverse=True)

    def scan(self):
        """One pass, newest file first. A failing file is recorded in `error`; the pass goes on."""
        error = None
        files = self.files()
        with self._lock:
            if not self._first_pass_done:
                self._progress = {"done": 0, "total": sum(sz for _, sz, _ in files)}
        try:
            if self._conn is None:
                self._conn = connect(self.db)
            for _, size, p in files:
                try:
                    ingest(self._conn, p)
                except Exception as e:   # noqa: BLE001 - one bad file must not stop the pass
                    error = f"{p.name}: {type(e).__name__}: {e}"
                    self._log_once(p, e)
                with self._lock:
                    if self._progress is not None:
                        self._progress["done"] += size
            prices = load_prices()
            th, self.warning = thresholds(self.alerts_path)
            live = live_sessions(self._conn, prices, th, time.time())
            with self._lock:
                self._snapshot = live
                self._first_pass_done = True
                self._progress = None   # backfill is over: later passes are cheap and must not flicker the UI
            if self.on_snapshot:
                try:
                    self.on_snapshot(live)
                except Exception as e:   # noqa: BLE001 - a tmux hiccup must not stop indexing
                    self._log_once("on_snapshot", e)
        except Exception as e:   # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            self._log_once(self.root, e)
        self.error = error

    def progress(self):
        """{done, total} bytes during the first pass, None once it has completed."""
        with self._lock:
            return dict(self._progress) if self._progress is not None else None

    def snapshot(self):
        with self._lock:
            return list(self._snapshot)

    def start(self, interval=5.0):
        def loop():
            while not self._stop.is_set():
                self.scan()
                self._stop.wait(interval)
        self.thread = threading.Thread(target=loop, name="usage-indexer", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(10)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


EFFORT_ABBR = {"low": "low", "medium": "med", "high": "high", "max": "max"}


def _project_live(s, live):
    repo = s.get("path") or ""
    return [e for e in live if repo and in_project(e.get("cwd"), repo)]   # every rule looks only at this project's sessions


def _agent_windows(s, mine):
    """Yield (window, pane, live entry or None) for each agent window of card s.

    `mine` is newest-first (live_sessions order), already scoped to the project. Rules: a teammate window
    "✦ <name>" matches the session whose agent_name is <name>; a worker pane matches a session without
    agent_name by cwd == pane path; the `claude` window's first pane matches the newest session without
    agent_name whose cwd is the repo. Other windows are not agent windows and are skipped.
    """
    repo = s.get("path") or ""
    for w in s.get("windows", []):
        panes = w.get("panes") or []
        if not panes:
            continue
        hit, target = None, panes[0]
        if w.get("teammate"):
            name = re.sub(r"^✦\s*", "", w.get("name", ""))
            hit = next((e for e in mine if e.get("agent_name") == name), None)
        elif w.get("worker"):
            for pane in panes:
                hit = next((e for e in mine if not e.get("agent_name") and e.get("cwd") == pane.get("path")), None)
                if hit:
                    target = pane
                    break
        elif w.get("name") == "claude":
            hit = next((e for e in mine if not e.get("agent_name") and e.get("cwd") == repo), None)
        else:
            continue
        yield w, target, hit


def card_alerts(sessions, live):
    """Attach usage alerts to board cards: s["usage_alerts"] = {pane id: [alerts]}, s["usage_alert_count"].

    Matching is _agent_windows'. The count covers every live session in the project, matched or not, so it
    equals the number of alerts the Usage tab lists.
    """
    for s in sessions:
        mine = _project_live(s, live)
        s["usage_alerts"] = {p["id"]: e["alerts"] for _, p, e in _agent_windows(s, mine) if e and e.get("alerts")}
        s["usage_alert_count"] = sum(len(e.get("alerts") or []) for e in mine)
    return sessions


def card_labels(sessions, live):
    """s["usage_labels"] = {pane id: {role, model, effort, label}} for matched agent windows.

    Returns {pane id: entry or None} for every agent window, so sync_labels can unset unmatched ones.
    Label: "<window name> · <family>" plus "·<effort>" when there is one.
    """
    wanted = {}
    for s in sessions:
        labels = {}
        for w, p, e in _agent_windows(s, _project_live(s, live)):
            if e is None:
                wanted[p["id"]] = None
                continue
            fam = _family(e.get("model") or "")
            eff = e.get("effort") or ""
            eff = EFFORT_ABBR.get(eff, eff)
            text = f"{w.get('name', '')} · {fam}" + (f"·{eff}" if eff else "")
            labels[p["id"]] = wanted[p["id"]] = {"role": e.get("role") or "", "model": fam, "effort": eff, "label": text}
        s["usage_labels"] = labels
    return wanted
