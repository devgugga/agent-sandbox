"""Unit tests for cli/asb/readiness.py and cli/asb/runtime_check.py."""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import ast
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
        self.assertNotIn("unshare", res.remediation)

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
    def test_probe_proxy_403_substring_in_port_number_does_not_false_positive(self, mock_run, mock_running):
        """M1: o casamento de status virou substring nua ("403" in output),
        e a saida agora inclui a porta do alvo vinda do `nc -z -v`. Uma porta
        como 40300 contem "403" sem ser um status HTTP 403 — o casamento
        precisa ser delimitado (" 403 ")."""
        mock_running.return_value = True
        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="nc: connect to proxy.example port 40300 (tcp) failed: Connection refused\n",
        )

        res = probe_proxy("asb-ws-agent", "asb-ws-proxy", target="github.com:443", timeout=2.0)
        self.assertNotEqual(res.code, "connect_denied")
        self.assertEqual(res.state, "unreachable")
        self.assertEqual(res.code, "proxy_unreachable")

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
        self.assertNotIn("--rootless-netns", res.remediation)
        self.assertIn("asb-agent suspend", res.remediation)
        self.assertIn("asb-agent resume", res.remediation)


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
    @mock.patch("asb.podman.running", return_value=True)
    @mock.patch("asb.podman.out", return_value="0.0.0.0:2222")
    @mock.patch("asb.readiness.probe_proxy")
    @mock.patch("asb.readiness.probe_host")
    @mock.patch("asb.readiness.probe_ssh")
    @mock.patch("asb.readiness.probe_keyring")
    def test_probe_workspace_integration_and_isolation_from_auth(
        self, mock_keyring, mock_ssh, mock_host, mock_proxy, mock_out, mock_running
    ):
        failure = ProbeResult("proxy", "failed", "connect_denied", 10, "review_allowlist")
        mock_proxy.return_value = failure
        mock_host.return_value = ProbeResult("host", "healthy", "ok", 12, "")
        mock_ssh.return_value = ProbeResult("ssh", "healthy", "ok", 8, "")
        mock_keyring.return_value = ProbeResult("keyring", "healthy", "ok", 5, "")

        result = probe_workspace("test-readiness")
        self.assertIn("connect_denied", [item.code for item in result])
        self.assertNotIn("unauthenticated", [item.state for item in result])
        mock_ssh.assert_called_once_with(port=2222)
        mock_proxy.assert_called_once()
        mock_host.assert_called_once()
        mock_keyring.assert_called_once()

    @mock.patch("asb.podman.running", return_value=False)
    @mock.patch("asb.readiness.probe_proxy")
    @mock.patch("asb.readiness.probe_host")
    @mock.patch("asb.readiness.probe_ssh")
    @mock.patch("asb.readiness.probe_keyring")
    def test_probe_workspace_when_agent_not_running(
        self, mock_keyring, mock_ssh, mock_host, mock_proxy, mock_running
    ):
        mock_proxy.return_value = ProbeResult("proxy", "healthy", "ok", 10, "")
        mock_host.return_value = ProbeResult("host", "healthy", "ok", 12, "")
        mock_keyring.return_value = ProbeResult("keyring", "healthy", "ok", 5, "")

        result = probe_workspace("test-readiness")
        mock_ssh.assert_not_called()
        ssh_results = [item for item in result if item.component == "ssh"]
        self.assertEqual(len(ssh_results), 1)
        self.assertEqual(ssh_results[0].code, "agent_not_running")



