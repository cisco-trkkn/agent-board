"""discord_watch: the watchdog that notices a lead without its discord MCP server and reconnects it."""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discord_watch as dw  # noqa: E402

CH = "--channels plugin:discord@claude-plugins-official"
SRV = "bun /h/.claude/plugins/cache/claude-plugins-official/discord/0.0.7/server.ts"
FX = Path(__file__).resolve().parent / "fixtures" / "discord-watch"
CMD = "/mcp reconnect plugin:discord:discord"
NOT_QUIET = dw.NOT_QUIET


def screen(name):
    """A real Claude Code 2.1.322 pane capture (see fixtures/discord-watch/README.md), as the rows the watchdog reads."""
    rows = (FX / f"{name}.txt").read_text().splitlines()
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


def styled(name):
    """A real 2.1.322 capture taken with `capture-pane -p -e -J` (SGR kept), as the rows the watchdog reads."""
    return dw.plain_rows((FX / f"{name}.ansi").read_text())


RULE = "─" * 40


def inline(sgr_line):
    """Rows for one input line drawn from a styled string, under a rule as in a real capture."""
    return dw.plain_rows(f"{RULE}\n{sgr_line}\n{RULE}")


def with_input(text):
    """The real idle capture with `text` on the input line."""
    rows = screen("idle")
    return [("❯ " + text) if r.startswith("❯") else r for r in rows]


def table(*rows):
    """rows: (pid, ppid, etime_s, args)"""
    return {p: dw.Proc(p, pp, et, a) for p, pp, et, a in rows}


class Finding(unittest.TestCase):
    def test_leads_need_channel_flag_and_a_claude_executable(self):
        t = table((1, 0, 999, f"claude --model opus {CH} --settings x"),
                  (2, 0, 999, f"/h/.local/share/claude/versions/2.1.322 {CH}"),
                  (3, 0, 999, "claude --model opus --settings x"),                 # no channel: a teammate or token-less lead
                  (4, 0, 999, f"vim {CH}"),                                         # not claude
                  (5, 0, 999, f"tail -f {CH}"),
                  (6, 0, 999, f"claude {CH.replace('discord', 'other')}"),
                  (7, 0, 999, "claude --channels=plugin:discord@claude-plugins-official --model opus"))
        self.assertEqual(sorted(dw.find_leads(t)), [1, 2, 7])

    def test_server_among_descendants_only(self):
        t = table((10, 1, 999, "claude " + CH), (11, 10, 99, "sh -c x"), (12, 11, 99, SRV),
                  (20, 1, 999, "claude " + CH), (21, 20, 99, "node other/server.ts"),
                  (30, 1, 999, SRV))                                                # someone else's server
        self.assertTrue(dw.has_server(10, t))
        self.assertFalse(dw.has_server(20, t))

    def test_bun_run_and_node_both_match(self):
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "bun run --cwd /h/.claude/plugins/cache/claude-plugins-official/discord/0.0.7 --silent start"),
                  (3, 2, 9, "bun server.ts"))
        self.assertTrue(dw.has_server(1, t))
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "sh /h/.claude/plugins/discord/scripts/discord-mcp-launch"))   # the launcher matches
        self.assertTrue(dw.has_server(1, t))
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "node /h/.claude/plugins/discord/scripts/discord-mcp-stub.js"))   # a stub is not a live channel
        self.assertFalse(dw.has_server(1, t))

    def test_node_server_ts_matches(self):   # the launcher execs node --experimental-strip-types <plugin>/server.ts
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "node --experimental-strip-types /h/.claude/plugins/cache/claude-plugins-official/discord/0.0.7/server.ts"))
        self.assertTrue(dw.has_server(1, t))
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "node --experimental-strip-types /h/other/server.ts"))   # not under /discord/
        self.assertFalse(dw.has_server(1, t))

    def test_pane_of_walks_ancestors(self):
        t = table((100, 1, 9, "-zsh"), (101, 100, 9, "claude " + CH))
        self.assertEqual(dw.pane_of(101, t, {100: "%3"}), "%3")
        self.assertEqual(dw.pane_of(101, t, {101: "%4"}), "%4")
        self.assertIsNone(dw.pane_of(101, t, {7: "%1"}))

    def test_parse_ps(self):
        out = "  10     1  01:02:03 claude --x\n  11    10     05:00 node a b\n  bad line\n  12 10 2-01:00:00 z\n"
        t = dw.parse_ps(out)
        self.assertEqual((t[10].ppid, t[10].age, t[10].args), (1, 3723, "claude --x"))
        self.assertEqual(t[11].age, 300)
        self.assertEqual(t[12].age, 2 * 86400 + 3600)
        self.assertEqual(len(t), 3)


