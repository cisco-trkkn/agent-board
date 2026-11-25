"use strict";
// Schedule rules (spec section 14): `daily HH:MM`, `weekly <Mon…Sun> HH:MM`, `every <n>m`, in local time.
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// rule text -> {kind: "daily", h, m} | {kind: "weekly", day, h, m} | {kind: "every", minutes}; throws on anything else.
function parseRule(text) {
  const s = String(text).trim();
  let m = /^daily (\d{2}):(\d{2})$/.exec(s);
  if (m) return hm({ kind: "daily" }, m[1], m[2], s);
  m = /^weekly (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{2}):(\d{2})$/.exec(s);
  if (m) return hm({ kind: "weekly", day: DAYS.indexOf(m[1]) }, m[2], m[3], s);
  m = /^every ([1-9]\d*)m$/.exec(s);
  if (m) return { kind: "every", minutes: Number(m[1]) };
  throw new Error(`bad rule "${s}": daily HH:MM | weekly <Mon…Sun> HH:MM | every <n>m`);
}
function hm(r, h, mm, s) {
  const H = Number(h);
  const M = Number(mm);
  if (H > 23 || M > 59) throw new Error(`bad rule "${s}": time out of range`);
  return { ...r, h: H, m: M };
}

// The first occurrence strictly after `after` (epoch seconds), in local time. For `every`, `anchor` (epoch seconds,
// the row's previous due time) keeps the grid: anchor + k*n minutes; without one the grid starts at `after`.
// A local time that a DST change skips runs one hour later (JS Date rolls 02:30 forward to 03:30); a time that
// occurs twice runs once, at its first occurrence.
function nextAfter(rule, after, anchor) {
  const r = typeof rule === "string" ? parseRule(rule) : rule;
  if (r.kind === "every") {
    const step = r.minutes * 60;
    const base = anchor === undefined || anchor === null ? after : anchor;
    if (base > after) return base;
    return base + (Math.floor((after - base) / step) + 1) * step;
  }
  const d = new Date(after * 1000);
  for (let i = 0; i <= 8; i++) {
    const c = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i, r.h, r.m, 0, 0);
    if (r.kind === "weekly" && c.getDay() !== r.day) continue;
    const t = c.getTime() / 1000;
    if (t > after) return t;
  }
  throw new Error("no next occurrence"); // unreachable: 8 days always hold one
}

module.exports = { DAYS, parseRule, nextAfter };
