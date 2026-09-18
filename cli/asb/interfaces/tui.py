"""cli/asb/interfaces/tui.py — `asb-agent tui`: navegador de projetos,
checkouts e sessoes.

Duas camadas:

- `TuiController` guarda o estado (linhas, selecao, mensagem, prompt) e faz
  as acoes pelos MESMOS servicos do CLI da Tarefa 9 (`session_start`,
  `session_attach`, `session_stop`) e, para worktrees, pelo
  `CheckoutManager` (Tarefa 11). `refresh()` le registro, workspaces, Git
  e sessoes, e so roda no inicio, em `r` e depois de uma acao: nunca a
  cada desenho, nunca em segundo plano;
- a camada curses (`render`, `handle_key`, `run`) so desenha linhas ja
  calculadas e mapeia teclas. `curses.wrapper()` e dono do setup/teardown.

`q` so sai: nunca para, suspende nem mata nada. O attach roda como processo
FILHO (nao `exec`), com o curses suspenso e restaurado num `finally`.

`w` cria um worktree: branch novo -> base (o branch de integracao, ou o
branch do checkout selecionado como escolha explicita) -> caminho editavel
-> previa (projeto, base e commit, branch, caminho, "creates branch") ->
so `y` cria. Qualquer outra tecla cancela sem efeito.

`f` finaliza um worktree: branch alvo (default: o de integracao) ->
confirmacao (commit de origem, branch e checkout alvo, limpeza depois do
merge e remocao do branch local, ambas NAO por padrao e alternadas com `c`
e `b`) -> so `y` roda `CheckoutManager.finish`. Numa linha marcada
`merged / cleanup available` (prova fresca do refresh), `f` oferece a
limpeza direto; tambem num worktree cujo sandbox esta POSITIVAMENTE
ausente (nunca criado ou purgado a mao), onde nao ha finish possivel e a
limpeza prova a integracao pelo HEAD do proprio worktree. Nao existe acao
de remocao remota.
"""
from __future__ import annotations

import curses
import io
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from .. import podman
from ..checkouts.git import BranchInfo, GitRepository
from ..checkouts.manager import (
    CheckoutManager, CreateCheckout, CreatePreview, FinishPreview,
    checkout_kind,
)
from ..checkouts.model import CheckoutKind, FinishCheckout, FinishResult
from ..projects.model import Project, ProjectId
from ..projects.registry import CheckoutBinding
from ..runtime.sandbox import WorkspaceDiscovery, WorkspaceStatus
from ..sessions.model import AgentKind, AgentSession, SessionState
from ..sessions.terminal import Liveness, TmuxTerminal
from .sessions import (
    SessionServices, session_attach, session_start, session_stop,
)
from .tui_model import (
    CheckoutView, RowKind, TreeRow, UnregisteredView, build_tree,
    checkout_key, project_key, sanitize,
)

MIN_WIDTH = 40
MIN_HEIGHT = 5
_REASON_LIMIT = 120

AGENTS = (AgentKind.CODEX, AgentKind.CLAUDE, AgentKind.ANTIGRAVITY)
_NOT_ATTACHABLE = frozenset({SessionState.RECOVERY_REQUIRED,
                             SessionState.COMPLETED, SessionState.FAILED})
_FINAL = frozenset({SessionState.COMPLETED, SessionState.FAILED})
_ENTER_KEYS = frozenset({10, 13, curses.KEY_ENTER})
_ESCAPE = 27
_BACKSPACE_KEYS = frozenset({8, 127, curses.KEY_BACKSPACE})
HELP = ("j/k move  Enter open  n new  d stop  w worktree  f finish  "
        "r refresh  q quit")


# -- leitura de branch (so chamada por refresh) --------------------------------


def read_branch(path: Path) -> BranchInfo | None:
    """Branch de `path` pelo `GitRepository` (§C): a TUI nao monta argv de
    Git. `None` em qualquer falha, nunca levanta."""
    return GitRepository(path).branch()


def run_child(argv: list[str]) -> int:
    """Roda o attach como processo filho, sem shell; devolve o exit code."""
    return subprocess.run(argv, check=False).returncode