class State(unittest.TestCase):
    def test_banner_once_per_lead_per_15_minutes(self):
        d = tempfile.mkdtemp()
        s = dw.State(Path(d) / "s.json")
        self.assertTrue(s.should_notify(5, 1000)); s.mark_notified(5, 1000)
        self.assertFalse(s.should_notify(5, 1000 + 899))
        self.assertTrue(s.should_notify(5, 1000 + 901))
        self.assertTrue(s.should_notify(6, 1001))
        self.assertFalse(dw.State(Path(d) / "s.json").should_notify(5, 1100))      # persisted

    def test_corrupt_state_file_is_ignored(self):
        d = Path(tempfile.mkdtemp()); (d / "s.json").write_text("garbage")
        s = dw.State(d / "s.json")
        self.assertTrue(s.should_notify(1, 5))
        self.assertTrue(s.may_try(1, 5))

    def test_backoff_doubles_from_60s_and_caps_at_30_minutes(self):
        s = dw.State(Path(tempfile.mkdtemp()) / "s.json")
        self.assertTrue(s.may_try(7, 0))
        delays, now = [], 1000
        for _ in range(8):
            s.failed(7, now)
            delays.append(s.tries[7]["next"] - now)
            self.assertFalse(s.may_try(7, now + delays[-1] - 1))
            self.assertTrue(s.may_try(7, now + delays[-1]))
            now += delays[-1]
        self.assertEqual(delays, [60, 120, 240, 480, 960, 1800, 1800, 1800])

    def test_failed_returns_the_attempt_count_and_alive_resets_it(self):
        d = Path(tempfile.mkdtemp()) / "s.json"
        s = dw.State(d)
        self.assertEqual(s.failed(7, 0), 1)
        self.assertEqual(s.failed(7, 100), 2)
        s.alive(7)
        self.assertEqual(s.failed(7, 200), 1)
        self.assertEqual(dw.State(d).tries[7]["n"], 1)                           # persisted

    def test_prune_drops_dead_leads(self):
        s = dw.State(Path(tempfile.mkdtemp()) / "s.json")
        s.failed(7, 0); s.mark_notified(7, 0); s.failed(8, 0)
        s.prune({8})
        self.assertEqual(list(s.tries), [8]); self.assertEqual(s.notified, {})


