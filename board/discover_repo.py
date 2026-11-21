#!/usr/bin/env python3
"""discover_repo: repo-side signal collectors for opportunity discovery.

todos() counts a TODO/FIXME/XXX marker only when it sits in a comment (#, //, /*, <!--, a
leading *, or -- before it) and skips paths with a `test` or `tests` directory segment, so
string literals, test fixtures and this module's own docstrings are not findings.

Each collector returns candidates {signal, key, title, evidence[], first_seen, count}
(see the opportunity-discovery design). Every git/gh/npm/pip-audit call goes through the
injectable `run` (default subprocess.run); stdlib only.
"""
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ideas  # noqa: E402

PATH_RE = re.compile(r"[\w./-]+\.(?:py|zsh|js|md|sh|json)")
DEFERRED_RE = re.compile(r"(?i)\b(deferred|parked)\b")
FIX_RE = re.compile(r"(?i)\bfix(?:ed)?\b")
# a marker counts only inside a comment: #, //, /*, <!--, a leading *, or -- before it
TODO_RE = re.compile(r"(?:#|//|/\*|<!--|^\s*\*|--).*\b(?:TODO|FIXME|XXX)\b")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
MAX_EVIDENCE = 20
WINDOW_DAYS = 30
SEVERE = {"moderate", "medium", "high", "critical"}


def _sha1(s, n):
    return hashlib.sha1(s.encode()).hexdigest()[:n]


