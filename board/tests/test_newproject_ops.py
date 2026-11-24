"""newproject through discord_ops: the ops events (form, token, Retry click, np_result) dispatched by consume(), and the
leak test over every place the token could land. Fakes and helpers come from test_newproject. Spec: docs/superpowers/
specs/2026-11-23-new-project-remote-design.md §2, §3."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_ops as ops  # noqa: E402
import newproject as np  # noqa: E402
import tc_env  # noqa: E402
from test_newproject import GUILD, NOW, TOKEN, Base  # noqa: E402


class Leak(Base):
    def haystacks(self):
        state = tc_env.agent_base()
        texts = {"state file": (np._dir() / "np1.json").read_text(), "audit": (self.ops / "audit.jsonl").read_text() if (self.ops / "audit.jsonl").exists() else "",
                 "board log": self.err.getvalue(), "cards and replies": json.dumps(self.outbox(), ensure_ascii=False)}
        ev = self.ops / "events"
        texts["events"] = "".join(p.read_text() for p in ev.rglob("*.json")) if ev.exists() else ""
        texts["newproject dir"] = "".join(p.read_text() for p in np._dir().iterdir() if p.is_file())
        return texts

    def through_consume(self, ev):
        """Write ev as the ops bridge would and let discord_ops.consume dispatch it."""
        e = self.ops / "events"
        e.mkdir(exist_ok=True)
        (e / f"{len(list(e.iterdir())):04d}.json").write_text(json.dumps(ev))
        ops.consume(lambda *a: None, lambda argv: "", NOW)

    def paste_via_consume(self, tok=TOKEN, user="U1"):
        d = np.token_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "1700000000001-0a1b2c3d.tok"
        f.write_text(tok)
        self.through_consume({"type": "np_token", "name": "np1", "file": f.name, "user": user, "iid": "I2", "ts": 1})
        return f

    def test_full_run_leaves_the_token_nowhere(self):
        # mutation: write the token into the state (st["token"] = tok in on_token) -> the state file check fails
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        f = self.paste_via_consume()
        self.rest.guilds = [GUILD]
        self.clock.t += np.POLL_S
        np.tick(self.ops, self.clock.t)
        self.through_consume({"type": "np_result", "action": "create_channel", "name": "np1", "req": self.last_op("create_channel")["req"], "ok": True, "channel_id": "555", "ts": 2})
        self.through_consume({"type": "np_result", "action": "channel_overwrite", "name": "np1", "req": self.last_op("channel_overwrite")["req"], "ok": True, "ts": 3})
        self.assertTrue(self.state()["done"])
        self.assertFalse(f.exists())
        self.assertEqual(list(np.token_dir().iterdir()), [])
        for where, text in self.haystacks().items():
            self.assertNotIn(TOKEN, text, where)

    def test_failed_token_step_leaves_the_token_nowhere_even_when_the_tool_echoes_it(self):
        # mutation: drop _scrub in _start.go -> the echoed token reaches the state file and the card
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        self.ctl.fail["discord token"] = (1, f"discord: could not write {TOKEN}")
        f = self.paste_via_consume()
        self.assertEqual(self.steps()["bot"], "waiting")
        self.assertIn("could not save the token: discord: could not write ***", self.state()["steps"]["bot"]["error"])
        self.assertFalse(f.exists())
        for where, text in self.haystacks().items():
            self.assertNotIn(TOKEN, text, where)

    def test_a_token_from_a_non_allowlisted_user_is_deleted_and_rejected(self):
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "new", "target": ""}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        f = self.paste_via_consume(user="EVIL")
        self.assertFalse(f.exists())
        self.assertEqual(self.ctl.argvs(("discord", "token")), [])
        self.assertEqual(json.loads((self.ops / "audit.jsonl").read_text().splitlines()[-1])["result"], "rejected")

    def test_retry_clicks_reach_the_step_machine_through_consume(self):
        self.ctl.fail["project new"] = (1, "project: clone failed: fatal: x")
        self.through_consume({"type": "modal", "form": "new-project", "fields": {"name": "np1", "source": "clone", "target": "u"}, "user": "U1", "channel_id": "CC", "iid": "I1", "ts": 1})
        del self.ctl.fail["project new"]
        self.through_consume({"type": "click", "custom_id": "ab:np:retry:np1:disk", "user": "U1", "message_id": "m1", "channel_id": "CC", "ts": 2})
        self.assertEqual(self.steps()["disk"], "done")
        self.through_consume({"type": "click", "custom_id": "ab:np:retry:np1:disk", "user": "EVIL", "message_id": "m1", "channel_id": "CC", "ts": 3})
        self.assertEqual(json.loads((self.ops / "audit.jsonl").read_text().splitlines()[-1])["result"], "rejected")


if __name__ == "__main__":
    unittest.main()
