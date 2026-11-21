# PCEE stage 2: plan registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every plan carries a `json:manifest`; a Node registry in `engine/` validates manifests, checks staleness, builds the dependency and conflict graphs and waves under three lock policies, and measures prediction against outcome, with `board/metrics.py` staying the only writer of `runs.jsonl` and gate K1 evaluated from it.

**Architecture:** New `engine/` Node package (no runtime deps, `node --test`), CLI `engine/bin/registry.js` wrapped by `tmux-ctl registry`. Node never opens `runs.jsonl`: it reads batch facts through `tmux-ctl metrics runs <batch> --json` and writes through `tmux-ctl metrics append`. Python `metrics record` calls `tmux-ctl registry facts` for the manifest fields. Lead rules (up-front planning, stale check, entry gates) go into `claude/orchestrator.md`; the manifest rule into `writing-plans-extras`.

**Tech Stack:** Node >= 22.13 (CommonJS, `node:test`, `node:child_process`, `node:fs`), Python 3.9+ (`board/metrics.py`, `fcntl`), zsh (`bin/tmux-ctl`, `install.sh`, `tools/tests/all.zsh`), git (`merge-tree`, `diff`, `cat-file`).

**Spec:** docs/superpowers/specs/2026-11-10-pcee-registry-design.md

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-10-pcee-registry-design.md",
 "base": "30b7e22",
 "depends_on": [],
 "writes": [{"path": "board/metrics.py", "mode": "modify"},
            {"path": "board/tests/test_metrics_append.py", "mode": "create"},
            {"path": "board/tests/test_metrics_record_manifest.py", "mode": "create"},
            {"path": "board/tests/test_metrics_gate_k1.py", "mode": "create"},
            {"path": "bin/tmux-ctl", "mode": "modify"},
            {"path": "install.sh", "mode": "modify"},
            {"path": "docs/INSTALL.md", "mode": "modify"},
            {"path": "tools/tests/all.zsh", "mode": "modify"},
            {"path": "tools/tests/test_install.zsh", "mode": "modify"},
            {"path": "tools/tests/test_ctl_registry.zsh", "mode": "create"},
            {"path": "engine/package.json", "mode": "create"},
            {"path": "engine/package-lock.json", "mode": "create"},
            {"path": "engine/bin/registry.js", "mode": "create"},
            {"path": "engine/lib/registry/git.js", "mode": "create"},
            {"path": "engine/lib/registry/manifest.js", "mode": "create"},
            {"path": "engine/lib/registry/validate.js", "mode": "create"},
            {"path": "engine/lib/registry/graphs.js", "mode": "create"},
            {"path": "engine/lib/registry/batch.js", "mode": "create"},
            {"path": "engine/lib/registry/analyse.js", "mode": "create"},
            {"path": "engine/lib/registry/stale.js", "mode": "create"},
            {"path": "engine/lib/registry/facts.js", "mode": "create"},
            {"path": "engine/lib/registry/report.js", "mode": "create"},
            {"path": "engine/test/helpers.js", "mode": "create"},
            {"path": "engine/test/cli.test.js", "mode": "create"},
            {"path": "engine/test/manifest.test.js", "mode": "create"},
            {"path": "engine/test/graphs.test.js", "mode": "create"},
            {"path": "engine/test/analyse.test.js", "mode": "create"},
            {"path": "engine/test/stale_facts.test.js", "mode": "create"},
            {"path": "engine/test/report.test.js", "mode": "create"},
            {"path": "engine/test/gate.test.js", "mode": "create"},
            {"path": "engine/test/fixtures/past13.json", "mode": "create"},
            {"path": "docs/superpowers/metrics/gates/K1.md", "mode": "create"},
            {"path": "docs/superpowers/metrics/configs/upfront-seq.md", "mode": "create"},
            {"path": "claude/skills/writing-plans-extras/SKILL.md", "mode": "modify"},
            {"path": "claude/orchestrator.md", "mode": "modify"},
            {"path": "README.md", "mode": "modify"}],
 "reads": ["board/usage.py", "docs/superpowers/metrics/runs.jsonl", "tools/discord-bridge/package.json"],
 "produces": ["tmux-ctl registry validate|analyse|stale|report|facts", "tmux-ctl metrics append|has|runs"],
 "consumes": ["tmux-ctl metrics", "usage.sqlite calls table"],
 "tests": ["engine/test/", "board/tests/test_metrics_append.py", "board/tests/test_metrics_record_manifest.py",
           "board/tests/test_metrics_gate_k1.py", "tools/tests/test_ctl_registry.zsh", "tools/tests/test_install.zsh"]}
