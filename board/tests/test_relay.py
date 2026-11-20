import io
import itertools
import os
import shlex
import shutil
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paneclass  # noqa: E402
import relay  # noqa: E402

SEP = paneclass.SEP


class FakeTmux:
    root = str(Path(tempfile.gettempdir()).resolve())  # an existing non-git dir

    def __init__(self):
        self.calls = []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            return self.root + "\n"
        if a[0] == "capture-pane":
            return "% claude-orchestrator 'Read /d.md'\nThe current directory no longer exists (it was deleted or moved).\n\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]


class RootTmux:
    """tmux stub for session_root: pane_current_path per pane id, session_path per session."""

    def __init__(self, panes, session_path="", active_path=""):
        self.panes, self.session_path, self.active_path = panes, session_path, active_path

    def __call__(self, *a, check=False):
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            target, fmt = a[-2], a[-1]
            if fmt == "#{session_path}":
                return self.session_path + "\n"
            if fmt == "#{pane_current_path}":
                return (self.panes[target] if target in self.panes else self.active_path) + "\n"
        return ""


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def statuses(*seq):
    return mock.patch.object(paneclass, "pane_status", side_effect=[("claude", s) for s in seq])


class WaitTest(unittest.TestCase):
    def test_needs_two_in_a_row(self):
        sleeps = []
        with statuses("working", "ready", "working", "ready", "ready"):
            self.assertTrue(relay.wait_turn_end(FakeTmux(), "%5", sleep=sleeps.append))
        self.assertEqual(len(sleeps), 4)

    def test_new_spinner_keeps_waiting(self):
        rows = ["· Hyperspacing… (30s · ↓ 2.2k tokens)", "", "─" * 60, "❯ ", "─" * 60]
        calls = []

        def tmux(*a, check=False):
            calls.append(a)
            return f"2.1.316{paneclass.SEP}0\n" if a[0] == "display" else "\n".join(rows)

        clock = iter(range(0, 1000, 2))
        self.assertFalse(relay.wait_turn_end(tmux, "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock)))

    def test_times_out(self):
        clock = iter(range(0, 1000, 2))
        with statuses(*["working"] * 100):
            ok = relay.wait_turn_end(FakeTmux(), "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock))
        self.assertFalse(ok)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "relay"


def fixture_tmux(name):
    """tmux stub answering display and capture-pane from a real capture of the lead's pane."""
    text = (FIXTURES / name).read_text()

    def tmux(*a, check=False):
        return f"2.1.329{paneclass.SEP}0\n" if a[0] == "display" else text
    return tmux


class WaitRealCaptureTest(unittest.TestCase):
    """Real read-only captures of a Claude lead pane with a task list under its input box (fixtures/relay/README.md).
    mod_states is stubbed to {}: no agent-status file, so the screen decides."""

    def setUp(self):
        p = mock.patch.object(paneclass, "mod_states", return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_idle_lead_with_task_list_ends_the_wait(self):
        # mutation: drop "ready" from relay.ENDED, or let classify read the task list rows as a spinner -> False
        sleeps = []
        self.assertTrue(relay.wait_turn_end(fixture_tmux("idle-lead-tasklist.txt"), "%5", sleep=sleeps.append))
        self.assertEqual(len(sleeps), 1)

    def test_working_lead_keeps_waiting_until_the_cap(self):
        # mutation: make classify return ready for a claude pane whose footer shows `esc to interrupt` -> True
        clock = iter(range(0, 1000, 2))
        ok = relay.wait_turn_end(fixture_tmux("working-lead.txt"), "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock))
        self.assertFalse(ok)


class SessionRootTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "i")
        self.wt = self.repo / ".claude" / "worktrees" / "w1"
        git(self.repo, "worktree", "add", "-q", str(self.wt), "-b", "w1")
        self.plain = self.tmp / "plain"
        self.plain.mkdir()

    def root(self, tmux, **kw):
        return relay.session_root(tmux, "proj", **kw)

    def test_session_path_wins_over_pane_path(self):
        # the lead cd'd into a repo; the project is rooted at the session's start dir
        tmux = RootTmux({"%5": str(self.repo)}, session_path=str(self.plain))
        self.assertEqual(self.root(tmux), str(self.plain))

    def test_pane_path_ignored_for_active_window_too(self):
        tmux = RootTmux({"%5": str(self.wt)}, session_path=str(self.plain), active_path=str(self.repo))
        self.assertEqual(self.root(tmux), str(self.plain))

    def test_session_path_in_live_worktree_resolves_to_main_checkout(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.wt))), str(self.repo))

    def test_deleted_worktree_session_path_falls_back_to_home(self):
        git(self.repo, "worktree", "remove", "--force", str(self.wt))
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": str(self.repo)}, session_path=str(self.wt))), str(self.plain))

    def test_session_subdir_resolves_to_main_checkout(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.repo / ".claude"))), str(self.repo))

    def test_session_path_that_is_a_git_repo_is_returned_unchanged(self):
        # a project rooted at $HOME which is itself a repo
        self.assertEqual(self.root(RootTmux({"%5": str(self.plain)}, session_path=str(self.repo))), str(self.repo))

    def test_non_git_session_path_is_returned_as_is(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.plain))), str(self.plain))

    def test_nothing_usable_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": "/gone"}, session_path="")), str(self.plain))


