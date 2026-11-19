"""One-line Discord status text: pure builders, no I/O."""
import discord_feed
import usage

MAX = 128
STALE = 600
SEP = " · "


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pct(block):
    v = block.get("used_percentage") if isinstance(block, dict) else None
    return round(v) if _num(v) else None


def _limits(limits, now):
    """(w, f, resets_at); None for each unknown or stale field."""
    if not isinstance(limits, dict):
        return None, None, None
    ra = limits.get("received_at")
    if not _num(ra) or now - ra > STALE:
        return None, None, None
    sd = limits.get("seven_day")
    resets = sd.get("resets_at") if isinstance(sd, dict) else None
    return _pct(sd), _pct(limits.get("five_hour")), resets if _num(resets) else None


def _pace(w, resets_at, now):
    """Unrounded pace, or None when it is not meaningful (shown as —)."""
    if w is None or resets_at is None:
        return None
    elapsed = 1 - (resets_at - now) / 604800
    if elapsed < 12 / 168:
        return None
    return (w / 100) / elapsed


def _lead_ctx(live, repo, sid):
    """Context % of the project's lead: the row with `sid`, else the max role-lead row in the repo; None if none."""
    rows = [r for r in live or [] if isinstance(r, dict) and _num(r.get("context_pct"))]
    if sid:
        for r in rows:
            if r.get("session_id") == sid:
                return round(r["context_pct"])
    best = None
    for r in rows:
        if r.get("role") == "lead" and usage.in_project(r.get("cwd"), repo) and (best is None or r["context_pct"] > best):
            best = r["context_pct"]
    return None if best is None else round(best)


def _spec(lead_tasks, floor):
    """(name, "k/n" or "") of the running spec, None when idle."""
    runs = [t for t in lead_tasks or [] if isinstance(t, dict)
            and str(t.get("subject", "")).startswith(discord_feed._PLAN_RUN) and t.get("status") == "in_progress"]
    if not runs:
        return None
    run = min(runs, key=discord_feed._tid)
    prog = discord_feed.spec_progress(lead_tasks, floor)
    return discord_feed._spec_name(run["subject"]), (f"{prog[0]}/{prog[1]}" if prog else "")


def _head(w, f, pace, c_text, warn):
    wk = "?" if w is None else f"{w}"
    p = "?" if w is None else ("—" if pace is None else f"{pace:.1f}")
    return ("⚠ " if warn else "") + SEP.join([f"wk {wk}% ▲{p}×", f"5h {'?' if f is None else f}%", c_text])


def _warn(w, f, pace, c):
    return (pace is not None and pace > 1.2) or (f is not None and f >= 80) or (c is not None and c >= 40)


def _cap(s):
    return s if len(s) <= MAX else s[:MAX - 1] + "…"


def _fit(prefix, name, suffix):
    room = MAX - len(prefix) - len(suffix)
    if len(name) > room:
        name = name[:max(room - 1, 0)] + "…"
    return _cap(prefix + name + suffix)


def _spend(v):
    return "—" if not _num(v) else f"{v:.2f}"


def project_line(record, live, limits, lead_tasks, now, floor=None, lead_sid=""):
    w, f, resets = _limits(limits, now)
    pace = _pace(w, resets, now)
    c = _lead_ctx(live, record.get("path") or "", lead_sid)
    head = _head(w, f, pace, "ctx —" if c is None else f"ctx {c}%", _warn(w, f, pace, c))
    head += SEP + f"${_spend(record.get('spend_today'))}" + SEP
    spec = _spec(lead_tasks, floor)
    if spec is None:
        return _cap(head + "idle")
    name, prog = spec
    return _fit(head, name, " " + prog if prog else "")


def ops_line(records, live, limits, tasks_by_project, now, floors=None, lead_sids=None):
    w, f, resets = _limits(limits, now)
    pace = _pace(w, resets, now)
    best = None
    spends = []
    running = 0
    for r in records:
        name = r.get("project")
        c = _lead_ctx(live, r.get("path") or "", (lead_sids or {}).get(name, ""))
        if c is not None and (best is None or c > best[0]):
            best = (c, name)
        if _num(r.get("spend_today")):
            spends.append(r["spend_today"])
        if _spec((tasks_by_project or {}).get(name), (floors or {}).get(name)) is not None:
            running += 1
    c = best[0] if best else None
    ctx = "ctx max —" if best is None else f"ctx max {c}% {best[1]}"
    head = _head(w, f, pace, ctx, _warn(w, f, pace, c))
    total = f"${sum(spends):.2f}" if spends else "$—"
    return _cap(head + SEP + total + SEP + f"{running} running")


def _tmux(*args):
    """tmux stdout; raises on a missing session or tmux."""
    import subprocess
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=True, timeout=10).stdout


def main(argv=None, now=None, home=None):
    """Print each project's status line, then the ops line, from this Mac's live state. Reads only."""
    import sys
    import time
    from pathlib import Path
    import planview
    argv = sys.argv[1:] if argv is None else argv
    now = time.time() if now is None else now
    home = Path(home or Path.home() / ".claude")
    try:
        limits = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
    except Exception:   # noqa: BLE001 - no taps: the lines show "?"
        limits = None
    conn = usage.connect(usage.db_path())
    try:
        prices = usage.load_prices()
        live = usage.live_sessions(conn, prices, usage.thresholds()[0], now)
        records, tasks_by, floors, sids = [], {}, {}, {}
        for name in argv:
            try:
                path = _tmux("display", "-p", "-t", f"={name}:", "#{session_path}").strip()
            except Exception:   # noqa: BLE001
                path = ""
            if not path:
                print(f"project {name}: no session")
                continue
            sid, pid, started = planview.lead_entry(name, home, _tmux)
            tasks = planview.raw_live_list(home, sid, pid, started)[1]
            rec = {"project": name, "path": path,
                   "spend_today": usage.spend_since(conn, path, usage._midnight(now, 0), prices)}
            floor = discord_feed.spec_floor(name)
            records.append(rec)
            tasks_by[name], floors[name], sids[name] = tasks, floor, sid
            print(f"project {name}: " + project_line(rec, live, limits, tasks, now, floor=floor, lead_sid=sid))
        print("ops: " + ops_line(records, live, limits, tasks_by, now, floors=floors, lead_sids=sids))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
