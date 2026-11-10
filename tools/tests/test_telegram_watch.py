"""telegram_watch: the watchdog that notices a lead without its telegram MCP server and reconnects it."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import telegram_watch as tw  # noqa: E402

CH = "--channels plugin:telegram@claude-plugins-official"
SRV = "node --experimental-strip-types --no-warnings /h/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7/server.ts"


def table(*rows):
    """rows: (pid, ppid, etime_s, args)"""
    return {p: tw.Proc(p, pp, et, a) for p, pp, et, a in rows}


class Finding(unittest.TestCase):
    def test_leads_need_channel_flag_and_a_claude_executable(self):
        t = table((1, 0, 999, f"claude --model opus {CH} --settings x"),
                  (2, 0, 999, f"/h/.local/share/claude/versions/2.1.322 {CH}"),
                  (3, 0, 999, "claude --model opus --settings x"),                 # no channel: a teammate or token-less lead
                  (4, 0, 999, f"vim {CH}"),                                         # not claude
                  (5, 0, 999, f"tail -f {CH}"),
                  (6, 0, 999, f"claude {CH.replace('telegram', 'other')}"))
        self.assertEqual(sorted(tw.find_leads(t)), [1, 2])

    def test_server_among_descendants_only(self):
        t = table((10, 1, 999, "claude " + CH), (11, 10, 99, "sh -c x"), (12, 11, 99, SRV),
                  (20, 1, 999, "claude " + CH), (21, 20, 99, "node other/server.ts"),
                  (30, 1, 999, SRV))                                                # someone else's server
        self.assertTrue(tw.has_server(10, t))
        self.assertFalse(tw.has_server(20, t))

    def test_bun_run_and_node_both_match(self):
        t = table((1, 0, 9, "claude " + CH), (2, 1, 9, "bun run --cwd /h/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7 --silent start"),
                  (3, 2, 9, "bun server.ts"))
        self.assertTrue(tw.has_server(1, t))

    def test_pane_of_walks_ancestors(self):
        t = table((100, 1, 9, "-zsh"), (101, 100, 9, "claude " + CH))
        self.assertEqual(tw.pane_of(101, t, {100: "%3"}), "%3")
        self.assertEqual(tw.pane_of(101, t, {101: "%4"}), "%4")
        self.assertIsNone(tw.pane_of(101, t, {7: "%1"}))

    def test_parse_ps(self):
        out = "  10     1  01:02:03 claude --x\n  11    10     05:00 node a b\n  bad line\n  12 10 2-01:00:00 z\n"
        t = tw.parse_ps(out)
        self.assertEqual((t[10].ppid, t[10].age, t[10].args), (1, 3723, "claude --x"))
        self.assertEqual(t[11].age, 300)
        self.assertEqual(t[12].age, 2 * 86400 + 3600)
        self.assertEqual(len(t), 3)


class Rate(unittest.TestCase):
    def test_once_per_lead_per_15_minutes(self):
        d = tempfile.mkdtemp()
        s = tw.State(Path(d) / "s.json")
        self.assertTrue(s.should_notify(5, 1000)); s.mark_notified(5, 1000)
        self.assertFalse(s.should_notify(5, 1000 + 899))
        self.assertTrue(s.should_notify(5, 1000 + 901))
        self.assertTrue(s.should_notify(6, 1001))
        s2 = tw.State(Path(d) / "s.json")                      # persisted
        self.assertFalse(s2.should_notify(5, 1100))

    def test_corrupt_state_file_is_ignored(self):
        d = Path(tempfile.mkdtemp()); (d / "s.json").write_text("garbage")
        self.assertTrue(tw.State(d / "s.json").should_notify(1, 5))


class Fake:
    """A tmux stand-in that shows the /mcp menu for one pane, driven by the keys it is sent."""

    def __init__(self, menu_rows=("claude.ai Claude Docs", "claude-artifacts", "plugin:telegram:telegram"), status="ok", input_text=""):
        self.keys, self.rows, self.menu, self.cur, self.screen, self.status = [], list(menu_rows), menu_rows, 0, "prompt", status
        self.input_text = input_text
        self.server_started = False

    def capture(self):
        if self.screen == "prompt":
            return ["", "─" * 40, f"❯ {self.input_text}", "─" * 40, "  auto mode on"]
        if self.screen == "list":
            out = ["❯ /mcp", "  ⎿  Reconnected to plugin:telegram:telegram.", "   Manage MCP servers"]
            out += [("   ❯ ✔ " if i == self.cur else "     ✔ ") + r for i, r in enumerate(self.rows)]
            return out + ["   ↑/↓ to navigate · Enter to confirm · Esc to cancel"]
        if self.screen == "detail":
            opts = ["Reconnect", "Disable"] if self.status == "ok" else ["Something else"]
            out = ["❯ /mcp", "   Plugin:telegram:telegram MCP Server", "   Status: ✘ failed"]
            out += [("   ❯ " if i == self.cur else "     ") + f"{i + 1}. {o}" for i, o in enumerate(opts)]
            return out + ["   ↑/↓ to navigate · Enter to select · Esc to back"]
        return ["???"]

    def send(self, *keys):
        for k in keys:
            self.keys.append(k)
            if k == "Escape":
                self.screen = {"detail": "list", "list": "prompt"}.get(self.screen, "prompt"); self.cur = 0
            elif k == "Down":
                self.cur += 1
            elif k == "Enter":
                if self.screen == "typed":
                    self.screen, self.cur = "list", 0
                elif self.screen == "list":
                    self.screen, self.cur = "detail", 0
                elif self.screen == "detail":
                    if self.status == "ok" and self.cur == 0:
                        self.server_started = True
                    self.screen = "prompt"
            elif k == "/mcp":
                self.screen = "typed"


class Reconnect(unittest.TestCase):
    def run_it(self, fake, server_after=True, idle=True):
        ctl = tw.PaneCtl(capture=lambda: fake.capture(), send=fake.send, sleep=lambda s: None)
        return tw.reconnect(ctl, has_server=lambda: fake.server_started and server_after)

    def test_happy_path_finds_telegram_by_reading_the_menu(self):
        f = Fake()
        self.assertEqual(self.run_it(f), "ok")
        self.assertEqual(f.keys, ["/mcp", "Enter", "Down", "Down", "Enter", "Enter"])

    def test_position_is_not_hardcoded(self):
        f = Fake(menu_rows=("a", "b", "c", "d", "plugin:telegram:telegram", "e"))
        self.assertEqual(self.run_it(f), "ok")
        self.assertEqual(f.keys.count("Down"), 4)

    def test_no_telegram_row_backs_out_with_escape(self):
        f = Fake(menu_rows=("a", "b"))
        r = self.run_it(f)
        self.assertNotEqual(r, "ok")
        self.assertEqual(f.keys[-1:], ["Escape"])               # one menu open, one Escape: never an Escape at the prompt
        self.assertEqual(f.screen, "prompt")
        self.assertFalse(f.server_started)

    def test_unexpected_detail_menu_backs_out(self):
        f = Fake(status="weird")
        self.assertNotEqual(self.run_it(f), "ok")
        self.assertEqual(f.keys[-2:], ["Escape"] * 2)           # detail -> list -> prompt
        self.assertEqual(f.screen, "prompt")
        self.assertEqual(f.keys.count("Enter"), 2)             # /mcp and open telegram, never "select" an unknown option

    def test_screen_with_a_prompt_line_in_the_transcript_still_finds_the_menu_cursor(self):
        f = Fake(menu_rows=("plugin:telegram:telegram",))       # the menu cursor is on telegram; a "❯ /mcp" line sits above it
        self.assertEqual(self.run_it(f), "ok")

    def test_server_still_missing_after_reconnect_is_a_failure(self):
        f = Fake()
        self.assertEqual(self.run_it(f, server_after=False), "no server after reconnect")

    def test_menu_never_appears(self):
        class Dead(Fake):
            def send(self, *k): self.keys += list(k)
        f = Dead()
        f.screen = "prompt"
        r = tw.reconnect(tw.PaneCtl(capture=lambda: f.capture(), send=f.send, sleep=lambda s: None), has_server=lambda: False)
        self.assertEqual(r, "menu did not open")
        self.assertNotIn("Escape", f.keys)                      # at the prompt Escape twice opens Rewind


class Idle(unittest.TestCase):
    def test_ready_with_empty_input_is_idle(self):
        rows = ["", "─" * 50, "❯ ", "─" * 50, "  auto mode"]
        self.assertTrue(tw.idle_at_prompt("claude", rows, None))

    def test_typed_text_is_not_idle(self):
        rows = ["", "─" * 50, "❯ half a sentence", "─" * 50]
        self.assertFalse(tw.idle_at_prompt("claude", rows, None))

    def test_working_spinner_is_not_idle(self):
        rows = ["✻ Thinking… (12s · ↓ 40 tokens)", "", "─" * 50, "❯ ", "─" * 50]
        self.assertFalse(tw.idle_at_prompt("claude", rows, None))

    def test_a_busy_mod_state_wins(self):
        rows = ["", "─" * 50, "❯ ", "─" * 50]
        self.assertFalse(tw.idle_at_prompt("claude", rows, "working"))

    def test_a_shell_is_not_a_lead(self):
        self.assertFalse(tw.idle_at_prompt("zsh", ["$ "], None))


class Once(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.env = {"TC_STATE": str(self.d)}
        self.lead = table((100, 1, 9, "-zsh"), (101, 100, 600, f"claude {CH}"))
        self.notes, self.recon = [], []

    def go(self, tbl=None, idle=True, recon="ok", now=5000, env=None, panes=None):
        return tw.watch_once(env=env or self.env, now=now, table=tbl or self.lead,
                             panes={100: "%1"} if panes is None else panes,
                             pane_idle=lambda p: idle,
                             do_reconnect=lambda p: (self.recon.append(p), recon)[1],
                             notify=lambda title, text: self.notes.append((title, text)))

    def log(self):
        return (self.d / "telegram-watch.log").read_text().splitlines() if (self.d / "telegram-watch.log").exists() else []

    def test_healthy_lead_does_nothing(self):
        t = table(*[(p.pid, p.ppid, p.age, p.args) for p in self.lead.values()], (102, 101, 5, SRV))
        self.go(t)
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

    def test_failed_reconnect_notifies_once_per_15_min(self):
        self.go(recon="menu did not open", now=5000)
        self.go(recon="menu did not open", now=5060)
        self.assertEqual(len(self.recon), 2)                    # retried next minute
        self.assertEqual(len(self.notes), 1)                    # but one banner
        self.go(recon="menu did not open", now=5000 + 901)
        self.assertEqual(len(self.notes), 2)

    def test_lead_without_a_pane_only_notifies(self):
        self.go(panes={})
        self.assertEqual(self.recon, [])
        self.assertEqual(len(self.notes), 1)

    def test_young_lead_gets_a_grace_period(self):
        t = table((100, 1, 9, "-zsh"), (101, 100, 20, f"claude {CH}"))
        self.go(t)
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))

    def test_disabled_by_env(self):
        self.go(env={**self.env, "TC_TELEGRAM_WATCH": "0"})
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))

    def test_disabled_by_flag_file(self):
        (self.d / "telegram-watch.off").write_text("")
        self.go()
        self.assertEqual((self.recon, self.notes, self.log()), ([], [], []))


class Banner(unittest.TestCase):
    def test_tc_notify_0_sends_no_banner_and_darwin_sends_one(self):
        calls = []
        real_run, real_plat = tw.subprocess.run, tw.sys.platform
        tw.subprocess.run = lambda argv, **k: calls.append(argv)
        old = os.environ.get("TC_NOTIFY")
        try:
            tw.sys.platform = "darwin"
            os.environ["TC_NOTIFY"] = "0"
            tw._notify("t", "x")
            self.assertEqual(calls, [])
            del os.environ["TC_NOTIFY"]
            tw._notify("t", "x")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "osascript")
            tw.sys.platform = "linux"
            tw._notify("t", "x")
            self.assertEqual(len(calls), 1)
        finally:
            tw.subprocess.run, tw.sys.platform = real_run, real_plat
            if old is not None:
                os.environ["TC_NOTIFY"] = old


if __name__ == "__main__":
    unittest.main()
