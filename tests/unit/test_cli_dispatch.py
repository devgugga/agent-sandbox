"""Unit tests for cli/asb-agent — paridade entre parser e despacho.

B#1: a Tarefa I2, ao adicionar `--json` ao `doctor`, apagou a linha
`sub.add_parser("login", ...)` de `build_parser()`. O handler
`args.command == "login"` sobreviveu orfao em `main()`, mas o argparse
rejeita o subcomando ANTES de `main()` rodar — e `lifecycle.login` e a
UNICA coisa que cria o volume `asb-credentials`, alem de ser o comando
citado por toda a remediacao de `auth status`, `doctor` e `keyring`.

Nenhum teste entrava nesse ramo. Este arquivo compara os subcomandos
REGISTRADOS no parser (introspeccao de `_SubParsersAction.choices`) com os
DESPACHADOS em `main()` (varredura AST de `args.command == "..."`), nos
dois sentidos: nenhum despacho sem registro, nenhum registro sem despacho.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import argparse
import ast
import contextlib
import io
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"


def _load_cli_module():
    """Carrega cli/asb-agent, que nao tem sufixo .py e por isso escapa do
    import normal."""
    loader = importlib.machinery.SourceFileLoader("asb_agent_cli", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _registered_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("asb-agent nao expoe subcomandos")


def _nested_subcommands(
        parser: argparse.ArgumentParser) -> dict[str, tuple[str, set[str]]]:
    """{comando de topo: (dest do subparser aninhado, nomes registrados)}."""
    nested: dict[str, tuple[str, set[str]]] = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            for inner in sub._actions:
                if isinstance(inner, argparse._SubParsersAction):
                    nested[name] = (inner.dest, set(inner.choices))
    return nested


def _dispatched_commands(source: str, attr: str = "command") -> set[str]:
    """Coleta os literais comparados contra `args.<attr>`.

    Por padrao restrito ao atributo `command`: `main()` tambem compara
    `args.auth_command == "status"`, que e um subcomando aninhado do `auth`
    e nao um comando de topo.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute)
                and left.attr == attr
                and isinstance(left.value, ast.Name)
                and left.value.id == "args"):
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant) \
                    and isinstance(comparator.value, str):
                found.add(comparator.value)
    return found


