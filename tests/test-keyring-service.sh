#!/usr/bin/env bash
# tests/test-keyring-service.sh — validação de concorrência e persistência do Secret Service singleton.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

TEST_ID="test-keyring-$$-$(date +%s%N 2>/dev/null || date +%s)"
TEST_CRED_VOL="test-cred-${TEST_ID}"
TEST_KEYRING_DATA_VOL="test-kdata-${TEST_ID}"
TEST_RUN_VOL="test-run-${TEST_ID}"
SERVICE_CONTAINER="test-svc-${TEST_ID}"
CLIENT_A="test-cli-a-${TEST_ID}"
CLIENT_B="test-cli-b-${TEST_ID}"
CLIENT_C="test-cli-c-${TEST_ID}"
MIGRATE_DATA_VOL="test-kdata-mig-${TEST_ID}"
MIGRATE_RUN_VOL="test-run-mig-${TEST_ID}"
MIGRATE_SVC="test-svc-mig-${TEST_ID}"
UPGRADE_SVC="test-svc-upg-${TEST_ID}"
UPGRADE_DATA_VOL="test-kdata-upg-${TEST_ID}"
UPGRADE_RUN_VOL="test-run-upg-${TEST_ID}"

# Abortar imediatamente antes de qualquer mutação se algum nome coincidir com recursos de produção
for res in "$TEST_CRED_VOL" "$TEST_KEYRING_DATA_VOL" "$TEST_RUN_VOL" "$SERVICE_CONTAINER" \
           "$CLIENT_A" "$CLIENT_B" "$CLIENT_C" "$MIGRATE_DATA_VOL" "$MIGRATE_RUN_VOL" "$MIGRATE_SVC" \
           "$UPGRADE_SVC" "$UPGRADE_DATA_VOL" "$UPGRADE_RUN_VOL"; do
  case "$res" in
    asb-credentials|asb-keyring|asb-keyring-runtime|asb-keyring-data|asb-toolcache)
      echo "ERRO FATAL: recurso de teste coincide com producao: $res" >&2
      exit 1
      ;;
  esac
done

REAL_PASS="$HOME/.config/agent-sandbox/keyring.pass"
if [ "${ASB_KEYRING_PASS_FILE:-}" = "$REAL_PASS" ]; then
  echo "ERRO FATAL: teste nao pode apontar para o passfile real: $REAL_PASS" >&2
  exit 1
fi

export ASB_CREDENTIALS_VOLUME="$TEST_CRED_VOL"
export ASB_KEYRING_DATA_VOLUME="$TEST_KEYRING_DATA_VOL"
export ASB_KEYRING_RUNTIME_VOLUME="$TEST_RUN_VOL"
export ASB_KEYRING_CONTAINER="$SERVICE_CONTAINER"

# Criar sempre um passfile sintético temporário e nunca usar credenciais reais do host
PASS_FILE=$(mktemp "${TMPDIR:-/tmp}/asb-test-pass-XXXXXX")
printf 'synthetic-passphrase-%s\n' "$TEST_ID" > "$PASS_FILE"
chmod 0600 "$PASS_FILE"
export ASB_KEYRING_PASS_FILE="$PASS_FILE"
PASS_CONTENT="$(cat "$PASS_FILE")"

IMAGE="${IMAGE:-agent-sandbox:latest}"

SYNTHETIC_SERVICE="asb-test"
SYNTHETIC_ACCOUNT="integration"
SYNTHETIC_SECRET="synthetic-secret-${TEST_ID}"

cleanup() {
  podman rm -f "$CLIENT_A" "$CLIENT_B" "$CLIENT_C" "$SERVICE_CONTAINER" "$MIGRATE_SVC" "$UPGRADE_SVC" >/dev/null 2>&1 || true
  podman volume rm -f "$TEST_CRED_VOL" "$TEST_RUN_VOL" "$TEST_KEYRING_DATA_VOL" "$MIGRATE_DATA_VOL" "$MIGRATE_RUN_VOL" "$UPGRADE_DATA_VOL" "$UPGRADE_RUN_VOL" >/dev/null 2>&1 || true
  if [ -f "$PASS_FILE" ]; then
    rm -f "$PASS_FILE"
  fi
}
trap cleanup EXIT

start_service() {
  podman run -d --name "$SERVICE_CONTAINER" \
    --label "asb.keyring.schema=2" \
    --network none \
    --stop-timeout 1 \
    --user 1000:1000 \
    --userns keep-id:uid=1000,gid=1000 \
    -v "$PASS_FILE:/run/asb-keyring-pass:ro,Z" \
    -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" \
    -v "$TEST_KEYRING_DATA_VOL:/run/asb-keyring-data:z" \
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
    --mount type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000 \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
    "$IMAGE" sleep 3600 >/dev/null
}

