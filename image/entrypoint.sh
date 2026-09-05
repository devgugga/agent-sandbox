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

# Configuracao do host: chega como mount READ-ONLY e e copiada para o home. Nao
# se monta direto sobre ~/.claude/settings.json porque os agentes escrevem
# nesses arquivos durante a sessao. Como a ORIGEM e um mount que o agente nao
# escreve, nao ha janela de TOCTOU — e por isso sumiram o instalador root, o
# token por partida e o portao do sshd que o v1 precisava.
if [ -f /run/asb-config/manifest.tsv ]; then
  while IFS=$'\t' read -r src dst; do
    [ -n "$src" ] || continue
    install -d -o "$ASB_USER" -g "$ASB_USER" "$(dirname "$dst")"
    rm -rf "$dst"
    cp -a "/run/asb-config/$src" "$dst"
    chown -R "$ASB_USER:$ASB_USER" "$dst"
  done < /run/asb-config/manifest.tsv
fi

# Credenciais: o volume e a fonte, e o caminho real e um LINK para dentro dele.
# Nao uma copia: os agentes renovam o token durante a sessao, e uma copia
# perderia a renovacao na proxima partida — que e exatamente o sintoma de
# "perdi a sessao" que este redesenho existe para eliminar.
if [ -d /run/asb-credentials ]; then
  link_credential() {
    real="$1"; stored="/run/asb-credentials/$2"
    install -d -o "$ASB_USER" -g "$ASB_USER" "$(dirname "$real")"
    [ -e "$stored" ] || [ -d "$stored" ] || {
      : > "$stored"; chmod 0600 "$stored"; }
    rm -rf "$real"
    ln -s "$stored" "$real"
    chown -h "$ASB_USER:$ASB_USER" "$real"
  }
  install -d -o "$ASB_USER" -g "$ASB_USER" -m 0700 /run/asb-credentials/keyrings
  link_credential "$ASB_HOME/.claude/.credentials.json" claude.json
  link_credential "$ASB_HOME/.codex/auth.json"          codex-auth.json
  link_credential "$ASB_HOME/.local/share/keyrings"     keyrings
  chown -R "$ASB_USER:$ASB_USER" /run/asb-credentials
fi

if [ -d "$ASB_HOME/.local/share/containers" ]; then
  chown -R "$ASB_USER:$ASB_USER" "$ASB_HOME/.local/share/containers"
fi

# O projeto continua apontando para localhost:5432. Sem pod, o agente e o
# encaminhador estao em namespaces separados, entao um socat local recria o
# endereco que o projeto espera. Dois saltos triviais; a alternativa seria
# reescrever a configuracao de cada projeto.
if [ -n "${ASB_HOST_PORTS:-}" ]; then
  fwd="asb-${ASB_WORKSPACE}-fwd"
  echo "$ASB_HOST_PORTS" | tr ',' '\n' | while read -r port; do
    [ -n "$port" ] || continue
    setsid socat "TCP-LISTEN:${port},bind=127.0.0.1,fork,reuseaddr" \
      "TCP:${fwd}:${port}" >/dev/null 2>&1 &
  done
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec /usr/sbin/sshd -D -e
