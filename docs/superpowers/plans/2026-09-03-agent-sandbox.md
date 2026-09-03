# agent-sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ambiente de execução isolado, por workspace, para agentes de IA
orquestrados pelo Orca, sem privilégio permanente no host.

**Architecture:** Pod Podman rootless por workspace. Um init container com
`NET_ADMIN` aplica nftables no netns compartilhado e termina. Um Squid (uid 900)
é o único processo com egresso; o container do agente (uid 1000) não tem egresso
direto nem DNS, e alcança o mundo apenas via proxy CONNECT com allowlist de
domínio. O Orca conecta por SSH em porta efêmera de `127.0.0.1`.

**Tech Stack:** Podman 6.1 rootless (pasta/netavark), nftables, Squid, Debian
slim, bash, Python 3.11+ (`tomllib`), OpenSSH.

**Spec:** `docs/superpowers/specs/2026-09-03-agent-sandbox-design.md`

## Global Constraints

Valores copiados literalmente do spec. Valem para todas as tarefas.

- **Nunca instalar `podman-docker`** — declara `Provides: docker` /
  `Conflicts With: docker` e sequestraria `/usr/bin/docker`.
- Docker do host permanece **intacto**. Nenhuma tarefa altera a stack existente,
  o Portainer, ou a rede `hexmed_network`.
- Runtime é **Podman rootless**. Nenhum comando do projeto usa `sudo`.
- Usuário do agente: **`agent`, uid 1000**, não-root (o Claude Code recusa
  `--dangerously-skip-permissions` como root).
- Usuário do proxy: **uid 900**.
- Regras de firewall, nesta ordem: `policy drop`;
  `ct state established,related accept`; `oif lo accept`;
  `meta skuid 900 accept`.
- O container do agente **nunca** recebe `NET_ADMIN`.
- O home do host **nunca** é montado no container.
- **Nenhuma credencial Git** dentro do sandbox.
- Contrato do Orca: **SSH mode**, `schemaVersion: 1`. Sem `orca serve`, sem
  `pairingCode`.
- Host keys SSH geradas em **build time**, nunca em runtime.
- Allowlist é por **domínio** (resolvida pelo Squid), nunca por IP.

---

## File Structure

```
image/Containerfile              imagem base (agentes, toolchain, sshd)
image/entrypoint.sh              entrypoint sshd do container do agente
image/firewall/apply.sh          regras nftables; roda no init container
image/squid/allowlist-base.txt   domínios comuns a todos os projetos
image/squid/squid.conf.tmpl      template do proxy
cli/agent-sandbox                dispatcher (bash)
cli/lib/profile.py               lê .agent-sandbox.toml → JSON
cli/lib/render_squid.py          allowlist base + perfil → squid.conf
cli/lib/pod.sh                   up/down do pod
cli/lib/auth.sh                  imagem autenticada
cli/lib/attach.sh                modo anexado (socat)
recipes/create.sh                contrato de ciclo de vida do Orca
recipes/destroy.sh
recipes/shim.template.sh         shim copiado para cada projeto consumidor
profiles/default.toml
tests/assert.sh                  helper de asserção
tests/test-*.sh                  um por tarefa
docs/domains/sandbox/*.md        domain pack (SSoT)
```

---

### Task 0: Helper de asserção

Todas as tarefas seguintes dependem dele. Sem framework de teste: é
infraestrutura, os testes são scripts que verificam comportamento observável.

**Files:**
- Create: `tests/assert.sh`

**Interfaces:**
- Produces: `assert_eq <esperado> <obtido> <mensagem>`,
  `assert_contains <agulha> <palheiro> <mensagem>`,
  `assert_fails <comando...>` — todas retornam 0 em sucesso, imprimem e
  retornam 1 em falha. `report` imprime o total e sai com 1 se houve falha.

- [ ] **Step 1: Escrever o helper**

```bash
#!/usr/bin/env bash
# tests/assert.sh — helper mínimo de asserção. Fonte: source tests/assert.sh
_pass=0; _fail=0

assert_eq() {
  local expected="$1" actual="$2" msg="$3"
  if [ "$expected" = "$actual" ]; then
    _pass=$((_pass+1)); echo "  ok: $msg"
  else
    _fail=$((_fail+1)); echo "  FALHOU: $msg"; echo "    esperado: [$expected]"; echo "    obtido:   [$actual]"
  fi
}

assert_contains() {
  local needle="$1" haystack="$2" msg="$3"
  case "$haystack" in
    *"$needle"*) _pass=$((_pass+1)); echo "  ok: $msg" ;;
    *) _fail=$((_fail+1)); echo "  FALHOU: $msg"; echo "    nao encontrou [$needle] em: $haystack" ;;
  esac
}

# Sucesso = o comando FALHAR. Usado para provar que algo esta bloqueado.
assert_fails() {
  local msg="$1"; shift
  if "$@" >/dev/null 2>&1; then
    _fail=$((_fail+1)); echo "  FALHOU: $msg (comando teve sucesso, deveria falhar)"
  else
    _pass=$((_pass+1)); echo "  ok: $msg"
  fi
}

report() {
  echo "---"; echo "passou: $_pass  falhou: $_fail"
  [ "$_fail" -eq 0 ] || return 1
}
```

- [ ] **Step 2: Verificar que o helper detecta falha**

Run:
```bash
bash -c 'source tests/assert.sh; assert_eq a b "deve falhar"; report' ; echo "exit=$?"
```
Expected: imprime `FALHOU: deve falhar` e `exit=1`.

- [ ] **Step 3: Verificar que o helper aceita sucesso**

Run:
```bash
bash -c 'source tests/assert.sh; assert_eq a a "deve passar"; report' ; echo "exit=$?"
```
Expected: imprime `ok: deve passar` e `exit=0`.

- [ ] **Step 4: Commit**

```bash
git add tests/assert.sh
git commit
```

---

### Task 1: Imagem base com host keys estáveis

O ponto não óbvio: containers efêmeros reutilizam portas em `127.0.0.1`. Se cada
container gerar sua própria host key, o `known_hosts` do usuário dispara
host-key-changed a cada workspace. As chaves vão no **build**.

**Files:**
- Create: `image/Containerfile`, `image/entrypoint.sh`, `tests/test-image.sh`

**Interfaces:**
- Produces: imagem `agent-sandbox-base`, usuário `agent` uid 1000, sshd na 22,
  autenticação só por chave pública lida de `$ORCA_SSH_PUBLIC_KEY`.

