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

# ==============================================================================
# Cobertura dos quatro hooks Orca (create -> suspend -> resume -> destroy)
# executando os scripts de producao verbatim sobre raiz efemera com stub de CLI
# estrito e stateful, sem tocar recursos de producao ou volumes globais.
# ==============================================================================
STAGE=$(mktemp -d -t asb-test-recipe-XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/recipes" "$STAGE/cli" "$STAGE/config/agent-sandbox" "$STAGE/repo"
cp "$ROOT/recipes/"*.sh "$STAGE/recipes/"
git -C "$STAGE/repo" init -q

ssh-keygen -q -t ed25519 -N "" -f "$STAGE/config/agent-sandbox/id_ed25519"
export XDG_CONFIG_HOME="$STAGE/config"
export RECIPE_STAGE="$STAGE"

cat << 'EOF' > "$STAGE/cli/asb-agent"
#!/usr/bin/env python3
import sys, os, json
from pathlib import Path

stage = Path(os.environ["RECIPE_STAGE"])
state_file = stage / "state.json"
invocations_file = stage / "invocations.jsonl"

args = sys.argv[1:]
with invocations_file.open("a") as f:
    f.write(json.dumps(args) + "\n")

state = json.loads(state_file.read_text()) if state_file.exists() else {"workspaces": {}}

if not args:
    sys.stderr.write("asb-agent stub: no arguments\n")
    sys.exit(2)

cmd = args[0]
if cmd == "up":
    if len(args) != 5 or args[1] != "--workspace" or args[3] != "--repo":
        sys.stderr.write(f"asb-agent stub: invalid up args: {args}\n")
        sys.exit(2)
    ws = args[2]
    repo = args[4]
    if not ws.startswith("test-"):
        sys.stderr.write(f"asb-agent stub: workspace {ws} must start with test-\n")
        sys.exit(2)
    if os.environ.get("STUB_FAIL_UP") == "1":
        sys.stderr.write("asb-agent: falha simulada no up\n")
        sys.exit(1)
    port = state["workspaces"].get(ws, {}).get("port", 44222)
    project_root = f"{stage}/repo"
    state["workspaces"][ws] = {
        "status": "running",
        "port": port,
        "project_root": project_root,
        "repo": repo,
    }
    state_file.write_text(json.dumps(state))
    print(json.dumps({"schemaVersion": 1, "port": port, "project_root": project_root}))
    sys.exit(0)

elif cmd == "suspend":
    if len(args) != 3 or args[1] != "--workspace":
        sys.stderr.write(f"asb-agent stub: invalid suspend args: {args}\n")
        sys.exit(2)
    ws = args[2]
    if not ws.startswith("test-"):
        sys.stderr.write(f"asb-agent stub: workspace {ws} must start with test-\n")
        sys.exit(2)
    if ws not in state["workspaces"]:
        sys.stderr.write(f"asb-agent: workspace {ws} not found\n")
        sys.exit(2)
    state["workspaces"][ws]["status"] = "stopped"
    state_file.write_text(json.dumps(state))
    sys.stderr.write(f"asb-agent: {ws} suspended\n")
    sys.exit(0)

elif cmd == "resume":
    if len(args) != 3 or args[1] != "--workspace":
        sys.stderr.write(f"asb-agent stub: invalid resume args: {args}\n")
        sys.exit(2)
    ws = args[2]
    if not ws.startswith("test-"):
        sys.stderr.write(f"asb-agent stub: workspace {ws} must start with test-\n")
        sys.exit(2)
    if os.environ.get("STUB_FAIL_RESUME") == "1":
        sys.stderr.write("asb-agent: falha simulada no resume\n")
        sys.exit(1)
    if ws not in state["workspaces"]:
        sys.stderr.write(f"asb-agent: workspace {ws} not found\n")
        sys.exit(2)
    entry = state["workspaces"][ws]
    entry["status"] = "running"
    state_file.write_text(json.dumps(state))
    print(json.dumps({"schemaVersion": 1, "port": entry["port"], "project_root": entry["project_root"]}))
    sys.exit(0)

elif cmd == "down":
    if len(args) != 3 or args[1] != "--workspace":
        sys.stderr.write(f"asb-agent stub: invalid down args: {args}\n")
        sys.exit(2)
    ws = args[2]
    if not ws.startswith("test-"):
        sys.stderr.write(f"asb-agent stub: workspace {ws} must start with test-\n")
        sys.exit(2)
    if ws in state["workspaces"]:
        del state["workspaces"][ws]
    state_file.write_text(json.dumps(state))
    sys.stderr.write(f"asb-agent: {ws} removed\n")
    sys.exit(0)

else:
    sys.stderr.write(f"asb-agent stub: unexpected command {cmd}\n")
    sys.exit(2)
EOF
chmod 0755 "$STAGE/cli/asb-agent"

# 1. create emite exatamente uma linha JSON schema 1 e carrega port/projectRoot do CLI
out=$(ORCA_WORKSPACE_ID="test-recipe-ws" "$STAGE/recipes/create.sh" "$STAGE/repo" 2>/dev/null)
assert_eq "1" "$(echo "$out" | wc -l)" "create emite exatamente UMA linha"
echo "$out" | jq -e . >/dev/null && { echo "  ok: create emite JSON valido"; _pass=$((_pass+1)); } || { echo "  FALHOU: JSON invalido"; _fail=$((_fail+1)); }
assert_eq "1" "$(echo "$out" | jq -r .schemaVersion)" "create schemaVersion 1"
assert_eq "ssh" "$(echo "$out" | jq -r .connection.type)" "create connection.type ssh"
assert_eq "127.0.0.1" "$(echo "$out" | jq -r .connection.target.host)" "create host loopback"
assert_eq "44222" "$(echo "$out" | jq -r .connection.target.port)" "create porta vinda do CLI"
assert_eq "$STAGE/repo" "$(echo "$out" | jq -r .connection.projectRoot)" "create projectRoot vindo do CLI"
assert_eq "true" "$(echo "$out" | jq -r .connection.target.identitiesOnly)" "create identitiesOnly true"
assert_eq "$STAGE/config/agent-sandbox/id_ed25519" "$(echo "$out" | jq -r .connection.target.identityFile)" "create identityFile efemero"
assert_eq "null" "$(echo "$out" | jq -r .pairingCode)" "create sem pairingCode"

# 2. suspend muda o estado sintético para parado
payload=$(printf '%s' "$out" | jq -c '{recipeResult: .}')
printf '%s' "$payload" | "$STAGE/recipes/suspend.sh" "$STAGE/repo" >/dev/null 2>&1
assert_eq "stopped" "$(jq -r '.workspaces["test-recipe-ws"].status' "$STAGE/state.json")" \
  "suspend muda o estado isolado para parado"

# 3. resume restaura o estado para running, preserva a mesma porta e emite uma linha
rout=$(printf '%s' "$payload" | "$STAGE/recipes/resume.sh" "$STAGE/repo" 2>/dev/null)
assert_eq "1" "$(echo "$rout" | wc -l)" "resume emite exatamente UMA linha"
assert_eq "running" "$(jq -r '.workspaces["test-recipe-ws"].status' "$STAGE/state.json")" \
  "resume restaura o estado para running"
assert_eq "$(echo "$out" | jq -r .connection.target.port)" "$(echo "$rout" | jq -r .connection.target.port)" \
  "resume preserva a mesma porta que o create"
assert_eq "$STAGE/repo" "$(echo "$rout" | jq -r .connection.projectRoot)" \
  "resume preserva projectRoot vindo do CLI"

# 4. destroy lê recipeResult.userData.workspace, remove o estado e não deixa órfãos
printf '%s' "$payload" | "$STAGE/recipes/destroy.sh" "$STAGE/repo" >/dev/null 2>&1
assert_eq "null" "$(jq -r '.workspaces["test-recipe-ws"]' "$STAGE/state.json")" \
  "destroy remove o workspace do estado"
assert_eq "0" "$(jq '.workspaces | length' "$STAGE/state.json")" \
  "destroy nao deixa orfaos no estado"

# 5. falha do CLI em create/resume não emite JSON de conexão
fout_up=$(STUB_FAIL_UP=1 ORCA_WORKSPACE_ID="test-fail-ws" "$STAGE/recipes/create.sh" "$STAGE/repo" 2>/dev/null || true)
assert_eq "" "$fout_up" "create com falha no CLI nao emite JSON de conexao"

fout_resume=$(STUB_FAIL_RESUME=1 printf '%s' "$payload" | "$STAGE/recipes/resume.sh" "$STAGE/repo" 2>/dev/null || true)
assert_eq "" "$fout_resume" "resume com falha no CLI nao emite JSON de conexao"

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
