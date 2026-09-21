# Contratos de Sessão dos Drivers de Provedor (Tarefa 5)

- **Data:** 2026-09-17
- **Contexto:** Tarefa 5 do plano `docs/superpowers/plans/2026-09-17-agent-sandbox-tui.md` — drivers de provedor com suporte explícito a resume (`cli/asb/agents/`).
- **Escopo:** Caracterização dos binários `codex`, `claude` e `agy` instalados no HOST de planejamento, executando apenas `--version` e `--help`. Nenhum prompt foi enviado, nenhuma sessão foi iniciada, nenhuma API de provedor foi contatada. Este documento não caracteriza os binários da IMAGEM do container — isso exige um container e fica fora do escopo desta tarefa (ver `agy` na matriz abaixo).
- **Sanitização:** Nenhum caminho completo do HOME do operador, identificador de conta ou conteúdo de transcript aparece abaixo. Locais de estado são descritos por forma (placeholders `<...>`), nunca pelo valor observado neste host.

---

## 1. Matriz de contratos

| provider | version (HOST, observado 2026-09-17) | launch | resume | session-id-source | decision |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **codex** | `codex-cli 0.154.0` (via `codex --version`) | `codex --help` lista `codex [OPTIONS] [PROMPT]`; nenhuma flag além do prompt posicional é necessária para lançar uma sessão interativa nova. | `codex --help` lista o subcomando `resume` ("Resume a previous interactive session"), aceitando um id de sessão como argumento posicional. Confirmado presente no `--help` do binário de HOST. | **Comprovado para instalação de HOST, apenas.** `$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<timestamp>-<uuid>.jsonl` (raiz de estado: `$CODEX_HOME` se definido, senão `~/.codex`; ver §2.1). Exatamente um arquivo `.jsonl` novo cuja primeira linha é um registro JSON `{"type": "session_meta", "payload": {"id": "<uuid>", ...}}` — o `id` é o provider-session-id. Zero ou múltiplos arquivos novos ⇒ `None`. **Não comprovado para sandbox:** um agente em sandbox grava seu estado de sessão no volume por-workspace `asb-<ws>-session`, montado sobre `.codex/sessions` do container sob um nome de diretório diferente (`codex-sessions/`); a raiz de varredura padrão do driver, do lado do host, não enxerga sessões de sandbox. Isso fica gated no checkpoint humano, com um container disponível. | `resume_supported=True` quando a opção `resume` está presente no `--help` (comprovado neste host, instalação de HOST). |
| **claude** | `2.1.275 (Claude Code)` (via `claude --version`) | `claude --help` lista `claude [options] [command] [prompt]`; nenhuma flag obrigatória para lançar uma sessão interativa nova. | `claude --help` lista `-r, --resume [value]` ("Resume a conversation by session ID, or open interactive picker"). Confirmado presente no `--help` do binário de HOST. | **Comprovado para instalação de HOST, apenas.** `~/.claude/projects/<slug(cwd)>/<uuid>.jsonl`, onde `slug(cwd)` substitui cada `/` e `.` do caminho absoluto do cwd por `-`. O UUID vem do **nome do arquivo** — nenhum conteúdo é lido. Exatamente um arquivo `.jsonl` novo no diretório do projeto ⇒ seu stem é o provider-session-id; zero ou múltiplos ⇒ `None`. (Verificação cruzada, não usada pelo driver: o próprio JSON de uma entrada nesse arquivo carrega um campo de metadado `sessionId` cujo valor é idêntico ao nome do arquivo — confirmado empiricamente neste host examinando apenas o nome de um campo, nunca seu conteúdo de conversa.) **Não comprovado para sandbox:** um agente em sandbox grava seu estado de sessão no volume por-workspace `asb-<ws>-session`, montado sobre `.claude/projects` do container sob um nome de diretório diferente (`claude-projects/`); a raiz de varredura padrão do driver, do lado do host, não enxerga sessões de sandbox. Isso fica gated no checkpoint humano, com um container disponível. | `resume_supported=True` quando a opção `--resume` está presente no `--help` (comprovado neste host, instalação de HOST). |
| **agy** | `1.2.5` (via `agy --version`) | `agy --help` (`Usage of agy:`) não exige nenhuma flag para uma sessão interativa nova. | `agy --help` lista `--conversation` ("Resume a previous conversation by ID"). **Presente no binário de HOST**, mas isso não basta: ver decisão. | **Não comprovado neste host.** Nenhum diretório de estado local foi encontrado para `agy` nos locais convencionais verificados (equivalentes a `~/.agy`, `~/.config/agy`, `~/.local/share/agy` — todos ausentes neste host). Sem um diretório observável para monitorar antes/depois do lançamento, não há como isolar um candidato a provider-session-id sem iniciar uma sessão real (fora do escopo desta tarefa). `discover_session_id()` retorna sempre `None`. | `resume_supported=False` neste host, apesar de `--conversation` existir no `--help` do binário de HOST — **a fonte do session-id não está provada, e a especificação proíbe anunciar resumption não provada.** **O binário da IMAGEM do container é o gate autoritativo real** para esta opção (spec/brief); só pode ser confirmado após o checkpoint humano, com um container disponível. Este documento registra apenas a observação de HOST. |

