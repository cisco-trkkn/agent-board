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


START_CAP = 30.0   # seconds a relayed lead has to start before the attempt counts as failed


def launch_line(root, prompt=None):
    """The line typed into the fresh shell: cd to root first, then the launcher. The cd repairs a shell left in a
    gone directory (Claude Code refuses to start there) and fails loudly when root itself is gone."""
    cmd = shlex.quote(orchestrator()) + (f" {shlex.quote(prompt)}" if prompt else "")
    return f"cd -- {shlex.quote(root)} && {cmd}"


def login_shell(tmux):
    """What tmux itself runs for a new window: the global default-shell, else $SHELL, else /bin/sh."""
    out = tmux("show-options", "-gv", "default-shell").strip()
    return out if out.startswith("/") else (os.environ.get("SHELL") or "/bin/sh")


def respawn(tmux, pane, root, prompt=None):
    """Replace whatever runs in pane with a fresh login shell in root, then start claude-orchestrator [prompt].
    The shell is passed explicitly: respawn-pane without a command re-runs the pane's original start command."""
    tmux("respawn-pane", "-k", "-t", pane, "-c", root, login_shell(tmux), "-l", check=True)
    tmux("send-keys", "-t", pane, "-l", "--", launch_line(root, prompt), check=True)
    tmux("send-keys", "-t", pane, "Enter", check=True)


def wait_started(tmux, pane, poll=2.0, cap=START_CAP, sleep=time.sleep, clock=time.monotonic):
    """True once the pane's foreground is not a shell on two polls in a row; False when cap passes first.
    "Not a shell", not "is claude": tmux names a running claude by its version binary, and a claude that dies at
    startup leaves the shell in front."""
    deadline = clock() + cap
    streak = 0
    while True:
        sleep(poll)
        kind, _ = paneclass.pane_status(tmux, pane)
        streak = streak + 1 if kind != "shell" else 0
        if streak >= 2:
            return True
        if clock() >= deadline:
            return False


def pane_tail(tmux, pane, n=12):
    """The pane's last n non-blank lines, each prefixed '| ' (the log's manual: line stays the only unprefixed one)."""
    rows = [r.rstrip() for r in tmux("capture-pane", "-p", "-J", "-t", pane, "-S", "-60").splitlines()]
    return "\n".join("| " + r for r in [r for r in rows if r.strip()][-n:])


