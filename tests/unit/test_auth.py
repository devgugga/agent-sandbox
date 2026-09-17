"""Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import keyring, lifecycle, podman  # noqa: E402


def valid_keyring_mounts(pass_file: Path | None = None) -> dict[str, dict[str, object]]:
    """Espelha a estrutura real de Mounts retornada por podman inspect."""
    return {
        "/run/asb-credentials": {
            "type": "volume", "name": "asb-credentials", "source": "", "rw": False},
        "/run/asb-keyring-data": {
            "type": "volume", "name": "asb-keyring-data", "source": "", "rw": True},
        "/run/asb-keyring": {
            "type": "volume", "name": "asb-keyring-runtime", "source": "", "rw": True},
        "/run/asb-keyring-pass": {
            "type": "bind", "name": "",
            "source": str(pass_file or lifecycle.KEYRING_PASS), "rw": False},
    }


class TestAuthLifecycle(unittest.TestCase):
    def test_ensure_keyring_pass_creates_file_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "agent-sandbox"
            keyring_pass = config_dir / "keyring.pass"
            with mock.patch.object(keyring, "CONFIG", config_dir), \
                 mock.patch.object(keyring, "KEYRING_PASS", keyring_pass):
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

    def test_ensure_keyring_pass_external_path_preserves_parent_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            external_dir = Path(tmp) / "shared-dir"
            external_dir.mkdir(mode=0o755)
            external_dir.chmod(0o755)
            pass_file = external_dir / "test-keyring.pass"
            with mock.patch.dict("os.environ", {"ASB_KEYRING_PASS_FILE": str(pass_file)}):
                self.assertFalse(pass_file.exists())
                p = lifecycle.ensure_keyring_pass()
                self.assertEqual(p, pass_file)
                self.assertTrue(pass_file.exists())
                # Passphrase file must be 0600
                self.assertEqual(pass_file.stat().st_mode & 0o777, 0o600)
                # Parent directory permissions must NOT have been changed to 0700
                self.assertEqual(external_dir.stat().st_mode & 0o777, 0o755)

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
    RUNTIME_DIR = Path("/opt/asb/runtime/rev1")

    def _systemd_mocks(self, stack, tmp: str):
        installed = stack.enter_context(mock.patch(
            "asb.supervisor.install_keyring_unit",
            return_value=Path(tmp) / f"{lifecycle.KEYRING_CONTAINER}.service"))
        systemctl = stack.enter_context(mock.patch(
            "asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0)))
        return installed, systemctl

    def test_ensure_keyring_service_creates_a_stopped_container_supervised_by_systemd(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("secret-pass")
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass))
            stack.enter_context(mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists",
                                           side_effect=lambda kind, name: kind == "image"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            installed, systemctl = self._systemd_mocks(stack, tmp)

            name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
        mock_run.assert_called_once()
        args = list(mock_run.call_args[0])
        self.assertEqual(args[0], "create")
        self.assertNotIn("-d", args)
        self.assertEqual(args[args.index("--name") + 1], lifecycle.KEYRING_CONTAINER)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--restart") + 1], "no")
        self.assertEqual(args[args.index("--user") + 1], "1000")
        self.assertEqual(args[args.index("--userns") + 1], "keep-id:uid=1000,gid=1000")
        self.assertIn(f"{fake_pass}:/run/asb-keyring-pass:ro,Z", args)
        self.assertIn("asb-credentials:/run/asb-credentials:ro,z", args)
        self.assertIn("asb-keyring-data:/run/asb-keyring-data:z", args)
        self.assertIn("asb-keyring-runtime:/run/asb-keyring:z", args)
        self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", args)
        self.assertIn(f"asb.keyring.schema={lifecycle.KEYRING_SCHEMA}", args)
        self.assertEqual(args[args.index("--entrypoint") + 1], "/usr/local/bin/start-keyring.sh")
        self.assertEqual(args[-1], lifecycle.IMAGE)
        installed.assert_called_once_with(lifecycle.KEYRING_CONTAINER, self.RUNTIME_DIR)
        unit = f"{lifecycle.KEYRING_CONTAINER}.service"
        self.assertEqual(
            [c.args[0] for c in systemctl.call_args_list],
            [["systemctl", "--user", "enable", unit], ["systemctl", "--user", "start", unit]],
        )

    def test_ensure_keyring_service_fails_when_image_is_missing(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=False))
            with self.assertRaises(podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
            self.assertIn(f"imagem {lifecycle.IMAGE} ausente", str(ctx.exception))

    def test_existing_supervised_container_is_kept_and_started_by_systemd(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts())))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="no"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            installed, systemctl = self._systemd_mocks(stack, tmp)

            name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
        mock_run.assert_not_called()
        installed.assert_called_once_with(lifecycle.KEYRING_CONTAINER, self.RUNTIME_DIR)
        self.assertEqual(len(systemctl.call_args_list), 2)

    def test_legacy_unless_stopped_container_is_recreated_keeping_volumes(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("pass")
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass))
            stack.enter_context(mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"))
            stack.enter_context(mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts(fake_pass))))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="unless-stopped"))
            mock_run = stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            _, systemctl = self._systemd_mocks(stack, tmp)

            lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        calls = [c.args for c in mock_run.call_args_list]
        self.assertEqual(calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))
        self.assertEqual(calls[1][0], "create")
        # So o container sai: nenhum volume e removido.
        self.assertFalse(any("volume" in c for c in calls))
        # A unidade para ANTES do rm: com ela ativa, o `rm` mata o processo
        # anexado, o Restart=always tenta subir um container que ja nao
        # existe e cada tentativa gasta uma partida do StartLimitBurst.
        unit = f"{lifecycle.KEYRING_CONTAINER}.service"
        systemctl_calls = [c.args[0] for c in systemctl.call_args_list]
        self.assertEqual(systemctl_calls[0],
                         ["systemctl", "--user", "stop", unit])

    def test_systemd_start_failure_is_an_infrastructure_error(self):
        import subprocess as _subprocess
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            stack.enter_context(mock.patch("asb.lifecycle.podman.exists", return_value=True))
            stack.enter_context(mock.patch("asb.keyring._inspect_keyring_container",
                                           return_value=(lifecycle.KEYRING_SCHEMA, valid_keyring_mounts())))
            stack.enter_context(mock.patch("asb.keyring._restart_policy", return_value="no"))
            stack.enter_context(mock.patch("asb.lifecycle.podman.run"))
            stack.enter_context(mock.patch(
                "asb.supervisor.install_keyring_unit",
                return_value=Path(tmp) / f"{lifecycle.KEYRING_CONTAINER}.service"))
            stack.enter_context(mock.patch(
                "asb.keyring.subprocess.run",
                side_effect=[mock.MagicMock(returncode=0),
                             _subprocess.CalledProcessError(1, ["systemctl"])]))
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
        self.assertIn("systemctl --user status", str(ctx.exception))

    def test_ensure_keyring_service_auto_upgrades_schema_1_container(self):
        run_calls = []
        def fake_run(*args, **kwargs):
            run_calls.append(args)
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("pass")
            with mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass), \
                 mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
                 mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"), \
                 mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
                 mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind in ("container", "image")) else False), \
                 mock.patch("asb.keyring._inspect_keyring_container", return_value=("1", {"/run/asb-credentials": True})), \
                 mock.patch("asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("asb.supervisor.install_keyring_unit", return_value=Path(tmp) / "asb-keyring.service"), \
                 mock.patch("asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0)):
                name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
                self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
                # Must remove only the container
                self.assertEqual(run_calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))
                # Must recreate with schema 2
                create_call = run_calls[1]
                self.assertEqual(create_call[0], "create")
                self.assertIn(f"asb.keyring.schema={lifecycle.KEYRING_SCHEMA}", create_call)
                self.assertIn("asb-credentials:/run/asb-credentials:ro,z", create_call)
                self.assertIn("asb-keyring-data:/run/asb-keyring-data:z", create_call)

    def test_ensure_keyring_service_auto_upgrades_legacy_mounts_contract(self):
        run_calls = []
        def fake_run(*args, **kwargs):
            run_calls.append(args)
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("pass")
            with mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass), \
                 mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
                 mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"), \
                 mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
                 mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind in ("container", "image")) else False), \
                 mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, {"/run/asb-credentials": {"type": "volume", "name": "asb-credentials", "source": "", "rw": True}})), \
                 mock.patch("asb.lifecycle.podman.run", side_effect=fake_run), \
                 mock.patch("asb.supervisor.install_keyring_unit", return_value=Path(tmp) / "asb-keyring.service"), \
                 mock.patch("asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0)):
                name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
                self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
                self.assertEqual(run_calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))

    def test_ensure_keyring_service_rejects_incompatible_schema(self):
        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=("99", valid_mounts)), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
            self.assertIn("podman rm -f", str(ctx.exception))
            self.assertIn("schema", str(ctx.exception).lower())
            mock_run.assert_not_called()

    def test_ensure_keyring_service_never_replaces_unknown_schema_with_bad_mounts(self):
        inspected = {
            "Config": {"Labels": {"asb.keyring.schema": "99"}},
            "Mounts": [
                {"Type": "volume", "Name": "wrong", "Destination": "/run/asb-credentials", "RW": True},
            ],
        }
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value=json.dumps(inspected)), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertIn("schema incompativel", str(ctx.exception))
        mock_run.assert_not_called()

    def test_ensure_keyring_service_never_replaces_container_when_inspect_fails(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", side_effect=lifecycle.podman.PodmanError("inspect falhou")), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service(self.RUNTIME_DIR)

        self.assertIn("inspecionar", str(ctx.exception))
        mock_run.assert_not_called()

    def test_keyring_environment_overrides(self):
        env = {
            "ASB_CREDENTIALS_VOLUME": "custom-cred-vol",
            "ASB_KEYRING_DATA_VOLUME": "custom-data-vol",
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
                 mock.patch("asb.supervisor.install_keyring_unit", return_value=Path(tmp) / "custom-keyring-cont.service"), \
                 mock.patch("asb.keyring.subprocess.run", return_value=mock.MagicMock(returncode=0)):
                c_vol = lifecycle.ensure_credentials_volume()
                self.assertEqual(c_vol, "custom-cred-vol")
                d_vol = lifecycle.ensure_keyring_data_volume()
                self.assertEqual(d_vol, "custom-data-vol")
                r_vol = lifecycle.ensure_keyring_runtime_volume()
                self.assertEqual(r_vol, "custom-run-vol")
                p_file = lifecycle.ensure_keyring_pass()
                self.assertEqual(p_file, custom_pass)

                name = lifecycle.ensure_keyring_service(self.RUNTIME_DIR)
                self.assertEqual(name, "custom-keyring-cont")
                args = list(mock_run.call_args[0])
                self.assertEqual(args[0], "create")
                self.assertIn("custom-keyring-cont", args)
                self.assertIn("custom-cred-vol:/run/asb-credentials:ro,z", args)
                self.assertIn("custom-data-vol:/run/asb-keyring-data:z", args)
                self.assertIn("custom-run-vol:/run/asb-keyring:z", args)
                self.assertIn(f"{custom_pass}:/run/asb-keyring-pass:ro,Z", args)


# TestLoginKeyringIntegration migrou para tests/unit/test_login_flow.py
# (classe TestLoginKeyringContract) junto com o proprio login, que saiu de
# lifecycle.py para auth.py na Tarefa A3.


class TestCheckKeyringService(unittest.TestCase):
    def test_check_keyring_service_container_missing(self):
        # I1 (fix round 1): infraestrutura ausente aponta para reparo de
        # infraestrutura, nunca para o "login" universal de conta.
        with mock.patch("asb.lifecycle.podman.exists", return_value=False):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertEqual(label, "container asb-keyring")
            self.assertNotEqual(fix, "asb-agent login")
            self.assertNotIn("login", fix)
            self.assertIn("workspace", fix)

    def test_check_keyring_service_container_stopped(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=False):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertEqual(label, "asb-keyring parado")
            self.assertNotIn("login", fix)
            # O keyring e supervisionado pelo systemd (Emenda A): iniciar o
            # container por fora deixa a unidade inativa e sem reinicio.
            self.assertEqual(fix, "systemctl --user restart asb-keyring.service")
            self.assertNotIn("podman start", fix)

    def test_check_keyring_service_schema_outdated(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=("1", {"/run/asb-credentials": False})):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertIn("desatualizado", label)
            self.assertNotIn("login", fix)
            self.assertIn("podman rm -f asb-keyring", fix)

    def test_check_keyring_service_mounts_violated(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, {"/run/asb-credentials": {"type": "volume", "name": "asb-credentials", "source": "", "rw": True}})):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertIn("violado", label)
            self.assertNotIn("login", fix)
            self.assertIn("podman rm -f asb-keyring", fix)

    def test_check_keyring_service_rejects_wrong_volume_source(self):
        inspected = {
            "Config": {"Labels": {"asb.keyring.schema": "2"}},
            "Mounts": [
                {"Type": "volume", "Name": "wrong-credentials", "Destination": "/run/asb-credentials", "RW": False},
                {"Type": "volume", "Name": "asb-keyring-data", "Destination": "/run/asb-keyring-data", "RW": True},
                {"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": True},
                {"Type": "bind", "Source": str(lifecycle.KEYRING_PASS), "Destination": "/run/asb-keyring-pass", "RW": False},
            ],
        }
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value=json.dumps(inspected)), \
             mock.patch("asb.lifecycle.podman.run", return_value=mock.MagicMock(returncode=0)):
            ok, label, _ = lifecycle.check_keyring_service()

        self.assertFalse(ok)
        self.assertIn("contrato de mounts", label)

    def test_check_keyring_service_requires_read_only_passfile_mount(self):
        inspected = {
            "Config": {"Labels": {"asb.keyring.schema": "2"}},
            "Mounts": [
                {"Type": "volume", "Name": "asb-credentials", "Destination": "/run/asb-credentials", "RW": False},
                {"Type": "volume", "Name": "asb-keyring-data", "Destination": "/run/asb-keyring-data", "RW": True},
                {"Type": "volume", "Name": "asb-keyring-runtime", "Destination": "/run/asb-keyring", "RW": True},
            ],
        }
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", return_value=json.dumps(inspected)), \
             mock.patch("asb.lifecycle.podman.run", return_value=mock.MagicMock(returncode=0)):
            ok, label, _ = lifecycle.check_keyring_service()

        self.assertFalse(ok)
        self.assertIn("contrato de mounts", label)

    def test_check_keyring_service_socket_missing(self):
        def fake_run(*args, **kwargs):
            if "test" in args:
                return mock.MagicMock(returncode=1)
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertEqual(label, "socket do Secret Service (asb-keyring)")
            self.assertNotIn("login", fix)
            # Mesma regra do container parado: pela unidade, nunca por fora.
            self.assertEqual(fix, "systemctl --user restart asb-keyring.service")
            self.assertNotIn("podman restart", fix)

    def test_check_keyring_service_unresponsive(self):
        def fake_run(*args, **kwargs):
            if "test" in args:
                return mock.MagicMock(returncode=0)
            if "dbus-send" in args:
                return mock.MagicMock(returncode=1)
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertEqual(label, "Secret Service sem resposta (asb-keyring)")
            self.assertNotIn("login", fix)
            # Mesma regra do container parado: pela unidade, nunca por fora.
            self.assertEqual(fix, "systemctl --user restart asb-keyring.service")
            self.assertNotIn("podman restart", fix)

    def test_check_keyring_service_healthy(self):
        def fake_run(*args, **kwargs):
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertTrue(ok)
            self.assertEqual(label, "Secret Service (asb-keyring)")
            self.assertEqual(fix, "")

    def test_check_keyring_service_custom_container(self):
        with mock.patch.dict("os.environ", {"ASB_KEYRING_CONTAINER": "custom-keyring"}), \
             mock.patch("asb.lifecycle.podman.exists", return_value=False):
            ok, label, fix = lifecycle.check_keyring_service()
            self.assertFalse(ok)
            self.assertEqual(label, "container custom-keyring")
            self.assertNotIn("login", fix)


# TestVerificacaoDeLogin migrou para tests/unit/test_login_flow.py. A tabela
# `LOGIN_CHECKS` que ela guardava foi REMOVIDA, nao renomeada: `claude -p ping`
# e `agy -p ping` mandavam um PROMPT ao modelo para descobrir se havia sessao,
# e A1 mediu que o do agy bloqueia 60s quando deslogado.
