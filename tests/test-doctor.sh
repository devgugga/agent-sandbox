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
assert_contains "asb-toolcache" "$OUT" "verifica o volume de toolcache"
assert_contains "asb-keyring" "$OUT" "verifica o container de Secret Service"
assert_contains "podman-restart" "$OUT" "verifica a restauracao no boot"

# Toda falha precisa nomear o comando exato. "algo esta errado" e inutil as 2h
# da manha, e e o requisito da §16.1.
if [ "$RC" -ne 0 ]; then
  assert_contains "asb-agent" "$OUT" "toda falha nomeia um comando a executar"
fi

echo "-- purge exige confirmacao --"
assert_fails "purge sem --yes e recusado" \
  "$ROOT/cli/asb-agent" purge --workspace inexistente

echo "-- sonda de egresso de workspace (controle positivo e negativo) --"
tmp=$(mktemp -d)
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.email t@e.com
git -C "$repo" config user.name T
echo ok > "$repo/README.md"
touch "$repo/.agent-sandbox.toml"
git -C "$repo" add -A && git -C "$repo" commit -qm inicial

WS_DOC="test-doctor-probe-$$"
cleanup() {
  "$ROOT/cli/asb-agent" purge --workspace "$WS_DOC" --yes >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

require "workspace de teste sobe para teste de egresso do doctor" \
  "$ROOT/cli/asb-agent" up --workspace "$WS_DOC" --repo "$repo"

# 1. Controle positivo: sonda de egresso do workspace e validada sem depender da saude global do host
DOC_POS=$("$ROOT/cli/asb-agent" doctor 2>&1)
assert_contains "$WS_DOC: rodando (egresso ok)" "$DOC_POS" \
  "controle positivo: sonda de egresso confirma conectividade de ponta a ponta"
assert_contains "Secret Service (asb-keyring)" "$DOC_POS" \
  "controle positivo: Secret Service singleton saudavel"
assert_not_contains "FALTA $WS_DOC" "$DOC_POS" \
  "controle positivo: nenhum erro reportado para o workspace de teste"

# 2. Controle negativo: desconectar rede externa simula perda de uplink rootless (falha do pasta)
podman network disconnect "asb-${WS_DOC}-out" "asb-${WS_DOC}-proxy"

DOC_NEG=$("$ROOT/cli/asb-agent" doctor 2>&1); RC_NEG=$?
assert_eq "1" "$RC_NEG" "doctor falha com codigo 1 quando o egresso cai"
assert_contains "FALTA $WS_DOC: uplink rootless morto (Network is unreachable)" "$DOC_NEG" \
  "controle negativo: diagnostico identifica queda de uplink rootless"
assert_contains "asb-agent suspend --workspace <id>; depois asb-agent resume --workspace <id>" "$DOC_NEG" \
  "controle negativo: diagnostico instrui recriar os workspaces para recuperar o uplink"
assert_not_contains "--rootless-netns" "$DOC_NEG" \
  "controle negativo: diagnostico nao recomenda o unshare que o piloto reprovou"

"$ROOT/cli/asb-agent" down --workspace "$WS_DOC" >/dev/null 2>&1 || true

report
