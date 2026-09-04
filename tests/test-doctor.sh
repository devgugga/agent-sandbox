#!/usr/bin/env bash
# tests/test-doctor.sh — diagnostico observavel e fail-closed.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== doctor =="

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
home="$tmp/home"
config="$home/.config/agent-sandbox"
mkdir -p "$tmp/bin" "$config/pods/asb-demo"
printf 'key\n' > "$config/id_ed25519"
printf 'pub\n' > "$config/id_ed25519.pub"
printf 'pass\n' > "$config/keyring.pass"
printf 'config\n' > "$config/pods/asb-demo/squid.conf"
chmod 0600 "$config/id_ed25519" "$config/keyring.pass"

cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
case "$1 ${2:-} ${3:-}" in
  "image exists agent-sandbox-auth")
    [ "${ASB_TEST_MODE:-}" != missing-auth ]
    exit $?
    ;;
  "image exists agent-sandbox-base") exit 0 ;;
  "image exists agent-sandbox-net") [ "${ASB_TEST_MODE:-}" != missing-net ]; exit $? ;;
  "pod ls "*) printf 'asb-demo\n'; exit 0 ;;
esac
case "$*" in
  *"filter name=asb-demo-agent"*)
    [ "${ASB_TEST_MODE:-}" = stopped ] || printf 'agent-id\n'
    exit 0
    ;;
  *"filter name=asb-demo-squid"*) printf 'squid-id\n'; exit 0 ;;
  *"inspect --format "*"asb-demo-agent"*) printf 'localhost/agent-sandbox-auth:latest\n'; exit 0 ;;
  *"exec --user 900 asb-demo-squid"*)
    [ "${ASB_TEST_MODE:-}" != bad-proxy ]
    exit $?
    ;;
  *"nft list table inet asb"*) exit 0 ;;
esac
exit 0
SH
chmod +x "$tmp/bin/podman"

run_doctor() {
  HOME="$home" XDG_CONFIG_HOME="$home/.config" PATH="$tmp/bin:$PATH" \
    ASB_TEST_MODE="$1" ./cli/agent-sandbox doctor 2>&1
}

healthy=$(run_doctor healthy)
healthy_rc=$?
assert_eq "0" "$healthy_rc" "doctor aprova ambiente saudavel"
assert_contains "OK" "$healthy" "doctor entrega diagnostico legivel"

missing=$(run_doctor missing-auth)
missing_rc=$?
assert_eq "1" "$missing_rc" "doctor reprova imagem auth ausente"
assert_contains "agent-sandbox-auth" "$missing" "doctor identifica a causa auth"

bad_proxy=$(run_doctor bad-proxy)
bad_proxy_rc=$?
assert_eq "1" "$bad_proxy_rc" "doctor reprova proxy sem conectividade"
assert_contains "proxy" "$bad_proxy" "doctor identifica a causa de rede"

stopped=$(run_doctor stopped)
stopped_rc=$?
assert_eq "1" "$stopped_rc" "doctor nao declara pod parado como saudavel"
assert_contains "suspenso" "$stopped" "doctor informa saude nao verificavel"

missing_net=$(run_doctor missing-net)
missing_net_rc=$?
assert_eq "1" "$missing_net_rc" "doctor exige a imagem da fronteira de rede"
assert_contains "agent-sandbox-net" "$missing_net" "doctor identifica imagem de rede ausente"

report
