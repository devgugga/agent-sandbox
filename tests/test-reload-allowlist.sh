#!/usr/bin/env bash
# tests/test-reload-allowlist.sh — recarga a quente da allowlist sem tocar no agente.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

echo "== recarga a quente da allowlist =="

tmp=$(mktemp -d)
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.email t@e.com
git -C "$repo" config user.name T
echo ok > "$repo/README.md"
touch "$repo/.agent-sandbox.toml"
git -C "$repo" add -A && git -C "$repo" commit -qm inicial

WS="test-reload-$$"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

require "workspace sobe" "$ROOT/cli/asb-agent" up --workspace "$WS" --repo "$repo"

# 1. Obter porta SSH inicial alocada ao agente
port_before=$(podman port "asb-${WS}-agent" 22 | head -n 1 | awk -F: '{print $NF}')
require "porta SSH inicial obtida" [ -n "$port_before" ]

# 2. Confirmar que dominio nao permitido (ex: httpbin.org) e recusado pelo Squid (403)
code_before=$(podman exec "asb-${WS}-proxy" sh -c \
  'printf "CONNECT httpbin.org:443 HTTP/1.1\r\nHost: httpbin.org:443\r\n\r\n" | nc -w 2 127.0.0.1 3128 | head -n 1' || true)
assert_contains "403" "$code_before" "dominio httpbin.org recusado antes de ser adicionado a allowlist"

# 3. Adicionar o dominio no .agent-sandbox.toml do repositorio de origem
cat > "$repo/.agent-sandbox.toml" <<'TOML'
[network]
allow = ["httpbin.org"]
TOML

# 4. Executar reload-allowlist
OUT_RELOAD=$("$ROOT/cli/asb-agent" reload-allowlist --workspace "$WS" 2>&1); RC_RELOAD=$?
assert_eq "0" "$RC_RELOAD" "reload-allowlist sai 0"
assert_contains "allowlist recarregada" "$OUT_RELOAD" "confirma recarga da allowlist"

# 5. Confirmar que agora o dominio httpbin.org responde 200 via Squid
code_after=$(podman exec "asb-${WS}-proxy" sh -c \
  'printf "CONNECT httpbin.org:443 HTTP/1.1\r\nHost: httpbin.org:443\r\n\r\n" | nc -w 2 127.0.0.1 3128 | head -n 1' || true)
assert_contains "200" "$code_after" "dominio httpbin.org permitido e funcional apos reload-allowlist"

# 6. Assercao crucial: a porta SSH NAO mudou (sessao do Orca preservada)
port_after=$(podman port "asb-${WS}-agent" 22 | head -n 1 | awk -F: '{print $NF}')
assert_eq "$port_before" "$port_after" "porta SSH publicada permanece rigorosamente identica"

# 7. O perfil DENTRO do workspace e gravavel pelo agente. A politica de
# egresso e do operador: um dominio que o agente acrescente ao proprio
# .agent-sandbox.toml NAO pode entrar na allowlist, mesmo com mtime mais novo
# e mesmo que o operador rode o reload por outro motivo qualquer.
repo_name=$(basename "$repo")
ws_conf="$HOME/asb-agent/$repo_name/$WS/$repo_name/.agent-sandbox.toml"
sleep 1 # mtime posterior ao do origin: e a condicao que a heuristica premiava
cat > "$ws_conf" <<'TOML'
[network]
allow = ["httpbin.org", "example.com"]
TOML

OUT_RELOAD2=$("$ROOT/cli/asb-agent" reload-allowlist --workspace "$WS" 2>&1); RC_RELOAD2=$?
assert_eq "0" "$RC_RELOAD2" "reload-allowlist com config editado no clone sai 0"

# CONTROLE NEGATIVO
code_clone=$(podman exec "asb-${WS}-proxy" sh -c \
  'printf "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n" | nc -w 2 127.0.0.1 3128 | head -n 1' || true)
assert_contains "403" "$code_clone" "dominio escrito pelo AGENTE no clone continua recusado"

# CONTROLE POSITIVO do mesmo reload: sem ele, o 403 acima poderia significar
# apenas que a recarga nao aconteceu, e a assercao passaria de graca.
code_origin=$(podman exec "asb-${WS}-proxy" sh -c \
  'printf "CONNECT httpbin.org:443 HTTP/1.1\r\nHost: httpbin.org:443\r\n\r\n" | nc -w 2 127.0.0.1 3128 | head -n 1' || true)
assert_contains "200" "$code_origin" "dominio do perfil do OPERADOR segue permitido apos o mesmo reload"

report
