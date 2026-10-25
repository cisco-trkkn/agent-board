#!/usr/bin/env python3
"""What always-on and injected text costs per session, by source.

usage: injection_costs.py --root R --repo P [--repo P2] --days N --out F [--board-repo B]

Output {"sources", "first_request_prompt_tokens", "static_files"}.
  sources: per injection.source -> sessions seen, total_chars, median_chars_per_session, count_per_session
    (by_session / median / max). An `attachment:hook_additional_context` event with a hook_event is reported as
    `hook:<hook_event>`; without one it stays `attachment:hook_additional_context`; stop_hook_summary events are
    `hook:unknown` (their hookInfos carry no event name). `claude-md` is never emitted as an injection event:
    CLAUDE.md cost comes from static_files only.
  first_request_prompt_tokens: per session, the earliest main request's input + cache_read + cache_creation
    (measured); a session with no main request (teammate session) uses its earliest team:<name> request and says
    so in `agent`; a session with only subagent requests is null with value_reason.
  static_files: char size read from disk now (measured) with tokens_estimate = chars / 4 (derived):
    ~/.claude/CLAUDE.md, <repo>/CLAUDE.md for each --repo, and the orchestrator prompt.
    Orchestrator prompt source (bin/claude-orchestrator, `--append-system-prompt-file`): the user override
    ~/.config/agent-board/orchestrator.md if readable, else <board-repo>/claude/orchestrator.md (the only file;
    no addendum). Teammates additionally get worker.md (bin/tmux-ctl: override ~/.config/agent-board/worker.md,
    else <board-repo>/claude/worker.md); it is listed too. Every path actually used is recorded in the output.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcripts as T

BOARD_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _source(e):
    if e["source"] == "attachment:hook_additional_context" and e.get("hook_event"):
        return "hook:%s" % e["hook_event"]
    return e["source"]


def _median(v):
    return float(statistics.median(v))


def costs(events):
    per = {}      # source -> session -> [chars...]
    first = {}    # session -> {"main": usage, "team": usage}
    sessions = set()
    for e in events:
        sessions.add(e["session"])
        if e["kind"] == "injection":
            per.setdefault(_source(e), {}).setdefault(e["session"], []).append(e["size"])
        elif e["kind"] == "usage":
            k = "main" if e["agent"] == "main" else "team" if e["agent"].startswith("team:") else None
            if k:
                cur = first.setdefault(e["session"], {}).get(k)
                if cur is None or (e["ts"] is not None and (cur["ts"] is None or e["ts"] < cur["ts"])):
                    first[e["session"]][k] = e
    sources = {}
    for src, by in sorted(per.items()):
        counts = {s: len(v) for s, v in by.items()}
        sources[src] = {
            "sessions": len(by),
            "total_chars": sum(sum(v) for v in by.values()),
            "median_chars_per_session": _median([sum(v) for v in by.values()]),
            "count_per_session": {"by_session": counts, "median": _median(counts.values()), "max": max(counts.values())},
            "source": "measured",
        }
    firsts = []
    for s in sorted(sessions):
        u = first.get(s, {}).get("main") or first.get(s, {}).get("team")
        if u is None:
            firsts.append({"session": s, "agent": None, "value": None,
                           "value_reason": "no main or team request in session", "source": "measured"})
        else:
            firsts.append({"session": s, "agent": u["agent"], "value": u["input"] + u["cache_read"] + u["cache_creation"],
                           "source": "measured"})
    return {"sources": sources, "first_request_prompt_tokens": firsts}


def static_files(paths):
    out = []
    for label, p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                n = len(fh.read())
            out.append({"label": label, "path": p, "chars": n, "source": "measured",
                        "tokens_estimate": {"value": n / 4, "source": "derived"}})
        except OSError as ex:
            out.append({"label": label, "path": p, "chars": None, "chars_reason": "unreadable: %s" % ex.strerror,
                        "source": "measured"})
    return out


def _prompt_path(name, board_repo):
    override = os.path.expanduser("~/.config/agent-board/%s" % name)
    return override if os.access(override, os.R_OK) else os.path.join(board_repo, "claude", name)


def static_paths(repos, board_repo):
    paths = [("user-claude-md", os.path.expanduser("~/.claude/CLAUDE.md"))]
    paths += [("repo-claude-md", os.path.join(r, "CLAUDE.md")) for r in repos]
    paths += [("orchestrator-prompt", _prompt_path("orchestrator.md", board_repo)),
              ("worker-prompt", _prompt_path("worker.md", board_repo))]
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--board-repo", default=BOARD_REPO)
    a = ap.parse_args(argv)
    res = costs(T.iter_events(a.root, a.repo, a.days))
    res["static_files"] = static_files(static_paths(a.repo, a.board_repo))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
