# Remote lead liveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the phone the user sees, as one reaction on their newest Discord message, whether the lead got, read and answered it (❓ gives one status line on demand); a successor lead started by a relay or `lead-restart` stays remote; and a project bot's `/ideas` covers only its own project.

**Architecture:** The board writes `lead-state.json` per bridged project on every overview build (new `board/lead_state.py`, called from `board/server.py`), from the overview record, the bot holder lookup and a cached tail read of the lead's transcript. The Discord bridge (a separate node process) tracks the newest allowlisted home-channel message, records its time in `last-user-message.json`, and every 10 s picks one liveness reaction with the pure `lib/liveness.js`; reaction swaps and the ❓ reply line go through the bridge's own outbox. `board/relay.py` copies the remote marker to the successor's session id, and `remote-ask-guard.sh` treats a lead without a marker as remote when the bridge saw the user within 12 h and no terminal prompt is newer.

**Tech Stack:** Python 3 standard library (`board/`, unittest), Node >= 22 (`node:test`, discord.js 14 only at runtime), zsh test harness (`tools/tests/lib.zsh`), bash + embedded Python hook.

**Spec:** `docs/superpowers/specs/2026-11-23-remote-lead-liveness-design.md`

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-23-remote-lead-liveness-design.md",
 "base": "0af42b5b388826b46ecd25063192c9d2f558f87d",
 "depends_on": [],
 "writes": [
  {"path": "board/lead_state.py", "mode": "create"},
  {"path": "board/tests/test_lead_state.py", "mode": "create"},
  {"path": "board/server.py", "mode": "modify"},
  {"path": "board/tests/test_lead_state_wiring.py", "mode": "create"},
  {"path": "tools/discord-bridge/lib/liveness.js", "mode": "create"},
  {"path": "tools/discord-bridge/test/liveness.test.js", "mode": "create"},
  {"path": "tools/discord-bridge/bridge.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/fake-client.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/liveness-bridge.test.js", "mode": "create"},
  {"path": "tools/discord-bridge/lib/commands.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/commands.test.js", "mode": "modify"},
  {"path": "board/discord_ops.py", "mode": "modify"},
  {"path": "board/tests/test_discord_ideas_wiring.py", "mode": "modify"},
  {"path": "board/relay.py", "mode": "modify"},
  {"path": "board/tests/test_relay.py", "mode": "modify"},
  {"path": "claude/plugin/scripts/remote-ask-guard.sh", "mode": "modify"},
  {"path": "tools/tests/test_remote_ask_guard.zsh", "mode": "modify"},
  {"path": "docs/ARCHITECTURE.md", "mode": "modify"}
 ],
 "reads": ["board/overview.py", "board/planview.py", "board/tc_env.py", "board/paneclass.py", "board/discord_ideas.py",
           "board/discord_controls.py", "board/discord_feed.py", "bin/tmux-ctl", "bin/claude-orchestrator",
           "tools/discord-bridge/lib/outbox.js", "tools/discord-bridge/lib/state.js", "tools/discord-bridge/test/bridge.test.js",
           "tools/tests/lib.zsh", "claude/plugin/scripts/remote-marker.sh"],
 "produces": ["lead-state.json", "last-user-message.json"],
 "consumes": [],
 "tests": ["board/tests/test_lead_state.py", "board/tests/test_lead_state_wiring.py", "tools/discord-bridge/test/liveness.test.js",
           "tools/discord-bridge/test/liveness-bridge.test.js", "tools/discord-bridge/test/commands.test.js",
           "board/tests/test_discord_ideas_wiring.py", "board/tests/test_relay.py", "tools/tests/test_remote_ask_guard.zsh"]}
