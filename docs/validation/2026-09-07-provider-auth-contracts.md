# Contratos de Autenticação por Fornecedor e Protocolo de Validação

> **Data:** 2026-09-07  
> **Status:** Concluído (Parte Sintética & Documental) — Gate de Autenticação Aberto  
> **Contexto:** Etapa 0 (Tarefa A1) do redesenho de inicialização e autenticação (`docs/superpowers/plans/2026-09-07-startup-auth-redesign.md` e `2026-09-07-agent-authentication.md`).  
> **Escopo:** Caracterização técnica, empírica e documental dos contratos de autenticação dos três agentes suportados (Claude Code, OpenAI Codex e Google Antigravity), divergências históricas, delimitação de hipóteses de falha e runbook do piloto com operador.

---

## 1. Sumário Executivo

A investigação sintética, documental e de engenharia reversa nos binários instalados na imagem oficial (`localhost/agent-sandbox:latest`) revelou as causas fundamentais das falhas de autenticação relatadas em produção:

1. **Claude Code (2.1.263):**
   - **Divergência Crítica:** Ao contrário do presumido em documentações antigas (como `docs/domains/sandbox/failure-modes.md §20`, que afirmava que Claude usava `gnome-keyring`/`libsecret`), o binário do Claude Code no Linux **não utiliza Secret Service/keyring**. Ele armazena credenciais estritamente em arquivo texto plano em `~/.claude/.credentials.json` (ou `$CLAUDE_CONFIG_DIR/.credentials.json`) com permissões `0600`.
   - **Causa do Arquivo de 0 Bytes e Perda de Sessão:** O leitor interno do Claude abre o arquivo de credenciais explicitamente com `O_RDONLY | O_NOFOLLOW` e trata `ELOOP` como `refused-symlink`. Ao encontrar um symlink (como o provisionado por `image/entrypoint.sh`), o Claude se recusa a ler ou gravar nele. Paralelamente, `entrypoint.sh` continha a instrução `: > "$stored"`, criando proativamente um arquivo vazio de 0 bytes no volume persistente quando ele não existia. Ao tentar gravar ou substituir atômica (`rename`), o symlink é desvinculado ou rejeitado, mantendo o arquivo no volume com 0 bytes indefinidamente.
   - **Comando Inválido no Lifecycle Legado:** `cli/asb/lifecycle.py` executava `claude /login`, que no Claude 2.1.263 imprime `/login isn't available in this environment.` e encerra com código 0 sem realizar autenticação. O comando correto na CLI é `claude auth login`.

2. **OpenAI Codex (0.153.4):**
   - **Contrato Estável:** Utiliza `CODEX_HOME` (`~/.codex`) com `auth storage mode: File` gravando em `~/.codex/auth.json`.
   - **Verificação e Status:** `codex login status` retorna código 1 com `Not logged in` quando deslogado, e código 0 quando autenticado. Suporta `codex login --device-auth`.
   - **Sensibilidade a Mounts:** Sob substituição atômica (`os.replace` / `rename`), bind-mount de arquivo único falha com `EBUSY` (Errno 16) no Linux, exigindo montagem de diretório.

3. **Google Antigravity (1.1.27):**
   - **Contrato com Secret Service:** O binário `agy` comunica-se via D-Bus com o serviço `org.freedesktop.secrets` (Secret Service API provida pelo `gnome-keyring-daemon`).
   - **Dependência de Ambiente e SSH:** O binário inspeciona ativamente a variável `SSH_CONNECTION`. Quando detectada em conexões remotas não filtradas, ignora o cache local e força fluxo interativo de autorização.
   - **Ausência de Subcomando de Status:** O `agy` não possui `agy auth status` ou `agy login`. O comando de checagem legado `agy -p ping < /dev/null` **bloqueia por até 60 segundos** aguardando inserção de código de autorização em vez de falhar imediatamente. Keyring saudável no D-Bus não garante reconhecimento da conta pelo `agy`.

---

## 2. Matriz de Contratos por Fornecedor

