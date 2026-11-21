"""findings: the parts opportunity discovery and the trend scout share.

Store(path, keep=14, extra=None) owns one JSON state file (flock on <path stem>.lock, atomic tmp + os.replace write).
dismissed_blocks() is the shared dismissal rule, kid/cut/value_line render post lines, and decide() applies a File / Dismiss
click to a stored post item. It writes no posts: each user (discover_post, scout_post) locks, finds the item and edits the post
around it. Test: tests/test_findings.py."""
import contextlib
import fcntl
import hashlib
import json
import os
import time

import analytics_post

REGROWTH = 1.5
URL_MAX = 150       # a longer url is rendered as plain text
MARKS = {"filed": "💡 filed", "dismissed": "✖ dismissed"}
escape = analytics_post.escape
_DEFAULTS = {"root": "", "failures": 0, "reported": {}, "dismissed": {}, "filed": {}, "posts": {}}


def kid(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def cut(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:max(n - 1, 0)] + "…"


def dismissed_blocks(st, key, count):
    """True while a dismissed key has not grown by REGROWTH since it was dismissed."""
    return key in st["dismissed"] and count < REGROWTH * st["dismissed"][key]["evidence_count"]


class Store:
    def __init__(self, path, keep=14, extra=None):
        self.path, self.keep = path, keep
        self.defaults = dict(_DEFAULTS, **(extra or {}))

    @contextlib.contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def read(self):
        try:
            st = json.loads(self.path.read_text())
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        out = json.loads(json.dumps(self.defaults))
        for k, dflt in out.items():
            v = st.get(k)
            if isinstance(v, type(dflt)):
                out[k] = v
        return out

    def write(self, st):
        st = dict(st)
        st["posts"] = {n: st["posts"][n] for n in sorted(st["posts"])[-self.keep:]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1) + "\n")
        os.replace(tmp, self.path)

    def load(self):
        return self.read()

    def save(self, st):
        with self.locked():
            self.write(st)

    def update(self, fn):
        """Read-modify-write under the lock; fn(state) edits the dict in place. Returns the saved state."""
        with self.locked():
            st = self.read()
            fn(st)
            self.write(st)
            return st


def value_line(value, effort, risk, parts, cap, links=True):
    """The value line. A link whose text had to be cut is dropped (plain cut text), so a link is never cut in half."""
    ev = []
    for text, url in parts:
        if links and url and len(text) <= cap and len(str(url)) <= URL_MAX:
            ev.append(f"[{escape(text)}]({str(url).replace(')', '%29')})")
        else:
            ev.append(escape(cut(text, cap)))
    c = max(cap // 4, 10)
    return (f"value {escape(cut(value, c))} · effort {escape(cut(effort, c))} · "
            f"risk {escape(cut(risk, c))} · evidence: " + "; ".join(ev))


def decide(st, it, act, now, idea_line_fn):
    """Apply `file` / `dismiss` to a stored post item; mutates st and it. Returns "filed", "dismissed" or "already <x>"."""
    key = it["key"]
    done = "filed" if act == "file" else "dismissed"
    if key in st["filed"]:
        return "already filed"
    if key in st["dismissed"] and st["dismissed"][key]["evidence_count"] == it["count"]:
        return "already dismissed"
    if it.get("decision"):
        return "already " + it["decision"]
    if act == "file":
        st["filed"][key] = {"at": iso(now), "idea_line": idea_line_fn(it)}
    else:
        st["dismissed"][key] = {"at": iso(now), "evidence_count": it["count"]}
    it["decision"] = done
    return done
