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
disable undelete rollback cancel run set rm cp mv rsync publish execute call submit
add-metadata remove-metadata replace invoke trigger""".split())
GCLOUD_PATHS = {tuple(p.split()) for p in """projects|organizations|resource-manager folders|services|run services
|run jobs|run revisions|iam service-accounts|iam roles|iam workload-identity-pools
|iam workload-identity-pools providers|pubsub topics|pubsub subscriptions|sql instances|sql databases
|storage buckets|secrets|functions|compute instances|compute networks|container clusters
|artifacts repositories|scheduler jobs|logging sinks|logging metrics|builds|builds triggers
|dns managed-zones|bigquery datasets""".replace("\n", "").split("|")}
GROUP_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TRACKS = {"alpha", "beta"}
SQL_DENY = set("""INSERT UPDATE DELETE MERGE CREATE DROP ALTER TRUNCATE GRANT REVOKE EXPORT CALL
DECLARE SET BEGIN EXECUTE LOAD""".split())
BQ_WRITE_FLAGS = ("--destination_", "--replace", "--append_table", "--schedule")

def _flag(t):
    return t.startswith("-")

def _flagfile(args):
    return any(_flag(t) and any(w in t.lower() for w in ("flagfile", "flags-file", "bigqueryrc")) for t in args)

def _gcloud(args):
    if args == ["--version"]:
        return True, "ok"
    if _flagfile(args):
        return False, "gcloud: flag files can inject flags"
    toks = [t for t in args if not _flag(t)]
    if toks[:1] and toks[0] in TRACKS:
        toks = toks[1:]
    # shape: <group...> <read verb> [<one resource arg>]
    for v in (len(toks) - 1, len(toks) - 2):
        if v >= 1 and toks[v] in GCLOUD_READ:
            group, resource = toks[:v], toks[v + 1:]
            break
    else:
        return False, "gcloud: not '<group...> <read verb> [<resource>]' (read verbs: describe, list, get-iam-policy, get-ancestors)"
    for i, t in enumerate(group):
        if not GROUP_RE.match(t):
            return False, f"gcloud: '{t}' is not a command-group token"
        if t in GCLOUD_DENY and not (t == "run" and i == 0):
            return False, f"gcloud: deny word '{t}'"
    if resource and resource[0] in GCLOUD_DENY:
        return False, f"gcloud: deny word '{resource[0]}'"
    if tuple(group) not in GCLOUD_PATHS:
        return False, f"gcloud: command path '{' '.join(group)}' is not in the allowlist"
    return True, "ok"

def _code_only(sql):
    """SQL with comments removed and string/quoted-identifier contents blanked, or None if unterminated."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i) or c == "#":
            m = re.compile(r"[\r\n]").search(sql, i)
            i = n if m is None else m.start()
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

def _sql_ok(sql):
    if re.search(r"\bEXTERNAL_QUERY\b", sql, re.I):
        return False, "bq: EXTERNAL_QUERY sends a string to another database"
    code = _code_only(sql)
    if code is None:
        return False, "bq: unterminated string or comment"
    stmts = [s for s in code.split(";") if s.strip()]
    if len(stmts) != 1:
        return False, "bq: query must be exactly one statement"
    words = re.findall(r"[A-Za-z_]+", stmts[0])
    if not words or words[0].upper() not in ("SELECT", "WITH"):
        return False, "bq: query must start with SELECT or WITH"
    bad = sorted({w.upper() for w in words} & SQL_DENY)
    if bad:
        return False, f"bq: SQL keyword {bad[0]}"
    return True, "ok"

def _bq(args):
    if _flagfile(args):
        return False, "bq: flag files can inject flags"
    toks = [t for t in args if not _flag(t)]
    if not toks:
        return False, "bq: no subcommand"
    for t in args[:args.index(toks[0])]:
        if "=" not in t:
            return False, f"bq: global flag '{t}' must be written --name=value"
    sub = toks[0]
    if sub in ("show", "ls"):
        return True, "ok"
    if sub != "query":
        return False, f"bq: subcommand '{sub}' is not read-only"
    if any(f.startswith(BQ_WRITE_FLAGS) for f in args if _flag(f)):
        return False, "bq: query writes to a destination"
    rest = toks[1:]
    if len(rest) != 1:
        return False, "bq: query needs exactly one SQL argument"
    # --dry_run/--nodry_run relax nothing: the SQL is checked the same either way.
    return _sql_ok(rest[0])

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
