#!/usr/bin/env bash
# recipes/destroy.sh — le o payload do ciclo de vida no stdin
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/recipes/common.sh"

payload=$(cat || true)
# O Orca aninha o resultado do create em `recipeResult` (ver o exemplo do guia:
# d.recipeResult?.userData?.resourceId). Ler so `.userData` encontra nada, cai
# na derivacao por caminho e — quando ela diverge — o pod fica orfao.
ws=$(printf '%s' "$payload" | jq -r '.recipeResult.userData.workspace // .userData.workspace // empty' 2>/dev/null || true)
# Sem payload, deriva o MESMO nome que o create derivaria. NAO usar
# ORCA_WORKSPACE_ID cru aqui: numa sessao do Orca ele e o id de worktree
# (`<uuid>::/caminho`), que contem ":" e "/" e e rejeitado pelo CLI. Quem
# sanitiza e o asb_workspace_id.
repo="${1:-$PWD}"
[ -n "$ws" ] || ws=$(asb_workspace_id "$repo")
[ -n "$ws" ] || { echo "sem workspace para destruir" >&2; exit 0; }
"$ROOT/cli/agent-sandbox" down --workspace "$ws" >&2
