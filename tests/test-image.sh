#!/usr/bin/env bash
# tests/test-image.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== Task 1: imagem base =="
uid=$(podman run --rm --entrypoint id --user agent agent-sandbox-base -u 2>/dev/null)
assert_eq "1000" "$uid" "agente roda como uid 1000"

user=$(podman run --rm --entrypoint id --user agent agent-sandbox-base -un 2>/dev/null)
assert_eq "agent" "$user" "usuario e 'agent'"

# host key deve ser identica entre dois containers (assada no build)
fp1=$(podman run --rm --entrypoint ssh-keygen agent-sandbox-base -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')
fp2=$(podman run --rm --entrypoint ssh-keygen agent-sandbox-base -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')
assert_eq "$fp1" "$fp2" "host key estavel entre containers"
assert_contains "SHA256:" "$fp1" "host key existe e tem fingerprint"

# Usar assert_eq: um `false` solto nao incrementa o contador de falhas, e a
# suite sairia com 0 mesmo imprimindo FALHOU.
for bin in claude codex agy git gh rg mise sshd secret-tool; do
  if podman run --rm --entrypoint sh agent-sandbox-base -c "command -v $bin" >/dev/null 2>&1; then
    assert_eq "presente" "presente" "$bin presente"
  else
    assert_eq "presente" "AUSENTE" "$bin presente"
  fi
done

# o agente nao pode escalar privilegio dentro da imagem
assert_fails "sudo nao existe/nao funciona" podman run --rm --entrypoint sudo agent-sandbox-base -n true
assert_fails "sem socket de container montado" podman run --rm --entrypoint test agent-sandbox-base -S /var/run/docker.sock

report
