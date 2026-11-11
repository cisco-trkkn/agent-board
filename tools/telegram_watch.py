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
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import namedtuple
from datetime import datetime
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
    """claude processes started with the telegram channel, as `--channels plugin:telegram@…` or `--channels=plugin:…`."""
    def has_channel(args):
        w = args.split()
        return CHANNEL in w or f"--channels={CHANNEL}" in w
    return [p.pid for p in table.values() if has_channel(p.args) and _is_claude(p.args)]


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


BACKOFF_FIRST, BACKOFF_CAP = 60, 1800   # seconds between reconnect attempts: 60, 120, 240 ... capped at 30 min


class State:
    """notified: pid -> last banner time. tries: pid -> {"n": failed attempts in a row, "next": earliest next attempt}."""

    def __init__(self, path):
        self.path = Path(path)
        self.notified, self.tries = {}, {}
        try:
            d = json.loads(self.path.read_text())
            self.notified = {int(k): float(v) for k, v in d.get("notified", {}).items()}
            self.tries = {int(k): {"n": int(v["n"]), "next": float(v["next"])} for k, v in d.get("tries", {}).items()}
        except (OSError, ValueError, AttributeError, TypeError, KeyError):
            self.notified, self.tries = {}, {}

    def should_notify(self, pid, now):
        return now - self.notified.get(pid, -1e12) >= NOTIFY_EVERY

    def mark_notified(self, pid, now):
        self.notified[pid] = now
        self.save()

    def may_try(self, pid, now):
        return now >= self.tries.get(pid, {"next": 0})["next"]

    def failed(self, pid, now):
        """Record a failed reconnect; returns how many in a row. The next attempt waits 60 s, then 120, 240 ... up to 30 min."""
        n = self.tries.get(pid, {"n": 0})["n"] + 1
        self.tries[pid] = {"n": n, "next": now + min(BACKOFF_FIRST * 2 ** (n - 1), BACKOFF_CAP)}
        self.save()
        return n

    def alive(self, pid):
        """A server was seen under this lead: forget its failures."""
        if self.tries.pop(pid, None) is not None:
            self.save()

    def prune(self, live):
        gone = [p for p in set(self.notified) | set(self.tries) if p not in live]
        for p in gone:
            self.notified.pop(p, None)
            self.tries.pop(p, None)
        if gone:
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"notified": {str(k): v for k, v in self.notified.items()},
                                       "tries": {str(k): v for k, v in self.tries.items()}}))
            os.replace(tmp, self.path)
        except OSError:
            pass


# ---- the pane

def _spinner_above_input(rows, span=8):
    """True when a spinner line (`✽ Actioning…`, `✻ Thinking… (3s …)`) sits in the few rows above the input box. Stricter than
    paneclass: its first-frame rule ignores a spinner followed by a `⎿ Tip:` row, which is how a turn starts (real 2.1.322
    capture in fixtures/telegram-watch/working.txt); calling that idle would type into a working lead."""
    tail = rows[-30:]
    for n in range(len(tail) - 1, 0, -1):
        if paneclass.INPUT_RE.match(tail[n]) and paneclass.RULE_RE.match(tail[n - 1]):
            return any(paneclass.SPINNER_RE.match(r) or paneclass.SPINNER_FIRST_RE.match(r) for r in tail[max(0, n - 1 - span):n - 1])
    return False


def idle_at_prompt(cmd, rows, mod):
    """A claude pane that is ready (no spinner, no dialog) and whose input line is empty."""
    if paneclass.classify(cmd, rows, False, mod) != ("claude", "ready"):
        return False
    return not paneclass.input_has_text(rows) and not _spinner_above_input(rows)


COMMAND = "/mcp reconnect plugin:telegram:telegram"
QUIET_GAP = 3      # seconds between the two captures that must show an untouched, empty input line (TC_TELEGRAM_WATCH_QUIET)
NOT_TYPED = "pane busy or has typed text"
QUIET_GAP_MAX = 10 # TC_TELEGRAM_WATCH_QUIET is capped here: it was a 30 s activity window before it became the gap
NOT_QUIET = "input line not quiet (busy, typed text or changing)"


