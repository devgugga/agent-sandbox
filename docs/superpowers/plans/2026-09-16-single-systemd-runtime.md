# Runtime único systemd — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar o runtime `legacy`, supervisionar todo recurso ASB pelo
systemd de usuário e impedir que qualquer produtor ASB crie o namespace
rootless antes de haver conectividade real.

**Architecture:** Uma unidade nova `asb-network.service` (oneshot, espera sem
limite) sonda o host até TCP+TLS funcionar; toda unidade de container de
workspace passa a ter `Requires=`/`After=` nela. O keyring vira
`asb-keyring.service` com sonda de prontidão. `up`/`resume` passam a ter um só
caminho, verificam o host com limite antes de iniciar o target, e nunca
executam `podman unshare`. A maquinaria de adoção e rollback é removida.

**Tech Stack:** Python >= 3.11 (biblioteca padrão), `unittest`, Podman >= 6.1
rootless, systemd de usuário com `Type=exec`.

**Spec:** [`docs/superpowers/specs/2026-09-16-single-systemd-runtime-design.md`](../specs/2026-09-16-single-systemd-runtime-design.md)
(Emenda A), que emenda
[`2026-09-07-startup-auth-redesign-design.md`](../specs/2026-09-07-startup-auth-redesign-design.md).
Evidência: [`docs/validation/startup-auth-pilot.md`](../../validation/startup-auth-pilot.md).

## Global Constraints

- Python >= 3.11; só biblioteca padrão no CLI; Podman >= 6.1; systemd de
  usuário com `Type=exec`; plataforma validada: Arch/Omarchy desta máquina.
- `Linger=no` permanece.
- Não desabilitar `podman-restart.service` globalmente.
- Login uma vez por fornecedor, compartilhado entre workspaces; preservar
  **dados e credenciais** (volumes `asb-credentials`, `asb-keyring-data`,
  `asb-keyring-runtime` e `~/.config/agent-sandbox/keyring.pass`). ID de
  container e porta SSH podem mudar **uma vez**, na troca.
- A espera por rede nunca chama Podman, nunca cria o namespace rootless e
  nunca executa `unshare`.
- Testes unitários: todo `tests/unit/test_*.py` importa `asb_test_isolation`
  na primeira linha; nenhum teste toca volume real; `subprocess`/`podman`
  sempre mockados.
- Testes de integração: todo recurso com prefixo `asb-test-`, registrado na
  `SandboxFixture`.
- Branch `feat/startup-auth-redesign`. Sem push. Commits pelo
  `commit-curator`, com Gitmoji literal, corpo estruturado em 76 colunas e sem
  trailer `Co-authored-by`.
- Graphify permanece pausado (`.git/graphify-pause`) até a Task 15.
- `git diff --check` limpo antes de cada commit.

**Como rodar testes** (sempre da raiz do repositório):

```bash
# um arquivo unitário
python3 -m unittest discover -s tests/unit -p 'test_network_gate.py' -v
# um teste unitário específico
python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -k test_up_never_initializes_the_rootless_namespace -v
# suíte unitária inteira
python3 -m unittest discover -s tests/unit
# um arquivo de integração
python3 -m unittest discover -s tests/integration -p 'test_network_gate.py' -v
```

---

### Task 1: Espera por conectividade real (`network_gate.py`)

**Files:**
- Create: `cli/asb/network_gate.py`
- Modify: `cli/asb/install.py` (constante `_RUNTIME_CHECK_PY`, linha ~572, e `runtime_payload`, linha ~588)
- Test: `tests/unit/test_network_gate.py`

**Interfaces:**
- Consumes: `asb.readiness.probe_host(target: str, timeout: float) -> ProbeResult`; `ProbeResult(component, state, code, elapsed_ms, remediation)`.
- Produces:
  - `network_gate.DEFAULT_TARGET = "github.com:443"`
  - `network_gate.gate_target() -> str` (lê `ASB_NETWORK_GATE_TARGET`)
  - `network_gate.wait_for_network(target: str, *, probe, sleep, clock, log, interval: float = 5.0, summary_every: float = 60.0) -> int`
  - `network_gate.main() -> int`
  - arquivo `network_gate.py` na raiz do runtime versionado, modo 0755.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/unit/test_network_gate.py`:

```python
"""Unit tests for cli/asb/network_gate.py — espera unica por conectividade real (Emenda A §4)."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import install, network_gate  # noqa: E402
from asb.readiness import ProbeResult  # noqa: E402

NON_HEALTHY_CODES = (
    "dns_failed", "timeout", "no_route", "tls_failed",
    "connection_refused", "unexpected_error",
)


def _result(state: str, code: str) -> ProbeResult:
    return ProbeResult("host", state, code, 0, "")


class _FakeClock:
    """Cada leitura avanca `step` segundos."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class TestWaitForNetwork(unittest.TestCase):
    def _run(self, results, *, step: float = 0.0):
        pending = list(results)
        calls: list[dict] = []
        sleeps: list[float] = []
        logs: list[str] = []

        def probe(**kwargs):
            calls.append(kwargs)
            return pending.pop(0)

        rc = network_gate.wait_for_network(
            "github.com:443",
            probe=probe,
            sleep=sleeps.append,
            clock=_FakeClock(step),
            log=logs.append,
            interval=5.0,
            summary_every=60.0,
        )
        return rc, calls, sleeps, logs

    def test_returns_zero_immediately_when_host_is_healthy(self):
        rc, calls, sleeps, _ = self._run([_result("healthy", "ok")])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [{"target": "github.com:443", "timeout": 5.0}])
        self.assertEqual(sleeps, [])

    def test_every_non_healthy_result_means_keep_waiting(self):
        for code in NON_HEALTHY_CODES:
            with self.subTest(code=code):
                rc, calls, sleeps, _ = self._run(
                    [_result("unreachable", code), _result("healthy", "ok")])
                self.assertEqual(rc, 0)
                self.assertEqual(len(calls), 2)
                self.assertEqual(sleeps, [5.0])

    def test_logs_only_state_changes_while_waiting(self):
        results = [_result("unreachable", "timeout")] * 4 + [
            _result("unreachable", "dns_failed"),
            _result("healthy", "ok"),
        ]
        rc, _, _, logs = self._run(results)
        self.assertEqual(rc, 0)
        waiting = [line for line in logs if "aguardando conectividade" in line]
        self.assertEqual(len(waiting), 2)
        self.assertIn("timeout", waiting[0])
        self.assertIn("dns_failed", waiting[1])
        self.assertIn("confirmada", logs[-1])

    def test_emits_a_bounded_number_of_summaries_while_the_code_repeats(self):
        results = [_result("unreachable", "timeout")] * 20 + [_result("healthy", "ok")]
        rc, _, _, logs = self._run(results, step=10.0)
        self.assertEqual(rc, 0)
        summaries = [line for line in logs if "ainda aguardando" in line]
        self.assertGreaterEqual(len(summaries), 2)
        self.assertLess(len(summaries), 20)


