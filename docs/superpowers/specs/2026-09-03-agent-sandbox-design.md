# Design: agent-sandbox

**Data:** 2026-09-03
**Status:** Aprovado para planejamento de implementação
**Escopo:** Ambiente de execução isolado para agentes de IA (Claude Code, Codex,
Gemini CLI) orquestrados pelo Orca, em host Omarchy/Arch.

---

## 1. Problema

Os agentes são orquestrados hoje pelo Orca em *yolo mode* — permissões
completamente ignoradas — executando **diretamente no host**. O incidente que
motivou este trabalho: um agente instalou pacotes de sistema (cliente
PostgreSQL) sem conhecimento do usuário, descoberto por acaso dias depois.

O risco real não é o pacote instalado. É que **não existe fronteira**: qualquer
ação que o agente decida tomar acontece na máquina do usuário, e não há
inventário do que já foi feito.

### Requisitos

1. Agentes não podem modificar o host (pacotes, serviços, arquivos fora do
   projeto).
2. Agentes precisam de acesso a banco de dados para rodar testes.
3. O Orca precisa lançar os agentes já dentro do ambiente isolado.
4. Precisa funcionar para **múltiplos projetos** (`hexmed-stack`, `BlackICE`,
   `tsguard`, e futuros), não só um.

---

## 2. Decisões

| # | Decisão | Justificativa |
|---|---|---|
| D1 | **Container** como fronteira, não sandbox nativo | Sandbox nativo do Claude Code cobre só Bash; hooks e MCP servers ficam de fora. A documentação da Anthropic é explícita: sessões com `--dangerously-skip-permissions` exigem container, VM ou sandbox-runtime. |
| D2 | **Podman rootless**; Docker permanece intacto | Zero privilégio permanente no host. Pré-requisitos (cgroup v2, subuid/subgid, userns, pasta) já satisfeitos na máquina. Docker continua rodando a infraestrutura via Portainer, sem alteração. |
| D3 | **Nunca instalar `podman-docker`** | O pacote declara `Provides: docker` / `Conflicts With: docker` e sequestraria `/usr/bin/docker`, quebrando os fluxos existentes da stack. |
| D4 | Banco **descartável por workspace** como padrão; modo anexado como opt-in | O container protege o host, não o banco compartilhado. Uma migração destrutiva é dano mais provável que instalação de pacote. |
| D5 | Sandbox de **tarefa**: build, testes e lint dentro; aplicação continua no host | Mantém a imagem enxuta e não altera o loop de desenvolvimento atual. |
| D6 | Egresso **default-deny** via proxy CONNECT com allowlist de domínio | Arquivos `.env` dos projetos contêm credenciais em texto puro; egresso aberto é canal de exfiltração via injeção de prompt. |
| D7 | **Imagem autenticada** (`podman commit` após login interativo) | O home do host nunca é montado. É o padrão documentado pelo próprio Orca (§7h do guia `orca-per-workspace-env`). |
| D8 | **Sem credencial Git** dentro do sandbox | Agente faz commit local; push e PR são do host. Alinhado ao `AGENTS.md` do repositório, que já proíbe `git push` sem autorização humana explícita. |
| D9 | Conexão Orca via **SSH mode**, não Orca-server mode | Evita a armadilha documentada de snapshotar máquina onde o runtime do Orca já rodou (VMs passam a compartilhar `deviceToken` e `agent-session-authority.key`). |

---

## 3. Arquitetura

### 3.1 Visão geral

```
Usuário cria workspace no Orca
  └─> Orca lê environmentRecipes do orca.yaml do projeto
       └─> executa create.sh NO HOST (como o usuário, sem sudo)
            └─> agent-sandbox up <workspace>
                 ├─ cria POD podman rootless
                 ├─ init container (NET_ADMIN) aplica nftables no netns e SAI
                 ├─ squid (uid 900) — proxy CONNECT com allowlist
                 ├─ serviços do perfil (postgres/redis) — modo isolado
                 └─ container do agente (uid 1000, sshd)
            └─> imprime JSON {connection:{type:"ssh",...}}
       └─> Orca disca SSH em 127.0.0.1:<porta> e abre o agente lá dentro
```

O agente nasce dentro do container. Não existe caminho dele para o host: sem
socket podman, sem socket docker, sem sudo, sem `~/.ssh`.

### 3.2 Rede — arquitetura validada empiricamente

Containers de um pod compartilham o *network namespace*. O firewall diferencia
processos por **uid do socket** (`meta skuid`), validado neste host:

