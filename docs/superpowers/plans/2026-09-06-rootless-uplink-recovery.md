# Rootless Uplink Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:test-driven-development` while implementing each task and
> `superpowers:verification-before-completion` before the handoff.

**Goal:** Fazer `up`, `resume` e a restauração do Podman prepararem o namespace
rootless antes de iniciar containers que precisam de egresso.

**Architecture:** Um helper fino em `asb.podman` encapsula
`podman unshare --rootless-netns`. O ciclo de vida chama esse helper nos dois
limites operacionais, e um drop-in de usuário adiciona a mesma ação como
`ExecStartPre` da unidade de restauração fornecida pelo Podman.

**Tech Stack:** Python 3.11, `unittest`, Podman rootless, systemd user units.

**Spec:**
[`docs/superpowers/specs/2026-09-06-rootless-uplink-recovery-design.md`](../specs/2026-09-06-rootless-uplink-recovery-design.md)

## Global Constraints

- Execute este plano antes do plano de Secret Service singleton.
- Trabalhe na branch fornecida pelo humano; não crie outro worktree.
- Não faça commit, não execute `graphify update .` e não altere
  `graphify-out/**`. Entregue o diff sem commit para revisão do Codex. Depois da
  revisão e do gate humano, o `commit-curator` fará o commit de código e o
  Graphify será sincronizado em um segundo commit.
- Não mate `pasta`, não reinicie workspaces ativos e não execute reboot como
  parte dos testes automatizados.
- Preserve todas as mudanças preexistentes e toque somente nos arquivos
  listados em cada tarefa.

## Task 1: Encapsular a inicialização do namespace rootless

**Files:**

- Modify: `cli/asb/podman.py`
- Modify: `tests/unit/test_podman.py`

- [ ] **Step 1: Escrever o teste que falha**

  Importe `ensure_rootless_netns` e adicione testes com mocks que provem:

  1. `shutil.which("true")` é resolvido para um caminho absoluto;
  2. `run("unshare", "--rootless-netns", "/usr/bin/true")` é chamado uma vez;
  3. a ausência de `true` gera `PodmanError` com correção compreensível.

  Não execute o helper real neste teste.

- [ ] **Step 2: Confirmar a falha esperada**

  Run:

  ```bash
  python -m unittest tests.unit.test_podman -v
  ```

  Expected: erro de importação ou atributo ausente apenas para o novo helper.

- [ ] **Step 3: Implementar o helper mínimo**

  Contrato esperado em `cli/asb/podman.py`:

  ```python
  def ensure_rootless_netns() -> None:
      true_bin = shutil.which("true")
      if true_bin is None:
          raise PodmanError("binario 'true' nao encontrado no PATH")
      run("unshare", "--rootless-netns", true_bin)
  ```

  Não adicione retry, cache ou tratamento que esconda o erro do Podman.

- [ ] **Step 4: Executar o teste focal**

  Run:

  ```bash
  python -m unittest tests.unit.test_podman -v
  ```

  Expected: `OK`.

## Task 2: Aplicar o helper em `up` e `resume`

**Files:**

- Modify: `cli/asb/lifecycle.py`
- Modify: `tests/test-lifecycle.sh`
- Modify: `tests/unit/test_lifecycle.py`

- [ ] **Step 1: Escrever testes de ordenação que falham**

  Use mocks com uma lista `events` e prove separadamente que:

  ```text
  up:     ensure_rootless_netns -> podman run do proxy
  resume: ensure_rootless_netns -> podman start do proxy
  ```

  Os testes unitários não devem executar Podman real. No shell test, preserve a
  asserção já existente de `CONNECT ... 200` depois de `resume`.

- [ ] **Step 2: Confirmar a falha esperada**

  Run:

  ```bash
  python -m unittest tests.unit.test_lifecycle -v
  ```

  Expected: os novos eventos não contêm `ensure_rootless_netns`.

