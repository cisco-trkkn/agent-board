"""Terraform extractor: resource blocks → components, projects/VPCs/envs → boundaries.

Block text is found with a brace-matching scanner, which gives exact lines. python-hcl2, when installed,
validates each file; a file it cannot parse is reported in unknowns and drops confidence to low.
"""
import os, re

SKIP_DIRS = {".git", ".terraform", "node_modules", ".venv", "__pycache__"}
BLOCK_RE = re.compile(r'^(resource|module|data)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{', re.M)
ENV_RE = re.compile(r'(?:^|[-_/])(dev|development|stage|staging|prod|production)(?:$|[-_/])')
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
    return {"staging": "stage", "development": "dev", "production": "prod"}.get(m.group(1), m.group(1)) if m else None

REF_RE = re.compile(r'\b(google_[a-z0-9_]+)\.([A-Za-z0-9_-]+)(?:\[[^\]]*\])?')
LOCALS_RE = re.compile(r'^locals\s*\{', re.M)
TARGET_ATTRS = ("topic", "subscription", "secret_id", "bucket", "dataset_id", "repository",
                "service_account_id", "subnetwork", "name")
TRUST_ROLES = {"roles/iam.workloadIdentityUser", "roles/iam.serviceAccountTokenCreator",
               "roles/iam.serviceAccountOpenIdTokenCreator", "roles/iam.serviceAccountUser"}

