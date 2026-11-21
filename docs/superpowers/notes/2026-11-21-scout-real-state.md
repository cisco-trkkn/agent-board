# Scout real-state checks (2026-11-21)

Read-only runs of the trend scout against this machine's real state, from the `spec-trend-scout` worktree (`zsh bin/tmux-ctl …`, so the branch code runs).

## Real scout dir, before and after the whole session

    $ ls -la ~/.local/state/agent-board/scout 2>&1     # before
    ls: /Users/francisco.ruiz/.local/state/agent-board/scout: No such file or directory
    $ ls -la ~/.local/state/agent-board/scout 2>&1     # after (re-checked below, after every real-state command)
    ls: /Users/francisco.ruiz/.local/state/agent-board/scout: No such file or directory

## Default sources: `TC_SCOUT_DIR=$(mktemp -d) tmux-ctl scout source test <name>`

Ten default sources (`scout source list`): claude-code-changelog, claude-code-npm, anthropic-news, anthropic-engineering, claude-blog, claude-code-release-notes, api-release-notes, models-overview, api-pricing, plugins. No `SSL_CERT_FILE` set; the PATH `python3`.

### Finding, fixed in this task: no CA bundle in the PATH python3

The `python3` on PATH is the python.org 3.14.7 framework build. Its OpenSSL looks for a CA file under `/Library/Frameworks/Python.framework/Versions/3.14/etc/openssl/cert.pem`, which does not exist, so the first run of every source failed (before the fix):

    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-changelog
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-npm
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-news
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-engineering
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-blog
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-release-notes
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-release-notes
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test models-overview
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-pricing
    scout: URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1082)>
    rc=1
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test plugins
    scout: every marketplace fetch failed
    rc=1

`board/scout_fetch.py` now builds its opener with `_ssl_context()`: when Python has no usable CA file or directory and `SSL_CERT_FILE` is unset, it loads `/etc/ssl/cert.pem`. Verification stays on. After the fix, the same ten commands, still without `SSL_CERT_FILE`:

    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-changelog
    Claude Code 2.1.330	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.329	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.328	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-npm
    @anthropic-ai/claude-code 2.1.330	https://www.npmjs.com/package/@anthropic-ai/claude-code
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-news
    Announcements	https://www.anthropic.com/news/announcements
    Investing in the public benefit We’re committing a portion of Anthropic’s shares to the Anthropic Public Benefit Fund, a new entity with a s
    Anthropic files S-1 with the SEC for proposed initial public offering Today, Anthropic, PBC filed a registration statement on Form S-1 with 
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-engineering
    The components of agent memory	https://www.anthropic.com/research/components-of-agent-memory
    Redesigning source control at Anthropic	https://www.anthropic.com/research/redesigning-source-control
    Harness design for long-running application development	https://www.anthropic.com/research/harness-design-long-running-apps
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-blog
    Linked billing on the Claude Platform	https://claude.com/resources/articles/linked-billing-on-claude-platform
    The Claude Tag guide for startups	https://claude.com/resources/articles/claude-tag-guide-for-startups
    Building always-on agents	https://claude.com/resources/articles/building-always-on-agents
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-release-notes
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-release-notes
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test models-overview
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-pricing
    rc=0
    === TC_SCOUT_DIR=<tmp> tmux-ctl scout source test plugins
    superpowers-extended-cc 6.5.3-dev → 7.1.2	https://github.com/pcvelz/superpowers
    rc=0

The four `html_diff` sources (`claude-code-release-notes`, `api-release-notes`, `models-overview`, `api-pricing`) print no items and exit 0: on a fresh scratch dir the first fetch only stores the page hash as its baseline (by design), so a one-shot `source test` has nothing to diff. The fetch itself succeeded. The other six print at least one item.

## Context pack: `tmux-ctl scout pack --root /Users/francisco.ruiz/agent-board`

    rc=0
    bytes: 30599        (limit 30720)
    headings: ## Shared context, ## Layout, ## Specs, ## Open ideas, ## Versions, ## Claude Code features in use

Built from the real context file and the real ideas file; nothing written (scout dir still absent).

## discover nightly on real state: `tmux-ctl discover nightly --dry-run --force --project agent-board`

    run dir: /Users/francisco.ruiz/.local/state/agent-board/discover/runs/agent-board/20261121-0604
    discover: agent-board: 6 candidates, 3 ranked, 3 new, would post
    ...
    rc=0

Run once, with the real model; no usage limit hit.

## Isolation leak check

`python3 -m unittest board.tests.test_scout_isolation -v` → `OK`, printing `scout isolation: compared 6 real paths, none changed` (real scout dir and its tree, the real discord outbox listing by name, the real ideas files, `git for-each-ref` of this repo; before = after).

Mutation check: a copy of the test whose scout step first writes `leak.txt` into the real scout dir FAILS (`FAILED (failures=1)`, the diff names `scout/leak.txt`); the real test then passes again, and the leak was removed (`ls ~/.local/state/agent-board/scout` → No such file or directory). The outbox is compared by names, not directory mtime: the live bridge consumes the outbox and moved its mtime during a run (one failure in about four).

## Full suite

`zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS 200 jobs in 9m25s`, `SLOW: 9m25s over the 5 min budget`, `rc=4`. (The first run had `FAIL 9/200` from the help range; fixed by `sed -n '2,84p'` in `bin/tmux-ctl`.)
