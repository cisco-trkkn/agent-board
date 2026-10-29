# Ideas → GitLab sync: real-state dry run (Task 5)

Run on 2026-10-28 from branch `feat/ideas-gitlab-sync` at 45dd5a4 (titles capped at 255 characters) against the user's real, aged `~/.local/state/agent-board/ideas/master-gcp-repo.md` and the real GitLab repo `trkkn/trkkn-na/master-gcp-repo`. Read-only: `--dry-run` issues only GET calls through real `glab api`. This is the second run; the first, before the cap, showed two titles over GitLab's 255-character limit.

## Command

```
env -u TC_IDEAS_DIR PATH=<scratch>/shimbin:$PATH TC_GITLAB_CONF=<scratch>/gitlab.json python3 -I board/ideas.py sync --project master-gcp-repo --dry-run
```

Scratch config (`<scratch>/gitlab.json`; `~/.config/agent-board/gitlab.json` does not exist and was not created):

```
{"master-gcp-repo":{"repo":"trkkn/trkkn-na/master-gcp-repo","since":"2026-10-22"}}
```

`<scratch>/shimbin/glab` is a call tracer: it appends its arguments as one line to `<scratch>/glab-calls.log`, then `exec`s the real `/Users/francisco.ruiz/.local/bin/glab`.

## Full dry-run output (uncapped, exit code 0, stderr empty)

```
create "Task 6 follow-up: mougii e2e runbook phase 3 and phase 6 step a assume a deployed workload; with OFFBOARD_PIPELINE_DELETION=all and zero modules no 'Deleting secret' line prints, so test_offboard_trace_deletes_every_catalog_secret cannot pass. Also remov…"
create "Task 6 follow-up: tools/gitlab-trigger.sh is curl-only; add a glab fallback."
create "Task 6 follow-up: landing-zone stage code (landing-zone/fast/stages/**, ci/actions/landing-zone/scripts/**) has no release path; a change limited to it fails prod-promotion-gate like !330 did (the !331 exemption covers only tests and mock records)."
create "Task 6 follow-up: migrate mougii-fe deploy_prod."
create "Task 6 follow-up: deferred minors from !318 and !322 (listed in those MR descriptions); drop the WIF retry once the Fabric pin is a23ea2ec; export mougii_ci_settings in the shared contract only if a job reads it."
create "if this solution was expanded to handle clients all over the globe. how does security, data privacy, gdpr requirements, documentation gaps, auditability queries/data"
create "connector framework cleanup MR: remove pipelines/bq-to-ga4/moved.tf once tenant states are confirmed free of bq-to-ga4 (or applied past the refit); delete date_utils.py + test; move generic fakes out of monorail_common tests package; deferred minors list…"
```

## Actions

- create "Task 6 follow-up: mougii e2e runbook phase 3 and phase 6 step a assume a deployed workload; with OFFBOARD_PIPELINE_DELETION=all and zero modules no 'Deleting secret' line prints, so test_offboard_trace_deletes_every_catalog_secret cannot pass. Also remov…"
- create "Task 6 follow-up: tools/gitlab-trigger.sh is curl-only; add a glab fallback."
- create "Task 6 follow-up: landing-zone stage code (landing-zone/fast/stages/**, ci/actions/landing-zone/scripts/**) has no release path; a change limited to it fails prod-promotion-gate like !330 did (the !331 exemption covers only tests and mock records)."
- create "Task 6 follow-up: migrate mougii-fe deploy_prod."
- create "Task 6 follow-up: deferred minors from !318 and !322 (listed in those MR descriptions); drop the WIF retry once the Fabric pin is a23ea2ec; export mougii_ci_settings in the shared contract only if a job reads it."
- create "if this solution was expanded to handle clients all over the globe. how does security, data privacy, gdpr requirements, documentation gaps, auditability queries/data"
- create "connector framework cleanup MR: remove pipelines/bq-to-ga4/moved.tf once tenant states are confirmed free of bq-to-ga4 (or applied past the refit); delete date_utils.py + test; move generic fakes out of monorail_common tests package; deferred minors list…"

## Counts

