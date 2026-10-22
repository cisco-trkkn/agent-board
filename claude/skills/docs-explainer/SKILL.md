---
name: docs-explainer
description: Use when asked to "explain to the client", for a "stakeholder summary", a "non-technical overview" or "what this means for" a team or client, to write an `[explainer]` section as a docs-compose guest, or to refresh an explainer after its source sections changed. Plain-language explainers for semi-technical stakeholders, derived from a Doc's other sections; not architecture docs, runbooks or reports.
---

# docs-explainer

Writes a plain-language explainer as a Claude Doc section for semi-technical stakeholders: what it is, why it matters to them, how it works, what changes for them. It **derives**: every claim comes from the Doc's other sections or the interview, never from fresh discovery. A finished explainer carries a stamp naming the section revisions it was derived from; a later change to one of them is a refresh of only the paragraphs it feeds.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, pending blocks, one section per call, the `read` outline and views, the diagram widget and its screenshot `read`, guarded edits). The guest and standalone rules come from `docs-compose/references/guest-contract.md`; the `Sources` schema, source kinds and stamp forms from `docs-compose/references/sources.md`. This skill adds the shape, the hard rules and the steps below, and restates none of those three.

**Guest mode.** Handed a guest brief by `docs-compose`, follow the guest contract and change only this: skip the birth; step 2 reads the Doc's other sections, already written (an explainer always runs last); step 3 asks nothing and uses the brief's interview answers; step 4 lays the shape out in the owned blocks; step 7's stamp is the last block of the explainer group, and step 7.3 returns `Sources` entries instead of writing the tab. Without a brief, the skill runs standalone as written below.

## Hard rules

1. **Derive, never discover.** Sources are the source sections first (`section:<heading>@rev<N>`), then interview answers (`interview:<n>`). No claim goes beyond what they say: a point the sources do not carry stays out, or becomes an interview question.
2. **Every technical term is translated**: in place, in plain words, or in the *Glossary*. The glossary holds only the terms that cannot be avoided.
3. **No internal ids, paths or shas in the body**: no project ids, resource names, file paths, commit or MR numbers. They stay in `Sources`. Name things by what they do ("the nightly ledger load"), not what they are called.

Plus the shared rules of the guest contract (traceability, interview budget, fresh-eyes review, one section per call).

Laid out as `docs-architecture`. Different: no discovery step (step 2 reads sections, not the repo); the review checks every sentence against a source and every term against the glossary; as a guest it always runs last.

## Shape

Five parts, in this order, plain words, sentences under 25 words:

1. **What it is**: one paragraph, the system or change in one sentence first.
2. **Why it matters to you**: the reader's stake (cost, risk, time, what they can now do).
3. **How it works**: at most one simple diagram, ≤ 6 nodes, in the GCP grammar of `docs-architecture/references/gcp-visual-grammar.md` with modules from `docs-architecture/references/svg-modules.md`, labels by role and never by project id. A one-line brief before it, a rendered look after it.
4. **What changes for you**: what the reader does, sees or decides differently, and when.
5. **Glossary**: a two-column table, term · plain meaning, only the terms used above.

## Workflow

### 1. Birth (standalone only)

The first Docs call births the Doc (title, byline, one `pending` "reading the sources…" block), before any Doc or repo read; loading skills may come first. The Doc is never deleted: a halt replaces that pending block with what was found.

### 2. Read the sources

**Revisions.** Read the **source Doc**'s main tab (this Doc as a guest; the linked source Doc when standalone from one) with the docs skill's `read` outline: its `<doc rev='N'>` is the revision you derive from, and each source section is cited `section:<heading>@rev<N>` with that N. Read each source section's body in full (`view` with its heading's `parentId`, or the blocks under it) before you use it.

