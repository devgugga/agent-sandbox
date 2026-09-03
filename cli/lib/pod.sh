#!/usr/bin/env bash
# cli/lib/pod.sh — ciclo de vida do pod. Fonte: source cli/lib/pod.sh
# Requer: ROOT (raiz do repo agent-sandbox)
set -euo pipefail

ASB_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox"
ASB_KEY="$ASB_CONFIG/id_ed25519"

asb_ensure_key() {
  [ -f "$ASB_KEY" ] && return 0
  mkdir -p "$ASB_CONFIG"; chmod 0700 "$ASB_CONFIG"
  ssh-keygen -t ed25519 -N '' -f "$ASB_KEY" -C agent-sandbox >&2
}

asb_up() {
  local ws="$1" repo="$2"
  local pod="asb-$ws"
  asb_ensure_key

  local profile squidconf
  profile=$(mktemp); squidconf=$(mktemp)
  python3 "$ROOT/cli/lib/profile.py" "$repo" > "$profile"
  python3 "$ROOT/cli/lib/render_squid.py" "$ROOT/image/squid/allowlist-base.txt" "$profile" > "$squidconf"

  podman pod exists "$pod" && podman pod rm -f "$pod" >/dev/null
  # porta 0 = o kernel sorteia; lemos de volta depois
  podman pod create --name "$pod" -p 127.0.0.1::22 >/dev/null
  podman pod start "$pod" >/dev/null

  # 1) firewall primeiro: nada sobe antes da fronteira existir
  podman run --rm --pod "$pod" --cap-add NET_ADMIN agent-sandbox-net \
    /usr/local/bin/apply.sh >&2

  # 2) proxy como uid 900 — o unico com egresso
  podman run -d --name "${pod}-squid" --pod "$pod" --user 900 \
    -v "$squidconf:/etc/squid/squid.conf:ro,Z" \
    agent-sandbox-net squid -N -f /etc/squid/squid.conf >/dev/null

  # 3) servicos declarados no perfil (modo isolado)
  python3 - "$profile" <<'PY' | while read -r name image; do
import json, sys
p = json.load(open(sys.argv[1]))
for name, svc in p.get("services", {}).items():
    print(name, svc["image"])
PY
    podman run -d --name "${pod}-${name}" --pod "$pod" \
      -e POSTGRES_PASSWORD=sandbox -e POSTGRES_USER=sandbox -e POSTGRES_DB=sandbox \
      "$image" >/dev/null
  done

  # 4) agente por ultimo, SEM NET_ADMIN
  local agent_image=agent-sandbox-base
  podman image exists agent-sandbox-auth && agent_image=agent-sandbox-auth

  podman run -d --name "${pod}-agent" --pod "$pod" \
    -e ORCA_SSH_PUBLIC_KEY="$(cat "${ASB_KEY}.pub")" \
    -e HTTPS_PROXY=http://127.0.0.1:3128 \
    -e HTTP_PROXY=http://127.0.0.1:3128 \
    -e NO_PROXY=127.0.0.1,localhost \
    -v "$repo:/workspace:Z" \
    "$agent_image" >/dev/null

  local port
  port=$(podman port "${pod}-agent" 22 2>/dev/null | head -1 | sed 's/.*://')
  [ -n "$port" ] || { echo "nao foi possivel determinar a porta SSH" >&2; return 1; }

  rm -f "$profile"
  printf '{"pod":"%s","port":%s,"user":"agent"}\n' "$pod" "$port"
}

asb_down() {
  local pod="asb-$1"
  podman pod exists "$pod" 2>/dev/null && podman pod rm -f "$pod" >/dev/null 2>&1
  return 0
}
