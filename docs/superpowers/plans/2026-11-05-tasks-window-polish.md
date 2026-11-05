# Tasks Window Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tasks window (`board/taskwin.py`) readable for real plans: per-blocker connector lanes with arrowheads, tier badges from the repo's routing file, every completion flashing, `+N more` in the list, a NO_COLOR critical-path marker, and compact 2-row cards before falling back to the list.

**Architecture:** All rendering changes stay inside the pure `render()` path of `board/taskwin.py` (no I/O, no clock, no tmux); new inputs arrive as arguments (`tier_model`). Only `watch()` does I/O: it reads `<root>/docs/superpowers/model-routing.json` once per plan change. Tasks run in order because every task edits the same file.

**Tech Stack:** Python 3 stdlib, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-05-tasks-window-polish-design.md`

## Global Constraints

- `render()` stays pure: no file reads, no `time.time()`, no tmux. Everything new arrives as an argument.
- Every colour-none render keeps the invariants checked by `check_plain` in `board/tests/test_taskwin.py`: at most `height` lines, each at most `width` display cells, no escapes, no `✗`.
- Lanes: at most `GUTTER - 1` (= 3) vertical lanes per gutter, lane `k` at `xs + 1 + k` where `xs` is the x of the right border of the column left of the gutter. Lane order: distinct blockers by (column, row). Overflow blockers share the last lane.
- Arrowhead `▸` sits in the cell `xd - 1`, just left of the dependent card's left border at `xd`; the card border itself stays `│`. One `▸` per (card, row).
- Badge rule: the tier is looked up in `tier_model` (default `TIER_MODEL`); a mapped value `"inherit"` → no badge; a mapped value in `TIER_STYLE` → that style; any other mapped string → badge in default style `()`. A raw tier that is not a tier name: badge only if it is a `TIER_STYLE` model name (today's behaviour; `tier="opus"` raw still shows nothing).
- Compact card is 2 rows, full card 4; `GAP` stays 1; the whole graph is one size. Edge rows: full `+1`, compact `+0`.
- Targeted tests only: `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'`. Never run the full board suite or `run-all.zsh`.
- Commit messages: conventional with scope `taskwin`, e.g. `feat(taskwin): …`; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- Compact cards (not a wrapped column) for tall graphs (2026-11-05, in the spec).
- No full suites; targeted tests only (queue rule).

**Lead rulings (made while planning, recorded in the ledger):**
- Ruling: the spec says a 14-task 9-root plan falls back to the list at 120x50, but a probe of `main` shows 9 roots (44 rows) still fit at 120x50 as full cards. The compact-card tests use a 14-task **9-root** plan at **120x40** (list today, compact after) and a 14-task **12-root** plan at **120x50** (list today, compact after), plus the 9-root plan at 120x200 → full cards. Cost if wrong: the threshold the user saw differs, but the behaviour (compact before list) is the same.
- Ruling: compact-card bottom segments drop in this order when they do not fit: badge first, then owner, duration last ("duration last to go" in the spec).
- Ruling: the header line (`✦ Task N done ✦`) keeps naming one task (the first young `done` event); only the card/list flash becomes a set.
- Ruling: "once per plan change" = re-read the routing file when `view["name"]` changes (and on the first tick).

---

### Task 1: Tier badges from the routing file

**Goal:** `render()` takes an optional `tier_model` mapping used by `_badge`, and `watch()` reads the repo's `docs/superpowers/model-routing.json` once per plan change and passes it.

**Files:**
- Modify: `board/taskwin.py` (`_badge`, `_draw_card`, `_list_line`, `_graph_lines`, `_list_lines`, `render`, `watch`; new `load_tier_model`)
- Test: `board/tests/test_taskwin.py` (new `TierModelTest`), `board/tests/test_taskwin_cli.py` (new tests in `TestWatch`)

