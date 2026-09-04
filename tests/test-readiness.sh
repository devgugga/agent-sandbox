#!/usr/bin/env bash
# tests/test-readiness.sh — readiness de boot e do proxy.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== readiness de rede e proxy =="

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

wait_out=$(ROOT="$PWD" HOME="$tmp" bash -c '
  source "$ROOT/cli/lib/pod.sh"
  probes=0
  asb_host_network_ready() {
    probes=$((probes + 1))
    [ "$probes" -ge 3 ]
  }
  ASB_NETWORK_WAIT_ATTEMPTS=3
  ASB_NETWORK_WAIT_INTERVAL=0
  asb_wait_for_host_network
  printf "%s" "$probes"
' 2>/dev/null)
assert_eq "3" "$wait_out" "restore espera a rede ficar pronta"

assert_fails "timeout de rede retorna falha para permitir retry do systemd" \
  env ROOT="$PWD" HOME="$tmp" bash -c '
    source "$ROOT/cli/lib/pod.sh"
    asb_host_network_ready() { return 1; }
    ASB_NETWORK_WAIT_ATTEMPTS=2
    ASB_NETWORK_WAIT_INTERVAL=0
    asb_wait_for_host_network
  '

proxy_out=$(ROOT="$PWD" HOME="$tmp" bash -c '
  source "$ROOT/cli/lib/pod.sh"
  probes=0
  asb_proxy_probe() {
    probes=$((probes + 1))
    [ "$probes" -ge 2 ]
  }
  ASB_PROXY_READY_ATTEMPTS=2
  ASB_PROXY_READY_INTERVAL=0
  asb_wait_for_proxy healthy-pod
  printf "%s" "$probes"
' 2>/dev/null)
assert_eq "2" "$proxy_out" "lifecycle espera prova real do proxy"

mkdir -p "$tmp/bin"
cat > "$tmp/bin/systemctl" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$tmp/bin/systemctl"
HOME="$tmp" PATH="$tmp/bin:$PATH" ./cli/agent-sandbox install-autostart \
  >/dev/null 2>&1
unit="$tmp/.config/systemd/user/agent-sandbox-restore.service"
assert_contains "Restart=on-failure" "$(cat "$unit")" \
  "unidade repete restore que falha por rede indisponivel"
assert_contains "RestartSec=5s" "$(cat "$unit")" \
  "retry da unidade tem backoff curto"
assert_contains "TimeoutStartSec=" "$(cat "$unit")" \
  "oneshot de restore tem deadline explicito"

mkdir -p "$tmp/hung-bin"
cat > "$tmp/hung-bin/ip" <<'SH'
#!/usr/bin/env bash
printf 'default via 192.0.2.1 dev test0\n'
SH
cat > "$tmp/hung-bin/getent" <<'SH'
#!/usr/bin/env bash
/usr/bin/sleep 10
SH
chmod +x "$tmp/hung-bin/ip" "$tmp/hung-bin/getent"
HOME="$tmp" PATH="$tmp/hung-bin:$PATH" ROOT="$PWD" \
  ASB_NETWORK_PROBE_TIMEOUT=0.1 ASB_NETWORK_WAIT_ATTEMPTS=1 \
  timeout 2 bash -c 'source "$ROOT/cli/lib/pod.sh"; asb_wait_for_host_network' \
  >/dev/null 2>&1
assert_eq "1" "$?" "NSS travado e interrompido pelo deadline interno"

report
