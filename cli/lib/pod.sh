#!/usr/bin/env bash
# cli/lib/pod.sh — ciclo de vida do pod. Fonte: source cli/lib/pod.sh
# Requer: ROOT (raiz do repo agent-sandbox)
set -euo pipefail

ASB_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox"
ASB_KEY="$ASB_CONFIG/id_ed25519"
ASB_KEYRING_PASS_FILE="$ASB_CONFIG/keyring.pass"
ASB_PODS_DIR="$ASB_CONFIG/pods"

# Estado por pod. NAO usar mktemp: /tmp e tmpfs, some no reboot, e o bind mount
# do squid apontando para um caminho inexistente faz `podman pod start` falhar
# SO no squid — subindo o agente sem proxy e, pior, sem firewall (o netns e
# recriado e as regras nft se perdem). Medido: curl direto respondendo 200.
asb_state_dir() { printf '%s/%s' "$ASB_PODS_DIR" "$1"; }

# O NetworkManager pode considerar a sessao grafica pronta antes de DHCP, DNS
# e rota default. Se o `pasta` nasce nesse intervalo, ele copia um namespace
# sem saida e esse estado nao se corrige quando a rede do host aparece depois.
asb_host_network_ready() {
  ip -4 route show default 2>/dev/null | grep -q '^default ' \
    && timeout "${ASB_NETWORK_PROBE_TIMEOUT:-2}" \
      getent ahostsv4 www.googleapis.com >/dev/null 2>&1
}

asb_wait_for_host_network() {
  local attempts="${ASB_NETWORK_WAIT_ATTEMPTS:-20}"
  local interval="${ASB_NETWORK_WAIT_INTERVAL:-1}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    asb_host_network_ready && return 0
    [ "$i" -eq "$attempts" ] || sleep "$interval"
  done
  echo "rede do host indisponivel apos $attempts tentativa(s)" >&2
  return 1
}

# Processo rodando nao significa proxy funcional. Esta prova acontece no mesmo
# netns do pod e como uid 900, o unico autorizado a sair: rota, DNS e CONNECT
# precisam funcionar antes de qualquer agente ser iniciado.
asb_proxy_probe() {
  local pod="$1"
  timeout "${ASB_PROXY_PROBE_TIMEOUT:-8}" \
    podman exec --user 900 "${pod}-squid" sh -ceu '
    ip -4 route show default | grep -q "^default "
    timeout 3 getent ahostsv4 api.anthropic.com >/dev/null
    first_line=$(
      printf "CONNECT api.anthropic.com:443 HTTP/1.1\r\nHost: api.anthropic.com:443\r\n\r\n" \
        | nc -w 3 127.0.0.1 3128 | head -n 1
    )
    case "$first_line" in
      "HTTP/1."*" 200 "*) exit 0 ;;
      *) exit 1 ;;
    esac
  ' >/dev/null 2>&1
}

asb_wait_for_proxy() {
  local pod="$1"
  local attempts="${ASB_PROXY_READY_ATTEMPTS:-5}"
  local interval="${ASB_PROXY_READY_INTERVAL:-1}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    asb_proxy_probe "$pod" && return 0
    [ "$i" -eq "$attempts" ] || sleep "$interval"
  done
  echo "proxy sem rota, DNS ou CONNECT apos $attempts tentativa(s): $pod" >&2
  return 1
}

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

asb_prepare_agent_start() (
  local pod="$1" token token_file
  podman cp "$ROOT/image/entrypoint.sh" \
    "${pod}-agent:/usr/local/bin/entrypoint.sh"
  podman cp "$ROOT/image/asb-agent" \
    "${pod}-agent:/usr/local/bin/asb-agent"
  podman cp "$ROOT/image/install-config.py" \
    "${pod}-agent:/usr/local/bin/asb-install-config"
  token=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
  token_file=$(mktemp)
  trap 'rm -f "$token_file"' EXIT
  printf '%s\n' "$token" > "$token_file"
  podman cp "$token_file" \
    "${pod}-agent:/run/agent-sandbox-provision-token"
  printf '%s\n' "$token"
)

