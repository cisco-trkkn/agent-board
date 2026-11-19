"""The checks that decide whether a consolidated core and archive may replace the old ones.

Pure functions over file texts (G2-G5 of the memory-consolidation plan), plus a `verify` CLI.
Imports nothing from the board."""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

CAP = 8192   # context.CAP; test_cap_matches_context keeps them equal
SECTIONS = ("Map", "How to run", "Gotchas", "Decisions")
ENTRY_RE = re.compile(r"^- .+ · (\d{4}-\d{2}-\d{2})( · archived \d{4}-\d{2}-\d{2})?( · stale: .+ gone)?$")
SUFFIX_RE = re.compile(r"( · archived \d{4}-\d{2}-\d{2})?( · stale: .+ gone)?$")
FILES_RE = re.compile(r"\(files: ([^)]*)\)")
STALE_RE = re.compile(r" · stale: .+ gone$")
SKELETON = "".join(f"## {s}\n\n" for s in SECTIONS)


def base(line):
    """The entry without its archive suffixes: what must survive a run byte for byte."""
    return SUFFIX_RE.sub("", line)


def files_of(line):
    m = FILES_RE.search(line)
    return {f.strip() for f in m.group(1).split(",") if f.strip()} if m else set()


def date_of(line):
    """The entry's own date (the first date group), never the `archived` date."""
    return ENTRY_RE.match(line).group(1)


def parse(text):
    """(entries, problems): entries is [(section, line)] in file order; problems is empty when the file is well formed."""
    entries, problems, seen, section = [], [], [], None
    for n, line in enumerate(text.split("\n"), 1):
        if line.startswith("## "):
            section = line[3:]
            seen.append(section)
        elif line.startswith("- "):
            if section is None:
                problems.append(f"line {n}: entry before any heading")
            elif not ENTRY_RE.match(line):
                problems.append(f"line {n}: not a valid entry")
            else:
                entries.append((section, line))
        elif line.strip() and not (section is None and (line.startswith("# ") or line.startswith("Last curated: "))):
            problems.append(f"line {n}: not an entry, heading or blank")
    if tuple(seen) != SECTIONS:
        problems.append(f"headings are {seen}, want {list(SECTIONS)}")
    return entries, problems


def lost(old_lines, new_lines, merged):
    """Old entries that survive neither verbatim nor through a declared merge. merged = report['changed']['merged']."""
    new_bases = {base(l) for l in new_lines}
    out = []
    for o in old_lines:
        if base(o) in new_bases:
            continue
        ok = False
        for m in merged:
            if o[:60] not in m.get("from", []):
                continue
            for t in new_lines:
                if t[:60] == m.get("into") and files_of(t) >= files_of(o) and date_of(t) >= date_of(o):
                    ok = True
        if not ok:
            out.append(o)
    return out


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(s, str) for s in v)


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool)


def report_problem(report):
    """None when the report has G4's shape, else the reason."""
    if not isinstance(report, dict):
        return "report is not an object"
    ch = report.get("changed")
    if not isinstance(ch, dict):
        return "changed is not an object"
    merged = ch.get("merged")
    if not isinstance(merged, list):
        return "changed.merged is not a list"
    for m in merged:
        if not (isinstance(m, dict) and isinstance(m.get("into"), str) and _is_str_list(m.get("from"))):
            return "changed.merged item needs into (string) and from (list of strings)"
    for k in ("archived", "stale", "added"):
        if not _is_count(ch.get(k)):
            return f"changed.{k} is not an integer"
    con = report.get("contradictions")
    if not isinstance(con, list):
        return "contradictions is not a list"
    for c in con:
        if not (isinstance(c, dict) and all(isinstance(c.get(k), str) for k in ("a", "b", "note"))):
            return "contradictions item needs a, b and note (strings)"
    props = report.get("proposals")
    if not isinstance(props, list):
        return "proposals is not a list"
    for p in props:
        if not isinstance(p, dict):
            return "proposals item is not an object"
        if p.get("kind") not in ("idea", "observer"):
            return "proposals kind must be idea or observer"
        if not (isinstance(p.get("text"), str) and p["text"].strip()):
            return "proposals text is empty"
        if not _is_str_list(p.get("evidence")):
            return "proposals evidence is not a list of strings"
    if not isinstance(report.get("summary"), str):
        return "summary is not a string"
    return None


