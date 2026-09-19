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
# Terminal persistente das sessoes de agente (asb.sessions.terminal).
assert_eq "0" "$(in_image sh -lc 'tmux -V >/dev/null 2>&1; echo $?')" \
  "tmux -V responde na imagem"
assert_eq "0" "$(in_image bash -lc "podman compose version >/dev/null 2>&1; echo \$?")" \
  "podman compose funciona via wrapper nativo"

# Ferramentas de contexto do agente (rtk, graphify) e o uv que as sustenta.
# Instaladas na imagem, e nao por workspace: sao usadas em todo projeto e no
# mise.toml de cada repositorio virariam download repetido.
for bin in uv rtk graphify; do
  assert_eq "0" "$(in_image sh -lc "command -v $bin >/dev/null; echo \$?")" \
    "$bin esta no PATH de um shell de login"
done

# O doctor le a versao da imagem pelo label, sem precisar subir container.
# Sem o label ele nao tem como detectar defasagem contra o host.
for label in asb.rtk.version asb.graphify.version; do
  assert_eq "0" "$(test -n "$(podman image inspect "$IMG" --format "{{index .Labels \"$label\"}}" 2>/dev/null)" && echo 0 || echo 1)" \
    "a imagem declara o label $label"
done

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

echo "== estado de primeira execucao do Claude =="

# O login do Claude fica em ~/.claude/.credentials.json (volume compartilhado),
# mas o "ja passei pelo onboarding" fica em ~/.claude.json, na camada gravavel
# de cada container. Sem a flag, todo workspace novo abre "Select login method"
# com a credencial valida. O helper semeia SO a flag, como o usuario comum.
SEED=/usr/local/bin/asb-seed-claude-state

assert_eq "0" "$(in_image sh -c "test -x $SEED; echo \$?")" \
  "asb-seed-claude-state existe na imagem"

# Le o caso pela entrada padrao e o roda como o usuario comum, com HOME
# temporario. O helper recebe o caminho em $SEED.
seed_case() {
  podman run --rm -i --user "$HOST_USER" --entrypoint "" -e SEED="$SEED" "$IMG" \
    bash -c 'export HOME=$(mktemp -d); cd "$HOME"; source /dev/stdin' 2>&1
}
# Prefixo comum: roda o helper e guarda codigo de saida e linhas de aviso.
RUN='timeout 10 "$SEED" 2>err; rc=$?; warns=$(wc -l < err)'

assert_eq '{"hasCompletedOnboarding": true}|600|0' "$(seed_case <<EOS
$RUN
printf '%s|%s|%s' "\$(cat .claude.json)" "\$(stat -c %a .claude.json)" "\$rc"
EOS
)" "ausente: cria exatamente a flag, modo 0600, sai 0"

assert_eq "same|0|0" "$(seed_case <<EOS
printf '{ "hasCompletedOnboarding":true,  "x": 1 }' > .claude.json
touch -d @1000 .claude.json
before=\$(stat -c '%i %Y %s' .claude.json)
$RUN
[ "\$before" = "\$(stat -c '%i %Y %s' .claude.json)" ] && s=same || s=changed
printf '%s|%s|%s' "\$s" "\$rc" "\$warns"
EOS
)" "flag ja true: arquivo nao e reescrito, sem aviso"

for initial in '' ',"hasCompletedOnboarding":false'; do
  label=ausente; [ -n "$initial" ] && label=false
  assert_eq "True|600|0|0|" "$(seed_case <<EOS
printf '%s' '{"oauthAccount":{"emailAddress":"a@b.c","n":[1,2.5,null]},"s":"ação ✓","big":12345678901234567890,"t":true$initial}' > .claude.json
chmod 0600 .claude.json
$RUN
ok=\$(python3 - <<'PY'
import json
d = json.load(open(".claude.json"))
flag = d.pop("hasCompletedOnboarding")
print(flag is True and d == {"oauthAccount": {"emailAddress": "a@b.c", "n": [1, 2.5, None]},
                             "s": "ação ✓", "big": 12345678901234567890, "t": True})
PY
)
printf '%s|%s|%s|%s|%s' "\$ok" "\$(stat -c %a .claude.json)" "\$rc" "\$warns" "\$(ls -A | grep -v -x -e .claude.json -e err)"
EOS
)" "flag $label: vira true, preserva as outras chaves e valores, 0600, sem temporario"
done