- [ ] **Step 1: Escrever o teste que falha**

```bash
#!/usr/bin/env bash
# tests/test-image.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

echo "== Task 1: imagem base =="
uid=$(podman run --rm agent-sandbox-base id -u 2>/dev/null)
assert_eq "1000" "$uid" "agente roda como uid 1000"

user=$(podman run --rm agent-sandbox-base id -un 2>/dev/null)
assert_eq "agent" "$user" "usuario e 'agent'"

# host key deve ser identica entre dois containers (assada no build)
fp1=$(podman run --rm agent-sandbox-base ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')
fp2=$(podman run --rm agent-sandbox-base ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')
assert_eq "$fp1" "$fp2" "host key estavel entre containers"
assert_contains "SHA256:" "$fp1" "host key existe e tem fingerprint"

for bin in claude codex gemini git gh rg mise sshd; do
  podman run --rm agent-sandbox-base sh -c "command -v $bin" >/dev/null 2>&1 \
    && { echo "  ok: $bin presente"; } || { echo "  FALHOU: $bin ausente"; false; }
done

# o agente nao pode escalar privilegio dentro da imagem
assert_fails "sudo nao existe/nao funciona" podman run --rm agent-sandbox-base sudo -n true
assert_fails "sem socket de container montado" podman run --rm agent-sandbox-base test -S /var/run/docker.sock

report
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `bash tests/test-image.sh`
Expected: FALHA — a imagem `agent-sandbox-base` não existe.

- [ ] **Step 3: Escrever o Containerfile**

```dockerfile
# image/Containerfile
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git openssh-server ripgrep jq socat \
      python3 build-essential procps less nano \
    && rm -rf /var/lib/apt/lists/*

# Node LTS (necessario para os CLIs dos agentes)
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# CLIs dos agentes
RUN npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli \
    && npm cache clean --force

# gh CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# usuario nao-root
RUN useradd -m -u 1000 -s /bin/bash agent

# mise para o agente
USER agent
RUN curl -fsSL https://mise.run | sh
ENV PATH="/home/agent/.local/bin:/home/agent/.local/share/mise/shims:${PATH}"
USER root

# HOST KEYS ASSADAS NO BUILD — nao gerar em runtime.
# Containers efemeros reusam portas em 127.0.0.1; chave por container
# dispararia host-key-changed a cada workspace.
RUN ssh-keygen -A && mkdir -p /run/sshd

# sshd: so chave publica, sem senha, sem root
RUN printf '%s\n' \
      'PermitRootLogin no' \
      'PasswordAuthentication no' \
      'PubkeyAuthentication yes' \
      'AuthorizedKeysFile /home/agent/.ssh/authorized_keys' \
      'AcceptEnv HTTPS_PROXY HTTP_PROXY NO_PROXY' \
      > /etc/ssh/sshd_config.d/agent-sandbox.conf

# Aninhamento: cada agente tenta se sandboxar dentro do container e conflita.
# O container E a fronteira; ver spec 3.6.
ENV GEMINI_SANDBOX=false
ENV CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

- [ ] **Step 4: Escrever o entrypoint**

```bash
#!/usr/bin/env bash
# image/entrypoint.sh — instala a chave publica do workspace e sobe o sshd
set -euo pipefail

if [ -n "${ORCA_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 0700 -o agent -g agent /home/agent/.ssh
  printf '%s\n' "$ORCA_SSH_PUBLIC_KEY" > /home/agent/.ssh/authorized_keys
  chown agent:agent /home/agent/.ssh/authorized_keys
  chmod 0600 /home/agent/.ssh/authorized_keys
fi

# NAO gerar host keys aqui: elas vem do build. Gerar apenas se sumirem.
[ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A

exec /usr/sbin/sshd -D -e
```

- [ ] **Step 5: Construir a imagem**

Run: `podman build -t agent-sandbox-base -f image/Containerfile image/`
Expected: build completa sem erro.

- [ ] **Step 6: Rodar o teste e ver passar**

Run: `bash tests/test-image.sh`
Expected: todas as asserções `ok`, `falhou: 0`, exit 0.

Nota: o teste roda `id -u` sobrescrevendo o entrypoint. Se a imagem tiver
`ENTRYPOINT`, use `podman run --rm --entrypoint id agent-sandbox-base -u`.
Ajuste o teste se necessário — o critério é o uid ser 1000.

- [ ] **Step 7: Commit**

```bash
git add image/Containerfile image/entrypoint.sh tests/test-image.sh
git commit
```

---

### Task 2: Firewall e proxy — o núcleo de segurança

Esta tarefa entrega a propriedade central do projeto. Os quatro cenários do teste
foram validados manualmente no spike (ver apêndice do spec); aqui viram
regressão automatizada.

**Files:**
- Create: `image/firewall/apply.sh`, `image/squid/allowlist-base.txt`,
  `image/squid/squid.conf.tmpl`, `image/Containerfile.net`,
  `tests/test-network.sh`

**Interfaces:**
- Produces: imagem `agent-sandbox-net` contendo `nftables`, `squid` e
  `apply.sh`. `apply.sh` não recebe argumento e aplica o ruleset no netns atual.

- [ ] **Step 1: Escrever o teste que falha**

```bash
#!/usr/bin/env bash
# tests/test-network.sh — os quatro cenarios que definem a seguranca do sandbox
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

POD=asb-test-net
cleanup() { podman rm -f asb-squid >/dev/null 2>&1; podman pod rm -f "$POD" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup

podman pod create --name "$POD" >/dev/null
podman pod start "$POD" >/dev/null

# init: aplica firewall e sai
podman run --rm --pod "$POD" --cap-add NET_ADMIN agent-sandbox-net \
  /usr/local/bin/apply.sh >/dev/null

# squid como uid 900, com allowlist contendo apenas example.com
podman run -d --name asb-squid --pod "$POD" --user 900 agent-sandbox-net \
  squid -N -f /etc/squid/squid.conf >/dev/null
sleep 5

run_as_agent() { podman run --rm --pod "$POD" --user 1000 agent-sandbox-net sh -c "$1" 2>/dev/null; }

echo "== Task 2: rede =="

# [1] dominio permitido, via proxy
code=$(run_as_agent "curl -s -o /dev/null -m 12 -w '%{http_code}' -x http://127.0.0.1:3128 https://example.com")
assert_eq "200" "$code" "dominio na allowlist passa pelo proxy"

# [2] dominio negado, via proxy
code=$(run_as_agent "curl -s -o /dev/null -m 12 -w '%{http_code}' -x http://127.0.0.1:3128 https://github.com")
[ "$code" = "200" ] && { echo "  FALHOU: dominio fora da allowlist passou"; false; } || echo "  ok: dominio fora da allowlist e negado"

# [3] bypass direto do proxy
assert_fails "conexao direta e bloqueada pelo nftables" \
  podman run --rm --pod "$POD" --user 1000 agent-sandbox-net \
    curl -s -m 8 -o /dev/null https://1.1.1.1

# [4] tunel DNS — verificar procurando IP valido, NUNCA "alguma saida".
#     dig +short escreve erro no stdout; casar com qualquer texto da falso positivo.
out=$(run_as_agent "dig +time=4 +tries=1 @1.1.1.1 example.com +short")
echo "$out" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
  && { echo "  FALHOU: agente resolveu DNS externo (tunel aberto)"; false; } \
  || echo "  ok: agente nao consegue consultar DNS"

# [5] agente nao pode desarmar o firewall
out=$(run_as_agent "nft flush ruleset 2>&1")
assert_contains "not permitted" "$out" "agente sem NET_ADMIN nao apaga o ruleset"

report
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bash tests/test-network.sh`
Expected: FALHA — imagem `agent-sandbox-net` não existe.

- [ ] **Step 3: Escrever as regras de firewall**

```bash
#!/usr/bin/env bash
# image/firewall/apply.sh
# Roda no INIT CONTAINER, com NET_ADMIN, e termina. O container do agente entra
# no pod DEPOIS e SEM NET_ADMIN — por isso ele nao consegue desfazer nada disso.
set -euo pipefail

nft add table inet asb
nft add chain inet asb out '{ type filter hook output priority 0; policy drop; }'

# respostas de conexoes que ja passaram pelo crivo
nft add rule inet asb out ct state established,related accept

# o agente alcanca o proxy pelo loopback (mesmo netns)
nft add rule inet asb out oif lo accept

# SOMENTE o uid do proxy fala com o mundo. O agente (uid 1000) nao emite
# nenhum pacote para fora — nem consulta DNS.
nft add rule inet asb out meta skuid 900 accept

echo "asb: firewall aplicado"
nft list ruleset
```

- [ ] **Step 4: Escrever a allowlist base e o template do Squid**

```text
# image/squid/allowlist-base.txt
# Um dominio por linha. Prefixo "." casa subdominios.
# APIs dos agentes
.anthropic.com
.openai.com
.googleapis.com
# codigo
.github.com
github.com
```

```text
# image/squid/squid.conf.tmpl
# __ALLOWLIST__ e substituido por cli/lib/render_squid.py
http_port 3128

acl allowed_domains dstdomain __ALLOWLIST__
acl SSL_ports port 443
acl CONNECT method CONNECT

# CONNECT-only para TLS: nao ha MITM, controla-se destino e nao conteudo.
http_access deny CONNECT !SSL_ports
http_access deny !allowed_domains
http_access allow allowed_domains
http_access deny all

cache deny all
access_log stdio:/tmp/squid-access.log
cache_log /tmp/squid-cache.log
pid_filename /tmp/squid.pid
```

- [ ] **Step 5: Escrever o Containerfile da imagem de rede**

```dockerfile
# image/Containerfile.net
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      nftables squid curl dnsutils netcat-openbsd iproute2 socat \
    && rm -rf /var/lib/apt/lists/*
COPY firewall/apply.sh /usr/local/bin/apply.sh
COPY squid/squid.conf.tmpl /etc/squid/squid.conf.tmpl
RUN chmod 0755 /usr/local/bin/apply.sh
# config de teste: apenas example.com. Em producao o CLI gera e monta o arquivo.
RUN sed 's/__ALLOWLIST__/.example.com/' /etc/squid/squid.conf.tmpl > /etc/squid/squid.conf \
    && chown -R 900:900 /var/spool/squid /var/log/squid 2>/dev/null || true
```

- [ ] **Step 6: Construir e rodar o teste**

Run:
```bash
podman build -t agent-sandbox-net -f image/Containerfile.net image/
bash tests/test-network.sh
```
Expected: cinco asserções `ok`, `falhou: 0`.

Se [1] falhar com timeout, verifique se o Squid subiu: `podman logs asb-squid`.

- [ ] **Step 7: Commit**

```bash
git add image/firewall image/squid image/Containerfile.net tests/test-network.sh
git commit
```

---

### Task 3: Perfil de projeto → configuração gerada

**Files:**
- Create: `cli/lib/profile.py`, `cli/lib/render_squid.py`, `profiles/default.toml`,
  `tests/test-profile.sh`

**Interfaces:**
- Produces:
  - `profile.py <caminho-do-repo>` → imprime JSON com as chaves
    `mode` (str), `services` (objeto), `allow` (lista de str), `proxy` (objeto).
    Se `.agent-sandbox.toml` não existir, usa `profiles/default.toml`.
  - `render_squid.py <allowlist-base> <perfil-json>` → imprime `squid.conf` no
    stdout.
- Consumes: `image/squid/squid.conf.tmpl` (Task 2).

- [ ] **Step 1: Escrever o teste que falha**

```bash
#!/usr/bin/env bash
# tests/test-profile.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "isolated"

[services.postgres]
image = "postgres:14"
port = 5432

[network]
allow = ["registry.npmjs.org"]

[proxy]
java = true
TOML

echo "== Task 3: perfil =="
json=$(python3 cli/lib/profile.py "$tmp")
assert_eq "isolated" "$(echo "$json" | jq -r .mode)" "le o modo"
assert_eq "postgres:14" "$(echo "$json" | jq -r '.services.postgres.image')" "le a imagem do servico"
assert_eq "5432" "$(echo "$json" | jq -r '.services.postgres.port')" "le a porta do servico"
assert_eq "registry.npmjs.org" "$(echo "$json" | jq -r '.allow[0]')" "le a allowlist do projeto"
assert_eq "true" "$(echo "$json" | jq -r '.proxy.java')" "le a flag de proxy java"

# ausencia de arquivo cai no default, nao quebra
json2=$(python3 cli/lib/profile.py "$tmp/inexistente")
assert_eq "isolated" "$(echo "$json2" | jq -r .mode)" "default aplicado quando nao ha perfil"

# squid.conf gerado contem base + projeto
conf=$(python3 cli/lib/render_squid.py image/squid/allowlist-base.txt <(echo "$json"))
assert_contains ".anthropic.com" "$conf" "allowlist base entra no squid.conf"
assert_contains "registry.npmjs.org" "$conf" "allowlist do projeto entra no squid.conf"
assert_contains "http_access deny all" "$conf" "default-deny preservado"
assert_contains "http_port 3128" "$conf" "porta do proxy preservada"

report
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bash tests/test-profile.sh`
Expected: FALHA — `cli/lib/profile.py` não existe.

- [ ] **Step 3: Escrever o perfil padrão**

```toml
# profiles/default.toml
[sandbox]
mode = "isolated"

[network]
allow = []

[proxy]
java = false
```

- [ ] **Step 4: Escrever o leitor de perfil**

```python
#!/usr/bin/env python3
"""cli/lib/profile.py — le .agent-sandbox.toml de um repo e emite JSON normalizado.

Uso: profile.py <caminho-do-repo>
Se o repo nao tiver perfil, usa profiles/default.toml.
"""
import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent.parent / "profiles" / "default.toml"


def load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: profile.py <caminho-do-repo>", file=sys.stderr)
        return 2

    repo = Path(sys.argv[1])
    candidate = repo / ".agent-sandbox.toml"
    raw = load(candidate) if candidate.is_file() else load(DEFAULT)
    base = load(DEFAULT)

    out = {
        "mode": raw.get("sandbox", {}).get("mode", base["sandbox"]["mode"]),
        "services": raw.get("services", {}),
        "allow": raw.get("network", {}).get("allow", []),
        "proxy": {**base.get("proxy", {}), **raw.get("proxy", {})},
    }

    if out["mode"] not in ("isolated", "attached"):
        print(f"modo invalido: {out['mode']!r}", file=sys.stderr)
        return 1

    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Escrever o gerador do squid.conf**

```python
#!/usr/bin/env python3
"""cli/lib/render_squid.py — junta allowlist base + perfil e emite squid.conf.

Uso: render_squid.py <allowlist-base.txt> <perfil.json>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent.parent / "image" / "squid" / "squid.conf.tmpl"


def read_base(path: Path) -> list[str]:
    domains = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(line)
    return domains


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: render_squid.py <allowlist-base> <perfil-json>", file=sys.stderr)
        return 2

    domains = read_base(Path(sys.argv[1]))
    profile = json.loads(Path(sys.argv[2]).read_text())
    domains.extend(profile.get("allow", []))

    # dedup preservando ordem
    seen, ordered = set(), []
    for d in domains:
        if d not in seen:
            seen.add(d)
            ordered.append(d)

    if not ordered:
        print("allowlist vazia: o sandbox ficaria sem egresso algum", file=sys.stderr)
        return 1

    sys.stdout.write(TEMPLATE.read_text().replace("__ALLOWLIST__", " ".join(ordered)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Rodar o teste e ver passar**

Run: `bash tests/test-profile.sh`
Expected: nove asserções `ok`, `falhou: 0`.

- [ ] **Step 7: Commit**

```bash
git add cli/lib/profile.py cli/lib/render_squid.py profiles/default.toml tests/test-profile.sh
git commit
```

---

### Task 4: CLI `up` / `down`

**Files:**
- Create: `cli/agent-sandbox`, `cli/lib/pod.sh`, `tests/test-lifecycle.sh`

**Interfaces:**
- Consumes: `profile.py`, `render_squid.py` (Task 3); imagens de Task 1 e 2.
- Produces:
  - `agent-sandbox up --workspace <id> --repo <caminho>` → imprime, no stdout,
    **uma linha JSON**: `{"pod":"<nome>","port":<int>,"user":"agent"}`.
    Progresso e erros vão para stderr.
  - `agent-sandbox down --workspace <id>` → remove o pod. Idempotente.
  - Nome do pod: `asb-<workspace>`. Chave SSH:
    `~/.config/agent-sandbox/id_ed25519`, gerada na primeira execução.

- [ ] **Step 1: Escrever o teste que falha**

```bash
#!/usr/bin/env bash
# tests/test-lifecycle.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh

WS=lifecycle-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q
cat > "$REPO/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "isolated"
[services.postgres]
image = "postgres:16-alpine"
port = 5432
TOML

echo "== Task 4: ciclo de vida =="
out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
echo "$out" | jq -e . >/dev/null 2>&1 && echo "  ok: up emitiu JSON valido" || { echo "  FALHOU: JSON invalido: $out"; false; }

port=$(echo "$out" | jq -r .port)
assert_contains "asb-$WS" "$(echo "$out" | jq -r .pod)" "nome do pod correto"

key=~/.config/agent-sandbox/id_ed25519
ssh_agent() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }

assert_eq "1000" "$(ssh_agent 'id -u')" "SSH conecta e o agente e uid 1000"
assert_eq "ok" "$(ssh_agent 'test -d /workspace && echo ok')" "repo montado em /workspace"

# o postgres do pod responde em localhost:5432 — a promessa central do modo isolado
assert_eq "ok" "$(ssh_agent 'for i in $(seq 30); do nc -z 127.0.0.1 5432 && { echo ok; exit; }; sleep 2; done')" \
  "postgres descartavel responde em localhost:5432"

# o firewall esta de pe dentro do workspace real
assert_fails "sem egresso direto no workspace real" \
  ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null agent@127.0.0.1 'curl -s -m 6 https://1.1.1.1'

./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1
assert_fails "pod removido no down" podman pod exists "asb-$WS"
./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1
assert_eq "0" "$?" "down e idempotente"

report
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bash tests/test-lifecycle.sh`
Expected: FALHA — `cli/agent-sandbox` não existe.

- [ ] **Step 3: Escrever `cli/lib/pod.sh`**

```bash
#!/usr/bin/env bash
# cli/lib/pod.sh — ciclo de vida do pod. Fonte: source cli/lib/pod.sh
# Requer: ROOT (raiz do repo agent-sandbox)
set -euo pipefail

ASB_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox"
ASB_KEY="$ASB_CONFIG/id_ed25519"

asb_ensure_key() {
  [ -f "$ASB_KEY" ] && return 0
  mkdir -p "$ASB_CONFIG"; chmod 0700 "$ASB_CONFIG"
  ssh-keygen -t ed25519 -N '' -f "$ASB_KEY" -C agent-sandbox >&2
}

asb_up() {
  local ws="$1" repo="$2"
  local pod="asb-$ws"
  asb_ensure_key

  local profile squidconf
  profile=$(mktemp); squidconf=$(mktemp)
  python3 "$ROOT/cli/lib/profile.py" "$repo" > "$profile"
  python3 "$ROOT/cli/lib/render_squid.py" "$ROOT/image/squid/allowlist-base.txt" "$profile" > "$squidconf"

  podman pod exists "$pod" && podman pod rm -f "$pod" >/dev/null
  # porta 0 = o kernel sorteia; lemos de volta depois
  podman pod create --name "$pod" -p 127.0.0.1::22 >/dev/null
  podman pod start "$pod" >/dev/null

  # 1) firewall primeiro: nada sobe antes da fronteira existir
  podman run --rm --pod "$pod" --cap-add NET_ADMIN agent-sandbox-net \
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
    podman run -d --name "${pod}-${name}" --pod "$pod" \
      -e POSTGRES_PASSWORD=sandbox -e POSTGRES_USER=sandbox -e POSTGRES_DB=sandbox \
      "$image" >/dev/null
  done

  # 4) agente por ultimo, SEM NET_ADMIN
  podman run -d --name "${pod}-agent" --pod "$pod" \
    -e ORCA_SSH_PUBLIC_KEY="$(cat "${ASB_KEY}.pub")" \
    -e HTTPS_PROXY=http://127.0.0.1:3128 \
    -e HTTP_PROXY=http://127.0.0.1:3128 \
    -e NO_PROXY=127.0.0.1,localhost \
    -v "$repo:/workspace:Z" \
    agent-sandbox-base >/dev/null

  local port
  port=$(podman pod inspect "$pod" --format '{{range .InfraConfig.PortBindings}}{{end}}' 2>/dev/null || true)
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
```

- [ ] **Step 4: Escrever o dispatcher**

```bash
#!/usr/bin/env bash
# cli/agent-sandbox — ponto de entrada do host
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/cli/lib/pod.sh"

usage() {
  cat >&2 <<'USAGE'
uso:
  agent-sandbox up   --workspace <id> --repo <caminho>
  agent-sandbox down --workspace <id>
USAGE
  exit 2
}

cmd="${1:-}"; shift || usage
ws=""; repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) ws="${2:-}"; shift 2 ;;
    --repo)      repo="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

# id do workspace vira nome de container: rejeitar o que nao for seguro
case "$ws" in
  ''|*[!a-zA-Z0-9._-]*) echo "workspace invalido: use apenas [a-zA-Z0-9._-]" >&2; exit 2 ;;
esac

case "$cmd" in
  up)   [ -d "$repo" ] || { echo "repo inexistente: $repo" >&2; exit 2; }
        asb_up "$ws" "$(cd "$repo" && pwd)" ;;
  down) asb_down "$ws" ;;
  *)    usage ;;
esac
```

- [ ] **Step 5: Tornar executável e rodar o teste**

Run:
```bash
chmod +x cli/agent-sandbox
bash tests/test-lifecycle.sh
```
Expected: todas as asserções `ok`. Este teste leva ~1 min (baixa `postgres:16-alpine`).

Se `postgres` não responder: `podman logs asb-lifecycle-test-postgres`.

- [ ] **Step 6: Commit**

```bash
git add cli/agent-sandbox cli/lib/pod.sh tests/test-lifecycle.sh
git commit
```

---

### Task 5: Imagem autenticada

Passo interativo. **O agente executor não consegue conduzir o login** — não há
TTY. O script prepara, o humano faz o login, o script verifica e commita.

**Files:**
- Create: `cli/lib/auth.sh`, `docs/domains/sandbox/authentication.md`
- Modify: `cli/agent-sandbox` (adicionar subcomando `auth`)

**Interfaces:**
- Produces: imagem `agent-sandbox-auth`, usada por `asb_up` no lugar de
  `agent-sandbox-base` quando existir.

- [ ] **Step 1: Escrever o script de autenticação**

```bash
#!/usr/bin/env bash
# cli/lib/auth.sh — cria a imagem autenticada a partir da base
set -euo pipefail

asb_auth() {
  local c=asb-auth
  podman rm -f "$c" >/dev/null 2>&1 || true
  podman run -d --name "$c" --entrypoint sleep agent-sandbox-base infinity >/dev/null

  cat >&2 <<EOF

Faça os três logins AGORA, em outro terminal, um de cada vez:

  podman exec -it $c claude   /login
  podman exec -it $c codex    login --device-auth
  podman exec -it $c gemini   auth

Use SEMPRE o fluxo device-auth. O OAuth padrão abre um servidor de callback
numa porta do container que seu navegador não alcança, e trava.

Quando terminar, pressione ENTER aqui.
EOF
  read -r _

  # Verificar pelo EXIT CODE. Nunca por grep de "logged in": a string casa
  # tambem com "not logged in" e commitaria uma imagem nao autenticada.
  local failed=0
  podman exec "$c" codex login status >/dev/null 2>&1 || { echo "codex NAO autenticado" >&2; failed=1; }
  podman exec "$c" claude -p 'ok' >/dev/null 2>&1 || { echo "claude NAO autenticado" >&2; failed=1; }
  if [ "$failed" -ne 0 ]; then
    echo "abortado: nao vou commitar uma imagem nao autenticada" >&2
    podman rm -f "$c" >/dev/null; return 1
  fi

  # Forcar o entrypoint de volta ao sshd: sem isso a imagem herda 'sleep'.
  podman commit --change='ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]' \
    "$c" agent-sandbox-auth >&2
  podman rm -f "$c" >/dev/null
  echo "imagem agent-sandbox-auth criada" >&2
}
```

- [ ] **Step 2: Ligar o subcomando no dispatcher**

Em `cli/agent-sandbox`, após `source "$ROOT/cli/lib/pod.sh"`, adicionar
`source "$ROOT/cli/lib/auth.sh"`, e no `case "$cmd"` adicionar antes de `*)`:

```bash
  auth) asb_auth ;;
```

O `auth` não usa `--workspace`; mova a validação de `ws` para dentro dos ramos
`up`/`down` para não rejeitar `auth`.

- [ ] **Step 3: Fazer `asb_up` preferir a imagem autenticada**

Em `cli/lib/pod.sh`, antes do `podman run` do agente:

```bash
  local agent_image=agent-sandbox-base
  podman image exists agent-sandbox-auth && agent_image=agent-sandbox-auth
```

e trocar `agent-sandbox-base` por `"$agent_image"` no `podman run` do agente.

- [ ] **Step 4: Verificar o entrypoint da imagem comitada**

Run:
```bash
podman image inspect agent-sandbox-auth --format '{{json .Config.Entrypoint}}'
```
Expected: `["/usr/local/bin/entrypoint.sh"]` — não `["sleep"]`.

- [ ] **Step 5: Verificar que a imagem autenticada sobe e aceita SSH**

Run: `bash tests/test-lifecycle.sh`
Expected: passa igual, agora usando `agent-sandbox-auth`.

- [ ] **Step 6: Commit**

```bash
git add cli/lib/auth.sh cli/agent-sandbox cli/lib/pod.sh docs/domains/sandbox/authentication.md
git commit
```

---

### Task 6: Agentes reais atrás do proxy

Risco aberto nº 2 do spec. Ferramentas que resolvem DNS antes de proxiar
quebram, porque o agente não tem DNS.

**Files:**
- Create: `tests/test-agents-behind-proxy.sh`
- Modify: `image/squid/allowlist-base.txt` conforme o que faltar

**Interfaces:**
- Consumes: `agent-sandbox-auth` (Task 5), pod de Task 4.

- [ ] **Step 1: Escrever o teste**

```bash
#!/usr/bin/env bash
# tests/test-agents-behind-proxy.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
WS=agents-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port)
key=~/.config/agent-sandbox/id_ed25519
sa() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>&1; }

echo "== Task 6: agentes atras do proxy =="
assert_contains "http://127.0.0.1:3128" "$(sa 'echo $HTTPS_PROXY')" "HTTPS_PROXY chega na sessao SSH"
assert_contains "false" "$(sa 'echo $GEMINI_SANDBOX')" "GEMINI_SANDBOX desligado"
assert_contains "ok" "$(sa 'claude -p "responda apenas: ok" 2>&1 | tail -1')" "Claude Code responde atras do proxy"
assert_contains "npm" "$(sa 'npm ping 2>&1 | tail -1')" "npm resolve atras do proxy"
report
```

- [ ] **Step 2: Rodar e observar o que falha**

Run: `bash tests/test-agents-behind-proxy.sh`
Expected: pode falhar. Cada falha indica um domínio ausente da allowlist ou uma
ferramenta que ignora proxy.

- [ ] **Step 3: Diagnosticar pelo log do Squid**

Run: `podman logs asb-agents-test-squid 2>&1 | grep DENIED`
Cada linha `TCP_DENIED` nomeia o domínio que faltou. Acrescente-o a
`image/squid/allowlist-base.txt` **somente se for legítimo** — a allowlist é o
controle, não uma formalidade.

- [ ] **Step 4: Repetir até passar**

Run: `bash tests/test-agents-behind-proxy.sh`
Expected: quatro asserções `ok`.

- [ ] **Step 5: Registrar o que quebrou**

Anotar em `docs/domains/sandbox/troubleshooting.md`, por ecossistema, o que
exigiu configuração além de `HTTPS_PROXY`.

- [ ] **Step 6: Commit**

```bash
git add tests/test-agents-behind-proxy.sh image/squid/allowlist-base.txt docs/domains/sandbox/troubleshooting.md
git commit
```

---

### Task 7: Receita do Orca

**Files:**
- Create: `recipes/create.sh`, `recipes/destroy.sh`, `recipes/shim.template.sh`,
  `tests/test-recipe.sh`

**Interfaces:**
- Consumes: `agent-sandbox up/down` (Task 4).
- Produces: JSON do contrato SSH do Orca, **uma linha, no stdout**. Todo
  progresso vai para stderr — qualquer ruído no stdout quebra o parser do Orca.

- [ ] **Step 1: Escrever o teste**

```bash
#!/usr/bin/env bash
# tests/test-recipe.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace recipe-test >/dev/null 2>&1' EXIT
git -C "$REPO" init -q

echo "== Task 7: receita Orca =="
out=$(ORCA_WORKSPACE_ID=recipe-test ./recipes/create.sh "$REPO" 2>/dev/null)
assert_eq "1" "$(echo "$out" | wc -l)" "create emite exatamente UMA linha"
echo "$out" | jq -e . >/dev/null && echo "  ok: JSON valido" || { echo "  FALHOU: JSON invalido"; false; }
assert_eq "1" "$(echo "$out" | jq -r .schemaVersion)" "schemaVersion 1"
assert_eq "ssh" "$(echo "$out" | jq -r .connection.type)" "connection.type ssh"
assert_eq "127.0.0.1" "$(echo "$out" | jq -r .connection.target.host)" "host loopback"
assert_eq "agent" "$(echo "$out" | jq -r .connection.target.username)" "username agent"
assert_eq "true" "$(echo "$out" | jq -r .connection.target.identitiesOnly)" "identitiesOnly true"
assert_eq "null" "$(echo "$out" | jq -r .pairingCode)" "SSH mode nao emite pairingCode"
report
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bash tests/test-recipe.sh`
Expected: FALHA — `recipes/create.sh` não existe.

- [ ] **Step 3: Escrever o create**

```bash
#!/usr/bin/env bash
# recipes/create.sh — contrato de ciclo de vida do Orca (SSH mode).
# Roda NO HOST, a partir da raiz do repo do projeto.
# Imprime UMA linha JSON no stdout. Todo o resto vai para stderr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="${1:-$PWD}"
ws="${ORCA_WORKSPACE_ID:-$(basename "$repo")-$$}"
ws=$(printf '%s' "$ws" | tr -c 'a-zA-Z0-9._-' '-')

up=$("$ROOT/cli/agent-sandbox" up --workspace "$ws" --repo "$repo")
port=$(printf '%s' "$up" | jq -r .port)
key="${XDG_CONFIG_HOME:-$HOME/.config}/agent-sandbox/id_ed25519"

jq -nc \
  --arg label "agent-sandbox-$ws" \
  --arg key "$key" \
  --argjson port "$port" '
{
  schemaVersion: 1,
  connection: {
    type: "ssh",
    projectRoot: "/workspace",
    target: {
      label: $label,
      host: "127.0.0.1",
      port: $port,
      username: "agent",
      identityFile: $key,
      identitiesOnly: true
    }
  }
}'
```

- [ ] **Step 4: Escrever o destroy e o shim**

```bash
#!/usr/bin/env bash
# recipes/destroy.sh — le o payload do ciclo de vida no stdin
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
payload=$(cat || true)
ws=$(printf '%s' "$payload" | jq -r '.userData.workspace // empty' 2>/dev/null || true)
[ -n "$ws" ] || ws="${ORCA_WORKSPACE_ID:-}"
[ -n "$ws" ] || { echo "sem workspace para destruir" >&2; exit 0; }
"$ROOT/cli/agent-sandbox" down --workspace "$ws" >&2
```

```bash
#!/usr/bin/env bash
# recipes/shim.template.sh — copiado para cada projeto consumidor como
# scripts/orca-vm/create.sh e destroy.sh. A LOGICA NAO E COPIADA: so o ponteiro.
# Editar aqui e ressincronizar; nunca editar a copia no projeto.
set -euo pipefail
exec "$HOME/Data/Projects/agent-sandbox/recipes/__ACTION__.sh" "$(cd "$(dirname "$0")/../.." && pwd)"
```

- [ ] **Step 5: Rodar o teste**

Run: `chmod +x recipes/*.sh && bash tests/test-recipe.sh`
Expected: oito asserções `ok`.

- [ ] **Step 6: Validar com o doctor do Orca**

Criar `orca.yaml` num repo de teste com:

```yaml
environmentRecipes:
  - id: agent-sandbox
    name: Agent Sandbox
    create:  ./scripts/orca-vm/create.sh
    destroy: ./scripts/orca-vm/destroy.sh
```

Run: `orca vm recipe doctor agent-sandbox --repo-path <repo> --json`
Expected: sem falhas. Este passo é gratuito e não provisiona nada.

- [ ] **Step 7: Self-test ao vivo**

Run: `orca vm recipe doctor agent-sandbox --repo-path <repo> --provision --json`
Expected: create → valida → destroy, verde. Em falha, o transcript completo
indica o que corrigir; itere até passar.

Lembrete do guia do Orca: o compositor só oferece a receita no seletor quando o
`orca.yaml` está no **branch primário** do checkout primário. O `doctor` valida
de qualquer branch.

- [ ] **Step 8: Commit**

```bash
git add recipes tests/test-recipe.sh
git commit
```

---

### Task 8: Modo anexado

O Squid não serve aqui: é proxy CONNECT para TLS e não carrega protocolo de fio
do PostgreSQL. Usa-se encaminhador TCP em loopback como uid 900.

**Files:**
- Create: `cli/lib/attach.sh`, `tests/test-attached.sh`
- Modify: `cli/lib/pod.sh` (chamar `asb_attach` quando `mode == "attached"`)

**Interfaces:**
- Consumes: perfil com `mode = "attached"` e `[[attach]]` com `port`.
- Produces: `asb_attach <pod> <perfil-json>` — sobe um container `socat` por
  porta declarada.

- [ ] **Step 1: Escrever o teste**

```bash
#!/usr/bin/env bash
# tests/test-attached.sh
# PRE-REQUISITO: a stack hexmed precisa estar no ar (postgres publicado na 5432).
set -uo pipefail
cd "$(dirname "$0")/.."
source tests/assert.sh
nc -z 127.0.0.1 5432 2>/dev/null || { echo "PULADO: nada escutando em 127.0.0.1:5432"; exit 0; }

WS=attached-test
REPO=$(mktemp -d); trap 'rm -rf "$REPO"; ./cli/agent-sandbox down --workspace "$WS" >/dev/null 2>&1' EXIT
git -C "$REPO" init -q
cat > "$REPO/.agent-sandbox.toml" <<'TOML'
[sandbox]
mode = "attached"
[[attach]]
port = 5432
TOML

out=$(./cli/agent-sandbox up --workspace "$WS" --repo "$REPO" 2>/dev/null)
port=$(echo "$out" | jq -r .port); key=~/.config/agent-sandbox/id_ed25519
sa() { ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null agent@127.0.0.1 "$1" 2>/dev/null; }

echo "== Task 8: modo anexado =="
assert_eq "ok" "$(sa 'nc -z -w4 127.0.0.1 5432 && echo ok')" "postgres real alcancavel em localhost:5432"
# cirurgico: apenas a porta declarada, nada mais do host
assert_fails "porta do host nao declarada continua bloqueada" \
  ssh -i "$key" -p "$port" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null agent@127.0.0.1 'nc -z -w4 127.0.0.1 6379'
report
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bash tests/test-attached.sh`
Expected: FALHA (ou PULADO se a stack não estiver no ar).

- [ ] **Step 3: Escrever o encaminhador**

```bash
#!/usr/bin/env bash
# cli/lib/attach.sh — modo anexado: encaminhador TCP em loopback como uid 900.
# O agente (uid 1000) fala com 127.0.0.1:<porta>; quem sai e o uid 900, ja
# permitido pelo firewall. O .env do projeto permanece intocado.
set -euo pipefail

asb_attach() {
  local pod="$1" profile="$2"
  # gateway do host visto de dentro do netns
  local hostip
  hostip=$(podman run --rm --pod "$pod" agent-sandbox-net \
    sh -c "ip route | awk '/default/{print \$3; exit}'")
  [ -n "$hostip" ] || { echo "nao foi possivel achar o IP do host" >&2; return 1; }

  python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))
for e in p.get("attach", []):
    print(e["port"])
' "$profile" | while read -r port; do
    podman run -d --name "${pod}-fwd-${port}" --pod "$pod" --user 900 \
      agent-sandbox-net \
      socat "TCP-LISTEN:${port},bind=127.0.0.1,fork,reuseaddr" "TCP:${hostip}:${port}" >/dev/null
    echo "anexado: 127.0.0.1:${port} -> ${hostip}:${port}" >&2
  done
}
```

- [ ] **Step 4: Ler `attach` no perfil**

Em `cli/lib/profile.py`, adicionar ao dicionário `out`:

```python
        "attach": raw.get("attach", []),
```

- [ ] **Step 5: Chamar no `asb_up`**

Em `cli/lib/pod.sh`, após subir o Squid e antes do container do agente:

```bash
  if [ "$(jq -r .mode "$profile")" = "attached" ]; then
    asb_attach "$pod" "$profile"
  fi
```

E `source "$ROOT/cli/lib/attach.sh"` no dispatcher.

- [ ] **Step 6: Rodar o teste**

Run: `bash tests/test-attached.sh`
Expected: duas asserções `ok`.

- [ ] **Step 7: Commit**

```bash
git add cli/lib/attach.sh cli/lib/profile.py cli/lib/pod.sh cli/agent-sandbox tests/test-attached.sh
git commit
```

---

### Task 9: Validação no hexmed-stack

**Files:**
- Create: `/home/v/Data/Projects/hexmed-stack/.agent-sandbox.toml`,
  `/home/v/Data/Projects/hexmed-stack/scripts/orca-vm/{create,destroy}.sh`,
  `/home/v/Data/Projects/hexmed-stack/orca.yaml`
- Create: `docs/domains/sandbox/hexmed-notes.md`

- [ ] **Step 1: Mapear o que a suíte realmente toca**

Run:
```bash
cd /home/v/Data/Projects/hexmed-stack
grep -rn "localhost:[0-9]\+" --include=".env*" . | grep -v node_modules
```
Expected: lista de portas. O spec já registra: `5432` (Postgres) e `6379`
(Redis) ficam no pod; **`8080` é o DCM4CHEE ARC e NÃO existe no pod isolado**.
Registrar quais testes dependem do ARC.

- [ ] **Step 2: Escrever o perfil do projeto**

```toml
# /home/v/Data/Projects/hexmed-stack/.agent-sandbox.toml
[sandbox]
mode = "isolated"

[services.postgres]
image = "postgres:14"
port  = 5432

[services.redis]
image = "redis:7-alpine"
port  = 6379

[network]
allow = ["registry.npmjs.org", "repo.maven.apache.org", "pypi.org", "files.pythonhosted.org"]

[proxy]
java = true
```

- [ ] **Step 3: Instalar os shims e o orca.yaml**

```bash
cd /home/v/Data/Projects/hexmed-stack
mkdir -p scripts/orca-vm
for a in create destroy; do
  sed "s/__ACTION__/$a/" \
    ~/Data/Projects/agent-sandbox/recipes/shim.template.sh > "scripts/orca-vm/$a.sh"
  chmod +x "scripts/orca-vm/$a.sh"
done
cat > orca.yaml <<'YAML'
environmentRecipes:
  - id: agent-sandbox
    name: Agent Sandbox
    create:  ./scripts/orca-vm/create.sh
    destroy: ./scripts/orca-vm/destroy.sh
YAML
```

- [ ] **Step 4: Validar a receita**

Run:
```bash
orca vm recipe doctor agent-sandbox --repo-path /home/v/Data/Projects/hexmed-stack --json
```
Expected: sem falhas.

- [ ] **Step 5: Rodar os testes que dependem só de Postgres e Redis**

Subir o workspace e rodar a suíte por SSH, **sem editar nenhum `.env`**.
Expected: passam. Se um teste falhar por `localhost:8080`, ele depende do ARC —
registrar em `hexmed-notes.md` como candidato a modo anexado ou stub, não como
falha do sandbox.

- [ ] **Step 6: Commit**

Commitar **apenas** o que é do `agent-sandbox`. As mudanças no `hexmed-stack`
são de outro repositório e exigem autorização separada do usuário.

```bash
git add docs/domains/sandbox/hexmed-notes.md
git commit
```

---

### Task 10: Domain pack e extensão aos demais projetos

**Files:**
- Create: `docs/domains/sandbox/README.md`, `architecture.md`, `network.md`,
  `credentials.md`
- Modify: `AGENTS.md` (linha na tabela de subagentes/domínios)

- [ ] **Step 1: Escrever o domain pack**

Conteúdo derivado do spec — arquitetura, rede, credenciais, troubleshooting.
Regra do `AGENTS.md`: agentes leem `docs/domains/`, não duplicam regra em prompt.

- [ ] **Step 2: Estender a `BlackICE` e `tsguard`**

Repetir os passos 2–4 da Task 9 para cada um, com perfil próprio.

- [ ] **Step 3: Sincronizar os mirrors de skills**

Run: `node scripts/sync-skills.mjs && node scripts/sync-skills.mjs --check`
Expected: paridade confirmada.

- [ ] **Step 4: Commit**

```bash
git add docs/domains/sandbox AGENTS.md
git commit
```

---

### Task 11: Tornar o sandbox o único caminho

**Este é o passo que fecha o problema original.** Os dez anteriores constroem a
opção; só este a torna a realidade. Enquanto o Orca puder lançar agente direto
no host, o sandbox não protege ninguém.

**Files:**
- Create: `docs/domains/sandbox/enforcement.md`

- [ ] **Step 1: Investigar se o Orca permite forçar a receita**

Run:
```bash
orca agent-context --json | jq -r '.commands[] | select((.summary + (.notes|join(" "))) | test("default|require|force|recipe"; "i")) | .command + " :: " + .summary'
```
Procurar: configuração de recipe padrão por projeto, ou bloqueio de criação de
workspace local.

- [ ] **Step 2: Registrar o achado, honestamente**

Se houver mecanismo, documentar e ativar. **Se não houver, escrever isso com
todas as letras** em `enforcement.md`: o sandbox é opt-in, depende de disciplina
do usuário, e essa é uma limitação real — não presumir que está resolvido.

- [ ] **Step 3: Commit**

```bash
git add docs/domains/sandbox/enforcement.md
git commit
```

---

## Self-Review

**Cobertura do spec:** D1→T1/T4, D2→T4, D3→Global Constraints, D4→T4/T8,
D5→T1, D6→T2/T3, D7→T5, D8→T1 (nenhuma credencial git na imagem),
D9→T7. §3.2 rede→T2. §3.3 componentes→T1/T3/T4. §3.4 modos→T4/T8.
§3.5 credenciais→T5. §3.6 aninhamento→T1 (env) e T6 (verificação).
§4 layout→estrutura de arquivos. §5 Orca→T7. §5.1 suspend/resume→
deliberadamente ausente, conforme o spec. §6 perfil→T3. §7 critérios→
distribuídos nos testes de T1/T2/T4/T7/T8. §8 limitações→T6 e T11.
§9 riscos→T4 (postgres) e T6 (agentes atrás do proxy). §10 sequenciamento→
ordem das tarefas.

**Placeholders:** nenhum `TBD`/`TODO`. Todo passo de código traz o código.

**Consistência de tipos:** `asb_up`/`asb_down`/`asb_auth`/`asb_attach` usados
com a mesma assinatura em que foram definidos. `profile.py` emite `mode`,
`services`, `allow`, `proxy` (T3) e ganha `attach` em T8, com o consumidor
correspondente. Nome do pod `asb-<workspace>` consistente entre T4, T7 e T8.
Porta do proxy `3128` consistente entre T2, T3 e T4. Uid 900/1000 consistentes
em todas as tarefas.
