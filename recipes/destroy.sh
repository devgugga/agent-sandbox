#!/usr/bin/env bash
# recipes/destroy.sh — le o payload do ciclo de vida no stdin
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
payload=$(cat || true)
ws=$(printf '%s' "$payload" | jq -r '.userData.workspace // empty' 2>/dev/null || true)
[ -n "$ws" ] || ws="${ORCA_WORKSPACE_ID:-}"
[ -n "$ws" ] || { echo "sem workspace para destruir" >&2; exit 0; }
"$ROOT/cli/agent-sandbox" down --workspace "$ws" >&2
