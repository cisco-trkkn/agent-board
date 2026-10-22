# Cloud allowlist

`scripts/cloud_read.py --log <path> -- <command…>` is the only way to read live GCP state. It runs the command without a shell when it is on this list, prints and logs `{n, command, timestamp, exit, output}` (cite it as `cloud:<n>`), and exits 0 if the command exited 0, else 1. A refused command exits 2 with one line `refused: <reason>`; it is never run and never logged.

**Fails closed: an identifier that equals a deny word is refused.** A project, service or table named `delete` or `run` is refused too. When unsure, the command is refused; do not work around a refusal, report it.

## gcloud

Allowed: `gcloud --version` alone, or a command whose non-flag tokens are exactly `[alpha|beta] <group…> <read verb> [<one resource arg>]`, with read verb one of `describe`, `list`, `get-iam-policy`, `get-ancestors`. Every group token must match `^[a-z][a-z0-9-]*$` and not be a deny word; the optional resource argument must not be a deny word. Anything else is refused, including a second positional after the verb, a read verb that is not the last verb, and any flag whose name contains `flagfile` or `flags-file` (a file can inject any flag).

Command paths: the group tokens (between the optional `alpha`/`beta` and the read verb) must equal exactly one of these paths, so a write command that merely ends in `list` or `describe` is refused: `projects`, `organizations`, `resource-manager folders`, `services`, `run services`, `run jobs`, `run revisions`, `iam service-accounts`, `iam roles`, `iam workload-identity-pools`, `iam workload-identity-pools providers`, `pubsub topics`, `pubsub subscriptions`, `sql instances`, `sql databases`, `storage buckets`, `secrets`, `functions`, `compute instances`, `compute networks`, `container clusters`, `artifacts repositories`, `scheduler jobs`, `logging sinks`, `logging metrics`, `builds`, `builds triggers`, `dns managed-zones`, `bigquery datasets`. Add a path here, reviewed, to read more (and in `GCLOUD_PATHS` in the script).

Deny words: `create delete update patch set-iam-policy add-iam-policy-binding remove-iam-policy-binding deploy apply import export ssh scp reset start stop resize enable disable undelete rollback cancel run set rm cp mv rsync publish execute call submit add-metadata remove-metadata replace invoke trigger`.

Exception for `run`: it is not a deny word at the command-group position, which is the first non-flag token after `gcloud`, or the second when the first is a release track `alpha` or `beta` (Cloud Run's group is literally `run`). Everywhere else `run` is denied.

Flags that take a value must be written `--flag=value`: a separate value token (`--project p`) counts as a positional and is usually refused.

Allowed examples:
- `gcloud projects describe trk-org-prod-0`
- `gcloud run services list --project=trk-org-prod-0 --format=json`
- `gcloud beta run services list`
- `gcloud projects get-iam-policy p`, `gcloud projects get-ancestors p`

Refused examples: `gcloud storage rm gs://b/obj list`, `gcloud storage cp list gs://b/x`, `gcloud functions call list`, `gcloud projects list a b`, `gcloud projects create p`, `gcloud run services delete s`, `gcloud projects set-iam-policy p f.json`, `gcloud projects add-iam-policy-binding p …`, `gcloud run deploy s`, `gcloud compute ssh vm`, `gcloud scheduler jobs run x`, `gcloud projects list delete`, `gcloud projects` (no read verb).

## bq

The subcommand is the first non-flag token after `bq`. Global flags before it must be written `--name=value` (`--project_id=p`); a bare flag there (`bq --project_id show …`) is refused, because bq would take `show` as its value and run the next token as the subcommand.

- `show` and `ls`: allowed.
- `query <sql>`: allowed when the SQL is one statement starting with `SELECT` or `WITH`, with none of these whole words, case-insensitive: `INSERT UPDATE DELETE MERGE CREATE DROP ALTER TRUNCATE GRANT REVOKE EXPORT CALL DECLARE SET BEGIN EXECUTE LOAD`. `--dry_run`, `--dry_run=…` and `--nodry_run` relax nothing: the SQL is checked the same with or without them, so `bq query --dry_run "DROP TABLE t"` is refused.
- `EXTERNAL_QUERY` anywhere in the SQL (checked on the raw text, case-insensitive) is refused: it sends a string to another database.
- Any flag whose name contains `flagfile`, `flags-file` or `bigqueryrc` is refused: a flag file or `.bigqueryrc` can set default flags such as `--destination_table`.
- `query` is refused with `--destination_table` (or any `--destination_*`, `--replace`, `--append_table`, `--schedule`), even with `--dry_run`, and when it has other than exactly one positional (the SQL).
- Any other subcommand (`rm`, `mk`, `load`, `cp`, `update`…): refused.

Before checking, comments (`--` and `#` end at `\r` or `\n`; `/* */`) are removed and the contents of quoted strings and identifiers are blanked, so `SELECT '--'; DROP TABLE t` is two statements and refused, and `SELECT 'DELETE; x'` is one statement and allowed. An unterminated string or comment is refused. Statements are split on `;`, empty parts dropped; exactly one must remain.

Allowed examples: `bq --project_id=p show ds.t`, `bq ls p:ds`, `bq query --dry_run --use_legacy_sql=false "SELECT 1"`, `bq query --use_legacy_sql=false "WITH a AS (SELECT 1 AS x) SELECT x FROM a"`.

Refused examples: `bq rm ds.t`, `bq mk ds`, `bq load ds.t gs://b/f`, `bq query "DROP TABLE t"`, `bq query "SELECT 1; SELECT 2"`, `bq query --destination_table=ds.t "SELECT 1"`.

## Everything else

`argv[0]` must be exactly `gcloud` or `bq` (no path, no `sh -c`, no `terraform`): refused otherwise.
