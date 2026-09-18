"""cli/asb/interfaces/tui.py — `asb-agent tui`: navegador de projetos,
checkouts e sessoes.

Duas camadas:

- `TuiController` guarda o estado (linhas, selecao, mensagem, prompt) e faz
  as acoes pelos MESMOS servicos do CLI da Tarefa 9 (`session_start`,
  `session_attach`, `session_stop`). `refresh()` e o unico lugar que le
  registro, workspaces, Git e sessoes, e so roda no inicio, em `r` e
  depois de um attach: nunca a cada desenho, nunca em segundo plano;
- a camada curses (`render`, `handle_key`, `run`) so desenha linhas ja
  calculadas e mapeia teclas. `curses.wrapper()` e dono do setup/teardown.

`q` so sai: nunca para, suspende nem mata nada. O attach roda como processo
FILHO (nao `exec`), com o curses suspenso e restaurado num `finally`.
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

from ..checkouts.model import CheckoutKind
from ..projects.model import Project, ProjectId
from ..runtime.sandbox import WorkspaceDiscovery, WorkspaceStatus
from ..sessions.model import AgentKind, AgentSession, SessionState
from .sessions import (
    SessionServices, session_attach, session_start, session_stop,
)
from .tui_model import (
    CheckoutView, RowKind, TreeRow, build_tree, checkout_key, project_key,
    sanitize,
)

MIN_WIDTH = 40
MIN_HEIGHT = 5
GIT_TIMEOUT_SECONDS = 5.0
_REASON_LIMIT = 120

AGENTS = (AgentKind.CODEX, AgentKind.CLAUDE, AgentKind.ANTIGRAVITY)
_NOT_ATTACHABLE = frozenset({SessionState.RECOVERY_REQUIRED,
                             SessionState.COMPLETED, SessionState.FAILED})
_FINAL = frozenset({SessionState.COMPLETED, SessionState.FAILED})
_ENTER_KEYS = frozenset({10, 13, curses.KEY_ENTER})
HELP = ("j/k move  Enter open  n new  d stop  w worktree  f finish  "
        "r refresh  q quit")


# -- leitura de branch (so chamada por refresh) --------------------------------


@dataclass(frozen=True)
class BranchInfo:
    name: str
    detached: bool


def read_branch(path: Path, *,
                run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                ) -> BranchInfo | None:
    """Branch de `path`, ou o commit abreviado num HEAD destacado; `None`
    em qualquer falha do Git (nunca levanta). Um Git que nem executa (sem
    binario, timeout) nao ganha a segunda tentativa."""
    def git(*args: str) -> subprocess.CompletedProcess | None:
        try:
            return run(["git", "-C", str(path), *args], shell=False,
                       capture_output=True, text=True,
                       timeout=GIT_TIMEOUT_SECONDS, check=False,
                       stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None

    def value(result: subprocess.CompletedProcess | None) -> str | None:
        if result is None or result.returncode != 0:
            return None
        return (result.stdout or "").strip() or None

    result = git("symbolic-ref", "--short", "HEAD")
    if result is None:
        return None
    name = value(result)
    if name is not None:
        return BranchInfo(name, False)
    commit = value(git("rev-parse", "--short", "HEAD"))
    return BranchInfo(commit, True) if commit is not None else None


def run_child(argv: list[str]) -> int:
    """Roda o attach como processo filho, sem shell; devolve o exit code."""
    return subprocess.run(argv, check=False).returncode


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
                 run_child: Callable[[list[str]], int] = run_child) -> None:
        self._services = services
        self._read_branch = read_branch
        self._run_child = run_child
        # Substituido pela camada curses (`run`); testes injetam um falso.
        self.terminal = _NoTerminal()
        self.rows: tuple[TreeRow, ...] = ()
        self.selected = 0
        self.message = ""
        self.prompt: Prompt | None = None
        self.running = True
        self._collapsed: set[str] = set()
        self._projects: list[Project] = []
        self._views: list[CheckoutView] = []
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
                               project_errors=self._project_errors)
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
            for found in discovered:
                view, sessions = self._checkout(
                    project, found,
                    by_checkout.get(found.binding.checkout_id, []))
                if store_error is not None:
                    view = _with_error(view, store_error)
                self._views.append(view)
                self._sessions.extend(sessions)
        self._rebuild(previous)

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
            kind=(CheckoutKind.PRIMARY if binding.source_path == project.primary
                  else CheckoutKind.WORKTREE),
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
            session_start(row.checkout_id, kind.value, None,
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

    def reserved(self, action: str) -> None:
        self.message = f"{action} is not available yet"

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
        controller.reserved("new worktree")
    elif key == ord("f"):
        controller.reserved("finish")
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
    `message` e `prompt`: nenhum servico, Git, Podman, SSH ou tmux."""
    height, width = screen.getmaxyx()
    screen.erase()
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        _put(screen, 0, f"terminal too small (min {MIN_WIDTH}x{MIN_HEIGHT})",
             width)
        _refresh(screen)
        return
    _put(screen, 0, f"asb-agent  {HELP}", width)
    body = height - 2
    top = max(0, controller.selected - body + 1)
    for offset, row in enumerate(controller.rows[top:top + body]):
        index = top + offset
        attr = curses.A_REVERSE if index == controller.selected else 0
        _put(screen, 1 + offset, "  " * row.depth + row.text, width, attr)
    status = controller.prompt.text if controller.prompt else controller.message
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
