# Spike: terraform-skill vs HashiCorp terraform-test / terraform-style-guide

Repos (full clones, 2026-10-25, read only, nothing run):
- `https://github.com/antonbabenko/terraform-skill` at `9c1e92d962a5407c227e5566416e962a2f057240` (2026-10-24), v1.17.2.
- `https://github.com/hashicorp/agent-skills` at `f706481af9b8fedb66de909f6243ad29601afa0c` (2026-09-28), skills under `plugins/terraform/skills/`.

## Recommendation

- **Install with edits: `antonbabenko/terraform-skill` only.** Skip the two HashiCorp skills.
- Copy `skills/terraform-skill/SKILL.md` and `skills/terraform-skill/references/*.md` (8 files) to `~/.claude/skills/terraform-skill/`. Never copy `mcp.json` (unpinned `docker run hashicorp/terraform-mcp-server:latest`) or `.github/`.
- Pin to commit `9c1e92d` and record it in a `SOURCE.txt` beside the skill (or in the install note), not inside the skill files.
- Edits to make after copying: (1) in `SKILL.md`, soften the "Response Contract" (5 mandatory sections in every reply, line 16) to "for plan, state or destructive changes". (2) Add one line saying that in `master-gcp-repo` the repo's CLAUDE.md and the Fabric pin pattern win over the generic CI templates. Leave `references/ci-cd-workflows.md` as is.
- Why not the HashiCorp pair: `terraform-test` is AWS-only examples (`aws_instance`, `AWS_ACCESS_KEY_ID`) and `terraform-style-guide` repeats what `terraform-skill` already says about `fmt`/`tflint`. `terraform-skill` has a `testing-frameworks.md` that covers `.tftest.hcl` and mocks. The only unique content in `terraform-test` is mock-provider detail (`references/MOCK_PROVIDERS.md`, 453 words); take that single file later if mocks become a need.

## Fit for this user

The user's repo: `~/master-gcp-repo/landing-zone/fast/stages/*` (12,846 `.tf` files, most under `.terraform/` module caches), 9 `backend "gcs"` blocks, Fabric modules pinned by SHA (`2-security/main.tf:31`: `source = "git::https://github.com/GoogleCloudPlatform/cloud-foundation-fabric.git//modules/project-factory?ref=11c1d248…"`), GitLab CI with `terraform init -backend=false` + `validate` (`ci/actions/validate/.gitlab-ci-validate.yml:28`), WIF in `2-project-factory-shared`.

| Topic | Coverage | Evidence (skill file:line) |
|---|---|---|
| GCP providers | partly | Only resource-name mapping tables and a secret-manager mention: `references/module-patterns.md:311` `\| Object storage \| aws_s3_bucket \| … \| google_storage_bucket \|`; `references/security-compliance.md:589` `IAM (google_project_iam_*)`. Examples elsewhere are S3/AWS (`testing-frameworks.md:89` `# tests/s3_bucket.tftest.hcl`). |
| Fabric modules | no | `grep -ri fabric` over the whole skill returns nothing. Only a generic `terraform-google-network` naming example (`module-patterns.md:718`). Its module guidance (own modules, registry versions) does not know the Fabric `?ref=<sha>` pattern. |
| GitLab CI plan/apply | partly | A real template exists: `references/ci-cd-workflows.md:147` "## GitLab CI Template" with validate → test → plan → apply, plan artifact, manual apply. But the template uses `image: hashicorp/terraform:latest` and applies from `main`; the repo has dev3/staging/main with `APPLY_MODE=plan` and stage pipelines. Also `state-management.md:609` has a GitLab snippet. |
| State in GCS | yes | `references/state-management.md:279` "### Google Cloud Storage Backend" with `backend "gcs" { bucket = … prefix = … }`, KMS-keyed bucket bootstrap (`:300-332`), `:442` "GCS \| ✅ Native" locking. `SKILL.md:215`: "Azure Storage, GCS, and Terraform Cloud all offer built-in lock…". |
| WIF | partly | One table and one sentence, no GitLab→GCP detail: `ci-cd-workflows.md:439` `\| GitHub Actions → GCP \| value passed via audience parameter \| …` (the GitLab row lists AWS only, `:440`); `:442` "Use keyless OIDC for all three clouds (… GCP Workload Identity Federation)". Nothing on pool/provider conditions or impersonation. |
| terraform test | yes (generic) | `references/testing-frameworks.md:86` "`terraform test` finds `*.tftest.hcl` files under `tests/`"; `SKILL.md:121` `command = apply` vs plan; mocks and cost strategy in `ci-cd-workflows.md` ("Use mocking for PR validation"). AWS examples only. The user's repo has no `.tftest.hcl` outside module caches; its tests are Python config tests (`test_fast_stage_configs.py`). |
| tflint / fmt | yes | `references/quick-reference.md:28` `terraform fmt -recursive -check`; `:32` `tflint --init && tflint`; `testing-frameworks.md:31` `id: terraform_tflint`; `SKILL.md:109` "`validate`, `tflint`, `trivy`, `checkov`". The user's repo has no own `.tflint.hcl`; the only ones are in vendored Fabric module caches. |

