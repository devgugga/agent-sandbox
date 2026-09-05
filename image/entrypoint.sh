#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd.
#
# Muito menor que o do v1 de proposito. Sumiram: a sonda de egresso direto (a
# topologia da rede e que isola agora, e ela nao pode "nao ter subido"), o
# token de provisionamento e o portao do sshd (a configuracao chega como mount
# read-only, entao nao ha janela de TOCTOU a fechar).
set -euo pipefail

ASB_USER=$(id -un 1000)
ASB_HOME=$(getent passwd 1000 | cut -d: -f6)

# O OpenSSH descarta o ambiente do processo pai ao criar a sessao do usuario.
# /etc/environment e lido pelo PAM (inclusive em `ssh host 'cmd'`, que NAO e
# shell de login); /etc/profile.d cobre os shells de login.
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|PATH)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<ENV_EOF
# Sem default fixo: o container de login roda FORA da rede interna e nao tem
# proxy algum. Um default apontando para um proxy inexistente quebraria os
# logins. Quem define o proxy e quem cria o container, via -e.
[ -n "\${HTTPS_PROXY:-}" ] && export HTTPS_PROXY="\$HTTPS_PROXY"
[ -n "\${HTTP_PROXY:-}" ] && export HTTP_PROXY="\$HTTP_PROXY"
[ -n "\${NO_PROXY:-}" ] && export NO_PROXY="\$NO_PROXY"
export PATH="$ASB_HOME/.local/bin:$ASB_HOME/.local/share/mise/shims:\${PATH}"
ENV_EOF

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o "$ASB_USER" -g "$ASB_USER" "$ASB_HOME/.ssh"
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > "$ASB_HOME/.ssh/authorized_keys"
  chown "$ASB_USER:$ASB_USER" "$ASB_HOME/.ssh/authorized_keys"
  chmod 0600 "$ASB_HOME/.ssh/authorized_keys"
fi

# O agy guarda credencial no Secret Service, nao em arquivo. A passphrase chega
# em RUNTIME e nunca e assada na imagem, entao o volume de credenciais sozinho
# carrega um keyring cifrado inutil.
if [ -n "${ASB_KEYRING_PASS:-}" ]; then
  printf '%s' "$ASB_KEYRING_PASS" > /run/asb-keyring-pass
  chown "$ASB_USER:$ASB_USER" /run/asb-keyring-pass
  chmod 0600 /run/asb-keyring-pass
  unset ASB_KEYRING_PASS
  su "$ASB_USER" -c /usr/local/bin/start-keyring.sh \
    > /etc/profile.d/agent-keyring.sh 2>/dev/null || true
  rm -f /run/asb-keyring-pass
  chmod 0644 /etc/profile.d/agent-keyring.sh
  # `ssh host 'cmd'` nao le /etc/profile.d. O formato de /etc/environment nao
  # aceita o prefixo `export`, entao ele e removido.
  sed 's/^export //' /etc/profile.d/agent-keyring.sh \
    | tr -d "'\"" >> /etc/environment || true
fi

[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec /usr/sbin/sshd -D -e
