#!/usr/bin/env bash
# tests/test-image.sh — propriedades da imagem base.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/tests/assert.sh"

IMG=agent-sandbox:latest
HOST_USER=$(id -un)
HOST_HOME=$HOME

echo "== imagem base =="

# CONTROLE POSITIVO: sem isto, todo assert_fails abaixo passaria de graca
# porque o `podman run` falharia por imagem ausente, nao por politica.
require "a imagem responde" podman run --rm "$IMG" true

in_image() { podman run --rm --user "$HOST_USER" --entrypoint "" "$IMG" "$@"; }

assert_eq "$HOST_USER" "$(in_image id -un -- 2>/dev/null || in_image sh -c 'id -un')" \
  "o usuario do container espelha o do host"
assert_eq "1000" "$(in_image sh -c 'id -u')" "uid do usuario e 1000"
assert_eq "$HOST_HOME" "$(in_image sh -c 'echo $HOME')" \
  "o home do container e identico ao do host"

for bin in claude codex agy gh git rg jq socat ssh-keygen podman-compose; do
  assert_eq "0" "$(in_image sh -lc "command -v $bin >/dev/null; echo \$?")" \
    "$bin esta no PATH de um shell de login"
done
assert_eq "0" "$(in_image bash -lc "podman compose version >/dev/null 2>&1; echo \$?")" \
  "podman compose funciona via wrapper nativo"

# O sandbox E a fronteira; sudo dentro dele so serviria para escapar dela.
assert_eq "1" "$(in_image bash -c 'command -v sudo >/dev/null; echo $?')" \
  "sudo nao existe na imagem"

# Ela protegia subprocessos NO HOST. Aqui nao protege nada, e o Claude Code
# responde a ela forcando o permission mode para default — anulando o
# --dangerously-skip-permissions que o Orca aplica, que e a capacidade que o
# sandbox existe para viabilizar com seguranca.
assert_eq "" "$(in_image sh -lc 'echo ${CLAUDE_CODE_SUBPROCESS_ENV_SCRUB:-}')" \
  "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB nao esta definida"
assert_eq "" "$(podman image inspect "$IMG" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep CLAUDE_CODE_SUBPROCESS_ENV_SCRUB || true)" \
  "e tambem nao esta no Config.Env da imagem"

assert_eq "agent-sandbox" "$(in_image cat /etc/agent-sandbox-release)" \
  "o marcador que o guarda procura esta presente"

# Chaves de host ASSADAS NO BUILD. Geradas em runtime, cada workspace teria a
# sua, e como todos atendem em 127.0.0.1 o ssh do Orca acusaria
# host-key-changed a cada workspace novo.
assert_eq "0" "$(in_image sh -c 'test -f /etc/ssh/ssh_host_ed25519_key; echo $?')" \
  "as host keys vieram do build"

for guard in asb-claude asb-codex asb-agy; do
  assert_eq "0" "$(in_image sh -c "test -x /usr/local/bin/$guard; echo \$?")" \
    "$guard existe na imagem"
done

report