| Fornecedor | Versão Fixada | Comando Nativo de Login | Comando de Status / Check | Destino Real no Linux | Tipo de Arquivo (Antes/Depois) | Modo de Armazenamento | Status Local Deslogado | Comportamento Symlink / Bind Mount |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Claude Code** | `2.1.263` | `claude auth login` *(suporta `--claudeai`, `--console`, `--sso`)* | `claude auth status --json` | `~/.claude/.credentials.json` | Regular `0600` (JSON com `claudeAi` / tokens) | Plaintext JSON (`fs/promises`) | Retorna 1; JSON `{"loggedIn": false, ...}` | **Recusa symlink com `O_NOFOLLOW` (`ELOOP`)**; bind-mount de arquivo falha `EBUSY` no `rename`; diretório montado funciona. |
| **OpenAI Codex** | `0.153.4` | `codex login --device-auth` | `codex login status` | `~/.codex/auth.json` | Regular `0600` (JSON com tokens de sessão) | File (`~/.codex/auth.json`) | Retorna 1; texto `Not logged in` | Bind-mount de arquivo falha com `EBUSY` em `rename`; diretório montado (`~/.codex`) funciona. |
| **Google Antigravity** | `1.1.27` | `agy` *(TUI interativa com OAuth URL e paste-code)* | Sem comando local nativo; `agy -p ping` (bloqueia 60s se deslogado) | `org.freedesktop.secrets` via D-Bus session bus | Entradas cifradas no keyring daemon (`login.keyring`) | Secret Service (`/run/asb-keyring/bus`) | Não responde status local; retorna prompt interativo | Não grava em arquivo direto no HOME do workspace; depende do socket do runtime e keyring compartilhado. |

---

## 3. Análise Detalhada dos Binários e Divergências Históricas

### 3.1 Claude Code: Análise Forense do Binário e a Divergência do Libsecret

A inspeção em profundidade do executável `/usr/bin/claude` (Node.js/Bun compilado) revelou as seguintes rotinas internas de persistência:

```javascript
import { lstat as h, mkdir as H, open as p } from "fs/promises";
import { basename as F, dirname as L, isAbsolute as _, join as D } from "path";

function f() {
    let e = Hy(); // Diretório base (~/.claude ou CLAUDE_CONFIG_DIR)
    return { storeDir: e, storePath: D(e, ".credentials.json") };
}

var P = s.O_NONBLOCK, c = 1048576;

async function b(e) {
    try {
        return { kind: "open", fileHandle: await p(e, s.O_RDONLY | s.O_NOFOLLOW | P) };
    } catch (r) {
        let n = A(r);
        if (n === "ELOOP") return { kind: "refused-symlink" };
        return { kind: "error", code: n };
    }
}
```

#### Achados Forenses:
1. **Divergência com a Documentação Antiga:**
   O documento `docs/domains/sandbox/failure-modes.md §20` afirmava:
   > *"Quando asb-agent login gravava credenciais, validava contra o daemon do container... Codex não era afetado porque grava direto em codex-auth.json... com a passphrase errada o agy falha enquanto o claude continua respondendo..."*
   Essa asserção pressupunha que Claude usava GNOME Keyring no Linux. A inspeção do binário provou que no Linux o Claude Code utiliza **exclusivamente armazenamento em arquivo (`.credentials.json`)**, sem qualquer chamada a D-Bus ou Secret Service.
2. **Rejeição Explícita de Symlinks (`O_NOFOLLOW` / `ELOOP`):**
   O Claude utiliza explicitamente as flags `O_RDONLY | O_NOFOLLOW` para leitura e `O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW` para escrita. Ao encontrar um symlink, o kernel Linux retorna `ELOOP` (Errno 40). O Claude captura esse erro e classifica internamente o estado como `refused-symlink`, tratando as credenciais como ausentes (`state: "absent"`).
3. **Escrita Atômica e Desvinculação do Volume:**
   Caso uma biblioteca ou rotina execute substituição atômica (`temporary.replace(target)`), o symlink criado pelo `entrypoint.sh` (`ln -s /run/asb-credentials/claude.json ~/.claude/.credentials.json`) é desvinculado: o arquivo de destino no volume persistente (`/run/asb-credentials/claude.json`) permanece intacto (com seus 0 bytes originais), enquanto `~/.claude/.credentials.json` transforma-se em um arquivo regular na camada volátil do container. Na reinicialização seguinte, o `entrypoint.sh` destrói o arquivo regular (`rm -rf "$real"`) e recria o symlink para o arquivo de 0 bytes.

### 3.2 OpenAI Codex: Análise de Armazenamento e Configuração Efetiva

A execução de `codex doctor` no container de produção retornou:

