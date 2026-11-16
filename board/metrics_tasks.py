"""Per-task metric lines: a ledger (progress.md), a plan's .tasks.json, the routing map and usage rows.

Pure functions. Rows go to tasks by ruling R1: by owner and ledger order, split by each task's end time.
"""
import json
import re

import metrics
import usage

TASK = re.compile(r"^Task (\d+): (.*)$")
DISPATCH = re.compile(r"^(?:fix round \d+(?:/\d+)? )?dispatched (?:to )?(?:fresh )?([A-Za-z0-9_-]+)(?: \((haiku|sonnet|opus|fable|inherit)\b)?")
REVIEW = re.compile(r"review dispatched (?:to )?([A-Za-z0-9_-]+)")
FIX = re.compile(r"fix round (\d+)")
COMMITS = re.compile(r"commits (.*)")
RANGE = re.compile(r"([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})")
FIX_FINDING = re.compile(r"fix round \d+(?:/\d+)? dispatched.*?\((Critical|Important):")
REVIEW_RESULT = re.compile(r"^(?:scoped )?(?:re-)?review(?! dispatched)")
SEVERITY = re.compile(r"(?:(\d+) )?(Critical|Important)\b")
FAMILIES = ("haiku", "sonnet", "opus", "fable")
TOKEN_COLS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
KEYS = ("spec", "batch", "task_id", "subject", "tier", "model_mapped", "model_used", "escalated", "owner",
        "started_at", "ended_at", "active_s", "tokens", "usd", "review_tokens", "review_usd", "fix_rounds",
        "findings", "review_rounds", "outcome", "code_in_steps", "partial")


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), None)


def _blank():
    return {"owners": [], "dispatch_models": [], "reviewers": [], "review_ends": [], "fix_rounds": 0,
            "findings": {"critical": 0, "important": 0, "minor": 0},
            "review_rounds": 0, "complete": False, "commit_end": None, "complete_at": None}


def parse_ledger(progress):
    """{task number: facts}. `complete_at` is the line index of the task's `complete` line (ledger order)."""
    out = {}
    named = {}   # task -> severities the review lines named since the last fix dispatch
    for i, line in enumerate((progress or "").splitlines()):
        m = TASK.match(line.strip().lstrip("-* ").strip())
        if not m:
            continue
        num = int(m.group(1))
        t = out.setdefault(num, _blank())
        rest = m.group(2)
        if rest.startswith("minor (deferred"):   # free text: no keyword in it is a ledger event
            t["findings"]["minor"] += 1
            continue
        d = DISPATCH.match(rest)
        if d:
            if d.group(1) not in t["owners"]:
                t["owners"].append(d.group(1))
            if d.group(2):
                t["dispatch_models"].append(d.group(2))
        for r in REVIEW.finditer(rest):
            if r.group(1) not in t["reviewers"]:
                t["reviewers"].append(r.group(1))
            rng = RANGE.findall(rest[r.end():])  # the reviewed range: `(A..B)` or `package review-A..B.diff`
            if rng:
                t["review_ends"].append(rng[-1][1])
        if "review dispatched" in rest or "re-review" in rest:
            t["review_rounds"] += 1
        for f in FIX.finditer(rest):
            t["fix_rounds"] = max(t["fix_rounds"], int(f.group(1)))
        c = COMMITS.search(rest)
        if c and RANGE.findall(c.group(1)):
            t["commit_end"] = RANGE.findall(c.group(1))[-1][1]
        if rest.startswith("complete"):
            t["complete"] = True
            t["complete_at"] = i
        sev = re.match(r"(Critical|Important):", rest)
        if sev:
            t["findings"][sev.group(1).lower()] += 1
        if REVIEW_RESULT.match(rest):
            seen = {}
            for f in SEVERITY.finditer(rest):
                k = f.group(2).lower()
                seen[k] = max(seen.get(k, 0), int(f.group(1)) if f.group(1) else 1)
            for k, n in seen.items():
                t["findings"][k] += n
                named.setdefault(num, set()).add(k)
        ff = FIX_FINDING.search(rest)
        if ff:
            k = ff.group(1).lower()
            if k not in named.get(num, ()):   # the review line of this round already counted it
                t["findings"][k] += 1
            named.pop(num, None)
    return out


FENCE = re.compile(r"^\s*(`{3,})(.*)$")


def _fences(lines):
    """Yield (line index, opening tag or None for a closing line, in_fence) walking lines with fence pairing: a fence
    opened with N backticks closes only on a line of >= N backticks and nothing else."""
    open_n = None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if open_n is None:
            yield i, (m.group(2).strip() if m else None), False
            if m:
                open_n = len(m.group(1))
        else:
            closes = m and len(m.group(1)) >= open_n and not m.group(2).strip()
            yield i, None, not closes
            if closes:
                open_n = None


def _has_code(lines):
    return any(tag is not None and tag != "json:metadata" for _, tag, _ in _fences(lines))


def plan_section(plan_text, n):
    """Lines of the `### Task N:` section of a plan (up to the next `### Task` or `## ` heading outside a fence), or None."""
    lines = (plan_text or "").splitlines()
    start = end = None
    for i, tag, inside in _fences(lines):
        if inside or tag is not None:
            continue
        line = lines[i]
        if start is None:
            if re.match(rf"###\s+Task {n}\b[:.]?", line):
                start = i + 1
        elif re.match(r"(###\s+Task\b|## )", line):
            end = i
            break
    if start is None:
        return None
    return lines[start:end]