class TestGateNeverSpawnsProcesses(unittest.TestCase):
    def test_wait_for_network_never_spawns_a_process(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("processo proibido")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("processo proibido")):
            rc = network_gate.wait_for_network(
                "github.com:443",
                probe=lambda **kw: _result("healthy", "ok"),
                sleep=lambda seconds: None,
                clock=lambda: 0.0,
                log=lambda message: None,
            )
        self.assertEqual(rc, 0)

    def test_module_imports_nothing_that_spawns_processes(self):
        tree = ast.parse(Path(network_gate.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(alias.name for alias in node.names)
        self.assertFalse({"subprocess", "podman"} & imported, imported)


class TestGateTarget(unittest.TestCase):
    def test_default_target_is_github_https(self):
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("ASB_NETWORK_GATE_TARGET", None)
            self.assertEqual(network_gate.gate_target(), "github.com:443")

    def test_environment_overrides_the_target(self):
        with mock.patch.dict(os.environ, {"ASB_NETWORK_GATE_TARGET": "127.0.0.1:18080"}):
            self.assertEqual(network_gate.gate_target(), "127.0.0.1:18080")


class TestRuntimeShipsNetworkGate(unittest.TestCase):
    def test_install_runtime_ships_the_wrapper_and_the_module(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            dest = install.install_runtime(repo, "revgate", target_base=Path(tmp))
            wrapper = dest / "network_gate.py"
            self.assertTrue(wrapper.is_file())
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
            self.assertIn("from asb.network_gate import main",
                          wrapper.read_text(encoding="utf-8"))
            self.assertTrue((dest / "asb" / "network_gate.py").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_network_gate.py' -v`
Expected: ERROR com `ImportError: cannot import name 'network_gate'`.

- [ ] **Step 3: Implementar o módulo**

Criar `cli/asb/network_gate.py`:

```python
"""cli/asb/network_gate.py — espera unica por conectividade real do host.

ExecStart de `asb-network.service` (Emenda A §4): `Type=oneshot`,
`TimeoutStartSec=infinity`. Sai 0 somente quando `probe_host()` devolve
`healthy`; qualquer outro resultado, inclusive `tls_failed` de um portal
cativo, e continuar esperando.

Nunca inicia processo, nunca cria o namespace rootless. Criar o namespace aqui
reproduziria o defeito do drop-in antigo, que o inicializava antes de a rede
funcionar e o deixava sem egresso ate o proximo boot.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

from .readiness import ProbeResult, probe_host

DEFAULT_TARGET = "github.com:443"
INTERVAL_SECONDS = 5.0
SUMMARY_SECONDS = 60.0


def gate_target() -> str:
    """Destino sondado; `ASB_NETWORK_GATE_TARGET` o substitui em ambiente isolado."""
    return os.environ.get("ASB_NETWORK_GATE_TARGET") or DEFAULT_TARGET


def _log_stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def wait_for_network(
    target: str,
    *,
    probe: Callable[..., ProbeResult] = probe_host,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = _log_stderr,
    interval: float = INTERVAL_SECONDS,
    summary_every: float = SUMMARY_SECONDS,
) -> int:
    """Bloqueia ate o host alcancar `target`; devolve 0.

    O journal recebe so mudancas de estado e um resumo a cada `summary_every`
    segundos: horas offline nao geram uma linha a cada `interval`.
    """
    started = clock()
    last_code: str | None = None
    last_log = started
    attempts = 0
    while True:
        attempts += 1
        result = probe(target=target, timeout=interval)
        if result.state == "healthy":
            log(f"asb-network: conectividade real confirmada ({target}) "
                f"apos {attempts} tentativa(s) e {int(clock() - started)}s")
            return 0
        if result.code != last_code:
            log(f"asb-network: aguardando conectividade real ({target}): {result.code}")
            last_code = result.code
            last_log = clock()
        elif clock() - last_log >= summary_every:
            log(f"asb-network: ainda aguardando ({target}): {result.code}, "
                f"{attempts} tentativa(s), {int(clock() - started)}s")
            last_log = clock()
        sleep(interval)


def main() -> int:
    return wait_for_network(gate_target())


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Instalar o wrapper no runtime**

Em `cli/asb/install.py`, logo abaixo da constante `_RUNTIME_CHECK_PY`, adicionar:

```python
_NETWORK_GATE_PY = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "runtime_dir = Path(__file__).resolve().parent\n"
    "if str(runtime_dir) not in sys.path:\n"
    "    sys.path.insert(0, str(runtime_dir))\n"
    "\n"
    "from asb.network_gate import main\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    sys.exit(main())\n"
)
```

Em `runtime_payload`, substituir:

```python
    payload = {
        "launcher.sh": (_LAUNCHER_SH.encode("utf-8"), 0o755),
        "runtime_check.py": (_RUNTIME_CHECK_PY.encode("utf-8"), 0o755),
    }
```

por:

```python
    payload = {
        "launcher.sh": (_LAUNCHER_SH.encode("utf-8"), 0o755),
        "runtime_check.py": (_RUNTIME_CHECK_PY.encode("utf-8"), 0o755),
        "network_gate.py": (_NETWORK_GATE_PY.encode("utf-8"), 0o755),
    }
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_network_gate.py' -v`
Expected: `OK` (9 testes).

Run: `python3 -m unittest discover -s tests/unit -p 'test_install.py'`
Expected: `OK` (o manifesto do runtime cobre o arquivo novo sem mudança de teste).

- [ ] **Step 6: Commit**

Pelo `commit-curator`, staging explícito de `cli/asb/network_gate.py`,
`cli/asb/install.py`, `tests/unit/test_network_gate.py`. Título sugerido:
`✨ adicionar espera unica por conectividade real: Emenda A`.

---

### Task 2: Unidade `asb-network.service` e dependência em toda unidade de workspace

**Files:**
- Modify: `cli/asb/supervisor.py` (antes de `class ContainerUnit`, linha ~61; campos e `__post_init__` de `ContainerUnit`; `render_unit`, linha ~102; depois de `render_target`, linha ~172; `install_workspace`, linha ~246; `__all__`)
- Modify: `tests/integration/sandbox_fixture.py` (`__init__` e `cli()`)
- Modify: `tests/integration/test_startup_auth.py` (`self.cli_env`, linha ~314)
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: arquivo `network_gate.py` no diretório do runtime (Task 1).
- Produces:
  - `supervisor.NETWORK_UNIT = "asb-network.service"`
  - `supervisor.network_unit_name() -> str` (lê `ASB_NETWORK_UNIT`)
  - `supervisor.render_network_unit(gate_path: Path, target: str | None = None) -> str`
  - campo `ContainerUnit.network_unit: str | None = NETWORK_UNIT`
  - `install_workspace` grava `<unit_dir>/<network_unit_name()>` e NÃO o inclui na lista devolvida (a espera é compartilhada; o rollback transacional de um `up` nunca pode apagá-la).
  - `SandboxFixture.network_unit` (nome prefixado, registrado).

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_supervisor.py`, acrescentar `import os` aos imports do
topo e, no fim do arquivo (antes de `if __name__`, se houver), a classe:

```python
class TestNetworkGateUnits(unittest.TestCase):
    """Emenda A §3/§4: toda unidade de container espera a conectividade real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.runtime_dir = self.root / "runtime" / "rev1"
        self.runtime_dir.mkdir(parents=True)
        self.launcher = self.runtime_dir / "launcher.sh"
        self.launcher.write_text("#!/bin/sh\nexit 0\n")
        self.state_dir = self.root / "state" / "ws"
        self.state_dir.mkdir(parents=True)
        self.manifest = self.state_dir / "runtime.json"

    def _unit_text(self, role: str, **kwargs) -> str:
        return supervisor.render_unit(supervisor.ContainerUnit(
            name=f"asb-ws-{role}",
            container_id="c1",
            role=role,
            unit_name=f"asb-ws-{role}.service",
            target_name="asb-ws.target",
            helper_path=self.launcher,
            manifest_path=self.manifest,
            **kwargs,
        ))

    def test_render_network_unit_is_an_infinite_oneshot_gate(self):
        gate = self.runtime_dir / "network_gate.py"
        text = supervisor.render_network_unit(gate)
        for line in ("Type=oneshot", "RemainAfterExit=yes",
                     "TimeoutStartSec=infinity", "Restart=on-failure"):
            self.assertIn(line + "\n", text)
        self.assertIn(f"ExecStart={gate}\n", text)
        self.assertNotIn("podman", text)
        self.assertNotIn("unshare", text)
        self.assertNotIn("Environment=", text)
        self.assertNotIn("[Install]", text)

    def test_render_network_unit_pins_the_gate_target_when_given(self):
        text = supervisor.render_network_unit(
            self.runtime_dir / "network_gate.py", target="127.0.0.1:18080")
        self.assertIn("Environment=ASB_NETWORK_GATE_TARGET=127.0.0.1:18080\n", text)

    def test_every_container_role_requires_and_orders_after_the_gate(self):
        for role in ("proxy", "agent", "forwarder", "docker", "svc-db"):
            with self.subTest(role=role):
                text = self._unit_text(role)
                self.assertIn("Requires=asb-network.service\n", text)
                after = next(l for l in text.splitlines() if l.startswith("After="))
                self.assertIn("asb-network.service", after.split("=", 1)[1].split())

    def test_network_unit_none_omits_the_dependency(self):
        text = self._unit_text("proxy", network_unit=None)
        self.assertNotIn("Requires=", text)
        self.assertNotIn("asb-network.service", text)

    def test_network_unit_name_honors_the_isolation_environment(self):
        with mock.patch.dict(os.environ, {"ASB_NETWORK_UNIT": "asb-test-x-network.service"}):
            self.assertEqual(supervisor.network_unit_name(), "asb-test-x-network.service")
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("ASB_NETWORK_UNIT", None)
            self.assertEqual(supervisor.network_unit_name(), "asb-network.service")

    def test_install_workspace_writes_the_shared_gate_and_wires_every_unit(self):
        unit_dir = self.root / "units"
        self.manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "workspace": "ws",
            "containers": {
                "proxy": {"name": "asb-ws-proxy", "id": "p1"},
                "agent": {"name": "asb-ws-agent", "id": "a1"},
                "forwarder": {"name": "asb-ws-fwd", "id": "f1", "unit": "asb-ws-fwd.service"},
            },
        }))
        with mock.patch.dict(os.environ, {"ASB_NETWORK_GATE_TARGET": "127.0.0.1:18080"}), \
             mock.patch("asb.supervisor.subprocess.run") as run:
            os.environ.pop("ASB_NETWORK_UNIT", None)
            written = supervisor.install_workspace(
                "ws", target_dir=unit_dir, state_dir=self.state_dir, helper_path=self.launcher)

        gate = unit_dir / "asb-network.service"
        self.assertTrue(gate.is_file())
        gate_text = gate.read_text(encoding="utf-8")
        self.assertIn(f"ExecStart={self.runtime_dir / 'network_gate.py'}\n", gate_text)
        self.assertIn("Environment=ASB_NETWORK_GATE_TARGET=127.0.0.1:18080\n", gate_text)
        # Compartilhada: nunca devolvida para o rollback transacional apagar.
        self.assertNotIn(gate, written)
        for unit in ("asb-ws-proxy.service", "asb-ws-agent.service", "asb-ws-fwd.service"):
            self.assertIn("Requires=asb-network.service\n",
                          (unit_dir / unit).read_text(encoding="utf-8"))
        run.assert_called_with(["systemctl", "--user", "daemon-reload"], check=True)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_supervisor.py' -k TestNetworkGateUnits -v`
Expected: ERROR com `AttributeError: module 'asb.supervisor' has no attribute 'render_network_unit'`.

- [ ] **Step 3: Implementar em `cli/asb/supervisor.py`**

3a. Logo antes de `@dataclass(frozen=True)` / `class ContainerUnit:`, adicionar:

```python
NETWORK_UNIT = "asb-network.service"


def network_unit_name() -> str:
    """Nome da espera por rede; `ASB_NETWORK_UNIT` isola testes de integracao."""
    return os.environ.get("ASB_NETWORK_UNIT") or NETWORK_UNIT
```

3b. Em `ContainerUnit`, depois da linha `keyring_unit: str | None = "asb-keyring.service"`, adicionar o campo:

```python
    network_unit: str | None = NETWORK_UNIT
```

e, em `__post_init__`, logo depois do bloco que valida `self.keyring_unit`:

```python
        if self.network_unit is not None:
            if not isinstance(self.network_unit, str):
                raise TypeError(f"network_unit must be a string or None, got {type(self.network_unit).__name__}")
            _validate_safe_name(self.network_unit, "network_unit")
```

3c. Em `render_unit`, substituir:

```python
    else:
        after_deps = unit.extra_after
        wants_deps = unit.extra_wants

    after_line = f"After={' '.join(after_deps)}\n" if after_deps else ""
```

por:

```python
    else:
        after_deps = unit.extra_after
        wants_deps = unit.extra_wants

    # Emenda A §3: toda unidade de container espera a conectividade real do
    # host. Qualquer container bridge que partisse antes criaria o namespace
    # rootless cedo, sem egresso, e nada a jusante o repararia.
    network_deps = (unit.network_unit,) if unit.network_unit else ()
    after_deps = tuple(dict.fromkeys(network_deps + tuple(after_deps)))
    requires_line = f"Requires={' '.join(network_deps)}\n" if network_deps else ""

    after_line = f"After={' '.join(after_deps)}\n" if after_deps else ""
```

e, no `return` de `render_unit`, substituir:

```python
        f"PartOf={target}\n"
        f"{after_line}"
```

por:

```python
        f"PartOf={target}\n"
        f"{requires_line}"
        f"{after_line}"
```

3d. Logo depois da função `render_target`, adicionar:

```python
def render_network_unit(gate_path: Path, target: str | None = None) -> str:
    """Renderiza a espera unica por conectividade real (Emenda A §4).

    `TimeoutStartSec=infinity`: sem rede, os workspaces aguardam e sobem
    sozinhos quando ela chegar. `Restart=on-failure` cobre so falha do proprio
    script; ausencia de rede nao e falha. Sem `[Install]`: quem a puxa sao as
    unidades de workspace, por `Requires=`.
    """
    gate_escaped = escape_systemd_arg(gate_path)
    env_line = (
        f"Environment=ASB_NETWORK_GATE_TARGET={escape_systemd_arg(target)}\n"
        if target else ""
    )
    return (
        "[Unit]\n"
        "Description=Agent Sandbox: espera por conectividade real\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        "TimeoutStartSec=infinity\n"
        "Restart=on-failure\n"
        "RestartSec=5s\n"
        f"{env_line}"
        f"ExecStart={gate_escaped}\n"
    )
```

3e. Em `install_workspace`, substituir:

```python
    written_files: list[Path] = []
    unit_names: list[str] = []
```

por:

```python
    written_files: list[Path] = []
    unit_names: list[str] = []

    # Espera unica por rede, compartilhada por todo workspace. Fica FORA de
    # `written_files`: essa lista alimenta o rollback transacional do `up`, e
    # a falha de um workspace nunca pode apagar a espera dos outros.
    gate_path = (
        helper_path / "network_gate.py"
        if helper_path.is_dir()
        else helper_path.parent / "network_gate.py"
    )
    network_unit = network_unit_name()
    _atomic_write_text(
        target_path / network_unit,
        render_network_unit(gate_path, target=os.environ.get("ASB_NETWORK_GATE_TARGET") or None),
    )
```

e, na construção de `ContainerUnit(...)` dentro do laço, acrescentar o argumento:

```python
            network_unit=network_unit,
```

3f. Em `__all__`, acrescentar `"NETWORK_UNIT"`, `"network_unit_name"` e `"render_network_unit"`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_supervisor.py' -v`
Expected: `OK` (os testes existentes de `render_unit` e `install_workspace` continuam verdes).

- [ ] **Step 5: Isolar a unidade de rede nos testes de integração**

Em `tests/integration/sandbox_fixture.py`, no `__init__`, logo abaixo de
`self.keyring_container = f"{self._prefix}-keyring"`, adicionar:

```python
        self.network_unit = f"{self._prefix}-network.service"
```

e, logo abaixo de `self._registered_units.add(f"{self._prefix}-keyring.service")`, adicionar:

```python
        self._registered_units.add(self.network_unit)
```

Em `cli()`, logo abaixo de `env["ASB_STATE_ROOT"] = str(self.state_root / "state")`, adicionar:

```python
        env["ASB_NETWORK_UNIT"] = self.network_unit
```

Em `tests/integration/test_startup_auth.py`, no dicionário `self.cli_env`, logo
abaixo da linha `"ASB_CONFIG_ROOT": str(self.config_dir),`, adicionar:

```python
            "ASB_NETWORK_UNIT": self.network_unit,
            "ASB_NETWORK_GATE_TARGET": f"127.0.0.1:{self.control.server_address[1]}",
```

- [ ] **Step 6: Confirmar que a fixture não regrediu**

Run: `python3 -m unittest discover -s tests/integration -p 'test_sandbox_fixture_guard.py' -v`
Expected: `OK`.

- [ ] **Step 7: Commit**

Pelo `commit-curator`, staging de `cli/asb/supervisor.py`,
`tests/unit/test_supervisor.py`, `tests/integration/sandbox_fixture.py`,
`tests/integration/test_startup_auth.py`. Título sugerido:
`✨ exigir espera de rede em toda unidade de workspace: Emenda A`.

---

### Task 3: Sonda de prontidão do keyring no `runtime_check`

**Files:**
- Modify: `cli/asb/runtime_check.py` (parser e início de `main`)
- Test: `tests/unit/test_runtime_check.py` (novo)

**Interfaces:**
- Consumes: `readiness.probe_keyring(container: str | None, timeout: float) -> ProbeResult`, `readiness.wait_until`.
- Produces: `runtime_check.py --role keyring --container <nome>` → 0 pronto, 1 indisponível, 2 uso inválido. Para `keyring`, `--manifest` não é exigido.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/unit/test_runtime_check.py`:

```python
"""Unit tests for cli/asb/runtime_check.py — papel keyring (Emenda A §5)."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import runtime_check  # noqa: E402
from asb.readiness import ProbeResult  # noqa: E402


def _once(probe, *, timeout, interval=1.0):
    return probe(1.0)


class TestKeyringRole(unittest.TestCase):
    def _main(self, argv, keyring_state="healthy"):
        result = ProbeResult("keyring", keyring_state,
                             "ok" if keyring_state == "healthy" else "keyring_unavailable", 0, "fix")
        stderr = io.StringIO()
        with mock.patch("asb.runtime_check.wait_until", side_effect=_once), \
             mock.patch("asb.runtime_check.probe_keyring", return_value=result) as probe, \
             contextlib.redirect_stderr(stderr):
            rc = runtime_check.main(argv)
        return rc, probe, stderr.getvalue()

    def test_keyring_ready_returns_zero_without_a_manifest(self):
        rc, probe, _ = self._main(["--role", "keyring", "--container", "asb-keyring"])
        self.assertEqual(rc, 0)
        probe.assert_called_once_with(container="asb-keyring", timeout=1.0)

    def test_keyring_unavailable_returns_one(self):
        rc, _, err = self._main(["--role", "keyring", "--container", "asb-keyring"],
                                keyring_state="failed")
        self.assertEqual(rc, 1)
        self.assertIn("keyring_unavailable", err)

    def test_keyring_without_container_is_a_usage_error(self):
        rc, probe, err = self._main(["--role", "keyring"])
        self.assertEqual(rc, 2)
        probe.assert_not_called()
        self.assertIn("--container", err)

    def test_proxy_still_requires_a_manifest(self):
        rc, _, _ = self._main(["--role", "proxy"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_runtime_check.py' -v`
Expected: FAIL/ERROR — o argparse rejeita `keyring` (`SystemExit: 2` em `invalid choice`).

- [ ] **Step 3: Implementar**

Em `cli/asb/runtime_check.py`, substituir:

```python
    parser.add_argument("pos_role", nargs="?", default=None, choices=["proxy", "agent"], help="Papel do container")
    parser.add_argument("--manifest", dest="manifest", default=None, help="Caminho do manifesto runtime.json")
    parser.add_argument("--role", dest="role", default=None, choices=["proxy", "agent"], help="Papel do container")

    args = parser.parse_args(argv)

    manifest_path_str = args.manifest or args.pos_manifest
    role = args.role or args.pos_role
```

por:

```python
    parser.add_argument("pos_role", nargs="?", default=None, choices=["proxy", "agent", "keyring"], help="Papel do container")
    parser.add_argument("--manifest", dest="manifest", default=None, help="Caminho do manifesto runtime.json")
    parser.add_argument("--role", dest="role", default=None, choices=["proxy", "agent", "keyring"], help="Papel do container")
    parser.add_argument("--container", dest="container", default=None, help="Container do keyring (papel keyring)")

    args = parser.parse_args(argv)

    manifest_path_str = args.manifest or args.pos_manifest
    role = args.role or args.pos_role

    # Emenda A §5: o keyring singleton nao tem manifesto de workspace. A unidade
    # so fica ativa depois que o Secret Service responde; sem isso, o
    # `After=` do agente esperaria apenas o inicio do processo.
    if role == "keyring":
        if not args.container:
            print("runtime_check [keyring]: --container e obrigatorio", file=sys.stderr)
            return 2
        keyring_res = wait_until(
            lambda t: probe_keyring(container=args.container, timeout=t),
            timeout=30.0,
            interval=1.0,
        )
        if keyring_res.state != "healthy":
            print(f"runtime_check [keyring]: keyring indisponivel: {keyring_res.code} -> {keyring_res.remediation}", file=sys.stderr)
            return 1
        return 0
```

Atualizar a docstring do módulo: `Consome um manifesto validado e o papel do container ('proxy', 'agent') ou, para 'keyring', o nome do container.`

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_runtime_check.py' -v`
Expected: `OK` (4 testes).

- [ ] **Step 5: Commit**

Pelo `commit-curator`, staging de `cli/asb/runtime_check.py`,
`tests/unit/test_runtime_check.py`. Título sugerido:
`✨ adicionar sonda de prontidao do keyring ao runtime_check: Emenda A`.

---

### Task 4: `up` e `prepare_workspace` com runtime único

**Files:**
- Modify: `cli/asb/lifecycle.py` (novo `ensure_runtime` logo depois de `_current_revision`, linha ~555; `prepare_workspace`, linha ~569; `up`, linha ~795; `_up`, linha ~869)
- Test: `tests/unit/test_lifecycle.py`

**Interfaces:**
- Consumes: `install.remove_project_dropin() -> bool`; `readiness.wait_until`; `readiness.probe_host`; `supervisor.install_workspace`; `supervisor.start_workspace(ws, enable=True)`.
- Produces:
  - `lifecycle.ensure_runtime(root: Path) -> Path` — instala o runtime da revisão atual e devolve o diretório.
  - `lifecycle.prepare_workspace(root: Path, ws: str, repo: Path, tx: WorkspaceTransaction | None = None) -> None`
  - `lifecycle.up(root: Path, ws: str, repo: Path) -> int`
  - `lifecycle._up(root: Path, ws: str, repo: Path) -> int`
  - Manifesto: `runtime_type` e `runtime_backend` sempre `"systemd"`; `revision` = nome do diretório do runtime.
  - Sem rede, `up` levanta `podman.PodmanError` contendo `"sem conectividade real"` antes de criar recurso.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_lifecycle.py`, **apagar** estes testes, que exigem o
comportamento removido:
- `TestLifecycleOrdering.test_up_ensures_rootless_netns_before_proxy_run`
- `TestTransactionalRollback.test_up_runtime_systemd_creates_containers_with_restart_no`

E acrescentar a classe:

```python
class TestSingleRuntimeUp(unittest.TestCase):
    """Emenda A: `up` tem runtime unico, remove o drop-in, verifica o host e nunca roda `unshare`."""

    def _run_up(self, *, host_state: str = "healthy"):
        import json
        from contextlib import ExitStack
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.profile import Profile
        from cli.asb.readiness import ProbeResult
        from cli.asb.workspace import Layout

        events: list[str] = []
        podman_calls: list[list[str]] = []

        def fake_run(*args, **kwargs):
            podman_calls.append(list(args))
            if args and args[0] in ("create", "network"):
                events.append(f"podman {args[0]}")
            return mock.MagicMock(returncode=0, stdout="cid-12345")

        def fake_probe_host(**kwargs):
            events.append("host-probe")
            code = "ok" if host_state == "healthy" else "timeout"
            return ProbeResult("host", host_state, code, 0, "")

        def fake_remove_dropin(*args, **kwargs):
            events.append("remove-dropin")
            return False

        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)
        fake_root, fake_state, fake_mount, fake_repo = (
            tmp / name for name in ("root", "state", "mount", "origin"))
        for d in (fake_root, fake_state, fake_mount, fake_repo):
            d.mkdir(parents=True)
        runtime_dir = tmp / "runtime" / "rev1"
        runtime_dir.mkdir(parents=True)
        fake_layout = Layout(ws="demo", project="proj", mount=fake_mount,
                             project_root=fake_mount / "proj", state=fake_state)
        fake_key = tmp / "key"
        fake_key.write_text("dummy")
        (tmp / "key.pub").write_text("ssh-ed25519 AAA dummy")
        fake_profile = Profile(services=[], host_ports=[], publish_ports=[],
                               host_api="none", container_mode="standard", allow=[])
        healthy = ProbeResult("probe", "healthy", "ok", 0, "")

        error = None
        rc = None
        with ExitStack() as stack:
            stack.enter_context(mock.patch("cli.asb.podman.exists", side_effect=lambda kind, name: kind == "image"))
            stack.enter_context(mock.patch("cli.asb.podman.run", side_effect=fake_run))
            stack.enter_context(mock.patch("cli.asb.podman.out", return_value="127.0.0.1:2222"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.load_profile", return_value=fake_profile))
            stack.enter_context(mock.patch("cli.asb.lifecycle.layout_for", return_value=fake_layout))
            stack.enter_context(mock.patch("cli.asb.lifecycle.prepare_clone"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.render", return_value="acl x"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.build_staging", return_value=0))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_ssh_key", return_value=fake_key))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_service"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_keyring_runtime_volume", return_value="k-run"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_credentials_volume", return_value="c-vol"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.credential_mount_args", return_value=[]))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_session_volume", return_value="asb-demo-session"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.ensure_toolcache_volume", return_value="t-vol"))
            stack.enter_context(mock.patch("cli.asb.lifecycle.discover_mise_dirs", return_value=[]))
            stack.enter_context(mock.patch("cli.asb.lifecycle.emit", return_value=0))
            stack.enter_context(mock.patch("cli.asb.install.remove_project_dropin", side_effect=fake_remove_dropin))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_host", side_effect=fake_probe_host))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_proxy", return_value=healthy))
            stack.enter_context(mock.patch("cli.asb.readiness.probe_ssh", return_value=healthy))
            stack.enter_context(mock.patch(
                "cli.asb.readiness.wait_until",
                side_effect=lambda probe, *, timeout, interval=1.0: probe(1.0)))
            mock_install = stack.enter_context(mock.patch(
                "cli.asb.lifecycle.supervisor.install_workspace", return_value=[]))
            mock_start = stack.enter_context(mock.patch(
                "cli.asb.lifecycle.supervisor.start_workspace",
                side_effect=lambda ws, **kw: events.append("start-target")))
            try:
                rc = lifecycle.up(fake_root, "demo", fake_repo)
            except lifecycle.podman.PodmanError as exc:
                error = exc

        manifest_file = fake_state / "runtime.json"
        manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else None
        return rc, error, events, podman_calls, mock_install, mock_start, manifest

    def test_up_creates_stopped_containers_without_restart_policy_and_starts_the_target(self):
        rc, error, _, podman_calls, mock_install, mock_start, manifest = self._run_up()
        self.assertIsNone(error)
        self.assertEqual(rc, 0)
        self.assertNotIn("run", {call[0] for call in podman_calls if call})
        creates = [call for call in podman_calls if call and call[0] == "create"]
        self.assertTrue(creates)
        for call in creates:
            self.assertEqual(call[call.index("--restart") + 1], "no")
            self.assertNotIn("-d", call)
        mock_install.assert_called_once()
        mock_start.assert_called_once_with("demo", enable=True)
        self.assertEqual(manifest["runtime_type"], "systemd")
        self.assertEqual(manifest["runtime_backend"], "systemd")
        self.assertEqual(manifest["revision"], "rev1")

    def test_up_removes_the_project_dropin_and_checks_the_host_before_creating_resources(self):
        _, error, events, _, _, _, _ = self._run_up()
        self.assertIsNone(error)
        self.assertEqual(events[:2], ["remove-dropin", "host-probe"])
        first_resource = next(i for i, e in enumerate(events) if e.startswith("podman "))
        self.assertLess(events.index("host-probe"), first_resource)
        self.assertLess(first_resource, events.index("start-target"))

    def test_up_without_network_fails_before_creating_any_resource(self):
        rc, error, _, podman_calls, mock_install, mock_start, manifest = self._run_up(
            host_state="unreachable")
        self.assertIsNone(rc)
        self.assertIsNotNone(error)
        self.assertIn("sem conectividade real", str(error))
        self.assertEqual(
            [c for c in podman_calls if c and c[0] in ("create", "network", "build")], [])
        mock_install.assert_not_called()
        mock_start.assert_not_called()
        self.assertIsNone(manifest)

    def test_up_never_initializes_the_rootless_namespace(self):
        _, error, _, podman_calls, _, _, _ = self._run_up()
        self.assertIsNone(error)
        self.assertEqual([c for c in podman_calls if c and c[0] == "unshare"], [])
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -k TestSingleRuntimeUp -v`
Expected: FAIL/ERROR — `mock.patch("cli.asb.lifecycle.ensure_runtime")` levanta `AttributeError` (ainda não existe).

- [ ] **Step 3: Implementar `ensure_runtime`**

Em `cli/asb/lifecycle.py`, logo depois da função `_current_revision`, adicionar:

```python
def ensure_runtime(root: Path) -> Path:
    """Instala o runtime versionado desta revisao e devolve o diretorio.

    Emenda A: todo workspace e o keyring sao unidades systemd, e as unidades
    executam `launcher.sh`, `runtime_check.py` e `network_gate.py` desse
    diretorio, nunca do checkout.
    """
    return install_runtime(root, _current_revision(root))
```

- [ ] **Step 4: Runtime único em `prepare_workspace`**

4a. Na assinatura, remover a linha `    runtime: str = "legacy",`.

4b. Remover a linha `    podman.ensure_rootless_netns()` (logo antes de `build_proxy(root)`).

4c. Substituir:

```python
    cmd_action = "create" if runtime == "systemd" else "run"
    cmd_flags = ["-d"] if cmd_action == "run" else []
    restart_policy = "no" if runtime == "systemd" else "unless-stopped"
```

por:

```python
    # Runtime unico (Emenda A): todo container ASB nasce parado e sem politica
    # de reinicio do Podman; quem o inicia e reinicia e sempre o systemd.
    cmd_action = "create"
    cmd_flags: list[str] = []
    restart_policy = "no"
```

4d. Substituir a linha `    ensure_keyring_service()` (antes de `agent_args = [`) por:

```python
    runtime_dir = ensure_runtime(root)
    ensure_keyring_service()
```

4e. No dicionário `manifest_data`, substituir:

```python
        "runtime_type": runtime,
        "runtime_backend": runtime,
```

por:

```python
        "runtime_type": "systemd",
        "runtime_backend": "systemd",
```

4f. Substituir:

```python
    if runtime == "systemd":
        rev = _current_revision(root)
        if (root / "cli" / "asb").is_dir():
            install_runtime(root, rev)
            manifest_data["revision"] = rev
```

por:

```python
    manifest_data["revision"] = runtime_dir.name
```

4g. Substituir:

```python
    # 7. Instalar unidades systemd se runtime gerenciado
    if runtime == "systemd":
        units = supervisor.install_workspace(ws, state_dir=layout.state)
        if tx and isinstance(units, (list, tuple)):
            for u in units:
                tx.record_unit(u)
```

por:

```python
    # 7. Instalar unidades systemd (runtime unico)
    units = supervisor.install_workspace(ws, state_dir=layout.state)
    if tx and isinstance(units, (list, tuple)):
        for u in units:
            tx.record_unit(u)
```

4h. Nas assinaturas de `start_services` e `start_forwarder`, trocar os padrões
`cmd_action: str = "run"` por `cmd_action: str = "create"` e
`restart: str = "unless-stopped"` por `restart: str = "no"`.

- [ ] **Step 5: Runtime único em `up`**

5a. Trocar `def up(root: Path, ws: str, repo: Path, runtime: str = "legacy") -> int:` por `def up(root: Path, ws: str, repo: Path) -> int:`.

5b. Substituir o trecho que vai de `    tx = WorkspaceTransaction(ws, is_existing=False)` até a chamada `            install.podman_restart()` (inclusive) por:

```python
    # Emenda A §5: o drop-in legado do podman-restart criava o namespace
    # rootless cedo em todo boot. Remocao idempotente e segura: so sai se o
    # conteudo for exatamente o do projeto; drop-ins alheios ficam intactos.
    if install.remove_project_dropin():
        print("drop-in legado do podman-restart removido", file=sys.stderr)

    # Emenda A §4: a espera de boot e sem limite, mas um `up` interativo sem
    # rede ficaria preso em `systemctl start`. Falha antes de criar qualquer
    # recurso, com sonda so do host: nao cria o namespace rootless.
    host_res = readiness.wait_until(
        lambda to: readiness.probe_host(timeout=to), timeout=30.0)
    if host_res.state != "healthy":
        raise podman.PodmanError(
            f"sem conectividade real ({host_res.code}); conecte a rede e "
            "rode 'asb-agent up' de novo")

    tx = WorkspaceTransaction(ws, is_existing=False)
    home = Path(os.path.expanduser("~"))
    layout = layout_for(repo, ws, home)
    try:
        prepare_workspace(root, ws, repo, tx=tx)
        supervisor.start_workspace(ws, enable=True)
```

5c. Trocar `_up` por:

```python
def _up(root: Path, ws: str, repo: Path) -> int:
    return up(root, ws, repo)
```

- [ ] **Step 6: Converter os testes de `up` que continuam valendo**

Em `tests/unit/test_lifecycle.py`, nos testes abaixo, aplicar exatamente as
edições (a)–(g), apenas onde cada uma se aplicar:

- `TestLifecycleOrdering.test_up_ensures_keyring_service_and_mounts_runtime_without_pass` → renomear para `test_up_ensures_keyring_service_before_creating_the_agent_and_mounts_runtime_without_pass`
- `TestTransactionalRollback.test_up_existing_workspace_failure_does_not_sweep`
- `TestTransactionalRollback.test_up_on_already_existing_container_does_not_sweep`
- `TestTransactionalRollback.test_up_rollback_by_id_in_new_workspace_cleans_only_tracked_ids`
- `TestTransactionalRollback.test_up_proxy_readiness_failure_before_mise_install`
- `TestTransactionalRollback.test_up_rolls_back_when_credential_mount_setup_fails`
- `TestTransactionalRollback.test_up_ssh_readiness_failure_propagates_and_does_not_emit`
- `TestTransactionalRollback.test_up_with_host_ports_writes_forwarder_manifest_entry`
- `TestTransactionalRollback.test_up_resolves_ssh_port_once_and_reuses_it_in_emit`
- `TestTransactionalRollback.test_up_rollback_removes_real_units_and_logs_removal_failure`

(a) Nas chamadas `up(...)`/`_up(...)`/`lifecycle.up(...)`, remover o argumento `runtime=...`.
(b) Onde a chamada chega a `prepare_workspace`, acrescentar ao bloco de patches, criando o diretório antes: `mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=<tmp> / "runtime" / "rev1")`.
(c) Acrescentar `mock.patch("cli.asb.install.remove_project_dropin", return_value=False)`.
(d) Onde `cli.asb.readiness.wait_until` é mockado com `return_value=<resultado>`, a primeira chamada agora é a sonda do host. Para forçar falha do proxy, usar `side_effect=[<saudavel>, <falho>]`; para falha de SSH, `side_effect=[<saudavel>, <saudavel>, <falho>]`; nos demais, manter `return_value` saudável.
(e) Remover os patches de `ensure_rootless_netns` e de `install.podman_restart`, e toda asserção sobre eles (inclusive `mock_restart.assert_called_once()`).
(f) Onde o teste espera o verbo `"run"` do Podman para criar container, trocar por `"create"`; onde espera `"-d"`, remover; onde espera `unless-stopped`, trocar por `no`. Em `side_effect` que filtra `args[0] == "run"` para registrar eventos de criação, trocar por `args[0] == "create"`.
(g) Se o teste não mocka `cli.asb.lifecycle.supervisor.install_workspace` e `cli.asb.lifecycle.supervisor.start_workspace`, acrescentar os dois patches (`return_value=[]` e mock simples).

- [ ] **Step 7: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -v`
Expected: `OK`. Os testes de `resume`/`suspend`/`down` ainda usam `_runtime_of` e continuam verdes nesta task.

Run: `python3 -m unittest discover -s tests/unit`
Expected: `OK`. Se `test_broker.py` ou `test_login_flow.py` falharem por chamar `up`/`prepare_workspace`, aplicar neles as mesmas edições (a)–(g).

- [ ] **Step 8: Commit**

Pelo `commit-curator`, staging de `cli/asb/lifecycle.py`,
`tests/unit/test_lifecycle.py` e de qualquer outro teste ajustado no Step 7.
Título sugerido: `🐛 unificar up no runtime systemd e esperar a rede: Emenda A`.

---

### Task 5: `resume`, `suspend` e `down` com runtime único

**Files:**
- Modify: `cli/asb/lifecycle.py` (`_runtime_of`, linha ~394; `down`, linha ~894; `suspend`, linha ~959; `resume`, linha ~1012)
- Test: `tests/unit/test_lifecycle.py`

**Interfaces:**
- Consumes: `lifecycle.ensure_runtime` (Task 4), `readiness.probe_host`, `supervisor.start_workspace(ws)`, `supervisor.remove_workspace_units`.
- Produces:
  - `resume(root, ws)`: sem rede devolve 1 antes de tocar keyring ou target; nunca roda `unshare`.
  - `suspend(ws)`: sempre `disable` + `stop` do target e verificação por Podman.
  - `down(ws)`: sempre tenta remover as unidades, best-effort.
  - `lifecycle._runtime_of` deixa de existir.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_lifecycle.py`, **apagar**:
- `TestLifecycleOrdering.test_resume_ensures_rootless_netns_before_proxy_start`
- `TestLifecycleOrdering.test_resume_ensures_keyring_service_before_starting_containers`
- a classe inteira `TestRuntimeOf`
- `TestManagedLifecycleCommands.test_suspend_legacy_stops_containers_directly`
- `TestManagedLifecycleCommands.test_down_legacy_does_not_call_remove_workspace_units`

E acrescentar:

```python
class TestSingleRuntimeResume(unittest.TestCase):
    """Emenda A: `resume` verifica o host, garante o keyring, sobe o target e nunca roda `unshare`."""

    def _run_resume(self, *, host_state: str = "healthy"):
        from unittest import mock
        from cli.asb import lifecycle
        from cli.asb.readiness import ProbeResult
        from cli.asb.workspace import Layout

        events: list[str] = []
        podman_calls: list[list[str]] = []
        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)
        state = tmp / "state"
        state.mkdir()
        runtime_dir = tmp / "runtime" / "rev1"
        runtime_dir.mkdir(parents=True)
        layout = Layout(ws="demo", project="proj", mount=tmp / "mount",
                        project_root=tmp / "mount" / "proj", state=state)
        names = {"net": "asb-demo", "out": "asb-demo-out",
                 "agent": "asb-demo-agent", "proxy": "asb-demo-proxy"}
        healthy = ProbeResult("probe", "healthy", "ok", 0, "")

        def fake_probe_host(**kwargs):
            events.append("host-probe")
            code = "ok" if host_state == "healthy" else "timeout"
            return ProbeResult("host", host_state, code, 0, "")

        def fake_podman_run(*args, **kwargs):
            podman_calls.append(list(args))
            return mock.MagicMock(returncode=0)

        with mock.patch("cli.asb.lifecycle._require_workspace",
                        return_value=(names, tmp / "home", tmp / "origin")), \
             mock.patch("cli.asb.lifecycle.layout_for", return_value=layout), \
             mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=runtime_dir), \
             mock.patch("cli.asb.lifecycle.ensure_keyring_service",
                        side_effect=lambda *a, **k: events.append("keyring")) as mock_keyring, \
             mock.patch("cli.asb.lifecycle.subprocess.run", return_value=mock.MagicMock(returncode=0)), \
             mock.patch("cli.asb.lifecycle.supervisor.start_workspace",
                        side_effect=lambda ws, **kw: events.append("start-target")) as mock_start, \
             mock.patch("cli.asb.lifecycle.podman.run", side_effect=fake_podman_run), \
             mock.patch("cli.asb.readiness.probe_host", side_effect=fake_probe_host), \
             mock.patch("cli.asb.readiness.probe_workspace", return_value=[healthy]), \
             mock.patch("cli.asb.readiness.wait_until",
                        side_effect=lambda probe, *, timeout, interval=1.0: probe(1.0)), \
             mock.patch("cli.asb.lifecycle.emit", return_value=0):
            rc = lifecycle.resume(tmp / "root", "demo")
        return rc, events, podman_calls, mock_keyring, mock_start

    def test_resume_checks_the_host_then_the_keyring_then_starts_the_target(self):
        rc, events, _, _, mock_start = self._run_resume()
        self.assertEqual(rc, 0)
        self.assertEqual(events, ["host-probe", "keyring", "start-target"])
        mock_start.assert_called_once_with("demo")

    def test_resume_without_network_returns_1_before_keyring_or_target(self):
        rc, events, _, mock_keyring, mock_start = self._run_resume(host_state="unreachable")
        self.assertEqual(rc, 1)
        self.assertEqual(events, ["host-probe"])
        mock_keyring.assert_not_called()
        mock_start.assert_not_called()

    def test_resume_never_initializes_the_rootless_namespace(self):
        rc, _, podman_calls, _, _ = self._run_resume()
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in podman_calls if c and c[0] == "unshare"], [])


