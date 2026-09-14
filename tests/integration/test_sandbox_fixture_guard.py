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
        created = {
            fixture.credentials_volume,
            fixture.toolcache_volume,
            fixture.keyring_runtime_volume,
            fixture.keyring_data_volume,
        }
        # O volume de sessao e registrado sem ser criado: quem o cria e
        # `lifecycle.ensure_session_volume`, na primeira subida real.
        volumes = created | {fixture.session_volume}
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

        surviving_volumes = created & _podman_names("volume")
        self.assertEqual(
            surviving_volumes, set(),
            f"volumes asb-test- vazados apos falha de setup: "
            f"{sorted(surviving_volumes)}")

        self.assertNotIn(container, _podman_names("container"))
        self.assertFalse(
            state_root.exists(),
            f"diretorio de estado temporario vazado: {state_root}")



@unittest.skipUnless(PODMAN, "podman nao encontrado no PATH")
class TestSessionVolumeTeardown(unittest.TestCase):
    """O volume de sessao e criado por `lifecycle`, nao pela fixture.

    Por nao estar registrado, o teardown nao sabia da existencia dele, e cada
    execucao de `test_workspace_supervision.py` deixava um
    `asb-test-<label>-<uid>-session` na maquina do operador. Era o unico desvio
    do criterio "zero recursos residuais `asb-test-*`" que o gate r13 apontou:
    tres volumes acumulados numa sessao.
    """

    def test_volume_created_by_lifecycle_is_removed_by_teardown(self):
        fixture = SandboxFixture("sessionvol", auto_setup=False)
        session = fixture.session_volume
        self.assertIn(session, fixture._registered_volumes)
        with fixture:
            # Exatamente o que `lifecycle.ensure_session_volume` faz na
            # primeira subida: cria o volume pelo nome canonico, fora do
            # controle da fixture.
            subprocess.run([PODMAN, "volume", "create", session],
                           check=True, capture_output=True, text=True)
            self.assertIn(session, _podman_names("volume"))
        self.assertNotIn(session, _podman_names("volume"),
                         f"volume de sessao vazado apos teardown: {session}")



if __name__ == "__main__":
    unittest.main()
