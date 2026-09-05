#!/usr/bin/env bash
# recipes/resume.sh — o Orca acorda o workspace. Reemite o JSON de conexao
# porque a porta pode ter mudado (o guia exige isso do hook resume).
#
# ATENCAO: isto NAO cobre o reboot da maquina. O Orca guarda o runtime como
# "running" no registro dele e, depois de religar, so disca na porta que ja
# tinha — sem chamar resume. Quem cobre o reboot e a unidade de usuario do
# systemd: `agent-sandbox install-autostart`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/recipes/common.sh"

payload=""
if [ ! -t 0 ]; then
  payload=$(cat || true)
fi
ws=$(printf '%s' "$payload" | jq -r '.recipeResult.userData.workspace // .userData.workspace // empty' 2>/dev/null || true)
[ -n "$ws" ] || ws=$(asb_workspace_id "${1:-$PWD}")
out=$("$ROOT/cli/asb-agent" resume --workspace "$ws")
asb_recipe_json "$ws" \
  "$(printf '%s' "$out" | jq -r .port)" \
  "$(printf '%s' "$out" | jq -r .project_root)"