class TestNoRuntimeSelection(unittest.TestCase):
    def test_runtime_selection_helper_no_longer_exists(self):
        from cli.asb import lifecycle
        self.assertFalse(hasattr(lifecycle, "_runtime_of"))
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -k "TestSingleRuntimeResume or TestNoRuntimeSelection" -v`
Expected: FAIL — `resume` ainda não consulta o host (`events` não começa com `host-probe`) e `_runtime_of` ainda existe.

- [ ] **Step 3: Implementar `resume`**

Substituir o corpo de `resume` desde `    n, home, origin = _require_workspace(ws)` até a linha `            if container != n["proxy"] and podman.exists("container", container):` / `                podman.run("start", container, check=False)` (fim do ramo `else:` legacy, inclusive) por:

```python
    _, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)

    # Emenda A §4: mesmo motivo do `up`. Sem rede, `systemctl start` ficaria
    # preso na espera sem limite; aqui a falha e imediata e nada e tocado.
    host_res = readiness.wait_until(
        lambda to: readiness.probe_host(timeout=to), timeout=30.0)
    if host_res.state != "healthy":
        print(f"erro: sem conectividade real ({host_res.code}); conecte a rede "
              "e rode 'asb-agent resume' de novo", file=sys.stderr)
        return 1

    ensure_keyring_service()

    target = f"asb-{ws}.target"
    subprocess.run(["systemctl", "--user", "enable", target], check=True)
    reset_units = [target]
    manifest_file = layout.state / "runtime.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            for info in manifest.get("containers", {}).values():
                if isinstance(info, dict) and "unit" in info:
                    reset_units.append(info["unit"])
        except Exception:
            pass
    subprocess.run(
        ["systemctl", "--user", "reset-failed", *reset_units],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    supervisor.start_workspace(ws)
```

Atualizar a docstring de `resume` para:

```python
    """Religa o workspace pelo systemd.

    Verifica a conectividade do host, garante o keyring, habilita o target,
    executa reset-failed nas unidades do workspace e inicia o target. O JSON
    de conexao so e emitido depois que readiness.probe_workspace reporta tudo
    saudavel.
    """
```

No comentário do gate de prontidão logo abaixo, trocar a frase inicial
`# Gate de prontidao COMUM aos dois runtimes:` por `# Gate de prontidao:` e
remover as frases que citam o ramo legacy.

- [ ] **Step 4: Implementar `suspend`**

Substituir:

```python
    n, home, origin = _require_workspace(ws)
    runtime = _runtime_of(ws, home)

    if runtime == "systemd":
        target = f"asb-{ws}.target"
        subprocess.run(
            ["systemctl", "--user", "disable", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["systemctl", "--user", "stop", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
```

por:

```python
    n, _, _ = _require_workspace(ws)

    target = f"asb-{ws}.target"
    subprocess.run(
        ["systemctl", "--user", "disable", target],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["systemctl", "--user", "stop", target],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
```

Docstring de `suspend`:

```python
    """Para o workspace: desabilita e para o target systemd e verifica que todos os containers pararam."""
```

- [ ] **Step 5: Implementar `down`**

Substituir o bloco que começa em `    # Remove unidades systemd SOMENTE para workspaces geridos por systemd:` e termina no `print(...)` do `except Exception as exc:` de `remove_workspace_units` (inclusive) por:

```python
    # Runtime unico (Emenda A): todo workspace tem unidades. `down` e a saida
    # de emergencia de um workspace quebrado, entao a remocao das unidades e
    # best-effort e nunca aborta a limpeza de containers e redes abaixo —
    # nem com `daemon-reload` falhando, nem sem `systemctl` no PATH, nem com
    # manifesto corrompido.
    try:
        supervisor.remove_workspace_units(
            ws, state_dir=home / ".local" / "state" / "agent-sandbox" / ws)
    except Exception as exc:
        print(f"aviso: falha ao remover unidades systemd de {ws}: {exc}; "
              "seguindo com limpeza local", file=sys.stderr)
```

- [ ] **Step 6: Remover `_runtime_of`**

Apagar a função `_runtime_of` inteira.

- [ ] **Step 7: Converter os testes que continuam valendo**

Em `tests/unit/test_lifecycle.py`:

7a. `TestResumeReadinessGate`:
- Renomear o método `_run_legacy_resume` para `_run_resume` e suas chamadas.
- Dentro dele, acrescentar `from cli.asb.readiness import ProbeResult` aos imports locais.
- No bloco de patches, substituir a linha `                 mock.patch("cli.asb.lifecycle.podman.ensure_rootless_netns"), \` por:

```python
                 mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=tmp / "runtime"), \
                 mock.patch("cli.asb.lifecycle.supervisor.start_workspace"), \
                 mock.patch("cli.asb.lifecycle.subprocess.run", return_value=mock.MagicMock(returncode=0)), \
                 mock.patch("cli.asb.readiness.probe_host", return_value=ProbeResult("host", "healthy", "ok", 0, "")), \
