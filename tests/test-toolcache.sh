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
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1
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

report
