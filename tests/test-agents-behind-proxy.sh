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
# O agy nao sobe container proprio: o conflito de aninhamento do Gemini some.
assert_contains "1.1." "$(sa 'agy --version')" "Antigravity CLI presente"
assert_contains "secrets" "$(sa 'ls ~/.local/share/keyrings 2>/dev/null | tr \"\\n\" \" \"; echo secrets')" \
  "diretorio de keyring existe"

claude_out=$(sa 'claude -p "responda apenas: ok" < /dev/null 2>&1 | tail -1')
assert_contains "ok" "$claude_out" "Claude Code responde atras do proxy"

npm_out=$(sa 'npm ping 2>&1 | grep -i pong || echo fail')
assert_contains "PONG" "$npm_out" "npm resolve atras do proxy"

# O Orca instala o relay dele DENTRO do container (~/.orca-remote) e o node-pty
# compila via node-gyp, que baixa os headers do Node de nodejs.org. Sem esse
# dominio na allowlist o workspace da receita falha no arranque com "Request
# was cancelled" — foi exatamente o que aconteceu no primeiro uso real.
sa 'mkdir -p /tmp/relay-probe && cd /tmp/relay-probe && npm install \
      --ignore-scripts=false --omit=dev --no-audit --no-fund node-pty@1.1.0' >/dev/null 2>&1
assert_eq "ok" "$(sa 'test -f /tmp/relay-probe/node_modules/node-pty/build/Release/pty.node && echo ok')" \
  "node-gyp compila modulo nativo atras do proxy (relay do Orca)"

report
