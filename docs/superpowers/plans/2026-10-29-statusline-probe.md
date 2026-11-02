# statusLine probe: the JSON Claude Code 2.1.312 passes to a statusLine command

Read-only record of one real interactive session, captured 2026-10-29. Fixture:
`claude/statusline/tests/fixtures/statusline-sample.json` (one real payload, scrubbed). Consumers: Task 5
(the tap script's field names) and Task 7 (the Usage tab).

## How captured

- Claude Code `2.1.312` (`claude --version`), model `--model haiku` (Haiku 5.5, context window
  1,000,000). Every field below appeared on Haiku; no second model was needed.
- A scratch project under this session's scratchpad (`git init`-ed), with `.claude/settings.local.json`
  as the only setting touched. `~/.claude/settings.json` has no `statusLine` key and was not written
  (checked before and after: `python3 -c "…print(d.get('statusLine'))"` → `None`).

  ```json
  {"statusLine": {"type": "command", "command": "python3 <scratchpad>/capture/capture.py", "padding": 0}}
  ```

  `capture.py` reads stdin, appends `<epoch>\t<payload>` to `payloads.ndjson`, and prints
  `probe-statusline` (which showed in the footer, proving the setting was live).
- Launched in a scratch tmux server: `~/.local/bin/tmux -L probe-sl-<pid> -f /dev/null new-session -d
  -s probe -c <scratch> "claude --model haiku"`. The folder-trust prompt was answered there (`Down`,
  `Enter`: "Yes, I trust this folder"); no login prompt appeared (the user's existing claude.ai Max
  login was used, so `rate_limits` is the subscriber form). The live tmux server was only read
  (`list-sessions`, to confirm no `probe` session on it).
- Turns run: turn 1 `Reply with the single word ok and nothing else.` (one API call); a 60 s idle wait;
  turn 2 `Use the Bash tool to run ls -a here, then … pwd, then reply with the single word done.`
  (three API calls: two tool uses and the final answer). Then `/exit`; the pane's shell ended with it
  and the scratch server was gone (`list-sessions` → `no server running`), confirmed by `kill-server`.
- Five payloads were captured. The fixture is the last one (after turn 2, the most complete: cache
  reads, accumulated cost, `rate_limits`). Scrubbing changed only paths, keeping type and shape:
  `transcript_path` → `/home/user/.claude/projects/-home-user-probe/<session_id>.jsonl`, `cwd` and
  `workspace.*_dir` → `/home/user/probe`, `scratchpad_dir` → `/tmp/claude-1000/-home-user-probe/
  <session_id>/scratchpad`. The project-dir encoding (`-home-user-probe`) stays consistent with
  `cwd`. `session_id` is the real UUID of the closed throwaway session (not secret-shaped; keeps the
  transcript join real). Checks: the fixture parses (`json.load` → rc 0); `grep -c '/Users/'` → 0;
  no `/private/tmp`, no email-shaped string, no user name.

## Fields

Each row cites the fixture (`statusline-sample.json`). "absent" = not in any of the five payloads.
Top-level keys in the sample: `session_id`, `transcript_path`, `cwd`, `scratchpad_dir`, `prompt_id`,
`effort`, `session_name`, `model`, `workspace`, `version`, `output_style`, `cost`, `context_window`,
`exceeds_200k_tokens`, `prompt_cache`, `fast_mode`, `thinking`, `rate_limits` (18 keys).

| Figure | JSON path | Sample value | Notes |
|---|---|---|---|
| Context-window size | `context_window.context_window_size` | `1000000` | Integer tokens. Present from the first payload (before any API call). |
| Used tokens | `context_window.total_input_tokens` | `41459` | Tokens in the context after the latest API response, input side: equals `current_usage.input_tokens + cache_creation_input_tokens + cache_read_input_tokens` (2 + 315 + 41142 = 41459 in the sample). `total_output_tokens` (`80`) is the latest response's output, not in the percentage. |
| Used tokens, by component | `context_window.current_usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` | `2, 80, 315, 41142` | `null` before the first API call (payload 0) and, per the docs, after `/compact` until the next call. |
| Used % | `context_window.used_percentage` | `4` | Number, `null` before the first API call (payload 0). Input-only formula (`total_input_tokens / context_window_size`, 41459/1e6 → 4). Integer in all five captures; the docs' example shows a decimal, so read it as a number, not an int. `remaining_percentage` is `96`. |
| Model id | `model.id` | `"claude-haiku-5-5"` | Present from the first payload. |
| Model display name | `model.display_name` | `"Haiku 5.5"` | |
| Effort | `effort.level` | `"medium"` | String. The footer showed `◐ medium · /effort`. |
| Session id | `session_id` | `"a6ade69c-e107-4020-9afb-0549650f396f"` | Same UUID as the transcript file name and its `sessionId` lines (see Call timing). |
| Cost | `cost.total_cost_usd` | `0.012401…` | Client-side list-price estimate, cumulative for the session; `0` before the first API call. Siblings: `total_duration_ms`, `total_api_duration_ms`, `total_lines_added`, `total_lines_removed`. |
| 5-hour plan window | `rate_limits.five_hour.used_percentage`, `.resets_at` | `63`, `1793266200` | Percent 0–100 and reset time (epoch seconds). **Exposed locally** on this claude.ai Max login. Absent in payload 0 (before the first API response); present in payloads 1–4. |
| Weekly plan window | `rate_limits.seven_day.used_percentage`, `.resets_at` | `93`, `1793469600` | Same shape as `five_hour`. `rate_limits.spend_limit` (gateway spend limits) did not appear: absent on a subscriber login. |

Other fields of interest for the board: `transcript_path` (absolute path of the session's
`.jsonl`, the file `board/usage.py` indexes), `cwd` and `workspace.project_dir`, `prompt_id` (UUID of
the current user prompt; absent in payload 0), `session_name` (Claude's auto-title, `"Single word
reply"`; absent in payload 0), `prompt_cache` (`warm`, `hit_ratio`, `expires_at`, …; absent in
payload 0), `exceeds_200k_tokens` (`false`), `fast_mode` (`false`), `thinking.enabled` (`true`),
`version` (`"2.1.312"`), `output_style.name` (`"default"`). Absent in every payload: `vim`, `agent`,
`pr`, `worktree`, `workspace.git_worktree`, `workspace.repo` (the scratch repo has no `origin`).

Tap-script consequences (Task 5): `rate_limits`, `prompt_cache`, `prompt_id` and `session_name` are
optional keys; `current_usage`, `used_percentage` and `remaining_percentage` can be `null`; everything
else above was present in all five payloads.

## Call timing

Observed (capture timestamps, seconds since the first payload; the five payloads of this session):

| # | t | Trigger | Evidence |
|---|---|---|---|
| 0 | 0.0 | Session start, right after the trust prompt | No `prompt_id`, `cost.total_cost_usd` 0, `current_usage` null, no `rate_limits`. |
| 1 | +20.4 | Turn 1's assistant message (`ok`), ~4 s after the prompt was sent | `prompt_id` 45ac668d…, `total_input_tokens` 41075, `rate_limits` appears. |
| – | +42 … +124 | 60 s idle at the prompt | No payload: the count stayed at 2. |
| 2 | +126.7 | Turn 2, first assistant message (the `ls -a` tool use), ~3 s after the prompt | `prompt_id` 89ce6f1a…, `total_output_tokens` 20; `cost` still turn 1's value. |
| 3 | +129.8 | Turn 2, second assistant message (the `pwd` tool use) | `total_output_tokens` 148, cost 0.01189. |
| 4 | +131.8 | Turn 2, final assistant message (`done`) | `total_output_tokens` 80, cost 0.01240, `cache_read_input_tokens` 41142. |
| – | exit | `/exit` | No payload. |

So Claude Code calls the statusLine once at session start and then once per assistant message
(one per API response, so a tool-using turn produces several calls, one every few seconds), not on a
timer: nothing during 60 s idle and nothing at exit. The docs for this version list the same triggers
plus `/compact` finishing, a permission-mode change, vim-mode toggles, a change to the `command`
setting, a `refreshInterval` timer when configured, and the moments a received `rate_limits.*.resets_at`
or a warm `prompt_cache.expires_at` passes; updates are debounced at 300 ms, and an in-flight script is
cancelled when a new update triggers (so the tap must write atomically and finish fast). For the board
this means a tap file is at most one API response stale while a session is active and frozen while it
idles: `received_at` (added by the tap) dates the figures, and an idle session's last payload is still
its current context state.

Session-id join: yes. `session_id` is the UUID that names the transcript file (`transcript_path`
ends in `<session_id>.jsonl`) and every line of that transcript carries it as `sessionId` (59 of 59
lines in the probe session: `grep -o '"sessionId":"…"' | sort | uniq -c`). `board/usage.py` keys its
`calls` and `cost_state` rows by that same `sessionId` (`usage.py:73,110`), so `<state_dir>/statusline/
<session_id>.json` joins the board's rows on `session_id` with no translation. Note that the statusLine
reports the main conversation only: subagent transcripts (`…/subagents/*.jsonl`) never trigger it,
and `cost.total_cost_usd` is the session's client-side estimate, not a per-call figure.

## Sample

`claude/statusline/tests/fixtures/statusline-sample.json`, payload 4 scrubbed as described above:

```json
{
  "session_id": "a6ade69c-e107-4020-9afb-0549650f396f",
  "transcript_path": "/home/user/.claude/projects/-home-user-probe/a6ade69c-e107-4020-9afb-0549650f396f.jsonl",
  "cwd": "/home/user/probe",
  "scratchpad_dir": "/tmp/claude-1000/-home-user-probe/a6ade69c-e107-4020-9afb-0549650f396f/scratchpad",
  "prompt_id": "89ce6f1a-…",
  "effort": {"level": "medium"},
  "session_name": "Single word reply",
  "model": {"id": "claude-haiku-5-5", "display_name": "Haiku 5.5"},
  "workspace": {"current_dir": "/home/user/probe", "project_dir": "/home/user/probe", "added_dirs": []},
  "version": "2.1.312",
  "output_style": {"name": "default"},
  "cost": {"total_cost_usd": 0.0124013, "total_duration_ms": 149296, "total_api_duration_ms": 6600,
           "total_lines_added": 0, "total_lines_removed": 0},
  "context_window": {
    "total_input_tokens": 41459, "total_output_tokens": 80, "context_window_size": 1000000,
    "current_usage": {"input_tokens": 2, "output_tokens": 80, "cache_creation_input_tokens": 315,
                      "cache_read_input_tokens": 41142},
    "used_percentage": 4, "remaining_percentage": 96
  },
  "exceeds_200k_tokens": false,
  "prompt_cache": {"warm": true, "caching_observed": true, "ttl": "1h", "expires_at": 1793259716,
                   "requests": 3, "misses": 1, "…": "…"},
  "fast_mode": false,
  "thinking": {"enabled": true},
  "rate_limits": {
    "five_hour": {"used_percentage": 63, "resets_at": 1793266200},
    "seven_day": {"used_percentage": 93, "resets_at": 1793469600}
  }
}
```

(Abridged here for reading: `prompt_id` and `prompt_cache` are complete in the fixture file, and the
numbers above are the fixture's.) The first payload of a session (before any API call), saved scrubbed
as `claude/statusline/tests/fixtures/statusline-sample-start.json`, differs: no
`prompt_id`, `session_name`, `prompt_cache` or `rate_limits`; `cost.total_cost_usd` 0;
`context_window.total_input_tokens` 0, `current_usage`, `used_percentage` and `remaining_percentage`
`null`.