def session_liveness(services: SessionServices
                     ) -> Callable[[CheckoutBinding, AgentSession], Liveness]:
    """Sonda do tmux da sessao pela conexao viva do workspace, sem nunca
    subir nada; uma conexao que nao resolve e `UNKNOWN`."""
    def probe(binding: CheckoutBinding, session: AgentSession) -> Liveness:
        try:
            connection = services.resolve(binding.workspace)
        except (podman.PodmanError, OSError, subprocess.SubprocessError):
            return Liveness.UNKNOWN
        return TmuxTerminal(connection).probe(session.terminal_id)
    return probe


def default_checkouts(services: SessionServices) -> CheckoutManager:
    """O `CheckoutManager` da TUI, com o que `finish` precisa: o runtime,
    as sessoes do store e a sonda de liveness."""
    return CheckoutManager(
        services.registry, runtime=services.runtime,
        sessions=lambda checkout_id: [s for s in services.store.list()
                                      if s.checkout_id == checkout_id],
        liveness=session_liveness(services))


def _reason(error: BaseException) -> str:
    lines = str(error).splitlines() or [type(error).__name__]
    return sanitize(lines[0].strip() or type(error).__name__)[:_REASON_LIMIT]


def _last_line(buffer: io.StringIO) -> str:
    lines = buffer.getvalue().strip().splitlines()
    return lines[-1] if lines else ""


