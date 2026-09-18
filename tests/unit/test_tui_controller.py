"""Testes de `asb.interfaces.tui` (Tarefa 10): o controlador da TUI e a
camada curses fina, com uma tela falsa.

Nenhum curses real, Podman, SSH, tmux, Git ou provedor: o registro, o
runtime e o gerente sao falsos; o `SessionStore` e REAL num diretorio
temporario; a leitura de branch e o processo filho do attach sao injetados.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import curses
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.checkouts.git import BranchInfo, Worktree  # noqa: E402
from asb.checkouts.manager import (  # noqa: E402
    CheckoutError, CheckoutManager, CreateCheckout, CreatePreview,
    FinishPreview, ListedCheckout,
)
from asb.checkouts.model import (  # noqa: E402
    Checkout, CheckoutId, CheckoutKind, CheckoutState, FinishCheckout,
    FinishResult, FinishState,
)
from asb.interfaces import sessions, tui  # noqa: E402
from asb.interfaces.tui_model import RowKind  # noqa: E402
from asb.podman import PodmanError  # noqa: E402
from asb.projects.model import Project, ProjectId  # noqa: E402
from asb.projects.registry import (  # noqa: E402
    CheckoutBinding, ProjectRegistry, ProjectRegistryError,
)
from asb.runtime.connection import ConnectionInfo  # noqa: E402
from asb.runtime.sandbox import (  # noqa: E402
    WorkspaceDiscovery, WorkspaceStatus,
)
from asb.sessions.manager import (  # noqa: E402
    AttachResult, SessionManager, StartSession,
)
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, SessionState, TerminalId,
)
from asb.sessions.store import SessionStore  # noqa: E402

PROJECT = ProjectId("p-alpha")
OTHER_PROJECT = ProjectId("p-beta")
PRIMARY = Path("/src/alpha")
WORKTREE = Path("/src/alpha-worktrees/topic")
SANDBOX_ROOT = Path("/home/op/asb-agent/alpha/ws-pri/alpha")
C_PRI = CheckoutId("c-pri")
C_WT = CheckoutId("c-wt")
ATTACH_ARGV = ("ssh", "-tt", "--", "v@127.0.0.1", "tmux attach-session -t =x")


def _info(workspace="ws-pri", root=SANDBOX_ROOT) -> ConnectionInfo:
    return ConnectionInfo(workspace=workspace, host="127.0.0.1", port=2222,
                          username="v", identity_file=Path("/keys/id"),
                          project_root=root)


def _forbidden(name):
    return mock.Mock(side_effect=AssertionError(f"{name} nao deveria rodar"))


class FakeTerminal:
    """O shim que a camada curses entrega ao controlador."""

    def __init__(self, events: list) -> None:
        self.events = events

    def suspend(self) -> None:
        self.events.append("suspend")

    def restore(self) -> None:
        self.events.append("restore")

    def redraw(self) -> None:
        self.events.append("redraw")


class FakeScreen:
    """Tela falsa: guarda o texto por linha e levanta `curses.error` ao
    escrever fora da tela ou na ultima celula, como o curses real."""

    def __init__(self, height=24, width=100, keys=(), on_key=None) -> None:
        self.height, self.width = height, width
        self.lines: dict[int, str] = {}
        self.attrs: dict[int, int] = {}
        self.keys = list(keys)
        self.on_key = on_key
        self.renders: list[tuple[int, int]] = []
        self.always_fail = False

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.lines = {}
        self.attrs = {}
        self.renders.append((self.height, self.width))

    def clear(self):
        self.erase()

    def addnstr(self, y, x, text, n, attr=0):
        if self.always_fail:
            raise curses.error("boom")
        if y >= self.height or x >= self.width or n < 0:
            raise curses.error("outside")
        text = text[:n]
        if y == self.height - 1 and x + len(text) >= self.width:
            raise curses.error("last cell")
        if x + len(text) > self.width:
            raise curses.error("wrapped")
        self.lines[y] = self.lines.get(y, "") + text
        self.attrs[y] = attr

    def refresh(self):
        pass

    def keypad(self, flag):
        pass

    def getch(self):
        key = self.keys.pop(0)
        if self.on_key is not None:
            self.on_key(self, key)
        return key

    def text(self) -> str:
        return "\n".join(self.lines[y] for y in sorted(self.lines))


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = SessionStore(Path(tmp.name) / "sessions.json")
        self.projects = [Project(id=PROJECT, primary=PRIMARY,
                                 integration_branch="main",
                                 worktree_root=PRIMARY.parent / "wts")]
        self.bindings = {
            C_PRI: CheckoutBinding(C_PRI, PROJECT, PRIMARY, "ws-pri"),
            C_WT: CheckoutBinding(C_WT, PROJECT, WORKTREE, "ws-wt"),
        }
        self.discovered = {PROJECT: [
            WorkspaceDiscovery(self.bindings[C_PRI], WorkspaceStatus.READY,
                               connection=_info()),
            WorkspaceDiscovery(self.bindings[C_WT], WorkspaceStatus.ABSENT),
        ]}
        self.registry = mock.MagicMock(spec=ProjectRegistry)
        self.registry.list.side_effect = lambda: list(self.projects)
        self.registry.checkout.side_effect = lambda cid: self.bindings[cid]
        self.runtime = mock.Mock()
        self.runtime.discover.side_effect = self._discover
        self.runtime.ensure.side_effect = lambda binding: _info()
        self.resolve = mock.Mock(return_value=_info())
        self.manager = mock.MagicMock(spec=SessionManager)
        self.manager.reconcile.side_effect = lambda cid: [
            s for s in self.store.list() if s.checkout_id == cid]
        self.manager_for = mock.Mock(return_value=self.manager)
        self.checkouts = mock.MagicMock(spec=CheckoutManager)
        self.checkouts.list.return_value = []
        self.checkouts.merged.return_value = False
        self.checkouts.sandbox_absent.return_value = False
        self.checkouts.lost_sessions.return_value = ()
        self.checkouts.default_path.side_effect = (
            lambda project, branch:
            project.worktree_root / branch.replace("/", "-"))
        self.branch_reads: list[Path] = []
        self.events: list = []
        self.child_error: BaseException | None = None

    def _discover(self, project):
        value = self.discovered[project.id]
        if isinstance(value, BaseException):
            raise value
        return list(value)

    def read_branch(self, path: Path):
        self.branch_reads.append(path)
        return BranchInfo(name=f"br-{path.name}", detached=False)

    def run_child(self, argv):
        self.events.append(("child", tuple(argv)))
        if self.child_error is not None:
            raise self.child_error
        return 0

    def services(self) -> sessions.SessionServices:
        return sessions.SessionServices(
            registry=self.registry, store=self.store, runtime=self.runtime,
            resolve=self.resolve, manager_for=self.manager_for)

    def controller(self, refresh=True) -> tui.TuiController:
        ctl = tui.TuiController(self.services(), read_branch=self.read_branch,
                                run_child=self.run_child,
                                checkouts=self.checkouts)
        ctl.terminal = FakeTerminal(self.events)
        if refresh:
            ctl.refresh()
        return ctl

    def stored(self, checkout=C_PRI, state=SessionState.RUNNING,
               title="codex session") -> AgentSession:
        record = self.store.insert(AgentSession.new(
            checkout, AgentKind.CODEX, SANDBOX_ROOT, title))
        return self.store.replace(record.with_state(
            state, terminal_id=TerminalId(f"asb-{record.id}")))

    def select(self, ctl: tui.TuiController, key: str) -> None:
        keys = [row.key for row in ctl.rows]
        ctl.move(keys.index(key) - ctl.selected)
        self.assertEqual(ctl.selected_row.key, key)


# -- refresh ---------------------------------------------------------------------


class TestRefresh(_Case):
    def test_branch_comes_from_the_sandbox_checkout_when_ready(self):
        ctl = self.controller()
        self.assertEqual(self.branch_reads, [SANDBOX_ROOT, WORKTREE])
        rows = {row.key: row for row in ctl.rows}
        self.assertIn(f"br-{SANDBOX_ROOT.name}", rows["c:c-pri"].text)
        self.assertNotIn("(host)", rows["c:c-pri"].text)
        self.assertIn("br-topic (host)", rows["c:c-wt"].text)
        self.assertIn("[primary]", rows["c:c-pri"].text)
        self.assertIn("[worktree]", rows["c:c-wt"].text)

    def test_a_primary_reached_through_a_symlink_is_still_primary(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        real = Path(tmp.name).resolve() / "alpha"
        real.mkdir()
        link = Path(tmp.name).resolve() / "alpha-link"
        link.symlink_to(real)
        self.projects[0] = replace(self.projects[0], primary=link)
        self.bindings[C_PRI] = CheckoutBinding(C_PRI, PROJECT, real, "ws-pri")
        self.discovered[PROJECT] = [WorkspaceDiscovery(
            self.bindings[C_PRI], WorkspaceStatus.ABSENT)]
        ctl = self.controller()
        rows = {row.key: row for row in ctl.rows}
        self.assertIn("[primary]", rows["c:c-pri"].text)

    def test_reconciles_only_ready_checkouts_that_have_sessions(self):
        pri = self.stored(C_PRI)
        self.stored(C_WT)
        reconciled = pri.with_state(SessionState.DETACHED)
        self.manager.reconcile.side_effect = lambda cid: [reconciled]
        ctl = self.controller()
        self.manager_for.assert_called_once_with(_info())
        self.manager.reconcile.assert_called_once_with(C_PRI)
        row = next(r for r in ctl.rows if r.session_id == pri.id)
        self.assertEqual(row.session_state, SessionState.DETACHED)

    def test_a_ready_checkout_without_sessions_builds_no_manager(self):
        self.controller()
        self.manager_for.assert_not_called()

    def test_one_failing_project_or_checkout_does_not_hide_the_rest(self):
        self.projects.append(Project(id=OTHER_PROJECT, primary=Path("/src/b"),
                                     integration_branch="main",
                                     worktree_root=Path("/src/b-wts")))
        self.discovered[OTHER_PROJECT] = PodmanError("podman\nausente")
        self.stored(C_PRI)
        self.manager.reconcile.side_effect = RuntimeError("ssh caiu")
        ctl = self.controller()
        rows = {row.key: row for row in ctl.rows}
        # So a primeira linha do erro, sem o newline cru.
        self.assertTrue(rows["p:p-beta"].text.endswith("!! podman"))
        self.assertIn("!! ssh caiu", rows["c:c-pri"].text)
        self.assertIn("c:c-wt", rows)
        # A sessao continua visivel com o estado do store.
        self.assertTrue(any(r.kind is RowKind.SESSION for r in ctl.rows))

    def test_a_registry_failure_leaves_an_empty_tree_and_a_message(self):
        self.registry.list.side_effect = PodmanError("registro corrompido")
        ctl = self.controller()
        self.assertEqual(ctl.rows, ())
        self.assertIn("registro corrompido", ctl.message)

    def test_selection_follows_its_key_across_a_refresh(self):
        later = self.stored(C_PRI, title="zzz")
        ctl = self.controller()
        self.select(ctl, f"s:{later.id}")
        self.stored(C_PRI, title="aaa")  # entra ACIMA da selecionada
        ctl.refresh()
        self.assertEqual(ctl.selected_row.key, f"s:{later.id}")

    def test_a_vanished_selection_falls_back_to_its_checkout(self):
        record = self.stored(C_PRI)
        ctl = self.controller()
        self.select(ctl, f"s:{record.id}")
        self.store.remove(record.id)
        ctl.refresh()
        self.assertEqual(ctl.selected_row.key, "c:c-pri")


# -- navegacao ---------------------------------------------------------------------


class TestNavigation(_Case):
    def test_move_is_clamped_and_skips_notes(self):
        self.projects.append(Project(id=OTHER_PROJECT, primary=Path("/src/b"),
                                     integration_branch="main",
                                     worktree_root=Path("/src/b-wts")))
        self.discovered[OTHER_PROJECT] = []
        ctl = self.controller()
        ctl.move(-5)
        self.assertEqual(ctl.selected_row.key, "p:p-alpha")
        ctl.move(99)
        self.assertEqual(ctl.selected_row.key, "p:p-beta")

    def test_enter_toggles_projects_and_checkouts(self):
        self.stored(C_PRI)
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        ctl.activate()
        self.assertFalse(any(r.kind is RowKind.SESSION for r in ctl.rows))
        self.assertEqual(ctl.selected_row.key, "c:c-pri")
        self.select(ctl, "p:p-alpha")
        ctl.activate()
        self.assertEqual([r.key for r in ctl.rows], ["p:p-alpha"])
        ctl.activate()
        self.assertIn("c:c-wt", [r.key for r in ctl.rows])


# -- attach ----------------------------------------------------------------------


class TestAttach(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.record = self.stored(C_PRI)
        self.manager.attach.side_effect = lambda sid: AttachResult(
            self.store.get(sid), ATTACH_ARGV)

    def test_enter_on_a_session_attaches_once_as_a_child(self):
        ctl = self.controller()
        self.select(ctl, f"s:{self.record.id}")
        self.manager.reconcile.reset_mock()
        ctl.activate()
        self.manager.attach.assert_called_once_with(self.record.id)
        self.assertEqual(self.events,
                         ["suspend", ("child", ATTACH_ARGV), "restore"])
        # Refresh depois que o attach volta.
        self.manager.reconcile.assert_called_once_with(C_PRI)
        self.assertTrue(ctl.running)

    def test_the_screen_is_restored_even_when_the_child_raises(self):
        self.child_error = OSError("ssh ausente")
        ctl = self.controller()
        self.select(ctl, f"s:{self.record.id}")
        ctl.activate()
        self.assertEqual(self.events,
                         ["suspend", ("child", ATTACH_ARGV), "restore"])
        self.assertIn("ssh ausente", ctl.message)

    def test_an_interrupt_in_the_child_still_restores_and_propagates(self):
        self.child_error = KeyboardInterrupt()
        ctl = self.controller()
        self.select(ctl, f"s:{self.record.id}")
        with self.assertRaises(KeyboardInterrupt):
            ctl.activate()
        self.assertEqual(self.events[-1], "restore")

    def test_the_default_child_runs_the_argv_without_a_shell(self):
        with mock.patch.object(tui.subprocess, "run",
                               return_value=subprocess.CompletedProcess(
                                   list(ATTACH_ARGV), 3)) as run:
            self.assertEqual(tui.run_child(list(ATTACH_ARGV)), 3)
        run.assert_called_once_with(list(ATTACH_ARGV), check=False)

    def test_an_exited_resumable_session_goes_to_attach(self):
        """Contexto §E: o `manager.attach` da Tarefa 8 retoma nativamente
        um `exited_resumable`; a TUI nao o barra."""
        record = self.stored(C_WT, state=SessionState.EXITED_RESUMABLE)
        ctl = self.controller()
        self.select(ctl, f"s:{record.id}")
        ctl.activate()
        self.manager.attach.assert_called_once_with(record.id)
        self.assertEqual(self.events,
                         ["suspend", ("child", ATTACH_ARGV), "restore"])

    def test_a_final_or_uncertain_session_shows_a_message(self):
        for state in (SessionState.RECOVERY_REQUIRED, SessionState.COMPLETED,
                      SessionState.FAILED):
            with self.subTest(state=state):
                record = self.stored(C_WT, state=state)
                ctl = self.controller()
                self.select(ctl, f"s:{record.id}")
                ctl.activate()
                self.manager.attach.assert_not_called()
                self.assertEqual(self.events, [])
                self.assertIn(str(state), ctl.message)


# -- acoes ------------------------------------------------------------------------


class TestActions(_Case):
    def test_q_quits_and_never_stops_anything(self):
        self.stored(C_PRI)
        self.manager.stop = _forbidden("stop")
        self.manager.suspend = _forbidden("suspend")
        ctl = self.controller()
        tui.handle_key(ctl, ord("q"))
        self.assertFalse(ctl.running)
        self.assertEqual(self.events, [])

    def test_n_on_a_checkout_starts_through_the_task_9_service(self):
        started = []

        def start(request: StartSession):
            started.append(request)
            return self.store.insert(AgentSession.new(
                request.checkout_id, request.agent, request.cwd,
                request.title)).with_state(SessionState.RUNNING)

        self.manager.start.side_effect = start
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        with mock.patch.object(tui, "session_start",
                               wraps=sessions.session_start) as service:
            tui.handle_key(ctl, ord("n"))
            self.assertIn("codex", ctl.prompt.text)
            self.assertIn("antigravity", ctl.prompt.text)
            tui.handle_key(ctl, ord("2"))
        service.assert_called_once()
        self.assertEqual(service.call_args.args[:3], ("c-pri", "claude", None))
        self.runtime.ensure.assert_called_once_with(self.bindings[C_PRI])
        self.assertEqual(started, [StartSession(
            checkout_id=C_PRI, agent=AgentKind.CLAUDE, cwd=SANDBOX_ROOT,
            title="claude session")])
        self.assertIsNone(ctl.prompt)
        self.assertIn("running", ctl.message)
        self.assertTrue(any(r.kind is RowKind.SESSION for r in ctl.rows))

    def test_n_can_be_cancelled_and_needs_a_checkout(self):
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        tui.handle_key(ctl, ord("n"))
        tui.handle_key(ctl, 27)
        self.assertIsNone(ctl.prompt)
        self.runtime.ensure.assert_not_called()
        self.select(ctl, "p:p-alpha")
        tui.handle_key(ctl, ord("n"))
        self.assertIsNone(ctl.prompt)
        self.assertIn("checkout", ctl.message)

    def test_a_failed_start_becomes_a_message(self):
        self.runtime.ensure.side_effect = PodmanError("up falhou")
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        tui.handle_key(ctl, ord("n"))
        tui.handle_key(ctl, ord("1"))
        self.assertIn("up falhou", ctl.message)

    def test_d_stop_requires_an_explicit_y(self):
        record = self.stored(C_PRI)
        self.manager.stop.side_effect = lambda sid: self.store.replace(
            self.store.get(sid).with_state(SessionState.COMPLETED))
        for keys, stopped in (("c", False), ("sn", False), ("s\n", False),
                              ("sy", True)):
            with self.subTest(keys=keys):
                ctl = self.controller()
                self.select(ctl, f"s:{record.id}")
                tui.handle_key(ctl, ord("d"))
                self.assertIn("stop", ctl.prompt.text)
                self.assertIn("cancel", ctl.prompt.text)
                for key in keys:
                    tui.handle_key(ctl, ord(key))
                self.assertIsNone(ctl.prompt)
                self.assertEqual(self.manager.stop.called, stopped)
        self.manager.stop.assert_called_once_with(record.id)
        self.assertEqual(self.store.get(record.id).state,
                         SessionState.COMPLETED)

    def test_r_refreshes(self):
        ctl = self.controller()
        self.runtime.discover.reset_mock()
        tui.handle_key(ctl, ord("r"))
        self.runtime.discover.assert_called_once()


# -- worktrees: listagem e `w` ------------------------------------------------------

EXTERNAL = Path("/src/alpha-worktrees/external")
DETACHED = Path("/src/alpha-worktrees/detached")
C_NEW = CheckoutId("c-new")
BASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _type(ctl: tui.TuiController, text: str) -> None:
    for ch in text:
        tui.handle_key(ctl, ord(ch))


class TestWorktreeListing(_Case):
    def test_unregistered_and_missing_worktrees_are_marked_not_hidden(self):
        self.checkouts.list.return_value = [
            ListedCheckout(PRIMARY, self.bindings[C_PRI], None, False),
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True),
            ListedCheckout(EXTERNAL, None, Worktree(
                EXTERNAL, "abc", "external", False, False), False),
            ListedCheckout(DETACHED, None, Worktree(
                DETACHED, "0123456789", None, True, False, prunable=True),
                True),
            ListedCheckout(Path("/src/bare.git"), None, Worktree(
                Path("/src/bare.git"), None, None, False, False, bare=True),
                False),
        ]
        ctl = self.controller()
        self.checkouts.list.assert_called_once_with(PROJECT)
        rows = {row.key: row for row in ctl.rows}
        self.assertNotIn("bare.git", " ".join(row.text for row in ctl.rows))
        self.assertIn("(detached 0123456)  unregistered",
                      rows[f"u:p-alpha:{DETACHED}"].text)
        self.assertTrue(rows[f"u:p-alpha:{DETACHED}"].text.endswith(
            "missing  prunable"))
        self.assertNotIn("missing", rows["c:c-pri"].text)
        self.assertIn("missing", rows["c:c-wt"].text)
        loose = rows[f"u:p-alpha:{EXTERNAL}"]
        self.assertIn("unregistered", loose.text)
        self.assertIn("external", loose.text)
        self.registry.register_checkout.assert_not_called()

    def test_a_failing_listing_marks_the_project_and_keeps_its_checkouts(self):
        self.checkouts.list.side_effect = CheckoutError("git\nquebrou")
        ctl = self.controller()
        rows = {row.key: row for row in ctl.rows}
        self.assertTrue(rows["p:p-alpha"].text.endswith("!! git"))
        self.assertIn("c:c-wt", rows)

    def test_n_on_an_unregistered_worktree_registers_it_then_starts(self):
        self.checkouts.list.return_value = [ListedCheckout(
            EXTERNAL, None,
            Worktree(EXTERNAL, "abc", "external", False, False), False)]
        binding = CheckoutBinding(C_NEW, PROJECT, EXTERNAL, "ws-new")
        self.bindings[C_NEW] = binding
        self.registry.register_checkout.return_value = binding
        self.manager.start.side_effect = lambda request: self.store.insert(
            AgentSession.new(request.checkout_id, request.agent, request.cwd,
                             request.title)).with_state(SessionState.RUNNING)
        ctl = self.controller()
        self.select(ctl, f"u:p-alpha:{EXTERNAL}")

        tui.handle_key(ctl, ord("n"))
        self.registry.register_checkout.assert_not_called()  # so na escolha
        tui.handle_key(ctl, ord("1"))

        self.registry.register_checkout.assert_called_once_with(PROJECT,
                                                                EXTERNAL)
        self.runtime.ensure.assert_called_once_with(binding)
        self.assertEqual(self.manager.start.call_args.args[0].checkout_id,
                         C_NEW)

    def test_a_refused_registration_starts_nothing(self):
        self.checkouts.list.return_value = [ListedCheckout(
            EXTERNAL, None,
            Worktree(EXTERNAL, "abc", "external", False, False), False)]
        self.registry.register_checkout.side_effect = ProjectRegistryError(
            "another repository")
        ctl = self.controller()
        self.select(ctl, f"u:p-alpha:{EXTERNAL}")
        tui.handle_key(ctl, ord("n"))
        tui.handle_key(ctl, ord("1"))
        self.assertIn("another repository", ctl.message)
        self.runtime.ensure.assert_not_called()


class TestNewWorktree(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.projects[0]
        self.checkouts.preview.side_effect = lambda request: CreatePreview(
            project=self.project, branch=request.branch, base=request.base,
            base_commit=BASE_COMMIT, path=request.path)
        self.checkouts.create.side_effect = lambda request: Checkout(
            C_NEW, PROJECT, request.path, CheckoutKind.WORKTREE,
            request.branch, CheckoutState.CLEAN, "ws-new")

    def open_confirmation(self, row="c:c-pri", base_key="1",
                          branch="feat/x") -> tui.TuiController:
        ctl = self.controller()
        self.select(ctl, row)
        tui.handle_key(ctl, ord("w"))
        self.assertIn("new branch", ctl.prompt.text)
        _type(ctl, branch + "\n")
        self.assertIn("base", ctl.prompt.text)
        tui.handle_key(ctl, ord(base_key))
        self.assertIn("path", ctl.prompt.text)
        self.assertEqual(ctl.prompt.value, "/src/wts/feat-x")
        tui.handle_key(ctl, 10)
        return ctl

    def test_the_preview_shows_everything_and_y_creates_once(self):
        ctl = self.open_confirmation()
        request = CreateCheckout(PROJECT, "feat/x", "main",
                                 Path("/src/wts/feat-x"))
        self.checkouts.preview.assert_called_once_with(request)
        detail = "\n".join(ctl.prompt.detail)
        for needle in (str(PRIMARY), "main", BASE_COMMIT[:12], "feat/x",
                       "/src/wts/feat-x", "creates branch: yes"):
            self.assertIn(needle, detail)
        self.checkouts.create.assert_not_called()
        self.runtime.discover.reset_mock()

        tui.handle_key(ctl, ord("y"))

        # Rodada 1: o create carrega o commit que o operador confirmou.
        self.checkouts.create.assert_called_once_with(
            replace(request, base_commit=BASE_COMMIT))
        self.runtime.discover.assert_called_once()  # refresh depois
        self.runtime.ensure.assert_not_called()  # runtime continua preguicoso
        self.assertIsNone(ctl.prompt)
        self.assertIn("created feat/x", ctl.message)

    def test_any_key_but_y_cancels_without_side_effects(self):
        for key in (ord("n"), ord("Y"), 10, 27, ord("q")):
            with self.subTest(key=key):
                ctl = self.open_confirmation()
                before = (list(self.registry.mock_calls),
                          list(self.runtime.mock_calls),
                          list(self.manager.mock_calls), self.store.list(),
                          ctl.rows)
                tui.handle_key(ctl, key)
                self.assertIsNone(ctl.prompt)
                self.assertEqual(ctl.message, "cancelled")
                self.assertTrue(ctl.running)
                self.assertEqual(
                    (list(self.registry.mock_calls),
                     list(self.runtime.mock_calls),
                     list(self.manager.mock_calls), self.store.list(),
                     ctl.rows), before)
        self.checkouts.create.assert_not_called()

    def test_escape_or_an_empty_answer_cancels_the_text_steps(self):
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        for keys in ([27], [10], [ord("x"), 27]):
            with self.subTest(keys=keys):
                tui.handle_key(ctl, ord("w"))
                for key in keys:
                    tui.handle_key(ctl, key)
                self.assertIsNone(ctl.prompt)
                self.assertEqual(ctl.message, "cancelled")
        self.checkouts.preview.assert_not_called()

    def test_the_path_is_editable(self):
        ctl = self.controller()
        self.select(ctl, "p:p-alpha")
        tui.handle_key(ctl, ord("w"))
        _type(ctl, "topic\n1")
        for _ in "topic":
            tui.handle_key(ctl, curses.KEY_BACKSPACE)
        tui.handle_key(ctl, 127)  # outro codigo de backspace
        tui.handle_key(ctl, curses.KEY_LEFT)  # ignorada
        _type(ctl, "/other dir")
        screen = FakeScreen(height=12, width=100)
        tui.render(screen, ctl)
        self.assertIn("path (Enter preview, Esc cancels): /src/wts/other dir_",
                      screen.lines[11])
        tui.handle_key(ctl, 10)
        self.checkouts.preview.assert_called_once_with(CreateCheckout(
            PROJECT, "topic", "main", Path("/src/wts/other dir")))

    def test_the_selected_checkout_branch_is_an_explicit_second_choice(self):
        ctl = self.open_confirmation(row="c:c-wt", base_key="2")
        self.assertEqual(self.branch_reads[-1], WORKTREE)
        self.assertEqual(self.checkouts.preview.call_args.args[0].base,
                         "br-topic")
        tui.handle_key(ctl, ord("y"))
        self.assertEqual(self.checkouts.create.call_args.args[0].base,
                         "br-topic")

    def test_a_project_row_offers_only_the_integration_branch(self):
        ctl = self.controller()
        self.select(ctl, "p:p-alpha")
        tui.handle_key(ctl, ord("w"))
        _type(ctl, "feat/x\n")
        self.assertIn("1 main", ctl.prompt.text)
        self.assertNotIn("2 ", ctl.prompt.text)
        tui.handle_key(ctl, ord("2"))
        self.assertEqual(ctl.message, "cancelled")

    def test_a_refused_preview_is_a_message_and_no_confirmation(self):
        self.checkouts.preview.side_effect = CheckoutError(
            "base 'main' does not resolve; choose a base explicitly")
        ctl = self.open_confirmation()
        self.assertIsNone(ctl.prompt)
        self.assertIn("choose a base explicitly", ctl.message)
        self.checkouts.create.assert_not_called()

    def test_a_failed_creation_shows_every_leftover(self):
        self.checkouts.create.side_effect = CheckoutError(
            "disk full; could not remove it (dirty); left worktree "
            "/src/wts/feat-x and branch feat/x for manual recovery")
        ctl = self.open_confirmation()
        tui.handle_key(ctl, ord("y"))
        self.assertIn("worktree failed", ctl.message)
        notice = "\n".join(ctl.notice)
        self.assertIn("left worktree /src/wts/feat-x and branch feat/x",
                      notice)
        screen = FakeScreen(height=12, width=100)
        tui.render(screen, ctl)
        self.assertIn("left worktree /src/wts/feat-x", screen.text())
        tui.handle_key(ctl, ord("j"))  # a proxima tecla dispensa o aviso
        self.assertEqual(ctl.notice, ())

    def test_the_default_checkout_manager_uses_the_session_services(self):
        with mock.patch.object(tui, "CheckoutManager") as manager:
            ctl = tui.TuiController(self.services())
        self.assertIs(ctl.checkouts, manager.return_value)
        [call] = manager.call_args_list
        self.assertEqual(call.args, (self.registry,))
        self.assertIs(call.kwargs["runtime"], self.runtime)
        # As sessoes do checkout vem do store; a liveness, do tmux pela
        # conexao viva, e UNKNOWN quando ela nao resolve.
        mine = self.stored(C_WT)
        self.stored(C_PRI)
        self.assertEqual(call.kwargs["sessions"](C_WT), [mine])
        liveness = call.kwargs["liveness"]
        with mock.patch.object(tui, "TmuxTerminal") as terminal:
            terminal.return_value.probe.return_value = tui.Liveness.DEAD
            self.assertIs(liveness(self.bindings[C_WT], mine),
                          tui.Liveness.DEAD)
        terminal.assert_called_once_with(_info())
        terminal.return_value.probe.assert_called_once_with(mine.terminal_id)
        # M4: depois do unbind, o registro vira `completed` no store.
        call.kwargs["complete_session"](mine)
        self.assertIs(self.store.get(mine.id).state,
                      SessionState.COMPLETED)
        self.resolve.assert_called_once_with("ws-wt")
        self.resolve.side_effect = PodmanError("container parado")
        self.assertIs(liveness(self.bindings[C_WT], mine),
                      tui.Liveness.UNKNOWN)

    def test_w_needs_a_project_or_checkout(self):
        record = self.stored(C_PRI)
        ctl = self.controller()
        self.select(ctl, f"s:{record.id}")
        tui.handle_key(ctl, ord("w"))
        self.assertIsNone(ctl.prompt)
        self.assertIn("project or checkout", ctl.message)

    def test_the_confirmation_is_drawn_above_the_status_line(self):
        ctl = self.open_confirmation()
        screen = FakeScreen(height=12, width=100)
        tui.render(screen, ctl)
        self.assertIn("creates branch: yes", screen.text())
        self.assertIn("y create", screen.lines[11])

    def test_a_short_terminal_keeps_one_tree_row_and_the_last_detail(self):
        ctl = self.open_confirmation()
        screen = FakeScreen(height=6, width=100)
        tui.render(screen, ctl)
        self.assertIn("[primary]", screen.lines[1])
        self.assertEqual([screen.lines[y] for y in (2, 3, 4)],
                         ["new branch: feat/x", "path: /src/wts/feat-x",
                          "creates branch: yes"])
        self.assertIn("y create", screen.lines[5])


# -- desenho ---------------------------------------------------------------------


SOURCE_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
SANDBOX_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"


class TestFinish(_Case):
    """`f`: alvo -> confirmacao com toggles explicitos -> so `y` roda. Os
    servicos de checkout sao falsos; so o fluxo da TUI e testado aqui."""

    def setUp(self) -> None:
        super().setUp()
        self.checkouts.finish_preview.side_effect = (
            lambda checkout_id, target, merge=True: FinishPreview(
                WORKTREE, "topic", SOURCE_COMMIT, "ws-wt", target,
                PRIMARY if merge else None,
                sandbox_branch="agent-work" if merge else None,
                sandbox_commit=SANDBOX_COMMIT if merge else None))
        self.checkouts.finish.return_value = FinishResult(
            FinishState.CLEANED, SOURCE_COMMIT, BASE_COMMIT,
            "merged refs/asb/ws-wt/topic into main; purged sandbox ws-wt")
        self.checkouts.cleanup.return_value = FinishResult(
            FinishState.CLEANED, SOURCE_COMMIT, BASE_COMMIT, "done")

    def open_confirmation(self, target="") -> tui.TuiController:
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        self.assertIn("target branch", ctl.prompt.text)
        self.assertEqual(ctl.prompt.value, "main")
        _type(ctl, target + "\n")
        return ctl

    def test_the_confirmation_shows_everything_and_both_toggles_default_no(self):
        ctl = self.open_confirmation()
        self.checkouts.finish_preview.assert_called_once_with(C_WT, "main")
        detail = "\n".join(ctl.prompt.detail)
        self.assertIn(f"merges: sandbox branch agent-work at "
                      f"{SANDBOX_COMMIT[:12]}", detail)
        for needle in (str(WORKTREE), SOURCE_COMMIT[:12], "target: main in "
                       f"{PRIMARY}", "cleanup after merge: no",
                       "delete local branch: no", "git branch -d",
                       "remote branches are never touched"):
            self.assertIn(needle, detail)
        self.checkouts.finish.assert_not_called()

    def test_y_finishes_once_with_the_chosen_toggles(self):
        ctl = self.open_confirmation()
        tui.handle_key(ctl, ord("c"))
        self.assertIn("cleanup after merge: yes", "\n".join(ctl.prompt.detail))
        tui.handle_key(ctl, ord("b"))
        self.assertIn("delete local branch: yes", "\n".join(ctl.prompt.detail))
        self.runtime.discover.reset_mock()
        tui.handle_key(ctl, ord("y"))
        self.checkouts.finish.assert_called_once_with(
            FinishCheckout(C_WT, "main", cleanup_after_merge=True,
                           delete_merged_branch=True,
                           expected_sandbox_branch="agent-work",
                           expected_sandbox_commit=SANDBOX_COMMIT))
        self.runtime.discover.assert_called_once()  # refresh depois
        self.assertEqual(ctl.message, "finish: cleaned")
        self.assertIn("purged sandbox ws-wt", ctl.notice)

    def test_the_target_branch_is_editable(self):
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        for _ in "main":
            tui.handle_key(ctl, 127)
        _type(ctl, "release\n")
        self.checkouts.finish_preview.assert_called_once_with(C_WT, "release")

    def test_any_other_key_or_an_empty_target_cancels(self):
        ctl = self.open_confirmation()
        tui.handle_key(ctl, ord("n"))
        self.assertEqual(ctl.message, "cancelled")
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        for _ in "main":
            tui.handle_key(ctl, 127)
        tui.handle_key(ctl, 10)
        self.assertEqual(ctl.message, "cancelled")
        self.checkouts.finish.assert_not_called()

    def test_a_refused_preview_is_a_message(self):
        self.checkouts.finish_preview.side_effect = CheckoutError(
            "target checkout /src/alpha has uncommitted changes")
        ctl = self.open_confirmation()
        self.assertIsNone(ctl.prompt)
        self.assertIn("finish refused: target checkout", ctl.message)

    def test_a_finish_that_raises_is_a_message(self):
        self.checkouts.finish.side_effect = RuntimeError("boom")
        ctl = self.open_confirmation()
        tui.handle_key(ctl, ord("y"))
        self.assertEqual(ctl.message, "finish failed: boom")

    def test_f_refuses_the_primary_and_non_checkout_rows(self):
        self.stored(C_PRI)
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        tui.handle_key(ctl, ord("f"))
        self.assertIsNone(ctl.prompt)
        self.assertIn("primary checkout is never finished", ctl.message)
        self.select(ctl, f"p:{PROJECT}")
        tui.handle_key(ctl, ord("f"))
        self.assertIn("select a registered worktree", ctl.message)
        session_row = next(r for r in ctl.rows if r.kind is RowKind.SESSION)
        self.select(ctl, session_row.key)
        tui.handle_key(ctl, ord("f"))
        self.assertIn("select a registered worktree", ctl.message)
        self.checkouts.finish_preview.assert_not_called()

    def test_the_merged_label_is_fresh_and_only_for_worktrees(self):
        self.checkouts.merged.return_value = True
        ctl = self.controller()
        rows = {row.key: row for row in ctl.rows}
        self.assertIn("merged / cleanup available", rows["c:c-wt"].text)
        self.assertNotIn("merged", rows["c:c-pri"].text)
        self.checkouts.merged.assert_called_once_with(C_WT, "main")
        ctl.refresh()
        self.assertEqual(self.checkouts.merged.call_count, 2)

    def test_a_missing_worktree_with_proof_is_labelled_cleanup_pending(self):
        self.checkouts.list.return_value = [
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True)]
        self.checkouts.merged.return_value = True
        ctl = self.controller()
        self.checkouts.merged.assert_called_once_with(C_WT, "main")
        rows = {row.key: row for row in ctl.rows}
        self.assertIn("merged / cleanup pending", rows["c:c-wt"].text)
        self.assertNotIn("cleanup available", rows["c:c-wt"].text)

    def test_f_on_a_missing_row_offers_cleanup_even_without_the_label(self):
        self.checkouts.list.return_value = [
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True)]
        self.checkouts.cleanup.return_value = FinishResult(
            FinishState.BLOCKED, None, None, "no export ref; manual recovery")
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        self.checkouts.finish_preview.assert_not_called()
        detail = "\n".join(ctl.prompt.detail)
        for needle in (str(WORKTREE), "missing", "ws-wt", "main",
                       "remote branches are never touched"):
            self.assertIn(needle, detail)
        tui.handle_key(ctl, ord("y"))
        self.checkouts.cleanup.assert_called_once_with(C_WT, "main", False)
        self.checkouts.finish.assert_not_called()
        self.assertEqual(ctl.message, "cleanup: blocked")
        self.assertIn("manual recovery", ctl.notice)

    def test_unlistable_lost_sessions_refuse_the_missing_row_cleanup(self):
        self.checkouts.list.return_value = [
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True)]
        self.checkouts.lost_sessions.side_effect = CheckoutError(
            "session store\nunreadable")
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        self.assertIsNone(ctl.prompt)
        self.assertEqual(ctl.message, "cleanup refused: session store")
        self.checkouts.cleanup.assert_not_called()

    def test_any_other_key_cancels_the_missing_row_cleanup(self):
        self.checkouts.list.return_value = [
            ListedCheckout(WORKTREE, self.bindings[C_WT], None, True)]
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        tui.handle_key(ctl, ord("n"))
        self.assertEqual(ctl.message, "cancelled")
        self.checkouts.cleanup.assert_not_called()

    def test_f_on_a_merged_row_offers_cleanup_directly(self):
        self.checkouts.merged.return_value = True
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        self.checkouts.finish_preview.assert_called_once_with(
            C_WT, "main", merge=False)
        detail = "\n".join(ctl.prompt.detail)
        for needle in (SOURCE_COMMIT[:12], "integrated into: main",
                       "purges sandbox ws-wt", "delete local branch: no",
                       "remote branches are never touched"):
            self.assertIn(needle, detail)
        tui.handle_key(ctl, ord("b"))
        self.assertIn("delete local branch: yes",
                      "\n".join(ctl.prompt.detail))
        tui.handle_key(ctl, ord("y"))
        self.checkouts.cleanup.assert_called_once_with(C_WT, "main", True)
        self.checkouts.finish.assert_not_called()
        self.assertEqual(ctl.message, "cleanup: cleaned")

    def test_a_refused_cleanup_preview_is_a_message(self):
        self.checkouts.merged.return_value = True
        self.checkouts.finish_preview.side_effect = CheckoutError("dirty")
        ctl = self.controller()
        self.select(ctl, "c:c-wt")
        tui.handle_key(ctl, ord("f"))
        self.assertIsNone(ctl.prompt)
        self.assertEqual(ctl.message, "cleanup refused: dirty")
        self.checkouts.cleanup.assert_not_called()


class TestRender(_Case):
    def test_drawing_calls_no_service(self):
        ctl = self.controller()
        self.runtime.reset_mock()
        self.registry.reset_mock()
        self.branch_reads.clear()
        screen = FakeScreen()
        tui.render(screen, ctl)
        tui.render(screen, ctl)
        self.assertEqual(self.runtime.mock_calls, [])
        self.assertEqual(self.registry.mock_calls, [])
        self.assertEqual(self.branch_reads, [])
        self.assertIn("[primary]", screen.text())

    def test_every_line_is_clipped_to_the_width(self):
        self.stored(C_PRI, title="x" * 500)
        ctl = self.controller()
        screen = FakeScreen(height=10, width=50)
        tui.render(screen, ctl)
        self.assertTrue(screen.lines)
        self.assertTrue(all(len(line) < 50 for line in screen.lines.values()))

    def test_a_narrow_or_short_terminal_shows_one_bounded_message(self):
        ctl = self.controller()
        for height, width in ((24, 10), (3, 100), (1, 1)):
            with self.subTest(size=(height, width)):
                screen = FakeScreen(height=height, width=width)
                tui.render(screen, ctl)
                self.assertLessEqual(len(screen.lines), 1)
                self.assertNotIn("[primary]", screen.text())
                self.assertTrue(all(len(line) < width
                                    for line in screen.lines.values()))

    def test_curses_errors_while_writing_never_escape(self):
        ctl = self.controller()
        for size in ((24, 100), (2, 5)):
            screen = FakeScreen(*size)
            screen.always_fail = True
            tui.render(screen, ctl)

    def test_a_hostile_title_is_drawn_without_control_characters(self):
        self.stored(C_PRI, title="evil\n\x1b[2Jtitle")
        ctl = self.controller()
        ctl.message = "msg\x1b[31m"
        screen = FakeScreen()
        tui.render(screen, ctl)
        drawn = "".join(screen.lines.values())
        self.assertIn("evil??[2Jtitle", drawn)
        self.assertFalse(any(ord(ch) < 32 or 127 <= ord(ch) < 160
                             for ch in drawn))

    def test_the_prompt_is_drawn_on_the_status_line(self):
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        tui.handle_key(ctl, ord("n"))
        screen = FakeScreen(height=12)
        tui.render(screen, ctl)
        self.assertIn("antigravity", screen.lines[11])

    def test_the_selection_stays_visible_in_a_short_window(self):
        for n in range(10):
            self.stored(C_PRI, title=f"t{n:02d}")
        ctl = self.controller()
        ctl.move(99)
        screen = FakeScreen(height=8, width=80)
        tui.render(screen, ctl)
        self.assertIn("[worktree]", screen.text())


class TestRunLoop(_Case):
    def test_resize_redraws_with_the_new_size_and_q_exits(self):
        def on_key(screen, key):
            if key == curses.KEY_RESIZE:
                screen.height, screen.width = 12, 60

        ctl = self.controller(refresh=False)
        screen = FakeScreen(24, 100, keys=[curses.KEY_RESIZE, ord("q")],
                            on_key=on_key)
        tui.run(screen, ctl)
        self.assertFalse(ctl.running)
        self.assertIn((12, 60), screen.renders)
        self.assertEqual(screen.renders[0], (24, 100))
        self.runtime.discover.assert_called()  # refresh inicial

    def test_a_resize_keeps_an_open_prompt(self):
        ctl = self.controller()
        self.select(ctl, "c:c-pri")
        tui.handle_key(ctl, ord("n"))
        prompt = ctl.prompt
        tui.handle_key(ctl, curses.KEY_RESIZE)
        self.assertIs(ctl.prompt, prompt)
        self.assertNotIn("cancelled", ctl.message)

    def test_run_tui_refuses_without_a_terminal(self):
        err = mock.Mock()
        with mock.patch.object(tui.sys, "stdin") as stdin, \
                mock.patch.object(tui.curses, "wrapper",
                                  _forbidden("wrapper")):
            stdin.isatty.return_value = False
            self.assertEqual(tui.run_tui(self.services(), err=err), 2)

    def test_run_tui_hands_setup_and_teardown_to_curses_wrapper(self):
        with mock.patch.object(tui.sys, "stdin") as stdin, \
                mock.patch.object(tui.sys, "stdout") as stdout, \
                mock.patch.object(tui.curses, "wrapper") as wrapper:
            stdin.isatty.return_value = True
            stdout.isatty.return_value = True
            self.assertEqual(tui.run_tui(self.services()), 0)
        wrapper.assert_called_once()
        self.assertIs(wrapper.call_args.args[0], tui.run)
        self.assertIsInstance(wrapper.call_args.args[1], tui.TuiController)


class TestReadBranch(unittest.TestCase):
    """O argv e as falhas moraram em `test_checkout_git.py` (§C); aqui so
    a delegacao do default do controlador."""

    def test_the_default_reads_through_the_git_repository(self):
        info = BranchInfo("main", False)
        with mock.patch.object(tui.GitRepository, "branch",
                               autospec=True, return_value=info) as branch:
            self.assertEqual(tui.read_branch(Path("/r")), info)
        [call] = branch.call_args_list
        self.assertEqual(call.args[0].path, Path("/r"))


class TestCursesTerminal(unittest.TestCase):
    def test_suspend_and_restore_use_prog_mode(self):
        screen = FakeScreen()
        drawn = []
        term = tui.CursesTerminal(screen, lambda: drawn.append(True))
        with mock.patch.object(tui.curses, "def_prog_mode") as dpm, \
                mock.patch.object(tui.curses, "endwin") as endwin, \
                mock.patch.object(tui.curses, "reset_prog_mode") as rpm:
            term.suspend()
            dpm.assert_called_once_with()
            endwin.assert_called_once_with()
            rpm.assert_not_called()
            term.restore()
            rpm.assert_called_once_with()
        term.redraw()
        self.assertEqual(drawn, [True])


if __name__ == "__main__":
    unittest.main()
