"""Ticking "Show dropped" re-renders the Ideas box at once from the last data, without a fetch.
Runs the page's own pollJSON and pollIdeas under node with stubbed fetch/el/$ (the harness of test_ideas_gitlab_ui.py);
here fetch answers 304 when If-None-Match matches, as the server does for an unchanged list."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BOARD = Path(os.environ.get("BOARD_DIR") or Path(__file__).resolve().parent.parent)


def grab(html, pattern, what):
    m = re.search(pattern, html, re.S | re.M)
    assert m, f"{what} not found in index.html"
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's pollIdeas")
class IdeasDroppedUiTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        js = """
let PAYLOAD = null, FETCHES = 0;
const session = () => ({name: "A"});
const API = "", POLL = new Map();
// one fixed ETag: the first call answers 200, every later conditional call 304 (an unchanged list)
const fetch = async (url, opts) => {
  FETCHES++;
  const inm = opts && opts.headers && opts.headers["If-None-Match"];
  if (inm === "e1") return {ok: false, status: 304, headers: {get: () => "e1"}, json: async () => null};
  return {ok: true, status: 200, headers: {get: () => "e1"}, json: async () => JSON.parse(JSON.stringify(PAYLOAD))};
};
function mk() {
  return {children: [], dataset: {}, textContent: "", append(...c) { this.children.push(...c); }, replaceChildren(...c) { this.children = c; },
          querySelector(sel) { return this.children.find((c) => c.cls && sel.includes(c.cls.split(" ")[0])) || null; }};
}
const el = (tag, cls, text) => { const n = mk(); n.cls = cls || ""; n.textContent = text || ""; n.tag = tag; return n; };
const box = mk();
const $ = () => box;
const bindAgentMenu = () => {}, post = async () => ({status: 200, j: {}}), toast = () => {};
const localStorage = {setItem() {}};
window = {};
let ideaEditing = null, ideaShowDropped = false, ideasShown = null;
%s
%s
const idea = (status, text) => ({status, ts: "t", text, detail: "", key: text, moved_to: "", issue: null});
const rows = () => box.querySelector(".ideas-list").children.map((r) => r.textContent);
const checkbox = () => box.children.flatMap((c) => c.children || []).find((c) => c.id === "ideas-show-dropped");
(async () => {
%s
})().catch((e) => { console.log("ERR", e.stack); process.exit(2); });
""" % (grab(html, r"^async function pollJSON\(path\) \{.*?^\}\n", "pollJSON"),
       grab(html, r"^async function pollIdeas\([^)]*\) \{.*?^\}\n", "pollIdeas"), scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def check(self, scenario):
        r = self.run_page(scenario)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_toggle_shows_then_hides_dropped_without_fetch(self):
        # mutation: cb.onchange calls pollIdeas() (no cache) -> the 304 early return keeps "gone" hidden
        self.check("""
PAYLOAD = {ideas: [idea("open", "keep"), idea("dropped", "gone")], open: 1, gitlab: null};
await pollIdeas();
await pollIdeas();   // an unchanged poll (304) renders nothing new
if (rows().join() !== "keep") { console.log("before", rows()); process.exit(1); }
const before = FETCHES, cb = checkbox();
cb.checked = true; await cb.onchange();
if (rows().join() !== "keep,gone") { console.log("after tick", rows()); process.exit(1); }
cb.checked = false; await cb.onchange();
if (rows().join() !== "keep") { console.log("after untick", rows()); process.exit(1); }
if (FETCHES !== before) { console.log("toggle fetched", FETCHES - before); process.exit(1); }
""")

    def test_toggle_before_any_data_fetches(self):
        # no cached reply yet: the toggle falls back to a normal poll
        # mutation: return early when there is no cache -> rows stay [ 'keep' ]
        self.check("""
PAYLOAD = {ideas: [idea("open", "keep"), idea("dropped", "gone")], open: 1, gitlab: null};
await pollIdeas();
POLL.clear();
const cb = checkbox(), before = FETCHES;
cb.checked = true; await cb.onchange();
if (FETCHES !== before + 1) { console.log("expected one fetch", FETCHES - before); process.exit(1); }
if (rows().join() !== "keep,gone") { console.log("rows", rows()); process.exit(1); }
""")


if __name__ == "__main__":
    unittest.main()
