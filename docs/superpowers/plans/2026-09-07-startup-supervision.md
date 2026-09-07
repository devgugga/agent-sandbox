# Supervisão da inicialização — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restaurar workspaces utilizáveis após login, preservando containers,
portas, dados e isolamento, com falha explícita quando dependências não funcionam.

**Architecture:** Unidades systemd supervisionam `podman start --attach` de
containers persistentes. O CLI mantém criação/teardown; sondas limitadas
comprovam prontidão; apenas o target do workspace controla seu autostart.

**Tech Stack:** Python >= 3.11/stdlib, Podman >= 6.1 rootless, systemd Type=exec,
Bash, Squid e SSH.

**Spec:** [Desenho §4–5 e §7–8](../specs/2026-09-07-startup-auth-redesign-design.md).

## Global Constraints

- Proposta; executar somente após revisão do desenho. I1 precede I2–I6.
- Python >= 3.11; biblioteca padrão no CLI; Podman >= 6.1; systemd de usuário
  com `Type=exec`; plataforma inicialmente validada: Arch/Omarchy desta máquina.
- Início automático após login do usuário; `Linger=no` permanece.
- Containers, dados, portas e isolamento são preservados na adoção.
- Apenas systemd reinicia recursos adotados: política Podman passa a `no`.
- Não desabilitar/parar `podman-restart.service` globalmente, matar pasta,
  apagar netns ou operar containers fora do manifesto validado.
- Helpers em `~/.local/lib/agent-sandbox/runtime/<revisao>/`, sem caminho do checkout.
- Testes automáticos só usam recursos `asb-test-`, dados sintéticos e temporários.
- stdout de up/resume é uma linha JSON apenas após prontidão; erros em stderr.
- Cada tarefa termina em revisão do diff e commit curado em branch. Aplicar
  governança Git e sincronização única de grafo descritas no plano coordenador.

## I1 — Provar supervisão e criar fixture isolada

**Files:** criar `tests/integration/sandbox_fixture.py`,
`tests/integration/test_supervisor_pilot.py`,
`docs/validation/2026-09-07-supervisor-pilot.md` durante a execução.

**Interfaces:** `SandboxFixture(label: str)` é context manager. Expõe
`workspace: str`, `container: str`, `unit: str`, `state_root: Path`;
`start() -> None`, `stop() -> None`, `break_proxy() -> None`,
`worktree_exists() -> bool`, `cli(*args: str) -> subprocess.CompletedProcess[str]`,
`inspect_identity() -> tuple[str, int]`, `write_sentinel() -> None`,
`sentinel_exists() -> bool`, `wait_active(timeout: float) -> bool`,
`fail_container() -> None`. Não depende das APIs novas para testar a premissa.

- [ ] Criar fixture com UUID, workspace `test-<label>-<uuid>`, recursos
  `asb-test-<label>-<uuid>-...`, chave SSH própria, volumes de credenciais,
  toolcache, keyring e passphrase próprios. Registrar cada ID antes de cleanup;
  recusar qualquer nome fora do prefixo e qualquer caminho fora da raiz temporária.
  Não reutilizar `asb-keyring`, `asb-login`, `asb-toolcache` ou sua senha real.
- [ ] Criar um container sintético persistente e uma unidade literal equivalente
  ao exemplo a seguir. O fixture substitui o nome concreto por seu nome validado;
  resolve o binário Podman absoluto e instala apenas essa unidade de teste.

```ini
[Unit]
Description=ASB supervision pilot
StartLimitIntervalSec=600s
StartLimitBurst=3

[Service]
Type=exec
ExecStart=/usr/bin/podman start --attach --sig-proxy=false asb-test-pilot
ExecStop=/usr/bin/podman stop --ignore --time=10 asb-test-pilot
ExecStopPost=/usr/bin/podman stop --ignore --time=10 asb-test-pilot
Restart=always
RestartSec=5s
TimeoutStartSec=150s
TimeoutStopSec=20s
KillMode=process
```

