#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd
set -euo pipefail

# Estes arquivos podem ser atualizados em um container autenticado antigo antes
# do start. Trave a propriedade antes de criar qualquer processo uid 1000.
chown root:root /usr/local/bin/entrypoint.sh /usr/local/bin/asb-agent \
  /usr/local/bin/asb-install-config
chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/asb-agent \
  /usr/local/bin/asb-install-config

# Propagar variaveis de ambiente do container para as sessoes SSH via PAM e profile
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|PATH)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<'ENV_EOF'
# Sem default fixo: o container de autenticacao roda fora do pod e nao tem
# Squid em 127.0.0.1:3128 — um default apontaria para um proxy inexistente e
# quebraria os logins. Quem define o proxy e o pod, via -e.
[ -n "${HTTPS_PROXY:-}" ] && export HTTPS_PROXY="$HTTPS_PROXY"
[ -n "${HTTP_PROXY:-}" ] && export HTTP_PROXY="$HTTP_PROXY"
[ -n "${NO_PROXY:-}" ] && export NO_PROXY="$NO_PROXY"
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

# Fail-closed. O netns do pod perde as regras nft toda vez que o pod para (um
# reboot, por exemplo), e `podman pod start` sobe este container do mesmo jeito
# — sem firewall e sem proxy. Medido: curl direto para a internet respondendo
# 200 dentro do sandbox. Se daqui da para sair sem proxy, a fronteira nao
# existe: e melhor nao servir SSH nenhum do que servir um sandbox falso.
#
# So vale dentro do pod: ASB_ENFORCE_FIREWALL nao e definido no container de
# autenticacao, que roda fora do pod e precisa de egresso direto para o login.
#
# Deteccao positiva apenas: sem rede alguma o teste nao acusa (e ai tambem nao
# ha egresso a proteger).
if [ "${ASB_ENFORCE_FIREWALL:-}" = "1" ]; then
  if timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/443' 2>/dev/null; then
    echo "agent-sandbox: EGRESSO DIRETO DETECTADO — o firewall do pod nao esta" >&2
    echo "agent-sandbox: aplicado. Recusando subir o sshd. Use 'agent-sandbox" >&2
    echo "agent-sandbox: resume', que reaplica as regras antes de subir o agente." >&2
    exit 1
  fi

  # O container e criado antes do start e o host atualiza runtime/config por
  # `podman exec`. SSH so fica disponivel depois do marcador, eliminando a
  # corrida com o Orca, que ja conhece a porta salva apos reboot.
  token_file=/run/agent-sandbox-provision-token
  if [ ! -r "$token_file" ]; then
    echo "agent-sandbox: token de provisionamento ausente" >&2
    exit 1
  fi
  provision_token=$(cat "$token_file")
  case "$provision_token" in
    ''|*[!a-f0-9]*) echo "agent-sandbox: token de provisionamento invalido" >&2; exit 1 ;;
  esac
  rm -f "$token_file"
  provision_marker="/run/agent-sandbox-provisioned-$provision_token"
  rm -f "$provision_marker"
  if ! timeout "${ASB_PROVISION_TIMEOUT:-120}" bash -c \
      'until [ -f "$1" ]; do sleep 0.1; done' _ "$provision_marker"; then
    echo "agent-sandbox: provisionamento nao concluiu; recusando subir sshd" >&2
    exit 1
  fi
  rm -f "$provision_marker"
fi

# NAO gerar host keys aqui: elas vem do build. Gerar apenas se sumirem.
[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