TMUX_BIN = os.path.expanduser("~/.local/bin/tmux") if os.access(os.path.expanduser("~/.local/bin/tmux"), os.X_OK) else shutil.which("tmux")


@unittest.skipUnless(TMUX_BIN, "no tmux")
class RealTmuxSessionRootTest(unittest.TestCase):
    """session_root against a real scratch tmux server: the lead's pane moves, the session path stays."""

    def test_pane_cd_does_not_move_the_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        a, b = Path(tmp.name).resolve() / "A", Path(tmp.name).resolve() / "B"
        a.mkdir()
        b.mkdir()
        sock = f"relay-root-{os.getpid()}"

        def tmux(*args, check=False):
            r = subprocess.run([TMUX_BIN, "-L", sock, "-f", "/dev/null", *args], capture_output=True, text=True)
            if check and r.returncode:
                raise RuntimeError(r.stderr)
            return r.stdout

        self.addCleanup(lambda: tmux("kill-server"))
        # the pane process cd's like a lead does, then stays alive
        tmux("new-session", "-d", "-s", "proj", "-n", "claude", "-c", str(a), f"cd {b} && exec sleep 60", check=True)
        pane = tmux("list-panes", "-t", "=proj:claude", "-F", "#{pane_id}").split()[0]
        for _ in range(50):
            if tmux("display", "-p", "-t", pane, "#{pane_current_path}").strip() == str(b):
                break
            time.sleep(0.1)
        self.assertEqual(tmux("display", "-p", "-t", pane, "#{pane_current_path}").strip(), str(b))  # really diverged
        self.assertEqual(relay.session_root(tmux, "proj"), str(a))


class RespawnCommandTest(unittest.TestCase):
    """respawn-pane without a command re-runs the pane's old start command: pass a login shell explicitly."""

    class Rec:
        def __init__(self, default_shell=""):
            self.calls, self.default_shell = [], default_shell

        def __call__(self, *a, check=False):
            self.calls.append(a)
            return self.default_shell + "\n" if a[:3] == ("show-options", "-gv", "default-shell") else ""

    def respawn_call(self, rec):
        return [c for c in rec.calls if c[0] == "respawn-pane"][0]

    def test_respawn_pane_ends_with_the_tmux_default_shell_as_login_shell(self):
        rec = self.Rec("/bin/zsh")
        relay.respawn(rec, "%1", "/r", "p")
        self.assertEqual(self.respawn_call(rec), ("respawn-pane", "-k", "-t", "%1", "-c", "/r", "/bin/zsh", "-l"))

    def test_falls_back_to_SHELL_then_bin_sh(self):
        with mock.patch.dict(os.environ, {"SHELL": "/opt/x/fish"}):
            rec = self.Rec("")
            relay.respawn(rec, "%1", "/r")
            self.assertEqual(self.respawn_call(rec)[-2:], ("/opt/x/fish", "-l"))
        with mock.patch.dict(os.environ, {}, clear=True):
            rec = self.Rec("")
            relay.respawn(rec, "%1", "/r")
            self.assertEqual(self.respawn_call(rec)[-2:], ("/bin/sh", "-l"))

    def test_send_keys_still_follow_respawn(self):
        rec = self.Rec("/bin/zsh")
        relay.respawn(rec, "%1", "/r", "p")
        names = [c[0] for c in rec.calls if c[0] in ("respawn-pane", "send-keys")]
        self.assertEqual(names, ["respawn-pane", "send-keys", "send-keys"])
        self.assertEqual(rec.calls[-1], ("send-keys", "-t", "%1", "Enter"))


