# Piloto real de inicialização e autenticação — T2

- **Tarefa:** T2 do plano
  [`2026-09-07-startup-auth-redesign.md`](../superpowers/plans/2026-09-07-startup-auth-redesign.md)
- **Spec:** §7 (migração e retorno) e §8 (aceitação) do
  [desenho](../superpowers/specs/2026-09-07-startup-auth-redesign-design.md)
- **Status:** EM EXECUÇÃO — fases (a) e (b) concluídas. Boot 1 REPROVADO: o
  drop-in do projeto cria o namespace rootless sem egresso (§6.2). Boot 2
  APROVADO com o drop-in desativado para a janela (§6.4). Boot 3 — o boot
  normal, na configuração real com o drop-in reinstalado pelo Orca — REPROVADO,
  e o workspace legacy do Orca falha em silêncio: SSH saudável, sem egresso
  (§6.6). Falta o boot com rede atrasada, adiado. Validação pelo Orca
  BLOQUEADA por defeito do Orca na reidratação do terminal (§6.7)
- **Última atualização:** 2026-09-16

> Este relatório registra somente o que foi medido. Todo item não executado
> está marcado como tal. Nenhum cenário é simulado como comprovação.

---

## 1. Ambiente e versões

| Item | Valor |
| :--- | :--- |
| Boot ID (preparação) | `20f6dd18-e7e2-41d1-9b53-cd222bcb07b6` |
| Podman | 6.1.1 (rootless) |
| systemd | 261 (261.2-1-arch), `systemd --user`, `Linger=no` |
| Python | 3.14.7 |
| Imagem | `agent-sandbox:latest`, id `e034d2a241242ec7a8b` |
| Branch | `feat/startup-auth-redesign` |

### 1.1. A imagem foi reconstruída antes do piloto

A imagem em uso até 2026-09-16 tinha sido construída em **2026-09-06 22:00**,
enquanto `image/entrypoint.sh` foi corrigido em **2026-09-08** (`f7da619`). A
imagem ainda continha o symlink e o arquivo de 0 bytes de credencial que a
tarefa A3 removeu.

Consequência para o registro desta branch: **toda a evidência anterior a
2026-09-16 foi medida contra uma imagem 8 dias mais velha que o código sob
teste**, incluindo o relatório A1
([`2026-09-07-auth-pilot-live.md`](2026-09-07-auth-pilot-live.md)). Após
`asb-agent build`, a imagem foi conferida contra o fonte (`diff` do
entrypoint embutido: idêntico) e as cinco suítes foram reexecutadas verdes.

Nenhum item já aprovado é reaberto aqui, mas os itens que A1 deixou em aberto
precisam ser relidos sabendo que foram medidos no entrypoint antigo.

---

## 2. Inventário de coexistência (spec §7)

Levantado antes de qualquer cenário de boot, como a spec exige.

| Recurso | Estado | Política Podman |
| :--- | :--- | :--- |
| `asb-keyring` | Up | `unless-stopped` |
| `asb-recovery-ssh-d3a10b71` | Exited (143), 9 dias | `no` |
| `asb-recovery-ssh-44b95c8d` | Exited (143), 9 dias | `no` |
| `podman-restart.service` | enabled / active | — |
| Workspaces ASB legados | **nenhum** (`asb-agent list`) | — |

> **ATENÇÃO — este inventário estava incompleto de duas formas.**
> 1. Ficou desatualizado: foi levantado antes de o próprio piloto criar o
>    workspace `t2-pilot-scratch` (§5.3.2), `legacy`/`unless-stopped`, que não
>    foi suspenso antes do boot 1.
> 2. **Não cobria a classe drop-in.** Listou containers e o
>    `podman-restart.service`, mas não o drop-in
>    `podman-restart.service.d/agent-sandbox.conf`, cujo `ExecStartPre` cria o
>    namespace rootless em todo boot. Esse é o produtor estrutural. Ver §6.2.

**Consequência:** a condição de coexistência da §7 — registrar e suspender
workspaces ASB legados numa janela acordada — **não tem alvo nesta máquina**.
Não há workspace legado a suspender. Os dois containers `asb-recovery-ssh-*`
estão parados há 9 dias com política `no`, portanto não inicializam o
namespace no boot.

Isto NÃO é o mesmo que provar suporte a produtores externos que inicializem o
mesmo namespace antes da rede. A spec §7 é explícita: um piloto isolado
aprovado não se confunde com esse suporte. Se algum workload alheio passar a
inicializar a rede cedo, o cenário precisa ser refeito e a interferência
registrada.

---

## 3. Workspace-piloto

| Item | Valor |
| :--- | :--- |
| Workspace | `t2-pilot-blackice` |
| Repositório de origem | `/home/v/Data/Projects/BlackICE` (limpo, `main`) |
| Backup da origem | `/home/v/Data/Projects/BlackICE.bk` (`diff -rq`: idêntico) |
| Porta SSH | 45379 |
| Runtime inicial | `legacy` |
| Container agente | `44a536c94a6e` |
| Container proxy | `30d00837899d` |

Autorização do operador registrada em sessão: usar BlackICE após verificar
worktree limpa, com `.bk` da pasta e restauração ao final se necessário.

**Limite declarado:** a spec §7 prevê adotar um workspace **existente**. Não
havia nenhum nesta máquina, então a adoção e o rollback do item 7 serão
ensaiados sobre este workspace-piloto recém-criado. Isso satisfaz o critério
de rollback sem perda de dados nem troca de porta, mas é uma prova mais fraca
do que adotar um workspace com histórico real de uso.

---

## 4. Coletor de evidência

`tests/integration/collect_boot_evidence.py`, `collect(workspace) -> dict`.

- Somente leitura: não cria estado, não clona, não inicia login.
- **Nunca chama `auth verify`**: o orçamento de A4 é uma chamada real por
  fornecedor, sem retry; um coletor por boot o queimaria três vezes por boot.
- Allowlist **positiva** de campos. O manifesto `runtime.json` carrega
  `ssh_key` e um conjunto variável de chaves `ASB_*` (entre elas
  `ASB_KEYRING_PASS_FILE`); uma denylist deixaria passar qualquer chave nova.
- As sondas de prontidão alcançam a rede por desenho (sonda de host em
  `github.com:443`): é a etapa de rede que o relatório precisa registrar.

Defeito encontrado no uso real e corrigido: `auth status --json` sai com
**código 2** quando algum fornecedor não está autenticado. O coletor
descartava o stdout pelo código de saída e reportava `providers: {}`. Agora o
stdout é lido independentemente do código.

---

## 5. Estado de autenticação medido

Medido com `asb-agent auth status --workspace t2-pilot-blackice --json`, que
nunca inicia login. Nenhuma credencial, token ou código OAuth é registrado.

### 5.1. Antes do login humano (imagem já reconstruída)

| Fornecedor | Estado | Origem |
| :--- | :--- | :--- |
| claude | `unauthenticated` | `claude auth status --json`: `loggedIn=false` |
| codex | `authenticated` | `codex login status`: sessão ativa (código 0) |
| agy | `unknown` | sem comando de status local comprovado |

Agregado: `incomplete`. Confirma que a falha do Claude relatada pelo operador
**persiste na imagem corrigida** e não era artefato da imagem velha.

### 5.2. Depois do login humano (2026-09-16T17:59Z)

Operador executou `asb-agent login --agent claude` e `--agent agy` por fluxo
de device-auth.

| Fornecedor | Estado | Origem |
| :--- | :--- | :--- |
| claude | `authenticated` | `claude auth status --json`: `loggedIn=true` |
| codex | `authenticated` | `codex login status`: sessão ativa (código 0) — mas ver §5.5 |
| agy | `unknown` por `status`; `authenticated` por `verify` | ver §5.3 e §5.3.1 |

Agregado por `status`: `unknown` (nenhum fornecedor deslogado; agy
indeterminado por `status`, que nunca faz chamada real).

**Claude: reproduzido e resolvido individualmente**, como a spec §8.3 exige —
`unauthenticated` na imagem corrigida, `authenticated` após login real.

