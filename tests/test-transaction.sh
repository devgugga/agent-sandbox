#!/usr/bin/env bash
# tests/test-transaction.sh — criacao transacional e rollback por ID
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

# 5. up em workspace existente falha com erro e NUNCA destroi containers preexistentes
if "$ROOT/cli/asb-agent" up --workspace "$WS_ROLLBACK" --repo "$repo" >/dev/null 2>&1; then
  existing_up_rc=0
else
  existing_up_rc=$?
fi
assert_fails "up em workspace existente falha com erro" [ "$existing_up_rc" -eq 0 ]
assert_eq "0" "$(podman container exists "asb-${WS_ROLLBACK}-agent"; echo $?)" \
  "container do agente permanece ativo apos falha de up sobre workspace existente"
assert_eq "0" "$(podman container exists "asb-${WS_ROLLBACK}-proxy"; echo $?)" \
  "proxy do workspace permanece ativo apos falha de up sobre workspace existente"

"$ROOT/cli/asb-agent" down --workspace "$WS_ROLLBACK" >/dev/null 2>&1

echo "-- isolamento entre workspaces irmaos (sem destruicao por prefixo) --"
WS_A="test-demo-$$"
WS_B="test-demo-$$-2"

cleanup_siblings() {
  "$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1 || true
  "$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1 || true
}
trap 'cleanup; cleanup_siblings' EXIT

"$ROOT/cli/asb-agent" up --workspace "$WS_A" --repo "$repo" >/dev/null 2>&1
"$ROOT/cli/asb-agent" up --workspace "$WS_B" --repo "$repo" >/dev/null 2>&1

assert_eq "0" "$(podman container exists "asb-${WS_A}-agent"; echo $?)" \
  "workspace A esta ativo antes do teste"
assert_eq "0" "$(podman container exists "asb-${WS_B}-agent"; echo $?)" \
  "workspace B (prefixado por A) esta ativo antes do teste"

# down de WS_A NAO pode derrubar containers de WS_B
"$ROOT/cli/asb-agent" down --workspace "$WS_A" >/dev/null 2>&1

assert_eq "1" "$(podman container exists "asb-${WS_A}-agent"; echo $?)" \
  "containers do workspace A foram removidos no down"
assert_eq "0" "$(podman container exists "asb-${WS_B}-agent"; echo $?)" \
  "containers do workspace B (irmao) permanecem intactos apos down do workspace A"
assert_eq "0" "$(podman container exists "asb-${WS_B}-proxy"; echo $?)" \
  "proxy do workspace B permanece intacto apos down do workspace A"

"$ROOT/cli/asb-agent" down --workspace "$WS_B" >/dev/null 2>&1

report