```

## Global Constraints

- **One writer for `runs.jsonl`:** only `board/metrics.py` opens it. No file under `engine/` reads or writes
  `runs.jsonl` (checked in Task 12: `grep -rn runs.jsonl engine/lib engine/bin` prints nothing).
- **Error lines:** every failing `registry` command prints exactly one line `registry: <sub>: <reason>` to stderr and
  exits non-zero (1 unless the spec names another code). No stack trace ever reaches stderr.
- **Exit codes:** `validate` 0 / 1 (one line per defect on stdout); `stale` 0 `fresh` / 1 `stale` + paths / 3
  `no manifest`; `analyse`, `report`, `facts` 0 / 1; `metrics append` 0 / 1; `metrics has` 0 / 1.
- **Manifest shape** (spec §1): fence tag `json:manifest`; keys `spec`, `base`, `depends_on[{spec, kind: hard|soft,
  interface?}]`, `writes[{path, mode: create|modify|append}]`, `reads[]`, `produces[]`, `consumes[]`, `tests[]`.
  Optional key added by this plan for refreshes: `refreshed_from: {"base": "<old sha>", "stale_paths": [..]}`.
- **Policies:** `strict`, `append`, `writes_only` exactly as spec §4. Relations of kind `conflict`/`interface` are
  conflict edges under every policy; `order` is a dependency edge.
- **Waves:** greedy colouring, plans ordered by conflict degree descending then spec path ascending; a plan's wave
  is the lowest colour not used by a conflicting neighbour AND greater than every `hard` dependency's wave.
- **Analysis line:** `{"kind":"analysis","batch":…,"specs":n,"waves":{"strict":n,"append":n,"writes_only":n},
  "parallelism":x,"parallelism_strict":x,"parallelism_writes_only":x,"appends_verified":bool,"clusters":n,
  "relations":n}`; ratios rounded to 4 decimals; written only through `tmux-ctl metrics append analysis --json`.
- **Metric definitions (defined once; every task cites these):**
  - *touched files*: `git diff --name-only <base>..<head>` minus paths under `docs/superpowers/` (same exclusion as
    `board/metrics.py` `EXCLUDED`).
  - *existed*: a touched path present in tree `<base>` (`git cat-file -e <base>:<path>`).
  - `recall_existing`: of touched files that existed, the share declared `modify` or `append` in `writes`, where a
    declared append that is an `append_violation` counts as not declared. `null` when no touched file existed.
  - `recall_created`: of touched files that did not exist, the share declared `create`. `null` when none.
  - `precision`: of `writes` paths (outside `docs/superpowers/`), the share touched. `null` when `writes` is empty.
  - *append verified*: `git diff -U0 <base>..<head> -- <path>` has no `-` content line and exactly one `@@` hunk.
    A declared append whose file is not touched is not a violation.
  - `refreshes`: 1 when the manifest has `refreshed_from`, else 0. `stale_paths`: `len(refreshed_from.stale_paths)`, else 0.
  - `manifest_tokens`: total tokens (input+output+cache_read+cache_write_5m+cache_write_1h) of usage rows whose
    `agent_name` is `refresh-<spec slug>` in the run's window, plus the rows of `crossplan-<batch>` from the batch
    line's `at` to the run's `ended_at`, divided by the batch line's spec count. `<spec slug>` = spec file name minus
    `.md`, minus a leading `YYYY-MM-DD-` and a trailing `-design`.
- **Zsh gotchas** (CLAUDE.md): never name a variable `path`; quote `=name` tmux targets; brace variables before `:`.
- **Commits:** conventional commits with scope (`feat(engine): …`, `feat(metrics): …`, `docs(rules): …`); end each
  commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).

**User decisions (already made):** the 2026-11-19 revision block of the spec (Node in `engine/`; Python metrics stays
the one writer with a file lock; `tmux-ctl registry` wraps Node like `tmux-ctl metrics` wraps Python; `node:sqlite`
later, `engines: node >= 22.13`; `engine/` has its own package and `node --test` suite; `install.sh` runs `npm ci` for
it and node becomes required). Queue answer for this spec: integration `merge`, no push.

**Rulings made while planning (lead):**
- Ruling: Node needs each batch's specs, run lines and real pair results, but must not open `runs.jsonl`; so Python
  gains a third read command, `tmux-ctl metrics runs <batch> --json` (beside the spec's `append` and `has`). Cost if
  wrong: one extra subcommand to fold later.
- Ruling: `refreshes`/`stale_paths` are carried in the manifest itself (`refreshed_from`), written by the refresh
  agent, so `registry facts` derives them from the plan alone. Cost if wrong: refresh agents that forget the key
  read as 0 refreshes.
- Ruling: `tmux-ctl registry` works outside tmux (pure analysis; `metrics record` calls it). Cost if wrong: none.
- Ruling: the strict wave count of the 13 backfilled plans (their `declared_list`, all as `modify`) under the tie-break
  rule is **6**, measured 2026-11-21 with `board/metrics.py greedy_waves` on `runs.jsonl`; the spec's "7" was a
  2026-11-10 measurement on different lists. The fixture pins 6.

---

### Task 1: Python: locked append, `metrics append|has|runs`

**Goal:** `board/metrics.py` takes an exclusive lock around every append and gains `append`, `has` and `runs` subcommands, so Node can write and read the run log without opening it.

**Files:**
- Modify: `board/metrics.py` (`_append_to` ~line 103, `SUBS` ~line 33, `_parser` ~line 1160, `main` dispatch ~line 1950, report pair loop ~lines 1066-1101, module docstring)
- Create: `board/tests/test_metrics_append.py`

**Acceptance Criteria:**
- [ ] `_append_to` holds `fcntl.flock(LOCK_EX)` on `<log>.lock` (sibling file) while writing; two processes appending 200 lines each give 400 parseable lines.
- [ ] `metrics append analysis --json '{"batch":"b","specs":2}'` appends one line with `"kind":"analysis"`; exit 0, prints nothing.
- [ ] `metrics append` refuses (exit 1, one line) kinds `batch`, `start`, `run`, `defect`, a non-object JSON, invalid JSON. `--batch X` sets `batch`.
- [ ] `metrics has <kind> [--spec S] [--batch B]` exits 0 when a line of that kind (and spec/batch when given) exists, else 1, and prints nothing.
- [ ] `metrics runs <batch> --json` prints `{"batch","base","at","specs":[…],"runs":{spec: last run line or null},"pairs":[{"a","b","clean":true|false,"paths":[…]}] or null}`; unknown batch exits 1.
- [ ] `metrics report` output is byte-identical before and after the pair-loop refactor (existing `test_metrics_report.py` passes unchanged).
- [ ] All three new subcommands accept `--log PATH` (read/write that file instead of the repo log), as `backfill --log` does.
- [ ] Docstring: `analysis` is listed as a kind, no longer "reserved".

**Verify:** `python3 -m unittest board.tests.test_metrics_append board.tests.test_metrics_report board.tests.test_metrics_log -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_metrics_append.py`. Pattern: copy the scratch-repo helpers from `board/tests/metrics_fixtures.py` (read it first; it builds a repo and a run log). Tests, each with the mutation that must make it fail:
  - `test_append_sets_kind_and_batch` (mutation: drop the `obj["kind"] = kind` line → fails).
  - `test_append_refuses_stage1_kinds` for each of `batch start run defect` (mutation: empty the refused tuple → fails).
  - `test_append_refuses_non_object` with `'[1]'` and `'nope'`.
  - `test_concurrent_appends_are_whole_lines`: two `subprocess.Popen([sys.executable, "-I", "board/metrics.py", "--repo", R, "append", "x", "--json", '{"pad":"<4000 x chars>"}', "--log", L])` loops of 200 each, then every line `json.loads` and count == 400 (mutation: remove the flock → may pass by luck; so also assert the lock file `L + ".lock"` exists after an append — removing the flock call and the lock-file open fails this).
  - `test_has_kind_spec_batch`: rc 0 / 1 combinations.
  - `test_runs_json_shape`: a batch line with two specs, one run line for one spec; assert keys, `runs[spec_without_run] is None`, `pairs` key present.
  - `test_runs_unknown_batch_exits_1`.

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest board.tests.test_metrics_append -v`
Expected: failures with `invalid choice: 'append'` (argparse) for every test.

- [ ] **Step 3: Implement**

```python
import fcntl  # with the other imports

STAGE1_KINDS = ("batch", "start", "run", "defect")


def _append_to(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p) + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(p, "a") as f:
                f.write(json.dumps(obj, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _with_log(args, fn):
    global LOG_OVERRIDE
    saved = LOG_OVERRIDE
    if getattr(args, "log", None):
        LOG_OVERRIDE = args.log
    try:
        return fn()
    finally:
        LOG_OVERRIDE = saved


def cmd_append(repo, args):
    def go():
        if args.kind in STAGE1_KINDS:
            raise MetricsError(f"kind {args.kind} has its own command")
        try:
            obj = json.loads(args.json)
        except ValueError:
            raise MetricsError("--json is not valid JSON")
        if not isinstance(obj, dict):
            raise MetricsError("--json must be a JSON object")
        obj["kind"] = args.kind
        if args.batch:
            obj["batch"] = args.batch
        append(repo, obj)
    return _with_log(args, go)


def cmd_has(repo, args):
    def go():
        for d in read_log(repo)[0]:
            if d.get("kind") == args.kind and (not args.spec or d.get("spec") == args.spec) \
                    and (not args.batch or d.get("batch") == args.batch):
                return 0
        return 1
    return _with_log(args, go)
```

`cmd_runs`: find the last `batch` line with that id (else `MetricsError(f"unknown batch {id}")`), `runs = {s: last_runs(lines).get((id, s)) for s in batch["specs"]}` (also include specs that have a run line for the batch but are not in `batch["specs"]`: a spec joined late), and `pairs = pair_results(repo, batch, [r for r in runs.values() if r])`. Print `json.dumps(obj, sort_keys=True)`.

Refactor: move the loop of `report_text` under `# parallel-buildable pairs` into

```python
def pair_results(repo, batch, runs):
    """[(a, b, clean, paths)] for every usable pair, or None when git merge-tree failed. Pair order and the usable
    rule are those of the report's parallel-buildable pairs."""
```

