"use strict";
// Approval holds (spec 13): the rules, the matcher and the PreToolUse decision. Loads ./db (node:sqlite) only after a rule matched.
const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const crypto = require("node:crypto");
const policy = require("./policy");

const GIT = "(?:^|[;&|(`'\"]|\\$\\(|\\b(?:env|command|exec|nohup|time|xargs)\\s+(?:\\S+=\\S*\\s+)*|\\s)(?:\\S*/)?git"
  + "(?:\\s+(?:-C\\s+\\S+|-c\\s+\\S+|--[a-z-]+(?:=\\S+)?|-[pP]))*\\s+";
const LEAD = "(?:^|[;&|(`'\"\\s])(?:\\S*/)?";

const DEFAULT_HOLDS = [
  { id: "git_push", tool: "Bash", pattern: GIT + "push\\b", outside_worktree: false },
  { id: "git_reset_hard", tool: "Bash", pattern: GIT + "reset\\b(?=[^;&|]*\\s--hard\\b)", outside_worktree: false },
  { id: "git_branch_force_delete", tool: "Bash", outside_worktree: false,
    pattern: GIT + "branch\\b(?=[^;&|]*\\s(?:-[a-zA-Z]*D[a-zA-Z]*|--delete\\s+--force|--force\\s+--delete|-d\\s+--force|-f\\s+-d|-df|-fd)(?:\\s|$))" },
  { id: "git_clean", tool: "Bash", pattern: GIT + "clean\\b", outside_worktree: false },
  { id: "rm_recursive_outside", tool: "Bash", pattern: LEAD + "rm\\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\\b", outside_worktree: true },
  { id: "write_outside", tool: "Write|Edit|MultiEdit|NotebookEdit", pattern: ".*", outside_worktree: true },
  { id: "pr_merge", tool: "Bash", pattern: LEAD + "(?:glab\\s+mr\\s+merge|gh\\s+pr\\s+merge)\\b", outside_worktree: false },
];

function compile(rule, id) {
  return { id, tool: new RegExp(`^(?:${rule.tool})$`), pattern: new RegExp(rule.pattern), outside: !!rule.outside_worktree };
}

function rulesFor(config) {
  const out = DEFAULT_HOLDS.map((r) => compile(r, r.id));
  ((config && config.holds) || []).forEach((r, i) => {
    try { out.push(compile(r, `config:${i}`)); } catch (e) { throw new Error(`bad hold rule ${i}: ${e.message}`); }
  });
  return out;
}

function realpathDeep(p) {
  let rest = [];
  let cur = path.resolve(p);
  for (;;) {
    try { return path.join(fs.realpathSync(cur), ...rest); } catch (e) {
      const up = path.dirname(cur);
      if (up === cur) return path.join(cur, ...rest);
      rest = [path.basename(cur), ...rest];
      cur = up;
    }
  }
}

const isOutside = (p, worktree) => {
  const wt = realpathDeep(worktree);
  const r = realpathDeep(p);
  return !(r === wt || r.startsWith(wt + path.sep));
};

const callPath = (input) => (input && (input.file_path || input.notebook_path || input.path)) || null;

