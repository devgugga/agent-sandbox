# Correções pós-verificação — agent-sandbox v2, BlackICE e hexmed-stack

> Data: 2026-09-05. Origem: verificação empírica da implementação do Gemini
> (workspaces reais `vfy-bi` e `vfy-hex`, criados, testados e destruídos).
> Executor: Gemini, exceto onde marcado **[HUMANO]**.

---

## Estado (atualizado 2026-09-05, após a entrega do Gemini)

| Tarefa | Estado |
| :--- | :--- |
| T1, T2, T3, T5, T6, T7 | **concluídas e verificadas empiricamente** (hexmed real: 5 diretórios do mise instalados, `pacs/server` responde `Python 3.8.20`; `test-toolcache.sh` 19/19; 103 testes unitários) |
| T4.2 | **concluída** — `host_ports` reduzido a 80, 5432, 6379, 8080; 389 e 8843 confirmados fechados |
| T4.1 | **[HUMANO] pendente**, porém **menos urgente do que registrado**: `deploy.bk/dcm4chee/.env` não está versionado e está no `.gitignore`, então o agente não recebe a senha do banco pela worktree. É pré-requisito para ligar T4.3, não um buraco aberto hoje |
| T4.3 | corretamente **não habilitado** |
| **T8** | **concluída e verificada empiricamente** — `doctor` sonda egresso real (DNS e TCP) em cada workspace ativo com controles positivo e negativo; recuperação (`podman unshare --rootless-netns true`) documentada em `failure-modes.md` |
| **T9** | **concluída** — pré-requisito `mvn package` do `Dockerfile.jvm` e fluxo híbrido documentados em `BlackICE/infra/README.md` |
| **T10** | **T10.1 [HUMANO] pendente** (exercitar reboot real com workspace ativo); **T10.2 concluída** (implicações de `Linger=no` documentadas em `failure-modes.md` e `README.md`) |
| **T11** | **concluída e verificada empiricamente** — `test_broker.py` hermético com mock de `/run/asb-docker/docker.sock` e `project_root` como `Path` real; 16/16 testes passam independente de broker no host |
| **T12** | **concluída** — `asb-agent login` executa no `$HOME` (`-w`) com aviso prévio de safety check do Claude; login intra-workspace documentado como via recomendada em `README.md` |
| **T13** | **concluída e verificada empiricamente** — `asb-agent reload-allowlist --workspace <ws>` implementado, recarrega squid e reinicia proxy sem tocar no agente nem mudar porta SSH (7/7 no `test-reload-allowlist.sh`) |
| **T14** | **investigada e pronta para decisão** — causa raiz das 777 tentativas ao `dcm4che.org` identificada no `apps/backend/pom.xml` (repositório Maven Maven2); inventário pronto para decisão humana |

Sobre T1, o Gemini escolheu a **Opção A (preservar o workspace)**, que era a
recomendada. Verificado: `up` sai 1, não emite o JSON da receita e mantém os
containers no ar.

---

## O que já está verificado e NÃO deve ser mexido

| Item | Evidência |
| :--- | :--- |
| Perfis v2 dos dois projetos carregam | `load_profile` OK em ambos |
| Cadeia de 3 saltos do BlackICE | `curl 127.0.0.1:18080` → **200** (host → netns do agente :80 → rootlessport aninhado → nginx) |
| `--sysctl net.ipv4.ip_unprivileged_port_start=0` | container aninhado liga em :80 sem privilégio |
| `host_ports` do hexmed | 80, 389, 5432, 6379, 8080, 8843 todas alcançáveis de dentro |
| Isolamento preservado com `publish_ports` | egresso direto `000`, domínio negado `000`, permitido `200` |
| Python 3.8 | instala **pré-compilado**; não compila do zero, não precisa de `www.python.org` nem de libs de build |
| `.apache.org` + `repo.maven.apache.org` | `normalize_domains` colapsa; sem FATAL do Squid |
| Base | 98 testes unitários OK, `doctor` sai 0, volume `asb-toolcache` montado, `orca.yaml` + 4 shims OK |

