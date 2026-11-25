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
  { id: "rm_recursive_outside", tool: "Bash", pattern: LEAD + "rm\\s+(?:(?:-[a-zA-Z]+|--[a-z-]+)\\s+)*(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?=\\s|$)", outside_worktree: true },
  { id: "write_outside", tool: "Write|Edit|MultiEdit|NotebookEdit", pattern: ".*", outside_worktree: true },
  { id: "pr_merge", tool: "Bash", pattern: LEAD + "(?:glab\\s+mr\\s+merge|gh\\s+pr\\s+merge)\\b", outside_worktree: false },
];

function compile(rule, id) {
  return { id, tool: new RegExp(`^(?:${rule.tool})$`), pattern: new RegExp(rule.pattern), outside: !!rule.outside_worktree };
}

// The defaults, then the config rules, then the protected set of the improvement loop (`repo`'s protected.txt; none
// without a repo or without the file).
function rulesFor(config, repo) {
  const out = DEFAULT_HOLDS.map((r) => compile(r, r.id));
  ((config && config.holds) || []).forEach((r, i) => {
    try { out.push(compile(r, `config:${i}`)); } catch (e) { throw new Error(`bad hold rule ${i}: ${e.message}`); }
  });
  if (repo) {
    require("../improve").protectedHolds(repo).forEach((r, i) => {
      try { out.push(compile(r, `improve_protected:${i}`)); } catch (e) { throw new Error(`bad protected rule ${i}: ${e.message}`); }
    });
  }
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

// The words of the command after the rule's match, up to the first unquoted `;`, `|`, `&&` or newline: quote-aware
// (a quoted word with spaces is one word). A word that cannot be resolved here (it holds `$` or a backtick, or a quote
// is left open) is `unsafe`: the caller treats it as outside the worktree (one approval; fails closed).
function bashWords(command, m) {
  const s = command.slice(m.index + m[0].length);
  const words = [];
  let cur = null;
  let q = null;
  let unsafe = false;
  const push = () => {
    if (cur !== null) words.push({ raw: cur.raw, text: cur.text, unsafe: unsafe || q !== null });
    cur = null; unsafe = false;
  };
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q === null && (c === ";" || c === "|" || c === "\n" || (c === "&" && s[i + 1] === "&"))) break;
    if (q === null && /\s/.test(c)) { push(); continue; }
    if (cur === null) cur = { raw: "", text: "" };
    if (cur.raw === "" && q === null) cur.raw = c;
    if (q === null && (c === "'" || c === '"')) { q = c; continue; }
    if (q !== null && c === q) { q = null; continue; }
    if (c === "\\" && q !== "'" && i + 1 < s.length) { cur.text += s[++i]; continue; }
    if (c === "$" || c === "`") unsafe = true;
    cur.text += c;
  }
  push();
  return words.filter((w) => !w.raw.startsWith("-")).map((w) => {
    let t = w.text;
    if (t === "~" || t.startsWith("~/")) t = path.join(process.env.HOME || "", t.slice(1));
    return { text: t, unsafe: w.unsafe };
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
      if (r.outside && !bashWords(command, m).some((w) => w.unsafe || isOutside(path.resolve(base, w.text), worktree))) continue;
      return r;
    }
    const p = callPath(input);
    if (p === null) continue;
    const abs = path.resolve(base, p);
    // the path as written, relative to the worktree, and relative to it with every symlink resolved
    if (!r.pattern.test(abs) && !r.pattern.test(path.relative(worktree, abs))
      && !r.pattern.test(path.relative(realpathDeep(worktree), realpathDeep(abs)))) continue;
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

// The main checkout of the worktree's repository, or null.
function repoFor(worktree) {
  try {
    const out = cp.execFileSync("git", ["-C", worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    return path.dirname(out);
  } catch { return null; }
}
const configFor = (repo) => { try { return repo ? policy.loadConfig(repo) : {}; } catch { return {}; } };

// `handle` is an open database or null (then it is opened here, after a rule matched, from env).
function decide(handle, hookInput, env, now) {
  if (!env.ENGINE_JOB) return { decision: "none" };
  const worktree = env.ENGINE_WORKTREE || (hookInput && hookInput.cwd) || process.cwd();
  const repo = repoFor(worktree);
  let rules;
  try { rules = rulesFor(configFor(repo), repo); } catch (e) {
    // a bad config rule must not switch the defaults or the protected set off, and an unreadable protected set not the defaults
    process.stderr.write(`engine hold: ${e.message}; using the default holds\n`);
    try { rules = rulesFor({ holds: [] }, repo); } catch { rules = rulesFor({ holds: [] }); }
  }
  const rule = match(rules, hookInput, worktree);
  if (!rule) return { decision: "none" };
  // fail closed: a held call cannot be recorded without the engine dir
  if (!env.ENGINE_DIR) return { decision: "deny", reason: `engine hold: ENGINE_DIR not set for job ${env.ENGINE_JOB}` };
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
