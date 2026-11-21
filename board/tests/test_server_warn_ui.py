"""The board's tmux server cwd banner: renderServerWarn shows data.server_warning and hides itself when it is empty.
Runs the page's own function under node with a stubbed $ (the harness style of test_ideas_dropped_ui.py)."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BOARD = Path(os.environ.get("BOARD_DIR") or Path(__file__).resolve().parent.parent)


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's renderServerWarn")
class ServerWarnUiTest(unittest.TestCase):
    def setUp(self):
        self.html = (BOARD / "index.html").read_text()

    def test_banner_element_and_render_call(self):   # mutation: drop renderServerWarn() from render() -> fails
        self.assertIn('id="server-warn"', self.html)
        self.assertRegex(self.html, r"function render\(\) \{[^\n]*\n[^\n]*renderServerWarn\(\)")

    def test_shows_then_hides(self):   # mutation: drop `b.hidden = !w` -> the second state stays visible
        fn = re.search(r"^function renderServerWarn\(\) \{.*?$", self.html, re.M)
        self.assertIsNotNone(fn, "renderServerWarn not found in index.html")
        js = fn.group(0) + """
const B = {textContent: "", hidden: true}; const $ = () => B; let data;
const out = [];
data = {server_warning: "tmux server cwd is gone (/x): new panes start there"}; renderServerWarn(); out.push([B.textContent, B.hidden]);
data = {server_warning: ""}; renderServerWarn(); out.push([B.textContent, B.hidden]);
data = null; renderServerWarn(); out.push([B.textContent, B.hidden]);
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         '[["tmux server cwd is gone (/x): new panes start there",false],["",true],["",true]]')


if __name__ == "__main__":
    unittest.main()
