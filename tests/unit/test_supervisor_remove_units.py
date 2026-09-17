"""Unit tests for supervisor.remove_workspace_units."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asb_test_isolation  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from asb import supervisor  # noqa: E402

WS = "demo"
KEYRING = "asb-test-kr"


def env_for(tmp: Path, **extra: str) -> dict[str, str]:
    """Ambiente minimo: config/drop-in e keyring sinteticos, nada do operador."""
    env = {"ASB_CONFIG_ROOT": str(tmp / "config"), "ASB_KEYRING_CONTAINER": KEYRING}
    env.update(extra)
    return env


@contextlib.contextmanager
def clean_env(env: dict[str, str]):
    """Aplica `env` e remove seams herdados que mudariam as raizes."""
    with mock.patch.dict(os.environ, env):
        for name in ("ASB_STATE_ROOT", "ASB_SYSTEMD_UNIT_DIR"):
            if name not in env:
                os.environ.pop(name, None)
        yield


class _TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class TestRemoveWorkspaceUnits(_TmpCase):
    def test_wants_link_that_cannot_be_removed_is_an_error(self) -> None:
        """R6: um symlink de wants que sobra reabilita o target no proximo boot."""
        unit_dir = self.tmp / "units"
        wants = unit_dir / "default.target.wants"
        wants.mkdir(parents=True)
        link = wants / f"asb-{WS}.target"
        link.symlink_to(unit_dir / f"asb-{WS}.target")
        # EACCES INJETADO no unlink do link, em vez de `wants.chmod(0o500)`: o
        # bit de escrita nao se aplica a root, e sob root este teste falharia por
        # ambiente. Injetar cobre o ramo em qualquer euid.
        real_unlink = os.unlink

        def unlink_eacces(path, *a, **kw):
            if os.fspath(path) == os.fspath(link):
                raise PermissionError(13, "Permission denied", str(path))
            return real_unlink(path, *a, **kw)

        done = subprocess.CompletedProcess([], 0, "", "")
        with clean_env(env_for(self.tmp)), \
                mock.patch("os.unlink", side_effect=unlink_eacces) as desligado, \
                mock.patch("subprocess.run", return_value=done) as run:
            with self.assertRaises(PermissionError):
                supervisor.remove_workspace_units(WS, target_dir=unit_dir, state_dir=self.tmp / "state" / WS)
        # Injecao observada: o EACCES foi entregue no unlink DO LINK de wants.
        self.assertTrue([c for c in desligado.call_args_list if os.fspath(c.args[0]) == os.fspath(link)],
                        desligado.call_args_list)
        self.assertTrue(link.is_symlink())
        self.assertEqual([c.args[0][2] for c in run.call_args_list], ["stop", "disable"])


if __name__ == "__main__":
    unittest.main()
