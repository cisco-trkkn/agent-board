#!/usr/bin/env python3
"""Run the checks from .agent-ci.yml that match the files changed on this branch.

Changed files = commits since merge-base with the integration branch
              + staged + unstaged + untracked files.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from agentci_config import STATE_DIR, load_config, repo_root  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ""
    # Piped (agents, Remote Control): flush every line so progress shows as it happens.
    sys.stdout.reconfigure(line_buffering=True)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def resolve_base(base: str) -> str | None:
    for ref in (f"origin/{base}", base):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", ref], capture_output=True).returncode == 0:
            return ref
    return None


def changed_files(base: str) -> list[str]:
    files: set[str] = set()
    ref = resolve_base(base)
    if ref:
        mb = git("merge-base", ref, "HEAD").strip()
        if mb:
            files.update(git("diff", "--name-only", mb, "HEAD").split())
    files.update(git("diff", "--name-only").split())
    files.update(git("diff", "--name-only", "--cached").split())
    files.update(git("ls-files", "--others", "--exclude-standard").split())
    return sorted(f for f in files if not f.startswith(STATE_DIR + "/"))


def glob_to_regex(pattern: str) -> re.Pattern:
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$")


def matches(check: dict, files: list[str]) -> list[str]:
    if check.get("always"):
        return ["(always)"]
    regs = [glob_to_regex(p) for p in check.get("paths") or []]
    return [f for f in files if any(r.match(f) for r in regs)]


def as_script(lines) -> str:
    if isinstance(lines, str):
        lines = [lines]
    return "set -eo pipefail\n" + "\n".join(lines)


def ensure_venv(root: str, version: str, name: str = "") -> str:
    """Create .agent-ci/venv-<name|version>, preferring uv (can fetch the exact CI Python), then pythonX.Y."""
    venv = os.path.join(root, STATE_DIR, f"venv-{name or version or 'default'}")
    if os.path.exists(os.path.join(venv, "bin", "python")):
        return venv
    uv = shutil.which("uv")
    if version and uv:
        print(f"{DIM}creating venv (uv, python {version}){RESET}")
        # UV_NATIVE_TLS: use the OS trust store (works behind corporate TLS inspection)
        rc = subprocess.run([uv, "venv", "--quiet", "--seed", "--python", version, venv],
                            env={**os.environ, "UV_NATIVE_TLS": "1"}).returncode
        if rc == 0:
            return venv
        shutil.rmtree(venv, ignore_errors=True)
    if version and shutil.which(f"python{version}"):
        print(f"{DIM}creating venv (python{version}){RESET}")
        subprocess.run([f"python{version}", "-m", "venv", venv], check=True)
    else:
        if version:
            print(f"{YELLOW}python {version} not available (install uv for exact match); using {sys.version.split()[0]}{RESET}")
        subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    return venv


def build_env(root: str, cfg: dict, extra: dict | None, chk: dict | None = None) -> dict:
    env = dict(os.environ)
    env["CI_PROJECT_DIR"] = root
    if cfg.get("python_venv"):
        chk = chk or {}
        version = str(chk.get("python_version") or cfg.get("python_version") or "")
        own = chk.get("venv") == "own"
        venv = ensure_venv(root, version, f"{chk['name']}-{version}" if own else "")
        env["VIRTUAL_ENV"] = venv
        env["PATH"] = os.path.join(venv, "bin") + os.pathsep + env["PATH"]
    for k, v in (extra or {}).items():
        env[str(k)] = str(v)
    return env


def run_setup(root: str, label: str, cmds, env: dict, force: bool, extra_keys=()) -> bool:
    if not cmds:
        return True
    script = as_script(cmds)
    key = script + repr(sorted((k, env.get(k)) for k in ("VIRTUAL_ENV", *extra_keys)))
    stamp = os.path.join(root, STATE_DIR, "setup", hashlib.sha1(key.encode()).hexdigest())
    if os.path.exists(stamp) and not force:
        return True
    print(f"{DIM}setup: {label}{RESET}")
    log = os.path.join(root, STATE_DIR, "logs", f"setup-{label}.log")
    with open(log, "w") as fh:
        rc = subprocess.run(["bash", "-c", script], cwd=root, env=env, stdin=subprocess.DEVNULL,
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        print(f"{RED}setup failed for {label}{RESET} (see {os.path.relpath(log, root)})")
        return False
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    open(stamp, "w").close()
    return True


def tail(path: str, n: int) -> str:
    with open(path, errors="replace") as fh:
        return "".join(fh.readlines()[-n:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="branch to diff against (default: integration_branch)")
    ap.add_argument("--all", action="store_true", help="run every check regardless of changes")
    ap.add_argument("--only", action="append", default=[], help="run only this check (repeatable)")
    ap.add_argument("--list", action="store_true", help="show which checks would run, then exit")
    ap.add_argument("--no-setup", action="store_true", help="skip setup commands")
    ap.add_argument("--resetup", action="store_true", help="re-run setup commands even if cached")
    ap.add_argument("--tail", type=int, default=40, help="log lines to show for failures")
    args = ap.parse_args()

    root = repo_root()
    os.chdir(root)
    cfg = load_config(root)
    os.makedirs(os.path.join(root, STATE_DIR, "logs"), exist_ok=True)
    base = args.base or cfg["integration_branch"]
    files = changed_files(base)

    selected = []
    for chk in cfg.get("checks") or []:
        if args.only and chk["name"] not in args.only:
            continue
        hits = ["(forced)"] if (args.all or args.only) else matches(chk, files)
        if hits:
            selected.append((chk, hits))

    print(f"{DIM}{len(files)} changed file(s) vs {base}; {len(selected)} check(s) selected{RESET}")
    if args.list:
        for chk, hits in selected:
            flag = f" {YELLOW}[ci-only: {chk.get('skip_local')}]{RESET}" if chk.get("skip_local") else ""
            print(f"  {chk['name']}{flag}  {DIM}<- {', '.join(hits[:3])}{'…' if len(hits) > 3 else ''}{RESET}")
        return 0
    if not selected:
        print(f"{GREEN}nothing to check{RESET}")
        return 0

    base_env = build_env(root, cfg, None)
    if not args.no_setup and not run_setup(root, "global", cfg.get("setup"), base_env, args.resetup):
        return 1

    results = []
    for chk, _ in selected:
        name = chk["name"]
        if chk.get("skip_local"):
            results.append((name, "SKIP", 0.0, None))
            continue
        env = build_env(root, cfg, chk.get("env"), chk)
        if not args.no_setup and not run_setup(root, name, chk.get("setup"), env, args.resetup, tuple(chk.get("env") or {})):
            results.append((name, "FAIL", 0.0, None))
            continue
        log = os.path.join(root, STATE_DIR, "logs", f"{name}.log")
        start = time.time()
        if sys.stdout.isatty():
            print(f"{DIM}running {name}…{RESET}", end="", flush=True)
        else:
            print(f"running {name}… (log: {os.path.relpath(log, root)})")
        with open(log, "w") as fh:
            rc = subprocess.run(["bash", "-c", as_script(chk["run"])], cwd=root, env=env,
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT).returncode
        dur = time.time() - start
        if sys.stdout.isatty():
            print("\r\033[K", end="")
        else:
            print(f"{'PASS' if rc == 0 else 'FAIL'} {name} {dur:.1f}s")
        results.append((name, "PASS" if rc == 0 else "FAIL", dur, log))

    failed = [r for r in results if r[1] == "FAIL"]
    for name, status, dur, log in results:
        color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[status]
        print(f"{color}{status}{RESET} {name} {DIM}{dur:.1f}s{RESET}")
    for name, _, _, log in failed:
        if log:
            print(f"\n{RED}── {name} ── last {args.tail} lines ({os.path.relpath(log, root)}){RESET}")
            print(tail(log, args.tail).rstrip())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
