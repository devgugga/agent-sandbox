#!/usr/bin/env bash
# cli/lib/pod.sh — ciclo de vida do pod. Fonte: source cli/lib/pod.sh
# Requer: ROOT (raiz do repo agent-sandbox)
set -euo pipefail

ASB_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox"
ASB_KEY="$ASB_CONFIG/id_ed25519"
ASB_KEYRING_PASS_FILE="$ASB_CONFIG/keyring.pass"

# A passphrase do keyring vive SO no host. A imagem autenticada carrega o
# login.keyring cifrado; sem esta passphrase ela e inutil — verificado: com a
# passphrase errada o Secret Service nega a leitura.
asb_ensure_keyring_pass() {
  [ -f "$ASB_KEYRING_PASS_FILE" ] && return 0
  mkdir -p "$ASB_CONFIG"; chmod 0700 "$ASB_CONFIG"
  ( umask 077; head -c 32 /dev/urandom | base64 | tr -d '\n' > "$ASB_KEYRING_PASS_FILE" )
  chmod 0600 "$ASB_KEYRING_PASS_FILE"
}

asb_ensure_key() {
  [ -f "$ASB_KEY" ] && return 0
  mkdir -p "$ASB_CONFIG"; chmod 0700 "$ASB_CONFIG"
  ssh-keygen -t ed25519 -N '' -f "$ASB_KEY" -C agent-sandbox >&2
}

asb_up() {
  local ws="$1" repo="$2"
  local pod="asb-$ws"
  asb_ensure_key
  asb_ensure_keyring_pass

  local profile squidconf
  profile=$(mktemp); squidconf=$(mktemp)
  chmod 0644 "$squidconf"
  python3 "$ROOT/cli/lib/profile.py" "$repo" > "$profile"
  python3 "$ROOT/cli/lib/render_squid.py" "$ROOT/image/squid/allowlist-base.txt" "$profile" > "$squidconf"

  podman pod exists "$pod" && podman pod rm -f "$pod" >/dev/null
  # porta 0 = o kernel sorteia; lemos de volta depois
  # keep-id: sem isso o uid 1000 do host mapeia para 0 aqui dentro e o agente
  # (uid 1000) nao consegue escrever no /workspace montado. O userns e do
  # POD: "--userns" em `podman run --pod` falha com "cannot set user
  # namespace mode when joining pod with infra container".
  podman pod create --name "$pod" -p 127.0.0.1::22 \
    --userns=keep-id:uid=1000,gid=1000 >/dev/null
  podman pod start "$pod" >/dev/null

  # 1) firewall primeiro: nada sobe antes da fronteira existir
  # --user 1000: sob keep-id o dono do user namespace e o uid 1000, nao o 0.
  # Como root o nft falha com "Operation not permitted" e o firewall NAO sobe
  # — silenciosamente, deixando o sandbox sem isolamento de rede algum.
  podman run --rm --pod "$pod" --user 1000 --cap-add NET_ADMIN agent-sandbox-net \
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
    # --user 0: imagens sem diretiva USER (como postgres) sao resolvidas por
    # keep-id para o uid mapeado do host, e ai o initdb falha em ajustar
    # permissoes dos diretorios da propria imagem ("Operation not permitted").
    podman run -d --name "${pod}-${name}" --pod "$pod" --user 0 \
      -e POSTGRES_PASSWORD=sandbox -e POSTGRES_USER=sandbox -e POSTGRES_DB=sandbox \
      "$image" >/dev/null
  done

  # 3.5) modo anexado: encaminhador TCP para servicos do host
  if [ "$(jq -r .mode "$profile")" = "attached" ]; then
    asb_attach "$pod" "$profile"
  fi

  # 4) agente por ultimo, SEM NET_ADMIN
  local agent_image=agent-sandbox-base
  podman image exists agent-sandbox-auth && agent_image=agent-sandbox-auth

  # Montar sob /home/agent, nao em /workspace: o Orca cria worktrees IRMAS do
  # projectRoot ("<root>-<nome>") quando nao configurado para usar .worktrees, e
  # com /workspace a irma cairia em /, que e 555 e nem root escreve.
  #
  # ATENCAO: comentario NUNCA no meio de um comando com continuacao de linha. O
  # "#" encerra a linha logica junto com a barra invertida, os argumentos
  # seguintes viram orfaos e o podman falha com "requires at least 1 arg(s)".
  podman run -d --name "${pod}-agent" --pod "$pod" \
    -e ORCA_SSH_PUBLIC_KEY="$(cat "${ASB_KEY}.pub")" \
    -e ASB_KEYRING_PASS="$(cat "$ASB_KEYRING_PASS_FILE")" \
    -e HTTPS_PROXY=http://127.0.0.1:3128 \
    -e HTTP_PROXY=http://127.0.0.1:3128 \
    -e NO_PROXY=127.0.0.1,localhost \
    -v "$repo:/home/agent/workspace:Z" \
    "$agent_image" >/dev/null

  # 5) provisionar a configuracao do host (skills, plugins, settings). Copia,
  #    nao montagem: o agente pode editar na sessao sem tocar no host, e a
  #    regra "home do host nunca e montado" continua valendo.
  local stage
  stage=$(mktemp -d)
  if python3 "$ROOT/cli/lib/provision.py" "$ROOT/profiles/provision.toml" "$stage" > "$stage/plan" 2>>"$stage/err"; then
    while IFS=$'\t' read -r src dst; do
      [ -n "$src" ] || continue
      podman exec --user 0 "${pod}-agent" mkdir -p "$(dirname "$dst")" 2>/dev/null
      # `podman cp` copia PARA DENTRO de um destino que ja exista, aninhando o
      # diretorio. Remover antes torna a copia idempotente.
      podman exec --user 0 "${pod}-agent" rm -rf "$dst" 2>/dev/null
      podman cp "$src" "${pod}-agent:$dst" 2>/dev/null \
        || echo "provisionamento: falhou $src" >&2
    done < "$stage/plan"
    # podman cp preserva o dono da origem; o agente precisa conseguir ler.
    podman exec --user 0 "${pod}-agent" \
      chown -R agent:agent /home/agent/.claude /home/agent/.codex /home/agent/.gemini 2>/dev/null
  else
    # Recusa do provisionador significa caminho negado no manifesto: abortar em
    # vez de subir um sandbox com a credencial do host dentro.
    cat "$stage/err" >&2
    rm -rf "$stage"
    echo "provisionamento recusado; abortando" >&2
    return 1
  fi
  rm -rf "$stage"

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
