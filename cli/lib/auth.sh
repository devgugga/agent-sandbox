#!/usr/bin/env bash
# cli/lib/auth.sh — cria a imagem autenticada a partir da base
set -euo pipefail

asb_wait_for_secret_service() {
  local c="$1"
  local attempts="${ASB_AUTH_READY_ATTEMPTS:-20}"
  local interval="${ASB_AUTH_READY_INTERVAL:-0.5}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if timeout "${ASB_AUTH_SERVICE_PROBE_TIMEOUT:-2}" \
      podman exec -u agent "$c" bash -lc \
      'dbus-send --session --dest=org.freedesktop.secrets --type=method_call --print-reply /org/freedesktop/DBus org.freedesktop.DBus.Peer.Ping' \
      >/dev/null 2>&1; then
      return 0
    fi
    [ "$i" -eq "$attempts" ] || sleep "$interval"
  done
  echo "Secret Service indisponivel apos $attempts tentativa(s)" >&2
  return 1
}

asb_auth() (
  local c=asb-auth
  asb_ensure_keyring_pass
  podman rm -f "$c" >/dev/null 2>&1 || true
  trap 'podman rm -f "$c" >/dev/null 2>&1 || true' EXIT
  # Entrypoint REAL, igual ao runtime: e ele quem sobe o dbus e o keyring e
  # popula /etc/profile.d. Com "--entrypoint sleep" nada disso acontece e o
  # agy cai no fallback de arquivo em texto puro.
  podman run -d --name "$c" -e ASB_KEYRING_PASS="$(cat "$ASB_KEYRING_PASS_FILE")" \
    agent-sandbox-base >/dev/null
  asb_wait_for_secret_service "$c" || {
    echo "abortado: o agy gravaria a credencial fora do keyring cifrado" >&2
    return 1
  }

  cat >&2 <<EOF

Faça os três logins AGORA, em outro terminal, um de cada vez:

  podman exec -it -u agent $c bash -lc 'claude /login'
  podman exec -it -u agent $c bash -lc 'codex login --device-auth'
  podman exec -it -u agent $c bash -lc agy

O 'bash -lc' nao e enfeite: sem shell de login o PATH nao tem o agy e o
DBUS nao aparece — e ai o agy grava a credencial em texto puro.

O agy NAO tem subcomando 'login' — rodar 'agy' puro abre o TUI, que dispara
o fluxo de autenticacao no primeiro uso. Sobre um terminal headless ele
imprime URL + codigo de ativacao para voce abrir no navegador do host.

Use SEMPRE o fluxo device-auth. O OAuth padrão abre um servidor de callback
numa porta do container que seu navegador não alcança, e trava.

Quando terminar, pressione ENTER aqui.
EOF
  read -r _

  # Verificar pelo EXIT CODE. Nunca por grep de "logged in": a string casa
  # tambem com "not logged in" e commitaria uma imagem nao autenticada.
  local failed=0
  timeout "${ASB_AUTH_AGENT_TIMEOUT:-90}" \
    podman exec -u agent "$c" bash -lc 'codex login status' >/dev/null 2>&1 \
    || { echo "codex NAO autenticado" >&2; failed=1; }
  timeout "${ASB_AUTH_AGENT_TIMEOUT:-90}" \
    podman exec -u agent "$c" bash -lc \
    'claude -p "responda apenas: ok"' >/dev/null 2>&1 \
    || { echo "claude NAO autenticado" >&2; failed=1; }
  timeout "${ASB_AUTH_AGENT_TIMEOUT:-90}" \
    podman exec -u agent "$c" bash -lc \
    'asb-agy -p "responda apenas: ok" --print-timeout 60s' >/dev/null 2>&1 \
    || { echo "Antigravity NAO autenticado" >&2; failed=1; }
  if [ "$failed" -ne 0 ]; then
    echo "abortado: nao vou commitar uma imagem nao autenticada" >&2
    return 1
  fi

  # Forcar o entrypoint de volta ao sshd: sem isso a imagem herda 'sleep'.
  podman commit --change='ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]' \
    "$c" agent-sandbox-auth >&2
  echo "imagem agent-sandbox-auth criada" >&2
)
