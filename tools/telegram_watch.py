#!/usr/bin/env python3
"""telegram_watch.py — the watchdog behind `tmux-ctl telegram watch --once` (launchd runs it every 60 s).

A lead started with `--channels plugin:telegram@claude-plugins-official` must have a telegram MCP server (server.ts)
among its descendants. When one is missing (Claude Code skipped the connection after a cached failure, or the server
died) the watchdog reconnects it through /mcp if the lead's pane is idle at its prompt, and sends a macOS banner (at
most once per lead per 15 minutes) when it could not. It does not use the board: tmux, ps and the pane's own text only.

State and log: ${TC_STATE:-~/.local/state/agent-board}/telegram-watch.{json,log}.
Off: TC_TELEGRAM_WATCH=0, or a file telegram-watch.off in that directory."""
import json
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import paneclass  # noqa: E402

CHANNEL = "plugin:telegram@claude-plugins-official"
NOTIFY_EVERY = 900      # seconds between two banners for one lead
GRACE = 45              # a lead younger than this may still be starting its servers
BUN_START = re.compile(r"\bbun run\b.*\bstart\b")   # the plugin's older launcher: bun run --cwd <plugin> start
VERSION_ARG0 = re.compile(r"^\d+\.\d+\.\d+$")

Proc = namedtuple("Proc", "pid ppid age args")


def state_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("TC_STATE") or Path.home() / ".local" / "state" / "agent-board")


def _etime(s):
    """ps etime ([[dd-]hh:]mm:ss) -> seconds."""
    days, _, rest = s.rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec + (int(days) * 86400 if days else 0)


def parse_ps(out):
    t = {}
    for line in out.splitlines():
        f = line.split(None, 3)
        if len(f) < 4:
            continue
        try:
            t[int(f[0])] = Proc(int(f[0]), int(f[1]), _etime(f[2]), f[3])
        except ValueError:
            continue
    return t


def read_table():
    r = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,args="], capture_output=True, text=True, timeout=15)
    return parse_ps(r.stdout)


def _is_claude(args):
    arg0 = args.split(None, 1)[0]
    base = os.path.basename(arg0)
    return base == "claude" or bool(VERSION_ARG0.match(base))


def find_leads(table):
    return [p.pid for p in table.values() if CHANNEL in p.args.split() and _is_claude(p.args)]


def descendants(pid, table):
    kids = {}
    for p in table.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    out, todo = [], list(kids.get(pid, []))
    while todo:
        n = todo.pop()
        out.append(n)
        todo += kids.get(n, [])
    return out


def _is_server(args):
    return "telegram" in args and ("server.ts" in args or bool(BUN_START.search(args)))


def has_server(pid, table):
    return any(_is_server(table[d].args) for d in descendants(pid, table))


def pane_of(pid, table, panes):
    """pane id of the tmux pane whose process is pid or one of its ancestors (panes: pane_pid -> pane id)."""
    seen = set()
    while pid in table and pid not in seen:
        if pid in panes:
            return panes[pid]
        seen.add(pid)
        pid = table[pid].ppid
    return panes.get(pid)


class State:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.notified = {int(k): float(v) for k, v in json.loads(self.path.read_text()).get("notified", {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            self.notified = {}

    def should_notify(self, pid, now):
        return now - self.notified.get(pid, -1e12) >= NOTIFY_EVERY

    def mark_notified(self, pid, now):
        self.notified[pid] = now
        self.save()

    def prune(self, live):
        gone = [p for p in self.notified if p not in live]
        for p in gone:
            del self.notified[p]
        if gone:
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"notified": {str(k): v for k, v in self.notified.items()}}))
            os.replace(tmp, self.path)
        except OSError:
            pass


# ---- the pane

def idle_at_prompt(cmd, rows, mod):
    """A claude pane that is ready (no spinner, no dialog) and whose input line is empty."""
    if paneclass.classify(cmd, rows, False, mod) != ("claude", "ready"):
        return False
    return not paneclass.input_has_text(rows)


class PaneCtl:
    def __init__(self, capture, send, sleep=time.sleep):
        self.capture, self.send, self.sleep = capture, send, sleep


def _menu_rows(rows, header):
    """The rows from the menu's header line down: a `❯ /mcp` line of the transcript above it is not the cursor."""
    for i, r in enumerate(rows):
        if header in r:
            return rows[i:]
    return []


def _cursor_row(rows, header):
    for r in _menu_rows(rows, header):
        if r.lstrip().startswith("❯"):
            return r
    return ""


def _menu_open(rows):
    return any("Esc to " in r for r in rows)


def _wait(ctl, pred, tries=12, step=0.25):
    for _ in range(tries):
        rows = ctl.capture()
        if pred(rows):
            return rows
        ctl.sleep(step)
    return None


def _back_out(ctl):
    """Escape while a menu is on screen, and no further: Escape twice at the prompt opens Rewind."""
    for _ in range(4):
        if not _menu_open(ctl.capture()):
            return
        ctl.send("Escape")
        ctl.sleep(0.3)


