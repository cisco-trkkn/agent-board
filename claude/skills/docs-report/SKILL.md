---
name: docs-report
description: Use when asked for a report, handover, close-out, security review, migration summary or "what changed" over a stretch of work in a repo, written as a Claude Doc from git history, MRs, agent artefacts, interview and read-only cloud state, or to add a dated update to such a report. Reports only; not runbooks, how-tos, client explainers or architecture docs.
---

# docs-report

Writes a report as a Claude Doc for whoever inherits or signs off the work: what was in scope, the outcome first, what changed and why, what was verified and how, the open risks with their owners, and the next steps. Every fact cites the record it came from. A finished report is **frozen**: a snapshot with a stamp, later extended only by dated updates, never rewritten.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, one section per call, pending blocks, tables, chart widgets, guarded edits). This skill adds the five steps and the hard rules below and restates nothing else.

The first **Docs** call, before any git read, `glab` call or cloud read, births the Doc (title, byline, one `pending` "gathering the record…" block); loading this skill and `anthropic-skills:docs` may precede it. Step 4 replaces that block with the outline. The Doc is never deleted: a halt replaces that pending block with what was found.

**Guest mode.** Handed a guest brief by `docs-compose`, follow `../docs-compose/references/guest-contract.md` and change only this: skip the birth; step 1 takes the range from the owned blocks' intents and the brief's interview answers; step 2 reuses every discovery artefact the brief lists (a listed cloud log is passed as `--log` again, so its `n` numbering continues); step 3 asks nothing and uses the brief's interview answers; step 4 lays the six parts out in the owned blocks (an owned block may become several pending blocks, in place); step 5's stamp is the last block of the report group, and step 5.3 returns `Sources` entries instead of writing the tab. Without a brief, the skill runs standalone as written below.

Layout follows `docs-architecture` (birth first, guest mode, hard rules, five steps, review then stamp). Different: no diagrams by default (a chart only where step 4 allows one); the review checks every claim in *Outcome* and *What changed* against its cited source; frozen with dated updates instead of a refresh.

## Hard rules

