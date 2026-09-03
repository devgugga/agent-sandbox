#!/usr/bin/env bash
# Roda como o usuario 'agent'. Destrava o keyring e imprime, no stdout, as
# variaveis que as sessoes SSH precisam herdar (o entrypoint redireciona a
# saida para /etc/profile.d/).
#
# O agy guarda a credencial no Secret Service (org.freedesktop.secrets), nao em
# arquivo. Sem um keyring destravado aqui dentro ele nao acha a sessao logada.
set -euo pipefail
pass_file=/run/asb-keyring-pass
[ -f "$pass_file" ] || exit 0

mkdir -p "$HOME/.local/share/keyrings"
eval "$(dbus-launch --sh-syntax)"
# --unlock le a passphrase do stdin e imprime atribuicoes de ambiente.
eval "$(gnome-keyring-daemon --unlock --components=secrets < "$pass_file")" || true
# A remocao e do entrypoint (root): este script roda como 'agent', que nao
# tem permissao de escrita em /run — e com set -e o rm abortaria tudo antes
# de imprimir as variaveis de ambiente.

# Aspas duplas, nao %q: o endereco do dbus contem virgula, e o %q a escapa
# com barra invertida — que o pam_env repassa literalmente, quebrando o caminho
# do socket ("Could not connect: No such file or directory").
printf 'export DBUS_SESSION_BUS_ADDRESS="%s"\n' "${DBUS_SESSION_BUS_ADDRESS:-}"
[ -n "${GNOME_KEYRING_CONTROL:-}" ] && \
  printf 'export GNOME_KEYRING_CONTROL="%s"\n' "$GNOME_KEYRING_CONTROL"
exit 0
