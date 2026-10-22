# Sources tab

Every section's provenance lives in one tab of the Doc named `Sources`. Its body is one ```json block: an object keyed by section heading.

```json
{
  "System map": {
    "type": "architecture",
    "stamp": "As built from mgr@<40-hex sha>, 2026-10-20",
    "sources": ["inventory:infra/ledger/google_sql_database_instance.ledger", "interview:1", "file:ci/x.yml:35-37"],
    "diagram": "091b3624-40b0"
  }
}
```

Required per section: `type`, `stamp` (non-empty), `sources` (non-empty, every entry matches a kind). Other keys (such as `diagram`, an explainer's `sourceDoc`: the link of the Doc its `section:` sources live in, or an explainer's `paragraphs`: `{"<block id>": ["<section heading>", …]}`, the source sections each derived paragraph cites) are allowed and not checked.

Check it before closing the Doc: `scripts/sources_check.py <file|->` (file or stdin; reads the whole text as json, or its first ```json block). Exit 0 prints `ok <N> sections`; exit 1 prints one `<section>: <problem>` line per problem; exit 2 means unparseable.

## Types

Exactly: `architecture`, `runbook`, `report`, `explainer`.

## Stamps

`<repo>` is a name, never a path.

| Type | Stamp |
|---|---|
| architecture | `As built from <repo>@<sha>, <date>` |
| runbook | `As of <repo>@<sha>, <date>` |
| report | `Report as of <date>, range <a>..<b>` |
| explainer | `Derived from §<heading> rev <N>[, §… rev <M>], <date>` |
| explainer, standalone from a repo | `Derived from <repo>@<sha>, <date>` |

## Source kinds

Exactly these eight.

| Kind | Form | Example |
|---|---|---|
| file | `file:<path>:<line>[-<line>]` | `file:ci/x.yml:35-37` |
| inventory | `inventory:<id>` | `inventory:env:prod` |
| interview | `interview:<n>` | `interview:3` |
| cloud | `cloud:<n>` | `cloud:4` |
| mr | `mr:<project>!<iid>` | `mr:group/proj!123` |
| commit | `commit:<sha 7-40 hex>` | `commit:df19131a` |
| artefact | `artefact:<path>[:<line>]` | `artefact:docs/superpowers/plans/p.md:40` |
| section | `section:<heading>@rev<N>` | `section:System map@rev12` |
