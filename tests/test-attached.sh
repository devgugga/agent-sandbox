#!/usr/bin/env bash
# tests/test-attached.sh
# PRE-REQUISITO: a stack hexmed precisa estar no ar (postgres publicado na 5432).
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

host_port_open() { (echo > "/dev/tcp/127.0.0.1/$1") 2>/dev/null || (command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$1" 2>/dev/null); }
host_port_open 5432 || { echo "PULADO: nada escutando em 127.0.0.1:5432"; exit 0; }

WS=attached-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q
cat > "$REPO/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "attached"
[[attach]]
port = 5432
TOML

out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port); key=~/.config/agent-sandbox/id_ed25519
sa() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }

echo "== Task 8: modo anexado =="
assert_eq "ok" "$(sa 'nc -z -w4 127.0.0.1 5432 && echo ok')" "postgres real alcancavel em localhost:5432"
# cirurgico: apenas a porta declarada, nada mais do host
assert_fails "porta do host nao declarada continua bloqueada" \
  ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null agent@127.0.0.1 'nc -z -w4 127.0.0.1 6379'
report