> As versões acima descrevem só o binário de HOST, na data indicada, e
> podem mudar num host atualizado depois desta observação. A versão da
> IMAGEM do container é outra coisa e não é fixada pelo build: cada build
> reinstala `claude`, `codex` e `agy` via mise `latest` e grava o que
> resolveu em `/opt/asb-mise/versions` (ver §4.4 para os valores desta
> build).

---

## 2. Notas de caracterização

### 2.1 Codex — raiz de estado

O binário honra a variável de ambiente `CODEX_HOME` para relocar todo o seu diretório de estado (`sessions/`, `auth.json`, `history.jsonl`, etc. — confirmado observando dois HOMEs distintos neste host, um com `$CODEX_HOME` exportado e outro sem, ambos com a mesma estrutura `sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`). O driver usa `$CODEX_HOME` quando definido, e cai para `~/.codex` como padrão documentado do próprio Codex CLI. Nenhum valor real de `$CODEX_HOME` nem nome de arquivo observado é reproduzido aqui — apenas a forma do caminho.

A primeira linha de um `rollout-*.jsonl` observado neste host tem o formato:

```json
{"timestamp": "...", "ordinal": 0, "type": "session_meta", "payload": {"session_id": "<uuid>", "id": "<uuid>", "timestamp": "...", "cwd": "...", "originator": "...", "cli_version": "...", "source": "...", "thread_source": "...", "model_provider": "...", "base_instructions": "...", "history_mode": "...", "context_window": "...", "git": {...}}}
```

O driver lê **apenas esta primeira linha** (metadado de sessão) e usa `payload["id"]` — nunca `payload["session_id"]` (ambos observados idênticos neste host, mas o brief especifica `id`) — e nunca abre ou lê as linhas seguintes (que são o transcript real da conversa).

### 2.2 Claude — slug do diretório de projeto

`~/.claude/projects/` contém um subdiretório por checkout, cujo nome é derivado do caminho absoluto do cwd substituindo `/` e `.` por `-`. Confirmado empiricamente neste host: o diretório correspondente ao cwd desta própria tarefa tinha exatamente o nome esperado por essa regra (incluindo o `.worktrees` do caminho, que produz um `--` duplo por causa da junção do `/` anterior com o `.` inicial). Apenas essas duas substituições (`/` e `.`) foram comprovadas a partir de um único caminho observado; o driver não generaliza para outros caracteres não alfanuméricos sem prova adicional.

Dentro desse diretório, cada sessão grava um arquivo `<uuid>.jsonl` cujo nome já é o identificador de sessão — o driver nunca precisa abrir o arquivo. Como verificação adicional (não usada pelo driver de produção, apenas para confirmar a hipótese), a primeira linha de um arquivo observado neste host continha um campo de nível superior chamado `sessionId` cujo valor era idêntico ao nome do arquivo; nenhum outro campo dessa linha (que também define `type`) foi necessário ou é lido pelo driver.

### 2.3 Antigravity — ausência de estado local

