#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd.
#
# Muito menor que o do v1 de proposito. Sumiram: a sonda de egresso direto (a
# topologia da rede e que isola agora, e ela nao pode "nao ter subido"), o
# token de provisionamento e o portao do sshd (a configuracao chega como mount
# read-only, entao nao ha janela de TOCTOU a fechar).
set -euo pipefail

ASB_USER=$(id -un 1000)
ASB_HOME=$(getent passwd 1000 | cut -d: -f6)

# O OpenSSH descarta o ambiente do processo pai ao criar a sessao do usuario.
# /etc/environment e lido pelo PAM (inclusive em `ssh host 'cmd'`, que NAO e
# shell de login); /etc/profile.d cobre os shells de login.
env | grep -E '^(HTTPS_PROXY|HTTP_PROXY|NO_PROXY|PATH|DBUS_SESSION_BUS_ADDRESS)=' > /etc/environment || true
cat > /etc/profile.d/agent-sandbox.sh <<ENV_EOF
# Sem default fixo: o container de login roda FORA da rede interna e nao tem
# proxy algum. Um default apontando para um proxy inexistente quebraria os
# logins. Quem define o proxy e quem cria o container, via -e.
[ -n "\${HTTPS_PROXY:-}" ] && export HTTPS_PROXY="\$HTTPS_PROXY"
[ -n "\${HTTP_PROXY:-}" ] && export HTTP_PROXY="\$HTTP_PROXY"
[ -n "\${NO_PROXY:-}" ] && export NO_PROXY="\$NO_PROXY"
[ -n "\${DBUS_SESSION_BUS_ADDRESS:-}" ] && export DBUS_SESSION_BUS_ADDRESS="\$DBUS_SESSION_BUS_ADDRESS"
export PATH="/usr/local/sbin:/usr/sbin:/sbin:$ASB_HOME/.local/bin:$ASB_HOME/.local/share/mise/shims:\${PATH}"
ENV_EOF

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o "$ASB_USER" -g "$ASB_USER" "$ASB_HOME/.ssh"
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > "$ASB_HOME/.ssh/authorized_keys"
  chown "$ASB_USER:$ASB_USER" "$ASB_HOME/.ssh/authorized_keys"
  chmod 0600 "$ASB_HOME/.ssh/authorized_keys"
fi


