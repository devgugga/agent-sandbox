#!/usr/bin/env bash
# tests/test-recipe.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source tests/assert.sh

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
a=$(ORCA_VM_INSTANCE_ID=test-vm-a bash -c 'source <(sed -n "/^asb_workspace_id()/,/^}/p" recipes/common.sh); asb_workspace_id /tmp/proj')
b=$(ORCA_VM_INSTANCE_ID=test-vm-b bash -c 'source <(sed -n "/^asb_workspace_id()/,/^}/p" recipes/common.sh); asb_workspace_id /tmp/proj')
assert_eq "test-vm-a" "$a" "usa ORCA_VM_INSTANCE_ID quando presente"
[ "$a" != "$b" ] && { echo "  ok: workspaces distintos geram nomes distintos"; _pass=$((_pass+1)); } \
                 || { echo "  FALHOU: nomes colidem entre workspaces"; _fail=$((_fail+1)); }

# O Orca aninha o resultado do create em recipeResult; ler so .userData nao
# encontra o nome e deixa o pod orfao.
nested=$(printf '{"recipeResult":{"userData":{"workspace":"test-vm-nested"}}}' \
  | bash -c 'payload=$(cat); jq -r ".recipeResult.userData.workspace // .userData.workspace // empty" <<<"$payload"')
assert_eq "test-vm-nested" "$nested" "destroy le workspace de recipeResult.userData"
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
# O piloto integrado executa o resume de producao com CLI, SSH e systemd
# reais, incluindo falha sem JSON e teardown. Todos os recursos pertencem a
# test-startuprecipe-<uuid>/asb-test-*; nao usa volumes globais de credenciais.
if python3 -B -m unittest \
  tests.integration.test_startup_auth.TestStartupAuth.test_recipe_resume_reads_cli_json_and_suppresses_failure -v; then
  _pass=$((_pass+1))
else
  _fail=$((_fail+1))
fi

report