### 5.3. Antigravity: evidência direta contradiz o classificador

`asb-agent login --agent agy` não pediu login (o operador registrou que o agy
aparentemente reconheceu um login anterior) e devolveu `PENDENTE`.

A chamada real de verificação foi gasta uma vez, dentro do orçamento de A4:

```
asb-agent auth verify --workspace t2-pilot-blackice --agent agy --json
-> callBudget: {"agy": 1}
-> state: unknown
-> evidence: "chamada real retornou codigo 0, mas a resposta nao bateu
   com o formato esperado (erro de formato, registrado separado de
   erro de credencial)"
```

Capturando a saída real de `asb-agy models` no container do piloto (nomes de
modelo não são credencial):

```
Fetching available models...
gemini-3.8-flash-high	Gemini 3.8 Flash (High)
gemini-3.8-flash-medium	Gemini 3.8 Flash (Medium)
...
claude-sonnet-4-6	Claude Sonnet 4.6 (Thinking)
gpt-oss-120b-medium	GPT-OSS 120B (Medium)
(14 modelos, RC=0)
```

**Causa do `unknown`:** `_agy_models_output_valid` (`cli/asb/auth.py:804`)
exige `_AGY_MODEL_IDENTIFIER.fullmatch(line)` em **toda** linha não vazia. A
saída real é `identificador<TAB>rótulo humano`, mais a linha de prosa
`Fetching available models...`. Portanto `fullmatch` falha nas 15 linhas e a
classificação **só pode** devolver `unknown`, independentemente do estado da
credencial. O comentário em `auth.py:786` explica por quê: a saída bruta de A1
"nao foi preservada", então a guarda foi escrita contra uma lembrança.

**Leitura honesta da evidência:** `RC=0`, 14 modelos listados e a linha
`Fetching available models...` comprovam uma ida ao servidor bem-sucedida. Um
`agy` deslogado não produz essa saída. A credencial do Antigravity está
**funcional por evidência direta**; o `unknown` é limitação da ferramenta de
classificação, **não** um estado de autenticação.

### 5.3.1. Correção da guarda (autorizada pelo operador) e resultado real

O operador autorizou a correção na forma recomendada: commit de A4 separado,
test-first. Aplicada em `cli/asb/auth.py`.

Duas descobertas durante a correção, ambas vindas de dado real e não de
suposição:

1. **`gpt-oss-120b-medium`** reprovava a regra de número, que exigia dígito
   sem letra logo depois. `120b` tem sufixo de unidade. Uma única linha
   reprovada derrubava a lista inteira.
2. **A ordem da prosa é o inverso do que a primeira captura sugeria.**
   `verify_client` monta `combined = f"{stdout}\n{stderr}"`; a listagem sai em
   stdout e `Fetching available models...` sai em **stderr**, portanto a prosa
   chega **depois** das linhas de modelo. A captura inicial por `podman exec`
   com `2>&1` intercalava na ordem oposta. A primeira tentativa de correção
   passou nos testes de unidade e **continuou reprovando na chamada real** —
   foi essa discrepância que revelou a ordem verdadeira.

A guarda continua falhando fechado. O que ela exige agora:

- pelo menos duas linhas de modelo;
- linhas de modelo **contíguas** — prosa no meio reprova a lista inteira;
- só a **coluna do identificador** sustenta família e versão; o rótulo humano
  nunca conta;
- nenhuma linha tolerada (antes ou depois do bloco) pode citar família
  conhecida.

Resultado da chamada real após a correção:

```
asb-agent auth verify --workspace t2-pilot-blackice --agent agy --json
-> callBudget: {"agy": 1}
-> state: authenticated   (exit 0)
-> evidence: "'agy models' retornou uma lista de nomes de modelos com
   codigo 0; prova acesso a lista, nao geracao"
```

**Antigravity: reproduzido e resolvido individualmente.** Com o Claude
(§5.2), fecha-se a exigência da spec §8.3 de tratar os dois separadamente.

**Limite que permanece por desenho:** `auth status` continua devolvendo
`unknown` para o agy, porque não há comando de status local e status nunca faz
chamada real (`cli/asb/auth.py:199`). Logo o coletor de evidência de boot —
que só consome `status`, nunca `verify` — também registra `unknown` para o
agy. O `authenticated` do agy vem exclusivamente de `verify`, registrado aqui.

**Obrigação da spec §8 ainda vale:** uma correção relacionada exige repetir os
cenários afetados. Como as fases (b), (c) e (d) ainda **não** foram
executadas, não há cenário a repetir — a correção veio antes, não depois.

---

### 5.3.2. Cliente novo e dois workspaces simultâneos

**Cliente novo.** Container efêmero, criado do zero, montando só o volume de
credenciais com `keyrings` mascarado:

```
claude: 504 bytes      codex: 3876 bytes
```

Ou seja: uma credencial gravada por um workspace é legível por um cliente que
nunca participou do login. Requisito de "login uma vez por fornecedor,
compartilhado" satisfeito para um cliente novo.

**Dois workspaces simultâneos — BLOQUEADOR ENCONTRADO.**

A primeira tentativa foi criar um segundo workspace do **mesmo** repositório
(BlackICE). Falhou:

```
Error: rootlessport listen tcp 127.0.0.1:8081: bind: address already in use
```

Causa: `/home/v/Data/Projects/BlackICE/.agent-sandbox.toml` declara

```toml
[docker]
publish_ports = ["18080:80", 8081]
```

A porta SSH é dinâmica (`-p 127.0.0.1::22`), mas `publish_ports` é **fixa por
desenho** — o desenvolvedor quer `localhost:18080` apontando para a aplicação.
Consequência: **dois workspaces do mesmo projeto que declare `publish_ports`
nunca podem rodar ao mesmo tempo**. O segundo `up` falha ao ligar a porta.

Isto não é falha de credencial nem de supervisão, e o workspace 1 permaneceu
intacto durante a falha (verificado). Mas colide com a exigência da spec §8.3
de "dois workspaces simultâneos utilizáveis" para qualquer projeto que
publique portas — que é justamente o caso de uso real do BlackICE.

**Não corrigido aqui.** Alocação dinâmica de `publish_ports` mudaria o
contrato do perfil (o endereço deixaria de ser previsível para o
desenvolvedor) e está fora do escopo de T2. Registrado como decisão de
arquitetura pendente.

**Contorno usado para provar o requisito de credencial:** segundo workspace
criado de um repositório descartável sem `publish_ports`
(`/home/v/Data/Projects/t2-pilot-scratch`, workspace `t2-pilot-scratch`,
porta 34075). Com os dois rodando ao mesmo tempo:

| Workspace | claude | codex | agy |
| :--- | :--- | :--- | :--- |
| `t2-pilot-blackice` (45379) | `authenticated` | `authenticated` | `authenticated` (verify) |
| `t2-pilot-scratch` (34075) | `authenticated` | `authenticated` | `authenticated` (verify) |

Os três fornecedores são utilizáveis nos dois workspaces simultâneos, a partir
de um único login por fornecedor. O `verify` do agy foi gasto uma vez em cada
workspace (`callBudget: {"agy": 1}` em cada chamada).

---

### 5.4. ACHADO DE SEGURANÇA: credencial viva exposta na raiz do volume

Severidade alta. Independente da questão do agy.

O volume `asb-credentials` ainda carrega os arquivos do layout ANTIGO na raiz,
ao lado dos diretórios por fornecedor do layout novo:

| Arquivo | Tamanho | Modo (host) | mtime |
| :--- | :--- | :--- | :--- |
| `claude.json` | **0 bytes** | 600 | 2026-09-05 00:32 |
| `codex-auth.json` | **3876 bytes** | 600 | 2026-09-05 15:26 |

`codex-auth.json` contém **material de credencial vivo**. Inspecionando apenas
os NOMES dos campos, nunca os valores:

```
auth_mode          : preenchido
OPENAI_API_KEY     : vazio
tokens.id_token    : preenchido
tokens.access_token: preenchido
tokens.refresh_token: preenchido
tokens.account_id  : preenchido
last_refresh       : preenchido
```

