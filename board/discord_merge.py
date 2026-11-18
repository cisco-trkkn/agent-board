#!/usr/bin/env python3
"""discord_merge: merge evidence and the merge-approval request for the ops bot (queue mode `integration: ask`).

`tmux-ctl discord merge-request` -> request(): evidence from git (argv lists only, `--` before paths), written to
<_ops>/evidence/<project>-<task>.json, and one `merge_approval` decision event in the project's feed (discord_ops mirrors it
into #approvals). on_merge() is discord_ops' Merge-button hook: it re-checks the branch tip and either tells the lead to
merge or re-posts fresh evidence. Branch, target, task and project values are shape-checked before anything runs.
Test: tests/test_discord_merge.py."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_feed  # noqa: E402
import tc_env  # noqa: E402

REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SRC_RE = re.compile(r"^merge:([A-Za-z0-9._-]+)(?::([0-9a-f]{8}))?$")
FILES_SHOWN = 25
DIFF_MAX = 1800
TEXT_MAX = 1900
FINDING_MAX = 200
DIFF_NOTE = "\n… too long, see board"
GIT_TIMEOUT = 60


def _ref(v, what):
    if not isinstance(v, str) or not REF_RE.match(v) or v.startswith("-") or ".." in v or v.endswith("/") or v.endswith(".lock"):
        raise ValueError(f"invalid {what}")
    return v


def _one_line(v, what, n=200):
    s = " ".join(str(v or "").split())[:n]
    if not s:
        raise ValueError(f"empty {what}")
    return s


def _git(repo, *args, check=True):
    """A git call as an argv list (never a shell string). The values are validated by the callers; paths follow `--`."""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace", timeout=GIT_TIMEOUT)
    if check and r.returncode != 0:
        raise ValueError(f"git {args[0]} failed")
    return r


def rev_parse(repo, branch):
    """The branch's commit sha, or None when the branch does not exist."""
    r = _git(repo, "rev-parse", "--verify", "--quiet", f"{_ref(branch, 'branch')}^{{commit}}", check=False)
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def evidence(repo, branch, target):
    """{sha, files:[{path, add, del}], stat:[lines], diffs:{path: text}} for `target...branch`. Rename detection is off:
    a moved file is listed under both its paths. Diffs are kept for the first FILES_SHOWN files (the select menu's options)."""
    _ref(branch, "branch")
    _ref(target, "target")
    sha = rev_parse(repo, branch)
    if not sha:
        raise ValueError("branch not found")
    rng = f"{target}...{branch}"
    files = []
    raw = _git(repo, "diff", "--no-ext-diff", "--no-color", "--numstat", "--no-renames", "-z", rng, "--").stdout
    for ent in filter(None, raw.split("\0")):
        add, dele, path = ent.split("\t", 2)
        files.append({"path": path, "add": int(add) if add.isdigit() else 0, "del": int(dele) if dele.isdigit() else 0})
    stat = _git(repo, "diff", "--no-ext-diff", "--no-color", "--stat=200,200", "--no-renames", rng, "--").stdout.splitlines()
    if stat and files:
        stat = stat[:-1]   # the trailing "N files changed" summary: the post carries its own totals
    diffs = {}
    for f in files[:FILES_SHOWN]:
        d = _git(repo, "diff", "--no-ext-diff", "--no-color", "--no-renames", rng, "--", f["path"]).stdout
        diffs[f["path"]] = d[:DIFF_MAX] + DIFF_NOTE if len(d) > DIFF_MAX else d
    return {"sha": sha, "files": files, "stat": stat, "diffs": diffs}


def post_text(spec, branch, target, ev, tests, verdict, findings):
    lines = [f"merge approval: {spec}", f"{branch} → {target} @ {ev['sha'][:8]}"]
    lines += ev["stat"][:FILES_SHOWN]
    if len(ev["stat"]) > FILES_SHOWN:
        lines.append(f"… {len(ev['stat']) - FILES_SHOWN} more")
    lines += [f"tests: {tests}", f"final review: {verdict}"]
    lines += [str(f)[:FINDING_MAX] for f in findings]
    adds, dels = sum(f["add"] for f in ev["files"]), sum(f["del"] for f in ev["files"])
    lines.append(f"diff: {len(ev['files'])} files, +{adds} −{dels}")
    return "\n".join(lines)[:TEXT_MAX]


def _ops_configured():
    import discord_ops
    return discord_ops.configured()


def _write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, p)


def _evidence_path(project, task):
    return tc_env.ops_dir() / "evidence" / f"{project}-{task}.json"


