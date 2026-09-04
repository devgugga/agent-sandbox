#!/usr/bin/env bash
# tests/test-guard.sh — o guarda asb-agent nos tres contextos.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
ROOT="$(pwd -P)"
GUARD="$ROOT/cli/asb-agent"
OTHER=$(mktemp -d); trap 'rm -rf "$OTHER"' EXIT

# Roda o guarda FORA da arvore de processos do Orca. Sem isso, qualquer teste
# executado de dentro de uma sessao do Orca herda orca-ide na ancestralidade e
# a deteccao de "lancamento automatico" acerta por acidente.
detached() {
  local dir="$1"; shift
  systemd-run --user --quiet --pipe --wait --working-directory="$dir" \
    --setenv=ASB_REPO_PATH="$ROOT" "$@" 2>&1
}

ln -sf "$GUARD" "$OTHER/asb-claude"

echo "== guarda de execucao =="

# CONTROLE POSITIVO: o binario real existe e responde. Sem isso, "bloqueado"
# nao prova nada — poderia ser apenas o agente ausente.
require "o binario real responde atraves do guarda" \
  systemd-run --user --quiet --pipe --wait --working-directory="$ROOT" \
    --setenv=ASB_REPO_PATH="$ROOT" "$OTHER/asb-claude" --version

out=$(detached "$ROOT" "$OTHER/asb-claude" --version)
assert_contains "Claude Code" "$out" "excecao: passa dentro do agent-sandbox"

out=$(detached "$OTHER" "$OTHER/asb-claude" --version)
assert_contains "Bloqueado" "$out" "bloqueia em projeto que nao e o agent-sandbox"

out=$(detached "$OTHER" "$OTHER/asb-claude")
assert_contains "chame o binario real" "$out" "humano ve a dica do binario real"

out=$(detached "$OTHER" "$OTHER/asb-claude" --dangerously-skip-permissions)
assert_contains "Bloqueado" "$out" "bloqueia lancamento automatico"
case "$out" in
  *"chame o binario real"*) echo "  FALHOU: dica de contorno exposta ao agente"; _fail=$((_fail+1)) ;;
  *) echo "  ok: dica de contorno oculta no lancamento automatico"; _pass=$((_pass+1)) ;;
esac

# Dentro da imagem o guarda tem de ser transparente, senao o agente nem inicia.
out=$(podman run --rm --entrypoint sh agent-sandbox-base -c 'asb-claude --version' 2>&1)
assert_contains "Claude Code" "$out" "transparente dentro do sandbox"
out=$(podman run --rm --entrypoint sh agent-sandbox-base -c 'test -f /etc/agent-sandbox-release && echo presente' 2>&1)
assert_contains "presente" "$out" "marcador do sandbox na imagem"

report