def _sh(run, argv, cwd=None):
    """One external call through `run`; never raises: (rc, stdout, stderr), rc None when it could not run."""
    try:
        r = run(argv, cwd=str(cwd) if cwd is not None else None, capture_output=True, text=True,
                timeout=120, errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", f"{type(e).__name__}: {e}"
    return r.returncode, r.stdout or "", r.stderr or ""


def _git(run, root, *args):
    return _sh(run, ["git", "-C", str(root), *args])


def _head(run, root):
    rc, out, _ = _git(run, root, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _naive(now):
    """datetime (naive local or aware) or epoch seconds -> naive local datetime; None -> now."""
    if now is None:
        return datetime.now()
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now)
    if now.tzinfo is not None:
        return now.astimezone().replace(tzinfo=None)
    return now


def link(root, head, path, line, run=subprocess.run):
    """https blob URL of path@head for a GitHub or GitLab origin; None otherwise."""
    if not head or not path:
        return None
    rc, out, _ = _git(run, root, "remote", "get-url", "origin")
    url = out.strip()
    if rc != 0 or not url:
        return None
    m = (re.match(r"^(?:https?|ssh|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
         or re.match(r"^(?:[^@/]+@)?([^/:]+):(.+?)(?:\.git)?/?$", url))
    if not m:
        return None
    host, repo = m[1].lower(), m[2]
    frag = f"#L{line}" if line else ""
    if host == "github.com":
        return f"https://github.com/{repo}/blob/{head}/{path}{frag}"
    if "gitlab" in host:
        return f"https://{host}/{repo}/-/blob/{head}/{path}{frag}"
    return None


def _ledgers(root):
    """[(dir name, date or None, progress.md path)] ascending by name; [] when there is no ledgers dir."""
    base = Path(root) / "docs" / "superpowers" / "ledgers"
    out = []
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            f = d / "progress.md"
            if f.is_file():
                m = DATE_RE.match(d.name)
                out.append((d.name, m[1] if m else None, f))
    return out


def _lines(f):
    try:
        return f.read_text(errors="replace").splitlines()
    except OSError:
        return []


def _first_seen(ledgers):
    ds = [d for _, d, _ in ledgers if d]
    return min(ds) if ds else date.today().isoformat()


def repeated_rulings(root, now=None, run=subprocess.run):
    root = Path(root)
    ledgers = _ledgers(root)
    if not ledgers:
        return []
    # rows: (dir, relpath, lineno, raw text, normalised words, first path)
    rows = []
    for name, _, f in ledgers:
        rel = f"docs/superpowers/ledgers/{name}/progress.md"
        for i, line in enumerate(_lines(f), 1):
            if "Ruling:" not in line:
                continue
            text = line.split("Ruling:", 1)[1]
            text = re.split(r" [—-] cost if wrong", text, maxsplit=1)[0]
            m = PATH_RE.search(text)
            rows.append({"dir": name, "rel": rel, "line": i, "raw": line.strip(),
                         "words": re.findall(r"[a-z0-9]+", text.lower()), "path": m[0] if m else None})
    head = _head(run, root)
    used = set()
    cands = []

    def emit(group, key, title):
        for r in group:
            used.add(id(r))
        cands.append({"signal": "repeated_ruling", "key": key, "title": title,
                      "evidence": [{"text": r["raw"], "path": r["rel"], "line": r["line"],
                                   "url": link(root, head, r["rel"], r["line"], run=run)}
                                   for r in group][-MAX_EVIDENCE:],
                      "first_seen": _first_seen([l for l in ledgers if l[0] in {r["dir"] for r in group}]),
                      "count": len({r["dir"] for r in group})})

    groups = {}
    for r in rows:
        if len(r["words"]) >= 6:
            groups.setdefault(tuple(r["words"][:6]), []).append(r)
    for words, g in groups.items():
        if len({r["dir"] for r in g}) >= 3:
            emit(g, "repeated_ruling:" + "-".join(words), "Repeated ruling: " + " ".join(words) + " …")
    groups = {}
    for r in rows:
        if id(r) not in used and r["path"] and len(r["words"]) >= 3:
            groups.setdefault((r["path"], tuple(r["words"][:3])), []).append(r)
    for (path, words), g in groups.items():
        if len({r["dir"] for r in g}) >= 3:
            emit(g, f"repeated_ruling:{path}:" + "-".join(words), f"Repeated ruling on {path}: " + " ".join(words) + " …")
    return cands


def deferred_minors(root, run=subprocess.run):
    root = Path(root)
    ledgers = _ledgers(root)
    head = _head(run, root)
    cands = []
    for name, day, f in ledgers:
        if not day:
            continue
        text = f.read_text(errors="replace") if f.is_file() else ""
        rel = f"docs/superpowers/ledgers/{name}/progress.md"
        for i, line in enumerate(_lines(f), 1):
            if not DEFERRED_RE.search(line):
                continue
            path = next((m[0] for m in PATH_RE.finditer(line)
                         if _git(run, root, "cat-file", "-e", f"HEAD:{m[0]}")[0] == 0), None)
            if not path:
                continue
            rc, out, _ = _git(run, root, "log", f"--since={day}", "--format=%H", "--", path)
            shas = out.split() if rc == 0 else []
            if not any(s[:7] not in text for s in shas):
                continue
            if any(d2 and d2 > day and path in l2 and FIX_RE.search(l2)
                   for _, d2, f2 in ledgers for l2 in _lines(f2)):
                continue
            stripped = line.strip()
            cands.append({"signal": "deferred_minor", "key": f"deferred_minor:{name}:{_sha1(stripped, 8)}",
                          "title": f"Deferred in {name} and {path} changed since: {stripped[:100]}",
                          "evidence": [{"text": stripped, "path": rel, "line": i,
                                        "url": link(root, head, rel, i, run=run)}],
                          "first_seen": day, "count": len(shas)})
    return cands


def _in_tests(path):
    return any(seg in ("test", "tests") for seg in path.split("/")[:-1])


def todos(root, now, run=subprocess.run):
    root = Path(root)
    since = (_naive(now) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    rc, out, _ = _git(run, root, "log", "-p", f"--since={since}", "--no-merges", "-U0", "--format=@@@ %aI")
    if rc != 0:
        return []
    head = _head(run, root)
    found = {}   # (path, stripped) -> earliest adding date
    cur_date, cur_path = None, None
    for line in out.splitlines():
        if line.startswith("@@@ "):
            cur_date, cur_path = line[4:14], None
        elif line.startswith("+++ "):
            cur_path = line[6:] if line.startswith("+++ b/") else None
        elif (line.startswith("+") and cur_path and not cur_path.endswith(".md") and not _in_tests(cur_path)
              and TODO_RE.search(line[1:])):
            found[(cur_path, line[1:].strip())] = cur_date   # log is newest first: the last write is the oldest
    show = {}
    cands = []
    for (path, text), day in found.items():
        if path not in show:
            rc, body, _ = _git(run, root, "show", f"HEAD:{path}")
            show[path] = body.splitlines() if rc == 0 else []
        lines = [l.strip() for l in show[path]]
        if text not in lines:
            continue
        n = lines.index(text) + 1
        cands.append({"signal": "todo", "key": f"todo:{path}:{_sha1(text, 8)}",
                      "title": f"{path}: {text[:100]}",
                      "evidence": [{"text": text, "path": path, "line": n,
                                    "url": link(root, head, path, n, run=run)}],
                      "first_seen": day, "count": 1})
    return sorted(cands, key=lambda c: c["key"])


def _first_line(s, default):
    for l in s.splitlines():
        if l.strip():
            return l.strip()
    return default


def _gh_why(err):
    line = _first_line(err, "failed")
    return line if line.startswith("gh:") else f"gh: {line}"


def _github_alerts(root, run, cands, skipped):
    rc, out, _ = _git(run, root, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", out.strip()) if rc == 0 else None
    if not m:
        return False
    rc, _, err = _sh(run, ["gh", "auth", "status"], cwd=root)
    if rc != 0:
        skipped.append({"signal": "dependency", "why": _gh_why(err)})
        return True
    rc, out, err = _sh(run, ["gh", "api", f"repos/{m[1]}/{m[2]}/dependabot/alerts?state=open&per_page=100"], cwd=root)
    if rc != 0:
        skipped.append({"signal": "dependency", "why": _gh_why(err)})
        return True
    try:
        alerts = json.loads(out)
    except ValueError:
        skipped.append({"signal": "dependency", "why": "gh: unreadable alerts JSON"})
        return True
    for a in alerts if isinstance(alerts, list) else []:
        adv = a.get("security_advisory") or {}
        if (adv.get("severity") or "").lower() not in SEVERE:
            continue
        pkg = (a.get("dependency") or {}).get("package") or {}
        title = f"{pkg.get('name')} ({pkg.get('ecosystem')}): {adv.get('summary')}"
        cands.append({"signal": "dependency", "key": f"dependency:github:{a.get('number')}", "title": title,
                      "evidence": [{"text": f"{adv.get('severity')} {adv.get('ghsa_id')}: {adv.get('summary')}",
                                    "path": None, "line": None, "url": a.get("html_url")}],
                      "first_seen": (a.get("created_at") or date.today().isoformat())[:10], "count": 1})
    return True


def dependencies(root, run=subprocess.run):
    root = Path(root)
    cands, skipped = [], []
    checked = _github_alerts(root, run, cands, skipped)
    rc, out, _ = _git(run, root, "ls-files")
    tracked = out.splitlines() if rc == 0 else []
    today = date.today().isoformat()
    for lock in (t for t in tracked if t.rsplit("/", 1)[-1] == "package-lock.json"):
        d = str(Path(lock).parent)
        checked = True
        rc, out, err = _sh(run, ["npm", "audit", "--json"], cwd=root / d)
        try:
            vulns = json.loads(out).get("vulnerabilities") or {}
        except (ValueError, AttributeError):
            skipped.append({"signal": "dependency", "why": f"npm: {_first_line(err, 'no audit JSON')} ({d})"})
            continue
        for pkg, v in vulns.items():
            if (v.get("severity") or "").lower() in SEVERE:
                cands.append({"signal": "dependency", "key": f"dependency:npm:{d}:{pkg}",
                              "title": f"{pkg} ({d}): {v.get('severity')} npm vulnerability",
                              "evidence": [{"text": f"{pkg} {v.get('range', '')} {v.get('severity')}".strip(),
                                            "path": lock, "line": None, "url": None}],
                              "first_seen": today, "count": 1})
    seen = set()
    for req in (t for t in tracked if fnmatch.fnmatch(t.rsplit("/", 1)[-1], "requirements*.txt")):
        rc, out, err = _sh(run, ["pip-audit", "-f", "json", "-r", req], cwd=root)
        if rc is None:
            break   # pip-audit not installed: not a finding and not worth a skipped line
        try:
            deps = json.loads(out).get("dependencies") or []
        except (ValueError, AttributeError):
            skipped.append({"signal": "dependency", "why": f"pip-audit: {_first_line(err, 'no JSON')} ({req})"})
            continue
        checked = True
        for dep in deps:   # pip-audit reports no severity: every vulnerability counts as moderate or worse
            for v in dep.get("vulns") or []:
                key = f"dependency:pip:{dep.get('name')}:{v.get('id')}"
                if key not in seen:
                    seen.add(key)
                    cands.append({"signal": "dependency", "key": key,
                                  "title": f"{dep.get('name')} {dep.get('version')}: {v.get('id')}",
                                  "evidence": [{"text": f"{dep.get('name')} {v.get('id')} fix {v.get('fix_versions')}",
                                                "path": req, "line": None, "url": None}],
                                  "first_seen": today, "count": 1})
    if not checked and not skipped:
        skipped.append({"signal": "dependency", "why": "no GitHub remote and no tracked lockfile"})
    return cands, skipped


def stale_ideas(project, now):
    cutoff = _naive(now) - timedelta(days=WINDOW_DAYS)
    now = _naive(now)
    cands = []
    for i in ideas.load(project):
        if i["status"] != "open":
            continue
        ts = datetime.strptime(i["ts"], "%Y-%m-%d %H:%M")
        if ts >= cutoff:
            continue
        cands.append({"signal": "stale_idea", "key": f"stale_idea:{_sha1(i['key'], 12)}",
                      "title": f"Open idea for {(now - ts).days} days: {i['text'][:100]}",
                      "evidence": [{"text": i["text"], "path": None, "line": None, "url": None}],
                      "first_seen": i["ts"][:10], "count": (now - ts).days})
    return cands
