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
| T4.1 | **[HUMANO] pendente** — é o elo que quebra a cadeia; T4.3 continua bloqueado por ela |
| T4.3 | corretamente **não habilitado** |
| **T8** | **concluída e verificada empiricamente** — `doctor` sonda egresso real (DNS e TCP) em cada workspace ativo com controles positivo e negativo; recuperação (`podman unshare --rootless-netns true`) documentada em `failure-modes.md` |
| **T9** | **concluída** — pré-requisito `mvn package` do `Dockerfile.jvm` e fluxo híbrido documentados em `BlackICE/infra/README.md` |

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
