"""cli/asb/interfaces/snapshot.py — leitura pura do estado de projetos,
checkouts e sessoes.

`read_snapshot` e o corpo de `TuiController.refresh` (Tarefa 10) extraido
sem curses: le registro, workspaces, Git e sessoes e devolve um `Snapshot`
imutavel, sem guardar nada e sem desenhar nada. A TUI e o futuro daemon web
chamam a MESMA funcao; por isso este modulo nao pode importar `curses`,
direta ou transitivamente — nenhuma das dependencias abaixo o faz.

`read_snapshot` nunca levanta por uma falha de projeto ou de checkout: ela
vira um erro no proprio `Snapshot` (`project_errors`, `CheckoutView.error`).
So uma falha do REGISTRO e excecao: ai o snapshot volta com as colecoes
vazias e `registry_error` preenchido — quem chama decide a mensagem (a TUI
aplica o prefixo `registry: `; o daemon devolve 503 com a razao crua).
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .. import podman
from ..checkouts.git import BranchInfo, GitRepository
from ..checkouts.manager import CheckoutManager, checkout_kind
from ..checkouts.model import CheckoutKind
from ..projects.model import Project, ProjectId
from ..projects.registry import CheckoutBinding
from ..runtime.sandbox import WorkspaceDiscovery, WorkspaceStatus
from ..sessions.model import AgentSession, SessionState
from ..sessions.terminal import Liveness, TmuxTerminal
from .sessions import SessionServices
from .tui_model import CheckoutView, UnregisteredView, sanitize

_REASON_LIMIT = 120


def read_branch(path: Path) -> BranchInfo | None:
    """Branch de `path` pelo `GitRepository` (§C): nunca monta argv de
    Git na mao. `None` em qualquer falha, nunca levanta."""
    return GitRepository(path).branch()


def _default_liveness(services: SessionServices
                      ) -> Callable[[CheckoutBinding, AgentSession], Liveness]:
    """Sonda padrao do tmux da sessao pela conexao viva do workspace, sem
    nunca subir nada; uma conexao que nao resolve e `UNKNOWN`. So o
    fallback de `default_checkouts` quando quem chama nao injeta a sua
    propria sonda (a TUI injeta: ver `tui.session_liveness`, que fica la
    de proposito para os testes poderem substituir `TmuxTerminal` pelo
    proprio modulo `tui`)."""
    def probe(binding: CheckoutBinding, session: AgentSession) -> Liveness:
        try:
            connection = services.resolve(binding.workspace)
        except (podman.PodmanError, OSError, subprocess.SubprocessError):
            return Liveness.UNKNOWN
        return TmuxTerminal(connection).probe(session.terminal_id)
    return probe


def default_checkouts(services: SessionServices, *,
                      manager: Callable[..., CheckoutManager] = CheckoutManager,
                      liveness: Callable[[CheckoutBinding, AgentSession],
                                         Liveness] | None = None,
                      ) -> CheckoutManager:
    """O `CheckoutManager` padrao (spec §7.4: o daemon monta o seu assim),
    com o que `finish` precisa: o runtime, as sessoes do store, a sonda de
    liveness e a escrita que marca `completed` os registros que sobram
    depois da limpeza. `manager` e `liveness` sao injetaveis — a TUI passa
    os seus proprios (ver `tui.session_liveness`) para continuar
    patcheavel nos testes existentes; sem eles, os padroes daqui servem
    para qualquer chamador sem curses, como o daemon."""
    return manager(
        services.registry, runtime=services.runtime,
        sessions=lambda checkout_id: [s for s in services.store.list()
                                      if s.checkout_id == checkout_id],
        liveness=liveness if liveness is not None
                 else _default_liveness(services),
        complete_session=lambda session: services.store.replace(
            session.with_state(SessionState.COMPLETED)))


def _reason(error: BaseException) -> str:
    lines = str(error).splitlines() or [type(error).__name__]
    return sanitize(lines[0].strip() or type(error).__name__)[:_REASON_LIMIT]


def _with_error(view: CheckoutView, error: str) -> CheckoutView:
    combined = f"{view.error}; {error}" if view.error else error
    return replace(view, error=combined)


def _worktrees(checkouts: CheckoutManager, project: Project
              ) -> tuple[set[str], list[UnregisteredView], str | None]:
    """Le a lista do Git (nunca grava): devolve os checkouts registrados
    que sumiram, os worktrees fora do registro e, se a listagem falhou, a
    razao (o chamador marca o projeto sem esconder os checkouts
    registrados)."""
    try:
        listed = checkouts.list(project.id)
    except Exception as error:
        return set(), [], _reason(error)
    missing: set[str] = set()
    unregistered: list[UnregisteredView] = []
    for entry in listed:
        if entry.binding is not None:
            if entry.missing:
                missing.add(entry.binding.checkout_id)
            continue
        # Sem vinculo, a entrada sempre vem do Git; um repositorio bare
        # nao tem checkout onde abrir sessao.
        wt = entry.worktree
        if wt is None or wt.bare:
            continue
        unregistered.append(UnregisteredView(
            project_id=project.id, path=entry.path,
            branch=wt.branch or (wt.head[:7] if wt.head else None),
            detached=wt.detached, missing=entry.missing,
            prunable=wt.prunable))
    return missing, unregistered, None


def _checkout(project: Project, found: WorkspaceDiscovery,
             sessions: list[AgentSession], services: SessionServices,
             read_branch: Callable[[Path], BranchInfo | None]
             ) -> tuple[CheckoutView, list[AgentSession]]:
    binding = found.binding
    ready = (found.status is WorkspaceStatus.READY
             and found.connection is not None)
    # Pronto: o branch do checkout de EXECUCAO do sandbox, onde o agente
    # roda `git switch`. Senao, o do operador, marcado como host.
    where = found.connection.project_root if ready else binding.source_path
    branch = read_branch(where)
    error = None
    if ready and sessions:
        try:
            manager = services.manager_for(found.connection)
            sessions = list(manager.reconcile(binding.checkout_id))
        except Exception as exc:
            error = _reason(exc)
    view = CheckoutView(
        checkout_id=binding.checkout_id, project_id=project.id,
        source_path=binding.source_path, workspace=binding.workspace,
        kind=checkout_kind(project, binding.source_path),
        status=found.status,
        branch=branch.name if branch is not None else None,
        detached=branch.detached if branch is not None else False,
        host_branch=not ready, reason=found.reason, error=error)
    return view, sessions


@dataclass(frozen=True)
class Snapshot:
    """A arvore inteira de UMA leitura: projetos, um `CheckoutView` por
    checkout, sessoes reconciliadas, worktrees fora do registro e os erros
    por projeto. `registry_error` so vem preenchido quando o proprio
    registro falhou; nesse caso as demais colecoes ficam vazias."""

    projects: tuple[Project, ...]
    checkouts: tuple[CheckoutView, ...]
    sessions: tuple[AgentSession, ...]
    unregistered: tuple[UnregisteredView, ...]
    project_errors: Mapping[ProjectId, str]
    registry_error: str | None


def read_snapshot(services: SessionServices, checkouts: CheckoutManager,
                  read_branch: Callable[[Path], BranchInfo | None]
                  ) -> Snapshot:
    """Le registro, workspaces, Git e sessoes e devolve um `Snapshot`.
    Nunca levanta por uma falha de projeto ou checkout; so uma falha do
    registro interrompe a leitura (colecoes vazias, `registry_error`
    preenchido)."""
    try:
        projects = list(services.registry.list())
    except Exception as error:  # fronteira de leitura: vira registry_error
        return Snapshot(projects=(), checkouts=(), sessions=(),
                        unregistered=(), project_errors={},
                        registry_error=_reason(error))
    project_errors: dict[ProjectId, str] = {}
    views: list[CheckoutView] = []
    unregistered: list[UnregisteredView] = []
    sessions: list[AgentSession] = []
    store_error = None
    try:
        stored = list(services.store.list())
    except Exception as error:
        stored = []
        store_error = f"sessions: {_reason(error)}"
    by_checkout: dict[str, list[AgentSession]] = {}
    for session in stored:
        by_checkout.setdefault(session.checkout_id, []).append(session)
    for project in projects:
        try:
            discovered = services.runtime.discover(project)
        except Exception as error:
            project_errors[project.id] = _reason(error)
            continue
        missing, project_unregistered, worktree_error = _worktrees(
            checkouts, project)
        if worktree_error is not None:
            project_errors[project.id] = worktree_error
        unregistered.extend(project_unregistered)
        for found in discovered:
            view, found_sessions = _checkout(
                project, found, by_checkout.get(found.binding.checkout_id, []),
                services, read_branch)
            if store_error is not None:
                view = _with_error(view, store_error)
            if found.binding.checkout_id in missing:
                view = replace(view, missing=True)
            if view.kind is CheckoutKind.WORKTREE:
                # Prova fresca a cada leitura, nunca guardada; para um
                # worktree ausente, a das refs exportadas.
                view = replace(view, merged=checkouts.merged(
                    view.checkout_id, project.integration_branch))
            views.append(view)
            sessions.extend(found_sessions)
    return Snapshot(projects=tuple(projects), checkouts=tuple(views),
                    sessions=tuple(sessions),
                    unregistered=tuple(unregistered),
                    project_errors=project_errors, registry_error=None)