Net: strong on state, security, identity-churn (`moved`/`import`), CI-drift discipline; thin on GCP specifics and nothing on Fabric. It is a general Terraform reviewer, not a GCP/Fabric expert.

## Conflicts

No hard conflict with `~/.claude/CLAUDE.md` (it holds only tooling gotchas and skill-companion rules) and `master-gcp-repo` has no AGENTS.md. Soft conflicts:

1. **Response format vs normal replies.**
   Skill, `SKILL.md:16`: "Every Terraform/OpenTofu response must include: 1. Assumptions & version floor … 5. Rollback notes".
   User side: no written rule, but the repo CLAUDE.md is terse and task-driven, and the superpowers `verification-before-completion` wants evidence, not templates. The contract would add five sections to even a one-line question. Fix: the edit above.
2. **CI template vs repo branch model.**
   Skill, `ci-cd-workflows.md:203`: `- if: '$CI_COMMIT_BRANCH == "main"'` + `when: manual` for `apply`, and `:150-` `image: hashicorp/terraform:latest`.
   Repo, `master-gcp-repo/CLAUDE.md`: "`dev3`, `staging`, `main` are protected; never push to them." and "default `APPLY_MODE=plan`. `stage` actions run only from `staging`, `prod` only from `main`." and "Merging to `main` deploys nothing". If an agent copies the template, it would add a main-only apply job. Also `:latest` contradicts the skill's own pin rule (`SKILL.md:174`: "pin runtime and providers").
3. **Skill-internal rule vs agent autonomy (compatible, but note).**
   Skill, `SKILL.md:24`: "Never recommend direct production apply without a reviewed plan artifact and approval." and `:26` never `terraform destroy` without `plan -destroy` shown and confirmed.
   Repo and CLAUDE.md agree (plan-only agents, stage pipelines apply). Aligned, no edit needed.
4. **TDD skill.**
   `superpowers-extended-cc:test-driven-development` + `test-driven-development-extras` ask for RED first and an isolation seam before side-effecting runs. Skill's testing guidance (`testing-frameworks.md:86`) is test-after-friendly and its `command = apply` tests create real resources (`SKILL.md:121`). Not contradictory, but when both trigger, TDD-extras governs: no `command = apply` against a real project without a seam. Worth one line in the install note.
5. **Fabric pins.**
   Repo pins Fabric by git SHA (`2-security/main.tf:31`). Skill `module-patterns.md` favours registry `version =` constraints. Different pinning style; the agent should follow the repo.

## Maintenance and licence

- Last commit: 2026-10-24 (`git log -1`). Commits in the last 6 months (since 2026-04-25): **33** (63 total; in-window months: 2026-05 24, 06 6, 07 1, 10 2; none in 08–09). Latest tag line shows v1.9.0 sorted last by string order; the frontmatter says `version: 1.17.2`.
- Open issues: **1** (`gh api … open_issues_count`; includes PRs). 2,427 stars. Not archived.
- Licence: Apache-2.0 in the `LICENSE` text (194 lines, "Licensed under the Apache License, Version 2.0" at line 6) and `license: Apache-2.0` in the frontmatter. GitHub's API reports `NOASSERTION` only because the file has a 2-line preamble ("Copyright 2026 Anton Babenko … Compliance.tf"). Low risk; Apache-2.0 allows the edits recommended above if the NOTICE/licence is kept: copy `LICENSE` to the skill folder.
- HashiCorp `agent-skills`: MPL-2.0 (API agrees), 14 open issues, 907 stars, repo last commit 2026-09-28, 15 commits in 6 months, the two terraform skills last touched 2026-08-10. `terraform-test` is `version: "0.0.2"`.
- Pinned updates: install by `git clone` + `git checkout 9c1e92d…`, then copy the 9 files. To update: `git fetch`, `git diff 9c1e92d..<new> -- skills/terraform-skill`, read the diff (text only, so a review is cheap), copy, and bump the recorded SHA. Because we edit `SKILL.md`, keep the edits as a patch (`diff -u`) to reapply. No auto-update; don't use the plugin/marketplace route.

## Size and trigger