class RelayTest(unittest.TestCase):
    def test_relay_respawns_and_writes_lineage(self):
        fake = FakeTmux()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, statuses("idle", "idle", "ready", "ready"), \
                mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            msg = relay.relay(fake, "proj", "/d.md", d, "OLD1", sleep=lambda s: None)
            lines = (Path(ld) / "proj.jsonl").read_text().splitlines()
            self.assertFalse((Path(d) / "lineage-proj.jsonl").exists())   # state_dir no longer decides the path
        self.assertIn("relayed", msg)
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual((rec["old_session_id"], rec["doc"], rec["pane"]), ("OLD1", "/d.md", "%5"))
        rp = [c for c in fake.calls if c[0] == "respawn-pane"]
        sk = [c for c in fake.calls if c[0] == "send-keys"]
        self.assertEqual(rp[0], ("respawn-pane", "-k", "-t", "%5", "-c", fake.root, relay.login_shell(fake), "-l"))
        self.assertEqual(sk[0], ("send-keys", "-t", "%5", "-l", "--",
                                 f"cd -- {shlex.quote(fake.root)} && " + shlex.quote(relay.orchestrator())
                                 + " 'Read /d.md and continue from where the previous session left off.'"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%5", "Enter"))
        # the session flags come from claude-orchestrator itself, never from the typed text
        self.assertNotIn("--settings", sk[0][-1])
        self.assertIn(" && " + shlex.quote(relay.orchestrator()) + " ", sk[0][-1])
        self.assertLess(fake.names().index("respawn-pane"), fake.names().index("send-keys"))

    def test_busy_leaves_pane_alone(self):
        fake = FakeTmux()
        clock = iter(range(0, 1000, 2))
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, statuses(*["working"] * 100), \
                mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            with self.assertRaises(RuntimeError):
                relay.relay(fake, "proj", "/d.md", d, "", cap=6, sleep=lambda s: None, clock=lambda: next(clock))
            self.assertFalse((Path(ld) / "proj.jsonl").exists())
        self.assertNotIn("respawn-pane", fake.names())

    def test_failed_start_retries_once_then_raises(self):
        fake = FakeTmux()
        seq = [("claude", "idle"), ("claude", "idle")] + [("shell", "idle")] * 100
        clock = itertools.count(0, 2)
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, redirect_stderr(err), \
                mock.patch.object(paneclass, "pane_status", side_effect=seq), mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            with self.assertRaises(RuntimeError) as cm:
                relay.relay(fake, "proj", "/d.md", d, "OLD1", start_cap=4, sleep=lambda s: None, clock=lambda: next(clock))
            self.assertFalse((Path(ld) / "proj.jsonl").exists())   # no lineage for a lead that never started
        self.assertEqual(fake.names().count("respawn-pane"), 2)
        self.assertIn("did not start", str(cm.exception))
        self.assertIn("| The current directory no longer exists", str(cm.exception))
        self.assertIn("attempt 1", err.getvalue())

    def test_failed_start_recovers_on_retry(self):
        fake = FakeTmux()
        seq = [("claude", "idle"), ("claude", "idle"), ("shell", "idle"), ("shell", "idle"), ("claude", "ready"), ("claude", "ready")]
        clock = itertools.count(0, 2)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, redirect_stderr(io.StringIO()), \
                mock.patch.object(paneclass, "pane_status", side_effect=seq), mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            msg = relay.relay(fake, "proj", "/d.md", d, "OLD1", start_cap=4, sleep=lambda s: None, clock=lambda: next(clock))
            lines = (Path(ld) / "proj.jsonl").read_text().splitlines()
        self.assertIn("relayed", msg)
        self.assertEqual(len(lines), 1)
        self.assertEqual(fake.names().count("respawn-pane"), 2)

    def test_wait_started_needs_two_non_shell_polls(self):
        seq = [("shell", "idle"), ("claude", "ready"), ("shell", "idle"), ("program", "running"), ("claude", "ready")]
        with mock.patch.object(paneclass, "pane_status", side_effect=seq) as ps:
            self.assertTrue(relay.wait_started(None, "%5", sleep=lambda s: None, clock=itertools.count(0, 0).__next__))
        self.assertEqual(ps.call_count, 5)

    def test_launch_line_cds_to_root_first(self):
        self.assertEqual(relay.launch_line("/a b", "go"), "cd -- '/a b' && " + shlex.quote(relay.orchestrator()) + " go")

    def test_main_failure_manual_line_cds_to_root(self):
        err = io.StringIO()
        with mock.patch.object(relay, "relay", side_effect=RuntimeError("boom")), \
                mock.patch.object(relay, "session_root", return_value="/r"), redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", "/tmp"])
        self.assertEqual(rc, 1)
        self.assertIn("\nmanual: cd -- /r && " + shlex.quote(relay.orchestrator()) + " 'Read /d.md", err.getvalue())

    def test_main_failure_prints_manual_command(self):
        err = io.StringIO()
        # session_root is mocked: unmocked it would call the real tmux on the default socket
        with mock.patch.object(relay, "relay", side_effect=RuntimeError("boom")), \
                mock.patch.object(relay, "session_root", side_effect=RuntimeError("no session")), redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", "/tmp"])
        self.assertEqual(rc, 1)
        self.assertIn(shlex.quote(relay.orchestrator()) + " 'Read /d.md", err.getvalue())


class LeadTmux:
    """tmux stub for lead_pane / restart_lead: sessions as (name, group, bg) and windows as {session: [(name, id, pane)]}."""

    def __init__(self, sessions, windows, root="/tmp", status="claude"):
        self.sessions, self.windows, self.root, self.calls = sessions, windows, root, []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-sessions":
            return "".join(f"{n}{SEP}{g}{SEP}{b}\n" for n, g, b in self.sessions)
        if a[0] == "list-windows":
            sess = a[a.index("-t") + 1].lstrip("=").rstrip(":")
            if sess not in self.windows:
                raise RuntimeError(f"can't find session: {sess}")
            return "".join(f"{n}{SEP}{i}{SEP}{p}\n" for n, i, p in self.windows[sess])
        if a[0] == "display":
            return self.root + "\n" if a[-1] == "#{session_path}" else "/bin/zsh\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]


class LeadPaneTest(unittest.TestCase):
    def tmux(self, sessions, windows):
        return LeadTmux(sessions, windows)

    def test_claude_window_wins_over_claude_next(self):
        t = self.tmux([("proj", "", "")], {"proj": [("claude-next", "@2", "%9"), ("claude", "@1", "%5")]})
        self.assertEqual(relay.lead_pane(t, "proj"), ("proj", "%5", "claude"))

    def test_claude_next_when_no_claude(self):
        t = self.tmux([("proj", "", "")], {"proj": [("shell", "@1", "%3"), ("claude-next", "@2", "%9")]})
        self.assertEqual(relay.lead_pane(t, "proj"), ("proj", "%9", "claude-next"))

    def test_none_when_neither(self):
        t = self.tmux([("proj", "", "")], {"proj": [("shell", "@1", "%3")]})
        self.assertIsNone(relay.lead_pane(t, "proj"))

    def test_unknown_project_is_none(self):
        self.assertIsNone(relay.lead_pane(self.tmux([("other", "", "")], {}), "proj"))

    def test_bg_session_is_never_the_project_session(self):
        t = self.tmux([("proj-bg", "", "1"), ("proj", "", "")], {"proj-bg": [("claude", "@7", "%70")], "proj": [("claude", "@1", "%5")]})
        self.assertEqual(relay.lead_pane(t, "proj"), ("proj", "%5", "claude"))

    def test_a_bg_flagged_session_is_never_the_lead_even_under_the_project_name(self):
        t = self.tmux([("proj", "", "1")], {"proj": [("claude", "@1", "%5")]})
        self.assertIsNone(relay.lead_pane(t, "proj"))

    def test_group_name_resolves_to_a_real_member_session(self):
        # a grouped session: the project key is the group; list-windows -t =<group> would fail, a member name works
        t = self.tmux([("proj-web1", "proj", ""), ("proj-bg", "", "1")], {"proj-web1": [("claude", "@1", "%5")]})
        self.assertEqual(relay.lead_pane(t, "proj"), ("proj-web1", "%5", "claude"))
        self.assertTrue(all("=proj-web1" in c or c[0] == "list-sessions" for c in t.calls))


class SessionForPaneTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "home" / "sessions").mkdir(parents=True)
        (self.d / "state" / "agent-status").mkdir(parents=True)

    def sess(self, name, tmux, sid, upd):
        (self.d / "home" / "sessions" / name).write_text(json.dumps({"sessionId": sid, "tmux": tmux, "updatedAt": upd}))

    def got(self, pane="%5"):
        return relay.session_for_pane(pane, str(self.d / "home"), str(self.d / "state"))

    def test_newest_updated_at_for_the_pane(self):
        self.sess("a.json", "proj:@1.%5", "OLD", 100)
        self.sess("b.json", "proj:@1.%5", "NEW", 200)
        self.sess("c.json", "other:@2.%6", "ELSE", 900)
        self.assertEqual(self.got(), "NEW")

    def test_pane_id_must_match_whole_not_a_suffix(self):
        self.sess("a.json", "proj:@1.%45", "WRONG", 100)
        self.assertEqual(self.got(), "")

    def test_falls_back_to_fresh_agent_status(self):
        (self.d / "state" / "agent-status" / "S1.json").write_text(json.dumps(
            {"session_id": "S1", "pane": "%5", "state": "ready", "updatedAt": time.time()}))
        self.assertEqual(self.got(), "S1")

    def test_stale_agent_status_is_ignored(self):
        (self.d / "state" / "agent-status" / "S1.json").write_text(json.dumps(
            {"session_id": "S1", "pane": "%5", "state": "ready", "updatedAt": time.time() - 600}))
        self.assertEqual(self.got(), "")

    def test_sessions_beat_agent_status(self):
        self.sess("a.json", "proj:@1.%5", "FROMSESS", 100)
        (self.d / "state" / "agent-status" / "S1.json").write_text(json.dumps(
            {"session_id": "S1", "pane": "%5", "state": "ready", "updatedAt": time.time()}))
        self.assertEqual(self.got(), "FROMSESS")

    def test_none(self):
        self.assertEqual(self.got(), "")


class NewestHandoffTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "drafts").mkdir()

    def doc(self, rel, project, age):
        p = self.d / rel
        p.write_text(f"Project: {project}\n\n# h\n")
        t = time.time() - age
        os.utime(p, (t, t))
        return str(p)

    def test_newest_of_this_project_ignores_another_projects_newer_doc(self):
        old = self.doc("a.md", "/r/one", 500)
        new = self.doc("b.md", "/r/one", 100)
        self.doc("c.md", "/r/two", 1)
        self.assertEqual(relay.newest_handoff("/r/one", str(self.d)), new)
        self.assertNotEqual(relay.newest_handoff("/r/one", str(self.d)), old)

    def test_drafts_are_not_handoffs(self):
        self.doc("drafts/x.md", "/r/one", 1)
        self.assertIsNone(relay.newest_handoff("/r/one", str(self.d)))

    def test_project_line_must_match_exactly(self):
        self.doc("a.md", "/r/one-more", 10)
        self.doc("b.md", "/r/one ", 10)
        self.assertIsNone(relay.newest_handoff("/r/one", str(self.d)))

    def test_missing_dir_is_none(self):
        self.assertIsNone(relay.newest_handoff("/r/one", str(self.d / "nope")))


