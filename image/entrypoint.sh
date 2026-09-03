#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd
set -euo pipefail

# Propagar variaveis de ambiente do container para as sessoes SSH via PAM e profile
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|CLAUDE_CODE_SUBPROCESS_ENV_SCRUB|PATH)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<'ENV_EOF'
# Sem default fixo: o container de autenticacao roda fora do pod e nao tem
# Squid em 127.0.0.1:3128 — um default apontaria para um proxy inexistente e
# quebraria os logins. Quem define o proxy e o pod, via -e.
[ -n "${HTTPS_PROXY:-}" ] && export HTTPS_PROXY="$HTTPS_PROXY"
[ -n "${HTTP_PROXY:-}" ] && export HTTP_PROXY="$HTTP_PROXY"
[ -n "${NO_PROXY:-}" ] && export NO_PROXY="$NO_PROXY"
export CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1
export PATH="/home/agent/.local/bin:/home/agent/.local/share/mise/shims:${PATH}"
ENV_EOF

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o agent -g agent /home/agent/.ssh
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > /home/agent/.ssh/authorized_keys
  chown agent:agent /home/agent/.ssh/authorized_keys
  chmod 0600 /home/agent/.ssh/authorized_keys
fi

# Keyring: o agy guarda credencial no Secret Service, nao em arquivo. A
# passphrase chega em RUNTIME (nunca e assada na imagem), entao a imagem
# autenticada sozinha e um keyring cifrado inutil.
if [ -n "${ASB_KEYRING_PASS:-}" ]; then
  printf '%s' "$ASB_KEYRING_PASS" > /run/asb-keyring-pass
  chown agent:agent /run/asb-keyring-pass
  chmod 0600 /run/asb-keyring-pass
  unset ASB_KEYRING_PASS
  su agent -c /usr/local/bin/start-keyring.sh > /etc/profile.d/agent-keyring.sh 2>/dev/null || true
  rm -f /run/asb-keyring-pass
  chmod 0644 /etc/profile.d/agent-keyring.sh
  # `ssh host 'cmd'` nao e shell de login e nao le /etc/profile.d. O PAM do
  # sshd le /etc/environment, entao as variaveis do keyring vao para la
  # tambem, sem o prefixo 'export' (formato do arquivo nao aceita).
  sed 's/^export //' /etc/profile.d/agent-keyring.sh \
    | tr -d "'\"" >> /etc/environment || true
fi

# NAO gerar host keys aqui: elas vem do build. Gerar apenas se sumirem.
[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