**Exposição comprovada empiricamente**, não deduzida. De dentro do container
do agente do workspace-piloto:

```
podman exec asb-t2-pilot-blackice-agent \
  sh -c 'cat /run/asb-credentials/codex-auth.json | wc -c'
-> LEGIVEL: 3876 bytes
-> campos: ['access_token', 'account_id', 'id_token', 'refresh_token']
```

O volume inteiro é montado rw em todo container de agente, com apenas
`keyrings` mascarado por tmpfs. Portanto **qualquer workspace lê o
refresh_token do Codex**. O layout novo não usa esse arquivo — ele não é lido
nem escrito por ninguém — mas continua legível enquanto existir.

`claude.json` com 0 bytes é fóssil do defeito de precriação anterior a A3
(arquivo de 0 bytes que jamais poderia ser lido como JSON). Inofensivo em
conteúdo, mas confirma que o layout antigo esteve vivo neste volume.

**Nada foi apagado.** Remover material de credencial é decisão do operador, e
apagar credencial nunca é recuperação válida.

### 5.5. CORREÇÃO: `codex-auth.json` é a credencial VIVA do Codex

Uma recomendação anterior deste relatório — "remover `codex-auth.json`, o
login novo já está confirmado" — estava **ERRADA** e teria destruído o acesso
do Codex. O registro fica aqui porque o erro é instrutivo.

`codex/auth.json` **não é um arquivo**: é um SYMLINK para o arquivo da raiz.

```
# dentro do container do agente
~/.codex/auth.json -> /run/asb-credentials/codex-auth.json   (3876 bytes)
~/.claude/.credentials.json                                   (504 bytes, arquivo comum)
```

| Fornecedor | Forma | Data | Layout |
| :--- | :--- | :--- | :--- |
| claude | arquivo comum, 504 B | 2026-09-16 14:58 (login desta janela) | **novo, correto** |
| codex | symlink → raiz, 3876 B | alvo de 2026-09-05 15:26 | **antigo (pré-A3)** |

Consequências:

1. O Codex **não foi autenticado nesta janela**. Ele reporta `authenticated`
   porque lê, através do symlink, uma credencial de **5 de setembro**.
2. Apagar `codex-auth.json` quebraria o symlink e derrubaria o Codex. A
   exposição da §5.4 e a credencial em uso são **o mesmo arquivo**.
3. O arranjo é exatamente o que A1/A3 documentam como defeituoso. O Codex
   sobrevive a ele só porque seu escritor tolera symlink — o Claude não, e é
   por isso que o Claude perdia o login a cada partida.
4. O symlink tem mtime 2026-09-16 11:08 (14:08 UTC), **cerca de 16 minutos
   antes** da reconstrução da imagem (14:24 UTC). O produtor conhecido desse
   arranjo é o entrypoint da imagem ANTIGA. Isto é inferência a partir dos
   carimbos de tempo, não atribuição comprovada.

**Remediação correta** (não executada — decisão do operador, e a spec §7 exige
janela explícita: preparar destino sem alterar a origem, parar escritores,
validar migração e rollback, nunca substituir credencial renovada por cópia
antiga):

- Opção A, mais limpa: `asb-agent login --agent codex` para que um arquivo
  comum seja gravado em `codex/auth.json`, como aconteceu com o Claude nesta
  janela. Só então remover o `codex-auth.json` da raiz.
- Opção B: copiar o conteúdo para um arquivo comum em `codex/auth.json`,
  confirmar `authenticated`, e só então remover a raiz.

Em ambos os casos, `claude.json` de 0 bytes pode ser removido sem risco: nada
aponta para ele e não contém material algum.

### 5.6. Opção A executada — symlink eliminado

O operador executou `asb-agent login --agent codex`. Resultado medido:

| Caminho | Antes | Depois |
| :--- | :--- | :--- |
| `codex/auth.json` | symlink → raiz | **arquivo comum**, 3876 B, 16:11 |
| `codex-auth.json` (raiz) | alvo do symlink, 5 set | **órfão**, inalterado, 5 set |
| symlinks no volume | 1 | Três boots reais, incl. rede com atraso de 60 s | **REPROVADO na configuração real** — boot 1 (`5acb7550`) e boot 3 (`019a9a43`, configuração de uso real com Orca) reprovados pelo mesmo motivo: namespace criado cedo sem egresso, sem recuperação (§6.2, §6.6). Boot 2 (`155a3648`) aprovado só com o drop-in desativado (§6.4). Boot com rede atrasada adiado. Reconexão do Orca **BLOQUEADA** por defeito do Orca na reidratação do terminal após reboot (§6.7) |

O escritor do Codex usou rename atômico e, ao fazê-lo, **substituiu o próprio
symlink** — exatamente o comportamento que A1 documentou como o mecanismo que
cortava o vínculo com o volume. Aqui o efeito foi benéfico: encerrou o arranjo
antigo.

Confirmado nos dois workspaces simultâneos: `~/.codex/auth.json` é arquivo
comum, e `codex` segue `authenticated`.

**Estado da exposição:** `codex-auth.json` na raiz agora é de fato obsoleto —
nada aponta para ele, e ele guarda uma credencial de 5 de setembro que não é
mais usada. Continua legível por qualquer container de agente enquanto
existir. Removê-lo agora fecha a exposição **sem** o risco descrito na §5.5.

### 5.7. Exposição fechada

Autorizado pelo operador. Conferências feitas **antes** de apagar:

| Verificação | Resultado |
| :--- | :--- |
| Algum código lê a raiz? | Só `LEGACY_ROOT_CREDENTIAL_FILES` (lista de **detecção**, `lifecycle.py:100`) |
| Algum symlink aponta para a raiz? | Nenhum |
| Arquivos alterados desde 5 set? | Não — `codex-auth.json` 15:26, `claude.json` 00:32 |
| Credencial em uso é outra? | Sim — `codex/auth.json`, arquivo comum de 16:11 |

Removidos: `codex-auth.json` (3876 B) e `claude.json` (0 B).

Resultado medido depois:

- Raiz do volume contém só `claude/`, `codex/` e `keyrings/`.
- O aviso de layout ANTIGO **parou de disparar**.
- Os dois workspaces simultâneos seguem `claude=authenticated`,
  `codex=authenticated`.

Nenhuma credencial em uso foi tocada. A remoção atingiu apenas a cópia
obsoleta, depois de o login novo estar confirmado — a ordem que a spec §7
exige.

---

## 6. Fase (b): adoção e rollback de supervisão

Executada em `t2-pilot-blackice`. `adopt-runtime` tem dry-run por padrão e
exige `--apply`, como a §7 pede ("inventariar antes de mudar supervisão"). O
inventário registrou IDs, imagens, estado e política anteriores, mounts e
portas dos dois containers antes de qualquer alteração.

| Invariante | Antes | Após adoção | Após rollback |
| :--- | :--- | :--- | :--- |
| `runtime_type` | `legacy` | `systemd` | `legacy` |
| Porta SSH | 45379 | **45379** | **45379** |
| ID do agente | `44a536c94a6e…` | **idêntico** | **idêntico** |
| ID do proxy | `30d00837899d…` | **idêntico** | **idêntico** |
| Política Podman | `unless-stopped` | `no` | `unless-stopped` |
| Unidades systemd | — | `active` | `inactive` |
| HEAD do checkout | `3bd3a1d` | `3bd3a1d` | `3bd3a1d` |
| Trabalho não commitado | `M README.md`, `?? T2-PILOT-UNTRACKED.txt` | idêntico | idêntico |
| sha256 dos dois arquivos | — | **inalterados** | **inalterados** |

Resultado de `adopt-runtime --apply`: `status: applied`,
`phase: readiness_verified`.

Guardrails da spec §7 conferidos:

- **Containers não foram recriados**: os IDs são os mesmos nas três medições.
- **`podman-restart.service` não foi desabilitado globalmente**:
  `enabled` / `active` antes e depois.
- **Workspace irmão intacto**: `t2-pilot-scratch` permaneceu `legacy`,
  `unless-stopped`, rodando, durante toda a adoção e o rollback.
