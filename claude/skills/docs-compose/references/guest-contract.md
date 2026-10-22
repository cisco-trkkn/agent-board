# Guest contract

The single source of the rules every doc-type skill (`docs-architecture`, `docs-runbook`, `docs-report`, `docs-explainer`) follows inside a composed Doc. Type skills point here and restate none of it. A skill runs as a **guest** when it is handed a guest brief, **standalone** when it is not.

## Guest brief

The composer (`docs-compose`, step 5) fills this template, one per guest. Every field is required; an empty list is written `none`.

    Guest brief: <type>
    Doc: <doc id>
    Main tab: <main tab id>
    Owned blocks (reading order):
      - <pending block id>: "<intent, [type] prefix included>"
    Audience: <the Doc's audience line>
    Interview answers:
      - interview:<n>: <question> → <answer>
    Discovery artefacts (reuse; do not rerun that discovery):
      - <path>: <what produced it, e.g. inventory.py on <repo>@<sha>>
    Sources (current):
    ```json
    <the Sources json merged so far, {} for the first guest>
    ```

## A guest

- Writes only into its owned blocks, one section per call, replacing each pending block with its heading and body.
- Leaves every other block as it found it: the title, the Doc-level line, other types' sections, and the `Sources` tab. It never births, renames or deletes the Doc, and never edits a block it does not own.
- Asks the user no interview questions of its own: the brief's answers are the Doc's whole interview.
- Runs its fresh-eyes review over its own sections before stamping them.
- Ends its section group with its stamp (`references/sources.md` § Stamps) as the last block it owns.
- Returns to the composer:
  1. its `Sources` entries, one per section it wrote, in the `references/sources.md` schema;
  2. the blocks it could not fill: each stays in the Doc as a pending block with its intent rewritten to say what is missing, never deleted.

## Standalone

With no guest brief, the type skill is its own composer for a single-type Doc: it births the Doc, writes its outline, confirms the outline only when the request was ambiguous, asks its own interview, and writes the `Sources` tab itself, checking it with `docs-compose/scripts/sources_check.py` before it finishes. `docs-architecture` standalone is unchanged apart from writing `Sources` instead of `Id map`.

## Shared rules

Every type, as guest or standalone:

- **Traceability.** Every fact traces to a source of a kind listed in `references/sources.md` § Source kinds. Nothing invented.
- **At most 5 interview questions per Doc**: pooled by the composer for a guest; the skill's own round when standalone.
- **Fresh-eyes review before the stamp.** A subagent when one can be spawned; otherwise review as a demanding outsider, tell the user, and say so in the report.
- **One section per call**, pending blocks first (the `anthropic-skills:docs` watch-it-fill rule).