class Screens(unittest.TestCase):
    """The parsers against real 2.1.322 captures."""

    def test_idle_screens_are_idle(self):
        for name in ("idle", "after-turn", "reconnect-ok", "reconnect-unknown", "reconnecting"):   # the last two quote `❯ /mcp …` in the transcript
            with self.subTest(name):
                self.assertTrue(dw.idle_at_prompt("claude", screen(name), None))
                self.assertEqual(dw.input_text(screen(name)), "")

    def test_idle_lead_with_teammates_is_ready_and_has_no_live_spinner(self):
        # real 2.1.325 capture; the pane has typed text on its input line, so it is ready but not "idle" for the watchdog
        rows = screen("idle-with-teammates")
        self.assertEqual(dw.paneclass.classify("claude", rows, False), ("claude", "ready"))
        self.assertFalse(dw.paneclass.spinner_live(rows[-30:]))
        self.assertEqual(dw.input_text(rows), "keep going with the queue")

    def test_typed_input_is_not_idle_and_is_read_back_exactly(self):
        self.assertFalse(dw.idle_at_prompt("claude", screen("typed-input"), None))
        self.assertEqual(dw.input_text(screen("typed-input")), "half a sentence")
        self.assertEqual(dw.input_text(screen("typed-list")), CMD)
        self.assertFalse(dw.idle_at_prompt("claude", screen("typed-list"), None))

    def test_two_real_idle_captures_taken_3_s_apart_are_quiet(self):
        a, b = screen("real-idle-1"), screen("real-idle-2")          # a real idle lead, capture-pane twice, 3 s apart
        for rows in (a, b):
            self.assertTrue(dw.idle_at_prompt("claude", rows, None))
            self.assertEqual(dw.input_text(rows), "")                  # the `Try "..."` placeholder reads as empty
        self.assertEqual(dw.input_frame(a), dw.input_frame(b))
        self.assertIn('Try "', dw.input_frame(a)[1])                   # and it is the same placeholder both times

    def test_a_dim_prompt_suggestion_is_not_typed_text(self):
        rows = styled("real-ghost-suggestion")     # real capture: `❯ ` + SGR 2 `run it with a few values`, turn ended
        self.assertEqual(dw.input_text(rows), "")
        self.assertTrue(dw.idle_at_prompt("claude", rows, None))
        self.assertEqual(dw.input_frame(rows)[1].rstrip(), "❯")

    def test_real_typed_text_is_text_in_the_same_capture_mode(self):
        rows = styled("real-typed-text")           # real capture: `❯ my typed words`, normal intensity
        self.assertEqual(dw.input_text(rows), "my typed words")
        self.assertFalse(dw.idle_at_prompt("claude", rows, None))

    def test_dim_text_off_the_input_line_is_kept(self):
        rows = dw.plain_rows("\x1b[2m✻ Thinking… (3s)\x1b[0m\n\x1b[39m❯\xa0\x1b[2mgo on\x1b[0m")
        self.assertEqual(rows[0], "✻ Thinking… (3s)")

    def test_a_2_inside_a_colour_argument_is_not_dim(self):
        # the `2` of `38;5;2`, `38;2;r;g;b`, `48;5;2`, `58;5;2` and the colon forms is a colour argument; the text is typed
        for sgr in ("38;5;2", "38;2;2;2;2", "38;2;200;2;2", "48;5;2", "48;2;2;2;2", "58;5;2", "38:2::2:2:2", "38:5:2", "1;38;5;2"):
            with self.subTest(sgr):
                rows = inline(f"\x1b[39m❯\xa0\x1b[{sgr}mtyped\x1b[0m")
                self.assertEqual(dw.input_text(rows), "typed")
                self.assertFalse(dw.idle_at_prompt("claude", rows, None))

    def test_dim_among_other_attributes_is_still_a_ghost(self):
        for sgr in ("2;37", "37;2", "1;2", "2;38;5;244", "38;5;244;2"):
            with self.subTest(sgr):
                self.assertEqual(dw.input_text(inline(f"\x1b[39m❯\xa0\x1b[{sgr}mghost\x1b[0m")), "")

    def test_22_and_0_end_the_dim_span(self):
        for end in ("22", "0", "", "22;38;5;2"):
            with self.subTest(end):
                rows = inline(f"\x1b[39m❯\xa0\x1b[2mghost\x1b[{end}mreal")
                self.assertEqual(dw.input_text(rows), "real")

    def test_an_unparseable_sequence_on_the_input_line_counts_as_typed(self):
        for sgr in ("2;?", "38;5", "38;2;1;2", "48", "2;99999999999999999999;;;?"):
            with self.subTest(sgr):
                rows = inline(f"\x1b[39m❯\xa0\x1b[2mfirst\x1b[0m\x1b[{sgr}mtext\x1b[0m")
                self.assertIn("first", dw.input_text(rows))   # nothing on that line is dropped as ghost
                self.assertFalse(dw.idle_at_prompt("claude", rows, None))

    def test_a_turn_in_progress_is_not_idle(self):
        self.assertFalse(dw.idle_at_prompt("claude", screen("working"), None))

    def test_a_busy_mod_state_wins_over_an_idle_screen(self):
        self.assertFalse(dw.idle_at_prompt("claude", screen("idle"), "working"))

    def test_no_input_line_reads_as_none(self):
        self.assertIsNone(dw.input_text(["$ ls", "file"]))


class SharedSpinnerRule(unittest.TestCase):
    """The watchdog and the board read a spinner with one rule (paneclass.spinner_live)."""

    def test_watchdog_never_idle_where_the_board_sees_a_live_spinner(self):
        names = sorted(p.stem for p in FX.glob("*.txt"))
        self.assertGreaterEqual(len(names), 10)   # every .txt capture in the fixture dir is checked
        live = 0
        for name in names:
            rows = screen(name)
            with self.subTest(name):
                if dw.paneclass.spinner_live(rows[-30:]):
                    live += 1
                    self.assertFalse(dw.idle_at_prompt("claude", rows, None))
                    self.assertFalse(dw.idle_at_prompt("claude", rows, "ready"))   # a fresh mod state that says ready
        self.assertGreaterEqual(live, 3)   # working.txt and the two task-label fixtures


class SendRemove(unittest.TestCase):
    def test_argv(self):
        calls = []
        dw.send_remove(lambda *a: calls.append(a), "%7", 2, 3)
        self.assertEqual(calls, [("send-keys", "-t", "%7", "End", "Left", "Left", "BSpace", "BSpace", "BSpace")])

    def test_argv_nothing_after(self):
        calls = []
        dw.send_remove(lambda *a: calls.append(a), "%7", 0, 2)
        self.assertEqual(calls, [("send-keys", "-t", "%7", "End", "BSpace", "BSpace")])

    def test_real_pane(self):
        """send_remove against a scratch tmux server: a bash --norc line editor honours End/Left/BSpace (cat does not)."""
        tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
        sock = f"tw-remove-{os.getpid()}"

        def t(*args):
            return subprocess.run([tmux, "-L", sock, "-f", "/dev/null", *args], capture_output=True, text=True, check=True).stdout

        try:
            t("new-session", "-d", "-x", "80", "-y", "6", "env PS1='$ ' /bin/bash --norc --noprofile")
            pane = t("display", "-p", "-t", "0", "#{pane_id}").strip()
            time.sleep(0.5)
            t("send-keys", "-t", pane, "-l", "abcXYZdef")
            time.sleep(0.2)
            dw.send_remove(t, pane, 3, 3)
            deadline = time.time() + 3
            while time.time() < deadline:
                line = [r for r in t("capture-pane", "-p", "-t", pane).splitlines() if r.strip()][-1]
                if line.endswith("abcdef"):
                    break
                time.sleep(0.1)
            self.assertEqual(line, "$ abcdef")
        finally:
            subprocess.run([tmux, "-L", sock, "-f", "/dev/null", "kill-server"], capture_output=True)


