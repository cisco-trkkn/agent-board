# docs-architecture Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local skill that makes Claude write layered, diagram-led architecture docs as Claude Docs. Facts come from a repo inventory, drawn in Google Cloud's visual language, with a refresh mode.

**Architecture:** The skill lives at `claude/skills/docs-architecture/`. `SKILL.md` holds the workflow, and `references/` holds the grammar, the diagram catalogue, the SVG modules and the refresh procedure. `assets/gcp-icons/` holds the icons. `scripts/inventory.py` is an offline, read-only extractor that turns a repo into `inventory.json` and has pluggable extractors under `scripts/extractors/`. Diagrams are native Claude Docs widgets drawn by `claude.Visualize` modules.

**Tech Stack:** Python 3 (stdlib; `python-hcl2` optional), `unittest`, Claude Docs (`anthropic-skills:docs`), inline SVG.

**Spec:** `docs/superpowers/specs/2026-10-20-docs-architecture-skill-design.md`

## Global Constraints

- Skill root: `~/agent-board/claude/skills/docs-architecture/` (this repo: `claude/skills/docs-architecture/`). Linked live by `bin/claude-config-link`; never copy files into `~/.claude/skills/` by hand.
- `inventory.py` is **read-only and offline**: no `terraform`, `gcloud`, `glab` or network calls. Local `git` (rev-parse, archive) is allowed.
- Output schema exactly as in the spec:
  - `components[]{id,kind,name,project,env,source}`
  - `edges[]{from,to,kind,label,source}` with kind ∈ `call|async|iam|trust`
  - `boundaries[]{id,kind,name,members}` with kind ∈ `org|folder|project|vpc|env`
  - `unknowns[]{what,source,why}`
  - `meta{repo,sha,extractors,confidence}`
- `source` is always `"<repo-relative path>:<1-based line>"`.
- Component id: `"<repo-relative dir>/<tf type>.<tf name>"` for Terraform. For CI it is `"ci/<job name>"`, and for Procfile services `"<dir>/procfile.<process>"`.
- Zero components → exit code 2. Stderr starts with `inventory: 0 components — discovery is broken, not an empty system` and lists per-extractor counts. Never an empty success.
- `confidence` is `"high"` when `python-hcl2` is importable and every `.tf` file parses with it. Otherwise it is `"low"`, and each failing file is added to `unknowns[]`.
- Test fixtures are captured from master-gcp-repo at `d906a77a` (current `dev3`) with `git show`, never hand-written.
- Tests run with `python3 -m unittest discover -s claude/skills/docs-architecture/tests` from the repo root.
- Diagrams: at most 12 nodes each, left → right flow, GCP category colours, and the edge/boundary semantics in the spec's Visual grammar section.
- Commit steps end with the attribution trailer your harness specifies.

**User decisions (already made):**
- Scope: architecture/system docs only. Runbooks, reports and client explainers are future skills (filed as an idea).
- All three gaps (diagrams, layered reading, identity) matter equally.
- Identity = GCP visual language.
- Facts: repo first, then a short interview.
- Freshness: snapshot plus refresh mode.
- Approach A: standalone skill, native widget diagrams, with an inventory helper script.

---

### Task 1: GCP icon set, source and licence

**Goal:** Curate about 30 Google Cloud product icons as SVG into `assets/gcp-icons/`, with their source and licence terms recorded. If the licence check fails, record the drawn-glyph fallback.

**Files:**
- Create: `claude/skills/docs-architecture/assets/gcp-icons/*.svg`
- Create: `claude/skills/docs-architecture/assets/gcp-icons/SOURCE.md`

**Acceptance Criteria:**
- [ ] `SOURCE.md` has three sections: `## Source` (the official URL the icons were downloaded from, plus the download date), `## Licence` (the terms quoted verbatim, with their URL), and `## Icons` (a table: file · product · GCP category).
- [ ] The icon set covers at least these products: Cloud Run, Cloud Functions, Pub/Sub, BigQuery, Cloud Storage, Artifact Registry, Secret Manager, IAM, Workload Identity Federation, VPC, Cloud Load Balancing, Cloud Build, Cloud Scheduler, Firestore, Cloud SQL, Cloud Monitoring, Cloud Logging, Service Account.
- [ ] It also includes generic glyphs: `gitlab.svg`, `ci-job.svg`, `external-system.svg`, `user.svg`.
- [ ] Every SVG is under 8 KB and has no `<script>`, external `href` or `@import`.
- [ ] If the licence does not allow redistribution in a private repo, `## Licence` says so and the folder instead holds drawn category glyphs (one per category) in GCP category colours, also checked by the next criterion.
- [ ] Every product named in `## Icons` maps to an existing file.

**Verify:** `cd claude/skills/docs-architecture/assets/gcp-icons && grep -c '^## ' SOURCE.md` → `3`; `ls *.svg | wc -l` → ≥ 22; `grep -lE '<script|@import|href="http' *.svg` → no output.

**Steps:**

- [ ] **Step 1:** Find Google's official Cloud architecture icon download (cloud.google.com, "Google Cloud icons") and its usage terms. Quote the terms verbatim in `SOURCE.md`.
- [ ] **Step 2:** Download into a new empty scratch dir, never into the repo directly. Copy only the needed product SVGs into `assets/gcp-icons/` with kebab-case names (`cloud-run.svg`, `pubsub.svg`, …).
- [ ] **Step 3:** Draw the four generic glyphs as simple single-colour SVGs (24×24 viewBox).
- [ ] **Step 4:** Write the `## Icons` table and run the Verify commands.
- [ ] **Step 5:** Commit: `git add claude/skills/docs-architecture/assets && git commit -m "feat(docs-architecture): GCP icon set with source and licence"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-architecture/assets/gcp-icons/SOURCE.md"], "verifyCommand": "cd claude/skills/docs-architecture/assets/gcp-icons && grep -c '^## ' SOURCE.md && ls *.svg | wc -l && ! grep -lE '<script|@import|href=\"http' *.svg", "acceptanceCriteria": ["SOURCE.md has Source, Licence, Icons sections", "18 named products + 4 generic glyphs present", "each svg < 8 KB, no script/external refs", "licence fallback recorded if redistribution not allowed", "every Icons row maps to a file"], "modelTier": "standard"}
```