```

- Renomear `test_legacy_resume_with_broken_proxy_refuses_to_emit` → `test_resume_with_broken_proxy_refuses_to_emit`, `test_legacy_resume_with_broken_ssh_refuses_to_emit` → `test_resume_with_broken_ssh_refuses_to_emit`, `test_legacy_resume_emits_only_when_every_probe_is_healthy` → `test_resume_emits_only_when_every_probe_is_healthy`.
- Trocar a docstring da classe por: `"""A#2: \`resume\` so publica conexao depois do gate de prontidao; falha de infraestrutura nao destroi dados."""`.

7b. `TestManagedLifecycleCommands` — remover a linha de patch `mock.patch("cli.asb.lifecycle._runtime_of", ...)` de todos os testes restantes, e:
- `test_suspend_managed_disables_and_stops_target_and_verifies_stopped` → renomear para `test_suspend_disables_and_stops_target_and_verifies_stopped`.
- `test_resume_managed_enables_resets_starts_and_checks_probes` → renomear para `test_resume_enables_resets_starts_and_checks_probes`; remover o patch `mock.patch("cli.asb.podman.ensure_rootless_netns")`; acrescentar `mock.patch("cli.asb.lifecycle.ensure_runtime", return_value=Path("/tmp/runtime/rev1"))`.
- `test_down_managed_removes_units_before_cleaning_containers` → renomear para `test_down_removes_units_before_cleaning_containers`.
- Substituir `test_down_with_corrupted_manifest_still_cleans_up_best_effort` por:

```python
    def test_down_with_corrupted_manifest_still_cleans_up_best_effort(self):
        """`down` e a saida de emergencia: um runtime.json corrompido que faz
        `remove_workspace_units` levantar NUNCA aborta a limpeza local."""
        from unittest import mock
        from cli.asb import lifecycle
        import contextlib
        import io

        with mock.patch("cli.asb.lifecycle.supervisor.remove_workspace_units",
                        side_effect=ValueError("manifesto de runtime corrompido")) as mock_remove, \
             mock.patch("cli.asb.lifecycle._sweep_containers") as mock_sweep, \
             mock.patch("cli.asb.podman.exists", return_value=False), \
             mock.patch("cli.asb.lifecycle._origin_of", return_value=None):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = lifecycle.down("demo")
        self.assertEqual(rc, 0)
        mock_remove.assert_called_once()
        mock_sweep.assert_called_once_with("demo")
        self.assertIn("manifesto de runtime corrompido", stderr.getvalue())
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_lifecycle.py' -v`
Expected: `OK`.

Run: `grep -rn "_runtime_of" cli/ tests/ --include=*.py`
Expected: nenhuma linha.

Run: `python3 -m unittest discover -s tests/unit`
Expected: `OK`.

- [ ] **Step 9: Commit**

Pelo `commit-curator`, staging de `cli/asb/lifecycle.py`,
`tests/unit/test_lifecycle.py`. Título sugerido:
`🐛 unificar resume, suspend e down no runtime systemd: Emenda A`.

---

### Task 6: Keyring supervisionado pelo systemd

**Files:**
- Modify: `cli/asb/supervisor.py` (novas funções antes de `class _AdoptionLock:`, linha ~427; `install_workspace`; `__all__`)
- Modify: `cli/asb/keyring.py` (imports; `ensure_keyring_service`, linha ~229; novo `_restart_policy`)
- Modify: `cli/asb/lifecycle.py` (`prepare_workspace` e `resume`)
- Modify: `cli/asb/auth.py` (linha ~573)
- Modify: `tests/integration/test_startup_auth.py` (linhas ~219–248)
- Test: `tests/unit/test_supervisor.py`, `tests/unit/test_auth.py`, `tests/unit/test_lifecycle.py`, `tests/unit/test_login_flow.py`

**Interfaces:**
- Consumes: `runtime_check.py --role keyring --container` (Task 3); `lifecycle.ensure_runtime(root) -> Path` (Task 4).
- Produces:
  - `supervisor.keyring_container_name() -> str`
  - `supervisor.keyring_unit_name() -> str`
  - `supervisor.render_keyring_unit(c_name: str, runtime_dir: Path) -> str`
  - `supervisor.install_keyring_unit(c_name: str, runtime_dir: Path, target_dir: Path | None = None) -> Path`
  - `keyring.ensure_keyring_service(runtime_dir: Path, timeout: float = 180.0) -> str`
  - `install_workspace` passa `keyring_unit=keyring_unit_name()` às unidades de agente.

- [ ] **Step 1: Escrever os testes que falham — unidade do keyring**

Em `tests/unit/test_supervisor.py`, acrescentar:

```python
class TestKeyringUnit(unittest.TestCase):
    """Emenda A §5: o keyring e uma unidade systemd com sonda de prontidao."""

    def test_render_keyring_unit_runs_readiness_and_ignores_the_network_gate(self):
        runtime_dir = Path("/opt/asb/runtime/rev1")
        text = supervisor.render_keyring_unit("asb-keyring", runtime_dir)
        self.assertIn(
            "ExecStart=/opt/asb/runtime/rev1/launcher.sh start --attach --sig-proxy=false asb-keyring\n", text)
        self.assertIn(
            "ExecStartPost=/opt/asb/runtime/rev1/runtime_check.py --role keyring --container asb-keyring\n", text)
        self.assertIn("WantedBy=default.target\n", text)
        self.assertNotIn("asb-network", text)
        self.assertNotIn("Requires=", text)

    def test_install_keyring_unit_writes_the_unit_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp) / "units"
            with mock.patch("asb.supervisor.subprocess.run") as run:
                path = supervisor.install_keyring_unit(
                    "asb-keyring", Path("/opt/rt"), target_dir=unit_dir)
            self.assertEqual(path, unit_dir / "asb-keyring.service")
            self.assertIn("--role keyring", path.read_text(encoding="utf-8"))
            run.assert_called_once_with(["systemctl", "--user", "daemon-reload"], check=True)

    def test_keyring_names_honor_the_isolation_environment(self):
        with mock.patch.dict(os.environ, {"ASB_KEYRING_CONTAINER": "asb-test-k-keyring"}):
            self.assertEqual(supervisor.keyring_container_name(), "asb-test-k-keyring")
            self.assertEqual(supervisor.keyring_unit_name(), "asb-test-k-keyring.service")

    def test_install_workspace_points_the_agent_at_the_keyring_unit_in_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime" / "rev1"
            runtime_dir.mkdir(parents=True)
            launcher = runtime_dir / "launcher.sh"
            launcher.write_text("#!/bin/sh\n")
            state_dir = root / "state" / "ws"
            state_dir.mkdir(parents=True)
            (state_dir / "runtime.json").write_text(json.dumps({
                "schemaVersion": 1, "workspace": "ws",
                "containers": {"agent": {"name": "asb-ws-agent", "id": "a1"}},
            }))
            unit_dir = root / "units"
            with mock.patch.dict(os.environ, {"ASB_KEYRING_CONTAINER": "asb-test-k-keyring"}), \
                 mock.patch("asb.supervisor.subprocess.run"):
                supervisor.install_workspace(
                    "ws", target_dir=unit_dir, state_dir=state_dir, helper_path=launcher)
            agent_text = (unit_dir / "asb-ws-agent.service").read_text(encoding="utf-8")
            self.assertIn("asb-test-k-keyring.service", agent_text)
            self.assertNotIn(" asb-keyring.service", agent_text)
```

- [ ] **Step 2: Escrever os testes que falham — `ensure_keyring_service`**

Em `tests/unit/test_auth.py`, na classe `TestKeyringServiceLifecycle`:

2a. **Substituir** `test_ensure_keyring_service_creates_container_with_expected_contract` e `test_ensure_keyring_service_starts_existing_stopped_container` por:

```python
    RUNTIME_DIR = Path("/opt/asb/runtime/rev1")

    def _systemd_mocks(self, stack, tmp: str):
        installed = stack.enter_context(mock.patch(
            "asb.supervisor.install_keyring_unit",
            return_value=Path(tmp) / f"{lifecycle.KEYRING_CONTAINER}.service"))
        systemctl = stack.enter_context(mock.patch(
            "asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0)))
        return installed, systemctl

    def test_ensure_keyring_service_creates_a_stopped_container_supervised_by_systemd(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("secret-pass")
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass))
            stack.enter_context(mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists",
                                           side_effect=lambda kind, name: kind == "image"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            installed, systemctl = self._systemd_mocks(stack, tmp)

            name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
        mock_run.assert_called_once()
        args = list(mock_run.call_args[0])
        self.assertEqual(args[0], "create")
        self.assertNotIn("-d", args)
        self.assertEqual(args[args.index("--name") + 1], lifecycle.KEYRING_CONTAINER)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--restart") + 1], "no")
        self.assertEqual(args[args.index("--user") + 1], "1000")
        self.assertEqual(args[args.index("--userns") + 1], "keep-id:uid=1000,gid=1000")
        self.assertIn(f"{fake_pass}:/run/asb-keyring-pass:ro,Z", args)
        self.assertIn("asb-credentials:/run/asb-credentials:ro,z", args)
        self.assertIn("asb-keyring-data:/run/asb-keyring-data:z", args)
        self.assertIn("asb-keyring-runtime:/run/asb-keyring:z", args)
        self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", args)
        self.assertIn(f"asb.keyring.schema={lifecycle.KEYRING_SCHEMA}", args)
        self.assertEqual(args[args.index("--entrypoint") + 1], "/usr/local/bin/start-keyring.sh")
        self.assertEqual(args[-1], lifecycle.IMAGE)
        installed.assert_called_once_with(lifecycle.KEYRING_CONTAINER, self.RUNTIME_DIR)
        unit = f"{lifecycle.KEYRING_CONTAINER}.service"
        self.assertEqual(
            [c.args[0] for c in systemctl.call_args_list],
            [["systemctl", "--user", "enable", unit], ["systemctl", "--user", "start", unit]],
        )

    def test_existing_supervised_container_is_kept_and_started_by_systemd(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts())))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="no"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            installed, systemctl = self._systemd_mocks(stack, tmp)

            name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
        mock_run.assert_not_called()
        installed.assert_called_once_with(lifecycle.KEYRING_CONTAINER, self.RUNTIME_DIR)
        self.assertEqual(len(systemctl.call_args_list), 2)

    def test_legacy_unless_stopped_container_is_recreated_keeping_volumes(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("pass")
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass))
            stack.enter_context(mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts(fake_pass))))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="unless-stopped"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            self._systemd_mocks(stack, tmp)

            lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        calls = [c.args for c in mock_run.call_args_list]
        self.assertEqual(calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))
        self.assertEqual(calls[1][0], "create")
        # So o container sai: nenhum volume e removido.
        self.assertFalse(any("volume" in c for c in calls))

    def test_systemd_start_failure_is_an_infrastructure_error(self):
        import subprocess as _subprocess
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts())))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="no"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            stack.enter_context(mock.patch(
                "asb.supervisor.install_keyring_unit",
                return_value=Path(tmp) / f"{lifecycle.KEYRING_CONTAINER}.service"))
            stack.enter_context(mock.patch(
                "asb.keyring.subprocess.run",
                side_effect=[mock.MagicMock(returncode=0),
                             _subprocess.CalledProcessError(1, ["systemctl"])]))
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
        self.assertIn("systemctl --user status", str(ctx.exception))
```

2b. Nos testes restantes da classe:
- `test_ensure_keyring_service_auto_upgrades_schema_1_container` e `test_ensure_keyring_service_auto_upgrades_legacy_mounts_contract`: trocar `lifecycle.ensure_keyring_service()` por `lifecycle.ensure_keyring_service(self.RUNTIME_DIR)`; substituir o patch `mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True)` por dois patches: `mock.patch("asb.supervisor.install_keyring_unit", return_value=Path(tmp) / "asb-keyring.service")` e `mock.patch("asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0))`; no primeiro teste, trocar `self.assertEqual(create_call[0], "run")` por `self.assertEqual(create_call[0], "create")`.
- `test_ensure_keyring_service_rejects_incompatible_schema`, `test_ensure_keyring_service_never_replaces_unknown_schema_with_bad_mounts` e `test_ensure_keyring_service_never_replaces_container_when_inspect_fails`: trocar `lifecycle.ensure_keyring_service()` por `lifecycle.ensure_keyring_service(self.RUNTIME_DIR)`. As asserções não mudam.

- [ ] **Step 3: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_supervisor.py' -k TestKeyringUnit -v`
Expected: ERROR — `module 'asb.supervisor' has no attribute 'render_keyring_unit'`.

Run: `python3 -m unittest discover -s tests/unit -p 'test_auth.py' -k TestKeyringServiceLifecycle -v`
Expected: ERROR/FAIL — `ensure_keyring_service() takes from 0 to 1 positional arguments` ou `_restart_policy` inexistente.

- [ ] **Step 4: Implementar em `cli/asb/supervisor.py`**

Imediatamente antes de `class _AdoptionLock:`, adicionar:

```python
def keyring_container_name() -> str:
    """Container do keyring singleton; `ASB_KEYRING_CONTAINER` isola testes."""
    return os.environ.get("ASB_KEYRING_CONTAINER", "asb-keyring")


def keyring_unit_name() -> str:
    """Unidade do keyring, nomeada pelo container como `asb-{ws}-{role}.service`."""
    return f"{keyring_container_name()}.service"


def render_keyring_unit(c_name: str, runtime_dir: Path) -> str:
    """Renderiza a unidade Type=exec do keyring singleton (Emenda A §5).

    `ExecStartPost` so deixa a unidade ativa com o Secret Service respondendo,
    entao o `After=` do agente espera o D-Bus pronto, nao so o processo. O
    container roda com `--network none`: a unidade NAO depende da espera por
    rede.
    """
    _validate_safe_name(c_name, "keyring_container")
    launcher = escape_systemd_arg(runtime_dir / "launcher.sh")
    check = escape_systemd_arg(runtime_dir / "runtime_check.py")
    name_escaped = escape_systemd_arg(c_name)
    podman_escaped = escape_systemd_arg(shutil.which("podman") or "/usr/bin/podman")
    return (
        "[Unit]\n"
        "Description=Agent Sandbox Secret Service keyring singleton\n"
        "StartLimitIntervalSec=600s\n"
        "StartLimitBurst=3\n"
        "\n"
        "[Service]\n"
        "Type=exec\n"
        f"ExecStart={launcher} start --attach --sig-proxy=false {name_escaped}\n"
        f"ExecStartPost={check} --role keyring --container {name_escaped}\n"
        f"ExecStop={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        f"ExecStopPost={podman_escaped} stop --ignore --time=10 {name_escaped}\n"
        "Restart=always\n"
        "RestartSec=5s\n"
        "TimeoutStartSec=150s\n"
        "TimeoutStopSec=20s\n"
        "KillMode=process\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install_keyring_unit(
    c_name: str,
    runtime_dir: Path,
    target_dir: Path | None = None,
) -> Path:
    """Grava a unidade do keyring atomicamente e executa daemon-reload."""
    _, target_path = _resolve_paths("", target_dir, None)
    target_path.mkdir(parents=True, exist_ok=True)
    unit_file = target_path / f"{c_name}.service"
    _atomic_write_text(unit_file, render_keyring_unit(c_name, runtime_dir))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return unit_file
```

Em `install_workspace`, na construção de `ContainerUnit(...)`, acrescentar o argumento:

```python
            keyring_unit=keyring_unit_name(),
```

Em `__all__`, acrescentar `"keyring_container_name"`, `"keyring_unit_name"`, `"render_keyring_unit"` e `"install_keyring_unit"`.

- [ ] **Step 5: Implementar em `cli/asb/keyring.py`**

5a. Nos imports do topo, acrescentar `import subprocess` (depois de `import shutil`).

5b. Logo antes de `def ensure_keyring_service`, adicionar:

```python
def _restart_policy(container: str) -> str:
    """Politica de reinicio do Podman do container (vazio quando nao declarada)."""
    return podman.out(
        "inspect", container, "--format", "{{.HostConfig.RestartPolicy.Name}}").strip()
```

5c. Substituir a função `ensure_keyring_service` inteira por:

```python
def ensure_keyring_service(runtime_dir: Path, timeout: float = 180.0) -> str:
    """Garante o keyring singleton supervisionado pelo systemd de usuario (Emenda A §5).

    O container nasce com `--restart=no`; quem o inicia e reinicia e a unidade
    `<container>.service`, cuja sonda `runtime_check --role keyring` so deixa a
    unidade ativa com o Secret Service respondendo.

    Container de schema 1, com contrato de mounts legado ou ainda com politica
    de reinicio do Podman (o runtime legacy) e recriado. SO o container sai:
    volumes e passfile ficam intactos, entao nenhuma credencial e apagada.
    A existencia e consultada uma vez so; depois do `rm` o estado segue pela
    variavel `present`.
    """
    from . import supervisor
    from .lifecycle import IMAGE, ensure_credentials_volume

    container = os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    present = podman.exists("container", container)
    if present:
        schema, mounts = _inspect_keyring_container(container)
        if schema not in ("", "1", KEYRING_SCHEMA):
            raise podman.PodmanError(
                f"container '{container}' possui schema incompativel ({schema}). "
                f"Remova-o com 'podman rm -f {container}' e execute 'asb-agent login'."
            )
        needs_recreate = (
            schema in ("", "1")
            or bool(_keyring_mount_contract_issue(mounts))
            or _restart_policy(container) != "no"
        )
        if needs_recreate:
            podman.run("rm", "-f", container, check=False)
            present = False

    if not present:
        if not podman.exists("image", IMAGE):
            raise podman.PodmanError(
                f"imagem {IMAGE} ausente; execute 'asb-agent build'")
        pass_file = ensure_keyring_pass()
        cred_vol = ensure_credentials_volume()
        keyring_data_vol = ensure_keyring_data_volume()
        run_vol = ensure_keyring_runtime_volume()
        podman.run(
            "create", "--name", container,
            "--label", f"asb.keyring.schema={KEYRING_SCHEMA}",
            "--network", "none",
            "--restart", "no",
            "--user", "1000",
            "--userns", "keep-id:uid=1000,gid=1000",
            "-v", f"{pass_file}:/run/asb-keyring-pass:ro,Z",
            "-v", f"{cred_vol}:/run/asb-credentials:ro,z",
            "-v", f"{keyring_data_vol}:/run/asb-keyring-data:z",
            "-v", f"{run_vol}:/run/asb-keyring:z",
            "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={KEYRING_BUS}",
            "--entrypoint", "/usr/local/bin/start-keyring.sh",
            IMAGE,
        )

    unit_name = supervisor.install_keyring_unit(container, runtime_dir).name
    try:
        subprocess.run(["systemctl", "--user", "enable", unit_name],
                       check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "--user", "start", unit_name],
                       check=True, capture_output=True, text=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise podman.PodmanError(
            f"servico de keyring '{unit_name}' nao ficou pronto; veja "
            f"'systemctl --user status {unit_name}' e "
            f"'journalctl --user -u {unit_name}'"
        ) from exc
    return container
```

- [ ] **Step 6: Ajustar os três chamadores**

6a. `cli/asb/lifecycle.py`, em `prepare_workspace`, substituir:

```python
    runtime_dir = ensure_runtime(root)
    ensure_keyring_service()
```

por:

```python
    runtime_dir = ensure_runtime(root)
    ensure_keyring_service(runtime_dir)
```

6b. `cli/asb/lifecycle.py`, em `resume`, substituir `    ensure_keyring_service()` por `    ensure_keyring_service(ensure_runtime(root))`.

6c. `cli/asb/auth.py`, em `login`, substituir `    lifecycle.ensure_keyring_service()` por `    lifecycle.ensure_keyring_service(lifecycle.ensure_runtime(root))`.

- [ ] **Step 7: Ajustar testes dos chamadores**

7a. `tests/unit/test_lifecycle.py`, em `TestSingleRuntimeResume`, acrescentar:

```python
    def test_resume_hands_the_installed_runtime_to_the_keyring(self):
        rc, _, _, mock_keyring, _ = self._run_resume()
        self.assertEqual(rc, 0)
        (runtime_dir,), _ = mock_keyring.call_args
        self.assertEqual(runtime_dir.name, "rev1")
```

7b. `tests/unit/test_lifecycle.py`, no teste renomeado na Task 4 `test_up_ensures_keyring_service_before_creating_the_agent_and_mounts_runtime_without_pass`: trocar o `side_effect=lambda: events.append("ensure_keyring_service")` por `side_effect=lambda *a, **k: events.append("ensure_keyring_service")`.