def request(project, repo, task, spec, branch, target, tests, verdict, findings, now):
    """Compute the evidence, store it (ops configured), append the merge_approval feed event.
    Returns {"spec", "ops": bool, "sha", "src_key"}. ValueError on a bad value, before anything is written."""
    if not isinstance(project, str) or not PROJECT_RE.match(project):
        raise ValueError("invalid project")
    if not isinstance(task, str) or not ID_RE.match(task):
        raise ValueError("invalid task")
    spec = _one_line(spec, "spec")
    tests, verdict = _one_line(tests, "tests", 300), _one_line(verdict, "verdict", 300)
    findings = [" ".join(str(f).split())[:FINDING_MAX] for f in findings if str(f).strip()]
    ev = evidence(repo, branch, target)
    text = post_text(spec, branch, target, ev, tests, verdict, findings)
    ops = _ops_configured()
    path = ""
    if ops:
        path = str(_evidence_path(project, task))
        _write_json(Path(path), {"project": project, "task": task, "spec": spec, "branch": branch, "target": target, "repo": str(repo),
                                 "tests": tests, "verdict": verdict, "findings": findings, "ts": now, "sha": ev["sha"],
                                 "files": ev["files"], "diffs": ev["diffs"], "text": text})
    refs = {"task": task, "sha": ev["sha"], "branch": branch}
    if path:
        refs["evidence"] = path
    discord_feed.append_event(project, {"ts": now, "project": project, "spec": spec, "kind": "merge_approval", "tier": "decision",
                                        "text": text, "refs": refs})
    return {"spec": spec, "ops": ops, "sha": ev["sha"], "src_key": discord_feed.merge_key(refs)}


def on_merge(project, src_key, rec, add_line, now):
    """The Merge button. Same branch tip as posted -> `[Discord] merge approved for <spec>` to the lead; a moved or deleted
    branch -> nothing is sent, and a moved one gets a fresh request. Returns {"result", "text"} for discord_ops, which edits
    both copies; never touches the ops state (its lock is held)."""
    m = SRC_RE.match(str(src_key))
    stale = {"result": "stale", "text": "branch changed since this was posted"}
    if not m or not PROJECT_RE.match(str(project)):
        return {"result": "stale", "text": "this approval cannot be checked; ask the lead to post it again"}
    task, sha8 = m.group(1), m.group(2)
    try:
        ev = json.loads(_evidence_path(project, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"result": "stale", "text": "no evidence stored for this approval; ask the lead to post it again"}
    if not isinstance(ev, dict) or not ev.get("sha"):
        return {"result": "stale", "text": "no evidence stored for this approval; ask the lead to post it again"}
    if sha8 and ev["sha"][:8] != sha8:
        return {"result": "stale", "text": "superseded by a newer request"}
    now_sha = rev_parse(ev["repo"], ev["branch"])
    if now_sha == ev["sha"]:
        add_line(project, f"[Discord] merge approved for {ev['spec']}")
        return {"result": "merged", "text": "merge approved — sent to the lead"}
    if now_sha:
        request(project, ev["repo"], task, ev["spec"], ev["branch"], ev["target"], ev["tests"], ev["verdict"], ev.get("findings") or [], now)
    return stale


# ---- CLI: tmux-ctl discord merge-request ----
_VALUE_OPTS = {"--project": "project", "--task": "task", "--spec": "spec", "--branch": "branch", "--target": "target",
               "--tests": "tests", "--verdict": "verdict", "--repo": "repo"}


def _parse(argv):
    """Hand-parsed so a rejected value is never echoed (it may be a token). None on any unknown or incomplete option."""
    o = {"target": "main", "findings": [], "repo": ""}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--finding" and i + 1 < len(argv):
            o["findings"].append(argv[i + 1])
        elif a in _VALUE_OPTS and i + 1 < len(argv):
            o[_VALUE_OPTS[a]] = argv[i + 1]
        else:
            return None
        i += 2
    return o


def main(argv):
    if not argv or argv[0] != "request":
        print("usage: discord_merge.py request --project <p> --task <id> --spec <spec> --branch <b> [--target main] "
              "--tests <line> --verdict <text> [--finding <line>]... [--repo <dir>]", file=sys.stderr)
        return 2
    o = _parse(argv[1:])
    need = ("project", "task", "spec", "branch", "tests", "verdict")
    if o is None or any(k not in o for k in need):
        print("merge-request: missing or unknown option (see tmux-ctl help)", file=sys.stderr)
        return 2
    repo = o["repo"]
    if not repo:
        # the main checkout, not a spec worktree that may be removed before the tap: the parent of the common git dir
        r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True)
        repo = os.path.dirname(r.stdout.strip().rstrip("/")) if r.returncode == 0 and r.stdout.strip() else ""
    if not repo:
        print("merge-request: not inside a git repository (use --repo)", file=sys.stderr)
        return 2
    try:
        res = request(o["project"], repo, o["task"], o["spec"], o["branch"], o["target"], o["tests"], o["verdict"], o["findings"], time.time())
    except ValueError as e:
        print(f"merge-request: {e}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as e:
        print(f"merge-request: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"merge-request: posted {res['spec']}" + ("" if res["ops"] else " (ops bot not set up: project channel only)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
