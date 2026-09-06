# Singleton Secret Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:test-driven-development` while implementing each task and
> `superpowers:verification-before-completion` before the handoff.

**Goal:** Persistir os logins de Claude Code e Antigravity de forma confiável,
fazendo login e workspaces consumirem uma única instância de Secret Service.

**Architecture:** Um container global sem rede é o único proprietário do D-Bus,
gnome-keyring e arquivos cifrados. Um volume de runtime compartilha apenas o
socket com containers clientes. Codex e o fallback legado do Claude continuam
usando os arquivos já persistidos no volume de credenciais.

**Tech Stack:** Python 3.11, Bash, Podman rootless, D-Bus, gnome-keyring,
libsecret, `unittest` e testes shell.

**Spec:**
[`docs/superpowers/specs/2026-09-06-singleton-secret-service-design.md`](../specs/2026-09-06-singleton-secret-service-design.md)

## Global Constraints

- Comece somente depois de concluir e testar o plano de recuperação do uplink.
- Execute as tarefas em ordem; elas deliberadamente compartilham
  `lifecycle.py` e `entrypoint.sh`.
- Trabalhe na branch fornecida pelo humano; não crie outro worktree.
- Não faça commit, não execute `graphify update .` e não altere
  `graphify-out/**`. Entregue o diff sem commit para revisão do Codex. Depois da
  revisão e do gate humano, o `commit-curator` fará o commit de código e o
  Graphify será sincronizado em um segundo commit.
- Nunca use o volume real `asb-credentials` nos testes. Todo teste de integração
  deve gerar nomes únicos, volumes descartáveis e cleanup por `trap`.
- Não execute `tests/test-auth.sh` antes de isolá-lo: a versão atual escreve em
  `codex-auth.json` do volume real e pode invalidar o login do operador.
- Não faça login real automaticamente e nunca imprima tokens ou conteúdo de
  keyrings.

## Task 1: Criar um teste de regressão isolado para o Secret Service

**Files:**

- Add: `tests/test-keyring-service.sh`
- Modify: `tests/test-auth.sh`

- [ ] **Step 1: Isolar o teste legado antes de executá-lo**

  Substitua qualquer referência fixa a `asb-credentials` por um volume de teste
  único criado no início do script. Registre containers e volumes exatos e
  remova-os em `trap cleanup EXIT`. Não leia nem escreva o volume de produção.

- [ ] **Step 2: Escrever o teste concorrente que falha na arquitetura atual**

  O novo teste deve, sem credenciais reais:

  1. criar volumes únicos de credenciais e runtime;
  2. iniciar o serviço global sob um nome único ou via overrides internos;
  3. iniciar dois clientes simultâneos ligados ao mesmo socket;
  4. gravar um item fictício com `secret-tool store` no cliente A;
  5. ler o mesmo item no cliente B;
  6. remover os clientes, reiniciar o serviço e ler o item em um cliente C;
  7. confirmar que nenhuma passphrase aparece em `podman inspect` dos clientes.

  Use uma chave e valor sintéticos, por exemplo
  `service=asb-test account=integration`, nunca dados de fornecedor.

- [ ] **Step 3: Confirmar a falha esperada**

  Run:

  ```bash
  bash tests/test-keyring-service.sh
  ```

  Expected: falha antes da implementação porque não existe serviço/socket
  singleton compartilhado. Registre o ponto exato da falha.

## Task 2: Transformar `start-keyring.sh` em serviço singleton

**Files:**

- Modify: `image/start-keyring.sh`
- Modify: `image/Containerfile`
- Modify: `tests/test-keyring-service.sh`

- [ ] **Step 1: Definir o contrato do processo**

  `image/start-keyring.sh` deve rodar como uid 1000 e:

  - exigir `/run/asb-keyring-pass` legível;
  - criar `/run/asb-keyring` e remover somente um socket stale dentro desse
    diretório explícito;
  - iniciar um session bus no endereço fixo
    `unix:path=/run/asb-keyring/bus`;
  - desbloquear/inicializar apenas o componente `secrets` do gnome-keyring com
    stdin vindo do arquivo de passphrase;
  - permanecer em foreground e propagar falha dos processos filhos;
  - encerrar os filhos ao receber `TERM`/`INT`.

  Não emita a passphrase, variáveis sensíveis ou conteúdo do keyring.

- [ ] **Step 2: Garantir dependências explícitas na imagem**

  Confirme que a imagem contém `dbus-daemon`, `dbus-send`,
  `gnome-keyring-daemon` e `secret-tool`. Adicione pacote somente se um binário
  realmente estiver ausente; não altere versões de CLIs sem necessidade.

- [ ] **Step 3: Construir e executar o teste focal**

  Run:

  ```bash
  asb-agent build
  bash tests/test-keyring-service.sh
  ```

  Expected nesta etapa: o serviço isolado fica saudável e preserva o item de
  teste entre clientes e restart. A integração com `lifecycle.py` ainda não é
  exigida.