assert_eq "1|0|link|{}" "$(seed_case <<EOS
printf '{}' > alvo.json; ln -s alvo.json .claude.json
$RUN
printf '%s|%s|%s|%s' "\$warns" "\$rc" "\$([ -L .claude.json ] && echo link)" "\$(cat alvo.json)"
EOS
)" "symlink: um aviso, link e alvo intocados, sai 0"

assert_eq "1|0|dir" "$(seed_case <<EOS
mkdir .claude.json
$RUN
printf '%s|%s|%s' "\$warns" "\$rc" "\$([ -d .claude.json ] && echo dir)"
EOS
)" "diretorio: um aviso, intocado, sai 0"

assert_eq "1|0|fifo" "$(seed_case <<EOS
mkfifo .claude.json
$RUN
printf '%s|%s|%s' "\$warns" "\$rc" "\$([ -p .claude.json ] && echo fifo)"
EOS
)" "FIFO: um aviso, sem bloquear, intocado, sai 0"

for bad in '' '{"hasCompletedOnboarding": fal' '[1, 2]' '"texto"' 'null'; do
  assert_eq "1|0|same" "$(seed_case <<EOS
printf '%s' '$bad' > .claude.json; cp .claude.json orig
$RUN
printf '%s|%s|%s' "\$warns" "\$rc" "\$(cmp -s orig .claude.json && echo same)"
EOS
)" "invalido ou nao-objeto ($bad): um aviso, intocado, sai 0"
done

assert_eq "1|0|same" "$(seed_case <<EOS
printf '{"a":1}' > .claude.json; chmod 000 .claude.json
$RUN
chmod 600 .claude.json
printf '%s|%s|%s' "\$warns" "\$rc" "\$([ "\$(cat .claude.json)" = '{"a":1}' ] && echo same)"
EOS
)" "ilegivel: um aviso, intocado, sai 0"

# ~/.claude e o diretorio da CREDENCIAL. Fechado em 000, qualquer acesso do
# helper ali falharia; o resultado tem de ser o mesmo de um home limpo.
assert_eq "0|0|x|True" "$(seed_case <<EOS
mkdir .claude; printf x > .claude/.credentials.json; chmod 000 .claude
$RUN
chmod 700 .claude
printf '%s|%s|%s|%s' "\$warns" "\$rc" "\$(cat .claude/.credentials.json)" \
  "\$(python3 -c 'import json;print(json.load(open(".claude.json"))=={"hasCompletedOnboarding":True})')"
EOS
)" "~/.claude (credencial) nao e tocado nem atrapalha"

# O runuser do entrypoint herda o PATH da imagem, com os shims do mise ANTES
# de /usr/bin, e esses shims vem do toolcache compartilhado. Um `python3` de
# projeto ali nao pode sequestrar o helper (falharia calado, saindo 0).
assert_eq "True|0" "$(seed_case <<EOS
mkdir shim; printf '#!/bin/sh\nexit 42\n' > shim/python3; chmod 0755 shim/python3
PATH="\$PWD/shim:\$PATH" $RUN
printf '%s|%s' "\$(python3 -c 'import json;print(json.load(open(".claude.json"))=={"hasCompletedOnboarding":True})' 2>/dev/null)" "\$warns"
EOS
)" "um python3 anterior no PATH (shim do mise) nao sequestra o helper"

# Ponta a ponta: o entrypoint REAL (root) semeia como o usuario comum, no home
# dele. Sem mounts, os blocos de config/credencial/toolcache nao rodam.
assert_eq "$HOST_USER 600 True" "$(podman run --rm "$IMG" sh -c \
  'printf "%s " "$(stat -c "%U %a" "$HOME/.claude.json")"; python3 -c "import json,os;print(json.load(open(os.path.expanduser(\"~/.claude.json\")))[\"hasCompletedOnboarding\"] is True)"' 2>&1)" \
  "o entrypoint semeia ~/.claude.json como o usuario comum"

report
