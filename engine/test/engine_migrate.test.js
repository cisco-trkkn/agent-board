"use strict";
// Task 8: the wake heartbeat plist (`wake install|status|uninstall`) and `schedule migrate`, on a temp HOME and a logging launchctl stub.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");
const { tmpEnv } = require("./engine_helpers");
const dbm = require("../lib/engine/db");
const rebuild = require("../lib/engine/rebuild");
const steps = require("../lib/engine/steps");
const launchd = require("../lib/engine/launchd");

const ENGINE = path.resolve(__dirname, "../bin/engine.js");
const WAKE = "com.user.agent-board-engine-wake";
const darwin = process.platform === "darwin";
const D = { skip: darwin ? false : "macOS only" };

// leak check: the real LaunchAgents (names and mtimes) and the real engine dir, before any test runs
const REAL_HOME = process.env.HOME || os.homedir();
const REAL_LA = path.join(REAL_HOME, "Library/LaunchAgents");
const REAL_ENGINE = path.join(REAL_HOME, ".local/state/agent-board/engine");
const snap = (dir, skipLive) => {
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => !(skipLive && n.startsWith("agent-board."))).sort(); } catch (_) { return {}; }
  const o = {};
  for (const n of names) { try { o[n] = fs.statSync(path.join(dir, n)).mtimeMs; } catch (_) { o[n] = null; } }
  return o;
};
const LA_BEFORE = snap(REAL_LA);
const ENG_BEFORE = snap(REAL_ENGINE, true);

const cleanups = [];
test.after(() => { for (const c of cleanups.reverse()) { try { c(); } catch (_) { /* ignore */ } } });

const JOBS = [
  { label: "com.user.agent-board-dream", name: "dream", args: ["/h/.local/bin/tmux-ctl", "context", "dream", "--all"], cal: { Hour: 3, Minute: 30 }, rule: "daily 03:30", command: "tmux-ctl context dream --all" },
  { label: "com.user.agent-board-discover", name: "discover-nightly", args: ["/h/.local/bin/tmux-ctl", "discover", "nightly"], cal: { Hour: 7, Minute: 0 }, rule: "daily 07:00", command: "tmux-ctl discover nightly" },
  { label: "com.user.agent-board-scout-poll", name: "scout-poll", args: ["/h/.local/bin/tmux-ctl", "scout", "poll"], cal: { Hour: 6, Minute: 0 }, rule: "daily 06:00", command: "tmux-ctl scout poll" },
  { label: "com.user.agent-board-scout-weekly", name: "scout-weekly", args: ["/h/.local/bin/tmux-ctl", "scout", "weekly"], cal: { Hour: 7, Minute: 0, Weekday: 0 }, rule: "weekly Sun 07:00", command: "tmux-ctl scout weekly" },
  { label: "com.user.agent-board-scout-weekly-retry", name: "scout-weekly-retry", args: ["/h/.local/bin/tmux-ctl", "scout", "weekly", "--retry"], cal: { Hour: 7, Minute: 0, Weekday: 1 }, rule: "weekly Mon 07:00", command: "tmux-ctl scout weekly --retry" },
];
const ENVV = { LANG: "en_US.UTF-8", PATH: "/h/.local/bin:/usr/bin:/bin", TMPDIR: "/var/folders/x/T/" };

