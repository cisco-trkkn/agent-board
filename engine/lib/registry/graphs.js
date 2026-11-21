"use strict";
// Pure graph functions over plan manifests: no fs, no git, no child_process.

const POLICIES = ["strict", "append", "writes_only"];
const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
const round4 = (x) => Math.round(x * 1e4) / 1e4;

function specSet(plans) {
  return new Set(plans.map((p) => p.spec));
}

function dependencyEdges(plans, relations) {
  const specs = specSet(plans);
  const out = [];
  for (const p of plans) {
    for (const d of (p.manifest.depends_on || [])) {
      if (!specs.has(d.spec) || d.spec === p.spec) continue;
      out.push({ from: p.spec, to: d.spec, kind: d.kind === "soft" ? "soft" : "hard", source: "manifest" });
    }
  }
  for (const r of relations || []) {
    if (r.kind === "order" && specs.has(r.a) && specs.has(r.b)) {
      out.push({ from: r.a, to: r.b, kind: "order", source: "crossplan" });
    }
  }
  return out.sort((x, y) => cmp(x.from, y.from) || cmp(x.to, y.to) || cmp(x.kind, y.kind));
}

// per path: {w: written, a: every write append, r: read}
function access(plan) {
  const m = new Map();
  const get = (p) => {
    if (!m.has(p)) m.set(p, { w: false, a: true, r: false });
    return m.get(p);
  };
  for (const w of plan.manifest.writes || []) {
    const e = get(w.path);
    e.w = true;
    if (w.mode !== "append") e.a = false;
  }
  for (const p of plan.manifest.reads || []) get(p).r = true;
  return m;
}

function appendOnly(e) {
  return e.w && e.a && !e.r;
}

function conflictsOn(policy, x, y) {
  if (policy === "writes_only") return x.w && y.w;
  if (!((x.w && (y.w || y.r)) || (y.w && x.r))) return false;
  if (policy === "append" && appendOnly(x) && appendOnly(y)) return false;
  return true;
}

function pathConflicts(plans, policy) {
  const acc = plans.map(access);
  const out = [];
  for (let i = 0; i < plans.length; i++) {
    for (let j = i + 1; j < plans.length; j++) {
      const [a, b, ea, eb] = plans[i].spec <= plans[j].spec
        ? [plans[i].spec, plans[j].spec, acc[i], acc[j]]
        : [plans[j].spec, plans[i].spec, acc[j], acc[i]];
      const paths = [];
      for (const [p, x] of ea) {
        const y = eb.get(p);
        if (y && conflictsOn(policy, x, y)) paths.push(p);
      }
      if (paths.length) out.push({ a, b, paths: paths.sort(), source: "manifest" });
    }
  }
  return out;
}

function conflictEdges(plans, policy, relations) {
  const specs = specSet(plans);
  const out = pathConflicts(plans, policy);
  for (const r of relations || []) {
    if ((r.kind === "conflict" || r.kind === "interface") && specs.has(r.a) && specs.has(r.b) && r.a !== r.b) {
      out.push({ a: r.a < r.b ? r.a : r.b, b: r.a < r.b ? r.b : r.a, paths: [], source: "crossplan" });
    }
  }
  return out.sort((x, y) => cmp(x.a, y.a) || cmp(x.b, y.b) || cmp(x.source, y.source));
}

function clusters(plans) {
  const parent = new Map(plans.map((p) => [p.spec, p.spec]));
  const find = (x) => {
    while (parent.get(x) !== x) {
      parent.set(x, parent.get(parent.get(x)));
      x = parent.get(x);
    }
    return x;
  };
  const union = (x, y) => parent.set(find(x), find(y));
  for (const e of dependencyEdges(plans, [])) if (e.kind === "hard") union(e.from, e.to);
  const byApp = new Map(plans.map((p) => [p.spec, access(p)]));
  for (const e of pathConflicts(plans, "strict")) {
    const ea = byApp.get(e.a);
    const eb = byApp.get(e.b);
    if (e.paths.some((p) => !(appendOnly(ea.get(p)) && appendOnly(eb.get(p))))) union(e.a, e.b);
  }
  const groups = new Map();
  for (const p of plans) {
    const r = find(p.spec);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push(p.spec);
  }
  return [...groups.values()].map((m) => m.sort()).sort((x, y) => cmp(x[0], y[0]));
}

function findCycle(nodes, deps) {
  const state = new Map();
  const stack = [];
  const visit = (n) => {
    state.set(n, 1);
    stack.push(n);
    for (const d of [...(deps.get(n) || [])].sort()) {
      if (!nodes.has(d)) continue;
      if (state.get(d) === 1) return [...stack.slice(stack.indexOf(d)), d];
      if (!state.get(d)) {
        const c = visit(d);
        if (c) return c;
      }
    }
    stack.pop();
    state.set(n, 2);
    return null;
  };
  for (const n of [...nodes].sort()) if (!state.get(n)) {
    const c = visit(n);
    if (c) return c;
  }
  return [];
}

function waves(plans, policy, relations) {
  const edges = conflictEdges(plans, policy, relations);
  const nbr = new Map(plans.map((p) => [p.spec, new Set()]));
  for (const e of edges) {
    nbr.get(e.a).add(e.b);
    nbr.get(e.b).add(e.a);
  }
  const deps = new Map(plans.map((p) => [p.spec, new Set()]));
  for (const e of dependencyEdges(plans, relations)) if (e.kind !== "soft") deps.get(e.from).add(e.to);
  const rank = (s) => nbr.get(s).size;
  const wave = {};
  const pending = new Set(plans.map((p) => p.spec));
  while (pending.size) {
    const ready = [...pending].filter((s) => [...deps.get(s)].every((d) => d in wave));
    if (!ready.length) {
      throw new Error("dependency cycle: " + findCycle(pending, deps).join(" -> "));
    }
    ready.sort((x, y) => rank(y) - rank(x) || cmp(x, y));
    const s = ready[0];
    let c = 0;
    for (const d of deps.get(s)) c = Math.max(c, wave[d] + 1);
    const used = new Set([...nbr.get(s)].filter((n) => n in wave).map((n) => wave[n]));
    while (used.has(c)) c++;
    wave[s] = c;
    pending.delete(s);
  }
  return wave;
}

function summary(plans, relations) {
  const n = plans.length;
  const count = {};
  for (const pol of POLICIES) {
    const w = Object.values(waves(plans, pol, relations));
    count[pol] = w.length ? Math.max(...w) + 1 : 0;
  }
  const ratio = (k) => (k ? round4(n / k) : 0);
  return {
    waves: count,
    parallelism: ratio(count.append),
    parallelism_strict: ratio(count.strict),
    parallelism_writes_only: ratio(count.writes_only),
    clusters: clusters(plans).length,
  };
}

function hotFiles(plans) {
  const n = new Map();
  for (const p of plans) {
    for (const path of new Set((p.manifest.writes || []).map((w) => w.path))) n.set(path, (n.get(path) || 0) + 1);
  }
  return [...n].filter(([, c]) => c >= 3).map(([path, count]) => ({ path, count }))
    .sort((x, y) => y.count - x.count || cmp(x.path, y.path));
}

module.exports = { dependencyEdges, conflictEdges, clusters, waves, summary, hotFiles };