returning `[(a, b, True, [])…]` for clean ones in the same loop order, and have `report_text` call it and derive `clean`, `bad`, `failed`, `usable` from its result so the printed lines do not change. `cmd_runs` maps tuples to `{"a","b","clean","paths"}`.

Parser: `append` (`kind`, `--json` required, `--batch`, `--log`), `has` (`kind`, `--spec`, `--batch`, `--log`), `runs` (`batch`, `--json` flag accepted, `--log`). Add `"append", "has", "runs"` to `SUBS` and the dispatch dict. `has`'s `--spec` goes through `rel_spec` like other `spec` args: add `elif getattr(args, "spec", None): args.spec = rel_spec(repo, args.spec)` only if `hasattr(args,"spec")` branch does not already cover a None value — guard `None`.

- [ ] **Step 4: Run GREEN**

Run: `python3 -m unittest board.tests.test_metrics_append board.tests.test_metrics_report board.tests.test_metrics_log -v`
Expected: `OK`

- [ ] **Step 5: Commit** `feat(metrics): locked append; append, has and runs subcommands` (stage `board/metrics.py board/tests/test_metrics_append.py`).

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_append.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_append board.tests.test_metrics_report board.tests.test_metrics_log -v", "acceptanceCriteria": ["flock on <log>.lock around each append; 2x200 concurrent appends give 400 parseable lines", "metrics append sets kind/batch; refuses batch/start/run/defect, non-object and invalid JSON with exit 1", "metrics has exit 0/1 by kind, spec, batch", "metrics runs <batch> --json shape; unknown batch exit 1", "metrics report output unchanged after pair_results refactor", "--log on append/has/runs", "docstring lists analysis as a kind"], "modelTier": "standard"}
```

---

### Task 2: `engine/` package, `registry.js` entry, `tmux-ctl registry`, all.zsh job

**Goal:** An empty-but-working `engine/` package whose CLI dispatches subcommands with the error-line convention, wrapped by `tmux-ctl registry`, and run by `tools/tests/all.zsh` as suite `engine`.

**Files:**
- Create: `engine/package.json`, `engine/package-lock.json`, `engine/bin/registry.js`, `engine/test/helpers.js`, `engine/test/cli.test.js`, `tools/tests/test_ctl_registry.zsh`
- Modify: `bin/tmux-ctl` (help block ~line 83, TMUX check line ~121, case near `metrics)` ~line 766), `tools/tests/all.zsh` (suite list and `add` lines)

**Acceptance Criteria:**
- [ ] `engine/package.json` is exactly the content below; `cd engine && npm test` passes.
- [ ] `node engine/bin/registry.js` with no args or an unknown sub prints `registry: usage: registry <validate|analyse|stale|report|facts> ...` on stderr and exits 2.
- [ ] A subcommand that throws prints exactly one stderr line `registry: <sub>: <message>` and exits 1. In this task no sub module exists yet, so every known sub resolves to the stub `() => { throw new Error("not built") }`, and the test is `facts x` → `registry: facts: not built`, exit 1.
- [ ] `tmux-ctl registry facts x` run outside tmux (`env -u TMUX`) reaches node (prints `registry: facts: not built` until Task 7).
- [ ] `zsh tools/tests/all.zsh --list --suite engine` prints one job `engine` with command `cd engine && node --test test/*.test.js`.
- [ ] `tmux-ctl --help` lists `tmux-ctl registry <validate|analyse|stale|report|facts> …`.

**Verify:** `(cd engine && npm test) && zsh tools/tests/test_ctl_registry.zsh && zsh tools/tests/all.zsh --list --suite engine`  → node `# fail 0`, zsh `ok` lines and no `FAIL`, one `engine` line

**Steps:**

- [ ] **Step 1: package files**

`engine/package.json`:

```json
{
  "name": "agent-board-engine",
  "version": "0.1.0",
  "private": true,
  "description": "PCEE engine: plan registry (stage 2)",
  "type": "commonjs",
  "engines": {"node": ">=22.13"},
  "scripts": {"test": "node --test test/*.test.js"},
  "license": "ISC"
}
```

Then `cd engine && npm install --package-lock-only` to create `package-lock.json` (no dependencies; it must exist so `npm ci` works).

- [ ] **Step 2: failing tests.** `engine/test/helpers.js` exports `run(args, opts)` → `{code, stdout, stderr}` using `spawnSync(process.execPath, [path.join(__dirname, "../bin/registry.js"), ...args], {encoding: "utf8", ...opts})`, and `scratchRepo()` → a temp dir with `git init -q -b main`, `user.email t@t`, `user.name t`, returning `{dir, git(...args) → stdout trimmed, write(rel, text), commit(msg) → sha}` (used by Tasks 3-9). `engine/test/cli.test.js`: no args → code 2 and the usage line; `bogus` → code 2; `facts x` → code 1 and stderr exactly one line starting `registry: facts: `.

- [ ] **Step 3: RED:** `cd engine && npm test` → fails (no `bin/registry.js`).

- [ ] **Step 4: implement `engine/bin/registry.js`**

```js
#!/usr/bin/env node
"use strict";
const SUBS = ["validate", "analyse", "stale", "report", "facts"];
const notBuilt = () => { throw new Error("not built"); };
function load(sub) {
  try { return require(`../lib/registry/${sub}.js`).main; } catch (e) {
    if (e.code === "MODULE_NOT_FOUND" && String(e.message).includes(`registry/${sub}.js`)) return notBuilt;
    throw e;
  }
}
function main(argv) {
  const sub = argv[0];
  if (!SUBS.includes(sub)) {
    process.stderr.write("registry: usage: registry <" + SUBS.join("|") + "> ...\n");
    return 2;
  }
  try {
    const rc = load(sub)(argv.slice(1), {cwd: process.cwd(), out: (s) => process.stdout.write(s + "\n")});
    return typeof rc === "number" ? rc : 0;
  } catch (e) {
    const msg = String(e && e.message ? e.message : e).split("\n")[0];
    process.stderr.write(`registry: ${sub}: ${msg}\n`);
    return typeof e.code === "number" ? e.code : 1;
  }
}
process.exitCode = main(process.argv.slice(2));
```

Every later module exports `main(args, ctx)` returning an exit code and printing through `ctx.out`; errors are thrown as `Error` (optionally with numeric `.code`).

- [ ] **Step 5: `bin/tmux-ctl`.** In the help block add `#   tmux-ctl registry <validate|analyse|stale|report|facts> …  plan manifests, graphs, waves (engine/, node)` next to the `metrics <sub>` line. Add `|| "$1" == registry` to the TMUX check condition on line ~121 and `registry` to its trailing comment. Add before `metrics)`:

```zsh
  registry)
    exec node "${0:A:h:h}/engine/bin/registry.js" "$@" ;;
```

- [ ] **Step 6: `tools/tests/test_ctl_registry.zsh`**: follow an existing small `tools/tests/test_ctl_*.zsh` for the `ok`/`FAIL` print style (read one first). Checks: `env -u TMUX zsh bin/tmux-ctl registry` exits 2 with the usage line; `env -u TMUX zsh bin/tmux-ctl registry facts x` stderr starts `registry: facts:`; `zsh bin/tmux-ctl --help | grep -q 'tmux-ctl registry'`.

- [ ] **Step 7: `tools/tests/all.zsh`.** Add `engine` to the usage strings and to the `[[ $s == (board|zsh|…) ]]` list; add after the hooks line:

```zsh
if want engine && [[ -f engine/package.json ]]; then add engine "cd engine && node --test test/*.test.js"; fi
```

and extend the tests-run awk with node's summary: add `/^# pass [0-9]+/{n+=$3}` to the awk program. Header comment: mention the engine suite.

- [ ] **Step 8: GREEN** with the Verify command. **Commit** `feat(engine): package, registry entry, tmux-ctl registry, all.zsh engine job`.

```json:metadata
{"files": ["engine/package.json", "engine/package-lock.json", "engine/bin/registry.js", "engine/test/helpers.js", "engine/test/cli.test.js", "bin/tmux-ctl", "tools/tests/all.zsh", "tools/tests/test_ctl_registry.zsh"], "verifyCommand": "(cd engine && npm test) && zsh tools/tests/test_ctl_registry.zsh && zsh tools/tests/all.zsh --list --suite engine", "acceptanceCriteria": ["engine/package.json as given; npm test passes", "no/unknown sub: usage line, exit 2", "thrown error: one stderr line registry: <sub>: <msg>, exit 1", "tmux-ctl registry works outside tmux", "all.zsh --list --suite engine shows the engine job", "tmux-ctl --help lists registry"], "modelTier": "mechanical"}
```

---

### Task 3: Install: `npm ci` for engine, node required, INSTALL.md row

**Goal:** `install.sh` installs the engine's deps and `--check` requires node >= 22.13; INSTALL.md says node is required.

**Files:**
- Modify: `install.sh` (`check_deps` line ~68, `bridge_deps` ~72-79, its call site, header comment line 5), `docs/INSTALL.md` (node row ~line 41), `tools/tests/test_install.zsh`

**Acceptance Criteria:**
- [ ] `install.sh --check` prints `ok <node path>` when `node --version` >= 22.13, and `MISSING node (needs >= 22.13; found <v or none>)` and exit 1 otherwise; the `optional: node missing` line is gone.
- [ ] `install.sh` runs `npm ci --omit=dev` in `engine/` when `engine/package-lock.json` exists (prints `installing engine deps`; `--dry-run` prints `would npm ci --omit=dev in <dir>`); npm missing prints `MISSING npm (the engine needs it)` and makes the install exit 1.
- [ ] INSTALL.md node + npm row: version `22.13+`, used by "the engine (`engine/`) and the Discord bridge (`tools/discord-bridge`)", note "required: `install.sh` runs `npm ci --omit=dev` in both; the engine uses `node:sqlite`; `--check` prints `MISSING node` below 22.13".
- [ ] `tools/tests/test_install.zsh` covers: stub node printing `v22.13.0` → `ok`, `v22.12.9` → `MISSING node`, no node → `MISSING node`; `--dry-run` shows the engine npm line.

**Verify:** `zsh tools/tests/test_install.zsh` → only `ok` lines, no `FAIL`

**Steps:**

- [ ] Read `tools/tests/test_install.zsh` first: it builds a stub PATH (`$STUB`); add a stub `node` script there per case (`print v22.13.0`). Write the new cases; RED: `zsh tools/tests/test_install.zsh` shows FAIL for them (mutation: keep the old `optional:` line → the `MISSING node` case fails).
- [ ] `check_deps` node part:

```zsh
  if p="$(command -v node)"; then
    v="$(node --version 2>/dev/null)"; v="${v#v}"
    local -a nv; nv=("${(@s:.:)v}")
    if [[ -n "$v" ]] && (( nv[1] * 1000000 + nv[2] * 1000 + ${nv[3]:-0} >= 22013000 )); then print -r -- "ok $p"
    else print "MISSING node (needs >= 22.13; found ${v:-no version})"; miss=1; fi
  else print "MISSING node (needs >= 22.13; found none)"; miss=1; fi
```

- [ ] Add `engine_deps()` beside `bridge_deps` (same shape, `d="$REPO/engine"`, messages `installing engine deps` / `engine deps: npm ci failed (run npm ci in engine/ to see why)`, npm missing → `print -u2 "MISSING npm (the engine needs it)"; return 1`), and call it where `bridge_deps` is called, propagating a non-zero return into the script's `rc`. Header line 5: replace `(node: "optional: node missing")` with `(node >= 22.13 is required)`.
- [ ] INSTALL.md row per the criterion. GREEN with Verify. **Commit** `feat(install): engine deps, node >= 22.13 required`.

```json:metadata
{"files": ["install.sh", "docs/INSTALL.md", "tools/tests/test_install.zsh"], "verifyCommand": "zsh tools/tests/test_install.zsh", "acceptanceCriteria": ["--check: ok for node >= 22.13, MISSING node otherwise, exit 1", "install runs npm ci --omit=dev in engine/; dry-run line; npm missing fails", "INSTALL.md node row says required for engine and bridge, 22.13+", "test_install covers 22.13.0, 22.12.9, none, dry-run"], "modelTier": "mechanical"}
```

---

### Task 4: Manifest parsing and `registry validate`

**Goal:** `tmux-ctl registry validate <plan>` checks a plan's manifest against git and its tasks' files and exits 0 or 1 with one line per defect.

**Files:**
- Create: `engine/lib/registry/git.js`, `engine/lib/registry/manifest.js`, `engine/lib/registry/validate.js`, `engine/test/manifest.test.js`

**Acceptance Criteria:**
- [ ] `git.js` exports `git(repo, args) → {rc, out}` (execFileSync, never throws, stdout as utf8), `existsAt(repo, ref, rel) → bool` (`git cat-file -e ref:rel`), `show(repo, ref, rel) → text|null`, `mainRoot(repo)` (the `--git-common-dir` parent, as `board/metrics.py main_root`), and `findPlan(repo, spec) → {path, text, ref}|null` with exactly `board/metrics.py find_plan`'s rule (working tree first, then every `refs/heads` branch; header line with `**Spec:**` containing the spec without `#part-N` in the first 40 lines; a line carrying the full spec incl. `#part-N` wins).
- [ ] `manifest.js` exports `parseManifest(text) → {manifest}|{error}`: fence regex ```` ```json:manifest[ \t]*\n(.*?)\n``` ```` (dotall); errors `no manifest`, `manifest: bad JSON`, `manifest: <key> missing`, `manifest: bad mode <m> for <path>`, `manifest: bad kind <k>`; and `taskFiles(tasksJsonText) → string[]` (union of each task's `json:metadata` `files`).
- [ ] `validate` defects, one line each on stdout, then exit 1: bad/missing manifest; `create path exists at base: <p>`; `<mode> path missing at base: <p>` for modify/append; `base not found: <sha>`; `task file not covered: <p>` for a task file in neither `writes` nor `reads`; `no .tasks.json` when `<plan>.tasks.json` is missing. Valid → no output, exit 0. Missing plan file → `registry: validate: no such plan <p>`, exit 1.
- [ ] `<plan>` is a path relative to the cwd's repo or absolute; base and files are checked in that repo.
- [ ] Tests on a scratch repo (helpers `scratchRepo`): valid plan → 0; each defect above produces its line (mutation per test: removing that check makes its test fail).
- [ ] `node engine/bin/registry.js validate docs/superpowers/plans/2026-11-21-pcee-registry.md` on this branch exits 0 (this plan's own manifest; base `30b7e22`).

**Verify:** `(cd engine && npm test) && node engine/bin/registry.js validate docs/superpowers/plans/2026-11-21-pcee-registry.md` → `# fail 0`, then exit 0 with no output

**Steps:**

- [ ] RED: write `engine/test/manifest.test.js` covering every criterion; `cd engine && npm test` fails with `not built` / missing module.
- [ ] Implement. `validate.main(args, ctx)`: `args[0]` required (else throw `usage: registry validate <plan>`); repo = `git rev-parse --show-toplevel` from ctx.cwd. Collect defects in order: manifest, base, per-write mode checks, coverage (`taskFiles` paths not in `writes[].path ∪ reads`), print each via `ctx.out`, return `defects.length ? 1 : 0`.
- [ ] GREEN, then the real check on this plan. **Commit** `feat(engine): manifest parsing and registry validate`.

```json:metadata
{"files": ["engine/lib/registry/git.js", "engine/lib/registry/manifest.js", "engine/lib/registry/validate.js", "engine/test/manifest.test.js"], "verifyCommand": "(cd engine && npm test) && node engine/bin/registry.js validate docs/superpowers/plans/2026-11-21-pcee-registry.md", "acceptanceCriteria": ["git.js helpers incl. findPlan with metrics.py find_plan's rule", "parseManifest errors as listed; taskFiles union", "validate prints one line per defect: create exists, modify/append missing, base not found, task file not covered, no .tasks.json; exit 1", "valid plan exit 0 no output; missing plan one error line", "this plan validates"], "modelTier": "standard"}
```

---

### Task 5: Graphs, clusters and waves

**Goal:** Pure functions computing the dependency graph, the conflict graph per lock policy, clusters and waves, pinned by unit fixtures and the 13 real past plans.

**Files:**
- Create: `engine/lib/registry/graphs.js`, `engine/test/graphs.test.js`, `engine/test/fixtures/past13.json`

**Acceptance Criteria:**
- [ ] Exports, with `plans = [{spec, manifest}]` and `relations = [{a, b, kind, why}]`:
  - `dependencyEdges(plans, relations) → [{from, to, kind: "hard"|"soft"|"order", source: "manifest"|"crossplan"}]` (`from` depends on `to`; `depends_on` entries naming specs outside the batch are dropped).
  - `conflictEdges(plans, policy, relations) → [{a, b, paths: [...], source}]`, `a < b` by spec path, per Global Constraints policies; relation `conflict`/`interface` edges carry `paths: []`, `source: "crossplan"`.
  - `clusters(plans) → [[spec…]…]` per spec §4 (hard deps or strict conflicts on a path not append-only for both), each sorted, list sorted by first member.
  - `waves(plans, policy, relations) → {spec: waveIndex}` per the Global Constraints rule; throws `dependency cycle: <a> -> <b> …` on a hard-dependency cycle.
  - `summary(plans, relations) → {waves: {strict, append, writes_only}, parallelism, parallelism_strict, parallelism_writes_only, clusters}` (wave count = max index + 1; ratio = specs / waves, 4 decimals; 0 specs → all 0).
  - `hotFiles(plans) → [{path, count}]` for paths written by >= 3 plans, count desc then path.
- [ ] Unit fixtures: two plans that both `append` one file → conflict under strict, not under append; write vs read → conflict under strict and append, not writes_only; a hard dependency puts the dependent in a later wave with no conflict; an `interface` relation is a conflict under all three; an `order` relation is a dependency edge; tie-break by spec path is deterministic (swap input order → same waves).
- [ ] `fixtures/past13.json` = `{spec: declared_list}` of the 13 `batch == "backfill"` run lines (last per spec); built as `{spec, manifest: {writes: files.map(p => ({path: p, mode: "modify"})), reads: [], depends_on: []}}`, `summary(...).waves.strict === 6`.

**Verify:** `cd engine && node --test test/graphs.test.js` → `# fail 0`

**Steps:**

- [ ] Generate the fixture (read-only on the real log), from the worktree root:

```zsh
python3 -I -c 'import json; L=[json.loads(l) for l in open("/Users/francisco.ruiz/agent-board/docs/superpowers/metrics/runs.jsonl") if l.strip()]
d={}
for r in L:
    if r.get("kind")=="run" and r.get("batch")=="backfill": d[r["spec"]]=sorted(r.get("declared_list") or [])
print(json.dumps(d, indent=1, sort_keys=True))' > engine/test/fixtures/past13.json
python3 -c 'import json;print(len(json.load(open("engine/test/fixtures/past13.json"))))'   # → 13
```

- [ ] RED: tests first (each names its mutation in a comment, e.g. "drop the append exemption → appendPair test fails"). Then implement: conflict degree computed from the policy's conflict edges; order plans by `(-degree, spec)`; for each plan, `min = 1 + max(wave of hard deps)` (0 if none) — process plans in topological order of hard deps, breaking ties by the degree order (Kahn's algorithm with a priority queue on `(-degree, spec)`); colour = smallest `c >= min` not used by an already-coloured conflicting neighbour.
- [ ] GREEN. **Commit** `feat(engine): dependency and conflict graphs, clusters, waves`.

```json:metadata
{"files": ["engine/lib/registry/graphs.js", "engine/test/graphs.test.js", "engine/test/fixtures/past13.json"], "verifyCommand": "cd engine && node --test test/graphs.test.js", "acceptanceCriteria": ["dependencyEdges, conflictEdges per policy, clusters, waves, summary, hotFiles as specified", "append pair, write-vs-read, hard dep later wave, interface relation, order relation, deterministic tie-break fixtures", "past13 fixture: strict waves == 6"], "modelTier": "standard"}
```

---

### Task 6: Batch reader and `registry analyse`

**Goal:** `tmux-ctl registry analyse <batch> [--relations <file>]` writes the analysis document and one `analysis` line through `tmux-ctl metrics append`.

**Files:**
- Create: `engine/lib/registry/batch.js`, `engine/lib/registry/analyse.js`, `engine/test/analyse.test.js`

**Acceptance Criteria:**
- [ ] `batch.js` exports `metricsCmd()` → argv prefix: `process.env.REGISTRY_METRICS_CMD` split on spaces when set (tests), else `[<repo>/bin/tmux-ctl, "metrics"]` resolved from `__dirname` (`engine/lib/registry` → repo root). `readBatch(repo, id) → JSON of metrics runs <id> --json` (throws `unknown batch <id>` on rc 1) and `appendAnalysis(repo, obj)` → runs `metrics append analysis --json <JSON>` and throws its stderr line on failure. No `fs` call in `engine/` names `runs.jsonl`.
- [ ] `analyse`: for each spec in the batch, `findPlan` + `parseManifest`; plans without a valid manifest are left out and listed under `## Plans without a manifest`. Relations file: parsed as a JSON list of `{a,b,kind,why}`; missing/malformed → ignored with the line `relations: ignored (<reason>)` in the document.
- [ ] Document `docs/superpowers/metrics/analysis/<batch>.md` (under `mainRoot`) with sections in this order: `# Analysis <batch>`, `## Manifests` (table: spec, base, writes, reads, depends_on), `## Dependency graph` (edge list, crossplan edges suffixed ` (cross-plan: <why>)`), `## Conflict graph` per policy (`### strict` etc., `a — b: paths`), `## Clusters`, `## Waves` (per policy: `wave N: spec, spec`), `## Hot files`, `## Plans without a manifest` (or `none`). Re-running overwrites the document but keeps a `## Prediction against outcome` section if present (it is appended by `report`).
- [ ] The analysis line has exactly the Global Constraints keys, `appends_verified: false`, `relations: <count used>`.
- [ ] Tests: scratch repo with three plans (two on branches, one in the working tree), a stub metrics command (a small node script in a temp dir printing a canned `runs --json` and appending `append` calls to a file) → document sections present in order, the appended JSON parses with the right counts; malformed relations → ignore line; a plan without a manifest → listed. One test runs the REAL `bin/tmux-ctl metrics append` with `--log <tmp>` via `REGISTRY_METRICS_CMD="zsh <repo>/bin/tmux-ctl metrics"` plus a `--log` passthrough: `appendAnalysis` accepts an optional `extra` argv (`["--log", tmp]`) used only by tests.

**Verify:** `cd engine && node --test test/analyse.test.js` → `# fail 0`

**Steps:**

- [ ] RED tests, then implement. `analyse.main(["<batch>", "--relations", f])`; output path printed via `ctx.out` (`analysis: <relative path>`).
- [ ] GREEN. **Commit** `feat(engine): registry analyse, analysis document and line`.

```json:metadata
{"files": ["engine/lib/registry/batch.js", "engine/lib/registry/analyse.js", "engine/test/analyse.test.js"], "verifyCommand": "cd engine && node --test test/analyse.test.js", "acceptanceCriteria": ["batch.js reads via metrics runs --json and writes via metrics append; REGISTRY_METRICS_CMD seam; no runs.jsonl in engine fs calls", "plans without manifest left out and listed", "relations file used, malformed ignored with a line", "document sections in the stated order; Prediction section preserved on rerun", "analysis line keys exact, appends_verified false", "one test through the real tmux-ctl metrics append --log"], "modelTier": "standard"}
```

---

### Task 7: `registry stale` and `registry facts`

**Goal:** `stale` tells whether `main` moved a manifest's paths since its base; `facts` prints the manifest fields of one spec's run.

**Files:**
- Create: `engine/lib/registry/stale.js`, `engine/lib/registry/facts.js`, `engine/test/stale_facts.test.js`

**Acceptance Criteria:**
- [ ] `stale <spec> [--main <ref>]` (default `main`): finds the plan (`findPlan`), no manifest → prints `no manifest`, exit 3. Paths = `modify`/`append`/`reads` paths in `git diff --name-only <base> <main>` plus `create` paths that exist at `<main>`. None → prints `fresh`, exit 0; else prints `stale` then one path per line (sorted), exit 1.
- [ ] `facts <spec> --base <sha> --head <sha>` prints one JSON object: `{"recall_existing", "recall_created", "precision", "append_violations": [paths], "refreshes", "stale_paths", "writes": [the manifest's writes], "declared": n, "touched": n, "both": n, "missed": [touched paths not declared]}` per the Global Constraints metric definitions. No manifest → `registry: facts: no manifest`, exit 3. The plan is looked up at `--head` first (`git show <head>:<path>` of the plan `findPlan` names), so a merged branch still works.
- [ ] Stale tests (scratch repo): `main` modifies a manifest `modify` path → stale with that path; modifies an unlisted path → fresh; creates a path the manifest lists `create` → stale; no manifest → 3.
- [ ] Append tests (spec Testing): declared append adding one block → not a violation; two separate blocks → violation; changing a line → violation; deleting a line → violation; each violation lowers `recall_existing` (that file counts as a miss); a `modify` file with an add-only diff is never treated as an append (no entry in `append_violations`).
- [ ] `recall_created` on a scratch repo: two created files, one declared `create` → 0.5; `refreshed_from` with 2 stale paths → `refreshes` 1, `stale_paths` 2.

**Verify:** `cd engine && node --test test/stale_facts.test.js` → `# fail 0`

**Steps:**

- [ ] RED tests then implement. Append check: `git diff -U0 <base> <head> -- <path>`; violation when any line matches `^-(?!--)` or the count of `^@@` lines != 1.
- [ ] GREEN. **Commit** `feat(engine): registry stale and facts`.

```json:metadata
{"files": ["engine/lib/registry/stale.js", "engine/lib/registry/facts.js", "engine/test/stale_facts.test.js"], "verifyCommand": "cd engine && node --test test/stale_facts.test.js", "acceptanceCriteria": ["stale: fresh 0 / stale+paths 1 / no manifest 3; create path now existing is stale", "facts JSON keys per metric definitions; no manifest exit 3; plan read at head", "append: one block ok; two blocks, changed line, deleted line are violations and misses; modify never treated as append", "recall_created 0.5 case; refreshed_from gives refreshes 1, stale_paths 2"], "modelTier": "standard"}
```

---

### Task 8: `metrics record` gains the manifest fields

**Goal:** When a spec's plan has a manifest, `metrics record` fills `manifest` (from `writes`), `recall_existing`/`recall_created`, `append_violations`, `refreshes`, `stale_paths` and `manifest_tokens` from `registry facts` and the usage index.

**Files:**
- Modify: `board/metrics.py` (`build_record_static` manifest block ~lines 470-480, `build_record` ~line 709, RESERVED ~line 236)
- Create: `board/tests/test_metrics_record_manifest.py`

**Acceptance Criteria:**
- [ ] Plan text with a `json:manifest` fence and both `base` and `head` known: `metrics record` runs the facts command (`os.environ["TC_REGISTRY_FACTS_CMD"]` split with `shlex` when set, else `[<repo>/bin/tmux-ctl, "registry"]`) with `facts <spec> --base <base> --head <head>`; on exit 0 the run line gets `manifest = {"declared", "touched", "both", "precision", "recall": both/touched, "recall_existing", "recall_created", "append_violations", "source": "manifest"}`, and top-level `refreshes`, `stale_paths`.
- [ ] No manifest: the line is unchanged from today (tasks' `files`; no `refreshes` key at all, so K1's `where: {"has": "refreshes"}` skips it); `manifest` gains `"source": "tasks"`.
- [ ] Facts command fails (rc != 0): `manifest` falls back to the tasks computation, `missing` gains `manifest_facts`, stderr `metrics: record: registry facts failed: <first line>`; the record is still written.
- [ ] `manifest_tokens` (removed from RESERVED) per the Global Constraints definition from the usage DB; `null` and in `missing` when there is no batch line.
- [ ] Tests: a scratch repo + facts stubbed by a fixture JSON (`TC_REGISTRY_FACTS_CMD="cat <fixture>"`-style script that ignores args) and the same through the REAL `node engine/bin/registry.js facts` → both runs give identical `manifest`, `refreshes`, `stale_paths` (spec "Facts handoff"); fixture usage DB (`usage.connect` on a temp file, rows inserted for `refresh-<slug>` in window, `crossplan-<batch>` in batch window, and an unrelated agent) → `manifest_tokens` = refresh tokens + crossplan tokens / batch spec count (mutation: drop the crossplan share → test fails).

**Verify:** `python3 -m unittest board.tests.test_metrics_record_manifest board.tests.test_metrics_record_git board.tests.test_metrics_record_usage -v` → `OK`

**Steps:**

- [ ] Read `board/tests/test_metrics_record_git.py` and `test_metrics_record_usage.py` first for the scratch-repo and fixture-DB patterns. RED tests. Implement in `build_record_static`: after the tasks manifest is computed, `man = _fence(plan_text, "json:manifest")`; if `man` and base and head → `_registry_facts(repo, spec, base, head)`. In `build_record`, compute `manifest_tokens` with `conn` (`usage._rows(conn, "select * from calls where agent_name=? and ts>=? and ts<=?", …)`, sum the five token columns).
- [ ] GREEN. **Commit** `feat(metrics): record reads manifest facts from the registry`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_record_manifest.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_record_manifest board.tests.test_metrics_record_git board.tests.test_metrics_record_usage -v", "acceptanceCriteria": ["manifest plan: facts command run; manifest from writes with recall_existing, recall_created, append_violations, source manifest; refreshes, stale_paths top-level", "no manifest: unchanged, no refreshes key, source tasks", "facts failure: fallback, missing manifest_facts, one stderr line, record still written", "manifest_tokens per definition; null+missing without batch line", "stub and real facts give identical fields; crossplan share mutation fails"], "modelTier": "standard"}
```

---

### Task 9: `registry report`: prediction against outcome

**Goal:** `tmux-ctl registry report <batch>` appends **Prediction against outcome** to the analysis document and writes a superseding analysis line with `appends_verified: true`.

**Files:**
- Create: `engine/lib/registry/report.js`, `engine/test/report.test.js`

**Acceptance Criteria:**
- [ ] Reads the batch through `readBatch` (run lines and real pairs). Per spec with a run line carrying `base` and `head`: computes facts (reusing `facts.js`'s function, not the CLI) and lists `recall_existing`, `recall_created`, `precision`, `refreshes`, files missed, append violations.
- [ ] Recomputes waves with every violated append as `modify` and appends a new analysis line, same keys, `appends_verified: true`.
- [ ] Pair table: for each pair in `pairs`, predicted conflict under each policy (from `conflictEdges`) against `clean`; per policy the four totals `predicted & clean`, `predicted & conflicting`, `not predicted & conflicting`, `not predicted & clean`. `pairs: null` → the line `Pairs: unavailable (git merge-tree failed)`.
- [ ] Ends with the sentence `Textual results do not show semantic conflicts.`
- [ ] The section replaces an existing `## Prediction against outcome` (idempotent rerun); no analysis document yet → runs `analyse` first.
- [ ] Tests on a scratch repo with two specs whose branches were merged, one with a violated append: section present once after two runs; the second analysis line has `appends_verified: true` and the append-aware wave count that treats the violation as `modify` (mutation: skip the downgrade → wave count test fails); pair totals add up to the pair count.

**Verify:** `cd engine && node --test test/report.test.js` → `# fail 0`

**Steps:**

- [ ] RED tests, implement, GREEN. **Commit** `feat(engine): registry report, prediction against outcome`.

```json:metadata
{"files": ["engine/lib/registry/report.js", "engine/test/report.test.js"], "verifyCommand": "cd engine && node --test test/report.test.js", "acceptanceCriteria": ["per-spec recall_existing, recall_created, precision, refreshes, missed, violations", "superseding analysis line appends_verified true with violations as modify", "pair table four totals per policy; null pairs line", "closing sentence", "idempotent section; runs analyse when no document"], "modelTier": "standard"}
```

---

### Task 10: Gate K1 and the `upfront-seq` configuration

**Goal:** `docs/superpowers/metrics/gates/K1.md` and `configs/upfront-seq.md` exist and `tmux-ctl metrics gate K1` evaluates them: pass, fail per condition, too early.

**Files:**
- Create: `docs/superpowers/metrics/gates/K1.md`, `docs/superpowers/metrics/configs/upfront-seq.md`, `board/tests/test_metrics_gate_k1.py`, `engine/test/gate.test.js`

**Acceptance Criteria:**
- [ ] `K1.md`: a prose paragraph (the checkpoint of spec §6: median recall on existing files >= 0.9 over at least 4 specs with manifests, append-aware parallelism >= 1.5 on verified appends, manifest tokens <= 10% of tokens; with 4 specs parallelism is 4, 2, 1.33 or 1) and a ```` ```json:gate ```` fence with exactly the spec §6 JSON.
- [ ] `upfront-seq.md`: one paragraph (plans written up front by planner agents, then run sequentially as `seq-sdd`) and a ```` ```json:config ```` fence `{"id": "upfront-seq", "baseline": false, "targets": [{"metric": "tokens_per_task", "max": 1.0}]}`.
- [ ] Python tests (temp repo copying the two files into its metrics dir): 4 run lines with `refreshes` and good values + analysis line `appends_verified: true, parallelism: 2` → `pass`, rc 0; each condition failing alone → `fail`, rc 1; 3 specs → `too early`; analysis line with `appends_verified: false` only → `too early`, rc 3; run lines without `refreshes` are not counted.
- [ ] `metrics gate K1` prints the append wave count beside the ratio: the gate's `analysis.parallelism` line ends with ` (append waves N)` when the last analysis line has `waves.append` (generic: for a `last`-agg metric under `analysis.`, append the sibling `waves.append` when present).
- [ ] `engine/test/gate.test.js`: appends an analysis line with `tmux-ctl metrics append analysis --json … --log <tmp>` from Node, then `tmux-ctl metrics gate K1` reading it gives the parallelism value back. If `gate` has no `--log`, add `--log` to `gate` in `board/metrics.py` (same `_with_log` helper as Task 1) and say so in the commit.

**Verify:** `python3 -m unittest board.tests.test_metrics_gate_k1 -v && (cd engine && node --test test/gate.test.js)` → `OK` and `# fail 0`

**Steps:**

- [ ] Write the two docs files (content per criteria), RED tests, the small `metrics.py` changes (`--log` on `gate`, the wave-count suffix), GREEN. **Commit** `feat(metrics): gate K1 and upfront-seq config`.

```json:metadata
{"files": ["docs/superpowers/metrics/gates/K1.md", "docs/superpowers/metrics/configs/upfront-seq.md", "board/tests/test_metrics_gate_k1.py", "engine/test/gate.test.js", "board/metrics.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_gate_k1 -v && (cd engine && node --test test/gate.test.js)", "acceptanceCriteria": ["K1.md prose + exact spec json:gate", "upfront-seq.md config fence", "pass / fail per condition / too early (3 specs, appends_verified false); runs without refreshes not counted", "append wave count printed beside parallelism", "Node test appends via metrics append and gate reads it"], "modelTier": "standard"}
```

---

### Task 11: Lead rules and the manifest rule for plan writers

**Goal:** `claude/orchestrator.md` Queue mode carries up-front planning, the stale check, entry gates and the analysis path in the morning report; `writing-plans-extras` gains the manifest rule; README mentions `engine/`.

**Files:**
- Modify: `claude/orchestrator.md` (Queue mode steps 2 and 5, a new step for up-front planning), `claude/skills/writing-plans-extras/SKILL.md` (new `## 14.` before `## Before you finish`, and one clause in that checklist), `README.md` (layout list)

**Acceptance Criteria:**
- [ ] orchestrator.md Queue mode, wording taken from the spec (quote, do not paraphrase the rule sentence):
  - the boundary rule of spec §2 verbatim (`> Before running the next spec, if any pending …`), with the 5-step up-front procedure (batch `--config upfront-seq`, planners `plan-<slug>` on Opus with `Reason: up-front planner`, at most four at a time, no native tasks, `registry validate` until it passes; `registry analyse`; `crossplan-<batch>` frontier agent writing `relations.json` from manifests + titles + Decisions; analyse again with `--relations`; shut planners down) and the failure rule (planner fails or never validates after one retry → just in time).
  - step 2 gains the stale check of spec §3 (rebase the plan-only branch onto `main`; `registry stale`; `fresh` runs as written; `stale` → one `refresh-<slug>` agent on Opus with `git diff <base> main -- <paths>`, which patches plan, `.tasks.json` and manifest, sets the new `base` and adds `"refreshed_from": {"base": <old>, "stale_paths": [...]}`, re-validates and commits; `writing-plans` is not run again for an up-front plan; a failed refresh → plan just in time).
  - entry gates of spec §6 (`Entry gate: <id>` header line; `registry report <batch>` then `metrics gate <id>`; non-zero → `failed — gate <id>: <line>` and `metrics record … --outcome failed`).
  - morning report: `tmux-ctl registry report <batch>` before the Metrics section, and the analysis document path after it.
  - error handling: a failing `registry` command never blocks the queue (plan just in time, no stale check).
- [ ] SKILL.md `## 14. Every plan carries a manifest`: the block's fields (spec §1 example), every path in any task's `files` is in `writes` or `reads`, fixtures and docs the tasks create are `create`, unsure between `modify` and `append` → `modify`, `tmux-ctl registry validate <plan>` passes before the plan is committed. The "Before you finish" paragraph gains "the plan carries a `json:manifest` that `registry validate` accepts".
- [ ] README layout lists `engine/` (Node: the PCEE plan registry; `tmux-ctl registry`).
- [ ] `grep -c 'registry stale' claude/orchestrator.md` >= 1, `grep -c 'Entry gate:' claude/orchestrator.md` >= 1, `grep -c '^## 14\.' claude/skills/writing-plans-extras/SKILL.md` == 1.
- [ ] Existing rules tests pass: `tools/tests/test_plugin.zsh`, `tools/tests/test_queue_ask_rule.zsh` (they grep orchestrator.md) and `tools/tests/test_install.zsh`.

**Verify:** `grep -c 'registry stale' claude/orchestrator.md && grep -c 'Entry gate:' claude/orchestrator.md && grep -c '^## 14\.' claude/skills/writing-plans-extras/SKILL.md && { for f in tools/tests/test_plugin.zsh tools/tests/test_queue_ask_rule.zsh tools/tests/test_install.zsh; do zsh $f; done 2>&1 | grep -c '^FAIL' || true; }` → `>=1`, `>=1`, `1`, then `0`

**Steps:**

- [ ] Use `writing-for-agents` skill for the wording. Edit, run Verify. **Commit** `docs(rules): up-front planning, stale check, entry gates, manifest rule`.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/skills/writing-plans-extras/SKILL.md", "README.md"], "verifyCommand": "grep -c 'registry stale' claude/orchestrator.md && grep -c 'Entry gate:' claude/orchestrator.md && grep -c '^## 14\\.' claude/skills/writing-plans-extras/SKILL.md && { for f in tools/tests/test_plugin.zsh tools/tests/test_queue_ask_rule.zsh tools/tests/test_install.zsh; do zsh $f; done 2>&1 | grep -c '^FAIL' || true; }", "acceptanceCriteria": ["orchestrator.md: boundary rule verbatim + up-front procedure + failure rule", "stale check with refresh agent and refreshed_from", "entry gates", "morning report runs registry report and names the analysis path", "registry failure never blocks the queue", "SKILL.md section 14 manifest rule + checklist clause", "README lists engine/", "rules suites: 0 FAIL"], "modelTier": "standard"}
```

---

### Task 12: Full suite and read-only real-state checks

**Goal:** Every suite passes and the new commands behave on the real repository state, read-only.

**Files:**
- Test only (no file changes; fixes go back to the owning task's files)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS` with rc 0 or 4 (4 = over the time budget, accepted on this machine), and the `engine` job in the job list.
- [ ] `grep -rn 'runs.jsonl' engine/lib engine/bin` prints nothing (one-writer rule), and the count of files it checked (`ls engine/lib/registry/*.js engine/bin/*.js | wc -l`) is >= 9.
- [ ] Real state, read-only: `zsh bin/tmux-ctl metrics runs 2026-11-11-1 --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["specs"]), sum(1 for v in d["runs"].values() if v))'` prints two numbers, the second >= 10 (that batch's specs recorded so far).
- [ ] `node engine/bin/registry.js validate docs/superpowers/plans/2026-11-21-pcee-registry.md` → exit 0.
- [ ] `node engine/bin/registry.js stale docs/superpowers/specs/2026-11-10-pcee-registry-design.md` → `fresh` (or `stale` naming only paths main really changed since 30b7e22; check with `git diff --name-only 30b7e22 main`).
- [ ] `node engine/bin/registry.js stale docs/superpowers/specs/2026-11-13-trend-scout-design.md` → `no manifest`, exit 3 (a real past plan).
- [ ] `zsh bin/tmux-ctl metrics gate K1; echo rc=$?` on the real log → `gate K1: too early`, rc 3 (no run has `refreshes` yet).
- [ ] `git status --porcelain docs/superpowers/metrics/runs.jsonl` in the main checkout is empty after all of the above (nothing wrote to the real log).

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line `ALL PASS …` and `rc=0` or `rc=4`

**Steps:**

- [ ] Run each criterion's command through `tmux-ctl run -t 1200 tests "<cmd>"`, capture the output in the ledger. Any failure: `superpowers-extended-cc:systematic-debugging`, fix in the owning file, re-run that task's Verify, then this one.

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh ALL PASS rc 0 or 4 with the engine job", "no runs.jsonl in engine/lib or engine/bin (>=9 files checked)", "metrics runs 2026-11-11-1 --json on the real log: >=10 run lines", "this plan validates", "stale on this spec fresh (or only real main changes)", "stale on trend-scout: no manifest, exit 3", "gate K1 on the real log: too early, rc 3", "real runs.jsonl untouched"], "modelTier": "standard"}
```

---

### Task 13: User gate: first live use of manifests (morning report)

**Goal:** On the specs after this one, four plans with valid manifests are committed before the first of them runs, the analysis document carries Prediction against outcome, and the `PCEE:` status line shows K1's values.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Test only

**Acceptance Criteria:**
- [ ] `git log --diff-filter=A --format=%ci -- <plan>` for four up-front plans is earlier than the first of those specs' `start` lines (`tmux-ctl metrics has start --spec <first> --batch <upfront batch>` and the start line's `at`).
- [ ] `node engine/bin/registry.js validate <plan>` exits 0 for each of the four.
- [ ] `docs/superpowers/metrics/analysis/<upfront batch>.md` contains `## Prediction against outcome`.
- [ ] `tmux-ctl metrics status` prints a `PCEE:` line naming gate K1 with its three values.

**Verify:** `tmux-ctl metrics gate K1; echo rc=$?` → prints each K1 condition with its value; rc 0, 1 or 3 recorded as evidence

**Lead step after this branch merges (spec §7):** the running lead keeps the rules it started with, so after the merge
the lead hands off to a fresh lead (`agent-board:handoff`; in Queue mode it relays without asking). The new lead
starts with the new rules and applies the boundary rule (up-front planning) before the next spec.

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl metrics gate K1; echo rc=$?", "acceptanceCriteria": ["four up-front plans committed before the first of them started", "registry validate exit 0 for each", "analysis document has Prediction against outcome", "metrics status PCEE line shows K1 values"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