**Acceptance Criteria:**
- [ ] `render(..., tier_model={"standard": "opus"})` shows the badge `opus` for a `standard` task, in the default style (no colour SGR right before `opus` in a `"256"` render).
- [ ] `tier_model={"frontier": "inherit"}` shows no badge for a `frontier` task.
- [ ] Without `tier_model`, all existing tier tests pass unchanged (incl. raw `tier="opus"` → no badge).
- [ ] `load_tier_model(root)` returns the file's string values for `mechanical`/`standard`/`frontier`, falling back to `TIER_MODEL` per tier for a missing file, unreadable/malformed JSON, a non-dict top level, or a non-string value.
- [ ] `watch()` calls `load_tier_model` once while `view["name"]` stays the same across ticks, again when it changes, and the rendered frame shows the routed model.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing render tests** (append to `board/tests/test_taskwin.py`):

```python
class TierModelTest(unittest.TestCase):
    def test_routing_override_badges_new_model_in_default_style(self):
        v = view_of([task(1, "a", "pending", tier="standard")])
        out = plain(v, 120, 30, t={}, tier_model={"standard": "opus"})
        self.assertIn("opus", out)
        self.assertNotIn("sonnet", out)
        col = taskwin.render(v, {}, 120, 30, NOW, 0, "256", tier_model={"standard": "opus"})
        i = col.index("opus")
        self.assertNotIn(taskwin.SGR["blue"][1], col[max(0, i - 20):i])  # default style, not sonnet's blue

    def test_inherit_shows_no_badge(self):
        v = view_of([task(1, "a", "pending", tier="frontier")])
        out = plain(v, 120, 30, t={}, tier_model={"frontier": "inherit"})
        self.assertNotIn("inherit", out)
        self.assertNotIn("fable", out)

    def test_partial_mapping_keeps_defaults_for_other_tiers(self):
        v = view_of([task(1, "a", "pending", tier="mechanical"), task(2, "b", "pending", tier="standard")])
        out = plain(v, 120, 30, t={}, tier_model={"standard": "opus"})
        self.assertIn("haiku", out)
        self.assertIn("opus", out)
```

`plain()` already forwards `**kw` to `render`. Mutation: make `_badge` ignore `tier_model` → the first and third tests fail.

- [ ] **Step 2: Write the failing watch tests** (in `board/tests/test_taskwin_cli.py`):

```python
class TestTierModel(Base):
    def write(self, text):
        p = self.repo / "docs" / "superpowers"
        p.mkdir(parents=True, exist_ok=True)
        (p / "model-routing.json").write_text(text)

    def test_reads_string_values(self):
        self.write('{"mechanical": "haiku", "standard": "opus", "frontier": "inherit", "enforceEffort": true}')
        self.assertEqual(taskwin.load_tier_model(self.repo),
                         {"mechanical": "haiku", "standard": "opus", "frontier": "inherit"})

    def test_falls_back_per_tier(self):
        self.write('{"standard": 3, "frontier": "opus"}')
        self.assertEqual(taskwin.load_tier_model(self.repo),
                         {"mechanical": "haiku", "standard": "sonnet", "frontier": "opus"})

    def test_missing_malformed_and_non_dict_fall_back(self):
        self.assertEqual(taskwin.load_tier_model(self.repo / "nope"), taskwin.TIER_MODEL)
        for bad in ("{not json", "[1, 2]", ""):
            self.write(bad)
            self.assertEqual(taskwin.load_tier_model(self.repo), taskwin.TIER_MODEL, bad)
```

And in `TestWatch`, a test that patches `taskwin.load_tier_model` with a `mock.Mock(wraps=taskwin.load_tier_model)`, runs `run_watch(3, view=...)` with a `view` side effect returning a fixed view named `"a"` twice then `"b"`, and asserts `call_count == 2`; plus one that writes `{"standard": "opus"}` into `self.repo` and asserts `"opus"` appears in the watch output for a view with one `standard` task (build the view dict directly in the side effect). Mutation: call `load_tier_model` every tick → the call-count test fails.

- [ ] **Step 3: Run to see them fail**

Run: `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'`
Expected: FAIL/ERROR — `render() got an unexpected keyword argument 'tier_model'`, `module 'taskwin' has no attribute 'load_tier_model'`.