echo "== 1. Criar volumes únicos de credenciais, dados do keyring e runtime =="
podman volume create "$TEST_CRED_VOL" >/dev/null
podman volume create "$TEST_KEYRING_DATA_VOL" >/dev/null
podman volume create "$TEST_RUN_VOL" >/dev/null
assert_eq "0" "$(podman volume exists "$TEST_CRED_VOL"; echo $?)" "volume de teste de credenciais criado"
assert_eq "0" "$(podman volume exists "$TEST_KEYRING_DATA_VOL"; echo $?)" "volume de teste de dados do keyring criado"
assert_eq "0" "$(podman volume exists "$TEST_RUN_VOL"; echo $?)" "volume de teste de runtime criado"

echo "== 2. Iniciar serviço global sob nome único =="
start_service

# Aguarda brevemente se o serviço precisa de tempo para inicializar
wait_for 5 podman exec -u 1000 "$SERVICE_CONTAINER" test -S /run/asb-keyring/bus || true

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
assert_eq "0" \
  "$(podman exec -u 1000 "$CLIENT_B" test -S /run/asb-keyring/bus >/dev/null 2>&1 && echo 0 || echo 1)" \
  "socket D-Bus /run/asb-keyring/bus está acessível no cliente B"

# Controle positivo: o serviço singleton possui dbus-daemon e gnome-keyring-daemon
require "serviço singleton possui dbus-daemon" podman exec "$SERVICE_CONTAINER" pgrep -f dbus-daemon
require "serviço singleton possui gnome-keyring-daemon" podman exec "$SERVICE_CONTAINER" pgrep -f gnome-keyring-daemon

# Clientes NAO possuem daemons locais de Secret Service
assert_fails "cliente A nao possui processo dbus-daemon proprio" \
  podman exec "$CLIENT_A" pgrep -f dbus-daemon
assert_fails "cliente A nao possui processo gnome-keyring-daemon proprio" \
  podman exec "$CLIENT_A" pgrep -f gnome-keyring-daemon
assert_fails "cliente B nao possui processo dbus-daemon proprio" \
  podman exec "$CLIENT_B" pgrep -f dbus-daemon
assert_fails "cliente B nao possui processo gnome-keyring-daemon proprio" \
  podman exec "$CLIENT_B" pgrep -f gnome-keyring-daemon

# Clientes recebem DBUS_SESSION_BUS_ADDRESS em exec, login shell e /etc/environment
assert_eq "unix:path=/run/asb-keyring/bus" \
  "$(podman exec -u 1000 "$CLIENT_A" sh -c 'echo "$DBUS_SESSION_BUS_ADDRESS"')" \
  "cliente A recebe DBUS_SESSION_BUS_ADDRESS em exec"
assert_eq "unix:path=/run/asb-keyring/bus" \
  "$(podman exec -u 1000 "$CLIENT_A" bash -l -c 'echo "$DBUS_SESSION_BUS_ADDRESS"')" \
  "cliente A recebe DBUS_SESSION_BUS_ADDRESS em shell de login"
assert_contains "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus" \
  "$(podman exec "$CLIENT_A" cat /etc/environment)" \
  "cliente A possui DBUS_SESSION_BUS_ADDRESS em /etc/environment"

# Clientes NAO criam link para ~/.local/share/keyrings
assert_fails "cliente A nao possui link para ~/.local/share/keyrings" \
  podman exec -u 1000 "$CLIENT_A" sh -c 'test -L "$HOME/.local/share/keyrings"'
assert_fails "cliente B nao possui link para ~/.local/share/keyrings" \
  podman exec -u 1000 "$CLIENT_B" sh -c 'test -L "$HOME/.local/share/keyrings"'

# Clientes NAO possuem montagem de dados do keyring
assert_fails "cliente A nao possui montagem de dados do keyring" \
  podman exec "$CLIENT_A" test -e /run/asb-keyring-data
assert_fails "cliente B nao possui montagem de dados do keyring" \
  podman exec "$CLIENT_B" test -e /run/asb-keyring-data
assert_eq "0" "$(podman exec "$SERVICE_CONTAINER" test -d /run/asb-keyring-data/keyrings; echo $?)" \
  "serviço singleton possui diretório /run/asb-keyring-data/keyrings"

# Clientes mantêm links de credenciais isoladas (claude e codex)
assert_eq "0" "$(podman exec -u 1000 "$CLIENT_A" sh -c 'test -L "$HOME/.claude/.credentials.json"; echo $?')" \
  "cliente A mantem link de credencial do Claude"
