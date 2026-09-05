#!/usr/bin/env bash
# tests/test-agents-behind-proxy.sh — agentes atras do proxy e ambiente SSH
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="agents-test-$$"
REPO=$(mktemp -d)
cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1 || true
  rm -rf "$REPO"
}
trap cleanup EXIT

git -C "$REPO" init -q -b main
git -C "$REPO" config user.email t@e.com
git -C "$REPO" config user.name T
echo ok > "$REPO/README.md"
git -C "$REPO" add -A && git -C "$REPO" commit -qm inicial

out=$("$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(printf '%s' "$out" | jq -r .port)
key="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519"
user=$(id -un)
sa() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o LogLevel=ERROR -o UserKnownHostsFile=/dev/null "$user@127.0.0.1" "$1" 2>&1; }

echo "== agentes atras do proxy =="
require "o agente responde por SSH" wait_for 15 sa true
assert_contains "http://asb-${WS}-proxy:3128" "$(sa 'echo $HTTPS_PROXY')" "HTTPS_PROXY chega na sessao SSH"

# CLAUDE_CODE_SUBPROCESS_ENV_SCRUB, herdada do spec original, faz o Claude Code
# FORCAR o permission mode para default — anulando o --dangerously-skip-permissions
# que o Orca aplica. Dentro do container ela nao protege nada, porque o container
# ja e a fronteira. O sandbox existe para tornar o yolo mode seguro; deixar essa
# variavel ligada desligava justamente o yolo mode.
assert_eq "" "$(sa 'echo ${CLAUDE_CODE_SUBPROCESS_ENV_SCRUB:-}')" \
  "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB ausente do ambiente do agente"
assert_eq "0" "$(sa 'asb-claude --dangerously-skip-permissions -p ok 2>&1 | grep -ci "forced to default"')" \
  "claude aceita --dangerously-skip-permissions sem forcar default"

# O agy nao sobe container proprio: o conflito de aninhamento do Gemini some.
assert_contains "1.1." "$(sa 'agy --version')" "Antigravity CLI presente"
assert_contains "secrets" "$(sa 'ls ~/.local/share/keyrings 2>/dev/null | tr "\n" " "; echo secrets')" \
  "diretorio de keyring existe"

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

# Chamadas vivas de modelo: executadas apos o login no volume asb-credentials.
claude_check=$(sa 'claude -p ping < /dev/null 2>&1 || true')
if [[ "$claude_check" == *"Not logged in"* ]]; then
  echo "  (Claude nao autenticado no volume; execute 'asb-agent login' para testar chamadas vivas de modelo)"
else
  claude_out=$(sa 'claude -p "responda apenas: ok" < /dev/null 2>&1 | tail -1')
  assert_contains "ok" "$claude_out" "Claude Code responde atras do proxy"
fi

agy_check=$(sa 'asb-agy -p "ping" --print-timeout 10s 2>&1 || true')
if [[ "$agy_check" == *"authentication required"* || "$agy_check" == *"authentication failed"* ]]; then
  echo "  (Antigravity nao autenticado no volume; execute 'asb-agent login' para testar chamadas vivas de modelo)"
else
  assert_contains "ok" "$(sa 'asb-agy -p "responda apenas ok" --print-timeout 45s 2>&1 | tail -1')" \
    "agy autentica por SSH quando lancado pelo guarda"
fi

report
