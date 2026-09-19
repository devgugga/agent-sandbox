"""cli/asb/interfaces/sessions.py — sessoes persistentes de agente pelo CLI.

`asb-agent project add` registra um projeto e o seu checkout primario;
`asb-agent session list|start|attach|stop|resume` opera as sessoes. A TUI
(Tarefa 10) reusa a mesma composicao (`session_services`) e o mesmo argv de
anexacao.

Regras de cada comando:

- `session list` le SO o `SessionStore`: nao reconcilia nem toca workspace
  algum, entao funciona com tudo parado;
- `session start` e o UNICO comando que pode subir um workspace, via
  `SandboxRuntime.ensure(binding)`;
- `attach`, `stop` e `resume` resolvem a conexao viva com
  `resolve_connection`: um workspace parado chega como `PodmanError`;
- nada aqui imprime saida de provedor, prompt ou transcricao.
"""
from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

from ..agents.antigravity import AntigravityDriver
from ..agents.base import AgentDriver
from ..agents.claude import ClaudeDriver
from ..agents.codex import CodexDriver
from ..checkouts.model import CheckoutId
from ..projects.registry import CheckoutBinding, ProjectRegistry
from ..runtime.connection import ConnectionInfo, resolve_connection
from ..runtime.sandbox import SandboxRuntime, session_volume_mountpoint
from ..sessions.manager import SessionManager, StartSession
from ..sessions.model import AgentKind, AgentSession, SessionId, SessionState
from ..sessions.store import SessionStore
from ..sessions.terminal import TmuxTerminal

_SCHEMA_VERSION = 1

# Estados em que `attach` recusa sem lancar nada: final ou incerto.
_NOT_ATTACHABLE = frozenset({SessionState.RECOVERY_REQUIRED,
                             SessionState.COMPLETED, SessionState.FAILED})
_LIVE = frozenset({SessionState.RUNNING, SessionState.DETACHED})


@dataclass(frozen=True)
class SessionServices:
    """Tudo que um comando de sessao usa. `manager_for` constroi o gerente
    de UM workspace a partir da sua conexao viva."""

    registry: ProjectRegistry
    store: SessionStore
    runtime: SandboxRuntime
    resolve: Callable[[str], ConnectionInfo]
    manager_for: Callable[[ConnectionInfo], SessionManager]


def default_drivers(workspace: str) -> dict[AgentKind, AgentDriver]:
    """Drivers que leem a evidencia de sessao no volume de sessao do
    workspace (Tarefa 8). O Claude recebe o id no lancamento e nao varre
    nada; Antigravity nao tem local de estado comprovado."""
    mount = session_volume_mountpoint(workspace)
    return {
        AgentKind.CODEX: CodexDriver(mount / "codex-sessions"),
        AgentKind.CLAUDE: ClaudeDriver(),
        AgentKind.ANTIGRAVITY: AntigravityDriver(None),
    }


