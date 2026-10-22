#!/usr/bin/env python3
"""Read-only cloud gate: run a gcloud/bq command only if it is on the allowlist, log every run.

Usage: cloud_read.py --log <path> -- <command...>
Exit: 0 command exited 0; 1 command failed; 2 refused (nothing ran, nothing logged).
Rules: references/cloud-allowlist.md. Fails closed: anything not positively recognised is refused.
"""
import datetime, json, os, re, shlex, subprocess, sys

GCLOUD_READ = {"describe", "list", "get-iam-policy", "get-ancestors"}
GCLOUD_DENY = set("""create delete update patch set-iam-policy add-iam-policy-binding
remove-iam-policy-binding deploy apply import export ssh scp reset start stop resize enable
disable undelete rollback cancel run set""".split())
TRACKS = {"alpha", "beta"}
SQL_DENY = set("""INSERT UPDATE DELETE MERGE CREATE DROP ALTER TRUNCATE GRANT REVOKE EXPORT CALL
DECLARE SET BEGIN EXECUTE LOAD""".split())
BQ_WRITE_FLAGS = ("--destination_", "--replace", "--append_table", "--schedule")

def _flag(t):
    return t.startswith("-")

def _gcloud(args):
    if args == ["--version"]:
        return True, "ok"
    toks = [t for t in args if not _flag(t)]
    if not toks:
        return False, "gcloud: no command"
    group = 1 if toks[0] in TRACKS and len(toks) > 1 else 0
    for i, t in enumerate(toks):
        if t in GCLOUD_DENY and not (t == "run" and i == group):
            return False, f"gcloud: deny word '{t}'"
    if not GCLOUD_READ & set(toks):
        return False, "gcloud: no read verb (describe, list, get-iam-policy, get-ancestors)"
    return True, "ok"

def _code_only(sql):
    """SQL with comments removed and string/quoted-identifier contents blanked, or None if unterminated."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i) or c == "#":
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                return None
            i, _ = j + 2, out.append(" ")
        elif c in "'\"`":
            j = i + 1
            while j < n and sql[j] != c:
                j += 2 if sql[j] == "\\" else 1
            if j >= n:
                return None
            out.append(c + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)

def _sql_ok(sql, dry):
    code = _code_only(sql)
    if code is None:
        return False, "bq: unterminated string or comment"
    stmts = [s for s in code.split(";") if s.strip()]
    if len(stmts) != 1:
        return False, "bq: query must be exactly one statement"
    if dry:
        return True, "ok"
    words = re.findall(r"[A-Za-z_]+", stmts[0])
    if not words or words[0].upper() not in ("SELECT", "WITH"):
        return False, "bq: query must start with SELECT or WITH"
    bad = sorted({w.upper() for w in words} & SQL_DENY)
    if bad:
        return False, f"bq: SQL keyword {bad[0]}"
    return True, "ok"

def _bq(args):
    toks = [t for t in args if not _flag(t)]
    if not toks:
        return False, "bq: no subcommand"
    sub = toks[0]
    if sub in ("show", "ls"):
        return True, "ok"
    if sub != "query":
        return False, f"bq: subcommand '{sub}' is not read-only"
    flags = [t for t in args if _flag(t)]
    if any(f.startswith(BQ_WRITE_FLAGS) for f in flags):
        return False, "bq: query writes to a destination"
    rest = toks[1:]
    if len(rest) != 1:
        return False, "bq: query needs exactly one SQL argument"
    dry = any(f == "--dry_run" or f.lower() == "--dry_run=true" for f in flags)
    return _sql_ok(rest[0], dry)

def allowed(argv):
    """(True, 'ok') when argv is a read-only gcloud/bq command, else (False, reason)."""
    if not argv:
        return False, "empty command"
    if argv[0] == "gcloud":
        return _gcloud(argv[1:])
    if argv[0] == "bq":
        return _bq(argv[1:])
    return False, f"'{argv[0]}' is not gcloud or bq"

def _refuse(reason):
    print(f"refused: {reason}")
    return 2

def main(argv, run=subprocess.run):
    if "--" not in argv:
        return _refuse("usage: cloud_read.py --log <path> -- <command...>")
    i = argv.index("--")
    head, cmd = argv[:i], argv[i + 1:]
    if len(head) != 2 or head[0] != "--log":
        return _refuse("usage: cloud_read.py --log <path> -- <command...>")
    log_path = head[1]
    ok, reason = allowed(cmd)
    if not ok:
        return _refuse(reason)
    entries = []
    if os.path.exists(log_path):
        try:
            entries = json.load(open(log_path))
            n = 1 + max([e["n"] for e in entries] or [0])
        except (ValueError, TypeError, KeyError):
            return _refuse(f"unreadable log {log_path}")
    else:
        n = 1
    try:
        r = run(cmd, capture_output=True, text=True, timeout=120)
        code, output = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        code, output = 124, "timeout after 120s"
    except OSError as e:
        code, output = 127, str(e)
    entry = {"n": n, "command": shlex.join(cmd),
             "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
             "exit": code, "output": output}
    entries.append(entry)
    with open(log_path, "w") as f:
        json.dump(entries, f, indent=1)
    print(json.dumps(entry))
    return 0 if code == 0 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
