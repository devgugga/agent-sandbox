#!/usr/bin/env bash
# tests/test-auth.sh — a credencial sobrevive ao workspace e a imagem.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

TEST_ID="test-auth-$$-$(date +%s%N 2>/dev/null || date +%s)"
WS_A="test-a-${TEST_ID}"
WS_B="test-b-${TEST_ID}"
TEST_CRED_VOL="asb-test-cred-${TEST_ID}"
TEST_KEYRING_DATA_VOL="asb-test-kdata-${TEST_ID}"
TEST_RUN_VOL="asb-test-run-${TEST_ID}"
TEST_KEYRING_CONTAINER="asb-test-keyring-${TEST_ID}"
TEST_PASS_FILE=$(mktemp "${TMPDIR:-/tmp}/asb-test-auth-pass-XXXXXX")
printf 'synthetic-pass-%s\n' "$TEST_ID" > "$TEST_PASS_FILE"
chmod 0600 "$TEST_PASS_FILE"

REAL_PASS="$HOME/.config/agent-sandbox/keyring.pass"
if [ "${ASB_KEYRING_PASS_FILE:-}" = "$REAL_PASS" ]; then
  echo "ERRO FATAL: teste nao pode apontar para o passfile real: $REAL_PASS" >&2
  exit 1
fi

# Abortar imediatamente se algum nome coincidir com recursos de produção
TEST_LOGIN_CONTAINER="asb-test-login-${TEST_ID}"
for res in "$TEST_CRED_VOL" "$TEST_RUN_VOL" "$TEST_KEYRING_DATA_VOL" "$TEST_KEYRING_CONTAINER" "$TEST_LOGIN_CONTAINER"; do
  case "$res" in
    asb-credentials|asb-keyring|asb-keyring-runtime|asb-keyring-data|asb-toolcache|asb-login)
      echo "ERRO FATAL: recurso de teste coincide com producao: $res" >&2
      exit 1
      ;;
  esac
done

export ASB_CREDENTIALS_VOLUME="$TEST_CRED_VOL"
export ASB_KEYRING_CONTAINER="$TEST_KEYRING_CONTAINER"
export ASB_KEYRING_RUNTIME_VOLUME="$TEST_RUN_VOL"
export ASB_KEYRING_DATA_VOLUME="$TEST_KEYRING_DATA_VOL"
export ASB_KEYRING_PASS_FILE="$TEST_PASS_FILE"
# Emenda A: `up` instala unidades systemd reais. Nome de teste para a espera
# por rede; o keyring ja e isolado por ASB_KEYRING_CONTAINER.
export ASB_NETWORK_UNIT="asb-test-network-${TEST_ID}.service"
UNIT_DIR="${ASB_SYSTEMD_UNIT_DIR:-$HOME/.config/systemd/user}"
IMAGE="${IMAGE:-agent-sandbox:latest}"

REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

# Prepara arquivo sentinela legado no volume de credenciais para comprovar isolamento do cliente.
# Os flags espelham keyring.py: `--user 1000 --userns keep-id:uid=1000,gid=1000` faz o uid do
# namespace coincidir com o do host, e `--entrypoint sh` evita o `chown` do entrypoint. Sem isso o
# preparo grava com uid de namespace que no host vira 100999/100000, e entao `ensure_credential_dirs`
# — que cria os diretorios PELO HOST — falha com EACCES, ou o singleton nao consegue ler o sentinela.
podman volume create "$TEST_CRED_VOL" >/dev/null
podman run --rm --user 1000 --userns keep-id:uid=1000,gid=1000 --entrypoint sh \
  -v "$TEST_CRED_VOL:/run/asb-credentials:z" "$IMAGE" \
  -c "mkdir -p /run/asb-credentials/keyrings && echo 'sentinel-secret-token' > /run/asb-credentials/keyrings/sentinel.keyring && chmod 0600 /run/asb-credentials/keyrings/sentinel.keyring"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1 || true
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1 || true
  for unit in "${TEST_KEYRING_CONTAINER}.service" "$ASB_NETWORK_UNIT"; do
    systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$unit"
  done
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  podman rm -f "asb-${WS_A}-agent" "asb-${WS_A}-proxy" "asb-${WS_B}-agent" "asb-${WS_B}-proxy" "$TEST_KEYRING_CONTAINER" "$TEST_LOGIN_CONTAINER" >/dev/null 2>&1 || true
  podman volume rm -f "$TEST_CRED_VOL" "$TEST_RUN_VOL" "$TEST_KEYRING_DATA_VOL" >/dev/null 2>&1 || true
  rm -f "$TEST_PASS_FILE"
  rm -rf "$(dirname "$REPO")"
}
trap cleanup EXIT

echo "== credenciais =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }
A="asb-${WS_A}-agent"
require "o agente A responde" podman exec "$A" true

# Valida schema 2 no singleton
assert_eq "2" \
  "$(podman inspect "$TEST_KEYRING_CONTAINER" --format '{{index .Config.Labels "asb.keyring.schema"}}')" \
  "singleton iniciado com schema 2"

# Valida que o container do workspace NÃO consegue ler nem escrever no subdiretório legado
assert_fails "container de workspace nao consegue ler arquivo no subdiretorio legado de keyrings" \
  podman exec "$A" cat /run/asb-credentials/keyrings/sentinel.keyring
assert_fails "container de workspace nao consegue escrever no subdiretorio legado de keyrings" \
  podman exec "$A" sh -c "echo hack > /run/asb-credentials/keyrings/hack.keyring"
