#!/usr/bin/env bash
# tests/test-recipe.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source tests/assert.sh
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; "$ROOT/cli/asb-agent" down --workspace recipe-test >/dev/null 2>&1; "$ROOT/cli/asb-agent" down --workspace "recipe-check-$$" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

echo "== Task 7: receita Orca =="

# A derivacao do nome do workspace ja causou dois defeitos: pod vazando (create
# usava $$, que o destroy nao reproduz) e nomes com traco duplo (o subshell do
# basename traz um newline que o `tr -c` converte). Ambos so aparecem em uso
# real, entao ficam fixados aqui.
_wsid() { env -u ORCA_WORKSPACE_ID bash -c '
  source <(sed -n "/^asb_workspace_id()/,/^}/p" "$1"); asb_workspace_id "$2"' _ "$1" "$2"; }

# Agora a funcao vive em recipes/common.sh e os quatro hooks a importam. A
# asserção deixou de comparar duas copias e passou a proibir que copias voltem
# a existir — que era a causa real dos dois defeitos.
dups=$(grep -l '^asb_workspace_id()' recipes/create.sh recipes/destroy.sh recipes/suspend.sh recipes/resume.sh 2>/dev/null | tr '\n' ' ')
assert_eq "" "$dups" "nenhum hook redefine asb_workspace_id (fonte unica em common.sh)"
for action in create destroy suspend resume; do
  rendered=$(sed "s/__ACTION__/$action/g" recipes/shim.template.sh)
  assert_contains "/recipes/$action.sh" "$rendered" \
    "template do consumidor suporta $action"
done

# O Orca passa ORCA_VM_INSTANCE_ID, unico por workspace. Sem usa-lo, a
# derivacao cai no caminho do repo — e como os shims rodam a partir do checkout
# PRIMARIO, todo workspace do projeto teria o mesmo nome e o segundo mataria o
# pod do primeiro.
a=$(ORCA_VM_INSTANCE_ID=vm-a bash -c 'source <(sed -n "/^asb_workspace_id()/,/^}/p" recipes/common.sh); asb_workspace_id /tmp/proj')
b=$(ORCA_VM_INSTANCE_ID=vm-b bash -c 'source <(sed -n "/^asb_workspace_id()/,/^}/p" recipes/common.sh); asb_workspace_id /tmp/proj')
assert_eq "vm-a" "$a" "usa ORCA_VM_INSTANCE_ID quando presente"
[ "$a" != "$b" ] && { echo "  ok: workspaces distintos geram nomes distintos"; _pass=$((_pass+1)); } \
                 || { echo "  FALHOU: nomes colidem entre workspaces"; _fail=$((_fail+1)); }

# O Orca aninha o resultado do create em recipeResult; ler so .userData nao
# encontra o nome e deixa o pod orfao.
nested=$(printf '{"recipeResult":{"userData":{"workspace":"vm-nested"}}}' \
  | bash -c 'payload=$(cat); jq -r ".recipeResult.userData.workspace // .userData.workspace // empty" <<<"$payload"')
assert_eq "vm-nested" "$nested" "destroy le workspace de recipeResult.userData"
assert_eq "$(_wsid recipes/common.sh /tmp/proj)" "$(_wsid recipes/common.sh /tmp/proj/)" \
  "barra final nao muda o nome"
case "$(_wsid recipes/common.sh /tmp/proj)" in
  *--*) echo "  FALHOU: nome com traco duplo"; _fail=$((_fail+1)) ;;
  *) echo "  ok: nome sem traco duplo"; _pass=$((_pass+1)) ;;
esac
case "$(_wsid recipes/common.sh /tmp/proj)" in
  ''|*[!a-zA-Z0-9._-]*) echo "  FALHOU: nome com caractere invalido"; _fail=$((_fail+1)) ;;
  *) echo "  ok: nome so com caracteres validos"; _pass=$((_pass+1)) ;;
esac
out=$(ORCA_WORKSPACE_ID=recipe-test ./recipes/create.sh "$REPO" 2>/dev/null)
assert_eq "1" "$(echo "$out" | wc -l)" "create emite exatamente UMA linha"
echo "$out" | jq -e . >/dev/null && { echo "  ok: JSON valido"; _pass=$((_pass+1)); } || { echo "  FALHOU: JSON invalido"; _fail=$((_fail+1)); }
assert_eq "1" "$(echo "$out" | jq -r .schemaVersion)" "schemaVersion 1"
assert_eq "ssh" "$(echo "$out" | jq -r .connection.type)" "connection.type ssh"
assert_eq "127.0.0.1" "$(echo "$out" | jq -r .connection.target.host)" "host loopback"
assert_eq "$(id -un)" "$(echo "$out" | jq -r .connection.target.username)" "username $(id -un)"
assert_eq "true" "$(echo "$out" | jq -r .connection.target.identitiesOnly)" "identitiesOnly true"
assert_eq "null" "$(echo "$out" | jq -r .pairingCode)" "SSH mode nao emite pairingCode"

# Hooks suspend/resume: o guia exige que resume reemita o JSON de conexao, e o
# `doctor` exige o par completo. Ambos leem o workspace do mesmo payload que o
# destroy le.
payload=$(printf '%s' "$out" | jq -c '{recipeResult: .}')
printf '%s' "$payload" | ./recipes/suspend.sh "$REPO" >/dev/null 2>&1
assert_eq "" "$(podman ps --filter name=asb-recipe-test-agent --filter status=running -q)" \
  "suspend do recipe para o pod"
rout=$(printf '%s' "$payload" | ./recipes/resume.sh "$REPO" 2>/dev/null)
assert_eq "1" "$(echo "$rout" | wc -l)" "resume emite exatamente UMA linha"
assert_eq "ssh" "$(echo "$rout" | jq -r .connection.type)" "resume reemite a conexao ssh"
assert_eq "$(echo "$out" | jq -r .connection.target.port)" "$(echo "$rout" | jq -r .connection.target.port)" \
  "resume devolve a mesma porta que o create"

# O projectRoot vem do CLI, nao e montado no shell: e ele que decide onde a
# worktree irma do Orca vai cair, e um valor divergente coloca o trabalho do
# agente fora do que o host enxerga.
json=$(ORCA_VM_INSTANCE_ID="recipe-check-$$" "$ROOT/recipes/create.sh" "$REPO")
root=$(printf '%s' "$json" | jq -r .connection.projectRoot)
assert_contains "$HOME/asb-agent" "$root" \
  "o projectRoot esta sob ~/asb-agent, visivel no host"
assert_eq "1" "$(printf '%s' "$json" | jq -r '.schemaVersion')" \
  "schemaVersion e 1"
ORCA_VM_INSTANCE_ID="recipe-check-$$" "$ROOT/recipes/destroy.sh" "$REPO"
assert_eq "1" "$(podman container exists asb-recipe-check-$$-agent; echo $?)" \
  "destroy nao deixa container para tras"

report