```text
Configuration
  ✓ config       loaded
      model                    <default> · openai
      cwd                      /
      config.toml              ~/.codex/config.toml
      MCP servers              0
      feature flags            47 enabled · 0 overridden
  ✗ auth         no Codex credentials were found — Run codex login or provide an API key...
      auth storage mode        File
      auth file                ~/.codex/auth.json
```

#### Achados Forenses:
1. O Codex utiliza `auth storage mode: File`, gravando em `~/.codex/auth.json`.
2. O subcomando `codex login status` é limpo e determinístico:
   - Saída: `Not logged in`
   - Código de saída: `1`
3. A precedência de configuração respeita:
   - Variável de ambiente `$CODEX_HOME` (padrão: `~/.codex`)
   - Argumento `-c, --config <key=value>`
   - `~/.codex/config.toml`
   - `auth.json` contém os tokens de acesso e refresh.

### 3.3 Google Antigravity: Análise de D-Bus, Secret Service e Sessão SSH

A análise de strings e chamadas de sistema no binário `/home/v/.local/bin/agy` (210 MB) revelou:
- `org.freedesktop.secrets`: 1 referência direta (interface D-Bus padrão da Secret Service API).
- `SecretService`: 24 referências.
- `keyring`: 176 referências.
- `SSH_CONNECTION`: 1 referência explícita no bloco de autenticação.

#### Achados Forenses:
1. **Comunicação com o Keyring:** O `agy` requer uma sessão ativa do D-Bus (`DBUS_SESSION_BUS_ADDRESS`) e comunicação com o serviço `org.freedesktop.secrets` fornecido pelo container singleton `asb-keyring`.
2. **Sensibilidade a Sessão SSH:** Ao detectar `SSH_CONNECTION`, `SSH_CLIENT` ou `SSH_TTY`, o `agy` assume que está sendo executado em um terminal remoto isolado e força o fluxo interativo de autorização via navegador/código, ignorando o keyring. O wrapper `cli/asb-guard` remove essas variáveis antes da execução do binário real.
3. **Ausência de Checagem Rápida e Bloqueio de 60s:**
   O `agy` não possui comando de verificação rápida de status. O comando `agy -p ping < /dev/null` não retorna imediatamente com erro quando deslogado; ele imprime a URL de autenticação e **aguarda 60 segundos por input** antes de abortar. Por isso, um check automatizado de status não pode usar `agy -p ping` sem timeout e tratamento específico.

---

## 4. Evidências Empíricas dos Testes de Integração

A suíte de testes implementada em `tests/integration/test_credential_writers.py` comprovou experimentalmente todos os comportamentos teóricos sob Linux kernel e Podman rootless (uid 1000):

```text
test_bind_mount_file_vs_directory_atomic_replace ... ok
test_claude_cli_behavior_on_credential_states ... ok
test_container_symlink_decoupling_under_atomic_replace_as_uid1000 ... ok
test_credential_target_states_absent_empty_corrupted_broken ... ok
test_uid1000_credential_read_write_permissions ... ok
test_o_nofollow_refuses_symlink_with_eloop ... ok
test_symlink_atomic_replace_decouples_target ... ok
----------------------------------------------------------------------
Ran 7 tests in 9.650s — OK
```

### 4.1 Falha de Symlink sob `replace()` Atômico
- **Teste:** `test_symlink_atomic_replace_decouples_target`
- **Resultado:** A substituição de um caminho que é um symlink por `replace()` desvincula o link. O arquivo apontado (`stored`) permanece com o conteúdo antigo (`"old"`), e o link se transforma em arquivo regular (`is_symlink() == False`).

### 4.2 Rejeição de Symlinks por `O_NOFOLLOW`
- **Teste:** `test_o_nofollow_refuses_symlink_with_eloop`
- **Resultado:** Abrir um symlink com `os.O_RDONLY | os.O_NOFOLLOW` levanta `OSError` com `errno.ELOOP` (Errno 40). Em arquivos regulares, a abertura é bem-sucedida. Isso comprova o mecanismo exato pelo qual o Claude Code 2.1.263 rejeita links simbólicos.

### 4.3 Bind-Mount de Arquivo vs Diretório sob `replace()`
- **Teste:** `test_bind_mount_file_vs_directory_atomic_replace`
- **Resultado:**
  - Montagem de arquivo individual (`-v /host/file:/mnt/target_file:z`): `os.replace('/mnt/tmp', '/mnt/target_file')` falha com `EBUSY` (Errno 16: *Device or resource busy*).
  - Montagem de diretório (`-v /host/dir:/mnt/target_dir:z`): `os.replace('/mnt/target_dir/tmp', '/mnt/target_dir/target_file')` tem sucesso atômico imediato.