def reconnect(ctl, has_server, settle=8):
    """Drive /mcp -> telegram -> Reconnect by reading the menu. 'ok' or the reason it stopped (after Escape x3)."""
    def fail(why):
        _back_out(ctl)
        return why

    ctl.send("/mcp")
    ctl.sleep(0.8)                     # the slash-command list must settle before Enter
    ctl.send("Enter")
    rows = _wait(ctl, lambda r: any("Manage MCP servers" in x for x in r))
    if rows is None:
        if paneclass.input_has_text(ctl.capture()):
            ctl.send("C-u")                   # Enter was not taken: clear the typed /mcp
        return fail("menu did not open")
    for _ in range(25):
        if "plugin:telegram:telegram" in _cursor_row(rows, "Manage MCP servers"):
            break
        ctl.send("Down")
        ctl.sleep(0.3)
        rows = ctl.capture()
        if "Manage MCP servers" not in "\n".join(rows):
            return fail("menu changed while looking for telegram")
    else:
        return fail("telegram not in the /mcp list")
    ctl.send("Enter")
    rows = _wait(ctl, lambda r: any("MCP Server" in x and "elegram" in x for x in r))
    if rows is None:
        return fail("telegram detail menu did not open")
    for _ in range(6):
        cur = _cursor_row(rows, "MCP Server")
        if "Reconnect" in cur:
            break
        if not any("Reconnect" in x for x in _menu_rows(rows, "MCP Server")):
            return fail("no Reconnect option")
        ctl.send("Down")
        ctl.sleep(0.3)
        rows = ctl.capture()
    else:
        return fail("could not reach Reconnect")
    ctl.send("Enter")
    for _ in range(settle * 2):
        ctl.sleep(0.5)
        if has_server():
            return "ok"
    return "no server after reconnect"


# ---- one pass

def watch_once(env=None, now=None, table=None, panes=None, pane_idle=None, do_reconnect=None, notify=None):
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    sd = state_dir(env)
    if env.get("TC_TELEGRAM_WATCH") == "0" or (sd / "telegram-watch.off").exists():
        return []
    table = read_table() if table is None else table
    leads = find_leads(table)
    st = State(sd / "telegram-watch.json")
    st.prune(set(leads))
    lines = []

    def log(msg):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))} {msg}"
        lines.append(line)
        try:
            sd.mkdir(parents=True, exist_ok=True)
            with open(sd / "telegram-watch.log", "a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    need = [p for p in leads if table[p].age >= GRACE and not has_server(p, table)]
    if not need:
        return lines
    if panes is None:
        panes = tmux_panes()
    for pid in sorted(need):
        pane = pane_of(pid, table, panes)
        why = ""
        if pane is None:
            why = "no tmux pane"
        elif (pane_idle or _pane_idle)(pane):
            res = (do_reconnect or _do_reconnect)(pane)
            log(f"lead pid {pid} pane {pane}: telegram server missing, reconnect: {res}")
            if res == "ok":
                continue
            why = f"reconnect failed ({res})"
        else:
            why = "pane busy or has typed text"
            log(f"lead pid {pid} pane {pane}: telegram server missing, {why}, not typing")
        if pane is None:
            log(f"lead pid {pid}: telegram server missing, {why}")
        if st.should_notify(pid, now):
            st.mark_notified(pid, now)
            (notify or _notify)("Telegram is down", f"lead pid {pid}: {why}. Run /mcp and reconnect telegram.")
            log(f"lead pid {pid}: notified")
    return lines


# ---- the real world

def _tmux():
    return paneclass.tmux_runner()


def tmux_panes():
    try:
        out = _tmux()("list-panes", "-a", "-F", "#{pane_pid} #{pane_id}")
    except (OSError, subprocess.SubprocessError):
        return {}
    d = {}
    for line in out.splitlines():
        a, _, b = line.partition(" ")
        if a.isdigit() and b:
            d[int(a)] = b.strip()
    return d


def _rows(pane):
    t = _tmux()
    return [l.rstrip() for l in t("capture-pane", "-p", "-J", "-t", pane, "-S", "-40").splitlines()]


def _pane_idle(pane):
    t = _tmux()
    cmd = t("display", "-p", "-t", pane, "#{pane_current_command}").strip()
    rows = _rows(pane)
    while rows and not rows[-1]:
        rows.pop()
    return idle_at_prompt(cmd, rows, paneclass.mod_states().get(pane))


def _do_reconnect(pane):
    t = _tmux()

    def send(*keys):
        for k in keys:
            if k == "/mcp":
                t("send-keys", "-t", pane, "-l", "/mcp")
            else:
                t("send-keys", "-t", pane, k)

    # the pane may have changed since the idle check: look again right before typing
    if not _pane_idle(pane):
        return "pane no longer idle"
    pid = int(t("display", "-p", "-t", pane, "#{pane_pid}").strip() or 0)

    def server():
        tbl = read_table()
        lead = [p for p in find_leads(tbl) if pane_of(p, tbl, {pid: pane}) == pane]
        return bool(lead) and all(has_server(p, tbl) for p in lead)

    return reconnect(PaneCtl(lambda: _rows(pane), send), server)


def _notify(title, text):
    if sys.platform != "darwin" or os.environ.get("TC_NOTIFY") == "0":
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
        import notify as board_notify
        subprocess.run(board_notify.banner_argv(title, text), capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001 - a banner that fails is not worth failing the watchdog
        pass


def main(argv):
    if argv[:1] == ["--once"] or not argv:
        for line in watch_once():
            print(line)
        return 0
    print("usage: telegram_watch.py --once", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