- Dry-run `create` lines: 7
- Independent count, `grep -cE '^- \[ \] 2026-10-(2[2-9]|3[01])' master-gcp-repo.md`: 7
- Equal. adopt lines: 0. Lines other than create/adopt/no: 0.
- The inbox has 9 open ideas; the 2 older than 2026-10-22 are before `since` and skipped.
- Same-minute ideas: **four** open ideas at `2026-10-22 17:52` (the brief said three), plus one at 17:53. All four give distinct creates (marker ordinals `#1`..`#4`), none adopted.

## Title length

Create title lengths in characters, in output order: 255, 76, 248, 48, 212, 165, 255. The longest is 255, which is GitLab's limit. The two ideas whose text was 289 and 334 characters (the first and last creates, in that order) are now exactly 255 characters and end in "…" (`Also remov…` and `minors list…`). No other title was shortened.

## GET-only call trace

Every `glab` invocation of the run, from `<scratch>/glab-calls.log`:

```
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-22 17:52#1 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-22 17:52#2 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-22 17:52#3 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-22 17:52#4 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-22 17:53#1 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-26 13:10#1 --> -f in=description -f state=all -f per_page=20
api -i -X GET projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues -f search=<!-- agent-board:master-gcp-repo:2026-10-27 16:02#1 --> -f in=description -f state=all -f per_page=20
```

- `wc -l` of the log: 7
- `grep -c -- '-X GET'` of the log: 7 (equal)
- `grep -vc -- '-X GET'` of the log: 0

One marker search per create, and nothing else. The searches all returned no match, as expected: no issue on the real instance carries an agent-board marker yet.

## Nothing written

- sha256 of the ideas file before: `fca1f4c0be276df44fabee34b5f0f526f52468893a0523860cea841f3c7c67e4`
- sha256 of the ideas file after:  `fca1f4c0be276df44fabee34b5f0f526f52468893a0523860cea841f3c7c67e4`
- Identical.
- `ls ~/.local/state/agent-board/ideas/master-gcp-repo.gitlab*.json` before and after: no matches. No token, sidecar or status file is written.
- Lock files do appear: the dry run takes and touches `master-gcp-repo.md.sync.lock` (a zero-byte file; its mtime changed, and `ls -l` of the ideas dir before and after differs only in that mtime). The ideas file and all other files were untouched.

## Limits of this run

An empty marker search on the real instance is only proven by the user gate's adopt step: here the search returned nothing for every idea, which cannot distinguish "no issue carries the marker" from "the search does not find markers". Only the gate's adopt step (below), which removes the token from a line whose issue exists and then syncs, shows the sync adopting the issue instead of creating a duplicate. A plain second sync does not: the token is already written, so it skips the search.

## User gate after merge

Copied from the spec's e2e check, to be run by the user once merged:

1. Map one project for real: create `~/.config/agent-board/gitlab.json` with that project's `repo` and `since`.
2. Add one idea to that project's inbox.
3. See the issue appear in the GitLab repo.
4. Drop the idea.
5. See the issue closed with `not-planned`.
6. Adopt step (proves no duplicate on a lost token): delete ` · gl#N` from the idea line by hand. `python3 board/ideas.py sync --project P --dry-run` must print `adopt #N "…"`, not `create`. Then a real `python3 board/ideas.py sync --project P` writes `gl#N` back, and the repo still has exactly one issue for that idea.
7. Restore the dropped idea (board restore): the issue reopens and `not-planned` is removed.
8. Mark an idea `[x] → <spec>`: the issue closes with a "Taken up" note.

### Merge-gate checklist (inputs the agents cannot read)

- [ ] The board server's PATH contains glab's directory: `ps eww -p $(lsof -tiTCP:7700 -sTCP:LISTEN) | tr ' ' '\n' | grep '^PATH='` must include `~/.local/bin` (`command -v glab` → `/Users/francisco.ruiz/.local/bin/glab`). tmux-dash starts the server with `nohup` from the caller's shell (bin/tmux-dash:47). If the directory is missing, the sync shows a warning rather than failing silently.
- [ ] Restart the board after merge (`tmux-dash` restart): the 60 s loop starts only in `__main__` (server.py:1013), so a board that is already running never re-syncs.
- [ ] glab is logged in to gitlab.com with a user who has at least Planner/Reporter on the repo: `glab auth status --hostname gitlab.com`, and the project's member page.
- [ ] The adopt step (6 above) passed.