`ExecStopPost` cobre falha durante startup, quando `ExecStop` pode não rodar.
Não copiar esse exemplo literalmente para o host de produção. Testar também
falha em ExecStartPost, saída zero inesperada e reconexão a container rodando.

- [ ] Escrever a prova usando um container que encerra por comando do fixture:

```python
with SandboxFixture("supervision") as sandbox:
    sandbox.start()
    original = sandbox.inspect_identity()
    sandbox.write_sentinel()
    sandbox.fail_container()
    self.assertTrue(sandbox.wait_active(timeout=30))
    self.assertEqual(sandbox.inspect_identity(), original)
    self.assertTrue(sandbox.sentinel_exists())
    sandbox.stop()
    self.assertFalse(sandbox.wait_active(timeout=7))
```

- [ ] Rodar `python3 -B -m unittest discover -s tests/integration -p 'test_supervisor_pilot.py' -v`.
  Registrar container ID, porta, restart detectado, parada intencional e ausência
  de órfãos. Esse é um experimento real, não mock do retorno de systemctl.
- [ ] Reprovar I1 se a supervisão não detectar saída, entrar em loop, perder
  dados ou exigir um daemon adicional. Não executar I2 antes de avaliar o
  relatório junto com A1. Não generalizar um piloto aprovado para reboot real.

## I2 — Diagnóstico tipado e prontidão observacional

**Files:** criar `cli/asb/readiness.py`, `cli/asb/runtime_check.py`,
`tests/unit/test_readiness.py`; modificar `cli/asb/doctor.py`.

**Interfaces:**

```python
from dataclasses import dataclass, replace
from collections.abc import Callable
from time import monotonic, sleep

@dataclass(frozen=True)
class ProbeResult:
    component: str
    state: str
    code: str
    elapsed_ms: int
    remediation: str

def wait_until(probe: Callable[[float], ProbeResult], *, timeout: float,
               interval: float = 1.0) -> ProbeResult:
    if timeout <= 0 or interval <= 0:
        raise ValueError("timeout e interval devem ser positivos")
    started = monotonic()
    deadline = started + timeout
    last = ProbeResult("probe", "failed", "timeout", 0, "inspect_component")
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return replace(last, elapsed_ms=int((monotonic() - started) * 1000))
        last = probe(min(5.0, remaining))
        if last.state == "healthy":
            return replace(last, elapsed_ms=int((monotonic() - started) * 1000))
        sleep(min(interval, max(0.0, deadline - monotonic())))
```

O callable recebe o timeout disponível e deve respeitá-lo em todo I/O;
testar isso com subprocesso deliberadamente lento. Produzir também
`probe_host(target: str, timeout: float) -> ProbeResult`,
`probe_proxy(agent: str, proxy: str, target: str, timeout: float) -> ProbeResult`,
`probe_ssh(port: int, user: str, key: Path, timeout: float) -> ProbeResult` e
`probe_workspace(ws: str) -> list[ProbeResult]`. `runtime_check.main() -> int`
consome um manifesto validado e o papel do container; nenhum comando livre.

- [ ] Escrever casos de host sem rota, destino recusando TCP, DNS falhando,
  proxy 403/503, serviço ausente, SSH lento e sucesso tardio. Exemplo de
  comportamento do coletor, usando `unittest.mock.patch` nos probes:

```python
failure = ProbeResult("proxy", "failed", "connect_denied", 10, "review_allowlist")
with patch("asb.readiness.probe_proxy", return_value=failure):
    result = readiness.probe_workspace("test-readiness")
    self.assertIn("connect_denied", [item.code for item in result])
    self.assertNotIn("unauthenticated", [item.state for item in result])
```

- [ ] Rodar `python3 -B -m unittest discover -s tests/unit -p 'test_readiness.py' -v`
  e confirmar RED no comportamento desejado.
