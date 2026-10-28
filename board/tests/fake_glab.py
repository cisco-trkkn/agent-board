#!/usr/bin/env python3
"""A stand-in for `glab api -i -X METHOD PATH [-f k=v]...` in tests.

$FAKE_GLAB_DIR/log.jsonl  gets one {"method", "path", "fields"} line per call.
$FAKE_GLAB_DIR/rules.json is a list of {"method", "path_re", "status", "body", "remaining", "once"};
the first rule whose method matches and whose path_re re.search-es the path answers (a "once" rule is
then removed). No match: GET -> 200 [], anything else -> 200 {}. The header block is the real
capture in fixtures/glab/list-empty-200.txt, with the status line and Ratelimit-Remaining replaced.
"""
import json
import os
import re
import sys
from pathlib import Path

d = Path(os.environ["FAKE_GLAB_DIR"])
argv = sys.argv[1:]
if argv[:2] != ["api", "-i"] or argv[2] != "-X":
    print(f"fake glab: unexpected argv {argv}", file=sys.stderr)
    sys.exit(2)
method, path, rest = argv[3], argv[4], argv[5:]
fields = {}
while rest:
    flag, kv, rest = rest[0], rest[1], rest[2:]
    assert flag == "-f", flag
    k, _, v = kv.partition("=")
    fields[k] = v
with open(d / "log.jsonl", "a") as f:
    f.write(json.dumps({"method": method, "path": path, "fields": fields}) + "\n")
rules_f = d / "rules.json"
rules = json.loads(rules_f.read_text()) if rules_f.exists() else []
hit = next((r for r in rules if r.get("method", "GET") == method and re.search(r["path_re"], path)), None)
if hit and hit.get("once"):
    rules.remove(hit)
    rules_f.write_text(json.dumps(rules))
status = hit["status"] if hit else 200
body = hit["body"] if hit else ([] if method == "GET" else {})
remaining = str(hit.get("remaining", 1990)) if hit else "1990"
head = (Path(__file__).resolve().parent / "fixtures" / "glab" / "list-empty-200.txt").read_text()
head = head.replace("\r\n", "\n").partition("\n\n")[0].split("\n")[1:]
head = [l for l in head if not l.lower().startswith(("ratelimit-remaining", "content-length"))]
reason = {200: "OK", 201: "Created", 404: "Not Found", 429: "Too Many Requests", 500: "Internal Server Error"}.get(status, "X")
text = json.dumps(body)
out = f"HTTP/2.0 {status} {reason}\n" + "".join(f"{l}\r\n" for l in head + [f"Ratelimit-Remaining: {remaining}", f"Content-Length: {len(text)}"]) + "\r\n" + text
sys.stdout.write(out)
if status >= 400:
    msg = body.get("message", "error") if isinstance(body, dict) else "error"
    print(f"glab: {msg} (HTTP {status})", file=sys.stderr)
    sys.exit(1)