def _archive(text):
    return text if text.strip() else SKELETON


def _lines(text):
    return [l for _, l in parse(_archive(text))[0]]


def check(old_core, old_archive, new_core, new_archive, report, root=None):
    """None when G5's file checks pass, else the check text (first failure, in G5's order)."""
    why = report_problem(report)
    if why:
        return f"report invalid: {why}"
    entries, problems = parse(new_core)
    if problems:
        return f"core invalid: {problems[0]}"
    if any(l != base(l) for _, l in entries):
        return "core invalid: archived entry in the core"
    size = len(new_core.encode("utf-8"))
    if size > CAP:
        return f"core over {CAP} bytes ({size})"
    a_entries, a_problems = parse(_archive(new_archive))
    if a_problems:
        return f"archive invalid: {a_problems[0]}"
    old = _lines(old_core) + _lines(old_archive)
    new = [l for _, l in entries] + [l for _, l in a_entries]
    gone = lost(old, new, report["changed"]["merged"])
    if gone:
        return f"entry lost: {gone[0][:60]}"
    if root is not None:
        was_stale = {base(l) for l in old if STALE_RE.search(l)}
        for _, l in a_entries:
            if STALE_RE.search(l) and base(l) not in was_stale:
                files = sorted(files_of(l))
                if not files:
                    return "stale claim: no files cited"
                for f in files:
                    if (Path(root) / f).exists():
                        return f"stale claim: {f} exists"
    return None


def counts(old_core, old_archive, new_core, new_archive, report):
    """{"merged", "archived", "stale", "added"} recomputed from the files (G4), whatever the report claims."""
    old_core_l, old_arch_l = _lines(old_core), _lines(old_archive)
    old = old_core_l + old_arch_l
    new_core_l, new_arch_l = _lines(new_core), _lines(new_archive)
    new = new_core_l + new_arch_l
    merged = report.get("changed", {}).get("merged", [])
    new_bases = {base(l) for l in new}
    old_bases = {base(l) for l in old}
    unaccounted = set(lost(old, new, merged))
    n_merged = sum(1 for o in old if base(o) not in new_bases and o not in unaccounted)
    arch_bases = {base(l) for l in new_arch_l}
    archived = sum(1 for o in old_core_l if base(o) in arch_bases)
    was_stale = {base(l) for l in old if STALE_RE.search(l)}
    stale = sum(1 for l in new_arch_l if STALE_RE.search(l) and base(l) not in was_stale)
    intos = {m.get("into") for m in merged}
    added = sum(1 for l in new if base(l) not in old_bases and l[:60] not in intos)
    return {"merged": n_merged, "archived": archived, "stale": stale, "added": added}


def diff(old_core, old_archive, new_core, new_archive, project):
    """One unified diff over both files; empty when nothing changed."""
    out = []
    for name, a, b in ((f"{project}.md", old_core, new_core),
                       (f"{project}.archive.md", _archive(old_archive), _archive(new_archive))):
        out.extend(difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True),
                                        fromfile=name, tofile=name))
    return "".join(out)


def _read(path, missing_ok=False):
    p = Path(path)
    if missing_ok and not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dream_check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    for f in ("old-core", "old-archive", "new-core", "new-archive", "report"):
        v.add_argument(f"--{f}", required=True)
    v.add_argument("--root")
    a = ap.parse_args(argv)
    try:
        report = json.loads(_read(a.report))
    except (OSError, ValueError) as ex:
        report = f"unreadable: {ex}"
    res = check(_read(a.old_core), _read(a.old_archive, True), _read(a.new_core),
                _read(a.new_archive, True), report, a.root)
    print("ok" if res is None else res)
    return 0 if res is None else 1


if __name__ == "__main__":
    sys.exit(main())