class Safe(unittest.TestCase):
    def test_only_copy_mode_blocks(self):
        self.assertIsNone(dw.unsafe_reason(in_mode=False))
        self.assertEqual(dw.unsafe_reason(in_mode=True), "pane in copy mode")

    def test_input_frame_is_the_rule_input_rule_and_ignores_the_status_rows(self):
        a = dw.input_frame(screen("typed-input"))
        self.assertEqual(len(a), 3)
        self.assertIn("half a sentence", a[1])
        moved = screen("idle")[:-2] + ["  Opus 5.5 · ctx 9% · 5h 60%", "  other status"]
        self.assertEqual(dw.input_frame(screen("idle")), dw.input_frame(moved))      # a redrawn status line is not typing
        self.assertNotEqual(dw.input_frame(screen("idle")), dw.input_frame(screen("typed-input")))
        self.assertIsNone(dw.input_frame(["$ ls"]))


class QuietGap(unittest.TestCase):
    def test_default_override_cap_and_bad_values(self):
        self.assertEqual(dw.quiet_gap({}), 3)
        self.assertEqual(dw.quiet_gap({"TC_DISCORD_WATCH_QUIET": "0"}), 0)
        self.assertEqual(dw.quiet_gap({"TC_DISCORD_WATCH_QUIET": "5"}), 5)
        self.assertEqual(dw.quiet_gap({"TC_DISCORD_WATCH_QUIET": "30"}), 10)       # an old 30 s override is capped
        self.assertEqual(dw.quiet_gap({"TC_DISCORD_WATCH_QUIET": "soon"}), 3)
        self.assertEqual(dw.quiet_gap({"TC_DISCORD_WATCH_QUIET": "-4"}), 0)


class Ctl:
    """A pane stand-in: records what is typed. screens: what capture() returns in turn (the last repeats)."""

    def __init__(self, screens, check=None, server_after_enter=True):
        self.screens, self.log, self.n = screens, [], 0
        self._check, self.server, self.entered = check, server_after_enter, False

    def capture(self):
        r = self.screens[min(self.n, len(self.screens) - 1)]
        self.n += 1
        return r

    def check(self): return self._check
    def pane_idle(self): return dw.idle_at_prompt("claude", self.capture(), None)
    def type_text(self, t): self.log.append(("type", t))
    def enter(self): self.log.append(("enter",)); self.entered = True
    def clear(self): self.log.append(("clear",))
    def remove(self, back, count): self.log.append(("remove", back, count))
    def sleep(self, s): pass
    def has_server(self): return self.entered and self.server


def run(ctl):
    return dw.reconnect(dw.PaneCtl(ctl.capture, ctl.type_text, ctl.enter, ctl.clear, ctl.check, ctl.pane_idle, ctl.sleep, remove=ctl.remove), ctl.has_server)