# -- controlador ----------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    """Pergunta de uma tecla na linha de status. Tecla fora de `choices`
    cancela."""

    text: str
    choices: dict[str, Callable[[], None]]
    # Linhas desenhadas acima da linha de status enquanto o prompt esta
    # aberto (a previa de um worktree).
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextPrompt:
    """Entrada de texto na linha de status: Enter envia, Esc cancela,
    Backspace apaga; so ASCII imprimivel entra no valor."""

    text: str
    value: str
    submit: Callable[[str], None]


class _NoTerminal:
    def suspend(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def redraw(self) -> None:
        pass


class TuiController:
    def __init__(self, services: SessionServices, *,
                 read_branch: Callable[[Path], BranchInfo | None] = read_branch,
                 run_child: Callable[[list[str]], int] = run_child,
                 checkouts: CheckoutManager | None = None) -> None:
        self._services = services
        self._read_branch = read_branch
        self._run_child = run_child
        self.checkouts = (checkouts if checkouts is not None
                          else default_checkouts(services))
        # Substituido pela camada curses (`run`); testes injetam um falso.
        self.terminal = _NoTerminal()
        self.rows: tuple[TreeRow, ...] = ()
        self.selected = 0
        self.message = ""
        self.prompt: Prompt | TextPrompt | None = None
        # Aviso de varias linhas (o que sobrou de uma criacao que falhou);
        # a proxima tecla o dispensa.
        self.notice: tuple[str, ...] = ()
        self.running = True
        self._collapsed: set[str] = set()
        self._projects: list[Project] = []
        self._views: list[CheckoutView] = []
        self._unregistered: list[UnregisteredView] = []
        self._sessions: list[AgentSession] = []
        self._project_errors: dict[ProjectId, str] = {}

    # -- estado ----------------------------------------------------------------

    @property
    def selected_row(self) -> TreeRow | None:
        if 0 <= self.selected < len(self.rows):
            return self.rows[self.selected]
        return None

    def _rebuild(self, previous: TreeRow | None = None) -> None:
        """Recalcula as linhas mantendo a selecao pela chave; se ela sumiu,
        cai para o checkout, depois o projeto, depois a mesma posicao."""
        previous = previous if previous is not None else self.selected_row
        old_index = self.selected
        self.rows = build_tree(self._projects, self._views, self._sessions,
                               collapsed=frozenset(self._collapsed),
                               project_errors=self._project_errors,
                               unregistered=self._unregistered)
        index = {row.key: i for i, row in enumerate(self.rows)}
        if previous is not None:
            candidates = [previous.key]
            if previous.checkout_id is not None:
                candidates.append(checkout_key(previous.checkout_id))
            if previous.project_id is not None:
                candidates.append(project_key(previous.project_id))
            for key in candidates:
                if key in index:
                    self.selected = index[key]
                    return
        self.selected = min(old_index, max(len(self.rows) - 1, 0))
        if self.selected_row is not None and not self.selected_row.selectable:
            self.move(-1)

    # -- refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        previous = self.selected_row
        services = self._services
        self._project_errors = {}
        self._views = []
        self._unregistered = []
        self._sessions = []
        try:
            self._projects = list(services.registry.list())
        except Exception as error:  # fronteira de UI: vira mensagem
            self._projects = []
            self.message = f"registry: {_reason(error)}"
            self._rebuild(previous)
            return
        store_error = None
        try:
            stored = list(services.store.list())
        except Exception as error:
            stored = []
            store_error = f"sessions: {_reason(error)}"
        by_checkout: dict[str, list[AgentSession]] = {}
        for session in stored:
            by_checkout.setdefault(session.checkout_id, []).append(session)
        for project in self._projects:
            try:
                discovered = services.runtime.discover(project)
            except Exception as error:
                self._project_errors[project.id] = _reason(error)
                continue
            missing = self._worktrees(project)
            for found in discovered:
                view, sessions = self._checkout(
                    project, found,
                    by_checkout.get(found.binding.checkout_id, []))
                if store_error is not None:
                    view = _with_error(view, store_error)
                if found.binding.checkout_id in missing:
                    view = replace(view, missing=True)
                if view.kind is CheckoutKind.WORKTREE:
                    # Prova fresca a cada refresh, nunca guardada; para um
                    # worktree ausente, a das refs exportadas.
                    view = replace(view, merged=self.checkouts.merged(
                        view.checkout_id, project.integration_branch))
                self._views.append(view)
                self._sessions.extend(sessions)
        self._rebuild(previous)

    def _worktrees(self, project: Project) -> set[str]:
        """Le a lista do Git (nunca grava): guarda os worktrees fora do
        registro e devolve os checkouts registrados que sumiram. Uma falha
        marca o projeto e nao esconde os checkouts registrados."""
        try:
            listed = self.checkouts.list(project.id)
        except Exception as error:
            self._project_errors[project.id] = _reason(error)
            return set()
        missing: set[str] = set()
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
            self._unregistered.append(UnregisteredView(
                project_id=project.id, path=entry.path,
                branch=wt.branch or (wt.head[:7] if wt.head else None),
                detached=wt.detached, missing=entry.missing,
                prunable=wt.prunable))
        return missing

    def _checkout(self, project: Project, found: WorkspaceDiscovery,
                  sessions: list[AgentSession]
                  ) -> tuple[CheckoutView, list[AgentSession]]:
        binding = found.binding
        ready = (found.status is WorkspaceStatus.READY
                 and found.connection is not None)
        # Pronto: o branch do checkout de EXECUCAO do sandbox, onde o
        # agente roda `git switch`. Senao, o do operador, marcado como host.
        where = found.connection.project_root if ready else binding.source_path
        branch = self._read_branch(where)
        error = None
        if ready and sessions:
            try:
                manager = self._services.manager_for(found.connection)
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

    # -- navegacao -------------------------------------------------------------

    def move(self, delta: int) -> None:
        if not self.rows:
            self.selected = 0
            return
        step = 1 if delta > 0 else -1
        index = self.selected
        for _ in range(abs(delta)):
            probe = index + step
            while 0 <= probe < len(self.rows) and \
                    not self.rows[probe].selectable:
                probe += step
            if not 0 <= probe < len(self.rows):
                break
            index = probe
        self.selected = index

    def toggle(self) -> None:
        row = self.selected_row
        if row is None or row.kind not in (RowKind.PROJECT, RowKind.CHECKOUT):
            return
        self._collapsed.symmetric_difference_update({row.key})
        self._rebuild(row)

    def activate(self) -> None:
        row = self.selected_row
        if row is None:
            return
        if row.kind is RowKind.SESSION:
            self.attach(row)
        else:
            self.toggle()

    def quit(self) -> None:
        """So encerra a TUI; sessoes e workspaces seguem como estao."""
        self.running = False

    # -- acoes -----------------------------------------------------------------

    def attach(self, row: TreeRow) -> None:
        if row.session_state in _NOT_ATTACHABLE:
            self.message = (f"session is {row.session_state}; "
                            "nothing to attach")
            return
        exit_codes: list[int] = []

        def execute(_file: str, argv: list[str]) -> None:
            self.terminal.suspend()
            try:
                exit_codes.append(self._run_child(argv))
            finally:
                self.terminal.restore()

        err = io.StringIO()
        try:
            code = session_attach(row.session_id, services=self._services,
                                  execute=execute, err=err)
        except Exception as error:
            message = f"attach failed: {_reason(error)}"
        else:
            if code != 0:
                message = _last_line(err) or "nothing to attach"
            elif exit_codes and exit_codes[0] != 0:
                message = f"attach exited with code {exit_codes[0]}"
            else:
                message = "detached"
        self.refresh()
        self.message = sanitize(message)

    def new_session(self) -> None:
        row = self.selected_row
        if row is None or row.kind is not RowKind.CHECKOUT:
            self.message = "select a checkout to start a session"
            return
        choices = {str(i): (lambda kind=kind: self._start(row, kind))
                   for i, kind in enumerate(AGENTS, start=1)}
        labels = "  ".join(f"{i} {kind}"
                           for i, kind in enumerate(AGENTS, start=1))
        self.prompt = Prompt(f"agent: {labels}  (other key cancels)", choices)

    def _start(self, row: TreeRow, kind: AgentKind) -> None:
        self.message = f"starting {kind} session..."
        self.terminal.redraw()
        out = io.StringIO()
        try:
            checkout_id = row.checkout_id
            if checkout_id is None:
                # Worktree criado fora da TUI: registrar (idempotente, com a
                # checagem de repositorio) so agora, na escolha do agente.
                checkout_id = self._services.registry.register_checkout(
                    row.project_id, row.source_path).checkout_id
            session_start(checkout_id, kind.value, None,
                          services=self._services, out=out)
        except Exception as error:
            message = f"start failed: {_reason(error)}"
        else:
            message = f"started {_last_line(out)}"
        self.refresh()
        self.message = sanitize(message)

    def session_menu(self) -> None:
        row = self.selected_row
        if row is None or row.kind is not RowKind.SESSION:
            self.message = "select a session to stop"
            return
        if row.session_state in _FINAL:
            self.message = f"session already {row.session_state}"
            return
        self.prompt = Prompt("session: s stop  c cancel", {
            "s": lambda: self._confirm_stop(row),
            "c": lambda: None,
        })

    def _confirm_stop(self, row: TreeRow) -> None:
        self.prompt = Prompt("stop this session? y stop  (other key cancels)",
                             {"y": lambda: self._stop(row)})

    def _stop(self, row: TreeRow) -> None:
        out = io.StringIO()
        try:
            session_stop(row.session_id, services=self._services, out=out)
        except Exception as error:
            message = f"stop failed: {_reason(error)}"
        else:
            message = f"stopped {_last_line(out)}"
        self.refresh()
        self.message = sanitize(message)

    # -- worktree (`w`) ----------------------------------------------------------

    def new_worktree(self) -> None:
        row = self.selected_row
        if row is None or row.kind not in (RowKind.PROJECT, RowKind.CHECKOUT):
            self.message = "select a project or checkout to create a worktree"
            return
        project = next(p for p in self._projects if p.id == row.project_id)
        self.prompt = TextPrompt(
            "new branch (Enter next, Esc cancels)", "",
            lambda branch: self._worktree_base(row, project, branch))

    def _worktree_base(self, row: TreeRow, project: Project,
                       branch: str) -> None:
        if not branch:
            self.message = "cancelled"
            return
        bases = [project.integration_branch]
        # O branch do checkout selecionado so entra como escolha explicita:
        # nunca e o default, para nao empilhar branches sem querer.
        if row.kind is RowKind.CHECKOUT and row.source_path is not None:
            info = self._read_branch(row.source_path)
            if info is not None and not info.detached \
                    and info.name not in bases:
                bases.append(info.name)
        choices = {str(i): (lambda base=base:
                            self._worktree_path(project, branch, base))
                   for i, base in enumerate(bases, start=1)}
        labels = "  ".join(f"{i} {base}" for i, base in enumerate(bases, 1))
        self.prompt = Prompt(sanitize(f"base: {labels}  (other key cancels)"),
                             choices)

    def _worktree_path(self, project: Project, branch: str, base: str) -> None:
        default = str(self.checkouts.default_path(project, branch))
        self.prompt = TextPrompt(
            "path (Enter preview, Esc cancels)", default,
            lambda path: self._worktree_preview(
                CreateCheckout(project.id, branch, base, Path(path))))

    def _worktree_preview(self, request: CreateCheckout) -> None:
        if not str(request.path) or str(request.path) == ".":
            self.message = "cancelled"
            return
        try:
            preview = self.checkouts.preview(request)
        except Exception as error:
            self.message = f"worktree refused: {_reason(error)}"
            return
        self.prompt = Prompt(
            "create this worktree? y create  (other key cancels)",
            # O create fica preso ao commit que o operador viu.
            {"y": lambda: self._worktree_create(
                replace(request, base_commit=preview.base_commit))},
            detail=_preview_lines(preview))

    def _worktree_create(self, request: CreateCheckout) -> None:
        self.message = "creating worktree..."
        self.terminal.redraw()
        notice: tuple[str, ...] = ()
        try:
            checkout = self.checkouts.create(request)
        except Exception as error:
            message = f"worktree failed: {_reason(error)}"
            notice = tuple(sanitize(part.strip())
                           for part in str(error).split(";") if part.strip())
        else:
            message = f"created {checkout.branch} at {checkout.path}"
        self.refresh()
        self.message = sanitize(message)
        self.notice = notice

    # -- finish (`f`) -------------------------------------------------------------

    def finish(self) -> None:
        row = self.selected_row
        view = next((v for v in self._views
                     if row is not None and v.checkout_id == row.checkout_id),
                    None)
        if view is None or row.kind is not RowKind.CHECKOUT:
            self.message = "select a registered worktree to finish"
            return
        if view.kind is CheckoutKind.PRIMARY:
            self.message = "the primary checkout is never finished"
            return
        project = next(p for p in self._projects if p.id == view.project_id)
        if view.missing:
            # Nada para mergear: so a limpeza, que prova tudo de novo e
            # recusa (BLOCKED) sem evidencia.
            self._missing_cleanup_confirm(view, project.integration_branch)
            return
        if view.merged:
            self._cleanup_confirm(view.checkout_id, project.integration_branch,
                                  delete=False)
            return
        if self.checkouts.sandbox_absent(view.checkout_id):
            # Sem sandbox nao ha o que exportar nem mergear: so a limpeza,
            # que prova a integracao pelo HEAD do worktree e recusa sem ela.
            self._cleanup_confirm(view.checkout_id, project.integration_branch,
                                  delete=False)
            return
        self.prompt = TextPrompt(
            "target branch (Enter next, Esc cancels)",
            project.integration_branch,
            lambda target: self._finish_confirm(
                FinishCheckout(view.checkout_id, target)))

    def _finish_confirm(self, request: FinishCheckout) -> None:
        if not request.target_branch:
            self.message = "cancelled"
            return
        try:
            preview = self.checkouts.finish_preview(request.checkout_id,
                                                    request.target_branch)
        except Exception as error:
            self.message = f"finish refused: {_reason(error)}"
            return
        cleanup = request.cleanup_after_merge
        delete = request.delete_merged_branch
        self.prompt = Prompt(
            "finish? y finish  c cleanup  b branch  (other key cancels)",
            # O finish fica preso ao branch e commit do sandbox mostrados.
            {"y": lambda: self._finish_run(replace(
                request, expected_sandbox_branch=preview.sandbox_branch,
                expected_sandbox_commit=preview.sandbox_commit)),
             "c": lambda: self._finish_confirm(
                 replace(request, cleanup_after_merge=not cleanup)),
             "b": lambda: self._finish_confirm(
                 replace(request, delete_merged_branch=not delete))},
            detail=_finish_lines(preview, cleanup=cleanup, delete=delete))

    def _finish_run(self, request: FinishCheckout) -> None:
        self.message = "finishing..."
        self.terminal.redraw()
        self._show_result(lambda: self.checkouts.finish(request), "finish")

    def _missing_cleanup_confirm(self, view: CheckoutView,
                                 target: str) -> None:
        self.prompt = Prompt(
            "clean up? y clean up  (other key cancels)",
            {"y": lambda: self._cleanup_run(view.checkout_id, target, False)},
            detail=tuple(sanitize(line) for line in (
                f"worktree: {view.source_path} is missing",
                f"cleanup: proves integration into {target} through the "
                f"export refs of {view.workspace}, then purges the sandbox "
                "and removes the registry binding",
                "without that proof it is refused and nothing is removed",
                "local branch: kept (its name is unknown here); remote "
                "branches are never touched",
            )))

    def _cleanup_confirm(self, checkout_id, target: str, *,
                         delete: bool) -> None:
        try:
            preview = self.checkouts.finish_preview(checkout_id, target,
                                                    merge=False)
        except Exception as error:
            self.message = f"cleanup refused: {_reason(error)}"
            return
        self.prompt = Prompt(
            "clean up? y clean up  b branch  (other key cancels)",
            {"y": lambda: self._cleanup_run(checkout_id, target, delete),
             "b": lambda: self._cleanup_confirm(checkout_id, target,
                                                delete=not delete)},
            detail=_cleanup_lines(preview, delete=delete))

    def _cleanup_run(self, checkout_id, target: str, delete: bool) -> None:
        self.message = "cleaning up..."
        self.terminal.redraw()
        self._show_result(
            lambda: self.checkouts.cleanup(checkout_id, target, delete),
            "cleanup")

    def _show_result(self, action: Callable[[], FinishResult],
                     name: str) -> None:
        notice: tuple[str, ...] = ()
        try:
            result = action()
        except Exception as error:
            message = f"{name} failed: {_reason(error)}"
        else:
            message = f"{name}: {result.state}"
            notice = tuple(sanitize(part.strip())
                           for part in result.message.split(";")
                           if part.strip())
        self.refresh()
        self.message = sanitize(message)
        self.notice = notice

    def edit(self, key: int) -> None:
        """Uma tecla para o `TextPrompt` aberto."""
        prompt = self.prompt
        if not isinstance(prompt, TextPrompt):
            return
        if key in _ENTER_KEYS:
            self.prompt = None
            prompt.submit(prompt.value.strip())
        elif key == _ESCAPE:
            self.prompt = None
            self.message = "cancelled"
        elif key in _BACKSPACE_KEYS:
            self.prompt = replace(prompt, value=prompt.value[:-1])
        elif 32 <= key < 127:
            self.prompt = replace(prompt, value=prompt.value + chr(key))

    def answer(self, key: str) -> None:
        """Responde o prompt aberto; tecla fora das opcoes cancela."""
        prompt, self.prompt = self.prompt, None
        if prompt is None:
            return
        action = prompt.choices.get(key)
        if action is None:
            self.message = "cancelled"
            return
        action()


def _preview_lines(preview: CreatePreview) -> tuple[str, ...]:
    return tuple(sanitize(line) for line in (
        f"project: {preview.project.primary}",
        f"base: {preview.base} at {preview.base_commit[:12]}",
        f"new branch: {preview.branch}",
        f"path: {preview.path}",
        f"creates branch: {'yes' if preview.creates_branch else 'no'}",
    ))


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _source_line(preview: FinishPreview) -> str:
    return (f"source: {preview.source_path} ({preview.source_branch}) at "
            f"{preview.source_commit[:12]}")


def _finish_lines(preview: FinishPreview, *, cleanup: bool,
                  delete: bool) -> tuple[str, ...]:
    return tuple(sanitize(line) for line in (
        _source_line(preview),
        f"merges: sandbox branch {preview.sandbox_branch} at "
        f"{(preview.sandbox_commit or '')[:12]} ({preview.workspace}); "
        "refused if it moves before the export",
        f"target: {preview.target_branch} in {preview.target_path}",
        f"cleanup after merge: {_yes(cleanup)} (c toggles; purges the "
        "sandbox, removes the worktree)",
        f"delete local branch: {_yes(delete)} (b toggles; git branch -d, "
        "after cleanup only; remote branches are never touched)",
    ))


def _cleanup_lines(preview: FinishPreview, *,
                   delete: bool) -> tuple[str, ...]:
    where = preview.target_path if preview.target_path is not None else "-"
    return tuple(sanitize(line) for line in (
        _source_line(preview),
        f"integrated into: {preview.target_branch} (checkout: {where})",
        f"cleanup: purges sandbox {preview.workspace}, removes the worktree",
        f"delete local branch: {_yes(delete)} (b toggles; git branch -d; "
        "remote branches are never touched)",
    ))


def _with_error(view: CheckoutView, error: str) -> CheckoutView:
    combined = f"{view.error}; {error}" if view.error else error
    return replace(view, error=combined)


# -- camada curses ---------------------------------------------------------------


def handle_key(controller: TuiController, key: int) -> None:
    """Mapeia uma tecla para uma acao do controlador. `KEY_RESIZE` nao faz
    nada aqui: o laco redesenha com o tamanho novo — nem cancela um prompt
    aberto."""
    if key == curses.KEY_RESIZE:
        return
    controller.notice = ()
    if isinstance(controller.prompt, TextPrompt):
        controller.edit(key)
        return
    if controller.prompt is not None:
        controller.answer(chr(key) if 0 <= key < 0x110000 else "")
        return
    if key in (curses.KEY_UP, ord("k")):
        controller.move(-1)
    elif key in (curses.KEY_DOWN, ord("j")):
        controller.move(1)
    elif key in _ENTER_KEYS:
        controller.activate()
    elif key == ord("n"):
        controller.new_session()
    elif key == ord("d"):
        controller.session_menu()
    elif key == ord("w"):
        controller.new_worktree()
    elif key == ord("f"):
        controller.finish()
    elif key == ord("r"):
        controller.refresh()
    elif key == ord("q"):
        controller.quit()


def _put(screen, y: int, text: str, width: int, attr: int = 0) -> None:
    """Escreve UMA linha saneada e cortada antes da ultima coluna; um
    `curses.error` (ex: a ultima celula da tela) nunca escapa."""
    limit = width - 1
    if limit <= 0:
        return
    try:
        screen.addnstr(y, 0, sanitize(text), limit, attr)
    except curses.error:
        pass


def render(screen, controller: TuiController) -> None:
    """Desenha o estado do controlador. So le `rows`, `selected`,
    `message`, `prompt` e `notice`: nenhum servico, Git, Podman, SSH ou
    tmux."""
    height, width = screen.getmaxyx()
    screen.erase()
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        _put(screen, 0, f"terminal too small (min {MIN_WIDTH}x{MIN_HEIGHT})",
             width)
        _refresh(screen)
        return
    _put(screen, 0, f"asb-agent  {HELP}", width)
    prompt = controller.prompt
    detail = prompt.detail if isinstance(prompt, Prompt) else controller.notice
    # A previa/aviso ocupa o fim do corpo; o cabecalho e uma linha de
    # arvore ficam sempre visiveis.
    keep = max(0, height - 3)
    detail = detail[len(detail) - keep:] if len(detail) > keep else detail
    body = height - 2 - len(detail)
    top = max(0, controller.selected - body + 1)
    for offset, row in enumerate(controller.rows[top:top + body]):
        index = top + offset
        attr = curses.A_REVERSE if index == controller.selected else 0
        _put(screen, 1 + offset, "  " * row.depth + row.text, width, attr)
    for offset, line in enumerate(detail):
        _put(screen, 1 + body + offset, line, width)
    if isinstance(prompt, TextPrompt):
        status = f"{prompt.text}: {prompt.value}_"
    elif prompt is not None:
        status = prompt.text
    else:
        status = controller.message
    _put(screen, height - 1, status, width)
    _refresh(screen)


def _refresh(screen) -> None:
    try:
        screen.refresh()
    except curses.error:
        pass


class CursesTerminal:
    """O que o controlador pode pedir ao terminal: sair do curses para um
    processo filho, voltar, e redesenhar antes de uma acao demorada."""

    def __init__(self, screen, draw: Callable[[], None]) -> None:
        self._screen = screen
        self._draw = draw

    def suspend(self) -> None:
        curses.def_prog_mode()
        curses.endwin()

    def restore(self) -> None:
        curses.reset_prog_mode()
        self._screen.clear()
        _refresh(self._screen)

    def redraw(self) -> None:
        self._draw()


def run(screen, controller: TuiController) -> None:
    """Laco principal, chamado por `curses.wrapper`."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    controller.terminal = CursesTerminal(
        screen, lambda: render(screen, controller))
    controller.message = "loading..."
    render(screen, controller)
    controller.message = ""
    controller.refresh()
    while controller.running:
        render(screen, controller)
        handle_key(controller, screen.getch())


def run_tui(services: SessionServices, *, err: TextIO | None = None) -> int:
    err = err or sys.stderr
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("asb-agent: tui precisa de um terminal interativo", file=err)
        return 2
    curses.wrapper(run, TuiController(services))
    return 0