```
pod (netns compartilhado)
├─ init (NET_ADMIN)  aplica nftables e termina
│     policy drop
│     + ct state established,related accept
│     + oif lo accept              ← agente alcança o proxy pelo loopback
│     + meta skuid 900 accept      ← SOMENTE o proxy fala com o mundo
├─ squid  uid 900    allowlist CONNECT por domínio; resolve DNS ele mesmo
└─ agente uid 1000   sem egresso direto, SEM DNS, sem NET_ADMIN
```

**Propriedades garantidas:**

- O agente não emite **nenhum** pacote para fora do netns — nem consulta DNS.
- O agente não pode alterar nem ler o ruleset (`Operation not permitted`).
- A allowlist é por **domínio**, resolvida pelo Squid — imune a rotação de IP de
  CDN e ao problema de dual-stack A/AAAA.
- O init container aplica as regras e morre; o container do agente entra no pod
  **sem** `NET_ADMIN`. Sem isso, o agente poderia apagar as próprias regras e a
  allowlist seria decorativa.

Allowlist base: APIs dos três agentes e GitHub. Cada perfil de projeto acrescenta
os registries do seu ecossistema.

O `squid.conf` efetivo é **gerado pelo CLI a cada `up`**, concatenando a
allowlist base (`image/squid/`) com a chave `network.allow` do
`.agent-sandbox.toml` do projeto. Não é editado à mão dentro do container, e o
container do agente não tem permissão de escrita sobre ele.

### 3.3 Componentes

**Imagem base (`agent-sandbox-base`)** — Debian slim, usuário não-root `agent`
(uid 1000). Contém `mise` (delega toolchains ao `mise.toml` de cada repo), git,
gh, ripgrep, sshd e os três CLIs de agente.

*Host keys SSH gerados no build*, não no runtime: containers efêmeros
reutilizam portas em `127.0.0.1`, e chaves geradas por container disparariam
aviso de host-key-changed a cada novo workspace.

**Imagem autenticada (`agent-sandbox-auth`)** — construída uma vez via
`agent-sandbox auth`. O usuário faz os três logins interativos usando o fluxo
**device-auth** (o OAuth padrão abre servidor de callback numa porta do container
inalcançável pelo navegador do host, e trava). O CLI então executa
`podman commit`.

**Pod por workspace** — containers compartilham o netns, portanto `localhost:5432`
dentro do container do agente é o Postgres descartável do pod. **Nenhum arquivo
`.env` de projeto precisa ser alterado**: os projetos já endereçam
`localhost:PORTA`, não nomes DNS de compose.

**CLI de host (`~/.local/bin/agent-sandbox`)** — `image build`, `auth`, `up`,
`down`, `doctor`, e os subcomandos que emitem o contrato JSON do Orca.
Instalado uma vez, versionado neste repositório.

### 3.4 Modos de acesso a dados

**Isolado (padrão)** — o pod sobe seus próprios Postgres e Redis, semeados de
migrations ou dump. Morrem com o workspace.

**Anexado (opt-in por workspace)** — acesso ao banco real do host.

O Squid **não serve** para este caso: é proxy CONNECT para TLS e não carrega o
protocolo de fio do PostgreSQL. O modo anexado usa mecanismo próprio — um
**encaminhador TCP em loopback** (`socat`) rodando como **uid 900** dentro do
pod, escutando em `127.0.0.1:5432` e repassando para o IP do host na porta 5432.

A propriedade se mantém: o agente (uid 1000) continua sem egresso direto e fala
apenas com o loopback; quem sai é o uid 900, já permitido pelo firewall. E o
`.env` do projeto continua intocado, porque o endereço permanece
`localhost:5432`.

Cada porta anexada é uma entrada explícita no perfil do projeto. **Nunca** se
libera faixa privada inteira: o host participa de uma rede Tailscale e o `pasta`
copia as interfaces do host para o netns do container, então liberar RFC1918 ou
CGNAT daria ao agente alcance à tailnet inteira.

### 3.5 Credenciais