- [ ] **Step 4: Implement**

```python
def _badge(t, tier_model=None):
    """(model name, style) for the task's tier; None when there is no badge."""
    raw = t.get("tier") or ""
    tm = TIER_MODEL if tier_model is None else {**TIER_MODEL, **tier_model}
    if raw in tm:
        model = tm[raw]
        if not isinstance(model, str) or not model or model == "inherit":
            return None
        return (model, (TIER_STYLE[model],) if model in TIER_STYLE else ())
    return (raw, (TIER_STYLE[raw],)) if raw in TIER_STYLE else None


def load_tier_model(root):
    """{tier: model} from <root>/docs/superpowers/model-routing.json; TIER_MODEL per tier on any problem."""
    try:
        data = json.loads((Path(root) / "docs" / "superpowers" / "model-routing.json").read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: (data[k] if isinstance(data.get(k), str) else v) for k, v in TIER_MODEL.items()}
```

Thread `tier_model=None` through `render` → `_graph_lines` / `_list_lines` → `_draw_card` / `_list_line` → `_badge`. In `watch`, keep `tm, tm_for = None, object()` before the loop; each tick after `_fetch`, `if view.get("name") != tm_for: tm, tm_for = load_tier_model(root), view.get("name")`, and pass `tier_model=tm` to `render`. The `render` CLI subcommand also passes `load_tier_model(a.root)`.

- [ ] **Step 5: Run to see them pass**, plus the snapshot tests (unchanged output without a routing override).

