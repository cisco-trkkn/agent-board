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
    def run_page(self, scenario, extra=()):
        html = (BOARD / "index.html").read_text()
        fns = "\n".join(grab(html, rf"^function {n}\([^)]*\) \{{[^\n]*\}}\n|^function {n}\([^)]*\) \{{\n.*?^\}}\n", n)
                        for n in ("homeView", "hashProject", "notifyNew", "unreadEvents", "renderBadge", "fmtAge", "ovName", "ovGroup", "ovSorted", "ovStatus", "ovRun", "ovPlanText", "ovMoreTasks"))
        for pat, what in extra:
            fns += "\n" + grab(html, pat, what)
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
const P = (name, o = {}) => Object.assign({project: name, needs_you: [], lead: {status: "ready", last_active: 0, idle_s: 30},
  plan: {name: null, done: 0, total: 0, active: false, in_progress: []}, last_run: null, spend_today: null, alerts: []}, o);
const ev = (id, ts) => ({id, ts, title: "T" + id, text: "x" + id});
const fail = (m) => { console.log("FAIL", m); process.exit(1); };
%s
""" % (fns, scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def check(self, scenario, extra=()):
        r = self.run_page(scenario, extra)
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

    def test_rows_order_needs_you_then_working_then_rest(self):
        # mutation: sort by name, or drop the group key -> rows jump or the needs-you row sinks
        self.check("""
const ps = [P("idle-old", {lead: {status: "ready", last_active: 10, idle_s: 500}}),
  P("work", {lead: {status: "working", last_active: 50, idle_s: null}}),
  P("idle-new", {lead: {status: "ready", last_active: 90, idle_s: 20}}),
  P("needs", {needs_you: [{window: "shell"}], lead: {status: "ready", last_active: 1, idle_s: 9}}),
  P("nolead", {lead: {status: "missing", last_active: null, idle_s: null}})];
const names = ovSorted(ps).map((p) => p.project).join(",");
if (names !== "needs,work,idle-new,idle-old,nolead") fail(names);
""")

    def test_rows_within_a_group_sort_by_project_name_not_activity(self):
        # mutation: sort by last_active inside a group -> rows swap places between polls
        self.check("""
const mkr = (n, t) => P(n, {lead: {status: "ready", last_active: t, idle_s: 5}});
const a = ovSorted([mkr("b", 1), mkr("a", 99), mkr("c", 50)]).map((p) => p.project).join(",");
const b = ovSorted([mkr("b", 77), mkr("a", 3), mkr("c", 8)]).map((p) => p.project).join(",");
if (a !== "a,b,c" || b !== "a,b,c") fail(a + " | " + b);
""")

    def test_status_labels_and_marks_differ_by_shape(self):
        self.check("""
const s = (o) => ovStatus(P("x", o));
if (s({needs_you: [{window: "w"}]}).label !== "Needs you") fail("needs");
if (s({lead: {status: "working", idle_s: null}}).label !== "Working") fail("working");
if (s({lead: {status: "ready", idle_s: 420}}).label !== "Idle 7m") fail("idle " + s({lead: {status: "ready", idle_s: 420}}).label);
if (s({lead: {status: "ready", idle_s: 30}}).label !== "Idle") fail("idle<1m");
if (s({lead: {status: "missing", idle_s: null}}).label !== "No lead") fail("nolead");
const marks = [s({needs_you: [{window: "w"}]}), s({lead: {status: "working"}}), s({}), s({lead: {status: "missing"}})].map((x) => x.mark);
if (new Set(marks).size !== 4) fail("marks share a shape: " + marks);
""")

    def test_last_run_line_label_result_age(self):
        # mutation: print the raw cmd, or lose the failed flag
        self.check("""
const r = (o) => ovRun(P("x", {last_run: Object.assign({label: "e2e-overseer", cmd: "zsh /very/long/path.zsh > /tmp/x", exit: 0, age_s: 3540, summary: ""}, o)}));
let x = r({}); if (x.text !== "e2e-overseer passed, 59m ago" || x.failed) fail(JSON.stringify(x));
x = r({label: "tests", exit: 2, age_s: 180}); if (x.text !== "tests failed (exit 2), 3m ago" || !x.failed) fail(JSON.stringify(x));
x = r({label: "unittest", exit: 124, age_s: 1980, summary: "timed out after 1800s"}); if (x.text !== "unittest timed out, 33m ago" || !x.failed) fail(JSON.stringify(x));
x = r({exit: null, age_s: 10}); if (x.text !== "e2e-overseer running, 10s" || x.failed) fail(JSON.stringify(x));
if (x.text.includes("/")) fail("path in text");
if (ovRun(P("x")) !== null) fail("no run, no line");
""")

    def test_unnamed_session_gets_a_placeholder(self):
        self.check("""
if (ovName("") !== "(unnamed session)" || ovName("agent-board") !== "agent-board") fail("name");
""")

    def test_inactive_plan_shows_no_plan_text_and_active_shows_progress(self):
        self.check("""
