"""tests/unit/test_uv_workspace.py — esqueleto do workspace uv (Tarefa 1).

Nome deliberadamente diferente de `test_workspace.py`: esse arquivo ja
existe e testa `cli/asb/workspace.py` (identidade, layout e clone de
checkout) — assunto sem relacao com o workspace uv da raiz do
repositorio. O brief original da Tarefa 1 pedia o teste em
`test_workspace.py`; escrever ali teria apagado a suite existente.

Cobre so o que a Tarefa 1 entrega: `import asb` funciona, `cli/asb-agent`
continua rodando sem venv (sys.path.insert, sem instalacao), e `asb` nunca
referencia `asb_server` (direcao unica de dependencia, spec Secao 5). A
asserçao de `from asb_server import app` do brief original foi movida para
a Tarefa 3 (ruling do controlador, amendment H) — `asb_server.app` nao
existe ate la.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

ROOT = Path(__file__).resolve().parents[2]
CLI_DIR = ROOT / "cli"
ASB_AGENT = CLI_DIR / "asb-agent"

sys.path.insert(0, str(CLI_DIR))


class TestImportAsb(unittest.TestCase):
    def test_import_asb_succeeds(self):
        import asb  # noqa: F401


class TestNoImportCycle(unittest.TestCase):
    """`asb` nunca importa `asb_server` nem sabe que o daemon existe."""

    def test_asb_package_never_references_asb_server(self):
        offenders = [
            str(path.relative_to(ROOT))
            for path in sorted((CLI_DIR / "asb").rglob("*.py"))
            if "asb_server" in path.read_text(encoding="utf-8")]
        self.assertEqual(
            offenders, [],
            "cli/asb nao pode referenciar asb_server (direcao unica de "
            "dependencia, spec Secao 5): " + ", ".join(offenders))

    def test_asb_agent_entrypoint_never_references_asb_server(self):
        text = ASB_AGENT.read_text(encoding="utf-8")
        self.assertNotIn("asb_server", text)

    def test_from_asb_server_import_app_works(self):
        # A outra metade da direcao: server importa asb. asb_server.app so
        # existe a partir da Tarefa 3 (ruling do controlador, amendment F);
        # por isso esta asserçao (do brief original da Tarefa 1) foi
        # movida para ca.
        from asb_server import app  # noqa: F401


class TestAsbAgentRunsWithoutVenv(unittest.TestCase):
    """cli/asb-agent roda direto do checkout: sem venv, sem PYTHONPATH."""

    def test_help_exits_zero_without_pythonpath_or_venv_on_path(self):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        # Remove qualquer .venv do PATH: simula um host sem uv/sem venv
        # ativado, que e o cenario real dos guards e do doctor.
        env["PATH"] = os.pathsep.join(
            part for part in env.get("PATH", "").split(os.pathsep)
            if ".venv" not in part)

        result = subprocess.run(
            [str(ASB_AGENT), "--help"],
            env=env, capture_output=True, text=True)

        self.assertEqual(
            result.returncode, 0,
            f"asb-agent --help falhou sem venv: {result.stderr}")
        self.assertIn("asb-agent", result.stdout)


if __name__ == "__main__":
    unittest.main()