class Reconnect(unittest.TestCase):
    def test_types_the_command_and_enter_when_the_input_reads_back_exactly(self):
        c = Ctl([screen("idle")] * 4 + [screen("typed-list")])
        self.assertEqual(run(c), "ok")
        self.assertEqual(c.log, [("type", CMD), ("enter",)])

    def test_a_dim_suggestion_does_not_block_the_reconnect(self):
        ghost, typed = styled("real-ghost-suggestion"), screen("typed-list")
        c = Ctl([ghost] * 4 + [typed])
        self.assertEqual(run(c), "ok")
        self.assertEqual(c.log, [("type", CMD), ("enter",)])

    def test_real_typed_text_still_blocks_with_the_styled_capture(self):
        c = Ctl([styled("real-typed-text")])
        self.assertEqual(run(c), NOT_QUIET)
        self.assertEqual(c.log, [])

    def test_unsafe_pane_gets_no_keys(self):
        c = Ctl([screen("idle")], check="pane in copy mode")
        self.assertEqual(run(c), "pane in copy mode")
        self.assertEqual(c.log, [])

    def test_input_with_text_gets_no_keys(self):
        c = Ctl([screen("typed-input")])
        self.assertEqual(run(c), NOT_QUIET)
        self.assertEqual(c.log, [])

    def test_a_turn_in_progress_gets_no_keys(self):
        c = Ctl([screen("working")])
        self.assertEqual(run(c), NOT_QUIET)
        self.assertEqual(c.log, [])

    def test_a_key_typed_before_our_command_is_kept_and_only_the_command_removed(self):
        c = Ctl([screen("idle")] * 4 + [with_input("x" + CMD), with_input("x")])
        self.assertEqual(run(c), "input changed while typing")
        self.assertEqual(c.log, [("type", CMD), ("remove", 0, len(CMD))])      # no Enter, no C-u

    def test_a_key_typed_after_our_command_is_kept_too(self):
        c = Ctl([screen("idle")] * 4 + [with_input(CMD + "yz"), with_input("yz")])
        self.assertEqual(run(c), "input changed while typing")
        self.assertEqual(c.log, [("type", CMD), ("remove", 2, len(CMD))])

    def test_if_the_line_is_not_the_users_own_text_after_removal_it_is_left_alone(self):
        c = Ctl([screen("idle")] * 4 + [with_input("x" + CMD), with_input("x" + CMD[:5])])
        self.assertEqual(run(c), "input changed while typing, line left as is")
        self.assertEqual(c.log, [("type", CMD), ("remove", 0, len(CMD))])      # one removal, never a C-u, never an Enter

    def test_a_line_that_does_not_contain_our_command_is_left_alone(self):
        c = Ctl([screen("idle")] * 4 + [with_input("half a sentence")])
        self.assertEqual(run(c), "input changed while typing, line left as is")
        self.assertEqual(c.log, [("type", CMD)])

    def test_a_redrawing_idle_pane_is_still_quiet(self):
        redrawn = screen("idle")[:-2] + ["  Opus 5.5 · ctx 9%", "  x"]          # status row changes every capture, input does not
        c = Ctl([screen("idle"), redrawn, screen("idle"), redrawn, screen("typed-list")])
        self.assertEqual(run(c), "ok")
        self.assertEqual(c.log, [("type", CMD), ("enter",)])

    def test_text_typed_between_the_two_captures_gets_no_keys(self):
        c = Ctl([screen("idle"), screen("typed-input")])
        self.assertEqual(run(c), NOT_QUIET)
        self.assertEqual(c.log, [])

    def test_a_working_pane_in_the_second_capture_gets_no_keys(self):
        c = Ctl([screen("idle"), screen("working")])
        self.assertEqual(run(c), NOT_QUIET)
        self.assertEqual(c.log, [])

    def test_the_gap_is_slept_between_the_captures(self):
        c = Ctl([screen("idle")] * 4 + [screen("typed-list")]); slept = []
        c.sleep = slept.append
        dw.reconnect(dw.PaneCtl(c.capture, c.type_text, c.enter, c.clear, c.check, c.pane_idle, c.sleep, remove=c.remove), c.has_server, quiet_gap=7, settle=1)
        self.assertEqual(slept[0], 7)

    def test_no_server_after_enter_is_a_failure_without_further_keys(self):
        c = Ctl([screen("idle")] * 4 + [screen("typed-list")], server_after_enter=False)
        r = dw.reconnect(dw.PaneCtl(c.capture, c.type_text, c.enter, c.clear, c.check, c.pane_idle, c.sleep, remove=c.remove), c.has_server, settle=1)
        self.assertEqual(r, "no server after reconnect")
        self.assertEqual(c.log, [("type", CMD), ("enter",)])

    def test_no_escape_or_menu_keys_exist(self):
        src = Path(dw.__file__).read_text()
        for banned in ("Escape", '"Down"', "Manage MCP servers", "_back_out", "_cursor_row"):
            self.assertNotIn(banned, src)