- `SKILL.md`: 2,551 words. References: `state-management.md` 5,872; `code-patterns.md` 4,363; `module-patterns.md` 2,989; `quick-reference.md` 2,797; `security-compliance.md` 2,277; `testing-frameworks.md` 1,787; `ci-cd-workflows.md` 1,639; `code-intelligence-lsp.md` 972 (total 25,247 words, ~196 KB bytes counted over all files). Only SKILL.md plus the matching references load per task ("Load only the matching reference file(s)", `SKILL.md` Workflow step 3), so a typical load is about 2.5k + 3–6k words. `code-intelligence-lsp.md` is about `terraform-ls`/an external plugin; skip it if you want a smaller install (the SKILL.md link would dangle, acceptable).
- Frontmatter description: "Use when writing, reviewing, or debugging Terraform/OpenTofu modules, tests, CI, scans, or state ops - diagnoses failure mode (identity churn, secrets, blast radius, CI drift, state corruption) with version-aware guards."
- Triggers on this user's work: yes, whenever they edit or review `.tf` in `landing-zone/fast/stages/*`, debug a stage plan, or touch the `terraform` jobs in `.gitlab-ci-validate.yml`. It would also fire on `terraform`-mentioning CI chatter in the many Python/Cloud Run tasks of `master-gcp-repo` (a bare "terraform validate job failed" may load 2.5k words). It should not fire for the Python pipelines, ruff, or docs work; the description is specific enough ("Terraform/OpenTofu") that false triggers should be rare. It has no `allowed-tools` key (grep count 0), so it adds no permissions.
- HashiCorp descriptions for comparison: `terraform-test`: "Comprehensive guide for writing and running Terraform tests. Use when creating test files (.tftest.hcl)…" (1,443 + 1,433 words of references); `terraform-style-guide`: "Generate Terraform HCL code following HashiCorp's official style conventions… Use when writing, reviewing, or generating Terraform configurations." (939 + 535). The style guide's broad "writing Terraform configurations" would fire alongside `terraform-skill` on every `.tf` edit: double loading, another reason to skip it.

## Method

```
S=<scratchpad>; mkdir -p $S/ab $S/hc
git clone -q https://github.com/antonbabenko/terraform-skill $S/ab/repo     # full clone
git clone -q https://github.com/hashicorp/agent-skills $S/hc/repo           # full clone
git log -1 --format='%H %cd' --date=short ; git rev-list --count --since=2026-04-25 HEAD ; git rev-list --count HEAD
git log -1 --format=%cd --date=short -- plugins/terraform/skills/terraform-test plugins/terraform/skills/terraform-style-guide
git log --format=%cd --date=short | awk '{print substr($1,1,7)}' | sort | uniq -c
gh api repos/antonbabenko/terraform-skill --jq '{o:.open_issues_count,l:.license.spdx_id,s:.stargazers_count,p:.pushed_at,arch:.archived}'
gh api repos/hashicorp/agent-skills      --jq '(same)'
wc -w SKILL.md references/*  ;  wc -c SKILL.md references/* | tail -1  ;  sed -n 1,15p SKILL.md
grep -niE 'gcp|google|gcs|fabric|workload identity|wif|gitlab|tflint|terraform fmt|\.tftest' SKILL.md references/*.md
grep -niE 'always|never|must|commit|push|apply|auto-approve|git ' SKILL.md
sed -n 147,215p references/ci-cd-workflows.md ; sed -n 436,444p ... ; sed -n 279,296p references/state-management.md
grep -n -iE 'aws|gcp|google|gitlab|tflint|fmt' (hashicorp terraform-test, terraform-style-guide files)
grep -rlI cloud-foundation-fabric --include='*.tf' …   # in ~/master-gcp-repo (read only)
grep -rhoI 'backend "[a-z]*"' --include='*.tf' . | sort | uniq -c
find . -name .tflint.hcl -o -name '*.tftest.hcl' -o -name .pre-commit-config.yaml
cat ~/master-gcp-repo/CLAUDE.md ; sed -n … ci/actions/validate/.gitlab-ci-validate.yml
```

Key outputs: ab HEAD `9c1e92d…` 2026-10-24, 33 commits since 2026-04-25 (63 total); hc HEAD `f706481…` 2026-09-28, 15 commits, skills last touched 2026-08-10; gh: ab `{"o":1,"l":"NOASSERTION","s":2427}`, hc `{"o":14,"l":"MPL-2.0","s":907}`; word counts as above; repo backends: 9 `gcs`, 1 `http`.

Assumptions and gaps:
- "Last 6 months" = since 2026-04-25.
- Open issue counts include PRs (GitHub API behaviour).
- The `.terraform/` module caches in `master-gcp-repo` inflate the 12,846 `.tf` count; I did not count only first-party files.
- I did not read every reference line; the fit table rests on grep plus the cited reads. `grep -c allowed-tools` on terraform-skill SKILL.md returned 0.
- Nothing was installed or executed from the clones.
