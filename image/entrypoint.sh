#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd
set -euo pipefail

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o agent -g agent /home/agent/.ssh
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > /home/agent/.ssh/authorized_keys
  chown agent:agent /home/agent/.ssh/authorized_keys
  chmod 0600 /home/agent/.ssh/authorized_keys
fi

# NAO gerar host keys aqui: elas vem do build. Gerar apenas se sumirem.
[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