class TestProbeSshIdentityAtCallSites(unittest.TestCase):
    """A#3: a sonda SSH tem de discar como o usuario REAL do host.

    `probe_ssh` trazia `user="v"` como default e apenas `lifecycle.up` o
    sobrescrevia. Os outros dois call sites — `probe_workspace` (consumido
    por `resume`) e `runtime_check` (gravado no ExecStartPost de TODA
    unidade systemd) — herdavam o literal. Consequencia: `--runtime systemd`
    so funcionava para um operador chamado `v`, e o ExecStartPost falhando
    marcava como failed um container saudavel. Estes testes atravessam os
    DOIS call sites com um usuario diferente e provam o argv do ssh: um
    teste que chamasse `probe_ssh` diretamente passaria mesmo com o literal
    de volta nos call sites.
    """

    @staticmethod
    def _capture_ssh_argv(captured: list[list[str]]):
        def fake_run(cmd, *args, **kwargs):
            captured.append(list(cmd))
            return mock.Mock(returncode=0, stdout="", stderr="")
        return fake_run

    def test_probe_workspace_uses_real_host_user_not_literal(self):
        captured: list[list[str]] = []
        healthy = ProbeResult("x", "healthy", "ok", 1, "")

        with mock.patch("getpass.getuser", return_value="alice"), \
             mock.patch("asb.readiness.probe_host", return_value=healthy), \
             mock.patch("asb.readiness.probe_proxy", return_value=healthy), \
             mock.patch("asb.readiness.probe_keyring", return_value=healthy), \
             mock.patch("asb.podman.running", return_value=True), \
             mock.patch("asb.podman.out", return_value="127.0.0.1:2222"), \
             mock.patch("subprocess.run", side_effect=self._capture_ssh_argv(captured)):
            results = probe_workspace("test-identity")

        ssh_results = [r for r in results if r.component == "ssh"]
        self.assertEqual([r.state for r in ssh_results], ["healthy"])
        self.assertEqual(len(captured), 1)
        self.assertIn("alice@127.0.0.1", captured[0])
        self.assertNotIn("v@127.0.0.1", captured[0])

    def test_runtime_check_agent_role_uses_real_host_user_not_literal(self):
        captured: list[list[str]] = []
        healthy = ProbeResult("x", "healthy", "ok", 1, "")

        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({
                "schemaVersion": 1,
                "workspace": "test-identity",
                "containers": {
                    "proxy": {"name": "asb-test-identity-proxy", "id": "p1"},
                    "agent": {"name": "asb-test-identity-agent", "id": "a1",
                              "port": 2222},
                },
            }, f)
            f.flush()

            with mock.patch("getpass.getuser", return_value="alice"), \
                 mock.patch("asb.runtime_check.probe_proxy", return_value=healthy), \
                 mock.patch("asb.runtime_check.probe_keyring", return_value=healthy), \
                 mock.patch("subprocess.run", side_effect=self._capture_ssh_argv(captured)):
                code = runtime_check.main(
                    ["--manifest", f.name, "--role", "agent"])

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("alice@127.0.0.1", captured[0])
        self.assertNotIn("v@127.0.0.1", captured[0])

    def test_probe_ssh_still_honours_explicit_user(self):
        captured: list[list[str]] = []
        with mock.patch("getpass.getuser", return_value="alice"), \
             mock.patch("subprocess.run", side_effect=self._capture_ssh_argv(captured)):
            res = probe_ssh(port=2222, user="bob", key=Path("/fake/key"),
                            timeout=2.0)
        self.assertEqual(res.state, "healthy")
        self.assertIn("bob@127.0.0.1", captured[0])


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


class TestNoRootlessNetnsAdvice(unittest.TestCase):
    """Emenda A: nenhuma orientacao pode mandar rodar `podman unshare --rootless-netns`.

    O piloto T2 mostrou que o comando nao recupera um namespace sem egresso e
    que o proprio `unshare` no boot era o produtor do defeito. `install.py` fica
    fora: ali o texto so serve para RECONHECER o drop-in legado e remove-lo.
    """

    def test_diagnostic_modules_never_recommend_the_rootless_netns_unshare(self):
        cli = Path(__file__).resolve().parents[2] / "cli" / "asb"
        # Tarefa 5 moveu a logica de diagnostico (e a maior parte da
        # orientacao que ela emite) de doctor.py para diagnostics/checks.py e
        # diagnostics/report.py; Tarefa 4 moveu a preparacao/orquestracao de
        # workspace de lifecycle.py para runtime/workspace.py e
        # runtime/storage.py. Uma lista fixa de nomes de modulo ESTREITA
        # silenciosamente quando o codigo se move — a rodada final de revisao
        # do plano de decomposicao (2026-09-21) achou esta lacuna: o guarda
        # continuava varrendo os quatro nomes originais e cobertura zero dos
        # modulos que hoje carregam a logica de risco. Mantidos os quatro
        # originais e somados os quatro que a decomposicao criou.
        for name in ("readiness.py", "doctor.py", "runtime_check.py",
                     "lifecycle.py", "diagnostics/checks.py",
                     "diagnostics/report.py", "runtime/workspace.py",
                     "runtime/storage.py"):
            with self.subTest(module=name):
                self.assertNotIn("--rootless-netns", (cli / name).read_text(encoding="utf-8"))