class TestCliParserDispatchParity(unittest.TestCase):
    def setUp(self):
        self.module = _load_cli_module()
        self.source = CLI_PATH.read_text(encoding="utf-8")
        self.registered = _registered_commands(self.module.build_parser())
        self.dispatched = _dispatched_commands(self.source)

    def test_scan_finds_the_dispatch_table(self):
        """Guarda do proprio teste: uma varredura que nao achasse nada
        passaria vazia nos dois assertos abaixo."""
        self.assertGreaterEqual(len(self.dispatched), 10)
        self.assertGreaterEqual(len(self.registered), 10)
        self.assertNotIn("status", self.dispatched,
                         "a varredura vazou args.auth_command")

    def test_every_dispatched_command_is_registered_in_the_parser(self):
        orphans = sorted(self.dispatched - self.registered)
        self.assertEqual(
            orphans, [],
            f"despacho sem registro no parser (argparse rejeita antes de "
            f"main() rodar): {orphans}")

    def test_every_registered_command_has_a_dispatch(self):
        unreachable = sorted(self.registered - self.dispatched)
        self.assertEqual(
            unreachable, [],
            f"subcomando registrado sem despacho em main(): {unreachable}")

    def test_connect_is_registered_and_dispatched(self):
        """Tarefa 4: `connect` e um subcomando de topo como qualquer outro
        (registrado no parser E despachado em `main()`) — a paridade acima
        ja cobre isso de forma generica, mas um assert explicito documenta
        a intencao para quem le so este arquivo."""
        self.assertIn("connect", self.registered)
        self.assertIn("connect", self.dispatched)

    def test_every_nested_command_is_registered_and_dispatched(self):
        """Tarefa 9: a mesma paridade, nos dois sentidos, para cada
        subcomando aninhado (`auth`, `project`, `session`): os nomes do
        subparser contra os literais comparados com `args.<dest>`."""
        nested = _nested_subcommands(self.module.build_parser())
        self.assertEqual(set(nested), {"auth", "project", "session"})
        for command, (dest, registered) in nested.items():
            with self.subTest(command=command):
                dispatched = _dispatched_commands(self.source, attr=dest)
                self.assertTrue(dispatched, f"nenhum despacho de {dest}")
                self.assertEqual(sorted(dispatched), sorted(registered))

    def test_session_and_project_are_registered_and_dispatched(self):
        for name in ("session", "project"):
            self.assertIn(name, self.registered)
            self.assertIn(name, self.dispatched)

    def test_tui_is_registered_and_dispatched_without_arguments(self):
        """Tarefa 10: `tui` e um comando de topo sem subcomandos nem
        argumentos; as acoes vivem nas teclas da TUI."""
        self.assertIn("tui", self.registered)
        self.assertIn("tui", self.dispatched)
        args = self.module.build_parser().parse_args(["tui"])
        self.assertEqual(vars(args), {"command": "tui"})

    def test_tui_dispatch_hands_the_session_services_to_the_tui(self):
        from unittest import mock
        services = object()
        with mock.patch.object(self.module.sys, "argv", ["asb-agent", "tui"]), \
                mock.patch.object(self.module.session_cli, "session_services",
                                  return_value=services) as build, \
                mock.patch.object(self.module.tui, "run_tui",
                                  return_value=0) as run_tui:
            self.assertEqual(self.module.main(), 0)
        build.assert_called_once_with(self.module.ROOT)
        run_tui.assert_called_once_with(services)

    def test_login_is_registered_without_a_workspace_argument(self):
        """`lifecycle.login(ROOT)` nao recebe workspace: registrar `login`
        via o helper `workspace_command` exigiria `--workspace` e quebraria
        o comando."""
        self.assertIn("login", self.registered)
        args = self.module.build_parser().parse_args(["login"])
        self.assertEqual(args.command, "login")
        self.assertFalse(hasattr(args, "workspace"))


class TestCliExitCodes(unittest.TestCase):
    """I5: `PodmanError` e INFRAESTRUTURA, e infraestrutura vale 2.

    O CLI inteiro usa 1 para "conta ausente" e 2 para "infraestrutura", com 2
    tendo precedencia (`auth status`, `login`, `doctor`). O handler mapeava
    `PodmanError` para 1, entao uma falha de podman — imagem ausente, volume
    que nao inspeciona — reportava como "conta ausente" e mandava o operador
    procurar login onde o problema era outro.
    """

    def setUp(self):
        self.module = _load_cli_module()

    def _run(self, argv, **patches):
        from unittest import mock
        with mock.patch.object(self.module.sys, "argv", argv), \
                mock.patch.object(self.module.sys, "stderr", io.StringIO()):
            with mock.patch.multiple(self.module.lifecycle, **patches):
                return self.module.main()

    def test_podman_failure_exits_with_the_infrastructure_code(self):
        from unittest import mock
        code = self._run(
            ["asb-agent", "build"],
            build=mock.Mock(side_effect=self.module.PodmanError(
                "imagem agent-sandbox:latest ausente")))
        self.assertEqual(code, 2)

    def test_profile_and_workspace_errors_still_exit_one(self):
        from unittest import mock
        for error in (self.module.ProfileError("perfil invalido"),
                      self.module.WorkspaceError("workspace desconhecido")):
            with self.subTest(error=type(error).__name__):
                code = self._run(["asb-agent", "build"],
                                 build=mock.Mock(side_effect=error))
                self.assertEqual(code, 1)

    def test_a_successful_command_still_exits_zero(self):
        """Guarda do proprio teste: um `main()` que sempre devolvesse 2
        passaria no primeiro asserto sem provar nada."""
        from unittest import mock
        code = self._run(["asb-agent", "build"], build=mock.Mock(return_value=0))
        self.assertEqual(code, 0)


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


if __name__ == "__main__":
    unittest.main()
