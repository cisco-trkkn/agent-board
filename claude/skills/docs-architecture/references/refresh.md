# Refresh mode

Updates a stamped architecture doc to the repo's current HEAD by rewriting only what changed. Preconditions: the doc has a stamp (`As built from <repo>@<sha>, <date>`) and an `Id map` tab (SKILL.md step 5), and the repo's checkout is at hand (`<repo>` in the stamp is a name, not a path: when the checkout is not the cwd, ask the user for its path). Without a stamp or an id map there is nothing to diff against: tell the user; a fresh doc only when they agree, never silently.

## 1. Read the stamp and the id map

1. Read the doc (docs skill) and find the stamp block in the main tab; take `<sha>` (full) and `<date>`.
2. `Id map` tab → its ```json block → `{section heading: {ids, diagram}}`. Interview answers appear as `interview:<n>`; they have no diff and stay as they are. File sources appear as `file:<path>:<line>`; step 2's source-file check covers them.

## 2. Diff the repo

    python3 <skill root>/scripts/inventory.py <repo> --since <sha> -o diff.json

- Compares two committed trees (`git archive` of `<sha>` and of HEAD). Uncommitted work never shows: if the user means uncommitted changes, they commit first, or the refresh waits.
- Output: `{since, head, components: {added, removed, changed}, edges: {added, removed, changed}}`; `since` and `head` are full shas. A changed component is one whose kind, name, project or env differ, listed with its new values. An edge is identified by `(from, to, kind, label)`; a changed edge has the same identity on both sides but another field differing (other than `source`, which moves with line numbers): the new edge plus `was: {field: old value}`. Every `iam` and `trust` edge carries `member`, the raw member expression, so a changed member condition shows as one changed edge.
- **Exit 2, "inventory: unknown --since sha":** the stamp sha is not in this clone (shallow clone, rewritten history, a different repo). Stop and ask the user which repo or sha to diff against. Never substitute a sha, never diff against an earlier stamp, never regenerate.
- Exit 2 on zero components: discovery is broken at HEAD; halt as SKILL.md says.
- Source-file check, before treating an empty diff as empty: `git diff --name-only <sha> <head>` (full shas from the output). A changed path that is cited as a `file:<path>:<line>` source in the id map, or is the `source` file of an id in the id map (join: run a full `python3 <skill root>/scripts/inventory.py <repo> -o <scratch>/head.json` at head, and read each id's `source` from it; `--since` output carries no `source` for unchanged ids, and the creation-time `inventory.json` is usually gone), marks its section touched (step 3), even when the six lists are empty.
- Empty diff (all six lists empty) **and** no touched section from the source-file check: say "no architecture change since <date>", move the stamp to `head` with today's date (step 5), nothing else.

## 3. Map the diff to sections

For each entry in the diff, find every section whose id map lists the id (components by id; edges, whether added, removed or changed, by their `from`/`to` ids). An added id not in any section belongs to the section whose project or subsystem it sits in (`project`, `env`, the boundary it is a member of); if that is unclear, it is one of the refresh's interview questions (still at most 5 in total).

Collect the set of touched sections. Each is rewritten whole, one section per call, in reading order:

- redraw the diagram as the docs skill's redraw road says (the whole module, from the stored code), keeping every text id and anchor whose node remains, adding and removing nodes and edges as the diff says, under the same brief with the finding sentence updated;
- rewrite the section's prose block to match;
- look at the redrawn diagram (screenshot `read`), as in step 4 of the workflow.

The hero diagram and the key-numbers strip are touched whenever a subsystem, project, env or external dependency was added or removed.

## 4. Leave everything else untouched

Every rewrite of an existing block goes through the docs skill's guarded edit. A guard refusal means the block changed or is gone since the stamp: **their edit wins**. Leave it, name it in the Changed row (step 5) as "left as edited"; when the diff still needs something from it, re-read it and change only that inside their words. Never force. Blocks outside the touched set are never written, so the user's edits there are never at risk.

## 5. Record and re-stamp

1. Under the stamp, a `Changed since <date>` table, one row per change: `date · change · section` (`2026-10-20 · added cloud_run_service worker · Orders`). Append to the existing table when the doc has one.
2. Move the stamp to the new sha and today's date: `As built from <repo>@<head>, <date>`.
3. Update the `Id map` tab: add the new ids to their sections, remove the gone ones, keep interview entries.
4. Reply with the Changed rows and any block left as edited.
