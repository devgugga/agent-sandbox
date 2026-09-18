"""Testes do CLI de sessoes persistentes (Tarefa 9): `asb-agent project add`
e `asb-agent session list|start|attach|stop|resume`.

Nenhum Podman, SSH, tmux ou provedor real: o registro e o store sao REAIS em
diretorios temporarios; o runtime, a resolucao de conexao e o gerente vem de
um `SessionServices` montado pelo teste. Onde o argv de anexacao importa, um
`SessionManager` e um `TmuxTerminal` reais rodam sobre um `run` falso.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.agents.base import AgentAvailability, ResumeUnsupported  # noqa: E402
from asb.agents.claude import ClaudeDriver  # noqa: E402
from asb.agents.codex import CodexDriver  # noqa: E402
from asb.agents.antigravity import AntigravityDriver  # noqa: E402
from asb.checkouts.model import CheckoutId  # noqa: E402
from asb.interfaces import sessions  # noqa: E402
from asb.podman import PodmanError  # noqa: E402
from asb.projects.model import ProjectId  # noqa: E402
from asb.projects.registry import (  # noqa: E402
    CheckoutBinding, ProjectRegistry, ProjectRegistryError,
)
from asb.runtime.connection import ConnectionInfo  # noqa: E402
from asb.sessions.manager import (  # noqa: E402
    AttachResult, ResumeResult, SessionManager, SessionManagerError,
    StartSession,
)
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, SessionId, SessionState, TerminalId,
)
from asb.sessions.store import SessionStore, SessionStoreError  # noqa: E402
from asb.sessions.terminal import TmuxTerminal  # noqa: E402

CLI_PATH = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"

PROJECT = ProjectId("p-" + "a" * 16)
CHECKOUT = CheckoutId("c-0001")
OTHER_CHECKOUT = CheckoutId("c-0002")
SOURCE = Path("/home/op/repo")
SANDBOX_ROOT = Path("/home/op/asb-agent/repo/ws-1/repo")


def _load_cli_module():
    loader = importlib.machinery.SourceFileLoader(
        "asb_agent_cli_sessions", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _info(**overrides) -> ConnectionInfo:
    fields = {
        "workspace": "ws-1", "host": "127.0.0.1", "port": 2222,
        "username": "v", "identity_file": Path("/keys/id_ed25519"),
        "project_root": SANDBOX_ROOT,
    }
    fields.update(overrides)
    return ConnectionInfo(**fields)


def _binding(checkout=CHECKOUT, workspace="ws-1") -> CheckoutBinding:
    return CheckoutBinding(checkout_id=checkout, project_id=PROJECT,
                           source_path=SOURCE, workspace=workspace)


def _forbidden(name):
    return mock.Mock(side_effect=AssertionError(f"{name} nao deveria rodar"))


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = SessionStore(self.tmp / "state" / "sessions.json")
        self.registry = mock.MagicMock(spec=ProjectRegistry)
        self.registry.checkout.side_effect = self._lookup
        self.bindings = {CHECKOUT: _binding()}
        self.runtime = mock.Mock()
        self.resolve = mock.Mock(return_value=_info())
        self.manager = mock.MagicMock(spec=SessionManager)
        self.manager_for = mock.Mock(return_value=self.manager)
        self.out = io.StringIO()
        self.err = io.StringIO()

    def _lookup(self, checkout_id):
        try:
            return self.bindings[checkout_id]
        except KeyError:
            raise ProjectRegistryError(f"unknown checkout id: {checkout_id}")

    def services(self, **overrides) -> sessions.SessionServices:
        fields = dict(registry=self.registry, store=self.store,
                      runtime=self.runtime, resolve=self.resolve,
                      manager_for=self.manager_for)
        fields.update(overrides)
        return sessions.SessionServices(**fields)

    def stored(self, checkout=CHECKOUT, state=SessionState.RUNNING,
               agent=AgentKind.CODEX, title="codex session") -> AgentSession:
        record = self.store.insert(
            AgentSession.new(checkout, agent, SANDBOX_ROOT, title))
        return self.store.replace(record.with_state(
            state, terminal_id=TerminalId(f"asb-{record.id}")))


# -- parser ---------------------------------------------------------------


def _nested_choices(parser: argparse.ArgumentParser, command: str):
    top = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    sub = top.choices[command]
    nested = next(a for a in sub._actions
                  if isinstance(a, argparse._SubParsersAction))
    return nested.dest, set(nested.choices)


class TestSessionParser(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_cli_module()
        self.parser = self.module.build_parser()

    def _reject(self, argv) -> str:
        stderr = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(stderr):
            self.parser.parse_args(argv)
        return stderr.getvalue()

    def test_session_and_project_register_exactly_the_nested_commands(self):
        self.assertEqual(_nested_choices(self.parser, "session"),
                         ("session_command",
                          {"list", "start", "attach", "stop", "resume"}))
        self.assertEqual(_nested_choices(self.parser, "project"),
                         ("project_command", {"add"}))

    def test_agent_choices_are_exactly_the_three_session_agents(self):
        args = self.parser.parse_args(
            ["session", "start", "--checkout", "c-1", "--agent", "claude"])
        self.assertEqual(args.agent, "claude")
        for bad in ("agy", "all", "gpt", "CODEX"):
            with self.subTest(agent=bad):
                message = self._reject(["session", "start", "--checkout",
                                        "c-1", "--agent", bad])
                self.assertIn("invalid choice", message)
                self.assertIn("'codex', 'claude', 'antigravity'", message)

    def test_start_requires_checkout_and_agent(self):
        self.assertIn("--agent", self._reject(
            ["session", "start", "--checkout", "c-1"]))
        self.assertIn("--checkout", self._reject(
            ["session", "start", "--agent", "codex"]))

    def test_start_title_is_optional(self):
        args = self.parser.parse_args(
            ["session", "start", "--checkout", "c-1", "--agent", "codex"])
        self.assertIsNone(args.title)

    def test_attach_stop_resume_take_one_session_id(self):
        for command in ("attach", "stop", "resume"):
            with self.subTest(command=command):
                args = self.parser.parse_args(["session", command, "s-1"])
                self.assertEqual(args.session_id, "s-1")
                self.assertIn("session_id", self._reject(["session", command]))

    def test_list_flags(self):
        args = self.parser.parse_args(["session", "list"])
        self.assertIsNone(args.checkout)
        self.assertFalse(args.as_json)
        args = self.parser.parse_args(
            ["session", "list", "--checkout", "c-1", "--json"])
        self.assertEqual(args.checkout, "c-1")
        self.assertTrue(args.as_json)

    def test_project_add_flags(self):
        args = self.parser.parse_args(["project", "add", "--repo", "/r"])
        self.assertEqual((args.repo, args.integration_branch,
                          args.worktree_root), ("/r", None, None))
        self.assertIn("--repo", self._reject(["project", "add"]))


# -- despacho -------------------------------------------------------------


class TestSessionDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_cli_module()
        self.services = object()

    def _run(self, argv, **handlers):
        stderr = io.StringIO()
        with mock.patch.object(self.module.sys, "argv", ["asb-agent", *argv]), \
                mock.patch.object(self.module.sys, "stderr", stderr), \
                mock.patch.object(self.module.session_cli, "session_services",
                                  return_value=self.services) as factory, \
                mock.patch.multiple(self.module.session_cli, **handlers):
            code = self.module.main()
        return code, stderr.getvalue(), factory

    def test_each_nested_command_reaches_its_handler(self):
        cases = [
            (["session", "list", "--checkout", "c-1", "--json"],
             "session_list", (("c-1",), {"as_json": True})),
            (["session", "start", "--checkout", "c-1", "--agent", "codex",
              "--title", "t"],
             "session_start", (("c-1", "codex", "t"), {})),
            (["session", "attach", "s-1"], "session_attach", (("s-1",), {})),
            (["session", "stop", "s-1"], "session_stop", (("s-1",), {})),
            (["session", "resume", "s-1"], "session_resume", (("s-1",), {})),
            (["project", "add", "--repo", "/r", "--integration-branch", "main",
              "--worktree-root", "/w"],
             "project_add", (("/r", "main", "/w"), {})),
        ]
        for argv, name, (args, kwargs) in cases:
            with self.subTest(command=argv[:2]):
                handler = mock.Mock(return_value=0)
                code, _, factory = self._run(argv, **{name: handler})
                self.assertEqual(code, 0)
                handler.assert_called_once_with(
                    *args, services=self.services, **kwargs)
                factory.assert_called_once_with(self.module.ROOT)

    def test_session_errors_print_one_line_and_exit_two(self):
        errors = [
            ProjectRegistryError("unknown checkout id: c-9"),
            SessionStoreError("unknown session id: s-9"),
            SessionManagerError("terminal asb-s-9 nao confirmou"),
            ResumeUnsupported("codex: resume nao confirmado"),
            PodmanError("workspace inexistente: ws-1 (use 'up')"),
            ValueError("invalid session id: 'X'"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                code, stderr, _ = self._run(
                    ["session", "stop", "s-9"],
                    session_stop=mock.Mock(side_effect=error))
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"asb-agent: {error}\n")


# -- session list -----------------------------------------------------------

STORED_KEYS = sorted(["id", "checkoutId", "agent", "title", "cwd",
                      "terminalId", "providerSessionId", "state",
                      "lastHealthyAt", "revision"])


class TestSessionList(_Case):
    def offline(self) -> sessions.SessionServices:
        """`list` nao pode tocar workspace nenhum."""
        return self.services(runtime=_forbidden("runtime"),
                             resolve=_forbidden("resolve_connection"),
                             manager_for=_forbidden("manager_for"))

    def test_json_is_schema_one_with_exactly_the_stored_fields(self):
        first = self.stored()
        second = self.stored(checkout=OTHER_CHECKOUT,
                             state=SessionState.COMPLETED,
                             agent=AgentKind.CLAUDE, title="review")

        code = sessions.session_list(None, as_json=True,
                                     services=self.offline(), out=self.out)

        self.assertEqual(code, 0)
        self.assertEqual(self.out.getvalue().count("\n"), 1)
        payload = json.loads(self.out.getvalue())
        self.assertEqual(sorted(payload), ["schemaVersion", "sessions"])
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual([s["id"] for s in payload["sessions"]],
                         [first.id, second.id])
        for entry in payload["sessions"]:
            self.assertEqual(sorted(entry), STORED_KEYS)
        # Os mesmos valores que o store guarda em disco, nada alem.
        on_disk = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["sessions"], on_disk["sessions"])
        self.runtime.assert_not_called()

    def test_json_filters_by_checkout(self):
        self.stored()
        other = self.stored(checkout=OTHER_CHECKOUT)

        sessions.session_list(str(OTHER_CHECKOUT), as_json=True,
                              services=self.offline(), out=self.out)

        payload = json.loads(self.out.getvalue())
        self.assertEqual([s["id"] for s in payload["sessions"]], [other.id])
        self.assertEqual(payload["sessions"][0]["checkoutId"],
                         str(OTHER_CHECKOUT))

    def test_text_shows_the_checkout_and_only_relationship_fields(self):
        record = self.stored(title="fix login")

        code = sessions.session_list(None, as_json=False,
                                     services=self.offline(), out=self.out)

        self.assertEqual(code, 0)
        self.assertEqual(self.out.getvalue(),
                         f"{record.id}  c-0001  codex  running  fix login\n")

    def test_text_with_no_sessions(self):
        sessions.session_list(None, as_json=False, services=self.offline(),
                              out=self.out)
        self.assertEqual(self.out.getvalue(), "nenhuma sessao\n")

    def test_json_with_no_store_file_is_an_empty_list(self):
        sessions.session_list(None, as_json=True, services=self.offline(),
                              out=self.out)
        self.assertEqual(json.loads(self.out.getvalue()),
                         {"schemaVersion": 1, "sessions": []})
        self.assertFalse(self.store.path.exists())

    def test_invalid_checkout_filter_is_refused(self):
        with self.assertRaises(ValueError):
            sessions.session_list("../x", as_json=True,
                                  services=self.offline(), out=self.out)


# -- session start ------------------------------------------------------------


class TestSessionStart(_Case):
    def _result(self, state) -> AgentSession:
        return self.stored(state=state)

    def test_ensures_the_bound_workspace_and_starts_in_the_sandbox_checkout(self):
        live = _info(project_root=SANDBOX_ROOT)
        self.runtime.ensure.return_value = live
        started = self._result(SessionState.RUNNING)
        self.manager.start.return_value = started

        code = sessions.session_start(
            "c-0001", "codex", None,
            services=self.services(resolve=_forbidden("resolve_connection")),
            out=self.out)

        self.assertEqual(code, 0)
        self.runtime.ensure.assert_called_once_with(_binding())
        self.manager_for.assert_called_once_with(live)
        self.manager.start.assert_called_once_with(StartSession(
            checkout_id=CHECKOUT, agent=AgentKind.CODEX, cwd=SANDBOX_ROOT,
            title="codex session"))
        self.assertEqual(self.out.getvalue(), f"{started.id} running\n")

    def test_explicit_title_is_passed_through(self):
        self.runtime.ensure.return_value = _info()
        self.manager.start.return_value = self._result(SessionState.RUNNING)

        sessions.session_start("c-0001", "antigravity", "triage",
                               services=self.services(), out=self.out)

        request = self.manager.start.call_args.args[0]
        self.assertEqual((request.agent, request.title),
                         (AgentKind.ANTIGRAVITY, "triage"))

    def test_an_unconfirmed_start_prints_its_state_and_exits_two(self):
        self.runtime.ensure.return_value = _info()
        for state in (SessionState.FAILED, SessionState.RECOVERY_REQUIRED):
            with self.subTest(state=state):
                self.out = io.StringIO()
                failed = self._result(state)
                self.manager.start.return_value = failed
                code = sessions.session_start("c-0001", "codex", None,
                                              services=self.services(),
                                              out=self.out)
                self.assertEqual(code, 2)
                self.assertEqual(self.out.getvalue(),
                                 f"{failed.id} {state}\n")

    def test_unknown_checkout_never_ensures(self):
        with self.assertRaises(ProjectRegistryError):
            sessions.session_start("c-0404", "codex", None,
                                   services=self.services(), out=self.out)
        self.runtime.ensure.assert_not_called()

    def test_invalid_checkout_id_never_reaches_the_registry(self):
        with self.assertRaises(ValueError):
            sessions.session_start("C 1", "codex", None,
                                   services=self.services(), out=self.out)
        self.registry.checkout.assert_not_called()


# -- session attach -------------------------------------------------------------


class _AliveRun:
    """`run` falso do `TmuxTerminal`: todo pane esta vivo."""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        # `list-panes -a -f <tag ou nome>`: uma sessao, $5, pane vivo.
        return subprocess.CompletedProcess(argv, 0, stdout="$5 0 \n",
                                           stderr="")


class TestSessionAttach(_Case):
    def test_replaces_the_process_with_ssh_attaching_to_exactly_one_terminal(self):
        record = self.stored(state=SessionState.RUNNING)
        info = _info()
        run = _AliveRun()
        manager = SessionManager(store=self.store,
                                 terminal=TmuxTerminal(info, run=run),
                                 drivers={}, remote_run=_forbidden("remote_run"))
        executed = []

        code = sessions.session_attach(
            str(record.id),
            services=self.services(manager_for=mock.Mock(return_value=manager),
                                   runtime=_forbidden("runtime")),
            execute=lambda file, argv: executed.append((file, argv)),
            err=self.err)

        self.assertEqual(code, 0)
        self.resolve.assert_called_once_with("ws-1")
        self.assertEqual(len(executed), 1)
        file, argv = executed[0]
        self.assertEqual(file, "ssh")
        self.assertEqual(argv[:-1], info.ssh_argv())
        # Um unico alvo, exato: o id tmux ($5) da sessao que carrega a tag,
        # escrito a mao e nao recomputado com shlex.
        self.assertEqual(argv[-1], "tmux attach-session -t '$5'")
        self.assertEqual(self.store.get(record.id).state,
                         SessionState.DETACHED)

    def test_final_or_uncertain_sessions_are_refused_without_launching(self):
        for state in (SessionState.RECOVERY_REQUIRED, SessionState.COMPLETED,
                      SessionState.FAILED):
            with self.subTest(state=state):
                self.err = io.StringIO()
                record = self.stored(state=state)
                code = sessions.session_attach(
                    str(record.id),
                    services=self.services(
                        resolve=_forbidden("resolve_connection"),
                        manager_for=_forbidden("manager_for")),
                    execute=_forbidden("execute"), err=self.err)
                self.assertEqual(code, 2)
                self.assertEqual(
                    self.err.getvalue(),
                    f"asb-agent: sessao {record.id} esta em {state}; "
                    "nada para anexar\n")

    def test_no_terminal_to_attach_after_recovery_exits_two(self):
        record = self.stored(state=SessionState.DETACHED)
        after = record.with_state(SessionState.RECOVERY_REQUIRED)
        self.manager.attach.return_value = AttachResult(after, None)

        code = sessions.session_attach(
            str(record.id), services=self.services(),
            execute=_forbidden("execute"), err=self.err)

        self.assertEqual(code, 2)
        self.assertEqual(self.err.getvalue(),
                         f"asb-agent: sessao {record.id} esta em "
                         "recovery_required; nada para anexar\n")

    def test_exited_resumable_goes_through_manager_attach(self):
        """`manager.attach` retoma nativamente (Tarefa 8): e assim que o
        CLI honra o "resume depois de reiniciar" do spec."""
        record = self.stored(state=SessionState.EXITED_RESUMABLE)
        resumed = record.with_state(SessionState.RUNNING)
        self.manager.attach.return_value = AttachResult(
            resumed, ("ssh", "-tt", "x"))
        executed = []

        code = sessions.session_attach(
            str(record.id), services=self.services(),
            execute=lambda file, argv: executed.append((file, argv)),
            err=self.err)

        self.assertEqual(code, 0)
        self.manager.attach.assert_called_once_with(record.id)
        self.assertEqual(executed, [("ssh", ["ssh", "-tt", "x"])])

    def test_invalid_session_id_is_refused_before_any_lookup(self):
        with self.assertRaises(ValueError):
            sessions.session_attach("s-1;rm", services=self.services(),
                                    execute=_forbidden("execute"),
                                    err=self.err)
        self.resolve.assert_not_called()

    def test_a_stopped_workspace_surfaces_the_podman_error(self):
        record = self.stored()
        self.resolve.side_effect = PodmanError("workspace inexistente: ws-1")
        with self.assertRaises(PodmanError):
            sessions.session_attach(str(record.id), services=self.services(),
                                    execute=_forbidden("execute"),
                                    err=self.err)
        self.runtime.ensure.assert_not_called()


# -- session stop / resume ------------------------------------------------------


class TestSessionStopResume(_Case):
    def test_stop_uses_the_live_connection_and_prints_the_state(self):
        record = self.stored()
        self.manager.stop.return_value = record.with_state(
            SessionState.COMPLETED)

        code = sessions.session_stop(str(record.id), services=self.services(),
                                     out=self.out)

        self.assertEqual(code, 0)
        self.resolve.assert_called_once_with("ws-1")
        self.runtime.ensure.assert_not_called()
        self.manager.stop.assert_called_once_with(record.id)
        self.assertEqual(self.out.getvalue(), f"{record.id} completed\n")

    def test_resume_prints_the_state_and_exit_reflects_it(self):
        record = self.stored(state=SessionState.EXITED_RESUMABLE)
        for state, expected in ((SessionState.RUNNING, 0),
                                (SessionState.DETACHED, 0),
                                (SessionState.RECOVERY_REQUIRED, 2)):
            with self.subTest(state=state):
                self.out = io.StringIO()
                self.manager.resume.return_value = ResumeResult(
                    record.with_state(state), True)
                code = sessions.session_resume(
                    str(record.id), services=self.services(), out=self.out)
                self.assertEqual(code, expected)
                self.assertEqual(self.out.getvalue(), f"{record.id} {state}\n")
        self.runtime.ensure.assert_not_called()

    def test_session_of_an_unknown_checkout_raises_the_registry_error(self):
        record = self.stored(checkout=OTHER_CHECKOUT)
        with self.assertRaises(ProjectRegistryError):
            sessions.session_stop(str(record.id), services=self.services(),
                                  out=self.out)
        self.resolve.assert_not_called()


# -- project add ------------------------------------------------------------------


def _git(args, cwd: Path) -> None:
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null",
               GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True,
                   capture_output=True, text=True)


class TestProjectAdd(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(["init", "-q"], self.repo)
        self.real_registry = ProjectRegistry(self.tmp / "state" / "projects.json")

    def _add(self, *args):
        return sessions.project_add(
            *args, services=self.services(
                registry=self.real_registry, runtime=_forbidden("runtime"),
                resolve=_forbidden("resolve_connection"),
                manager_for=_forbidden("manager_for")),
            out=self.out)

    def test_registers_the_project_and_its_primary_checkout(self):
        code = self._add(str(self.repo), "main", None)

        self.assertEqual(code, 0)
        payload = json.loads(self.out.getvalue())
        self.assertEqual(sorted(payload), ["checkoutId", "projectId",
                                           "schemaVersion", "sourcePath",
                                           "workspace"])
        self.assertEqual(payload["schemaVersion"], 1)
        project = self.real_registry.list()[0]
        [binding] = self.real_registry.bindings(project.id)
        self.assertEqual(payload, {
            "schemaVersion": 1, "projectId": str(project.id),
            "checkoutId": str(binding.checkout_id),
            "sourcePath": str(self.repo.resolve()),
            "workspace": binding.workspace,
        })
        self.assertEqual(project.integration_branch, "main")
        self.assertEqual(project.worktree_root,
                         self.tmp.resolve() / "repo-worktrees")
        self.assertFalse((self.tmp / "repo-worktrees").exists())

    def test_explicit_worktree_root_and_idempotent_rerun(self):
        self._add(str(self.repo), "main", str(self.tmp / "wt"))
        first = json.loads(self.out.getvalue())
        self.out = io.StringIO()
        self._add(str(self.repo), "main", str(self.tmp / "wt"))
        second = json.loads(self.out.getvalue())

        self.assertEqual(first, second)
        project = self.real_registry.list()[0]
        self.assertEqual(project.worktree_root, (self.tmp / "wt").resolve())
        self.assertEqual(len(self.real_registry.bindings(project.id)), 1)

    def test_missing_branch_discovery_fails_loudly_and_registers_nothing(self):
        with self.assertRaises(ProjectRegistryError):
            self._add(str(self.repo), None, None)
        self.assertEqual(self.out.getvalue(), "")
        self.assertEqual(self.real_registry.list(), [])


# -- composicao ---------------------------------------------------------------------


class TestSessionServices(unittest.TestCase):
    def test_default_state_paths_and_no_host_access_on_construction(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch("subprocess.run", _forbidden("subprocess.run")):
            services = sessions.session_services(Path("/root-of-repo"))
            state = Path(home) / ".local" / "state" / "agent-sandbox"
            self.assertEqual(services.registry.path, state / "projects.json")
            self.assertEqual(services.store.path, state / "sessions.json")
            self.assertEqual(services.runtime.root, Path("/root-of-repo"))
            self.assertIs(services.runtime.registry, services.registry)
            self.assertFalse(state.exists())

    def test_manager_is_bound_to_one_workspace_with_its_session_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = sessions.session_services(
                Path("/r"), state_dir=Path(tmp) / "state",
                sleep=lambda _: None)
            with mock.patch.object(sessions, "session_volume_mountpoint",
                                   return_value=Path("/vol")) as mountpoint:
                manager = services.manager_for(_info(workspace="ws-9"))
            mountpoint.assert_called_once_with("ws-9")
            self.assertIsInstance(manager, SessionManager)
            self.assertIs(manager._store, services.store)

    def test_default_drivers_read_the_workspace_session_volume(self):
        with mock.patch.object(sessions, "session_volume_mountpoint",
                               return_value=Path("/vol")):
            drivers = sessions.default_drivers("ws-9")
        self.assertEqual(set(drivers), set(AgentKind))
        self.assertIsInstance(drivers[AgentKind.CODEX], CodexDriver)
        self.assertIsInstance(drivers[AgentKind.CLAUDE], ClaudeDriver)
        self.assertIsInstance(drivers[AgentKind.ANTIGRAVITY], AntigravityDriver)
        self.assertEqual(drivers[AgentKind.CODEX]._sessions_root,
                         Path("/vol/codex-sessions"))
        self.assertEqual(drivers[AgentKind.CLAUDE]._sessions_root,
                         Path("/vol/claude-projects"))
        self.assertIsNone(drivers[AgentKind.ANTIGRAVITY]._sessions_root)


class TestRemoteRun(unittest.TestCase):
    def test_runs_non_interactive_ssh_and_returns_stdout_even_on_failure(self):
        info = _info()
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 3, stdout="codex 1.2\n",
                                               stderr="boom")

        out = sessions.remote_run(info, ["codex", "--version"], timeout=5.0,
                                  run=fake_run)

        self.assertEqual(out, "codex 1.2\n")
        [(argv, kwargs)] = calls
        self.assertEqual(argv, info.ssh_argv(("codex", "--version"),
                                             interactive=False))
        self.assertEqual(kwargs, {
            "shell": False, "capture_output": True, "text": True,
            "timeout": 5.0, "check": False, "stdin": subprocess.DEVNULL})

    def test_raises_only_what_the_driver_probe_absorbs(self):
        for error in (FileNotFoundError("ssh"),
                      subprocess.TimeoutExpired("ssh", 5.0),
                      OSError("exec format error")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    sessions.remote_run(_info(), ["codex", "--help"],
                                        timeout=5.0,
                                        run=mock.Mock(side_effect=error))

    def test_a_driver_probe_through_remote_run_survives_a_timeout(self):
        """O contrato de ponta a ponta: um probe real sobre `remote_run`
        nunca aborta, so marca indisponivel."""
        run = mock.Mock(side_effect=subprocess.TimeoutExpired("ssh", 5.0))
        availability = CodexDriver().probe(
            lambda argv, timeout: sessions.remote_run(
                _info(), argv, timeout=timeout, run=run))
        self.assertIsInstance(availability, AgentAvailability)
        self.assertFalse(availability.available)


if __name__ == "__main__":
    unittest.main()
