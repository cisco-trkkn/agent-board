"""watch: the night watch. Acts on the notifier's events for projects in queue mode: one nudge to the lead per stall,
the awake fix, one re-alert after REALERT_S, a heartbeat on every overview. Spec docs/superpowers/specs/2026-11-23-night-watch-design.md.

Deterministic, no LLM, no thread of its own: server.py calls Watch.observe(ov, events) after Notifier.observe on each
overview. Clock, tmux-ctl runner, nudge and alert sinks are injected. State: <state_dir>/watch.json (open stalls),
<state_dir>/watch/heartbeat ({"at", "queue"}). Never raises from observe: a failing piece is logged to stderr.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import notify, tc_env  # noqa: E402

STALL_KINDS = ("teammate_gone", "teammate_silent", "lead_idle", "awake_dropped")   # alert + nudge + re-alert
WATCH_KINDS = STALL_KINDS + ("weekly_pace",)                                       # weekly_pace: alert only
REALERT_S = 900
AWAKE_ARGV = ("awake", "on", "--queue", "--lid")
# Run watch (spec 2026-11-24-run-watch-design.md §b): a run in a `✦` pane past its cap is alerted once; with its CPU time
# unchanged on FLAT_KILL overviews in a row it is killed by PID (TERM, KILL after KILL_GRACE_S if alive).
CAPS_FILE = Path(__file__).resolve().parent.parent / "docs" / "superpowers" / "run-caps.json"
DEFAULT_CAPS = {"default_s": 900, "caps": [
    {"match": "node --test", "cap_s": 360}, {"match": "npm test", "cap_s": 360},
    {"match": "unittest discover -s board/tests", "cap_s": 1080},
    {"match": "tools/tests/all.zsh", "cap_s": 1620}, {"match": "tools/tests/run-all.zsh", "cap_s": 1620}]}
FLAT_KILL = 2
KILL_GRACE_S = 10
KILLED_KEEP_S = 3600   # a killed entry never outlives this, settled or not
_caps_logged = set()


def load_caps(path=None):
    """{"default_s", "caps": [{"match", "cap_s"}]} from `path`, else $TC_RUN_CAPS, else docs/superpowers/run-caps.json.
    A missing or unparsable file gives DEFAULT_CAPS and one log line (once per file and error kind)."""
    p = Path(path or os.environ.get("TC_RUN_CAPS") or CAPS_FILE)
    try:
        d = json.loads(p.read_text())
        caps = [{"match": str(c["match"]), "cap_s": int(c["cap_s"])} for c in d.get("caps") or []]
        return {"default_s": int(d.get("default_s", DEFAULT_CAPS["default_s"])), "caps": caps}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        k = (str(p), type(e).__name__)
        if k not in _caps_logged:
            _caps_logged.add(k)
            print(f"watch: run caps {p}: {type(e).__name__}: {e}; using the defaults", file=sys.stderr, flush=True)
        return DEFAULT_CAPS


def cap_for(cmd, caps):
    """The first cap whose `match` is a substring of the command line, else default_s."""
    return next((c["cap_s"] for c in caps["caps"] if c["match"] in cmd), caps["default_s"])


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
    def __init__(self, now=time.time, run=None, nudge=None, alert=None, state_dir=None, tell=None, kill=os.kill, caps_file=None):
        """run(argv) -> output, raises on failure (argv starts with "awake"; the caller prefixes tmux-ctl).
        nudge(project, line) queues one line for the lead's pane. alert(event) posts one Discord line (notify.discord_sink)."""
        self.now = now
        self.run = run or (lambda argv: (_ for _ in ()).throw(RuntimeError("no runner")))
        self.nudge = nudge or (lambda project, line: None)
        self.alert = alert or (lambda ev: None)
        self._dir = state_dir
        self._queue = frozenset()   # queue-mode projects in the previous overview (awake_dropped grace)
        self.stalls = None   # read from watch.json on the first observe
        self.runs = None     # run watch entries, "<window>:<pid>" -> {...}, from the same file
        self.tell = tell or (lambda pane, line: False)   # tell(pane, line) -> True when typed into a teammate's pane
        self.kill = kill     # kill(pid, sig), os.kill's shape
        self.caps_file = caps_file

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

    def _load(self, part="stalls"):
        try:
            d = json.loads(self.file.read_text())
            return {k: v for k, v in (d.get(part) or {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    @property
    def kills_file(self):
        return self.dir / "watch" / "kills.jsonl"

    def _save(self):
        try:
            _write_json(self.file, {"stalls": self.stalls, "runs": self.runs or {}})
        except OSError as e:
            print(f"watch: save failed: {e}", file=sys.stderr, flush=True)

    def _alert(self, project, text, kind="watch", key=""):
        try:
            self.alert({"project": project, "kind": kind, "key": key, "title": project, "text": text, "ts": self.now()})
        except Exception as e:   # noqa: BLE001
            print(f"watch: alert failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def observe(self, ov, events):
        """Act on one overview and the notifier's events for it. Returns the actions taken, for tests:
        [("nudge"|"fix"|"alert"|"realert", project, kind, key, text)]."""
        now = self.now()
        if self.stalls is None:
            self.stalls = self._load()
            # a project with a persisted stall was in queue mode before the restart: keep awake_dropped's grace
            self._queue = frozenset(k.split("\t")[0] for k in self.stalls)
        if self.runs is None:
            self.runs = self._load("runs")
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
        if self._watch_runs(recs, now, acts):
            changed = True
        if changed:
            self._save()
        return acts

    def _watch_runs(self, recs, now, acts):
        """Overdue runs in queue-mode `✦` panes (run watch spec §b); True when self.runs changed."""
        changed, seen, caps = False, set(), None
        for project, rec in recs.items():
            for r in rec.get("runs") or []:
                k = f"{r['window']}:{r['pid']}"
                seen.add(k)
                st = self.runs.get(k)
                if st is not None and st.get("cmd") != notify.flat_cmd(r["cmd"], 200):
                    del self.runs[k]   # the PID was reused by another command in this window: a fresh run
                    st = None
                    changed = True
                if st is None:
                    caps = caps or load_caps(self.caps_file)
                    cap = cap_for(r["cmd"], caps)
                    if r["elapsed_s"] <= cap:
                        continue
                    st = self.runs[k] = {"project": project, "first_at": now, "cpu": r["cpu_s"], "flat_count": 0,
                                         "pidset": sorted(r["pids"]),
                                         "killed_at": None, "cap_s": cap, "cmd": notify.flat_cmd(r["cmd"], 200)}
                    changed = True
                    text = notify.run_overdue_text(r["window"].removeprefix("✦ "), r["cmd"], r["elapsed_s"], cap)
                    self._alert(project, text, kind="run_overdue", key=k)
                    acts.append(("alert", project, "run_overdue", k, text))
                    continue
                if st.get("killed_at") is not None:
                    continue
                if r["cpu_s"] > st["cpu"] or sorted(r["pids"]) != st.get("pidset"):
                    # moving: CPU rose, or the subtree's PIDs changed (a worker exited, so its CPU left the sum)
                    st.update(cpu=r["cpu_s"], flat_count=0, pidset=sorted(r["pids"]))
                else:
                    st["flat_count"] += 1
                changed = True
                if st["flat_count"] >= FLAT_KILL:
                    self._kill(project, k, r, st, now, acts)
        for k in list(self.runs):
            st = self.runs[k]
            rec = recs.get(st.get("project"))
            if rec is None or (k not in seen and st.get("killed_at") is None):
                del self.runs[k]   # queue mode off, or the PID was gone before the kill: the stall clears
                changed = True
            elif st.get("killed_at") is not None:
                changed |= self._after_kill(rec, k, st, now, acts)
                settled = st.get("escalated") and st.get("told") and st.get("nudged_at") is not None
                if (k not in seen and settled) or now - st["killed_at"] > KILLED_KEEP_S:
                    del self.runs[k]
                    changed = True
        return changed

    def _kill(self, project, k, r, st, now, acts):
        try:
            self.kill(r["pid"], signal.SIGTERM)
        except ProcessLookupError:
            del self.runs[k]   # gone before the kill: the stall clears
            return
        except OSError as e:   # incl. PermissionError: not ours to kill, and no retry on every overview
            print(f"watch: kill {r['pid']} failed: {e}; dropped", file=sys.stderr, flush=True)
            if isinstance(e, PermissionError):
                del self.runs[k]
            return
        for q in r["pids"][1:]:
            try:
                self.kill(q, signal.SIGTERM)
            except OSError:
                pass
        n = r["elapsed_s"] // 60
        st.update(killed_at=now, pids=list(r["pids"]), pcmds={str(q): c for q, c in zip(r["pids"], r.get("pcmds") or [])}, escalated=False, told=None, nudged_at=None, min=n, window=r["window"])
        line = {"at": iso(now), "project": project, "window": r["window"], "pid": r["pid"], "cmd": st["cmd"],
                "elapsed_s": r["elapsed_s"], "cap_s": st["cap_s"]}
        try:
            self.kills_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.kills_file, "a") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"watch: kills.jsonl failed: {e}", file=sys.stderr, flush=True)
        acts.append(("kill", project, "run_overdue", k, st["cmd"]))

    def _after_kill(self, rec, k, st, now, acts):
        """The teammate line, the lead nudge and the KILL escalation of one killed run, each once; True when st changed."""
        changed, project = False, rec["project"]
        cmd80, n, window = notify.flat_cmd(st["cmd"], 80), st.get("min", 0), st.get("window") or k.rsplit(":", 1)[0]
        if st.get("told") is None:
            mate = next((a for a in rec.get("agents") or [] if a.get("window") == window), None)
            if mate is None:
                st["told"] = "no pane"   # the window has no claude pane any more: nobody to tell
                changed = True
            elif mate.get("state") in ("ready", "working"):   # at its prompt, or busy waiting on the killed command
                line = f"[Watch] killed {cmd80} after {n} min, no progress: report to the lead"
                try:
                    if self.tell(mate["pane"], line):
                        st["told"] = "typed"
                        changed = True
                        acts.append(("tell", project, "run_overdue", k, line))
                except Exception as e:   # noqa: BLE001 - try again on the next overview
                    print(f"watch: tell failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if st.get("nudged_at") is None and _lead_ready(rec):
            line = f"[Watch] killed {window.removeprefix('✦ ')}'s {cmd80} after {n} min, no progress: read its report."
            try:
                self.nudge(project, line)
                st["nudged_at"] = now
                changed = True
                acts.append(("nudge", project, "run_overdue", k, line))
            except Exception as e:   # noqa: BLE001
                print(f"watch: nudge failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if not st.get("escalated") and now - st["killed_at"] >= KILL_GRACE_S:
            # KILL only a PID this overview's sample shows with the command line seen at TERM time (a reused PID, or an
            # entry from an earlier board run, must never get a signal); an old entry gets none at all.
            cur = {}
            if now - st["killed_at"] <= KILL_GRACE_S * 6:
                for r in rec.get("runs") or []:
                    if f"{r['window']}:{r['pid']}" == k:
                        cur = dict(zip(r["pids"], r.get("pcmds") or []))
            for q in st.get("pids") or []:
                if q not in cur or cur[q] != (st.get("pcmds") or {}).get(str(q)):
                    continue
                try:
                    self.kill(q, 0)
                    self.kill(q, signal.SIGKILL)
                    acts.append(("kill9", project, "run_overdue", k, str(q)))
                except OSError:
                    pass   # gone
            st["pids"] = []
            st["escalated"] = True
            changed = True
        return changed