- **Guest:** every section of the Doc that is not yours is a candidate source; read them all, cite only those you use.
- **Standalone:** ask for a source Doc or a repo (this is the first interview question). A source Doc: read it as above and link it in the explainer's lead. A repo: under the precondition of `docs-architecture` SKILL.md step 1 (the paragraph starting "Before running it"), run `python3 <docs-architecture root>/scripts/inventory.py <repo> -o <scratch>/inventory.json` for counts only (services, environments, projects), cited `artefact:<path of that inventory.json>`; everything else comes from the interview.

Done when every source section you will cite has been read whole at revision N.

### 3. Interview

- **Guest:** ask nothing; the brief's answers are the whole interview.
- **Standalone:** at most 5 questions in one round, only what the sources cannot say: who reads it, what they decide, what changes for them and when.

### 4. Outline

- **Guest:** your owned blocks are the outline; lay the five shape parts out in them, splitting a block as the guest contract allows.
- **Standalone:** replace the birth block with one `pending` block per shape part (intent `[explainer] <part>`) and a pending stamp block last. Confirm the outline only when the request was ambiguous.

### 5. Write

One shape part per call, in reading order. For each sentence, note which source section or interview answer carries it; a sentence with no carrier is cut. The diagram goes as widget and embed in one batch with its part.

### 6. Review

Dispatch a fresh-eyes subagent with the Doc link; no subagent available: the guest contract's fallback. It checks **every** sentence of the explainer, not a sample, against its source section or interview answer, every technical term against the glossary or an in-place translation, and the body for any id, path or sha. It also reads the explainer as the stakeholder would: does each part answer its heading for someone who never saw the other sections? Fix what it finds. Done when it reports no unsourced sentence, no untranslated term and no internal id.

### 7. Stamp and Sources

1. Stamp the last block you own: `Derived from §<heading> rev <N>[, §… rev <M>], <date>`, one `§<heading> rev <N>` per source section cited. Standalone from a repo (no source section): `Derived from <repo>@<sha>, <date>`, `<repo>` a name never a path, `<sha>` the inventory's `meta.sha`.
2. One `Sources` entry per explainer section: `type: explainer`, the stamp, its `section:<heading>@rev<N>`, `interview:<n>` and `artefact:` sources, `diagram` when it has one, and, standalone from a source Doc, `"sourceDoc": "<that Doc's link>"`.
3. **Guest:** return the entries and the unfilled blocks to the composer. **Standalone:** write the `Sources` tab and run `python3 <docs-compose root>/scripts/sources_check.py <file|->` on it until it exits 0.

## Refresh

An explainer moves only when its sources move; nothing else triggers a rewrite.

1. Read the `Sources` entries of type `explainer`. Read the source sections where they live: the entries' `sourceDoc` when set, otherwise this Doc's main tab. For each cited `section:<heading>@rev<N>`, read that tab with `{"kind":"view","sinceRev":N}`. The section has **moved** when any of its blocks appears changed or gone, or its heading is gone. A `sourceDoc` you cannot read: stop and ask for access; never report "no change" from a Doc you did not read.
   Standalone from a repo (stamp `Derived from <repo>@<sha>, …`): re-run the inventory at HEAD (step 2's command and precondition) and compare its counts with the ones the explainer states; a count that differs has moved, and only the sentences carrying it are re-derived (step 3).
2. Nothing moved: say "no source changed since <date>" and stop; the explainer and its stamp stay as they are.
3. Each moved section: say so in the reply ("§System map moved from rev 12 to rev 31"). Re-read it whole at the current rev, re-check every sentence of the explainer sections that cite it, and rewrite only the paragraphs it no longer carries, one call each, through the docs skill's guarded edit. On a guard refusal, follow `docs-architecture/references/refresh.md` § 4: their edit wins. Paragraphs drawn only from unmoved sections are never written.
4. Re-run step 6 over the rewritten paragraphs. Add a `Changed since <date>` row per change under the stamp (`refresh.md` § 5 item 1), and move the stamp: the re-derived sections' revs to the current rev (from a repo: HEAD's sha), today's date. **Every** explainer entry gets the moved stamp as its `stamp`; only the re-derived sections' entries get new sources; then run `sources_check.py` as the guest contract's refresh rule says.
