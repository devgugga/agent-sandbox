#!/usr/bin/env bash
# tests/test-transaction.sh — `up` atomico e imagem auth obrigatoria.
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== criacao transacional =="

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/repo"
git -C "$tmp/repo" init -q

cat > "$tmp/bin/podman" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ASB_TEST_PODMAN_LOG"
case "$1 ${2:-} ${3:-}" in
  "image exists agent-sandbox-auth")
    [ "${ASB_TEST_MODE:-}" != missing-auth ]
    exit $?
    ;;
  "pod exists "*) [ "${ASB_TEST_MODE:-}" = existing ]; exit $? ;;
  "port "*) printf '127.0.0.1:42022\n'; exit 0 ;;
  "cp "*) [ "${ASB_TEST_MODE:-}" != copy-fails ]; exit $? ;;
esac
exit 0
SH
chmod +x "$tmp/bin/podman"

log="$tmp/missing-auth.log"
if HOME="$tmp/home-a" XDG_CONFIG_HOME="$tmp/home-a/.config" \
    PATH="$tmp/bin:$PATH" ASB_TEST_PODMAN_LOG="$log" \
    ASB_TEST_MODE=missing-auth ./cli/agent-sandbox up \
      --workspace no-auth --repo "$tmp/repo" >/dev/null 2>&1; then
  missing_rc=0
else
  missing_rc=$?
fi
assert_eq "1" "$missing_rc" "up recusa imagem sem autenticacao"
assert_eq "" "$(grep -F 'pod create' "$log" 2>/dev/null)" \
  "recusa acontece antes de criar o pod"

mkdir -p "$tmp/home-existing/.config/agent-sandbox/pods/asb-existing"
printf 'preservar\n' > "$tmp/home-existing/.config/agent-sandbox/pods/asb-existing/sentinel"
log="$tmp/existing.log"
if HOME="$tmp/home-existing" XDG_CONFIG_HOME="$tmp/home-existing/.config" \
    PATH="$tmp/bin:$PATH" ASB_TEST_PODMAN_LOG="$log" ASB_TEST_MODE=existing \
    ./cli/agent-sandbox up --workspace existing --repo "$tmp/repo" \
      >/dev/null 2>&1; then
  existing_rc=0
else
  existing_rc=$?
fi
assert_eq "1" "$existing_rc" "up recusa substituir workspace existente"
assert_eq "preservar" "$(cat "$tmp/home-existing/.config/agent-sandbox/pods/asb-existing/sentinel" 2>/dev/null)" \
  "recusa preserva o estado do workspace existente"
assert_eq "" "$(grep -F 'pod rm -f asb-existing' "$log" || true)" \
  "recusa nao remove o pod existente"

mkdir -p "$tmp/home-b/.gemini/antigravity-cli"
printf '{}\n' > "$tmp/home-b/.gemini/antigravity-cli/settings.json"
log="$tmp/copy-fails.log"
if HOME="$tmp/home-b" XDG_CONFIG_HOME="$tmp/home-b/.config" \
    PATH="$tmp/bin:$PATH" ASB_TEST_PODMAN_LOG="$log" \
    ASB_TEST_MODE=copy-fails ASB_PROXY_READY_ATTEMPTS=1 \
    ./cli/agent-sandbox up --workspace rollback --repo "$tmp/repo" \
      >/dev/null 2>&1; then
  copy_rc=0
else
  copy_rc=$?
fi
assert_eq "1" "$copy_rc" "falha de copia aborta o up"
assert_contains "pod rm -f asb-rollback" "$(cat "$log")" \
  "rollback remove o pod parcial"
assert_eq "" "$(test -e "$tmp/home-b/.config/agent-sandbox/pods/asb-rollback" && echo existe)" \
  "rollback remove o estado parcial"

report
