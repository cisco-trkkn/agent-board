"use strict";
const fs = require("node:fs");
const path = require("node:path");

// Scripted backend for tests. script["<kind><task>"] = steps:
//   {status, tool?, at}  {report: text, at}  {gone: true, at}  {hang: true, at}
// `at` is seconds after start; poll() returns events due by opts.now().
function createBackend(opts = {}) {
  const script = opts.script || {};
  const now = opts.now || (() => Date.now() / 1000);
  const reportDir = opts.reportDir || ".";
  const calls = [];
  const jobs = new Map(); // job id -> {reportPath}
  const pending = []; // {due, order, make}
  let n = 0;
  let order = 0;

  const queue = (due, make) => pending.push({ due, order: order++, make });
  const reportPath = (job) => job.report || path.join(reportDir, `${job.id}.md`);

  function handleFor(job, window) {
    n += 1;
    return { job: job.id, window: window || job.window || job.id, pane: `%fake${n}`, session_id: `fake-sess-${n}` };
  }

  async function start(job) {
    const handle = handleFor(job);
    calls.push({ method: "start", job, handle });
    const rp = reportPath(job);
    jobs.set(job.id, { reportPath: rp });
    const t0 = now();
    queue(t0, () => ({ handle, type: "started" }));
    const steps = script[`${job.kind}${job.task == null ? "" : job.task}`] || [];
    for (const s of steps) {
      const due = t0 + (s.at || 0);
      if (s.report !== undefined) {
        queue(due, () => {
          fs.mkdirSync(path.dirname(rp), { recursive: true });
          fs.writeFileSync(rp, s.report);
          return { handle, type: "report", path: rp };
        });
      } else if (s.gone) {
        queue(due, () => ({ handle, type: "gone" }));
      } else if (s.hang) {
        queue(due, () => ({ handle, type: "status", state: "busy", updatedAt: due, tool: null, lastToolAt: null, turnStartedAt: t0 }));
      } else if (s.status) {
        queue(due, () => ({
          handle, type: "status", state: s.status, updatedAt: due,
          tool: s.tool === undefined ? null : s.tool, lastToolAt: s.tool ? due : null, turnStartedAt: t0,
        }));
      }
    }
    return handle;
  }

  async function close(handle) {
    calls.push({ method: "close", handle });
    queue(now(), () => ({ handle, type: "gone" }));
  }

  async function resume(handle, text) {
    calls.push({ method: "resume", handle, text });
    return handleFor({ id: handle.job }, handle.window);
  }

  function poll() {
    const t = now();
    const due = pending.filter((p) => p.due <= t).sort((a, b) => a.due - b.due || a.order - b.order);
    for (const p of due) pending.splice(pending.indexOf(p), 1);
    return due.map((p) => p.make());
  }

  return { start, close, resume, poll, calls };
}

module.exports = { createBackend };