- Trabalho não commitado verificado também **de dentro** do container, como o
  usuário real.

Duas observações para o runbook de T3, nenhuma reprovando o critério:

1. **Os containers são reiniciados** na transição (uptime zerado, `Up 13
   seconds` após o rollback), embora não sejam recriados. Adoção e rollback
   causam interrupção breve de serviço; não são operações a quente.
2. **Assimetria de interface:** `adopt-runtime` é dry-run por padrão e precisa
   de `--apply`; `rollback-runtime` **aplica imediatamente**, sem dry-run nem
   confirmação. Defensável (o rollback é a direção segura), mas surpreende
   quem espera simetria — vale documentar.

**Critério 7 satisfeito:** rollback ensaiado sem perda de dados e sem troca de
porta. Ressalva já registrada na §3: o workspace adotado foi criado por este
piloto, não é um workspace com histórico real de uso.

---

## 6.1. Fase (c) preparada — aguardando janela de reboot

Estado montado para o **boot 1 (normal)**. Evidência pré-boot salva em
`~/.local/state/agent-sandbox/t2-evidence/pre-boot1-*.json` (fora de qualquer
workspace, sobrevive ao reboot).

| Workspace | runtime | porta | agente | proxy |
| :--- | :--- | :--- | :--- | :--- |
| `t2-pilot-blackice` | **systemd** | 45379 | `44a536c94a6e` | `30d00837899d` |
| `t2-pilot-scratch` | `legacy` | 34075 | `4a5a8d097460` | `f0b7613bf892` |

Trabalho não commitado a preservar (`t2-pilot-blackice`):

```
 M README.md            2c1a0f4c5b73c5d7…
?? T2-PILOT-UNTRACKED.txt  e0190ec774262c94…
HEAD 3bd3a1d
boot_id atual 20f6dd18-e7e2-41d1-9b53-cd222bcb07b6
```

Pré-condições conferidas:

- `asb-t2-pilot-blackice.target` está `enabled`, com
  `WantedBy=default.target` e `Wants=` os dois serviços — ou seja, o boot
  puxa a supervisão sem comando corretivo.
- Política Podman do workspace adotado é `no`: quem o inicia é o systemd,
  não o `podman-restart.service`.
- `Linger=no` permanece: as unidades de usuário só sobem **após o login**
  do operador, que é o desenho declarado na spec.
- O workspace `t2-pilot-scratch` continua `legacy`/`unless-stopped`, servindo
  de controle: no boot ele deve voltar pelo `podman-restart.service`, por um
  caminho diferente do adotado.

O que verificar depois de cada boot, sem comando corretivo:

1. `boot_id` mudou (prova que houve boot real, não um resume).
2. Porta 45379 e os IDs dos containers preservados.
3. `M README.md` e `?? T2-PILOT-UNTRACKED.txt` intactos, com os mesmos sha256.
4. Prontidão automática; reconexão do Orca sem `resume` corretivo.

**Reboots não fazem parte da suíte automática e não foram executados por
mim.** Eles derrubam a sessão do agente e exigem janela acordada, conforme o
plano ("não considerar espera sem resposta uma autorização").

---

## 6.2. Boot 1 — REPROVADO, e o teste estava contaminado

**Boot ID:** `5acb7550-4fd6-49e8-a3f0-eedc7ee0e30a` (antes: `20f6dd18…`).
Boot real confirmado pela troca de `boot_id` e uptime de 1 minuto.
Autologin do SDDM (`User=v`, `Session=omarchy.desktop`); nenhum comando
corretivo executado pelo operador nem por mim.

### Resultado

O workspace adotado **não ficou pronto**. O proxy terminou em `failed` após
3 reinícios, e os dois containers de `t2-pilot-blackice` ficaram `exited`.

### Linha do tempo medida

| Hora | Evento |
| :--- | :--- |
| 16:23:46 | boot do kernel |
| 16:24:14 | `network-online.target` (sistema) |
| **16:24:15** | **`pasta` cria o namespace rootless compartilhado** |
| 16:24:16 | `podman-restart.service` restaura o workspace **legacy** `t2-pilot-scratch` |
| 16:24:55 | systemd inicia o agente adotado (mesmo ID `44a536c94a6e`) |
| 16:25:00 | systemd inicia o proxy adotado (mesmo ID `30d00837899d`) |
| 16:25:32 | `runtime_check [proxy]: timeout na sonda de egresso do proxy` |
| 16:25:40 | `Scheduled restart job, restart counter is at 2` |
| ~16:26:35 | proxy `failed`, `NRestarts=3`; systemd desiste |

### Diagnóstico

| Camada | Estado | Evidência |
| :--- | :--- | :--- |
| Host | **rede OK** | `curl https://github.com` → HTTP 200 em 0,3 s |
| Rede do Podman (dentro do container) | **OK** | `default via 10.89.3.1 dev eth1`; `aardvark-dns` rodando |
| Egresso do namespace rootless | **QUEBRADO** | proxy legacy: `CONNECT tunnel failed, response 503`; proxy adotado: timeout na sonda |

A quebra está **entre** a rede do container e o host — no upstream do `pasta`.
E ela atinge os dois workspaces, legacy e adotado, porque compartilham o
namespace. Não é defeito do caminho systemd.

### Causa-raiz: o drop-in do próprio projeto cria o namespace em todo boot

> Uma primeira versão desta seção atribuía a contaminação apenas ao workspace
> legacy `t2-pilot-scratch` não suspenso. **Isso era metade da causa**, e foi
> corrigido antes do commit. Registrado porque a causa incompleta levaria a
> repetir o boot e medir de novo o mesmo defeito.

`podman-restart.service` carrega um drop-in **escrito pelo próprio
agent-sandbox** (`cli/asb/install.py:90`):

```
~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf
# Managed by agent-sandbox: podman-restart netns initialization
[Service]
ExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true
```

Ele vem do plano `2026-09-06-rootless-uplink-recovery`, cujo objetivo era
"preparar o namespace rootless antes de iniciar containers que precisam de
egresso". A unidade está habilitada, então o `ExecStartPre` roda em **todo**
boot, **independentemente** de haver algum container com
`should-start-on-boot`. O `pasta` nasceu às **16:24:15**; o
`podman-restart.service` registrou início às 16:24:16 — o `ExecStartPre` roda
imediatamente antes do `ExecStart`.

A prova de que o defeito é do **namespace**, e não da ordem entre workspaces:
o proxy do `t2-pilot-scratch`, que rodava **dentro** desse mesmo namespace,
também estava sem egresso (`CONNECT tunnel failed, response 503`) enquanto o
host tinha HTTP 200. Um namespace, os dois workspaces quebrados.

**Achado de desenho:** o mecanismo de 2026-09-06 garante que o namespace
**exista** cedo, mas **não** que seu uplink **funcione**. Criado quebrado,
nada a jusante o repara — o workspace adotado, que só subiu às 16:24:55,
herdou um namespace que não criou. É a spec §7 literalmente:

> "aguardar rede em uma unidade não repara um namespace já inicializado cedo
> por outra."

E é a mesma falha que `failure-modes.md:145` já registrava:
`podman unshare --rootless-netns true` não recupera um namespace quebrado. O
que este boot acrescenta é que o próprio `unshare` no boot **é** o produtor.

Não se determinou **por que** o uplink capturado às 16:24:15 não funcionava —
se o `network-online.target` (16:24:14) foi atingido antes de haver
conectividade real, ou outra causa. Isso fica em aberto e não é presumido.

### A ferramenta tinha avisado

O inventário do `adopt-runtime`, disponível desde a fase (b), já listava:

```
inventory.diagnostics.rootless_netns_producers = [
  "dropin:agent-sandbox.conf(projeto)",
  "unit:podman-restart.service(habilitada em default.target.wants)",
  "workspaces_rotulados:2",
  "containers_sem_label:3"
]
```

Esse aviso não foi lido na fase (b): só as primeiras linhas do JSON foram
examinadas. A verificação feita depois, "nenhum produtor precoce restante",
filtrava containers `bridge` em execução e **não enxerga a classe drop-in**.
O `_netns_producers()` do código cobre exatamente essa classe; a checagem
manual não cobria.

