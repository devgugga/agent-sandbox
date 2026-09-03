#!/usr/bin/env bash
# recipes/create.sh — contrato de ciclo de vida do Orca (SSH mode).
# Roda NO HOST, a partir da raiz do repo do projeto.
# Imprime UMA linha JSON no stdout. Todo o resto vai para stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${1:-$PWD}"
ws="${ORCA_WORKSPACE_ID:-$(basename "$repo")-$$}"
ws=$(printf '%s' "$ws" | tr -c 'a-zA-Z0-9._-' '-')

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
