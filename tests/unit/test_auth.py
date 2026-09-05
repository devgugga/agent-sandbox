"""Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py."""
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import lifecycle  # noqa: E402


class TestAuthLifecycle(unittest.TestCase):
    def test_ensure_keyring_pass_creates_file_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "agent-sandbox"
            keyring_pass = config_dir / "keyring.pass"
            with mock.patch.object(lifecycle, "CONFIG", config_dir), \
                 mock.patch.object(lifecycle, "KEYRING_PASS", keyring_pass):
                self.assertFalse(keyring_pass.exists())
                p1 = lifecycle.ensure_keyring_pass()
                self.assertEqual(p1, keyring_pass)
                self.assertTrue(keyring_pass.exists())
                # Check permissions
                mode = keyring_pass.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)
                config_mode = config_dir.stat().st_mode & 0o777
                self.assertEqual(config_mode, 0o700)

                content1 = keyring_pass.read_text().strip()
                # Must be valid base64 of 32 bytes
                decoded = base64.b64decode(content1)
                self.assertEqual(len(decoded), 32)

                # Calling again should return existing without re-generating
                p2 = lifecycle.ensure_keyring_pass()
                self.assertEqual(p2, keyring_pass)
                self.assertEqual(keyring_pass.read_text().strip(), content1)

    def test_ensure_credentials_volume_creates_when_missing(self):
        with mock.patch("asb.podman.exists", return_value=False) as mock_exists, \
             mock.patch("asb.podman.run") as mock_run:
            vol = lifecycle.ensure_credentials_volume()
            self.assertEqual(vol, lifecycle.CREDENTIALS_VOLUME)
            mock_exists.assert_called_once_with("volume", lifecycle.CREDENTIALS_VOLUME)
            mock_run.assert_called_once_with("volume", "create", lifecycle.CREDENTIALS_VOLUME)

    def test_ensure_credentials_volume_idempotent_when_present(self):
        with mock.patch("asb.podman.exists", return_value=True) as mock_exists, \
             mock.patch("asb.podman.run") as mock_run:
            vol = lifecycle.ensure_credentials_volume()
            self.assertEqual(vol, lifecycle.CREDENTIALS_VOLUME)
            mock_exists.assert_called_once_with("volume", lifecycle.CREDENTIALS_VOLUME)
            mock_run.assert_not_called()


class TestVerificacaoDeLogin(unittest.TestCase):
    """A verificacao do login tem de EXERCITAR autenticacao.

    `asb-agy --version` responde 0 com o agente deslogado: o `asb-agent login`
    imprimia "Antigravity: ok" enquanto a CLI dizia "You are currently not
    signed in". Um falso verde aqui e pior que nenhuma checagem, porque manda
    o operador embora achando que a credencial foi gravada.
    """

    def test_nenhuma_checagem_e_consulta_de_versao(self):
        from asb import lifecycle
        for label, command in lifecycle.LOGIN_CHECKS:
            with self.subTest(agente=label):
                self.assertNotIn(
                    "--version", command,
                    f"a checagem do {label} e {command!r}, que responde 0 com "
                    f"o agente deslogado")

    def test_ha_uma_checagem_para_cada_agente_instalado(self):
        from asb import lifecycle
        labels = {label for label, _ in lifecycle.LOGIN_CHECKS}
        self.assertEqual(labels, {"Codex", "Claude Code", "Antigravity"})