### O papel do workspace legacy

Deixar `t2-pilot-scratch` em `legacy` como "controle" foi erro de desenho do
piloto: a §7 exige suspender workspaces legados antes da janela de boot. Ele
foi **um** produtor adicional, restaurado às 16:24:16. Mas suspendê-lo **não
basta** para um boot limpo, porque o drop-in cria o namespace mesmo sem ele.

**Portanto o boot 1 NÃO mede se o runtime adotado sobe limpo.** E repetir o
boot só suspendendo o scratch reproduziria o mesmo defeito.

### O que o boot 1 comprova

1. **O mecanismo de inicialização do namespace no boot não garante egresso,
   e um namespace criado quebrado não se recupera.** Reproduzido em hardware
   real, afetando legacy e adotado. Pela regra de parada da §8, gate
   reprovado **interrompe expansão e migração**, e só a decisão que falhou
   deve ser revista — aqui, a de inicializar o namespace via `ExecStartPre`
   no boot.
2. **Falha de admissão não publicou sucesso (§8.5).** `runtime_check.py`
   recusou a sonda de egresso e a unidade não foi dada como pronta.
3. **Credenciais não foram apagadas (§8.4).** `claude/.credentials.json` 504 B
   e `codex/auth.json` 3876 B, mesmos tamanhos de antes do boot.
4. **Indisponibilidade não virou logout (§8.4).** Com o agente adotado caído e
   sem egresso, `auth status` devolveu `claude=unreachable codex=unreachable`
   — e não `unauthenticated`.
5. **Trabalho não commitado sobreviveu ao reboot.** HEAD `3bd3a1d`,
   `M README.md` e `?? T2-PILOT-UNTRACKED.txt`, os dois sha256 idênticos.
6. **Nenhum container foi recriado.** Os quatro IDs batem com o baseline.

### O que o boot 1 NÃO comprova, e um limite novo

- A porta 45379 não é mensurável com o container `exited` — isto **não** é
  troca de porta, é ausência de medição.
- **Não houve recuperação automática.** Depois que o proxy atingiu o limite de
  reinícios, o systemd desistiu e o workspace ficou fora do ar. A §8.4 exige
  "recuperação automática validada no piloto"; isto está **não demonstrado**.

### O que deliberadamente não foi feito

**Nenhum reset global do namespace rootless** (`podman unshare
--rootless-netns`, `podman system migrate` ou equivalente). Dois motivos:
`failure-modes.md` já registra que `podman unshare --rootless-netns true` não
recuperou um namespace quebrado num piloto anterior; e a §8.4 proíbe promover
recuperação que dependa de reset global. Tentar, e dar certo, provaria
justamente o que a spec veda promover.

### Duas medições descartadas por serem inválidas

- `wget` no proxy devolveu `rc=127`: comando inexistente na imagem, **não**
  falha de egresso.
- `getent hosts github.com` falhando **dentro do agente**: o agente é isolado
  por desenho e só sai pelo proxy; não resolver DNS direto é o esperado.

### Estado preparado depois do boot 1

`t2-pilot-scratch` foi suspenso com autorização do operador. Os dois
containers ficaram `exited`, com IDs preservados e `StoppedByUser=true`. A
política continua `unless-stopped`; o que deve mantê-los parados no próximo
boot é o filtro `should-start-on-boot=true` do `podman-restart.service`
combinado com `StoppedByUser`. Um reboot com este estado testaria esse
mecanismo específico (critério 2).

### Próximo passo — decisão do operador

Repetir o boot **só suspendendo o scratch não é um teste válido**: o drop-in
continua listado em `rootless_netns_producers` e recriaria o namespace cedo,
reproduzindo o mesmo defeito. Nenhum reboot deve ser pedido sem que a lista de
produtores tenha sido reconferida pela ferramenta, não por filtro manual.

A evidência deste boot fica preservada como entrada própria, sem ser
sobrescrita.

---

## 6.3. Boot 2 preparado — teste discriminante com o drop-in desativado

Autorizado pelo operador (opção recomendada). Objetivo: separar "o redesenho
funciona quando o drop-in sai" de "o namespace rootless quebra no boot de
qualquer jeito". Registrado também como o cenário **um workspace ativo e outro
suspenso** (critério 2), conforme combinado — e **não** como "boot normal",
para os três boots continuarem distintos.

### Exceção de janela, não remoção definitiva

A spec §7 só autoriza remover o drop-in "após inventário confirmar que foi
criado pelo projeto **e que os recursos ASB foram adotados**". A primeira
condição vale (cabeçalho `Managed by agent-sandbox`); a segunda **não**:
`t2-pilot-scratch` é legacy e o `asb-keyring` não foi adotado. O código já
tem o caminho projetado para isso (`supervisor.py`, `intent_to_remove` →
`removed_by_adoption`), que corretamente não disparou. Por isso esta é uma
**desativação temporária para a janela**, com restauração obrigatória.

### RESTAURAÇÃO OBRIGATÓRIA ao fim da janela

```
cp -p ~/.local/state/agent-sandbox/t2-evidence/dropin-backup/agent-sandbox.conf \
      ~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf
systemctl --user daemon-reload
```

Backup verificado idêntico ao original (`cmp`), modo 600, 142 bytes, sha256
`91476ff033a8a1ba7ea1709bbcdd464b6dbdd7a7d846c8f81fe652288476f206`.

**Durante a janela não rodar `asb-agent up`** para workspace legacy:
`install.podman_restart()` é chamado só pelo ramo legacy de `up`
(`lifecycle.py:826`) e reinstalaria o drop-in. `auth status`, o coletor e o
`adopt-runtime` em dry-run não passam por esse caminho.

### Verificação de produtores — pela ferramenta

Depois de remover o drop-in e rodar `daemon-reload`:

```
ExecStartPre efetivo no podman-restart.service: 0
inventory.diagnostics.rootless_netns_producers = [
  "unit:podman-restart.service(habilitada em default.target.wants)",
  "workspaces_rotulados:2",
  "containers_sem_label:3"
]
```

A entrada `dropin:` sumiu. A ferramenta ainda lista `podman-restart.service`
como **classe** de produtor, de forma conservadora e correta. O que ele de
fato inicia no boot (`--filter should-start-on-boot=true`) é **somente**
`asb-keyring`, com `NetworkMode=none`. `t2-pilot-scratch` está fora
(`StoppedByUser=true`).

**Incerteza residual, não presumida resolvida:** se iniciar um container
`network=none` ainda inicializa o namespace rootless. O boot responde: se o
`pasta` nascer **junto do `podman-restart`**, o keyring ainda é produtor; se
nascer **junto da unidade adotada**, ela é a primeira produtora.

### O que o desenho adotado promete — e o que isto testa

| Propriedade | Valor | Consequência |
| :--- | :--- | :--- |
| Ordenação por rede | **nenhuma** (sem `After=network-online.target`) | unidade de usuário não depende de target de rede do sistema; a espera é pela sonda |
| `Restart` | `always` | reinicia após sonda falha |
| `StartLimitBurst` | **3 em 10 min** | no boot 1, o proxy estourou esse limite e o systemd **desistiu de vez** |
| `TimeoutStartSec` | 2 min 30 s | — |

**Risco registrado para o boot de rede atrasada:** com a sonda de egresso
levando ~32 s por tentativa, três tentativas cobrem pouco mais de 1,5 min. Se
a rede demorar mais que isso, a unidade atinge o limite e não se recupera
sozinha. Não é conclusão — é o que o boot de rede atrasada precisa medir.

### Estado salvo

`~/.local/state/agent-sandbox/t2-evidence/pre-boot2-*.json` e
`pre-boot2-estado.txt`. Boot ID antes do reboot: `5acb7550…`. Trabalho não
commitado a preservar: HEAD `3bd3a1d`, `M README.md` (`2c1a0f4c…`),
`?? T2-PILOT-UNTRACKED.txt` (`e0190ec7…`).

