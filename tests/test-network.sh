#!/usr/bin/env bash
# tests/test-network.sh — os quatro cenarios que definem a seguranca do sandbox
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

POD=asb-test-net
cleanup() { podman rm -f asb-squid >/dev/null 2>&1; podman pod rm -f "$POD" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup

podman pod create --name "$POD" >/dev/null
podman pod start "$POD" >/dev/null

# init: aplica firewall e sai
podman run --rm --pod "$POD" --cap-add NET_ADMIN agent-sandbox-net \
  /usr/local/bin/apply.sh >/dev/null

# squid como uid 900, com allowlist contendo apenas example.com
podman run -d --name asb-squid --pod "$POD" --user 900 agent-sandbox-net \
  squid -N -f /etc/squid/squid.conf >/dev/null
# Espera o proxy responder de fato, em vez de torcer por um sleep fixo.
wait_for 30 podman run --rm --pod "$POD" --user 1000 agent-sandbox-net \
  sh -c 'echo > /dev/tcp/127.0.0.1/3128'
require "o pod responde e o proxy esta de pe" \
  podman run --rm --pod "$POD" --user 1000 agent-sandbox-net \
    curl -s -o /dev/null -m 15 -x http://127.0.0.1:3128 https://example.com

run_as_agent() { podman run --rm --pod "$POD" --user 1000 agent-sandbox-net sh -c "$1" 2>/dev/null; }

echo "== Task 2: rede =="

# [1] dominio permitido, via proxy
code=$(run_as_agent "curl -s -o /dev/null -m 12 -w '%{http_code}' -x http://127.0.0.1:3128 https://example.com")
assert_eq "200" "$code" "dominio na allowlist passa pelo proxy"

# [2] dominio negado, via proxy
code=$(run_as_agent "curl -s -o /dev/null -m 12 -w '%{http_code}' -x http://127.0.0.1:3128 https://github.com")
if [ "$code" = "200" ]; then
  echo "  FALHOU: dominio fora da allowlist passou"
  _fail=$((_fail+1))
else
  echo "  ok: dominio fora da allowlist e negado"
  _pass=$((_pass+1))
fi

# [3] bypass direto do proxy
assert_fails "conexao direta e bloqueada pelo nftables" \
  podman run --rm --pod "$POD" --user 1000 agent-sandbox-net \
    curl -s -m 8 -o /dev/null https://1.1.1.1

# [4] tunel DNS — verificar procurando IP valido, NUNCA "alguma saida".
#     dig +short escreve erro no stdout; casar com qualquer texto da falso positivo.
out=$(run_as_agent "dig +time=4 +tries=1 @1.1.1.1 example.com +short")
if echo "$out" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "  FALHOU: agente resolveu DNS externo (tunel aberto)"
  _fail=$((_fail+1))
else
  echo "  ok: agente nao consegue consultar DNS"
  _pass=$((_pass+1))
fi

# [5] agente nao pode desarmar o firewall
out=$(run_as_agent "nft flush ruleset 2>&1")
assert_contains "not permitted" "$out" "agente sem NET_ADMIN nao apaga o ruleset"

report
