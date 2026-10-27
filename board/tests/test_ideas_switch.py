"""The ideas box follows the project: A -> B -> A must show A's ideas even when A's poll answers 304."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BOARD = Path(__file__).resolve().parent.parent


def grab(html, pattern, what):
    m = re.search(pattern, html, re.S | re.M)
    assert m, f"{what} not found in index.html"
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's pollIdeas")
class IdeasSwitchTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        js = """
const IDEAS = {A: [{status:"open", ts:"t", text:"alpha", detail:"", key:"a", moved_to:""}],
               B: [{status:"open", ts:"t", text:"beta", detail:"", key:"b", moved_to:""}]};
let cur = "A";
const session = () => ({name: cur});
const API = "", POLL = new Map();
// a server with ETags: the same body gives the same ETag, and If-None-Match on it is a 304
const fetch = async (url, o) => {
  const name = url.split("session=")[1], body = JSON.stringify({ideas: IDEAS[name], open: IDEAS[name].length}), etag = '"' + body.length + name + '"';
  if (o.headers["If-None-Match"] === etag) return {ok: false, status: 304, headers: {get: () => etag}};
  return {ok: true, status: 200, headers: {get: () => etag}, json: async () => JSON.parse(body)};
};
function mk() {
  const n = {children: [], dataset: {}, textContent: "", append(...c) { this.children.push(...c); }, replaceChildren(...c) { this.children = c; },
             querySelector(sel) { return this.children.find((c) => c.cls && sel.includes(c.cls.split(" ")[0])) || null; }};
  return n;
}
const el = (tag, cls, text) => { const n = mk(); n.cls = cls || ""; n.textContent = text || ""; n.tag = tag; return n; };
const box = mk();
const $ = () => box;
const bindAgentMenu = () => {}, post = async () => ({status: 200, j: {}}), toast = () => {};
window = {};
let ideaEditing = null, ideaShowDropped = false;
let ideasShown = null;
%s
%s
const rows = () => box.querySelector(".ideas-list").children.map((r) => r.textContent);
(async () => {
%s
})().catch((e) => { console.log("ERR", e.stack); process.exit(2); });
""" % (grab(html, r"^async function pollJSON\(path\) \{.*?^\}\n", "pollJSON"),
       grab(html, r"^async function pollIdeas\(\) \{.*?^\}\n", "pollIdeas"), scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def test_back_to_first_project_shows_its_ideas(self):
        r = self.run_page("""
cur = "A"; await pollIdeas(); const a1 = rows().join();
cur = "B"; await pollIdeas(); const b = rows().join();
cur = "A"; await pollIdeas(); const a2 = rows().join();   // A's URL has a cached ETag: the server answers 304
console.log(a1, b, a2);
if (a1 !== "alpha" || b !== "beta" || a2 !== "alpha") process.exit(1);
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unchanged_poll_of_the_same_project_does_not_rebuild(self):
        r = self.run_page("""
await pollIdeas(); const first = box.querySelector(".ideas-list").children[0];
await pollIdeas();
if (box.querySelector(".ideas-list").children[0] !== first) { console.log("REBUILT"); process.exit(1); }
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