class Once(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.env = {"TC_STATE": str(self.d)}
        self.lead = table((100, 1, 9, "-zsh"), (101, 100, 600, f"claude {CH}"))
        self.healthy = table((100, 1, 9, "-zsh"), (101, 100, 600, f"claude {CH}"), (102, 101, 5, SRV))
        self.notes, self.recon = [], []

    def go(self, tbl=None, idle=True, recon="ok", now=5000, env=None, panes=None):
        return dw.watch_once(env=env or self.env, now=now, table=tbl or self.lead,
                             panes={100: "%1"} if panes is None else panes,
                             pane_idle=lambda p: idle,
                             do_reconnect=lambda p: (self.recon.append(p), recon)[1],
                             notify=lambda title, text: self.notes.append((title, text)))

    def log(self):
        return (self.d / "discord-watch.log").read_text().splitlines() if (self.d / "discord-watch.log").exists() else []

    def test_healthy_lead_does_nothing(self):
        self.go(self.healthy)
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))

    def test_missing_idle_reconnects_and_logs_without_notifying(self):
        self.go()
        self.assertEqual(self.recon, ["%1"])
        self.assertEqual(self.notes, [])
        self.assertEqual(len(self.log()), 1)
        self.assertIn("reconnect", self.log()[0]); self.assertIn("pid 101", self.log()[0])

    def test_busy_pane_is_never_typed_into_and_notifies(self):
        self.go(idle=False)
        self.assertEqual(self.recon, [])
        self.assertEqual(len(self.notes), 1)
        self.assertIn("busy", self.log()[0])

    def test_failed_reconnect_backs_off_and_notifies_once_when_the_backoff_starts(self):
        self.go(recon="no server after reconnect", now=5000)
        self.assertEqual((len(self.recon), len(self.notes)), (1, 1))
        self.go(recon="no server after reconnect", now=5059)                  # inside the 60 s backoff: no attempt, no log
        self.assertEqual(len(self.recon), 1)
        n = len(self.log())
        self.go(recon="no server after reconnect", now=5060)                  # attempt 2, next in 120 s, no new banner
        self.assertEqual((len(self.recon), len(self.notes)), (2, 1))
        self.go(recon="no server after reconnect", now=5060 + 119)
        self.assertEqual(len(self.recon), 2)
        self.go(recon="no server after reconnect", now=5060 + 120)
        self.assertEqual((len(self.recon), len(self.notes)), (3, 1))
        self.assertGreater(len(self.log()), n)

    def test_a_live_server_resets_the_backoff(self):
        self.go(recon="no server after reconnect", now=5000)
        self.go(self.healthy, now=5010)                                         # server seen alive
        self.go(recon="no server after reconnect", now=5011)                   # attempts again at once, banner again
        self.assertEqual((len(self.recon), len(self.notes)), (2, 2))

    def test_lead_without_a_pane_only_notifies(self):
        self.go(panes={})
        self.assertEqual(self.recon, [])
        self.assertEqual(len(self.notes), 1)

    def test_young_lead_gets_a_grace_period(self):
        t = table((100, 1, 9, "-zsh"), (101, 100, 20, f"claude {CH}"))
        self.go(t)
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))

    def test_disabled_by_env(self):
        self.go(env={**self.env, "TC_DISCORD_WATCH": "0"})
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))

    def test_disabled_by_flag_file(self):
        (self.d / "discord-watch.off").write_text("")
        self.go()
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))


