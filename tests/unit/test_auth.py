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

    def test_ensure_keyring_runtime_volume_creates_when_missing(self):
        with mock.patch("asb.podman.exists", return_value=False) as mock_exists, \
             mock.patch("asb.podman.run") as mock_run:
            vol = lifecycle.ensure_keyring_runtime_volume()
            self.assertEqual(vol, lifecycle.KEYRING_RUNTIME_VOLUME)
            mock_exists.assert_called_once_with("volume", lifecycle.KEYRING_RUNTIME_VOLUME)
            mock_run.assert_called_once_with("volume", "create", lifecycle.KEYRING_RUNTIME_VOLUME)

    def test_ensure_keyring_runtime_volume_idempotent_when_present(self):
        with mock.patch("asb.podman.exists", return_value=True) as mock_exists, \
             mock.patch("asb.podman.run") as mock_run:
            vol = lifecycle.ensure_keyring_runtime_volume()
            self.assertEqual(vol, lifecycle.KEYRING_RUNTIME_VOLUME)
            mock_exists.assert_called_once_with("volume", lifecycle.KEYRING_RUNTIME_VOLUME)
            mock_run.assert_not_called()


class TestKeyringServiceLifecycle(unittest.TestCase):
    def test_ensure_keyring_service_creates_container_with_expected_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("secret-pass")
            with mock.patch("asb.lifecycle.ensure_keyring_pass", return_value=fake_pass), \
                 mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
                 mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
                 mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if kind == "image" else False), \
                 mock.patch("asb.lifecycle.podman.run") as mock_run, \
                 mock.patch("asb.lifecycle._wait_for_keyring_readiness") as mock_wait:
                name = lifecycle.ensure_keyring_service()
                self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
                mock_wait.assert_called_once_with(lifecycle.KEYRING_CONTAINER, timeout=5.0)
                mock_run.assert_called_once()
                args = list(mock_run.call_args[0])
                self.assertEqual(args[0], "run")
                self.assertIn("-d", args)
                self.assertIn("--name", args)
                self.assertEqual(args[args.index("--name") + 1], lifecycle.KEYRING_CONTAINER)
                self.assertIn("--network", args)
                self.assertEqual(args[args.index("--network") + 1], "none")
                self.assertIn("--restart", args)
                self.assertEqual(args[args.index("--restart") + 1], "unless-stopped")
                self.assertIn("--user", args)
                self.assertEqual(args[args.index("--user") + 1], "1000")
                self.assertIn("--userns", args)
                self.assertEqual(args[args.index("--userns") + 1], "keep-id:uid=1000,gid=1000")
                self.assertIn(f"{fake_pass}:/run/asb-keyring-pass:ro,Z", args)
                self.assertIn("asb-credentials:/run/asb-credentials:z", args)
                self.assertIn("asb-keyring-runtime:/run/asb-keyring:z", args)
                self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", args)
                self.assertIn("asb.keyring.schema=1", args)
                self.assertIn("--entrypoint", args)
                self.assertEqual(args[args.index("--entrypoint") + 1], "/usr/local/bin/start-keyring.sh")
                self.assertEqual(args[-1], lifecycle.IMAGE)
                self.assertFalse(any("squid" in str(arg) for arg in args))

    def test_ensure_keyring_service_starts_existing_stopped_container(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value="1"), \
             mock.patch("asb.lifecycle.podman.running", return_value=False), \
             mock.patch("asb.lifecycle.podman.run") as mock_run, \
             mock.patch("asb.lifecycle._wait_for_keyring_readiness") as mock_wait:
            name = lifecycle.ensure_keyring_service()
            self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
            mock_run.assert_called_once_with("start", lifecycle.KEYRING_CONTAINER)
            mock_wait.assert_called_once_with(lifecycle.KEYRING_CONTAINER, timeout=5.0)

    def test_ensure_keyring_service_rejects_incompatible_schema(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value="bad-schema"), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service()
            self.assertIn("podman rm -f", str(ctx.exception))
            self.assertIn("schema", str(ctx.exception).lower())
            mock_run.assert_not_called()

    def test_ensure_keyring_service_waits_for_socket_and_secrets(self):
        calls = []
        def fake_run(*args, **kwargs):
            calls.append(args)
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value="1"), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run):
            name = lifecycle.ensure_keyring_service()
            self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
            has_socket_check = any("test" in cmd and lifecycle.KEYRING_BUS in cmd for cmd in calls)
            has_secrets_check = any("dbus-send" in cmd and "string:org.freedesktop.secrets" in cmd for cmd in calls)
            self.assertTrue(has_socket_check)
            self.assertTrue(has_secrets_check)

    def test_ensure_keyring_service_timeout_raises_podman_error_citing_login(self):
        def fake_run(*args, **kwargs):
            if "test" in args:
                return mock.MagicMock(returncode=0)
            if "dbus-send" in args:
                return mock.MagicMock(returncode=1)
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value="1"), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run), \
             mock.patch("time.sleep"):
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(timeout=0.01)
            self.assertIn("asb-agent login", str(ctx.exception))

    def test_keyring_environment_overrides(self):
        env = {
            "ASB_CREDENTIALS_VOLUME": "custom-cred-vol",
            "ASB_KEYRING_RUNTIME_VOLUME": "custom-run-vol",
            "ASB_KEYRING_CONTAINER": "custom-keyring-cont",
            "ASB_KEYRING_PASS_FILE": "/custom/path/keyring.pass",
        }
        with tempfile.TemporaryDirectory() as tmp:
            custom_pass = Path(tmp) / "custom.pass"
            custom_pass.write_text("my-secret")
            env["ASB_KEYRING_PASS_FILE"] = str(custom_pass)
            with mock.patch.dict("os.environ", env), \
                 mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if kind == "image" else False), \
                 mock.patch("asb.lifecycle.podman.run") as mock_run, \
                 mock.patch("asb.lifecycle._wait_for_keyring_readiness"):
                c_vol = lifecycle.ensure_credentials_volume()
                self.assertEqual(c_vol, "custom-cred-vol")
                r_vol = lifecycle.ensure_keyring_runtime_volume()
                self.assertEqual(r_vol, "custom-run-vol")
                p_file = lifecycle.ensure_keyring_pass()
                self.assertEqual(p_file, custom_pass)

                name = lifecycle.ensure_keyring_service()
                self.assertEqual(name, "custom-keyring-cont")
                args = list(mock_run.call_args[0])
                self.assertIn("custom-keyring-cont", args)
                self.assertIn("custom-cred-vol:/run/asb-credentials:z", args)
                self.assertIn("custom-run-vol:/run/asb-keyring:z", args)
                self.assertIn(f"{custom_pass}:/run/asb-keyring-pass:ro,Z", args)


