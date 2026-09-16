# Piloto real de inicialização e autenticação — T2

- **Tarefa:** T2 do plano
  [`2026-09-07-startup-auth-redesign.md`](../superpowers/plans/2026-09-07-startup-auth-redesign.md)
- **Spec:** §7 (migração e retorno) e §8 (aceitação) do
  [desenho](../superpowers/specs/2026-09-07-startup-auth-redesign-design.md)
- **Status:** EM EXECUÇÃO — preparação concluída, cenários disruptivos não
  executados
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
| symlinks no volume | 1 | **0** |

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

## 7. Critérios de aceite (spec §8)

| # | Critério | Estado |
| :--- | :--- | :--- |
| 1 | Três boots reais, incl. rede com atraso de 60 s | **NÃO EXECUTADO** |
| 2 | Suspenso continua suspenso; retomado preserva porta, ID, trabalho não commitado e dados de serviço | **NÃO EXECUTADO** |
| 3 | Login real nos três fornecedores; cliente novo e dois workspaces; renovação observada ou pendente | **PARCIAL** — Claude (§5.2) e Antigravity (§5.3.1) reproduzidos e resolvidos individualmente; cliente novo e dois workspaces simultâneos utilizáveis nos três fornecedores (§5.3.2). **Em aberto:** Codex está `authenticated` por credencial de 2026-09-05 via symlink legado, não por login desta janela (§5.5); **renovação real não observada**; e dois workspaces do MESMO projeto com `publish_ports` não sobem juntos (§5.3.2) |
| 4 | Queda de rede não apaga credencial; sem reset global | **NÃO EXECUTADO** |
| 5 | Proxy ausente, porta 80 sem listener e keyring indisponível detectados | Coberto por suíte automatizada; **não revalidado no piloto real** |
| 6 | Bloqueios de rede válidos, com controles positivos de SSH e proxy | Controles positivos observados na preparação (§3); **cenário negativo não reexecutado aqui** |
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
| workspace `t2-pilot-blackice` (porta 45379) | BlackICE |
| workspace `t2-pilot-scratch` (porta 34075) | repo descartável |
| `/home/v/Data/Projects/t2-pilot-scratch` | criado para §5.3.2 |
| `/home/v/Data/Projects/BlackICE.bk` | backup pedido pelo operador |

| Fase | Conteúdo | Exige |
| :--- | :--- | :--- |
| (a) | **Quase completa.** Falta só: observação de renovação real (depende de tempo; a spec permite marcar pendente, nunca simular) | — |
| (b) | **CONCLUÍDA** (§6) | — |
| (c) | Três boots: normal; rede atrasada 60 s; um workspace ativo e outro suspenso | Reboots reais |
| (d) | Perda temporária de rede, sem apagar login e sem reset global | Interrupção de rede do desktop |

Ao final, restaurar `BlackICE.bk` se necessário e remover o workspace-piloto.