def _code_in_steps(description, section=None):
    """True when the plan's task section (else the tasks.json description) holds a fenced block other than json:metadata."""
    return _has_code(section if section is not None else (description or "").splitlines())


def _tokens(r):
    return sum(r[k] or 0 for k in TOKEN_COLS)


def _sum(rows, prices):
    """(tokens, usd) over rows; (None, None) with no rows. usd is None when no row could be priced."""
    if not rows:
        return None, None
    costs = [c for c in (usage.call_cost(r, prices) for r in rows) if c is not None]
    return sum(_tokens(r) for r in rows), (round(sum(costs), 6) if costs else None)


def _pick(tasks, ts):
    """tasks: [(end, number)] in the owner's ledger order. First whose end >= ts, else the last."""
    for end, n in tasks:
        if end >= ts:
            return n
    return tasks[-1][1]


def build_task_lines(spec, batch, tasks_text, progress, routing, rows, commit_time, run_end, prices=None, plan_text=None):
    """One dict per plan task. commit_time: sha -> epoch int or None. run_end: epoch int or None (the fallback end)."""
    prices = prices if prices is not None else usage.load_prices()
    plan = json.loads(tasks_text)
    plan = plan["tasks"] if isinstance(plan, dict) else plan
    ledger = parse_ledger(progress)
    info = []
    for i, pt in enumerate(plan):
        m = re.match(r"Task (\d+):", pt.get("subject") or "")
        n = int(m.group(1)) if m else i + 1
        meta = metrics._fence(pt.get("description") or "", "json:metadata") or {}
        info.append((n, pt, meta))

    def end_of(n):
        led = ledger.get(n)
        e = commit_time(led["commit_end"]) if led and led["commit_end"] else None
        if e is None:
            e = run_end
        return e if e is not None else float("inf")

    def order(n):  # ledger order of the `complete` lines; tasks never completed come after, by number
        led = ledger.get(n)
        return (0, led["complete_at"], n) if led and led["complete_at"] is not None else (1, 0, n)

    reviewers = {name for led in ledger.values() for name in led["reviewers"]}
    by_owner, by_reviewer = {}, {}
    for n in sorted(ledger, key=order):
        for o in ledger[n]["owners"]:
            if o not in reviewers:
                by_owner.setdefault(o, []).append((end_of(n), n))
        for o in ledger[n]["reviewers"]:
            by_reviewer.setdefault(o, [])
        for sha in ledger[n]["review_ends"]:
            t = commit_time(sha)
            for o in ledger[n]["reviewers"]:
                by_reviewer[o].append((t if t is not None else end_of(n), n))
    for o, lst in by_reviewer.items():
        if not lst:  # reviewer named without a range: fall back to the task ends
            lst.extend((end_of(n), n) for n in sorted(ledger, key=order) if o in ledger[n]["reviewers"])
        lst.sort(key=lambda p: p[0])

    mine, theirs = {}, {}
    for r in rows:
        a = r["agent_name"]
        if a in by_reviewer:
            # a row belongs to the task whose review dispatch is the latest at or before the row (a dispatch's
            # time is the commit time of its reviewed range end), else the earliest dispatch
            lst = by_reviewer[a]
            n = next((num for t, num in reversed(lst) if t <= r["ts"]), lst[0][1])
            theirs.setdefault(n, []).append(r)
        elif a in by_owner:
            mine.setdefault(_pick(by_owner[a], r["ts"]), []).append(r)

    out = []
    for n, pt, meta in info:
        led = ledger.get(n) or _blank()
        tier = meta.get("modelTier")
        mapped = routing.get(tier) if tier else None
        rs = mine.get(n, [])
        tokens, usd = _sum(rs, prices)
        rtokens, rusd = _sum(theirs.get(n, []), prices)
        per_model = {}
        for r in rs:
            per_model[r["model"]] = per_model.get(r["model"], 0) + _tokens(r)
        used = max(per_model, key=per_model.get) if per_model else None
        mf = family(mapped)
        fams = {family(m) for m in led["dispatch_models"]} | {family(used)}
        fams.discard(None)
        mins = {int(r["ts"] // 60) for r in rs}
        out.append({
            "spec": spec, "batch": batch, "task_id": n, "subject": pt.get("subject"),
            "tier": tier, "model_mapped": mapped, "model_used": used,
            "escalated": bool(mf and any(f != mf for f in fams)),
            "owner": led["owners"][-1] if led["owners"] else None,
            "started_at": metrics.utc(min(r["ts"] for r in rs)) if rs else None,
            "ended_at": metrics.utc(max(r["ts"] for r in rs)) if rs else None,
            "active_s": 60 * len(mins), "tokens": tokens, "usd": usd,
            "review_tokens": rtokens, "review_usd": rusd,
            "fix_rounds": led["fix_rounds"], "findings": dict(led["findings"]),
            "review_rounds": led["review_rounds"],
            "outcome": "complete" if led["complete"] else pt.get("status"),
            "code_in_steps": _code_in_steps(pt.get("description"), plan_section(plan_text, n) if plan_text else None),
            "partial": not rs,
        })
    return out