- Home do host **nunca** é montado (regra explícita do guia do Orca).
- Sem `~/.ssh`, sem `gh auth token`, sem PAT dentro do sandbox.
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` habilitado.
- **Consequência aceita:** a imagem autenticada carrega credencial *baked*. Não
  sai do disco do usuário, mas todo workspace lê a mesma, e ela expira. O
  procedimento de re-autenticação e o sintoma de expiração são parte da
  documentação entregue.

### 3.6 Conflitos de aninhamento entre agentes

Os três agentes tentam se sandboxar dentro do container e conflitam. A imagem
resolve explicitamente:

| Agente | Configuração | Motivo |
|---|---|---|
| Gemini CLI | `GEMINI_SANDBOX=false` | Caso contrário sobe o *próprio* container (docker-in-docker). |
| Codex | `sandbox_mode = "danger-full-access"` **declarado** | Sem `SYS_ADMIN` o bwrap dele falha e ele cai nisso **em silêncio**. Melhor explícito e comentado que degradando escondido. |
| Claude Code | `--dangerously-skip-permissions` liberado | A fronteira agora existe. Exige usuário não-root — daí `agent` uid 1000. |

O sandbox bwrap nativo do Claude Code fica como camada interna **opcional**,
condicionada a userns aninhado funcionar em rootless — não verificado.

---

## 4. Layout do repositório

Seguindo a Golden Rule do `AGENTS.md` — conhecimento de domínio mora uma vez:

```
docs/domains/sandbox/     SSoT: arquitetura, rede, credenciais, troubleshooting
image/Containerfile       imagem base
image/firewall/           regras nftables + allowlist base
image/squid/              template de configuração do proxy
cli/agent-sandbox         CLI do host
recipes/                  scripts do contrato de ciclo de vida do Orca
profiles/default.toml     perfil padrão
```

---

## 5. Integração com o Orca

O compositor lê `environmentRecipes` do `orca.yaml` do **checkout primário, no
branch primário** — não de worktree nem de branch de feature. Cada projeto recebe:

```yaml
environmentRecipes:
  - id: agent-sandbox
    name: Agent Sandbox
    create:  ./scripts/orca-vm/create.sh
    destroy: ./scripts/orca-vm/destroy.sh
```

Os scripts são *shims* de poucas linhas que chamam o CLI compartilhado. **A
lógica não é copiada entre repositórios** — apenas o ponteiro. Atualizações
acontecem em um lugar só.

`create.sh` roda no host e imprime uma única linha JSON:

```json
{
  "schemaVersion": 1,
  "connection": {
    "type": "ssh",
    "projectRoot": "/workspace/<repo>",
    "target": {
      "label": "agent-sandbox-<workspace>",
      "host": "127.0.0.1",
      "port": 49213,
      "username": "agent",
      "identityFile": "~/.config/agent-sandbox/id_ed25519",
      "identitiesOnly": true
    }
  }
}
```

`port` é a porta efêmera publicada em `127.0.0.1`, sorteada a cada
`create` e preenchida pelo CLI — o valor acima é ilustrativo. `portForwards`
fica disponível para expor portas de serviço do sandbox quando necessário.

### 5.1 Ciclo de vida: suspend e resume

O contrato do Orca trata `suspend` e `resume` como opcionais. **Esta primeira
versão não os implementa**, por uma razão específica: `podman pod pause` congela
os processos, mas a porta SSH publicada e o netns sobrevivem — e o `resume`
teria de reemitir o JSON de conexão porque a porta pode mudar. Sem eles, dormir
e acordar a máquina simplesmente derruba o workspace, e o Orca recria.

A consequência a aceitar: **o estado não commitado dentro do container é
perdido** ao dormir a máquina. O agente deve commitar localmente ao concluir
etapas. Se isso se mostrar doloroso no uso real, `suspend`/`resume` viram a
primeira extensão — o contrato já os prevê.

---

## 6. Configuração por projeto

`.agent-sandbox.toml` na raiz de cada repositório:

```toml
[sandbox]
mode = "isolated"          # ou "attached"

[services.postgres]
image = "postgres:14"
port  = 5432
seed  = "./db/seed.sql"

[services.redis]
image = "redis:7-alpine"
port  = 6379

[network]
allow = ["registry.npmjs.org", "repo.maven.apache.org"]

