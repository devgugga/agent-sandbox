#!/usr/bin/env bash
# tests/test-doctor.sh — diagnostico do ambiente.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

echo "== doctor =="
OUT=$("$ROOT/cli/asb-agent" doctor 2>&1); RC=$?

require "doctor produz saida" sh -c '[ -n "'"$(printf %s "$OUT" | head -c 1)"'" ]'

assert_contains "podman" "$OUT" "verifica o podman"
assert_contains "python" "$OUT" "verifica a versao do python"
assert_contains "agent-sandbox:latest" "$OUT" "verifica a imagem base"
assert_contains "asb-credentials" "$OUT" "verifica o volume de credenciais"
assert_contains "podman-restart" "$OUT" "verifica a restauracao no boot"

# Toda falha precisa nomear o comando exato. "algo esta errado" e inutil as 2h
# da manha, e e o requisito da §16.1.
if [ "$RC" -ne 0 ]; then
  assert_contains "asb-agent" "$OUT" "toda falha nomeia um comando a executar"
fi

echo "-- purge exige confirmacao --"
assert_fails "purge sem --yes e recusado" \
  "$ROOT/cli/asb-agent" purge --workspace inexistente

report
