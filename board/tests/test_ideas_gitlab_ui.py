"""The Ideas box shows a GitLab #N link per idea with an issue, and a warning while the sync is failing.
Runs the page's own pollIdeas under node with stubbed fetch/el/$ (the harness of test_ideas_switch.py)."""
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
class IdeasGitlabUiTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        js = """
let PAYLOAD = null, N = 0;
const session = () => ({name: "A"});
const API = "", POLL = new Map();
// every call answers 200 with a new ETag, so each poll is "changed"
const fetch = async () => ({ok: true, status: 200, headers: {get: () => String(++N)}, json: async () => JSON.parse(JSON.stringify(PAYLOAD))});
function mk() {
  return {children: [], dataset: {}, textContent: "", append(...c) { this.children.push(...c); }, replaceChildren(...c) { this.children = c; },
          querySelector(sel) { return this.children.find((c) => c.cls && sel.includes(c.cls.split(" ")[0])) || null; }};
}
const el = (tag, cls, text) => { const n = mk(); n.cls = cls || ""; n.textContent = text || ""; n.tag = tag; return n; };
const box = mk();
const $ = () => box;
const bindAgentMenu = () => {}, post = async () => ({status: 200, j: {}}), toast = () => {};
window = {};
let ideaEditing = null, ideaShowDropped = false, ideasShown = null;
%s
%s
const idea = (issue, text) => ({status: "open", ts: "t", text, detail: "", key: text, moved_to: "", issue});
const small = (i) => box.querySelector(".ideas-list").children[i].children.find((c) => c.tag === "small");
const links = (i) => small(i).children.filter((c) => c.tag === "a");
const warns = () => box.children.flatMap((c) => c.children || []).filter((c) => c.cls === "ideas-gitlab-warn");
(async () => {
%s
})().catch((e) => { console.log("ERR", e.stack); process.exit(2); });
""" % (grab(html, r"^async function pollJSON\(path\) \{.*?^\}\n", "pollJSON"),
       grab(html, r"^async function pollIdeas\(\) \{.*?^\}\n", "pollIdeas"), scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def check(self, scenario):
        r = self.run_page(scenario)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_link_only_on_ideas_with_an_issue(self):
        # mutation: always render the link -> the issue:null row has one
        self.check("""
PAYLOAD = {ideas: [idea(null, "none"), idea(12, "has")], open: 2, gitlab: {repo: "g/r", url: "https://gitlab.com/g/r", ok: true, error: ""}};
await pollIdeas();   // rows are newest first: "has" then "none"
const a = links(0);
if (a.length !== 1) { console.log("expected one link", a.length); process.exit(1); }
if (a[0].textContent !== "GitLab #12" || a[0].href !== "https://gitlab.com/g/r/-/issues/12" || a[0].target !== "_blank" || a[0].rel !== "noopener") {
  console.log("bad link", a[0].textContent, a[0].href, a[0].target, a[0].rel); process.exit(1);
}
if (links(1).length !== 0) { console.log("link on an idea without an issue"); process.exit(1); }
""")

    def test_warning_appears_then_clears(self):
        # mutation: never remove the warning -> the second poll still shows it
        self.check("""
const gl = (ok, error) => ({repo: "g/r", url: "https://gitlab.com/g/r", ok, error});
PAYLOAD = {ideas: [idea(1, "x")], open: 1, gitlab: gl(false, "HTTP 500: boom <b>x</b>")};
await pollIdeas();
let w = warns();
if (w.length !== 1 || w[0].textContent !== "GitLab sync: HTTP 500: boom <b>x</b>") { console.log("warn", w.length, w[0] && w[0].textContent); process.exit(1); }
await pollIdeas();
if (warns().length !== 1) { console.log("warning duplicated"); process.exit(1); }
PAYLOAD = {ideas: [idea(1, "x")], open: 1, gitlab: gl(true, "")};
await pollIdeas();
if (warns().length !== 0) { console.log("warning not cleared"); process.exit(1); }
""")

    def test_unmapped_project_looks_as_before(self):
        self.check("""
PAYLOAD = {ideas: [idea(null, "x")], open: 1, gitlab: null};
await pollIdeas();
if (warns().length !== 0 || links(0).length !== 0) process.exit(1);
// an old server without the key behaves the same
PAYLOAD = {ideas: [idea(null, "y")], open: 1};
await pollIdeas();
if (warns().length !== 0 || links(0).length !== 0) process.exit(1);
""")

    def test_glab_text_never_goes_through_innerhtml(self):
        html = (BOARD / "index.html").read_text()
        fn = grab(html, r"^async function pollIdeas\(\) \{.*?^\}\n", "pollIdeas")
        self.assertNotIn("innerHTML", fn)


if __name__ == "__main__":
    unittest.main()
