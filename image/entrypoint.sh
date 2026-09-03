#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd
set -euo pipefail

# Propagar variaveis de ambiente do container para as sessoes SSH via PAM e profile
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|GEMINI_SANDBOX|CLAUDE_CODE_SUBPROCESS_ENV_SCRUB|PATH)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<'ENV_EOF'
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:3128}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:3128}"
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export GEMINI_SANDBOX=false
export CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1
export PATH="/home/agent/.local/bin:/home/agent/.local/share/mise/shims:${PATH}"
ENV_EOF

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o agent -g agent /home/agent/.ssh
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > /home/agent/.ssh/authorized_keys
  chown agent:agent /home/agent/.ssh/authorized_keys
  chmod 0600 /home/agent/.ssh/authorized_keys
fi

# NAO gerar host keys aqui: elas vem do build. Gerar apenas se sumirem.
[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
