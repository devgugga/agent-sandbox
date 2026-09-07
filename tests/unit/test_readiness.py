"""Unit tests for cli/asb/readiness.py and cli/asb/runtime_check.py."""
from __future__ import annotations

import errno
import json
import socket
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import readiness
from asb import runtime_check
from asb.readiness import ProbeResult, wait_until, probe_host, probe_proxy, probe_ssh, probe_workspace


class TestProbeResult(unittest.TestCase):
    def test_probe_result_frozen_and_fields(self):
        result = ProbeResult(
            component="host",
            state="healthy",
            code="ok",
            elapsed_ms=42,
            remediation="",
        )
        self.assertEqual(result.component, "host")
        self.assertEqual(result.state, "healthy")
        self.assertEqual(result.code, "ok")
        self.assertEqual(result.elapsed_ms, 42)
        self.assertEqual(result.remediation, "")

        with self.assertRaises((AttributeError, TypeError)):
            result.state = "failed"  # type: ignore


class TestWaitUntil(unittest.TestCase):
    def test_invalid_parameters_raise_value_error(self):
        with self.assertRaises(ValueError):
            wait_until(lambda _: ProbeResult("p", "healthy", "ok", 0, ""), timeout=0)
        with self.assertRaises(ValueError):
            wait_until(lambda _: ProbeResult("p", "healthy", "ok", 0, ""), timeout=5, interval=0)

    def test_immediate_success(self):
        calls = []

        def probe(avail_timeout: float) -> ProbeResult:
            calls.append(avail_timeout)
            return ProbeResult("test", "healthy", "ok", 5, "")

        res = wait_until(probe, timeout=5.0, interval=0.1)
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.code, "ok")
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0], 5.0)

    def test_eventual_success_within_timeout(self):
        attempts = 0

        def probe(avail_timeout: float) -> ProbeResult:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return ProbeResult("test", "failed", "busy", 2, "retry")
            return ProbeResult("test", "healthy", "ok", 3, "")

        res = wait_until(probe, timeout=5.0, interval=0.01)
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.code, "ok")
        self.assertEqual(attempts, 3)

    def test_timeout_expiration_returns_last_failure(self):
        def probe(avail_timeout: float) -> ProbeResult:
            return ProbeResult("test", "failed", "unreachable", 10, "fix_net")

        res = wait_until(probe, timeout=0.05, interval=0.01)
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "unreachable")
        self.assertGreaterEqual(res.elapsed_ms, 40)

    def test_monotonic_clock_and_individual_timeout_cap(self):
        received_timeouts = []

        def probe(avail_timeout: float) -> ProbeResult:
            received_timeouts.append(avail_timeout)
            return ProbeResult("test", "failed", "pending", 1, "")

        curr_time = 1000.0

        def fake_monotonic():
            return curr_time

        def fake_sleep(sec):
            nonlocal curr_time
            curr_time += sec

        with mock.patch("asb.readiness.sleep", side_effect=fake_sleep), \
             mock.patch("asb.readiness.monotonic", side_effect=fake_monotonic):
            wait_until(probe, timeout=12.0, interval=1.0)

        # Individual probe timeout should be capped at 5.0
        self.assertTrue(all(t <= 5.0 for t in received_timeouts))
        self.assertGreaterEqual(len(received_timeouts), 2)


class TestProbeHost(unittest.TestCase):
    @mock.patch("socket.create_connection")
    @mock.patch("ssl.create_default_context")
    def test_probe_host_success(self, mock_ssl_ctx, mock_create_conn):
        mock_sock = mock.MagicMock()
        mock_create_conn.return_value.__enter__.return_value = mock_sock
        mock_wrap = mock.MagicMock()
        mock_ssl_ctx.return_value.wrap_socket.return_value.__enter__.return_value = mock_wrap

        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.code, "ok")

    @mock.patch("socket.create_connection", side_effect=socket.gaierror("Name or service not known"))
    def test_probe_host_dns_failed(self, mock_create_conn):
        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "unreachable")
        self.assertEqual(res.code, "dns_failed")

    @mock.patch("socket.create_connection", side_effect=OSError(errno.ENETUNREACH, "Network is unreachable"))
    def test_probe_host_no_route(self, mock_create_conn):
        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "unreachable")
        self.assertEqual(res.code, "no_route")

    @mock.patch("socket.create_connection", side_effect=OSError(errno.ECONNREFUSED, "Connection refused"))
    def test_probe_host_connection_refused(self, mock_create_conn):
        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "connection_refused")

    @mock.patch("socket.create_connection", side_effect=TimeoutError("Connection timed out"))
    def test_probe_host_timeout(self, mock_create_conn):
        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "unreachable")
        self.assertEqual(res.code, "timeout")

    @mock.patch("socket.create_connection")
    @mock.patch("ssl.create_default_context")
    def test_probe_host_tls_failed(self, mock_ssl_ctx, mock_create_conn):
        mock_sock = mock.MagicMock()
        mock_create_conn.return_value.__enter__.return_value = mock_sock
        mock_ssl_ctx.return_value.wrap_socket.side_effect = ssl.SSLError("certificate verify failed")

        res = probe_host(target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "host")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "tls_failed")