def remote_run(connection: ConnectionInfo, argv: Sequence[str], *,
               timeout: float,
               run: Callable[..., subprocess.CompletedProcess] = subprocess.run
               ) -> str:
    """Roda `argv` DENTRO do sandbox por SSH nao interativo e devolve o
    stdout, com qualquer exit status. So levanta o que o `probe` dos
    drivers absorve (`FileNotFoundError`, `TimeoutExpired`, `OSError`):
    `check=False`, nunca `CalledProcessError`."""
    result = run(connection.ssh_argv(tuple(argv), interactive=False),
                 shell=False, capture_output=True, text=True,
                 timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    return result.stdout or ""


def session_services(
        root: Path, *, state_dir: Path | None = None,
        drivers: Callable[[str], Mapping[AgentKind, AgentDriver]] = default_drivers,
        sleep: Callable[[float], object] = time.sleep) -> SessionServices:
    """Composicao de producao. Construir nao toca disco, Podman nem SSH:
    so `manager_for` consulta o volume de sessao, e so quando chamado."""
    if state_dir is None:
        state_dir = Path.home() / ".local" / "state" / "agent-sandbox"
    registry = ProjectRegistry(state_dir / "projects.json")
    store = SessionStore(state_dir / "sessions.json")

    def manager_for(connection: ConnectionInfo) -> SessionManager:
        return SessionManager(
            store=store,
            terminal=TmuxTerminal(connection),
            drivers=drivers(connection.workspace),
            remote_run=functools.partial(remote_run, connection),
            sleep=sleep,
        )

    return SessionServices(
        registry=registry, store=store,
        runtime=SandboxRuntime(root=root, registry=registry),
        resolve=resolve_connection, manager_for=manager_for)


# -- project add ----------------------------------------------------------------


def project_add(repo: str, integration_branch: str | None,
                worktree_root: str | None, *, services: SessionServices,
                out: TextIO | None = None) -> int:
    """Registra o projeto e o checkout primario; nunca cria workspace."""
    out = out or sys.stdout
    repo_path = Path(repo).resolve()
    root = (Path(worktree_root) if worktree_root
            else repo_path.parent / f"{repo_path.name}-worktrees")
    project = services.registry.add(repo_path, integration_branch, root)
    binding = services.registry.register_checkout(project.id, project.primary)
    print(json.dumps({
        "schemaVersion": _SCHEMA_VERSION,
        "projectId": str(project.id),
        "checkoutId": str(binding.checkout_id),
        "sourcePath": str(binding.source_path),
        "workspace": binding.workspace,
    }), file=out)
    return 0


# -- session list -----------------------------------------------------------------


def _session_json(session: AgentSession) -> dict[str, object]:
    """Exatamente os campos de relacionamento que o store grava."""
    healthy = session.last_healthy_at
    started = session.started_at
    return {
        "id": str(session.id),
        "checkoutId": str(session.checkout_id),
        "agent": str(session.agent),
        "title": session.title,
        "cwd": str(session.cwd),
        "terminalId": (str(session.terminal_id)
                       if session.terminal_id is not None else None),
        "providerSessionId": (str(session.provider_session_id)
                              if session.provider_session_id is not None
                              else None),
        "state": str(session.state),
        "lastHealthyAt": (healthy.strftime("%Y-%m-%dT%H:%M:%SZ")
                          if healthy is not None else None),
        "revision": session.revision,
        "startedAt": (started.strftime("%Y-%m-%dT%H:%M:%SZ")
                      if started is not None else None),
    }


def session_list(checkout: str | None, *, as_json: bool,
                 services: SessionServices, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    wanted = CheckoutId(checkout) if checkout is not None else None
    found = [s for s in services.store.list()
             if wanted is None or s.checkout_id == wanted]
    if as_json:
        print(json.dumps({"schemaVersion": _SCHEMA_VERSION,
                          "sessions": [_session_json(s) for s in found]}),
              file=out)
        return 0
    if not found:
        print("nenhuma sessao", file=out)
    for s in found:
        print(f"{s.id}  {s.checkout_id}  {s.agent}  {s.state}  {s.title}",
              file=out)
    return 0


# -- session start ------------------------------------------------------------------


def session_start(checkout: str, agent: str, title: str | None, *,
                  services: SessionServices, out: TextIO | None = None) -> int:
    """Sobe o workspace do checkout se preciso e inicia a sessao no
    checkout de EXECUCAO do sandbox (`project_root`), nunca no do operador."""
    out = out or sys.stdout
    kind = AgentKind(agent)
    binding = services.registry.checkout(CheckoutId(checkout))
    connection = services.runtime.ensure(binding)
    manager = services.manager_for(connection)
    session = manager.start(StartSession(
        checkout_id=binding.checkout_id, agent=kind,
        cwd=connection.project_root, title=title or f"{kind} session"))
    print(f"{session.id} {session.state}", file=out)
    return 0 if session.state is SessionState.RUNNING else 2


# -- sessao existente: attach / stop / resume -----------------------------------------


def _existing(session_id: str, services: SessionServices
              ) -> tuple[AgentSession, CheckoutBinding]:
    record = services.store.get(SessionId(session_id))
    return record, services.registry.checkout(record.checkout_id)


def _manager(binding: CheckoutBinding,
             services: SessionServices) -> SessionManager:
    # `resolve`, nunca `ensure`: estes comandos nao sobem workspace.
    return services.manager_for(services.resolve(binding.workspace))


def session_attach(session_id: str, *, services: SessionServices,
                   execute: Callable[[str, list[str]], object] = os.execvp,
                   err: TextIO | None = None) -> int:
    """Substitui o processo pelo `ssh` que anexa ao tmux da sessao; ao
    desanexar, o controle volta ao shell que chamou. `execute` e injetavel;
    o default `os.execvp` nao retorna."""
    err = err or sys.stderr
    record, binding = _existing(session_id, services)
    if record.state not in _NOT_ATTACHABLE:
        result = _manager(binding, services).attach(record.id)
        if result.argv is not None:
            argv = list(result.argv)
            execute(argv[0], argv)
            return 0
        record = result.session
    print(f"asb-agent: sessao {record.id} esta em {record.state}; "
          "nada para anexar", file=err)
    return 2


def session_stop(session_id: str, *, services: SessionServices,
                 out: TextIO | None = None) -> int:
    out = out or sys.stdout
    record, binding = _existing(session_id, services)
    session = _manager(binding, services).stop(record.id)
    print(f"{session.id} {session.state}", file=out)
    return 0


def session_resume(session_id: str, *, services: SessionServices,
                   out: TextIO | None = None) -> int:
    out = out or sys.stdout
    record, binding = _existing(session_id, services)
    session = _manager(binding, services).resume(record.id).session
    print(f"{session.id} {session.state}", file=out)
    return 0 if session.state in _LIVE else 2
