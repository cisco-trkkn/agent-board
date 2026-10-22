---
name: docs-compose
description: Use for any doc request that may mix kinds (architecture, runbook or how-to, report or handover, client explainer), used alongside `anthropic-skills:docs`. Builds one Claude Doc from a confirmed, typed outline and hands each section to its type skill as a guest; for one type alone, that type's skill may run standalone.
---

# docs-compose

The composer: builds one Claude Doc whose sections are each written by the skill for that kind of writing (`docs-architecture`, `docs-runbook`, `docs-report`, `docs-explainer`). It owns the Doc, the outline, the interview and the `Sources` tab; the type skills, as **guests**, own their sections.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, pending blocks, one section per call, tabs, guarded edits). This skill adds the six steps and the rules below and restates nothing else. The guest rules live in `references/guest-contract.md`; the `Sources` schema in `references/sources.md`.

## Rules

- **Birth first.** The first Docs call births the Doc (title, byline, one `pending` "planning the outline…" block), before any repo read, inventory run or cloud read; loading skills may precede it. The Doc is never deleted: a halt replaces the planning block with what was found.
- **No section before the yes.** Step 3's answer gates every non-pending write.
- **At most 5 interview questions per Doc**, pooled across all guests in one round.
- **Guests write the sections.** The composer writes the title, the outline, the Doc-level line and the `Sources` tab, and no section body, diagram or stamp.
- **Fresh-eyes review before each stamp**, run by each guest over its own section group (guest contract).

Copied from `docs-architecture`: birth first, fresh-eyes review. Different: the birth block is "planning the outline…" (not "discovering the repo…"); no Doc-level stamp (stamps are per section group); no diagrams; the interview is one pooled round of at most 5 across guests.

## Workflow

### 1. Birth

Create the Doc: title, byline, one `pending` block with intent "planning the outline…". Done when the Doc's link is up and holds only that pending block.

### 2. Outline

From the request, decide the sections and the type of each: `architecture`, `runbook`, `report`, `explainer`. Replace the planning block with **typed pending blocks**, one per section, each intent prefixed with its type: `[explainer] What this means for you`, `[architecture] System map`, `[runbook] Rotate the planner WIF binding`, `[report] Migration close-out, 2026-10`. Order is reader-first: an explainer leads, depth follows. A one-type request gets a one-type outline. Done when every section is a pending block with a `[type]` prefix.

### 3. Confirm

Ask the user one question: the outline as it stands, with "go / change". On a change (add, drop, reorder, retype), redo the pending blocks and ask again. Done on a "go".

### 4. Interview pool

For each confirmed type, read its skill's interview step and draft the questions it would ask about this Doc, after looking where its skill says to look first (code, history) so no question asks what the repo shows. Merge duplicates, keep the 5 that most change what gets written, ask them in one round. Number the answers `interview:1`…`interview:<n>`; every guest may cite any of them. Done when at most 5 questions are asked and each answer has its `interview:<n>` number (zero questions is fine).

### 5. Delegate

Run the guests one at a time, in reading order of each type's first section, explainers last even when they read first (they derive from the others' sections). For each: fill the brief template from `references/guest-contract.md`, load the type skill, and follow its guest mode with that brief. Keep each guest's returned `Sources` entries and its list of unfilled blocks; the next brief carries the entries merged so far. Done when every guest has returned.

### 6. Close

1. Every pending block is filled, or is one a guest returned as unfilled with its intent rewritten to say what is missing; tell the user which.
2. Write the `Sources` tab (one ```json block, `references/sources.md`) from the merged entries and run `python3 <skill root>/scripts/sources_check.py <file|->` on it. Fix each `<section>: <problem>` line it prints (send a source or stamp gap back to the guest that owns the section) and run it again.
3. Add one Doc-level line under the title listing the section types and linking the `Sources` tab.

Done when `sources_check.py` exits 0 (`ok <N> sections`, N = the number of written sections).
