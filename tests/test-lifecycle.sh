#!/usr/bin/env bash
# tests/test-lifecycle.sh — a fronteira sobrevive a parada e a religada.
#
# Este e o teste que o v1 nao tinha. Nele o sandbox voltava do reboot com o
# ruleset vazio e egresso direto liberado, e o unico sintoma visivel era o
# squid morto.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-life-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
PROXY="asb-${WS}-proxy"

connect_ok() {
  podman exec "$AGENT" sh -c '
    printf "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n" \
      | timeout 10 nc '"$PROXY"' 3128 | head -n 1' 2>/dev/null | grep -q " 200 "
}

echo "== ciclo de vida =="
OUT=$("$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO") || {
  echo "  ABORTADO: up falhou"; exit 1; }
PORT_ANTES=$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
IP_ANTES=$(podman inspect "$PROXY" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')

require "o agente responde antes do ciclo" podman exec "$AGENT" true
require "CONNECT funciona antes do ciclo" connect_ok

echo "-- suspend / resume --"
"$ROOT/cli/asb-agent" suspend --workspace "$WS" >/dev/null
assert_eq "" "$(podman ps --filter "name=^${AGENT}$" --filter status=running -q)" \
  "suspend realmente parou o agente"

OUT2=$("$ROOT/cli/asb-agent" resume --workspace "$WS") || {
  echo "  ABORTADO: resume falhou"; exit 1; }
PORT_DEPOIS=$(printf '%s' "$OUT2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')

require "o agente responde apos o resume" podman exec "$AGENT" true

# A porta e resolvida na CRIACAO e gravada no spec do container. O Orca guarda
# a que o create devolveu e disca nela para sempre — inclusive apos reboot.
assert_eq "$PORT_ANTES" "$PORT_DEPOIS" "a porta SSH sobrevive ao ciclo"

# ---- A FRONTEIRA CONTINUA DE PE, SEM NADA TER REAPLICADO ----
assert_fails "o agente continua sem alcancar a internet apos o resume" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'
assert_eq "" "$(podman exec "$AGENT" sh -c 'ip -4 route show default' 2>/dev/null)" \
  "o agente continua sem rota default apos o resume"

echo "-- o agente sobe ANTES do proxy (ordem do boot) --"
# podman-restart.service nao ordena nada, e o IP do proxy MUDA entre partidas.
# Se algo cachear o endereco antigo, o sintoma e "internet quebrada apos
# reboot" — identico ao bug do v1 que este redesenho elimina.
podman stop -t 2 "$AGENT" "$PROXY" >/dev/null 2>&1
podman start "$AGENT" >/dev/null
require "o agente sobe sozinho, sem o proxy" podman exec "$AGENT" true
assert_fails "sem o proxy no ar, nao ha egresso (fail-closed por topologia)" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'

podman start "$PROXY" >/dev/null
IP_DEPOIS=$(podman inspect "$PROXY" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
assert_eq "0" "$(wait_for 20 connect_ok; echo $?)" \
  "o agente reconecta ao proxy pelo NOME apos ele subir depois"
echo "  (ip do proxy antes=$IP_ANTES depois=$IP_DEPOIS)"

echo "-- list --"
assert_contains "$WS" "$("$ROOT/cli/asb-agent" list)" "list mostra o workspace"

report