const unquote = (w) => (w.length >= 2 && /^["']/.test(w) && w[w.length - 1] === w[0] ? w.slice(1, -1) : w);

function bashWords(command, m) {
  let tail = command.slice(m.index + m[0].length);
  const cut = tail.search(/;|&&|\|\||\||\n/);
  if (cut >= 0) tail = tail.slice(0, cut);
  return tail.split(/\s+/).filter((w) => w && !w.startsWith("-")).map(unquote).map((w) => {
    if (w === "~" || w.startsWith("~/")) return path.join(process.env.HOME || "", w.slice(1));
    return w;
  });
}

// The first rule the call matches, or null.
function match(rules, { tool_name, tool_input, cwd }, worktree) {
  const input = tool_input || {};
  const base = cwd || worktree;
  for (const r of rules) {
    if (!r.tool.test(tool_name)) continue;
    if (tool_name === "Bash") {
      const command = typeof input.command === "string" ? input.command : "";
      const m = r.pattern.exec(command);
      if (!m) continue;
      if (r.outside && !bashWords(command, m).some((w) => isOutside(path.resolve(base, w), worktree))) continue;
      return r;
    }
    const p = callPath(input);
    if (p === null) continue;
    const abs = path.resolve(base, p);
    if (!r.pattern.test(abs) && !r.pattern.test(path.relative(worktree, abs))) continue;
    if (r.outside && !isOutside(abs, worktree)) continue;
    return r;
  }
  return null;
}

function canon(v) {
  if (Array.isArray(v)) return v.map(canon);
  if (v && typeof v === "object") return Object.fromEntries(Object.keys(v).sort().map((k) => [k, canon(v[k])]));
  return v;
}
const canonical = (input) => { const { description, ...rest } = input || {}; return JSON.stringify(canon(rest)); };
const callHash = (tool, input) => crypto.createHash("sha256").update(`${tool}\n${canonical(input)}`).digest("hex");

function question(tool, input) {
  const i = input || {};
  const p = callPath(i);
  const what = tool === "Bash" && typeof i.command === "string" ? i.command : p !== null ? p : canonical(i);
  return `${tool}: ${what}`.slice(0, 300);
}

function configFor(worktree) {
  try {
    const out = cp.execFileSync("git", ["-C", worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    return policy.loadConfig(path.dirname(out));
  } catch { return {}; }
}

// `handle` is an open database or null (then it is opened here, after a rule matched, from env).
function decide(handle, hookInput, env, now) {
  if (!env.ENGINE_JOB) return { decision: "none" };
  const worktree = env.ENGINE_WORKTREE || (hookInput && hookInput.cwd) || process.cwd();
  const rule = match(rulesFor(configFor(worktree)), hookInput, worktree);
  if (!rule) return { decision: "none" };
  let d = handle;
  try {
    const t = now !== undefined ? now : Date.now() / 1000;
    const db = require("./db");
    if (!d) {
      process.env.TC_ENGINE_DIR = env.ENGINE_DIR;
      d = db.open(env.ENGINE_PROJECT);
    }
    const tool = hookInput.tool_name;
    const hash = callHash(tool, hookInput.tool_input);
    return db.tx(d, () => {
      const job = d.prepare("SELECT spec FROM jobs WHERE id=?").get(env.ENGINE_JOB);
      const spec = job ? job.spec : null;
      const pass = spec === null ? undefined : d.prepare(
        "SELECT * FROM holds WHERE call_hash=? AND spec=? AND used_at IS NULL AND expires_at>? ORDER BY created_at LIMIT 1").get(hash, spec, t);
      if (pass) {
        const row = db.put(d, "holds", { ...pass, used_at: t });
        db.event(d, { spec, job: env.ENGINE_JOB, kind: "hold_pass_used", ts: t, rows: [{ table: "holds", row }] });
        return { decision: "allow", hold_id: pass.hold_id };
      }
      const hold_id = crypto.randomUUID();
      require("./inbox").insert(d, { source: "approval", source_id: hold_id, spec, job: env.ENGINE_JOB, kind: "hold",
        payload: { hold_id, tool, input: hookInput.tool_input, call_hash: hash, rule: rule.id, session_id: hookInput.session_id, cwd: hookInput.cwd } }, t);
      return { decision: "deny", hold_id,
        reason: `held for approval ${hold_id}: report status blocked with the concern "awaiting approval ${hold_id}", then stop` };
    });
  } catch (e) {
    e.matched = true;
    throw e;
  } finally {
    if (d && !handle) d.close();
  }
}

module.exports = { DEFAULT_HOLDS, rulesFor, match, callHash, question, decide };