[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

# Configuracao do host: chega como mount READ-ONLY e e copiada para o home. Nao
# se monta direto sobre ~/.claude/settings.json porque os agentes escrevem
# nesses arquivos durante a sessao. Como a ORIGEM e um mount que o agente nao
# escreve, nao ha janela de TOCTOU — e por isso sumiram o instalador root, o
# token por partida e o portao do sshd que o v1 precisava.
if [ -f /run/asb-config/manifest.tsv ]; then
  while IFS=$'\t' read -r src dst; do
    [ -n "$src" ] || continue
    install -d -o "$ASB_USER" -g "$ASB_USER" "$(dirname "$dst")"
    # Trocar por rename, nao apagar no lugar. Com `~/.claude` e `~/.codex`
    # agora montados de um volume COMPARTILHADO entre workspaces, um
    # `rm -rf "$dst"` seguido de `cp -a` deixaria outro workspace lendo um
    # diretorio meio copiado durante a partida deste. A copia acontece ao
    # lado e so entra no lugar pronta.
    #
    # O antigo tambem sai por RENAME, e so e apagado DEPOIS que o novo ja
    # esta no lugar: um `rm -rf "$dst"` aqui destruia, a cada `up`, um
    # diretorio que outro workspace estava lendo naquele instante — a janela
    # era a copia inteira, nao um instante.
    #
    # LIMITE, declarado em vez de escondido: nao ha troca atomica de
    # diretorio em POSIX. `mv` sobre diretorio nao vazio nao e
    # `renameat2(RENAME_EXCHANGE)`, entao resta uma janela entre os dois
    # renames — na ordem de microssegundos — em que "$dst" nao existe. Um
    # leitor que ja tenha os arquivos abertos nao e afetado (o inode antigo
    # so e desligado no fim), e nenhum leitor jamais ve conteudo pela metade.
    #
    # Agentes que partem juntos (todo boot, depois da espera unica por rede)
    # disputam o mesmo destino no volume compartilhado, e `$$` vale 1 em todo
    # container: sem trava, um apagava a copia que o outro fazia (boot A1 do
    # piloto, §6.9). A trava e `flock` no diretorio pai — lock do kernel no
    # inode do volume, visivel entre containers, sem arquivo de lock.
    exec {parent_lock}<"$(dirname "$dst")"
    flock -w 120 "$parent_lock"
    staged="${dst}.asb-staging.$$"
    previous="${dst}.asb-previous.$$"
    rm -rf "$staged" "$previous"
    cp -a "/run/asb-config/$src" "$staged"
    chown -R "$ASB_USER:$ASB_USER" "$staged"
    if [ -e "$dst" ]; then
      mv "$dst" "$previous"
    fi
    mv "$staged" "$dst"
    rm -rf "$previous"
    exec {parent_lock}<&-
  done < /run/asb-config/manifest.tsv
fi

# Credenciais: NADA a fazer aqui. Os diretorios de credencial chegam como
# mounts (`~/.claude`, `~/.codex`, subpaths do volume asb-credentials), feitos
# por quem cria o container. O entrypoint nao os toca.
#
# O que existia aqui era a causa medida do "Claude perde o login a cada
# partida" (Tarefa A1):
#   1. `: > "$stored"` precriava a credencial como arquivo de 0 BYTES, que
#      jamais poderia ser lido como JSON. O volume de producao tinha
#      literalmente `claude.json` com 0 bytes.
#   2. `rm -rf "$real"; ln -s "$stored" "$real"` refazia um SYMLINK a cada
#      partida. O Claude Code 2.1.263 abre a credencial com
#      `O_RDONLY | O_NOFOLLOW`; num symlink o Linux devolve ELOOP, que ele
#      classifica como `refused-symlink` e trata como credencial AUSENTE.
#   3. Qualquer escritor que use `rename` atomico sobre o symlink substitui o
#      proprio symlink e corta o vinculo com o volume.
# O Codex sobrevivia a esse arranjo so porque o escritor dele tolera o
# symlink. Nao reintroduzir link nem precriacao de arquivo aqui.
if [ -d /run/asb-credentials ] && [ -w /run/asb-credentials ]; then
  chown "$ASB_USER:$ASB_USER" /run/asb-credentials
  for f in /run/asb-credentials/*; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
      # keyrings: mascarado por tmpfs, e nao e nosso.
      # claude/codex: os diretorios de credencial, criados pelo host ja com o
      # uid certo e montados por cima. Um `chown -R` aqui reescreveria
      # metadado de credencial viva a cada partida sem corrigir nada.
      keyrings|claude|codex) continue ;;
    esac
    chown -R "$ASB_USER:$ASB_USER" "$f" 2>/dev/null || true
  done
fi

if [ -d /run/asb-toolcache ]; then
  install -d -o "$ASB_USER" -g "$ASB_USER" \
    /run/asb-toolcache/mise \
    /run/asb-toolcache/mise/migrations \
    /run/asb-toolcache/cache \
    /run/asb-toolcache/m2 \
    /run/asb-toolcache/uv
  install -d -o "$ASB_USER" -g "$ASB_USER" "$ASB_HOME/.local/share"
  rm -rf "$ASB_HOME/.local/share/mise" "$ASB_HOME/.cache" "$ASB_HOME/.m2" "$ASB_HOME/.local/share/uv"
  ln -sfn /run/asb-toolcache/mise "$ASB_HOME/.local/share/mise"
  ln -sfn /run/asb-toolcache/cache "$ASB_HOME/.cache"
  ln -sfn /run/asb-toolcache/m2 "$ASB_HOME/.m2"
  ln -sfn /run/asb-toolcache/uv "$ASB_HOME/.local/share/uv"
  chown -h "$ASB_USER:$ASB_USER" "$ASB_HOME/.local/share/mise" "$ASB_HOME/.cache" "$ASB_HOME/.m2" "$ASB_HOME/.local/share/uv"
  chown -R "$ASB_USER:$ASB_USER" /run/asb-toolcache
fi

if [ -d "$ASB_HOME/.local/share/containers" ]; then
  chown -R "$ASB_USER:$ASB_USER" "$ASB_HOME/.local/share/containers"
fi

# O projeto continua apontando para localhost:5432. Sem pod, o agente e o
# encaminhador estao em namespaces separados, entao um socat local recria o
# endereco que o projeto espera. Dois saltos triviais; a alternativa seria
# reescrever a configuracao de cada projeto.
if [ -n "${ASB_HOST_PORTS:-}" ]; then
  fwd="asb-${ASB_WORKSPACE}-fwd"
  echo "$ASB_HOST_PORTS" | tr ',' '\n' | while read -r port; do
    [ -n "$port" ] || continue
    setsid socat "TCP-LISTEN:${port},bind=127.0.0.1,fork,reuseaddr" \
      "TCP:${fwd}:${port}" >/dev/null 2>&1 &
  done
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec /usr/sbin/sshd -D -e
