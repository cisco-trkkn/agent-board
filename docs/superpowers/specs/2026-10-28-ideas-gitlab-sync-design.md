# Ideas → GitLab issues (one-way sync)

Date: 2026-10-28. Idea: inbox line 49 (2026-10-21 ticket tracker), Phase 1 of the spike
`docs/superpowers/spikes/2026-10-25-ticket-tracker.md`.

## Goal

A project's ideas backlog shows up as GitLab issues, so it can be ordered on a board and put into
iterations there. The local ideas file stays the source of truth. Sync runs one way only,
local → GitLab, and it never reads GitLab edits back into the file.

Out of scope: plan and task sync (spike Phase 2), pulling from GitLab, bulk import of existing ideas,
iterations, milestones and assignees (GitLab owns those), and GitHub Issues.

## Decisions (settled with the user)

| Question | Decision |
|---|---|
| First use | Ideas backlog (not plan execution) |
| Where issues go | Per-project mapping to a GitLab repo; an unmapped project stays local only |
| When an idea becomes an issue | Automatically, for every new idea in a mapped project (opting in is the consent) |
| Later changes pushed | Status **and** text edits |
| Content | Title only; detail lines stay local |
| Mechanism | Reconciler (diff the file against a last-pushed sidecar), not inline calls |

## Config

`~/.config/agent-board/gitlab.json` (optional; absent = feature off everywhere; `TC_GITLAB_CONF` overrides
the path for tests):

```json
{"master-gcp-repo": {"repo": "trkkn/trkkn-na/master-gcp-repo", "since": "2026-10-28"}}
```

- `repo`: the GitLab project path, passed to `glab -R`.
- `since`: `YYYY-MM-DD`. Only ideas whose timestamp is on or after this date are ever created as issues.
  Older ideas never get an issue, so no bulk import happens. Required: a mapping without `since` is
  rejected with an error, not defaulted.
- Nothing in agent-board writes this file. It is documented in `docs/CUSTOMIZATION.md`.

## Data model

**Token on the idea line.** An idea that has an issue carries ` · gl#<iid>` at the end of its text, before
any ` → …` suffix the lead or a move appends:

```
- [ ] 2026-10-28 10:00 · add retries to the export · gl#12
- [x] 2026-10-28 10:00 · add retries to the export · gl#12 → docs/superpowers/specs/…
- [-] 2026-10-28 10:00 · add retries to the export · gl#12 → moved to other-project
```

- `load()` strips the token out of `text` into a new `issue` field (int or `None`), the same way it strips
  `→ moved to`. `key` stays the raw `ts · text` of the line, token included, so the stale-key model is
  unchanged.
- `edit()` keeps the token: the user edits the visible text, and the token is put back on.
- `move()` does not copy the token to the target; the target project gets its own issue if it is mapped.
- The token regex is anchored: ` · gl#(\d+)(?= → |$)`. A `gl#` elsewhere in the idea text is left alone.

**Sidecar** `<ideas_dir>/<project>.gitlab.json`: what was last pushed for each iid.

```json
{"12": {"ts": "2026-10-28 10:00", "title": "add retries to the export", "state": "open"}}
```

`state` is `open`, `closed-done`, `closed-dropped` or `closed-moved`. Writes are atomic
(tmp + `os.replace`) and happen under the ideas file's existing `<file>.lock`.

## Sync: `ideas.py sync --project P`

1. No mapping for P → exit 0 silently. `glab` not on PATH → exit 0, plus one line in the status file
   (below).
2. Take a separate non-blocking lock, `<file>.sync.lock`. If another sync holds it, exit 0: that run will
   pick up whatever this one would have seen.
