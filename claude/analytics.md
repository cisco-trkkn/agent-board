# Weekly findings: three recommendations

You are given one file, `stats.json`, whose path is on the last line of this message ("Stats file: ..."). Read that file
and nothing else. It holds the numbers of an agent-board team's recent work: trends against the previous window,
per-(tier, model) task statistics, flags, and coverage.

Return exactly three recommendations as one JSON array in a fenced json block, and nothing after it. Each item:

    {"title": "...", "change": "...", "expected_effect": "...",
     "evidence": [{"key": "<key path in stats.json>", "value": <that value>}], "risk": "..."}

Rules:

- Recommend changes to routing (which model a tier uses), plan granularity, review setup, team shape or workflow rules.
- Each recommendation is small and testable: one change someone can make in one sitting and check afterwards.
- Never recommend editing the orchestrator or its own prompt (this file), or any rule that governs how recommendations
  are made. If the numbers point there, recommend something nearby that you may.
- Prefer changes whose effect next week's numbers can show: name the key path that should move and in which direction.
- Cite only key paths that exist in stats.json, with their exact values. Key paths are dotted, for example
  `trends.median_usd_per_spec.current`; a list step is its index, for example `flags.overpowered.0.model_used`;
  `by_tier_model` keys contain `|`, for example `by_tier_model.standard|sonnet.tasks`. Copy the value as it is written in the
  file. Every cited key and value is checked by code against stats.json, and an item with one wrong is dropped.
- Cite at least one key per item. Do not cite a number you computed yourself.
- If `coverage` shows few tasks with cost data, say so in `risk` and prefer changes that need no cost data.
