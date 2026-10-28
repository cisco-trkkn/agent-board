"""Offline tests for the local-check setup cache key."""
import importlib.util
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("local_check", os.path.join(HERE, "local-check.py"))
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


class SetupCacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, lc.STATE_DIR, "logs"))
        os.makedirs(os.path.join(self.root, "src"))

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w") as fh:
            fh.write(text)

    def run_setup(self, cmds):
        """Returns how many times the setup commands really ran."""
        with patch.object(lc.subprocess, "run", return_value=Namespace(returncode=0)) as run:
            self.assertTrue(lc.run_setup(self.root, "t", cmds, {}, False))
        return run.call_count

    def test_changed_requirements_file_reruns_setup(self):
        cmds = ["pip install -r requirements.txt"]
        self.write("requirements.txt", "requests\n")
        self.assertEqual(1, self.run_setup(cmds))
        self.assertEqual(0, self.run_setup(cmds))  # unchanged: cached
        self.write("requirements.txt", "requests\nflask\n")
        self.assertEqual(1, self.run_setup(cmds))  # same command text, new package

    def test_cd_prefix_resolves_the_file_in_that_directory(self):
        cmds = ["cd src && pip install --requirement requirements.txt"]
        self.write("src/requirements.txt", "requests\n")
        self.assertEqual(1, self.run_setup(cmds))
        self.write("src/requirements.txt", "requests\nflask\n")
        self.assertEqual(1, self.run_setup(cmds))

    def test_constraint_file_and_nested_include_count(self):
        cmds = ["pip install -r requirements.txt -c constraints.txt"]
        self.write("requirements.txt", "-r base.txt\n")
        self.write("base.txt", "requests\n")
        self.write("constraints.txt", "requests<3\n")
        self.assertEqual(1, self.run_setup(cmds))
        self.write("constraints.txt", "requests<2\n")
        self.assertEqual(1, self.run_setup(cmds))
        self.write("base.txt", "requests\nflask\n")
        self.assertEqual(1, self.run_setup(cmds))

    def test_missing_file_is_a_marker_not_an_error(self):
        cmds = ["pip install -r nope.txt"]
        self.assertEqual(1, self.run_setup(cmds))
        self.assertEqual(0, self.run_setup(cmds))
        self.write("nope.txt", "requests\n")  # appears later: key changes
        self.assertEqual(1, self.run_setup(cmds))

    def test_commands_without_pip_ignore_dash_r(self):
        cmds = ["rm -r build"]
        self.write("build", "x")
        self.assertEqual(1, self.run_setup(cmds))
        self.write("build", "y")
        self.assertEqual(0, self.run_setup(cmds))

    def test_setup_without_file_references_keeps_the_old_key(self):
        cmds = ["pip install requests"]
        env = {"VIRTUAL_ENV": None}
        old = lc.hashlib.sha1((lc.as_script(cmds) + repr(sorted((k, env.get(k)) for k in ("VIRTUAL_ENV",)))).encode()).hexdigest()
        self.assertEqual(1, self.run_setup(cmds))
        self.assertTrue(os.path.exists(os.path.join(self.root, lc.STATE_DIR, "setup", old)))


class CheckEnvTests(unittest.TestCase):
    """Checks start from a defined environment: state-redirecting variables of the caller are dropped."""

    AMBIENT = {"TF_DATA_DIR": "/tmp/other-tenant/.terraform", "TF_WORKSPACE": "stage",
               "TF_CLI_ARGS": "-no-color", "TF_CLI_ARGS_plan": "-lock=false", "HOME_MARKER": "kept"}

    def build(self, cfg=None, extra=None):
        with patch.dict(os.environ, self.AMBIENT):
            return lc.build_env("/repo", cfg or {}, extra)

    def test_caller_terraform_state_vars_are_dropped(self):
        env = self.build()
        # Assert on one key at a time: a failing assertNotIn(k, env) prints the whole environment.
        for k in ("TF_DATA_DIR", "TF_WORKSPACE", "TF_CLI_ARGS", "TF_CLI_ARGS_plan"):
            self.assertIsNone(env.get(k), k)
        self.assertEqual("kept", env["HOME_MARKER"])
        self.assertEqual("/repo", env["CI_PROJECT_DIR"])

    def test_check_env_can_set_a_dropped_var(self):
        env = self.build(extra={"TF_DATA_DIR": ".terraform-check"})
        self.assertEqual(".terraform-check", env["TF_DATA_DIR"])

    def test_env_unset_adds_repo_specific_names(self):
        env = self.build(cfg={"env_unset": ["HOME_MARKER"]})
        self.assertIsNone(env.get("HOME_MARKER"), "HOME_MARKER")

    def test_real_shell_does_not_see_caller_tf_data_dir(self):
        # One unpatched run: the env reaches a real bash the way a check's `run` does.
        import subprocess
        env = self.build()
        out = subprocess.run(["bash", "-c", 'echo "${TF_DATA_DIR-unset}"'], env=env,
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual("unset", out)


if __name__ == "__main__":
    unittest.main()