// A temp HOME with the fixture plists, a tmux-ctl, a stub launchctl and a temp engine dir.
function world({ odd = false } = {}) {
  const e = tmpEnv();
  cleanups.push(() => e.restore());
  const home = path.join(e.root, "home");
  const la = path.join(home, "Library/LaunchAgents");
  fs.mkdirSync(la, { recursive: true });
  fs.mkdirSync(path.join(home, ".local/bin"), { recursive: true });
  fs.writeFileSync(path.join(home, ".local/bin/tmux-ctl"), "#!/bin/sh\n", { mode: 0o755 });
  for (const j of JOBS) {
    fs.writeFileSync(path.join(la, `${j.label}.plist`), launchd.plistXml({
      Label: j.label, ProgramArguments: j.args, StartCalendarInterval: j.cal, WorkingDirectory: "/h/agent-board", EnvironmentVariables: ENVV,
    }));
  }
  const oddLabel = "com.user.agent-board-scout-poll";
  if (odd) {
    fs.writeFileSync(path.join(la, `${oddLabel}.plist`), launchd.plistXml({
      Label: oddLabel, ProgramArguments: ["/h/.local/bin/tmux-ctl", "scout", "poll"], StartInterval: 600, WorkingDirectory: "/h", EnvironmentVariables: ENVV,
    }));
  }
  const ctl = path.join(e.root, "ctl");
  fs.mkdirSync(ctl);
  const log = path.join(ctl, "calls.log");
  const stub = path.join(ctl, "launchctl");
  fs.writeFileSync(stub, `#!/bin/sh
echo "$@" >> "${log}"
c="$1"
if [ "$c" = print ]; then [ -e "${ctl}/print-rc" ] && exit "$(cat "${ctl}/print-rc")"; exit 0; fi
if [ "$c" = bootstrap ]; then [ -e "${ctl}/bootstrap-rc" ] && { echo "Bootstrap failed: 5: Input/output error" >&2; exit "$(cat "${ctl}/bootstrap-rc")"; }; exit 0; fi
if [ "$c" = bootout ] && [ -e "${ctl}/kill-on-bootout" ]; then rm -f "${ctl}/kill-on-bootout"; kill -9 $PPID; sleep 1; exit 0; fi
if [ "$c" = list ]; then [ -e "${ctl}/list-fail" ] && exit 1; [ -e "${ctl}/list-out" ] && cat "${ctl}/list-out"; exit 0; fi
exit 0
`, { mode: 0o755 });
  const env = { ...process.env, HOME: home, TC_ENGINE_DIR: e.engineDir, TC_STATE: e.state, TC_PROJECT: "p", AS_LAUNCHCTL: stub, AS_BIN_DIR: path.join(e.root, "bin") };
  delete env.TMUX;
  return {
    e, home, la, ctl, log, stub, env,
    plist: (label) => path.join(la, `${label}.plist`),
    calls: (re) => (fs.existsSync(log) ? fs.readFileSync(log, "utf8").split("\n").filter((l) => l && (!re || re.test(l))) : []),
    flag: (n, v = "") => fs.writeFileSync(path.join(ctl, n), String(v)),
    eng(args, extra = {}) { return cp.spawnSync("node", [ENGINE, ...args], { env: { ...env, ...extra }, encoding: "utf8", timeout: 60000 }); },
    db() { return dbm.open("p"); },
  };
}
const ok = (project = "p") => assert.equal(rebuild.check(project).rc, 0, JSON.stringify(rebuild.check(project).diffs));
const rows = (d) => d.prepare("SELECT * FROM timers WHERE kind='schedule' AND fired_at IS NULL ORDER BY id").all().map((r) => ({ id: r.id, ...JSON.parse(r.payload) }));
const withEnv = (w, fn) => {
  const old = {};
  for (const k of ["HOME", "AS_LAUNCHCTL", "AS_BIN_DIR", "TC_ENGINE_DIR", "TC_STATE"]) old[k] = process.env[k];
  Object.assign(process.env, { HOME: w.home, AS_LAUNCHCTL: w.stub, AS_BIN_DIR: w.env.AS_BIN_DIR, TC_ENGINE_DIR: w.e.engineDir, TC_STATE: w.e.state });
  try { return fn(); } finally { for (const [k, v] of Object.entries(old)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; } }
};

test("plistXml round-trips through plutil", D, () => {
  const obj = { Label: "a&b<c>", N: 900, T: true, F: false, A: ["x", "y z", "q'\""], M: { K: "v&", Z: 0 } };
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "pl-")), "x.plist");
  cleanups.push(() => fs.rmSync(path.dirname(f), { recursive: true, force: true }));
  fs.writeFileSync(f, launchd.plistXml(obj));
  const r = cp.spawnSync("plutil", ["-convert", "json", "-o", "-", f], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), obj);
  assert.deepEqual(launchd.readPlist(f), obj);
});

test("wake install writes the heartbeat plist, bootouts then bootstraps; a second install backs the old one up", D, () => {
  const w = world();
  const r = w.eng(["wake", "install"], { TC_STATE: w.e.state });
  assert.equal(r.status, 0, r.stderr + r.stdout);
  const p = launchd.readPlist(w.plist(WAKE));
  assert.equal(p.Label, WAKE);
  assert.deepEqual(p.ProgramArguments, [path.join(w.home, ".local/bin/tmux-ctl"), "engine", "wake"]);
  assert.equal(p.StartInterval, 900);
  assert.equal(p.RunAtLoad, true);
  assert.equal(p.WorkingDirectory, path.resolve(__dirname, "../.."));
  assert.equal(p.EnvironmentVariables.PATH, `${w.home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`);
  assert.equal(p.EnvironmentVariables.TC_STATE, w.e.state);
  assert.equal(p.EnvironmentVariables.TC_ENGINE_DIR, w.e.engineDir);
  assert.equal(p.EnvironmentVariables.TMPDIR, undefined);
  const uid = process.getuid();
  assert.deepEqual(w.calls(), [`bootout gui/${uid}/${WAKE}`, `bootstrap gui/${uid} ${w.plist(WAKE)}`]);
  assert.equal(w.eng(["wake", "install"]).status, 0);
  const baks = fs.readdirSync(w.la).filter((n) => n.startsWith(`${WAKE}.plist.bak-`));
  assert.equal(baks.length, 1);
  assert.match(baks[0], /\.bak-\d{8}$/);
});