def input_text(rows):
    """The text on Claude's input line (the `❯` line right below a full-width rule, lowest first), '' when empty,
    None when there is no input line. Same screen rules as paneclass.input_has_text."""
    tail = rows[-30:]
    for n in range(len(tail) - 1, -1, -1):
        m = paneclass.INPUT_RE.match(tail[n])
        if not m:
            continue
        boxed = tail[n].lstrip()[:1] in ("│", "|")
        if not boxed and not (n > 0 and paneclass.RULE_RE.match(tail[n - 1])):
            continue
        txt = m.group(1)
        return "" if txt.startswith('Try "') else txt
    return None


def input_frame(rows):
    """The input box as drawn: the rule above the input line, the line itself and the rule below it (when there is one).
    The status rows under the box (ctx %, usage) redraw on their own, so they are left out. None when there is no input line."""
    tail = rows[-30:]
    for n in range(len(tail) - 1, 0, -1):
        if paneclass.INPUT_RE.match(tail[n]) and paneclass.RULE_RE.match(tail[n - 1]):
            below = tail[n + 1] if n + 1 < len(tail) and paneclass.RULE_RE.match(tail[n + 1]) else ""
            return (tail[n - 1], tail[n], below)
    return None


def quiet_gap(env=None):
    """Seconds between the two quiet captures: TC_TELEGRAM_WATCH_QUIET (0..QUIET_GAP_MAX), QUIET_GAP when unset or not a number."""
    env = os.environ if env is None else env
    try:
        v = float(env.get("TC_TELEGRAM_WATCH_QUIET") or QUIET_GAP)
    except ValueError:
        v = QUIET_GAP
    return min(max(v, 0), QUIET_GAP_MAX)


def unsafe_reason(in_mode):
    return "pane in copy mode" if in_mode else None


class PaneCtl:
    """What reconnect() needs from a pane: capture() -> rows, type_text(t), enter(), clear(), check() -> reason or None,
    pane_idle() -> bool, sleep(s), remove(back, count): delete count characters that end `back` characters before the end
    of the input line (End, Left x back, Backspace x count)."""

    def __init__(self, capture, type_text, enter, clear, check, pane_idle, sleep=time.sleep, remove=None):
        self.capture, self.type_text, self.enter, self.clear = capture, type_text, enter, clear
        self.check, self.pane_idle, self.sleep, self.remove = check, pane_idle, sleep, remove


def _remove_command(ctl, line):
    """The line did not read back as the command: take our text out and keep the user's. Done only when the line holds the
    command once; afterwards the line must be exactly the user's own text, else it is left as it is and the caller notifies."""
    left_as_is = "input changed while typing, line left as is"
    if not line or line.count(COMMAND) != 1 or ctl.remove is None:
        return left_as_is
    before, _, after = line.partition(COMMAND)
    ctl.remove(len(after), len(COMMAND))
    ctl.sleep(0.3)
    if input_text(ctl.capture()) != before + after:
        return left_as_is
    return "input changed while typing"


