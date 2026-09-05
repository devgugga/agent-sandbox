# Design: agent-sandbox v2

**Data:** 2026-09-04
**Status:** Aprovado para planejamento de implementação
**Escopo:** Reconstrução do ambiente de execução isolado para agentes de IA
(Claude Code, Codex, Antigravity) orquestrados pelo Orca, em host Omarchy/Arch.
**Substitui:** `2026-09-03-agent-sandbox-design.md` e
`2026-09-04-orca-reboot-persistence-design.md`.

---

## 1. Por que reconstruir

O sistema v1 funciona em condições ideais e quebra em uso diário. Nove
problemas foram levantados pelo operador; oito são sintomas de uma única causa.

### 1.1 Os problemas relatados

| # | Problema | Fechado por |
|---|---|---|
| 1 | Agentes perdem sessão; sandbox não sobe após reboot, e quando sobe, sobe sem segurança | §4, §7 |
| 2 | Worktree criada dentro do Podman, inacessível às ferramentas do host | §5 |
| 3 | Agentes sem acesso a logs, rede e comandos dos containers Docker | §6 |
| 4 | Falta de documentação; manutenção depende de perguntar a um agente | §10 |
| 5 | Complexidade: 26 h de depuração entre dois modelos, e ainda restam falhas | §4 |
| 6 | Integração incompleta de Claude e Codex | §7 |
| 7 | A promessa era profissional e robusta; desandou | §3 |
| 8 | Skills, hooks e MCPs foram um pesadelo de portar (3+ tentativas) | §7.2 |
| 9 | Ferramentas de dev (`uv`) ausentes na imagem | §8 |

### 1.2 A causa raiz

Não é ausência de tipagem estática nem escolha de linguagem. É **excesso de
invariantes**.

O log de commits registra a doença: `fix pod lifecycle`, `restore firewall and
persistent state`, `fix workspace naming determinism`, `fix mount point and
podman command syntax`, `fix Podman rootless user namespace mapping`, `restore
autonomous mode`. Quase todo commit `🐛` corrige uma **regra de ordenação ou de
estado** que precisa valer simultaneamente em quatro caminhos de ciclo de vida
(`up`, `resume`, `restore-all`, `suspend`).

O invariante central e mais caro:

> As regras nftables vivem no *network namespace* do pod. O netns é recriado a
> cada `podman pod start`. Logo, **toda** partida precisa reaplicar o firewall
> antes de qualquer container de usuário — e provar que aplicou.

Desse único invariante nasceram: o init container com `CAP_NET_ADMIN`, o
`--user 1000` (não-óbvio) para o `nft` funcionar sob `keep-id`, o `resume`
ordenado que nunca passa por `up`, a prova `nft list table inet asb`, a sonda
fail-closed no entrypoint, o `restore-all`, a espera por rota/DNS do host, a
unidade systemd customizada, e o código de saída 2 para pods legados.

**Reescrever em Go ou Rust portaria esses invariantes fielmente e reproduziria
os mesmos bugs.** O alvo do redesign é ter menos invariantes.

---

## 2. Fatos verificados empiricamente

Medidos nesta máquina (Podman 6.1.0, Arch, kernel 7.1.9) antes de decidir
qualquer coisa. Nenhuma decisão abaixo se apoia em documentação ou memória.

### F1 — Rede `--internal` isola sem nftables e **persiste através de restart**

```
podman network create --internal asb-test
podman run --rm --network asb-test alpine …
  → ip route            : só a rota de link, SEM default
  → nc -z 1.1.1.1 443   : BLOCKED
  → nslookup api.anthropic.com : NORESOLVE
```

Após `podman stop` + `podman start` do container, **sem reaplicar nada**:
`STILL_BLOCKED`, `DNS_STILL_BLOCKED`. O Podman reconstrói a rede em toda
partida.

### F2 — Proxy dual-homed funciona e é alcançável por nome

Container conectado a `asb-test` **e** a uma rede normal: obtém `eth0` interno
e `eth1` externo, e `nc -z 1.1.1.1 443` retorna `PROXY_EGRESS_OK`. Do lado
interno, o agente resolve o proxy pelo **nome do container** via aardvark-dns —
inclusive depois do restart, quando o IP muda (`10.89.0.3` → `10.89.0.5`).

### F3 — Publicação de porta funciona em rede interna, e a porta é estável