---

### Task 2: inventory.py core + Terraform components and boundaries

**Goal:** `scripts/inventory.py <repo>` emits schema-valid JSON with Terraform components and project/vpc/env boundaries. Each component carries its `file:line`, and an empty repo halts with exit 2.

**Files:**
- Create: `claude/skills/docs-architecture/scripts/inventory.py`
- Create: `claude/skills/docs-architecture/scripts/extractors/__init__.py`
- Create: `claude/skills/docs-architecture/scripts/extractors/terraform.py`
- Create: `claude/skills/docs-architecture/tests/helpers.py`
- Create: `claude/skills/docs-architecture/tests/test_terraform_components.py`
- Create: `claude/skills/docs-architecture/tests/fixtures/mgr/…` (captured)
- Modify: `CLAUDE.md` (Commands block: add the skill's test command)

**Acceptance Criteria:**
- [ ] Fixtures are captured with `git show d906a77a:<path>` from `~/master-gcp-repo`, and `tests/fixtures/mgr/SOURCE.txt` records the sha and the file list.
- [ ] `infra/ledger/google_pubsub_topic.pipeline_events` has kind `pubsub_topic` and source `infra/ledger/pipeline-events.tf:25`.
- [ ] `infra/ledger/google_service_account.ledger` has kind `service_account`, source `infra/ledger/main.tf:140` and project `var.project_id`.
- [ ] `*_iam_member` / `*_iam_binding` resources are not components.
- [ ] An empty dir gives exit code 2, and the stderr text names the discovery-broken message.
- [ ] `meta.extractors.terraform` equals the number of Terraform components, and `meta.confidence` is `high` when hcl2 is importable.

**Verify:** `python3 -m unittest discover -s claude/skills/docs-architecture/tests -v` → all OK.

**Steps:**

- [ ] **Step 1: Capture fixtures** (from the repo root `~/agent-board`):

```bash
F=claude/skills/docs-architecture/tests/fixtures/mgr; mkdir -p $F
M=~/master-gcp-repo; SHA=d906a77a
LIST="$(git -C $M ls-tree --name-only $SHA infra/ledger/ landing-zone/fast-bootstrap/ | grep '\.tf$')
.gitlab-ci.yml
ci/actions/landing-zone/.gitlab-ci-landing-zone.yml
tools/cloudrun-ledger-layer/Procfile"
for f in $LIST; do mkdir -p "$F/$(dirname $f)"; git -C $M show "$SHA:$f" > "$F/$f"; done
{ echo "captured from master-gcp-repo@$SHA with git show"; echo "$LIST"; } > $F/SOURCE.txt
grep -rnEi '(token|password|secret)\s*=\s*"[A-Za-z0-9+/_-]{16,}"' $F || echo "no literal secrets"
```

Expected: the last line prints `no literal secrets`. If it prints matches, stop and report them to the lead.

- [ ] **Step 2: Write `tests/helpers.py`:**

```python
import io, json, os, sys, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
FIXTURE = os.path.join(HERE, "fixtures", "mgr")
sys.path.insert(0, SCRIPTS)
import inventory  # noqa: E402

def run(argv):
    """Run inventory.main(argv); return (exit code, parsed stdout JSON or None, stderr text)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = inventory.main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()

def by_id(items):
    return {i["id"]: i for i in items}
```

- [ ] **Step 3: Write the failing test `tests/test_terraform_components.py`:**

```python
import tempfile, unittest
from helpers import run, by_id, FIXTURE

class TerraformComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.inv, cls.err = run([FIXTURE])

    def test_exit_ok(self):
        self.assertEqual(self.code, 0, self.err)

    def test_topic(self):
        c = by_id(self.inv["components"])["infra/ledger/google_pubsub_topic.pipeline_events"]
        self.assertEqual((c["kind"], c["source"]), ("pubsub_topic", "infra/ledger/pipeline-events.tf:25"))

    def test_service_account(self):
        c = by_id(self.inv["components"])["infra/ledger/google_service_account.ledger"]
        self.assertEqual((c["kind"], c["source"], c["project"]),
                         ("service_account", "infra/ledger/main.tf:140", "var.project_id"))

    def test_iam_members_are_not_components(self):
        self.assertFalse([c for c in self.inv["components"] if c["id"].split("/")[-1].split(".")[0].endswith(("_iam_member", "_iam_binding"))])

    def test_meta_counts(self):
        tf = [c for c in self.inv["components"] if not c["id"].startswith("ci/") and ".procfile." not in c["id"]]
        self.assertEqual(self.inv["meta"]["extractors"]["terraform"], len(tf))

    def test_empty_repo_halts(self):
        with tempfile.TemporaryDirectory() as d:
            code, inv, err = run([d])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("inventory: 0 components — discovery is broken, not an empty system"), err)

if __name__ == "__main__":
    unittest.main()
```

Run: `cd claude/skills/docs-architecture/tests && python3 -m unittest test_terraform_components -v`. Expected: ERROR, `ModuleNotFoundError: No module named 'inventory'`.

- [ ] **Step 4: Write `scripts/extractors/terraform.py`** (components and boundaries; Task 3 adds edges to the same module):

```python
"""Terraform extractor: resource blocks → components, projects/VPCs/envs → boundaries.

Block text is found with a brace-matching scanner, which gives exact lines. python-hcl2, when installed,
validates each file; a file it cannot parse is reported in unknowns and drops confidence to low.
"""
import os, re

SKIP_DIRS = {".git", ".terraform", "node_modules", ".venv", "__pycache__"}
BLOCK_RE = re.compile(r'^(resource|module|data)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{', re.M)
ENV_RE = re.compile(r'(?:^|[-_/])(dev|stage|staging|prod)(?:$|[-_/])')
KINDS = {
    "google_cloud_run_v2_service": "cloud_run_service", "google_cloud_run_service": "cloud_run_service",
    "google_cloud_run_v2_job": "cloud_run_job", "google_cloudfunctions2_function": "cloud_function",
    "google_cloudfunctions_function": "cloud_function", "google_pubsub_topic": "pubsub_topic",
    "google_pubsub_subscription": "pubsub_subscription", "google_bigquery_dataset": "bigquery_dataset",
    "google_storage_bucket": "gcs_bucket", "google_secret_manager_secret": "secret",
    "google_service_account": "service_account", "google_cloud_scheduler_job": "scheduler_job",
    "google_artifact_registry_repository": "artifact_registry", "google_sql_database_instance": "cloud_sql",
    "google_firestore_database": "firestore", "google_iam_workload_identity_pool": "wif_pool",
    "google_iam_workload_identity_pool_provider": "wif_provider", "google_compute_network": "vpc",
    "google_compute_subnetwork": "subnet", "google_monitoring_alert_policy": "alert_policy",
    "google_logging_metric": "log_metric", "google_project": "project",
}

def tf_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".tf"):
                yield os.path.join(d, f)

def blocks(text):
    """Yield (block, type, name, line, body) for each top-level resource/module/data block."""
    for m in BLOCK_RE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        block, a, b = m.group(1), m.group(2), m.group(3)
        typ, name = ("module", a) if block == "module" else (a, b)
        yield block, typ, name, text.count("\n", 0, m.start()) + 1, text[m.end():i - 1]

def attr(body, key):
    m = re.search(r'^\s*' + re.escape(key) + r'\s*=\s*(.+?)\s*$', body, re.M)
    return m.group(1).strip('"') if m else None

def env_of(reldir):
    m = ENV_RE.search(reldir)
    return {"staging": "stage"}.get(m.group(1), m.group(1)) if m else None

def hcl2_ok(path):
    try:
        import hcl2
    except ImportError:
        return None                     # not installed
    try:
        with open(path) as fh:
            hcl2.load(fh)
        return True
    except Exception:
        return False

def extract(root):
    out = {"components": [], "edges": [], "boundaries": [], "unknowns": [], "confidence": "high"}
    projects = {}                       # (reldir, project expr) -> member ids
    vpcs = {}                           # reldir -> (vpc id, member ids)
    for path in tf_files(root):
        rel = os.path.relpath(path, root)
        reldir = os.path.dirname(rel)
        ok = hcl2_ok(path)
        if ok is not True:
            out["confidence"] = "low"
            if ok is False:
                out["unknowns"].append({"what": rel, "source": f"{rel}:1", "why": "python-hcl2 could not parse this file"})
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for block, typ, name, line, body in blocks(text):
            if block != "resource" or typ not in KINDS:
                continue
            cid = f"{reldir}/{typ}.{name}"
            project = attr(body, "project")
            out["components"].append({"id": cid, "kind": KINDS[typ], "name": attr(body, "name") or name,
                                      "project": project, "env": env_of(reldir), "source": f"{rel}:{line}"})
            if project:
                projects.setdefault((reldir, project), []).append(cid)
            if typ == "google_compute_network":
                vpcs.setdefault(reldir, (cid, []))
            elif typ == "google_compute_subnetwork" and reldir in vpcs:
                vpcs[reldir][1].append(cid)
    for (reldir, expr), members in sorted(projects.items()):
        out["boundaries"].append({"id": f"{reldir}/project:{expr}", "kind": "project", "name": expr, "members": members})
    for reldir, (vid, members) in sorted(vpcs.items()):
        out["boundaries"].append({"id": f"{vid}#vpc", "kind": "vpc", "name": vid.rsplit(".", 1)[-1], "members": members})
    envs = {}
    for c in out["components"]:
        if c["env"]:
            envs.setdefault(c["env"], []).append(c["id"])
    for env, members in sorted(envs.items()):
        out["boundaries"].append({"id": f"env:{env}", "kind": "env", "name": env, "members": members})
    return out
```

- [ ] **Step 5: Write `scripts/extractors/__init__.py`:**

```python
"""Extractors: each module exposes extract(root) -> {components, edges, boundaries, unknowns, confidence}."""
from . import terraform

EXTRACTORS = [("terraform", terraform)]
```

- [ ] **Step 6: Write `scripts/inventory.py`:**

```python
#!/usr/bin/env python3
"""inventory.py — read a repo and emit the architecture inventory the docs-architecture skill draws from.

Read-only and offline: it never runs terraform, gcloud, glab or any network call (local git only).
Usage: inventory.py <repo> [--since <sha>] [-o inventory.json]
"""
import argparse, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extractors import EXTRACTORS  # noqa: E402

def git_sha(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None

def build(repo):
    inv = {"components": [], "edges": [], "boundaries": [], "unknowns": [],
           "meta": {"repo": os.path.abspath(repo), "sha": git_sha(repo), "extractors": {}, "confidence": "high"}}
    for name, mod in EXTRACTORS:
        part = mod.extract(repo)
        for key in ("components", "edges", "boundaries", "unknowns"):
            inv[key].extend(part[key])
        inv["meta"]["extractors"][name] = len(part["components"])
        if part["confidence"] == "low":
            inv["meta"]["confidence"] = "low"
    return inv

def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventory.py", description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    ap.add_argument("--since", help="emit the diff between <sha> and the working tree instead")
    ap.add_argument("-o", "--output", help="write JSON here instead of stdout")
    a = ap.parse_args(argv)
    inv = build(a.repo)
    if not inv["components"]:
        counts = ", ".join(f"{k}={v}" for k, v in inv["meta"]["extractors"].items())
        print(f"inventory: 0 components — discovery is broken, not an empty system ({counts}; repo {a.repo})",
              file=sys.stderr)
        return 2
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.output:
        with open(a.output, "w") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7:** Run `python3 -m unittest discover -s claude/skills/docs-architecture/tests -v` from the repo root. Expected: 6 tests OK. If `test_topic` fails on the line number, compare with `grep -n 'resource "google_pubsub_topic" "pipeline_events"' tests/fixtures/mgr/infra/ledger/pipeline-events.tf`. The fixture is the truth.
- [ ] **Step 8:** In `CLAUDE.md`'s Commands block, add the line `python3 -m unittest discover -s claude/skills/docs-architecture/tests   # docs-architecture inventory`.
- [ ] **Step 9:** Commit: `git add claude/skills/docs-architecture CLAUDE.md && git commit -m "feat(docs-architecture): inventory core and Terraform components"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-architecture/scripts/inventory.py", "claude/skills/docs-architecture/scripts/extractors/__init__.py", "claude/skills/docs-architecture/scripts/extractors/terraform.py", "claude/skills/docs-architecture/tests/helpers.py", "claude/skills/docs-architecture/tests/test_terraform_components.py", "CLAUDE.md"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-architecture/tests -v", "acceptanceCriteria": ["fixtures captured from master-gcp-repo@d906a77a, SOURCE.txt present, no literal secrets", "pipeline_events topic: kind pubsub_topic, source infra/ledger/pipeline-events.tf:25", "ledger SA: service_account, main.tf:140, project var.project_id", "no iam_member/iam_binding components", "empty dir exits 2 with discovery-broken stderr", "meta.extractors.terraform equals TF component count"], "modelTier": "standard"}
```

---

### Task 3: Terraform edges (iam, trust, async, call) and unknowns

**Goal:** The Terraform extractor emits `iam`, `trust`, `async` and `call` edges with `file:line`. It resolves one level of `local.*`, and it records variable-driven targets in `unknowns[]` instead of dropping them.

**Files:**
- Modify: `claude/skills/docs-architecture/scripts/extractors/terraform.py`
- Create: `claude/skills/docs-architecture/tests/test_terraform_edges.py`

**Acceptance Criteria:**
- [ ] async edge `infra/ledger/google_pubsub_topic.pipeline_events` → `infra/ledger/google_pubsub_subscription.pipeline_events_ledger`, source `infra/ledger/pipeline-events.tf:71`.
- [ ] iam edge `infra/ledger/google_service_account.ledger` → `infra/ledger/google_secret_manager_secret.db_password`, label `roles/secretmanager.secretAccessor`, source `infra/ledger/main.tf:205`.
- [ ] trust edge `landing-zone/fast-bootstrap/google_iam_workload_identity_pool.gitlab` → `landing-zone/fast-bootstrap/google_service_account.planner`, label `roles/iam.workloadIdentityUser`, source `landing-zone/fast-bootstrap/identity.tf:67` (resolved through `local.pool_principal`).
- [ ] `unknowns[]` has an entry with source `infra/ledger/applied-events.tf:1` whose `why` contains `var.ledger_service_name`.
- [ ] `unknowns[]` has an entry with source `infra/ledger/pipeline-events.tf:71` whose `why` mentions the push endpoint.
- [ ] Every edge's `from` and `to` is either a component id, a boundary id, or a `principal:<expr>` string. Every `principal:` endpoint has a matching unknowns entry.

**Verify:** `python3 -m unittest discover -s claude/skills/docs-architecture/tests -v` → all OK.

**Steps:**

- [ ] **Step 1: Write the failing test `tests/test_terraform_edges.py`:**

```python
import unittest
from helpers import run, FIXTURE

L = "infra/ledger/"
B = "landing-zone/fast-bootstrap/"

class TerraformEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.inv, cls.err = run([FIXTURE])
        cls.edges = {(e["from"], e["to"], e["kind"]): e for e in cls.inv["edges"]}

    def edge(self, frm, to, kind):
        self.assertIn((frm, to, kind), self.edges, f"missing {kind} edge {frm} -> {to}")
        return self.edges[(frm, to, kind)]

    def test_topic_to_subscription(self):
        e = self.edge(L + "google_pubsub_topic.pipeline_events", L + "google_pubsub_subscription.pipeline_events_ledger", "async")
        self.assertEqual(e["source"], L + "pipeline-events.tf:71")

    def test_secret_accessor(self):
        e = self.edge(L + "google_service_account.ledger", L + "google_secret_manager_secret.db_password", "iam")
        self.assertEqual((e["label"], e["source"]), ("roles/secretmanager.secretAccessor", L + "main.tf:205"))

    def test_wif_trust_through_local(self):
        e = self.edge(B + "google_iam_workload_identity_pool.gitlab", B + "google_service_account.planner", "trust")
        self.assertEqual((e["label"], e["source"]), ("roles/iam.workloadIdentityUser", B + "identity.tf:67"))

    def test_variable_target_is_unknown(self):
        hits = [u for u in self.inv["unknowns"] if u["source"] == L + "applied-events.tf:1"]
        self.assertTrue(hits and "var.ledger_service_name" in hits[0]["why"], self.inv["unknowns"])

    def test_push_endpoint_unknown(self):
        hits = [u for u in self.inv["unknowns"] if u["source"] == L + "pipeline-events.tf:71" and "push endpoint" in u["why"]]
        self.assertTrue(hits, self.inv["unknowns"])

    def test_endpoints_resolve(self):
        ids = {c["id"] for c in self.inv["components"]} | {b["id"] for b in self.inv["boundaries"]}
        unknown_whats = {u["what"] for u in self.inv["unknowns"]}
        for e in self.inv["edges"]:
            for end in (e["from"], e["to"]):
                if end.startswith("principal:"):
                    self.assertIn(end, unknown_whats, e)
                else:
                    self.assertIn(end, ids, e)

if __name__ == "__main__":
    unittest.main()
```

Run it. Expected: FAIL, missing edges.

- [ ] **Step 2: Add edge extraction to `terraform.py`.** The rules:
  - **Locals.** For each directory, collect `locals { k = expr }` entries (any `.tf` file in that dir) into `{k: expr}`. Before scanning an attribute, substitute `local.k` with its expression text (one level).
  - **References.** Find them with `REF_RE = re.compile(r'\b(google_[a-z0-9_]+)\.([A-Za-z0-9_-]+)(?:\[[^\]]*\])?')`. A reference resolves to `f"{reldir}/{type}.{name}"` when that id is a component.
  - **IAM resources** (type ends `_iam_member` or `_iam_binding`):
    - The **target** is the first resolvable ref in the first present attribute among `topic, subscription, secret_id, bucket, dataset_id, repository, service_account_id, subnetwork, name`.
    - Else, for `google_project_iam_member`, the target is the project boundary id `f"{reldir}/project:{expr}"`. For `google_organization_iam_member` or `google_folder_iam_member` it is `f"{reldir}/{org|folder}:{attr org_id|folder}"`, and you add that boundary (kind `org`/`folder`, members `[]`) if it is missing.
    - Else, add an unknown `{what: f"{typ}.{name} target", source, why: f"target is variable-driven: {expr}"}` and emit no edge.
    - The **from** endpoint is the first resolvable ref in `member` (or in `members` for bindings). Otherwise it is `f"principal:{member expr}"`, with an unknown `{what: that same string, source, why: "principal is not a resource in this repo"}`.
    - The **kind** is `trust` when the role is `roles/iam.workloadIdentityUser`, `roles/iam.serviceAccountTokenCreator`, `roles/iam.serviceAccountOpenIdTokenCreator` or `roles/iam.serviceAccountUser`, or when the resolved member text contains `principalSet://` or `principal://`. Otherwise it is `iam`.
    - The **label** is the role. If the role is `each.value`, use the label `"<for_each roles>"` and add the role list found in `for_each` to the label when it is a literal list.
    - For a `principalSet`/`principal` member whose substituted text contains a ref to a `google_iam_workload_identity_pool`, the `from` is that pool's id.
  - **Pub/Sub:** for `google_pubsub_subscription`, the first ref in `topic` gives an `async` edge topic → subscription, labelled with the subscription name. If the subscription has a `push_endpoint` that holds a ref to a `cloud_run_service`/`cloud_function` component, add a `call` edge subscription → service. If it has no such ref, add the unknown `{what: f"{typ}.{name} push endpoint", source, why: f"push endpoint is variable-driven: {expr}"}`.
  - **Scheduler:** a `google_cloud_scheduler_job` with a ref in `uri` gives a `call` edge; without one, an unknown, as above.
  - The edge `source` is the IAM/subscription/scheduler resource's own block line.
- [ ] **Step 3:** Run the full suite. Expected: all OK, including Task 2's tests.
- [ ] **Step 4:** Commit: `git add claude/skills/docs-architecture && git commit -m "feat(docs-architecture): Terraform iam/trust/async edges and unknowns"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-architecture/scripts/extractors/terraform.py", "claude/skills/docs-architecture/tests/test_terraform_edges.py"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-architecture/tests -v", "acceptanceCriteria": ["async topic->subscription edge at pipeline-events.tf:71", "iam ledger SA -> db_password secretAccessor at main.tf:205", "trust WIF pool gitlab -> planner SA at identity.tf:67 via local.pool_principal", "unknown at applied-events.tf:1 naming var.ledger_service_name", "unknown push endpoint at pipeline-events.tf:71", "all edge endpoints resolve or are principal: with an unknown"], "modelTier": "standard"}
```

---

### Task 4: GitLab CI and Procfile extractors

**Goal:** CI jobs (with stage and environment) and Procfile processes become components, and a CI job that runs a Terraform directory gets a `call` edge to that directory's project boundary.

**Files:**
- Create: `claude/skills/docs-architecture/scripts/extractors/gitlab_ci.py`
- Create: `claude/skills/docs-architecture/scripts/extractors/procfile.py`
- Modify: `claude/skills/docs-architecture/scripts/extractors/__init__.py`
- Create: `claude/skills/docs-architecture/tests/test_ci_procfile.py`

**Acceptance Criteria:**
- [ ] Every top-level job in the fixture's `.gitlab-ci.yml` and `ci/actions/landing-zone/.gitlab-ci-landing-zone.yml` is a component `ci/<job>` of kind `ci_job` with a `file:line` source. Keys starting with `.` and the reserved keys (`stages, variables, include, default, workflow, image, services, before_script, after_script, cache`) are excluded.
- [ ] A job's `environment:` name, or `environment: name:`, sets its `env`, normalised to dev/stage/prod when it matches.
- [ ] `tools/cloudrun-ledger-layer/procfile.web` has kind `service_source`, source `tools/cloudrun-ledger-layer/Procfile:1`, and its name contains `ledger_api`.
- [ ] Parsing uses no YAML library (GitLab `!reference` tags break `safe_load`). It is a line scanner, and the test proves a `!reference` line does not crash it.
- [ ] `meta.extractors` has `terraform`, `gitlab_ci` and `procfile` keys.

**Verify:** `python3 -m unittest discover -s claude/skills/docs-architecture/tests -v` → all OK.

**Steps:**

- [ ] **Step 1:** List the expected jobs from the fixture, so the test asserts real names: `grep -nE '^[A-Za-z][A-Za-z0-9_ :-]*:\s*$' tests/fixtures/mgr/.gitlab-ci.yml tests/fixtures/mgr/ci/actions/landing-zone/.gitlab-ci-landing-zone.yml`. Pick three job names and their lines for the test, excluding reserved keys.
- [ ] **Step 2:** Write `tests/test_ci_procfile.py`. Assert the three jobs (id, kind `ci_job`, source), no component for any reserved key or `.`-prefixed key, the Procfile component above, the `meta.extractors` keys, and that `gitlab_ci.extract()` on a temp dir holding a `.gitlab-ci.yml` with a `script: [!reference [.x, script]]` line returns without raising. Run it; expected FAIL.
- [ ] **Step 3:** Implement `gitlab_ci.py`. Scan files matching `.gitlab-ci.yml` or `*.gitlab-ci*.yml` / `.gitlab-ci-*.yml`. A job starts at a column-0 key `^([A-Za-z0-9][^:#]*):\s*$`. Within its indented block, read `stage:` and `environment:` (inline value, or the next-line `name:`). Collect script lines. When a script line contains `-chdir=<dir>` or `cd <dir>`, and `<dir>` contains a `.tf` file, emit a `call` edge `ci/<job>` → `f"{dir}/project:{expr}"` for each project boundary in that dir, labelled `"terraform"`. If no project boundary exists, add an unknown. To know the boundaries, `gitlab_ci.extract(root)` re-runs `terraform.extract(root)` (cheap) for the boundaries. Confidence is always `high`.
- [ ] **Step 4:** Implement `procfile.py`. For each `Procfile`, each `name: command` line gives a component `{id: f"{reldir}/procfile.{name}", kind: "service_source", name: "<reldir basename>: <first --target=X value or the command's first word>", project: None, env: None, source: f"{rel}:{line}"}`, and an unknown `{what: id, why: "deploy target (Cloud Run service) not declared in this repo"}`.
- [ ] **Step 5:** Register both in `EXTRACTORS` (order: terraform, gitlab_ci, procfile). Run the full suite. Expected: all OK.
- [ ] **Step 6:** Commit: `git add claude/skills/docs-architecture && git commit -m "feat(docs-architecture): GitLab CI and Procfile extractors"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-architecture/scripts/extractors/gitlab_ci.py", "claude/skills/docs-architecture/scripts/extractors/procfile.py", "claude/skills/docs-architecture/scripts/extractors/__init__.py", "claude/skills/docs-architecture/tests/test_ci_procfile.py"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-architecture/tests -v", "acceptanceCriteria": ["top-level CI jobs are ci_job components with file:line, reserved and dot keys excluded", "environment sets env", "Procfile web process is service_source at Procfile:1 naming ledger_api", "no YAML library; !reference line does not crash", "meta.extractors has terraform, gitlab_ci, procfile"], "modelTier": "standard"}
```

---

### Task 5: `--since <sha>` diff mode

**Goal:** `inventory.py <repo> --since <sha>` emits `{"since": sha, "head": sha, "components": {"added","removed","changed"}, "edges": {"added","removed"}}`, computed offline from `git archive`.

**Files:**
- Modify: `claude/skills/docs-architecture/scripts/inventory.py`
- Create: `claude/skills/docs-architecture/tests/test_since.py`

**Acceptance Criteria:**
- [ ] In a scratch git repo (a temp dir: `git init`, then the fixture's `infra/ledger/*.tf` committed as commit A), add a `google_cloud_run_v2_service "probe"` resource and delete the `google_secret_manager_secret_iam_member "ledger_password_reader"` block, as commit B. Then `--since A` lists the probe under `components.added` and the ledger→db_password iam edge under `edges.removed`.
- [ ] `changed` lists components whose `kind`, `name`, `project` or `env` differ. A pure line shift is **not** a change.
- [ ] An unknown sha gives exit 2 with `inventory: unknown --since sha` on stderr.
- [ ] The scratch repo lives under `tempfile.TemporaryDirectory()` and is gone after the test (leak check: no `tmp*` dirs left by the test under `$TMPDIR` whose names it created).

**Verify:** `python3 -m unittest discover -s claude/skills/docs-architecture/tests -v` → all OK.

**Steps:**

- [ ] **Step 1:** Write `tests/test_since.py`. In `setUp`, create the temp dir, `git init -q`, set `user.email`/`user.name` locally, copy the fixture `infra/ledger` files and commit (A). Append the probe resource to `main.tf`, remove the 7-line `ledger_password_reader` block (main.tf:205–211 in the fixture), and commit (B). Assert as in the criteria, and add one test for the unknown sha. Run it; expected FAIL.
- [ ] **Step 2:** Implement it in `inventory.py`:

```python
def build_at(repo, sha):
    """Inventory of <repo> at <sha>, from `git archive` into a temp dir (offline, read-only on the repo)."""
    import tarfile, tempfile, io
    try:
        blob = subprocess.run(["git", "-C", repo, "archive", "--format=tar", sha], capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None
    with tempfile.TemporaryDirectory() as d:
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            t.extractall(d, filter="data")
        inv = build(d)
    return inv

SAME = ("kind", "name", "project", "env")

def diff(old, new, since):
    oc, nc = {c["id"]: c for c in old["components"]}, {c["id"]: c for c in new["components"]}
    ek = lambda e: (e["from"], e["to"], e["kind"], e["label"])
    oe, ne = {ek(e): e for e in old["edges"]}, {ek(e): e for e in new["edges"]}
    return {"since": since, "head": new["meta"]["sha"],
            "components": {"added": [nc[i] for i in sorted(nc.keys() - oc.keys())],
                           "removed": [oc[i] for i in sorted(oc.keys() - nc.keys())],
                           "changed": [nc[i] for i in sorted(nc.keys() & oc.keys())
                                       if any(nc[i][k] != oc[i][k] for k in SAME)]},
            "edges": {"added": [ne[k] for k in sorted(ne.keys() - oe.keys())],
                      "removed": [oe[k] for k in sorted(oe.keys() - ne.keys())]}}
```

In `main`, after the zero-components check and when `a.since` is set: `old = build_at(a.repo, a.since)`. If `old is None`, print `inventory: unknown --since sha {a.since}` to stderr and return 2. Otherwise output `diff(old, inv, a.since)` instead of `inv`.
- [ ] **Step 3:** Run the full suite. Expected: all OK. Run `ls -d ${TMPDIR:-/tmp}/tmp* 2>/dev/null | wc -l` before and after; the count must be unchanged.
- [ ] **Step 4:** Commit: `git add claude/skills/docs-architecture && git commit -m "feat(docs-architecture): --since diff mode"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["claude/skills/docs-architecture/scripts/inventory.py", "claude/skills/docs-architecture/tests/test_since.py"], "verifyCommand": "python3 -m unittest discover -s claude/skills/docs-architecture/tests -v", "acceptanceCriteria": ["probe service in components.added, ledger->db_password iam edge in edges.removed", "line shift alone is not a change", "unknown sha exits 2 with message", "scratch repo removed after the test"], "modelTier": "standard"}
```

---

### Task 6: Visual grammar and diagram catalogue references

**Goal:** Write `references/gcp-visual-grammar.md` and `references/diagram-set.md`. Together they must let an agent that has never seen a GCP architecture diagram draw consistent, at-a-glance diagrams of any layer.

**Files:**
- Create: `claude/skills/docs-architecture/references/gcp-visual-grammar.md`
- Create: `claude/skills/docs-architecture/references/diagram-set.md`

**Constraints:**
- Content exactly as in the spec's "Visual grammar (GCP)" section. Colours are given as concrete hex tokens per category, each with a light and a dark value, checked for contrast against the Docs page background in both themes. Icons are referenced by their `assets/gcp-icons/` file names from Task 1.
- `diagram-set.md` covers the five diagrams: system context, subsystem/container zoom, data flow, trust boundaries, deploy topology. For each it gives the reader question it answers, which inventory kinds and edge kinds go on it, the 12-node limit and how to split, and the one-sentence brief template.
- Follow `writing-for-agents`: short, concrete, no padding. Each file is under 250 lines.
- No client names or project ids in examples. Use placeholders like `<tenant>-prod`.

**Acceptance Criteria:**
- [ ] `gcp-visual-grammar.md` has sections `## Colour`, `## Icons`, `## Boundaries`, `## Edges`, `## Layout`, `## Page frame`, each matching the spec.
- [ ] The colour table gives hex values for all 5 categories × light/dark, plus the trust-crossing marker colour, with a contrast ratio of at least 3:1 against the page background (a computed number in the table).
- [ ] `diagram-set.md` has one `## ` section per diagram (5), each with "Answers", "Draws", "Omits", "Split when" and "Brief".
- [ ] Every icon file named exists in `assets/gcp-icons/`.

**Verify:** `cd claude/skills/docs-architecture/references && grep -c '^## ' gcp-visual-grammar.md` → `6`; `grep -c '^## ' diagram-set.md` → `5`; `for f in $(grep -oE '[a-z0-9-]+\.svg' *.md | cut -d: -f2 | sort -u); do test -f ../assets/gcp-icons/$f || echo MISSING $f; done` → no output.

```json:metadata
{"files": ["claude/skills/docs-architecture/references/gcp-visual-grammar.md", "claude/skills/docs-architecture/references/diagram-set.md"], "verifyCommand": "cd claude/skills/docs-architecture/references && grep -c '^## ' gcp-visual-grammar.md && grep -c '^## ' diagram-set.md", "acceptanceCriteria": ["grammar has Colour, Icons, Boundaries, Edges, Layout, Page frame", "hex per category light/dark + trust marker, contrast >= 3:1 computed", "diagram-set has 5 diagram sections with Answers/Draws/Omits/Split when/Brief", "every named icon file exists"], "modelTier": "frontier"}
```

---

### Task 7: SVG drawing modules, render-checked in a real Doc

**Goal:** Write `references/svg-modules.md`: copy-ready `claude.Visualize` module snippets for an icon node, a labelled edge (solid/dashed/dotted), a boundary box (org/project/vpc), an environment band, a swimlane and a trust-crossing marker, plus one composed example. Each is verified by rendering in a real Claude Doc in light and dark.

**Files:**
- Create: `claude/skills/docs-architecture/references/svg-modules.md`

**Constraints:**
- Read `anthropic-skills:docs` and its `guide` topics `topic.diagram` and `topic.charts` first. The module contract (how a widget module returns SVG, how labels stay editable in place, theme tokens) comes from there, never from memory.
- Use the colours and icons from Task 6 and Task 1. Icons are inlined. No external fetches.
- Labels must stay editable in place, as that topic describes.
- Make the render check in a scratch Doc titled `docs-architecture module check (scratch)`, then delete that Doc afterwards. Record the screenshot reads in the task report.

**Acceptance Criteria:**
- [ ] `svg-modules.md` has one `## ` section per primitive (6) plus `## Composed example`, each with a fenced module snippet.
- [ ] The composed example draws a 5-node diagram: Cloud Run → Pub/Sub (dashed) → Cloud Run → BigQuery, plus a WIF pool with a dotted trust edge and a trust-crossing marker, inside a project boundary with an env band.
- [ ] The task report shows the screenshot `read` of the composed example in light and in dark. Every label is legible and no element is clipped. If a screenshot cannot be returned, the report says so, and the task stays open for the lead.
- [ ] The scratch Doc is deleted (the report shows the delete call result).

**Verify:** `grep -c '^## ' claude/skills/docs-architecture/references/svg-modules.md` → `7`; the report contains both screenshot reads.

```json:metadata
{"files": ["claude/skills/docs-architecture/references/svg-modules.md"], "verifyCommand": "grep -c '^## ' claude/skills/docs-architecture/references/svg-modules.md", "acceptanceCriteria": ["6 primitive sections + Composed example with module snippets", "composed example: 5 nodes, async + trust edges, marker, project boundary, env band", "light and dark screenshot reads in report, legible, unclipped", "scratch Doc deleted"], "modelTier": "frontier"}
```

---

### Task 8: SKILL.md, refresh procedure, install link

**Goal:** Write `SKILL.md` (triggers, the 5-step workflow, hard rules) and `references/refresh.md`, then link the skill live with `bin/claude-config-link` so that `docs-architecture` appears in a new session's skill listing.

**Files:**
- Create: `claude/skills/docs-architecture/SKILL.md`
- Create: `claude/skills/docs-architecture/references/refresh.md`
- Live: `~/.claude/skills/docs-architecture` (symlink made by `bin/claude-config-link`)

**Constraints:**
- Use `writing-for-agents` (and `superpowers-extended-cc:writing-skills` for skill structure). `SKILL.md` stays under 150 lines and points to the references at their trigger points.
- `SKILL.md` must say to load `anthropic-skills:docs` first. It must not restate that skill's rules, only add to them.
- Hard rules carried verbatim in meaning from the spec:
  - every node and edge traces to the inventory or an interview answer
  - zero components halts
  - at most 5 interview questions, seeded from `unknowns[]`
  - one section per call
  - a brief before each diagram, and a rendered look after it
  - fresh-eyes review before stamping
  - the stamp format `As built from <repo>@<sha>, <date>`
  - a hidden id-map block
- `refresh.md` implements the spec's Refresh mode steps 1–5, including "their edit wins" on a guard mismatch.
- Run `bin/claude-config-link --dry-run` first. The only new line expected is the `docs-architecture` link. Then run it for real. Never move `.bak` copies into `~/.claude/skills/`.

**Acceptance Criteria:**
- [ ] The `SKILL.md` frontmatter `description` names the triggers ("architecture doc", "system overview", "how X fits together") and says it is for architecture/system docs only.
- [ ] `SKILL.md` names each of the 5 workflow steps and each reference file at the step that needs it.
- [ ] `ls -l ~/.claude/skills/docs-architecture` is a symlink to `~/agent-board/claude/skills/docs-architecture`.
- [ ] `claude -p "list your available skills by name only" --max-turns 1` output contains `docs-architecture`.

**Verify:** `ls -l ~/.claude/skills/docs-architecture`; `wc -l claude/skills/docs-architecture/SKILL.md` → < 150; `claude -p "list your available skills by name only" --max-turns 1 | grep -c docs-architecture` → ≥ 1.

```json:metadata
{"files": ["claude/skills/docs-architecture/SKILL.md", "claude/skills/docs-architecture/references/refresh.md"], "verifyCommand": "ls -l ~/.claude/skills/docs-architecture && wc -l claude/skills/docs-architecture/SKILL.md", "acceptanceCriteria": ["description names triggers and architecture-only scope", "5 steps named with references at their step", "live symlink into agent-board", "new session lists docs-architecture"], "modelTier": "frontier"}
```

---

### Task 9: End-to-end: architecture doc for master-gcp-repo

**Goal:** Using only the installed skill, produce a real Claude Doc architecture overview of master-gcp-repo at current `dev3`. Then have a fresh-eyes reviewer verify traceability and at-a-glance quality.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- None in the repo: output is a Claude Doc plus `inventory.json` in the task's scratch dir

**Constraints:**
- Real, aged state: run against the user's real `~/master-gcp-repo` at `origin/dev3`, read-only. If you need a scratch checkout, use `git worktree add --detach` and remove it afterwards. Never against fixtures.
- Interview questions go to the lead, not the user. The lead answers or forwards them.
- Run `inventory.py` with `-o` into the task's scratch dir. Never write into master-gcp-repo.

**Acceptance Criteria:**
- [ ] The Doc exists and its link is in the report. It has a hero context diagram, a key-numbers strip, at least 3 subsystem sections each with a zoom diagram, and a trust-boundary diagram showing the GitLab WIF pool → planner/deployer service-account path.
- [ ] The stamp reads `As built from master-gcp-repo@<dev3 sha>, <date>`, and the hidden id-map block is present.
- [ ] A fresh reviewer subagent (standard tier) samples 10 diagram nodes and traces each to a `file:line` in master-gcp-repo, and all 10 trace. It also gives a per-diagram verdict on "makes its point at a glance", and any "no" is fixed and re-reviewed.
- [ ] No diagram has more than 12 nodes.

**Verify:** the report contains the Doc link, the inventory `meta` (sha, extractor counts, confidence), the reviewer's 10-node trace table, and its per-diagram verdicts.

```json:metadata
{"files": [], "verifyCommand": "", "acceptanceCriteria": ["Doc with hero, key numbers, >=3 subsystem zooms, WIF trust diagram", "stamp with dev3 sha + hidden id map", "reviewer: 10/10 nodes trace to file:line; at-a-glance verdicts all yes", "no diagram > 12 nodes"], "modelTier": "frontier", "userGate": true, "tags": ["user-gate"], "subagentBrief": "Real master-gcp-repo dev3, read-only; reviewer traces 10 nodes."}
```

---

### Task 10: End-to-end: refresh keeps hand edits

**Goal:** Prove refresh mode on the Task 9 Doc. After a real later change, only the affected sections change, and a hand edit survives.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- None in the repo: edits the Task 9 Claude Doc; scratch worktree of master-gcp-repo, removed afterwards

**Constraints:**
- Make the "later change" in a scratch detached worktree of master-gcp-repo at the Task 9 sha, by merging `agent/fable-sec-planner-wif` (`8ee8fdc3`) locally. Never push, never touch the user's branches, and remove the worktree afterwards.
- Before refreshing, hand-edit one sentence in a section the change does not touch, and record its text.

**Acceptance Criteria:**
- [ ] `inventory.py --since <task-9 sha>` on the scratch worktree reports the planner WIF binding change (shown in the report).
- [ ] After refresh, the trust-boundary section and diagram reflect the change, and the Doc has a `Changed since <date>` row naming it.
- [ ] The hand-edited sentence is unchanged, byte for byte (shown by a read of that block before and after).
- [ ] Sections the change does not touch keep their block revisions. Show the read of their revs before and after.
- [ ] The stamp moves to the new sha, and the scratch worktree is removed (`git -C ~/master-gcp-repo worktree list` shows none).

**Verify:** the report contains the diff JSON, the before/after reads of the hand-edited block and of two untouched sections, the changelog row, the new stamp, and the worktree list.

```json:metadata
{"files": [], "verifyCommand": "", "acceptanceCriteria": ["--since reports the planner WIF change", "trust section+diagram updated, Changed since row added", "hand edit byte-identical", "untouched sections keep revs", "stamp moved, scratch worktree removed"], "modelTier": "frontier", "userGate": true, "tags": ["user-gate"], "subagentBrief": "Scratch worktree merge of 8ee8fdc3; never push."}
```
