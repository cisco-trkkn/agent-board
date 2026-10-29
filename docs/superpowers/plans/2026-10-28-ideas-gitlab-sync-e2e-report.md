# Ideas → GitLab sync: real-state dry run (Task 5)

Run on 2026-10-28 from branch `feat/ideas-gitlab-sync` against the user's real, aged `~/.local/state/agent-board/ideas/master-gcp-repo.md` and the real GitLab repo `trkkn/trkkn-na/master-gcp-repo`. Read-only: `--dry-run` issues only GET calls through real `glab api`.

## Command

```
env -u TC_IDEAS_DIR TC_GITLAB_CONF=<scratch>/gitlab.json python3 -I board/ideas.py sync --project master-gcp-repo --dry-run
```

Scratch config (`<scratch>/gitlab.json`; `~/.config/agent-board/gitlab.json` does not exist and was not created):

```
{"master-gcp-repo":{"repo":"trkkn/trkkn-na/master-gcp-repo","since":"2026-10-22"}}
```

## Full dry-run output (uncapped, exit code 0, stderr empty)

```
create "Task 6 follow-up: mougii e2e runbook phase 3 and phase 6 step a assume a deployed workload; with OFFBOARD_PIPELINE_DELETION=all and zero modules no 'Deleting secret' line prints, so test_offboard_trace_deletes_every_catalog_secret cannot pass. Also remove the stale runbook __TODO_* claim."
create "Task 6 follow-up: tools/gitlab-trigger.sh is curl-only; add a glab fallback."
create "Task 6 follow-up: landing-zone stage code (landing-zone/fast/stages/**, ci/actions/landing-zone/scripts/**) has no release path; a change limited to it fails prod-promotion-gate like !330 did (the !331 exemption covers only tests and mock records)."
create "Task 6 follow-up: migrate mougii-fe deploy_prod."
create "Task 6 follow-up: deferred minors from !318 and !322 (listed in those MR descriptions); drop the WIF retry once the Fabric pin is a23ea2ec; export mougii_ci_settings in the shared contract only if a job reads it."
create "if this solution was expanded to handle clients all over the globe. how does security, data privacy, gdpr requirements, documentation gaps, auditability queries/data"
create "connector framework cleanup MR: remove pipelines/bq-to-ga4/moved.tf once tenant states are confirmed free of bq-to-ga4 (or applied past the refit); delete date_utils.py + test; move generic fakes out of monorail_common tests package; deferred minors listed in docs/superpowers/plans/2026-10-22-connector-framework-evidence/progress.md"
```

## Actions

- create "Task 6 follow-up: mougii e2e runbook phase 3 and phase 6 step a assume a deployed workload; with OFFBOARD_PIPELINE_DELETION=all and zero modules no 'Deleting secret' line prints, so test_offboard_trace_deletes_every_catalog_secret cannot pass. Also remove the stale runbook __TODO_* claim."
- create "Task 6 follow-up: tools/gitlab-trigger.sh is curl-only; add a glab fallback."
- create "Task 6 follow-up: landing-zone stage code (landing-zone/fast/stages/**, ci/actions/landing-zone/scripts/**) has no release path; a change limited to it fails prod-promotion-gate like !330 did (the !331 exemption covers only tests and mock records)."
- create "Task 6 follow-up: migrate mougii-fe deploy_prod."
- create "Task 6 follow-up: deferred minors from !318 and !322 (listed in those MR descriptions); drop the WIF retry once the Fabric pin is a23ea2ec; export mougii_ci_settings in the shared contract only if a job reads it."
- create "if this solution was expanded to handle clients all over the globe. how does security, data privacy, gdpr requirements, documentation gaps, auditability queries/data"
- create "connector framework cleanup MR: remove pipelines/bq-to-ga4/moved.tf once tenant states are confirmed free of bq-to-ga4 (or applied past the refit); delete date_utils.py + test; move generic fakes out of monorail_common tests package; deferred minors listed in docs/superpowers/plans/2026-10-22-connector-framework-evidence/progress.md"

## Counts

- Dry-run `create` lines: 7
- Independent count, `grep -cE '^- \[ \] 2026-10-(2[2-9]|3[01])' master-gcp-repo.md`: 7
- Equal. Lines other than create/adopt/no: 0. adopt lines: 0.
- The inbox has 9 open ideas in total; the 2 older than 2026-10-22 are before `since` and correctly skipped.
- Same-minute ideas: the file has **four** open ideas at `2026-10-22 17:52` (the brief said three; a fifth idea is at 17:53). All four produce four distinct creates, none adopted, so the `#<n>` ordinal marker separates them.

## Nothing written

- sha256 of the ideas file before: `fca1f4c0be276df44fabee34b5f0f526f52468893a0523860cea841f3c7c67e4`
- sha256 of the ideas file after:  `fca1f4c0be276df44fabee34b5f0f526f52468893a0523860cea841f3c7c67e4`
- Identical.
- `ls ~/.local/state/agent-board/ideas/master-gcp-repo.gitlab*.json` before and after: no matches (no sidecar or status file created).

## User gate after merge

Copied from the spec's e2e check, to be run by the user once merged:

1. Map one project for real: create `~/.config/agent-board/gitlab.json` with that project's `repo` and `since`.
2. Add one idea to that project's inbox.
3. See the issue appear in the GitLab repo.
4. Drop the idea.
5. See the issue closed with `not-planned`.
