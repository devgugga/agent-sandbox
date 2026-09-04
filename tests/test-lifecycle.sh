#!/usr/bin/env bash
# tests/test-lifecycle.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

WS=lifecycle-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q
cat > "$REPO/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "isolated"
[services.postgres]
image = "postgres:16-alpine"
port = 5432
TOML

echo "== Task 4: ciclo de vida =="
out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
echo "$out" | jq -e . >/dev/null 2>&1 && { echo "  ok: up emitiu JSON valido"; _pass=$((_pass+1)); } || { echo "  FALHOU: JSON invalido: $out"; _fail=$((_fail+1)); }

port=$(echo "$out" | jq -r .port)
assert_contains "asb-$WS" "$(echo "$out" | jq -r .pod)" "nome do pod correto"

key=~/.config/agent-sandbox/id_ed25519
ssh_probe() { ssh -q -o ConnectTimeout=3 -i "$key" -p "$port" -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null agent@127.0.0.1 true; }
wait_for 40 ssh_probe
require "SSH do workspace aceita conexao" ssh_probe
ssh_agent() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }

assert_eq "1000" "$(ssh_agent 'id -u')" "SSH conecta e o agente e uid 1000"
assert_eq "ok" "$(ssh_agent 'test -d /home/agent/workspace && echo ok')" "repo montado em /home/agent/workspace"

# O bug que a suite nao pegava: /home/agent/workspace existia mas era ilegivel para o
# agente (uid 1000 -> subuid sem posse). Existir nao basta; tem que escrever.
assert_eq "ok" "$(ssh_agent 'echo teste > /home/agent/workspace/.asb-escrita && echo ok')" \
  "agente ESCREVE em /home/agent/workspace"
assert_eq "teste" "$(cat "$REPO/.asb-escrita" 2>/dev/null)" \
  "host le de volta o que o agente escreveu"

# o postgres do pod responde em localhost:5432 — a promessa central do modo isolado
assert_eq "ok" "$(ssh_agent 'for i in $(seq 30); do nc -z 127.0.0.1 5432 && { echo ok; exit; }; sleep 2; done')" \
  "postgres descartavel responde em localhost:5432"

# o firewall esta de pe dentro do workspace real
assert_fails "sem egresso direto no workspace real" \
  ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null agent@127.0.0.1 'curl -s -m 6 https://1.1.1.1'

./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1
assert_fails "pod removido no down" podman pod exists "asb-$WS"
./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1
assert_eq "0" "$?" "down e idempotente"

report