test("wake install: a failed bootstrap exits 1 with launchctl's message", D, () => {
  const w = world();
  w.flag("bootstrap-rc", 5);
  const r = w.eng(["wake", "install"]);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /Bootstrap failed: 5/);
});

test("wake status and uninstall", D, () => {
  const w = world();
  let r = w.eng(["wake", "status"]);
  assert.equal(r.status, 0);
  assert.equal(r.stdout, "loaded\nlast wake: none\n");
  w.flag("print-rc", 113);
  assert.equal(w.eng(["wake", "status"]).stdout.split("\n")[0], "not loaded");
  // the newest schedule_due or schedule_ran event over every project database
  const d = w.db();
  d.prepare("INSERT INTO events(spec, job, ts, kind, detail) VALUES (NULL, NULL, ?, 'schedule_ran', '{}')").run(1700000000);
  d.prepare("INSERT INTO events(spec, job, ts, kind, detail) VALUES (NULL, NULL, ?, 'schedule_due', '{}')").run(1700003600);
  d.prepare("INSERT INTO events(spec, job, ts, kind, detail) VALUES (NULL, NULL, ?, 'other', '{}')").run(1800000000);
  d.close();
  const l = w.eng(["wake", "status"]).stdout.split("\n")[1];
  assert.match(l, /^last wake: \d{4}-\d\d-\d\d \d\d:\d\d$/);
  const t = new Date(1700003600 * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  assert.equal(l, `last wake: ${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())} ${pad(t.getHours())}:${pad(t.getMinutes())}`);
  assert.equal(w.eng(["wake", "uninstall"]).stdout, "not installed\n");
  w.eng(["wake", "install"]);
  r = w.eng(["wake", "uninstall"]);
  assert.equal(r.stdout, `removed ${w.plist(WAKE)}\n`);
  assert.equal(fs.existsSync(w.plist(WAKE)), false);
  assert.ok(w.calls(new RegExp(`^bootout gui/\\d+/${WAKE}$`)).length >= 2);
});

test("wake with an unknown argument is a usage error", () => {
  const w = world();
  const r = w.eng(["wake", "bogus"]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /usage: engine wake/);
});

test("migrate: five plists become five rows, five plist_remove steps done, odd one left", D, () => {
  const w = world({ odd: true });
  const r = w.eng(["schedule", "migrate"]);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  const lines = r.stdout.trim().split("\n");
  for (const j of JOBS.filter((x) => x.name !== "scout-poll")) assert.ok(lines.includes(`migrated ${j.label} -> ${j.name} (${j.rule})`), r.stdout);
  assert.ok(lines.includes("cannot migrate com.user.agent-board-scout-poll: no StartCalendarInterval"), r.stdout);
  assert.ok(lines.includes("ops digest: no launchd job (runs in the bridge's tick): nothing to migrate"));
  const d = w.db();
  const got = rows(d);
  assert.deepEqual(got.map((x) => x.name), ["dream", "discover-nightly", "scout-weekly", "scout-weekly-retry"].sort());
  for (const j of JOBS.filter((x) => x.name !== "scout-poll")) {
    const row = got.find((x) => x.name === j.name);
    assert.equal(row.rule, j.rule);
    assert.equal(row.command, j.command);
    assert.equal(row.cwd, "/h/agent-board");
    assert.deepEqual(row.env, ENVV);
    assert.equal(row.skip_if_weekly_usage, 85);
    assert.equal(d.prepare("SELECT state FROM steps WHERE key=?").get(`plist_remove:${j.label}`).state, "done");
    assert.equal(fs.existsSync(w.plist(j.label)), false);
    assert.equal(w.calls(new RegExp(`^bootout gui/\\d+/${j.label}$`)).length, 1);
  }
  assert.equal(fs.existsSync(w.plist("com.user.agent-board-scout-poll")), true);
  assert.equal(d.prepare("SELECT count(*) c FROM steps WHERE key='plist_remove:com.user.agent-board-scout-poll'").get().c, 0);
  d.close();
  ok();
});

test("migrate: a second run prints already migrated or not installed and changes nothing", D, () => {
  const w = world({ odd: true });
  w.eng(["schedule", "migrate"]);
  const before = w.calls(/^(?!print)/).length; // the heartbeat check is a print
  const d0 = w.db();
  const ev0 = d0.prepare("SELECT count(*) c FROM events").get().c;
  d0.close();
  const r = w.eng(["schedule", "migrate"]);
  assert.equal(r.status, 0, r.stderr);
  for (const j of JOBS.filter((x) => x.name !== "scout-poll")) assert.ok(r.stdout.includes(`not installed ${j.label}\n`), r.stdout);
  assert.equal(w.calls(/^(?!print)/).length, before);
  const d = w.db();
  assert.equal(d.prepare("SELECT count(*) c FROM events").get().c, ev0);
  d.close();
  ok();
});

test("migrate: exit 2 and no row when the heartbeat is not loaded; --dry-run skips the check", D, () => {
  const w = world();
  w.flag("print-rc", 113);
  const r = w.eng(["schedule", "migrate"]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /the wake heartbeat is not loaded: run tmux-ctl engine wake install first/);
  assert.equal(fs.existsSync(w.e.engineDir), false);
  const dry = w.eng(["schedule", "migrate", "--dry-run"]);
  assert.equal(dry.status, 0, dry.stderr);
  assert.equal(fs.existsSync(path.join(w.e.engineDir, "p.sqlite")), false);
  for (const j of JOBS) assert.equal(fs.existsSync(w.plist(j.label)), true);
});

test("migrate --dry-run prints the same lines prefixed 'would ' and writes nothing", D, () => {
  const w = world({ odd: true });
  const r = w.eng(["schedule", "migrate", "--dry-run"]);
  assert.equal(r.status, 0, r.stderr);
  const lines = r.stdout.trim().split("\n");
  assert.ok(lines.includes("would migrated com.user.agent-board-dream -> dream (daily 03:30)"), r.stdout);
  assert.ok(lines.every((l) => l.startsWith("would ")), r.stdout);
  assert.equal(fs.existsSync(path.join(w.e.engineDir, "p.sqlite")), false);
  assert.equal(w.calls().length, 0);
  for (const j of JOBS) assert.equal(fs.existsSync(w.plist(j.label)), true);
});

test("migrate: a kill between the plist_remove intent and the unlink keeps the row; the rerun runs once", D, async () => {
  const w = world();
  w.flag("kill-on-bootout");
  const r = w.eng(["schedule", "migrate"]);
  assert.notEqual(r.status, 0);
  const d = w.db();
  assert.ok(rows(d).length >= 1, "the row was written before the removal");
  const first = d.prepare("SELECT key, state FROM steps WHERE kind='plist_remove' AND state='intent'").all();
  assert.equal(first.length, 1);
  d.close();
  const label = first[0].key.slice("plist_remove:".length);
  assert.equal(fs.existsSync(w.plist(label)), true);
  const n0 = w.calls(new RegExp(`^bootout gui/\\d+/${label}$`)).length;
  assert.equal(n0, 1);
  // resume's reconcile (core.resume, as `engine start` and `engine wake` reach it) finds the plist still there and reruns the step once
  const core = require("../lib/engine/core");
  const eng = withEnv(w, () => core.start({ project: "p", repo: w.home, backend: require("../lib/engine/backend/fake").createBackend({ script: {} }), tmuxCtl: "true", session: "x", tickMs: 100 }));
  try { await withEnv(w, () => eng.resume()); } finally { eng.stop(); }
  assert.equal(fs.existsSync(w.plist(label)), false);
  assert.equal(w.calls(new RegExp(`^bootout gui/\\d+/${label}$`)).length, n0 + 1);
  // and a second migrate finishes the other labels, never touching this one again
  const r2 = w.eng(["schedule", "migrate"]);
  assert.equal(r2.status, 0, r2.stderr);
  assert.equal(w.calls(new RegExp(`^bootout gui/\\d+/${label}$`)).length, n0 + 1);
  assert.equal(JOBS.filter((j) => fs.existsSync(w.plist(j.label))).length, 0);
  const d3 = w.db();
  assert.equal(rows(d3).length, 5);
  d3.close();
  ok();
});

test("migrate: a plist whose row is identical prints already migrated and still removes it", D, () => {
  const w = world();
  assert.equal(w.eng(["schedule", "add", "dream", "--rule", "daily 03:30", "--", "tmux-ctl context dream --all"]).status, 0);
  const r = w.eng(["schedule", "migrate"]);
  assert.equal(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes("already migrated com.user.agent-board-dream\n"), r.stdout);
  assert.equal(fs.existsSync(w.plist("com.user.agent-board-dream")), false);
  ok();
});

test("migrate: a reinstalled plist is removed again and there is still one row", D, () => {
  const w = world();
  assert.equal(w.eng(["schedule", "migrate"]).status, 0);
  const j = JOBS[0];
  fs.writeFileSync(w.plist(j.label), launchd.plistXml({ Label: j.label, ProgramArguments: j.args, StartCalendarInterval: j.cal, WorkingDirectory: "/h/agent-board", EnvironmentVariables: ENVV }));
  const r = w.eng(["schedule", "migrate"]);
  assert.equal(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes(`already migrated ${j.label}\n`), r.stdout);
  assert.equal(fs.existsSync(w.plist(j.label)), false);
  assert.equal(w.calls(new RegExp(`^bootout gui/\\d+/${j.label}$`)).length, 2);
  const d = w.db();
  assert.equal(rows(d).filter((x) => x.name === j.name).length, 1);
  d.close();
  ok();
});

test("steps.CHECKS.plist_remove: done when the plist is gone and launchctl list lacks the label; unknown when launchctl fails", D, () => {
  const w = world();
  const label = JOBS[0].label;
  const row = { key: `plist_remove:${label}`, result: { label, plist: w.plist(label) } };
  withEnv(w, () => {
    assert.equal(steps.CHECKS.plist_remove({}, row), "not_done"); // plist present
    fs.rmSync(w.plist(label));
    assert.equal(steps.CHECKS.plist_remove({}, row), "done");
    w.flag("list-out", `PID\tStatus\tLabel\n-\t0\t${label}\n`);
    assert.equal(steps.CHECKS.plist_remove({}, row), "not_done"); // still loaded
    w.flag("list-out", "PID\tStatus\tLabel\n-\t0\tcom.other\n");
    assert.equal(steps.CHECKS.plist_remove({}, row), "done");
    w.flag("list-fail");
    assert.equal(steps.CHECKS.plist_remove({}, row), "unknown");
  });
});

test("core never parks a spec on plist_remove", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../lib/engine/core.js"), "utf8");
  assert.match(src, /NEVER_PARK = \[[^\]]*"plist_remove"/);
});

