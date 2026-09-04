#!/usr/bin/env bash
# cli/lib/doctor.sh — diagnostico read-only dos pre-requisitos e pods.
set -euo pipefail

asb_doctor_ok() { printf 'OK    %s\n' "$1"; }
asb_doctor_fail() { printf 'FALHA %s\n' "$1"; }

asb_doctor() {
  local failures=0 path permission pod image
  local -a pods=()

  if command -v podman >/dev/null 2>&1; then
    asb_doctor_ok "Podman disponivel"
  else
    asb_doctor_fail "Podman ausente"
    return 1
  fi

  for image in agent-sandbox-base agent-sandbox-net agent-sandbox-auth; do
    if podman image exists "$image"; then
      asb_doctor_ok "imagem $image"
    else
      asb_doctor_fail "imagem $image ausente"
      failures=$((failures + 1))
    fi
  done

  for path in "$ASB_KEY" "${ASB_KEY}.pub" "$ASB_KEYRING_PASS_FILE"; do
    if [ -f "$path" ]; then
      asb_doctor_ok "arquivo $path"
    else
      asb_doctor_fail "arquivo ausente: $path"
      failures=$((failures + 1))
    fi
  done
  for path in "$ASB_KEY" "$ASB_KEYRING_PASS_FILE"; do
    [ -f "$path" ] || continue
    permission=$(stat -c '%a' "$path" 2>/dev/null || printf '?')
    case "$permission" in
      600|400) asb_doctor_ok "permissao $permission em $path" ;;
      *) asb_doctor_fail "permissao insegura $permission em $path (esperado 600)"
         failures=$((failures + 1)) ;;
    esac
  done

  mapfile -t pods < <(podman pod ls --format '{{.Name}}' | grep '^asb-' || true)
  for pod in "${pods[@]}"; do
    if [ -f "$(asb_state_dir "$pod")/squid.conf" ]; then
      asb_doctor_ok "$pod possui estado persistente"
    else
      asb_doctor_fail "$pod sem estado persistente"
      failures=$((failures + 1))
    fi

    image=$(podman inspect --format '{{.ImageName}}' "${pod}-agent" 2>/dev/null || true)
    case "$image" in
      *agent-sandbox-auth*) asb_doctor_ok "$pod usa imagem autenticada" ;;
      *) asb_doctor_fail "$pod nao usa agent-sandbox-auth"
         failures=$((failures + 1)) ;;
    esac

    if [ -z "$(podman ps --filter "name=${pod}-agent" --filter status=running -q)" ]; then
      asb_doctor_fail "$pod esta suspenso; saude de runtime nao verificavel"
      failures=$((failures + 1))
      continue
    fi
    if [ -z "$(podman ps --filter "name=${pod}-squid" --filter status=running -q)" ]; then
      asb_doctor_fail "$pod: proxy nao esta rodando"
      failures=$((failures + 1))
      continue
    fi
    if podman exec --privileged --user 0 "${pod}-squid" \
        nft list table inet asb >/dev/null 2>&1; then
      asb_doctor_ok "$pod: firewall aplicado"
    else
      asb_doctor_fail "$pod: firewall ausente"
      failures=$((failures + 1))
    fi
    if asb_proxy_probe "$pod"; then
      asb_doctor_ok "$pod: proxy possui rota, DNS e CONNECT"
    else
      asb_doctor_fail "$pod: proxy sem rota, DNS ou CONNECT"
      failures=$((failures + 1))
    fi
  done

  if [ "$failures" -eq 0 ]; then
    printf 'OK    diagnostico concluido sem falhas\n'
    return 0
  fi
  printf 'FALHA diagnostico encontrou %s problema(s)\n' "$failures"
  return 1
}