7c. `tests/unit/test_login_flow.py`: em cada bloco que já tem `mock.patch.object(auth.lifecycle, "ensure_keyring_service", ...)` (linhas ~91 e ~442) e `mock.patch.object(lifecycle, "ensure_keyring_service")` (linha ~162), acrescentar na linha seguinte o patch correspondente, para que nenhum teste instale runtime real:

```python
                mock.patch.object(auth.lifecycle, "ensure_runtime", return_value=Path("/tmp/asb-test-runtime")), \
```

(usar `lifecycle` no lugar de `auth.lifecycle` no bloco da linha ~162). Se `Path` não estiver importado no arquivo, acrescentar `from pathlib import Path`.

7d. `tests/unit/test_broker.py`, linha ~221: acrescentar `mock.patch("asb.lifecycle.ensure_runtime", return_value=Path("/tmp/asb-test-runtime")), \` logo abaixo de `mock.patch("asb.lifecycle.ensure_keyring_service"), \`.

7e. `tests/integration/test_startup_auth.py`: trocar

```python
    def ensure_then_fault():
        real_ensure()
```

por

```python
    def ensure_then_fault(runtime_dir):
        real_ensure(runtime_dir)
```

e trocar

```python
        if args == ["setup-keyring"]:
            lifecycle.ensure_keyring_service()
            return 0
```

por

```python
        if args == ["setup-keyring"]:
            lifecycle.ensure_keyring_service(lifecycle.ensure_runtime(ROOT))
            return 0
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_supervisor.py' -v`
Expected: `OK`.

Run: `python3 -m unittest discover -s tests/unit -p 'test_auth.py' -v`
Expected: `OK`.

Run: `python3 -m unittest discover -s tests/unit`
Expected: `OK`.

Run: `grep -rn "ensure_keyring_service()" cli/ tests/ --include=*.py`
Expected: nenhuma linha. (O `tests/test-keyring-service.sh` ainda tem uma
chamada sem argumento dentro de `python3 -c`; a Task 11 a corrige.)

- [ ] **Step 9: Commit**

Pelo `commit-curator`, staging de `cli/asb/supervisor.py`, `cli/asb/keyring.py`,
`cli/asb/lifecycle.py`, `cli/asb/auth.py`, `tests/unit/test_supervisor.py`,
`tests/unit/test_auth.py`, `tests/unit/test_lifecycle.py`,
`tests/unit/test_login_flow.py`, `tests/unit/test_broker.py`,
`tests/integration/test_startup_auth.py`. Título sugerido:
`🔐 supervisionar o keyring pelo systemd preservando credenciais: Emenda A`.

---

### Task 7: CLI sem `--runtime`, `adopt-runtime` e `rollback-runtime`

**Files:**
- Modify: `cli/asb-agent` (parser do `up`, linhas ~40–47; parsers de adoção, linhas ~92–111; despacho, linhas ~129–202)
- Test: `tests/unit/test_cli_dispatch.py`

**Interfaces:**
- Consumes: `lifecycle.up(root, ws, repo)` (Task 4).
- Produces: `asb-agent up --workspace W --repo R`; subcomandos `adopt-runtime` e `rollback-runtime` inexistentes.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_cli_dispatch.py`, acrescentar ao fim (antes de `if __name__`, se houver):

```python
class TestSingleRuntimeCli(unittest.TestCase):
    """Emenda A: nao ha escolha de runtime nem adocao/rollback na CLI."""

    def _subcommands(self):
        parser = _load_cli_module().build_parser()
        action = next(a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction))
        return parser, action.choices

    def test_adoption_and_rollback_commands_are_gone(self):
        _, choices = self._subcommands()
        self.assertNotIn("adopt-runtime", choices)
        self.assertNotIn("rollback-runtime", choices)

    def test_up_rejects_a_runtime_option(self):
        parser, _ = self._subcommands()
        stderr = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(stderr):
            parser.parse_args(["up", "--workspace", "w", "--repo", "/tmp", "--runtime", "systemd"])
        self.assertIn("--runtime", stderr.getvalue())
```

Acrescentar `import contextlib` aos imports do topo do arquivo, se ausente.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -k TestSingleRuntimeCli -v`
Expected: FAIL — os dois subcomandos ainda existem e `--runtime` é aceito.

- [ ] **Step 3: Implementar**

3a. No parser do `up`, apagar o bloco:

```python
    up.add_argument(
        "--runtime",
        choices=["legacy", "systemd"],
        default="legacy",
        help="backend de supervisao (default: legacy)",
    )
```

3b. Apagar os blocos `adopt_parser = sub.add_parser(...)` e `rollback_parser = sub.add_parser(...)` com todos os seus `add_argument`.

3c. No despacho do `up`, substituir:

```python
            return lifecycle.up(
                ROOT,
                args.workspace,
                Path(args.repo).resolve(),
                runtime=args.runtime,
            )
```

por:

```python
            return lifecycle.up(
                ROOT,
                args.workspace,
                Path(args.repo).resolve(),
            )
```

3d. Apagar os ramos `if args.command == "adopt-runtime":` e `if args.command == "rollback-runtime":` inteiros.

3e. Conferir imports órfãos: rodar `grep -n "json\.\|supervisor\." cli/asb-agent`. Remover `import json` se `json.` não aparecer mais; remover `supervisor` do import se `supervisor.` não aparecer mais.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_cli_dispatch.py' -v`
Expected: `OK` (inclusive a paridade parser↔despacho já existente).

Run: `python3 cli/asb-agent --help`
Expected: a lista de subcomandos não contém `adopt-runtime` nem `rollback-runtime`.

- [ ] **Step 5: Commit**

Pelo `commit-curator`, staging de `cli/asb-agent`, `tests/unit/test_cli_dispatch.py`.
Título sugerido: `♻️ remover escolha de runtime e adocao da CLI: Emenda A`.

---

### Task 8: Remover a maquinaria de adoção, rollback, drop-in e `unshare`

**Files:**
- Modify: `cli/asb/supervisor.py`, `cli/asb/install.py`, `cli/asb/podman.py`, `cli/asb/keyring.py`, `cli/asb/lifecycle.py`
- Delete: `tests/integration/test_adoption.py`, `tests/unit/test_id_swap_protection.py`, `tests/unit/test_journal_schema.py`, `tests/unit/test_runtime_integrity.py`
- Rename: `tests/unit/test_systemd_status_and_rollback.py` → `tests/unit/test_supervisor_remove_units.py`
- Modify: `tests/unit/test_keyring_readiness.py`, `tests/unit/test_isolation_guard.py`, `tests/unit/test_install.py`, `tests/unit/test_podman.py`, `tests/unit/test_login_flow.py`, `tests/unit/test_broker.py`, `tests/unit/test_lifecycle.py`, `tests/integration/test_startup_auth.py`

**Interfaces:**
- Consumes: nada novo. Depois das Tasks 4–7 nenhum código de produção chama o que sai aqui.
- Produces: remoção sem mudança de comportamento observável.

- [ ] **Step 1: Confirmar que o que sai está órfão**

Run:

```bash
grep -rn "adopt_workspace\|rollback_workspace\|adopt_keyring\|rollback_keyring\|podman_restart\|ensure_rootless_netns\|restore_project_dropin\|_wait_for_keyring_readiness" cli/ --include=*.py cli/asb-agent | grep -v "^cli/asb/supervisor.py:\|^cli/asb/install.py:\|^cli/asb/podman.py:\|^cli/asb/keyring.py:"
```

Expected: só `cli/asb/lifecycle.py` com o import de `_wait_for_keyring_readiness` (removido no Step 5). Qualquer outra linha é chamador vivo: parar e reportar.

- [ ] **Step 2: `cli/asb/supervisor.py`**

2a. Apagar `class _AdoptionLock:` e todo o seu corpo.

2b. Apagar tudo de `def _systemctl(` (inclusive) até o fim do arquivo. Nenhuma das funções nesse trecho é usada fora do `supervisor.py`; as funções novas das Tasks 2 e 6 ficaram antes de `_AdoptionLock` e não são afetadas.

2c. Substituir:

```python
from . import install, podman
from .install import (
    get_dropin_path,
    install_runtime,
    remove_project_dropin,
    restore_project_dropin,
)
```

por:

```python
from .install import install_runtime
```

2d. Em `__all__`, apagar `"adopt_workspace"`, `"rollback_workspace"`, `"adopt_keyring"` e `"rollback_keyring"`.

2e. Para cada nome em `fcntl hashlib json re stat sys time podman install`, rodar `grep -n "\b<nome>\." cli/asb/supervisor.py`; remover o import dos que não aparecerem mais.

- [ ] **Step 3: `cli/asb/install.py`**

Apagar as funções `podman_restart`, `_default_dropin_body`, `_fchmod_regular_at` e `restore_project_dropin` inteiras. Rodar `grep -n "PODMAN_RESTART_UNIT" cli/ -r`; se só restar a definição, apagá-la. Manter `PROJECT_DROPIN_HEADER`, `get_dropin_path`, `_is_project_dropin`, `_read_regular_at`, `read_project_dropin`, `check_project_dropin` e `remove_project_dropin`.

- [ ] **Step 4: `cli/asb/podman.py`**

Apagar a função `ensure_rootless_netns`.

- [ ] **Step 5: `cli/asb/keyring.py` e `cli/asb/lifecycle.py`**

Apagar `_wait_for_keyring_readiness` de `keyring.py`. Em `lifecycle.py`, remover a linha `    _wait_for_keyring_readiness,` do bloco `from .keyring import (...)`. Rodar `grep -n "\btime\." cli/asb/keyring.py`; se vazio, remover `import time`.

- [ ] **Step 6: Apagar testes inteiros da maquinaria removida**

```bash
git rm tests/integration/test_adoption.py tests/unit/test_id_swap_protection.py \
       tests/unit/test_journal_schema.py tests/unit/test_runtime_integrity.py
git mv tests/unit/test_systemd_status_and_rollback.py tests/unit/test_supervisor_remove_units.py
```

- [ ] **Step 7: Enxugar os testes mistos**

7a. `tests/unit/test_supervisor_remove_units.py`: manter o cabeçalho (docstring, imports, `sys.path`, constantes e helpers do topo como `WS`, `clean_env`, `env_for`), a classe `_TmpCase` e a classe `TestRemoveWorkspaceUnits`. Apagar `FakeHost`, `TestUnitStatusTable`, `TestManagerSeam`, `TestWorkspaceRollbackMutations`, `TestAdoptionStart`, `TestKeyringRollbackMutations`, `TestAdoptionLock`, `TestHelpers` e `TestNetnsProducerInventory` (a Task 9 cobre o inventário no `doctor`). Depois, apagar helpers do topo que nenhum código restante do arquivo referencie (conferir cada um com `grep -n`). Atualizar a docstring do módulo para `"""Unit tests for supervisor.remove_workspace_units."""`.

7b. `tests/unit/test_keyring_readiness.py`: apagar `TestKeyringAdoptionReadiness` e `TestIdSwapDuringDropinRestoration`, e os helpers do topo usados só por elas. Manter `TestProbeContract`.

7c. `tests/unit/test_isolation_guard.py`: apagar a classe `TestPublicCli` (seus quatro testes exercitam `adopt-runtime`/`rollback-runtime` e as funções `adopt_*`/`rollback_*`) e qualquer helper, como `FixtureHost`, que só sirva a testes de adoção. Critério objetivo: ao fim, `grep -n "adopt\|rollback_keyring\|rollback_workspace" tests/unit/test_isolation_guard.py` não devolve nada e o arquivo roda verde.

7d. `tests/unit/test_install.py`: apagar a classe `TestPodmanRestart` e todo teste que referencie `restore_project_dropin`, `_default_dropin_body` ou `_fchmod_regular_at`. Onde um teste de `remove_project_dropin` usava `_default_dropin_body()` para criar o arquivo, trocar por `install.PROJECT_DROPIN_HEADER + "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n"`.

7e. `tests/unit/test_podman.py`: apagar `test_ensure_rootless_netns_success`, `test_ensure_rootless_netns_missing_true_raises` e `ensure_rootless_netns` do import.

7f. Apagar todo patch residual dos nomes removidos:
- `tests/unit/test_login_flow.py`: a linha `mock.patch.object(lifecycle.podman, "ensure_rootless_netns"), \` (~155).
- `tests/unit/test_broker.py`: a linha `mock.patch("asb.install.podman_restart"), \` (~227).
- `tests/integration/test_startup_auth.py`: a linha `mock_netns = stack.enter_context(mock.patch.object(lifecycle.podman, "ensure_rootless_netns"))` e toda linha que use `mock_netns`.
- `tests/unit/test_lifecycle.py`: qualquer patch restante de `ensure_rootless_netns` ou `podman_restart`.
- `tests/unit/test_auth.py`: o teste `test_ensure_keyring_service_waits_for_socket_and_secrets`, somente se ele chamar `_wait_for_keyring_readiness`; se testar `check_keyring_service`, manter.

- [ ] **Step 8: Verificar**

Run:

```bash
grep -rn "adopt_\|rollback_workspace\|rollback_keyring\|podman_restart\|ensure_rootless_netns\|restore_project_dropin\|_AdoptionLock\|_runtime_of\|_wait_for_keyring_readiness\|adopt-runtime\|rollback-runtime\|_resolve_versioned_runtime\|_validate_installed_runtime" cli/ tests/ recipes/ --include=*.py --include=*.sh cli/asb-agent
```

Expected: nenhuma linha.

Run: `python3 -m unittest discover -s tests/unit`
Expected: `OK`.

Run: `python3 -c "import sys; sys.path.insert(0,'cli'); import asb.supervisor, asb.install, asb.podman, asb.keyring, asb.lifecycle, asb.doctor, asb.auth"`
Expected: sem saída (import limpo).

- [ ] **Step 9: Commit**

Pelo `commit-curator`, staging de todos os arquivos alterados, apagados e
renomeados nesta task, por caminho explícito. Título sugerido:
`♻️ remover adocao, rollback, drop-in e unshare do runtime: Emenda A`.

---

### Task 9: `doctor` e orientação de `probe_host`

**Files:**
- Modify: `cli/asb/doctor.py` (imports; novas funções antes de `def diagnose`; item 9 de `diagnose`)
- Modify: `cli/asb/readiness.py` (`probe_host`, ramo `ENETUNREACH`/`EHOSTUNREACH`)
- Test: `tests/unit/test_doctor.py`, `tests/unit/test_readiness.py`

**Interfaces:**
- Consumes: `install.read_project_dropin()`, `install.get_dropin_path()`, `supervisor.network_unit_name()`, `podman.run(..., check=False, capture=True)`.
- Produces:
  - `doctor.check_project_dropin_absent() -> dict` (check `project_dropin_absent`, afeta a saúde da infraestrutura)
  - `doctor.check_network_gate() -> dict` (check `network_gate`, informativo)
  - `doctor.third_party_netns_producers() -> list[str]` (check `netns_producers_third_party`, informativo)

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_doctor.py`, acrescentar:

