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