[proxy]
# ecossistemas que exigem configuração além de HTTPS_PROXY
java = true                # grava systemProp.https.proxyHost
```

---

## 7. Critérios de verificação

Nenhuma alegação de conclusão sem estes resultados observados:

| Verificação | Critério |
|---|---|
| `orca vm recipe doctor <id> --json` | passa em dry-run |
| `orca vm recipe doctor <id> --provision --json` | create → valida → destroy, verde |
| Domínio na allowlist, via proxy | HTTP 200 |
| Domínio fora da allowlist, via proxy | negado pelo Squid |
| Conexão direta ignorando o proxy | bloqueada pelo nftables |
| `dig @1.1.1.1 <qualquer>.com` do agente | sem resposta (verificado por `dig`, `getent` e `nc -u`) |
| `nft flush ruleset` do container do agente | `Operation not permitted` |
| `ls /var/run/*.sock`; `sudo -n true` de dentro | ambos falham |
| Host key SSH estável entre dois workspaces | sem aviso de host-key-changed |
| Testes do `hexmed-stack` que dependem **apenas de Postgres e Redis** | passam sem editar `.env` |
| Testes que dependem do DCM4CHEE ARC | mapeados antes; `DCM4CHEE_ARC_5_HOST=localhost:8080` **não existe** dentro do pod isolado |

---

## 8. Limitações conhecidas

Documentadas porque são reais, não porque foram resolvidas:

1. **Exfiltração para domínio permitido continua possível.** Se `github.com`
   está na allowlist, um gist é uma saída. Nenhuma allowlist de rede resolve
   isso.
2. **Sem MITM de TLS** — decisão deliberada para evitar distribuir certificado
   self-signed. Controla-se *para onde*, não *o quê*.
3. **Ferramentas que ignoram variáveis de proxy** vão falhar. `HTTPS_PROXY`
   cobre a maioria; Maven e Gradle exigem `systemProp` separado. Cada
   ecossistema precisa de teste próprio.
4. **Ferramentas que resolvem DNS antes de proxiar** falham, já que o agente não
   tem DNS. Precisa de verificação por ecossistema.
5. **A imagem autenticada expira** e exige re-login periódico.
6. **Disponível não é obrigatório.** Enquanto o Orca puder lançar agente
   diretamente no host, o sandbox não protege ninguém. Ver §10.

---

## 9. Riscos abertos

| Risco | Mitigação |
|---|---|
| `orca.yaml` pode não aceitar caminho para CLI compartilhado | Resolvido por design: shim de poucas linhas por repositório funciona nos dois casos. |
| bwrap aninhado em rootless (camada interna opcional) | Não verificado. É opcional; se falhar, o container continua sendo a fronteira. |
| Postgres descartável respondendo em `localhost:5432` no pod | Não verificado empiricamente. Primeiro item da implementação. |
| Claude Code real atrás do proxy com `HTTPS_PROXY` | Não verificado empiricamente. Segundo item da implementação. |

---

## 10. Sequenciamento

1. Imagem base + host keys no build.
2. Verificar Postgres descartável em `localhost:5432` dentro do pod.
3. Verificar os três agentes reais atrás do proxy.
4. `agent-sandbox auth` — imagem autenticada.
5. CLI + shims de receita; validar com `doctor` e depois `--provision`.
6. Validar no `hexmed-stack`. **Primeiro mapear o que a suíte realmente
   toca**: os `.env` apontam para `localhost:8080` (DCM4CHEE ARC) e
   `localhost:6379` além do Postgres, e o ARC não está no pod. Testes que
   dependem dele exigem modo anexado ou stub — decidir caso a caso.
7. Estender a `BlackICE` e `tsguard`.
8. **Tornar o caminho sandboxed o único.** Investigar se o Orca permite forçar
   isso. Se não permitir, é disciplina do usuário — e precisa ser dito
   claramente, não presumido.

O passo 8 é o que efetivamente fecha o problema original. Os sete anteriores
constroem a opção; só o oitavo a torna a realidade.

---

## Apêndice — Evidência do spike (2026-09-03)

Executado neste host, com Podman 6.1.0 rootless, backend netavark, runtime runc,
cgroup v2.

| Verificação | Resultado |
|---|---|
| Podman rootless operacional | `rootless=true` |
| nftables aplicado no netns do pod com `NET_ADMIN` | aplicado |
| Regras valem para os demais containers do pod | `example.com` bloqueado de outro container |
| Container **sem** `NET_ADMIN` remove as regras? | **Não** — `Operation not permitted`; não apaga, não lê, não altera interface |
| `meta skuid` diferencia processos no netns compartilhado | uid 900 → HTTP 200; uid 1000 → bloqueado |
| Squid CONNECT, domínio permitido | HTTP 200 |
| Squid CONNECT, domínio negado | negado |
| Bypass direto do proxy | bloqueado pelo nftables |
| DNS arbitrário do agente | `no servers could be reached` |

**Achado descartado por erro de teste:** uma primeira medição indicou vazamento
de DNS. Era falso positivo — `dig +short` escreve mensagens de erro no stdout, e
o teste casava com qualquer saída. Refeito procurando um endereço IPv4 válido e
confirmado por três vias independentes (`dig`, `getent`, `nc -u`).

**Achado que alterou o design:** uma allowlist de nftables somente-IPv4 quebra
silenciosamente. `api.anthropic.com` deu timeout mesmo liberado por IPv4, porque
o cliente preferiu o registro AAAA e o `policy drop` da família `inet` o pegou.
O comportamento é *fail-closed* (correto), mas inviabilizaria o uso. A adoção do
proxy com allowlist por domínio elimina a classe inteira do problema.