3. Load the ideas and the sidecar. For each idea, in file order:
   - **Create:** status open, no token, `ts ≥ since`.
     1. Search first: `glab issue list` in the repo for the description marker
        `<!-- agent-board:<project>:<ts>#<n> -->`, across open and closed issues. `n` is the 1-based position
        among all lines in the file with the same `ts`, in file order, whatever their status; ideas are
        never deleted, so `n` is stable across edits.
     2. If an issue is found, adopt its iid. Otherwise create one: title = text, label `idea`,
        description = the marker line only.
     3. Write the token to the line through `_rewrite` (under the lock, by key). If the key is stale,
        skip the idea; the next pass handles it.
     4. Only then update the sidecar.
   - **Retitle:** token present, sidecar title ≠ current text → update the issue title, then the sidecar.
   - **Taken up `[x]`:** token present, sidecar state `open` → close the issue, then add a note
     `Taken up → <spec suffix>`, set state `closed-done`.
   - **Dropped `[-]`:** with no `→ moved to`: add label `not-planned`, close, set `closed-dropped`.
     With `→ moved to X`: close, then add a note `Moved to X`, set `closed-moved`. GitLab has no close
     reason, so the `not-planned` label stands in for one.
   - **Restored `[-]`→`[ ]`** (the board's restore): token present, sidecar state `closed-dropped` →
     reopen, remove the `not-planned` label, set `open`.
4. Each issue's push runs on its own. One failure records the error and the loop moves on to the next idea;
   the sidecar is not updated for the failed one, so the next pass retries it. A 429, or
   `Ratelimit-Remaining` 0, stops the pass.
5. Write the status file `<ideas_dir>/<project>.gitlab-status.json`: `{"at": …, "ok": bool, "error": "…",
   "pending": n}`.

Exact `glab` subcommands and flags (`issue create/list/update/close/note`, `--yes`, the JSON output
flag) are pinned during planning by one real read-only probe, per `test-driven-development-extras`.

## Triggers

- **After every ideas.py write** (`add`, `edit`, `set_status`, `move`; the CLI and the board's server
  routes): spawn `ideas.py sync --project P` detached (`start_new_session=True`, stdio to `/dev/null`).
  Only when P is mapped, so unmapped projects never fork. For `move`, both projects are synced. Capturing
  an idea never waits on GitLab.
- **Board server:** a daemon thread runs `sync` every 60s for each mapped project. This catches the
  lead's direct file edits (`[x] → spec`, which go through no code path) and retries failures.
- **Manual:** `ideas.py sync --project P` from a shell, for debugging.

## Board

The Ideas box shows a muted `GitLab: #12` link on each line that has a token, built from `repo` plus the
iid. It shows a one-line warning `GitLab sync: <error>` when the status file has `ok: false`. The
`/ideas` JSON gains `issue` per idea and `gitlab: {repo, ok, error}` per project. No other UI changes.

## Error handling

| Case | Behaviour |
|---|---|
| Config absent or project unmapped | No-op, no fork |
| Config invalid JSON or missing `since` | Sync exits 2 and the status file holds the error; ideas capture is unaffected |
| `glab` missing or not logged in | Status file error; each pass retries |
| Create succeeded, token write lost (crash, stale key) | The next pass's marker search adopts the existing issue: no duplicate |
| Two syncs at once | The second exits on the non-blocking sync lock |
| Rate limit | The pass stops; the next one continues |

## Testing

- A fake `glab` on PATH (a script that logs argv as JSON lines and returns canned output) in
  `board/tests/test_ideas_gitlab.py`. It covers create, adopting via the marker, retitle, the three closes,
  restore, `since` filtering, an unmapped project making no call, a failure leaving the sidecar
  unchanged, the stale key on token write, and the sync lock.
- Parsing: the token is stripped into `issue`, `edit` keeps it, `move` drops it, and a `gl#` in the middle
  of the text is not matched.
- One real read-only run of `glab issue list -R <mapped repo> --output json` (or the probed equivalent)
  pins the JSON shape that the fake returns. Create, close and update are not run for real in tests.
- The isolation seam: `TC_IDEAS_DIR`, `TC_GITLAB_CONF` and PATH are set before any RED run, so no test
  can reach the real config or the real `glab`.
- An e2e check after the merge (a user gate): map a project in the real config, add one idea, see the
  issue, mark it dropped, see it closed with `not-planned`.

## Risks

- Client-confidential titles: the mapping is opt-in per project, title only, and nothing is ever pushed
  from the shared `francisco_ruiz` inbox unless the user maps it.
- Notification noise: only ideas after `since` are created, and edits only change titles.
- The tier is unconfirmed: nothing here needs Premium (no epics, iterations or scoped labels).
