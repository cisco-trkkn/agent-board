"""paneclass and tc_env must agree with the one definition in tools/lib/tc-env.zsh."""
import os
import re
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import paneclass  # noqa: E402
import tc_env  # noqa: E402

ZSH_LIB = HERE.parent / "tools" / "lib" / "tc-env.zsh"


def zsh(snippet, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("TC_STATE", "TMPDIR")}
    e.update(env or {})
    return subprocess.run(["zsh", "-fc", f"source {ZSH_LIB}; {snippet}"], capture_output=True, text=True,
                          env=e, check=True).stdout.strip()


class TcEnvTest(unittest.TestCase):
    def test_lib_exists(self):
        self.assertTrue(ZSH_LIB.is_file())

    def test_shells_agree(self):
        self.assertEqual(paneclass.SHELLS, tc_env.SHELLS)
        self.assertEqual(zsh('print -r -- "$TC_SHELLS"'), "(" + "|".join(sorted(tc_env.SHELLS, key=lambda s: zsh_order(s))) + ")")

    def test_prompt_regex_agrees(self):
        self.assertEqual(paneclass.WAITING_RE.pattern, tc_env.PROMPT_PATTERN)
        self.assertEqual(zsh('print -r -- "$TC_PROMPT_RE"'), tc_env.PROMPT_PATTERN)
        self.assertTrue(paneclass.WAITING_RE.flags & re.I)

    def test_prompt_regex_is_valid_ere(self):
        # tmux-ctl tell greps with it: grep -E must match the same sample lines
        for line in ("Do you want to proceed?", "❯ 1. Yes", "Allow this", "(y/n)"):
            r = subprocess.run(["grep", "-qiE", tc_env.PROMPT_PATTERN], input=line, text=True)
            self.assertEqual(r.returncode, 0, line)
        r = subprocess.run(["grep", "-qiE", tc_env.PROMPT_PATTERN], input="just working", text=True)
        self.assertEqual(r.returncode, 1)

    def test_state_dir_agrees(self):
        for env in ({"TC_STATE": "/x/y"}, {"TMPDIR": "/tmp/q/"}, {}):
            saved = {k: os.environ.get(k) for k in ("TC_STATE", "TMPDIR")}
            try:
                for k in saved:
                    os.environ.pop(k, None)
                os.environ.update(env)
                py = str(tc_env.state_dir())
            finally:
                for k, v in saved.items():
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v
            self.assertEqual(py, zsh('print -r -- "$(tc_state_dir)"', env))

    def test_lineage_dir_agrees(self):
        for env in ({"TC_LINEAGE": "/x/l"}, {"XDG_STATE_HOME": "/x/xdg"}, {"HOME": "/x/home"}):
            e = {k: v for k, v in os.environ.items() if k not in ("TC_LINEAGE", "XDG_STATE_HOME")}
            e.update(env)
            with mock.patch.dict(os.environ, e, clear=True):
                py = str(tc_env.lineage_dir())
            self.assertEqual(py, zsh('print -r -- "$TC_LINEAGE_DIR"', {k: v for k, v in e.items()}), env)
        self.assertEqual(zsh('print -r -- "$TC_LINEAGE_DIR"', {"TC_LINEAGE": "/x/l"}), "/x/l")
        self.assertTrue(zsh('print -r -- "$TC_LINEAGE_DIR"', {"HOME": "/x/home"}).endswith("/x/home/.local/state/agent-board/lineage")
                        or "XDG" in os.environ)


def zsh_order(s):
    return ["zsh", "bash", "sh", "fish", "-zsh", "-bash"].index(s)


if __name__ == "__main__":
    unittest.main()
