"""watch: the night watch. Acts on the notifier's events for projects in queue mode: one nudge to the lead per stall,
the awake fix, one re-alert after REALERT_S, a heartbeat on every overview. Spec docs/superpowers/specs/2026-11-23-night-watch-design.md.

Deterministic, no LLM, no thread of its own: server.py calls Watch.observe(ov, events) after Notifier.observe on each
overview. Clock, tmux-ctl runner, nudge and alert sinks are injected. State: <state_dir>/watch.json (open stalls),
<state_dir>/watch/heartbeat ({"at", "queue"}). Never raises from observe: a failing piece is logged to stderr.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import notify, tc_env  # noqa: E402

STALL_KINDS = ("teammate_gone", "teammate_silent", "lead_idle", "awake_dropped")   # alert + nudge + re-alert
WATCH_KINDS = STALL_KINDS + ("weekly_pace",)                                       # weekly_pace: alert only
REALERT_S = 900
AWAKE_ARGV = ("awake", "on", "--queue", "--lid")


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _key(project, kind, key):
    return f"{project}\t{kind}\t{key}"


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    os.replace(tmp, path)


def _lead_ready(rec):
    """The lead's own pane (window `claude`) is at its prompt. Not lead.status: that reads `working` while a teammate works."""
    return any(a.get("window") == "claude" and a.get("state") == "ready" for a in rec.get("agents") or [])


def _owned(rec, owner):
    return next((o for o in rec.get("owned") or [] if o.get("owner") == owner), {})


def nudge_line(kind, key, rec, stall):
    if kind == "teammate_gone":
        return f"[Watch] teammate {key} window is gone (task #{_owned(rec, key).get('task', '?')} in progress): respawn it."
    if kind == "teammate_silent":
        o = _owned(rec, key)
        return (f"[Watch] teammate {key} has been idle {(o.get('ready_s') or 0) // 60} min with task #{o.get('task', '?')} in progress: "
                "check its report or nudge it.")
    if kind == "lead_idle":
        plan, lead = rec.get("plan") or {}, rec.get("lead") or {}
        k = (plan.get("total") or 0) - (plan.get("done") or 0)
        return f"[Watch] you have been idle {(lead.get('idle_s') or 0) // 60} min with {k} open tasks: continue the queue."
    if kind == "awake_dropped":
        return f"[Watch] the awake hold dropped and I restarted it: {stall.get('fix') or 'failed: not run'}."
    return None


class Watch:
    def __init__(self, now=time.time, run=None, nudge=None, alert=None, state_dir=None):
        """run(argv) -> output, raises on failure (argv starts with "awake"; the caller prefixes tmux-ctl).
        nudge(project, line) queues one line for the lead's pane. alert(event) posts one Discord line (notify.discord_sink)."""
        self.now = now
        self.run = run or (lambda argv: (_ for _ in ()).throw(RuntimeError("no runner")))
        self.nudge = nudge or (lambda project, line: None)
        self.alert = alert or (lambda ev: None)
        self._dir = state_dir
        self._queue = frozenset()   # queue-mode projects in the previous overview (awake_dropped grace)
        self.stalls = None   # read from watch.json on the first observe

    @property
    def dir(self):
        """state_dir as given, else tc_env.state_dir() at call time ($TC_STATE_DIR: a test's TC_STATE set after import counts)."""
        return Path(self._dir) if self._dir else tc_env.state_dir()

    @property
    def file(self):
        return self.dir / "watch.json"

    @property
    def heartbeat(self):
        return self.dir / "watch" / "heartbeat"

    def _load(self):
        try:
            d = json.loads(self.file.read_text())
            return {k: v for k, v in (d.get("stalls") or {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save(self):
        try:
            _write_json(self.file, {"stalls": self.stalls})
        except OSError as e:
            print(f"watch: save failed: {e}", file=sys.stderr, flush=True)

    def _alert(self, project, text):
        try:
            self.alert({"project": project, "kind": "watch", "key": "", "title": project, "text": text, "ts": self.now()})
        except Exception as e:   # noqa: BLE001
            print(f"watch: alert failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def observe(self, ov, events):
        """Act on one overview and the notifier's events for it. Returns the actions taken, for tests:
        [("nudge"|"fix"|"alert"|"realert", project, kind, key, text)]."""
        now = self.now()
        if self.stalls is None:
            self.stalls = self._load()
        recs = {p["project"]: p for p in ov.get("projects") or [] if p.get("queue")}
        try:
            _write_json(self.heartbeat, {"at": iso(now), "queue": sorted(recs)})
        except OSError as e:
            print(f"watch: heartbeat failed: {e}", file=sys.stderr, flush=True)
        cur = {_key(c["project"], c["kind"], c["key"]): c for c in notify.conditions(ov, self._queue)
               if c["project"] in recs and c["kind"] in WATCH_KINDS}
        self._queue = frozenset(recs)
        acts, changed = [], False
        # The watch latches on the record fields, not on the notifier's events (its RATE_S would swallow a second stall).
        for k, c in cur.items():
            if k in self.stalls or c["kind"] not in STALL_KINDS:
                continue
            self.stalls[k] = {"first_at": now, "nudged_at": None, "fixed_at": None, "realerted_at": None}
            changed = True
            if c["kind"] == "lead_idle":   # the notifier's lead_idle is card-only (routine tier): post it in queue mode
                self._alert(c["project"], c["text"])
                acts.append(("alert", c["project"], c["kind"], c["key"], c["text"]))
        for k in [k for k in self.stalls if k not in cur]:
            del self.stalls[k]
            changed = True
        for k, st in self.stalls.items():
            c = cur[k]
            project, kind, key, rec = c["project"], c["kind"], c["key"], recs[c["project"]]
            if kind == "awake_dropped" and st.get("fixed_at") is None:
                try:
                    self.run(list(AWAKE_ARGV))
                    st["fix"] = "ok"
                except Exception as e:   # noqa: BLE001
                    first = (str(e).strip().splitlines() or [type(e).__name__])[0]
                    st["fix"] = f"failed: {first[:200]}"
                st["fixed_at"] = now
                changed = True
                text = f"awake hold restarted: {st['fix']}"
                self._alert(project, text)
                acts.append(("fix", project, kind, key, text))
            if kind in STALL_KINDS and st.get("nudged_at") is None and _lead_ready(rec):
                line = nudge_line(kind, key, rec, st)
                try:
                    self.nudge(project, line)
                    st["nudged_at"] = now
                    changed = True
                    acts.append(("nudge", project, kind, key, line))
                except Exception as e:   # noqa: BLE001 - try again on the next overview
                    print(f"watch: nudge failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            if kind in STALL_KINDS and st.get("realerted_at") is None and now - st["first_at"] >= REALERT_S:
                text = f"{c['text']} — lead did not react (15 min)"
                self._alert(project, text)
                st["realerted_at"] = now
                changed = True
                acts.append(("realert", project, kind, key, text))
        if changed:
            self._save()
        return acts
