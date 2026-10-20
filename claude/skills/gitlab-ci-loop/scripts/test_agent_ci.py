"""Offline tests for the guarded stage-0 API request and exact-pipeline watcher."""
import importlib.util
import os
import sys
import unittest
from argparse import Namespace
from unittest.mock import patch

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("agent_ci", os.path.join(HERE, "agent-ci.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

CFG = {"stage0_plan": {"project_path": "group/project", "ref": "main"},
       "branch_prefix": "agent/", "max_ci_rounds": 5}
SHA = "f" * 40


def responses(endpoint, method="GET", **kwargs):
    if endpoint == "projects/:id":
        return {"id": 42, "path_with_namespace": "group/project"}
    if endpoint == "projects/:id/repository/branches/main":
        return {"protected": True, "commit": {"id": SHA}}
    if endpoint == "projects/:id/pipeline" and method == "POST":
        data = kwargs["fields"]
        assert data == {"ref": "main", "variables": [
            {"key": k, "value": v} for k, v in agent.STAGE0_VARIABLES.items()
        ]}
        return {"id": 123, "ref": "main", "sha": SHA, "source": "api", "web_url": "https://example/pipeline/123"}
    if endpoint == "projects/:id/pipelines/123":
        return {"id": 123, "ref": "main", "source": "api", "sha": SHA,
                "status": "success", "web_url": "https://example/pipeline/123"}
    if endpoint == "projects/:id/pipelines/123/variables":
        return [{"key": k, "value": v} for k, v in agent.STAGE0_VARIABLES.items()]
    raise AssertionError((endpoint, method))


class Stage0Tests(unittest.TestCase):
    @patch.object(agent, "glab_bin", return_value="glab")
    @patch.object(agent.subprocess, "run")
    def test_api_uses_json_field_for_variables(self, run, _bin):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"id": 1}'
        agent.api("projects/:id/pipeline", "POST", fields={
            "ref": "main",
            "variables": [{"key": "APPLY_MODE", "value": "plan"}],
        })
        cmd = run.call_args.args[0]
        self.assertIn("-F", cmd)
        self.assertIn('variables=[{"key": "APPLY_MODE", "value": "plan"}]', cmd)
        self.assertNotIn("variables[0][key]", cmd)

    @patch.object(agent, "ensure_auth")
    @patch.object(agent, "api", side_effect=responses)
    def test_dry_run_does_not_post(self, api, _auth):
        self.assertEqual(0, agent.cmd_stage0_plan(CFG, Namespace(execute=False)))
        self.assertNotIn("POST", [call.args[1] for call in api.call_args_list if len(call.args) > 1])

    @patch.object(agent, "ensure_auth")
    @patch.object(agent, "rounds_file", return_value="/nonexistent/agent-ci-rounds")
    @patch.object(agent, "api_read_with_permission_check", return_value=[
        {"key": k, "value": v} for k, v in agent.STAGE0_VARIABLES.items()
    ])
    @patch.object(agent, "api", side_effect=responses)
    def test_execute_posts_fixed_plan_and_validates_it(self, api, _variables, _rounds, _auth):
        self.assertEqual(0, agent.cmd_stage0_plan(CFG, Namespace(execute=True)))
        self.assertEqual(1, sum(call.args[:2] == ("projects/:id/pipeline", "POST")
                                for call in api.call_args_list))

    @patch.object(agent, "ensure_auth")
    @patch.object(agent, "api", side_effect=responses)
    def test_rejects_unprotected_main(self, api, _auth):
        def unprotected(endpoint, method="GET", **kwargs):
            if endpoint.endswith("/branches/main"):
                return {"protected": False}
            return responses(endpoint, method, **kwargs)
        api.side_effect = unprotected
        with self.assertRaises(SystemExit):
            agent.cmd_stage0_plan(CFG, Namespace(execute=True))
        self.assertFalse(any(call.args[0] == "projects/:id/pipeline" for call in api.call_args_list))

    @patch.object(agent, "ensure_auth")
    @patch.object(agent, "api", side_effect=responses)
    def test_rejects_other_project(self, api, _auth):
        with self.assertRaises(SystemExit):
            agent.cmd_stage0_plan({**CFG, "stage0_plan": {**CFG["stage0_plan"], "project_path": "other/repo"}},
                                  Namespace(execute=True))
        self.assertFalse(any(call.args[0] == "projects/:id/pipeline" for call in api.call_args_list))

    def test_invalid_preset(self):
        for cfg in ({}, {"stage0_plan": {"project_path": "group/project", "ref": "dev3"}},
                    {"stage0_plan": {"project_path": "", "ref": "main"}}):
            with self.assertRaises(SystemExit):
                agent.stage0_config(cfg)

    @patch.object(agent, "branch", return_value="fix/stage0-tooling")
    @patch.object(agent, "jobs_of", return_value=[])
    @patch.object(agent, "api_read_with_permission_check", return_value=None)
    @patch.object(agent, "api", side_effect=responses)
    def test_success_without_stage0_job_is_not_green(self, *_):
        args = Namespace(pipeline=123, stage0=True, timeout=1, interval=1, tail=5)
        self.assertEqual(3, agent.cmd_watch(CFG, args))

    @patch.object(agent, "branch", return_value="fix/stage0-tooling")
    @patch.object(agent, "jobs_of", return_value=[{"name": "landing-zone-deploy-stage0", "status": "success", "id": 1}])
    @patch.object(agent, "stage0_round")
    @patch.object(agent, "summarize_stage0_plan")
    @patch.object(agent, "api_read_with_permission_check", return_value=None)
    @patch.object(agent, "api", side_effect=responses)
    def test_exact_successful_stage0_job_is_green(self, *_):
        args = Namespace(pipeline=123, stage0=True, timeout=1, interval=1, tail=5)
        self.assertEqual(0, agent.cmd_watch(CFG, args))

    @patch.object(agent, "api", side_effect=responses)
    @patch.object(agent, "api_read_with_permission_check", return_value=[
        {"key": "APPLY_MODE", "value": "apply"}
    ])
    def test_rejects_wrong_pipeline_variables(self, _read, _api):
        with self.assertRaises(SystemExit):
            agent.validate_stage0_pipeline(CFG, 123)

    @patch.object(agent, "api", return_value=(
        "[INFO] Running FAST stage '0-org-setup' in mode: plan\n"
        "Plan: 2 to add, 0 to change, 0 to destroy.\n"
        "[INFO] Plan-only mode complete for 0-org-setup.\n"
    ))
    def test_missing_artifact_cannot_be_called_reviewable(self, _api):
        self.assertFalse(agent.summarize_stage0_plan({"id": 3}, False))

    @patch.object(agent, "api", return_value=(
        "[INFO] Running FAST stage '0-org-setup' in mode: plan\n"
        "Plan: 2 to add, 0 to change, 1 to destroy.\n"
        "[INFO] Plan-only mode complete for 0-org-setup.\n"
    ))
    @patch.object(agent.subprocess, "run")
    def test_destructive_plan_only_reports_action_counts(self, run, _api):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"resource_changes":[{"change":{"actions":["delete","create"],"after":{"secret":"dont print"}}}]}'
        self.assertFalse(agent.summarize_stage0_plan(
            {"id": 3, "artifacts": [{"file_type": "archive", "size": 123}]}, True))

    @patch.object(agent, "api", return_value=(
        "[INFO] Running FAST stage '0-org-setup' in mode: plan\n"
        "Plan: 1 to add, 0 to change, 0 to destroy.\n"
        "[INFO] Plan-only mode complete for 0-org-setup.\n"
    ))
    @patch.object(agent.subprocess, "run")
    def test_safe_plan_with_artifact_is_reviewable(self, run, _api):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"resource_changes":[{"change":{"actions":["create"]}}]}'
        self.assertTrue(agent.summarize_stage0_plan(
            {"id": 3, "artifacts": [{"file_type": "archive", "size": 123}]}, False))

    @patch.object(agent, "api", return_value="Running FAST stage '0-org-setup' in mode: apply")
    def test_apply_trace_never_accepted_as_plan(self, _api):
        self.assertFalse(agent.summarize_stage0_plan({"id": 3}, False))


if __name__ == "__main__":
    unittest.main()
