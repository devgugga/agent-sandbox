#!/usr/bin/env bash
# tests/test-profile.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "isolated"

[services.postgres]
image = "postgres:14"
port = 5432

[network]
allow = ["registry.npmjs.org"]

[proxy]
java = true
TOML

echo "== Task 3: perfil =="
json=$(python3 cli/lib/profile.py "$tmp")
assert_eq "isolated" "$(echo "$json" | jq -r .mode)" "le o modo"
assert_eq "postgres:14" "$(echo "$json" | jq -r '.services.postgres.image')" "le a imagem do servico"
assert_eq "5432" "$(echo "$json" | jq -r '.services.postgres.port')" "le a porta do servico"
assert_eq "registry.npmjs.org" "$(echo "$json" | jq -r '.allow[0]')" "le a allowlist do projeto"
assert_eq "true" "$(echo "$json" | jq -r '.proxy.java')" "le a flag de proxy java"

# ausencia de arquivo cai no default, nao quebra
json2=$(python3 cli/lib/profile.py "$tmp/inexistente")
assert_eq "isolated" "$(echo "$json2" | jq -r .mode)" "default aplicado quando nao ha perfil"

# squid.conf gerado contem base + projeto
conf=$(python3 cli/lib/render_squid.py image/squid/allowlist-base.txt <(echo "$json"))
assert_contains ".anthropic.com" "$conf" "allowlist base entra no squid.conf"
assert_contains "registry.npmjs.org" "$conf" "allowlist do projeto entra no squid.conf"
assert_contains "http_access deny all" "$conf" "default-deny preservado"
assert_contains "http_port 3128" "$conf" "porta do proxy preservada"

report