Run: `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add board/taskwin.py board/tests/test_taskwin.py board/tests/test_taskwin_cli.py
git commit -m "feat(taskwin): tier badges follow the repo's model-routing.json"
```

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin.py", "board/tests/test_taskwin_cli.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["tier_model={'standard':'opus'} badges opus in default style", "inherit shows no badge", "existing tier tests unchanged", "load_tier_model falls back per tier on missing/malformed/non-dict/non-string", "watch reads routing once per plan name change and the frame shows the routed model"], "modelTier": "standard"}
```

---

### Task 2: Every completion flashes, `+N more`, NO_COLOR critical-path marker

**Goal:** Flash every task with a young `done` event; end an overflowing list with `+N more`; mark critical-path ids with `*` when `color == "none"`.

**Files:**
- Modify: `board/taskwin.py` (`_young` helper or a new `_young_ids`, `render`, `_graph_lines`, `_draw_card`, `_list_lines`, `_list_line`)
- Test: `board/tests/test_taskwin.py`

**Acceptance Criteria:**
- [ ] Two `done` events within `DONE_TTL` of `now`: both cards render inverse in a `"256"` render (graph layout), and both list lines render inverse at width 60.
- [ ] A `done` event older than `DONE_TTL` does not flash.
- [ ] The header still shows one `✦ Task N done ✦` line.
- [ ] List layout with more unfinished tasks than rows: the last row is `+N more` (grey in colour), N = unfinished tasks not shown; no task line is cut off silently. With completed tasks present they are summarised first (as now) and N counts only unfinished tasks.
- [ ] `color="none"`: every critical-path card top border reads `╭─ <glyph> *<id> ` and every critical-path list line reads `<glyph> *<id>`; non-critical ids have no `*`. Colour renders contain no `*` before ids.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** (append to `board/tests/test_taskwin.py`):

```python
class PolishTest(unittest.TestCase):
    def two_done(self):
        ev = [{"kind": "done", "id": "1", "at": NOW - 1}, {"kind": "done", "id": "2", "at": NOW - 1.5}]
        return timing({"1": NOW - 1, "2": NOW - 1.5}, events=ev)

    def inverse_ids(self, out):
        return set(re.findall(r"\x1b\[7[;0-9]*m[^\x1b]*?([0-9]+)", out))

    def test_every_young_done_flashes_in_graph(self):
        v = view_of([task(1, "a", "completed"), task(2, "b", "completed"), task(3, "c", "pending", [1, 2])])
        col = taskwin.render(v, self.two_done(), 120, 40, NOW, 0, "256")
        tops = [l for l in col.split("\n") if "╭" in l]
        self.assertTrue(any("\x1b[7" in l and " 1 " in taskwin.strip(l) for l in tops))
        self.assertTrue(any("\x1b[7" in l and " 2 " in taskwin.strip(l) for l in tops))

    def test_every_young_done_flashes_in_list(self):
        v = view_of([task(1, "a", "completed"), task(2, "b", "completed"), task(3, "c", "pending", [1, 2])])
        lines = taskwin.render(v, self.two_done(), 60, 40, NOW, 0, "256").split("\n")
        for i in ("1", "2"):
            line = next(l for l in lines if taskwin.strip(l).startswith("● " + i + " "))
            self.assertIn("\x1b[7", line, i)

    def test_old_done_does_not_flash(self):
        ev = [{"kind": "done", "id": "1", "at": NOW - 5}]
        v = view_of([task(1, "a", "completed"), task(2, "b", "pending", [1])])
        col = taskwin.render(v, timing({"1": NOW - 5}, events=ev), 60, 40, NOW, 0, "256")
        self.assertNotIn("\x1b[7", col)

    def test_list_overflow_ends_in_plus_n_more(self):
        v = view_of([task(i, f"t{i}", "pending") for i in range(1, 21)])
        out = plain(v, 60, 10, t={})          # 3 header rows, 7 body rows
        lines = out.split("\n")
        self.assertEqual(lines[-1].strip(), "+14 more")   # 6 shown, 14 not
        check_plain(self, out, 60, 10)

    def test_plus_n_more_counts_only_unfinished(self):
        v = view_of([task(i, f"t{i}", "completed") for i in range(1, 4)] +
                    [task(i, f"t{i}", "pending") for i in range(4, 24)])
        lines = plain(v, 60, 10, t={}).split("\n")
        self.assertTrue(lines[3].startswith("●"))          # done summary row
        self.assertEqual(lines[-1].strip(), "+15 more")    # 7 body rows: summary, 5 tasks, +N → 20-5

    def test_no_plus_n_more_when_everything_fits(self):
        v = view_of([task(i, f"t{i}", "pending") for i in range(1, 5)])
        self.assertNotIn("more", plain(v, 60, 20, t={}))

    def test_no_color_marks_critical_path(self):
        v = view_of(chain(3) + [task(9, "lone", "pending")])
        out = plain(v, 120, 40, t={})
        for i in ("1", "2", "3"):
            self.assertRegex(out, r"╭─ \S \*" + i + " ")
        self.assertNotIn("*9", out)
        narrow = plain(v, 60, 40, t={})
        for i in ("1", "2", "3"):
            self.assertRegex(narrow, r"(?m)^\S \*" + i + " ")
        self.assertRegex(narrow, r"(?m)^\S 9 ")

    def test_colour_has_no_star(self):
        v = view_of(chain(3))
        self.assertNotIn("*", taskwin.strip(taskwin.render(v, {}, 120, 40, NOW, 0, "256")))
```

Mutations: keep the single `flash_id` → both flash tests fail on task 2; remove the `+N` row → overflow tests fail; drop the `color == "none"` check (always star) → `test_colour_has_no_star` fails. Before relying on `test_list_overflow_ends_in_plus_n_more`, compute the expected N by hand from the row budget (`avail = height - HEADER_ROWS`) and adjust the literal only if the hand count disagrees with the comment; say so in your report.

- [ ] **Step 2: Run to see them fail** — `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'`; expected FAIL on task 2 not inverse, no `+N more`, no `*`.

- [ ] **Step 3: Implement**
  - Add `_young_ids(timing, now)` → `{str(e["id"]) for done events with 0 <= now - at < DONE_TTL}`; `render` passes `flash_ids` (a set) instead of `flash_id`; cards and list lines flash when `t["id"] in flash_ids`.
  - `_list_lines`: after choosing `rows` and the summary, if `len(rows) > n - (1 if summary else 0)`, reserve the last row: show `n - 1 - (1 if summary else 0)` tasks, then `+N more` in `("grey",)` where N = `len(rows) - shown`.
  - Critical path: `render` computes `crit = set(critical_path(tasks))` once and passes it plus `color` to both layouts. `_draw_card` writes `" *" + id + " "` instead of `" " + id + " "` when `color == "none" and accent`. `_list_line` takes `mark` and writes `" *" + id + "  "`.

