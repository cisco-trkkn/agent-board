"""Shared helpers for the gitlab-ci-loop skill: repo root discovery and .agent-ci.yml loading."""
from __future__ import annotations

import os
import subprocess
import sys

CONFIG_NAME = ".agent-ci.yml"
STATE_DIR = ".agent-ci"

DEFAULTS = {
    "version": 1,
    "integration_branch": "main",
    "branch_prefix": "agent/",
    "protected_branches": ["main"],
    "max_ci_rounds": 5,
    "python_venv": False,
    "setup": [],
    "checks": [],
}


def die(msg: str, code: int = 1) -> None:
    print(f"[agent-ci] {msg}", file=sys.stderr)
    sys.exit(code)


def repo_root() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        die("not inside a git repository")
    return out.stdout.strip()


def load_yaml(path: str):
    try:
        import yaml  # type: ignore
    except ImportError:
        die("PyYAML is required: python3 -m pip install --user pyyaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(root: str | None = None) -> dict:
    root = root or repo_root()
    path = os.path.join(root, CONFIG_NAME)
    if not os.path.exists(path):
        die(f"{CONFIG_NAME} not found in {root}. Run the skill's bootstrap.sh first.")
    cfg = dict(DEFAULTS)
    cfg.update(load_yaml(path))
    for chk in cfg.get("checks") or []:
        if "name" not in chk or "run" not in chk:
            die(f"every check in {CONFIG_NAME} needs 'name' and 'run': {chk}")
    return cfg


def main() -> None:
    """CLI: agentci_config.py get <key>  -> prints value (lists space-separated)."""
    if len(sys.argv) != 3 or sys.argv[1] != "get":
        die("usage: agentci_config.py get <key>")
    val = load_config().get(sys.argv[2], "")
    if isinstance(val, list):
        print(" ".join(str(v) for v in val))
    else:
        print(val)


if __name__ == "__main__":
    main()
