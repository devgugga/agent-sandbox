#!/usr/bin/env bash
# recipes/common.sh — derivacao do id de workspace, compartilhada pelos quatro
# hooks de ciclo de vida. Ja esteve duplicada em create.sh e destroy.sh, e cada
# divergencia entre as copias vazou um pod. Fonte: source recipes/common.sh

# Nome DETERMINISTICO derivado do caminho do repo. Com $$ (PID) o destroy nao
# tem como reproduzir o nome e o pod vaza — o `doctor --provision` deixou um
# pod para tras exatamente assim, reportando sucesso.
asb_workspace_id() {
  local repo="$1"
  # ORCA_VM_INSTANCE_ID e o identificador UNICO POR WORKSPACE que o Orca passa
  # aos scripts de ciclo de vida. Sem ele, a derivacao cai no caminho do repo —
  # e como o Orca executa os shims a partir do checkout PRIMARIO, todo workspace
  # do mesmo projeto receberia o mesmo nome e o segundo mataria o pod do
  # primeiro.
  local given="${ORCA_VM_INSTANCE_ID:-${ORCA_WORKSPACE_ID:-}}"
  if [ -n "$given" ]; then
    printf '%s' "$given" | tr -c 'a-zA-Z0-9._-' '-'
    return
  fi
  # Normalizar ANTES de derivar: barra final muda o hash, e create e destroy
  # divergiriam se o caminho chegasse de formas diferentes — o mesmo tipo de
  # divergencia que fazia o pod vazar.
  repo="${repo%/}"
  local base short
  # ${repo##*/} em vez de $(basename ...): o subshell traz um newline final que
  # o `tr -c` converte em traco, produzindo nomes como "hexmed-stack--f05b729e".
  base=${repo##*/}
  base=$(printf '%s' "$base" | tr -c 'a-zA-Z0-9._-' '-')
  short=$(printf '%s' "$repo" | sha256sum | cut -c1-8)
  printf '%s-%s' "$base" "$short"
}

# Resultado que o Orca consome. create e resume emitem a MESMA forma: o resume
# tambem devolve a conexao, porque a porta pode ter mudado.
# Os chamadores extraem port/project_root do stdout JSON do CLI somente
# apos retorno zero; este helper adapta o schema, nao verifica prontidao.
asb_recipe_json() {
  local ws="$1" port="$2" project_root="$3"
  local key="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519"
  jq -nc \
    --arg label "agent-sandbox-$ws" \
    --arg ws "$ws" \
    --arg key "$key" \
    --arg root "$project_root" \
    --arg user "$(id -un)" \
    --argjson port "$port" '
  {
    schemaVersion: 1,
    userData: { workspace: $ws },
    connection: {
      type: "ssh",
      projectRoot: $root,
      target: {
        label: $label,
        host: "127.0.0.1",
        port: $port,
        username: $user,
        identityFile: $key,
        identitiesOnly: true
      }
    }
  }'
}