`podman run -d --network <interna> -p 127.0.0.1::8080` publica normalmente; o
host alcança o serviço. Após `stop`/`start`, **a mesma porta** (`39781`) é
reusada, e o egresso do container continua `BLOCKED`. A porta que o Orca grava
permanece válida.

### F4 — `podman-restart.service` já existe como unidade de usuário

`/usr/lib/systemd/user/podman-restart.service`, `WantedBy=default.target`,
`After=network-online.target`, executando
`podman start --all --filter should-start-on-boot=true`.

### F5 — O socket do Docker é inalcançável pelo usuário

`/var/run/docker.sock` é `root:docker 0660`, e `id` do operador retorna
`uid=1000(v) groups=1000(v),998(wheel)` — **sem o grupo `docker`**. O histórico
confirma o uso real: `sudo docker compose`, `sudo docker ps`, `sudo docker logs`.
Um container rootless montando esse socket vê `nobody:nobody` e não lê nada.

### F6 — Podman rootless aninhado funciona sem privilégio

`podman run --user 1000 --device /dev/fuse --security-opt label=disable
quay.io/podman/stable` reporta `Rootless=true`, driver `overlay`, e executa um
container filho com sucesso. Sem `--privileged`.

### F7 — O Orca cria a worktree como irmã do `projectRoot`

De `~/.config/orca/orca-ephemeral-vm-runtimes.json`:

```
"workspaceId": "cac06f44-…::/home/agent/workspace-Add-Url-to-Generate-Key"
```

Com `projectRoot = /home/agent/workspace`, a worktree nasceu em
`/home/agent/workspace-<Nome>` — armazenamento privado do container. É a causa
mecânica do problema #2.

---

## 3. Decisões