- [ ] Implementar sondas com subprocessos limitados e monotonic clock, usando
  os prazos da spec. Parser de CONNECT trabalha com status HTTP e código
  observado; não traduz todo erro em uplink morto. A sonda é de dentro do agente
  para o proxy, não somente localhost dentro do proxy. Para admissão anterior
  ao agente, usar probe do proxy e completar a prova pelo agente antes de emitir.
- [ ] Adaptar doctor para `--json`, relatório schema 1 com `infrastructure`
  e `providers` separados. O doctor não inicia/reinicia nada. Serviço sem
  healthcheck fica `process_running`, não `application_ready`.
- [ ] Repetir testes unitários; usar fixture I1 para provar SSH positivo e
  distinguir proxy inacessível de CONNECT negado sem tocar na allowlist real.

## I3 — Instalação versionada e uma única supervisão

**Files:** criar `cli/asb/supervisor.py`, `tests/unit/test_supervisor.py`;
modificar `cli/asb/install.py`, `tests/unit/test_install.py`.

**Interfaces:** `ContainerUnit` dataclass contém `name: str`, `container_id: str`,
`role: str`, `unit_name: str`, `target_name: str`, `helper_path: Path`,
`manifest_path: Path`. Produzir `render_unit(unit: ContainerUnit) -> str`,
`install_runtime(root: Path, revision: str) -> Path`,
`install_workspace(ws: str) -> None`, `start_workspace(ws: str) -> None`,
`stop_workspace(ws: str) -> None`, `remove_workspace_units(ws: str) -> None`.

- [ ] Escrever teste que renderiza unidade com caminhos temporários contendo
  espaço e `%`, rejeita newline em nomes e evita shell interpolation:

```python
text = supervisor.render_unit(unit)
self.assertIn("--attach", text)
self.assertIn("--sig-proxy=false", text)
self.assertIn("Restart=always", text)
self.assertIn("ExecStopPost=", text)
self.assertNotIn(str(checkout), text)
self.assertNotIn("start --all", text)
```

`unit` é uma instância completa de ContainerUnit sobre o fixture do teste;
`checkout` é a raiz temporária que simula o repositório. Testar escaping pelo
parser real systemd, não apenas por substring.
- [ ] Confirmar RED com `python3 -B -m unittest discover -s tests/unit -p 'test_supervisor.py' -v`.
- [ ] Implementar renderização a partir do template validado em I1, adicionando
  `PartOf` do target e ordenação por papéis. Proxy espera host; agente espera
  sondas de proxy e keyring antes da admissão. `ExecStartPost` exige prontidão
  da unidade, não só processo Podman criado. Não usar BindsTo para matar o
  agente quando o proxy cair depois de uma partida saudável.
- [ ] Instalar pacote do helper e dependências Python locais em diretório
  versionado; não symlinkar o checkout. O launcher usa import do pacote instalado
  e não consulta PYTHONPATH do projeto consumidor. Validar paths/IDs a partir
  do manifesto fora do mount; não aceitar comandos arbitrários no JSON.
- [ ] Gravar unidades de forma atômica, fazer daemon-reload e validar com
  `systemd-analyze --user verify` dos arquivos gerados. Criar target regular
  habilitável; não copiar a semântica de enable de Quadlet.
- [ ] Ensaiar instalação duas vezes, checkout movido e falha de escrita. Nenhum
  cenário cria segundo supervisor ou corrompe a geração em uso. Helper antigo
  permanece disponível para rollback; não fazer garbage collection nesta tarefa.

## I4 — Forwarder com falha visível e portas baixas

**Files:** criar `image/forwarder.sh`, `tests/integration/test_forwarder.py`;
modificar `image/Containerfile.proxy`, `cli/asb/lifecycle.py:start_forwarder`.

