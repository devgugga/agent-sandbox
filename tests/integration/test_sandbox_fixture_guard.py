"""Integration test for tests/integration/sandbox_fixture.py — guarda do setup.

B#5: `SandboxFixture.setup_environment()` cria quatro volumes ANTES de
qualquer outra coisa. Se `setup_container()`, `install_unit()` ou
`setup_forwarder()` levantam depois disso, `__enter__` nunca retorna `self`
— e o protocolo de context manager do Python NAO chama `__exit__` quando o
proprio `__enter__` levanta. Volumes e containers ja criados ficavam para
tras, sem rastreio e sem caminho de limpeza. Foi assim que 8 volumes de
teste vazaram na maquina do operador.

Este teste usa podman de verdade — e a unica forma de provar que nenhum
recurso `asb-test-` sobrevive. A falha e forcada por uma imagem inexistente
com `--pull=never`: `setup_container` levanta DEPOIS de os volumes terem
sido criados e ANTES de `install_unit` tocar no systemd.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sandbox_fixture import SandboxFixture  # noqa: E402

PODMAN = shutil.which("podman")
MISSING_IMAGE = "localhost/asb-test-imagem-inexistente:none"


def _podman_names(kind: str) -> set[str]:
    res = subprocess.run(
        [PODMAN, kind, "ls", "--format", "{{.Name}}"]
        if kind == "volume"
        else [PODMAN, kind, "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in res.stdout.splitlines() if line.strip()}


@unittest.skipUnless(PODMAN, "podman nao encontrado no PATH")
class TestSandboxFixtureEnterGuard(unittest.TestCase):
    def test_enter_failure_leaves_no_asb_test_resource_behind(self):
        fixture = SandboxFixture("enterguard", image=MISSING_IMAGE)
        volumes = {
            fixture.credentials_volume,
            fixture.toolcache_volume,
            fixture.keyring_runtime_volume,
            fixture.keyring_data_volume,
        }
        container = fixture.container
        state_root = fixture.state_root
        self.assertTrue(state_root.is_dir())

        with self.assertRaises(subprocess.CalledProcessError):
            with fixture:
                self.fail("setup_container deveria ter falhado com imagem "
                          "inexistente")

        # Os volumes chegaram a existir (o defeito so tem sentido se
        # setup_environment de fato os criou antes da falha).
        self.assertEqual(fixture._registered_volumes, volumes)

        surviving_volumes = volumes & _podman_names("volume")
        self.assertEqual(
            surviving_volumes, set(),
            f"volumes asb-test- vazados apos falha de setup: "
            f"{sorted(surviving_volumes)}")

        self.assertNotIn(container, _podman_names("container"))
        self.assertFalse(
            state_root.exists(),
            f"diretorio de estado temporario vazado: {state_root}")


if __name__ == "__main__":
    unittest.main()
