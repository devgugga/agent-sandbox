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

# Uma denylist por nome nao basta: um plugin pode chamar o link de qualquer
# coisa e apontar para ~/.aws, ~/.config/gcloud ou outro segredo desconhecido.
mkdir -p "$STAGE/external-source" "$STAGE/external-secret"
printf 'cloud-secret\n' > "$STAGE/external-secret/innocent-name"
ln -s "$STAGE/external-secret" "$STAGE/external-source/vendor-data"
cat > "$STAGE/external-link.toml" <<TOML
[[entry]]
src = "$STAGE/external-source"
dst = "/home/agent/.gemini/external-source"
TOML
python3 cli/lib/provision.py "$STAGE/external-link.toml" "$STAGE/link-output" \
  >/dev/null 2>&1 \
  && { echo "  FALHOU: symlink externo fora das raizes confiaveis foi aceito"; _fail=$((_fail+1)); } \
  || { echo "  ok: symlink externo fora das raizes confiaveis e recusado"; _pass=$((_pass+1)); }

cat > "$STAGE/destination-escape.toml" <<TOML
[[entry]]
src = "$STAGE/external-secret/innocent-name"
dst = "/home/agent/.gemini/../../workspace/escape.json"
TOML
python3 cli/lib/provision.py "$STAGE/destination-escape.toml" "$STAGE/escape-output" \
  >/dev/null 2>&1 \
  && { echo "  FALHOU: destino com .. escapou da raiz permitida"; _fail=$((_fail+1)); } \
  || { echo "  ok: destino com .. e recusado"; _pass=$((_pass+1)); }

# --- o filtro de settings ---
plan=$(python3 cli/lib/provision.py profiles/provision.toml "$STAGE")
assert_contains "settings.json" "$plan" "manifesto real produz um plano"
if [ -f "$STAGE/claude-settings.json" ]; then
  assert_eq "false" "$(jq 'has("hooks")' "$STAGE/claude-settings.json")" "hooks removido do settings"
  assert_eq "false" "$(jq 'has("statusLine")' "$STAGE/claude-settings.json")" "statusLine removido"
  assert_eq "true" "$(jq 'has("enabledPlugins")' "$STAGE/claude-settings.json")" "enabledPlugins preservado"
fi

# --- Antigravity: estado configuravel completo e hooks portaveis ---
agy_fixture="$STAGE/agy-source"
mkdir -p "$agy_fixture/plugins/demo" "$agy_fixture/skills/demo"
printf '{}\n' > "$agy_fixture/config.json"
printf '{}\n' > "$agy_fixture/mcp_config.json"
printf '{}\n' > "$agy_fixture/import_manifest.json"
printf 'plugin\n' > "$agy_fixture/plugins/demo/plugin.txt"
printf 'skill\n' > "$agy_fixture/skills/demo/SKILL.md"
cat > "$agy_fixture/hooks.json" <<'JSON'
{
  "orca-status": {
    "PreInvocation": [
      {"command": "'/home/tester/.orca/agent-hooks/antigravity-hook.sh' pre-invocation"}
    ]
  }
}
JSON
agy_manifest="$STAGE/agy-manifest.toml"
cat > "$agy_manifest" <<TOML
[[entry]]
src = "$agy_fixture/config.json"
dst = "/home/agent/.gemini/config/config.json"

[[entry]]
src = "$agy_fixture/hooks.json"
dst = "/home/agent/.gemini/config/hooks.json"
filter = "antigravity-hooks"

[[entry]]
src = "$agy_fixture/mcp_config.json"
dst = "/home/agent/.gemini/config/mcp_config.json"

[[entry]]
src = "$agy_fixture/import_manifest.json"
dst = "/home/agent/.gemini/config/import_manifest.json"

[[entry]]
src = "$agy_fixture/plugins"
dst = "/home/agent/.gemini/config/plugins"

