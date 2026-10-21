# docs-compose and doc-type skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Claude Doc per request whose sections are each written by the right doc-type skill (architecture, runbook, report, explainer), coordinated by a `docs-compose` composer.

**Architecture:** `docs-compose` births the Doc, proposes a typed outline, confirms once, pools the interview, and hands each section group to a type skill through a guest brief; guests write only their own blocks and stamp their own section group; a `Sources` tab (validated by `sources_check.py`) is what refresh reads. `docs-report` reaches the cloud only through `cloud_read.py`, a read-only allowlist.

**Tech Stack:** Markdown skills (SKILL.md + references), Python 3 stdlib scripts with `unittest`, `anthropic-skills:docs` (Claude Docs MCP), git, `glab`, `gcloud`/`bq` (read-only).

**Spec:** `docs/superpowers/specs/2026-10-20-docs-compose-design.md` (binding). Pattern skill: `claude/skills/docs-architecture/` (spec `docs/superpowers/specs/2026-10-20-docs-architecture-skill-design.md`).

## Global Constraints

- Execution happens in a worktree under `.claude/worktrees/` (the agent-board checkout is the live install); merging to main makes skills and `claude/CLAUDE.md` live.
- Skills live in `claude/skills/docs-{compose,runbook,report,explainer}/` (and the existing `docs-architecture/`), tracked in agent-board, linked live by `bin/claude-config-link` only after merge.
- Every type skill loads `anthropic-skills:docs` first and restates none of its rules (birth, one section per call, pending blocks, widget contract, screenshot reads, guarded edits).
- Guest contract (spec § The guest contract): a guest never births, renames or deletes the Doc and never edits a block it does not own; writes only its own pending blocks, one section per call; fresh-eyes review before its stamp; its stamp is the last block it owns; returns `Sources` entries and lists what it could not fill (never deletes a block).
- Section types are exactly `architecture`, `runbook`, `report`, `explainer`. Source kinds are exactly: `file:<path>:<line>[-<line>]`, `inventory:<id>`, `interview:<n>`, `cloud:<n>`, `mr:<project>!<iid>`, `commit:<sha 7-40 hex>`, `artefact:<path>[:<line>]`, `section:<heading>@rev<N>`.
- Stamps: architecture `As built from <repo>@<sha>, <date>`; runbook `As of <repo>@<sha>, <date>`; report `Report as of <date>, range <a>..<b>`; explainer `Derived from §<heading> rev <N>[, §… rev <M>], <date>`. `<repo>` is a name, never a path.
- At most 5 interview questions per Doc in total (pooled by the composer as guest; the skill's own when standalone).
- Cloud: read-only, only via `docs-report/scripts/cloud_read.py`; ask the user once per session before the first cloud read, naming the project(s). Never run a runbook command. Never write to any cloud resource.
- Scripts: Python 3 stdlib only; tests are `unittest`, discovered per skill: `python3 -m unittest discover -s claude/skills/<skill>/tests`.
- master-gcp-repo is read-only for every task (scratch detached worktrees only, removed afterwards, never pushed; the user's own worktrees untouched).
- Agent shells run zsh: no unquoted `$VAR` word-splitting in snippets (use arrays or `${=VAR}`), quote words starting with `=`.
- Commits: conventional with scope, e.g. `feat(docs-compose): …`; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- "each of the new docs skills need to be created but then when I call claude docs each skill gets used as needed all within the same doc."
- Mix is ad hoc: the request decides the section types.
- Propose, I confirm: the composer shows a typed outline and asks once before writing.
- Scope: composition + all three new types in this plan.
- Report facts from: git history and MRs, agent session artefacts, interview, live cloud state (read-only).
- Approach 1: composer + guest type skills, per-section stamps, shared `Sources` tab.
- Spec approved as written ("spec looks good").

---

### Task 1: `sources_check.py` and the Sources schema

**Goal:** A validator for the `Sources` json block, with the schema documented in `docs-compose/references/sources.md`.

**Files:**
- Create: `claude/skills/docs-compose/scripts/sources_check.py`
- Create: `claude/skills/docs-compose/references/sources.md`
- Test: `claude/skills/docs-compose/tests/test_sources_check.py`

**Acceptance Criteria:**
- [ ] `sources_check.py <file|->` reads a json object, or the first ```json fenced block in the text; exit 0 and prints `ok <N> sections` when valid
- [ ] exit 1 with one line `<section>: <problem>` per problem for: non-object top level, missing/unknown `type`, empty or missing `stamp`, empty or missing `sources`, a source matching no kind pattern; exit 2 on unparseable input
- [ ] each source kind pattern accepts its valid form and rejects a near miss (tests per kind)
- [ ] `references/sources.md` lists the tab name, the json shape, the four types, the eight kinds with one example each, and the stamp per type, verbatim from Global Constraints

**Verify:** `python3 -m unittest discover -s claude/skills/docs-compose/tests` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** (`tests/test_sources_check.py`; import the script by path, as `docs-architecture/tests/helpers.py` does)

```python
import io, json, os, sys, contextlib, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import sources_check  # noqa: E402

GOOD = {"System map": {"type": "architecture", "stamp": "As built from mgr@" + "a" * 40 + ", 2026-10-20",
                       "sources": ["inventory:infra/ledger/google_sql_database_instance.ledger", "interview:1",
                                   "file:ci/x.yml:35-37"], "diagram": "091b3624-40b0"}}

def check(text):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sources_check.main(text)
    return code, out.getvalue()

class SourcesCheck(unittest.TestCase):
    def test_valid_object(self):
        self.assertEqual(check(json.dumps(GOOD)), (0, "ok 1 sections\n"))

    def test_valid_fenced_block_in_tab_text(self):
        code, _ = check("Sources\n\n```json\n" + json.dumps(GOOD) + "\n```\n")
        self.assertEqual(code, 0)

    def test_each_problem_is_one_line(self):
        bad = {"A": {"type": "howto", "stamp": "", "sources": []},
               "B": {"type": "report", "stamp": "Report as of 2026-10-20, range a..b", "sources": ["jira:12"]}}
        code, out = check(json.dumps(bad))
        self.assertEqual(code, 1)
        self.assertEqual(sorted(out.splitlines()), sorted([
            "A: unknown type 'howto'", "A: empty stamp", "A: no sources",
            "B: source 'jira:12' matches no kind"]))

    def test_unparseable_is_exit_2(self):
        self.assertEqual(check("not json")[0], 2)

    def test_top_level_must_be_object(self):
        self.assertEqual(check("[1]")[0], 1)

    def test_kinds_accept_and_reject(self):
        cases = {
            "file:a/b.tf:12": True, "file:a/b.tf:12-14": True, "file:a/b.tf": False,
            "inventory:env:prod": True, "inventory:": False,
            "interview:3": True, "interview:x": False,
            "cloud:4": True, "cloud:": False,
            "mr:group/proj!123": True, "mr:proj123": False,
            "commit:df19131a": True, "commit:xyz1234": False, "commit:abc": False,
            "artefact:docs/superpowers/plans/p.md": True, "artefact:p.md:40": True, "artefact:": False,
            "section:System map@rev12": True, "section:System map": False,
        }
        for src, ok in cases.items():
            with self.subTest(src=src):
                self.assertEqual(sources_check.source_ok(src), ok)
```

- [ ] **Step 2: Run, expect failure** — `python3 -m unittest discover -s claude/skills/docs-compose/tests` → `ModuleNotFoundError: No module named 'sources_check'`

- [ ] **Step 3: Implement** (`scripts/sources_check.py`; `main(text)` takes the input text so tests need no files; the CLI reads the path or stdin and calls it)

```python
#!/usr/bin/env python3
"""Validate a docs-compose Sources block: python3 sources_check.py <file|->"""
import json, re, sys

TYPES = ("architecture", "runbook", "report", "explainer")
KINDS = [r"file:[^:\s]+:\d+(-\d+)?", r"inventory:\S+", r"interview:\d+", r"cloud:\d+",
         r"mr:[\w./-]+!\d+", r"commit:[0-9a-f]{7,40}", r"artefact:[^:\s]+(:\d+)?", r"section:.+@rev\d+"]
KIND = re.compile("^(" + "|".join(KINDS) + ")$")
FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

def source_ok(s):
    return isinstance(s, str) and bool(KIND.match(s))

def problems(doc):
    if not isinstance(doc, dict):
        return ["<top>: not an object"]
    out = []
    for name, sec in doc.items():
        sec = sec if isinstance(sec, dict) else {}
        if sec.get("type") not in TYPES:
            out.append(f"{name}: unknown type {sec.get('type')!r}")
        if not str(sec.get("stamp") or "").strip():
            out.append(f"{name}: empty stamp")
        if not sec.get("sources"):
            out.append(f"{name}: no sources")
        out += [f"{name}: source {s!r} matches no kind" for s in sec.get("sources") or [] if not source_ok(s)]
    return out

def main(text):
    m = FENCE.search(text)
    try:
        doc = json.loads(m.group(1) if m else text)
    except ValueError as e:
        print(f"unparseable: {e}")
        return 2
    found = problems(doc)
    for p in found:
        print(p)
    if found:
        return 1
    print(f"ok {len(doc)} sections")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: sources_check.py <file|->")
    sys.exit(main(sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read()))
```

- [ ] **Step 4: Run, expect pass** — same command → `OK` (6 tests). Then delete one pattern from `KINDS` and confirm `test_kinds_accept_and_reject` fails, restore it (the test must be able to fail).
- [ ] **Step 5: Write `references/sources.md`** per the Acceptance Criteria (short; tables welcome).
- [ ] **Step 6: Commit** — `git add claude/skills/docs-compose && git commit -m "feat(docs-compose): Sources schema and sources_check.py"` with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-compose/scripts/sources_check.py", "claude/skills/docs-compose/references/sources.md", "claude/skills/docs-compose/tests/test_sources_check.py"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-compose/tests", "acceptanceCriteria": ["valid object or fenced block -> exit 0 'ok N sections'", "one line per problem, exit 1; unparseable exit 2", "each kind accepts/rejects (tests)", "sources.md lists tab, shape, types, kinds, stamps"], "modelTier": "standard"}
```

---

### Task 2: `cloud_read.py`, the read-only cloud gate

**Goal:** The only path from `docs-report` to the cloud: runs a command when it matches the read-only allowlist, refuses anything else, and logs every run for `cloud:<n>` citations.

**Files:**
- Create: `claude/skills/docs-report/scripts/cloud_read.py`
- Create: `claude/skills/docs-report/references/cloud-allowlist.md`
- Test: `claude/skills/docs-report/tests/test_cloud_read.py`

**Acceptance Criteria:**
- [ ] `cloud_read.py --log <path> -- <command…>` runs the command (no shell) only when `allowed(argv)` is true; prints the log entry `{n, command, timestamp, exit, output}` as json and appends it to the json list at `--log` (created if missing; `n` = 1 + highest existing); exit 0 if the command exited 0, else 1
- [ ] refused commands are never run: exit 2, one line `refused: <reason>`, nothing logged
- [ ] allowed: `gcloud --version`; any `gcloud …` whose non-flag tokens include one of `describe`, `list`, `get-iam-policy`, `get-ancestors` and none of the deny words; `bq [global flags] show|ls …`; `bq … query --dry_run …`; `bq … query <sql>` where the SQL is one statement starting `SELECT` or `WITH` and contains no DML/DDL keyword (whole word, case-insensitive) and no `--destination_table` flag
- [ ] refused (tests): `gcloud projects create`, `gcloud … delete`, `gcloud projects set-iam-policy`, `gcloud projects add-iam-policy-binding`, `gcloud run deploy`, `gcloud compute ssh`, `bq rm`, `bq mk`, `bq load`, `bq query` with each of INSERT/UPDATE/DELETE/MERGE/CREATE/DROP, two statements, `--destination_table=x`, any non-gcloud/bq argv[0]
- [ ] the runner is a seam (`main(argv, run=subprocess.run)`); unit tests use a fake runner and assert it was or was not called; ONE test runs the real `gcloud --version` (skipped only when `gcloud` is not on PATH, with the skip reason)
- [ ] the allowed forms were probed for real once against the installed CLIs (`gcloud projects get-ancestors --help`, `bq help query | grep -- --dry_run`), output pasted in the report
- [ ] `references/cloud-allowlist.md` states the same rules in prose, with examples of allowed and refused commands, and "fails closed: an identifier that equals a deny word is refused"

**Verify:** `python3 -m unittest discover -s claude/skills/docs-report/tests` → `OK`

**Steps:**

- [ ] **Step 1: Probe the real CLIs** (read-only, offline): `gcloud --version | head -1`, `gcloud projects get-ancestors --help | head -3`, `bq help query | grep -n -- '--dry_run\|--destination_table'`. Record the output for the report.

- [ ] **Step 2: Write the failing tests** (`tests/test_cloud_read.py`)

```python
import io, json, os, shutil, sys, tempfile, contextlib, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import cloud_read  # noqa: E402

class Fake:
    def __init__(self): self.calls = []
    def __call__(self, argv, **kw):
        self.calls.append(argv)
        class R: returncode, stdout, stderr = 0, "out\n", ""
        return R

ALLOWED = [
    ["gcloud", "--version"],
    ["gcloud", "projects", "describe", "trk-org-prod-0"],
    ["gcloud", "run", "services", "list", "--project=trk-org-prod-0", "--format=json"],
    ["gcloud", "projects", "get-iam-policy", "p"],
    ["gcloud", "projects", "get-ancestors", "p"],
    ["bq", "--project_id=p", "show", "ds.t"],
    ["bq", "ls", "p:ds"],
    ["bq", "query", "--dry_run", "--use_legacy_sql=false", "SELECT 1"],
    ["bq", "query", "--use_legacy_sql=false", "WITH a AS (SELECT 1 AS x) SELECT x FROM a"],
]
REFUSED = [
    ["gcloud", "projects", "create", "p"],
    ["gcloud", "run", "services", "delete", "s"],
    ["gcloud", "projects", "set-iam-policy", "p", "f.json"],
    ["gcloud", "projects", "add-iam-policy-binding", "p", "--member=x", "--role=y"],
    ["gcloud", "run", "deploy", "s"],
    ["gcloud", "compute", "ssh", "vm"],
    ["gcloud", "projects", "list", "delete"],
    ["bq", "rm", "ds.t"], ["bq", "mk", "ds"], ["bq", "load", "ds.t", "gs://b/f"],
    ["bq", "query", "INSERT INTO t VALUES (1)"],
    ["bq", "query", "SELECT 1; UPDATE t SET a = 1"],
    ["bq", "query", "DELETE FROM t WHERE true"],
    ["bq", "query", "MERGE t USING s ON true WHEN MATCHED THEN DELETE"],
    ["bq", "query", "CREATE TABLE t AS SELECT 1"],
    ["bq", "query", "DROP TABLE t"],
    ["bq", "query", "SELECT 1; SELECT 2"],
    ["bq", "query", "--destination_table=ds.t", "SELECT 1"],
    ["terraform", "plan"], ["sh", "-c", "gcloud projects list"],
]

class CloudRead(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cloudread-")
        self.log = os.path.join(self.dir, "cloud-log.json")
    def tearDown(self):
        shutil.rmtree(self.dir)

    def call(self, argv, run):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cloud_read.main(["--log", self.log, "--"] + argv, run=run)
        return code, out.getvalue()

    def test_allowed_forms(self):
        for argv in ALLOWED:
            with self.subTest(argv=argv):
                self.assertTrue(cloud_read.allowed(argv)[0])

    def test_refused_forms_never_run(self):
        for argv in REFUSED:
            with self.subTest(argv=argv):
                fake = Fake()
                code, out = self.call(argv, fake)
                self.assertEqual((code, fake.calls), (2, []))
                self.assertTrue(out.startswith("refused: "))
        self.assertFalse(os.path.exists(self.log))

    def test_log_entries_number_up(self):
        fake = Fake()
        self.call(["gcloud", "projects", "describe", "p"], fake)
        code, out = self.call(["bq", "ls", "p:ds"], fake)
        entry = json.loads(out)
        self.assertEqual((code, entry["n"], entry["exit"], entry["output"]), (0, 2, 0, "out\n"))
        self.assertEqual([e["n"] for e in json.load(open(self.log))], [1, 2])
        self.assertRegex(entry["timestamp"], r"^\d{4}-\d\d-\d\dT")

    @unittest.skipUnless(shutil.which("gcloud"), "gcloud not on PATH")
    def test_one_real_call(self):
        code, out = self.call(["gcloud", "--version"], cloud_read.subprocess.run)
        self.assertEqual(code, 0)
        self.assertIn("Google Cloud SDK", json.loads(out)["output"])
```

- [ ] **Step 3: Run, expect failure** — `python3 -m unittest discover -s claude/skills/docs-report/tests` → `ModuleNotFoundError: No module named 'cloud_read'`

- [ ] **Step 4: Implement** `scripts/cloud_read.py`: `allowed(argv) -> (bool, reason)` and `main(argv, run=subprocess.run)` using `argparse` (`--log` required, then `--` and the command). Rules exactly as the Acceptance Criteria. Deny words for gcloud non-flag tokens: `create delete update patch set-iam-policy add-iam-policy-binding remove-iam-policy-binding deploy apply import export ssh scp reset start stop resize enable disable undelete rollback cancel run set`. For `bq`: the subcommand is the first non-flag token after argv[0]; `query` SQL is the last non-flag token; strip `--` line comments and `/* */` blocks before checking; split on `;` and drop empty trailing parts; exactly one statement; first word `SELECT` or `WITH`; reject the whole words `INSERT UPDATE DELETE MERGE CREATE DROP ALTER TRUNCATE GRANT REVOKE EXPORT CALL DECLARE SET BEGIN EXECUTE LOAD`. `--dry_run` makes any single `bq query` allowed except with `--destination_table`. Run with `run(argv, capture_output=True, text=True, timeout=120)`; output = stdout + stderr.

- [ ] **Step 5: Run, expect pass** — same command → `OK`. Then remove `delete` from the deny words and confirm a refused-forms subtest fails; restore.
- [ ] **Step 6: Write `references/cloud-allowlist.md`** per the Acceptance Criteria.
- [ ] **Step 7: Commit** — `feat(docs-report): read-only cloud_read gate` with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-report/scripts/cloud_read.py", "claude/skills/docs-report/references/cloud-allowlist.md", "claude/skills/docs-report/tests/test_cloud_read.py"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-report/tests", "acceptanceCriteria": ["allowlisted run logs {n,command,timestamp,exit,output}", "refused never runs, exit 2, nothing logged", "allowed/refused forms as listed (tests)", "runner seam + one real gcloud --version", "real CLI probe output in report", "cloud-allowlist.md matches"], "modelTier": "standard"}
```

---

### Task 3: `docs-compose` skill and the guest contract

**Goal:** The composer skill (birth, outline, confirm, interview pool, delegate, close) and `references/guest-contract.md`, the single source of the guest rules.

**Files:**
- Create: `claude/skills/docs-compose/SKILL.md`
- Create: `claude/skills/docs-compose/references/guest-contract.md`

**Constraints:**
- Follow the spec's § The composer and § The guest contract exactly; use `writing-for-agents` for the prose; SKILL.md short (docs-architecture's SKILL.md is the length reference).
- Description triggers: any request for a doc that may mix kinds, and "used alongside `anthropic-skills:docs`". It must not steal single-type requests the type skills' own descriptions cover better: say "for one type alone, that type's skill may run standalone".
- The guest brief is a fixed field list (Doc id, main tab id, owned block ids, audience line, interview answers, current `Sources` json); write it as a template the composer fills.
- Order rule: guests run in reading order of their first section, except explainers last. Close runs `scripts/sources_check.py` on the `Sources` block and fixes what it reports.
- Copies docs-architecture's birth-first and fresh-eyes rules. Differences, named: the composer births a "planning the outline…" block (not "discovering the repo…"); it writes no Doc-level stamp; it owns no diagrams; its interview is a pooled round of at most 5 across guests.

**Acceptance Criteria:**
- [ ] SKILL.md has the six steps in spec order, each naming its observable output (pending planning block; typed pending blocks with `[type]` prefixes; one confirm question; ≤ 5 pooled questions recorded as `interview:<n>`; guest briefs; `sources_check.py` exit 0)
- [ ] guest-contract.md holds the brief template, the must/must-not list, standalone mode, and the shared rules; no other file restates them (type skills point to it)

**Verify:** `grep -c '^### ' claude/skills/docs-compose/SKILL.md` → `6`

```json:metadata
{"files": ["claude/skills/docs-compose/SKILL.md", "claude/skills/docs-compose/references/guest-contract.md"], "verifyCommand": "grep -c '^### ' claude/skills/docs-compose/SKILL.md", "acceptanceCriteria": ["six steps with observable outputs", "guest-contract.md is the single source", "structure check = 6"], "modelTier": "frontier"}
```

---

### Task 4: `docs-architecture` guest mode and the Sources fallback

**Goal:** docs-architecture works as a guest (owned blocks, own stamp, returns `Sources` entries) and standalone writes `Sources` instead of `Id map`; refresh reads `Sources` and falls back to `Id map`.

**Files:**
- Modify: `claude/skills/docs-architecture/SKILL.md` (birth paragraph, step 3, step 5.3, Refresh)
- Modify: `claude/skills/docs-architecture/references/refresh.md` (§ 1, § 2 source-file check, § 3)

**Constraints:**
- Point to `docs-compose/references/guest-contract.md`; restate nothing from it.
- Guest mode skips birth and the frame step's page frame; Layer 0–2 go into the owned blocks; its stamp ends its own section group.
- `Sources` entries for architecture carry today's id-map content: each id as `inventory:<id>`, interview as `interview:<n>`, file sources as `file:…`, plus `"diagram"`; `type: "architecture"`; `stamp` = the section group's stamp.
- Refresh: read the `Sources` tab's architecture entries; when the Doc has no `Sources` tab, read the `Id map` tab exactly as today. In a mixed Doc, refresh touches only architecture sections and moves only the architecture stamp.
- Standalone behaviour otherwise unchanged; the existing 45 tests stay green.

**Acceptance Criteria:**
- [ ] SKILL.md names guest mode in one paragraph that links the guest contract, and step 5.3 writes `Sources` (standalone) / returns entries (guest)
- [ ] refresh.md § 1 reads `Sources`, with the `Id map` fallback stated in one sentence; § 3 limits a mixed-Doc refresh to architecture sections
- [ ] `python3 -m unittest discover -s claude/skills/docs-architecture/tests` still `OK` (45)

**Verify:** `python3 -m unittest discover -s claude/skills/docs-architecture/tests`

```json:metadata
{"files": ["claude/skills/docs-architecture/SKILL.md", "claude/skills/docs-architecture/references/refresh.md"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-architecture/tests", "acceptanceCriteria": ["guest mode paragraph linking guest contract", "Sources read with Id map fallback; mixed-Doc refresh limited to architecture", "45 tests OK"], "modelTier": "frontier"}
```

---

### Task 5: `docs-runbook` skill

**Goal:** A guest-capable runbook skill: one procedure per section with cited commands, a cold walk review, and file-change refresh.

**Files:**
- Create: `claude/skills/docs-runbook/SKILL.md`

**Constraints:**
- Spec § docs-runbook is binding: shape (When to use · Before you start · numbered Steps with Expected after risky steps · If it fails · Rollback · Verify it worked), sources, rules (every command cited or a documented CLI form of a cited tool; `<UPPER_SNAKE>` placeholders with their source; destructive steps carry a confirm line and rollback; never run a command), stamp `As of <repo>@<sha>, <date>`, refresh on `git diff --name-only <sha> HEAD` touching a cited file.
- Follows docs-architecture's layout (description, Hard rules, Workflow, Refresh). Differences, named: no inventory script (sources are cited files read directly); diagrams only as a branch flowchart using `docs-architecture/references/svg-modules.md` primitives without GCP icons; the review is a cold walk of each procedure, not a node trace; refresh is per procedure, rewriting in place.
- Points to the guest contract and `anthropic-skills:docs`; restates neither.

**Acceptance Criteria:**
- [ ] SKILL.md has the procedure shape as a template, the four rules, the stamp, and the refresh rule
- [ ] description triggers on "runbook", "how-to", "procedure", "playbook", "how do I operate/rotate/deploy X" and excludes architecture, reports, explainers
- [ ] the clean-tree/detached-worktree precondition from docs-architecture step 1 is reused by pointer, not copied

**Verify:** `grep -c -E '^(#{2,3}) ' claude/skills/docs-runbook/SKILL.md`

```json:metadata
{"files": ["claude/skills/docs-runbook/SKILL.md"], "verifyCommand": "grep -c -E '^(#{2,3}) ' claude/skills/docs-runbook/SKILL.md", "acceptanceCriteria": ["procedure template, four rules, stamp, refresh", "triggers and exclusions in description", "clean-tree precondition by pointer"], "modelTier": "frontier"}
```

---

### Task 6: `docs-report` skill

**Goal:** A guest-capable report skill: scope, outcome first, changes table, verification, risks and owners, next steps; facts from git/MRs, agent artefacts, interview and read-only cloud reads; frozen with dated updates.

**Files:**
- Create: `claude/skills/docs-report/SKILL.md`

**Constraints:**
- Spec § docs-report is binding. Sources: local `git log`, `glab mr list/view` (read-only), artefacts under `docs/superpowers/` and `~/.claude/handoffs/` (SDD ledger `Ruling:` lines cited as `artefact:<path>:<line>`), interview, and cloud only via `scripts/cloud_read.py --log <scratch>/cloud-log.json -- …` (Task 2), each fact citing `cloud:<n>`.
- Ask the user once per session before the first cloud read, naming the project(s); a "no" means the report states "cloud state not checked" in its verification section.
- Stamp `Report as of <date>, range <a>..<b>`; refresh never rewrites, only appends `Update <date>` on request.
- Charts only through the docs skill's chart widgets, from data rows the report cites.
- Follows docs-architecture's layout. Differences, named: no diagrams by default; the review checks each claim in Outcome and What changed against its cited source; frozen instead of refreshable.

**Acceptance Criteria:**
- [ ] SKILL.md has the six-part shape, the four source kinds with their commands, the one-time cloud question, the `cloud_read.py` invocation, the stamp and the frozen/update rule
- [ ] description triggers on "report", "handover", "close-out", "security review", "migration summary", "what changed" and excludes runbooks/explainers/architecture
- [ ] no `gcloud`/`bq` command appears in SKILL.md except inside a `cloud_read.py --` invocation (checked by Verify)

**Verify:** `grep -nE '(^|[^-])\b(gcloud|bq) ' claude/skills/docs-report/SKILL.md | grep -vc 'cloud_read.py'`

```json:metadata
{"files": ["claude/skills/docs-report/SKILL.md"], "verifyCommand": "grep -nE '(^|[^-])\\b(gcloud|bq) ' claude/skills/docs-report/SKILL.md | grep -vc 'cloud_read.py'", "acceptanceCriteria": ["shape, sources, one-time cloud question, cloud_read invocation, stamp, frozen rule", "triggers and exclusions", "gcloud/bq only via cloud_read.py (count 0)"], "modelTier": "frontier"}
```

---

### Task 7: `docs-explainer` skill

**Goal:** A guest-capable explainer skill for semi-technical stakeholders, derived from the Doc's other sections, with a glossary and revision-based refresh.

**Files:**
- Create: `claude/skills/docs-explainer/SKILL.md`

**Constraints:**
- Spec § docs-explainer is binding: shape (What it is · Why it matters to you · How it works, ≤ 1 diagram of ≤ 6 nodes, same GCP grammar, no project ids · What changes for you · Glossary), sources `section:<heading>@rev<N>` first then interview, no claim beyond sources, no internal ids/paths/shas in the body, stamp `Derived from §<heading> rev <N>…, <date>`, refresh when a source section's rev moved.
- Standalone: asks for a source Doc or repo; with a repo, may call `docs-architecture/scripts/inventory.py` for counts only.
- Follows docs-architecture's layout. Differences, named: no discovery step; the review checks every sentence against a source section and every term against the glossary; it always runs last as a guest.

**Acceptance Criteria:**
- [ ] SKILL.md has the shape, the source rule, the no-internal-ids rule, the stamp and the refresh rule, and how it reads section revisions (docs skill `read` outline)
- [ ] description triggers on "explain to the client", "stakeholder summary", "non-technical overview", "what this means for" and excludes the other types

**Verify:** `grep -c -E 'section:|Derived from' claude/skills/docs-explainer/SKILL.md`

```json:metadata
{"files": ["claude/skills/docs-explainer/SKILL.md"], "verifyCommand": "grep -c -E 'section:|Derived from' claude/skills/docs-explainer/SKILL.md", "acceptanceCriteria": ["shape, source rule, no internal ids, stamp, refresh, rev reading", "triggers and exclusions"], "modelTier": "frontier"}
```

---

### Task 8: Wiring: companion line and repo commands

**Goal:** The `docs-compose` companion line in the global instructions and the new test commands in agent-board's CLAUDE.md, both as branch edits that go live at merge.

**Files:**
- Modify: `claude/CLAUDE.md` (the global instructions; `~/.claude/CLAUDE.md` is a symlink to it, so the edit is live only once merged to main)
- Modify: `CLAUDE.md` (agent-board, the Commands block)

**Acceptance Criteria:**
- [ ] `claude/CLAUDE.md` under "Plan and review companions" has the bullet: "- Whenever `anthropic-skills:docs` runs, also load `docs-compose` (typed outline, one confirm, guests per section type, Sources tab)." placed after the last existing bullet of that list
- [ ] agent-board `CLAUDE.md` Commands lists `python3 -m unittest discover -s claude/skills/docs-compose/tests` and `python3 -m unittest discover -s claude/skills/docs-report/tests`, each with a short comment, after the docs-architecture line
- [ ] nothing outside the worktree is written (no edit through `~/.claude/CLAUDE.md`, which points at the live checkout)

**Verify:** `grep -c 'docs-compose' claude/CLAUDE.md CLAUDE.md`

**Steps:**

- [ ] **Step 1:** In the worktree, edit `claude/CLAUDE.md`: add the bullet from the Acceptance Criteria after the last bullet under "# Plan and review companions".
- [ ] **Step 2:** In the worktree, edit `CLAUDE.md` Commands: after `python3 -m unittest discover -s claude/skills/docs-architecture/tests   # docs-architecture inventory` add
  `python3 -m unittest discover -s claude/skills/docs-compose/tests        # docs-compose Sources check` and
  `python3 -m unittest discover -s claude/skills/docs-report/tests         # docs-report cloud gate`.
- [ ] **Step 3:** Run the Verify command → `claude/CLAUDE.md:1` and `CLAUDE.md:1`.
- [ ] **Step 4:** Commit both: `docs(claude): docs-compose companion line and test commands`, with your harness's attribution trailer.

```json:metadata
{"files": ["claude/CLAUDE.md", "CLAUDE.md"], "verifyCommand": "grep -c 'docs-compose' claude/CLAUDE.md CLAUDE.md", "acceptanceCriteria": ["companion bullet in claude/CLAUDE.md", "two test commands in CLAUDE.md", "edits only inside the worktree"], "modelTier": "mechanical"}
```

---

### Task 9: End-to-end: one mixed Doc on master-gcp-repo

**Goal:** Using the skills from the worktree, produce one real Claude Doc on master-gcp-repo at current `dev3` whose sections are explainer + architecture + runbook + report, and prove the composition rules hold.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- None in the repo: a Claude Doc, plus scratch files (inventory, cloud log, block-rev snapshots) in the plan's SDD workspace

**Constraints:**
- Real, aged state: `~/master-gcp-repo` at `origin/dev3` via a detached scratch worktree, removed afterwards; never pushed. The request is ad hoc and written by the lead, e.g. "Doc for the ledger subsystem: what it means for the client, how it fits together, how to rotate the ledger deployer's WIF binding, and a close-out of the last two weeks of ledger changes."
- The composer's confirm question and the interview go to the lead, who answers; the report's one-time cloud question goes to the **user** (it is theirs to grant; the lead relays it). A "no" is a valid answer and is recorded.
- The e2e teammate did not write the skills; it loads them by reading the worktree's SKILL.md files.

**Acceptance Criteria:**
- [ ] the confirm question was asked while every section block was still `pending` (outline read captured before and after)
- [ ] block-revision audit: a docs `read` outline after each guest finishes shows that guest changed only its owned block ids (table of block id → rev per guest)
- [ ] `sources_check.py` exits 0 on the `Sources` tab's json block (output captured)
- [ ] each of the four section groups ends with its own stamp in the spec's format
- [ ] a fresh standard-tier reviewer traces 10 sampled facts across all four types (≥ 2 per type) to their sources, all trace, and walks one runbook procedure cold with a verdict
- [ ] every `cloud:<n>` in `Sources` matches an entry in the cloud log, and the log's first entry is later than the user's recorded yes (or the report says "cloud state not checked" after a no)
- [ ] the scratch worktree is gone (`git -C ~/master-gcp-repo worktree list` shows it absent; the user's worktrees untouched)

**Verify:** report contains the Doc link, the before/after outline reads, the block-rev audit table, the `sources_check.py` output, the four stamps, the reviewer's trace table and runbook verdict, the cloud log, and the worktree list

```json:metadata
{"files": [], "verifyCommand": "", "acceptanceCriteria": ["confirm asked while all pending", "block-rev audit: guests touched only owned blocks", "sources_check exit 0", "four stamps", "reviewer 10/10 trace + runbook cold walk", "cloud log matches cloud:<n>, after the user's yes", "scratch worktree removed"], "modelTier": "frontier", "userGate": true, "tags": ["user-gate"], "subagentBrief": "Real master-gcp-repo dev3, read-only; mixed explainer+architecture+runbook+report Doc; lead answers confirm/interview, user answers the cloud question."}
```

---

### Task 10: End-to-end: refresh across types

**Goal:** On the Task 9 Doc, a real later change to a file a runbook procedure cites refreshes only that procedure, the explainer re-derives only what moved, and the report stays frozen.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- None in the repo: edits the Task 9 Doc; scratch detached worktree of master-gcp-repo, removed afterwards

**Constraints:**
- The change: in a scratch detached worktree at the Task 9 sha, a real commit by the e2e teammate to one file cited by a runbook procedure (e.g. a CI rule line), local only, never pushed. If an existing branch of the user's already changes a cited file, merge it locally instead (preferred: real change).
- Snapshot every block's rev/hash before the refresh.

**Acceptance Criteria:**
- [ ] only the blocks of the affected runbook procedure (and the runbook stamp) changed rev; every other runbook procedure, every report block and every architecture block keeps its rev (before/after table)
- [ ] the explainer states that its source section's rev moved and re-derives only paragraphs that cite that section (or states none changed, with reason)
- [ ] the runbook stamp moved to the new sha; the report stamp is byte-identical
- [ ] `sources_check.py` still exits 0; the scratch worktree is removed

**Verify:** report contains the change commit, the before/after rev table for all blocks, the explainer's statement, both stamps before/after, `sources_check.py` output and the worktree list

```json:metadata
{"files": [], "verifyCommand": "", "acceptanceCriteria": ["only the affected procedure's blocks changed", "explainer flags moved rev, re-derives only affected paragraphs", "runbook stamp moved, report stamp identical", "sources_check exit 0, worktree removed"], "modelTier": "frontier", "userGate": true, "tags": ["user-gate"], "subagentBrief": "Scratch worktree change to a runbook-cited file; never push; rev audit of all blocks."}
```

---

### Task 11: Regression: refresh the existing Task 9 architecture Doc, then go live

**Goal:** The architecture Doc built before this plan (Id map tab, no Sources) still refreshes through the fallback; after merge, the four skills are linked live and listed, and the companion line is live.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- None in the repo: reads (and only if the diff says so, edits) Doc `3ab3959b-abc5-4a8b-bf81-226e1c063fed`

**Constraints:**
- Aged real state: that Doc was built and refreshed on 2026-10-20 (stamp `7a42e580`, a dangling merge commit still in master-gcp-repo's object store). Refresh it with `--since 7a42e580` against a scratch detached worktree at current `origin/dev3`; never pushed; worktree removed.
- The live link and `claude -p` listing happen only after the branch is merged to main (lead's finishing step); this task's last criterion is checked then.

**Acceptance Criteria:**
- [ ] the refresh reads the `Id map` tab (no `Sources` tab exists) and produces a section mapping from the `--since` diff (diff JSON and mapping in the report)
- [ ] sections the diff does not touch keep their block revs (before/after reads of two of them)
- [ ] after merge: `bin/claude-config-link` links `docs-compose`, `docs-runbook`, `docs-report`, `docs-explainer`, and `claude -p "list your available skills by name only" --max-turns 1` output contains all four names (grep count 4); `grep -c docs-compose ~/.claude/CLAUDE.md` → 1

**Verify:** report contains the diff JSON, the section mapping, the before/after rev reads, the worktree list; post-merge: the link output and `claude -p … | grep -c -E 'docs-(compose|runbook|report|explainer)'` → `4`

```json:metadata
{"files": [], "verifyCommand": "", "acceptanceCriteria": ["Id map fallback used, mapping from --since diff", "untouched sections keep revs", "post-merge: four skills linked and listed, companion line live"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"], "subagentBrief": "Refresh Doc 3ab3959b via Id map fallback on a scratch worktree at origin/dev3; post-merge live link + listing."}
```
