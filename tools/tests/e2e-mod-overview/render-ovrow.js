// usage: node render-ovrow.js <board/index.html> <overview.json>   (no jsdom here: a minimal DOM shim, the page's own functions)
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const ov = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const grab = (re, what) => { const m = html.match(re); if (!m) throw new Error(what + " not found"); return m[0]; };
const fn = (n) => grab(new RegExp(`^function ${n}\\([^)]*\\) \\{[^\\n]*\\}\\n|^function ${n}\\([^)]*\\) \\{\\n.*?^\\}\\n`, "ms"), n);
const names = ["fmtAge", "ovName", "ovGroup", "ovStatus", "ovRun", "ovPlanText", "ovMoreTasks", "ovAgentLine", "ovNeedsText", "ovRow"];
const consts = ["alertColor", "OV_WORD"].map((n) => grab(new RegExp(`^const ${n} = [^\\n]*\\n`, "m"), n));
class Node_ { constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this.textContent = ""; this.title = ""; this.href = ""; this.dataset = {}; }
  append(...c) { this.children.push(...c); } get firstChild() { return this.children[0]; } }
const document = { createElement: (t) => new Node_(t) };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const code = consts.join("") + names.map(fn).join("\n") + "\nmodule.exports = { ovRow };";
const m = { exports: {} }; new Function("module", "document", "el", code)(m, document, el);
const dump = (n, d = 0) => { console.log(" ".repeat(d * 2) + `<${n.tag} class="${n.className}">` + (n.textContent ? " " + n.textContent : "")); n.children.forEach((c) => dump(c, d + 1)); };
for (const p of ov.projects) { console.log("PROJECT", p.project); dump(m.exports.ovRow(p)); }
