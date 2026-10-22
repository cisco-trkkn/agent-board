# Cloud allowlist

`scripts/cloud_read.py --log <path> -- <command…>` is the only way to read live GCP state. It runs the command without a shell when it is on this list, prints and logs `{n, command, timestamp, exit, output}` (cite it as `cloud:<n>`), and exits 0 if the command exited 0, else 1. A refused command exits 2 with one line `refused: <reason>`; it is never run and never logged.

**Fails closed: an identifier that equals a deny word is refused.** A project, service or table named `delete` or `run` is refused too. When unsure, the command is refused; do not work around a refusal, report it.

## gcloud

Allowed: `gcloud --version` alone, or any `gcloud …` whose non-flag tokens include one of `describe`, `list`, `get-iam-policy`, `get-ancestors` and none of the deny words.

Deny words: `create delete update patch set-iam-policy add-iam-policy-binding remove-iam-policy-binding deploy apply import export ssh scp reset start stop resize enable disable undelete rollback cancel run set`.

Exception for `run`: it is not a deny word at the command-group position, which is the first non-flag token after `gcloud`, or the second when the first is a release track `alpha` or `beta` (Cloud Run's group is literally `run`). Everywhere else `run` is denied.

A value given as a separate token (`--project p`) counts as a non-flag token; write `--project=p`.

Allowed examples:
- `gcloud projects describe trk-org-prod-0`
- `gcloud run services list --project=trk-org-prod-0 --format=json`
- `gcloud beta run services list`
- `gcloud projects get-iam-policy p`, `gcloud projects get-ancestors p`

Refused examples: `gcloud projects create p`, `gcloud run services delete s`, `gcloud projects set-iam-policy p f.json`, `gcloud projects add-iam-policy-binding p …`, `gcloud run deploy s`, `gcloud compute ssh vm`, `gcloud scheduler jobs run x`, `gcloud projects list delete`, `gcloud projects` (no read verb).

## bq

The subcommand is the first non-flag token after `bq` (global flags such as `--project_id=p` come before it).

- `show` and `ls`: allowed.
- `query --dry_run …` (bare `--dry_run` or `--dry_run=true`): allowed for one statement of any kind. `--dry_run=false` and `--nodry_run` do not count.
- `query <sql>`: allowed when the SQL is one statement starting with `SELECT` or `WITH`, with none of these whole words, case-insensitive: `INSERT UPDATE DELETE MERGE CREATE DROP ALTER TRUNCATE GRANT REVOKE EXPORT CALL DECLARE SET BEGIN EXECUTE LOAD`.
- `query` is refused with `--destination_table` (or any `--destination_*`, `--replace`, `--append_table`, `--schedule`), even with `--dry_run`, and when it has other than exactly one positional (the SQL).
- Any other subcommand (`rm`, `mk`, `load`, `cp`, `update`…): refused.

Before checking, comments (`--`, `#`, `/* */`) are removed and the contents of quoted strings and identifiers are blanked, so `SELECT '--'; DROP TABLE t` is two statements and refused, and `SELECT 'DELETE; x'` is one statement and allowed. An unterminated string or comment is refused. Statements are split on `;`, empty parts dropped; exactly one must remain.

Allowed examples: `bq --project_id=p show ds.t`, `bq ls p:ds`, `bq query --dry_run --use_legacy_sql=false "SELECT 1"`, `bq query --use_legacy_sql=false "WITH a AS (SELECT 1 AS x) SELECT x FROM a"`.

Refused examples: `bq rm ds.t`, `bq mk ds`, `bq load ds.t gs://b/f`, `bq query "DROP TABLE t"`, `bq query "SELECT 1; SELECT 2"`, `bq query --destination_table=ds.t "SELECT 1"`.

## Everything else

`argv[0]` must be exactly `gcloud` or `bq` (no path, no `sh -c`, no `terraform`): refused otherwise.
