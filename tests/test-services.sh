#!/usr/bin/env bash
# tests/test-services.sh — servicos descartaveis e portas do host.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-svc-$$"
PORT=54321
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md
cat > .agent-sandbox.toml <<TOML
[docker]
host_ports = [$PORT]

[services.cache]
image = "docker.io/library/redis:7-alpine"
TOML
git add -A && git commit -qm inicial
cd "$ROOT"

# Servico do host em 0.0.0.0, como o docker compose publica. Ligado apenas a
# 127.0.0.1 ele NAO seria alcancavel — medido.
python3 - "$PORT" <<'PY' &
import socket, sys, threading, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", int(sys.argv[1]))); s.listen(5)
def serve():
    while True:
        c, _ = s.accept(); c.sendall(b"HOST-OK\n"); c.close()
threading.Thread(target=serve, daemon=True).start(); time.sleep(120)
PY
HOST_SVC=$!
cleanup() {
  kill "$HOST_SVC" 2>/dev/null
  "$ROOT/cli/asb-agent" purge --workspace "$WS" --yes >/dev/null 2>&1
}
trap cleanup EXIT
sleep 1

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== servicos e portas do host =="
require "o agente responde" podman exec "$AGENT" true
require "o servico do host responde no proprio host" \
  timeout 3 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT"

assert_eq "0" "$(podman exec "$AGENT" sh -c \
  'timeout 5 nc -z asb-'"$WS"'-svc-cache 6379; echo $?')" \
  "o servico descartavel e alcancavel por nome"

# O projeto continua apontando para localhost: e a razao do socat de loopback
# dentro do container do agente.
assert_contains "HOST-OK" "$(podman exec "$AGENT" sh -c \
  "timeout 5 nc 127.0.0.1 $PORT")" \
  "a porta declarada do host chega em localhost dentro do sandbox"

# Cirurgico: SO as portas declaradas. O host participa de uma rede Tailscale, e
# abrir faixas privadas entregaria a tailnet inteira ao agente.
assert_fails "uma porta NAO declarada do host nao e alcancavel" \
  podman exec "$AGENT" sh -c "timeout 3 nc -z 127.0.0.1 $((PORT+1))"

echo "-- suspend e resume afetam TODOS os containers do workspace --"
"$ROOT/cli/asb-agent" suspend --workspace "$WS" >/dev/null

assert_eq "" "$(podman ps --filter "name=^asb-${WS}-svc-cache$" --filter status=running -q)" \
  "suspend parou o container de servico"
assert_eq "" "$(podman ps --filter "name=^asb-${WS}-fwd$" --filter status=running -q)" \
  "suspend parou o container encaminhador"
assert_eq "" "$(podman ps --filter "name=^asb-${WS}-agent$" --filter status=running -q)" \
  "suspend parou o container do agente"

"$ROOT/cli/asb-agent" resume --workspace "$WS" >/dev/null

assert_eq "0" "$(podman exec "$AGENT" sh -c \
  'timeout 5 nc -z asb-'"$WS"'-svc-cache 6379; echo $?')" \
  "resume religou o servico descartavel"
assert_contains "HOST-OK" "$(podman exec "$AGENT" sh -c \
  "timeout 5 nc 127.0.0.1 $PORT")" \
  "resume religou o encaminhador para o host"

echo "-- servicos sao descartaveis --"
"$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null
assert_eq "1" "$(podman container exists asb-${WS}-svc-cache; echo $?)" \
  "o servico foi removido junto com o workspace"

report
