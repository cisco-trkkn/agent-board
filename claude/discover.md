# Opportunity discovery: rank the candidates

You read `collected.json` in the current directory: candidate findings from one project's tests, run
records, ledgers, code, dependencies and ideas. Each candidate has `key`, `title`, `signal`, `count` and
an `evidence` list. You may Read the files the evidence names. You change nothing.

Pick the few candidates that are most worth the user's attention, and rank them. Judge value to the
user's work: time saved, failures avoided, cost. A tidier repo is not a reason by itself. Prefer a
finding that repeats (high `count`) and that costs the user something every week over a one-off nit.

Rules:
- Never propose an item that changes `claude/orchestrator.md`, the worker rules (`claude/worker.md`) or
  `claude/discover.md`. Drop those candidates.
- Use only keys that appear in `collected.json`. Do not invent candidates.
- `evidence_refs` are indexes into that candidate's own `evidence` list, as integers.
- `why` says in one or two sentences what it costs the user now and what fixing it buys.
- `risk` says in one sentence what could go wrong if it is done.
- Answer with at most 5 items; fewer, or none, when nothing is worth the user's time.

Answer with JSON only, no prose and no code fence, in exactly this shape:

{"items": [{"key", "title", "why", "expected_value": "high|medium|low", "effort": "S|M|L", "risk", "evidence_refs": [int]}]}

`key`, `title`, `why` and `risk` are strings; `expected_value` is one of high, medium, low; `effort` is
S, M or L (small, medium, large).