- [ ] **Step 3: Fazer as duas chamadas cirúrgicas**

  Em `_up()`, chame `podman.ensure_rootless_netns()` depois das duas guardas
  iniciais (imagem presente e workspace ainda inexistente) e antes de
  `build_proxy(root)`. Em `resume()`, chame-o depois de validar o workspace e
  antes de `podman.run("start", n["proxy"], ...)`.

  Não execute o helper para operações que não iniciam containers com egresso.

- [ ] **Step 4: Executar os testes focais**

  Run:

  ```bash
  python -m unittest tests.unit.test_lifecycle -v
  bash tests/test-lifecycle.sh
  ```

  Expected: todos passam e o teste shell continua recebendo HTTP 200 pelo
  proxy depois do `resume`.

## Task 3: Preparar o uplink antes da restauração no login

**Files:**

- Modify: `cli/asb/install.py`
- Modify: `tests/unit/test_install.py`

- [ ] **Step 1: Escrever testes do drop-in que falham**

  Com `TemporaryDirectory`, `Path.home()` mockado e `shutil.which()` mockado,
  prove que `podman_restart()`:

  - cria `~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf`;
  - grava uma seção `[Service]` e exatamente um `ExecStartPre` com caminhos
    absolutos para `podman` e `true`;
  - chama primeiro `systemctl --user daemon-reload` e depois
    `systemctl --user enable podman-restart.service`;
  - é idempotente quando chamado duas vezes;
  - retorna `1` sem escrever drop-in se a unidade da distribuição não existe.

  Faça o caminho da unidade uma constante mockável, por exemplo
  `PODMAN_RESTART_UNIT`, para o teste não depender de `/usr/lib`.

- [ ] **Step 2: Confirmar a falha esperada**

  Run:

  ```bash
  python -m unittest tests.unit.test_install -v
  ```

  Expected: os novos testes falham porque o drop-in ainda não existe.

- [ ] **Step 3: Implementar o drop-in mínimo**

  O arquivo gerado deve equivaler a:

  ```ini
  [Service]
  ExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true
  ```

  Resolva os dois binários com `shutil.which`; escreva o arquivo com
  `Path.write_text`; chame `daemon-reload` antes de `enable`. Não copie nem
  substitua a unidade da distribuição.

- [ ] **Step 4: Executar o teste focal**

  Run:

  ```bash
  python -m unittest tests.unit.test_install -v
  ```

  Expected: `OK`.

## Task 4: Documentar e verificar a correção de rede

**Files:**

- Modify: `docs/domains/sandbox/README.md`
- Modify: `docs/domains/sandbox/failure-modes.md`
- Modify: `docs/domains/sandbox/security.md` only if it currently claims a
  different boot boundary

- [ ] **Step 1: Atualizar o SSoT**

  Documente o estado `container running + uplink rootless morto`, a recuperação
  automática em `up`/`resume`/systemd e o comando manual mantido pelo doctor.
  Não duplique detalhes em wrappers de agentes.

- [ ] **Step 2: Rodar a suíte automatizada proporcional ao risco**

  Run:

  ```bash
  python -m unittest discover -s tests/unit -v
  bash tests/test-doctor.sh
  bash tests/test-lifecycle.sh
  git diff --check
  ```

  Expected: todos os comandos retornam `0`.

- [ ] **Step 3: Verificar a unidade sem reiniciar a máquina**

  Depois de executar o fluxo que chama `podman_restart()`, rode:

  ```bash
  systemd-analyze --user verify podman-restart.service
  systemctl --user show podman-restart.service -p ExecStartPre
  ```

  Expected: verificação sem erro e `ExecStartPre` contendo
  `podman unshare --rootless-netns`.

- [ ] **Step 4: Handoff para revisão**

  Entregue ao Codex:

  - `git status --short`;
  - `git diff --stat`;
  - os comandos executados e seus códigos de saída;
  - qualquer teste manual não executado.

  Não faça commit e não rode Graphify.