def reconnect(ctl, has_server, settle=8, quiet_gap=QUIET_GAP):
    """Type `/mcp reconnect plugin:telegram:telegram` and Enter into an idle pane. 'ok', 'no server after reconnect' (the
    command ran) or why nothing was sent. The pane is checked again right before typing; after typing, the input line must
    read back exactly the command (the user may have started typing) or no Enter is sent and only our command text is
    removed from the line, so what the user typed stays."""
    why = ctl.check()
    if why:
        return why
    # nobody is typing: two captures quiet_gap apart, both idle with an empty input line, the input box identical
    first = ctl.capture()
    if not idle_at_prompt("claude", first, None) or input_text(first) != "":
        return NOT_QUIET
    ctl.sleep(quiet_gap)
    second = ctl.capture()
    if not idle_at_prompt("claude", second, None) or input_text(second) != "" or input_frame(first) != input_frame(second):
        return NOT_QUIET
    why = ctl.check()
    if why:
        return why
    if not ctl.pane_idle() or input_text(ctl.capture()) != "":
        return NOT_TYPED
    ctl.type_text(COMMAND)
    ctl.sleep(0.3)                  # the slash-command list needs a moment before Enter submits
    line = input_text(ctl.capture())
    if line != COMMAND:
        return _remove_command(ctl, line)
    ctl.enter()
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

    grace = float(env.get("TC_TELEGRAM_WATCH_GRACE") or GRACE)
    for pid in leads:
        if has_server(pid, table):
            st.alive(pid)
    need = [p for p in leads if table[p].age >= grace and not has_server(p, table) and st.may_try(p, now)]
    if not need:
        return lines
    if panes is None:
        panes = tmux_panes()
    for pid in sorted(need):
        pane = pane_of(pid, table, panes)
        why = ""
        if pane is None:
            why = "no tmux pane"
            log(f"lead pid {pid}: telegram server missing, {why}")
        elif not (pane_idle or _pane_idle)(pane):
            why = NOT_TYPED
            log(f"lead pid {pid} pane {pane}: telegram server missing, {why}, not typing")
        else:
            res = (do_reconnect or _do_reconnect)(pane)
            log(f"lead pid {pid} pane {pane}: telegram server missing, reconnect: {res}")
            if res == "ok":
                st.alive(pid)
                continue
            if res == "no server after reconnect":      # the command ran and did not help: back off, one banner
                if st.failed(pid, now) == 1:
                    (notify or _notify)("Telegram is down", f"lead pid {pid}: reconnect did not bring the server back; retrying with backoff. Check /mcp.")
                    log(f"lead pid {pid} pane {pane}: notified, backing off")
                continue
            why = res                                   # nothing was typed: same as a busy pane
        if st.should_notify(pid, now):
            st.mark_notified(pid, now)
            (notify or _notify)("Telegram is down", f"lead pid {pid}: {why}. Run /mcp reconnect plugin:telegram:telegram.")
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


SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")


def _dim_flips(params, dim):
    """Dim state after one SGR sequence: 2 turns it on; 22 and 0 (or an empty list) turn it off."""
    for n in (params.split(";") if params else ["0"]):
        if n == "2":
            dim = True
        elif n in ("0", "22", ""):
            dim = False
    return dim


def _plain_line(line):
    """The line without escape sequences; on an input line (`❯ …`) also without its dim text, which is Claude's greyed
    prompt suggestion (real 2.1.322 capture: fixtures/telegram-watch/real-ghost-suggestion.ansi), not typed text."""
    out, dim, pos, plain = [], False, 0, ANSI_RE.sub("", line)
    ghostable = bool(paneclass.INPUT_RE.match(plain))
    for m in ANSI_RE.finditer(line):
        out.append((line[pos:m.start()], dim))
        sgr = SGR_RE.fullmatch(m.group())
        if sgr:
            dim = _dim_flips(sgr.group(1), dim)
        pos = m.end()
    out.append((line[pos:], dim))
    return "".join(t for t, d in out if not (d and ghostable)).rstrip()


def plain_rows(text):
    """Rows from a `capture-pane -p -e -J` capture: escapes removed, dim text on the input line dropped (a prompt suggestion)."""
    rows = [_plain_line(l) for l in text.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return rows


def _rows(pane):
    return plain_rows(_tmux()("capture-pane", "-p", "-e", "-J", "-t", pane, "-S", "-40"))


def _pane_idle(pane):
    # the pane holds a claude process (find_leads found it by its command line), whatever tmux calls the command
    # (a bare version number, node...): classify it as claude
    return idle_at_prompt("claude", _rows(pane), paneclass.mod_states().get(pane))


def _do_reconnect(pane):
    t = _tmux()

    def check():
        f = t("display", "-p", "-t", pane, "#{pane_in_mode} #{pane_pid}").split()
        if len(f) < 2:
            return "pane not found"
        return unsafe_reason(f[0] != "0")

    pid = int((t("display", "-p", "-t", pane, "#{pane_pid}").strip() or "0"))

    def leads():
        tbl = read_table()
        return tbl, [p for p in find_leads(tbl) if pane_of(p, tbl, {pid: pane}) == pane]

    if not leads()[1]:
        return "lead has gone"           # never type into a shell prompt

    def server():
        tbl, lead = leads()
        return bool(lead) and all(has_server(p, tbl) for p in lead)

    def remove(back, count):
        keys = ["End"] + ["Left"] * back + ["BSpace"] * count
        t("send-keys", "-t", pane, *keys)

    ctl = PaneCtl(lambda: _rows(pane),
                  lambda text: t("send-keys", "-t", pane, "-l", text),
                  lambda: t("send-keys", "-t", pane, "Enter"),
                  lambda: t("send-keys", "-t", pane, "C-u"),
                  check, lambda: _pane_idle(pane), remove=remove)
    return reconnect(ctl, server, quiet_gap=quiet_gap())


def _notify(title, text):
    if sys.platform != "darwin" or os.environ.get("TC_NOTIFY") == "0":
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
        import notify as board_notify
        subprocess.run(board_notify.banner_argv(title, text), capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001 - a banner that fails is not worth failing the watchdog
        pass


# ---- the launchd job (every 60 s), same shape as `agent-worktrees schedule`

LABEL = "com.user.agent-board-telegram-watch"


def _home():
    return Path(os.environ.get("TW_HOME") or Path.home())


def _plist_path(home=None):
    return Path(home or _home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_text(cli_path, home):
    """The LaunchAgent plist (bytes): `<cli_path> telegram watch --once` every 60 seconds."""
    log = f"{home}/.local/state/agent-board/telegram-watch.launchd.log"
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(cli_path), "telegram", "watch", "--once"],
        "StartInterval": 60,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        # ~/.bun/bin: tmux-ctl's helpers and the plugin's launcher live there; tmux and python3 come from the other two
        "EnvironmentVariables": {"PATH": f"{home}/.local/bin:/opt/homebrew/bin:{home}/.bun/bin:/usr/bin:/bin"},
    })


