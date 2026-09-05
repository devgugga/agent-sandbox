#!/usr/bin/env bash
# tests/test-nested.sh — runtime de containers DENTRO do sandbox.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-nested-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md
printf '[docker]\nmode = "nested"\n' > .agent-sandbox.toml
git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== containers aninhados =="
require "o agente responde" podman exec "$AGENT" true
require "o podman aninhado responde" \
  podman exec -u 1000 "$AGENT" bash -lc 'podman --version'

assert_contains "true" \
  "$(podman exec -u 1000 "$AGENT" bash -lc \
     'podman info --format "{{.Host.Security.Rootless}}" 2>/dev/null | tail -1')" \
  "o podman aninhado roda rootless"

# O pull sai pelo Squid: sem os registries na allowlist a falha apareceria como
# "o build nao funciona", sem apontar a causa.
assert_contains "ANINHADO-OK" \
  "$(podman exec -u 1000 "$AGENT" bash -lc \
     'timeout 300 podman run --rm docker.io/library/alpine:latest echo ANINHADO-OK 2>&1 | tail -1')" \
  "o agente puxa e roda uma imagem atraves do proxy"

# Rede definida pelo usuario e resolucao por nome (suporte real a podman compose)
podman exec -u 1000 "$AGENT" bash -lc 'podman network create appnet >/dev/null'
podman exec -u 1000 "$AGENT" bash -lc 'podman run -d --name svc --network appnet docker.io/library/alpine:latest sh -c "while true; do echo NET-OK | nc -l -p 8080; done" >/dev/null'

RESOLV_OUT=$(podman exec -u 1000 "$AGENT" bash -lc 'timeout 15 podman run --rm --network appnet docker.io/library/alpine:latest nc svc 8080 2>&1')
assert_contains "NET-OK" "$RESOLV_OUT" \
  "redes definidas pelo usuario e resolucao por nome entre containers funcionam"

podman exec -u 1000 "$AGENT" bash -lc 'podman rm -f svc >/dev/null; podman network rm appnet >/dev/null'

# A fronteira nao afrouxa por causa do modo aninhado.
assert_fails "o agente continua sem egresso direto" \
  podman exec "$AGENT" sh -c 'timeout 5 bash -c "exec 3<>/dev/tcp/1.1.1.1/443"'
assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e /var/run/docker.sock; echo \$?")" \
  "o socket do Docker do host nao esta montado"
assert_eq "" "$(podman exec "$AGENT" sh -c 'ls /sys/firmware 2>/dev/null')" \
  "/sys/firmware permanece mascarado do host no modo aninhado"

report