## Task 3: Adicionar o ciclo de vida do serviço global

**Files:**

- Modify: `cli/asb/lifecycle.py`
- Modify: `tests/unit/test_auth.py`
- Modify: `tests/unit/test_lifecycle.py`

- [ ] **Step 1: Escrever testes unitários que falham**

  Cubra os contratos abaixo sem Podman real:

  - `ensure_keyring_runtime_volume()` cria o volume uma vez e é idempotente;
  - `ensure_keyring_service()` cria `asb-keyring` com `--network none`,
    `--restart unless-stopped`, uid/userns corretos, passphrase como bind mount
    `ro`, credenciais/runtime como volumes e nenhum proxy/workspace mount;
  - um container existente e parado é iniciado, não duplicado;
  - o helper espera pelo socket e testa `org.freedesktop.secrets` com timeout;
  - timeout gera `PodmanError` citando `asb-agent login`;
  - os argumentos de um agente contêm runtime +
    `DBUS_SESSION_BUS_ADDRESS`, mas não `ASB_KEYRING_PASS`;
  - `up`, `resume` e `login` garantem o serviço antes de criar/iniciar clientes;
  - `down`, `suspend` e `purge` não removem o container/volume global.

  Constantes mínimas esperadas:

  ```python
  KEYRING_CONTAINER = "asb-keyring"
  KEYRING_RUNTIME_VOLUME = "asb-keyring-runtime"
  KEYRING_BUS = "/run/asb-keyring/bus"
  ```

  Para isolamento de integração, implemente estes overrides internos por
  ambiente, mantendo os valores acima como defaults de produção:

  ```text
  ASB_CREDENTIALS_VOLUME
  ASB_KEYRING_RUNTIME_VOLUME
  ASB_KEYRING_CONTAINER
  ASB_KEYRING_PASS_FILE
  ```

  Eles não devem virar opções públicas do CLI.

- [ ] **Step 2: Confirmar a falha esperada**

  Run:

  ```bash
  python -m unittest tests.unit.test_auth tests.unit.test_lifecycle -v
  ```

  Expected: falhas por helpers/argumentos ausentes.

- [ ] **Step 3: Implementar `ensure_keyring_service()`**

  Crie/inicie o serviço de forma idempotente. Monte:

  ```text
  f"{KEYRING_PASS}:/run/asb-keyring-pass:ro,Z"
  asb-credentials:/run/asb-credentials:z
  asb-keyring-runtime:/run/asb-keyring:z
  ```

  Configure no container:

  ```text
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus
  ```

  Use um label de contrato, por exemplo `asb.keyring.schema=1`. Se existir um
  container homônimo incompatível, falhe com instrução exata para removê-lo e
  recriar workspaces; não substitua silenciosamente um serviço usado por
  clientes ativos.

  A saúde deve exigir socket e resposta do Secret Service, não apenas status
  `running`. Use polling curto com deadline explícito; nada de espera infinita.

- [ ] **Step 4: Ligar os três limites do ciclo de vida**

  - `_up()`: garantir serviço antes de montar/criar o agente;
  - `resume()`: garantir serviço antes de iniciar os containers do workspace;
  - `login()`: garantir serviço antes de criar `asb-login`.

  Em clientes, monte runtime em `/run/asb-keyring:ro,z`, passe o endereço do
  bus e remova totalmente `ASB_KEYRING_PASS`. Mude o volume compartilhado de
  credenciais para rótulo `:z` quando houver múltiplos consumidores.

- [ ] **Step 5: Executar os testes focais**

  Run:

  ```bash
  python -m unittest tests.unit.test_auth tests.unit.test_lifecycle -v
  ```

  Expected: `OK`.

## Task 4: Tornar o entrypoint exclusivamente cliente do Secret Service

**Files:**

- Modify: `image/entrypoint.sh`
- Modify: `tests/test-auth.sh`
- Modify: `tests/test-keyring-service.sh`

- [ ] **Step 1: Escrever as asserções que falham**

  Prove que um container cliente:

  - não possui processo próprio `dbus-daemon` ou `gnome-keyring-daemon`;
  - recebe `DBUS_SESSION_BUS_ADDRESS` em shell SSH/login e em `podman exec`;
  - não tem `$HOME/.local/share/keyrings` apontando para o volume persistente;
  - mantém os links de Codex e fallback do Claude no volume isolado;
  - lê o item sintético pelo serviço compartilhado.

- [ ] **Step 2: Remover o daemon por cliente**

  Remova do entrypoint o consumo de `ASB_KEYRING_PASS` e a chamada a
  `start-keyring.sh`. Inclua `DBUS_SESSION_BUS_ADDRESS` na propagação para
  `/etc/environment` e `/etc/profile.d/agent-sandbox.sh`.

  No bloco de credenciais, preserve somente:

  ```text
  ~/.claude/.credentials.json -> /run/asb-credentials/claude.json
  ~/.codex/auth.json          -> /run/asb-credentials/codex-auth.json
  ```

  Não crie nem faça link de `~/.local/share/keyrings` no cliente.