---

## 6.4. Boot 2 — APROVADO sem comando corretivo

**Boot ID:** `155a3648-6141-441a-ad3a-58409d299fc0` (antes: `5acb7550…`).
Cenário: drop-in desativado, `t2-pilot-blackice` adotado e ativo,
`t2-pilot-scratch` suspenso. Autologin; **nenhum comando corretivo**.

### Linha do tempo medida

| Hora | Evento |
| :--- | :--- |
| 16:54:37 | boot do kernel |
| 16:56:14 | `network-online.target` (sistema) |
| 16:56:15 | `podman-restart.service` inicia — sobe só `asb-keyring` (`network=none`) |
| 16:56:16 | proxy adotado inicia (mesmo ID `30d00837899d`) |
| 16:56:52 | sonda falha: `proxy retornou status inesperado: HTTP/1.1 500 Internal Server Error` |
| **16:56:54** | **`pasta` nasce** — o único namespace rootless em uso daqui em diante |
| 16:57:00 | `restart counter is at 1`; **`Started ... proxy`** — sonda passa |
| 16:57:01 | agente `active` (0 reinícios); target `active` |

Pronto **47 s após o `network-online.target`**, com **1 reinício** do proxy —
dentro do `StartLimitBurst=3`.

### Verificação pelo caminho real, não só pelo estado do systemd

| Verificação | Resultado |
| :--- | :--- |
| Egresso agente → proxy → `github.com` | **HTTP 200 em 0,33 s** |
| Controle negativo: `example.com` (fora da allowlist) | **403**, bloqueado |
| Porta SSH | **127.0.0.1:45379**, preservada |
| SSH com a chave real (`~/.config/agent-sandbox/id_ed25519`) | **OK**, `hostname=44a536c94a6e` |
| IDs dos containers | **idênticos** (`30d00837899d`, `44a536c94a6e`) |
| Trabalho não commitado | HEAD `3bd3a1d`; sha256 `2c1a0f4c…` e `e0190ec7…` **idênticos** |
| Credenciais | `claude=authenticated`, `codex=authenticated` |
| Sondas do coletor | host, proxy, ssh e keyring **`healthy`** |
| `t2-pilot-scratch` suspenso | **`Exited` há 22 min** — atravessou o reboot parado |

Uma medição foi descartada por erro meu: a primeira tentativa de SSH usou um
caminho de chave inexistente (`~/.local/state/agent-sandbox/ssh/id_ed25519`)
e falhou com `Identity file ... not accessible`. Não é falha do produto; com
a chave real (`lifecycle.SSH_KEY`) o SSH funcionou.

### A incerteza residual da §6.3 foi resolvida

O `podman-restart.service` iniciou às 16:56:15 e o `pasta` só nasceu às
16:56:54. Portanto **iniciar o `asb-keyring` com `network=none` não cria o
namespace rootless**. Neste boot, quem criou o namespace foi o workspace
adotado.

### Contraste com o boot 1 — hipótese principal, não comprovada

O fato comum aos dois boots: a primeira tentativa do proxy **falhou** nos dois,
logo após o `network-online.target`. A diferença: no boot 1 **nenhum**
reinício recuperou; no boot 2 **o primeiro** recuperou.

Inferência a partir dos carimbos: o proxy subiu às 16:56:16 em rede `bridge`,
que exige namespace; o único `pasta` existente nasceu às 16:56:54, **depois**
de a primeira tentativa já ter falhado. Logo, o namespace que serve o
workspace pronto **não é** o que estava ativo na tentativa que falhou — ele foi
**substituído**.

Hipótese principal: **um namespace criado cedo só se recupera se nada o mantiver
aberto.** No boot 1, o namespace foi criado pelo `unshare` do drop-in e
mantido aberto pelos containers do `t2-pilot-scratch`, então cada reinício do
proxy reutilizou o mesmo namespace quebrado. No boot 2, nada o segurava: quando
o proxy caiu, o namespace foi recriado já com a rede de pé.

Se confirmada, o dano do drop-in não é só criar o namespace cedo — é criá-lo de
um jeito que impede os reinícios de renová-lo. **Isto não foi comprovado**: não
se observou diretamente a destruição do primeiro namespace, só a ausência dele.

### O que o boot 2 comprova

1. **O runtime adotado sobe pronto sem comando corretivo** quando nenhum
   outro produtor inicializa o namespace antes dele.
2. **Critério 2, primeira metade:** workspace suspenso **permanece suspenso**
   no reboot. O mecanismo que o segura é o filtro
   `should-start-on-boot=true` do `podman-restart` com `StoppedByUser=true`.
3. **Sonda falha + reinício recupera**, dentro do limite de reinícios.
4. **Critério 6:** bloqueio de rede válido, com controle positivo
   (github 200) e negativo (example.com 403).
5. Porta, IDs, trabalho não commitado e credenciais preservados.

### O que ainda falta neste boot

- **Critério 2, segunda metade:** retomar o `t2-pilot-scratch` e comprovar
  que preserva porta 34075, IDs e dados. Adiado de propósito: retomá-lo agora
  o tornaria de novo produtor legacy antes dos boots restantes.

---

## 6.5. Orca: excluído e depois REINTEGRADO por decisão do operador

**Histórico da decisão, em 2026-09-16:**

1. O operador decidiu ignorar o Orca e, mais tarde, removê-lo como dependência.
   Os itens de aceite ligados ao Orca foram marcados como excluídos.
2. **Na mesma sessão o operador voltou atrás:** o Orca volta ao plano como
   originalmente previsto, e ele mesmo criou um workspace pelo Orca para testar
   o reboot. **A exclusão está retirada.** Os itens de aceite do Orca voltam a
   ser pendentes:
   - critério 1: verificar manualmente a reconexão do Orca, sem `resume`
     corretivo;
   - critério 5: falhas de admissão não emitem JSON de sucesso ao Orca.

### Workspace criado pelo Orca

| Item | Valor |
| :--- | :--- |
| Workspace | `orca-6ac72f62-53d9-481f-8bf0-297ab6626bd7` |
| Repositório | `/home/v/Data/Projects/hexmed-stack` |
| Criado | 2026-09-16 17:10:32 |
| Runtime | **`legacy`** |
| Porta SSH | 46851 |
| Containers | `proxy`, **`fwd`**, `agent` — todos `unless-stopped`, rede `bridge` |
| `ASB_HOST_PORTS` | `80,5432,6379,8080` |

O `orca.yaml` e os shims de `hexmed-stack` foram conferidos antes: idênticos
aos do BlackICE, `orca-ide vm recipe doctor` com 6 checagens `pass`, sem `warn`
nem `fail`, receita versionada na branch primária. Não se usou `--provision`.

### O caminho de criação do Orca reinstalou o drop-in

Isto deixou de ser contexto e passou a afetar diretamente o plano de boots.
`recipes/create.sh` chama `asb-agent up` **sem `--runtime`**, portanto
`legacy`, e o ramo legacy de `up` chama `install.podman_restart()`
(`lifecycle.py:826`). Medido:

- o drop-in `agent-sandbox.conf` **voltou**, byte a byte idêntico ao backup, com
  mtime **17:10:32 — o mesmo segundo** de criação do workspace do Orca;
- `rootless_netns_producers` pela ferramenta:
  `dropin:agent-sandbox.conf(projeto)`, `unit:podman-restart.service`,
  `workspaces_rotulados:3`, `containers_sem_label:3`;
- o `podman-restart` iniciará no próximo boot o `asb-keyring` (`network=none`)
  **e os três containers do Orca em rede `bridge`**.

Consequência: **a desativação temporária do drop-in da §6.3 foi desfeita pelo
fluxo normal do Orca.** Todo workspace criado pelo Orca hoje nasce `legacy`,
reinstala o drop-in e vira produtor precoce do namespace. O runtime systemd
nunca é exercitado pelo caminho real de criação do Orca.

### O forwarder

O workspace do Orca tem um container `fwd`, que os workspaces do piloto não
têm, porque `hexmed-stack` publica portas de host. A §7 registra que o
forwarder pode precisar de recriação específica ao ser adotado. Nenhuma adoção
foi feita neste workspace.

