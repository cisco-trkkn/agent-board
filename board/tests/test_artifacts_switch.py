"""The artifacts pane follows the project: A -> B -> A must render A's items even when A's poll answers 304."""
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


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's pollArtifacts")
class ArtifactsSwitchTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        js = """
const item = (p) => ({path: p, url: "", kind: "plan", title: "", history: [], latest: {ts: 1, epoch: 0, hash: "h", agent: "x"}, first_ts: 1, dismissed: false});
const DATA = {A: [item("/a/one.md")], B: [item("/b/two.md")]};
let cur = "A";
const session = () => ({name: cur});
const API = "", POLL = new Map();
let gets = 0;
// a server with ETags: the same body gives the same ETag, and If-None-Match on it is a 304
const fetch = async (url, o) => {
  gets++;
  const name = url.split("session=")[1], body = JSON.stringify({epoch: 0, active_plan: null, started_from: null, items: DATA[name], sections: [], dismissed: [], comments: []}), etag = '"' + body.length + name + '"';
  if (o.headers["If-None-Match"] === etag) return {ok: false, status: 304, headers: {get: () => etag}};
  return {ok: true, status: 200, headers: {get: () => etag}, json: async () => JSON.parse(body)};
};
const ART = {};
const artFor = (n) => ART[n] || (ART[n] = {items: new Map(), versions: new Map(), seen: new Map(), loadedAt: 0, plan: null, comments: [], sections: []});
let rendered = [];   // what each renderArtifacts() call would draw: the project's items
const renderArtifacts = () => { rendered.push([...artFor(session().name).items.keys()].join()); };
const trackVersion = async () => {}, renderDoc = () => {}, toast = () => {};
const $ = () => ({onclick() {}});
const getSelection = () => null;
let docSel = null, docSess = null, docMode = "read", docRendered = null;
let artShown = null;
%s
%s
(async () => {
%s
})().catch((e) => { console.log("ERR", e.stack); process.exit(2); });
""" % (grab(html, r"^async function pollJSON\(path\) \{.*?^\}\n", "pollJSON"),
       grab(html, r"^async function pollArtifacts\(\) \{.*?^\}\n", "pollArtifacts"), scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def test_back_to_first_project_renders_its_items(self):
        r = self.run_page("""
cur = "A"; await pollArtifacts(); const a1 = rendered[rendered.length - 1];
cur = "B"; await pollArtifacts(); const b = rendered[rendered.length - 1];
cur = "A"; await pollArtifacts(); const a2 = rendered[rendered.length - 1];   // A's URL has a cached ETag: the server answers 304
console.log(a1, b, a2);
if (a1 !== "/a/one.md" || b !== "/b/two.md" || a2 !== "/a/one.md") process.exit(1);
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_unchanged_poll_of_the_same_project_does_not_rebuild(self):
        r = self.run_page("""
await pollArtifacts(); const n = rendered.length;
await pollArtifacts();
if (rendered.length !== n) { console.log("REBUILT"); process.exit(1); }
""")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
