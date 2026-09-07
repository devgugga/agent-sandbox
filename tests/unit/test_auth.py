"""Testes de autenticação e volume de credenciais em cli/asb/lifecycle.py."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import keyring, lifecycle  # noqa: E402


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
    def test_ensure_keyring_service_creates_container_with_expected_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_pass = Path(tmp) / "keyring.pass"
            fake_pass.write_text("secret-pass")
            with mock.patch("asb.keyring.ensure_keyring_pass", return_value=fake_pass), \
                 mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
                 mock.patch("asb.keyring.ensure_keyring_data_volume", return_value="asb-keyring-data"), \
                 mock.patch("asb.keyring.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
                 mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if kind == "image" else False), \
                 mock.patch("asb.lifecycle.podman.run") as mock_run, \
                 mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True) as mock_wait:
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
                self.assertIn("asb-credentials:/run/asb-credentials:ro,z", args)
                self.assertIn("asb-keyring-data:/run/asb-keyring-data:z", args)
                self.assertIn("asb-keyring-runtime:/run/asb-keyring:z", args)
                self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", args)
                self.assertIn(f"asb.keyring.schema={lifecycle.KEYRING_SCHEMA}", args)
                self.assertIn("--entrypoint", args)
                self.assertEqual(args[args.index("--entrypoint") + 1], "/usr/local/bin/start-keyring.sh")
                self.assertEqual(args[-1], lifecycle.IMAGE)
                self.assertFalse(any("squid" in str(arg) for arg in args))

    def test_ensure_keyring_service_starts_existing_stopped_container(self):
        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.running", return_value=False), \
             mock.patch("asb.lifecycle.podman.run") as mock_run, \
             mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True) as mock_wait:
            name = lifecycle.ensure_keyring_service()
            self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
            mock_run.assert_called_once_with("start", lifecycle.KEYRING_CONTAINER)
            mock_wait.assert_called_once_with(lifecycle.KEYRING_CONTAINER, timeout=5.0)

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
                 mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True):
                name = lifecycle.ensure_keyring_service()
                self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
                # Must remove only the container
                self.assertEqual(run_calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))
                # Must recreate with schema 2
                create_call = run_calls[1]
                self.assertEqual(create_call[0], "run")
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
                 mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True):
                name = lifecycle.ensure_keyring_service()
                self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
                self.assertEqual(run_calls[0], ("rm", "-f", lifecycle.KEYRING_CONTAINER))

    def test_ensure_keyring_service_rejects_incompatible_schema(self):
        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=("99", valid_mounts)), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service()
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
                lifecycle.ensure_keyring_service()

        self.assertIn("schema incompativel", str(ctx.exception))
        mock_run.assert_not_called()

    def test_ensure_keyring_service_never_replaces_container_when_inspect_fails(self):
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.lifecycle.podman.out", side_effect=lifecycle.podman.PodmanError("inspect falhou")), \
             mock.patch("asb.lifecycle.podman.run") as mock_run:
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service()

        self.assertIn("inspecionar", str(ctx.exception))
        mock_run.assert_not_called()

    def test_ensure_keyring_service_waits_for_socket_and_secrets(self):
        calls = []
        def fake_run(*args, **kwargs):
            calls.append(args)
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run):
            name = lifecycle.ensure_keyring_service()
            self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
            has_socket_check = any("test" in cmd and lifecycle.KEYRING_BUS in cmd for cmd in calls)
            has_secrets_check = any("dbus-send" in cmd and "string:org.freedesktop.secrets" in cmd for cmd in calls)
            self.assertTrue(has_socket_check)
            self.assertTrue(has_secrets_check)

    def test_ensure_keyring_service_recovers_after_restarting_unresponsive_container(self):
        calls = []
        def fake_run(*args, **kwargs):
            calls.append(args)
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run), \
             mock.patch("asb.keyring._wait_for_keyring_readiness", side_effect=[False, True]):
            name = lifecycle.ensure_keyring_service()
            self.assertEqual(name, lifecycle.KEYRING_CONTAINER)
            self.assertIn(("restart", lifecycle.KEYRING_CONTAINER), calls)

    def test_ensure_keyring_service_restarts_and_fails_with_repair_command_if_still_unresponsive(self):
        calls = []
        def fake_run(*args, **kwargs):
            calls.append(args)
            return mock.MagicMock(returncode=0)

        valid_mounts = valid_keyring_mounts()
        with mock.patch("asb.lifecycle.podman.exists", return_value=True), \
             mock.patch("asb.keyring._inspect_keyring_container", return_value=(lifecycle.KEYRING_SCHEMA, valid_mounts)), \
             mock.patch("asb.lifecycle.podman.running", return_value=True), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_run), \
             mock.patch("asb.keyring._wait_for_keyring_readiness", side_effect=[False, False]):
            with self.assertRaises(lifecycle.podman.PodmanError) as ctx:
                lifecycle.ensure_keyring_service()
            self.assertIn("podman rm -f", str(ctx.exception))
            self.assertIn("asb-agent login", str(ctx.exception))
            self.assertIn(("restart", lifecycle.KEYRING_CONTAINER), calls)

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
                 mock.patch("asb.keyring._wait_for_keyring_readiness", return_value=True):
                c_vol = lifecycle.ensure_credentials_volume()
                self.assertEqual(c_vol, "custom-cred-vol")
                d_vol = lifecycle.ensure_keyring_data_volume()
                self.assertEqual(d_vol, "custom-data-vol")
                r_vol = lifecycle.ensure_keyring_runtime_volume()
                self.assertEqual(r_vol, "custom-run-vol")
                p_file = lifecycle.ensure_keyring_pass()
                self.assertEqual(p_file, custom_pass)

                name = lifecycle.ensure_keyring_service()
                self.assertEqual(name, "custom-keyring-cont")
                args = list(mock_run.call_args[0])
                self.assertIn("custom-keyring-cont", args)
                self.assertIn("custom-cred-vol:/run/asb-credentials:ro,z", args)
                self.assertIn("custom-data-vol:/run/asb-keyring-data:z", args)
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
        self.assertIn("type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000", run_args_captured)
        self.assertIn(f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}", run_args_captured)
        self.assertFalse(any("ASB_KEYRING_PASS" in str(a) for a in run_args_captured))

    def test_login_cleanup_removes_asb_login_without_touching_keyring_container(self):
        removed_containers = []

        def fake_podman_run(*args, **kwargs):
            if len(args) >= 3 and args[0] == "rm" and "-f" in args:
                idx = args.index("-f") + 1
                removed_containers.append(args[idx])
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind == "image" or name == "asb-login") else False), \
             mock.patch("asb.lifecycle.ensure_keyring_service"), \
             mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
             mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_podman_run), \
             mock.patch("asb.lifecycle.podman.require_binary", return_value="podman"), \
             mock.patch("subprocess.run", return_value=mock.MagicMock(returncode=0)):
            rc = lifecycle.login(Path("/fake/root"))
            self.assertEqual(rc, 0)

        self.assertIn("asb-login", removed_containers)
        self.assertNotIn(lifecycle.KEYRING_CONTAINER, removed_containers)
        self.assertNotIn("asb-keyring", removed_containers)

    def test_login_failure_still_cleans_up_asb_login_and_preserves_keyring(self):
        removed_containers = []

        def fake_podman_run(*args, **kwargs):
            if len(args) >= 3 and args[0] == "rm" and "-f" in args:
                idx = args.index("-f") + 1
                removed_containers.append(args[idx])
            return mock.MagicMock(returncode=0)

        # Fail one of the LOGIN_CHECKS
        def fake_subproc_run(cmd, *args, **kwargs):
            if any("timeout" in str(c) for c in cmd):
                return mock.MagicMock(returncode=1)
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind == "image" or name == "asb-login") else False), \
             mock.patch("asb.lifecycle.ensure_keyring_service"), \
             mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
             mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
             mock.patch("asb.lifecycle.podman.run", side_effect=fake_podman_run), \
             mock.patch("asb.lifecycle.podman.require_binary", return_value="podman"), \
             mock.patch("subprocess.run", side_effect=fake_subproc_run):
            with self.assertRaises(lifecycle.podman.PodmanError):
                lifecycle.login(Path("/fake/root"))

        self.assertIn("asb-login", removed_containers)
        self.assertNotIn(lifecycle.KEYRING_CONTAINER, removed_containers)

    def test_login_executes_real_login_checks_inside_asb_login(self):
        executed_commands = []

        def fake_subproc_run(cmd, *args, **kwargs):
            executed_commands.append(list(cmd))
            return mock.MagicMock(returncode=0)

        with mock.patch("asb.lifecycle.podman.exists", side_effect=lambda kind, name: True if (kind == "image" or name == "asb-login") else False), \
             mock.patch("asb.lifecycle.ensure_keyring_service"), \
             mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
             mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
             mock.patch("asb.lifecycle.podman.run"), \
             mock.patch("asb.lifecycle.podman.require_binary", return_value="podman"), \
             mock.patch("subprocess.run", side_effect=fake_subproc_run):
            rc = lifecycle.login(Path("/fake/root"))
            self.assertEqual(rc, 0)

        # Each check in LOGIN_CHECKS must have been run against asb-login with timeout
        for label, check_cmd in lifecycle.LOGIN_CHECKS:
            matched = False
            for cmd in executed_commands:
                if "asb-login" in cmd and check_cmd in cmd and "timeout" in cmd:
                    matched = True
                    break
            self.assertTrue(matched, f"check '{label}' ({check_cmd}) was not executed on asb-login")


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
            self.assertEqual(fix, "reinicie o container: podman start asb-keyring")

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
            self.assertEqual(fix, "reinicie o servico: podman restart asb-keyring")

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
            self.assertEqual(fix, "reinicie o servico: podman restart asb-keyring")

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
