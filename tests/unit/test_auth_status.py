"""Testes de cli/asb/auth.py — separacao de status de conta, rede e infraestrutura.

Tarefa A2: `auth.py` responde SOMENTE "esta a conta autenticada", nunca
"a infraestrutura esta saudavel" (isso e keyring.py/readiness.py) e nunca
inicia login, logout ou envia prompt — e diagnostico puro.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import auth  # noqa: E402


class TestAuthResult(unittest.TestCase):
    def test_is_frozen_dataclass_with_expected_fields(self):
        result = auth.AuthResult(
            provider="claude",
            state="authenticated",
            checked_at="2026-09-07T00:00:00Z",
            evidence="ok",
            remediation="",
        )
        self.assertEqual(result.provider, "claude")
        self.assertEqual(result.state, "authenticated")
        with self.assertRaises(Exception):
            result.state = "unknown"


# TestParseClaudeStatus migrou para tests/unit/test_agent_drivers.py
# (classe TestClaudeParseAuthStatus) junto com o proprio parser, que saiu
# de auth.py para ClaudeDriver.parse_auth_status na Tarefa 2.


class TestParseCodexStatus(unittest.TestCase):
    def test_authenticated(self):
        result = auth.parse_codex_status(0, "Logged in using ChatGPT\n", "")
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.provider, "codex")
        self.assertEqual(result.remediation, "")

    def test_unauthenticated(self):
        result = auth.parse_codex_status(1, "Not logged in\n", "")
        self.assertEqual(result.state, "unauthenticated")

    def test_explicit_negative_prevails_over_positive_substring(self):
        # "Not logged in" CONTEM a substring "logged in" -- a negativa
        # explicita tem que vencer, nunca ser lida como positiva.
        result = auth.parse_codex_status(1, "Not logged in\n", "")
        self.assertEqual(result.state, "unauthenticated")

    def test_explicit_negative_on_stderr_also_prevails(self):
        result = auth.parse_codex_status(0, "", "Not logged in")
        self.assertEqual(result.state, "unauthenticated")

    def test_unknown_format_does_not_become_authenticated(self):
        result = auth.parse_codex_status(0, "algo inesperado\n", "")
        self.assertEqual(result.state, "unknown")

    def test_comando_ausente(self):
        result = auth.parse_codex_status(
            127, "", "bash: line 1: codex: command not found")
        self.assertEqual(result.state, "unknown")

    def test_timeout(self):
        result = auth.parse_codex_status(124, "", "")
        self.assertEqual(result.state, "unknown")

    def test_authenticated_requires_returncode_zero(self):
        # Mensagem de sucesso mas codigo != 0 e contraditorio -> unknown.
        result = auth.parse_codex_status(1, "Logged in using ChatGPT\n", "")
        self.assertEqual(result.state, "unknown")


class TestCheckStatus(unittest.TestCase):
    def test_rejects_all(self):
        with self.assertRaises(ValueError):
            auth.check_status("all", "asb-ws-agent")

    def test_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            auth.check_status("bogus", "asb-ws-agent")

    def test_agy_returns_unknown_without_touching_podman(self):
        # A1: `agy -p ping` bloqueia ate 60s deslogado. check_status NUNCA
        # pode invocar podman/subprocess para agy.
        with mock.patch("asb.auth.podman.running") as mock_running, \
             mock.patch("asb.auth.podman.run") as mock_run:
            result = auth.check_status("agy", "asb-ws-agent")
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.provider, "agy")
        mock_running.assert_not_called()
        mock_run.assert_not_called()
        self.assertIn("verify", result.remediation.lower())
        # A4 entregou o `verify`: a orientacao e o comando real, com o
        # --workspace que ele exige, e nao "quando disponivel".
        self.assertEqual(result.remediation,
                         "asb-agent auth verify --workspace <id> --agent agy")

    def test_container_not_running_is_unreachable_not_unauthenticated(self):
        # Infra parada != conta deslogada.
        with mock.patch("asb.auth.podman.running", return_value=False), \
             mock.patch("asb.auth.podman.run") as mock_run:
            result = auth.check_status("claude", "asb-ws-agent")
        self.assertEqual(result.state, "unreachable")
        mock_run.assert_not_called()

    def test_claude_executes_exact_status_command_as_uid_1000_bounded(self):
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return mock.Mock(returncode=0, stdout='{"loggedIn": true}', stderr="")

        with mock.patch("asb.auth.podman.running", return_value=True), \
             mock.patch("asb.auth.podman.run", side_effect=fake_run):
            result = auth.check_status("claude", "asb-ws-agent")

        self.assertEqual(
            captured["args"],
            ("exec", "-u", "1000", "asb-ws-agent", "timeout", "10",
             "bash", "-lc", "claude auth status --json"),
        )
        self.assertEqual(captured["kwargs"].get("check"), False)
        self.assertTrue(captured["kwargs"].get("capture"))
        self.assertEqual(result.state, "authenticated")

    def test_codex_executes_exact_status_command(self):
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args
            return mock.Mock(returncode=0, stdout="Logged in using ChatGPT", stderr="")

        with mock.patch("asb.auth.podman.running", return_value=True), \
             mock.patch("asb.auth.podman.run", side_effect=fake_run):
            result = auth.check_status("codex", "asb-ws-agent")

        self.assertEqual(
            captured["args"],
            ("exec", "-u", "1000", "asb-ws-agent", "timeout", "10",
             "bash", "-lc", "codex login status"),
        )
        self.assertEqual(result.state, "authenticated")

    def test_status_commands_never_carry_a_mutating_verb(self):
        # "claude" migrou para ClaudeDriver.status_command (Tarefa 2); ver
        # tests/unit/test_agent_drivers.py::TestClaudeParseAuthStatus.
        self.assertEqual(auth.STATUS_COMMANDS["codex"], "codex login status")
        for command in auth.STATUS_COMMANDS.values():
            self.assertNotIn("logout", command)
            self.assertNotIn("/login", command)

    def test_podman_exec_failure_becomes_provider_error_not_unauthenticated(self):
        # PodmanError levantado pelo `podman exec` (o proprio comando do
        # fornecedor falhou ao rodar): erro de infraestrutura.
        with mock.patch("asb.auth.podman.running", return_value=True), \
             mock.patch("asb.auth.podman.run",
                        side_effect=auth.podman.PodmanError("podman nao encontrado no PATH")):
            result = auth.check_status("claude", "asb-ws-agent")
        self.assertEqual(result.state, "provider_error")

    def test_podman_running_check_failure_becomes_provider_error(self):
        # C1: `podman.running()` chama `podman ps`, que pode levantar
        # PodmanError sozinho (binario ausente, "podman ps" falhou -- servico
        # quebrado, permissao, rootless travado). Isso escapava de
        # check_status sem tratamento e virava 1 ("conta ausente") em vez de
        # 2 ("provider_error") -- exatamente a confusao infra/conta que a
        # Tarefa A2 existe para eliminar. A regressao anterior
        # (test_podman_missing_becomes_provider_error_not_unauthenticated)
        # mockava podman.running como True, entao NUNCA exercitava este
        # caminho apesar do nome prometer isso.
        with mock.patch(
            "asb.auth.podman.running",
            side_effect=auth.podman.PodmanError(
                "podman ps --filter name=^asb-test-nonexistent-agent$ "
                "--filter status=running --quiet falhou: ..."),
        ), mock.patch("asb.auth.podman.run") as mock_run:
            result = auth.check_status("claude", "asb-test-nonexistent-agent")
        self.assertEqual(result.state, "provider_error")
        # Se a checagem de "esta rodando" ja falhou por infra, o exec do
        # comando de status do fornecedor nunca deveria ser tentado.
        mock_run.assert_not_called()

    def test_running_check_host_side_timeout_becomes_provider_error(self):
        # I2: um `podman ps` travado no lado do HOST tem que ter um teto,
        # nao bloquear o CLI indefinidamente.
        with mock.patch(
            "asb.auth.podman.running",
            side_effect=subprocess.TimeoutExpired(cmd="podman ps", timeout=10),
        ), mock.patch("asb.auth.podman.run") as mock_run:
            result = auth.check_status("claude", "asb-ws-agent")
        self.assertEqual(result.state, "provider_error")
        mock_run.assert_not_called()

    def test_exec_host_side_timeout_becomes_provider_error(self):
        # I2: um `podman exec` travado no lado do HOST (nao apenas o
        # `timeout 10` interno ao container) tambem tem que virar
        # provider_error em vez de travar o CLI.
        with mock.patch("asb.auth.podman.running", return_value=True), \
             mock.patch(
                 "asb.auth.podman.run",
                 side_effect=subprocess.TimeoutExpired(cmd="podman exec", timeout=15)):
            result = auth.check_status("claude", "asb-ws-agent")
        self.assertEqual(result.state, "provider_error")

    def test_running_check_and_exec_pass_a_host_side_timeout(self):
        # Confirma que check_status realmente PASSA um timeout do lado do
        # host para as duas chamadas podman (nao so trata a excecao se ela
        # ocorrer) -- sem isso, nada limita um podman travado.
        running_kwargs = {}
        exec_kwargs = {}

        def fake_running(name, **kwargs):
            running_kwargs.update(kwargs)
            return True

        def fake_run(*args, **kwargs):
            exec_kwargs.update(kwargs)
            return mock.Mock(returncode=0, stdout='{"loggedIn": true}', stderr="")

        with mock.patch("asb.auth.podman.running", side_effect=fake_running), \
             mock.patch("asb.auth.podman.run", side_effect=fake_run):
            auth.check_status("claude", "asb-ws-agent")

        self.assertIsNotNone(running_kwargs.get("timeout"))
        self.assertGreater(running_kwargs["timeout"], 0)
        self.assertIsNotNone(exec_kwargs.get("timeout"))
        self.assertGreater(exec_kwargs["timeout"], 0)


class TestStatusCommand(unittest.TestCase):
    def test_status_rejects_invalid_provider(self):
        with self.assertRaises(ValueError):
            auth.status("ws", "bogus", json_output=True)

    def test_status_all_checks_three_providers_against_the_agent_container(self):
        calls = []

        def fake_check_status(provider, container):
            calls.append((provider, container))
            return auth.AuthResult(provider, "authenticated", "t", "ok", "")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "asb-ws-agent"}), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = auth.status("ws", "all", json_output=True)

        self.assertEqual({c[0] for c in calls}, {"claude", "codex", "agy"})
        self.assertTrue(all(c[1] == "asb-ws-agent" for c in calls))
        self.assertEqual(rc, 0)

    def test_status_single_provider_checks_only_that_one(self):
        calls = []

        def fake_check_status(provider, container):
            calls.append(provider)
            return auth.AuthResult(provider, "authenticated", "t", "ok", "")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "asb-ws-agent"}), \
             mock.patch("sys.stdout", io.StringIO()):
            auth.status("ws", "claude", json_output=True)

        self.assertEqual(calls, ["claude"])

    def test_json_report_is_schema1_with_utc_timestamp(self):
        def fake_check_status(provider, container):
            return auth.AuthResult(
                provider, "unauthenticated", "2026-09-07T00:00:00Z",
                evidence="loggedIn=false", remediation="asb-agent login")

        out = io.StringIO()
        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "asb-ws-agent"}), \
             mock.patch("sys.stdout", out):
            rc = auth.status("ws", "claude", json_output=True)

        data = json.loads(out.getvalue())
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["workspace"], "ws")
        self.assertTrue(data["checkedAt"].endswith("Z"))
        self.assertEqual(len(data["results"]), 1)
        r = data["results"][0]
        self.assertEqual(r["provider"], "claude")
        self.assertEqual(r["state"], "unauthenticated")
        self.assertEqual(rc, 1)

    def test_json_mode_prints_only_json_to_stdout(self):
        def fake_check_status(provider, container):
            return auth.AuthResult(provider, "authenticated", "t", "ok", "")

        out = io.StringIO()
        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "asb-ws-agent"}), \
             mock.patch("sys.stdout", out):
            auth.status("ws", "claude", json_output=True)

        # stdout deve conter EXATAMENTE um objeto JSON, nada mais.
        json.loads(out.getvalue())

    def test_aggregate_all_authenticated_is_zero(self):
        def fake_check_status(provider, container):
            return auth.AuthResult(provider, "authenticated", "t", "ok", "")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "c"}), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = auth.status("ws", "all", json_output=True)
        self.assertEqual(rc, 0)

    def test_aggregate_unauthenticated_present_is_one(self):
        def fake_check_status(provider, container):
            state = "unauthenticated" if provider == "claude" else "authenticated"
            return auth.AuthResult(provider, state, "t", "x", "y")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "c"}), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = auth.status("ws", "all", json_output=True)
        self.assertEqual(rc, 1)

    def test_aggregate_unknown_has_precedence_over_unauthenticated(self):
        def fake_check_status(provider, container):
            if provider == "claude":
                return auth.AuthResult(provider, "unauthenticated", "t", "x", "y")
            if provider == "codex":
                return auth.AuthResult(provider, "unknown", "t", "x", "y")
            return auth.AuthResult(provider, "authenticated", "t", "", "")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "c"}), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = auth.status("ws", "all", json_output=True)
        self.assertEqual(rc, 2)

    def test_agent_all_with_agy_unknown_never_reaches_zero_or_one(self):
        # Consequencia deliberada do design: agy e sempre "unknown" ate a
        # Tarefa A4 (verify), entao `--agent all` nunca retorna 0 nem 1
        # enquanto agy estiver no conjunto -- sempre 2.
        def fake_check_status(provider, container):
            state = "unknown" if provider == "agy" else "authenticated"
            return auth.AuthResult(provider, state, "t", "", "")

        with mock.patch("asb.auth.check_status", side_effect=fake_check_status), \
             mock.patch("asb.lifecycle.names", return_value={"agent": "c"}), \
             mock.patch("sys.stdout", io.StringIO()):
            rc = auth.status("ws", "all", json_output=True)
        self.assertEqual(rc, 2)

    def test_status_podman_running_failure_yields_provider_error_and_aggregate_two(self):
        # Regressao end-to-end de C1: exercita status() -> check_status()
        # REAL (nao mockado), com podman.running levantando PodmanError, e
        # confirma que o relatorio JSON reflete provider_error e o codigo
        # agregado e 2 -- nao 1 nem uma excecao escapando sem tratamento.
        out = io.StringIO()
        with mock.patch(
                "asb.auth.podman.running",
                side_effect=auth.podman.PodmanError(
                    "podman ps --filter name=^asb-test-nonexistent-agent$ "
                    "--filter status=running --quiet falhou: ..."),
             ), \
             mock.patch("asb.auth.podman.run") as mock_run, \
             mock.patch("asb.lifecycle.names",
                        return_value={"agent": "asb-test-nonexistent-agent"}), \
             mock.patch("sys.stdout", out):
            rc = auth.status("ws", "claude", json_output=True)

        data = json.loads(out.getvalue())
        self.assertEqual(data["results"][0]["state"], "provider_error")
        self.assertEqual(rc, 2)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