class TestLoginKeyringIntegration(unittest.TestCase):
    def test_login_ensures_keyring_service_and_passes_shared_bus_without_passphrase(self):
        events = []
        run_args_captured = []

        def fake_podman_run(*args, **kwargs):
            if len(args) >= 4 and args[0] == "run" and "--name" in args:
                idx = args.index("--name") + 1
                if args[idx] == "asb-login":
                    events.append("run asb-login")
                    run_args_captured.extend(args)
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind == "image" or name == "asb-login") else False), \
             mock.patch("asb.lifecycle.ensure_keyring_service", side_effect=lambda: events.append("ensure_keyring_service")), \
             mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
             mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_podman_run), \
             mock.patch("asb.lifecycle.podman.require_binary", return_value="podman"), \
             mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)):
            rc = lifecycle.login(Path("/fake/root"))
            self.assertEqual(rc, 0)

        self.assertIn("ensure_keyring_service", events)
        self.assertIn("run asb-login", events)
        self.assertLess(events.index("ensure_keyring_service"), events.index("run asb-login"))

        self.assertIn("asb-keyring-runtime:/run/asb-keyring:ro,z", run_args_captured)
        self.assertIn("asb-credentials:/run/asb-credentials:z", run_args_captured)
        self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", run_args_captured)
        self.assertFalse(any("ASB_KEYRING_PASS" in str(a) for a in run_args_captured))


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