```python
class TestEmendaAChecks(unittest.TestCase):
    """Emenda A: o doctor aponta o drop-in legado, a espera de rede e produtores alheios."""

    PROJECT_DROPIN = (
        "# Managed by agent-sandbox: podman-restart netns initialization\n"
        "[Service]\nExecStartPre=/usr/bin/podman unshare --rootless-netns /usr/bin/true\n"
    )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_root = Path(self._tmp.name)
        self.dropin_dir = self.config_root / "systemd" / "user" / "podman-restart.service.d"
        env = mock.patch.dict(os.environ, {"ASB_CONFIG_ROOT": str(self.config_root)})
        env.start()
        self.addCleanup(env.stop)

    def test_absent_project_dropin_is_healthy(self):
        check = doc_mod.check_project_dropin_absent()
        self.assertEqual(check["name"], "project_dropin_absent")
        self.assertTrue(check["healthy"])
        self.assertEqual(check["remediation"], "")

    def test_present_project_dropin_is_an_infrastructure_failure(self):
        self.dropin_dir.mkdir(parents=True)
        (self.dropin_dir / "agent-sandbox.conf").write_text(self.PROJECT_DROPIN)
        check = doc_mod.check_project_dropin_absent()
        self.assertFalse(check["healthy"])
        self.assertIn("daemon-reload", check["remediation"])

    def test_network_gate_state_is_reported_without_failing_health(self):
        with mock.patch("asb.doctor.subprocess.run",
                        return_value=mock.Mock(stdout="activating\n")):
            check = doc_mod.check_network_gate()
        self.assertEqual(check["name"], "network_gate")
        self.assertTrue(check["healthy"])
        self.assertIn("activating", check["label"])
        self.assertIn("aguardando", check["remediation"])

    def test_third_party_producers_exclude_asb_workspaces_and_networkless_containers(self):
        self.dropin_dir.mkdir(parents=True)
        (self.dropin_dir / "agent-sandbox.conf").write_text(self.PROJECT_DROPIN)
        (self.dropin_dir / "other.conf").write_text("[Service]\nExecStartPre=/bin/true\n")
        ps = mock.Mock(returncode=0, stderr="", stdout=(
            "asb-demo-proxy|asb.workspace=demo|asb-demo\n"
            "foreign-app|app=x|podman\n"
            "networkless||\n"
        ))
        with mock.patch("asb.doctor.podman.run", return_value=ps) as run:
            producers = doc_mod.third_party_netns_producers()
        self.assertEqual(producers, ["dropin:other.conf", "container:foreign-app"])
        self.assertEqual(run.call_args.args[:4], ("ps", "-a", "--filter", "should-start-on-boot=true"))
```

No teste existente `test_doctor_all_healthy`:
- trocar `self.assertIn("podman-restart.service habilitado", output)` por `self.assertIn("drop-in legado do podman-restart ausente", output)`;
- acrescentar `mock.patch("asb.doctor.third_party_netns_producers", return_value=[])` ao `with` que já mocka `check_keyring_service`.

Se `os` ou `tempfile` não estiverem importados em `tests/unit/test_doctor.py`, acrescentá-los.

Em `tests/unit/test_readiness.py`, em `test_probe_host_no_route`, acrescentar ao fim:

```python
        self.assertNotIn("unshare", res.remediation)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `python3 -m unittest discover -s tests/unit -p 'test_doctor.py' -k TestEmendaAChecks -v`
Expected: ERROR — `module 'asb.doctor' has no attribute 'check_project_dropin_absent'`.

Run: `python3 -m unittest discover -s tests/unit -p 'test_readiness.py' -k test_probe_host_no_route -v`
Expected: FAIL — `'unshare' unexpectedly found`.

- [ ] **Step 3: Implementar em `cli/asb/doctor.py`**

3a. Nos imports: acrescentar `import os`; trocar `from . import podman` por `from . import install, podman`; acrescentar `from .supervisor import network_unit_name`.

3b. Imediatamente antes de `def diagnose`, adicionar:

```python
def check_project_dropin_absent() -> dict[str, Any]:
    """Emenda A: o drop-in do projeto criava o namespace rootless cedo em todo boot."""
    path = install.get_dropin_path()
    try:
        exists, ours, _, _ = install.read_project_dropin()
        error = ""
    except RuntimeError as exc:
        exists, ours, error = True, True, str(exc)
    healthy = not (exists and ours)
    return {
        "name": "project_dropin_absent",
        "healthy": healthy,
        "label": ("drop-in legado do podman-restart ausente" if healthy
                  else f"drop-in legado do podman-restart presente ({path})"),
        "remediation": "" if healthy else (
            error or f"rm {shlex.quote(str(path))} && systemctl --user daemon-reload"),
    }


def check_network_gate() -> dict[str, Any]:
    """Estado da espera unica por rede (informativo: inativa antes do 1o workspace e normal)."""
    unit = network_unit_name()
    state = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True, text=True).stdout.strip() or "desconhecido"
    return {
        "name": "network_gate",
        "healthy": True,
        "label": f"espera por rede {unit}: {state}",
        "remediation": "aguardando conectividade real do host" if state == "activating" else "",
    }


def third_party_netns_producers() -> list[str]:
    """Produtores do namespace rootless no boot que NAO sao do ASB.

    Duas classes, as que falharam no piloto: drop-ins de `podman-restart`
    alheios (o do projeto e checado por `check_project_dropin_absent`) e
    containers alheios, em rede, que o `podman-restart` sobe no boot.
    """
    producers: list[str] = []
    dropin = install.get_dropin_path()
    try:
        entries = sorted(os.listdir(dropin.parent))
    except FileNotFoundError:
        entries = []
    except OSError as exc:
        producers.append(f"desconhecido: {dropin.parent} ilegivel ({exc})")
        entries = []
    for entry in entries:
        if entry == dropin.name:
            try:
                _, ours, _, _ = install.read_project_dropin()
            except RuntimeError:
                ours = True
            if ours:
                continue
        producers.append(f"dropin:{entry}")

    res = podman.run("ps", "-a", "--filter", "should-start-on-boot=true",
                     "--format", "{{.Names}}|{{.Labels}}|{{.Networks}}",
                     check=False, capture=True)
    if res.returncode != 0:
        producers.append(f"desconhecido: podman ps falhou ({(res.stderr or '').strip() or res.returncode})")
        return producers
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        name, _, rest = line.partition("|")
        labels, _, networks = rest.partition("|")
        if "asb.workspace=" in labels or networks.strip() in ("", "none"):
            continue
        producers.append(f"container:{name}")
    return producers
```

3c. Em `diagnose`, substituir o bloco inteiro:

```python
    # 9. podman-restart.service
    restart_res = subprocess.run(
        ["systemctl", "--user", "is-enabled", "podman-restart.service"],
        capture_output=True, text=True).stdout.strip()
    restart_ok = (restart_res == "enabled")
    checks.append({
        "name": "podman_restart_service",
        "healthy": restart_ok,
        "label": "podman-restart.service habilitado (restauracao no boot)",
        "remediation": "" if restart_ok else "systemctl --user enable podman-restart.service",
    })
    infra_healthy &= restart_ok
```

por:

```python
    # 9. Emenda A: drop-in legado ausente, espera por rede, produtores alheios
    dropin_check = check_project_dropin_absent()
    checks.append(dropin_check)
    infra_healthy &= dropin_check["healthy"]
    checks.append(check_network_gate())
    producers = third_party_netns_producers()
    checks.append({
        "name": "netns_producers_third_party",
        "healthy": True,
        "label": ("nenhum produtor alheio do namespace rootless no boot" if not producers
                  else "produtores alheios do namespace rootless: " + ", ".join(producers)),
        "remediation": "" if not producers
                       else "podem inicializar o namespace antes da rede; revise-os",
    })
```

- [ ] **Step 4: Implementar em `cli/asb/readiness.py`**

Em `probe_host`, substituir:

```python
            return ProbeResult("host", "unreachable", "no_route", elapsed, "podman unshare --rootless-netns true")
```

por:

```python
            return ProbeResult("host", "unreachable", "no_route", elapsed, "sem rota ate o destino; verifique a conexao de rede do host")
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python3 -m unittest discover -s tests/unit -p 'test_doctor.py' -v`
Expected: `OK`.

Run: `python3 -m unittest discover -s tests/unit -p 'test_readiness.py' -v`
Expected: `OK`.

Run: `grep -rn "unshare" cli/`
Expected: nenhuma linha.

- [ ] **Step 6: Commit**

Pelo `commit-curator`, staging de `cli/asb/doctor.py`, `cli/asb/readiness.py`,
`tests/unit/test_doctor.py`, `tests/unit/test_readiness.py`. Título sugerido:
`✨ diagnosticar drop-in legado e espera de rede no doctor: Emenda A`.

---

### Task 10: Teste de integração da espera com systemd real

**Files:**
- Create: `tests/integration/test_network_gate.py`

**Interfaces:**
- Consumes: `supervisor.render_network_unit(gate_path, target)` (Task 2); `network_gate.main` (Task 1); `SandboxFixture(label, auto_setup=False)` com `_prefix`, `_unit_dir`, `state_root`, `register_unit`.
- Produces: prova com systemd real de que uma unidade com `Requires=`/`After=` na espera não parte enquanto a sonda falha e parte sozinha quando a sonda passa (spec §7.1).

- [ ] **Step 1: Escrever o teste**

Criar `tests/integration/test_network_gate.py`:

```python
"""Integracao real: a espera por rede segura unidades dependentes (Emenda A §7.1).

Sem Podman. Duas unidades de usuario isoladas pela SandboxFixture: a espera,
sondando uma porta TCP local ainda fechada, e uma dependente com `Requires=` e
`After=` nela. A dependente nao pode partir enquanto a porta esta fechada, e
deve partir sozinha quando um listener aparece.
"""
from __future__ import annotations

import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
sys.path.insert(0, str(ROOT))
from asb import supervisor  # noqa: E402
from tests.integration.sandbox_fixture import SandboxFixture  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _is_active(unit: str) -> str:
    return subprocess.run(["systemctl", "--user", "is-active", unit],
                          capture_output=True, text=True).stdout.strip()


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return predicate()


def _user_manager_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(["systemctl", "--user", "show-environment"],
                          capture_output=True).returncode == 0