class TestHostPortsProbe(unittest.TestCase):
    """`host_ports` e uma pos-condicao prometida ao projeto: sem sonda, o `up`
    imprimia o JSON de conexao com o banco declarado simplesmente ausente."""

    def test_missing_listener_is_reported_with_the_port(self):
        def fake_run(argv, **kwargs):
            # dash nao tem /dev/tcp: a sonda precisa pedir bash explicitamente.
            assert "bash" in argv, argv
            port = argv[-1].rsplit("/", 1)[-1]
            return mock.Mock(returncode=0 if port == "5432" else 1, stdout="", stderr="")

        with mock.patch("asb.readiness.subprocess.run", side_effect=fake_run):
            res = readiness.probe_host_ports("asb-demo-agent", [5432, 18080])
        self.assertEqual(res.state, "failed")
        self.assertEqual(res.code, "no_listener")
        self.assertIn("18080", res.remediation)
        self.assertNotIn("5432", res.remediation)

    def test_every_listener_present_is_healthy(self):
        with mock.patch("asb.readiness.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            res = readiness.probe_host_ports("asb-demo-agent", [5432])
        self.assertEqual(res.state, "healthy")
        self.assertEqual(res.remediation, "")

    def test_no_declared_port_is_healthy_without_touching_podman(self):
        with mock.patch("asb.readiness.subprocess.run") as run:
            res = readiness.probe_host_ports("asb-demo-agent", [])
        run.assert_not_called()
        self.assertEqual(res.state, "healthy")


class TestProbeRemediationNeverCarriesCapturedOutput(unittest.TestCase):
    """A remediacao vai para o stderr do operador e para o journal. Interpolar
    saida capturada ali e o padrao que nao pode chegar aos caminhos de
    autenticacao, onde apareceriam codigos OAuth."""

    def test_unknown_proxy_response_points_at_the_logs(self):
        with mock.patch("asb.podman.running", return_value=True), \
             mock.patch("asb.readiness.subprocess.run",
                        return_value=mock.Mock(returncode=0,
                                               stdout="SEGREDO-DA-SAIDA", stderr="")):
            res = readiness.probe_proxy("asb-demo-agent", "asb-demo-proxy")
        self.assertEqual(res.code, "unknown_response")
        self.assertNotIn("SEGREDO-DA-SAIDA", res.remediation)
        self.assertIn("podman logs", res.remediation)

    def test_unexpected_http_status_points_at_the_logs(self):
        with mock.patch("asb.podman.running", return_value=True), \
             mock.patch("asb.readiness.subprocess.run",
                        return_value=mock.Mock(returncode=0,
                                               stdout="HTTP/1.1 418 SEGREDO", stderr="")):
            res = readiness.probe_proxy("asb-demo-agent", "asb-demo-proxy")
        self.assertEqual(res.code, "http_418")
        self.assertNotIn("SEGREDO", res.remediation)
        self.assertIn("podman logs", res.remediation)


class TestNoDirectPodmanLifecycleAdvice(unittest.TestCase):
    """R11: orientacao que dirige container supervisionado por fora do systemd.

    O keyring e os containers de workspace sao iniciados e reiniciados pelas
    unidades; `podman restart`/`podman start` mata o processo anexado e o
    `ExecStopPost` da unidade para o container de novo. Tres remediacoes do
    keyring carregaram essa orientacao ate a revisao final da T3.
    """

    def test_diagnostic_modules_never_tell_the_operator_to_drive_podman(self):
        # So o TEXTO que chega ao operador: comentario que diz "nunca
        # `podman restart`" e exatamente o que se quer preservar.
        #
        # Mesma lacuna da §"TestNoRootlessNetnsAdvice" acima (achado da
        # rodada final de revisao do plano de decomposicao, 2026-09-21):
        # esta tupla e fixa e a decomposicao moveu a construcao de texto de
        # remediacao (doctor.py -> diagnostics/checks.py e
        # diagnostics/report.py; parte de lifecycle.py -> runtime/workspace.py
        # e runtime/storage.py). Mantidos os cinco originais e somados os
        # quatro modulos que hoje constroem remediacao para container
        # supervisionado.
        cli = Path(__file__).resolve().parents[2] / "cli" / "asb"
        for name in ("keyring.py", "doctor.py", "readiness.py", "auth.py",
                     "lifecycle.py", "diagnostics/checks.py",
                     "diagnostics/report.py", "runtime/workspace.py",
                     "runtime/storage.py"):
            tree = ast.parse((cli / name).read_text(encoding="utf-8"))
            literals = [node.value for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            for forbidden in ("podman restart", "podman start "):
                with self.subTest(module=name, advice=forbidden):
                    self.assertEqual(
                        [lit for lit in literals if forbidden in lit], [])


class TestDomainPackDescribesTheSingleRuntime(unittest.TestCase):
    """T3: o domain pack e o que agentes e operador leem antes de agir.

    Ele descreveu o runtime removido (drop-in, `unless-stopped`, unshare,
    `--runtime`) meses depois de o codigo mudar. `known-regressions.md` fica
    fora: ali os termos antigos sao citados de proposito, como forma do defeito.
    """

    STALE = (
        "unless-stopped",
        "rootless-netns true",
        "ensure_rootless_netns",
        "adopt-runtime",
        "rollback-runtime",
        "--runtime",
        "podman start asb-",
    )

    def test_domain_pack_carries_no_advice_from_the_removed_runtime(self):
        pack = Path(__file__).resolve().parents[2] / "docs" / "domains" / "sandbox"
        docs = sorted(d for d in pack.glob("*.md") if d.name != "known-regressions.md")
        self.assertTrue(docs)
        for doc in docs:
            text = doc.read_text(encoding="utf-8")
            for term in self.STALE:
                with self.subTest(doc=doc.name, term=term):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
