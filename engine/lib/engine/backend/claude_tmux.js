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

// The tokens a session used since `since` (seconds): input + output + cache creation of the assistant rows of
// <root>/*/<sessionId>.jsonl, once per message id (a transcript repeats one message on several lines), without the
// `<synthetic>` rows. Cache reads are not counted. Read-only; {tokens: null, reason} when it cannot be measured.
function transcriptUsage(root, sessionId, since) {
  if (!sessionId) return { tokens: null, reason: "no session id" };
  let file = null;
  try {
    for (const d of fs.readdirSync(root)) {
      const p = path.join(root, d, `${sessionId}.jsonl`);
      if (fs.existsSync(p)) { file = p; break; }
    }
  } catch { /* no projects directory */ }
  if (!file) return { tokens: null, reason: `no transcript for session ${sessionId}` };
  let text;
  try { text = fs.readFileSync(file, "utf8"); } catch (e) { return { tokens: null, reason: `transcript unreadable: ${e.code || e.message}` }; }
  const perId = new Map();
  let anon = 0;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; }
    const m = o && o.message;
    if (!m || !m.usage || m.model === "<synthetic>" || (o.type && o.type !== "assistant" && m.role !== "assistant")) continue;
    if (since !== undefined && since !== null) {
      const ts = Date.parse(o.timestamp);
      if (!(ts / 1000 >= since)) continue;
    }
    const u = m.usage;
    const n = (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_creation_input_tokens || 0);
    perId.set(m.id || `anon${anon++}`, n); // the same id again is the same message
  }
  if (!perId.size) return { tokens: null, reason: `no usage rows in the transcript of session ${sessionId}` };
  let sum = 0;
  for (const n of perId.values()) sum += n;
  return { tokens: sum };
}

const USAGE_KINDS = new Set(["5-hour", "weekly", "session"]);

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
    const env = ctlEnv();
    env.ENGINE_JOB = String(job.id);
    env.ENGINE_PROJECT = opts.project || "";
    env.ENGINE_DIR = paths.engineDir();
    env.ENGINE_WORKTREE = path.resolve(job.worktree);
    const r = cp.spawnSync(tmuxCtl, args, { env, encoding: "utf8" });
    if (r.status !== 0) throw new Error(`tmux-ctl agent failed (${r.status}): ${(r.stderr || r.stdout || "").trim()}`);
    const l = tmux(["list-panes", "-s", "-t", `=${session}:`, "-F", "#{window_name} #{pane_id}"]);
    const row = (l.stdout || "").split("\n").map((x) => x.split(" ")).find((x) => x[0] === window);
    if (!row) throw new Error(`window ${window} not found after start`);
    return row[1];
  }

  function register(job, window, pane, minMtime) {
    const handle = { job: job.id, window, pane };
    entries.push({ handle, job, worktree: job.worktree, minMtime: minMtime || 0, started: false, reportSent: false, limitSent: false, lastKey: null, gone: false });
    return handle;
  }

  async function start(job) {
    return register(job, windowFor(job), launch(windowFor(job), job, [], job.brief));
  }

  const entryOf = (handle) => entries.find((e) => e.handle.pane === handle.pane);

  // After an engine restart: watch a window an earlier process started. `job` is the jobs row plus `worktree`,
  // `handle` its window, pane and session id. True when that pane is still open under that window name (tmux reuses
  // pane ids after a server restart, so the pane id alone is not enough); the job is then polled and closed like one
  // this process started, without a second `started` event. False when it is gone.
  async function adopt(job, handle) {
    if (!handle || !handle.pane) return false;
    const lp = tmux(["list-panes", "-a", "-F", "#{pane_id}\t#{window_name}"]);
    if (lp.status !== 0) return false;
    const row = lp.stdout.split("\n").map((l) => l.split("\t")).find((x) => x[0] === handle.pane);
    if (!row || (handle.window && row[1] !== handle.window)) return false;
    const have = entries.find((e) => e.handle.pane === handle.pane && !e.gone);
    if (have) return true;
    const h = register(job, row[1], handle.pane);
    if (handle.session_id) h.session_id = handle.session_id;
    entryOf(h).started = true;
    return true;
  }

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

  async function resume(handle, text, job) {
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
    const rjob = job ? { ...e.job, ...job, worktree: e.worktree } : e.job;
    const pane = launch(window, rjob, ["--resume", sid], briefPath);
    const next = register(rjob, window, pane, Date.now());
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
      // Claude's limit message is only in the pane text: look at ready or unknown handles, once per handle.
      if (!e.limitSent && (!best || best.state === "ready")) {
        const cap = tmux(["capture-pane", "-p", "-J", "-t", h.pane, "-S", "-40"]);
        const m = cap.status === 0 ? /^\s*You've hit your (\S+(?: \S+)?) limit/m.exec(cap.stdout) : null;
        if (m) {
          e.limitSent = true;
          out.push({ handle: h, type: "status", state: USAGE_KINDS.has(m[1]) ? "usage_limit" : "model_limit",
            updatedAt: Math.floor(Date.now() / 1000), tool: null, lastToolAt: null, turnStartedAt: null });
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

  function usage(handle, { since } = {}) {
    const root = opts.transcriptRoot || path.join(process.env.CLAUDE_CONFIG_DIR || path.join(process.env.HOME || "", ".claude"), "projects");
    return transcriptUsage(root, handle && handle.session_id, since);
  }

  return { start, close, resume, poll, adopt, usage };
}

module.exports = { createBackend, readStatusFiles, transcriptUsage };
