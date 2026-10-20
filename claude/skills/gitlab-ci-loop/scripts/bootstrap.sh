#!/usr/bin/env bash
# Set up the gitlab-ci-loop in the current git repo. Idempotent: safe to re-run.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTEGRATION="" PREFIX="agent/" PROTECTED="" STARTER_CI=false FORCE_CONFIG=false INSTALL_GLAB=false

usage() {
  cat <<EOF
Usage: bootstrap.sh [options]
  --integration <branch>   branch agent MRs target (default: remote default branch)
  --prefix <prefix>        agent branch prefix (default: agent/)
  --protected <a,b,c>      branches agent-ci must never push (default: default+integration+staging/prod if present)
  --starter-ci             add a minimal .gitlab-ci.yml if the repo has none
  --force-config           regenerate .agent-ci.yml even if it exists
  --install-glab           install glab if missing
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --integration) INTEGRATION="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --protected) PROTECTED="$2"; shift 2 ;;
    --starter-ci) STARTER_CI=true; shift ;;
    --force-config) FORCE_CONFIG=true; shift ;;
    --install-glab) INSTALL_GLAB=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1"; usage; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not a git repo"; exit 2; }
cd "$ROOT"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
echo "gitlab-ci-loop bootstrap → $ROOT"

# 1. CLI entrypoint
mkdir -p "$HOME/.local/bin"
chmod +x "$SKILL_DIR/scripts/agent-ci.py" "$SKILL_DIR/scripts/local-check.py"   # the symlink needs an executable target
ln -sf "$SKILL_DIR/scripts/agent-ci.py" "$HOME/.local/bin/agent-ci"
ok "agent-ci → ~/.local/bin/agent-ci"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "add ~/.local/bin to PATH (e.g. echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc)";; esac

# 2. glab
GLAB="$(command -v glab || true)"; [[ -z "$GLAB" && -x "$HOME/.local/bin/glab" ]] && GLAB="$HOME/.local/bin/glab"
if [[ -z "$GLAB" ]]; then
  if $INSTALL_GLAB; then bash "$SKILL_DIR/scripts/install-glab.sh"; GLAB="$HOME/.local/bin/glab"
  else warn "glab missing — run: bash $SKILL_DIR/scripts/install-glab.sh"; fi
fi
if [[ -n "$GLAB" ]]; then
  if "$GLAB" auth status >/dev/null 2>&1; then ok "glab authenticated"
  else warn "glab not authenticated — run: glab auth login"; fi
fi
python3 -c 'import yaml' 2>/dev/null || warn "PyYAML missing — run: python3 -m pip install --user pyyaml"

# 3. branches
DEFAULT="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
[[ -z "$DEFAULT" ]] && DEFAULT="$(git config init.defaultBranch || echo main)"
INTEGRATION="${INTEGRATION:-$DEFAULT}"
if [[ -z "$PROTECTED" ]]; then
  PROTECTED="$DEFAULT"
  [[ "$INTEGRATION" != "$DEFAULT" ]] && PROTECTED="$PROTECTED,$INTEGRATION"
  for b in staging production prod release; do
    git show-ref --quiet "refs/remotes/origin/$b" && PROTECTED="$PROTECTED,$b"
  done
fi
ok "integration=$INTEGRATION prefix=$PREFIX protected=$PROTECTED"

# 4. starter CI
if [[ ! -f .gitlab-ci.yml ]]; then
  if $STARTER_CI; then cp "$SKILL_DIR/templates/gitlab-ci.starter.yml" .gitlab-ci.yml; ok "added starter .gitlab-ci.yml (fill in real checks)"
  else warn "no .gitlab-ci.yml — re-run with --starter-ci to add a minimal one"; fi
fi

# 5. config
if [[ ! -f .agent-ci.yml ]] || $FORCE_CONFIG; then
  python3 "$SKILL_DIR/scripts/gen-config.py" --integration "$INTEGRATION" --prefix "$PREFIX" \
    --protected "$PROTECTED" -o .agent-ci.yml
  ok ".agent-ci.yml generated — review paths/run commands"
else
  ok ".agent-ci.yml exists (use --force-config to regenerate)"
fi

# 6. AGENTS.md managed block
python3 - "$SKILL_DIR/templates/AGENTS.md.tmpl" <<'PY'
import re, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(sys.argv[1]), "..", "scripts"))
from agentci_config import load_config
cfg = load_config()
block = open(sys.argv[1]).read()
for k, v in {"PREFIX": cfg["branch_prefix"], "INTEGRATION": cfg["integration_branch"],
             "MAX_ROUNDS": cfg["max_ci_rounds"],
             "PROTECTED": ", ".join(f"`{b}`" for b in cfg["protected_branches"])}.items():
    block = block.replace("{{" + k + "}}", str(v))
path = "AGENTS.md"
text = open(path).read() if os.path.exists(path) else "# Agent instructions\n"
pat = re.compile(r"<!-- gitlab-ci-loop:start.*?<!-- gitlab-ci-loop:end -->\n?", re.S)
text = pat.sub(lambda _: block, text) if pat.search(text) else text.rstrip() + "\n\n" + block
open(path, "w").write(text)
PY
ok "AGENTS.md loop block up to date"

# 7. gitignore
touch .gitignore
grep -qxF '.agent-ci/' .gitignore || { printf '\n# gitlab-ci-loop local cache\n.agent-ci/\n' >> .gitignore; ok ".agent-ci/ added to .gitignore"; }

echo
echo "Next: review .agent-ci.yml, run 'agent-ci check --list', then commit .agent-ci.yml, AGENTS.md and .gitignore."