Uma busca pelos locais convencionais de estado de uma CLI (variantes de diretório de configuração/dados sob o HOME) não encontrou nenhum diretório para `agy` neste host, o que é consistente com uma instalação sem histórico de sessões locais. Isso não prova que `agy` nunca persiste estado local — apenas que, neste host e nesta instalação, nenhum local foi encontrado sem iniciar uma sessão real (fora do escopo). Por isso `AntigravityDriver` nunca declara uma raiz de estado (`scan_root` é sempre `None`), `capture_before`/`capture_after` são sempre vazios, e `discover_session_id` sempre retorna `None`.

### 2.4 Limite desta tarefa

Nenhum comando além de `--version` e `--help` foi executado em qualquer um dos três binários. Nenhum comando foi observado travar ou parecer interativo — os três respondem `--version`/`--help` imediatamente. Nenhuma credencial, token, identificador de conta ou conteúdo de transcript foi lido ou reproduzido neste documento.

---

## 3. Decisão consolidada

- `CodexDriver` e `ClaudeDriver`: `resume_supported=True` é alcançável (opção confirmada no `--help` do binário de HOST **e** fonte de session-id comprovada **para instalação de HOST**). A fonte de session-id para um agente rodando em sandbox permanece não comprovada nesta tarefa — o volume por-workspace `asb-<ws>-session` monta o estado de sessão sob nomes de diretório diferentes dos usados no HOST (`codex-sessions/`, `claude-projects/`), então as raízes de varredura padrão dos drivers não os alcançam; a redesenho dessas raízes fica gated no checkpoint humano, com um container disponível (mesmo tratamento dado ao Antigravity abaixo). `probe()` ainda pode reportar `False` em runtime se o `--help` real não confirmar a opção (ex.: versão diferente na imagem).
- `AntigravityDriver`: `resume_supported` nunca é `True` neste host, mesmo com `--conversation` presente no `--help`, porque a fonte do session-id não está provada. O binário da imagem do container permanece o gate autoritativo desta capacidade; a revalidação com container faz parte do checkpoint humano após a Tarefa 5, não desta tarefa.

---

## 4. Revisão após o piloto (2026-09-19)

O piloto (rodada 5) mostrou que a descoberta por arquivo novo não
funciona para um agente real em sandbox: o Claude e o Codex só criam o
arquivo de sessão na primeira mensagem, depois da janela de cinco
tentativas. As decisões abaixo substituem, para o sandbox, a fonte de
session-id da matriz da §1.

### 4.1 Claude — id atribuído no lançamento

- O manager gera um UUID (`uuid4`), grava-o como `providerSessionId` na
  escrita `starting`, antes de lançar, e o driver lança
  `claude --session-id <uuid> --dangerously-skip-permissions`. O resume é
  `claude --resume <uuid> --dangerously-skip-permissions` (o id vem logo
  depois de `--resume`, cujo valor é opcional). Nenhuma descoberta roda
  para o Claude; o driver não varre `claude-projects/`.
- O driver só aceita um UUID canônico (minúsculas, com hífens), que também
  satisfaz `ProviderSessionId`.
- Binário da IMAGEM (`localhost/agent-sandbox:latest`), num container
  descartável, só `--help` — a versão observada nesta medição,
  `2.1.263 (Claude Code)`, foi superada pela troca da imagem para mise
  `latest` (§4.4); o valor de cada build fica registrado em
  `/opt/asb-mise/versions` (`claude=2.1.276` nesta build): lista
  `--session-id <uuid>` ("must be a valid UUID"), `-r, --resume [value]` e
  `--dangerously-skip-permissions`. `claude … --help` sai 0 até com uma
  flag inexistente, então o `--help` NÃO prova que o argv completo é
  aceito; isso só um lançamento real prova (fora do escopo: nenhuma
  conversa foi iniciada).

### 4.2 Modo de permissão

Claude e Codex lançam e retomam sem prompts de permissão, como o Orca os
lança: o sandbox é a fronteira de isolamento. Codex:
`codex --dangerously-bypass-approvals-and-sandbox` e
`codex resume --dangerously-bypass-approvals-and-sandbox <id>` (a forma
`codex resume [OPTIONS] [SESSION_ID]` do `--help` do binário da imagem
observado nesta medição, `codex-cli 0.153.4` — superado pela troca da
imagem para mise `latest`, §4.4). Ali o `--help` discrimina: as duas
formas saem 0 e `codex resume` com uma flag inexistente sai 2.
Antigravity não recebe flag de bypass.