- **Traceability.** Every fact cites a source of a kind in `../docs-compose/references/sources.md` § Source kinds: `commit:`, `mr:`, `artefact:`, `interview:`, `cloud:`, `file:`. A claim with no source is cut or turned into a question.
- **Read-only, everywhere.** Local git reads, `glab mr list` and `glab mr view`, file reads, and cloud reads only through `scripts/cloud_read.py` (step 2). Nothing here writes to a cloud resource, a repo or an MR.
- **A refusal is a finding.** `cloud_read.py` exit 2 means the command was never run. Record the `refused: <reason>` line in *What was verified, and how* as a check not made; the next move is a different allowlisted read or the gap stated, and the refused command stays refused, in every form.
- **One cloud question per session**, asked before the first cloud read (step 2).
- **Interview: at most 5 questions** standalone; none as a guest.
- **One section per call** (the docs skill's watch-it-fill rule).
- **Fresh-eyes review before the stamp.** A subagent when one can be spawned; otherwise review it yourself as a demanding outsider, tell the user, and say so in your report.
- **Stamp** `Report as of <date>, range <a>..<b>` and its `Sources` entries (step 5) close every report.

## Shape

One report = these six parts, in this order, then the stamp.

| Part | Holds |
|---|---|
| *Scope* | what the work was, the period, the range `<a>..<b>` (shas or dates), the repo(s) |
| *Outcome* | the result in a few sentences, first, before any detail |
| *What changed* | a table: MR or commit · change · why |
| *What was verified, and how* | each check, how it was made, its result; refusals and gaps; `cloud state not checked` when the cloud question got a no |
| *Open risks and owners* | each risk with a named owner, or "owner: none" |
| *Next steps* | concrete actions, each with its owner where one is known |

## Workflow

### 1. Scope

Fix the repo(s) and the range `<a>..<b>`: from the request, else from the artefacts (a plan's first commit, a handoff's date), else as an interview question. Done when `<a>` and `<b>` are both concrete (a sha, a tag or a date).

### 2. Gather

Read the four source kinds over the range. Each fact you keep gets its citation as you read it.

1. **Git history and MRs.**
   - `git log --format='%H %ad %s' --date=short <a>..<b>` (or `--since=<date> --until=<date>` for a date range), `git show --stat <sha>` per commit worth a row; cite `commit:<sha>`.
   - `glab mr list --merged --repo=<group/project> --output=json` filtered to the range by `merged_at`, then `glab mr view <iid> --repo=<group/project>` for the description and discussion; cite `mr:<group/project>!<iid>`. The MR description is the first place to find a row's *why*.
2. **Agent artefacts.** Plans, specs, SDD ledgers, handoff docs and review reports under `docs/superpowers/` (and `.superpowers/sdd/`) in the repo and under `~/.claude/handoffs/`. In a ledger, `grep -n 'Ruling:'` finds the decisions; cite each as `artefact:<path>:<line>`.
3. **Interview** (step 3) for what no file records.
4. **Live cloud state**, read-only, only through the gate.
   - First, once per session: ask the user whether you may read live cloud state, naming the project(s) you will read (from the repo's Terraform, the artefacts, or the request). A yes covers the named projects for the rest of the session; a new project is a new question. A no: make no cloud read, and *What was verified, and how* says `cloud state not checked`. As a guest, a consent answer already in the brief's interview answers counts as the question asked.
   - Each read is one line:

         python3 <skill root>/scripts/cloud_read.py --log <scratch>/cloud-log.json -- gcloud run services list --project=<PROJECT> --format=json
         python3 <skill root>/scripts/cloud_read.py --log <scratch>/cloud-log.json -- bq --project_id=<PROJECT> show <dataset>.<table>

   - Value flags are written `--flag=value`. Only the command paths in `references/cloud-allowlist.md` are readable; read it before the first cloud read.
   - Exit 0: the command ran and exited 0. Exit 1: it ran and failed (its output is logged; report the failure). Exit 2: refused, never run, never logged (hard rule: a refusal is a finding).
   - Every logged run prints its `n`; cite each fact drawn from it as `cloud:<n>`. `<scratch>` is the session's scratch dir, never the repo.

Done when every MR and commit in the range is either a candidate *What changed* row or judged noise (merges, formatting), every artefact in the range has been read, and the cloud question has been answered.

### 3. Interview

Standalone: ask at most 5 questions, in one round, only for what no source shows: the outcome as the owner sees it, open risks, owners, what was verified by hand, intent behind a change with no recorded *why*. Each answer is a source, `interview:<n>`. No question whose answer is in git, an MR or an artefact: cite that instead. As a guest: ask nothing; the brief's answers are the whole interview.

### 4. Outline and write

Replace the gathering block with pending blocks: the six parts of § Shape, then the stamp. Then write one part per call, in order.

- *What changed*: one row per MR (its commits folded in), or per commit where there was no MR; *why* comes from the MR description, an artefact or an interview answer, and a row whose *why* has none says "why: not recorded".
- *What was verified, and how*: each check names its method (test run, MR pipeline, cloud read) and cites it; a refusal or a failed read is listed as a check not made.
- *Open risks and owners*: owners come from the interview or an artefact, never inferred from commit authorship alone.
- **Charts** are optional, only through the docs skill's chart widgets, and only from data rows the report itself cites (for example pipeline success per week from the MRs read in step 2). No chart from data with no citation.

### 5. Review and stamp

1. Dispatch a fresh-eyes subagent with the Doc link and the cloud log (if any). It opens the cited source of **every** claim in *Outcome* and *What changed* (the commit, the MR, the artefact line, the `cloud:<n>` entry, the interview answer) and flags each claim the source does not support, then judges the rest: outcome first, risks each with an owner line, next steps concrete. No subagent available: the fallback in Hard rules. Fix what it finds.
2. Stamp the last block: `Report as of <date>, range <a>..<b>` (`<date>` = today; `<a>..<b>` = step 1's range).
3. Sources: one entry per section, in the schema of `../docs-compose/references/sources.md`: `{"type": "report", "stamp": "<the step 5.2 stamp>", "sources": [...]}`. Standalone: write them as a second tab `Sources` holding one ```json block and check it with `python3 <skills dir>/docs-compose/scripts/sources_check.py <file|->` until it exits 0. Guest: return them to the composer.

## Updates

A stamped report is frozen: its parts and stamp stay as written, even when later work changes the picture. When the user asks for an update, gather and interview again over the new range `<b>..<c>` (steps 1–3, the same cloud rules), and append one `Update <date>` subsection after the stamp: what changed since, what was verified, risks closed or opened, next steps, ending with its own stamp `Report as of <date>, range <b>..<c>`. Review it as in step 5.1, and add its own `Sources` entry keyed by its heading, with its own stamp and sources. Without a request, a stamped report gets no update.
