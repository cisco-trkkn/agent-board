"use strict";
// Schedule rules (spec section 14): parseRule and nextAfter. The DST cases run in a child node process with
// TZ=America/New_York, so the zone is fixed for that process; the in-process ones use epoch seconds only.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const cp = require("node:child_process");
const { parseRule, nextAfter } = require("../lib/engine/schedule_rules");

const MOD = path.join(__dirname, "..", "lib", "engine", "schedule_rules.js");

// Run `body` in a child node process with TZ=America/New_York; `L(y, mo, d, h, mi)` is local time as epoch seconds.
function inNewYork(body) {
  const script = [
    `const { parseRule, nextAfter } = require(${JSON.stringify(MOD)});`,
    "const L = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi).getTime() / 1000;",
    body,
  ].join("\n");
  const r = cp.spawnSync(process.execPath, ["-e", script], {
    env: { ...process.env, TZ: "America/New_York" },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr);
  return r.stdout.trim();
}

const show = (expr) => `console.log(new Date((${expr}) * 1000).toString().slice(0, 24));`;

test("the child process really runs in America/New_York", () => {
  // July is EDT: offset 240 minutes behind UTC.
  assert.equal(inNewYork("console.log(new Date(2026, 6, 1).getTimezoneOffset());"), "240");
});

test("parseRule accepts exactly the three forms", () => {
  assert.deepEqual(parseRule("daily 03:30"), { kind: "daily", h: 3, m: 30 });
  assert.deepEqual(parseRule("weekly Sun 07:00"), { kind: "weekly", day: 0, h: 7, m: 0 });
  assert.deepEqual(parseRule("weekly Sat 23:59"), { kind: "weekly", day: 6, h: 23, m: 59 });
  assert.deepEqual(parseRule("every 15m"), { kind: "every", minutes: 15 });
  assert.deepEqual(parseRule("every 1m"), { kind: "every", minutes: 1 });
});

test("parseRule throws on malformed and out-of-range rules", () => {
  for (const bad of ["daily 3:30", "weekly sun 07:00", "every 0m", "daily 24:00", "hourly"]) {
    assert.throws(() => parseRule(bad), /bad rule/, `expected ${JSON.stringify(bad)} to throw`);
  }
});

test("daily: the same day when still ahead, the next day once the time has passed", () => {
  assert.equal(
    inNewYork(show(`nextAfter("daily 03:30", L(2026, 11, 24, 2, 0))`)),
    "Tue Nov 24 2026 03:30:00",
  );
  // Exactly at 03:30 is not "after": the next occurrence is the next day.
  assert.equal(
    inNewYork(show(`nextAfter("daily 03:30", L(2026, 11, 24, 3, 30))`)),
    "Wed Nov 25 2026 03:30:00",
  );
});

test("weekly: the next named weekday", () => {
  assert.equal(
    inNewYork(show(`nextAfter("weekly Sun 07:00", L(2026, 11, 24, 12, 0))`)),
    "Sun Nov 29 2026 07:00:00",
  );
});

test("spring forward: a time that does not exist runs at the rolled-forward time", () => {
  // 2027-03-14 02:30 does not exist in New York; JS Date rolls it to 03:30.
  assert.equal(
    inNewYork(show(`nextAfter("daily 02:30", L(2027, 3, 14, 0, 0))`)),
    "Sun Mar 14 2027 03:30:00",
  );
});

test("fall back: a time that occurs twice runs once, at its first occurrence", () => {
  const first = inNewYork(show(`nextAfter("daily 01:30", L(2026, 11, 1, 0, 0))`));
  assert.equal(first, "Sun Nov 01 2026 01:30:00");
  // Continue from that first occurrence: the second 01:30 is skipped, the next one is the following day.
  const next = inNewYork(
    `const first = nextAfter("daily 01:30", L(2026, 11, 1, 0, 0));` +
      show("nextAfter(\"daily 01:30\", first)"),
  );
  assert.equal(next, "Mon Nov 02 2026 01:30:00");
});

test("across the fall-back change a daily 07:00 is 25 hours after the previous day's", () => {
  const hours = inNewYork(
    `const t = nextAfter("daily 07:00", L(2026, 10, 31, 8, 0));` +
      "console.log((t - L(2026, 10, 31, 7, 0)) / 3600);",
  );
  assert.equal(hours, "25");
});

test("every: the anchor keeps the grid, and no anchor starts it at `after`", () => {
  assert.equal(nextAfter("every 15m", 1000, 100), 1900);
  assert.equal(nextAfter("every 15m", 50, 100), 100);
  // 1000 is itself on the anchor-100 grid (100 + 900): the occurrence strictly after it is 1900, as above.
  assert.equal(nextAfter("every 1m", 130), 190);
});
