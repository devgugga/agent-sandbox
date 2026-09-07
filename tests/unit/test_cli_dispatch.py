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

import argparse
import ast
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


def _dispatched_commands(source: str) -> set[str]:
    """Coleta os literais comparados contra `args.command`.

    Restrito ao atributo `command`: `main()` tambem compara
    `args.auth_command == "status"`, que e um subcomando aninhado do `auth`
    e nao um comando de topo.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute)
                and left.attr == "command"
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

    def test_login_is_registered_without_a_workspace_argument(self):
        """`lifecycle.login(ROOT)` nao recebe workspace: registrar `login`
        via o helper `workspace_command` exigiria `--workspace` e quebraria
        o comando."""
        self.assertIn("login", self.registered)
        args = self.module.build_parser().parse_args(["login"])
        self.assertEqual(args.command, "login")
        self.assertFalse(hasattr(args, "workspace"))


if __name__ == "__main__":
    unittest.main()
