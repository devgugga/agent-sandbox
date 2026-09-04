#!/usr/bin/env bash
# recipes/create.sh — contrato de ciclo de vida do Orca (SSH mode).
# Roda NO HOST, a partir da raiz do repo do projeto.
# Imprime UMA linha JSON no stdout. Todo o resto vai para stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/recipes/common.sh"
repo="${1:-$PWD}"

ws=$(asb_workspace_id "$repo")
up=$("$ROOT/cli/agent-sandbox" up --workspace "$ws" --repo "$repo")
asb_recipe_json "$ws" "$(printf '%s' "$up" | jq -r .port)"
