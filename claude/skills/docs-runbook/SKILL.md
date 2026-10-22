---
name: docs-runbook
description: Use when asked for a "runbook", "how-to", "procedure" or "playbook", or "how do I operate/rotate/deploy X" for a repo, to write a `[runbook]` section as a docs-compose guest, or to refresh a runbook after the repo changed. Operator procedures only, written as a Claude Doc with every command cited; not architecture docs, reports or client explainers.
---

# docs-runbook

Writes operator procedures into a Claude Doc. Each section is one procedure that a stranger can follow cold, and every command in it is taken from a file in the repo and cited. A finished runbook is a snapshot with a stamp; a later repo change is a per-procedure refresh, never a silent regeneration.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, pending blocks, one section per call, the diagram widget and its screenshot `read`, guarded edits). The guest and standalone rules come from `docs-compose/references/guest-contract.md`, and the `Sources` schema, source kinds and stamp forms from `docs-compose/references/sources.md`. This skill adds the procedure shape, the four rules and the steps below, and restates none of those three.

**Mode.** You run as a **guest** when you are handed a guest brief, and **standalone** when you are not. Every step below says what changes between the two.

## Hard rules

1. **Every command is cited.** A command in a step either appears in a cited file (`file:<path>:<line>`) or is a documented CLI form of an installed CLI that a cited file invokes (`gcloud`, `terraform`, `kubectl`: resolved on PATH outside the repo tree). A documented form calls the same tool as the cited line and differs only in subcommand, flags or arguments that the tool's help output names. Confirm it by running that help (rule 4), save the output to the scratch dir, and cite both the invoking line and `artefact:<path>` of the saved help. A repo script, a Makefile/npm/just target or anything under the repo has no documented forms. Its forms come from reading its source, cited `file:<path>:<line>`. A command with neither source stays out of the procedure: the block keeps a pending intent naming what is missing.
2. **Placeholders are `<UPPER_SNAKE>`, and each one names its source**: a Terraform output or variable, a CI variable or an interview answer, cited, e.g. `<PROJECT_ID>`: output `project_id`, `file:infra/outputs.tf:12`. *Before you start* lists them all.
3. **Destructive steps carry a confirm line and a rollback.** A step is destructive when it deletes, overwrites, revokes, rotates, applies infrastructure or touches prod. Directly under its command, write a **Confirm:** line saying what will change and what the operator checks before running it. *Rollback* holds the matching undo, naming the step number it reverses. A destructive step with no undo says so in its Confirm line.
4. **Commands are cited and reviewed, never executed.** This covers every command a runbook holds, including "to check it works": no dry run, no `plan`, no step itself. The one invocation allowed is help output, to confirm a documented form (rule 1): `<tool> [sub…] --help`, `<tool> --help <topic>` (only a topic the tool's own `--help` output names, e.g. `curl --help all`) or `<tool> --version`, saved to the scratch dir. It is allowed only for an installed CLI whose `command -v <tool>` resolves outside the repo tree. A repo script or target can run its body when given `--help`, so it is read, never invoked. You find a command's behaviour in the cited file and the saved help. *Expected* output comes from those sources or from an interview answer; when neither shows it, write the observable state to check and leave out the output.

Plus the shared rules of the guest contract (traceability, interview budget, fresh-eyes review, one section per call).

## Procedure shape

Each section holds one procedure. Fill this template in this order and leave no part empty: when a part does not apply, write one line saying why (e.g. "Rollback: none needed, read-only").

~~~markdown
## <Verb> <object>            e.g. Rotate the planner WIF binding

**When to use:** <one line: the trigger or symptom>

**Before you start**
- Access: <role or group, on which project/env>, e.g. `roles/iam.workloadIdentityPoolAdmin` on `<PROJECT_ID>`
- Tools: <cli and version where a cited file pins it>
- Placeholders: `<NAME>`: <what it is>, <source>

**Steps**
1. <what this does, one line>
   ```
   <copy-paste command>
   ```
   **Confirm:** <what changes; what to check first>      ← destructive steps only
   **Expected:** <output or observable state>             ← after every risky step

**If it fails:** <symptom → cause → what to do>, one line each, from the cited files or the interview

**Rollback:** <undo per destructive step, naming its step number>

**Verify it worked:** <a read-only check and its expected result>
~~~

A risky step is any step that changes state. **Branch flowchart:** draw a diagram only when the procedure branches (a choice of path, or an *If it fails* path that rejoins the steps). Draw it as a flowchart from `docs-architecture/references/svg-modules.md`: the prelude, *Labelled edge* and its marker, and *Boundary box*. Each node is the *Icon node* box with no glyph, its text the step number and verb, and each edge label is the branch condition. No GCP icons. Write a one-line brief before the diagram (what branches, which steps), and look at the rendered result after it, as the docs skill says.

## Workflow

### 1. Birth (standalone only)

The first Docs call births the Doc (title, byline, one `pending` "reading the repo…" block), before any repo read; loading skills may come first. The Doc is never deleted: if you halt, replace that pending block with what you found. As a guest, the Doc already exists and you write only your owned blocks.

### 2. Gather

Before you read any file: the precondition of `docs-architecture` SKILL.md step 1 (the paragraph starting "Before running it"). The stamp sha is HEAD, so cited lines must be HEAD's committed lines. As a guest, reuse every discovery artefact the brief names (e.g. an `inventory.json`) instead of producing it again.

Read, citing each command and value as `file:<path>:<line>`:

- repo scripts (`scripts/`, `bin/`, `Makefile`);
- CI job definitions (`.gitlab-ci.yml` and its includes): the deploy and ops jobs show the real commands and their variables;
- existing `docs/runbooks/*`: cite whatever still matches the code, and take as fact only what the code confirms;
- Terraform outputs and variables, which supply placeholders and resource names.

Done when every procedure in scope has, for each step, a cited command or a gap you have named.

### 3. Interview

You need answers for intent and who may run each procedure, because code cannot tell either.

- **Guest:** ask no questions of your own. The brief's interview answers are the whole interview; cite them as `interview:<n>`. If a procedure still lacks something only a person can answer, leave its block unfilled (step 7).
- **Standalone:** ask at most 5 questions in one round, and only what the repo cannot show (who may run it, when, which env is safe to try first, what a failure looks like in practice). Number the answers `interview:1`…`interview:<n>`.

### 4. Outline

- **Guest:** your owned blocks, in brief order, are the outline. One procedure per block; a block whose intent holds several procedures is split as the guest contract allows. Split off your stamp block in place under that same rule, so the stamp is the last block you own (step 7).
- **Standalone:** replace the birth block with one `pending` block per procedure (intent `[runbook] <Verb> <object>`) and a pending stamp block last. Confirm the outline with the user only when the request was ambiguous.

### 5. Write

One procedure per call, in reading order. Fill the template in § Procedure shape, applying the four hard rules. For any procedure that branches, write the flowchart as the widget and embed in one batch with its section.

### 6. Review: cold walk

Dispatch a fresh-eyes subagent with the Doc link and the repo path. If you cannot spawn one, use the guest contract's fallback. The review has two passes:

1. **Cold walk.** Using only the Doc, the reviewer walks every procedure step by step as an operator who has never seen the system. For each step it asks: is every placeholder resolvable from what *Before you start* says, does every `<UPPER_SNAKE>` placeholder name where its current value is read from, does every precondition name its command, is every permission named, does a risky step say what to expect, does a destructive step have its Confirm line and its Rollback entry, and is there a path for each failure. It reports the first step at which it would get stuck, per procedure.
2. **Citations.** Against the repo, it checks every command and placeholder against its cited line, all of them, not a sample, and checks each documented form against its saved help `artefact:`, which must come from an installed CLI outside the repo tree in one of rule 4's help forms. It runs none of them (hard rule 4).

Fix what it finds and re-walk the procedures you changed. Done when the review reports no stuck step and no uncited command.

### 7. Stamp and Sources

1. Stamp the last block you own: `As of <repo>@<sha>, <date>` (`<repo>` is a name, never a path; `<sha>` is the full HEAD sha from step 2).
2. One `Sources` entry per procedure written: `type: runbook`, the stamp, every `file:`, `interview:` and `artefact:` source the procedure cites, and `diagram` when it has one.
3. **Guest:** return the entries and the list of unfilled blocks to the composer, as the guest contract says. **Standalone:** write the `Sources` tab and run `python3 <docs-compose root>/scripts/sources_check.py <file|->` on it until it exits 0.

## Refresh

A stamped runbook is refreshed one procedure at a time, in place. You regenerate a whole runbook only when the user agrees.

1. Read the stamp's `<sha>` and the `Sources` entries of type `runbook`. The precondition from step 2 applies at HEAD.
2. Run `git diff --name-only --no-renames <sha> HEAD` (with rename detection, a moved cited file would be listed only under its new path). If git does not know `<sha>`, stop and ask which repo or sha to diff against; never substitute one.
3. A procedure is **touched** when a changed path is one of its `file:` sources. No touched procedure: say "no runbook change since <date>" and move the stamp to HEAD with today's date (step 5's `Sources` update applies).
4. Re-check each touched procedure against HEAD (steps 2 and 5), then rewrite it in place, one call each, through the docs skill's guarded edit: only the blocks whose content is stale; blocks still correct keep their revs. On a guard refusal, follow `docs-architecture/references/refresh.md` § 4: their edit wins. Untouched procedures are never written and keep their block revisions.
5. Re-run step 6 over the touched procedures. Then add a `Changed since <date>` row per change immediately before the stamp (`refresh.md` § 5 item 1), move the stamp to HEAD with today's date. Untouched procedures are verified as of HEAD too, because none of their cited files changed between `<sha>` and HEAD. So set the new stamp on every `runbook` entry in `Sources`, update the touched procedures' sources, and run `sources_check.py` as the guest contract's refresh rule says.
