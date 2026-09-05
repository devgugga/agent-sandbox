#!/usr/bin/env bash
# tests/test-auth.sh — a credencial sobrevive ao workspace e a imagem.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS_A="test-auth-a-$$"
WS_B="test-auth-b-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1
}
trap cleanup EXIT

echo "== credenciais =="
"$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }
A="asb-${WS_A}-agent"
require "o agente A responde" podman exec "$A" true

# O caminho real e um LINK para o volume: o refresh de token que o agente faz
# durante a sessao precisa aterrissar no volume, nao numa copia efemera.
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.claude/.credentials.json'; echo \$?")" \
  "a credencial do Claude e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'; echo \$?")" \
  "a credencial do Codex e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.local/share/keyrings'; echo \$?")" \
  "o keyring e um link para o volume"

# Escreve pelo CAMINHO REAL (como o agente faz) e confirma que aterrissou no
# volume. Se algum agente substituir o link por arquivo comum, este teste e o
# que acusa — e a correcao e trocar o link por bind mount do arquivo.
podman exec "$A" sh -c "printf 'marca-do-teste' > '$HOME/.codex/auth.json'"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'; echo \$?")" \
  "escrever pelo caminho real nao destruiu o link"

"$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null

echo "-- outro workspace ve a mesma credencial --"
"$ROOT/cli/asb-agent" up --workspace "$WS_B" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up de B falhou"; exit 1; }
B="asb-${WS_B}-agent"
require "o agente B responde" podman exec "$B" true
assert_eq "marca-do-teste" \
  "$(podman exec "$B" sh -c "cat '$HOME/.codex/auth.json'")" \
  "a credencial sobreviveu ao down e chegou ao workspace novo"

echo "-- o volume nao e removido por down nem por purge --"
"$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null
assert_eq "0" "$(podman volume exists asb-credentials; echo $?)" \
  "o volume de credenciais sobreviveu ao down"

report
