#!/usr/bin/env bash
# tests/test-transaction.sh — criacao transacional e rollback via _sweep_containers
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

echo "== criacao transacional =="

tmp=$(mktemp -d)
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.email t@e.com
git -C "$repo" config user.name T
echo ok > "$repo/README.md"
git -C "$repo" add -A && git -C "$repo" commit -qm inicial

WS_ROLLBACK="test-tx-rb-$$"

cleanup() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_ROLLBACK" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

# 1. Forcar falha no up com servico cuja imagem nao existe.
# O proxy e as redes sobem antes; quando o servico falha, o bloco except
# de up dispara _sweep_containers e remove as redes.
cat > "$repo/.agent-sandbox.toml" <<'EOF'
[services.bad]
image = "invalid-local-image-that-does-not-exist:never"
EOF

if "$ROOT/cli/asb-agent" up --workspace "$WS_ROLLBACK" --repo "$repo" >/dev/null 2>&1; then
  rc=0
else
  rc=$?
fi
assert_fails "up falha quando servico tem imagem invalida" [ "$rc" -eq 0 ]

# 2. Assegurar que _sweep_containers removeu todos os containers asb-<ws>-*
surviving_containers=$(podman ps -a --filter "name=^asb-${WS_ROLLBACK}-" --format '{{.Names}}')
assert_eq "" "$surviving_containers" "nenhum container asb-<ws>-* sobrevive a falha forcada"

# 3. Assegurar que nenhuma rede asb-<ws> ou asb-<ws>-out sobrevive
surviving_networks=$(podman network ls --filter "name=^asb-${WS_ROLLBACK}" --format '{{.Name}}')
assert_eq "" "$surviving_networks" "nenhuma rede asb-<ws> sobrevive a falha forcada"

# 4. Um up que falhou no meio nao impede repeticao no mesmo workspace:
# no v1 ficavam restos que faziam a repeticao falhar com "workspace ja existe".
cat > "$repo/.agent-sandbox.toml" <<'EOF'
# perfil valido
EOF

if "$ROOT/cli/asb-agent" up --workspace "$WS_ROLLBACK" --repo "$repo" >/dev/null 2>&1; then
  retry_rc=0
else
  retry_rc=$?
fi
assert_eq "0" "$retry_rc" "repetir up apos rollback sucede sem erro de workspace existente"
assert_eq "0" "$(podman container exists "asb-${WS_ROLLBACK}-agent"; echo $?)" \
  "o container do agente existe apos up bem-sucedido"

"$ROOT/cli/asb-agent" down --workspace "$WS_ROLLBACK" >/dev/null 2>&1

report