### 4.2.1 Trust do diretório (Codex)

O Codex guarda os diretórios confiados na tabela `projects` de
`~/.codex/config.toml`. No sandbox esse arquivo vive no volume
COMPARTILHADO de credenciais e o manifesto de config do entrypoint o copia
do host a cada start do container: uma entrada por workspace seria
disputada entre checkouts e apagada no start seguinte, e o caminho do
sandbox nunca coincide com um caminho do host. Por isso o driver NÃO
escreve nada nesse arquivo (nem o lê): passa o trust como override POR
LANÇAMENTO na linha de comando, no lançamento e no resume, escopado ao
checkout de execução da sessão (`ConnectionInfo.project_root`, o mesmo
`cwd` que o driver já recebe):

```
codex --dangerously-bypass-approvals-and-sandbox \
      -c projects."<cwd>".trust_level="trusted"
codex resume --dangerously-bypass-approvals-and-sandbox <id> \
      -c projects."<cwd>".trust_level="trusted"
```

Medido no binário da IMAGEM (`codex 0.155.0` — o valor que o mise
`latest` resolveu nesta build, registrado em `/opt/asb-mise/versions`,
ver §4.4; não é uma versão fixada —, containers `--rm` descartáveis,
nenhuma conversa iniciada):
- `codex --help` e `codex resume --help` listam `-c, --config <key=value>`
  ("Use a dotted path (`foo.bar.baz`) to override nested values. The
  `value` portion is parsed as TOML").
- `codex doctor -c projects."/root".trust_level="trusted"` reporta
  `✓ config loaded`; `codex doctor -c badkey` reporta
  `✗ config could not be loaded`. Ou seja, o override com caminho citado
  na chave pontilhada é de fato parseado e aceito.
- Depois do posicional também vale: `codex resume --dangerously-bypass-…
  <uuid> -c badkey` sai com `Error parsing -c overrides: Invalid override
  (missing '='): badkey`, e com o override válido chega a `Error: stdin is
  not a terminal`. Por isso o `-c` vai no FIM do argv e o id continua
  exatamente onde estava.
- A tabela é `projects` e o campo é `trust_level` com o valor `trusted`
  (strings do binário: `struct ProjectConfig with 1 element`,
  `trust_level`, `trusted`, `failed to persist trusted project state`).

Um `=` no caminho é recusado por um motivo diferente e mais grave: o `-c`
parte o argumento em `key=value` no PRIMEIRO `=`, então um `=` dentro da
chave citada a parte ao meio. Medido:
`codex doctor -c 'projects."/work/a=b".trust_level="trusted"'` reporta
`✗ config could not be loaded` — a sessão nem começaria, o que é pior que
voltar ao prompt de trust. Já um caminho com aspa embutida
(`projects."/a"b".trust_level="trusted"`) o Codex ACEITA em silêncio, com
uma chave errada: o binário não protege contra isso, só a omissão do
driver protege.

A forma de lançamento também foi conferida: `codex
--dangerously-bypass-approvals-and-sandbox -c badkey` sai com
`Error parsing -c overrides: Invalid override (missing '='): badkey`,
provando que o `-c` depois da flag de bypass é parseado.

NÃO verificado: que o override suprime a pergunta de trust numa sessão
real — isso exige um TTY e uma conversa de verdade, fora do escopo desta
validação. O que está provado é o nome da chave, o valor, e que a forma
citada parseia e é carregada.

Segurança: a chave TEM de ser citada (uma chave nua de TOML não aceita
`/`) e a citação não é escapada, então um `cwd` com aspa dupla,
contrabarra, `=` ou caractere de controle (inclusive quebra de linha) faz
o driver OMITIR a flag inteira — o Codex volta a perguntar pelo trust, nunca
recebe um TOML quebrado. O argv atravessa `ssh_argv` (`shlex.join`, um
elemento por vez) e o `tmux new-session -- <argv>` com dois ou mais
elementos faz exec direto, então as aspas chegam literais ao binário.

### 4.3 Como cada provedor obtém o id (estado atual)

**Claude.** Nenhuma descoberta: o manager gera um UUID (`uuid4`), grava-o
como `providerSessionId` na escrita `starting`, antes de lançar, e lança
`claude --session-id <uuid> --dangerously-skip-permissions`; o resume é
`claude --resume <uuid> --dangerously-skip-permissions` (ver 4.1).

**Codex.** Evidência do piloto: uma única sessão produziu DOIS rollouts na
primeira mensagem, ~5 s depois da primeira escrita da sessão (fora da
janela de cinco tentativas), ambos com o cwd exato da sessão — o thread do
usuário (`source: "cli"`, `thread_source: "user"`, sem
`parent_thread_id`) e um subagente (`source: {"subagent": …}`,
`thread_source: "guardian_review"`, com `parent_thread_id` e
`multi_agent_version`), aberto por `approvals_reviewer = "auto_review"`.

Regra de candidato (só a primeira linha, `session_meta`, é lida):
- cwd exato da sessão; arquivo regular, sem seguir symlink, sem bloquear em
  FIFO, primeira linha de no máximo 64 KiB; uma linha que o parser JSON
  recusa (inclusive `[` aninhado além da recursão ou um inteiro além do
  limite de dígitos) não dá id e nunca levanta;
- thread do usuário: sem `parent_thread_id`, `source` string e
  `thread_source == "user"` (um `codex exec` não é a sessão);
- `payload.timestamp` com fuso, igual ou posterior ao `startedAt` da
  sessão, gravado arredondado PARA CIMA ao segundo (o store guarda
  segundos inteiros);
- o instante não cai na vida de NENHUMA outra sessão do mesmo agente e cwd,
  viva ou final, com ou sem id (uma sessão com id pode abrir outro thread
  do usuário, como o `/new` do Codex). A vida vai de 1 s antes do
  `startedAt` gravado ao `endedAt` — carimbado pelo store, arredondado para
  cima, na primeira escrita de `completed`/`failed` —, aberta sem ele; um
  registro sem `startedAt` contém todo instante;
- o id não é o `providerSessionId` de outra sessão guardada.

Quando: na janela do start (cinco tentativas, 1 s entre elas, contra o
instantâneo pré-lançamento); de novo, preguiçosamente, quando uma sessão
sem id sonda ALIVE (reconcile/attach) ou DEAD; e uma última vez logo antes
de gravar `completed`, para que a sessão reclame o próprio rollout antes de
a sua vida fechar. Em toda tentativa a varredura vem primeiro e as
sessões guardadas são lidas depois. Exatamente um candidato → gravado, na
mesma escrita da classificação; zero ou vários → nada. Um registro sem
`startedAt` nunca faz descoberta preguiçosa.

Verificação na história de HOST do operador (só leitura, só a primeira
linha de cada `~/.codex/sessions/**/*.jsonl`, só contagens): 167 arquivos,
todos `session_meta`; 144 com `parent_thread_id`, 144 com `source` objeto,
os mesmos 144 nos dois conjuntos (0 com só um dos marcadores); 23 sem
nenhum, todos com `source` string e `thread_source: "user"`; os 167 com
`payload.timestamp` ISO-8601 com fuso.

### 4.4 Troca para mise `latest` na imagem (2026-09-19)

A imagem deixou de fixar versões: `claude`, `codex` e `agy` vêm do mise
(backends aqua do host, `latest` no build) e a versão de cada build fica em
`/opt/asb-mise/versions`. As versões citadas em 4.1 e 4.2 (`2.1.263`,
`0.153.4`) são as da caracterização, não mais as da imagem. Rechecado no
primeiro build pós-troca (`claude=2.1.276`, `codex=0.155.0`, `agy=1.2.6`),
container descartável, só `--help`, HOME temporário:
- Claude ainda lista `--session-id <uuid>`, `-r, --resume [value]` e
  `--dangerously-skip-permissions`.
- Codex ainda mostra `codex resume [OPTIONS] [SESSION_ID] [PROMPT]` com
  `--dangerously-bypass-approvals-and-sandbox`, e `codex resume` com flag
  inexistente ainda sai 2.
Um rebuild pode trazer outra versão; estes `--help` são o que rechecar.
