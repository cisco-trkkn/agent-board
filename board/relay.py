#!/usr/bin/env python3
"""relay: hand a dev session's `claude` window to a fresh orchestrator, in place.

  relay.py --session S --doc D [--old-session ID] [--state DIR] [--socket PATH]

Waits until the lead's turn has ended (paneclass says idle/ready on two polls in a row, 2s apart,
120s cap), respawns the pane with `claude-orchestrator "Read <doc> ..."`, and appends
{ts, old_session_id, doc, pane} to <state>/lineage-<session>.jsonl. The board's
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


def main_checkout(d):
    """d's project main checkout: a worktree maps to the repo that owns it; a non-git dir stays as is."""
    r = subprocess.run(["git", "-C", d, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    common = r.stdout.strip()
    if r.returncode != 0 or not common:
        return d
    return str(Path(common).parent)


def session_root(tmux, sess, pane=None):
    """Where the new lead starts: the project's main checkout, never a worktree (auto-cleanup may remove it).

    Candidates in order: the claude pane's current path, the session's start path, $HOME. A path that is
    empty or no longer a directory (a removed worktree) is skipped.
    """
    if pane is None:
        pane = claude_pane(tmux, sess)
    cands = []
    if pane:
        cands.append(tmux("display", "-p", "-t", pane, "#{pane_current_path}").strip())
    cands.append(tmux("display", "-p", "-t", f"={sess}:", "#{session_path}").strip())
    cands.append(os.environ.get("HOME", ""))
    for d in cands:
        if d and os.path.isdir(d):
            return main_checkout(d)
    return str(Path.home())


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
    respawn(tmux, pane, session_root(tmux, sess, pane), prompt_for(doc))
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(state_dir) / f"lineage-{sess}.jsonl", "a") as f:
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