## 6.6. Boot 3 — configuração real: REPROVADO, e com falha silenciosa

**Boot ID:** `019a9a43-8213-4dff-a8b9-8d6b27975594` (antes: `155a3648…`).
Primeiro boot na configuração de uso real: drop-in **ativo** (reinstalado pelo
Orca, §6.5), `t2-pilot-blackice` adotado, workspace do Orca **legacy** com
forwarder, `t2-pilot-scratch` suspenso. Autologin; nenhum comando corretivo.
Esperado antes do reboot: reproduzir a falha do boot 1.

### Linha do tempo medida

| Hora | Evento |
| :--- | :--- |
| 17:16:15 | boot do kernel |
| 17:16:45 | `network-online.target` |
| **17:16:46** | **`pasta` nasce** — 1 s após a rede, como no boot 1 |
| 17:16:46 | proxy adotado inicia |
| 17:16:47 | `podman-restart` (ExecMainStart), após o `ExecStartPre` do drop-in; sobe os 3 containers do Orca |
| 17:17:23 | proxy adotado: `timeout na sonda de egresso do proxy` |
| 17:18:03 | idem, 2ª tentativa |
| 17:18:43 | idem, 3ª tentativa |
| 17:18:52 | `Start request repeated too quickly` → **`start-limit-hit`** |

Mesmo motivo nas três tentativas, idêntico ao boot 1. A falha foi confirmada
por espera ativa até estado terminal, cobrindo `failed`, `active` e timeout.

### Workspace adotado: não se recuperou

Proxy `failed` após 3 reinícios; os dois containers `exited`. Nenhum comando
corretivo foi executado.

### Workspace do Orca (legacy): FALHA SILENCIOSA

| Verificação | Resultado |
| :--- | :--- |
| SSH na porta 46851 (o que o Orca usa para reconectar) | **OK**, `hostname=d4eef7acd56f` |
| Egresso agente → proxy → `github.com` | **`CONNECT tunnel failed, response 503`** |
| Host → `github.com` | HTTP 200 em 0,30 s |
| Rota dentro do proxy | `default via 10.89.5.1`; `aardvark-dns` rodando |
| Coletor | `ssh: healthy`, **`proxy: unreachable`** |
| Credenciais | `claude=authenticated`, `codex=authenticated` |

**Este é o achado mais grave do piloto.** O caminho legacy não tem sonda de
prontidão. Os três containers ficam `Up`, o SSH responde e o Orca consegue
reconectar — tudo parece funcionando —, mas **nenhum agente alcança API
alguma**. Nada acusa o defeito. No workspace adotado a sonda recusou publicar
prontidão; no legacy, ninguém pergunta.

### Terceiro ponto a favor da hipótese do namespace preso

| Boot | O que mantinha o namespace aberto | Adotado se recuperou? |
| :--- | :--- | :--- |
| 1 | drop-in + containers legacy do `t2-pilot-scratch` | **não** |
| 2 | Suspenso continua suspenso; retomado preserva porta, ID, trabalho não commitado e dados de serviço | **PARCIAL** — suspenso **permaneceu suspenso em dois reboots** (boots 2 e 3). Retomada e preservação ainda não medidas |
| 3 | drop-in + 3 containers legacy do Orca, estáveis | **não** |

A hipótese da §6.4 previa, **antes** deste boot, que o adotado não se
recuperaria enquanto os containers do Orca segurassem o namespace. A previsão
se confirmou. Isso a fortalece, mas **não a prova**: a destruição e recriação
do namespace segue inferida pelos carimbos, não observada.

### O que o boot 3 comprova

1. **A configuração de uso real falha no boot.** Com o drop-in e um workspace
   legacy, nenhum workspace tem egresso depois do reboot.
2. **O caminho legacy falha em silêncio**: SSH saudável, egresso morto.
3. **Critério 2:** `t2-pilot-scratch` permaneceu suspenso por mais um reboot
   (`exited`, `StoppedByUser=true`).
4. **§8.4:** credenciais intactas; trabalho não commitado idêntico byte a byte
   (HEAD `3bd3a1d`, sha256 `2c1a0f4c…` e `e0190ec7…`); IDs preservados.
5. **Sem recuperação automática** no adotado: `start-limit-hit`.

### Pendente neste boot

- **Reconexão do Orca, verificação manual do operador.** Pelo que foi medido,
  espera-se que o Orca **reconecte** (o SSH está saudável) e que isso **não**
  signifique workspace utilizável.

Evidência: `~/.local/state/agent-sandbox/t2-evidence/post-boot3-*`.

---

## 6.7. Validação pelo Orca BLOQUEADA por defeito do Orca

**Relato do operador em 2026-09-16, após o boot 3:** o Orca tem um defeito,
ainda não corrigido, ao **reidratar o terminal depois de um reboot**. Por isso
não é possível continuar os testes de reboot pelo Orca.

**Estado:** a verificação manual da reconexão do Orca (critério 1) está
**BLOQUEADA** — nem reprovada, nem excluída. A causa é externa ao
agent-sandbox, e o defeito não foi reproduzido nem investigado neste piloto;
está registrado conforme relatado pelo operador.

Isto não invalida o que foi medido no boot 3 pelo lado do sandbox: o SSH do
workspace do Orca respondeu, e o egresso estava morto (§6.6). O defeito de
reidratação do terminal é uma camada acima do SSH e não explica o 503.

### Por que o Orca cria workspaces `legacy`

Não é exigência do Orca. `recipes/create.sh` chama `asb-agent up` sem
`--runtime`, e o padrão de `up` é `legacy` (`cli/asb-agent:44`,
`default="legacy"`). Nenhuma variável de ambiente escolhe o runtime. O padrão é
intencional nesta fase: o plano coordenador deixa a "decisão de promover o
runtime" para o gate de aceite do T3, e proíbe migrar workspaces antes dele.

O caminho systemd do código cobre o forwarder (`start_forwarder` em
`lifecycle.py`, unidade `forwarder` no manifesto), que o `hexmed-stack` usa.
**Isso não foi exercitado no piloto real.**

### Consequência para o plano

T2 se prolonga. O que ainda pode avançar **sem** o Orca:

- a correção da inicialização do namespace (spec antes do código, pelo
  AGENTS.md), seguida da repetição dos boots afetados;
- a segunda metade do critério 2 (retomar o suspenso e medir preservação),
  que não exige reboot;
- a observação de renovação real de credencial, que depende só de tempo.

O boot com rede atrasada fica adiado: com a configuração atual ele reproduziria
uma falha já conhecida.

---

## 6.8. Troca para o runtime único (Emenda A, Task 13)

Executada em 2026-09-17, 12:42–12:50, com autorização do operador. Estado
anterior em `~/.local/state/agent-sandbox/t2-evidence/pre-troca.txt`; saída
da troca em `troca.log`, `up-blackice.json` e `up-*.err` no mesmo diretório.

### Resíduo de teste removido antes da troca

A inspeção prévia achou recursos `asb-test-*` de execuções anteriores
interrompidas: 4 containers, 2 redes e 34 volumes. O mais grave era
`asb-test-fwdold-c4051f9c-fwd` (`tests/integration/test_forwarder.py:52`), com
política `always` e rede `pasta`: subiria no boot pelo `podman-restart` e
criaria o namespace rootless cedo, contaminando justamente a medição da Task
14. Os dois outros containers vinham de `test_startup_auth.py`
(`startupupexist`, `startupkeyring`). Tudo foi removido; depois disso só o
`asb-keyring` estava marcado para subir no boot.

### Medições

