#!/usr/bin/env bash
# recipes/suspend.sh — o Orca adormece o workspace. Para o pod SEM destruir:
# o historico do agente e a porta SSH ja gravada pelo Orca precisam sobreviver.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/recipes/common.sh"

payload=$(cat || true)
ws=$(printf '%s' "$payload" | jq -r '.recipeResult.userData.workspace // .userData.workspace // empty' 2>/dev/null || true)
[ -n "$ws" ] || ws=$(asb_workspace_id "${1:-$PWD}")
"$ROOT/cli/agent-sandbox" suspend --workspace "$ws" >&2
