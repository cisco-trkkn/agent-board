# ctxsize fixture: lead.jsonl

Cut on 2026-11-20 with `tools/audit/capture_fixture.py` (message text replaced, paths redacted).

Sources (basenames):
- lead transcript `a364e07d-0932-4636-b113-df5eb607a886.jsonl`:
  `python3 tools/audit/capture_fixture.py a364e07d-0932-4636-b113-df5eb607a886.jsonl <scratch>/lead_cap.jsonl --max-lines 400`
  (captured line numbers 1, 43, 44, 56, 57, 59, 74, 93, 98)
- subagent transcript `agent-a9b4a62fb4c984e56.jsonl` (under `4ab7bd48-bfec-473e-a725-67e6b5abbb0b/subagents/`):
  `python3 tools/audit/capture_fixture.py agent-a9b4a62fb4c984e56.jsonl <scratch>/sub2_cap.jsonl --max-lines 400`
  (captured line 41, the sidechain assistant line)

Hand edit: fixture line 10 is captured line 98 of the lead capture (request BKMjFb) with its `message.usage` key
deleted, because no captured assistant line lacked usage. Nothing else was edited. Lines are in the order below,
not captured order; fixture line 9's timestamp is earlier than line 10's by design of the pick, and line 7 is the sidechain.

Fixture lines (context = input + cache_read + cache_creation; total = context + output_tokens):

| line | requestId (last 6) | sidechain | timestamp (UTC) | context | output | total |
|------|-----|-----|-----|-----|-----|-----|
| 1 | | | fixture-header | | | |
| 2 | ZAq3kU | no | 2026-11-20T23:16:43.157Z | 63194 | 209 | 63403 |
| 3 | ZAq3kU | no | 2026-11-20T23:16:43.804Z | 63194 | 209 | 63403 |
| 4 | yLo2qP | no | 2026-11-20T23:16:49.083Z | 67099 | 379 | 67478 |
| 5 | yLo2qP | no | 2026-11-20T23:16:49.672Z | 67099 | 379 | 67478 |
| 6 | yLo2qP | no | 2026-11-20T23:16:51.375Z | 67099 | 379 | 67478 |
| 7 | xUyN2R | yes | 2026-11-05T05:58:22.275Z | 95453 | 2798 | 98251 |
| 8 | ysKf6d | no | 2026-11-20T23:17:03.086Z | 73748 | 514 | 74262 |
| 9 | CtMmwY | no | 2026-11-20T23:17:12.145Z | 75890 | 239 | 76129 |
| 10 | BKMjFb | no | 2026-11-20T23:17:16.833Z | no usage | | |

Main-thread turns (last line of each requestId): ZAq3kU ts 1795216603.804 ctx 63194 total 63403;
yLo2qP ts 1795216611.375 ctx 67099 total 67478; ysKf6d ts 1795216623.086 ctx 73748 total 74262;
CtMmwY ts 1795216632.145 ctx 75890 total 76129. Peak 75890, last 75890 (line 10 has no usage).
