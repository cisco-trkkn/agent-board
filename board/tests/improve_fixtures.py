"""Fixtures for the improve loop's tests: a scratch engine DB, run records and a run log."""
import json
import sqlite3
from pathlib import Path

EVENTS = ("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, spec TEXT, job TEXT, "
          "kind TEXT, detail TEXT)")   # engine/lib/engine/db.js:16


def engine_db(tmp, project="proj"):
    """<tmp>/<project>.sqlite with the engine's real events columns; returns its path."""
    p = Path(tmp) / f"{project}.sqlite"
    c = sqlite3.connect(p)
    c.execute(EVENTS)
    c.commit()
    c.close()
    return p


def run(spec, **kw):
    """A run record. Engine-run records carry a non-null budget, lead-run ones None (no runner field)."""
    rec = {"kind": "run", "spec": spec, "outcome": "merged", "tasks": 3, "tokens": {"total": 1000},
           "variants": [], "budget": None, "batch": "b1", "ended_at": "2026-11-25T00:00:00Z"}
    rec.update(kw)
    return rec


def write_log(tmp, lines):
    p = Path(tmp) / "runs.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in lines))
    return p