**Interfaces:** forwarder recebe portas inteiras validadas como argv, inicia
um socat por porta, propaga falha de qualquer filho, e encerra todos em TERM.
`probe_workspace` de I2 inclui cada listener e destino.

- [ ] Criar fixture com 80 e 5432 e teste em que um listener é encerrado:

```python
before = sandbox.forwarder_restart_count()
sandbox.fail_forwarder_listener(80)
self.assertTrue(sandbox.wait_forwarder_listener(80, timeout=30))
self.assertGreater(sandbox.forwarder_restart_count(), before)
```

Adicionar esses três métodos ao SandboxFixture: retornos `int`, `None`, `bool`.
Implementar a falha pelo PID específico do socat de teste; nunca pgrep no host.
- [ ] Rodar `python3 -B -m unittest discover -s tests/integration -p 'test_forwarder.py' -v`
  e confirmar que a versão atual falha, incluindo controle positivo em 5432.
- [ ] Implementar supervisão de filhos e `--sysctl net.ipv4.ip_unprivileged_port_start=0`
  exclusivamente no forwarder. A imagem atual é Debian bookworm-slim. Usar
  Bash explicitamente e verificar sua presença no teste da imagem. Copiar
  `image/forwarder.sh` para `/usr/local/bin/asb-forwarder` com modo executável.
  O núcleo do supervisor é:

```bash
#!/usr/bin/env bash
set -uo pipefail
pids=()
stop_children() {
  trap '' TERM INT
  if ((${#pids[@]})); then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap 'stop_children; exit 0' TERM INT
for port in "$@"; do
  socat "TCP-LISTEN:${port},fork,reuseaddr" "TCP:host.containers.internal:${port}" &
  pids+=("$!")
done
wait -n "${pids[@]}"
result=$?
stop_children
((result != 0)) || result=1
exit "$result"
```

  Validar previamente argc > 0 e portas inteiras 1–65535. O wrapper só recebe
  portas já normalizadas pelo Profile, não comandos ou destinos livres.
- [ ] Testar TERM, erro de bind inicial e perda posterior de filho; validar
  que destinos continuam restritos às portas declaradas e não há proxy geral.
- [ ] GREEN, sintaxe do script, diff e commit. Atualizar container existente
  que precise novo sysctl somente por migração explícita dessa role; agente,
  banco e porta SSH não são recriados para corrigir o forwarder.

## I5 — Integrar ciclo de vida, prontidão e rollback de criação

**Files:** modificar `cli/asb/lifecycle.py`, `cli/asb-agent`,
`tests/unit/test_lifecycle.py`, `tests/test-transaction.sh`;
criar `tests/integration/test_workspace_supervision.py`.

**Interfaces:** preservar `up(root, ws, repo)`, `resume(root, ws)`, `suspend(ws)`
e `down(ws)`. Produzir `prepare_workspace(root: Path, ws: str, repo: Path) -> None`
para criação sem restauração global; integra `start_workspace` e probes.

- [ ] Testar que falha em workspace existente não executa sweep:

```python
with patch("asb.lifecycle.prepare_workspace"), \
     patch("asb.lifecycle.supervisor.start_workspace", side_effect=RuntimeError("proxy")), \
     patch("asb.lifecycle._sweep_containers") as sweep:
    with self.assertRaises(RuntimeError):
        lifecycle.up(root, "test-existing", repo)
    sweep.assert_not_called()
```

- [ ] Confirmar RED e adicionar teste de recursos novos parcialmente criados:
  cleanup deve atingir somente IDs registrados naquela transação. A nova
  transação não remove containers preexistentes encontrados pelo mesmo label.
- [ ] Separar create/start: novos containers gerenciados têm restart policy no;
  systemd controla a partida. Criar proxy e verificar rede antes de mise install.
  Conferir porta por inspect e SSH antes de emit; erro de subprocesso obrigatório
  é propagado. Não emitir JSON apenas porque a porta está cadastrada.
