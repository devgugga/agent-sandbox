#!/usr/bin/env bash
# tests/test-broker.sh — o filtro do socket do Docker.
#
# Nao exige o broker instalado: sem ele, o teste PULA em vez de falhar, porque
# a instalacao pede sudo e nao pode ser um pre-requisito silencioso da suite.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

SOCK=/run/asb-docker/docker.sock
if [ ! -S "$SOCK" ]; then
  echo "PULADO: broker nao instalado (use 'asb-agent install-broker')"
  exit 0
fi

echo "== filtro do broker =="
ask() {
  printf 'GET %s HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n' "$1" \
    | timeout 5 socat - "UNIX-CONNECT:$SOCK" 2>/dev/null | head -n 1
}
post() {
  printf 'POST %s HTTP/1.1\r\nHost: docker\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' "$1" \
    | timeout 5 socat - "UNIX-CONNECT:$SOCK" 2>/dev/null | head -n 1
}

require "o broker responde" sh -c '[ -n "$(printf "GET /v1.43/version HTTP/1.1\r\nHost: d\r\nConnection: close\r\n\r\n" | timeout 5 socat - UNIX-CONNECT:'"$SOCK"' | head -n 1)" ]'

assert_contains "200" "$(ask /v1.43/version)"          "version e permitido"
assert_contains "200" "$(ask /v1.43/containers/json)"  "ps e permitido"

# Leitura so. Qualquer mutacao e 403, e isso NAO e configuravel: exec num
# container root com bind mount do host e root do host.
assert_contains "403" "$(post /v1.43/containers/create)"     "create e recusado"
assert_contains "403" "$(post /v1.43/containers/x/start)"    "start e recusado"
assert_contains "403" "$(post /v1.43/containers/x/exec)"     "exec e recusado"
assert_contains "403" "$(post /v1.43/build)"                 "build e recusado"
assert_contains "403" "$(ask /v1.43/images/json)"            "endpoint nao listado e recusado"
assert_contains "403" "$(ask '/v1.43/containers/../../secret')" "travessia de caminho e recusada"

assert_eq "1000" "$(stat -c %u "$SOCK")" "o socket pertence ao uid 1000"
assert_eq "600"  "$(stat -c %a "$SOCK")" "o socket e 0600"

report