| Verificação | Antes | Depois |
| :--- | :--- | :--- |
| `claude/.credentials.json` (sha256, 16 hex) | `c564e17795d34f2c` | `c564e17795d34f2c` |
| `codex/auth.json` (sha256, 16 hex) | `9069867d64caaef6` | `9069867d64caaef6` |
| `asb-keyring`: política / id | `unless-stopped` / `b7e8796615ea` | `no` / `71d444fe1081` (recriado 12:42:11) |
| drop-in `podman-restart.service.d/agent-sandbox.conf` | ausente | ausente |
| `asb-keyring.service`, `asb-network.service` | — | `active`, `active` |
| proxy e agente dos dois pilotos | — | `active` (quatro unidades) |
| `auth status` (BlackICE) | — | claude e codex `authenticated`; agy `unknown` (sem status local, como antes) |
| egresso a partir do agente | — | github.com 200; example.com negado (`CONNECT tunnel failed, response 403`) |
| trabalho não commitado do BlackICE | HEAD `3bd3a1d`, `M README.md`, `?? T2-PILOT-UNTRACKED.txt`, `2c1a0f4c5b73c5d7` / `e0190ec774262c94` | idêntico |
| `asb-agent doctor` | — | rc 0; drop-in ausente, espera por rede ativa, nenhum produtor alheio do namespace no boot |

O drop-in já estava ausente antes da troca (o `up` de `tests/test-auth.sh` o
removera, ver a lacuna de isolamento registrada na verificação das Tasks 1–12),
por isso o `up` não imprimiu a mensagem de remoção prevista no plano. As portas
SSH mudaram com a recriação: `t2-pilot-blackice` 45115, `t2-pilot-scratch`
42887.

### Suítes em shell com o keyring de produção (Step 6)

Primeira rodada: 8 de 11 com `falhou: 0` (agents-behind-proxy 9, lifecycle 7,
network 13, provision 5, recipe 39, services 9, toolcache 22, transaction 13).
Três falharam:

- **`test-reload-allowlist.sh` (4/8) — defeito real do runtime único.**
  `reload_allowlist` ainda usava `podman restart` no proxy. Sob o systemd o
  proxy roda como `start --attach` da unidade; o restart mata esse processo e
  o `ExecStopPost=podman stop` da unidade para o container recém-reiniciado
  (journal: `podman stop` PID 1438898 logo após o `restart` das 12:45:02).
  Corrigido em `777b00b` com `systemctl --user try-restart` da unidade do
  proxy; nova rodada 8/8.
- **`test-doctor.sh` (13/14) — teste desatualizado.** Ainda exigia a
  orientação `podman unshare --rootless-netns`, removida em `14f51bf`. Passa a
  exigir suspender e retomar, e a ausência do unshare; nova rodada 15/15.
- **`test-nested.sh` (abortado) — colisão de ambiente, não defeito.** O teste
  publica a porta fixa `127.0.0.1:18080`, que o workspace do BlackICE publica
  pelo perfil do projeto (`rootlessport listen tcp 127.0.0.1:18080: bind:
  address already in use`). Com a mesma suíte apontada para 18097, 8/8. O
  `up` reportou só `nao foi possivel determinar a porta SSH`, sem dizer que a
  unidade do agente falhou.

Nenhuma unidade `asb-test-*` sobrou. A primeira rodada deixou 14 volumes
`asb-test-*-session` (nenhum do nested); com as repetições, 17 foram
removidos. As repetições finais de doctor, reload e nested não deixaram
volume. A causa do vazamento não foi investigada.

### Pendências abertas pela troca

- `test-nested.sh` usa porta fixa do host e falha com qualquer workspace real
  que publique 18080.
- Volume de sessão vazado por testes em shell, de forma intermitente.
- O `up` não confere o estado das unidades depois de iniciar o target, e dá
  um erro enganoso quando o agente não sobe.
- Testes interrompidos deixam containers com política `always`, que voltam no
  boot seguinte.

---

## 7. Critérios de aceite (spec §8)

| # | Critério | Estado |
| :--- | :--- | :--- |
| 1 | Três boots reais, incl. rede com atraso de 60 s | **PARCIAL** — boot 1 (`5acb7550`) REPROVADO: o drop-in cria o namespace sem egresso e nada o repara (§6.2). Boot 2 (`155a3648`) APROVADO sem comando corretivo, com o drop-in desativado (§6.4), registrado como o cenário ativo+suspenso. Faltam: boot normal e boot com rede atrasada 60 s. Reconexão do Orca **pendente** — exclusão retirada pelo operador (§6.5) |
| 2 | Suspenso continua suspenso; retomado preserva porta, ID, trabalho não commitado e dados de serviço | **PARCIAL** — suspenso **permaneceu suspenso** no boot 2 (§6.4). Retomada e preservação ainda não medidas |
| 3 | Login real nos três fornecedores; cliente novo e dois workspaces; renovação observada ou pendente | **PARCIAL** — Claude (§5.2) e Antigravity (§5.3.1) reproduzidos e resolvidos individualmente; cliente novo e dois workspaces simultâneos utilizáveis nos três fornecedores (§5.3.2). **Em aberto:** Codex está `authenticated` por credencial de 2026-09-05 via symlink legado, não por login desta janela (§5.5); **renovação real não observada**; e dois workspaces do MESMO projeto com `publish_ports` não sobem juntos (§5.3.2) |
| 4 | Queda de rede não apaga credencial; sem reset global | **PARCIAL** — credenciais intactas nos três boots; indisponibilidade classificada como `unreachable`, não logout; nenhum reset global usado. **Recuperação automática reprovada** nos boots 1 e 3 (`start-limit-hit`). Cenário de queda de rede (fase d) não executado |
| 5 | Proxy ausente, porta 80 sem listener e keyring indisponível detectados | **PARCIAL** — falha de egresso do proxy foi detectada e a unidade **não** foi dada como pronta (§6.2, §6.4). Porta 80 e keyring indisponível não revalidados no piloto real. A parte "JSON de sucesso ao Orca" está **pendente** — exclusão retirada pelo operador (§6.5) |
| 6 | Bloqueios de rede válidos, com controles positivos de SSH e proxy | **SATISFEITO no boot 2** (§6.4) — egresso permitido github 200, negado example.com 403, SSH OK |
| 7 | Rollback de supervisão ensaiado sem perda de dados nem troca de porta | **SATISFEITO** (§6) — porta, IDs e trabalho não commitado preservados; ressalva: workspace criado pelo piloto |
| 8 | Dois dias de uso real sem reparo manual | **NÃO EXECUTADO** |

Nenhum critério está aprovado. O gate de autenticação continua aberto.

---

## 8. Fases pendentes e janelas

O plano exige acordar workspace e janela com o operador antes de **cada** ação
disruptiva, e não considerar espera sem resposta uma autorização.

### Decisões pendentes do operador

1. **`codex-auth.json` na raiz do volume (§5.4).** Remover agora que o login
   novo está confirmado, ou manter e aceitar a exposição registrada.
2. ~~**Guarda do agy.**~~ **RESOLVIDO** em §5.3.1: corrigida test-first e
   confirmada por chamada real (`authenticated`, exit 0).
3. **`publish_ports` fixas (§5.3.2).** Dois workspaces do mesmo projeto não
   sobem juntos. Decidir se a alocação passa a ser dinâmica (quebra o endereço
   previsível que o desenvolvedor espera) ou se a limitação é aceita e
   documentada no runbook de T3.

### Recursos criados por este piloto (a limpar ao final)

| Recurso | Origem |
| :--- | :--- |
| workspace `t2-pilot-blackice` (porta 45115 desde §6.8) | BlackICE |
| workspace `t2-pilot-scratch` (porta 42887 desde §6.8) | repo descartável |
| `/home/v/Data/Projects/t2-pilot-scratch` | criado para §5.3.2 |
| `/home/v/Data/Projects/BlackICE.bk` | backup pedido pelo operador |

| Fase | Conteúdo | Exige |
| :--- | :--- | :--- |
| (a) | **Quase completa.** Falta só: observação de renovação real (depende de tempo; a spec permite marcar pendente, nunca simular) | — |
| (b) | **CONCLUÍDA** (§6) | — |
| (c) | Três boots: normal; rede atrasada 60 s; um workspace ativo e outro suspenso | Reboots reais |
| (d) | Perda temporária de rede, sem apagar login e sem reset global | Interrupção de rede do desktop |

Ao final, restaurar `BlackICE.bk` se necessário e remover o workspace-piloto.