asb_provision_agent() (
  local pod="$1" token="$2" stage
  stage=$(mktemp -d)
  trap 'rm -rf "$stage"' EXIT

  if python3 "$ROOT/cli/lib/provision.py" "$ROOT/profiles/provision.toml" "$stage" > "$stage/plan" 2>"$stage/err"; then
    [ ! -s "$stage/err" ] || cat "$stage/err" >&2
    while IFS=$'\t' read -r src dst; do
      [ -n "$src" ] || continue
      podman exec --user 0 "${pod}-agent" \
        /usr/local/bin/asb-install-config prepare "$dst"
      if ! podman cp "$src" "${pod}-agent:$dst" 2>/dev/null; then
        echo "provisionamento: falhou copiar $src para $dst" >&2
        return 1
      fi
      podman exec --user 0 "${pod}-agent" \
        /usr/local/bin/asb-install-config finalize "$dst"
    done < "$stage/plan"
  else
    # Recusa do provisionador significa caminho negado no manifesto: abortar em
    # vez de subir um sandbox com a credencial do host dentro.
    cat "$stage/err" >&2
    echo "provisionamento recusado; abortando" >&2
    return 1
  fi
  podman exec --user 0 "${pod}-agent" \
    touch "/run/agent-sandbox-provisioned-$token"
)

asb_up() (
  local ws="$1" repo="$2"
  local pod="asb-$ws"
  local state="" pod_created=0 succeeded=0

  cleanup_up() {
    local rc=$?
    if [ "$succeeded" -eq 0 ]; then
      [ "$pod_created" -eq 0 ] || podman pod rm -f "$pod" >/dev/null 2>&1 || true
      [ -z "$state" ] || rm -rf "$state"
    fi
    return "$rc"
  }
  trap cleanup_up EXIT

  if ! podman image exists agent-sandbox-auth; then
    echo "imagem agent-sandbox-auth ausente; execute 'agent-sandbox auth'" >&2
    return 1
  fi
  if podman pod exists "$pod"; then
    echo "workspace ja existe: $pod (use 'resume' ou 'down' explicitamente)" >&2
    return 1
  fi

  asb_ensure_key
  asb_ensure_keyring_pass

  state=$(asb_state_dir "$pod")
  local profile squidconf
  rm -rf "$state"; mkdir -p "$state"; chmod 0700 "$ASB_PODS_DIR" "$state"
  profile="$state/profile.json"; squidconf="$state/squid.conf"
  printf '%s' "$repo" > "$state/repo"
  python3 "$ROOT/cli/lib/profile.py" "$repo" > "$profile"
  python3 "$ROOT/cli/lib/render_squid.py" "$ROOT/image/squid/allowlist-base.txt" "$profile" > "$squidconf"
  # o squid roda como uid 900 e precisa ler o arquivo montado
  chmod 0644 "$squidconf"

  # porta 0 = o kernel sorteia; lemos de volta depois
  # keep-id: sem isso o uid 1000 do host mapeia para 0 aqui dentro e o agente
  # (uid 1000) nao consegue escrever no /workspace montado. O userns e do
  # POD: "--userns" em `podman run --pod` falha com "cannot set user
  # namespace mode when joining pod with infra container".
  podman pod create --name "$pod" -p 127.0.0.1::22 \
    --userns=keep-id:uid=1000,gid=1000 >/dev/null
  pod_created=1
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
  if ! asb_wait_for_proxy "$pod"; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "proxy nao ficou saudavel; pod parado (fail-closed)" >&2
    return 1
  fi

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
  # Montar sob /home/agent, nao em /workspace: o Orca cria worktrees IRMAS do
  # projectRoot ("<root>-<nome>") quando nao configurado para usar .worktrees, e
  # com /workspace a irma cairia em /, que e 555 e nem root escreve.
  #
  # ATENCAO: comentario NUNCA no meio de um comando com continuacao de linha. O
  # "#" encerra a linha logica junto com a barra invertida, os argumentos
  # seguintes viram orfaos e o podman falha com "requires at least 1 arg(s)".
  podman create --name "${pod}-agent" --pod "$pod" \
    -e ORCA_SSH_PUBLIC_KEY="$(cat "${ASB_KEY}.pub")" \
    -e ASB_KEYRING_PASS="$(cat "$ASB_KEYRING_PASS_FILE")" \
    -e HTTPS_PROXY=http://127.0.0.1:3128 \
    -e HTTP_PROXY=http://127.0.0.1:3128 \
    -e NO_PROXY=127.0.0.1,localhost \
    -e ASB_ENFORCE_FIREWALL=1 \
    -v "$repo:/home/agent/workspace:Z" \
    agent-sandbox-auth >/dev/null
  local provision_token
  provision_token=$(asb_prepare_agent_start "$pod")
  podman start "${pod}-agent" >/dev/null

  # 5) provisionar a configuracao do host (skills, plugins, settings). Copia,
  #    nao montagem: o agente pode editar na sessao sem tocar no host, e a
  #    regra "home do host nunca e montado" continua valendo.
  asb_provision_agent "$pod" "$provision_token"

  local result
  result=$(asb_emit "$pod")
  succeeded=1
  trap - EXIT
  printf '%s\n' "$result"
)

