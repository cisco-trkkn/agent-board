# Published: Claude Code Runtime Audit — Baseline 2026-10

- Claude Doc: https://claude.ai/artifact/MeJQKYt9sKa3JebeHwX7B3
- Published: 2026-10-25
- Source: `docs/superpowers/reports/runtime-audit/report.md` (this commit, `docs(audit): publish runtime audit`), after the Task 12 probe review (`probe-review.md`: 14 hold, 2 relabel, 0 drop)
- Toolkit sha: c24ce6b (`tools/audit/`; handoff figures from this run — every other figure from the earlier a58d81b run, see the report header)
- `audit-out` date: 2026-10-25 (`manifest.json generated 2026-10-25T02:24:06-04:00`; gate-log snapshot in `audit-out/2026-10-25/claude-hooks-snapshot/`)
- Doc sections: Summary · Current-state architecture · Baseline measurements · Efficiency audit · Hypotheses · Expanded ideas · Roadmap · Measurement plan; a `Sources` tab lists each section's provenance
- Charts in the Doc are drawn from `audit-out/2026-10-25/*.json` rows (peak context per lead session, injected-text medians, tool-output share, context at handoff); no images
