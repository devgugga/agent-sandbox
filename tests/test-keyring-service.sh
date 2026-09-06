#!/usr/bin/env bash
# tests/test-keyring-service.sh — validação de concorrência e persistência do Secret Service singleton.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

TEST_ID="test-keyring-$$"
TEST_CRED_VOL="${ASB_CREDENTIALS_VOLUME:-asb-cred-${TEST_ID}}"
TEST_RUN_VOL="${ASB_KEYRING_RUNTIME_VOLUME:-asb-run-${TEST_ID}}"
SERVICE_CONTAINER="${ASB_KEYRING_CONTAINER:-asb-svc-${TEST_ID}}"
CLIENT_A="asb-cli-a-${TEST_ID}"
CLIENT_B="asb-cli-b-${TEST_ID}"
CLIENT_C="asb-cli-c-${TEST_ID}"

PASS_FILE="${ASB_KEYRING_PASS_FILE:-}"
PASS_CREATED=0
if [ -z "$PASS_FILE" ]; then
  PASS_FILE=$(mktemp)
  printf 'synthetic-passphrase-%s\n' "$TEST_ID" > "$PASS_FILE"
  chmod 0600 "$PASS_FILE"
  PASS_CREATED=1
fi
PASS_CONTENT="$(cat "$PASS_FILE")"

IMAGE="${IMAGE:-agent-sandbox:latest}"

SYNTHETIC_SERVICE="asb-test"
SYNTHETIC_ACCOUNT="integration"
SYNTHETIC_SECRET="synthetic-secret-${TEST_ID}"

cleanup() {
  podman rm -f "$CLIENT_A" "$CLIENT_B" "$CLIENT_C" "$SERVICE_CONTAINER" >/dev/null 2>&1 || true
  podman volume rm -f "$TEST_CRED_VOL" "$TEST_RUN_VOL" >/dev/null 2>&1 || true
  if [ "$PASS_CREATED" -eq 1 ] && [ -f "$PASS_FILE" ]; then
    rm -f "$PASS_FILE"
  fi
}
trap cleanup EXIT

start_service() {
  podman run -d --name "$SERVICE_CONTAINER" \
    --network none \
    --stop-timeout 1 \
    --user 1000:1000 \
    --userns keep-id:uid=1000,gid=1000 \
    -v "$PASS_FILE:/run/asb-keyring-pass:ro,Z" \
    -v "$TEST_CRED_VOL:/run/asb-credentials:z" \
    -v "$TEST_RUN_VOL:/run/asb-keyring:z" \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
    --entrypoint /usr/local/bin/start-keyring.sh \
    "$IMAGE" >/dev/null
}

start_client() {
  local name="$1"
  podman run -d --name "$name" \
    --network none \
    --stop-timeout 1 \
    --userns keep-id:uid=1000,gid=1000 \
    -v "$TEST_RUN_VOL:/run/asb-keyring:ro,z" \
    -v "$TEST_CRED_VOL:/run/asb-credentials:z" \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
    "$IMAGE" sleep 3600 >/dev/null
}

echo "== 1. Criar volumes únicos de credenciais e runtime =="
podman volume create "$TEST_CRED_VOL" >/dev/null
podman volume create "$TEST_RUN_VOL" >/dev/null
assert_eq "0" "$(podman volume exists "$TEST_CRED_VOL"; echo $?)" "volume de teste de credenciais criado"
assert_eq "0" "$(podman volume exists "$TEST_RUN_VOL"; echo $?)" "volume de teste de runtime criado"

echo "== 2. Iniciar serviço global sob nome único =="
start_service

# Aguarda brevemente se o serviço precisa de tempo para inicializar
wait_for 3 podman exec -u 1000 "$SERVICE_CONTAINER" test -S /run/asb-keyring/bus || true

assert_eq "running" \
  "$(podman inspect "$SERVICE_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || echo 'missing')" \
  "o container do serviço keyring está em execução"

echo "== 3. Iniciar dois clientes simultâneos ligados ao mesmo socket =="
start_client "$CLIENT_A"
start_client "$CLIENT_B"

require "cliente A está ativo" podman exec "$CLIENT_A" true
require "cliente B está ativo" podman exec "$CLIENT_B" true

assert_eq "0" \
  "$(podman exec -u 1000 "$CLIENT_A" test -S /run/asb-keyring/bus >/dev/null 2>&1 && echo 0 || echo 1)" \
  "socket D-Bus /run/asb-keyring/bus está acessível no cliente A"

echo "== 4. Gravar item fictício com secret-tool no cliente A =="
store_rc=0
printf '%s\n' "$SYNTHETIC_SECRET" | podman exec -i -u 1000 "$CLIENT_A" \
  secret-tool store --label="Test Secret" service "$SYNTHETIC_SERVICE" account "$SYNTHETIC_ACCOUNT" >/dev/null 2>&1 || store_rc=$?
assert_eq "0" "$store_rc" "cliente A gravou o segredo sintético com secret-tool"

echo "== 5. Ler o mesmo item no cliente B =="
read_b="$(podman exec -u 1000 "$CLIENT_B" \
  secret-tool lookup service "$SYNTHETIC_SERVICE" account "$SYNTHETIC_ACCOUNT" 2>/dev/null || true)"
assert_eq "$SYNTHETIC_SECRET" "$read_b" "cliente B leu o segredo sintético gravado pelo cliente A"

echo "== 6. Verificar ausência de passphrase em inspect dos clientes A e B =="
assert_fails "nenhuma variavel ASB_KEYRING_PASS no ambiente do cliente A" \
  sh -c "podman inspect '$CLIENT_A' --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fq 'ASB_KEYRING_PASS'"
assert_fails "passphrase nao aparece em podman inspect do cliente A" \
  sh -c "podman inspect '$CLIENT_A' | grep -Fq '$PASS_CONTENT'"
assert_fails "nenhuma variavel ASB_KEYRING_PASS no ambiente do cliente B" \
  sh -c "podman inspect '$CLIENT_B' --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fq 'ASB_KEYRING_PASS'"
assert_fails "passphrase nao aparece em podman inspect do cliente B" \
  sh -c "podman inspect '$CLIENT_B' | grep -Fq '$PASS_CONTENT'"

echo "== 7. Remover clientes, reiniciar serviço e ler item no cliente C =="
podman rm -f "$CLIENT_A" "$CLIENT_B" >/dev/null 2>&1 || true

podman restart "$SERVICE_CONTAINER" >/dev/null 2>&1 || {
  podman start "$SERVICE_CONTAINER" >/dev/null 2>&1 || true
}
wait_for 3 podman exec -u 1000 "$SERVICE_CONTAINER" test -S /run/asb-keyring/bus || true

start_client "$CLIENT_C"
require "cliente C está ativo" podman exec "$CLIENT_C" true

read_c="$(podman exec -u 1000 "$CLIENT_C" \
  secret-tool lookup service "$SYNTHETIC_SERVICE" account "$SYNTHETIC_ACCOUNT" 2>/dev/null || true)"
assert_eq "$SYNTHETIC_SECRET" "$read_c" "cliente C leu o segredo sintético após reinício do serviço"

assert_fails "nenhuma variavel ASB_KEYRING_PASS no ambiente do cliente C" \
  sh -c "podman inspect '$CLIENT_C' --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fq 'ASB_KEYRING_PASS'"
assert_fails "passphrase nao aparece em podman inspect do cliente C" \
  sh -c "podman inspect '$CLIENT_C' | grep -Fq '$PASS_CONTENT'"

report