---

## Ordem de execução

**T1 antes de T2 e T3.** Sem T1, as falhas de T2/T3 voltam a passar despercebidas.

---

## T1 — `up` dá verde mesmo quando o `mise install` falha

**Problema.** `cli/asb/lifecycle.py:318-330` chama `podman.run(..., check=False)`,
imprime `aviso:` e continua o laço. O `up` sai **0** ainda que nenhuma toolchain
tenha instalado. O código de saída está desacoplado do que se afirma — mesma
classe do assert de SSH que já foi corrigido antes.

**Efeito.** Foi isto que escondeu T2 e T3 na entrega anterior.

**Correção.** Acumular as falhas do laço. Se houver qualquer uma:

1. imprimir o `stderr` de cada falha (já é feito hoje);
2. **não** emitir o JSON do contrato da receita;
3. sair com código diferente de zero.

### Decisão pendente [HUMANO]: destruir ou preservar o workspace

Este é o único item da lista cuja correção não é mecânica. Não implementar
antes de decidir, porque a escolha entra no critério do teste.

**Opção A — preservar (recomendada).** Sai ≠ 0, imprime os diretórios que
falharam e orienta: *"workspace no ar, toolchains faltando; corrija a allowlist
e rode `asb-agent up` de novo"*. O laço do mise é idempotente, então o próprio
`up` é o caminho de retry.

**Opção B — rollback.** Aciona `_sweep_containers` por
`--label asb.workspace={ws}`, como nos demais erros do `up`. Fica consistente
com o resto do comando.

O argumento a favor de A: quando o `up` chega no laço do mise, já criou rede,
proxy, fwd, container do agente e a worktree irmã do Orca. Derrubar tudo isso
porque faltou um domínio na allowlist faz o operador pagar a construção inteira
de novo para corrigir uma linha de TOML. O `asb-toolcache` barateia o download,
não a reconstrução do workspace. E no caminho do Orca, sair ≠ 0 sem JSON no
stdout deixa um ambiente ao qual ele não consegue se conectar.

**Verificação.** Teste de integração com um `mise.toml` apontando para um
domínio fora da allowlist: o `up` precisa sair ≠ 0. O que se afirma sobre
containers e diretório depende da opção escolhida acima. Controle positivo
obrigatório: o mesmo teste com toolchain válida precisa sair 0.

---

## T2 — `mise.toml` na raiz anula os subprojetos

**Problema.** `cli/asb/lifecycle.py:309-316`:

```python
mise_dirs = []
if (layout.project_root / "mise.toml").exists():
    mise_dirs.append(layout.project_root)
else:                                    # ← ou-exclusivo
    for p in layout.project_root.glob("*/mise.toml"):
        mise_dirs.append(p.parent)
    for p in layout.project_root.glob("*/*/mise.toml"):
        mise_dirs.append(p.parent)
```

O hexmed passou a ter `mise.toml` na raiz, então o `up` rodou **só nela**:

```
info executando mise install em hexmed-stack...
ok   ferramentas mise instaladas (hexmed-stack)      ← só isto, mais nada
```

`portal/back`, `portal/front`, `pacs/client` e `pacs/server` **nunca receberam
`mise install`**. Na verificação isso não apareceu porque o `asb-toolcache` já
tinha java/node de execuções anteriores; num cache limpo os quatro
subprojetos ficam sem toolchain.

**Erro conceitual.** O `mise` é hierárquico para *resolver* versões, mas
`mise install` só instala o que está em escopo a partir do diretório corrente.
Raiz e subprojetos não são alternativas — são todos necessários.

**Correção.** Instalar em **todos** os diretórios com `mise.toml`, raiz
inclusive. Trocar o `if/else` por uma varredura única, com poda dos diretórios
que nunca contêm toolchain de projeto:

- podar: `.git`, `node_modules`, `target`, `dist`, `build`, `.venv`
- ordem estável (raiz primeiro) apenas para o log ficar legível — **não** há
  aquecimento de cache entre diretórios: `mise install` na raiz instala só o
  que está no escopo da raiz. Cada diretório é independente, inclusive quanto
  ao trust (é o `mise install -y` naquele diretório que confia naquele config).

Preferir `rglob` com poda a mais um nível de `glob` fixo: hoje a profundidade
para em 2 e o próximo projeto pode ter `apps/x/y/mise.toml`.

**Verificação.** Teste de integração com um projeto de fixture contendo
`mise.toml` na raiz **e** em `a/` e `a/b/` — os três precisam aparecer no log e
as três ferramentas precisam resolver dentro do container.

---

## T3 — `pacs/server/mise.toml` quebra o diretório inteiro

**Arquivo.** `hexmed-stack/pacs/server/mise.toml`

```toml
[settings]
python.github_attestations = false     # ← remover o bloco inteiro
```

**Dois problemas independentes.**

1. **A opção não existe.**
   `mise settings get python.github_attestations` →
   `mise ERROR Setting [python.github_attestations] is not set`.
   Os nomes reais são `github_attestations`, `aqua.github_attestations` e
   `github.github_attestations`. A linha nunca teve efeito.

2. **A presença de `[settings]` torna o arquivo não-confiável**, e o `mise`
   falha *hard* em tudo naquele diretório:

   ```
   mise ERROR Config files in .../pacs/server/mise.toml are not trusted.
   python: mise ERROR ...    uv: mise ERROR ...
   ```

   Os irmãos (`portal/back`, `portal/front`, `pacs/client`) têm só `[tools]` e
   funcionam sem trust explícito — o contraste isola a causa.

**Correção.** Apagar o bloco `[settings]`. O arquivo fica:

```toml
[tools]
python = "3.8"
uv = "latest"
```

**Atenção:** a prova abaixo foi feita numa cópia dentro do workspace
descartável `vfy-hex`, que já foi purgado. **O arquivo do repositório continua
com o bloco inválido** — conferir e corrigir, não pular a tarefa por não achar
o problema.

**Verificação (já executada, reproduzir no teste).** Com o bloco removido,
`python --version` no diretório responde `Python 3.8.20`. O Python 3.8 instala
pré-compilado; a `[settings]` não era necessária para nada.

---

## T4 — Endurecer o acesso do hexmed ao host

Contexto: `deploy.bk/dcm4chee/docker-compose.yml` monta caminhos absolutos do
host em **read-write**, e os containers rodam como root (`sudo docker`):

| Serviço | Bind mount | Porta |
| :--- | :--- | :--- |
| `db` (postgres) | `/var/local/dcm4chee-arc/db` | 5432 |
| `ldap` | `/var/local/dcm4chee-arc/{ldap,slapd.d}` | 389 |
| `keycloak` | `/var/local/dcm4chee-arc/keycloak` | 8843 |
| `arc` | `/var/local/dcm4chee-arc/wildfly`, `/storage` | 8080 |

(Os do `nginx-dev` são todos `:ro`; esses não entram na análise.)

O bind mount sozinho não abre canal — o agente só tem TCP. O que ele define é
**até onde chega** um abuso da porta. Como os serviços usam `env_file: .env` e o
Docker materializa essas variáveis na config do container, existe esta cadeia:

```
host_api="read" → GET /containers/{id}/json → senha do .env
                → conecta em 5432 como superusuário
                → COPY ... TO PROGRAM
                → escreve em /var/local/dcm4chee-arc/db como root no host
```

Nenhum elo é furado sozinho; juntos saem do sandbox.

> **Dependência.** T4.3 não pode ser habilitado antes de T4.1 estar no ar.
> T4.1 é o elo que quebra a cadeia e não é tarefa do Gemini — concluir T1–T3 e
> T5–T7 e reportar pronto **não** muda a postura de segurança aqui.

