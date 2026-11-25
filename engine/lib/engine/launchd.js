"use strict";
// The wake heartbeat LaunchAgent (`engine wake install|status|uninstall`) and `engine schedule migrate` (spec 14).
// Seams, as board/scout_schedule.py: HOME (plists under $HOME/Library/LaunchAgents), AS_LAUNCHCTL (split on spaces),
// AS_PLUTIL (default plutil), AS_BIN_DIR (fallback tmux-ctl directory). Off macOS every command prints `macOS only`, exit 2.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");

const WAKE_LABEL = "com.user.agent-board-engine-wake";
const TIMEOUT = 30000;
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// (label, schedule name) of the plists the five earlier agent-board jobs installed (A11)
const MIGRATE = [
  ["com.user.agent-board-dream", "dream"],
  ["com.user.agent-board-discover", "discover-nightly"],
  ["com.user.agent-board-scout-poll", "scout-poll"],
  ["com.user.agent-board-scout-weekly", "scout-weekly"],
  ["com.user.agent-board-scout-weekly-retry", "scout-weekly-retry"],
];
const DIGEST_LINE = "ops digest: no launchd job (runs in the bridge's tick): nothing to migrate";
const MAC_ONLY = "macOS only";

const home = () => process.env.HOME || os.homedir();
const plistPath = (label) => path.join(home(), "Library", "LaunchAgents", `${label}.plist`);
const split = (v, dflt) => (v || dflt).split(/\s+/).filter(Boolean);
const uid = () => process.getuid();

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function xmlOf(v, ind) {
  const pad = "\t".repeat(ind);
  if (typeof v === "string") return `${pad}<string>${esc(v)}</string>\n`;
  if (typeof v === "boolean") return `${pad}<${v}/>\n`;
  if (typeof v === "number" && Number.isInteger(v)) return `${pad}<integer>${v}</integer>\n`;
  if (Array.isArray(v)) return `${pad}<array>\n${v.map((x) => xmlOf(x, ind + 1)).join("")}${pad}</array>\n`;
  if (v && typeof v === "object") {
    return `${pad}<dict>\n${Object.entries(v).map(([k, x]) => `${pad}\t<key>${esc(k)}</key>\n${xmlOf(x, ind + 1)}`).join("")}${pad}</dict>\n`;
  }
  throw new Error(`plistXml: cannot write ${JSON.stringify(v)}`);
}
function plistXml(obj) {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n${xmlOf(obj, 0)}</plist>\n`;
}

function readPlist(file) {
  const [cmd, ...a] = split(process.env.AS_PLUTIL, "plutil");
  const r = cp.spawnSync(cmd, [...a, "-convert", "json", "-o", "-", file], { encoding: "utf8", timeout: TIMEOUT });
  if (r.error || r.status !== 0) throw new Error(`cannot read ${file}: ${(r.stderr || (r.error && r.error.message) || "").trim()}`);
  return JSON.parse(r.stdout);
}

function launchctl(args) {
  const [cmd, ...a] = split(process.env.AS_LAUNCHCTL, "launchctl");
  const r = cp.spawnSync(cmd, [...a, ...args], { encoding: "utf8", timeout: TIMEOUT });
  if (r.error) return { status: 127, stdout: "", stderr: String(r.error.message) };
  return { status: r.status === null ? 1 : r.status, stdout: r.stdout || "", stderr: r.stderr || "" };
}

const labelLoaded = (label) => launchctl(["print", `gui/${uid()}/${label}`]).status === 0;

const executable = (p) => { try { fs.accessSync(p, fs.constants.X_OK); return fs.statSync(p).isFile(); } catch (_) { return false; } };
const checkoutRoot = () => path.resolve(__dirname, "../../..");
function tmuxCtlPath() {
  const mine = path.join(home(), ".local", "bin", "tmux-ctl");
  if (executable(mine)) return mine;
  return path.join(process.env.AS_BIN_DIR || path.join(checkoutRoot(), "bin"), "tmux-ctl");
}

function wakePlist() {
  const env = { PATH: `${home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`, LANG: process.env.LANG || "en_US.UTF-8" };
  if (process.env.TC_STATE) env.TC_STATE = process.env.TC_STATE;
  else if (process.env.TMPDIR) env.TMPDIR = process.env.TMPDIR;
  if (process.env.TC_ENGINE_DIR) env.TC_ENGINE_DIR = process.env.TC_ENGINE_DIR;
  return {
    Label: WAKE_LABEL, ProgramArguments: [tmuxCtlPath(), "engine", "wake"], StartInterval: 900, RunAtLoad: true,
    WorkingDirectory: checkoutRoot(), EnvironmentVariables: env,
  };
}

const macOnly = (io) => { io.err(`${MAC_ONLY}\n`); return 2; };
const isMac = () => process.platform === "darwin";

function install(io) {
  if (!isMac()) return macOnly(io);
  const file = plistPath(WAKE_LABEL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (fs.existsSync(file)) {
    const d = new Date();
    const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
    const bak = `${file}.bak-${stamp}`;
    fs.copyFileSync(file, bak);
    io.out(`backed up the old plist to ${bak}`);
  }
  fs.writeFileSync(file, plistXml(wakePlist()));
  launchctl(["bootout", `gui/${uid()}/${WAKE_LABEL}`]); // not loaded yet is fine
  const r = launchctl(["bootstrap", `gui/${uid()}`, file]);
  if (r.status !== 0) { io.err(`launchctl bootstrap failed for ${WAKE_LABEL}: ${(r.stderr || r.stdout).trim()}\n`); return 1; }
  io.out(`installed ${file}`);
  return 0;
}

const pad = (n) => String(n).padStart(2, "0");
function status(io) {
  if (!isMac()) return macOnly(io);
  io.out(labelLoaded(WAKE_LABEL) ? "loaded" : "not loaded");
  const paths = require("./paths");
  const dbm = require("./db");
  let best = null;
  let files = [];
  try { files = fs.readdirSync(paths.engineDir()).filter((f) => f.endsWith(".sqlite")); } catch (_) { /* no engine dir */ }
  for (const f of files) {
    let d = null;
    try {
      d = dbm.open(path.basename(f, ".sqlite"));
      const m = d.prepare("SELECT max(ts) m FROM events WHERE kind IN ('schedule_due','schedule_ran')").get().m;
      if (m !== null && m !== undefined && (best === null || m > best)) best = m;
    } catch (_) { /* unreadable project */ } finally { if (d) { try { d.close(); } catch (_) { /* closed */ } } }
  }
  if (best === null) io.out("last wake: none");
  else {
    const t = new Date(best * 1000);
    io.out(`last wake: ${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())} ${pad(t.getHours())}:${pad(t.getMinutes())}`);
  }
  return 0;
}

function uninstall(io) {
  if (!isMac()) return macOnly(io);
  const file = plistPath(WAKE_LABEL);
  if (!fs.existsSync(file)) { io.out("not installed"); return 0; }
  launchctl(["bootout", `gui/${uid()}/${WAKE_LABEL}`]);
  fs.rmSync(file, { force: true });
  io.out(`removed ${file}`);
  return 0;
}

// ---- migrate ---------------------------------------------------------------------------------------------------

// `daily HH:MM` / `weekly Dow HH:MM` from a StartCalendarInterval dict, or {why}.
function ruleOf(cal) {
  if (!cal || typeof cal !== "object" || Array.isArray(cal)) return { why: "no StartCalendarInterval" };
  const keys = Object.keys(cal);
  if (keys.some((k) => !["Hour", "Minute", "Weekday"].includes(k)) || !Number.isInteger(cal.Hour) || !Number.isInteger(cal.Minute)) {
    return { why: `unsupported StartCalendarInterval ${JSON.stringify(cal)}` };
  }
  const hm = `${pad(cal.Hour)}:${pad(cal.Minute)}`;
  if (cal.Weekday === undefined) return { rule: `daily ${hm}` };
  if (!Number.isInteger(cal.Weekday) || cal.Weekday < 0 || cal.Weekday > 7) return { why: `unsupported Weekday ${JSON.stringify(cal.Weekday)}` };
  return { rule: `weekly ${DAYS[cal.Weekday % 7]} ${hm}` };
}

// The plist_remove step's action: unload, then unlink.
function removeAct(label, file) {
  launchctl(["bootout", `gui/${uid()}/${label}`]);
  fs.rmSync(file, { force: true });
  return { label, plist: file };
}
const stepDesc = (label, file) => ({ key: `plist_remove:${label}`, spec: null, kind: "plist_remove", facts: { label, plist: file } });

// Reruns a plist_remove step reconcile found not done. -> true when it finished.
function rerunPlistRemove(db, row) {
  const steps = require("./steps");
  const f = row.result || {};
  if (!f.label || !f.plist) return false;
  steps.run(db, { ...stepDesc(f.label, f.plist) }, () => removeAct(f.label, f.plist));
  return true;
}

async function migrate({ dryRun, project, io }) {
  if (!isMac()) return macOnly(io);
  const pre = dryRun ? "would " : "";
  const say = (s) => io.out(pre + s);
  let db = null;
  let schedule = null;
  let steps = null;
  if (!dryRun) {
    if (!labelLoaded(WAKE_LABEL)) {
      io.err("the wake heartbeat is not loaded: run tmux-ctl engine wake install first\n");
      return 2;
    }
    schedule = require("./schedule");
    steps = require("./steps");
    db = require("./db").open(project);
  }
  try {
    for (const [label, name] of MIGRATE) {
      const file = plistPath(label);
      if (!fs.existsSync(file)) { say(`not installed ${label}`); continue; }
      let p;
      try { p = readPlist(file); } catch (e) { say(`cannot migrate ${label}: ${e.message}`); continue; }
      const r = ruleOf(p.StartCalendarInterval);
      const args = Array.isArray(p.ProgramArguments) ? p.ProgramArguments.map(String) : [];
      if (r.why || !args.length) { say(`cannot migrate ${label}: ${r.why || "no ProgramArguments"}`); continue; }
      if (dryRun) { say(`migrated ${label} -> ${name} (${r.rule})`); continue; }
      const command = schedule.shellJoin(["tmux-ctl", ...args.slice(1)]);
      const cwd = typeof p.WorkingDirectory === "string" ? p.WorkingDirectory : undefined;
      const env = p.EnvironmentVariables && typeof p.EnvironmentVariables === "object" ? p.EnvironmentVariables : {};
      let added;
      try { added = schedule.add(db, { name, rule: r.rule, command, cwd, env }, Date.now() / 1000); } catch (e) {
        say(`cannot migrate ${label}: ${String(e.message).split("\n")[0]}`);
        continue;
      }
      // the row is written before the plist goes: a kill between the intent and the unlink loses nothing
      steps.run(db, stepDesc(label, file), () => removeAct(label, file));
      say(added.status === "unchanged" ? `already migrated ${label}` : `migrated ${label} -> ${name} (${r.rule})`);
    }
    say(DIGEST_LINE);
    return 0;
  } finally { if (db) db.close(); }
}

module.exports = { WAKE_LABEL, plistXml, readPlist, launchctl, labelLoaded, install, status, uninstall, migrate, rerunPlistRemove, ruleOf };
