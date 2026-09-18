"""Testes de `asb.interfaces.cli.connect` e do subcomando `connect` do CLI
(Tarefa 4).

`connect()` e o unico lugar que troca o processo do host por `ssh`: le a
conexao viva via `resolve_connection` (nunca inicia, religa ou muda nada) e
substitui o processo atual por um shell de login no diretorio do projeto.
Cobre o argv exato passado a `execute`, a ausencia de qualquer subprocesso de
shell local, o registro do subcomando no parser e o despacho em `main()`, e
que uma falha de infraestrutura (`PodmanError`, workspace parado ou ausente)
atravessa sem disfarce e sem mutar nada.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.podman import PodmanError  # noqa: E402
from asb.runtime.connection import ConnectionInfo  # noqa: E402

CLI_PATH = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"


def _load_cli_module():
    loader = importlib.machinery.SourceFileLoader("asb_agent_cli_connect", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _info(**overrides) -> ConnectionInfo:
    fields = {
        "workspace": "ws-1", "host": "127.0.0.1", "port": 2222,
        "username": "v", "identity_file": Path("/keys/id_ed25519"),
        "project_root": Path("/sandbox/repo"),
    }
    fields.update(overrides)
    return ConnectionInfo(**fields)


class TestConnectExecvpContract(unittest.TestCase):
    """Contrato duro de `connect()`: nunca inicia um subprocesso de shell,
    so troca o processo do host pelo `ssh` local."""

    def test_execute_receives_ssh_as_file_and_the_full_local_argv(self):
        from asb.interfaces.cli import connect

        info = _info()
        calls = []
        with mock.patch("asb.interfaces.cli.resolve_connection", return_value=info):
            rc = connect("ws-1", execute=lambda file, argv: calls.append((file, argv)))

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        file, argv = calls[0]
        self.assertEqual(file, "ssh")
        # As mesmas flags locais que `ConnectionInfo.ssh_argv` ja produz,
        # sem nenhuma modificacao: nada aqui reimplementa a montagem do SSH.
        self.assertEqual(argv[:-1], info.ssh_argv())

    def test_remote_command_is_a_single_trailing_shell_string(self):
        from asb.interfaces.cli import connect

        info = _info()
        calls = []
        with mock.patch("asb.interfaces.cli.resolve_connection", return_value=info):
            connect("ws-1", execute=lambda file, argv: calls.append((file, argv)))

        remote = calls[0][1][-1]
        self.assertIn("sh -lc", remote)
        self.assertIn(
            "cd -- /sandbox/repo && exec ${SHELL:-/bin/bash} -l", remote)

    def test_only_the_remote_path_is_shell_quoted(self):
        """Um `project_root` com espaco prova que so o caminho remoto passa
        por `shlex.quote` — as flags locais do SSH nunca viram texto de
        shell."""
        from asb.interfaces.cli import connect

        info = _info(project_root=Path("/sandbox/repo with space"))
        calls = []
        with mock.patch("asb.interfaces.cli.resolve_connection", return_value=info):
            connect("ws-1", execute=lambda file, argv: calls.append((file, argv)))

        remote = calls[0][1][-1]
        self.assertIn("'/sandbox/repo with space'", remote)

    def test_never_starts_a_local_shell_subprocess(self):
        """Guarda contra regressao: `connect` nunca chama `subprocess.*` nem
        `os.system`; a unica saida e o `execute` injetado."""
        from asb.interfaces.cli import connect

        info = _info()
        with mock.patch("asb.interfaces.cli.resolve_connection", return_value=info), \
                mock.patch("subprocess.run", side_effect=AssertionError(
                    "connect nao deve rodar subprocess.run")), \
                mock.patch("os.system", side_effect=AssertionError(
                    "connect nao deve rodar os.system")):
            rc = connect("ws-1", execute=lambda file, argv: 0)
        self.assertEqual(rc, 0)

    def test_a_stopped_or_missing_workspace_raises_without_mutating_anything(self):
        """`connect` nunca engole `PodmanError`: nao ha 'up'/'resume'
        automatico escondido atras do comando."""
        from asb.interfaces.cli import connect

        with mock.patch("asb.interfaces.cli.resolve_connection",
                        side_effect=PodmanError("workspace inexistente: ws-1 (use 'up')")):
            with self.assertRaises(PodmanError):
                connect("ws-1", execute=lambda file, argv: (_ for _ in ()).throw(
                    AssertionError("execute nao deveria ser chamado")))


class TestConnectParserRegistration(unittest.TestCase):
    def setUp(self):
        self.module = _load_cli_module()

    def test_connect_is_registered_with_a_required_workspace_flag(self):
        parser = self.module.build_parser()
        args = parser.parse_args(["connect", "--workspace", "ws-1"])
        self.assertEqual(args.command, "connect")
        self.assertEqual(args.workspace, "ws-1")

    def test_connect_without_workspace_is_rejected(self):
        parser = self.module.build_parser()
        stderr = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(stderr):
            parser.parse_args(["connect"])
        # Sem isto, este teste passaria mesmo se `--workspace` nunca
        # tivesse sido exigido (por exemplo, se `connect` nem existisse no
        # parser) — o mesmo padrao de `test_up_rejects_a_runtime_option`.
        self.assertIn("--workspace", stderr.getvalue())

    def test_existing_commands_are_still_registered(self):
        """Guarda contra regressao: adicionar `connect` nao pode remover ou
        reescrever nenhum subcomando existente."""
        parser = self.module.build_parser()
        action = next(a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction))
        for name in ("up", "down", "suspend", "resume", "reload-allowlist",
                     "pull", "purge", "build", "login", "auth", "doctor",
                     "list", "install-guards", "install-broker"):
            self.assertIn(name, action.choices)


class TestConnectDispatch(unittest.TestCase):
    def setUp(self):
        self.module = _load_cli_module()

    def _run(self, argv, connect_mock):
        with mock.patch.object(self.module.sys, "argv", argv), \
                mock.patch.object(self.module.sys, "stderr", io.StringIO()), \
                mock.patch.object(self.module.cli, "connect", connect_mock):
            return self.module.main()

    def test_main_dispatches_connect_with_the_workspace_argument(self):
        connect_mock = mock.Mock(return_value=0)
        code = self._run(["asb-agent", "connect", "--workspace", "ws-1"], connect_mock)
        self.assertEqual(code, 0)
        connect_mock.assert_called_once_with("ws-1")

    def test_connect_podman_error_surfaces_as_the_existing_infrastructure_exit_code(self):
        connect_mock = mock.Mock(side_effect=PodmanError(
            "workspace inexistente: ws-1 (use 'up')"))
        code = self._run(["asb-agent", "connect", "--workspace", "ws-1"], connect_mock)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
