# Scout real-state checks (2026-11-21)

Read-only runs of the trend scout against this machine's real state, from the `spec-trend-scout` worktree (`zsh bin/tmux-ctl …`, so the branch code runs).

## Real scout dir, before and after the whole session

    $ ls -la ~/.local/state/agent-board/scout 2>&1     # before
    ls: /Users/francisco.ruiz/.local/state/agent-board/scout: No such file or directory
    $ ls -la ~/.local/state/agent-board/scout 2>&1     # after (re-checked below, after every real-state command)
    ls: /Users/francisco.ruiz/.local/state/agent-board/scout: No such file or directory

## Default sources: `TC_SCOUT_DIR=$(mktemp -d) tmux-ctl scout source test <name>`

Ten default sources (`scout source list`): claude-code-changelog, claude-code-npm, anthropic-news, anthropic-engineering, claude-blog, claude-code-release-notes, api-release-notes, models-overview, api-pricing, plugins.

### Finding: every fetch fails with the default python3's TLS setup

The `python3` on PATH is the python.org 3.14.7 framework build; its OpenSSL looks for a CA file under `/Library/Frameworks/Python.framework/Versions/3.14/etc/openssl/cert.pem`, which is not there. Plain run, all ten sources:

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

(`/usr/bin/python3` fetches `registry.npmjs.org` fine: 200.) A launchd poll or weekly run would fail the same way unless the environment carries a CA bundle (`SSL_CERT_FILE`) or the certificates are installed for that Python. This is an environment finding, not changed here.

### With `SSL_CERT_FILE=/etc/ssl/cert.pem` (a per-command env var, no code change)

    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-changelog
    Claude Code 2.1.330	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.329	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.328	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.327	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.326	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    Claude Code 2.1.325	https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-npm
    @anthropic-ai/claude-code 2.1.330	https://www.npmjs.com/package/@anthropic-ai/claude-code
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-news
    Announcements	https://www.anthropic.com/news/announcements
    Investing in the public benefit We’re committing a portion of Anthropic’s shares to the Anthropic Public Benefit Fund, a new entity with a structure that increa
    Anthropic files S-1 with the SEC for proposed initial public offering Today, Anthropic, PBC filed a registration statement on Form S-1 with the U.S. Securities 
    Features	https://www.anthropic.com/news/features
    Anthropic announces closing of initial public offering, including full exercise of underwriters’ option to purchase additional shares, and closing of concurrent
    Anthropic prices initial public offering	https://www.anthropic.com/news/anthropic-prices-initial-public-offering
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test anthropic-engineering
    The components of agent memory	https://www.anthropic.com/research/components-of-agent-memory
    Redesigning source control at Anthropic	https://www.anthropic.com/research/redesigning-source-control
    Harness design for long-running application development	https://www.anthropic.com/research/harness-design-long-running-apps
    Designing AI-resistant technical evaluations	https://www.anthropic.com/research/AI-resistant-technical-evaluations
    Building strong safety evaluations	https://www.anthropic.com/research/building-strong-safety-evaluations
    How we contain Claude across products	https://www.anthropic.com/research/how-we-contain-claude
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-blog
    Linked billing on the Claude Platform	https://claude.com/resources/articles/linked-billing-on-claude-platform
    The Claude Tag guide for startups	https://claude.com/resources/articles/claude-tag-guide-for-startups
    Building always-on agents	https://claude.com/resources/articles/building-always-on-agents
    Operate Claude Managed Agents inside your security perimeter	https://claude.com/resources/articles/self-hosted-claude-managed-agents
    J. Crew brings its signature approach to styling to life with Claude	https://claude.com/resources/articles/j-crew-style-advisor-with-claude
    Introducing Claude for Manufacturing	https://claude.com/resources/articles/claude-for-manufacturing
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test claude-code-release-notes
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-release-notes
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test models-overview
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test api-pricing
    rc=0
    === SSL_CERT_FILE=/etc/ssl/cert.pem TC_SCOUT_DIR=<tmp> tmux-ctl scout source test plugins
    superpowers-extended-cc 6.5.3-dev → 7.1.2	https://github.com/pcvelz/superpowers
    rc=0

The four `html_diff` sources (`claude-code-release-notes`, `api-release-notes`, `models-overview`, `api-pricing`) print no items and exit 0: on a fresh scratch dir the first fetch only stores the page hash as its baseline (by design, "first poll of a source"), so a one-shot `source test` has nothing to diff. The fetch itself succeeded (rc 0, no URLError). The other six print at least one item.

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

`python3 -m unittest board.tests.test_scout_isolation -v` → `OK`, printing `scout isolation: compared 10 real paths, none changed` (real scout dir and its tree, real outbox dir, real ideas files, `git for-each-ref` of this repo; before = after).