def _launchctl(*args):
    cmd = shlex.split(os.environ.get("TW_LAUNCHCTL") or "launchctl")
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def _executable(p):
    return p.is_file() and os.access(p, os.X_OK)


def tmux_ctl_path(home=None):
    """~/.local/bin/tmux-ctl, else the one beside this checkout (TW_BIN_DIR is the test seam); RuntimeError otherwise."""
    beside = Path(os.environ.get("TW_BIN_DIR") or Path(__file__).resolve().parent.parent / "bin")
    cands = [Path(home or _home()) / ".local" / "bin" / "tmux-ctl", beside / "tmux-ctl"]
    for c in cands:
        if _executable(c):
            return c
    raise RuntimeError("no executable tmux-ctl to schedule; checked " + ", ".join(str(c) for c in cands))


def schedule_install():
    home = _home()
    target = tmux_ctl_path(home)               # before anything is written
    plist = _plist_path(home)
    plist.parent.mkdir(parents=True, exist_ok=True)
    (home / ".local" / "state" / "agent-board").mkdir(parents=True, exist_ok=True)
    lines = []
    if plist.exists():
        bak = plist.with_name(f"{plist.name}.bak-{datetime.now():%Y%m%d}")
        shutil.copy2(plist, bak)
        lines.append(f"backed up the old plist to {bak}")
    plist.write_bytes(plist_text(target, str(home)))
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}/{LABEL}")   # not loaded yet is fine
    r = _launchctl("bootstrap", f"gui/{uid}", str(plist))
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {(r.stderr or r.stdout).strip()}")
    return lines + [f"installed {plist}: telegram watch --once every 60 seconds"]


def schedule_uninstall():
    plist = _plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if plist.exists():
        plist.unlink()
        return [f"removed {plist}"]
    return ["not installed"]


def schedule_status():
    r = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if r.returncode != 0:
        return ["not installed"]
    keep = [l.strip() for l in r.stdout.splitlines() if re.match(r"^\t(state|last exit code) = ", l)]
    return keep or ["installed"]


def main(argv):
    if argv[:1] == ["--once"] or not argv:
        for line in watch_once():
            print(line)
        return 0
    if argv[:1] in (["install"], ["uninstall"], ["status"]):
        if sys.platform != "darwin" and "TW_LAUNCHCTL" not in os.environ:
            print("telegram watch: launchd is macOS only; run `tmux-ctl telegram watch --once` from cron or a timer", file=sys.stderr)
            return 2
        try:
            lines = {"install": schedule_install, "uninstall": schedule_uninstall, "status": schedule_status}[argv[0]]()
        except RuntimeError as e:
            print(f"telegram watch: {e}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        return 0
    print("usage: tmux-ctl telegram watch --once|install|uninstall|status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