@unittest.skipUnless(_user_manager_available(), "requer systemd de usuario")
class TestNetworkGateHoldsDependents(unittest.TestCase):
    def test_dependent_waits_while_probe_fails_and_starts_when_network_appears(self):
        port = _free_port()
        with SandboxFixture("netgate", auto_setup=False) as fx:
            gate_unit = fx.register_unit(f"{fx._prefix}-network.service")
            dep_unit = fx.register_unit(f"{fx._prefix}-dep.service")
            fx.state_root.mkdir(parents=True, exist_ok=True)

            wrapper = fx.state_root / "network_gate_wrapper.py"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT / 'cli')!r})\n"
                "from asb.network_gate import main\n"
                "sys.exit(main())\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)

            (fx._unit_dir / gate_unit).write_text(
                supervisor.render_network_unit(wrapper, target=f"127.0.0.1:{port}"),
                encoding="utf-8",
            )
            (fx._unit_dir / dep_unit).write_text(
                "[Unit]\n"
                f"Requires={gate_unit}\n"
                f"After={gate_unit}\n"
                "\n"
                "[Service]\n"
                "Type=exec\n"
                "ExecStart=/usr/bin/sleep 300\n",
                encoding="utf-8",
            )
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "start", "--no-block", dep_unit], check=True)

            # Porta fechada: a espera fica ativando e a dependente nao parte.
            self.assertTrue(_wait_for(lambda: _is_active(gate_unit) == "activating", 15.0),
                            _is_active(gate_unit))
            time.sleep(6.0)
            self.assertEqual(_is_active(gate_unit), "activating")
            self.assertNotEqual(_is_active(dep_unit), "active")

            server = socketserver.TCPServer(("127.0.0.1", port), socketserver.BaseRequestHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertTrue(_wait_for(lambda: _is_active(dep_unit) == "active", 30.0),
                                f"gate={_is_active(gate_unit)} dep={_is_active(dep_unit)}")
                self.assertEqual(_is_active(gate_unit), "active")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar**

Run: `python3 -m unittest discover -s tests/integration -p 'test_network_gate.py' -v`
Expected: `OK` (1 teste, ~15–40 s). A fixture remove as duas unidades no teardown e prova a ausência delas.

Critério de validade do teste: se o `network_gate` sair 0 com a sonda falhando, a asserção `assertEqual(_is_active(gate_unit), "activating")` precisa falhar. Confirmar uma vez: inserir `return 0` como primeira linha do corpo de `wait_for_network`, rodar o teste e vê-lo falhar; depois reverter com `git checkout cli/asb/network_gate.py` e rodar de novo, verde.

- [ ] **Step 3: Commit**

Pelo `commit-curator`, staging de `tests/integration/test_network_gate.py`.
Título sugerido: `✅ provar com systemd real que a espera segura dependentes: Emenda A`.

---

### Task 11: Testes em shell no runtime único

**Files:**
- Modify: `tests/test-auth.sh` (bloco de `export`, linha ~36; `cleanup`)
- Modify: `tests/test-keyring-service.sh` (chamada da linha ~296–299; remoção da linha ~325; `cleanup`, linha ~58)

**Interfaces:**
- Consumes: `lifecycle.ensure_runtime(root)` e `ensure_keyring_service(runtime_dir)` (Task 6); `ASB_NETWORK_UNIT` (Task 2).
- Produces: os dois scripts que isolam o keyring deixam de gravar unidades com nome de produção e removem as unidades de teste que criam.

**Contexto.** Depois da Emenda A, `up`, `resume`, `login` e
`ensure_keyring_service` instalam unidades systemd reais. Dois scripts isolam o
keyring (`test-auth.sh`, `test-keyring-service.sh`) e hoje não limpariam as
unidades de teste, que ficariam habilitadas para o boot. Os outros onze scripts
que chamam `up`/`resume`/`login` — `test-agents-behind-proxy.sh`,
`test-doctor.sh`, `test-lifecycle.sh`, `test-nested.sh`, `test-network.sh`,
`test-provision.sh`, `test-recipe.sh`, `test-reload-allowlist.sh`,
`test-services.sh`, `test-toolcache.sh`, `test-transaction.sh` — já usam o
keyring de produção `asb-keyring` sem isolamento. Com o runtime único eles
instalam `asb-keyring.service` e `asb-network.service` de produção, que é o
estado final desejado, e **recriam o container `asb-keyring` se ele ainda for
legacy**. Não mudam aqui; só rodam depois da troca (Task 13, Step 6).

- [ ] **Step 1: `tests/test-auth.sh`**

Logo abaixo de `export ASB_KEYRING_PASS_FILE="$TEST_PASS_FILE"`, adicionar:

```bash
# Emenda A: `up` instala unidades systemd reais. Nome de teste para a espera
# por rede; o keyring ja e isolado por ASB_KEYRING_CONTAINER.
export ASB_NETWORK_UNIT="asb-test-network-${TEST_ID}.service"
UNIT_DIR="${ASB_SYSTEMD_UNIT_DIR:-$HOME/.config/systemd/user}"
```

Em `cleanup()`, logo abaixo das duas linhas `"$ROOT/cli/asb-agent" down ...`, adicionar:

```bash
  for unit in "${TEST_KEYRING_CONTAINER}.service" "$ASB_NETWORK_UNIT"; do
    systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$unit"
  done
  systemctl --user daemon-reload >/dev/null 2>&1 || true
```

- [ ] **Step 2: `tests/test-keyring-service.sh`**

2a. Substituir:

```bash
UPG_OUT=$(ASB_KEYRING_CONTAINER="$UPGRADE_SVC" \
          ASB_KEYRING_DATA_VOLUME="$UPGRADE_DATA_VOL" \
          ASB_KEYRING_RUNTIME_VOLUME="$UPGRADE_RUN_VOL" \
          python3 -c "from cli.asb.lifecycle import ensure_keyring_service; print(ensure_keyring_service())")
```

por:

```bash
UPG_OUT=$(ASB_KEYRING_CONTAINER="$UPGRADE_SVC" \
          ASB_KEYRING_DATA_VOLUME="$UPGRADE_DATA_VOL" \
          ASB_KEYRING_RUNTIME_VOLUME="$UPGRADE_RUN_VOL" \
          ASB_ROOT="$ROOT" \
          python3 -c "import os; from pathlib import Path; from cli.asb.lifecycle import ensure_keyring_service, ensure_runtime; print(ensure_keyring_service(ensure_runtime(Path(os.environ['ASB_ROOT']))))")
```

2b. Logo acima de `export ASB_CREDENTIALS_VOLUME="$TEST_CRED_VOL"`, adicionar:

```bash
UNIT_DIR="${ASB_SYSTEMD_UNIT_DIR:-$HOME/.config/systemd/user}"
drop_test_unit() {
  systemctl --user disable --now "$1.service" >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/$1.service"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}
```

2c. A unidade do container de upgrade tem `Restart=always`: ela precisa sair
**antes** do container, senão o systemd tenta subir um container removido.
Substituir a linha (~325):

```bash
podman rm -f "$UPGRADE_SVC" >/dev/null 2>&1 || true
```

por:

```bash
drop_test_unit "$UPGRADE_SVC"
podman rm -f "$UPGRADE_SVC" >/dev/null 2>&1 || true
```

2d. Em `cleanup()`, como primeira linha do corpo, adicionar:

```bash
  drop_test_unit "$UPGRADE_SVC"
```

- [ ] **Step 3: Rodar e confirmar**

```bash
bash tests/test-auth.sh
bash tests/test-keyring-service.sh
systemctl --user list-unit-files 'asb-test-*' --no-legend
ls "$HOME/.config/systemd/user" | grep -E '^asb-network\.service$|^asb-test-' || echo "sem residuo"
```

Expected: os dois scripts com `falhou: 0`; nenhuma unidade `asb-test-*`
residual; nenhuma `asb-network.service` criada por estes dois scripts.

Run: `grep -rn "ensure_keyring_service()" cli/ tests/`
Expected: nenhuma linha (agora incluindo scripts em shell).

- [ ] **Step 4: Commit**

Pelo `commit-curator`, staging de `tests/test-auth.sh`,
`tests/test-keyring-service.sh`. Título sugerido:
`✅ isolar e limpar unidades systemd nos testes em shell: Emenda A`.

---

### Task 12: Verificação completa antes da máquina real

**Files:** nenhum arquivo novo.

- [ ] **Step 1: Suítes automatizadas**

```bash
python3 -m unittest discover -s tests/unit
python3 -m unittest discover -s tests/integration
bash tests/test-auth.sh
bash tests/test-keyring-service.sh
```

Expected: tudo `OK` / `falhou: 0`. Registrar as contagens reais (a suíte unitária encolhe por causa dos testes removidos na Task 8; anotar o número antes e depois).

**Não rodar aqui** os onze scripts em shell que usam o keyring de produção
(lista na Task 11): com o runtime único eles recriam o container `asb-keyring`
de produção, e isso é a troca da Task 13, que exige janela do operador. Eles
rodam no Step 7 da Task 13.

- [ ] **Step 2: Imagem atualizada**

```bash
podman image inspect agent-sandbox:latest --format '{{.Created}}'
podman run --rm --entrypoint cat agent-sandbox:latest /usr/local/bin/entrypoint.sh | diff - image/entrypoint.sh && echo IDENTICO
```

Expected: `IDENTICO`. Se divergir, rodar `cli/asb-agent build` e repetir o Step 1 — a imagem desatualizada já invalidou evidência nesta branch uma vez.

- [ ] **Step 3: Invariantes por busca**

```bash
grep -rn "unless-stopped" cli/
grep -rn "unshare" cli/
git diff --check main...HEAD
```

Expected: as duas primeiras sem linhas; a terceira sem saída.

- [ ] **Step 4: Revisão**

Despachar `regression-sentinel` e `test-shape-auditor` sobre `git diff main...HEAD -- cli/ tests/`. Resolver achados antes da Task 13.

---

### Task 13: Troca na máquina real (janela do operador)

**Files:** nenhum arquivo de código. Registrar em `docs/validation/startup-auth-pilot.md` (nova seção `6.8`).

Pré-requisito: autorização explícita do operador para a janela. Nada aqui é
automático.

- [ ] **Step 1: Registrar o estado anterior (só leitura)**

```bash
MP=$(podman volume inspect asb-credentials --format '{{.Mountpoint}}')
sha256sum "$MP/claude/.credentials.json" "$MP/codex/auth.json" | cut -c1-16
podman inspect asb-keyring --format '{{.HostConfig.RestartPolicy.Name}} {{.Id}}'
ls ~/.config/systemd/user/podman-restart.service.d/ 2>/dev/null
cd ~/asb-agent/BlackICE/t2-pilot-blackice/BlackICE && git rev-parse --short HEAD && git status --short && sha256sum README.md T2-PILOT-UNTRACKED.txt | cut -c1-16
```

Guardar a saída em `~/.local/state/agent-sandbox/t2-evidence/pre-troca.txt`.

- [ ] **Step 2: Derrubar os workspaces do piloto** (o trabalho fica no clone)

```bash
cli/asb-agent down --workspace t2-pilot-blackice
cli/asb-agent down --workspace t2-pilot-scratch
```

- [ ] **Step 3: Recriar o primeiro workspace**

```bash
cli/asb-agent up --workspace t2-pilot-blackice --repo /home/v/Data/Projects/BlackICE
```

Expected: stderr contém `drop-in legado do podman-restart removido` na primeira execução; JSON de conexão no stdout.

- [ ] **Step 4: Verificar a troca**

```bash
ls ~/.config/systemd/user/podman-restart.service.d/agent-sandbox.conf 2>&1   # esperado: No such file
podman inspect asb-keyring --format '{{.HostConfig.RestartPolicy.Name}}'     # esperado: no
systemctl --user is-active asb-keyring.service asb-network.service           # esperado: active active
systemctl --user is-active asb-t2-pilot-blackice-proxy.service asb-t2-pilot-blackice-agent.service
MP=$(podman volume inspect asb-credentials --format '{{.Mountpoint}}')
sha256sum "$MP/claude/.credentials.json" "$MP/codex/auth.json" | cut -c1-16  # esperado: igual ao Step 1
cli/asb-agent auth status --workspace t2-pilot-blackice --json               # claude e codex authenticated
podman exec -u 1000 asb-t2-pilot-blackice-agent sh -c 'curl -sS -o /dev/null -m 20 -w "%{http_code}\n" https://github.com'   # 200
podman exec -u 1000 asb-t2-pilot-blackice-agent sh -c 'curl -sS -o /dev/null -m 15 -w "%{http_code}\n" https://example.com'  # falha 403
cd ~/asb-agent/BlackICE/t2-pilot-blackice/BlackICE && git status --short && sha256sum README.md T2-PILOT-UNTRACKED.txt | cut -c1-16  # igual ao Step 1
cli/asb-agent doctor
```

Expected: todos os valores indicados. Credenciais com o mesmo hash; trabalho
não commitado idêntico. Se qualquer credencial mudar ou faltar, parar e
registrar — a Emenda A exige preservá-las.

- [ ] **Step 5: Segundo workspace simultâneo**

```bash
cli/asb-agent up --workspace t2-pilot-scratch --repo /home/v/Data/Projects/t2-pilot-scratch
systemctl --user is-active asb-t2-pilot-scratch-proxy.service asb-t2-pilot-scratch-agent.service
```

Expected: `active active`, com os dois workspaces no ar.

- [ ] **Step 6: Suítes em shell que usam o keyring de produção**

Só agora, com a troca feita:

```bash
for t in agents-behind-proxy doctor lifecycle nested network provision recipe \
         reload-allowlist services toolcache transaction; do
  echo "== $t =="; bash "tests/test-$t.sh" 2>&1 | tail -3
done
systemctl --user list-unit-files 'asb-test-*' --no-legend
```

Expected: cada script com `falhou: 0`; a última linha sem nenhuma unidade
`asb-test-*` residual. Se sobrar unidade, removê-la com
`systemctl --user disable --now <unidade>` e `rm` do arquivo, e registrar qual
script deixou o resíduo.

- [ ] **Step 7: Registrar e commitar**

Escrever a seção `6.8. Troca para o runtime único` no relatório do piloto com
os valores medidos, e commitar pelo `commit-curator`. Título sugerido:
`📝 registrar troca para o runtime unico no piloto: Emenda A`.

---

### Task 14: Boots reais (janelas do operador, spec §7.2)

**Files:** `docs/validation/startup-auth-pilot.md` (seções `6.9`–`6.11`).

Cada boot exige autorização do operador. Antes de cada um, salvar evidência
pré-boot; depois, **só leitura**, sem comando corretivo.

- [ ] **Step 1: Coleta pré-boot (para cada boot)**

```bash
E=~/.local/state/agent-sandbox/t2-evidence
for WS in t2-pilot-blackice t2-pilot-scratch; do
  python3 tests/integration/collect_boot_evidence.py "$WS" > "$E/pre-bootA<N>-$WS.json"
done
cat /proc/sys/kernel/random/boot_id > "$E/pre-bootA<N>-boot_id.txt"
```

(`<N>` = 1, 2, 3.)

- [ ] **Step 2: Os três boots**

| Boot | Preparação | Ação do operador |
| :--- | :--- | :--- |
| A1 normal | os dois workspaces ativos | reiniciar; autologin; não rodar nada |
| A2 rede atrasada 60 s | os dois ativos | desconectar o cabo `eno1`, reiniciar, reconectar ~60 s após o login |
| A3 ativo + suspenso | `cli/asb-agent suspend --workspace t2-pilot-scratch` | reiniciar; autologin; não rodar nada |

- [ ] **Step 3: Coleta pós-boot (só leitura, para cada boot)**

```bash
cat /proc/sys/kernel/random/boot_id                                   # deve diferir do pré-boot
systemctl --user show -p ActiveEnterTimestamp --value asb-network.service
ps -eo lstart,args | grep '[p]asta --config'                          # hora de nascimento do namespace
systemctl --user is-active asb-network.service asb-keyring.service \
  asb-t2-pilot-blackice-proxy.service asb-t2-pilot-blackice-agent.service \
  asb-t2-pilot-scratch-proxy.service asb-t2-pilot-scratch-agent.service
for WS in t2-pilot-blackice t2-pilot-scratch; do
  podman exec -u 1000 asb-$WS-agent sh -c 'curl -sS -o /dev/null -m 20 -w "%{http_code}\n" https://github.com' 2>&1
done
podman exec -u 1000 asb-t2-pilot-blackice-agent sh -c 'curl -sS -o /dev/null -m 15 -w "%{http_code}\n" https://example.com' 2>&1
journalctl --user -b -u asb-network.service --no-pager
E=~/.local/state/agent-sandbox/t2-evidence
for WS in t2-pilot-blackice t2-pilot-scratch; do
  python3 tests/integration/collect_boot_evidence.py "$WS" > "$E/post-bootA<N>-$WS.json"
done
```

No boot A3, o scratch deve estar `inactive`/parado, e o egresso só é medido no blackice.

- [ ] **Step 4: Avaliar cada boot**

Aprovado somente se, sem nenhum comando corretivo:
1. `boot_id` mudou;
2. **o `pasta` nasceu depois de `ActiveEnterTimestamp` de `asb-network.service`** — a medida decisiva;
3. egresso pelo caminho real: `github.com` 200 e `example.com` bloqueado, em cada workspace ativo;
4. porta, trabalho não commitado e credenciais preservados;
5. no A3, o suspenso permaneceu parado;
6. no A2, a espera registrou no journal a mudança de estado e concluiu sozinha depois da reconexão.

- [ ] **Step 5: Regra de parada (spec §7.3)**

Se um boot perder o egresso **com o `pasta` nascido depois da espera**, a
premissa da Emenda A está refutada: parar, registrar no relatório e voltar ao
desenho, sem migrar mais nada. Se o `pasta` nascer **antes** da espera, há um
produtor ASB ou alheio não coberto: rodar `cli/asb-agent doctor`, registrar o
produtor e parar.

- [ ] **Step 6: Registrar e commitar**

Uma seção por boot no relatório, com linha do tempo, medidas e veredito; commit
pelo `commit-curator`. Título sugerido:
`📝 registrar boots reais do runtime unico: Emenda A`.

---

### Task 15: Fechamento

**Files:** `docs/validation/startup-auth-pilot.md`; `graphify-out/**`.

- [ ] **Step 1: Atualizar critérios e status do relatório**

Atualizar a tabela de critérios da §7 do relatório com os resultados das
Tasks 13–14, e o status do cabeçalho. O critério 7 (rollback) deixa de existir,
conforme a Emenda A.

- [ ] **Step 2: Verificação final**

```bash
python3 -m unittest discover -s tests/unit
python3 -m unittest discover -s tests/integration
git diff --check main...HEAD
git status --short
```

Expected: verde, sem saída do `diff --check`, árvore limpa após o commit do relatório.

- [ ] **Step 3: Graphify (AGENTS.md §7.2–§7.4)**

```bash
rm -f "$(git rev-parse --git-common-dir)/graphify-pause"
graphify update .
```

Commit separado pelo `commit-curator`, contendo estritamente `graphify-out/**`,
com o título exato `🕸️ sync knowledge graph` e sem corpo.

- [ ] **Step 4: Fora de escopo, registrado para T3**

Anotar no relatório, sem implementar: a correção da orientação
`podman unshare --rootless-netns true` em
`docs/domains/sandbox/failure-modes.md` e as menções a `adopt-runtime`,
`rollback-runtime` e `--runtime` na documentação do domain pack pertencem à T3
do plano coordenador.