- [ ] **Step 4: Run to see them pass** (snapshots too: `wide.txt`/`narrow.txt` are colour-none renders of `SIX`, whose critical path is 3→4→6 — so they **will** change by the `*` markers; regenerate them with the snippet below, then `git diff board/tests/fixtures/taskwin/` must show only `*` insertions before ids 3, 4, 6 (and the `─` shortened by one cell to keep width).

```bash
cd board && python3 -c "
import sys; sys.path.insert(0,'tests'); import test_taskwin as T
open('tests/fixtures/taskwin/wide.txt','w').write(T.plain(T.SIX,120,40,session='dev'))
open('tests/fixtures/taskwin/narrow.txt','w').write(T.plain(T.SIX,60,40,session='dev'))"
```

- [ ] **Step 5: Commit**

```bash
git add board/taskwin.py board/tests/test_taskwin.py board/tests/fixtures/taskwin/
git commit -m "feat(taskwin): flash every completion, +N more in the list, NO_COLOR critical-path marker"
```

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin.py", "board/tests/fixtures/taskwin/wide.txt", "board/tests/fixtures/taskwin/narrow.txt"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["two young done events: both cards and both list lines inverse", "old done event does not flash", "header still names one task", "list overflow ends in +N more with N = unfinished not shown", "color=none marks critical-path ids with * in cards and list; colour renders have no *"], "modelTier": "standard"}
```

---

### Task 3: Per-blocker connector lanes with arrowheads

**Goal:** Each distinct blocker feeding a gutter gets its own vertical lane, and every edge ends in `▸` just left of the dependent card.

**Files:**
- Modify: `board/taskwin.py` (`_draw_edges`)
- Test: `board/tests/test_taskwin.py`; regenerate `board/tests/fixtures/taskwin/wide.txt`

**Acceptance Criteria:**
- [ ] Two blockers (column 0, rows 0 and 1) feeding two dependents (column 1, rows 0 and 1, each blocked by both): the two vertical lanes are at different x (`xs+1`, `xs+2`), asserted by exact glyph strings for the gutter cells of the edge rows, and a `▸` at `xd-1` on each dependent's entry row.
- [ ] Five blockers in one column feeding one dependent: blockers 0 and 1 have their own lanes (`xs+1`, `xs+2`); blockers 2–4 share lane `xs+3`.
- [ ] A spanning edge (column 0 → column 2) still routes along a gap row and ends in `▸`.
- [ ] Where two edges enter the same card row there is exactly one `▸`; the dependent's left border stays `│` (no `┤` from an entering edge).
- [ ] Lane crossings draw `┼`; all colour-none invariants (`check_plain`) hold for `SIX` at every width in `test_every_width_respects_cells_and_height`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Build each fixture with `view_of`/`task`, render with `plain(v, 120, 40, t={})`, and slice the gutter: for column-0 cards `cw = taskwin._card_width(ncols, 120)`, `xs = cw - 1`, `xd = cw + taskwin.GUTTER`, body row `y` of a card in row `r` is `taskwin.HEADER_ROWS + r * (taskwin.CARD_H + taskwin.GAP) + 1`. Assert `line[xs+1:xd]` for each edge row as an exact 4-character string you derive by hand from the rules in Global Constraints (write the expected strings before running; do not paste them from the output). Example shape for the two-by-two case (row-0 blocker uses lane 0, row-1 blocker lane 1; each dependent entered from both lanes):

```python
    def gutter(self, out, y, xs, xd):
        return out.split("\n")[y][xs + 1:xd]

    def test_two_blockers_two_dependents_get_distinct_lanes(self):
        v = view_of([task(1, "a", "pending"), task(2, "b", "pending"),
                     task(3, "c", "pending", [1, 2]), task(4, "d", "pending", [1, 2])])
        out = plain(v, 120, 40, t={})
        cw = taskwin._card_width(2, 120)
        xs, xd = cw - 1, cw + taskwin.GUTTER
        y0 = taskwin.HEADER_ROWS + 1
        y1 = y0 + taskwin.CARD_H + taskwin.GAP
        self.assertEqual(self.gutter(out, y0, xs, xd), "<hand-derived>")
        self.assertEqual(self.gutter(out, y1, xs, xd), "<hand-derived>")
        self.assertEqual(out.split("\n")[y0][xd - 1], "▸")
        self.assertEqual(out.split("\n")[y1][xd - 1], "▸")
        self.assertEqual(out.split("\n")[y0][xd], "│")
```

Replace each `<hand-derived>` with the exact string before the RED run and say in your report how you derived it. Add the five-blocker test (assert the x positions of the `│` cells in a gap row between blocker rows 2 and 4: lane 2 only, i.e. `line[xs+3] == "│"` and `line[xs+1]`, `line[xs+2]` are blank there), the spanning test (`chain`-like 1 → 2 → 3 plus 1 → 3; `▸` before card 3), and the one-`▸` / `│`-border test. Mutation: set every lane to `xs + 1` (today's shared bus) → the distinct-lane and five-blocker tests fail.

- [ ] **Step 2: Run to see them fail** — expected: gutter strings differ, no `▸`.

- [ ] **Step 3: Implement in `_draw_edges(cv, cols, cw, pos)`**
  - First pass: for every edge (blocker `b` at `(a, ra)` → dependent at `(c, rb)`), record which gutters it uses vertically: gutter `a` (bus_a) always; gutter `c - 1` (bus_b) when `c > a + 1`. Per gutter `g`, sort the distinct blockers by `pos[b]` (column, row) and give lane `min(k, GUTTER - 2)` → x = `g * (cw + GUTTER) + cw + k` (that is `xs + 1 + k`, with `xs = g * (cw + GUTTER) + cw - 1`).
  - Second pass: route each edge as today but with `bus_a = lane x of b in gutter a`, `bus_b = lane x of b in gutter c - 1`, and end the last horizontal segment at `xd - 1` instead of `xd`. Collect the arrow cells `(xd - 1, yd)` in a set.
  - Drawing: as today, then overwrite each arrow cell with `▸` in `("grey",)` (one per cell, by construction). The `│`→`├` rule for the source border stays; the `│`→`┤` rule is no longer reached because edges stop at `xd - 1` — keep it harmless.
  - Edge rows `ys`/`yd` stay `+1` here; Task 4 parametrises them.

- [ ] **Step 4: Run to see them pass**; regenerate `wide.txt` with the snippet from Task 2 Step 4 and check `git diff board/tests/fixtures/taskwin/wide.txt` shows only gutter changes (lanes, `▸`) — no card content changes. `narrow.txt` must not change.

- [ ] **Step 5: Commit**

```bash
git add board/taskwin.py board/tests/test_taskwin.py board/tests/fixtures/taskwin/wide.txt
git commit -m "feat(taskwin): one connector lane per blocker, arrowheads at each dependent"
```

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin.py", "board/tests/fixtures/taskwin/wide.txt"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["two blockers into two dependents use distinct lanes, exact gutter glyphs asserted, ▸ at each entry", "five blockers: lanes 0-1 distinct, rest share lane 2", "spanning edge routes along a gap row and ends in ▸", "one ▸ per entered card row; dependent border stays │", "crossings ┼; check_plain invariants hold at all widths"], "modelTier": "standard"}
```

---

### Task 4: Compact cards for tall graphs

**Goal:** `_plan_graph` tries compact 2-row cards (with the same done-column collapse) before giving up to the list.

**Files:**
- Modify: `board/taskwin.py` (`_plan_graph`, `_graph_lines`, `_draw_card` or a new `_draw_compact`, `_draw_edges`)
- Test: `board/tests/test_taskwin.py`

**Acceptance Criteria:**
- [ ] A 14-task plan with 9 roots renders as the list at 120x40 on `main` (RED) and as compact cards after (every card's top border is followed directly by its bottom border `╰`).
- [ ] A 14-task plan with 12 roots at 120x50: list on `main`, compact cards after.
- [ ] The 9-root plan at 120x200 renders full 4-row cards (a `│ ` subject row under each top border).
- [ ] Compact top row: `╭─ <glyph> <id> <subject…> ─╮`; bottom row: `╰─ <badge> · ✦ <owner> · <dur> ─╯`, segments dropped badge first, then owner, duration last, when they do not fit; NO_COLOR `*` marker from Task 2 also applies on the compact top row.
- [ ] Edges between compact cards enter and leave on the top row (`+0`), and end in `▸` (Task 3 rules).
- [ ] `check_plain` invariants hold for both plans at 120x40, 120x50, 120x200 and 80x30.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** (append):

```python
def roots_plan(nroots):
    """14 tasks: `nroots` roots, the rest a short dependency tail over them."""
    ts = [task(i, f"root task {i}", "pending", tier="standard") for i in range(1, nroots + 1)]
    rest = list(range(nroots + 1, 15))
    for k, i in enumerate(rest):
        blockers = [rest[k - 1]] if k else [1, 2]
        if k == len(rest) - 1:
            blockers = blockers + [3, 4]
        ts.append(task(i, f"tail task {i}", "pending", blockers, tier="standard"))
    return view_of(ts)


class CompactTest(unittest.TestCase):
    def is_compact(self, out):
        lines = out.split("\n")
        tops = [k for k, l in enumerate(lines) if "╭" in l]
        return bool(tops) and all("╰" in lines[k + 1] for k in tops)

    def test_nine_roots_at_120x40_is_compact(self):
        out = plain(roots_plan(9), 120, 40, t={})
        check_plain(self, out, 120, 40)
        self.assertIn("╭", out)
        self.assertTrue(self.is_compact(out))

    def test_twelve_roots_at_120x50_is_compact(self):
        out = plain(roots_plan(12), 120, 50, t={})
        check_plain(self, out, 120, 50)
        self.assertTrue(self.is_compact(out))

    def test_tall_terminal_keeps_full_cards(self):
        out = plain(roots_plan(9), 120, 200, t={})
        self.assertIn("╭", out)
        self.assertFalse(self.is_compact(out))
        self.assertRegex(out, r"│ root task 1")

    def test_compact_rows_and_drop_order(self):
        v = view_of([task(1, "first subject", "in_progress", owner="ann", state="working", tier="standard")] +
                    [task(i, f"r{i}", "pending") for i in range(2, 13)])
        t = timing({"1": NOW - 720})
        out = plain(v, 120, 40, t=t)
        lines = out.split("\n")
        k = next(k for k, l in enumerate(lines) if " 1 first" in l)
        self.assertRegex(lines[k], r"╭─ \S 1 first subject")
        self.assertRegex(lines[k + 1], r"╰─ sonnet · ✦ ann.* · 12m ─╯")

    def test_compact_edges_enter_on_top_row(self):
        out = plain(roots_plan(12), 120, 50, t={})
        for l in out.split("\n"):
            if "▸" in l:
                self.assertIn("╭", l)
```

Also unit-test the drop order directly on a narrow card: call the compact card drawer on a `Canvas(18, 2)` (or the smallest width where only the duration fits) and assert the bottom row keeps `12m` and drops `sonnet` and `ann`. Mutations: remove the compact attempt from `_plan_graph` → the three layout tests fail (list); use `+1` edge rows for compact → `test_compact_edges_enter_on_top_row` fails.

Before the RED run, check `roots_plan(9)` really falls back to the list at 120x40 on the current code (and `roots_plan(12)` at 120x50); if either does not, adjust the height (not the root count) and say so in your report.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement**
  - `_plan_graph(tasks, width, avail, card_h)`: the existing body with `CARD_H` replaced by `card_h`; return `(live, collapsed, cw, card_h)`. A wrapper tries `card_h=4` then `card_h=2` and returns the first non-None.
  - `_graph_lines` uses the returned `card_h` for row positions (`r * (card_h + GAP)`), the `spans_top` extra row, and passes it to `_draw_edges` (edge row offset `1 if card_h == 4 else 0`; the gap-row choice uses `card_h` too).
  - Compact card drawer: top = `╭─ ` + glyph + ` [*]id ` + truncated subject + ` ─…─╮`; bottom = `╰─ ` + segments joined by ` · ` + ` ─…─╯`; drop segments in the order badge, owner, duration until they fit `cw - 6`. Inverse flash covers both rows.

- [ ] **Step 4: Run to see them pass** (snapshots must not change: `SIX` fits full cards).

- [ ] **Step 5: Commit**

```bash
git add board/taskwin.py board/tests/test_taskwin.py
git commit -m "feat(taskwin): compact two-row cards before falling back to the list"
```

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["14-task 9-root plan: list at 120x40 before, compact after", "14-task 12-root plan at 120x50: compact", "9-root plan at 120x200: full cards", "compact rows match the spec; drop order badge, owner, duration last", "compact edges enter on the top row and end in ▸", "check_plain holds at 120x40, 120x50, 120x200, 80x30"], "modelTier": "standard"}
```

---

### Task 5: Real-state render check

**Goal:** Render real plans' task lists with the finished code and record the output in a notes file for the morning report.

**Files:**
- Create: `docs/superpowers/notes/2026-11-05-tasks-window-polish-real-render.md`

**Acceptance Criteria:**
- [ ] The notes file holds, each in a fenced block, colour-none renders (`render(..., color="none")`) of the newest real plan in `docs/superpowers/plans/*.md.tasks.json` (by filename date) at 120x50 and 200x60, and of `docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md.tasks.json` (14 tasks) at 120x50, with `tier_model=load_tier_model(<worktree root>)`.
- [ ] One more render of a real live list from `~/.claude/tasks/<dir>/` (read-only; the newest dir with ≥ 8 task files) at 120x50, task subjects kept, any owner names kept, no session ids in the doc (directory name replaced by `<session>`).
- [ ] Under each block, one line: layout used (full / compact / list), whether every unfinished task id is visible, and any glyph problem seen (overlapping lanes, `▸` on a border, a cut card). A problem found is reported to the lead, not fixed in this task.
- [ ] `grep -c '^```' <notes>` is 8 (four fenced blocks).

**Verify:** `test "$(grep -c '^```' docs/superpowers/notes/2026-11-05-tasks-window-polish-real-render.md)" = 8 && echo OK`

**Steps:**

- [ ] **Step 1:** Load each `.tasks.json` as `planview` does (`planview.file_tasks(path)` returns the normalised task list; check its signature first) and build `{"name": <plan name>, "active": True, "tasks": tasks}`; render with `taskwin.render(view, {}, W, H, time.time(), 0, "none", tier_model=taskwin.load_tier_model("."))` from the worktree root with `board/` on `sys.path`.
- [ ] **Step 2:** For the live list, `planview.live_tasks(home, sid)` or `_read_dir` on the newest qualifying `~/.claude/tasks/<dir>`; read only, never write there.
- [ ] **Step 3:** Write the notes file with the four blocks and the one-line findings; commit.

```bash
git add docs/superpowers/notes/2026-11-05-tasks-window-polish-real-render.md
git commit -m "docs(test): tasks-window polish real-plan renders"
```

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-05-tasks-window-polish-real-render.md"], "verifyCommand": "test \"$(grep -c '^```' docs/superpowers/notes/2026-11-05-tasks-window-polish-real-render.md)\" = 8 && echo OK", "acceptanceCriteria": ["newest real plan at 120x50 and 200x60, 14-task handoff-relay plan at 120x50, colour-none, routed tier_model", "a real ~/.claude/tasks list at 120x50, read-only, no session ids", "one findings line under each block", "four fenced blocks"], "modelTier": "standard"}
```