[[entry]]
src = "$agy_fixture/skills"
dst = "/home/agent/.gemini/config/skills"
TOML
agy_plan=$(python3 cli/lib/provision.py "$agy_manifest" "$STAGE" 2>/dev/null)
for destination in config.json hooks.json mcp_config.json import_manifest.json plugins skills; do
  assert_contains "/home/agent/.gemini/config/$destination" "$agy_plan" \
    "Antigravity provisiona $destination"
done
hook_src=$(printf '%s\n' "$agy_plan" | awk -F '\t' '$2 ~ /hooks.json$/ {print $1}')
assert_contains "/home/agent/.orca/agent-hooks/antigravity-hook.sh" \
  "$(jq -r '.. | .command? // empty' "$hook_src")" \
  "hook do host e normalizado para o home do container"
assert_eq "" "$(jq -r '.. | .command? // empty' "$hook_src" | grep -F '/home/tester/' || true)" \
  "hook provisionado nao conserva caminho absoluto do host"

# --- ponta a ponta ---
out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port); key=~/.config/agent-sandbox/id_ed25519
sa(){ ssh -q -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }
require "o workspace responde" sa true
assert_eq "$(sha256sum image/asb-agent | cut -c1-16)" \
          "$(sa 'sha256sum /usr/local/bin/asb-agent | cut -c1-16')" \
  "workspace recebe o guarda atual sem exigir novo login da imagem auth"
assert_eq "identicos" "$(cmp -s cli/asb-agent image/asb-agent && echo identicos)" \
  "guardas do host e da imagem permanecem identicos"

# Contar entradas nao prova nada: as skills do host sao symlinks para fora do
# home (/usr/share/omarchy/..., ~/.agents/skills/...) e o `podman cp` os
# preserva, entao chegavam como links QUEBRADOS — presentes num `ls`, inuteis
# para o agente. A assercao tem de exigir conteudo legivel.
assert_eq "$(ls ~/.claude/skills 2>/dev/null | wc -l)" \
          "$(sa 'find ~/.claude/skills -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l')" \
  "skills do host chegam USAVEIS (SKILL.md legivel)"
assert_eq "0" "$(sa 'find ~/.claude/skills ~/.codex/skills -xtype l 2>/dev/null | wc -l')" \
  "nenhum symlink quebrado nas skills"
assert_eq "$(ls ~/.codex/skills 2>/dev/null | wc -l)" \
          "$(sa 'ls ~/.codex/skills 2>/dev/null | wc -l')" \
  "skills do codex chegam ao sandbox"
assert_eq "$(sha256sum ~/.claude/plugins/installed_plugins.json | cut -c1-16)" \
          "$(sa 'sha256sum ~/.claude/plugins/installed_plugins.json 2>/dev/null | cut -c1-16')" \
  "plugins do host chegam identicos"
assert_eq "$(find ~/.gemini/config/plugins -type f 2>/dev/null | wc -l)" \
          "$(sa 'find ~/.gemini/config/plugins -type f 2>/dev/null | wc -l')" \
  "plugins do Antigravity chegam ao sandbox"
assert_eq "$(find ~/.gemini/config/skills -name SKILL.md -type f 2>/dev/null | wc -l)" \
          "$(sa 'find ~/.gemini/config/skills -name SKILL.md -type f 2>/dev/null | wc -l')" \
  "skills do Antigravity chegam ao sandbox"
assert_eq "ok" "$(sa 'test -f ~/.gemini/config/mcp_config.json && echo ok')" \
  "configuracao MCP do Antigravity chega ao sandbox"

# A credencial do container tem de vir da IMAGEM, nunca do host.
for f in .claude/.credentials.json .codex/auth.json; do
  if [ "$(sha256sum ~/"$f" 2>/dev/null | cut -c1-16)" = "$(sa "sha256sum ~/$f 2>/dev/null | cut -c1-16")" ]; then
    echo "  FALHOU: credencial do host vazou para o sandbox ($f)"; _fail=$((_fail+1))
  else
    echo "  ok: credencial do host nao vazou ($f)"; _pass=$((_pass+1))
  fi
done

report
