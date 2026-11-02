"""The Overseer home's page logic runs under node with stubs: routing helpers, notifyNew (the browser notification) and renderBadge.
Same harness idea as test_ideas_gitlab_ui.py: the page's own functions are cut out of index.html and run."""
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


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's overview functions")
class OverviewHomeUiTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        fns = "\n".join(grab(html, rf"^function {n}\([^)]*\) \{{[^\n]*\}}\n|^function {n}\([^)]*\) \{{\n.*?^\}}\n", n)
                        for n in ("homeView", "hashProject", "notifyNew", "unreadEvents", "renderBadge"))
        js = """
const mk = () => ({textContent: "", dataset: {}});
const nodes = {};
const $ = (s) => nodes[s] || (nodes[s] = mk());
const document = {title: "Agent Board"};
const location = {hash: ""};
const shown = [];
class Notification { constructor(title, o) { shown.push({title, body: o.body, tag: o.tag}); } }
Notification.permission = "granted";
const window = {Notification};
const OV = {data: null, seenTs: 0, notifiedTs: null};
%s
const ev = (id, ts) => ({id, ts, title: "T" + id, text: "x" + id});
const fail = (m) => { console.log("FAIL", m); process.exit(1); };
%s
""" % (fns, scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def check(self, scenario):
        r = self.run_page(scenario)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_home_view_and_hash_project(self):
        self.check("""
location.hash = ""; if (!homeView()) fail("empty hash is the home");
location.hash = "#"; if (!homeView()) fail("a bare # is the home");
location.hash = "#my%20proj"; if (homeView()) fail("#proj is a project page");
if (hashProject() !== "my proj") fail("hashProject decodes: " + hashProject());
location.hash = "#%E0%A4%A"; if (hashProject() !== "") fail("a bad escape gives an empty project");
""")

    def test_first_notify_call_seeds_without_a_notification(self):
        # mutation: notify on the first call -> history raises banners when the page opens
        self.check("""
notifyNew([ev(1, 100), ev(2, 200)]);
if (shown.length) fail("first call raised " + shown.length);
if (OV.notifiedTs !== 200) fail("seed " + OV.notifiedTs);
notifyNew([ev(1, 100), ev(2, 200)]);
if (shown.length) fail("same events raised a banner");
""")

    def test_newer_event_raises_one_notification(self):
        # mutation: compare with >= or skip the ts check -> old events repeat
        self.check("""
notifyNew([ev(1, 100)]);
notifyNew([ev(1, 100), ev(2, 200)]);
if (shown.length !== 1 || shown[0].title !== "T2" || shown[0].body !== "x2") fail(JSON.stringify(shown));
notifyNew([ev(1, 100), ev(2, 200)]);
if (shown.length !== 1) fail("repeat banner " + shown.length);
""")

    def test_no_notification_without_granted_permission(self):
        self.check("""
Notification.permission = "default";
notifyNew([ev(1, 100)]);
notifyNew([ev(1, 100), ev(2, 200)]);
if (shown.length) fail("banner without permission");
if (OV.notifiedTs !== 200) fail("still advances: " + OV.notifiedTs);
""")

    def test_badge_counts_unread_and_sets_the_title(self):
        self.check("""
OV.seenTs = 100; OV.data = {events: [ev(1, 100), ev(2, 200), ev(3, 300)]};
renderBadge();
if (document.title !== "(2) Agent Board") fail(document.title);
if ($("#ov-unread").textContent !== "2") fail($("#ov-unread").textContent);
OV.seenTs = 300; renderBadge();
if (document.title !== "Agent Board" || $("#ov-unread").textContent !== "") fail("not cleared: " + document.title);
""")


if __name__ == "__main__":
    unittest.main()
