#!/usr/bin/env bash
# cli/lib/attach.sh — modo anexado: encaminhador TCP em loopback como uid 900.
# O agente (uid 1000) fala com 127.0.0.1:<porta>; quem sai e o uid 900, ja
# permitido pelo firewall. O .env do projeto permanece intocado.
set -euo pipefail

asb_attach() {
  local pod="$1" profile="$2"
  # gateway do host visto de dentro do netns
  local hostip
  hostip=$(podman run --rm --pod "$pod" agent-sandbox-net \
    sh -c "ip route | awk '/default/{print \$3; exit}'")
  [ -n "$hostip" ] || { echo "nao foi possivel achar o IP do host" >&2; return 1; }

  python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))
for e in p.get("attach", []):
    print(e["port"])
' "$profile" | while read -r port; do
    podman run -d --name "${pod}-fwd-${port}" --pod "$pod" --user 900 \
      agent-sandbox-net \
      socat "TCP-LISTEN:${port},bind=127.0.0.1,fork,reuseaddr" "TCP:${hostip}:${port}" >/dev/null
    echo "anexado: 127.0.0.1:${port} -> ${hostip}:${port}" >&2
  done
}