def relay(tmux, sess, doc, state_dir, old_session_id="", attempts=2, start_cap=START_CAP, **wait):
    pane = claude_pane(tmux, sess)
    if pane is None:
        raise RuntimeError(f"no claude window in {sess}")
    if not wait_turn_end(tmux, pane, **wait):
        raise RuntimeError("the lead is still busy after the wait; not switching. Run tmux-ctl relay again when it is idle")
    root = session_root(tmux, sess)
    timing = {k: wait[k] for k in ("sleep", "clock") if k in wait}
    shown = ""
    for n in range(1, attempts + 1):
        respawn(tmux, pane, root, prompt_for(doc))
        if wait_started(tmux, pane, cap=start_cap, **timing):
            break
        shown = pane_tail(tmux, pane)
        print(f"relay: attempt {n}: the new lead did not start in {root}; the pane shows:\n{shown}", file=sys.stderr)
    else:
        raise RuntimeError(f"the new lead did not start in {root} after {attempts} attempts; the pane shows:\n{shown}")
    lin = tc_env.lineage_dir()   # persistent state; state_dir no longer decides the path
    lin.mkdir(parents=True, exist_ok=True)
    with open(lin / f"{sess}.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "old_session_id": old_session_id, "doc": str(doc), "pane": pane}) + "\n")
    return f"relayed {sess}:claude to a fresh orchestrator with {doc}"


class LeadRestartError(RuntimeError):
    pass


def lead_pane(tmux, project):
    """(session, pane id, window name) of the project's lead, or None. The session is a real, non-bg one: the project
    key may be a group name that list-windows cannot target. R3: window `claude`, else `claude-next`."""
    rows = [l.split(SEP) for l in tmux("list-sessions", "-F", f"#{{session_name}}{SEP}#{{session_group}}{SEP}#{{@tc_bg}}").splitlines()]
    live = [r for r in rows if len(r) == 3 and not r[2]]
    names = [r[0] for r in live if r[0] == project] + [r[0] for r in live if r[1] == project and r[0] != project]
    for sess in names:
        try:
            wins = [l.split(SEP) for l in tmux("list-windows", "-t", f"={sess}", "-F", f"#{{window_name}}{SEP}#{{window_id}}{SEP}#{{pane_id}}", check=True).splitlines()]
        except RuntimeError:
            continue
        for want in ("claude", "claude-next"):
            for w in wins:
                if len(w) == 3 and w[0] == want:
                    return sess, w[2], want
    return None


def session_for_pane(pane, home, state):
    """R6: the newest ~/.claude/sessions/*.json entry whose tmux field ends with .<pane>, else a fresh agent-status record of the pane, else ''."""
    best = (-1, "")
    for f in sorted((Path(home) / "sessions").glob("*.json")):
        try:
            e = json.loads(f.read_text())
            if str(e.get("tmux", "")).endswith("." + pane) and e.get("sessionId"):
                upd = e.get("updatedAt") or 0
                if upd > best[0]:
                    best = (upd, str(e["sessionId"]))
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    if best[1]:
        return best[1]
    rec = paneclass.mod_records(d=Path(state) / "agent-status").get(pane)
    return str(rec.get("session_id") or "") if rec else ""


def newest_handoff(root, handoffs):
    """The newest handoffs/*.md (not drafts/) whose first line is `Project: <root>`, or None."""
    best = (-1.0, None)
    try:
        names = sorted(os.listdir(handoffs))
    except OSError:
        return None
    for n in names:
        p = os.path.join(handoffs, n)
        if not n.endswith(".md") or not os.path.isfile(p):
            continue
        try:
            with open(p, errors="replace") as f:
                first = f.readline().rstrip("\r\n")
            m = os.path.getmtime(p)
        except OSError:
            continue
        if first == f"Project: {root}" and m > best[0]:
            best = (m, p)
    return best[1]


LEAD_START_CAP = 60.0


def pane_has_child(tmux, pane):
    """True when the pane's own process has a child. R4's pane command is `<orchestrator>; exec <shell> -l`: tmux then
    reports the zsh -c wrapper (the foreground process group's leader) as the pane command for the whole run, so
    wait_started's "not a shell" never sees the lead. The orchestrator is that wrapper's child; a start that failed
    has already exec'd the login shell, which has none."""
    pid = tmux("display", "-p", "-t", pane, "#{pane_pid}").strip()
    if not pid.isdigit():
        return False
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(len(r.split()) == 2 and r.split()[1] == pid for r in out.splitlines())


def wait_lead_started(tmux, pane, poll=2.0, cap=LEAD_START_CAP, sleep=time.sleep, clock=time.monotonic):
    """True once pane_has_child holds on two polls in a row; False when cap passes first."""
    deadline = clock() + cap
    streak = 0
    while True:
        sleep(poll)
        streak = streak + 1 if pane_has_child(tmux, pane) else 0
        if streak >= 2:
            return True
        if clock() >= deadline:
            return False


def restart_lead(tmux, project, resume=False, doc=None, home=None, state=None, handoffs=None, **timing):
    """Restart the project's lead pane (spec §2, R3 R4 R6). Everything is checked before anything changes; the respawn
    command is the pane's own command and ends in a login shell, so the window survives claude's exit. Nothing is typed."""
    if resume and doc:
        raise LeadRestartError("usage: lead-restart <project> [--resume | --doc <handoff>]")
    found = lead_pane(tmux, project)
    if found is None:
        raise LeadRestartError(f"no lead pane for {project}")
    sess, pane, win = found
    root = os.path.realpath(session_root(tmux, sess))
    if resume:
        sid = session_for_pane(pane, home or os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude"), state or default_state())
        if not sid:
            raise LeadRestartError(f"no session id for {project}'s lead pane {pane}: cannot --resume")
        args, what = f"--resume {shlex.quote(sid)}", f"resume {sid}"
    else:
        d = doc or newest_handoff(root, handoffs or str(tc_env.agent_base() / "handoffs"))
        if not d:
            raise LeadRestartError(f"no handoff doc for {root}: pass --doc <file> or --resume")
        if not os.path.isfile(d):
            raise LeadRestartError(f"no handoff doc '{d}'")
        args, what = shlex.quote(prompt_for(d)), f"doc {os.path.basename(d)}"
    if win == "claude-next":
        tmux("rename-window", "-t", pane, "claude", check=True)
    shell = os.environ.get("SHELL") or "/bin/zsh"
    tmux("respawn-pane", "-k", "-t", pane, "-c", root, f"{shlex.quote(orchestrator())} {args}; exec {shlex.quote(shell)} -l", check=True)
    if not wait_lead_started(tmux, pane, cap=LEAD_START_CAP, **timing):
        raise LeadRestartError(f"the new lead did not start in {root}; the pane shows:\n{pane_tail(tmux, pane)}")
    return {"project": project, "pane": pane, "what": what}


def lead_main(argv):
    ap = argparse.ArgumentParser(prog="relay.py lead-restart")
    ap.add_argument("project")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--doc", default=None)
    ap.add_argument("--socket", default="")
    a = ap.parse_args(argv)
    tmux = paneclass.tmux_runner(["-S", a.socket] if a.socket else [])
    try:
        r = restart_lead(tmux, a.project, resume=a.resume, doc=a.doc)
    except LeadRestartError as e:
        print(f"lead-restart: {e}", file=sys.stderr)
        return 1
    print(f"lead-restart: {r['project']} restarted ({r['what']})")
    print(f"pane {r['pane']}")
    return 0


def default_state():
    return str(tc_env.state_dir())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["lead-restart"]:
        return lead_main(argv[1:])
    ap = argparse.ArgumentParser(description="hand the claude window to a fresh orchestrator")
    ap.add_argument("--session", required=True)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--old-session", default="")
    ap.add_argument("--state", default=default_state())
    ap.add_argument("--socket", default="")
    ap.add_argument("--start-cap", type=float, default=START_CAP, help=argparse.SUPPRESS)   # test knob
    a = ap.parse_args(argv)
    tmux = paneclass.tmux_runner(["-S", a.socket] if a.socket else [])
    try:
        print(relay(tmux, a.session, a.doc, a.state, a.old_session, start_cap=a.start_cap))
        return 0
    except Exception as e:
        # last resort: the root is unknown, so the manual line cannot cd to it
        try:
            root = session_root(tmux, a.session)
        except Exception:
            root = None
        manual = launch_line(root, prompt_for(a.doc)) if root else f"{shlex.quote(orchestrator())} {shlex.quote(prompt_for(a.doc))}"
        print(f"relay failed: {e}\nStart the new lead by hand in the claude window:\nmanual: {manual}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
