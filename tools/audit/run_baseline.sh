#!/usr/bin/env bash
# usage: run_baseline.sh [days] — runs every audit metric over the agreed scope, read-only
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; top="$(git -C "$here" rev-parse --show-toplevel)"
days="${1:-30}"; root="$HOME/.claude/projects"
out="$top/audit-out/$(date +%F)"; mkdir -p "$out"
repos=(--repo /Users/francisco.ruiz/master-gcp-repo --repo /Users/francisco.ruiz/agent-board)
for m in session_metrics waste_signals handoff_trace; do
  python3 "$here/$m.py" --root "$root" "${repos[@]}" --days "$days" --out "$out/$m.json"
  echo "wrote $out/$m.json"
done
python3 "$here/injection_costs.py" --root "$root" "${repos[@]}" --days "$days" \
  --board-repo /Users/francisco.ruiz/agent-board --out "$out/injection_costs.json"
echo "wrote $out/injection_costs.json"
python3 "$here/transcripts.py" --manifest --root "$root" "${repos[@]}" --days "$days" \
  --sha "$(git -C "$here" rev-parse --short HEAD)" --out "$out/manifest.json"
echo "wrote $out/manifest.json"
