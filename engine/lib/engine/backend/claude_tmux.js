"use strict";
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const report = require("../report.js");
const paths = require("../paths.js");

// Reads every <dir>/*.json agent-status file. A record needs a string `pane` and `state`; anything else
// (unparsable, partial, wrong shape) is counted in `skipped`. Read-only.
function readStatusFiles(dir) {
  const records = [];
  let skipped = 0;
  let names;
  try { names = fs.readdirSync(dir).filter((f) => f.endsWith(".json")); } catch { return { records, skipped }; }
  for (const f of names) {
    let o;
    try { o = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")); } catch { skipped += 1; continue; }
    if (o && typeof o === "object" && typeof o.pane === "string" && typeof o.state === "string") records.push(o);
    else skipped += 1;
  }
  return { records, skipped };
}

// Window name <spec slug>·<kind><task>, from a job id `<slug>:<kind><task>:<attempt>` (spec A2).
const windowFor = (job) => job.window || (() => { const p = String(job.id).split(":"); return `${p[0]}·${p[1]}`; })();
const logName = (id) => {
  const m = /^(.*):(\d+)$/.exec(id);
  return (m ? `${m[1]}-${m[2]}` : id).replace(/[:/]/g, "_") + ".log";
};

function createBackend(opts) {
  const { session, tmuxCtl, statusDir, tmuxArgs = [] } = opts;
  const tmuxBin = opts.tmuxBin || process.env.TC_TMUX_BIN || "tmux";
  const resumeWaitMs = opts.resumeWaitMs == null ? 5000 : opts.resumeWaitMs;
  const baseEnv = () => ({ ...process.env, ...(opts.env || {}) });
  const entries = []; // {handle, job, worktree, minMtime, started, reportSent, lastKey, gone}
  let resumes = 0;

  const tmux = (args, env) => cp.spawnSync(tmuxBin, [...tmuxArgs, ...args], { env: env || baseEnv(), encoding: "utf8" });

  function ctlEnv() {
    const env = baseEnv();
    env.TC_SESSION = session;
    if (tmuxArgs.length) {
      const a = [];
      for (let i = 0; i < tmuxArgs.length; i++) { if (tmuxArgs[i] === "-f") i += 1; else a.push(tmuxArgs[i]); }
      env.TMUX_DASH_TMUX_ARGS = a.join(" ");
      if (!env.TMUX) {
        const sock = tmux(["display", "-p", "#{socket_path}"], env).stdout.trim();
        env.TMUX = `${sock},0,0`;
      }
    }
    return env;
  }

  function launch(window, job, extra, briefPath) {
    const args = ["agent", window, "--dir", job.worktree, ...extra,
      "--model", job.model, "--effort", job.effort, "--brief", briefPath];
    const r = cp.spawnSync(tmuxCtl, args, { env: ctlEnv(), encoding: "utf8" });
    if (r.status !== 0) throw new Error(`tmux-ctl agent failed (${r.status}): ${(r.stderr || r.stdout || "").trim()}`);
    const l = tmux(["list-panes", "-s", "-t", `=${session}:`, "-F", "#{window_name} #{pane_id}"]);
    const row = (l.stdout || "").split("\n").map((x) => x.split(" ")).find((x) => x[0] === window);
    if (!row) throw new Error(`window ${window} not found after start`);
    return row[1];
  }

  function register(job, window, pane, minMtime) {
    const handle = { job: job.id, window, pane };
    entries.push({ handle, job, worktree: job.worktree, minMtime: minMtime || 0, started: false, reportSent: false, lastKey: null, gone: false });
    return handle;
  }

  async function start(job) {
    return register(job, windowFor(job), launch(windowFor(job), job, [], job.brief));
  }

  const entryOf = (handle) => entries.find((e) => e.handle.pane === handle.pane);

  function latestRecord(pane) {
    const { records } = readStatusFiles(statusDir);
    let best = null;
    for (const r of records) if (r.pane === pane && (!best || (r.updatedAt || 0) >= (best.updatedAt || 0))) best = r;
    return best;
  }

  async function close(handle) {
    const e = entryOf(handle);
    const id = e ? e.job.id : handle.job;
    const cap = tmux(["capture-pane", "-p", "-J", "-t", handle.pane, "-S", "-200"]);
    if (cap.status === 0 && e) {
      const dir = path.join(paths.workspace(e.worktree), "logs");
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, logName(id)), cap.stdout);
    }
    tmux(["kill-pane", "-t", handle.pane]);
  }

  async function resume(handle, text) {
    const e = entryOf(handle);
    if (!e) throw new Error(`unknown handle ${handle.pane}`);
    let sid = handle.session_id;
    const end = Date.now() + resumeWaitMs;
    for (;;) {
      if (!sid) { const r = latestRecord(handle.pane); sid = r && r.session_id; }
      if (sid || Date.now() >= end) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!sid) throw new Error(`no session id for ${handle.pane}: cannot resume`);
    resumes += 1;
    const dir = path.join(paths.workspace(e.worktree), "briefs");
    fs.mkdirSync(dir, { recursive: true });
    const briefPath = path.join(dir, `${logName(e.job.id).replace(/\.log$/, "")}-resume${resumes}.md`);
    fs.writeFileSync(briefPath, text);
    const window = `${e.handle.window}-r${resumes}`;
    const pane = launch(window, e.job, ["--resume", sid], briefPath);
    const next = register(e.job, window, pane, Date.now());
    next.session_id = sid;
    return next;
  }

  function poll() {
    const out = [];
    const live = entries.filter((e) => !e.gone);
    if (!live.length) return out;
    const { records } = readStatusFiles(statusDir);
    const lp = tmux(["list-panes", "-a", "-F", "#{pane_id}"]);
    const panes = lp.status === 0 ? new Set(lp.stdout.split("\n").filter(Boolean)) : null;
    for (const e of live) {
      const h = e.handle;
      if (!e.started) { e.started = true; out.push({ handle: h, type: "started" }); }
      let best = null;
      for (const r of records) if (r.pane === h.pane && (!best || (r.updatedAt || 0) >= (best.updatedAt || 0))) best = r;
      if (best) {
        if (best.session_id) h.session_id = best.session_id;
        const key = `${best.state}|${best.updatedAt}`;
        if (key !== e.lastKey) {
          e.lastKey = key;
          out.push({ handle: h, type: "status", state: best.state, updatedAt: best.updatedAt,
            tool: best.tool == null ? null : best.tool, lastToolAt: best.lastToolAt == null ? null : best.lastToolAt,
            turnStartedAt: best.turnStartedAt == null ? null : best.turnStartedAt });
        }
      }
      if (!e.reportSent && e.job.report) {
        try {
          const st = fs.statSync(e.job.report);
          if (st.mtimeMs >= e.minMtime && report.parse(fs.readFileSync(e.job.report, "utf8"), e.job.kind)) {
            e.reportSent = true;
            out.push({ handle: h, type: "report", path: e.job.report });
          }
        } catch { /* no report yet */ }
      }
      if (panes && !panes.has(h.pane)) { e.gone = true; out.push({ handle: h, type: "gone" }); }
    }
    return out;
  }

  return { start, close, resume, poll };
}

module.exports = { createBackend, readStatusFiles };
