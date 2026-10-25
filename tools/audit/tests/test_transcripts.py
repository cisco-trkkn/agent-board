"""Tests for tools/audit/transcripts.py.

Real transcript format, observed 2026-10-25 over ~/.claude/projects (agent-board: 61 files):
  line types: assistant, user, attachment, system, api-request*, last-prompt, mode, permission-mode, ...
  system subtypes (all projects): stop_hook_summary, turn_duration, away_summary, api_error,
    local_command, informational.  NO subtype marks compaction in the real data: no `compact_boundary`
    line exists in any transcript.  Task 5 must detect compaction/handoff from other evidence (user text,
    `isCompactSummary` is also absent); do not key on a system subtype.
  attachment types (agent-board): total_tokens_reminder, deferred_tools_record, hook_success, task_reminder,
    bash_output_audience_note, batching_reminder_sent, environment, command_permissions, prompt_snapshot,
    mcp_instructions_delta, deferred_tools_delta, silent_turn_reminder, hook_additional_context, date,
    skill_listing, model, agent_listing_delta, session_context, credential_org, remote_session_change,
    instructions, queued_command, auto_mode, hook_system_message, edited_text_file, team_context,
    skill_mention, nested_memory.
  Hook attachments carry `hookEvent` (e.g. SessionStart); stop_hook_summary carries `hookInfos`
    (list of {command, durationMs}) and `hookAdditionalContext` (list).
  Subagents: <session>/subagents/agent-<id>.jsonl plus agent-<id>.meta.json.
"""
import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import transcripts as T

def write(dirpath, name, lines, partial_tail=None):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "w") as fh:
        for l in lines: fh.write(json.dumps(l) + "\n")
        if partial_tail: fh.write(partial_tail)
    return p

def asst(req, cwd, inp=1, out=2, ts="2026-10-20T10:00:00Z", **kw):
    d = {"type": "assistant", "requestId": req, "cwd": cwd, "sessionId": "s1", "timestamp": ts,
         "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": inp, "output_tokens": out,
                     "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                     "content": [{"type": "text", "text": "hi"}]}}
    d.update(kw); return d

class Synthetic(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.repo = "/r/repo"
        self.proj = os.path.join(self.root, "-r-repo")

    def events(self, kind=None):
        ev = list(T.iter_events(self.root, [self.repo], days=3650))
        return [e for e in ev if kind is None or e["kind"] == kind]

    def test_duplicate_request_ids_count_once_latest_wins(self):
        write(self.proj, "s1.jsonl", [asst("r1", self.repo, out=1), asst("r1", self.repo, out=9)])
        u = self.events("usage")
        self.assertEqual(len(u), 1); self.assertEqual(u[0]["output"], 9)

    def test_partial_last_line_skipped(self):
        write(self.proj, "s1.jsonl", [asst("r1", self.repo)], partial_tail='{"type":"assistant"')
        self.assertEqual(len(self.events("usage")), 1)

    def test_out_of_scope_cwd_ignored_worktree_included(self):
        write(self.proj, "s1.jsonl", [asst("r1", "/other"), asst("r2", self.repo + "/.claude/worktrees/x")])
        self.assertEqual([e["request_id"] for e in self.events("usage")], ["r2"])

    def test_subagent_file_gets_sub_agent_id(self):
        write(os.path.join(self.proj, "s1", "subagents"), "agent-abc.jsonl", [asst("r3", self.repo)])
        self.assertEqual(self.events("usage")[0]["agent"], "sub:abc")

    def test_teammate_line_gets_team_agent_id(self):
        write(self.proj, "s1.jsonl", [asst("r4", self.repo, agentName="atlas")])
        self.assertEqual(self.events("usage")[0]["agent"], "team:atlas")

    def test_tool_use_and_result(self):
        a = asst("r5", self.repo)
        a["message"]["content"] = [{"type": "tool_use", "id": "t1", "name": "Read",
                                    "input": {"file_path": "/r/repo/x.py"}}]
        u = {"type": "user", "cwd": self.repo, "sessionId": "s1", "timestamp": "2026-10-20T10:00:01Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "abcd", "is_error": False}]}}
        write(self.proj, "s1.jsonl", [a, u])
        tu = self.events("tool_use")[0]; tr = self.events("tool_result")[0]
        self.assertEqual((tu["tool"], tu["target"], len(tu["args_key"])), ("Read", "/r/repo/x.py", 12))
        self.assertEqual((tr["tool_use_id"], tr["size"], tr["is_error"]), ("t1", 4, False))

class Fixtures(unittest.TestCase):
    def test_fixtures_parse_and_have_usage(self):
        fx = os.path.join(HERE, "fixtures")
        ev = list(T.iter_events(fx, None, days=None))   # repos=None, days=None: no scope filter
        self.assertTrue(any(e["kind"] == "usage" for e in ev))
        self.assertTrue(any(e["agent"].startswith("sub:") for e in ev))
        self.assertTrue(any(e["kind"] == "system" for e in ev))

class RealState(unittest.TestCase):
    def test_real_reconciles_with_usage_sum(self):
        # Live transcripts grow while the test runs (this very session writes to them), so both tools read
        # one frozen copy of the agent-board project dirs (mtimes preserved: both order files by mtime).
        import glob, shutil
        repo = "/Users/francisco.ruiz/agent-board"
        tools = os.path.dirname(os.path.dirname(HERE))
        real = os.path.expanduser("~/.claude/projects")
        with tempfile.TemporaryDirectory() as snap:
            for d in glob.glob(os.path.join(real, "-Users-francisco-ruiz-agent-board*")):
                shutil.copytree(d, os.path.join(snap, os.path.basename(d)))   # copytree keeps mtimes (copy2)
            out = subprocess.run([sys.executable, os.path.join(tools, "usage-sum.py"), "--repo", repo, "--days", "30",
                                  "--root", snap], capture_output=True, text=True, check=True).stdout
            calls = int(out.split("calls=")[1].split()[0])
            n = sum(1 for e in T.iter_events(snap, [repo], days=30) if e["kind"] == "usage")
        self.assertGreater(calls, 0)
        self.assertEqual(n, calls)

if __name__ == "__main__":
    unittest.main()
