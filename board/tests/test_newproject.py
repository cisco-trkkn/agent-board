"""newproject: the /new-project step machine against a fake Discord REST and a fake tmux-ctl (argv recorded).
Scratch TC_STATE and HOME; workers run inline (_spawn); the clock is a FakeClock. Spec: docs/superpowers/specs/
2026-11-23-new-project-remote-design.md §1-§3."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import newproject as np  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0
TOKEN = "NEWBOT.tok3n.SECRETSECRETSECRETSECRETSECRET"
GUILD = "999"


class FakeClock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class FakeRest:
    """Answers by path; the token must be TOKEN or the answer is 401. calls: [(method, path)]."""
    def __init__(self):
        self.calls = []
        self.flags = 1 << 18
        self.guilds = []
        self.me = (200, {"id": "777", "username": "np1-bot"})

    def __call__(self, method, path, token):
        self.calls.append((method, path))
        if token != TOKEN:
            return 401, None
        if path == "/users/@me":
            return self.me
        if path == "/applications/@me":
            return 200, {"id": "777", "flags": self.flags}
        if path == "/users/@me/guilds":
            return 200, [{"id": g} for g in self.guilds]
        return 404, None


class FakeCtl:
    """Records (argv after tmux-ctl, stdin); `discord token` saves stdin to the project's .env like the real one.
    fail: {first two argv words joined: (rc, output)}."""
    def __init__(self):
        self.calls = []
        self.fail = {}

    def __call__(self, argv, stdin=None, timeout=180):
        args = [str(a) for a in argv[1:]] if str(argv[0]).endswith("tmux-ctl") else [str(a) for a in argv]
        self.calls.append((args, stdin))
        if args[:1] == ["git"]:   # the folder refusal's own git call
            import subprocess
            r = subprocess.run(args, capture_output=True, text=True)
            return r.returncode, (r.stdout + r.stderr).strip()
        key = " ".join(args[:2])
        if key in self.fail:
            return self.fail[key]
        if args[:2] == ["project", "new"]:
            if args[3] == "--dir":
                return 0, args[4]
            d = Path.home() / args[2]
            d.mkdir(parents=True, exist_ok=True)
            return 0, str(d)
        if args[:2] == ["discord", "token"]:
            dd = tc_env.discord_dir(args[3])
            dd.mkdir(parents=True, exist_ok=True)
            (dd / ".env").write_text(f"DISCORD_BOT_TOKEN={stdin.strip()}\n")
            return 0, f"discord: token saved for {args[3]}"
        return 0, "ok"

    def argvs(self, prefix=()):
        return [a for a, _ in self.calls if tuple(a[:len(prefix)]) == tuple(prefix) and a[:1] != ["git"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(Path(self.tmp.name) / "state"), "HOME": str(home)})
        p.start()
        self.addCleanup(p.stop)
        self.home = home
        self.ops = tc_env.ops_dir()
        self.ops.mkdir(parents=True)
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "CC", "approvals": "AP", "user": "U1"}))
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        (self.ops / "bridge-state.json").write_text(json.dumps({"guild_id": GUILD}))
        self.rest, self.ctl, self.clock = FakeRest(), FakeCtl(), FakeClock()
        self.sessions = set()
        self.err = io.StringIO()
        for patcher in (mock.patch.object(np, "_http", self.rest), mock.patch.object(np, "_run", self.ctl),
                        mock.patch.object(np, "_spawn", lambda fn: fn()), mock.patch.object(np, "_clock", self.clock),
                        mock.patch.object(np, "_session_exists", lambda n: n in self.sessions),
                        mock.patch("sys.stderr", self.err)):
            patcher.start()
            self.addCleanup(patcher.stop)

    # ---- helpers ----
    def outbox(self):
        box = self.ops / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def ireplies(self):
        return [o["content"] for o in self.outbox() if o["op"] == "ireply"]

    def cards(self):
        return [o for o in self.outbox() if o["op"] in ("post", "edit") and str(o.get("key", "")).startswith("np:")]

    def last_card(self):
        return self.cards()[-1]

    def state(self, name="np1"):
        return np.load(name)

    def steps(self, name="np1"):
        return {s: v["state"] for s, v in self.state(name)["steps"].items()}

    def modal(self, name="np1", source="new", target="", channel="CC", user="U1"):
        return np.on_modal(self.ops, {"type": "modal", "form": "new-project", "fields": {"name": name, "source": source, "target": target},
                                      "user": user, "channel_id": channel, "iid": "I1"})

    def paste(self, name="np1", tok=TOKEN):
        d = np.token_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "1700000000001-0a1b2c3d.tok"
        f.write_text(tok)
        return np.on_token(self.ops, {"type": "np_token", "name": name, "file": f.name, "user": "U1", "iid": "I2"}), f

    def result(self, op, **kw):
        return np.on_result(self.ops, {"type": "np_result", "action": op["op"], "name": op["name"], "req": op["req"], **kw})

    def last_op(self, kind):
        return [o for o in self.outbox() if o["op"] == kind][-1]

    def to_joined(self):
        self.modal()
        self.paste()
        self.assertEqual(self.steps()["joined"], "waiting")

    def to_channel(self):
        self.to_joined()
        self.rest.guilds = [GUILD]
        self.clock.t += np.POLL_S
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.steps()["channel"], "running")


class FullRun(Base):
    def test_new_source_runs_every_step_in_order_to_the_hello(self):
        self.assertEqual(self.modal(), "started")
        self.assertEqual(self.ctl.argvs(("project", "new")), [["project", "new", "np1", "--init"]])
        self.assertEqual(self.steps()["disk"], "done")
        self.assertEqual(self.state()["dir"], str(self.home / "np1"))
        self.assertEqual(self.steps()["bot"], "waiting")
        card = self.last_card()
        self.assertIn("New Application → Bot → turn on Message Content Intent → Reset Token", card["text"])
        self.assertIn(np.PORTAL, card["text"])
        self.assertEqual(card["rows"], [[{"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}]])
        self.assertEqual(self.paste()[0], "token received")
        self.assertEqual([c for c in self.ctl.calls if c[0][:2] == ["discord", "token"]], [(["discord", "token", "--project", "np1"], TOKEN + "\n")])
        self.assertEqual(self.steps()["check"], "done")
        self.assertEqual((self.state()["bot_id"], self.state()["app_id"]), ("777", "777"))
        self.assertIn(f"https://discord.com/oauth2/authorize?client_id=777&scope=bot&permissions=2252109051432000&guild_id={GUILD}&disable_guild_select=true",
                      self.last_card()["text"])
        self.assertEqual(self.steps()["joined"], "waiting")
        np.tick(self.ops, self.clock.t + 1)                 # not in the guild yet
        self.assertEqual(self.steps()["joined"], "waiting")
        self.rest.guilds = [GUILD]
        np.tick(self.ops, self.clock.t + 5)                 # under 10 s since the last poll: no poll
        self.assertEqual(self.rest.calls.count(("GET", "/users/@me/guilds")), 1)
        self.clock.t += np.POLL_S + 1
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.steps()["joined"], "done")
        cc = self.last_op("create_channel")
        self.assertEqual({k: cc[k] for k in ("guild", "name")}, {"guild": GUILD, "name": "np1"})
        self.assertEqual(self.result(cc, ok=True, channel_id="555"), "channel created")
        ow = self.last_op("channel_overwrite")
        self.assertEqual({k: ow[k] for k in ("channel", "user", "allow")}, {"channel": "555", "user": "777", "allow": "2252109051432000"})
        self.assertEqual(self.result(ow, ok=True), "done")
        self.assertEqual(self.ctl.argvs(("discord",))[1:], [
            ["discord", "allow", "U1", "--project", "np1"], ["discord", "policy", "allowlist", "--project", "np1"],
            ["discord", "channel", "555", "--project", "np1"], ["discord", "bridge", "start", "--project", "np1"]])
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np1"]])
        self.assertTrue(self.state()["done"])
        self.assertTrue(all(v == "done" for v in self.steps().values()))
        self.assertIn(f"Done: https://discord.com/channels/{GUILD}/555", self.last_card()["text"])
        self.assertEqual(self.last_card()["rows"], [])

    def test_clone_and_folder_pass_their_source_to_project_new(self):
        self.modal(name="np2", source="clone", target="git@x:y/np2.git")
        self.assertEqual(self.ctl.argvs(("project", "new")), [["project", "new", "np2", "--clone", "git@x:y/np2.git"]])
        repo = self.home / "src" / "np3"
        repo.mkdir(parents=True)
        os.system(f"git init -q -b main {repo}")
        self.modal(name="np3", source="folder", target=str(repo))
        self.assertEqual(self.ctl.argvs(("project", "new"))[-1], ["project", "new", "np3", "--dir", str(repo)])

    def test_folder_start_passes_the_folder(self):
        # mutation: drop the --dir extra in _do_start -> project start gets no --dir and the session opens ~/np3
        repo = self.home / "src" / "np3"
        repo.mkdir(parents=True)
        os.system(f"git init -q -b main {repo}")
        self.modal(name="np3", source="folder", target=str(repo))
        st = self.state("np3")
        self.assertEqual(st["dir"], str(repo))
        for s in ("disk", "bot", "check", "joined", "channel", "access"):
            st["steps"][s]["state"] = "done"
        st["steps"]["start"]["state"] = "pending"
        st["channel_id"] = "555"
        np._save(st)
        np._advance(self.ops, "np3")
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np3", "--dir", str(repo)]])


class Refusals(Base):
    def refused(self, *a, **kw):
        r = self.modal(*a, **kw)
        self.assertTrue(r.startswith("refused"), r)
        self.assertIsNone(np.load(kw.get("name", "np1")))
        self.assertEqual(self.cards(), [])
        self.assertEqual(self.ctl.argvs(("project",)), [])
        return self.ireplies()[-1]

    def test_bad_name(self):
        self.assertIn("Bad name", self.refused(name="a.b"))

    def test_existing_project_state_dir(self):
        tc_env.discord_dir("np1").mkdir(parents=True)
        self.assertIn("A project state dir for np1 already exists", self.refused())

    def test_existing_tmux_session(self):
        self.sessions.add("np1")
        self.assertEqual(self.refused(), "A tmux session np1 already exists.")

    def test_existing_home_folder_for_new_and_clone(self):
        (self.home / "np1").mkdir()
        self.assertEqual(self.refused(), "~/np1 already exists.")
        self.assertEqual(self.refused(source="clone", target="u"), "~/np1 already exists.")

    def test_folder_not_a_work_tree_or_misnamed(self):
        plain = self.home / "np1"
        plain.mkdir()
        self.assertIn("is not a git work tree", self.refused(source="folder", target=str(plain)))
        other = self.home / "other"
        other.mkdir()
        os.system(f"git init -q -b main {other}")
        self.assertIn("The folder is named other, not np1", self.refused(source="folder", target=str(other)))

    def test_outside_the_command_center(self):
        self.assertEqual(self.refused(channel="AP"), "Use /new-project in the command center.")

    def test_ops_bot_not_connected(self):
        (self.ops / "bridge-state.json").unlink()
        self.assertIn("has not connected yet", self.refused())


class Failures(Base):
    def test_clone_failure_shows_gits_line_and_retry_reruns_only_disk(self):
        self.ctl.fail["project new"] = (1, "project: clone failed: fatal: repository 'u' not found")
        self.modal(source="clone", target="u")
        self.assertEqual(self.steps()["disk"], "failed")
        self.assertEqual(self.state()["steps"]["disk"]["error"], "project: clone failed: fatal: repository 'u' not found")
        self.assertIn({"label": "Retry project on disk", "style": 2, "custom_id": "ab:np:retry:np1:disk"}, self.last_card()["rows"][0])
        self.assertEqual(self.steps()["bot"], "pending")
        del self.ctl.fail["project new"]
        self.assertEqual(np.on_click(self.ops, "U1", "ab:np:retry:np1:disk"), "retrying")
        self.assertEqual(len(self.ctl.argvs(("project", "new"))), 2)
        self.assertEqual((self.steps()["disk"], self.steps()["bot"]), ("done", "waiting"))

    def test_a_done_step_reruns_nothing(self):
        self.modal()
        n = len(self.ctl.calls)
        self.assertEqual(np.on_click(self.ops, "U1", "ab:np:retry:np1:disk"), "not failed")
        self.assertEqual(len(self.ctl.calls), n)

    def test_token_rejected_asks_for_the_token_again(self):
        self.modal()
        self.paste(tok="WRONG.token.value")
        self.assertEqual(self.steps()["check"], "failed")
        self.assertEqual(self.state()["steps"]["check"]["error"], "token rejected")
        self.assertEqual(self.steps()["bot"], "waiting")
        self.assertIn({"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}, self.last_card()["rows"][0])
        self.paste()
        self.assertEqual((self.steps()["check"], self.steps()["joined"]), ("done", "waiting"))

    def test_intent_off_stops_before_the_invite_and_retry_checks_again(self):
        # mutation: drop the INTENT_FLAGS test -> check is done and joined waits
        self.rest.flags = 0
        self.modal()
        self.paste()
        self.assertEqual(self.state()["steps"]["check"]["error"], "turn on Message Content Intent, then Retry")
        self.assertEqual(self.steps()["joined"], "pending")
        self.assertNotIn("oauth2/authorize", self.last_card()["text"])
        self.rest.flags = 1 << 19   # the LIMITED flag counts too
        np.on_click(self.ops, "U1", "ab:np:retry:np1:check")
        self.assertEqual(self.steps()["joined"], "waiting")

    def test_invite_not_accepted_after_30_minutes_and_retry_polls_again(self):
        self.to_joined()
        self.clock.t += np.JOIN_TIMEOUT_S
        np.tick(self.ops, self.clock.t)
        self.assertEqual(self.state()["steps"]["joined"]["error"], "invite not accepted")
        np.on_click(self.ops, "U1", "ab:np:retry:np1:joined")
        self.assertEqual(self.steps()["joined"], "waiting")
        self.assertEqual(self.state()["join"]["since"], self.clock.t)

    def test_missing_manage_channels_then_retry_sends_a_new_create(self):
        self.to_channel()
        first = self.last_op("create_channel")
        self.assertEqual(self.result(first, ok=False, error="missing permissions"), "failed")
        self.assertEqual(self.state()["steps"]["channel"]["error"], "ops bot lacks Manage Channels")
        np.on_click(self.ops, "U1", "ab:np:retry:np1:channel")
        second = self.last_op("create_channel")
        self.assertNotEqual(first["req"], second["req"])
        # mutation: drop the req match in on_result -> the late answer to the first op creates the channel
        self.assertEqual(self.result(first, ok=True, channel_id="1"), "stale")
        self.assertIsNone(self.state()["channel_id"])
        self.result(second, ok=True, channel_id="555")
        self.assertEqual(self.state()["channel_id"], "555")

    def test_overwrite_refused_names_manage_roles_and_retry_skips_the_create(self):
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        self.result(self.last_op("channel_overwrite"), ok=False, error="missing permissions")
        self.assertIn("lacks Manage Roles", self.state()["steps"]["channel"]["error"])
        n = len([o for o in self.outbox() if o["op"] == "create_channel"])
        np.on_click(self.ops, "U1", "ab:np:retry:np1:channel")
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "create_channel"]), n)
        self.assertEqual(self.result(self.last_op("channel_overwrite"), ok=True), "done")

    def test_a_repeated_answer_after_done_changes_nothing(self):
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        ow = self.last_op("channel_overwrite")
        self.result(ow, ok=True)
        n = len(self.ctl.calls)
        self.assertEqual(self.result(ow, ok=True), "stale")
        self.assertEqual(len(self.ctl.calls), n)

    def test_bridge_that_does_not_start_keeps_the_earlier_steps(self):
        # mutation: make on_click reset every step to pending -> the access step reruns and n_access grows
        self.ctl.fail["discord bridge"] = (1, "bridge: node_modules missing (tmux-ctl discord bridge install)")
        self.to_channel()
        self.result(self.last_op("create_channel"), ok=True, channel_id="555")
        self.result(self.last_op("channel_overwrite"), ok=True)
        self.assertEqual(self.state()["steps"]["start"]["error"], "bridge: bridge: node_modules missing (tmux-ctl discord bridge install)")
        self.assertTrue(all(self.steps()[s] == "done" for s in np.STEPS[:-1]))
        self.assertEqual(self.ctl.argvs(("project", "start")), [])
        del self.ctl.fail["discord bridge"]
        n_access = len(self.ctl.argvs(("discord", "allow")))
        np.on_click(self.ops, "U1", "ab:np:retry:np1:start")
        self.assertEqual(len(self.ctl.argvs(("discord", "allow"))), n_access)
        self.assertEqual(self.ctl.argvs(("project", "start")), [["project", "start", "np1"]])
        self.assertTrue(self.state()["done"])


class Resume(Base):
    def test_slash_resumes_an_unfinished_setup_on_a_new_card(self):
        self.modal()
        self.assertEqual(np.on_slash(self.ops, {"name": "np1", "channel_id": "CC", "iid": "I3"}), "resumed")
        old, new = self.cards()[-2:]
        self.assertEqual((old["op"], old["key"], old["rows"]), ("edit", "np:np1:1", []))
        self.assertIn("(moved to a new card below)", old["text"])
        self.assertEqual((new["op"], new["key"]), ("post", "np:np1:2"))
        self.assertEqual(new["rows"], [[{"label": "Paste token", "style": 1, "custom_id": "ab:np:token:np1"}]])
        self.paste()
        self.assertEqual(self.last_card()["key"], "np:np1:2")

    def test_the_form_with_an_unfinished_name_resumes_instead_of_refusing(self):
        self.modal()
        self.assertEqual(self.modal(), "resumed")
        self.assertEqual(len(self.ctl.argvs(("project", "new"))), 1)

    def test_unknown_and_finished_setups(self):
        self.assertEqual(np.on_slash(self.ops, {"name": "zz", "channel_id": "CC", "iid": "I3"}), "no setup")
        self.modal()
        st = self.state()
        st["done"] = True
        np._save(st)
        self.assertEqual(np.on_slash(self.ops, {"name": "np1", "channel_id": "CC", "iid": "I3"}), "already set up")


class Robustness(Base):
    def test_stale_worker_result_is_dropped(self):
        # mutation: drop the run-id guard in _start.go -> the late result marks disk done
        held = []
        with mock.patch.object(np, "_spawn", held.append):
            self.modal()
        st = self.state()
        st["steps"]["disk"]["run"] = "other"
        np._save(st)
        held[0]()
        self.assertEqual(self.steps()["disk"], "running")
        self.assertIn("np1 disk: stale result dropped", self.err.getvalue())

    def test_a_running_step_with_no_answer_fails_after_15_minutes(self):
        with mock.patch.object(np, "_spawn", lambda fn: None):
            self.modal()
        np.tick(self.ops, NOW + np.STALE_RUN_S + 1)
        self.assertEqual(self.state()["steps"]["disk"]["error"], "interrupted; Retry")

    def test_token_for_a_setup_not_waiting_is_deleted_unread(self):
        r, f = self.paste(name="ghost")
        self.assertEqual(r, "not waiting")
        self.assertFalse(f.exists())
        self.assertEqual(self.ctl.argvs(("discord", "token")), [])

    def test_a_file_name_outside_the_token_dir_is_never_read(self):
        secret = self.home / "secret.txt"
        secret.write_text("x")
        self.modal()
        r = np.on_token(self.ops, {"type": "np_token", "name": "np1", "file": "../../home/secret.txt", "user": "U1", "iid": "I2"})
        self.assertEqual(r, "bad token")
        self.assertTrue(secret.exists())

    def test_orphan_token_files_are_swept_after_10_minutes(self):
        d = np.token_dir()
        d.mkdir(parents=True)
        f = d / "1-00000000.tok"
        f.write_text(TOKEN)
        os.utime(f, (NOW - np.TOKEN_FILE_TTL_S - 1, NOW - np.TOKEN_FILE_TTL_S - 1))
        np.tick(self.ops, NOW)
        self.assertFalse(f.exists())


if __name__ == "__main__":
    unittest.main()
