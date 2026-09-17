#!/usr/bin/env bash
# tests/test-toolcache.sh — o volume asb-toolcache sobrevive ao workspace e compartilha ferramentas mise e cache.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS_A="test-toolcache-a-$$"
WS_B="test-toolcache-b-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md
cat > mise.toml << 'EOF'
[tools]
EOF
git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() {
  # WS_MULTI e WS_FAIL nascem no meio do teste: sem eles aqui, o volume de
  # sessao de cada um ficava na maquina do operador.
  for ws in "$WS_A" "$WS_B" "${WS_MULTI:-}" "${WS_FAIL:-}"; do
    [ -n "$ws" ] || continue
    "$ROOT/cli/asb-agent" purge --workspace "$ws" --yes >/dev/null 2>&1
  done
  rm -rf "$(dirname "$REPO")"
}
trap cleanup EXIT

echo "== toolcache =="
UP_OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$REPO" 2>&1) || {
  echo "  ABORTADO: up falhou"; echo "$UP_OUT"; exit 1; }
A="asb-${WS_A}-agent"
require "o agente A responde" podman exec "$A" true

assert_contains "mise" "$UP_OUT" "asb-agent up detectou mise.toml e executou mise"

echo "-- symlinks para asb-toolcache --"
assert_eq "0" "$(podman exec "$A" sh -c "test -d /run/asb-toolcache; echo \$?")" \
  "/run/asb-toolcache esta montado"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.local/share/mise'; echo \$?")" \
  "~/.local/share/mise e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.cache'; echo \$?")" \
  "~/.cache e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.m2'; echo \$?")" \
  "~/.m2 e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.local/share/uv'; echo \$?")" \
  "~/.local/share/uv e um link para o volume"

# REGRESSAO: o entrypoint faz `rm -rf ~/.local/share/uv` antes de linkar o
# volume, e o `uv tool install` instala ali por padrao. Instalar o graphify no
# caminho default apagaria a instalacao no primeiro arranque, e o sintoma
# ("graphify nao existe") nao apontaria para o toolcache. Por isso as
# ferramentas vivem fora do home reciclado.
echo "-- ferramentas sobrevivem ao entrypoint --"
for bin in uv rtk graphify; do
  assert_eq "0" "$(podman exec -u 1000 "$A" bash -lc "$bin --version >/dev/null 2>&1; echo \$?")" \
    "$bin responde --version depois que o entrypoint reciclou o home"
done

# Escreve marcadores no toolcache via caminhos do usuario
podman exec "$A" sh -c "mkdir -p '$HOME/.local/share/mise' '$HOME/.cache' '$HOME/.m2' '$HOME/.local/share/uv' && \
  echo 'mise-cache-marca' > '$HOME/.local/share/mise/marker' && \
  echo 'cache-marca' > '$HOME/.cache/marker' && \
  echo 'm2-marca' > '$HOME/.m2/marker' && \
  echo 'uv-marca' > '$HOME/.local/share/uv/marker'"

"$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null

echo "-- outro workspace ve o mesmo cache --"
"$ROOT/cli/asb-agent" up --workspace "$WS_B" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up de B falhou"; exit 1; }
B="asb-${WS_B}-agent"
require "o agente B responde" podman exec "$B" true

assert_eq "mise-cache-marca" \
  "$(podman exec "$B" sh -c "cat '$HOME/.local/share/mise/marker'")" \
  "o diretorio do mise sobreviveu ao down e chegou ao workspace novo"
assert_eq "cache-marca" \
  "$(podman exec "$B" sh -c "cat '$HOME/.cache/marker'")" \
  "o diretorio ~/.cache sobreviveu ao down e chegou ao workspace novo"
assert_eq "m2-marca" \
  "$(podman exec "$B" sh -c "cat '$HOME/.m2/marker'")" \
  "o diretorio ~/.m2 sobreviveu ao down e chegou ao workspace novo"
assert_eq "uv-marca" \
  "$(podman exec "$B" sh -c "cat '$HOME/.local/share/uv/marker'")" \
  "o diretorio ~/.local/share/uv sobreviveu ao down e chegou ao workspace novo"

"$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null
assert_eq "0" "$(podman volume exists asb-toolcache; echo $?)" \
  "o volume asb-toolcache sobreviveu ao down"

echo "-- varredura em multiplos diretorios e falha no up --"
WS_MULTI="test-toolcache-multi-$$"
REPO_MULTI=$(mktemp -d)/proj-multi
mkdir -p "$REPO_MULTI/a/b" "$REPO_MULTI/node_modules/bad" && cd "$REPO_MULTI"
git init -q -b main . && git config user.email t@e.com && git config user.name T
cat > mise.toml << 'EOF'
[tools]
EOF
cat > a/mise.toml << 'EOF'
[tools]
EOF
cat > a/b/mise.toml << 'EOF'
[tools]
EOF
cat > node_modules/bad/mise.toml << 'EOF'
[tools]
EOF
git add -A && git commit -qm multi
cd "$ROOT"

MULTI_OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS_MULTI" --repo "$REPO_MULTI" 2>&1)
MULTI_RC=$?
assert_eq "0" "$MULTI_RC" "up multi-diretorio teve sucesso"
assert_contains "executando mise install em proj-multi" "$MULTI_OUT" "instalou na raiz"
assert_contains "executando mise install em a" "$MULTI_OUT" "instalou em subdiretorio a"
assert_contains "executando mise install em b" "$MULTI_OUT" "instalou em subdiretorio a/b"
if echo "$MULTI_OUT" | grep -q "executando mise install em bad"; then
  assert_eq "pruned" "executed" "diretorio node_modules deveria ter sido podado"
else
  assert_eq "pruned" "pruned" "diretorio node_modules foi podado da varredura"
fi
"$ROOT/cli/asb-agent" down --workspace "$WS_MULTI" >/dev/null 2>&1
rm -rf "$(dirname "$REPO_MULTI")"

echo "-- falha no mise install sai diferente de zero e preserva workspace --"
WS_FAIL="test-toolcache-fail-$$"
REPO_FAIL=$(mktemp -d)/proj-fail
mkdir -p "$REPO_FAIL" && cd "$REPO_FAIL"
git init -q -b main . && git config user.email t@e.com && git config user.name T
cat > mise.toml << 'EOF'
[tools]
ferramenta_inexistente_12345 = "latest"
EOF
git add -A && git commit -qm fail
cd "$ROOT"

FAIL_RC=0
FAIL_OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS_FAIL" --repo "$REPO_FAIL" 2>&1) || FAIL_RC=$?
if [ "$FAIL_RC" -ne 0 ]; then
  assert_eq "1" "1" "asb-agent up saiu com codigo diferente de zero quando mise install falhou"
else
  assert_eq "1" "0" "asb-agent up deveria ter falhado com codigo diferente de zero"
fi

if echo "$FAIL_OUT" | grep -q '"workspace":'; then
  assert_eq "sem-json" "com-json" "up nao deve emitir contrato de receita JSON quando falha"
else
  assert_eq "sem-json" "sem-json" "up nao emitiu contrato de receita JSON na falha"
fi

assert_eq "0" "$(podman exec "asb-${WS_FAIL}-agent" true >/dev/null 2>&1; echo $?)" \
  "workspace foi preservado no ar para inspecao e retry do operador"

"$ROOT/cli/asb-agent" down --workspace "$WS_FAIL" >/dev/null 2>&1
rm -rf "$(dirname "$REPO_FAIL")"

report