### T4.1 [HUMANO] — conta de banco sem superusuário

A mitigação de maior valor e custo zero. Corta a cadeia no meio: sem
`pg_execute_server_program`, o `COPY TO PROGRAM` é negado mesmo que o agente
descubra a senha do `postgres`.

```sql
CREATE ROLE agente LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE pacsdb TO agente;
GRANT USAGE ON SCHEMA public TO agente;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agente;
```

Requer admin do banco — não é tarefa do Gemini.

### T4.2 — enxugar `host_ports`

Rever se o agente precisa falar **direto** com `389` (LDAP) e `8843`
(Keycloak). Quem conversa com eles é a aplicação, não o agente. Se for só para
debug, remover as duas reduz superfície sem custo. Confirmar com o humano antes
de editar.

### T4.3 [HUMANO] — instalar o broker, se quiser leitura de logs

Opcional e desacoplado: sem ele o hexmed sobe e enxerga o banco normalmente.

```bash
sudo asb-agent install-broker
# depois descomentar em hexmed-stack/.agent-sandbox.toml:
#   host_api = "read"
```

O broker só deixa passar **GET** em oito rotas (`/version`, `/info`, `/events`,
`/containers/json`, `/containers/{id}/{json,logs,stats,top}`); qualquer mutação
recebe 403 e não chega no socket. Fica tranquilo **depois** de T4.1 — aí o
`inspect` vira leitura de configuração, não chave para o disco.

---

## T5 — Documentação do sandbox

`docs/domains/sandbox/configuration.md` já cobre `publish_ports`. Faltam:

- o volume `asb-toolcache`: o que guarda (`mise`, `.cache`, `.m2`, `uv`), que é
  compartilhado entre workspaces e que é ele que torna o rollback de T1 barato;
- o ciclo do `mise install` no `up`: **quais** diretórios são varridos (depois
  de T2) e que o primeiro `up` de um projeto, com cache frio, paga o download
  de todas as toolchains — é a diferença entre segundos e vários minutos, e o
  operador precisa saber disso antes de achar que travou;
- em `failure-modes.md`: `mise install` falhando por domínio fora da allowlist
  é o modo de falha esperado, e o sintoma (depois de T1) passa a ser `up` ≠ 0
  com o `stderr` do mise.

---

## T6 — Limpeza

Resíduo das sondagens manuais da entrega anterior. Nada tem
`restart=always`, então não volta no boot; é higiene, não risco.

- 8 containers de `agent-sandbox-base:latest` parados há horas (`capsh --print`,
  `which mise`, …). Ficam "Up" porque o entrypoint segura o `sshd` em primeiro
  plano mesmo depois de o comando de sondagem terminar.
- ~22 volumes anônimos
- ~20 diretórios `tmp.*` em `~/asb-agent`, mais `probe/`, `proj/`, `repo/` e
  `BlackICE/blackice-dryrun`
- imagens antigas: `agent-sandbox-auth-prev{,2,3}`, `-old`, `-base`, `-net`

Confirmar com o humano antes de apagar — pode haver algo em investigação.

---

## T7 — Menores

- `hexmed-stack/.agent-sandbox.toml`: `repo.maven.apache.org` é redundante sob
  `.apache.org` (o `normalize_domains` já colapsa). Remover é cosmético.
- Primeiro `up` emite `[WARN] migrate: failed create_dir_all:
  ~/.local/share/mise/migrations` — efeito do symlink do toolcache. Inofensivo,
  mas polui a saída; vale criar o diretório no `entrypoint.sh`.

---

## T8 — Perda de egresso do podman rootless passa despercebida

**Incidente observado (2026-09-05).** Um `podman pull` dentro do sandbox travou:
blobs pequenos concluíam, o de 107 MiB parava em 16 KiB e o pull reiniciava em
laço. A causa **não** era a allowlist, nem MTU, nem política do Squid.

