#!/usr/bin/env bash
# tests/test-provision.sh — provisionamento da configuracao do host.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
WS=provision-test
REPO=$(mktemp -d); STAGE=$(mktemp -d)
trap 'rm -rf "$REPO" "$STAGE"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

echo "== provisionamento =="

# --- a lista de negacao, que e a peca de seguranca ---
bad=$(mktemp)
cat > "$bad" <<'TOML'
[[entry]]
src = "~/.claude/.credentials.json"
dst = "/home/agent/.claude/.credentials.json"
TOML
python3 cli/lib/provision.py "$bad" "$STAGE" >/dev/null 2>&1 \
  && { echo "  FALHOU: manifesto com credencial foi aceito"; _fail=$((_fail+1)); } \
  || { echo "  ok: manifesto com credencial e recusado"; _pass=$((_pass+1)); }

# diretorio que ESCONDE um caminho negado tambem tem de ser recusado
mkdir -p "$STAGE/fake"; : > "$STAGE/fake/auth.json"
cat > "$bad" <<TOML
[[entry]]
src = "$STAGE/fake"
dst = "/home/agent/fake"
TOML
python3 cli/lib/provision.py "$bad" "$STAGE" >/dev/null 2>&1 \
  && { echo "  FALHOU: diretorio com credencial escondida foi aceito"; _fail=$((_fail+1)); } \
  || { echo "  ok: caminho negado dentro de diretorio e detectado"; _pass=$((_pass+1)); }
rm -f "$bad"

# --- o filtro de settings ---
plan=$(python3 cli/lib/provision.py profiles/provision.toml "$STAGE")
assert_contains "settings.json" "$plan" "manifesto real produz um plano"
if [ -f "$STAGE/claude-settings.json" ]; then
  assert_eq "false" "$(jq 'has("hooks")' "$STAGE/claude-settings.json")" "hooks removido do settings"
  assert_eq "false" "$(jq 'has("statusLine")' "$STAGE/claude-settings.json")" "statusLine removido"
  assert_eq "true" "$(jq 'has("enabledPlugins")' "$STAGE/claude-settings.json")" "enabledPlugins preservado"
fi

# --- ponta a ponta ---
out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port); key=~/.config/agent-sandbox/id_ed25519
sa(){ ssh -q -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }
require "o workspace responde" sa true

assert_eq "$(ls ~/.claude/skills 2>/dev/null | wc -l)" "$(sa 'ls ~/.claude/skills 2>/dev/null | wc -l')" \
  "skills do host chegam ao sandbox"
assert_eq "$(sha256sum ~/.claude/plugins/installed_plugins.json | cut -c1-16)" \
          "$(sa 'sha256sum ~/.claude/plugins/installed_plugins.json 2>/dev/null | cut -c1-16')" \
  "plugins do host chegam identicos"

# A credencial do container tem de vir da IMAGEM, nunca do host.
for f in .claude/.credentials.json .codex/auth.json; do
  if [ "$(sha256sum ~/"$f" 2>/dev/null | cut -c1-16)" = "$(sa "sha256sum ~/$f 2>/dev/null | cut -c1-16")" ]; then
    echo "  FALHOU: credencial do host vazou para o sandbox ($f)"; _fail=$((_fail+1))
  else
    echo "  ok: credencial do host nao vazou ($f)"; _pass=$((_pass+1))
  fi
done

report
