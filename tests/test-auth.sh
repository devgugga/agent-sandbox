#!/usr/bin/env bash
# tests/test-auth.sh — a credencial sobrevive ao workspace e a imagem.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS_A="test-auth-a-$$"
WS_B="test-auth-b-$$"
TEST_CRED_VOL="${ASB_CREDENTIALS_VOLUME:-asb-test-cred-$$}"
export ASB_CREDENTIALS_VOLUME="$TEST_CRED_VOL"
TEST_KEYRING_CONTAINER="${ASB_KEYRING_CONTAINER:-asb-keyring-test-auth-$$}"
TEST_RUN_VOL="${ASB_KEYRING_RUNTIME_VOLUME:-asb-run-test-auth-$$}"
export ASB_KEYRING_CONTAINER="$TEST_KEYRING_CONTAINER"
export ASB_KEYRING_RUNTIME_VOLUME="$TEST_RUN_VOL"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1 || true
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1 || true
  podman rm -f "asb-${WS_A}-agent" "asb-${WS_A}-proxy" "asb-${WS_B}-agent" "asb-${WS_B}-proxy" "$TEST_KEYRING_CONTAINER" >/dev/null 2>&1 || true
  podman volume rm -f "$TEST_CRED_VOL" "$TEST_RUN_VOL" >/dev/null 2>&1 || true
  rm -rf "$(dirname "$REPO")"
}
trap cleanup EXIT

echo "== credenciais =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }
A="asb-${WS_A}-agent"
require "o agente A responde" podman exec "$A" true

# O caminho real e um LINK para o volume: o refresh de token que o agente faz
# durante a sessao precisa aterrissar no volume, nao numa copia efemera.
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.claude/.credentials.json'; echo \$?")" \
  "a credencial do Claude e um link para o volume"
assert_eq "0" "$(podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'; echo \$?")" \
  "a credencial do Codex e um link para o volume"

# O cliente NÃO deve criar link para ~/.local/share/keyrings
assert_fails "o keyring nao e um link no container cliente" \
  podman exec -u 1000 "$A" sh -c 'test -L "$HOME/.local/share/keyrings"'

# O cliente não possui processos locais de Secret Service (D-Bus / keyring)
assert_fails "nenhum processo dbus-daemon rodando no container cliente" \
  podman exec "$A" pgrep -f dbus-daemon
assert_fails "nenhum processo gnome-keyring-daemon rodando no container cliente" \
  podman exec "$A" pgrep -f gnome-keyring-daemon

# DBUS_SESSION_BUS_ADDRESS propagado para podman exec, shell de login e PAM
assert_eq "unix:path=/run/asb-keyring/bus" \
  "$(podman exec -u 1000 "$A" sh -c 'echo "$DBUS_SESSION_BUS_ADDRESS"')" \
  "DBUS_SESSION_BUS_ADDRESS definido em podman exec"
assert_eq "unix:path=/run/asb-keyring/bus" \
  "$(podman exec -u 1000 "$A" bash -l -c 'echo "$DBUS_SESSION_BUS_ADDRESS"')" \
  "DBUS_SESSION_BUS_ADDRESS propagado para shell de login"
assert_contains "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus" \
  "$(podman exec "$A" cat /etc/environment)" \
  "DBUS_SESSION_BUS_ADDRESS presente em /etc/environment"

# DBUS_SESSION_BUS_ADDRESS propagado em sessão SSH
PORT=$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
SSH_KEY="$HOME/.config/agent-sandbox/id_ed25519"
ssh_dbus=$(ssh -i "$SSH_KEY" -p "$PORT" \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes \
  "$(id -un)@127.0.0.1" 'echo "$DBUS_SESSION_BUS_ADDRESS"' 2>/dev/null || true)
assert_eq "unix:path=/run/asb-keyring/bus" "$ssh_dbus" \
  "DBUS_SESSION_BUS_ADDRESS propagado em sessao SSH"

# Grava item sintético pelo Secret Service no cliente A
SYNTHETIC_SECRET="secret-auth-$$"
store_rc=0
printf '%s\n' "$SYNTHETIC_SECRET" | podman exec -i -u 1000 "$A" \
  secret-tool store --label="Test Secret" service "asb-test-auth" account "agent" >/dev/null 2>&1 || store_rc=$?
assert_eq "0" "$store_rc" "cliente A gravou segredo via Secret Service compartilhado"
assert_eq "$SYNTHETIC_SECRET" \
  "$(podman exec -u 1000 "$A" secret-tool lookup service "asb-test-auth" account "agent" 2>/dev/null || true)" \
  "cliente A le segredo gravado via Secret Service"

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
assert_eq "$SYNTHETIC_SECRET" \
  "$(podman exec -u 1000 "$B" secret-tool lookup service "asb-test-auth" account "agent" 2>/dev/null || true)" \
  "o segredo no Secret Service compartilhado sobreviveu ao down e foi lido pelo workspace B"

echo "-- o volume nao e removido por down nem por purge --"
"$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null
assert_eq "0" "$(podman volume exists "$TEST_CRED_VOL"; echo $?)" \
  "o volume de credenciais sobreviveu ao down"

report
