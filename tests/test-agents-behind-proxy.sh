#!/usr/bin/env bash
# tests/test-agents-behind-proxy.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
WS=agents-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port)
key=~/.config/agent-sandbox/id_ed25519
sa() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>&1; }

echo "== Task 6: agentes atras do proxy =="
assert_contains "http://127.0.0.1:3128" "$(sa 'echo $HTTPS_PROXY')" "HTTPS_PROXY chega na sessao SSH"
assert_contains "false" "$(sa 'echo $GEMINI_SANDBOX')" "GEMINI_SANDBOX desligado"

claude_out=$(sa 'claude -p "responda apenas: ok" < /dev/null 2>&1 | tail -1')
assert_contains "ok" "$claude_out" "Claude Code responde atras do proxy"

npm_out=$(sa 'npm ping 2>&1 | grep -i pong || echo fail')
assert_contains "PONG" "$npm_out" "npm resolve atras do proxy"

report
