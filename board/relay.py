#!/usr/bin/env python3
"""relay: hand a dev session's `claude` window to a fresh orchestrator, in place.

  relay.py --session S --doc D [--old-session ID] [--state DIR] [--socket PATH]

Waits until the lead's turn has ended (paneclass says idle/ready on two polls in a row, 2s apart,
120s cap), respawns the pane with `claude-orchestrator "Read <doc> ..."`, and appends
{ts, old_session_id, doc, pane} to tc_env.lineage_dir()/<session>.jsonl (~/.local/state/agent-board/lineage). The board's
restart_orchestrator uses respawn() too. On failure the old pane is left alone.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import paneclass  # noqa: E402
import tc_env  # noqa: E402

SEP = paneclass.SEP
ENDED = {"idle", "ready"}


def prompt_for(doc):
    return f"Read {doc} and continue from where the previous session left off."


def wait_turn_end(tmux, pane, poll=2.0, cap=120.0, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + cap
    streak = 0
    while True:
        _, status = paneclass.pane_status(tmux, pane)
        streak = streak + 1 if status in ENDED else 0
        if streak >= 2:
            return True
        if clock() >= deadline:
            return False
        sleep(poll)


def claude_pane(tmux, sess):
    for line in tmux("list-windows", "-t", f"={sess}", "-F", f"#{{window_name}}{SEP}#{{window_index}}", check=True).splitlines():
        name, _, idx = line.partition(SEP)
        if name == "claude":
            return tmux("list-panes", "-t", f"={sess}:{idx}", "-F", "#{pane_id}", check=True).splitlines()[0]
    return None


def _git_root(d):
    """d's main checkout, d itself when git answers "not a repo", or None when git could not run (missing, hung)."""
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) < 2 or not lines[0].strip():
        return d
    common, top = lines[0].strip(), lines[1].strip()
    home = os.environ.get("HOME", "")
    # ~ is itself a git repo: a plain folder under it must not resolve to ~ (bin/dev's rule). Compare the toplevel,
    # not the common dir's parent: a linked worktree of the ~ repo has its own toplevel and still maps to ~.
    if home and os.path.realpath(top) == os.path.realpath(home) and os.path.realpath(d) != os.path.realpath(home):
        return d
    return str(Path(common).parent)


def main_checkout(d):
    """d's project main checkout: a worktree maps to the repo that owns it; a non-git dir, a plain folder under ~,
    and a dir where git cannot run stay as is."""
    root = _git_root(d)
    return d if root is None else root


# start path -> (has its own .git, main checkout). A plain folder inside a parent repo changes when it is
# `git init`ed, so an entry is recomputed when the .git stat differs. A failure to run git is never cached.
_roots = {}


def root_for(start_path):
    """The project's main checkout for a session started in start_path: that dir, else $HOME, else Path.home().

    A path that is empty or no longer a directory (a removed worktree) is skipped and its cache entry dropped.
    """
    for d in (start_path, os.environ.get("HOME", "")):
        if d and os.path.isdir(d):
            has_git = os.path.exists(os.path.join(d, ".git"))
            hit = _roots.get(d)
            if hit is not None and hit[0] == has_git:
                return hit[1]
            root = _git_root(d)
            if root is None:
                return d
            _roots[d] = (has_git, root)
            return root
        _roots.pop(d, None)
    return str(Path.home())


def session_root(tmux, sess):
    """Where the new lead starts: the project's main checkout, never a worktree (auto-cleanup may remove it).
    The claude pane's current path is not used: Claude Code follows the lead's cd."""
    return root_for(tmux("display", "-p", "-t", f"={sess}:", "#{session_path}").strip())


def orchestrator():
    """The lead's launcher by absolute path: on a fresh install only ~/.local/bin/agent-board is linked, so <repo>/bin is not on PATH."""
    repo = os.environ.get("AGENT_BOARD_REPO") or str(Path(__file__).resolve().parent.parent)
    return str(Path(repo) / "bin" / "claude-orchestrator")


def respawn(tmux, pane, root, prompt=None):
    """Replace whatever runs in pane with a fresh shell in root, then start claude-orchestrator [prompt]."""
    tmux("respawn-pane", "-k", "-t", pane, "-c", root, check=True)  # no command: fresh default shell
    cmd = shlex.quote(orchestrator()) + (f" {shlex.quote(prompt)}" if prompt else "")
    tmux("send-keys", "-t", pane, "-l", "--", cmd, check=True)
    tmux("send-keys", "-t", pane, "Enter", check=True)


def relay(tmux, sess, doc, state_dir, old_session_id="", **wait):
    pane = claude_pane(tmux, sess)
    if pane is None:
        raise RuntimeError(f"no claude window in {sess}")
    if not wait_turn_end(tmux, pane, **wait):
        raise RuntimeError("the lead is still busy after the wait; not switching. Run tmux-ctl relay again when it is idle")
    respawn(tmux, pane, session_root(tmux, sess), prompt_for(doc))
    lin = tc_env.lineage_dir()   # persistent state; state_dir no longer decides the path
    lin.mkdir(parents=True, exist_ok=True)
    with open(lin / f"{sess}.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "old_session_id": old_session_id, "doc": str(doc), "pane": pane}) + "\n")
    return f"relayed {sess}:claude to a fresh orchestrator with {doc}"


def default_state():
    return str(tc_env.state_dir())


def main(argv=None):
    ap = argparse.ArgumentParser(description="hand the claude window to a fresh orchestrator")
    ap.add_argument("--session", required=True)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--old-session", default="")
    ap.add_argument("--state", default=default_state())
    ap.add_argument("--socket", default="")
    a = ap.parse_args(argv)
    tmux = paneclass.tmux_runner(["-S", a.socket] if a.socket else [])
    try:
        print(relay(tmux, a.session, a.doc, a.state, a.old_session))
        return 0
    except Exception as e:
        print(f"relay failed: {e}\nThe old session is untouched. Start the new lead by hand in the claude window:\n"
              f"  {shlex.quote(orchestrator())} {shlex.quote(prompt_for(a.doc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