class Repair(unittest.TestCase):
    """Spec §3 watch repair: a bot-less idle lead of a project with a token is restarted with --resume. Every seam is injected:
    no tmux, no bridge outbox, no real state dir."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.env = {"TC_STATE": str(self.d)}
        self.tbl = table((100, 1, 9, "-zsh"), (101, 100, 600, "claude --model opus"))   # a lead started without the channel
        self.restarts, self.posts, self.notes = [], [], []
        self.holder_of, self.idle, self.res = "", True, (True, "restarted")
        self.lead = ("%1", 100)

    def go(self, now=5000, tbl=None, projects=("p",), lead="default"):
        return dw.watch_once(env=self.env, now=now, table=tbl or self.tbl, panes={100: "%1"},
                             projects=lambda: list(projects), holder=lambda proj: self.holder_of,
                             lead_of=lambda proj: self.lead if lead == "default" else lead,
                             pane_idle=lambda p: self.idle,
                             restart=lambda proj: (self.restarts.append(proj), self.res)[1],
                             post=lambda proj, text: self.posts.append((proj, text)),
                             notify=lambda title, text: self.notes.append((title, text)))

    def log(self):
        f = self.d / "discord-watch.log"
        return f.read_text().splitlines() if f.exists() else []

    def test_a_raising_repair_does_not_stop_the_reconnect_path(self):
        # mutation: drop the try/except in watch_once -> the UnicodeDecodeError aborts the run before the reconnect
        def boom(proj):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        tbl = table((100, 1, 9, "-zsh"), (101, 100, 600, f"claude {CH}"))
        recon = []
        dw.watch_once(env=self.env, now=5000, table=tbl, panes={100: "%1"}, projects=lambda: ["p"],
                      holder=boom, lead_of=lambda proj: self.lead, pane_idle=lambda p: True,
                      do_reconnect=lambda p: (recon.append(p), "ok")[1],
                      restart=lambda proj: (True, "x"), post=lambda proj, t: None, notify=lambda a, b: None)
        self.assertEqual(recon, ["%1"])
        self.assertTrue(any("repair skipped: UnicodeDecodeError" in l for l in self.log()))

    def test_restart_on_the_second_idle_run_not_the_first(self):
        self.go(5000)
        self.assertEqual(self.restarts, [])
        self.go(5060)
        self.assertEqual(self.restarts, ["p"])

    def test_a_busy_run_resets_the_count(self):
        self.go(5000)
        self.idle = False
        self.go(5060)
        self.idle = True
        self.go(5120)
        self.assertEqual(self.restarts, [])
        self.go(5180)
        self.assertEqual(self.restarts, ["p"])

    def test_busy_lead_is_never_restarted(self):
        self.idle = False
        for n in range(4):
            self.go(5000 + 60 * n)
        self.assertEqual(self.restarts, [])

    def test_held_bot_is_never_restarted(self):
        self.holder_of = "555 %9"
        for n in range(4):
            self.go(5000 + 60 * n)
        self.assertEqual(self.restarts, [])

    def test_a_lead_already_running_with_the_channel_is_left_alone(self):
        t = table((100, 1, 9, "-zsh"), (101, 100, 600, f"claude {CH}"), (102, 101, 5, SRV))
        for n in range(4):
            self.go(5000 + 60 * n, tbl=t)
        self.assertEqual(self.restarts, [])

    def test_a_pane_with_no_claude_in_it_is_left_alone(self):
        t = table((100, 1, 9, "-zsh"))
        for n in range(4):
            self.go(5000 + 60 * n, tbl=t)
        self.assertEqual(self.restarts, [])

    def test_only_claude_and_claude_next_windows_are_lead_windows(self):
        rows = [("p", "", "", "agent-1", "%7", 70), ("p", "", "", "claude-next", "%8", 80), ("p", "", "", "claude", "%9", 90),
                ("p-bg", "", "1", "claude", "%5", 50), ("other", "", "", "claude", "%6", 60), ("p2", "p", "", "claude", "%4", 40)]
        self.assertEqual(dw.pick_lead("p", rows), ("%9", 90))
        self.assertEqual(dw.pick_lead("p", [r for r in rows if r[3] != "claude" or r[2]]), ("%8", 80))
        self.assertIsNone(dw.pick_lead("p", [r for r in rows if r[3] not in ("claude", "claude-next")]))
        self.assertIsNone(dw.pick_lead("zz", rows))

    def test_a_project_without_a_lead_window_is_skipped(self):
        for n in range(4):
            self.go(5000 + 60 * n, lead=None)
        self.assertEqual(self.restarts, [])

    def test_fifteen_minute_cap_per_project(self):
        self.go(5000)
        self.go(5060)
        self.assertEqual(len(self.restarts), 1)
        for n in range(2, 14):                               # still idle, inside 15 min of the attempt at 5060
            self.go(5000 + 60 * n)
        self.assertEqual(len(self.restarts), 1)
        self.go(5060 + 899)
        self.assertEqual(len(self.restarts), 1)
        self.go(5060 + 900)
        self.assertEqual(len(self.restarts), 2)

    def test_the_cap_is_per_project_and_a_failed_attempt_counts(self):
        self.res = (False, "boom")
        self.go(5000, projects=("a", "b"))
        self.go(5060, projects=("a", "b"))
        self.assertEqual(sorted(self.restarts), ["a", "b"])
        self.go(5120, projects=("a", "b"))
        self.assertEqual(len(self.restarts), 2)

    def test_success_posts_and_logs(self):
        self.go(5000)
        self.go(5060)
        self.assertEqual(self.posts, [("p", "p lead reconnected to Discord")])
        self.assertEqual(self.notes, [])
        self.assertTrue(any("p lead reconnected" in l or "restarted" in l for l in self.log()))

    def test_failure_logs_and_banners_without_posting(self):
        self.res = (False, "no pane")
        self.go(5000)
        self.go(5060)
        self.assertEqual(self.posts, [])
        self.assertEqual(len(self.notes), 1)
        self.assertIn("p", self.notes[0][1])
        self.assertTrue(any("no pane" in l for l in self.log()))

    def test_state_keys_survive_prune_and_a_new_process(self):
        self.go(5000)                                        # idle_seen written
        self.go(5060)                                        # restarted written
        st = dw.State(self.d / "discord-watch.json")
        st.prune(set())
        self.assertEqual(dw.State(self.d / "discord-watch.json").restarted, {"p": 5060})
        self.go(5120)
        self.assertEqual(len(self.restarts), 1)

    def test_default_projects_are_the_dirs_with_a_bot_token(self):
        for name, env in (("a", "DISCORD_BOT_TOKEN=x\n"), ("b", "OTHER=1\n"), ("_ops", "DISCORD_BOT_TOKEN=x\n")):
            (self.d / "discord" / name).mkdir(parents=True)
            (self.d / "discord" / name / ".env").write_text(env)
        (self.d / "discord" / "c").mkdir()
        self.assertEqual(dw.projects_with_token(self.d), ["a"])


class Banner(unittest.TestCase):
    def test_tc_notify_0_sends_no_banner_and_darwin_sends_one(self):
        calls = []
        real_run, real_plat = dw.subprocess.run, dw.sys.platform
        dw.subprocess.run = lambda argv, **k: calls.append(argv)
        old = os.environ.get("TC_NOTIFY")
        try:
            dw.sys.platform = "darwin"
            os.environ["TC_NOTIFY"] = "0"
            dw._notify("t", "x")
            self.assertEqual(calls, [])
            del os.environ["TC_NOTIFY"]
            dw._notify("t", "x")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "osascript")
            dw.sys.platform = "linux"
            dw._notify("t", "x")
            self.assertEqual(len(calls), 1)
        finally:
            dw.subprocess.run, dw.sys.platform = real_run, real_plat
            if old is not None:
                os.environ["TC_NOTIFY"] = old


def write_stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class Schedule(unittest.TestCase):
    """The launchd job, against a fake launchctl and a scratch HOME (never the real LaunchAgents)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = Path(self.tmp) / "home"
        self.calls = Path(self.tmp) / "calls"
        self.stub = Path(self.tmp) / "launchctl"
        write_stub(self.stub, f'echo "$@" >> {self.calls}\nexit ${{LC_RC:-0}}\n')
        self.sibling = Path(self.tmp) / "repo" / "bin"
        self.link = self.home / ".local" / "bin" / "tmux-ctl"
        write_stub(self.link, "exit 0\n")
        self.saved = {k: os.environ.get(k) for k in ("TW_HOME", "TW_LAUNCHCTL", "TW_BIN_DIR")}
        os.environ.update(TW_HOME=str(self.home), TW_LAUNCHCTL=str(self.stub), TW_BIN_DIR=str(self.sibling))
        self.addCleanup(self.restore)
        self.plist = self.home / "Library" / "LaunchAgents" / "com.user.agent-board-discord-watch.plist"
        real = Path.home() / "Library" / "LaunchAgents" / "com.user.agent-board-discord-watch.plist"
        before = (real.exists(), real.stat().st_mtime if real.exists() else None)
        self.addCleanup(lambda: self.assertEqual(
            (real.exists(), real.stat().st_mtime if real.exists() else None), before, "a schedule test touched the real plist"))

    def restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_plist_fields(self):
        cli = str(self.link)
        d = plistlib.loads(dw.plist_text(cli, str(self.home)))
        self.assertEqual(d["Label"], "com.user.agent-board-discord-watch")
        self.assertEqual(d["ProgramArguments"], [cli, "discord", "watch", "--once"])
        self.assertEqual(d["StartInterval"], 60)
        log = str(self.home / ".local" / "state" / "agent-board" / "discord-watch.launchd.log")
        self.assertEqual((d["StandardOutPath"], d["StandardErrorPath"]), (log, log))
        path = d["EnvironmentVariables"]["PATH"].split(":")
        for need in (f"{self.home}/.local/bin", "/opt/homebrew/bin", f"{self.home}/.bun/bin", "/usr/bin", "/bin"):
            self.assertIn(need, path)

    @unittest.skipUnless(shutil.which("plutil"), "plutil is macOS only")
    def test_plist_passes_plutil_lint(self):
        f = Path(self.tmp) / "x.plist"
        f.write_bytes(dw.plist_text(str(self.link), str(self.home)))
        r = subprocess.run(["plutil", "-lint", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_writes_plist_then_bootout_and_bootstrap(self):
        lines = dw.schedule_install()
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"][0], str(self.link))
        uid = os.getuid()
        self.assertEqual(self.called(), [f"bootout gui/{uid}/com.user.agent-board-discord-watch",
                                         f"bootstrap gui/{uid} {self.plist}"])
        self.assertTrue(lines)

    def test_install_backs_up_an_existing_plist(self):
        self.plist.parent.mkdir(parents=True); self.plist.write_text("old")
        dw.schedule_install()
        self.assertEqual([p.read_text() for p in self.plist.parent.glob("*.bak-*")], ["old"])

    def test_install_falls_back_to_the_tmux_ctl_beside_the_checkout(self):
        self.link.unlink()
        beside = self.sibling / "tmux-ctl"
        write_stub(beside, "exit 0\n")
        dw.schedule_install()
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"][0], str(beside))

    def test_install_without_any_tmux_ctl_writes_nothing(self):
        self.link.unlink()
        with self.assertRaises(RuntimeError):
            dw.schedule_install()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.called(), [])

    def test_failed_bootstrap_is_an_error(self):
        os.environ["LC_RC"] = "5"
        self.addCleanup(os.environ.pop, "LC_RC", None)
        with self.assertRaises(RuntimeError):
            dw.schedule_install()

    def test_uninstall_boots_out_and_removes(self):
        dw.schedule_install()
        self.calls.unlink()
        self.assertEqual(dw.schedule_uninstall(), [f"removed {self.plist}"])
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.called(), [f"bootout gui/{os.getuid()}/com.user.agent-board-discord-watch"])
        self.assertEqual(dw.schedule_uninstall(), ["not installed"])


if __name__ == "__main__":
    unittest.main()