class TestProbeProxy(unittest.TestCase):
    @mock.patch("asb.podman.running")
    @mock.patch("subprocess.run")
    def test_probe_proxy_success_200(self, mock_run, mock_running):
        mock_running.return_value = True
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="HTTP/1.1 200 Connection established\r\n\r\n",
            stderr="",
        )

        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "proxy")
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.code, "ok")

    @mock.patch("asb.podman.running")
    @mock.patch("subprocess.run")
    def test_probe_proxy_403_connect_denied(self, mock_run, mock_running):
        mock_running.return_value = True
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="HTTP/1.1 403 Forbidden\r\n\r\n",
            stderr="",
        )

        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "proxy")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "connect_denied")
        self.assertIn("allow", res.remediation.lower())

    @mock.patch("asb.podman.running")
    @mock.patch("subprocess.run")
    def test_probe_proxy_503_connect_failed(self, mock_run, mock_running):
        mock_running.return_value = True
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="HTTP/1.1 503 Service Unavailable\r\n\r\n",
            stderr="",
        )

        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "proxy")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "connect_failed")

    @mock.patch("asb.podman.running", return_value=False)
    def test_probe_proxy_proxy_stopped_inaccessible(self, mock_running):
        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "proxy")
        self.assertEqual(res.state, "unreachable")
        self.assertIn("proxy", res.code)

    @mock.patch("asb.podman.running")
    @mock.patch("subprocess.run")
    def test_probe_proxy_no_route(self, mock_run, mock_running):
        mock_running.return_value = True
        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="nc: connect to 1.1.1.1 port 53 failed: Network is unreachable\n",
        )

        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertEqual(res.component, "proxy")
        self.assertEqual(res.state, "unreachable")
        self.assertEqual(res.code, "no_route")


class TestProbeSSH(unittest.TestCase):
    @mock.patch("subprocess.run")
    def test_probe_ssh_success(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        res = probe_ssh(port=2222, user="v", key=Path("/fake/id_ed25519"), timeout=2.0)
        self.assertEqual(res.component, "ssh")
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.code, "ok")

    @mock.patch("subprocess.run")
    def test_probe_ssh_key_refused(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=255,
            stdout="",
            stderr="v@127.0.0.1: Permission denied (publickey).\n",
        )

        res = probe_ssh(port=2222, user="v", key=Path("/fake/id_ed25519"), timeout=2.0)
        self.assertEqual(res.component, "ssh")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "key_refused")

    @mock.patch("subprocess.run")
    def test_probe_ssh_connection_refused(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=255,
            stdout="",
            stderr="ssh: connect to host 127.0.0.1 port 2222: Connection refused\n",
        )

        res = probe_ssh(port=2222, user="v", key=Path("/fake/id_ed25519"), timeout=2.0)
        self.assertEqual(res.component, "ssh")
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "connection_refused")


class TestProbeWorkspace(unittest.TestCase):
    @mock.patch("asb.readiness.probe_proxy")
    @mock.patch("asb.readiness.probe_host")
    @mock.patch("asb.readiness.probe_ssh")
    @mock.patch("asb.readiness.probe_keyring")
    def test_probe_workspace_integration_and_isolation_from_auth(
        self, mock_keyring, mock_ssh, mock_host, mock_proxy
    ):
        failure = ProbeResult("proxy", "failed", "connect_denied", 10, "review_allowlist")
        mock_proxy.return_value = failure
        mock_host.return_value = ProbeResult("host", "healthy", "ok", 12, "")
        mock_ssh.return_value = ProbeResult("ssh", "healthy", "ok", 8, "")
        mock_keyring.return_value = ProbeResult("keyring", "healthy", "ok", 5, "")

        result = probe_workspace("test-readiness")
        self.assertIn("connect_denied", [item.code for item in result])
        self.assertNotIn("unauthenticated", [item.state for item in result])


class TestRuntimeCheck(unittest.TestCase):
    def test_runtime_check_proxy_role_success(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({
                "schemaVersion": 1,
                "workspace": "test-check",
                "containers": {
                    "proxy": {"name": "asb-test-check-proxy", "id": "p123"},
                    "agent": {"name": "asb-test-check-agent", "id": "a123"},
                }
            }, f)
            f.flush()

            with mock.patch("asb.runtime_check.probe_host", return_value=ProbeResult("host", "healthy", "ok", 5, "")), \
                 mock.patch("asb.runtime_check.wait_until", return_value=ProbeResult("proxy", "healthy", "ok", 10, "")):
                code = runtime_check.main(["--manifest", f.name, "--role", "proxy"])
                self.assertEqual(code, 0)

    def test_runtime_check_agent_role_failure(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({
                "schemaVersion": 1,
                "workspace": "test-check",
                "containers": {
                    "proxy": {"name": "asb-test-check-proxy", "id": "p123"},
                    "agent": {"name": "asb-test-check-agent", "id": "a123", "port": 2222},
                }
            }, f)
            f.flush()

            with mock.patch("asb.runtime_check.wait_until", return_value=ProbeResult("proxy", "failed", "connect_failed", 5, "fix")):
                code = runtime_check.main(["--manifest", f.name, "--role", "agent"])
                self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