assert_eq "0" "$(podman exec -u 1000 "$CLIENT_A" sh -c 'test -L "$HOME/.codex/auth.json"; echo $?')" \
  "cliente A mantem link de credencial do Codex"

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
wait_for 5 podman exec -u 1000 "$SERVICE_CONTAINER" test -S /run/asb-keyring/bus || true

start_client "$CLIENT_C"
require "cliente C está ativo" podman exec "$CLIENT_C" true

read_c="$(podman exec -u 1000 "$CLIENT_C" \
  secret-tool lookup service "$SYNTHETIC_SERVICE" account "$SYNTHETIC_ACCOUNT" 2>/dev/null || true)"
assert_eq "$SYNTHETIC_SECRET" "$read_c" "cliente C leu o segredo sintético após reinício do serviço"

assert_fails "nenhuma variavel ASB_KEYRING_PASS no ambiente do cliente C" \
  sh -c "podman inspect '$CLIENT_C' --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fq 'ASB_KEYRING_PASS'"
assert_fails "passphrase nao aparece em podman inspect do cliente C" \
  sh -c "podman inspect '$CLIENT_C' | grep -Fq '$PASS_CONTENT'"
assert_fails "cliente C nao possui processo dbus-daemon proprio" \
  podman exec "$CLIENT_C" pgrep -f dbus-daemon
assert_fails "cliente C nao possui processo gnome-keyring-daemon proprio" \
  podman exec "$CLIENT_C" pgrep -f gnome-keyring-daemon
assert_fails "cliente C nao possui link para ~/.local/share/keyrings" \
  podman exec -u 1000 "$CLIENT_C" sh -c 'test -L "$HOME/.local/share/keyrings"'
assert_fails "cliente C nao possui montagem de dados do keyring" \
  podman exec "$CLIENT_C" test -e /run/asb-keyring-data

podman rm -f "$CLIENT_C" "$SERVICE_CONTAINER" >/dev/null 2>&1 || true

echo "== 8. Teste de migração do keyring legado e recuperação de migração parcial =="
# Simula dados legados existentes em /run/asb-credentials/keyrings
podman run --rm -v "$TEST_CRED_VOL:/run/asb-credentials:z" "$IMAGE" \
  sh -c "mkdir -p /run/asb-credentials/keyrings && echo 'legacy-token-data' > /run/asb-credentials/keyrings/legacy.keyring && echo 'complete-token-data' > /run/asb-credentials/keyrings/partial.keyring && chmod 0600 /run/asb-credentials/keyrings/*.keyring"

# Cria novo volume de dados pré-populado com destino parcial e SEM marcador .migration_done
podman volume create "$MIGRATE_DATA_VOL" >/dev/null
podman run --rm -v "$MIGRATE_DATA_VOL:/run/asb-keyring-data:z" "$IMAGE" \
  sh -c "mkdir -p /run/asb-keyring-data/keyrings && echo 'stale-partial-data' > /run/asb-keyring-data/keyrings/partial.keyring && chmod 0700 /run/asb-keyring-data/keyrings"

# Cria volume de runtime exclusivo para não interferir no singleton ativo
podman volume create "$MIGRATE_RUN_VOL" >/dev/null

podman run -d --name "$MIGRATE_SVC" \
  --label "asb.keyring.schema=2" \
  --network none \
  --stop-timeout 1 \
  --user 1000:1000 \
  --userns keep-id:uid=1000,gid=1000 \
  -v "$PASS_FILE:/run/asb-keyring-pass:ro,Z" \
  -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" \
  -v "$MIGRATE_DATA_VOL:/run/asb-keyring-data:z" \
  -v "$MIGRATE_RUN_VOL:/run/asb-keyring:z" \
  -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
  --entrypoint /usr/local/bin/start-keyring.sh \
  "$IMAGE" >/dev/null

wait_for 5 podman exec -u 1000 "$MIGRATE_SVC" test -S /run/asb-keyring/bus || true

# O arquivo legado foi migrado para o novo volume de dados
migrated_content="$(podman exec "$MIGRATE_SVC" cat /run/asb-keyring-data/keyrings/legacy.keyring 2>/dev/null || true)"
assert_eq "legacy-token-data" "$migrated_content" "dados legados migrados com sucesso para volume de dados"

# O arquivo parcial foi atualizado com sucesso pela recuperação
migrated_partial="$(podman exec "$MIGRATE_SVC" cat /run/asb-keyring-data/keyrings/partial.keyring 2>/dev/null || true)"
assert_eq "complete-token-data" "$migrated_partial" "migracao parcial retomada e completada com sucesso"

# Marcador de conclusão foi gravado
assert_eq "0" "$(podman exec "$MIGRATE_SVC" test -f /run/asb-keyring-data/.migration_done; echo $?)" \
  "marcador de conclusao de migracao criado com sucesso"