### 4.4 Estados de Credenciais como UID 1000 no Container
- **Teste:** `test_credential_target_states_absent_empty_corrupted_broken`
- **Resultado:**
  - *Destino ausente:* Retorna `FileNotFoundError` (`ENOENT`).
  - *Arquivo de 0 bytes:* Leitura retorna string vazia `""`; `json.loads("")` levanta `json.decoder.JSONDecodeError` (*Expecting value: line 1 column 1*), explicando a corrupção/rejeição de estado.
  - *Arquivo corrompido:* Levanta `JSONDecodeError`.
  - *Symlink quebrado:* `is_symlink() == True`, mas `exists() == False`; abertura falha com `FileNotFoundError`.

### 4.5 Comportamento da CLI do Claude frente aos Estados
- **Teste:** `test_claude_cli_behavior_on_credential_states`
- **Resultado:** `claude auth status --json` retorna código 1 e `{"loggedIn": false}` para:
  1. Arquivo ausente.
  2. Arquivo vazio de 0 bytes (sintoma produzido pelo `entrypoint.sh`).
  3. JSON corrompido.
  4. Symlink quebrado.
  5. Symlink apontando para arquivo JSON válido (rejeição via `O_NOFOLLOW`).

---

## 5. Delimitação das Hipóteses de Falha

### 5.1 Hipótese Delimitada: Falha do Claude Code (Arquivo Vazio e Perda de Login)
1. **Inicialização do `entrypoint.sh`:** O script continha a rotina `[ -e "$stored" ] || { : > "$stored"; chmod 0600 "$stored"; }`. Isso criava `/run/asb-credentials/claude.json` com tamanho 0.
2. **Criação do Symlink:** O script executava `ln -s /run/asb-credentials/claude.json ~/.claude/.credentials.json`.
3. **Rejeição por `O_NOFOLLOW`:** O Claude Code tenta abrir o arquivo com `O_NOFOLLOW`, recebe `ELOOP` do kernel, classifica o symlink como `refused-symlink` e não lê nem escreve no alvo.
4. **Comando Legado Nulo:** `asb-agent login` executava `claude /login`, que no Claude 2.1 não inicia autenticação (`/login isn't available in this environment`).
5. **Conclusão:** O Claude nunca conseguiu autenticar ou persistir credenciais através do symlink; qualquer tentativa mantinha o arquivo de 0 bytes no volume.

### 5.2 Hipótese Delimitada: Falha do Antigravity (Keyring vs Reconhecimento de Conta)
1. **Confusão entre Keyring Saudável e Login Válido:** O fato de o container `asb-keyring` responder `org.freedesktop.secrets` no D-Bus não significa que exista um token do Google gravado. O keyring pode estar vazio ou desprovido do segredo do Antigravity.
2. **Ambiente SSH Scrubbing:** Conexões SSH sem o wrapper `asb-guard` injetam `SSH_CONNECTION`, fazendo o `agy` assumir login remoto interativo novo e desconsiderar o cache.
3. **Variável D-Bus:** Se a sessão SSH for iniciada sem carregar `/etc/environment` ou profile, `DBUS_SESSION_BUS_ADDRESS` estará ausente, impedindo o `agy` de consultar o keyring.
4. **Comportamento em Testes sem TTY:** `agy -p ping` sem autenticação trava por 60s aguardando input humano, induzindo o operador a achar que o comando congelou ou quebrou.

---

## 6. Protocolo de Validação Real (Gate de Autenticação — Runbook do Piloto)

> **2026-09-07 — roteiro abaixo suspenso. Não executar os comandos de §6.1–6.2.**
> A montagem em `/run/asb-credentials` aciona os mesmos symlinks recusados pelo
> Claude. Além disso, `--userns keep-id` não substitui `--user`: a imagem termina
> com `USER root` e o entrypoint executa `bash` sem baixar privilégios. O keyring
> exclusivo também não é preparado pelos comandos abaixo. O registro é mantido
> para rastreabilidade, não como instrução operacional.
>
> Usar o [piloto assistido atualizado](2026-09-07-auth-pilot-live.md).
> Nenhuma autenticação real nem aprovação de A1 é inferida dessa preparação.

O protocolo histórico abaixo ainda não havia sido executado pelo operador.

