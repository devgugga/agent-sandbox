#!/usr/bin/env bash
# recipes/shim.template.sh — copiado para cada projeto consumidor como
# scripts/orca-vm/{create,destroy,suspend,resume}.sh. A LOGICA NAO E COPIADA:
# so o ponteiro.
# Editar aqui e ressincronizar; nunca editar a copia no projeto.
set -euo pipefail
exec "$HOME/Data/Projects/agent-sandbox/recipes/__ACTION__.sh" "$(cd "$(dirname "$0")/../.." && pwd)"