class WaitLeadStartedTest(unittest.TestCase):
    def test_needs_a_child_on_two_polls_in_a_row(self):
        seq = iter([True, False, True, True])
        with mock.patch.object(relay, "pane_has_child", side_effect=lambda *a: next(seq)):
            self.assertTrue(relay.wait_lead_started(FakeTmux(), "%5", sleep=lambda s: None))

    def test_a_pane_that_fell_back_to_the_shell_never_counts(self):
        clock = iter(range(0, 1000, 2))
        with mock.patch.object(relay, "pane_has_child", return_value=False):
            self.assertFalse(relay.wait_lead_started(FakeTmux(), "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock)))

    def test_pane_has_child_reads_the_process_table(self):
        out = "  10 1\n  20 10\n  30 99\n"
        t = lambda *a, check=False: "10\n"
        with mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout=out)):
            self.assertTrue(relay.pane_has_child(t, "%5"))
        with mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout="  10 1\n  30 99\n")):
            self.assertFalse(relay.pane_has_child(t, "%5"))


class RestartLeadTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "home" / "sessions").mkdir(parents=True)
        (self.d / "state").mkdir()
        (self.d / "handoffs").mkdir()
        (self.d / "root").mkdir()
        self.root = str((self.d / "root").resolve())
        self.doc = self.d / "handoffs" / "h.md"
        self.doc.write_text(f"Project: {os.path.realpath(self.root)}\n")
        p = mock.patch.object(relay, "pane_has_child", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.env = mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_restart(self, tmux, **kw):
        kw.setdefault("sleep", lambda s: None)
        return relay.restart_lead(tmux, "proj", home=str(self.d / "home"), state=str(self.d / "state"),
                                  handoffs=str(self.d / "handoffs"), **kw)

    def tmux(self, win="claude"):
        return LeadTmux([("proj", "", "")], {"proj": [(win, "@1", "%5")]}, root=self.root)

    def respawn_cmd(self, t):
        c = [c for c in t.calls if c[0] == "respawn-pane"][0]
        return c

    def test_doc_mode_respawns_with_command_and_types_nothing(self):
        t = self.tmux()
        out = self.run_restart(t)
        c = self.respawn_cmd(t)
        self.assertEqual(c[:7], ("respawn-pane", "-k", "-t", "%5", "-c", os.path.realpath(self.root), c[6]))
        self.assertIn(relay.orchestrator(), c[6])
        self.assertIn(shlex.quote(f"Read {self.doc} and continue from where the previous session left off."), c[6])
        self.assertTrue(c[6].endswith("; exec /bin/zsh -l"))
        self.assertNotIn("send-keys", t.names())
        self.assertEqual(out["pane"], "%5")
        self.assertEqual(out["what"], "doc h.md")

    def test_resume_mode_uses_the_pane_session_id(self):
        (self.d / "home" / "sessions" / "a.json").write_text(json.dumps({"sessionId": "SID1", "tmux": "proj:@1.%5", "updatedAt": 5}))
        t = self.tmux()
        out = self.run_restart(t, resume=True)
        self.assertIn(" --resume SID1; exec", self.respawn_cmd(t)[6])
        self.assertEqual(out["what"], "resume SID1")

    def test_resume_without_id_changes_nothing(self):
        t = self.tmux("claude-next")
        with self.assertRaises(relay.LeadRestartError) as cm:
            self.run_restart(t, resume=True)
        self.assertIn("session id", str(cm.exception))
        self.assertTrue(set(t.names()) <= {"list-sessions", "list-windows", "display"})

    def test_no_handoff_changes_nothing(self):
        self.doc.unlink()
        t = self.tmux("claude-next")
        with self.assertRaises(relay.LeadRestartError):
            self.run_restart(t)
        self.assertNotIn("rename-window", t.names())
        self.assertNotIn("respawn-pane", t.names())

    def test_no_lead_pane_message(self):
        t = LeadTmux([("proj", "", "")], {"proj": [("shell", "@1", "%3")]}, root=self.root)
        with self.assertRaises(relay.LeadRestartError) as cm:
            self.run_restart(t)
        self.assertEqual(str(cm.exception), "no lead pane for proj")
        self.assertNotIn("respawn-pane", t.names())

    def test_claude_next_is_renamed_before_the_respawn(self):
        t = self.tmux("claude-next")
        self.run_restart(t)
        n = t.names()
        self.assertLess(n.index("rename-window"), n.index("respawn-pane"))
        self.assertIn(("rename-window", "-t", "%5", "claude"), t.calls)

    def test_explicit_doc_wins_and_resume_with_doc_is_refused(self):
        other = self.d / "mine.md"
        other.write_text("x")
        t = self.tmux()
        self.run_restart(t, doc=str(other))
        self.assertIn(str(other), self.respawn_cmd(t)[6])
        with self.assertRaises(relay.LeadRestartError):
            self.run_restart(self.tmux(), doc=str(other), resume=True)

    def test_not_started_raises_with_the_pane_tail(self):
        with mock.patch.object(relay, "wait_lead_started", return_value=False) as ws:
            with self.assertRaises(relay.LeadRestartError) as cm:
                self.run_restart(self.tmux())
        self.assertEqual(ws.call_args.kwargs["cap"], 60)
        self.assertIn("did not start", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