O `pasta` — processo que dá uplink ao namespace de rede rootless compartilhado
do podman — parou de servir tráfego. Cascata:

```
pasta para
 └─ aardvark-dns: "dns request failed: io error: Network is unreachable (os error 101)"
     └─ squid nao resolve:            NONE_NONE/500 ... HIER_NONE/-
         └─ e nas conexoes ja abertas: NONE_NONE/503 apos 66s, 119s, 135s
             └─ podman: blobs pequenos "done", o grande trava e reinicia
```

Diagnóstico de dentro do proxy, com a rota default **correta**:

```
default via 10.89.3.1 dev eth1     ← rota ok
dig @10.89.2.1  → timed out
dig @10.89.3.1  → no servers could be reached
TCP 1.1.1.1:443 → Network is unreachable
```

**Linha do tempo.** Último túnel bem-sucedido 13:12:03 (blobs de 28 MB, 8 MB e
4,5 MB passaram normalmente); `rootless-netns-a4542060.scope` termina 13:12:04;
falhas de 13:13:12 a 13:14:30; um túnel às 13:27 levou **895 segundos**. O
podman só percebeu às 13:36, quando um comando forçou a verificação.

**Causa do desligamento do `pasta`: desconhecida.** Duas candidatas não
discriminadas — contabilidade de lifecycle do podman perturbada por um `purge`
15 min antes, ou evento de rede do host (a máquina roda Tailscale). O
experimento que separa as duas (subir dois workspaces, derrubar um, observar o
outro) **não deve ser executado enquanto houver workspace em uso**: o modo de
falha dele é cortar a sessão ativa.

### T8.1 — `doctor` precisa provar egresso, não inferir

Hoje o `doctor` valida imagem, volumes, guardas e `podman-restart.service`.
Nenhuma dessas checagens teria pego este incidente: **tudo continuava
"presente" enquanto nada saía**.

Acrescentar, para cada workspace em execução, uma asserção que **saia de dentro
do proxy até um destino real** — resolução DNS mais conexão TCP, com timeout
curto (5s) para não travar o `doctor`. O diagnóstico precisa distinguir três
estados, porque hoje os três produzem o mesmo sintoma para o operador:

1. egresso ok;
2. **uplink rootless morto** (rota presente, `Network is unreachable`) → apontar
   a recuperação do T8.2;
3. domínio fora da allowlist (`TCP_DENIED`/`NONE_NONE` com rota viva) → apontar
   o `[network] allow` do projeto.

Controle positivo obrigatório no teste: com egresso saudável a asserção passa;
o teste tem de falhar de verdade quando o egresso cai — não vale asserção que
só verifica se o container existe.

### T8.2 — documentar a recuperação

Uma linha resolve, e sem ela o sintoma é indistinguível de "o sandbox
bloqueou":

```bash
podman unshare --rootless-netns true
```

Os containers em execução **recuperam o egresso sem reiniciar** — verificado no
incidente. Documentar em `docs/domains/sandbox/failure-modes.md` junto com a
assinatura do problema (`Network is unreachable` vindo do aardvark-dns, blobs
grandes travando, `NONE_NONE/503` no log do Squid).

---

## T9 — Documentação de build do BlackICE

> Acrescentada por iniciativa própria a partir de um erro real de uso; se não
> fizer sentido, corte.

O `README` documenta o fluxo **aninhado** (`podman compose` dentro do sandbox).
Mas há um segundo fluxo legítimo, de fato usado, que não está escrito em lugar
nenhum: **build do Maven dentro do sandbox, `sudo docker compose` no host** —
possível porque a worktree fica no mesmo caminho absoluto dos dois lados.

Falta também o pré-requisito que quebra esse fluxo na prática: o
`apps/backend/src/main/docker/Dockerfile.jvm` é o Dockerfile de **modo JVM** do
Quarkus e não compila Java — ele só copia `target/quarkus-app/`, que é produzido
por `mvn package`. Sem esse passo o `docker compose --build` falha com
`"/target/quarkus-app/quarkus": not found`, e o erro não sugere a causa.