assert_contains "mode=000" \
  "$(podman inspect "$A" --format '{{index .HostConfig.Tmpfs "/run/asb-credentials/keyrings"}}')" \
  "mascara tmpfs presente em /run/asb-credentials/keyrings no workspace"

# Valida que o container de login também aplica a máscara de isolamento
podman run -d --name "$TEST_LOGIN_CONTAINER" \
  --userns keep-id:uid=1000,gid=1000 \
  -v "$TEST_RUN_VOL:/run/asb-keyring:ro,z" \
  -e DBUS_SESSION_BUS_ADDRESS="unix:path=/run/asb-keyring/bus" \
  -v "$TEST_CRED_VOL:/run/asb-credentials:z" \
  --mount type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000 \
  "$IMAGE" sleep 3600 >/dev/null
assert_fails "container de login nao consegue ler arquivo no subdiretorio legado de keyrings" \
  podman exec "$TEST_LOGIN_CONTAINER" cat /run/asb-credentials/keyrings/sentinel.keyring
assert_fails "container de login nao consegue escrever no subdiretorio legado de keyrings" \
  podman exec "$TEST_LOGIN_CONTAINER" sh -c "echo hack > /run/asb-credentials/keyrings/hack.keyring"
podman rm -f "$TEST_LOGIN_CONTAINER" >/dev/null 2>&1 || true

# Valida que o arquivo sentinela permanece intacto no volume de credenciais
assert_eq "sentinel-secret-token" \
  "$(podman run --rm --entrypoint cat -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" "$IMAGE" /run/asb-credentials/keyrings/sentinel.keyring 2>/dev/null || true)" \
  "arquivo sentinela preservado no volume de credenciais subjacente"

# O diretorio de credencial e MONTADO do volume, e nao um symlink de arquivo.
# A1 mediu por que: `rename` atomico sobre um symlink substitui o proprio
# symlink e corta o vinculo com o volume; o mesmo `rename` sobre um arquivo
# bind-montado falha com EBUSY; e o Claude Code 2.1.263 abre a credencial com
# `O_RDONLY | O_NOFOLLOW`, entao um symlink devolve ELOOP e ele trata a
# credencial como AUSENTE. Só o diretorio montado sobrevive aos tres.
for d in .claude .codex; do
  assert_eq "0" "$(podman exec "$A" sh -c "test -d '$HOME/$d'; echo \$?")" \
    "$d e um diretorio no agente"
  assert_fails "$d NAO e um symlink no agente" \
    podman exec "$A" sh -c "test -L '$HOME/$d'"
done
# `podman inspect` reporta o subpath no campo `SubPath` de cada mount (medido
# no podman 6.1), e nao com a sintaxe da linha de comando.
MOUNTS_A=$(podman inspect "$A" --format \
  '{{range .Mounts}}{{.Name}}|{{.Destination}}|{{.SubPath}}{{"\n"}}{{end}}')
assert_contains "$TEST_CRED_VOL|$HOME/.claude|claude" "$MOUNTS_A" \
  "o agente monta o subpath claude do volume de credenciais em ~/.claude"
assert_contains "$TEST_CRED_VOL|$HOME/.codex|codex" "$MOUNTS_A" \
  "o agente monta o subpath codex do volume de credenciais em ~/.codex"

# O subdiretorio legado `keyrings` do volume nao pode aparecer pelo caminho da
# credencial: o subpath expoe SOMENTE o diretorio do fornecedor.
assert_fails "o mount de credencial nao expoe o subdiretorio keyrings" \
  podman exec "$A" test -e "$HOME/.claude/keyrings"

# O cliente NÃO deve criar link para ~/.local/share/keyrings
assert_fails "o keyring nao e um link no container cliente" \
  podman exec -u 1000 "$A" sh -c 'test -L "$HOME/.local/share/keyrings"'

# O cliente NÃO deve ter o volume de dados do keyring montado
assert_fails "volume de dados do keyring nao esta montado no cliente" \
  podman exec "$A" test -e /run/asb-keyring-data

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

# Escreve pelo CAMINHO REAL com RENAME ATOMICO, que e o padrao dos escritores
# de credencial de verdade — e exatamente a operacao que, no arranjo antigo de
# symlink, substituia o link e cortava o vinculo com o volume. Dado sintetico,
# nunca uma credencial real.
podman exec -u 1000 "$A" sh -c \
  "printf 'marca-do-teste' > '$HOME/.codex/auth.json.tmp' \
   && mv -f '$HOME/.codex/auth.json.tmp' '$HOME/.codex/auth.json'"
assert_eq "marca-do-teste" \
  "$(podman exec "$A" sh -c "cat '$HOME/.codex/auth.json'")" \
  "o rename atomico aterrissou no caminho real"
assert_fails "apos o rename, a credencial e arquivo comum e nao symlink" \
  podman exec "$A" sh -c "test -L '$HOME/.codex/auth.json'"
assert_eq "marca-do-teste" \
  "$(podman run --rm --entrypoint cat -v "$TEST_CRED_VOL:/run/asb-credentials:ro,z" \
      "$IMAGE" /run/asb-credentials/codex/auth.json 2>/dev/null || true)" \
  "o rename atomico aterrissou DENTRO do volume, nao numa copia efemera"

# A causa do defeito original, agora um asserto: nada pode precriar a
# credencial do Claude como arquivo de 0 bytes.
assert_fails "nada precria a credencial do Claude como arquivo vazio" \
  podman exec "$A" test -e "$HOME/.claude/.credentials.json"

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
assert_eq "0" "$(podman volume exists "$TEST_KEYRING_DATA_VOL"; echo $?)" \
  "o volume de dados do keyring sobreviveu ao down"

report
