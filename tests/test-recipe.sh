#!/usr/bin/env bash
# tests/test-recipe.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace recipe-test >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

echo "== Task 7: receita Orca =="
out=$(ORCA_WORKSPACE_ID=recipe-test ./recipes/create.sh "$REPO" 2>/dev/null)
assert_eq "1" "$(echo "$out" | wc -l)" "create emite exatamente UMA linha"
echo "$out" | jq -e . >/dev/null && { echo "  ok: JSON valido"; _pass=$((_pass+1)); } || { echo "  FALHOU: JSON invalido"; _fail=$((_fail+1)); }
assert_eq "1" "$(echo "$out" | jq -r .schemaVersion)" "schemaVersion 1"
assert_eq "ssh" "$(echo "$out" | jq -r .connection.type)" "connection.type ssh"
assert_eq "127.0.0.1" "$(echo "$out" | jq -r .connection.target.host)" "host loopback"
assert_eq "agent" "$(echo "$out" | jq -r .connection.target.username)" "username agent"
assert_eq "true" "$(echo "$out" | jq -r .connection.target.identitiesOnly)" "identitiesOnly true"
assert_eq "null" "$(echo "$out" | jq -r .pairingCode)" "SSH mode nao emite pairingCode"
report
