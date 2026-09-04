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
  # ORCA_VM_INSTANCE_ID e o identificador UNICO POR WORKSPACE que o Orca passa
  # aos scripts de ciclo de vida. Sem ele, a derivacao cai no caminho do repo —
  # e como o Orca executa os shims a partir do checkout PRIMARIO, todo workspace
  # do mesmo projeto receberia o mesmo nome e o segundo mataria o pod do
  # primeiro.
  local given="${ORCA_VM_INSTANCE_ID:-${ORCA_WORKSPACE_ID:-}}"
  if [ -n "$given" ]; then
    printf '%s' "$given" | tr -c 'a-zA-Z0-9._-' '-'
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
    projectRoot: "/home/agent/workspace",
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
