#!/usr/bin/env bash
# tests/test-network.sh — a fronteira de rede do sandbox.
#
# Toda assercao de bloqueio aqui e precedida por um controle positivo. Sem
# isso, um container que nao subiu faria "esta bloqueado" passar de graca — e
# um falso verde numa assercao de seguranca e pior que uma falha.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-net-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

echo "== topologia de rede =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }

AGENT="asb-${WS}-agent"
PROXY="asb-${WS}-proxy"

# ---- CONTROLES POSITIVOS ----
require "o container do agente responde" podman exec "$AGENT" true
require "o container do proxy responde"  podman exec "$PROXY" true
require "o proxy tem egresso real" \
  podman exec "$PROXY" sh -c 'timeout 5 nc -z 1.1.1.1 443'

# ---- O AGENTE NAO SAI ----
assert_fails "o agente nao alcanca a internet por IP" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'

assert_eq "" "$(podman exec "$AGENT" sh -c 'ip -4 route show default' 2>/dev/null)" \
  "o agente nao tem rota default"

# Casar a FORMA de uma resposta real, nunca "qualquer saida": ferramentas de
# DNS escrevem erros em stdout, e "tem texto" reportaria um vazamento
# inexistente.
assert_eq "" "$(podman exec "$AGENT" sh -c \
  'getent ahostsv4 api.anthropic.com 2>/dev/null | awk "{print \$1}" | head -1')" \
  "o agente nao resolve DNS externo"

# ---- O AGENTE SAI PELO PROXY ----
assert_contains "200" "$(podman exec "$AGENT" sh -c '
  printf "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n" \
    | timeout 10 nc asb-'"$WS"'-proxy 3128 | head -n 1')" \
  "CONNECT para dominio permitido responde 200"

assert_fails "CONNECT para dominio NAO permitido e recusado" \
  podman exec "$AGENT" sh -c '
    printf "CONNECT exfil.example.net:443 HTTP/1.1\r\nHost: exfil.example.net:443\r\n\r\n" \
      | timeout 10 nc asb-'"$WS"'-proxy 3128 | head -n 1 | grep -q " 200 "'

# ---- SSH PUBLICADO E UTIL ----
PORT=$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
assert_eq "0" "$(timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT" 2>/dev/null; echo $?)" \
  "a porta SSH publicada aceita conexao no host"

# ---- O MOUNT E IDENTICO E GRAVAVEL ----
MOUNT="$HOME/asb-agent/$(basename "$REPO")/$WS"
assert_eq "0" "$(podman exec "$AGENT" sh -c "test -d '$MOUNT'; echo \$?")" \
  "o caminho do mount e identico dentro do container"
assert_eq "1000" "$(podman exec "$AGENT" sh -c "stat -c %u '$MOUNT'")" \
  "o mount pertence ao uid 1000 (sem keep-id o agente nao escreve nele)"
podman exec "$AGENT" sh -c "touch '$MOUNT/escrito-pelo-agente'" 2>/dev/null
assert_eq "0" "$(test -f "$MOUNT/escrito-pelo-agente"; echo $?)" \
  "o que o agente escreve aparece no host"

# ---- O AGENTE NAO ALCANCA O ESTADO NEM O RESTO DO DISCO ----
STATE="$HOME/.local/state/agent-sandbox/$WS"
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$STATE/squid.conf'; echo \$?")" \
  "o agente nao enxerga o squid.conf (nao pode editar a propria allowlist)"
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$HOME/Data'; echo \$?")" \
  "o agente nao enxerga os outros projetos do host"

# ---- SEM CAPACIDADE DE REDE ----
assert_fails "o agente nao tem CAP_NET_ADMIN" \
  podman exec "$AGENT" sh -c 'ip link add dummy0 type dummy'

report