| # | Decisão | Justificativa |
|---|---|---|
| D1 | **Isolamento por topologia de rede**, não por firewall aplicado | F1: a rede `--internal` é reconstruída pelo Podman a cada partida. Não há regra a perder, nem ordem a respeitar, nem prova a fazer. Elimina o invariante da §1.2. |
| D2 | **Sem pod.** Containers independentes numa rede nomeada | O pod existia para compartilhar o netns com o init container do firewall. Sem firewall, o pod não tem função — e some junto o `--userns` no pod, a distinção infra/membros e o `pod start` que subia tudo de uma vez. |
| D3 | **Um container por nível de confiança** | O proxy passa a ter perna na rede externa: qualquer processo nele tem egresso. Fundir squid, filtro de Docker e forwarders faria "acesso a Docker" implicar "egresso irrestrito". |
| D4 | **Caminho idêntico host↔container**, usuário `v`, uid 1000, home `/home/v` | F7: a worktree irmã precisa cair numa pasta montada. Idêntico (não só montado) também elimina a reescrita de caminhos de hooks do Orca. |
| D5 | **Credenciais em volume nomeado**, não em imagem derivada | Imagem derivada acopla login a rebuild de imagem (problema #1) e produz `agent-sandbox-auth-prev3`. Volume sobrevive a rebuild, a `down` e a reboot. |
| D6 | **Python 3 da stdlib, arquivo único, zero dependências** | `tomllib` é stdlib; YAML exigiria PyYAML instalado no host. O programa só orquestra `podman`: binário estático não compra nada, e um passo de build atrapalha correção emergencial. Robustez vem de menos invariantes (§1.2), não de tipagem. |
| D7 | **Acesso a Docker é eixo configurável por projeto**, default fechado | As necessidades diferem por projeto e projetos futuros não são conhecidos. `host_ports`, `mode` e `host_api` são independentes. |
| D8 | **Nunca montar `/var/run/docker.sock` cru no sandbox** | F5: é root do host. Anularia a fronteira inteira. Não é construído nem como opt-in. |
| D9 | **`podman-restart.service` no lugar de restauração customizada** | F4: unidade oficial, já ordenada após a rede. Substitui `restore-all`, a espera por rota/DNS, a unidade customizada e o código de saída 2. |
| D10 | **Manter TOML** | `tomllib` é stdlib desde Python 3.11 (decorre de D6). A estrutura já existe e funciona. |
| D11 | **Manter Podman rootless; Docker do host intocado** | Herdado do v1 e ainda válido: zero privilégio permanente no host. `podman-docker` continua proibido (sequestraria `/usr/bin/docker`). |

---

## 4. Topologia e ciclo de vida

### 4.1 Topologia

```
rede asb-<ws>  (--internal: sem rota default, sem DNS externo)
│
├─ asb-<ws>-agent      uid 1000 · -p 127.0.0.1::22 · NENHUM egresso
├─ asb-<ws>-proxy      interna + EXTERNA         → internet (allowlist do Squid)
├─ asb-<ws>-docker     interna + socket do broker → SEM rede externa   [opt-in]
├─ asb-<ws>-fwd        interna + gateway do host  → SEM internet       [opt-in]
└─ asb-<ws>-svc-<nome> interna apenas (postgres, redis, …)
```

O agente alcança tudo por **nome de container** (F2), estável através de
restart. `HTTPS_PROXY=http://asb-<ws>-proxy:3128`.

### 4.2 Ciclo de vida

O v1 tinha quatro caminhos com ordens diferentes. O v2 tem **um**.

| Operação | Implementação |
| :--- | :--- |
| `up` | cria rede, clona repo, monta staging, `podman run` de cada container |
| `suspend` | `podman stop` dos containers do workspace |
| `resume` | `podman start` dos containers do workspace |
| reboot | `podman-restart.service` (F4), sem código nosso |
| `down` | `podman rm -f` + `podman network rm`. **Não apaga `~/asb-agent/<proj>/<ws>/`** |
| `purge` | remove também o diretório do workspace, após confirmação |

Todos os containers recebem `--restart=unless-stopped`, que é o que a unidade
da F4 seleciona no boot.

**A ordem de partida deixou de ser um invariante de segurança.** Se o agente
subir antes do proxy, ele fica alguns segundos sem saída e depois funciona — não
existe janela em que ele tenha egresso indevido, porque o bloqueio é a própria
topologia (F1). Essa é a diferença essencial em relação ao v1, onde partir fora
de ordem produzia um sandbox sem isolamento nenhum.

### 4.3 Identidade do workspace

Derivada de `ORCA_VM_INSTANCE_ID`, sanitizada com `tr -c 'a-zA-Z0-9._-' '-'`.
Se ausente, deriva deterministicamente do caminho do repositório
(`<basename>-<sha256[0:8]>`), com o caminho normalizado antes (barra final
altera o hash). **Nunca de `$$`**: um nome irreprodutível impede o `destroy` de
encontrar o pod, e vaza recursos silenciosamente enquanto o Orca reporta
sucesso.

---

## 5. Sistema de arquivos

### 5.1 Layout

```
host                                          container
~/asb-agent/hexmed-stack/mvp-closure/    ←→   /home/v/asb-agent/hexmed-stack/mvp-closure/
   ├─ hexmed-stack/          clone com hardlinks — este é o projectRoot
   └─ hexmed-stack-<Nome>/   worktree irmã criada pelo Orca (F7), visível no host
```

`~/Data/Projects/<proj>` (o checkout primário, com o `.git` de origem) **nunca é
montado**. O agente enxerga apenas a própria worktree.

O clone é feito no host com `git clone <origem>` — para origem local o Git usa
hardlinks por padrão, então é rápido e barato em disco — e é **auto-contido**:
não depende de um `.git` externo não montado, que é exatamente o que quebraria
`git worktree` dentro do container.

### 5.2 O estado do workspace fica FORA da pasta montada

O `squid.conf` renderizado, o perfil normalizado e o caminho de origem vivem em
`~/.local/state/agent-sandbox/<ws>/` — **nunca** dentro de
`~/asb-agent/<proj>/<ws>/`, que é montado no container com escrita. Guardar a
allowlist dentro do mount permitiria ao agente **editar a própria allowlist** e
liberar os domínios que quisesse.

Também não em `/tmp`: é tmpfs, some no reboot, e um bind mount apontando para
caminho inexistente foi exatamente o que matou o Squid do v1 ao religar a
máquina.

`down` remove o diretório de estado; `purge` remove estado e workspace.

### 5.3 Como o trabalho retorna

O agente **não recebe credenciais de Git** (§9). O trabalho sai pelo host:

```
asb-agent pull <ws>     # git fetch de ~/asb-agent/… para o checkout primário
```

Sem merge automático. O operador testa e faz o push. Se precisar de ajuste, o
workspace continua vivo, o agente commita mais, e um novo `pull` traz a
diferença — o fluxo não quebra no meio, que é o que acontece hoje.

---

## 6. Acesso a Docker

Três eixos independentes em `.agent-sandbox.toml`, todos fechados por padrão.
O esquema completo do arquivo está no Anexo (§17).

### 6.1 `host_ports` — alcançar serviços do host

```toml
[docker]
host_ports = [5432, 6379]
```

Sobe `asb-<ws>-fwd`, um container com `socat` conectado à rede interna e ao
gateway do host, encaminhando **apenas as portas declaradas**. Sem internet.

**Nunca abrir faixas privadas.** O host participa de uma rede Tailscale
(`tailf4341c.ts.net` aparece no `search` do resolv.conf); liberar RFC1918 ou
CGNAT entregaria a tailnet inteira ao agente.

### 6.2 `mode = "nested"` — containers dentro do sandbox

```toml
[docker]
mode = "nested"        # "none" (padrão) | "nested"
```

O Podman já vem na imagem base; a flag apenas adiciona
`--device /dev/fuse --security-opt label=disable` ao container do agente (F6).
Nada é instalado da rede no `up` — mesma razão da §8. O agente constrói imagens e sobe stacks
completos com **zero exposição do host**.

Resolve o BlackICE integralmente: a dependência dele é ter *um* runtime de
containers, não *o do host* — ele constrói as próprias imagens
(`infra/compose.apps.yml` usa `build:`). Os pulls de imagem saem pelo Squid via
`HTTPS_PROXY`, então os registries usados precisam estar na allowlist.

### 6.3 `host_api = "read"` — socket filtrado, só leitura

```toml
[docker]
host_api = "read"      # "none" (padrão) | "read"
```

Necessário para o hexmed, que precisa ler logs de containers rodando **no host,
com dados reais** — algo que `nested` não pode oferecer.

F5 estabelece que nem o operador lê o socket sem `sudo`. A travessia honesta é
um broker root:

```
asb-agent install-broker      # requer sudo, uma vez
```

Instala uma unidade systemd **de sistema** rodando nginx como root, com o
socket real montado read-only, expondo `/run/asb-docker.sock` (uid 1000, 0600)
que aceita apenas:

```
GET /v*/version | /v*/events | /v*/containers/json
GET /v*/containers/<id>/json | /v*/containers/<id>/logs
tudo o mais → 403
```

É o mesmo mecanismo que o BlackICE já roda em produção
(`infra/traefik/docker-api-proxy/nginx.conf`), acrescido de `logs` e de um
`server` que reescreve o prefixo de versão da API para uma suportada pelo
daemon.

O sandbox monta esse socket **somente** no container `asb-<ws>-docker`, que não
tem rede externa (D3), e o agente fala com ele pela rede interna.

**O que isto concede, declarado sem eufemismo:** leitura de Docker sem senha
para o uid 1000. É um aumento de privilégio real, pequeno e só-leitura. Mutação
(`create`, `start`, `exec`, `build`, bind mounts) recebe 403 e não é
configurável.

### 6.4 O que não será construído

Montar o socket cru, ou permitir `exec`/`create` através do broker (D8).
`docker exec` num container root com bind mount do host **é** root do host; não
existe forma honesta de chamar isso de contenção. Quem precisar disso usa
`nested`, ou roda no host conscientemente.

---

## 7. Credenciais, configuração e integração dos agentes

### 7.1 Credenciais em volume

Volume nomeado `asb-credentials`, compartilhado entre workspaces, montado
apenas nos caminhos de credencial:

| Agente | Caminho | Proteção |
| :--- | :--- | :--- |
| Claude Code | `~/.claude/.credentials.json` | texto claro no volume |
| Codex | `~/.codex/auth.json` | texto claro no volume |
| Antigravity | keyring do Secret Service | cifrado; passphrase só no host |

```
asb-agent login        # uma vez, não por workspace
```

Sobe um container **fora** da rede interna (login por device-auth precisa de
egresso direto) com o volume montado, executa os três logins, verifica por
**código de saída** e sai. Sem `podman commit`, sem imagem derivada, sem
`-prev3`.

`asb-agent down` e `purge` **nunca** removem `asb-credentials`.

Detalhes que já custaram uma rodada de depuração cada, preservados do v1:

- `bash -lc` é obrigatório: sem shell de login, `agy` não está no `PATH` e
  `DBUS_SESSION_BUS_ADDRESS` está ausente — é exatamente assim que a credencial
  vai parar em arquivo texto em vez do keyring.
- `agy` não tem subcomando `login`; o binário nu abre a TUI, que autentica no
  primeiro uso.
- Sempre device-auth: o OAuth padrão abre um servidor de callback numa porta do
  container que o navegador do host não alcança, e trava.
- Verificar por código de saída, **nunca** por `grep 'logged in'` — a string
  casa também com "**not** logged in" e comitaria uma sessão inautenticada.
- O keyring exige que o entrypoint real rode (D-Bus, desbloqueio); com
  `--entrypoint sleep` o `agy` cai no fallback de texto claro em silêncio.

### 7.2 Configuração por staging montado

O v1 copiava com `podman cp`, exigindo um instalador root no container
(`install-config.py`), um token de provisionamento por partida e um portão no
sshd para fechar a corrida de TOCTOU e a reconexão do Orca.

O v2 monta. O CLI constrói um diretório de staging no host a partir de
`profiles/provision.toml` e o **bind-monta read-only** nos caminhos de destino.
Isso apaga `install-config.py`, o token e o portão do sshd.

O staging vive em `~/.local/state/agent-sandbox/<ws>/staging/`, **fora** da
pasta montada com escrita, e o mount é `:ro`. Pela mesma razão da §5.2: se o
agente alcançasse a origem do staging, reescreveria os próprios hooks e a
configuração de MCP para a partida seguinte.

Preservado do v1 porque é genuinamente necessário:

- A allowlist é **explícita**. `~/.claude` contém `.credentials.json` e
  `~/.codex` contém `auth.json`; declarar o diretório inteiro entregaria a
  credencial do host ao sandbox.
- Symlinks são materializados no staging, mas só quando o alvo resolvido
  permanece dentro da árvore declarada, de `~/.agents/skills` ou do diretório
  de skills do sistema Omarchy. Qualquer outro alvo externo é **recusado**, não
  seguido.

**Filtros: dois morrem, dois permanecem.**

| Filtro | Destino | Motivo |
| :--- | :--- | :--- |
| `antigravity-hooks` | **removido** | Existia para reescrever o home do host; com D4 o caminho é idêntico. |
| reescrita de hooks no `asb-agy` | **removido** | Mesma razão. |
| `claude-settings` | **mantido** | `hooks` e `statusLine` apontam para *binários* do host que não existem no container. Com caminho idêntico o path passa a resolver para um local plausível e vazio: falha silenciosa em vez de erro visível. Pior, não melhor. |
| `codex-config` | **mantido** | `projects.*` é indexado pelo caminho do workspace, que difere do host de qualquer forma. |

### 7.3 Integração dos três agentes

Claude, Codex e Antigravity usam a **mesma** trilha: mesmo volume de
credenciais, mesmo staging, mesmo `asb-agent login`, mesmo guarda. Não há
caminho especial para nenhum deles. Isso fecha o problema #6.

O guarda (`cli/asb-agent`, instalado como `asb-claude`, `asb-codex`, `asb-agy`)
é preservado sem mudança de comportamento, incluindo a supressão da dica de
bypass quando o lançamento é automático — um agente em modo autônomo trata
"chame este caminho" como instrução, e a mensagem entregaria o próprio bypass.
Ele continua **não sendo fronteira de segurança**: endereça execução
acidental fora do sandbox.

---

## 8. Ferramentas de desenvolvimento

A fonte da verdade é o **`mise.toml` do próprio projeto** (o hexmed já tem um).
Um volume nomeado `asb-toolcache`, compartilhado entre workspaces, guarda
`~/.local/share/mise` e `~/.cache`. O `uv` é instalado uma vez e permanece
disponível em todos os workspaces, sem rebuild de imagem.

```toml
[tools]
extra = ["uv", "go@1.23"]     # escape hatch, só para o que o projeto não declara
```

Esquema completo no Anexo (§17).

**Por que não instalar da rede a cada `up`:** seria lento em uma ferramenta de
uso diário e acrescentaria um modo de falha novo (cada ferramenta nova exige um
domínio novo na allowlist, e a falha aparece como "o sandbox não sobe"). O
cache compartilhado paga o custo uma vez só.

---

## 9. Fronteiras de segurança

### 9.1 Invariantes inegociáveis

1. O `$HOME` do host nunca é montado em container algum.
2. Nenhuma chave SSH, credencial Git, PAT ou token do `gh` do host entra no
   sandbox.
3. `/var/run/docker.sock` nunca é montado cru no sandbox (D8).
4. O container do agente nunca tem rede externa, `CAP_NET_ADMIN` ou `sudo`.
5. `~/Data/Projects` nunca é montado; só a worktree do workspace.

### 9.2 O que isto não protege

- **Exfiltração para um domínio permitido.** Se `github.com` está na
  allowlist, um gist é uma saída. Nenhuma allowlist de rede resolve isso.
- **`host_api = "read"`** concede leitura de Docker sem senha ao uid 1000 (§6.3).
- **`mode = "nested"`** dá ao agente um runtime de containers completo
  dentro da própria fronteira; ele não escapa dela, mas consome recursos do
  host.
- O guarda `asb-*` não é contenção (§7.3).

### 9.3 DNS

O container do agente **não tem DNS externo** (F1). A resolução acontece no
Squid, o que fecha o tunelamento de DNS como canal de exfiltração e, de quebra,
elimina o problema de dual-stack: a allowlist por IP tentada no v1 deixava
`api.anthropic.com` expirar porque o cliente preferia o registro AAAA.

---

## 10. Documentação

O v1 tem oito documentos escritos como registro de escavação: cada um explica
por que um bug específico aconteceu, e nenhum explica o sistema. O operador não
consegue manter o que não consegue ler.

```
docs/domains/sandbox/
├── README.md          o sistema em uma página: topologia, containers, comandos
├── configuration.md   referência completa de .agent-sandbox.toml
├── security.md        fronteiras, o que protege e o que não protege
└── failure-modes.md   o registro forense, consolidado em um arquivo só
```

`README.md` é o documento de entrada e responde, sem depender dos outros: o que
cada container faz, o que cada comando faz, onde ficam os arquivos, e o que
fazer quando algo não sobe.

---

## 11. Superfície do CLI

`cli/asb-agent` (com symlink `asb`), Python 3, arquivo único, stdlib apenas.

```
asb-agent up       --workspace <id> --repo <caminho>
asb-agent down     --workspace <id>
asb-agent purge    --workspace <id>
asb-agent suspend  --workspace <id>
asb-agent resume   --workspace <id>
asb-agent pull     --workspace <id>
asb-agent login
asb-agent build
asb-agent doctor
asb-agent install-guards
asb-agent install-broker      # requer sudo
asb-agent list
```

`up` e `resume` emitem uma linha JSON de conexão em stdout; todo o resto vai
para stderr. O contrato do recipe do Orca (`schemaVersion`, `connection.target`,
`projectRoot`) é preservado sem mudança, incluindo a reemissão completa no
`resume`.

Os quatro hooks do Orca (`create`, `destroy`, `suspend`, `resume`) continuam
obrigatórios e continuam derivando a identidade do workspace de um único lugar
compartilhado (§4.3).

---

## 12. Testes

A suíte atual é preservada em espírito e reescrita para a topologia nova. Dois
padrões são obrigatórios porque a ausência deles já deixou falhas passarem:

1. **Controle positivo em toda asserção negativa.** "X está bloqueado" passa de
   graça quando o container nunca subiu: o comando falha e o teste conclui
   "bloqueado". O `require` do `assert.sh` aborta a suíte quando o ambiente não
   responde. O mesmo vale ao interpretar saída: `dig +short` escreve erros em
   **stdout**, então casar "qualquer saída" reporta um vazamento de DNS que não
   existe. Casar o formato de uma resposta real, não a presença de texto.
2. **Asserção do permission mode efetivo do Claude.** Foi a ausência dela que
   permitiu ao `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` forçar o modo `default` e
   anular o `--dangerously-skip-permissions` do Orca — o sandbox existe para
   viabilizar autonomia com segurança, e uma flag de endurecimento a desligava
   em silêncio.

Cobertura mínima: isolamento de rede (incluindo **após restart**, que é o teste
que o v1 não tinha), estabilidade da porta SSH, ausência de DNS no agente,
CONNECT através do Squid, permanência do volume de credenciais após `down`,
visibilidade da worktree no host, filtro do broker recusando mutação, e o
permission mode efetivo dos três agentes.

---

## 13. O que é removido

| Removido | Substituto |
| :--- | :--- |
| Pod do Podman | rede nomeada (D2) |
| `image/Containerfile.net`, `image/firewall/apply.sh`, nftables | `--internal` (F1) |
| Init container, `CAP_NET_ADMIN`, `--user 1000` para `nft` | — |
| `resume` ordenado, prova de firewall, `asb_wait_for_proxy` | `podman start` |
| `restore-all`, `asb_wait_for_host_network`, unidade systemd, código de saída 2 | `podman-restart.service` (F4, D9) |
| Sonda fail-closed de egresso no entrypoint | topologia (F1) |
| Token de provisionamento e portão do sshd | staging montado (§7.2) |
| `image/install-config.py` | staging montado (§7.2) |
| Imagem `agent-sandbox-auth` e derivadas `-prev*` | volume `asb-credentials` (D5) |
| Reescrita de caminho de hooks no `asb-agy` | caminho idêntico (D4) |
| `~/.config/agent-sandbox/pods/<pod>/` | `~/.local/state/agent-sandbox/<ws>/` (§5.2) |

`cli/lib/render_squid.py` é preservado: a normalização de domínios que ele faz
não é opcional. Declarar `.github.com` e `github.com` no mesmo ACL `dstdomain`
é erro fatal de configuração do Squid.

---

## 14. Riscos

| Risco | Mitigação |
| :--- | :--- |
| Reescrita troca bugs conhecidos por bugs novos | A suíte de testes já codifica as armadilhas do v1 e é preservada (§12); §15 lista o que não pode voltar. |
| `nested` puxa imagens pelo Squid e falha por domínio ausente | Registries usados entram na allowlist base; a falha nomeia o domínio recusado. |
| O broker root amplia privilégio do uid 1000 | Só-leitura, sem mutação configurável, e declarado explicitamente (§6.3, §9.2). |
| Perda dos logins existentes na transição | Decisão do operador: login único é aceitável. Não haverá extração da imagem antiga. |
| Mover o checkout do `agent-sandbox` quebra caminhos instalados | `doctor` verifica e aponta; `install-guards` e `install-broker` são reexecutáveis. |
| Agente sobe antes do proxy no boot e cacheia o IP dele | F2 mostra que o IP do proxy **muda** entre partidas, e `podman-restart.service` não ordena nada. Se um processo longo resolver `asb-<ws>-proxy` uma vez e guardar o IP, o sintoma é "internet quebrada após reboot" — idêntico ao bug do v1 que estamos eliminando. Teste obrigatório: subir o agente **antes** do proxy e verificar que o CONNECT funciona depois. Se não funcionar, fixar o IP do proxy na rede (`--ip`). |

---

## 15. Modos de falha que não podem voltar

Cada item abaixo foi uma falha real no v1. Estão aqui para que o plano de
implementação os trate como requisitos, não como curiosidades.

1. **`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` nunca é definida na imagem.** Ela
   protegia subprocessos *no host*; dentro do container não protege nada e o
   Claude Code responde a ela forçando o permission mode para `default`.
2. **Nunca colocar comentário no meio de um comando com continuação de linha.**
   O `#` encerra a linha lógica junto com a barra invertida e os argumentos
   seguintes viram órfãos. `bash -n` aceita: a suíte fica verde e a falha só
   aparece em runtime.
3. **Nome de workspace sempre determinístico** (§4.3).
4. **Verificação de login por código de saída, nunca por `grep`** (§7.1).
5. **Asserção negativa sempre pareada com controle positivo** (§12).
6. **Squid: nunca declarar domínio pai e filho no mesmo ACL** (§13).
7. **Antigravity precisa de `.googleusercontent.com`** na allowlist: a
   verificação de elegibilidade busca a foto de perfil do usuário e, sem o
   domínio, `agy` aborta com `Forbidden` **mesmo autenticado**.
8. **`agy` trata sessão SSH como novo login remoto** e ignora a credencial em
   cache. O guarda `asb-agy` limpa `SSH_CONNECTION`, `SSH_CLIENT` e `SSH_TTY`
   antes do `exec`, escopado só ao `agy`.
9. **Variáveis de ambiente não chegam via SSH sozinhas.** O OpenSSH descarta o
   ambiente do processo pai; o entrypoint escreve em `/etc/environment` (lido
   pelo PAM) *e* em `/etc/profile.d/` (lido por shells de login), porque
   `ssh host 'cmd'` não é shell de login.
10. **O recipe só aparece no seletor do Orca** com **Settings → Experimental →
    "Cloud VM"** ligado, e com o `orca.yaml` commitado na branch primária do
    projeto.

---

## 16. Portabilidade e reinstalação

**Requisito:** reinstalar o sistema operacional, ou levar este repositório para
outra máquina Linux, não pode exigir edição manual de arquivo algum. Tudo que o
sandbox instala no host é **gerado por um comando reexecutável**.

No v1 isso não valia: o `ExecStart` da unidade systemd tinha o caminho absoluto
do checkout assado no momento da instalação, então **mover ou renomear a pasta
`agent-sandbox` quebrava a restauração no boot em silêncio**. Esse modo de falha
não pode existir no v2.

### 16.1 Regras

1. Nenhum caminho absoluto do checkout é gravado em arquivo de sistema. O que
   depende do local do repositório é resolvido em tempo de execução, a partir do
   próprio script.
2. Todo instalador é idempotente e reexecutável: `install-guards`,
   `install-broker` e a habilitação do `podman-restart.service`.
3. `asb-agent doctor` detecta host novo, checkout movido e dependência ausente,
   e **nomeia o comando exato** a executar. Nunca "algo está errado".

### 16.2 Dependências, e o que acontece sem cada uma

| Dependência | Por quê | Sem ela |
| :--- | :--- | :--- |
| Podman ≥ 4.0 | rede `--internal` com netavark e resolução por nome via aardvark-dns (F1, F2) | não funciona; `doctor` recusa na hora |
| systemd (sessão de usuário) | `podman-restart.service` para o reboot (F4) | workspaces não voltam sozinhos; `asb-agent resume` manual funciona |
| Python ≥ 3.11 | `tomllib` na stdlib (D6) | não funciona |
| git | clone e worktrees (§5) | não funciona |
| Docker no host | **apenas** o eixo `host_api` (§6.3) | os outros dois eixos e todo o resto seguem normais |

Nada disso é específico do Arch ou do Omarchy. A única suposição de
distribuição é o caminho do socket do Docker, que o `install-broker` detecta em
vez de assumir.

### 16.3 Máquina nova, do zero

```
git clone <este-repo> && cd agent-sandbox
asb-agent doctor              # diz o que falta
asb-agent build               # constrói a imagem base
asb-agent login               # os três logins, uma vez
asb-agent install-guards
asb-agent install-broker      # opcional, só para o eixo host_api
```

Credenciais **não** atravessam máquinas: o keyring do Antigravity é cifrado com
uma passphrase que vive só no host de origem, por projeto (§7.1). Em máquina
nova, `login` de novo. Isso é intencional — uma cópia do volume levada para
outra máquina é inútil sem a passphrase.

---

## 17. Anexo — esquema completo de `.agent-sandbox.toml`

Todo campo é opcional. Ausente significa o padrão, e o padrão é sempre o
fechado. Um arquivo ausente equivale a um arquivo vazio: sandbox isolado, sem
acesso a Docker, sem portas do host.

```toml
[network]
# Domínios adicionais liberados no Squid, somados à allowlist base.
# Prefixo "." casa o domínio e todos os subdomínios.
allow = ["pypi.org", "files.pythonhosted.org", ".sentry.io"]

[docker]
# Portas de serviços do HOST alcançáveis pelo agente (§6.1).
# Apenas as declaradas. Nunca faixas.
host_ports = [5432, 6379]

# Runtime de containers DENTRO do sandbox (§6.2).
#   "none"   (padrão) — sem containers aninhados
#   "nested"          — Podman rootless dentro do sandbox
mode = "nested"

# Acesso à API do Docker do HOST, via broker filtrado (§6.3).
#   "none" (padrão) — nenhum acesso
#   "read"          — version, events, ps, inspect, logs. Mutação → 403.
# Exige `asb-agent install-broker` executado uma vez com sudo.
host_api = "read"

[tools]
# Escape hatch. A fonte da verdade é o mise.toml DO PROJETO (§8);
# use isto apenas para o que o projeto não declara.
extra = ["uv", "go@1.23"]

[services]
# Serviços descartáveis, criados no `up` e destruídos no `down`.
# Alcançados pelo agente em asb-<ws>-svc-<nome>, pela rede interna.
[services.db]
image = "docker.io/library/postgres:17"
env = { POSTGRES_USER = "sandbox", POSTGRES_PASSWORD = "sandbox", POSTGRES_DB = "sandbox" }
```

### Nota sobre containers de serviço

Imagens sem diretiva `USER` (como `postgres`) precisam de `--user 0`. Sob
`keep-id` elas seriam resolvidas para o uid mapeado do host, e o `initdb` falha
ao ajustar permissões dos diretórios da própria imagem com `Operation not
permitted`. Isso vale mesmo sem pod, porque o mapeamento de usuário permanece.

### O que saiu do esquema do v1

`[sandbox] mode = "isolated" | "attached"` deixa de existir. O modo "anexado" era
uma chave global que ligava encaminhadores para o host; virou o eixo
`docker.host_ports`, que é explícito sobre **quais** portas e não implica mais
nada. `[proxy] java` também sai: era um ajuste pontual que nunca foi exercitado.