def value(body, key):
    """Full (possibly multi-line, bracket-balanced) text of `key = ...`, or None."""
    m = re.search(r'^[ \t]*' + re.escape(key) + r'[ \t]*=[ \t]*', body, re.M)
    if not m:
        return None
    i, depth = m.end(), 0
    while i < len(body):
        c = body[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if depth < 0 or (c == "\n" and depth == 0):
            break
        i += 1
    return body[m.end():i].strip()

def dir_locals(text):
    out = {}
    for m in LOCALS_RE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        for k in re.findall(r'^[ \t]*(\w+)[ \t]*=', body, re.M):
            out[k] = (value(body, k) or "").strip('"')
    return out

def split_list(text):
    """Top-level comma-separated items of a `[a, b, ...]` expression; a non-list is one item."""
    t = text.strip()
    if not (t.startswith("[") and t.endswith("]")):
        return [t] if t else []
    items, depth, quote, cur = [], 0, False, ""
    for c in t[1:-1]:
        if c == '"':
            quote = not quote
        elif not quote and c in "([{":
            depth += 1
        elif not quote and c in ")]}":
            depth -= 1
        if c == "," and depth == 0 and not quote:
            items.append(cur)
            cur = ""
        else:
            cur += c
    items.append(cur)
    return [i.strip().strip('"') for i in items if i.strip()]

def subst(expr, locs):
    """Substitute local.k with its expression, one level."""
    return re.sub(r'\blocal\.(\w+)', lambda m: locs.get(m.group(1), m.group(0)), expr or "")

def refs(reldir, expr, ids):
    """Component ids referenced in expr, in order."""
    out = []
    for m in REF_RE.finditer(expr or ""):
        cid = f"{reldir}/{m.group(1)}.{m.group(2)}"
        if cid in ids and cid not in out:
            out.append(cid)
    return out

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

def add_edges(out, pending, locals_by_dir, projects):
    ids = {c["id"]: c for c in out["components"]}
    boundaries = {}                     # extra org/folder/project boundaries created by IAM targets

    def unknown(what, source, why):
        u = {"what": what, "source": source, "why": why}
        if u not in out["unknowns"]:
            out["unknowns"].append(u)

    def edge(frm, to, kind, label, source):
        e = {"from": frm, "to": to, "kind": kind, "label": label, "source": source}
        if e not in out["edges"]:
            out["edges"].append(e)

    for reldir, rel, typ, name, line, body in pending:
        src, locs = f"{rel}:{line}", locals_by_dir.get(reldir, {})
        get = lambda k: subst(value(body, k), locs).strip('"') if value(body, k) is not None else None
        if typ == "google_pubsub_subscription":
            topic = get("topic")
            sub = f"{reldir}/{typ}.{name}"
            t = refs(reldir, topic, ids)
            if t:
                edge(t[0], sub, "async", name, src)
            elif topic:
                unknown(f"{typ}.{name} topic", src, f"topic is variable-driven: {topic}")
            endpoint = get("push_endpoint")
            if endpoint is not None:
                svc = [r for r in refs(reldir, endpoint, ids) if ids[r]["kind"] in ("cloud_run_service", "cloud_function")]
                if svc:
                    edge(sub, svc[0], "call", "push", src)
                else:
                    unknown(f"{typ}.{name} push endpoint", src, f"push endpoint is variable-driven: {endpoint}")
        elif typ == "google_cloud_scheduler_job":
            uri = get("uri")
            if uri is not None:
                r = refs(reldir, uri, ids)
                if r:
                    edge(f"{reldir}/{typ}.{name}", r[0], "call", "scheduler", src)
                else:
                    unknown(f"{typ}.{name} uri", src, f"uri is variable-driven: {uri}")
        else:
            add_iam(out, ids, boundaries, reldir, typ, name, src, body, get, refs, unknown, edge, projects)
    out["boundaries"].extend(boundaries.values())

def add_iam(out, ids, boundaries, reldir, typ, name, src, body, get, refs, unknown, edge, projects):
    # target
    target, shown = None, None
    for a in TARGET_ATTRS:
        v = get(a)
        if v is not None:
            shown = v
            r = refs(reldir, v, ids)
            if r:
                target = r[0]
            break
    if target is None and typ == "google_project_iam_member" and attr(body, "project"):
        expr = attr(body, "project")       # raw, like Task 2's boundary ids and `projects` keys
        target = f"{reldir}/project:{expr}"
        if (reldir, expr) not in projects:
            boundaries.setdefault(target, {"id": target, "kind": "project", "name": expr, "members": []})
    elif target is None and typ in ("google_organization_iam_member", "google_folder_iam_member"):
        kind, a = ("org", "org_id") if "organization" in typ else ("folder", "folder")
        expr = get(a)
        if expr:
            target = f"{reldir}/{kind}:{expr}"
            boundaries.setdefault(target, {"id": target, "kind": kind, "name": expr, "members": []})
    if target is None:
        unknown(f"{typ}.{name} target", src, f"target is variable-driven: {shown if shown is not None else '(no recognised target attribute)'}")
        return
    # members: one edge per resolvable member, one unknown per unresolvable one
    if get("member") is not None:
        members = [get("member")]
    else:
        members = split_list(get("members") or "")
    if not members:
        unknown(f"{typ}.{name} members", src, "no member or members attribute found")
    # role and kind
    role = (get("role") or "").strip('"')
    roles = [role]
    label = role
    if role == "each.value":
        listed = re.findall(r'"(roles/[^"]+)"', get("for_each") or "")
        roles = listed or roles
        label = "<for_each roles>" + (": " + ", ".join(listed) if listed else "")
    for member in members:
        pool = [r for r in refs(reldir, member, ids) if ids[r]["kind"] == "wif_pool"]
        principalish = "principalSet://" in member or "principal://" in member
        if principalish and pool:
            frm = pool[0]
        else:
            r = refs(reldir, member, ids)
            if r:
                frm = r[0]
            else:
                frm = f"principal:{member}"
                unknown(frm, src, "principal is not a resource in this repo")
        kind = "trust" if principalish or any(x in TRUST_ROLES for x in roles) else "iam"
        edge(frm, target, kind, label, src)

def extract(root):
    out = {"components": [], "edges": [], "boundaries": [], "unknowns": [], "confidence": "high"}
    projects = {}                       # (reldir, project expr) -> member ids
    vpcs = {}                           # reldir -> (vpc id, member ids)
    locals_by_dir = {}                  # reldir -> {local name: expression}
    pending = []                        # edge-bearing resources, scanned once all components are known
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
        locals_by_dir.setdefault(reldir, {}).update(dir_locals(text))
        for block, typ, name, line, body in blocks(text):
            if block == "resource" and (typ.endswith(("_iam_member", "_iam_binding"))
                                        or typ in ("google_pubsub_subscription", "google_cloud_scheduler_job")):
                pending.append((reldir, rel, typ, name, line, body))
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
    add_edges(out, pending, locals_by_dir, projects)
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
