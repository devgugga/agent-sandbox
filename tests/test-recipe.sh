#!/usr/bin/env bash
# tests/test-recipe.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace recipe-test >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

echo "== Task 7: receita Orca =="

# A derivacao do nome do workspace ja causou dois defeitos: pod vazando (create
# usava $$, que o destroy nao reproduz) e nomes com traco duplo (o subshell do
# basename traz um newline que o `tr -c` converte). Ambos so aparecem em uso
# real, entao ficam fixados aqui.
_wsid() { env -u ORCA_WORKSPACE_ID bash -c '
  source <(sed -n "/^asb_workspace_id()/,/^}/p" "$1"); asb_workspace_id "$2"' _ "$1" "$2"; }

assert_eq "$(_wsid recipes/create.sh /tmp/proj)" "$(_wsid recipes/destroy.sh /tmp/proj)" \
  "create e destroy derivam o mesmo nome"
assert_eq "$(_wsid recipes/create.sh /tmp/proj)" "$(_wsid recipes/create.sh /tmp/proj/)" \
  "barra final nao muda o nome"
case "$(_wsid recipes/create.sh /tmp/proj)" in
  *--*) echo "  FALHOU: nome com traco duplo"; _fail=$((_fail+1)) ;;
  *) echo "  ok: nome sem traco duplo"; _pass=$((_pass+1)) ;;
esac
case "$(_wsid recipes/create.sh /tmp/proj)" in
  ''|*[!a-zA-Z0-9._-]*) echo "  FALHOU: nome com caractere invalido"; _fail=$((_fail+1)) ;;
  *) echo "  ok: nome so com caracteres validos"; _pass=$((_pass+1)) ;;
esac
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