```

## Global Constraints

- **Paths.** The spec's `$TC_STATE/discord/<project>` is `tc_env.discord_dir(project)` = `${TC_STATE:-~/.local/state/agent-board}/discord/<project>` (the bridge's own `dir`, the lead's `DISCORD_STATE_DIR`). The spec's `$TC_STATE/remote/<sid>` is the remote marker the guard already uses: `tc_env.state_dir()/remote/<sid>` = `${TC_STATE:-$TMPDIR/tmux-ctl-<uid>}/remote/<sid>` (`--state` in `relay.py`). Never mix the two bases.
- **`lead-state.json`** (written only by `board/lead_state.py`, atomically: unique temp file + `os.replace`):
  `{"at": ISO-Z, "state": "busy"|"ready"|"needs_you"|"down", "since": ISO-Z, "tool": str|null, "queued": int, "last_read_text": str|null, "last_read_message_id": str|null, "holder": bool, "reason": str|null, "window": "claude"}`.
  ISO-Z is `2026-11-24T21:40:00Z` (seconds, UTC, `Z`). Written only for a project whose discord dir holds `bridge.json`.
- **`last-user-message.json`** (written only by the bridge, atomically): `{"ts": ISO (JS toISOString), "message_id": "<snowflake>"}` for the newest home-channel message from an allowlisted user.
- **Reactions** (exact strings, `lib/liveness.js` `E`): 📨 posted, ⏳ busy, 👀 read, ✅ answered, 🙋 needs you, ⚠️ (`'⚠️'`) down. Precedence ⚠️, 🙋, ✅, 👀, ⏳, 📨. Stale = `at` more than 180 s old. The bridge evaluates at most every 10 s (`LIVE_MS = 10000`).
- **❓ reply lines** (exact): `busy 6m26s: <tool>; <n> message(s) queued` (no `: <tool>` when tool is null), `ready since HH:MM`, `needs you: a dialog is waiting in claude`, `down: <reason> since HH:MM`, `no lead state (board not running?)`.
- **Remote window:** 43200 s (12 h), the same constant the guard's peer rule uses.
- **Outbox ops added to the bridge** (written by the bridge itself into `<dir>/outbox/`, `<13-digit ms>-<8 hex>.json`, temp + rename, the same naming as `board/discord_feed.outbox_write`): `{"op": "liveness", "message_id", "add": emoji|null, "remove": emoji|null, "unreact": {"emoji", "user"}|null}` and `{"op": "liveness_reply", "text"}`.
- No model or network call in the board or guard path. The overview must not slow down: the transcript is read only from its last 1 MiB and only when its (size, mtime) changed.
- Commits: conventional with scope (`feat(board): …`, `feat(discord-bridge): …`, `fix(relay): …`, `docs(architecture): …`); end each commit message with the attribution trailer your harness specifies. Stage only the task's files (`git add <paths>`), commit with `git commit -- <paths>` semantics; never `git add -A`.
- zsh suites run with `env -u AGENT_BOARD_LEAD` (shared context: hook tests misread a lead shell).

**Assumptions (planner, not in the spec; the lead may overrule):**
- A1. "The transcript tail the usage index already parses" is implemented as a cached 1 MiB tail read of `<home>/projects/*/<sid>.jsonl`: the usage indexer keeps no row text, so there is nothing to reuse. The cache makes an unchanged transcript free.
- A2. `lead-state.json` carries three keys the spec does not list: `last_read_message_id` (the `message_id` attribute of the channel tag; a read match by id is exact where a text match is ambiguous for repeated short replies like "yes"), `reason` (for the `down: <reason>` line) and `window` (for the `needs you` line). The bridge still accepts a text match as the spec says.
- A3. `queued` = channel prompts enqueued and not yet dequeued, from the transcript's `queue-operation` rows (real rows: `enqueue` with `content`, `dequeue` FIFO, `remove` with the removed `content`, `popAll`); counts only contents holding `<channel source="plugin:discord:discord"`.
- A4. "The lead answered" = a message by the bot's own user id in the home channel, newer than the target, that the bridge did not send itself (its own sends are recorded in `st.own_sent`) and that is not an interaction response (`interactionMetadata`/`interaction` set). The lead's plugin and the bridge share one bot token, so author id alone cannot tell them apart.
- A5. The `tmux-ctl lead-restart` marker copy lives in `board/relay.py`'s `restart_lead`, which `lead-restart` calls; `bin/tmux-ctl` itself is unchanged.
- A6. The guard finds the project's discord dir from `DISCORD_STATE_DIR` (set for a lead that holds the bot), else from the tmux session of `TMUX_PANE` (the same rule as `bin/claude-orchestrator`: session group or name, `-bg` stripped) under `${TC_STATE:-~/.local/state/agent-board}/discord/`.
- A7. Removing the user's ❓ needs the bot's Manage Messages permission; without it the bridge logs one line and the reply still posts.
- A8. Threads are out of scope (spec): only messages whose `channel.id` is the home channel itself are tracked or answered.

**User decisions (already made):** scope a+b+c, d parked; liveness = one swapped state reaction on the latest message plus ❓ on demand; the board computes lead state and hands it to the bridge as a file, no model in the path (spec Decisions 1-3, user on Discord 2026-11-23).

---

### Task 1: lead_state module (board)

**Goal:** `board/lead_state.py` computes and atomically writes `lead-state.json` for each bridged project from an overview record, the holder flag and the lead transcript's tail.

**Files:**
- Create: `board/lead_state.py`
- Test: `board/tests/test_lead_state.py`

**Acceptance Criteria:**
- [ ] Each `state` from fixed records: working → busy, ready → ready, waiting → needs_you, missing → down, holder false → down (with `reason` "bot not held").
- [ ] `since` is kept across writes while `state` is unchanged and reset when it changes.
- [ ] `last_read_text` / `last_read_message_id` come from the newest non-sidechain channel user row of a fixture transcript, trimmed and cut to 200 chars.
- [ ] `queued` counts pending channel enqueues only (dequeue FIFO, remove by content, popAll clears).
- [ ] Atomic write: exactly one `os.replace`, no temp file left; no file for a project without `bridge.json`; one failing project does not stop the next.
- [ ] An unchanged transcript is not read twice (cache by size and mtime); only the last 1 MiB is read.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_lead_state.py' -v` → `OK`, 15 tests

**Steps:**

- [ ] **Step 1: Write the failing test** — create `board/tests/test_lead_state.py` with exactly this content. Rows copy the shapes of real lead transcript rows (`038623a9…`, 2026-11-17), ids and text replaced. Mutations are named next to the guard tests.

```python
"""lead_state: the per-project lead-state.json (spec 2026-11-23-remote-lead-liveness §1). Scratch TC_STATE.
Transcript rows copy the shape of real lead transcript rows (038623a9, 2026-11-17): a channel user row with
origin {kind: channel, server: plugin:discord:discord} and queue-operation enqueue/dequeue/remove/popAll rows; ids and text replaced."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lead_state  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0


def rec(status="ready", tool=None, project="alpha"):
    return {"project": project, "lead": {"status": status}, "needs_you": [],
            "agents": [{"window": "claude", "pane": "%1", "tool": tool}]}


def chan(text, mid="m1"):
    return {"type": "user", "isSidechain": False, "isMeta": True, "origin": {"kind": "channel", "server": "plugin:discord:discord"},
            "message": {"role": "user", "content": f'<channel source="plugin:discord:discord" chat_id="C1" message_id="{mid}" user="u" user_id="U1" ts="2026-11-24T21:00:00.000Z">\n{text}\n</channel>'}}


def q(op, content=None):
    r = {"type": "queue-operation", "operation": op, "timestamp": "2026-11-24T21:00:00Z", "sessionId": "s1"}
    if content is not None:
        r["content"] = content
    return r


CH = lambda t, mid="m9": chan(t, mid)["message"]["content"]   # noqa: E731


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        lead_state._cache.clear()
        lead_state._paths.clear()
        self.home = Path(self.tmp.name) / "home"
        self.d = tc_env.discord_dir("alpha")
        self.d.mkdir(parents=True)
        (self.d / "bridge.json").write_text(json.dumps({"channel": "C1"}))

    def transcript(self, rows, sid="s1"):
        f = self.home / "projects" / "-x" / f"{sid}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return f

    def tick(self, records, now=NOW, holder=True, sid="s1"):
        lead_state.tick(records, now, holder_of=lambda p: holder, sid_of=lambda p: sid, home=self.home)

    def state(self, project="alpha"):
        return json.loads((tc_env.discord_dir(project) / "lead-state.json").read_text())


class States(Base):
    def test_each_state(self):
        for status, holder, want in [("working", True, "busy"), ("ready", True, "ready"), ("waiting", True, "needs_you"),
                                     ("missing", True, "down"), ("ready", False, "down")]:
            with self.subTest(status=status, holder=holder):
                self.tick([rec(status)], holder=holder)
                self.assertEqual(self.state()["state"], want)

    def test_down_reasons(self):   # mutation: holder checked before the missing lead -> the first reason is "bot not held"
        self.tick([rec("missing")], holder=False)
        self.assertEqual(self.state()["reason"], "no claude in the lead window")
        self.tick([rec("ready")], holder=False)
        self.assertEqual(self.state()["reason"], "bot not held")
        self.assertIs(self.state()["holder"], False)

    def test_tool_only_while_busy(self):
        self.tick([rec("working", tool="Bash: npm test")])
        self.assertEqual(self.state()["tool"], "Bash: npm test")
        self.tick([rec("ready", tool="Bash: npm test")])
        self.assertIsNone(self.state()["tool"])

    def test_since_kept_across_writes_and_reset_on_change(self):   # mutation: since = iso(now) always -> fails
        self.tick([rec("working")], now=NOW)
        self.tick([rec("working")], now=NOW + 30)
        s = self.state()
        self.assertEqual(s["since"], lead_state.iso(NOW))
        self.assertEqual(s["at"], lead_state.iso(NOW + 30))
        self.tick([rec("ready")], now=NOW + 60)
        self.assertEqual(self.state()["since"], lead_state.iso(NOW + 60))

    def test_no_file_without_bridge_json(self):
        tc_env.discord_dir("beta").mkdir(parents=True)
        self.tick([rec(project="beta")])
        self.assertFalse((tc_env.discord_dir("beta") / "lead-state.json").exists())

    def test_one_failing_project_does_not_stop_the_next(self):
        def holder(p):
            if p == "alpha":
                raise RuntimeError("boom")
            return True
        tc_env.discord_dir("gamma").mkdir(parents=True)
        (tc_env.discord_dir("gamma") / "bridge.json").write_text("{}")
        lead_state.tick([rec(project="alpha"), rec(project="gamma")], NOW, holder_of=holder, sid_of=lambda p: "", home=self.home)
        self.assertEqual(self.state("gamma")["state"], "ready")

    def test_atomic_write_leaves_no_temp_file(self):   # mutation: write straight to the target path -> a replace never happens
        with mock.patch.object(lead_state.os, "replace", wraps=os.replace) as rp:
            self.tick([rec()])
        self.assertEqual(rp.call_count, 1)
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["bridge.json", "lead-state.json"])


class Transcript(Base):
    def test_last_read_text_and_id_from_the_newest_channel_row(self):
        self.transcript([chan("first", "m1"), {"type": "user", "origin": {"kind": "human"}, "message": {"content": "typed"}},
                         chan("  deploy it?  ", "m2")])
        self.tick([rec()])
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("deploy it?", "m2"))

    def test_text_cut_to_200(self):
        self.transcript([chan("x" * 300)])
        self.tick([rec()])
        self.assertEqual(self.state()["last_read_text"], "x" * 200)

    def test_sidechain_rows_ignored(self):
        self.transcript([chan("main", "m1"), dict(chan("side", "m2"), isSidechain=True)])
        self.tick([rec()])
        self.assertEqual(self.state()["last_read_text"], "main")

    def test_no_transcript_no_channel_row(self):
        self.tick([rec()], sid="")
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"], s["queued"]), (None, None, 0))

    def test_queued_counts_pending_channel_enqueues(self):
        # 3 channel enqueues, a teammate enqueue; one dequeue (FIFO: the first channel one), one remove of the third
        self.transcript([q("enqueue", CH("a", "m1")), q("enqueue", "<teammate-message>x</teammate-message>"),
                         q("enqueue", CH("b", "m2")), q("enqueue", CH("c", "m3")), q("dequeue"), q("remove", CH("c", "m3"))])
        self.tick([rec("working")])
        self.assertEqual(self.state()["queued"], 1)   # mutation: count every pending enqueue -> 2

    def test_pop_all_clears(self):
        self.transcript([q("enqueue", CH("a")), q("enqueue", CH("b")), q("popAll", "x")])
        self.tick([rec("working")])
        self.assertEqual(self.state()["queued"], 0)

    def test_unchanged_transcript_is_not_read_again(self):   # mutation: drop the cache check -> _tail_lines runs twice
        self.transcript([chan("hi")])
        with mock.patch.object(lead_state, "_tail_lines", wraps=lead_state._tail_lines) as tl:
            self.tick([rec()])
            self.tick([rec()], now=NOW + 10)
        self.assertEqual(tl.call_count, 1)

    def test_tail_only(self):   # a channel row before the last TAIL bytes is not seen
        f = self.transcript([chan("old", "m1")])
        with open(f, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "pad": "y" * (lead_state.TAIL + 10)}) + "\n")
        self.tick([rec()])
        self.assertIsNone(self.state()["last_read_text"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 -m unittest discover -s board/tests -p 'test_lead_state.py'`
Expected: `ModuleNotFoundError: No module named 'lead_state'`.

- [ ] **Step 3: Write the module** — create `board/lead_state.py` with exactly this content:

```python
#!/usr/bin/env python3
"""lead_state: <discord dir>/lead-state.json for each project with a Discord bridge (spec 2026-11-23-remote-lead-liveness §1).

tick(records, now, *, holder_of, sid_of, home) is called after each overview build. `records` are overview.build()'s
project records; holder_of(project) -> bool (the lead pane holds the project's bot); sid_of(project) -> the lead's session
id or "". No LLM, no network. A failing project is logged and skipped. The file:
  {"at", "state": busy|ready|needs_you|down, "since", "tool", "queued", "last_read_text", "last_read_message_id",
   "holder", "reason", "window"}
`last_read_message_id`, `reason` (why down) and `window` are additions to the spec's schema (plan assumption A2).
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import tc_env  # noqa: E402

TAIL = 1024 * 1024   # bytes of the lead transcript read from its end
READ_MAX = 200
CHANNEL = "plugin:discord:discord"
_TAG = re.compile(r'<channel source="plugin:discord:discord"([^>]*)>(.*?)</channel>', re.S)
_MID = re.compile(r'\bmessage_id="([^"]+)"')
_cache = {}   # transcript path -> ((size, mtime_ns), info)
_paths = {}   # session id -> transcript path
_lock = threading.Lock()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def classify(rec, holder):
    """(state, reason): down when the lead is missing or nobody holds the bot, needs_you when the lead pane waits on a
    dialog or permission prompt, busy while it works, else ready."""
    status = (rec.get("lead") or {}).get("status")
    if status in (None, "missing"):
        return "down", "no claude in the lead window"
    if not holder:
        return "down", "bot not held"
    if status == "waiting":
        return "needs_you", None
    if status == "working":
        return "busy", None
    return "ready", None


def lead_tool(rec):
    return next((a.get("tool") for a in rec.get("agents") or [] if a.get("window") == "claude"), None)


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        start = max(0, size - TAIL)
        f.seek(start)
        data = f.read().decode("utf-8", "replace")
    lines = data.splitlines()
    return lines[1:] if start > 0 else lines   # the first line of a mid-file read is partial


def transcript_info(path):
    """(last_read_text, last_read_message_id, queued) from the transcript's tail; (None, None, 0) when unreadable.
    Cached by (size, mtime): an unchanged file is not read again."""
    if not path:
        return None, None, 0
    try:
        stt = os.stat(path)
    except OSError:
        return None, None, 0
    key = (stt.st_size, stt.st_mtime_ns)
    hit = _cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    text = mid = None
    pending = []   # queued prompt contents, FIFO
    try:
        lines = _tail_lines(path)
    except OSError:
        return None, None, 0
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        if r.get("type") == "queue-operation":
            op, c = r.get("operation"), r.get("content")
            if op == "enqueue":
                pending.append(c if isinstance(c, str) else "")
            elif op == "dequeue" and pending:
                pending.pop(0)
            elif op == "remove" and c in pending:
                pending.remove(c)
            elif op == "popAll":
                pending.clear()
            continue
        o = r.get("origin") or {}
        if r.get("type") == "user" and not r.get("isSidechain") and o.get("kind") == "channel" and o.get("server") == CHANNEL:
            m = _TAG.search(_text((r.get("message") or {}).get("content")))
            if m:
                text = m.group(2).strip()[:READ_MAX]
                mm = _MID.search(m.group(1))
                mid = mm.group(1) if mm else None
    info = (text, mid, sum(1 for c in pending if f'<channel source="{CHANNEL}"' in c))
    _cache[path] = (key, info)
    return info


def transcript_path(home, sid):
    """<home>/projects/*/<sid>.jsonl, or None. The hit is cached per session id."""
    if not sid or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        return None
    p = _paths.get(sid)
    if p and os.path.isfile(p):
        return p
    hits = sorted(Path(home).glob(f"projects/*/{sid}.jsonl"))
    if not hits:
        return None
    _paths[sid] = str(hits[0])
    return _paths[sid]


def read(path):
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def compute(rec, holder, info, prev, now):
    state, reason = classify(rec, holder)
    since = prev.get("since") if prev and prev.get("state") == state and isinstance(prev.get("since"), str) else iso(now)
    text, mid, queued = info
    return {"at": iso(now), "state": state, "since": since, "tool": lead_tool(rec) if state == "busy" else None,
            "queued": queued, "last_read_text": text, "last_read_message_id": mid, "holder": bool(holder),
            "reason": reason, "window": "claude"}


def write(path, obj):
    """Atomic: a temp file unique to this process and thread, then rename."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def tick(records, now, *, holder_of, sid_of, home):
    for r in records:
        p = r.get("project")
        try:
            d = tc_env.discord_dir(p)
            if not (d / "bridge.json").is_file():
                continue
            holder = bool(holder_of(p))
            info = transcript_info(transcript_path(home, sid_of(p) or ""))
            with _lock:   # read-modify-write of `since`: one writer at a time in this process
                f = d / "lead-state.json"
                write(f, compute(r, holder, info, read(f), now))
        except Exception as e:   # noqa: BLE001 - one project's failure never breaks the overview or the next project
            print(f"lead_state: {p}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
```

- [ ] **Step 4: Run the test, then one named mutation**

Run: `python3 -m unittest discover -s board/tests -p 'test_lead_state.py' -v` → `Ran 15 tests … OK`.
Then change `compute`'s `since = …` line to `since = iso(now)`, rerun, see `test_since_kept_across_writes_and_reset_on_change` FAIL, and restore the line. Report the failure line.

- [ ] **Step 5: Commit**

```bash
git add board/lead_state.py board/tests/test_lead_state.py
git commit -m "feat(board): lead_state writes lead-state.json per bridged project"
```
(end the message with your harness's attribution trailer)

```json:metadata
{"files": ["board/lead_state.py", "board/tests/test_lead_state.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_lead_state.py' -v", "acceptanceCriteria": ["each state from fixed records incl. holder false -> down", "since kept and reset", "last_read_text/id from fixture transcript", "queued counts pending channel enqueues", "atomic write, no file without bridge.json, failure isolated", "transcript cache and 1 MiB tail"], "modelTier": "mechanical"}
```

### Task 2: board writes lead-state.json on every overview

**Goal:** `board/server.py` calls `lead_state.tick` after each fresh overview build with a real holder lookup and the lead's session id, and `python3 board/lead_state.py --dry-run` prints what it would write for the user's real projects without writing.

**Files:**
- Modify: `board/server.py` (new `lead_state_tick(records, now)` next to `feed_tick`; one call in `overview_payload` after `feed_tick`)
- Modify: `board/lead_state.py` (add `main()` with `--dry-run [--project P]`)
- Test: `board/tests/test_lead_state_wiring.py`

**Acceptance Criteria:**
- [ ] `overview_payload()` calls `lead_state_tick(ov["projects"], ov["generated"])` once per fresh build (not on a cache hit), after `feed_tick`; an exception inside it is logged to stderr and `overview_payload` still returns the value.
- [ ] `holder_of(p)` is true only when the `={p}:claude` pane id is in `discord_leads([(pane, pane_pid)])`; a project with no claude window gives false (and so `down`).
- [ ] `sid_of(p)` is `planview.lead_entry(p, HOME / ".claude", tmux)[0]`.
- [ ] `TC_LEAD_STATE=0` turns the tick off (same pattern as `TC_DISCORD_BRIDGE=0`).
- [ ] `python3 board/lead_state.py --dry-run` (real state, read-only) prints one JSON object per bridged project, `{"project", "file", "would_write": {...}}`, writes nothing (the file's mtime is unchanged), and exits 0.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_lead_state*.py' -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_lead_state_wiring.py`. Import `server` the way `board/tests/test_overview_api.py` does (read it first: it sets `TMUX_DASH_TOKEN` and `TC_STATE` before the import). Cases, each with its mutation:
  - `overview_payload` with `build_overview`, `ensure_overseer`, `ensure_discord_bridges`, `feed_tick` and `lead_state.tick` patched: `lead_state.tick` called once with the built records and `generated`; a second call inside `OVERVIEW_EVERY` (cache hit) does not call it again. Mutation: call it before the cache check → called twice.
  - `lead_state.tick` raising `RuntimeError` → `overview_payload()` still returns a dict with `projects`, and stderr holds `lead state failed`. Mutation: drop the try → the test errors.
  - `holder_of`: patch `server.tmux` to return `"%7\t4242"` for `display … ={p}:claude` and `server.discord_leads` to return `{"%7"}` → True; return `set()` → False; `tmux` returning `""` → False and `discord_leads` not called.
  - `TC_LEAD_STATE=0` → `lead_state.tick` not called.
  - `lead_state.main(["--dry-run", "--project", "alpha"])` with a scratch `TC_STATE`, `bridge.json` present and `overview.board_overview` patched to return one record → prints one JSON line naming `alpha`, and `lead-state.json` does not exist afterwards. Mutation: call `write` in dry-run → the file exists.

- [ ] **Step 2: Run to see them fail** — `python3 -m unittest discover -s board/tests -p 'test_lead_state_wiring.py'` → `AttributeError: module 'server' has no attribute 'lead_state_tick'`.

- [ ] **Step 3: Implement.** In `board/server.py`, import `lead_state` with the other board modules, then add next to `feed_tick`:

```python
def lead_state_tick(records, now):
    """lead-state.json for each bridged project (spec 2026-11-23-remote-lead-liveness §1). TC_LEAD_STATE=0: never."""
    if os.environ.get("TC_LEAD_STATE") == "0":
        return
    home = HOME / ".claude"

    def holder_of(p):
        raw = tmux("display", "-p", "-t", f"={p}:claude", "#{pane_id}\t#{pane_pid}").strip()
        if not raw:
            return False
        pane, ppid = raw.split("\t")
        return pane in discord_leads([(pane, int(ppid))])

    lead_state.tick(records, now, holder_of=holder_of, sid_of=lambda p: planview.lead_entry(p, home, tmux)[0], home=home)
```

and in `overview_payload`, after the `feed_tick(...)` line:

```python
    try:
        lead_state_tick(ov["projects"], ov["generated"])
    except Exception as e:   # noqa: BLE001 - never breaks the overview
        print(f"tmux-dash: lead state failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
```

In `board/lead_state.py` add a `main(argv=None)` with argparse `--dry-run` (required for now; without it print usage and return 2) and `--project`: records from `overview.board_overview() or overview.local_overview()` (import inside `main`), holder from `server.discord_leads` via the same `display` lookup (import `server` inside `main`, after `os.environ.setdefault("TMUX_DASH_TOKEN", "local")`), sid from `planview.lead_entry`; for each bridged project print `json.dumps({"project": p, "file": str(f), "would_write": compute(r, holder, info, read(f), time.time())})`. Add `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 4: Run** `python3 -m unittest discover -s board/tests -p 'test_lead_state*.py' -v` → OK. Then the real-state read-only check: `stat -f %m ~/.local/state/agent-board/discord/agent-board/lead-state.json 2>/dev/null; python3 board/lead_state.py --dry-run --project agent-board; stat -f %m ~/.local/state/agent-board/discord/agent-board/lead-state.json 2>/dev/null` → one JSON line with a `would_write.state` of busy/ready/needs_you/down, and the two `stat` lines equal (or both empty). Paste the output in your report.

- [ ] **Step 5: Commit** `board/server.py board/lead_state.py board/tests/test_lead_state_wiring.py` as `feat(board): write lead-state.json on every overview`.

```json:metadata
{"files": ["board/server.py", "board/lead_state.py", "board/tests/test_lead_state_wiring.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_lead_state*.py' -v", "acceptanceCriteria": ["tick once per fresh overview build after feed_tick, failure logged", "holder_of via discord_leads on the claude pane", "sid_of via planview.lead_entry", "TC_LEAD_STATE=0 off", "--dry-run prints and writes nothing; real-state run pasted"], "modelTier": "standard"}
```

### Task 3: liveness.js (pure reaction choice and ❓ line)

**Goal:** `tools/discord-bridge/lib/liveness.js` picks the one liveness reaction for a target message from `lead-state.json` and builds the ❓ reply line, with no I/O besides `readState`.

**Files:**
- Create: `tools/discord-bridge/lib/liveness.js`
- Test: `tools/discord-bridge/test/liveness.test.js`

**Acceptance Criteria:**
- [ ] Each reaction of the spec table from a fixed state and target; precedence ⚠️ > 🙋 > ✅ > 👀 > ⏳ > 📨.
- [ ] `at` older than 180 s, unparsable, or no state → ⚠️.
- [ ] Read by `last_read_message_id` or first 200 trimmed chars; an empty text never counts as read.
- [ ] Every ❓ reply line of Global Constraints, including the missing/stale line.

**Verify:** `cd tools/discord-bridge && node --test test/liveness.test.js` → `# pass 8`, `# fail 0`

**Steps:**

- [ ] **Step 1: Write the failing test** — create `tools/discord-bridge/test/liveness.test.js` with exactly:

```js
'use strict';
process.env.TZ = 'UTC'; // hhmm is local time: pin it before any Date is built
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const lv = require('../lib/liveness');

const NOW = Date.parse('2026-11-24T21:46:26Z');
const iso = (ms) => new Date(ms).toISOString();
const st = (o = {}) => ({ at: iso(NOW - 5000), state: 'ready', since: iso(NOW - 60000), tool: null, queued: 0, last_read_text: null, holder: true, ...o });
const msg = (o = {}) => ({ id: '100', text: 'deploy it?', answered: false, ...o });

test('each reaction of the table', () => {
  assert.strictEqual(lv.pick(st(), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(st({ state: 'busy' }), msg(), NOW), '⏳');
  assert.strictEqual(lv.pick(st({ last_read_text: 'deploy it?' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st(), msg({ answered: true }), NOW), '✅');
  assert.strictEqual(lv.pick(st({ state: 'needs_you' }), msg(), NOW), '🙋');
  assert.strictEqual(lv.pick(st({ state: 'down' }), msg(), NOW), '⚠️');
});

test('precedence: ⚠️ > 🙋 > ✅ > 👀 > ⏳ > 📨', () => {
  const read = { last_read_text: 'deploy it?' };
  assert.strictEqual(lv.pick(st({ state: 'down', ...read }), msg({ answered: true }), NOW), '⚠️');
  assert.strictEqual(lv.pick(st({ state: 'needs_you', ...read }), msg({ answered: true }), NOW), '🙋'); // mutation: answered checked before needs_you -> fails
  assert.strictEqual(lv.pick(st({ state: 'busy', ...read }), msg({ answered: true }), NOW), '✅');
  assert.strictEqual(lv.pick(st({ state: 'busy', ...read }), msg(), NOW), '👀'); // mutation: busy checked before read -> fails
});

test('a stale or missing state file is ⚠️', () => {
  assert.strictEqual(lv.pick(st({ at: iso(NOW - 181000) }), msg(), NOW), '⚠️'); // mutation: STALE_MS 300 s -> fails
  assert.strictEqual(lv.pick(st({ at: iso(NOW - 179000) }), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(null, msg(), NOW), '⚠️');
  assert.strictEqual(lv.pick(st({ at: 'garbage' }), msg(), NOW), '⚠️');
});

test('read: by message id, or first 200 chars after trim; a different text is not read', () => {
  const long = 'x'.repeat(250);
  assert.strictEqual(lv.pick(st({ last_read_text: long.slice(0, 200) }), msg({ text: long }), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_text: '  deploy it?\n' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_message_id: '100', last_read_text: 'other' }), msg(), NOW), '👀');
  assert.strictEqual(lv.pick(st({ last_read_text: 'other' }), msg(), NOW), '📨');
  assert.strictEqual(lv.pick(st({ last_read_text: '' }), msg({ text: '' }), NOW), '📨'); // an empty text never counts as read
});

test('no target: null', () => { assert.strictEqual(lv.pick(st(), null, NOW), null); });

test('❓ reply lines', () => {
  assert.strictEqual(lv.replyLine(st({ state: 'busy', since: iso(NOW - 386000), tool: 'Bash: npm test', queued: 2 }), NOW), 'busy 6m26s: Bash: npm test; 2 message(s) queued');
  assert.strictEqual(lv.replyLine(st({ state: 'busy', since: iso(NOW - 42000) }), NOW), 'busy 42s; 0 message(s) queued');
  assert.strictEqual(lv.replyLine(st({ state: 'ready', since: '2026-11-24T21:40:00Z' }), NOW), 'ready since 21:40');
  assert.strictEqual(lv.replyLine(st({ state: 'needs_you' }), NOW), 'needs you: a dialog is waiting in claude');
  assert.strictEqual(lv.replyLine(st({ state: 'down', reason: 'bot not held', since: '2026-11-24T20:05:00Z' }), NOW), 'down: bot not held since 20:05');
  assert.strictEqual(lv.replyLine(null, NOW), 'no lead state (board not running?)');
  assert.strictEqual(lv.replyLine(st({ at: iso(NOW - 181000) }), NOW), 'no lead state (board not running?)');
});

test('dur', () => { assert.deepStrictEqual([0, 59999, 60000, 3600000, 3900000].map(lv.dur), ['0s', '59s', '1m00s', '1h00m', '1h05m']); });

test('readState: missing, garbage and an array are null; an object is returned', () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), 'lv-'));
  const f = path.join(d, 'lead-state.json');
  assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, 'nope'); assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, '[1]'); assert.strictEqual(lv.readState(f), null);
  fs.writeFileSync(f, JSON.stringify(st())); assert.strictEqual(lv.readState(f).state, 'ready');
});
```

- [ ] **Step 2: Run to see it fail** — `cd tools/discord-bridge && node --test test/liveness.test.js` → `Cannot find module '../lib/liveness'`.

- [ ] **Step 3: Write the module** — create `tools/discord-bridge/lib/liveness.js` with exactly:

```js
'use strict';
// Lead liveness (spec 2026-11-23-remote-lead-liveness §2): which reaction the newest allowlisted home-channel message
// carries, and the ❓ reply line. Pure: the bridge passes the parsed lead-state.json, the target message and the clock.
const fs = require('node:fs');

const STALE_MS = 180 * 1000;
const E = { posted: '📨', busy: '⏳', read: '👀', answered: '✅', needs: '🙋', down: '⚠️' };
const ALL = new Set(Object.values(E));
const READ_MAX = 200;

// lead-state.json parsed, or null when missing or unreadable.
function readState(file) {
  try {
    const s = JSON.parse(fs.readFileSync(file, 'utf8'));
    return s && typeof s === 'object' && !Array.isArray(s) ? s : null;
  } catch { return null; }
}

// Missing, without a parsable `at`, or `at` more than 180 s before nowMs.
function stale(state, nowMs) {
  const at = Date.parse(state?.at ?? '');
  return !Number.isFinite(at) || nowMs - at > STALE_MS;
}

const head = (t) => String(t ?? '').trim().slice(0, READ_MAX);

// The lead read the message: its id is the transcript's newest channel message id, or its first 200 chars equal last_read_text.
function isRead(state, target) {
  if (state?.last_read_message_id && String(state.last_read_message_id) === String(target.id)) return true;
  return typeof state?.last_read_text === 'string' && head(state.last_read_text) !== '' && head(state.last_read_text) === head(target.text);
}

// target {id, text, answered}; precedence ⚠️, 🙋, ✅, 👀, ⏳, 📨. null without a target.
function pick(state, target, nowMs) {
  if (!target) return null;
  if (stale(state, nowMs) || state.state === 'down') return E.down;
  if (state.state === 'needs_you') return E.needs;
  if (target.answered) return E.answered;
  if (isRead(state, target)) return E.read;
  if (state.state === 'busy') return E.busy;
  return E.posted;
}

const pad = (n) => String(n).padStart(2, '0');
// 42s, 6m26s, 1h05m
function dur(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${pad(s % 60)}s`;
  return `${Math.floor(s / 3600)}h${pad(Math.floor((s % 3600) / 60))}m`;
}
// local HH:MM
function hhmm(ms) { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }

// The one ❓ reply line, from lead-state.json only.
function replyLine(state, nowMs) {
  if (!state || stale(state, nowMs)) return 'no lead state (board not running?)';
  const since = Date.parse(state.since ?? '');
  const sinceMs = Number.isFinite(since) ? since : Date.parse(state.at);
  const n = Number.isInteger(state.queued) && state.queued > 0 ? state.queued : 0;
  if (state.state === 'busy') return `busy ${dur(nowMs - sinceMs)}${state.tool ? `: ${state.tool}` : ''}; ${n} message(s) queued`;
  if (state.state === 'ready') return `ready since ${hhmm(sinceMs)}`;
  if (state.state === 'needs_you') return `needs you: a dialog is waiting in ${state.window || 'claude'}`;
  return `down: ${state.reason || 'unknown'} since ${hhmm(sinceMs)}`;
}

module.exports = { E, ALL, STALE_MS, readState, stale, isRead, pick, replyLine, dur, hhmm };
```

- [ ] **Step 4: Run** → `# pass 8`, `# fail 0`. Then move the `if (target.answered)` line above the `needs_you` line, rerun, see `precedence` FAIL (🙋 expected, ✅ actual), restore. Report the failure line.

- [ ] **Step 5: Commit** both files as `feat(discord-bridge): liveness reaction choice and ❓ line`.

```json:metadata
{"files": ["tools/discord-bridge/lib/liveness.js", "tools/discord-bridge/test/liveness.test.js"], "verifyCommand": "cd tools/discord-bridge && node --test test/liveness.test.js", "acceptanceCriteria": ["each reaction and precedence", "stale or missing -> warning", "read by id or 200 chars", "every reply line"], "modelTier": "mechanical"}
```

### Task 4: bridge liveness reaction and last-user-message.json

**Goal:** In project mode the bridge tracks the newest allowlisted home-channel message, writes `last-user-message.json`, and every 10 s swaps one bot liveness reaction on it through its own outbox, leaving the plugin's 👀 ack alone.

**Files:**
- Modify: `tools/discord-bridge/bridge.js`
- Modify: `tools/discord-bridge/test/fake-client.js` (reaction entries with `emoji`, `me`, `users.remove`; messages with `createdTimestamp`)
- Test: `tools/discord-bridge/test/liveness-bridge.test.js` (new file; copy `setup()` from `test/bridge.test.js` and add a `leadState(obj)` writer)

**Acceptance Criteria:**
- [ ] An allowlisted user's message in the home channel becomes the target: `last-user-message.json` = `{"ts": <createdTimestamp ISO>, "message_id"}`, and within two ticks (≤ 4 s fake clock) the message carries 📨 for a fresh `ready` state.
- [ ] Each table state shows on the target after a state-file change: ⏳ (busy, unread), 👀 (read by id), ✅ (a bot message after it that the bridge did not send), 🙋, ⚠️ (down, stale `at`, missing file). A swap removes the bot's previous liveness reaction (`users.remove('BOT')`) and adds the new one.
- [ ] No-op when unchanged: five ticks over 50 s with the same state make exactly one `react` call.
- [ ] A newer allowlisted message moves the target: the old message's bridge-added reaction is removed. Delivery: an older snowflake delivered late and a repeat of the current message change nothing (no reset, no new file write).
- [ ] The plugin's ack: when the target already carries the bot's 👀 before the bridge picks 👀, the bridge adds nothing, and a later swap to ✅ does not remove that 👀.
- [ ] The bridge's own home-channel sends (card, post, dialog, prompt, approval, edit reply, ireply fallback, liveness reply) are recorded in `st.own_sent` (capped 200) and never count as the lead's answer; neither does a message with `interactionMetadata` or `interaction`.
- [ ] Not tracked: a non-allowlisted author, another channel, a thread of the home channel, and everything in ops mode.
- [ ] All existing bridge tests still pass.

**Verify:** `cd tools/discord-bridge && npm test` → `# fail 0`

**Steps:**

- [ ] **Step 1: Extend the fake** (`test/fake-client.js`). Reaction cache entries become `{ emoji: { name: e }, me: true, users: { remove: async (u) => { record('unreact', msgId, { emoji: e, user: u }); entry.me = u === BOT ? false : entry.me; if no users left delete it } } }`, built by one helper used by both `_makeMessage().react` and `fakeMessage().react` (and the `hasEyes` seed). `fakeMessage` gains `createdTimestamp` (default `Date.parse('2026-11-24T21:00:00Z')`), `bot` on `author` (`authorBot` option), `interactionMetadata` option, and the message is registered with `client.messages.set(id, m)` by the tests so `channels.fetch(home).messages.fetch(id)` finds it. Keep every existing field: the existing tests read `.me` and `.reacted`.

- [ ] **Step 2: Write the failing tests** in `test/liveness-bridge.test.js`, one `test()` per acceptance criterion above (snowflake ids like `'1001'`, `'1002'`; the target author `U1` is in `access.json` `allowFrom`, `bridge.json` `{channel: 'C1'}`). Drive with `bridge.onMessage(m)` then `await bridge.tick()` and `s.clock.t += 2000`. Name the mutations: drop the `want === L.shown` check → the no-op test fails; drop the `own_sent` filter → "own post is not an answer" fails; drop the snowflake `newer` check → "older delivered late" fails; drop the `👀 already mine` check → the plugin-ack test fails.

- [ ] **Step 3: Run to see them fail** — `cd tools/discord-bridge && node --test test/liveness-bridge.test.js`.

- [ ] **Step 4: Implement in `bridge.js`** (project mode only; `ops` skips all of it):
  - `const liveness = require('./lib/liveness');`, `const LIVE_MS = 10000;`, `let lastLiveAt = -Infinity;`, state `st.liveness ||= { target: null, shown: null, added: null, bot_after: [] }` and `st.own_sent ||= []` (add both to `lib/state.js` defaults only if a test needs it; reading `||=` in `createBridge` is enough).
  - `newer(a, b)`: `try { return BigInt(a) > BigInt(b); } catch { return String(a) > String(b); }`.
  - `noteOwn(msg)`: push `msg.id` into `st.own_sent`, keep the last 200, `save()`. Call it on the result of each home-channel send listed in the acceptance criteria (today's `ch.send` / `msg.reply` sites in `createCard`, `opPost`, `opDialog`, `opPrompt`, `opApproval`, `opEdit`'s reply, `opIreply`'s fallback; the thread send in `opThread`'s target is harmless to record too).
  - `enqueue(op)`: `<dir>/outbox/<13-digit ms>-<8 hex>.json`, ms = `Math.max(now(), lastEnq + 1)`, `crypto.randomBytes(4).toString('hex')`, write `.tmp` then `fs.renameSync`.
  - `track(msg)` called first thing in `onMessage` (before the reply-armed early return): home channel only (`msg.channel?.id === cfg().channel`); a bot-authored message (`msg.author?.id === client.user?.id`) newer than the target and without `interactionMetadata`/`interaction` is pushed to `bot_after` (last 50); an allowlisted, non-bot author with a message newer than the target becomes the new target (`{id, text: content.trim().slice(0, 200)}`), resets `shown`/`added`/`bot_after`, enqueues `{op: 'liveness', message_id: old.id, add: null, remove: old.added}` when the old one had a bridge-added reaction, writes `last-user-message.json` atomically, and sets `lastLiveAt = -Infinity`.
  - `liveTick()` at the end of `tick()` (after the outbox loop, inside the `busy` guard): skip when `now() - lastLiveAt < LIVE_MS`; `want = liveness.pick(liveness.readState(path.join(dir, 'lead-state.json')), { ...L.target, answered: L.bot_after.some((id) => !st.own_sent.includes(id)) }, now())`; when `want && want !== L.shown`: `enqueue({ op: 'liveness', message_id: L.target.id, add: want, remove: L.added })`, `L.shown = want`, `save()`.
  - `opLiveness(op)` in `handlers`: fetch the message from the home channel (`UNKNOWN_MESSAGE` → log and return); `remove` → `reactionOf(msg, op.remove)?.users.remove(client.user.id)`; `unreact` → `reactionOf(msg, op.unreact.emoji)?.users.remove(String(op.unreact.user))`, a failure logs `liveness: cannot remove ❓ (grant Manage Messages)` once per process; `add` → if `add === '👀'` and `reactionOf(msg, '👀')?.me` is already true, add nothing and set `L.added = null`, else `await msg.react(add)` and, when `message_id` is the current target, `L.added = add`; when only removing on the current target set `L.added = null`. `reactionOf(msg, e)` = `msg.reactions?.cache?.get(e) ?? [...(msg.reactions?.cache?.values() ?? [])].find((r) => strip(r.emoji?.name) === strip(e))` with `strip = (s) => String(s ?? '').replace(/️/g, '')`.
  - Delivery semantics (state them in a comment above `track`): handlers run on one JS thread and `liveTick` only inside the serialized `tick`; out-of-order and repeated `messageCreate` deliveries are dropped by the snowflake `newer` guard; a repeated outbox op is idempotent (react and remove of the same emoji twice end in the same state).

- [ ] **Step 5: Run** `cd tools/discord-bridge && npm test` → `# fail 0` (the count rises by the new tests). Run each named mutation once and report its failing test name.

- [ ] **Step 6: Commit** `tools/discord-bridge/bridge.js tools/discord-bridge/test/fake-client.js tools/discord-bridge/test/liveness-bridge.test.js` as `feat(discord-bridge): liveness reaction on the newest user message`.

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/fake-client.js", "tools/discord-bridge/test/liveness-bridge.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["target tracked, last-user-message.json written, posted reaction within 2 ticks", "each table state and swap removes the previous", "no-op when unchanged", "newer message moves target; late older and repeat ignored", "plugin 👀 ack untouched", "own sends and interaction messages never an answer", "non-allowlisted, other channel, thread, ops mode not tracked", "existing tests pass"], "modelTier": "standard"}
```

### Task 5: ❓ on demand

**Goal:** An allowlisted user's ❓ reaction on any home-channel message gets one reply line built from `lead-state.json`, and the bridge removes that ❓.

**Files:**
- Modify: `tools/discord-bridge/bridge.js` (`onReaction`, `liveness_reply` handler)
- Test: `tools/discord-bridge/test/liveness-bridge.test.js`

**Acceptance Criteria:**
- [ ] ❓ (with or without U+FE0F) by an allowlisted user on any message in the home channel, bot-authored or not, enqueues `{op: 'liveness_reply', text: liveness.replyLine(state, now())}` and `{op: 'liveness', message_id, add: null, remove: null, unreact: {emoji: '❓', user}}`; after one tick the channel got exactly one `send` with that text and the fake recorded `unreact` for the user.
- [ ] Missing `lead-state.json` → the reply is `no lead state (board not running?)`; a fresh busy state → the `busy …` line.
- [ ] ❓ from a non-allowlisted user, in another channel, or in ops mode → no op, no send.
- [ ] The same ❓ delivered twice within 10 s → one reply (dedupe key `message_id:user`).
- [ ] The reply message is recorded in `st.own_sent`, so a following bot `messageCreate` for it does not turn the target ✅.
- [ ] The existing ✅ ❌ 🛑 ▶ ⏭ react events are unchanged (existing tests pass).

**Verify:** `cd tools/discord-bridge && npm test` → `# fail 0`

**Steps:**

- [ ] **Step 1: Failing tests** in `test/liveness-bridge.test.js`, one per criterion. Mutations: drop the dedupe map → "twice within 10 s" fails; drop `noteOwn` on the reply → "reply is not an answer" fails.
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.** In `onReaction`, after the allowlist check and before the `REACT_EMOJI` check: `if (!ops && emoji === '❓') return onAsk(reaction, user);`. `onAsk` fetches a partial message, requires `msg.channel?.id === cfg().channel`, dedupes on `${msg.id}:${user.id}` for 10 s (a `Map` of ms, entries older than 60 s pruned), then `enqueue` the two ops above. `opLivenessReply(op)`: `const m = await (await home()).send({ content: cut(String(op.text), REPLY_MAX), allowedMentions: { parse: [] } }); noteOwn(m);`, registered in `handlers` as `liveness_reply`. Enqueue the reply op before the unreact op so the line posts even when the unreact fails.
- [ ] **Step 4: Run** `cd tools/discord-bridge && npm test` → `# fail 0`; run both mutations once and report the failing test names.
- [ ] **Step 5: Commit** `tools/discord-bridge/bridge.js tools/discord-bridge/test/liveness-bridge.test.js` as `feat(discord-bridge): ❓ reaction answers with the lead state`.

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/liveness-bridge.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["❓ by allowlisted user -> one reply line and the ❓ removed", "missing file line and busy line", "non-allowlisted, other channel, ops ignored", "dedupe within 10 s", "reply recorded as own send", "existing react events unchanged"], "modelTier": "standard"}
```

### Task 6: /ideas on project bots covers only their project

**Goal:** Project bots register `/ideas`; on a project bot it covers only its own project (another named project is refused with one line), its groups post into the project's channel and their Park / Brainstorm / Drop buttons act on that project; the ops bot is unchanged.

**Files:**
- Modify: `tools/discord-bridge/lib/commands.js`
- Modify: `tools/discord-bridge/test/commands.test.js`
- Modify: `board/discord_ops.py` (`handle_event`'s `ideas_slash` branch)
- Modify: `board/tests/test_discord_ideas_wiring.py`

**Acceptance Criteria:**
- [ ] `payload(false)` includes `ideas` (with an optional `project` option); `payload(true)` is unchanged. The existing assertion "project bots do not register /ideas" is replaced by its opposite.
- [ ] On a project bot (`ctx.ops` false, dir `myproj`): `/ideas` with no project writes `{type: 'slash', command: 'ideas', project: 'myproj', bridge: 'myproj'}` and answers `asked the overseer, about 1 min`, in any channel; `/ideas project:other` answers exactly `/ideas here covers only myproj; use the ops bot for other` and writes no event (checked before `crossDenied`).
- [ ] Ops bot: `/ideas` with and without a project writes the same events as today (`bridge: '_ops'`, project null or named).
- [ ] Board: a slash `ideas` event with `bridge` a project name calls `discord_ideas.request(<bridge>, <bridge>, …)` (the event's own project ignored when it differs, audit result `refused: other project`, no request); `bridge` `_ops` or missing calls `request(<event project or None>, "_ops", …)` as today. Clicks already edit through the request's own bridge (`discord_ideas.click` reads `st["bridge"]`): one test asserts a request made with bridge `alpha` writes its post and the click's edit into `tc_env.discord_dir("alpha")/outbox`.
- [ ] The test `test_named_project_passes_through_on_the_ops_bridge` is rewritten to the new rule; the null-project, disallowed-user and other-slash tests still pass.

**Verify:** `cd tools/discord-bridge && node --test test/commands.test.js && cd ../.. && python3 -m unittest discover -s board/tests -p 'test_discord_ideas*.py' -v`

**Steps:**

- [ ] **Step 1: Failing tests** (both files). In `commands.test.js` reuse its `fakeCommand`/`s.run` helpers (`/ideas` tests at lines ~271-290 show the shape). In `test_discord_ideas_wiring.py` extend `Slash`; for the outbox test use the real `discord_ideas.request` and `post` with a scratch `TC_STATE`, a `tc_env.discord_dir("alpha")` dir with `bridge.json`, and an idea added with `ideas.add("alpha", …)` (read `board/tests/test_discord_ideas.py` for the post document shape). Mutations: keep `name !== 'ideas'` in `payload` → the registration test fails; drop the other-project refusal → the refusal test fails; keep `"_ops"` hardcoded in `handle_event` → the bridge test fails.
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.**
  - `commands.js` `payload`: drop the `filter((name) => ops || name !== 'ideas')` and its comment. In `handleCommand`, before `crossDenied`: `if (name === 'ideas' && !ctx.ops && given && given !== own) { await ctx.answer(i, \`/ideas here covers only ${own}; use the ops bot for ${given}\`); return; }`; `project` for `ideas` becomes `ctx.ops ? given : own`. The final `ideas` branch keeps `bridge: own`.
  - `discord_ops.handle_event`: `bridge = str(ev.get("bridge") or "_ops")`; for `ideas_slash` with `bridge != "_ops"`: when `ev.get("project")` names another project → result `refused: other project`, audit, return it; else `discord_ideas.request(bridge, bridge, add_line, time.time())`. `_ops` keeps today's call. Update the comment `# /ideas always posts in #command-center` to say a project bot's posts in its own channel.
- [ ] **Step 4: Run** the Verify command → both pass.
- [ ] **Step 5: Commit** the four files as `feat(discord): /ideas on a project bot covers only its project`.

```json:metadata
{"files": ["tools/discord-bridge/lib/commands.js", "tools/discord-bridge/test/commands.test.js", "board/discord_ops.py", "board/tests/test_discord_ideas_wiring.py"], "verifyCommand": "cd tools/discord-bridge && node --test test/commands.test.js && cd ../.. && python3 -m unittest discover -s board/tests -p 'test_discord_ideas*.py' -v", "acceptanceCriteria": ["project bots register /ideas, ops payload unchanged", "project bot /ideas -> own project event; other project refused with one line, no event", "ops bot events unchanged", "board routes by event bridge; post and click edit land in the project outbox", "old ops-only test rewritten"], "modelTier": "standard"}
```

### Task 7: relay and lead-restart carry the remote marker

**Goal:** When `relay.py` starts a successor lead (handoff relay or `lead-restart`), it copies `<state>/remote/<old sid>` to `<state>/remote/<new sid>` as soon as the new session's `sessions/*.json` entry for the pane appears, when the old marker exists.

**Files:**
- Modify: `board/relay.py` (`session_started_after`, `await_new_session`, `carry_remote`; calls in `relay()` and `restart_lead()`)
- Modify: `board/tests/test_relay.py`

**Acceptance Criteria:**
- [ ] `session_started_after(pane, home, t0_ms)` returns the `sessionId` of the newest `<home>/sessions/*.json` entry whose `tmux` ends with `.<pane>` and whose `startedAt >= t0_ms - 1000`, else `""`.
- [ ] `await_new_session(...)` polls a bounded number of times (`int(cap / poll)`, cap 30 s, poll 1 s) using the caller's `sleep`, so tests with a no-op sleep never wait in real time.
- [ ] `carry_remote(state, old, new)` copies (`shutil.copy2`) only when both ids match `[A-Za-z0-9_-]+`, differ, the old marker exists and the new one does not; returns True when it copied. It never raises (an `OSError` returns False).
- [ ] `relay()`: old id = `old_session_id` or `session_for_pane(pane, home, state_dir)` read before the respawn; t0 taken before the first respawn; after `wait_started` succeeds, await the new id and carry the marker; stderr says `relay: remote marker carried to <new>` when it copied. The lineage row and return text are unchanged.
- [ ] `restart_lead()`: the same, old id from `session_for_pane` before the respawn; with `--resume` keeping the same id nothing is copied.
- [ ] Tests (temp `home` and `state`): marker copied on relay; copied on lead-restart; not copied without an old marker; not copied when the new id equals the old; no session entry within the cap → nothing copied and relay still succeeds. Mutation: drop the `startedAt >= t0` filter → the test with an older entry for the same pane (the old session) copies onto itself / picks the old id and fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_relay.py' -v` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests** in `test_relay.py`, reusing `FakeTmux`, `statuses(...)` and the `LeadTmux` fixtures already there (read `RelayTest` and the `restart_lead` tests at lines ~260-330 and ~480-610). Write session entries as `<home>/sessions/<n>.json` with `{"sessionId", "tmux": "proj:@1.%5", "startedAt", "updatedAt"}`; make the fake `sleep` write the new session's entry on its first call so the poll finds it.
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** the three helpers next to `session_for_pane`, add `home=None` to `relay()` (default `os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")`) and thread `sleep` from `**wait`/`**timing` into `await_new_session`. Keep `relay()`'s existing positional signature.
- [ ] **Step 4: Run** the Verify command → OK; run the named mutation once and report the failing test.
- [ ] **Step 5: Commit** `board/relay.py board/tests/test_relay.py` as `feat(relay): carry the remote marker to the successor lead`.

```json:metadata
{"files": ["board/relay.py", "board/tests/test_relay.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_relay.py' -v", "acceptanceCriteria": ["session_started_after filters by pane and startedAt", "bounded poll with injected sleep", "carry_remote copies only when old exists, ids differ, new absent; never raises", "relay carries marker after start, lineage unchanged", "restart_lead carries marker; resume same id copies nothing", "tests incl. no entry within cap"], "modelTier": "standard"}
```

### Task 8: remote-ask-guard 12 h rule for a lead without a marker

**Goal:** `remote-ask-guard.sh` denies `AskUserQuestion` with the remote-lead text for a lead (`AGENT_BOARD_LEAD=1`) that has no marker of its own when the project's `last-user-message.json` is within 43200 s and no typed terminal prompt in the lead's transcript is newer.

**Files:**
- Modify: `claude/plugin/scripts/remote-ask-guard.sh` (lead branch, after the existing marker check; header comment gains rule 2b)
- Modify: `tools/tests/test_remote_ask_guard.zsh`

**Acceptance Criteria:**
- [ ] Lead, no marker, `last-user-message.json` 1 h old, transcript with no `origin.kind == "human"` row newer than it → exit 2 with exactly the LEAD text.
- [ ] Same, but a human-origin row whose `timestamp` is newer than the file's `ts` → exit 0, silent.
- [ ] File 13 h old → silent; no file → silent; unparsable file → silent (fails open).
- [ ] Discord dir: `DISCORD_STATE_DIR` when set; else the scratch tmux session of `TMUX_PANE` (session group or name, `-bg` stripped) under `${TC_STATE:-~/.local/state/agent-board}/discord/` — one test uses `tt_setup`'s scratch server for this.
- [ ] The rule never writes or removes the marker; every existing case of the suite still passes; worker/teammate order unchanged (a teammate still gets the teammate text).

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_remote_ask_guard.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Failing cases** appended to `tools/tests/test_remote_ask_guard.zsh` before `tt_done`, in its `run`/`denies`/`silent` style. Write the file with `python3 -c` (ISO `ts` from `datetime.now(timezone.utc) - timedelta(hours=1)` formatted `%Y-%m-%dT%H:%M:%S.000Z`) and transcripts with `mk_tr_extra`-style rows carrying `timestamp` and `origin`. For the tmux fallback read `tools/tests/lib.zsh` for the scratch session's name and socket, set `TMUX="<socket>,0,0"` and `TMUX_PANE` to its first pane, and unset `DISCORD_STATE_DIR`. Mutations: drop the newer-human check → the "terminal prompt newer" case fails; use 86400 → the 13 h case fails.
- [ ] **Step 2: Run to see them fail** — `env -u AGENT_BOARD_LEAD zsh tools/tests/test_remote_ask_guard.zsh`.
- [ ] **Step 3: Implement** in the embedded Python, inside `if env.get("AGENT_BOARD_LEAD") == "1":`, after `if marker and os.path.exists(marker): deny(LEAD)`:

```python
        if recent_remote(d.get("transcript_path"), discord_dir(), time.time()):
            deny(LEAD)
        sys.exit(0)
```

with helpers at module level: `discord_dir()` (A6: `DISCORD_STATE_DIR`, else `tmux display -p -t $TMUX_PANE '#{?session_group,#{session_group},#{session_name}}'` and `'#{@tc_bg}'` via the same binary choice as `is_teammate`, base `TC_STATE` or `$HOME/.local/state/agent-board`), `_ts(s)` (`datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()`, None on error), and `recent_remote(tp, ddir, now)`: read `<ddir>/last-user-message.json`; False unless `now - ts <= 43200`; scan the transcript's last 4 MiB (reuse the `last_user_row` reading pattern) for non-sidechain `type == "user"` rows with `origin.kind == "human"`; False when any has `_ts(timestamp) > ts`; else True. Any exception → False. Add rule 2b to the header comment.
- [ ] **Step 4: Run** the Verify command → `ALL PASS`; run both mutations once, report the failing check names.
- [ ] **Step 5: Commit** both files as `feat(plugin): remote-ask-guard treats a lead as remote after a recent Discord message`.

```json:metadata
{"files": ["claude/plugin/scripts/remote-ask-guard.sh", "tools/tests/test_remote_ask_guard.zsh"], "verifyCommand": "env -u AGENT_BOARD_LEAD zsh tools/tests/test_remote_ask_guard.zsh", "acceptanceCriteria": ["lead, no marker, recent file, no newer typed prompt -> LEAD text", "newer typed prompt -> silent", "13 h old, missing, unparsable -> silent", "DISCORD_STATE_DIR then tmux session fallback", "marker untouched, existing cases pass"], "modelTier": "standard"}
```

### Task 9: ARCHITECTURE.md

**Goal:** `docs/ARCHITECTURE.md` documents `lead-state.json`, `last-user-message.json`, the reaction table and the marker carry.

**Files:**
- Modify: `docs/ARCHITECTURE.md`

**Acceptance Criteria:**
- [ ] A new `## Lead liveness on Discord` section right after `## Handoff relay`, holding: who writes `lead-state.json` and when (every overview build, `board/lead_state.py`), its keys, the reaction table with precedence and the 180 s stale rule, the ❓ line, `last-user-message.json` and the guard's 12 h rule, and the relay/lead-restart marker carry.
- [ ] Two rows in the `## State files` table: `~/.local/state/agent-board/discord/<p>/lead-state.json` (writer board, reader bridge) and `…/last-user-message.json` (writer bridge, reader `remote-ask-guard.sh`).
- [ ] Every key, emoji and constant matches Global Constraints of this plan (a reviewer diffs them).

**Verify:** `grep -c '^## Lead liveness on Discord$' docs/ARCHITECTURE.md && grep -c 'lead-state.json\|last-user-message.json' docs/ARCHITECTURE.md` → `1`, then a count ≥ 4

**Steps:**

- [ ] **Step 1:** Read `docs/ARCHITECTURE.md` `## Handoff relay`, `## State files` and the shipped code of Tasks 1-8 (not only this plan): document what the code does. Write the section in the file's style (short paragraphs, one table).
- [ ] **Step 2:** Run the Verify command.
- [ ] **Step 3:** Commit `docs/ARCHITECTURE.md` as `docs(architecture): lead liveness on Discord`.

```json:metadata
{"files": ["docs/ARCHITECTURE.md"], "verifyCommand": "grep -c '^## Lead liveness on Discord$' docs/ARCHITECTURE.md && grep -c 'lead-state.json\\|last-user-message.json' docs/ARCHITECTURE.md", "acceptanceCriteria": ["section after Handoff relay with writer, keys, reaction table, stale rule, ❓ line, 12 h rule, marker carry", "two State files rows", "values match Global Constraints"], "modelTier": "mechanical"}
```

### Task 10: live check from the phone (user gate, after merge)

**Goal:** After the branch is merged to `main` and the board and the agent-board bridge run the merged code, the user sends a message to the agent-board lead from the phone and watches 📨 → ⏳ or 👀 → ✅, then reacts ❓ once and gets one status line.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (read-only checks of the real state)

**Acceptance Criteria:**
- [ ] Before asking the user: the real `~/.local/state/agent-board/discord/agent-board/lead-state.json` is fresh (`at` under 180 s old) and names a state; the bridge was restarted after the merge (its `bridge.pid` mtime is newer than the merge commit).
- [ ] The user reports (Discord or terminal) seeing 📨 then ⏳ or 👀 then ✅ on their message, and one ❓ reply line; the lead quotes the user's words in the task close.
- [ ] `last-user-message.json` names the user's test message id after it was sent.

**Verify:** `python3 -c 'import json,os,time,datetime as d;f=os.path.expanduser("~/.local/state/agent-board/discord/agent-board/");s=json.load(open(f+"lead-state.json"));age=time.time()-d.datetime.fromisoformat(s["at"].replace("Z","+00:00")).timestamp();u=json.load(open(f+"last-user-message.json"));print(s["state"],int(age),u["message_id"]);raise SystemExit(0 if age<180 else 1)'` → prints the state, an age under 180 and the message id; exit 0

**Steps:** none scripted beyond the Verify command; the lead asks the user on Discord (numbered list, reply tool) to send one message and react ❓ once, and records the answer.

```json:metadata
{"files": [], "verifyCommand": "python3 -c 'import json,os,time,datetime as d;f=os.path.expanduser(\"~/.local/state/agent-board/discord/agent-board/\");s=json.load(open(f+\"lead-state.json\"));age=time.time()-d.datetime.fromisoformat(s[\"at\"].replace(\"Z\",\"+00:00\")).timestamp();u=json.load(open(f+\"last-user-message.json\"));print(s[\"state\"],int(age),u[\"message_id\"]);raise SystemExit(0 if age<180 else 1)'", "acceptanceCriteria": ["real lead-state.json fresh and bridge restarted after merge", "user reports 📨 -> ⏳/👀 -> ✅ and one ❓ line, quoted", "last-user-message.json names the test message"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"], "gateScope": "post-merge"}
```

---

## Self-review against the spec

- §1 lead state file → Tasks 1-2 (states, since, queued, last_read_text, holder, atomic, bridge.json gate, no slow-down via cache).
- §2 reactions → Task 3 (table, precedence, stale), Task 4 (10 s loop, swap, no-op, older message loses it, plugin 👀 ack, outbox), Task 5 (❓ lines, removal, non-allowlisted ignored).
- §3 remote across handoffs → Task 7 (relay and lead-restart copy), Task 8 (12 h rule), Task 4 (`last-user-message.json`).
- §4 /ideas per project → Task 6 (bridge and board, ops unchanged).
- §5 docs → Task 9. §6 testing → each task's tests; the post-merge phone check → Task 10 (user gate).
- Out of scope respected: no threads (A8), no bot-message reactions beyond ❓ replies, no teammate liveness, ackReaction unchanged.
