#!/usr/bin/env bash
# recipes/create.sh — contrato de ciclo de vida do Orca (SSH mode).
# Roda NO HOST, a partir da raiz do repo do projeto.
# Imprime UMA linha JSON no stdout. Todo o resto vai para stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${1:-$PWD}"
# Nome DETERMINISTICO derivado do caminho do repo. Com $$ (PID) o destroy nao
# tem como reproduzir o nome e o pod vaza — o `doctor --provision` deixou um
# pod para tras exatamente assim, reportando sucesso.
asb_workspace_id() {
  local repo="$1"
  if [ -n "${ORCA_WORKSPACE_ID:-}" ]; then
    printf '%s' "$ORCA_WORKSPACE_ID" | tr -c 'a-zA-Z0-9._-' '-'
    return
  fi
  local base short
  base=$(basename "$repo" | tr -c 'a-zA-Z0-9._-' '-')
  short=$(printf '%s' "$repo" | sha256sum | cut -c1-8)
  printf '%s-%s' "$base" "$short"
}

ws=$(asb_workspace_id "$repo")

up=$("$ROOT/cli/agent-sandbox" up --workspace "$ws" --repo "$repo")
port=$(printf '%s' "$up" | jq -r .port)
key="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519"

jq -nc \
  --arg label "agent-sandbox-$ws" \
  --arg ws "$ws" \
  --arg key "$key" \
  --argjson port "$port" '
{
  schemaVersion: 1,
  userData: {
    workspace: $ws
  },
  connection: {
    type: "ssh",
    projectRoot: "/workspace",
    target: {
      label: $label,
      host: "127.0.0.1",
      port: $port,
      username: "agent",
      identityFile: $key,
      identitiesOnly: true
    }
  }
}'