- [ ] **Step 3: Reconstruir e executar integração isolada**

  Run:

  ```bash
  asb-agent build
  bash tests/test-keyring-service.sh
  bash tests/test-auth.sh
  ```

  Expected: ambos retornam `0` sem tocar `asb-credentials` de produção.

## Task 5: Validar login real no mesmo serviço e diagnosticar falhas

**Files:**

- Modify: `cli/asb/lifecycle.py`
- Modify: `cli/asb/doctor.py`
- Modify: `tests/unit/test_auth.py`
- Modify: `tests/unit/test_doctor.py`
- Modify: `tests/test-doctor.sh`

- [ ] **Step 1: Escrever testes de login/doctor que falham**

  Prove que:

  - `login()` monta o runtime compartilhado, não passa a passphrase e mantém os
    checks reais de `LOGIN_CHECKS`;
  - remover `asb-login` não remove `asb-keyring`;
  - o doctor distingue container ausente, parado, socket ausente e Secret
    Service sem resposta;
  - cada falha indica exatamente `asb-agent login`;
  - serviço saudável produz linha `ok`.

- [ ] **Step 2: Confirmar a falha esperada**

  Run:

  ```bash
  python -m unittest tests.unit.test_auth tests.unit.test_doctor -v
  ```

  Expected: falhas apenas nas novas expectativas.

- [ ] **Step 3: Implementar as mudanças mínimas**

  Reutilize o mesmo health check do lifecycle ou extraia uma função pequena e
  não mutante no módulo adequado. Não faça o doctor iniciar/recriar serviços.
  O doctor diagnostica; `login`, `up` e `resume` reparam dentro de seus escopos.

- [ ] **Step 4: Executar os testes focais**

  Run:

  ```bash
  python -m unittest tests.unit.test_auth tests.unit.test_doctor -v
  bash tests/test-doctor.sh
  ```

  Expected: todos retornam `0`.

## Task 6: Atualizar o SSoT e executar a verificação completa

**Files:**

- Modify: `docs/domains/sandbox/README.md`
- Modify: `docs/domains/sandbox/security.md`
- Modify: `docs/domains/sandbox/failure-modes.md`
- Modify: `docs/superpowers/specs/2026-09-04-agent-sandbox-v2-design.md` only to
  add a dated supersession note linking to the new spec; do not rewrite history

- [ ] **Step 1: Documentar arquitetura, segurança e migração**

  Atualize o SSoT com:

  - um único proprietário do keyring;
  - ausência de rede e mounts de workspace no serviço;
  - diferença entre arquivo do Codex, fallback do Claude e Secret Service;
  - `pull` antes de recriar workspaces antigos;
  - comandos de diagnóstico e recuperação.

  Na spec histórica, acrescente apenas uma nota informando que a seção de
  credenciais foi substituída pela spec de 2026-09-06.

- [ ] **Step 2: Rodar a suíte automatizada**

  Run:

  ```bash
  python -m unittest discover -s tests/unit -v
  bash tests/test-auth.sh
  bash tests/test-keyring-service.sh
  bash tests/test-doctor.sh
  bash tests/test-lifecycle.sh
  git diff --check
  ```

  Expected: todos retornam `0`; os scripts mostram seus nomes aleatórios de
  recursos e confirmam cleanup.

- [ ] **Step 3: Executar somente a inspeção não sensível**

  Run:

  ```bash
  podman inspect asb-keyring --format '{{.HostConfig.NetworkMode}} {{.Config.User}}'
  podman inspect asb-keyring --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -F ASB_KEYRING_PASS && exit 1 || true
  podman ps --filter name=asb-keyring
  ```

  Expected: nenhuma rede, usuário não-root esperado, serviço rodando e nenhuma
  passphrase no ambiente.

- [ ] **Step 4: Declarar o gate manual pendente**

  Não autentique contas do operador. No handoff, solicite que o humano execute:

  ```bash
  asb-agent login
  ```

  Depois, em um workspace novo/recriado, o humano deve confirmar:

  ```bash
  asb-claude -p ping
  asb-agy -p ping
  codex login status
  ```

  O conteúdo de saída não deve ser capturado se puder conter dados da conta;
  basta registrar exit codes e estados `ok`/falha.

- [ ] **Step 5: Handoff para revisão**

  Entregue ao Codex:

  - `git status --short`;
  - `git diff --stat`;
  - resultados e códigos de saída de todos os testes;
  - confirmação de que volumes reais não foram usados;
  - gate manual ainda pendente ou resultado fornecido pelo humano.

  Não faça commit e não rode Graphify.