### 6.1 Pré-requisitos do Piloto
1. Volume exclusivo e isolado para credenciais do piloto:
   ```bash
   podman volume create asb-test-pilot-auth-credentials
   ```
2. Singleton de keyring do piloto ativo e responsivo em `/run/asb-keyring/bus`.
3. Conectividade direta de rede (sem proxy intermediário restritivo) no container de login.
4. Nenhuma credencial de produção deve ser copiada ou exposta em logs.

### 6.2 Roteiro de Execução com Operador

#### Etapa 1: Login Interativo por Fornecedor
Iniciar o container piloto de login isolado:
```bash
podman run -it --rm --name asb-pilot-login \
  --userns keep-id:uid=1000,gid=1000 \
  -v asb-test-pilot-auth-credentials:/run/asb-credentials:z \
  -v asb-test-pilot-keyring-runtime:/run/asb-keyring:ro,z \
  -e DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus \
  -w /home/v \
  localhost/agent-sandbox:latest bash
```

1. **Claude Code:**
   - Executar: `claude auth login`
   - O operador conclui a autenticação (navegador ou colagem do código de autorização).
   - Inspecionar metadados sem exibir o conteúdo do token:
     ```bash
     ls -la ~/.claude/.credentials.json
     test -s ~/.claude/.credentials.json && echo "Arquivo não-vazio gravado com sucesso"
     claude auth status --json
     ```
   - Confirmar se `loggedIn: true`.

2. **OpenAI Codex:**
   - Executar: `codex login --device-auth`
   - O operador segue as instruções do terminal para validar o código de dispositivo.
   - Inspecionar metadados:
     ```bash
     ls -la ~/.codex/auth.json
     codex login status
     ```
   - Confirmar código de saída 0 e status autenticado.

3. **Google Antigravity:**
   - Executar: `agy`
   - O operador realiza o fluxo interativo do OAuth Google até o fechamento da TUI.
   - Encerrar o container de login (`exit`).

#### Etapa 2: Validação em Cliente Novo (Cold Start)
Iniciar um **segundo container**, sem histórico de processos, montando o mesmo volume de credenciais:
```bash
podman run -it --rm --name asb-pilot-verify \
  --userns keep-id:uid=1000,gid=1000 \
  -v asb-test-pilot-auth-credentials:/run/asb-credentials:z \
  -v asb-test-pilot-keyring-runtime:/run/asb-keyring:ro,z \
  -e DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus \
  -w /home/v \
  localhost/agent-sandbox:latest bash
```

- Verificar Claude: `claude auth status --json` (deve retornar 0 e `loggedIn: true`).
- Verificar Codex: `codex login status` (deve retornar 0).
- Verificar Antigravity via sessão SSH simulada com `asb-guard`:
  - Garantir que `SSH_CONNECTION` é removida.
  - Executar comando de teste mínimo real com timeout explícito de 15s.

#### Etapa 3: Validação de Concorrência e Renovação de Token
1. Iniciar dois containers de workspace simultaneamente (`ws-1` e `ws-2`) compartilhando o volume.
2. Executar chamadas em paralelo em ambos.
3. Se ocorrer renovação de token (`refresh_token` acionado por expiração natural), observar:
   - O arquivo no volume foi atualizado?
   - O outro container continuou operacional ou perdeu a sessão?
   - *Nota:* Não alterar o relógio da máquina nem adulterar tokens artificialmente. Caso a renovação natural não ocorra durante a janela do piloto, registrar como `pending` e acompanhar até a Etapa T2.

---

## 7. Critérios de Decisão para a Etapa 2 (Tarefas A3 e A4)

1. **Abandono Definitivo de Symlinks para Arquivos Únicos de Credenciais:**
   - Os testes provaram categoricamente que symlinks quebram sob substituição atômica e são rejeitados pelo `O_NOFOLLOW` do Claude Code.
   - A solução de persistência deve compartilhar o **diretório que contém as credenciais** (ex: bind mount ou volume mount do diretório pai, como `/home/v/.claude/` e `/home/v/.codex/`), ou gerenciar o ciclo de persistência sem symlinks intermediários individuais.
2. **Substituição dos Comandos de Login e Verificação:**
   - Atualizar `cli/asb/lifecycle.py` para usar `claude auth login` em vez de `claude /login`.
   - Implementar em `cli/asb/auth.py` (Tarefa A2) a separação rigorosa entre status de infraestrutura (keyring/rede) e status de conta do fornecedor, usando `parse_claude_status` e `parse_codex_status`.
