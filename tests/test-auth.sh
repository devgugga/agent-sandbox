#!/usr/bin/env bash
# tests/test-auth.sh — auth so gera imagem depois de provar os tres agentes.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== autenticacao verificavel =="

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/sleep" <<'SH'
#!/usr/bin/env bash
exit 0
SH
cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ASB_TEST_PODMAN_LOG"
case "$*" in
  *dbus-send*)
    count=$(cat "$ASB_TEST_DBUS_COUNT" 2>/dev/null || printf 0)
    count=$((count + 1))
    printf '%s\n' "$count" > "$ASB_TEST_DBUS_COUNT"
    [ "$count" -ge 3 ]
    exit $?
    ;;
  *"asb-agy -p"*) [ "${ASB_TEST_MODE:-}" != agy-fails ]; exit $? ;;
  *"claude -p"*)
    [ "${ASB_TEST_MODE:-}" != claude-hangs ] || /usr/bin/sleep 10
    exit 0
    ;;
esac
exit 0
SH
chmod +x "$tmp/bin/podman" "$tmp/bin/sleep"

run_auth() {
  local mode="$1" home="$tmp/home-$1" log="$tmp/$1.log"
  mkdir -p "$home/.config/agent-sandbox"
  printf 'test-pass\n' > "$home/.config/agent-sandbox/keyring.pass"
  chmod 0600 "$home/.config/agent-sandbox/keyring.pass"
  : > "$tmp/dbus-$mode"
  if printf '\n' | HOME="$home" XDG_CONFIG_HOME="$home/.config" \
      PATH="$tmp/bin:$PATH" ASB_TEST_MODE="$mode" \
      ASB_TEST_PODMAN_LOG="$log" ASB_TEST_DBUS_COUNT="$tmp/dbus-$mode" \
      ASB_AUTH_READY_ATTEMPTS=3 ASB_AUTH_READY_INTERVAL=0 \
      ASB_AUTH_AGENT_TIMEOUT="${ASB_AUTH_AGENT_TIMEOUT:-90}" \
      ./cli/agent-sandbox auth >/dev/null 2>&1; then
    printf 0
  else
    printf '%s' "$?"
  fi
}

assert_eq "0" "$(run_auth healthy)" "auth aceita os tres agentes verificados"
assert_eq "3" "$(cat "$tmp/dbus-healthy")" \
  "auth espera o Secret Service responder em vez de usar sleep fixo"
assert_contains "asb-agy -p" "$(cat "$tmp/healthy.log")" \
  "auth valida Antigravity de ponta a ponta"
assert_contains "commit" "$(cat "$tmp/healthy.log")" \
  "imagem e gerada depois das verificacoes"

assert_eq "1" "$(run_auth agy-fails)" "auth recusa quando Antigravity falha"
assert_eq "" "$(grep -F 'commit' "$tmp/agy-fails.log" || true)" \
  "falha do Antigravity impede commit da imagem"
assert_contains "rm -f asb-auth" "$(cat "$tmp/agy-fails.log")" \
  "container temporario sempre e limpo"

started=$SECONDS
timeout_result=$(ASB_AUTH_AGENT_TIMEOUT=0.1 run_auth claude-hangs)
assert_eq "1" "$timeout_result" \
  "auth interrompe verificacao de agente travada"
elapsed=$((SECONDS - started))
[ "$elapsed" -lt 3 ] \
  && { echo "  ok: timeout de auth e realmente limitado"; _pass=$((_pass+1)); } \
  || { echo "  FALHOU: timeout de auth levou ${elapsed}s"; _fail=$((_fail+1)); }

report