test("real state, read-only: schedule migrate --dry-run over the real LaunchAgents with a stub that fails all but list", D, () => {
  const e = tmpEnv();
  cleanups.push(() => e.restore());
  const stub = path.join(e.root, "fail-launchctl");
  fs.writeFileSync(stub, "#!/bin/sh\n[ \"$1\" = list ] && exit 0\nexit 1\n", { mode: 0o755 });
  const before = snap(REAL_LA);
  const env = { ...process.env, TC_ENGINE_DIR: e.engineDir, TC_STATE: e.state, TC_PROJECT: "p", AS_LAUNCHCTL: stub };
  const r = cp.spawnSync("node", [ENGINE, "schedule", "migrate", "--dry-run"], { env, encoding: "utf8", timeout: 60000 });
  console.log(r.stdout.trimEnd());
  assert.equal(r.status, 0, r.stderr);
  const known = [
    /^would migrated com\.user\.agent-board-[a-z-]+ -> [a-z-]+ \((daily \d\d:\d\d|weekly [A-Z][a-z]{2} \d\d:\d\d)\)$/,
    /^would not installed com\.user\.agent-board-[a-z-]+$/,
    /^would already migrated com\.user\.agent-board-[a-z-]+$/,
    /^would cannot migrate com\.user\.agent-board-[a-z-]+: .+$/,
    /^would ops digest: no launchd job \(runs in the bridge's tick\): nothing to migrate$/,
  ];
  for (const l of r.stdout.trim().split("\n")) assert.ok(known.some((re) => re.test(l)), `unknown line: ${l}`);
  assert.deepEqual(snap(REAL_LA), before);
  assert.equal(fs.existsSync(path.join(e.engineDir, "p.sqlite")), false);
});

test("leak check: the real LaunchAgents and the real engine dir are unchanged", () => {
  assert.deepEqual(snap(REAL_LA), LA_BEFORE);
  assert.equal(fs.existsSync(path.join(REAL_LA, `${WAKE}.plist`)), Object.prototype.hasOwnProperty.call(LA_BEFORE, `${WAKE}.plist`));
  assert.deepEqual(snap(REAL_ENGINE, true), ENG_BEFORE);
});