Documentar a ordem: `mvn package` (dentro do sandbox, onde a toolchain já
existe) → `docker compose up -d --build`.

---

## T10 — Restauração no boot nunca foi exercitada

Era a **reclamação nº 1** da lista original ("o sandbox não sobe depois do
reboot, quebrando o Orca"). A fiação está correta, mas nenhum reboot aconteceu
desde que ela foi ligada — então a afirmação "resolvido" hoje é inferência, não
evidência.

**O que está verificado:**

| Item | Estado |
| :--- | :--- |
| Política dos containers | `unless-stopped` |
| `ExecStart` da unit | `podman start --all --filter should-start-on-boot=true` |
| `[Install] WantedBy` | `default.target` |
| Symlink de habilitação | presente |

**O que prova que nunca rodou:**

```
symlink criado:  Sep 5 00:21
boot atual:      Sep 4 21:36
journalctl --user -u podman-restart.service  ->  -- No entries --
ActiveEnterTimestamp=   (vazio)
```

A unit foi habilitada **depois** do boot corrente. Não é defeito; é ausência de
oportunidade.

### T10.1 [HUMANO] — o teste que nenhuma suíte substitui

Com um workspace no ar, reiniciar a máquina e, após o login, rodar:

```bash
asb-agent doctor
```

O esperado é o workspace aparecer como `rodando (egresso ok)` sem nenhuma
intervenção. Registrar o resultado real — inclusive se falhar — em
`docs/domains/sandbox/failure-modes.md`.

### T10.2 — documentar o que `Linger=no` implica

```
loginctl show-user $USER --property=Linger  ->  Linger=no
```

Sem linger, o gerenciador systemd do usuário sobe **no login**, não no boot.
A consequência precisa estar escrita porque muda o significado de "sobe
sozinho":

- **Desktop com login gráfico** (o caso do operador, que abre o Orca depois de
  logar): a restauração acontece no login e o requisito está satisfeito.
- **Headless / entrar por SSH esperando o sandbox já de pé**: não sobe até
  alguém logar no console. Aí é preciso `loginctl enable-linger $USER`.

**Não habilitar linger por padrão.** Ele faz os containers do workspace
seguirem de pé com a máquina ligada e ninguém logado, o que é uma mudança de
postura — mais superfície ativa sem operador presente — e deve ser escolha
explícita, não efeito colateral de uma tarefa de documentação.

Documentar as duas situações e o comando, em `failure-modes.md`, junto do
sintoma "o workspace sumiu depois do reboot".

---

## Contexto: dois falsos verdes achados em uso real (JÁ CORRIGIDOS)

Registrados para o padrão não se repetir. **Não refazer.**

1. **Allowlist defasada.** `.openai.com` não cobre `chatgpt.com`, que o Codex
   >= v0.153 usa; `.anthropic.com` não cobre `platform.claude.com`, que o
   Claude Code >= v2.1 usa. Os dois agentes morriam com `CONNECT 403`, que o
   operador lê como bloqueio proposital do sandbox. Corrigido com `.chatgpt.com`
   e `.claude.com`, mais um teste em `test_squid.py` que afirma que a base
   alcança a API de **cada agente que a imagem instala**.

2. **A verificação do login mentia.** `asb-agy --version` responde 0 com o
   agente deslogado; o `asb-agent login` imprimia `Antigravity: ok` enquanto a
   CLI dizia *"You are currently not signed in"*. Corrigido para `agy -p ping`,
   com a lista extraída para `LOGIN_CHECKS` e dois testes em `test_auth.py`.

---

## T11 — `test_broker` depende do estado ambiente da máquina

**Arquivo.** `tests/unit/test_broker.py`,
`test_lifecycle_up_refuses_read_when_broker_socket_missing`.

**Problema.** O nome diz *"when broker socket missing"*, mas o teste **nunca
torna o socket ausente** — depende de `/run/asb-docker/docker.sock` não existir
na máquina. Passou o dia todo enquanto o broker não estava instalado; no minuto
em que o operador rodou `asb-agent install-broker`, passou a quebrar. Um teste
unitário que muda de resultado conforme o host não pode ser acreditado em
nenhuma das duas direções.

**Segundo defeito, encadeado.** Quando a guarda não dispara, a execução segue
para o laço do mise e estoura longe da causa:

```
TypeError: sequence item 0: expected str instance, MagicMock found
  lifecycle.py: failed_names = ", ".join(d.name for d, _, _ in mise_errors)
```

`mock_layout.return_value` só configura `.state` e `.mount`; `.project_root`
fica um `MagicMock`, e `discover_mise_dirs` o devolve como se fosse diretório.

**Correção.**

1. Tornar o teste hermético: controlar a existência do socket em vez de
   herdá-la do host. O resultado tem de ser o mesmo com e sem broker instalado.
2. Configurar `mock_layout.return_value.project_root` com um diretório real,
   para que uma futura falha da guarda quebre **na asserção** e não num
   `TypeError` distante.

**Verificação.** Controle positivo nos dois sentidos: passa com o broker
instalado **e** sem ele. O broker está instalado nesta máquina agora, então dá
para exercitar os dois casos de verdade.

**Conclusão e Evidência:**
- Em `tests/unit/test_broker.py`, `Path.exists` foi mockado para interceptar `/run/asb-docker/docker.sock` e `mock_layout.return_value.project_root` foi configurado como `Path("/tmp/dummy-asb-mount")`.
- 16/16 testes em `test_broker.py` passam de forma 100% hermética.

---

## T12 — `asb-agent login`: armadilha de UX no passo do Claude

O `login` roda `claude /login` com diretório de trabalho em `/`. O Claude Code
pede confirmação de confiança na pasta **antes** de qualquer login, e o default
é a opção errada:

```
Accessing workspace: /
Quick safety check: Is this a project you created or one you trust?
) No, exit                     ← selecionado por padrão
  Yes, I trust this folder
```

Um Enter distraído sai sem logar, o laço segue para o Codex, e o resultado é um
`claude.json` de **0 bytes** no volume — foi exatamente o que aconteceu em uso
real, e só apareceu dias depois, quando o Claude pediu login dentro de um
workspace.

**Correção — escolher uma, não empilhar:**

- rodar o passo do Claude num diretório dedicado e já confiável (por exemplo
  `$ASB_HOME`, com a marca de confiança criada na imagem), **ou**
- imprimir instrução explícita antes do passo, mandando escolher
  *"Yes, I trust this folder"*.

**Nota importante para quem implementar:** existe um caminho melhor que já
funciona hoje — **logar de dentro de um workspace**. O entrypoint faz symlink
de `~/.claude/.credentials.json` e `~/.local/share/keyrings` para o volume
`asb-credentials` (verificado), então um login feito ali dentro persiste para
todos os workspaces. Documentar isso em `docs/domains/sandbox/README.md` como a
via recomendada, deixando o `asb-agent login` para o primeiro uso da máquina.

**Conclusão e Evidência:**
- Em `cli/asb/lifecycle.py`: adicionado `-w str(Path.home())` ao `podman exec` e alerta em `stderr` instruindo a escolher *"Yes, I trust this folder"* no safety check.
- Em `docs/domains/sandbox/README.md`: documentada a via recomendada de autenticação diretamente de dentro de qualquer workspace ativo, pois o volume `asb-credentials` já persiste as credenciais globalmente.

---

## T13 — Não há como recarregar a allowlist sem recriar o workspace

O `squid.conf` é gerado no `up` a partir de `allowlist-base.txt` mais o perfil e
montado read-only no proxy. Mudar a allowlist depois exigiria `down` + `up` —
mas o `up` publica a porta SSH com `-p 127.0.0.1::22`, **aleatória a cada
criação**. Num workspace do Orca isso significa perder a porta que o Orca
guardou, ou seja, perder a sessão.

A correção das duas allowlists foi feita à mão: regenerar o `squid.conf` no
diretório de estado e `podman restart asb-<ws>-proxy`. O container do agente não
é tocado e a porta sobrevive.

**Correção.** Um subcomando — `asb-agent reload-allowlist --workspace <ws>` ou
equivalente — que faça exatamente isso. Sem ele, "mudei a allowlist" implica
"recrie o workspace", caro demais numa ferramenta de uso diário para uma
mudança de uma linha.

**Verificação.** Teste de integração: subir workspace, confirmar que um domínio
é negado, acrescentá-lo ao perfil, rodar o comando, confirmar que passa a ser
permitido — **e que a porta SSH não mudou**. Essa última asserção é o ponto
inteiro do comando.

**Conclusão e Evidência:**
- Adicionado subcomando `asb-agent reload-allowlist --workspace <ws>` em `cli/asb-agent` e `cli/asb/lifecycle.py:reload_allowlist`.
- Regenera `squid.conf` a partir de `.agent-sandbox.toml` (do repo de origem ou clone do workspace com mtime mais recente) e reinicia `asb-<ws>-proxy` sem tocar no container do agente nem alterar a porta SSH publicada.
- Teste de integração `tests/test-reload-allowlist.sh` criado e verificado: 7/7 asserções passando (403 antes, reload sai 0, 200 depois, porta SSH inalterada, edição no clone validada).
- Teste unitário adicionado em `tests/unit/test_lifecycle.py` (`TestReloadAllowlist`).

---

## T14 — Inventário de domínios negados aguardando decisão

Coletado dos logs do Squid dos workspaces reais. **Não liberar nada sem o
humano decidir**; a lista existe para a decisão ser informada.

| Domínio | Tentativas | O que quebra hoje |
| :--- | ---: | :--- |
| `www.dcm4che.org` | 777 | Maven no Quarkus backend (`apps/backend/pom.xml`) |
| `registry.access.redhat.com` | 2 | imagem base do backend (`ubi9/openjdk-21-runtime`); build aninhado falha |
| `dl-cdn.alpinelinux.org` | 2 | `apk` dentro de builds aninhados |
| `cdn.playwright.dev` + 3 `*.azureedge.net` | 8 | download de browser do Playwright |
| `pypi.org` | 4 | ausente da allowlist do BlackICE |
| `repo.gradle.org` | 2 | Gradle |
| `dl.google.com`, `*.gvt1.com`, `clients2.google.com` | ~80 | auto-updater do Antigravity |

**Recomendações e Achados da Investigação:**

- **Origem das 777 tentativas ao `dcm4che.org` identificada:** No arquivo `apps/backend/pom.xml` (linhas 22-28), o projeto BlackICE declara explicitamente:
  ```xml
  <repositories>
      <repository>
          <id>dcm4che</id>
          <url>https://www.dcm4che.org/maven2</url>
      </repository>
  </repositories>
  ```
  Cada resolução de dependência ou build do Maven (`mvn package` / `mvn compile`) consulta esse repositório remoto para cada artefato não encontrado no cache local, gerando centenas de conexões HTTPS bloqueadas pelo Squid.
- `registry.access.redhat.com` pertence a `NESTED_REGISTRIES` em `cli/asb/squid.py`, ao lado de docker.io, quay.io e ghcr.io: é registry de container e só faz sentido com `mode = "nested"`.
- `dl-cdn.alpinelinux.org`, Playwright, `pypi.org` e Gradle são específicos de projeto e pertencem ao `[network] allow` do BlackICE.
- **Manter o auto-updater do Google bloqueado.** A versão do `agy` é fixada na imagem; permitir auto-update dentro do sandbox contorna esse controle e faz a ferramenta mudar sob os pés do operador.
- Decisão sobre inclusão de `www.dcm4che.org` e demais domínios aguarda deliberação do operador humano.