# Resultado que o recipe do Orca consome. A porta e lida do podman, nunca
# inventada: o Orca guarda a que o create devolveu e disca nela para sempre.
asb_emit() {
  local pod="$1" port
  port=$(podman port "${pod}-agent" 22 2>/dev/null | head -1 | sed 's/.*://')
  [ -n "$port" ] || { echo "nao foi possivel determinar a porta SSH" >&2; return 1; }
  printf '{"pod":"%s","port":%s,"user":"agent"}\n' "$pod" "$port"
}

asb_suspend() {
  local pod="asb-$1"
  podman pod exists "$pod" || { echo "pod inexistente: $pod" >&2; return 1; }
  podman pod stop "$pod" >/dev/null 2>&1
  return 0
}

# Reacende um pod parado (reboot da maquina, suspend do workspace) SEM recriar:
# recriar perderia o historico do agente e, no reboot, a porta SSH que o Orca
# ja gravou. A ordem aqui e a mesma do `up` e e o ponto todo desta funcao:
# `podman pod start` sobe TUDO de uma vez, e o agente fica no ar antes do
# firewall existir. Medido: com `pod start` o sandbox voltava com o ruleset
# vazio e egresso direto liberado.
asb_resume() {
  local ws="$1" pod="asb-$ws"
  podman pod exists "$pod" || { echo "pod inexistente: $pod (use 'up')" >&2; return 1; }

  # Codigo 2 = pod anterior a este estado persistido; nao da para restaurar e
  # NAO e falha operacional. O restore-all precisa distinguir os dois, senao um
  # pod legado marca a unidade do systemd como failed no boot.
  local state; state=$(asb_state_dir "$pod")
  [ -f "$state/squid.conf" ] || {
    echo "estado ausente em $state; recrie o workspace com 'up'" >&2; return 2; }

  # Ja de pe: ainda validar a fronteira inteira. Se estiver quebrada, parar e
  # continuar pelo caminho seguro de reconstrucao do netns.
  if [ -n "$(podman ps --filter "name=${pod}-agent" --filter status=running -q)" ]; then
    if [ -n "$(podman ps --filter "name=${pod}-squid" --filter status=running -q)" ] \
        && podman exec --privileged --user 0 "${pod}-squid" \
          nft list table inet asb >/dev/null 2>&1 \
        && asb_proxy_probe "$pod"; then
      asb_emit "$pod"
      return 0
    fi
    echo "pod em execucao falhou na validacao; reiniciando com seguranca" >&2
    podman pod stop "$pod" >/dev/null 2>&1
  fi

  # 1) SO a infra: cria o netns sem subir nenhum container de usuario.
  local infra
  infra=$(podman pod inspect "$pod" --format '{{.InfraContainerID}}')
  [ -n "$infra" ] || { echo "pod sem container de infra: $pod" >&2; return 1; }
  podman start "$infra" >/dev/null 2>&1 || {
    echo "nao foi possivel subir a infra do pod (porta ja em uso?)" >&2; return 1; }

  # 2) firewall antes de tudo. Falhou -> derruba o pod inteiro. Um pod meio
  #    subido e exatamente o estado inseguro que este caminho existe para evitar.
  if ! podman run --rm --pod "$pod" --user 1000 --cap-add NET_ADMIN \
        agent-sandbox-net /usr/local/bin/apply.sh >&2; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "firewall nao subiu; pod parado (fail-closed)" >&2
    return 1
  fi
  # 3) provar que subiu, em vez de confiar no codigo de saida
  if ! podman run --rm --pod "$pod" --user 1000 --cap-add NET_ADMIN \
        agent-sandbox-net nft list table inet asb >/dev/null 2>&1; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "regras nft ausentes apos o apply; pod parado (fail-closed)" >&2
    return 1
  fi

  # 4) resto na ordem do up: proxy, servicos/encaminhadores, agente por ultimo
  local members others
  members=$(podman pod inspect "$pod" --format '{{range .Containers}}{{.Name}}
{{end}}')
  # O proxy tem que estar de pe ANTES do agente: com o firewall aplicado e sem
  # squid, o agente sobe sem egresso algum e parece so "internet quebrada".
  # Verificar em vez de confiar no `podman start` — um pod sem container de
  # squid (legado, ou construido pela metade) passaria batido no `|| true`.
  podman start "${pod}-squid" >/dev/null 2>&1 || true
  if [ -z "$(podman ps --filter "name=${pod}-squid" --filter status=running -q)" ]; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "proxy nao subiu; pod parado (fail-closed)" >&2
    return 1
  fi
  if ! asb_wait_for_proxy "$pod"; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "proxy nao ficou saudavel; pod parado (fail-closed)" >&2
    return 1
  fi
  others=$(printf '%s\n' "$members" | grep -v -e '-infra$' -e "^${pod}-squid$" -e "^${pod}-agent$" || true)
  for c in $others; do podman start "$c" >/dev/null 2>&1 || true; done
  local provision_token
  if ! provision_token=$(asb_prepare_agent_start "$pod"); then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "runtime do agente nao foi atualizado; pod parado" >&2
    return 1
  fi
  podman start "${pod}-agent" >/dev/null || {
    podman pod stop "$pod" >/dev/null 2>&1
    echo "container do agente nao subiu; pod parado" >&2
    return 1
  }
  if ! asb_provision_agent "$pod" "$provision_token"; then
    podman pod stop "$pod" >/dev/null 2>&1
    echo "configuracao dos agentes nao foi sincronizada; pod parado" >&2
    return 1
  fi

  asb_emit "$pod"
}

# O que a unidade do systemd chama no boot. O Orca marca o workspace como
# "running" no seu registro e nao reexecuta o create depois de um reboot: ele
# so disca na porta que ja gravou. Sem isto, o workspace fica quebrado.
asb_restore_all() {
  local rc=0 pod ws n=0 skipped=0 code needs_network=0
  local -a pods=()
  mapfile -t pods < <(podman pod ls --format '{{.Name}}' | grep '^asb-' || true)
  for pod in "${pods[@]}"; do
    [ -f "$(asb_state_dir "$pod")/squid.conf" ] && needs_network=1
  done
  if [ "$needs_network" -eq 1 ] && ! asb_wait_for_host_network; then
    echo "restauracao adiada: rede do host ainda nao esta pronta" >&2
    return 1
  fi
  for pod in "${pods[@]}"; do
    ws="${pod#asb-}"
    asb_resume "$ws" >/dev/null && code=0 || code=$?
    case "$code" in
      0) echo "restaurado: $pod" >&2; n=$((n+1)) ;;
      # Pod anterior ao estado persistido: nada a fazer, e nao e falha. Deixar
      # que marque a unidade como failed no boot esconderia falhas reais.
      2) echo "ignorado (sem estado, anterior a esta versao): $pod" >&2; skipped=$((skipped+1)) ;;
      *) echo "FALHOU restaurar: $pod" >&2; rc=1 ;;
    esac
  done
  echo "$n sandbox(es) restaurado(s), $skipped ignorado(s)" >&2
  return $rc
}

asb_down() {
  local pod="asb-$1"
  podman pod exists "$pod" 2>/dev/null && podman pod rm -f "$pod" >/dev/null 2>&1
  rm -rf "$(asb_state_dir "$pod")"
  return 0
}
