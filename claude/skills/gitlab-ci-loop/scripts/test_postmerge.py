"""Offline tests for post-merge diagnosis, cross-pipeline following, incident tracking and MR targets."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("agent_ci", os.path.join(HERE, "agent-ci.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

CFG = {"integration_branch": "dev3", "branch_prefix": "agent/", "max_ci_rounds": 5,
       "protected_branches": ["main", "staging", "dev3"], "mr_targets": ["staging"],
       "postmerge": {"ref": "staging", "max_rounds": 2}}


class SignatureTests(unittest.TestCase):
    def test_same_failure_same_signature_across_ids_and_timestamps(self):
        a = ["$ python run.py", "2026-10-09 22:36:59,285 ERROR Failed: Unsupported platform '$TRANSFORM_PLATFORMS'",
             "ERROR: Job failed: exit code 1"]
        b = ["$ python run.py", "2026-10-10 01:02:03,999 ERROR Failed: Unsupported platform '$TRANSFORM_PLATFORMS'",
             "ERROR: Job failed: exit code 1"]
        self.assertEqual(agent.error_signature("deploy-x", a), agent.error_signature("deploy-x", b))
        self.assertIn("Unsupported platform", agent.error_signature("deploy-x", a))
        self.assertNotIn("Job failed", agent.error_signature("deploy-x", a))

    def test_dispatch_hash_and_pipeline_ids_are_normalized(self):
        s1 = agent.error_signature("dispatch-76dee6a433e9-45",
                                   ["[release][ERROR] GitLab fanout pipeline 2932302332 finished with status failed."])
        s2 = agent.error_signature("dispatch-22760fcd6b8e-43",
                                   ["[release][ERROR] GitLab fanout pipeline 2932243673 finished with status failed."])
        self.assertEqual(s1, s2)

    def test_names_with_digits_are_not_normalized(self):
        sig = agent.error_signature("t", ["ERROR implemented platforms are ga4, pinterest, tiktok; exit 12"])
        self.assertIn("ga4", sig)
        self.assertIn("exit N", sig)

    def test_hint_uses_root_error_not_earlier_terraform_warnings(self):
        lines = ["$ terraform output -raw vm_name", "│ Warning: No outputs found", "│ The state file either has no outputs",
                 "$ . ci/scripts/deploy-dags.sh equifax",
                 "2026-10-09 22:36:59,285 ERROR Failed: Unsupported platform '$TRANSFORM_PLATFORMS'; implemented ga4",
                 "ERROR: Job failed: exit code 1"]
        self.assertEqual("unexpanded", agent.failure_hint(lines))
        self.assertEqual("infra", agent.failure_hint(["$ gcloud x", "ERROR: (gcloud) PERMISSION_DENIED on iam.serviceAccounts"]))
        self.assertIsNone(agent.failure_hint(["│ Warning: No outputs found", "ERROR boom"]))

    def test_different_errors_differ(self):
        self.assertNotEqual(agent.error_signature("j", ["ERROR boom a"]), agent.error_signature("j", ["ERROR kaboom b"]))


class FollowTests(unittest.TestCase):
    def run_print(self, referenced_status="failed"):
        jobs = {1: [{"status": "failed", "stage": "stage-cohort", "name": "dispatch-76dee6a433e9-45",
                     "id": 10, "web_url": "u1"}],
                2: [{"status": "failed", "stage": "deploy", "name": "transform-equifax", "id": 20, "web_url": "u2"}]}
        logs = {10: "$ python dispatch.py\n[release][ERROR] GitLab fanout pipeline 2932302332 finished with status failed.\n",
                20: "$ python t.py\nERROR Failed: Unsupported platform 'x'\n"}

        def fake_jobs(pid, project=":id"):
            return jobs[{100: 1, 2932302332: 2}[pid]]

        def fake_api(endpoint, method="GET", raw=False, fields=None):
            if "/trace" in endpoint:
                return logs[int(endpoint.split("/jobs/")[1].split("/")[0])]
            if endpoint.endswith("/bridges?per_page=100"):
                return []
            raise AssertionError(endpoint)

        records = []
        with patch.object(agent, "jobs_of", side_effect=fake_jobs), \
                patch.object(agent, "api", side_effect=fake_api), \
                patch.object(agent, "api_optional", return_value={"status": referenced_status}) as opt:
            n = agent.print_failures(100, ":id", 20, records=records)
        return n, records, opt

    def test_follows_pipeline_id_found_in_log_and_marks_wrapper(self):
        n, records, opt = self.run_print()
        self.assertEqual(2, n)
        opt.assert_called_once_with("projects/:id/pipelines/2932302332")
        wrapper = next(r for r in records if r["job"].startswith("dispatch"))
        root = next(r for r in records if r["job"] == "transform-equifax")
        self.assertTrue(wrapper["wrapper"])
        self.assertFalse(root["wrapper"])

    def test_does_not_follow_non_failed_referenced_pipeline(self):
        n, records, _ = self.run_print(referenced_status="success")
        self.assertEqual(1, n)
        self.assertFalse(records[0]["wrapper"])


class PostmergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inc = os.path.join(self.tmp, "incidents.json")
        self.patches = [patch.object(agent, "incidents_path", return_value=self.inc),
                        patch.object(agent, "ensure_auth"),
                        patch.object(agent, "jobs_of", return_value=[]),
                        patch.object(agent, "api_optional", return_value=[]),
                        patch.object(agent.time, "sleep")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.calls = []

    def args(self, **kw):
        base = dict(ref=None, pipeline=555, mr=None, note=None, timeout=5, interval=0, tail=5)
        base.update(kw)
        return Namespace(**base)

    def fake_api(self, status="failed", ref="staging"):
        def _api(endpoint, method="GET", raw=False, fields=None):
            self.calls.append((method, endpoint))
            if endpoint == "projects/:id/pipelines/555":
                return {"id": 555, "ref": ref, "sha": "a" * 40, "status": status, "web_url": "u"}
            raise AssertionError(endpoint)
        return _api

    def fake_print(self, sig="deploy-x :: ERROR boom", hint=None):
        def _print(pid, project, tail, depth=0, seen=None, records=None):
            records.append({"pipeline": pid, "job": "deploy-x", "stage": "deploy", "url": "u",
                            "wrapper": False, "signature": sig, "hint": hint})
            return 1
        return _print

    def test_green_clears_incidents_and_returns_0(self):
        agent.save_incidents({"old": {"count": 1, "pipelines": [1], "attempts": []}})
        with patch.object(agent, "api", side_effect=self.fake_api("success")):
            self.assertEqual(0, agent.cmd_postmerge(CFG, self.args()))
        self.assertEqual({}, agent.load_incidents())

    def test_red_counts_distinct_pipelines_and_stops_at_limit(self):
        with patch.object(agent, "api", side_effect=self.fake_api()), \
                patch.object(agent, "print_failures", side_effect=self.fake_print()):
            self.assertEqual(1, agent.cmd_postmerge(CFG, self.args()))
            self.assertEqual(1, agent.cmd_postmerge(CFG, self.args()))  # same pipeline: no double count
            self.assertEqual(1, agent.load_incidents()["deploy-x :: ERROR boom"]["count"])
        def other(endpoint, method="GET", raw=False, fields=None):
            return {"id": 556, "ref": "staging", "sha": "b" * 40, "status": "failed", "web_url": "u"}
        with patch.object(agent, "api", side_effect=other), \
                patch.object(agent, "print_failures", side_effect=self.fake_print()):
            self.assertEqual(5, agent.cmd_postmerge(CFG, self.args(pipeline=556)))

    def test_is_read_only(self):
        with patch.object(agent, "api", side_effect=self.fake_api()), \
                patch.object(agent, "print_failures", side_effect=self.fake_print()):
            agent.cmd_postmerge(CFG, self.args())
        self.assertTrue(self.calls)
        self.assertTrue(all(m == "GET" for m, _ in self.calls))

    def test_refuses_pipeline_on_other_ref(self):
        with patch.object(agent, "api", side_effect=self.fake_api(ref="agent/foo")):
            with self.assertRaises(SystemExit):
                agent.cmd_postmerge(CFG, self.args())

    def test_mr_uses_its_target_branch_not_postmerge_ref(self):
        def _api(endpoint, method="GET", raw=False, fields=None):
            self.calls.append((method, endpoint))
            if endpoint == "projects/:id/merge_requests/291":
                return {"iid": 291, "state": "merged", "target_branch": "main", "merge_commit_sha": "c" * 40}
            if endpoint.startswith("projects/:id/pipelines?sha="):
                self.assertIn("ref=main", endpoint)
                return [{"id": 777}]
            if endpoint == "projects/:id/pipelines/777":
                return {"id": 777, "ref": "main", "sha": "c" * 40, "status": "success", "web_url": "u"}
            raise AssertionError(endpoint)
        with patch.object(agent, "api", side_effect=_api):
            self.assertEqual(0, agent.cmd_postmerge(CFG, self.args(pipeline=None, mr=291)))

    def test_explicit_ref_wins_over_mr_target(self):
        def _api(endpoint, method="GET", raw=False, fields=None):
            if endpoint == "projects/:id/merge_requests/291":
                return {"iid": 291, "state": "merged", "target_branch": "main", "merge_commit_sha": "c" * 40}
            if endpoint.startswith("projects/:id/pipelines?sha="):
                self.assertIn("ref=staging", endpoint)
                return [{"id": 555}]
            if endpoint == "projects/:id/pipelines/555":
                return {"id": 555, "ref": "staging", "sha": "a" * 40, "status": "success", "web_url": "u"}
            raise AssertionError(endpoint)
        with patch.object(agent, "api", side_effect=_api):
            self.assertEqual(0, agent.cmd_postmerge(CFG, self.args(pipeline=None, mr=291, ref="staging")))

    def test_note_requires_unique_incident(self):
        agent.save_incidents({"a :: x": {"count": 1, "pipelines": [1], "attempts": []},
                              "a :: y": {"count": 1, "pipelines": [2], "attempts": []}})
        with self.assertRaises(SystemExit):
            agent.add_attempt("a ::", "ambiguous")
        agent.add_attempt("a :: x", "changed var passing")
        self.assertEqual("changed var passing", agent.load_incidents()["a :: x"]["attempts"][0]["note"])


class TargetTests(unittest.TestCase):
    def test_default_target_is_integration(self):
        with patch.object(agent, "target_path", return_value="/nonexistent/x"):
            self.assertEqual("dev3", agent.target_for(CFG, "agent/foo"))

    def test_recorded_target_must_be_allowed(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("staging")
        with patch.object(agent, "target_path", return_value=fh.name):
            self.assertEqual("staging", agent.target_for(CFG, "agent/foo"))
            self.assertEqual("dev3", agent.target_for({**CFG, "mr_targets": []}, "agent/foo"))

    def test_recorded_target_survives_a_base_config_without_mr_targets(self):
        # A branch cut from staging carries staging's .agent-ci.yml, which may predate mr_targets.
        old_cfg = {k: v for k, v in CFG.items() if k != "mr_targets"}
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("staging")
        with patch.object(agent, "target_path", return_value=fh.name):
            self.assertEqual("staging", agent.target_for(old_cfg, "agent/foo"))
            self.assertEqual("dev3", agent.target_for({**old_cfg, "protected_branches": ["main"]}, "agent/foo"))

    def test_start_rejects_unlisted_base(self):
        with patch.object(agent, "sh") as sh:
            with self.assertRaises(SystemExit):
                agent.cmd_start(CFG, Namespace(topic="x", base="main"))
        sh.assert_not_called()

    def test_start_allows_listed_base(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(agent, "target_path", return_value=os.path.join(d, "t", "agent__x")), \
                patch.object(agent, "base_ref", return_value="origin/staging"), \
                patch.object(agent, "sh") as sh:
            self.assertEqual(0, agent.cmd_start(CFG, Namespace(topic="x", base="staging")))
            self.assertEqual("staging", open(os.path.join(d, "t", "agent__x")).read())
        self.assertEqual(("git", "switch", "-c", "agent/x", "origin/staging"), sh.call_args.args)


class LintTests(unittest.TestCase):
    def _run(self, outputs):
        results = iter(outputs)
        def fake_run(cmd, **kw):
            rc, out = next(results)
            return Namespace(returncode=rc, stdout=out, stderr="")
        with tempfile.TemporaryDirectory() as d:
            for name in ("a/.gitlab-ci-x.yml", ".gitlab-ci.yml"):
                os.makedirs(os.path.join(d, os.path.dirname(name)), exist_ok=True)
                open(os.path.join(d, name), "w").close()
            cwd = os.getcwd(); os.chdir(d)
            try:
                with patch.object(agent, "sh", return_value="a/.gitlab-ci-x.yml\n.gitlab-ci.yml\nREADME.md"), \
                        patch.object(agent, "base_ref", return_value="origin/staging"), \
                        patch.object(agent, "target_for", return_value="staging"), \
                        patch.object(agent, "glab_bin", return_value="glab"), \
                        patch.object(agent.subprocess, "run", side_effect=fake_run) as run:
                    agent.lint_ci_if_changed(CFG)
                    return [c.args[0] for c in run.call_args_list]
            finally:
                os.chdir(cwd)

    def test_lints_each_changed_file_and_tolerates_unresolvable_local_includes(self):
        calls = self._run([(0, "valid"),
                           (1, ".gitlab-ci.yml is invalid.\n1 Local file `ci/new.yml` does not exist!")])
        self.assertEqual([["glab", "ci", "lint", "a/.gitlab-ci-x.yml"], ["glab", "ci", "lint", ".gitlab-ci.yml"]], calls)

    def test_fragment_without_root_stages_is_a_warning(self):
        self._run([(1, "x is invalid.\n1 enforce job: chosen stage branch-policy does not exist; available stages are .pre"),
                   (0, "valid")])

    def test_real_lint_errors_still_fail(self):
        with self.assertRaises(SystemExit):
            self._run([(1, "x is invalid.\n1 jobs:foo config contains unknown keys: bar")])


class SettleTests(unittest.TestCase):
    def test_failed_merge_request_pipeline_beats_green_push_pipeline(self):
        push = {"id": 1, "status": "success", "source": "push", "web_url": "u1"}
        mr = {"id": 2, "status": "failed", "source": "merge_request_event", "web_url": "u2"}
        def fake_api(endpoint):
            return [mr, push] if "pipelines?sha=" in endpoint else mr
        with patch.object(agent, "api", side_effect=fake_api):
            self.assertEqual(2, agent.settle_commit_pipelines("abc", push, 1e18, 0)["id"])

    def test_all_green_keeps_the_watched_pipeline(self):
        push = {"id": 1, "status": "success", "web_url": "u1"}
        with patch.object(agent, "api", return_value=[{"id": 2, "status": "success"}, push]):
            self.assertIs(push, agent.settle_commit_pipelines("abc", push, 1e18, 0))


class TitleTests(unittest.TestCase):
    def test_format_both_ways_and_leaves_free_text(self):
        self.assertEqual("[fix(release)]: route x", agent.format_mr_title("fix(release): route x", "bracketed"))
        self.assertEqual("[fix(release)]: route x", agent.format_mr_title("[fix(release)]: route x", "bracketed"))
        self.assertEqual("fix(release): route x", agent.format_mr_title("[fix(release)]: route x", "plain"))
        self.assertEqual("[feat!]: drop y", agent.format_mr_title("feat!: drop y", "bracketed"))
        self.assertEqual("Update docs", agent.format_mr_title("Update docs", "bracketed"))

    def test_auto_follows_recent_merged_titles_into_the_target(self):
        merged = [{"title": "[fix(release)]: a"}, {"title": "[hotfix]: b"}, {"title": "fix(airflow): c"}]
        with patch.object(agent, "api_optional", return_value=merged) as api:
            self.assertEqual("bracketed", agent.mr_title_style(CFG, "staging"))
        self.assertIn("target_branch=staging", api.call_args.args[0])
        with patch.object(agent, "api_optional", return_value=[{"title": "fix: a"}, {"title": "[fix]: b"}]):
            self.assertEqual("plain", agent.mr_title_style(CFG, "dev3"))
        with patch.object(agent, "api_optional", return_value=None):
            self.assertEqual("plain", agent.mr_title_style(CFG, "dev3"))

    def test_explicit_style_skips_the_api(self):
        with patch.object(agent, "api_optional") as api:
            self.assertEqual("bracketed", agent.mr_title_style({**CFG, "mr_title_style": "bracketed"}, "staging"))
        api.assert_not_called()


class ResolveTests(unittest.TestCase):
    def test_mr_resolves_to_the_push_pipeline_not_dispatch_api_pipelines(self):
        def fake_api(endpoint, *a, **k):
            if endpoint.endswith("merge_requests/147"):
                return {"state": "merged", "merge_commit_sha": "7c5e"}
            self.assertIn("source=push", endpoint)
            return [{"id": 2939979683}]
        with patch.object(agent, "api", side_effect=fake_api):
            self.assertEqual(2939979683, agent.resolve_postmerge_pipeline(
                Namespace(pipeline=None, mr=147), "staging"))


class MrCreateTests(unittest.TestCase):
    def _create(self, cfg):
        posted = {}
        def fake_api(endpoint, method="GET", raw=False, fields=None):
            if method == "POST":
                posted.update(fields)
                return {"iid": 9, "web_url": "u"}
            raise AssertionError(endpoint)
        with patch.object(agent, "find_mr", return_value=None), \
                patch.object(agent, "target_for", return_value="staging"), \
                patch.object(agent, "base_ref", return_value="origin/staging"), \
                patch.object(agent, "sh", return_value="fix(airflow): deploy DAGs"), \
                patch.object(agent, "mr_title_style", return_value="bracketed"), \
                patch.object(agent, "api", side_effect=fake_api):
            agent.ensure_mr(cfg, "agent/x")
        return posted

    def test_mrs_open_ready_for_review_by_default(self):
        posted = self._create(CFG)
        self.assertEqual("[fix(airflow)]: deploy DAGs", posted["title"])
        self.assertEqual("staging", posted["target_branch"])

    def test_subjects_follow_first_parent_only(self):
        with patch.object(agent, "find_mr", return_value=None), \
                patch.object(agent, "target_for", return_value="dev3"), \
                patch.object(agent, "base_ref", return_value="origin/dev3"), \
                patch.object(agent, "sh", return_value="merge: sync") as sh, \
                patch.object(agent, "mr_title_style", return_value="plain"), \
                patch.object(agent, "api", return_value={"iid": 1, "web_url": "u"}):
            agent.ensure_mr(CFG, "agent/sync")
        self.assertIn("--first-parent", sh.call_args.args)

    def test_mr_draft_opt_in(self):
        self.assertEqual("Draft: [fix(airflow)]: deploy DAGs", self._create({**CFG, "mr_draft": True})["title"])


class FollowTests(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(agent, "ensure_auth"), patch.object(agent.time, "sleep")):
            p.start(); self.addCleanup(p.stop)

    def follow_args(self, **kw):
        base = dict(mr=148, merge_timeout=10_000, merge_interval=0, timeout=5, interval=0, tail=5)
        base.update(kw)
        return Namespace(**base)

    def test_waits_for_merge_then_diagnoses_the_target_pipeline(self):
        states = iter(["opened", "opened", "merged"])
        def fake_api(endpoint, *a, **k):
            if endpoint.endswith("merge_requests/148"):
                return {"iid": 148, "state": next(states), "target_branch": "staging", "merge_commit_sha": "7c5e"}
            self.assertIn("sha=7c5e&ref=staging&source=push", endpoint)
            return [{"id": 777}]
        with patch.object(agent, "api", side_effect=fake_api), \
                patch.object(agent, "cmd_postmerge", return_value=1) as pm:
            self.assertEqual(1, agent.cmd_follow(CFG, self.follow_args()))
        self.assertEqual(("staging", 777), (pm.call_args.args[1].ref, pm.call_args.args[1].pipeline))

    def test_closed_mr_stops_without_diagnosing(self):
        with patch.object(agent, "api", return_value={"iid": 148, "state": "closed"}), \
                patch.object(agent, "cmd_postmerge") as pm:
            self.assertEqual(3, agent.cmd_follow(CFG, self.follow_args()))
        pm.assert_not_called()

    def test_unmerged_mr_times_out(self):
        with patch.object(agent, "api", return_value={"iid": 148, "state": "opened"}), \
                patch.object(agent.time, "time", side_effect=[0, 0, 20_000]):
            self.assertEqual(4, agent.cmd_follow(CFG, self.follow_args()))

    def test_follow_is_read_only(self):
        methods = []
        def fake_api(endpoint, method="GET", *a, **k):
            methods.append(method)
            if endpoint.endswith("merge_requests/148"):
                return {"iid": 148, "state": "merged", "target_branch": "dev3", "sha": "ab"}
            return [{"id": 1}]
        with patch.object(agent, "api", side_effect=fake_api), patch.object(agent, "cmd_postmerge", return_value=0):
            agent.cmd_follow(CFG, self.follow_args())
        self.assertEqual({"GET"}, set(methods))


class FinishSquashTests(unittest.TestCase):
    def _finish(self, merges: str, no_squash=False):
        git_calls = []
        def fake_sh(*cmd, **kw):
            git_calls.append(cmd)
            if cmd[:2] == ("git", "merge-base"):
                return "mb"
            if cmd[:3] == ("git", "rev-list", "--merges"):
                return merges
            if cmd[:2] == ("git", "rev-list"):
                return "c3\nc2\nc1"
            return ""
        with patch.object(agent, "guard_branch", return_value="agent/sync"), \
                patch.object(agent, "ensure_auth"), patch.object(agent, "ensure_clean"), \
                patch.object(agent, "pipeline_for", return_value={"status": "success"}), \
                patch.object(agent, "head_sha", return_value="c3"), \
                patch.object(agent, "base_ref", return_value="origin/dev3"), \
                patch.object(agent, "target_for", return_value="dev3"), \
                patch.object(agent, "sh", side_effect=fake_sh), \
                patch.object(agent, "git_net", side_effect=lambda *a: ["git", *a]), \
                patch.object(agent, "ensure_mr", return_value={"iid": 1, "web_url": "u"}), \
                patch.object(agent, "mr_title_style", return_value="bracketed"), \
                patch.object(agent, "api"), patch.object(agent, "bump_rounds"):
            agent.cmd_finish(CFG, Namespace(message="merge: sync staging into dev3", force=False,
                                            no_follow=True, no_squash=no_squash))
        return git_calls

    def test_branch_with_a_merge_commit_is_not_squashed(self):
        calls = self._finish(merges="c2")
        self.assertNotIn(("git", "reset", "--soft", "mb"), calls)
        self.assertFalse(any("--force-with-lease" in c for c in calls))

    def test_no_squash_flag_keeps_commits(self):
        self.assertNotIn(("git", "reset", "--soft", "mb"), self._finish(merges="", no_squash=True))

    def test_linear_branch_is_still_squashed(self):
        self.assertIn(("git", "reset", "--soft", "mb"), self._finish(merges=""))


class AlreadyMergedTests(unittest.TestCase):
    def test_finish_after_the_user_merged_goes_straight_to_follow(self):
        def fake_api(endpoint, *a, **k):
            if "state=opened" in endpoint:
                return []
            self.assertIn("state=merged&source_branch=agent%2Fsync", endpoint)
            return [{"iid": 150, "sha": "old", "target_branch": "dev3"},
                    {"iid": 153, "sha": "head", "target_branch": "dev3"}]
        with patch.object(agent, "guard_branch", return_value="agent/sync"), \
                patch.object(agent, "ensure_auth"), \
                patch.object(agent, "head_sha", return_value="head"), \
                patch.object(agent, "api", side_effect=fake_api), \
                patch.object(agent, "sh") as sh, \
                patch.object(agent, "cmd_follow", return_value=0) as follow:
            self.assertEqual(0, agent.cmd_finish(CFG, Namespace(message="m", force=False, no_follow=False,
                                                                no_squash=False, merge_timeout=1, merge_interval=0)))
        self.assertEqual(153, follow.call_args.args[1].mr)
        sh.assert_not_called()

    def test_reused_branch_name_with_new_commits_is_not_treated_as_merged(self):
        def fake_api(endpoint, *a, **k):
            return [] if "state=opened" in endpoint else [{"iid": 150, "sha": "old", "target_branch": "dev3"}]
        with patch.object(agent, "api", side_effect=fake_api), patch.object(agent, "head_sha", return_value="new"):
            self.assertIsNone(agent.merged_mr_for_head("agent/sync"))


class TreeTests(unittest.TestCase):
    """Live tree: bridge children plus API pipelines matched to dispatch-<plan hash>-<target id> jobs."""

    def test_renders_bridges_and_dispatch_created_pipelines(self):
        root = {"id": 1, "status": "running", "ref": "staging", "created_at": "2026-10-12T19:50:00Z"}
        jobs = {1: [{"name": "build", "status": "success"}],
                10: [{"name": "dispatch-45ef60f72d0c-48", "status": "running"},
                     {"name": "dispatch-06c466cc0d0a-47", "status": "running"}],
                20: [{"name": "generate", "status": "success"}], 21: [], 30: []}
        def fake_optional(endpoint):
            if endpoint.startswith("projects/:id/pipelines?"):
                self.assertIn("source=api", endpoint)
                return [{"id": 20, "status": "running"}, {"id": 30, "status": "success"}, {"id": 99, "status": "failed"}]
            if endpoint.endswith("/variables"):
                pid = int(endpoint.split("/")[-2])
                return {20: [{"key": "RELEASE_PLAN_ID", "value": "release-fe7b-45ef60f72d0c"},
                             {"key": "RELEASE_TARGET_ID", "value": "48"}],
                        30: [{"key": "RELEASE_PLAN_ID", "value": "release-fe7b-06c466cc0d0a"},
                             {"key": "RELEASE_TARGET_ID", "value": "47"}],
                        99: []}[pid]
            pid = int(endpoint.split("/")[-2])
            return {1: [{"name": "run-stage-cohort", "downstream_pipeline": {"id": 10, "status": "running"}}],
                    20: [{"name": "trigger:child", "downstream_pipeline": {"id": 21, "status": "running"}}]
                    }.get(pid, [])
        cache: dict = {}
        with patch.object(agent, "api_optional", side_effect=fake_optional), \
                patch.object(agent, "jobs_of", side_effect=lambda pid, project=":id": jobs[pid]):
            text = agent.PipelineTree(root, cache).render()
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("pipeline 1 ▶ running"))
        self.assertTrue(lines[1].startswith("   run-stage-cohort → 10 ▶"))
        self.assertTrue(lines[2].startswith("      dispatch-45ef60f72d0c-48 → 20 ▶"))
        self.assertTrue(lines[3].startswith("         trigger:child → 21 ▶"))
        self.assertTrue(lines[4].startswith("      dispatch-06c466cc0d0a-47 → 30 ✓"))
        self.assertNotIn(" 99 ", text)
        self.assertEqual({20, 30, 99}, set(cache))   # variables are cached across polls

    def test_prints_only_on_change(self):
        tree = Namespace(render=lambda: "pipeline 1 ▶ running")
        with patch.object(agent, "say"), patch("builtins.print") as pr:
            last = agent.print_tree_if_changed(tree, "")
            agent.print_tree_if_changed(tree, last)
        self.assertEqual(1, pr.call_count)


if __name__ == "__main__":
    unittest.main()
