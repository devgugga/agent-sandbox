#!/usr/bin/env bash
# recipes/destroy.sh — le o payload do ciclo de vida no stdin
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Nome DETERMINISTICO derivado do caminho do repo. Com $$ (PID) o destroy nao
# tem como reproduzir o nome e o pod vaza — o `doctor --provision` deixou um
# pod para tras exatamente assim, reportando sucesso.
asb_workspace_id() {
  local repo="$1"
  if [ -n "${ORCA_WORKSPACE_ID:-}" ]; then
    printf '%s' "$ORCA_WORKSPACE_ID" | tr -c 'a-zA-Z0-9._-' '-'
    return
  fi
  # Normalizar ANTES de derivar: barra final muda o hash, e create e destroy
  # divergiriam se o caminho chegasse de formas diferentes — o mesmo tipo de
  # divergencia que fazia o pod vazar.
  repo="${repo%/}"
  local base short
  # ${repo##*/} em vez de $(basename ...): o subshell traz um newline final que
  # o `tr -c` converte em traco, produzindo nomes como "hexmed-stack--f05b729e".
  base=${repo##*/}
  base=$(printf '%s' "$base" | tr -c 'a-zA-Z0-9._-' '-')
  short=$(printf '%s' "$repo" | sha256sum | cut -c1-8)
  printf '%s-%s' "$base" "$short"
}

payload=$(cat || true)
ws=$(printf '%s' "$payload" | jq -r '.userData.workspace // empty' 2>/dev/null || true)
# Sem payload, deriva o MESMO nome que o create derivaria. NAO usar
# ORCA_WORKSPACE_ID cru aqui: numa sessao do Orca ele e o id de worktree
# (`<uuid>::/caminho`), que contem ":" e "/" e e rejeitado pelo CLI. Quem
# sanitiza e o asb_workspace_id.
repo="${1:-$PWD}"
[ -n "$ws" ] || ws=$(asb_workspace_id "$repo")
[ -n "$ws" ] || { echo "sem workspace para destruir" >&2; exit 0; }
"$ROOT/cli/agent-sandbox" down --workspace "$ws" >&2
