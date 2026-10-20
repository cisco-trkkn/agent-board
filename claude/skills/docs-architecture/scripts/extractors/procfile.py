"""Procfile extractor: each `name: command` line → a service_source component."""
import os, re
from . import terraform

LINE_RE = re.compile(r'^([A-Za-z0-9_-]+):\s*(.+?)\s*$')
TARGET_RE = re.compile(r'--target[= ](\S+)')

def extract(root):
    out = {"components": [], "edges": [], "boundaries": [], "unknowns": [], "confidence": "high"}
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in terraform.SKIP_DIRS)
        if "Procfile" not in files:
            continue
        rel = os.path.relpath(os.path.join(d, "Procfile"), root)
        reldir = os.path.dirname(rel)
        with open(os.path.join(d, "Procfile"), encoding="utf-8", errors="replace") as fh:
            for n, raw in enumerate(fh.read().splitlines(), 1):
                m = LINE_RE.match(raw)
                if not m or raw.lstrip().startswith("#"):
                    continue
                name, cmd = m.groups()
                t = TARGET_RE.search(cmd)
                cid = f"{reldir}/procfile.{name}"
                src = f"{rel}:{n}"
                out["components"].append({"id": cid, "kind": "service_source",
                                          "name": f"{os.path.basename(reldir) or '.'}: {t.group(1) if t else cmd.split()[0]}",
                                          "project": None, "env": None, "source": src})
                out["unknowns"].append({"what": cid, "source": src,
                                        "why": "deploy target (Cloud Run service) not declared in this repo"})
    return out
