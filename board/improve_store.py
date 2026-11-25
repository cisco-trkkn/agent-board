"""improve_store: the supervised improvement loop's proposals table in the engine database (spec 2026-11-16 §5).
Every state change is one `improve` row in the engine's events table, written in the same transaction as the proposals
update, so `engine rebuild --check` can replay it. Protected (docs/superpowers/improve/protected.txt).
Test: tests/test_improve_store.py."""
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_class  # noqa: E402
import tc_env  # noqa: E402

# Byte-identical to the statement in engine/lib/engine/db.js SCHEMA (a test compares them).
PROPOSALS_SQL = ("CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, source TEXT, kind TEXT, target TEXT, patch TEXT, "
                 "evidence TEXT, class TEXT, state TEXT, outcome TEXT, created_at REAL, updated_at REAL, trial_started_at REAL, "
                 "trial_len INTEGER DEFAULT 5, commit_sha TEXT, dedupe_key TEXT UNIQUE, title TEXT, shrinks_reads INTEGER DEFAULT 0, "
                 "reason TEXT);")
TRANSITIONS = {
    "proposed": {"trial", "rejected", "drafted"},
    "trial": {"kept", "reverted", "awaiting_you", "rejected"},
    "awaiting_you": {"promoted", "rejected", "trial"},
    "kept": {"reverted"},
    "promoted": {"reverted"},
    "drafted": {"rejected", "promoted"},
}
EVIDENCE_TYPES = {"run", "task", "event", "ledger", "report", "hook"}
SETTABLE = {"trial_started_at", "trial_len", "commit_sha", "title", "outcome", "shrinks_reads"}
RETIRE_CAP = 5
DAY = 86400


class ImproveError(Exception):
    pass


def engine_dir():
    return Path(os.environ.get("TC_ENGINE_DIR") or Path.home() / ".local" / "state" / "agent-board" / "engine")


def patches_dir(project):
    return tc_env.state_dir() / "improve" / project / "patches"


class Store:
    def __init__(self, project, now=time.time):
        self.project, self.now = project, now
        self.path = engine_dir() / f"{project}.sqlite"
        err = ImproveError(f"improve: no engine database at {self.path}")
        if not self.path.exists():
            raise err
        c = self._conn()
        try:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                raise err
            c.execute(PROPOSALS_SQL)
            c.commit()
        finally:
            c.close()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    def _append_event(self, c, row, old, reason, extra=None):
        detail = {"rows": [{"table": "proposals", "row": dict(row)}], "proposal": row["id"], "from": old, "to": row["state"],
                  "reason": reason, "kind": row["kind"]}
        detail.update(extra or {})
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, NULL, NULL, 'improve', ?)",
                  (self.now(), json.dumps(detail)))

    def get(self, pid):
        c = self._conn()
        try:
            r = c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
        finally:
            c.close()
        return dict(r) if r else None

    def list(self, state=None):
        c = self._conn()
        try:
            rows = c.execute("SELECT * FROM proposals" + (" WHERE state = ?" if state else ""), (state,) if state else ()).fetchall()
        finally:
            c.close()
        return sorted((dict(r) for r in rows), key=lambda r: int(r["id"][1:]))

    def _retire_count(self, c, tick):
        if tick is not None:
            q = "SELECT detail FROM events WHERE kind='improve'"
            return sum(1 for (d,) in c.execute(q) if (j := json.loads(d)).get("tick") == tick and j.get("kind") == "retire"
                       and j.get("from") is None)
        q = "SELECT detail FROM events WHERE kind='improve' AND ts > ?"
        return sum(1 for (d,) in c.execute(q, (self.now() - DAY,)) if (j := json.loads(d)).get("tick") is None
                   and j.get("kind") == "retire" and j.get("from") is None)

    def insert(self, source, kind, target, patch, evidence, outcome=None, shrinks_reads=False, title=None, tick=None,
               state="proposed", reason=None):
        if state not in ("proposed", "drafted"):
            raise ImproveError(f"improve: bad initial state {state}")
        key = hashlib.sha256(f"{source}\0{target}\0{hashlib.sha256((patch or '').encode()).hexdigest()}".encode()).hexdigest()
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                ex = c.execute("SELECT id FROM proposals WHERE dedupe_key = ?", (key,)).fetchone()
                if ex:
                    c.execute("ROLLBACK")
                    return ex["id"]
                if not any(isinstance(e, dict) and e.get("type") in EVIDENCE_TYPES for e in (evidence or [])):
                    raise ImproveError("no deterministic evidence")
                if kind == "retire" and self._retire_count(c, tick) >= RETIRE_CAP:
                    raise ImproveError("retire cap")
                text = None
                if target:
                    f = improve_class.REPO / target
                    if f.is_file():
                        text = f.read_text(errors="replace")
                cls = improve_class.derive(kind, target, patch, source=source, target_text=text)
                n = 1 + max((int(r[0][1:]) for r in c.execute("SELECT id FROM proposals")), default=0)
                pid, now = f"P{n}", self.now()
                c.execute("INSERT INTO proposals(id, source, kind, target, patch, evidence, class, state, outcome, created_at, "
                          "updated_at, dedupe_key, title, shrinks_reads, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (pid, source, kind, target, patch, json.dumps(evidence), cls, state, outcome, now, now, key, title,
                           1 if shrinks_reads else 0, reason))
                row = c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
                self._append_event(c, row, None, "insert", {"tick": tick})
                if patch is not None:
                    d = patches_dir(self.project)
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"{pid}.diff").write_text(patch)
                c.execute("COMMIT")
                return pid
            except BaseException:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise
        finally:
            c.close()

    def transition(self, pid, to, reason, **fields):
        bad = set(fields) - SETTABLE
        if bad:
            raise ImproveError(f"improve: cannot set {sorted(bad)}")
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                r = c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
                if not r:
                    raise ImproveError(f"improve: no proposal {pid}")
                if to not in TRANSITIONS.get(r["state"], ()):
                    raise ImproveError(f"improve: {pid} cannot go {r['state']} -> {to}")
                sets = {"state": to, "reason": reason, "updated_at": self.now(), **fields}
                c.execute(f"UPDATE proposals SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), pid))
                new = c.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
                self._append_event(c, new, r["state"], reason)
                c.execute("COMMIT")
                return dict(new)
            except BaseException:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise
        finally:
            c.close()
