#!/usr/bin/env python3
"""Generate a starter .agent-ci.yml by scanning .gitlab-ci.yml (and its local includes).

Validation-like jobs (stage matches --stages) become local checks:
  rules:changes      -> paths
  before_script      -> setup (package installs only; OS package managers are dropped)
  script             -> run
  variables          -> env
  services           -> skip_local (needs sidecar containers)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from agentci_config import die, repo_root  # noqa: E402

RESERVED = {"stages", "include", "variables", "default", "workflow", "image", "services",
            "before_script", "after_script", "cache", "types", "pages"}
SETUP_RE = re.compile(r"^\s*(pip3?|python3? -m pip|npm (ci|install)|yarn( install)?|pnpm install|poetry install|uv (sync|pip install)|go mod download|bundle install)\b")
DROP_RE = re.compile(r"^\s*(apt(-get)?|apk|yum|dnf|brew)\b|^\s*export PATH=|^\s*\. .*auth|gcloud auth")
ARTIFACT_NOISE = [
    (re.compile(r"\s+--json-report(-file=\S+)?"), ""),
    (re.compile(r"\s*>\s*/tmp/\S+"), ""),
]


class Ref(list):
    pass


def yaml_load(path: str):
    import yaml  # type: ignore

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!reference", lambda l, n: Ref(l.construct_sequence(n)))
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader) or {}


def collect(root: str, path: str, seen: set, docs: dict, notes: list) -> None:
    full = os.path.join(root, path.lstrip("/"))
    for match in sorted(glob.glob(full)) or [full]:
        if match in seen or not os.path.exists(match):
            if not os.path.exists(match):
                notes.append(f"include not found: {path}")
            continue
        seen.add(match)
        data = yaml_load(match)
        incs = data.get("include") or []
        if isinstance(incs, (str, dict)):
            incs = [incs]
        for inc in incs:
            if isinstance(inc, str):
                if inc.startswith("http"):
                    notes.append(f"remote include skipped: {inc}")
                else:
                    collect(root, inc, seen, docs, notes)
            elif isinstance(inc, dict) and "local" in inc:
                collect(root, inc["local"], seen, docs, notes)
            else:
                notes.append(f"non-local include skipped: {inc}")
        for k, v in data.items():
            if isinstance(v, dict):
                docs[k] = v


def resolve(name: str, jobs: dict, depth: int = 0) -> dict:
    job = jobs.get(name) or {}
    parents = job.get("extends") or []
    if isinstance(parents, str):
        parents = [parents]
    merged: dict = {}
    if depth < 10:
        for p in parents:
            deep_merge(merged, resolve(p, jobs, depth + 1))
    deep_merge(merged, {k: v for k, v in job.items() if k != "extends"})
    return merged


def deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v


def as_lines(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    out = []
    for item in v:
        out.extend(as_lines(item) if isinstance(item, list) and not isinstance(item, Ref) else
                   [f"# TODO !reference {list(item)}"] if isinstance(item, Ref) else [str(item)])
    return out


def to_check(name: str, job: dict) -> dict:
    paths: list[str] = []
    always = False
    for rule in job.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("when") == "never":
            continue
        ch = rule.get("changes")
        if isinstance(ch, dict):
            ch = ch.get("paths")
        if ch:
            paths.extend(p for p in ch if p not in paths)
        elif "if" in rule and ("merge_request" in rule["if"] or "push" in rule["if"]):
            pass
    only_changes = (job.get("only") or {}).get("changes") if isinstance(job.get("only"), dict) else None
    if only_changes:
        paths.extend(p for p in only_changes if p not in paths)
    if not paths:
        always = True

    setup, run, dropped = [], [], []
    cwd = None
    for line in as_lines(job.get("before_script")) + as_lines(job.get("script")):
        cd = re.match(r"^\s*cd\s+(.+?)\s*$", line)
        if cd:
            cwd = cd.group(1)
        if DROP_RE.search(line):
            dropped.append(line)
        elif SETUP_RE.search(line):
            setup.append(f"cd {cwd} && {line}" if cwd else line)
        else:
            for rx, rep in ARTIFACT_NOISE:
                line = rx.sub(rep, line)
            run.append(line)

    check = {"name": name}
    if always:
        check["always"] = True
    else:
        check["paths"] = [p.replace("**/*", "**") if p.endswith("**/*") else p for p in paths]
    env = {k: v for k, v in (job.get("variables") or {}).items() if isinstance(v, (str, int, float))}
    if env:
        check["env"] = env
    if setup:
        check["setup"] = setup
    check["run"] = run or ["# TODO: no script found"]
    if job.get("services"):
        check["skip_local"] = "needs CI services: " + ", ".join(
            s if isinstance(s, str) else s.get("name", "?") for s in job["services"])
    image = job.get("image") if isinstance(job.get("image"), str) else (job.get("image") or {}).get("name")
    if image and "python" in image and not re.match(r"^python:", image):
        check["venv"] = "own"  # specialised image (e.g. apache/airflow): keep its deps isolated
        m = re.search(r"python(\d+\.\d+)", image)
        if m:
            check["python_version"] = m.group(1)
        af = re.match(r"^apache/airflow:(\d+\.\d+\.\d+)-python(\d+\.\d+)", image)
        if af:  # reproduce the official Airflow image: pin airflow and constrain every pip install
            av, pv = af.groups()
            check.setdefault("env", {})["PIP_CONSTRAINT"] = (
                f"https://raw.githubusercontent.com/apache/airflow/constraints-{av}/constraints-{pv}.txt")
            check.setdefault("setup", []).insert(0, f'pip install --quiet "apache-airflow=={av}"')
    check["_image"] = job.get("image") if isinstance(job.get("image"), str) else (job.get("image") or {}).get("name")
    check["_dropped"] = dropped
    return check


def dump(cfg_head: dict, checks: list[dict], notes: list[str], python_venv: bool, python_version: str = "") -> str:
    j = json.dumps
    out = [
        "# gitlab-ci-loop config — generated by gen-config.py; edit freely.",
        "# Each check runs locally (bash, repo root) when a changed file matches `paths`.",
        "version: 1",
        f"integration_branch: {j(cfg_head['integration'])}   # agent MRs target this branch",
        f"branch_prefix: {j(cfg_head['prefix'])}",
        f"protected_branches: {j(cfg_head['protected'])}   # agent-ci refuses to push these",
        "max_ci_rounds: 5                # stop and report to the user after this many red pipelines",
        f"python_venv: {'true' if python_venv else 'false'}               # run checks inside .agent-ci/venv",
        f"python_version: {j(python_version)}          # venv interpreter (uv fetches it if missing); match CI image",
        "setup: []                       # global setup commands, run once (cached)",
    ]
    for n in notes:
        out.append(f"# NOTE: {n}")
    out.append("checks:" if checks else "checks: []")
    for c in checks:
        out.append(f"  - name: {j(c['name'])}")
        if c.get("_image"):
            out.append(f"    # CI image: {c['_image']}")
        for d in c.get("_dropped", []):
            out.append(f"    # dropped (CI-only): {d}")
        if c.get("always"):
            out.append("    always: true")
        else:
            out.append("    paths:")
            out.extend(f"      - {j(p)}" for p in c["paths"])
        if c.get("env"):
            out.append("    env:")
            out.extend(f"      {k}: {j(str(v))}" for k, v in c["env"].items())
        if c.get("venv"):
            out.append(f"    venv: {j(c['venv'])}   # isolated venv; pin the image's preinstalled packages in setup")
        if c.get("python_version"):
            out.append(f"    python_version: {j(c['python_version'])}")
        if c.get("skip_local"):
            out.append(f"    skip_local: {j(c['skip_local'])}")
        if c.get("setup"):
            out.append("    setup:")
            out.extend(f"      - {j(s)}" for s in c["setup"])
        out.append("    run:")
        out.extend(f"      - {j(r)}" for r in c["run"])
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--integration", default="main")
    ap.add_argument("--prefix", default="agent/")
    ap.add_argument("--protected", default="", help="comma-separated protected branches")
    ap.add_argument("--stages", default=r"validate|test|lint|check|verify|health",
                    help="regex of stage names treated as validation")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()

    root = repo_root()
    ci = os.path.join(root, ".gitlab-ci.yml")
    notes: list[str] = []
    checks: list[dict] = []
    if os.path.exists(ci):
        docs: dict = {}
        collect(root, ".gitlab-ci.yml", set(), docs, notes)
        stage_re = re.compile(args.stages)
        for name in docs:
            if name.startswith(".") or name in RESERVED:
                continue
            job = resolve(name, docs)
            if "script" not in job:
                continue
            if stage_re.search(str(job.get("stage", "test"))):
                checks.append(to_check(name, job))
    else:
        notes.append("no .gitlab-ci.yml found — add checks by hand")

    python_venv = any("python" in " ".join(c["run"] + c.get("setup", [])) or "pytest" in " ".join(c["run"])
                      for c in checks)
    versions = [m.group(1) for c in checks
                for m in [re.search(r"python:(\d+\.\d+)", str(c.get("_image") or ""))] if m]
    python_version = max(set(versions), key=versions.count) if versions else ""
    protected = [b for b in args.protected.split(",") if b] or [args.integration]
    text = dump({"integration": args.integration, "prefix": args.prefix, "protected": protected},
                checks, notes, python_venv, python_version)
    if args.output == "-":
        sys.stdout.write(text)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.output} ({len(checks)} checks)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
