#!/usr/bin/env bash
# tests/test-provision.sh — a configuracao do host chega ao sandbox, e a
# credencial do host NAO chega.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

WS="test-prov-$$"
REPO=$(mktemp -d)/proj
mkdir -p "$REPO" && cd "$REPO"
git init -q -b main . && git config user.email t@e.com && git config user.name T
echo ok > README.md && git add -A && git commit -qm inicial
cd "$ROOT"

cleanup() { "$ROOT/cli/asb-agent" purge --workspace "$WS" --yes >/dev/null 2>&1; }
trap cleanup EXIT

AGENT="asb-${WS}-agent"
"$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$REPO" >/dev/null || {
  echo "  ABORTADO: up falhou"; exit 1; }

echo "== provisionamento da configuracao =="
require "o agente responde" podman exec "$AGENT" true

# Skills so servem se estiverem materializadas: um symlink do host para
# /usr/share/omarchy/... chega quebrado se nao for resolvido.
if [ -d "$HOME/.claude/skills" ]; then
  assert_eq "0" "$(podman exec "$AGENT" sh -c "test -d '$HOME/.claude/skills'; echo \$?")" \
    "as skills do Claude chegaram"
  assert_eq "0" "$(podman exec "$AGENT" sh -c \
    "find '$HOME/.claude/skills' -xtype l | head -1 | wc -l | grep -q '^0$'; echo \$?")" \
    "nenhuma skill chegou como link quebrado"
fi

# A credencial do host NUNCA entra: ela mora no volume de credenciais, que e
# outro caminho e outro dono.
for leak in "$HOME/.claude/.credentials.json.host" "$HOME/.ssh/id_ed25519"; do
  assert_eq "1" "$(podman exec "$AGENT" sh -c "test -e '$leak'; echo \$?")" \
    "nao vazou: $leak"
done

# O staging e read-only: o agente nao pode reescrever a propria origem de
# configuracao para a proxima partida.
assert_fails "o agente nao escreve no staging montado" \
  podman exec "$AGENT" sh -c 'touch /run/asb-config/x'

report