- [ ] `suspend`: disable target, stop target, verificar parada de todos os
  containers próprios. `resume`: enable target, reset-failed de unidades próprias,
  start e probes. `down`: disable/stop/remove unidades próprias antes de remover
  os recursos já abrangidos pelo contrato atual; nunca remover auth global.
- [ ] Autostart de recursos gerenciados depende apenas de target habilitado;
  boot não depende de Orca chamar resume. Unit tests simulam APIs; integração
  prova parada, retomada e reconexão com ID/porta/sentinela preservados.
- [ ] Runtime legado permanece identificado e não é migrado por up/resume.
  Antes da promoção, novos workspaces gerenciados exigem `up --runtime systemd`;
  o manifesto decide o backend de resume. O default só muda no gate final T3.
- [ ] Executar unitários e integração desta tarefa. Atualizar testes existentes
  de egress/lifecycle para distinguirem contrato legado e gerenciado, sem rodar
  a suíte shell antiga contra volumes de produção.

## I6 — Adoção e rollback sem recriação dos workspaces

**Files:** modificar `cli/asb/supervisor.py`, `cli/asb-agent`,
`cli/asb/install.py`; criar `tests/integration/test_adoption.py`.

**Interfaces:** `adopt_workspace(ws: str, *, apply: bool) -> dict`,
`rollback_workspace(ws: str) -> dict`, `adopt_keyring(*, apply: bool) -> dict`,
`rollback_keyring() -> dict`. Parser: `adopt-runtime --workspace ID [--apply]`,
`adopt-runtime --keyring [--apply]`, `rollback-runtime --workspace ID` ou
`rollback-runtime --keyring`; modo padrão de adoção é somente inventário.

- [ ] Testar recusa de adoção por ID divergente e retorno exato de política:

```python
original = sandbox.inspect_identity()
sandbox.cli("adopt-runtime", "--workspace", sandbox.workspace, "--apply")
sandbox.cli("rollback-runtime", "--workspace", sandbox.workspace)
self.assertEqual(sandbox.inspect_identity(), original)
self.assertTrue(sandbox.sentinel_exists())
```

No teste também conferir returncodes de ambos os comandos; falha não pode ser
ocultada pelo assert final. Injetar erro entre policy update e start da unidade.
- [ ] Confirmar RED. Implementar lock por workspace e diário de etapas schema 1:
  inventário, unidades preparadas, políticas alteradas, supervisão iniciada,
  prontidão aprovada. Retomada usa o diário e verifica IDs novamente.
- [ ] No apply, operar somente os containers inventariados. Guardar se estavam
  running ou stopped e se target/unidades existiam; rollback restaura esses
  estados e policies, não apenas as configurações. Não recriar containers.
- [ ] Adotar keyring separadamente com lock global. Nenhum workspace desliga
  esse serviço durante down/suspend. Só remover o drop-in antigo se o conteúdo
  e o inventário confirmarem propriedade do projeto e adoção completa.
- [ ] Não corrigir mounts antigos nesta transação. Gerar diagnóstico que separa
  necessidade de migração de credenciais, mudança do forwarder e adoção de
  supervisão. Recriação estritamente necessária segue janela e backup próprios.
- [ ] Inventariar também produtores do namespace rootless compartilhado. Uma
  unidade legada pode criá-lo antes da rede e contaminar o piloto gerenciado.
  Não alterar serviços alheios para fazer o teste passar; aplicar a condição
  de coexistência da spec §7 e registrar essa dependência no relatório.
- [ ] Validar arquivos/IDs/portas antes e depois, inclusive erro intermediário.
  Ensaiar exclusivamente em fixture; adoção do workspace real pertence a T2.

## Saída desta frente

Infraestrutura gerenciada aprovada nas integrações isoladas e pronta para T1.
Boot real e estabilidade diária continuam abertos até T2/T3. Não declarar
reboot corrigido com base em stop/start ou em um serviço systemd ativo.