# O arquivo legado no volume original NÃO foi apagado (preservação de compatibilidade)
original_content="$(podman run --rm --entrypoint cat -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" "$IMAGE" /run/asb-credentials/keyrings/legacy.keyring 2>/dev/null || true)"
assert_eq "legacy-token-data" "$original_content" "dados legados preservados no volume de credenciais sem remocao automatica"

podman rm -f "$MIGRATE_SVC" >/dev/null 2>&1 || true
podman volume rm -f "$MIGRATE_DATA_VOL" "$MIGRATE_RUN_VOL" >/dev/null 2>&1 || true

echo "== 9. Teste de upgrade automático schema 1 -> schema 2 =="
podman rm -f "$UPGRADE_SVC" >/dev/null 2>&1 || true
podman volume rm -f "$UPGRADE_DATA_VOL" "$UPGRADE_RUN_VOL" >/dev/null 2>&1 || true

# Cria container inicial com schema 1 e contrato legado (sem volume de dados dedicado, credenciais RW)
podman run -d --name "$UPGRADE_SVC" \
  --label "asb.keyring.schema=1" \
  --network none \
  --stop-timeout 1 \
  --user 1000:1000 \
  --userns keep-id:uid=1000,gid=1000 \
  -v "$PASS_FILE:/run/asb-keyring-pass:ro,Z" \
  -v "$TEST_CRED_VOL:/run/asb-credentials:z" \
  -v "$UPGRADE_RUN_VOL:/run/asb-keyring:z" \
  -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
  --entrypoint /usr/local/bin/start-keyring.sh \
  "$IMAGE" >/dev/null

assert_eq "1" "$(podman inspect "$UPGRADE_SVC" --format '{{index .Config.Labels "asb.keyring.schema"}}')" \
  "container inicial possui schema 1"
assert_fails "container inicial nao possui asb-keyring-data montado" \
  podman exec "$UPGRADE_SVC" test -d /run/asb-keyring-data

# Executa ensure_keyring_service apontando para o container UPGRADE_SVC com volume de dados e runtime dedicados
UPG_OUT=$(ASB_KEYRING_CONTAINER="$UPGRADE_SVC" \
          ASB_KEYRING_DATA_VOLUME="$UPGRADE_DATA_VOL" \
          ASB_KEYRING_RUNTIME_VOLUME="$UPGRADE_RUN_VOL" \
          python3 -c "from cli.asb.lifecycle import ensure_keyring_service; print(ensure_keyring_service())")
assert_eq "$UPGRADE_SVC" "$UPG_OUT" "ensure_keyring_service concluiu upgrade com sucesso"

# Valida schema 2
assert_eq "2" "$(podman inspect "$UPGRADE_SVC" --format '{{index .Config.Labels "asb.keyring.schema"}}')" \
  "container atualizado possui schema 2"

# Valida contratos de montagem:
# asb-credentials: ro (RW == false)
assert_eq "false" "$(podman inspect "$UPGRADE_SVC" --format '{{range .Mounts}}{{if eq .Destination "/run/asb-credentials"}}{{println .RW}}{{end}}{{end}}')" \
  "volume de credenciais montado como somente leitura apos upgrade"
# asb-keyring-data: rw (RW == true)
assert_eq "true" "$(podman inspect "$UPGRADE_SVC" --format '{{range .Mounts}}{{if eq .Destination "/run/asb-keyring-data"}}{{println .RW}}{{end}}{{end}}')" \
  "volume de dados do keyring montado como leitura/escrita apos upgrade"
# asb-keyring: rw (RW == true)
assert_eq "true" "$(podman inspect "$UPGRADE_SVC" --format '{{range .Mounts}}{{if eq .Destination "/run/asb-keyring"}}{{println .RW}}{{end}}{{end}}')" \
  "volume de runtime do keyring montado como leitura/escrita apos upgrade"

# Valida que dados legados foram migrados e continuam acessíveis no serviço
mig_upg="$(podman exec "$UPGRADE_SVC" cat /run/asb-keyring-data/keyrings/legacy.keyring 2>/dev/null || true)"
assert_eq "legacy-token-data" "$mig_upg" "credenciais legadas migradas e disponiveis no servico apos upgrade"

# Valida que dados legados foram preservados na origem
orig_upg="$(podman run --rm --entrypoint cat -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" "$IMAGE" /run/asb-credentials/keyrings/legacy.keyring 2>/dev/null || true)"
assert_eq "legacy-token-data" "$orig_upg" "credenciais legadas preservadas na origem apos upgrade"

podman rm -f "$UPGRADE_SVC" >/dev/null 2>&1 || true
podman volume rm -f "$UPGRADE_DATA_VOL" "$UPGRADE_RUN_VOL" >/dev/null 2>&1 || true

report
