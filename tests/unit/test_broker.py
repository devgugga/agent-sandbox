
import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

BROKER_PATH = Path(__file__).resolve().parents[2] / "broker" / "asb-docker-broker.py"
spec = importlib.util.spec_from_file_location("asb_docker_broker", BROKER_PATH)
broker_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker_mod)
permitted = broker_mod.permitted


class TestBrokerPermitted(unittest.TestCase):
    """Testa a função permitted(method, target) do broker."""

    def test_allowed_endpoints_without_version(self):
        self.assertTrue(permitted("GET", "/version"))
        self.assertTrue(permitted("GET", "/info"))
        self.assertTrue(permitted("GET", "/events"))
        self.assertTrue(permitted("GET", "/containers/json"))
        self.assertTrue(permitted("GET", "/containers/my-container_1.0/json"))
        self.assertTrue(permitted("GET", "/containers/c123/logs"))
        self.assertTrue(permitted("GET", "/containers/c123/stats"))
        self.assertTrue(permitted("GET", "/containers/c123/top"))

    def test_allowed_endpoints_with_version_prefix(self):
        self.assertTrue(permitted("GET", "/v1.43/version"))
        self.assertTrue(permitted("GET", "/v1.40/info"))
        self.assertTrue(permitted("GET", "/v1.41/events"))
        self.assertTrue(permitted("GET", "/v1.43/containers/json"))
        self.assertTrue(permitted("GET", "/v1.43/containers/web-server/json"))
        self.assertTrue(permitted("GET", "/v1.43/containers/web-server/logs"))
        self.assertTrue(permitted("GET", "/v1.43/containers/web-server/stats"))
        self.assertTrue(permitted("GET", "/v1.43/containers/web-server/top"))

    def test_allowed_endpoints_with_query_parameters(self):
        self.assertTrue(permitted("GET", "/v1.43/containers/json?all=1"))
        self.assertTrue(permitted("GET", "/v1.43/containers/json?all=true&limit=10"))
        self.assertTrue(permitted("GET", "/v1.43/containers/c1/logs?stdout=1&stderr=1&follow=1"))
        self.assertTrue(permitted("GET", "/v1.43/containers/c1/stats?stream=false"))
        self.assertTrue(permitted("GET", "/v1.43/events?since=12345"))

    def test_non_get_methods_are_rejected(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            self.assertFalse(permitted(method, "/version"))
            self.assertFalse(permitted(method, "/v1.43/version"))
            self.assertFalse(permitted(method, "/v1.43/containers/json"))
            self.assertFalse(permitted(method, "/v1.43/containers/c1/logs"))

    def test_mutating_endpoints_are_rejected(self):
        self.assertFalse(permitted("POST", "/v1.43/containers/create"))
        self.assertFalse(permitted("POST", "/v1.43/containers/c1/start"))
        self.assertFalse(permitted("POST", "/v1.43/containers/c1/stop"))
        self.assertFalse(permitted("POST", "/v1.43/containers/c1/exec"))
        self.assertFalse(permitted("POST", "/v1.43/build"))
        self.assertFalse(permitted("POST", "/v1.43/images/create"))

    def test_unlisted_read_endpoints_are_rejected(self):
        # Leitura de imagens, volumes, redes e secrets não estão no escopo do broker
        self.assertFalse(permitted("GET", "/images/json"))
        self.assertFalse(permitted("GET", "/v1.43/images/json"))
        self.assertFalse(permitted("GET", "/v1.43/volumes"))
        self.assertFalse(permitted("GET", "/v1.43/networks"))
        self.assertFalse(permitted("GET", "/v1.43/secrets"))
        self.assertFalse(permitted("GET", "/v1.43/exec/xyz/json"))
        self.assertFalse(permitted("GET", "/"))

    def test_path_traversal_is_rejected(self):
        self.assertFalse(permitted("GET", "/v1.43/containers/../../secret"))
        self.assertFalse(permitted("GET", "/v1.43/../../etc/shadow"))
        self.assertFalse(permitted("GET", "/containers/../../root"))
        self.assertFalse(permitted("GET", "version"))
        self.assertFalse(permitted("GET", ""))

    def test_container_name_validation(self):
        # Subcaminhos ou caracteres estranhos no nome do container não são aceitos
        self.assertFalse(permitted("GET", "/v1.43/containers/foo/bar/json"))
        self.assertFalse(permitted("GET", "/v1.43/containers/foo bar/logs"))
        self.assertFalse(permitted("GET", "/v1.43/containers//logs"))


class TestBrokerHandler(unittest.TestCase):
    """Testa a rejeição no nível de protocolo HTTP no Handler."""

    def _test_rejected_request(self, raw_request: bytes):
        import socket
        client_sock, srv_sock = socket.socketpair()
        try:
            client_sock.sendall(raw_request)
            broker_mod.Handler(srv_sock, ("127.0.0.1", 0), None)
            resp = client_sock.recv(4096)
            self.assertTrue(resp.startswith(b"HTTP/1.1 403 Forbidden"))
        finally:
            client_sock.close()
            srv_sock.close()

    def test_handler_rejects_post_request(self):
        self._test_rejected_request(
            b"POST /v1.43/containers/create HTTP/1.1\r\nHost: docker\r\n\r\n"
        )

    def test_handler_rejects_unlisted_endpoint(self):
        self._test_rejected_request(
            b"GET /v1.43/images/json HTTP/1.1\r\nHost: docker\r\n\r\n"
        )

    def test_handler_rejects_path_traversal(self):
        self._test_rejected_request(
            b"GET /v1.43/containers/../../secret HTTP/1.1\r\nHost: docker\r\n\r\n"
        )

    def test_handler_rejects_malformed_request(self):
        self._test_rejected_request(b"GARBAGE\r\n\r\n")


class TestBrokerInstaller(unittest.TestCase):
    """Testa cli/asb/install.py broker()."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]

    def test_broker_returns_1_when_docker_socket_missing(self):
        from asb import install
        with unittest.mock.patch("asb.install.DOCKER_SOCKETS", ("/nonexistent/docker.sock",)):
            ret = install.broker(self.root)
            self.assertEqual(ret, 1)

    def test_broker_installs_unit_and_script(self):
        from asb import install
        with unittest.mock.patch("asb.install.DOCKER_SOCKETS", ("/run/docker.sock",)), \
             unittest.mock.patch("subprocess.run") as mock_run, \
             unittest.mock.patch("pathlib.Path.exists", return_value=True):
            ret = install.broker(self.root)
            self.assertEqual(ret, 0)
            calls = mock_run.call_args_list
            self.assertEqual(len(calls), 4)
            # 1. install script
            self.assertEqual(calls[0][0][0], [
                "sudo", "install", "-m", "0755",
                str(self.root / "broker" / "asb-docker-broker.py"),
                str(install.BROKER_SCRIPT)
            ])
            # 2. tee service unit
            self.assertEqual(calls[1][0][0], ["sudo", "tee", str(install.BROKER_UNIT)])
            unit_text = calls[1][1]["input"]
            import os
            self.assertIn("Environment=ASB_DOCKER_SOCK=/run/docker.sock", unit_text)
            self.assertIn("Environment=ASB_BROKER_SOCK=/run/asb-docker/docker.sock", unit_text)
            self.assertIn(f"Environment=ASB_BROKER_UID={os.getuid()}", unit_text)
            self.assertIn(f"ExecStart={sys.executable} {install.BROKER_SCRIPT}", unit_text)
            # 3. daemon-reload
            self.assertEqual(calls[2][0][0], ["sudo", "systemctl", "daemon-reload"])
            # 4. enable --now
            self.assertEqual(calls[3][0][0], ["sudo", "systemctl", "enable", "--now", "asb-docker-broker.service"])


class TestLifecycleHostApi(unittest.TestCase):
    """Testa o comportamento de host_api em cli/asb/lifecycle.py."""

    def test_lifecycle_up_refuses_read_when_broker_socket_missing(self):
        from asb import lifecycle, podman
        from asb.profile import Profile
        root = Path(__file__).resolve().parents[2]
        fake_profile = Profile(host_api="read")

        def fake_exists(kind, name):
            return kind == "image"

        orig_exists = Path.exists

        def fake_path_exists(p):
            if str(p) == "/run/asb-docker/docker.sock":
                return False
            return orig_exists(p)

        with mock.patch("asb.lifecycle.load_profile", return_value=fake_profile), \
             mock.patch("asb.podman.exists", side_effect=fake_exists), \
             mock.patch("asb.podman.run"), \
             mock.patch("asb.lifecycle.build_proxy"), \
             mock.patch("asb.lifecycle.prepare_clone"), \
             mock.patch("asb.lifecycle.layout_for") as mock_layout, \
             mock.patch("pathlib.Path.write_text"), \
             mock.patch("pathlib.Path.chmod"), \
             mock.patch.object(Path, "exists", fake_path_exists):
            mock_layout.return_value.state = Path("/tmp/dummy-asb-state")
            mock_layout.return_value.mount = Path("/tmp/dummy-asb-mount")
            mock_layout.return_value.project_root = Path("/tmp/dummy-asb-mount")
            with self.assertRaises(podman.PodmanError) as ctx:
                lifecycle._up(root, "ws-test", root)
            self.assertIn('host_api = "read" pede o broker', str(ctx.exception))

    def test_lifecycle_up_starts_relay_when_broker_socket_present(self):
        from asb import lifecycle
        from asb.profile import Profile
        root = Path(__file__).resolve().parents[2]
        fake_profile = Profile(host_api="read")

        def fake_exists(kind, name):
            return kind == "image"

        runs = []

        def fake_run(*args, **kwargs):
            runs.append(args)

        with mock.patch("asb.lifecycle.load_profile", return_value=fake_profile), \
             mock.patch("asb.podman.exists", side_effect=fake_exists), \
             mock.patch("asb.podman.run", side_effect=fake_run), \
             mock.patch("asb.podman.out", return_value="127.0.0.1:2222\n"), \
             mock.patch("asb.lifecycle.build_proxy"), \
             mock.patch("asb.lifecycle.prepare_clone"), \
             mock.patch("asb.lifecycle.layout_for") as mock_layout, \
             mock.patch("asb.lifecycle.build_staging", return_value=0), \
             mock.patch("asb.lifecycle.ensure_ssh_key"), \
             mock.patch("asb.lifecycle.ensure_keyring_service"), \
             mock.patch("asb.lifecycle.ensure_keyring_runtime_volume", return_value="asb-keyring-runtime"), \
             mock.patch("asb.lifecycle.ensure_credentials_volume", return_value="asb-credentials"), \
             mock.patch("asb.lifecycle.credential_mount_args", return_value=[]), \
             mock.patch("asb.lifecycle.ensure_session_volume", return_value="asb-test-ws-session"), \
             mock.patch("asb.readiness.wait_until", return_value=mock.MagicMock(state="healthy", code="ok")), \
             mock.patch("asb.install.podman_restart"), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("pathlib.Path.write_text"), \
             mock.patch("pathlib.Path.read_text", return_value="ssh-ed25519 AAAA"), \
             mock.patch("pathlib.Path.chmod"):
            mock_layout.return_value.state = Path("/tmp/dummy-asb-state")
            mock_layout.return_value.mount = Path("/tmp/dummy-asb-mount")
            mock_layout.return_value.project_root = Path("/tmp/dummy-asb-mount")
            ret = lifecycle._up(root, "ws-test", root)
            self.assertEqual(ret, 0)

            # Check relay container was started
            relay_call = next((cmd for cmd in runs if "asb-ws-test-docker" in cmd), None)
            self.assertIsNotNone(relay_call)
            self.assertIn("socat TCP-LISTEN:2375,fork,reuseaddr UNIX-CONNECT:/var/run/docker.sock", relay_call)

            # Check agent container has DOCKER_HOST env
            agent_call = next((cmd for cmd in runs if "asb-ws-test-agent" in cmd), None)
            self.assertIsNotNone(agent_call)
            self.assertIn("DOCKER_HOST=tcp://asb-ws-test-docker:2375", agent_call)


if __name__ == "__main__":
    unittest.main()