if (ovPlanText(P("x", {plan: {name: "p", done: 7, total: 7, active: false, in_progress: []}})) !== "") fail("finished plan shows text");
if (ovPlanText(P("x")) !== "") fail("no plan shows text");
if (ovPlanText(P("x", {plan: {name: "p", done: 5, total: 7, active: true, in_progress: []}})) !== "5/7") fail("progress");
const t = (n) => ({subject: "T" + n, owner: "o", state: "working"});
const two = ovMoreTasks([t(1), t(2)]); if (two.shown.length !== 2 || two.more !== 0) fail("two");
const four = ovMoreTasks([t(1), t(2), t(3), t(4)]); if (four.shown.length !== 2 || four.more !== 2) fail("four");
""")

    def test_agent_line_window_state_word_duration_and_tool(self):
        # mutation: show the board state ("working") instead of the word -> the first assert fails
        self.check("""
const L = (o) => ovAgentLine(Object.assign({window: "qrev", state: "working", state_s: 720, turn_s: 720, tool: "Bash: zsh tools/tests/run-all.zsh"}, o));
if (L({}) !== "qrev · busy 12m · Bash: zsh tools/tests/run-all.zsh") fail(L({}));
if (L({state: "waiting", state_s: 45, tool: null}) !== "qrev · needs you 45s") fail(L({state: "waiting", state_s: 45, tool: null}));
if (L({state: "ready", state_s: 3700, tool: null}) !== "qrev · idle 1h") fail(L({state: "ready", state_s: 3700, tool: null}));
if (L({state_s: null, tool: null}) !== "qrev · busy") fail("no duration: " + L({state_s: null, tool: null}));
if (L({state_s: null}) !== "qrev · busy · Bash: zsh tools/tests/run-all.zsh") fail("no duration, tool: " + L({state_s: null}));
if (L({state: "idle", state_s: null, tool: null}) !== "qrev · idle") fail("unknown state passes through: " + L({state: "idle", state_s: null, tool: null}));
""", extra=[(r"^function ovAgentLine\([^)]*\) \{\n.*?^\}\n", "ovAgentLine"), (r"^const OV_WORD = [^\n]*\n", "OV_WORD")])

    def test_ovrow_renders_an_agents_entry_per_line_and_none_without_agents(self):
        html = (BOARD / "index.html").read_text()
        row = grab(html, r"^function ovRow\(p\) \{\n.*?^\}\n", "ovRow")
        self.assertIn("ovAgentLine(a)", row)
        self.assertRegex(row, r"for \(const a of p\.agents \|\| \[\]\)")   # a record without agents renders as today
        self.assertIn("ovNeedsText(n)", row)

    def test_needs_you_line_carries_the_reason(self):
        # mutation: drop the reason suffix -> the first assert fails
        self.check("""
if (ovNeedsText({window: "✦ parse", reason: "permission: Bash: rm x"}) !== "✦ parse needs you — permission: Bash: rm x") fail(ovNeedsText({window: "✦ parse", reason: "permission: Bash: rm x"}));
if (ovNeedsText({window: "✦ parse", reason: null}) !== "✦ parse needs you") fail("null reason");
if (ovNeedsText({window: "✦ parse"}) !== "✦ parse needs you") fail("no reason key");
""", extra=[(r"^function ovNeedsText\([^\n]*\n", "ovNeedsText")])

    def test_failing_and_stuck_badges_are_amber(self):
        # mutation: leave them out of alertColor -> red
        self.check("""
for (const k of ["context", "burn", "failing", "stuck"]) if (alertColor(k) !== "amber") fail(k + " " + alertColor(k));
for (const k of ["total", "day_total", "model_mismatch"]) if (alertColor(k) !== "red") fail(k + " " + alertColor(k));
""", extra=[(r"^const alertColor = [^\n]*\n", "alertColor")])

    def test_page_markup_rules(self):
        # truncation, hidden epoch/artifacts, one column when the overseer is off, narrow-screen stack, muted contrast
        html = (BOARD / "index.html").read_text()
        render = grab(html, r"^function renderHome\(\) \{\n.*?^\}\n", "renderHome")
        self.assertNotIn("epoch", render)
        self.assertNotIn("artifacts", render)
        self.assertNotIn("ov-art", html)
        self.assertRegex(html, r"\.ov-sub > \*[^}]*text-overflow: ellipsis")
        self.assertRegex(html, r"\.events li[^}]*text-overflow: ellipsis")
        self.assertRegex(html, r"\.home\.ov-on \.home-grid \{[^}]*40%")
        self.assertRegex(html, r"@media \(max-width: 900px\)[^@]*\.home\.ov-on \.home-grid")
        self.assertIn("(unnamed session)", grab(html, r"^function renderTabs\(\) \{\n.*?^\}\n", "renderTabs") + grab(html, r"^function ovName\([^\n]*\n", "ovName"))

    def test_muted_text_reaches_4_5_to_1_on_the_board_backgrounds(self):
        html = (BOARD / "index.html").read_text()
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
        def ratio(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + .05) / (lb + .05)
        light = grab(html, r":root \{.*?\n\}", "light tokens"); dark = grab(html, r"prefers-color-scheme: dark\) \{.*?\n  \}", "dark tokens")
        for block in (light, dark):
            tok = dict(re.findall(r"--([\w-]+): (#[0-9a-fA-F]{6})", block))
            for bg in ("bg", "panel"):
                self.assertGreaterEqual(ratio(tok["muted"], tok[bg]), 4.5, (block[:30], bg))


if __name__ == "__main__":
    unittest.main()
