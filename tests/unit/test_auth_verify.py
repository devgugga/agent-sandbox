"""Testes de cli/asb/auth.py — verificacao real e orcamento explicito (A4).

Diferente de DIAGNOSTICO (status, Tarefa A2) e de LOGIN (Tarefa A3), esta
metade faz UMA chamada real ao fornecedor por `verify()`, sem retry, para
provar que o SERVIDOR aceitou a credencial — nao apenas que o cliente local
acha que esta logado. Nenhum teste aqui alcanca um fornecedor de verdade:
`podman.run`, `podman.running` e `readiness.probe_proxy` sao todos
simulados. O container e o proxy do workspace existem apenas como
argumentos capturados.

Contexto empirico (Tarefa A1, docs/validation/2026-09-07-auth-pilot-live.md):

* `agy -p ping` bloqueia ate 60s aguardando input quando deslogado — nunca
  usado aqui. `agy models` e um subcomando REAL e documentado (`agy --help`
  na versao fixada 1.1.27) que falha rapido sem credencial: o piloto mediu
  `exit 1` sem bloqueio no cliente de controle sem keyring.
* `--print-timeout` (default 5m0s) e uma flag real de `agy`, mas sua
  aplicabilidade a `agy models` (em vez de `-p/--print`) nao foi confirmada
  sem uma chamada real — por isso o orcamento de tempo desta tarefa usa
  APENAS o `timeout` externo do bash, nunca essa flag, para o agy.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb import auth, readiness  # noqa: E402
from asb.auth import AuthResult  # noqa: E402


def _healthy_probe():
    return readiness.ProbeResult("proxy", "healthy", "ok", 5, "")


def _unreachable_probe():
    return readiness.ProbeResult("proxy", "unreachable", "no_route", 5,
                                 "podman unshare --rootless-netns true")


def _ok(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return mock.MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestClassifyVerification(unittest.TestCase):
    """O teste verbatim do brief: rede ruim nunca vira logout."""

    def test_bad_network_never_becomes_unauthenticated(self):
        result = auth.classify_verification(
            "claude", 1, "connection timed out", network_ok=False)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.remediation, "login")

    def test_rate_limit_is_provider_error_not_unauthenticated(self):
        rate_limited = auth.classify_verification(
            "claude", 1, "HTTP 429", network_ok=True)
        self.assertEqual(rate_limited.state, "provider_error")

    def test_rate_limit_never_recommends_removing_the_credential(self):
        result = auth.classify_verification("codex", 1, "HTTP 429", network_ok=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_service_outage_is_provider_error_not_unauthenticated(self):
        result = auth.classify_verification(
            "codex", 1, "503 Service Unavailable", network_ok=True)
        self.assertEqual(result.state, "provider_error")
        self.assertNotIn("login", result.remediation.lower())

    def test_timeout_text_is_unreachable_even_when_network_ok_was_true(self):
        """O texto capturado da CHAMADA (nao a pre-checagem) tambem pode
        denunciar timeout -- e tem de cair na mesma categoria nao acusatoria."""
        result = auth.classify_verification(
            "agy", 124, "operation timed out", network_ok=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_gnu_timeout_returncode_alone_is_never_unauthenticated(self):
        """Codigo 124 (o `timeout` do coreutils matou o processo) sem texto
        algum: nao ha evidencia de credencial invalida em lugar nenhum."""
        result = auth.classify_verification("agy", 124, "", network_ok=True)
        self.assertNotEqual(result.state, "unauthenticated")

    def test_bare_403_is_never_unauthenticated(self):
        """403 puro tambem e a assinatura de uma negativa de ACL do proxy.
        So a evidencia PROPRIA do fornecedor pode virar `unauthenticated`."""
        result = auth.classify_verification(
            "claude", 1, "HTTP/1.1 403 Forbidden", network_ok=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_bare_401_is_never_unauthenticated(self):
        result = auth.classify_verification(
            "codex", 1, "401 Unauthorized", network_ok=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_provider_own_evidence_of_invalid_credential_is_unauthenticated(self):
        cases = {
            "claude": "authentication_error: invalid x-api-key",
            "codex": "Not logged in",
            "agy": "authentication required",
        }
        for provider, text in cases.items():
            with self.subTest(provider=provider):
                result = auth.classify_verification(provider, 1, text, network_ok=True)
                self.assertEqual(result.state, "unauthenticated")
                self.assertEqual(result.remediation, "asb-agent login")

    def test_success_is_returncode_zero_with_no_error_markers(self):
        result = auth.classify_verification("claude", 0, "ASB_AUTH_VERIFY_OK",
                                            network_ok=True)
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.remediation, "")

    def test_the_word_timeout_alone_does_not_false_positive_on_success(self):
        """Mesmo espirito do R4 (docs/domains/sandbox/known-regressions.md),
        mas em texto: 'timeout' sozinho aparece em nomes de flag e linhas de
        configuracao benignas (ex.: uma saida de sucesso do agy que
        mencione '--print-timeout'). Só 'timed out' (a frase) e evidencia
        real de falha de rede."""
        result = auth.classify_verification(
            "agy", 0, "print-timeout: 5m0s", network_ok=True)
        self.assertEqual(result.state, "authenticated")
        self.assertNotEqual(result.state, "unreachable")

    def test_429_substring_in_a_port_number_does_not_false_positive(self):
        """R4 do catalogo de regressoes (docs/domains/sandbox/known-
        regressions.md): `"403" in output` tambem casava a porta 40300.
        Aqui, uma porta ou id que contenha "429" como substring nao pode
        virar `provider_error` por limite de taxa."""
        result = auth.classify_verification(
            "claude", 0, "listening on port 14290, connected", network_ok=True)
        self.assertNotEqual(result.state, "provider_error")
        self.assertEqual(result.state, "authenticated")

    def test_503_substring_in_a_byte_count_does_not_false_positive(self):
        result = auth.classify_verification(
            "codex", 0, "processed 5003 bytes successfully", network_ok=True)
        self.assertNotEqual(result.state, "provider_error")
        self.assertEqual(result.state, "authenticated")

    def test_delimited_429_still_matches_as_rate_limit(self):
        """Guarda do proprio guarda: a delimitacao nao pode se tornar tao
        estrita a ponto de parar de reconhecer o codigo real."""
        for text in ("HTTP 429", "429 Too Many Requests", "status=429,"):
            with self.subTest(text=text):
                result = auth.classify_verification("claude", 1, text, network_ok=True)
                self.assertEqual(result.state, "provider_error")

    def test_delimited_503_still_matches_as_service_error(self):
        for text in ("HTTP/1.1 503 Service Unavailable", "(503)"):
            with self.subTest(text=text):
                result = auth.classify_verification("codex", 1, text, network_ok=True)
                self.assertEqual(result.state, "provider_error")

    def test_unrecognized_nonzero_output_is_unknown_not_unauthenticated(self):
        result = auth.classify_verification("claude", 1, "algo inesperado",
                                            network_ok=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_evidence_never_carries_the_raw_output(self):
        """A evidencia e sempre texto enlatado (categoria), nunca o `output`
        interpolado -- e ali que um token ou codigo OAuth apareceria."""
        secret = "sk-ant-oat01-SEGREDO-DE-VERDADE"
        for state_probe in (
            ("connection timed out", False),
            ("HTTP 429 " + secret, True),
            ("Not logged in " + secret, True),
        ):
            output, network_ok = state_probe
            with self.subTest(output=output):
                result = auth.classify_verification("claude", 1, output,
                                                    network_ok=network_ok)
                self.assertNotIn(secret, result.evidence)

    def test_every_state_produced_fits_the_deny_by_default_aggregate(self):
        """Guarda contra estado inventado: cada estado que classify_verification
        pode produzir tem de mapear para 0 (so authenticated), 1 ou 2 no
        agregado, nunca cair fora do conjunto que _aggregate_exit_code conhece."""
        scenarios = [
            ("claude", 1, "connection timed out", False),   # unreachable
            ("claude", 1, "HTTP 429", True),                 # provider_error
            ("claude", 1, "503 Service Unavailable", True),  # provider_error
            ("codex", 1, "Not logged in", True),              # unauthenticated
            ("claude", 0, "ASB_AUTH_VERIFY_OK", True),        # authenticated
            ("claude", 1, "algo inesperado", True),           # unknown
        ]
        for provider, rc, output, network_ok in scenarios:
            with self.subTest(output=output):
                result = auth.classify_verification(provider, rc, output, network_ok)
                code = auth._aggregate_exit_code([result])
                self.assertIn(code, (0, 1, 2))
                if result.state == "authenticated":
                    self.assertEqual(code, 0)
                else:
                    self.assertNotEqual(code, 0)


class TestVerifyClientCallBudget(unittest.TestCase):
    """Uma chamada por fornecedor por `verify_client`, sem retry, e sempre
    observavel via `call_budget()`."""

    def setUp(self):
        auth.reset_call_budget()

    def tearDown(self):
        auth.reset_call_budget()

    def test_no_call_is_spent_when_the_container_is_not_running(self):
        with mock.patch.object(auth.podman, "running", return_value=False), \
                mock.patch.object(auth.readiness, "probe_proxy") as probe, \
                mock.patch.object(auth.podman, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        probe.assert_not_called()
        run.assert_not_called()
        self.assertEqual(result.state, "unreachable")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)

    def test_no_call_is_spent_when_the_proxy_is_not_reachable(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_unreachable_probe()), \
                mock.patch.object(auth.podman, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        run.assert_not_called()
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)

    def test_exactly_one_call_is_spent_on_a_successful_verification(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")) as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")
        self.assertEqual(auth.call_budget()["claude"], 1)
        exec_calls = [c for c in run.call_args_list if c.args and c.args[0] == "exec"]
        self.assertEqual(len(exec_calls), 1, "mais de uma chamada real foi feita")

    def test_call_budget_is_per_provider(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")):
            auth.verify_client("claude", "asb-demo-agent")
            auth.verify_client("codex", "asb-demo-agent")

        budget = auth.call_budget()
        self.assertEqual(budget["claude"], 1)
        self.assertEqual(budget["codex"], 1)

    def test_reset_call_budget_clears_the_counter(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")):
            auth.verify_client("claude", "asb-demo-agent")
        self.assertEqual(auth.call_budget()["claude"], 1)
        auth.reset_call_budget()
        self.assertEqual(auth.call_budget(), {})


class TestVerifyClientTimeoutNeverBecomesLogout(unittest.TestCase):
    """A protecao mais critica desta tarefa: se a chamada em si expirar (o
    caso mais parecido com o bloqueio de 60s do agy deslogado, A1), o
    resultado nunca pode ser confundido com uma prova de que a conta esta
    deslogada."""

    def test_a_host_side_timeout_on_the_call_itself_is_unreachable(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    side_effect=subprocess.TimeoutExpired(cmd="podman", timeout=70)):
            result = auth.verify_client("agy", "asb-demo-agent")

        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotEqual(result.remediation, "asb-agent login")

    def test_a_timeout_still_counts_against_the_budget(self):
        """O orcamento e gasto na TENTATIVA, nao no sucesso: nao ha retry
        escondido so porque a chamada expirou."""
        auth.reset_call_budget()
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    side_effect=subprocess.TimeoutExpired(cmd="podman", timeout=70)):
            auth.verify_client("agy", "asb-demo-agent")
        self.assertEqual(auth.call_budget()["agy"], 1)
        auth.reset_call_budget()


class TestVerifyClientAgy(unittest.TestCase):
    """Sem prompt, sem `-p`: `agy models` e a chamada real (A1 confirmou o
    subcomando; A4 nao usa `agy -p`, que bloqueia 60s quando deslogado)."""

    def test_agy_verification_never_sends_a_prompt(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "modelo-a\nmodelo-b")) as run:
            result = auth.verify_client("agy", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")
        exec_call = next(c for c in run.call_args_list if c.args[0] == "exec")
        command = exec_call.args[-1]
        self.assertIn("agy models", command)
        self.assertNotIn(" -p ", f" {command} ")
        self.assertNotIn("--print", command)

    def test_agy_verification_closes_stdin(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "modelo-a")) as run:
            auth.verify_client("agy", "asb-demo-agent")

        exec_call = next(c for c in run.call_args_list if c.args[0] == "exec")
        self.assertIn("/dev/null", exec_call.args[-1])

    def test_agy_verification_failure_uses_provider_evidence(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    return_value=_ok(1, "", "authentication required")):
            result = auth.verify_client("agy", "asb-demo-agent")

        self.assertEqual(result.state, "unauthenticated")


class TestVerifyClientFormatEvidence(unittest.TestCase):
    """Evidencia de sucesso exige resposta no formato solicitado, nao um
    grep de 'ok'. Um exit 0 com resposta errada e um erro de FORMATO,
    registrado separado de erro de credencial."""

    def test_exit_zero_with_the_wrong_response_is_not_authenticated(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    return_value=_ok(0, "claro! aqui esta: ok")):
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertNotEqual(result.state, "authenticated")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_whitespace_is_normalized_before_comparison(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    return_value=_ok(0, "  ASB_AUTH_VERIFY_OK  \n")):
            result = auth.verify_client("codex", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")

    def test_a_help_string_never_counts_as_success_evidence(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.podman, "run",
                    return_value=_ok(0, "Usage: claude [options] [command] [prompt]")):
            result = auth.verify_client("claude", "asb-demo-agent")
        self.assertNotEqual(result.state, "authenticated")


class TestVerifyClientCommands(unittest.TestCase):
    """As chamadas usam flags CONFIRMADAS na versao fixada (A1/A4), stdin
    fechado, e nao usam flag alguma inventada."""

    def _exec_command(self, provider, run_mock):
        exec_call = next(c for c in run_mock.call_args_list if c.args[0] == "exec")
        return exec_call.args[-1]

    def test_claude_uses_dash_p_and_closes_stdin(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")) as run:
            auth.verify_client("claude", "asb-demo-agent")
        command = self._exec_command("claude", run)
        self.assertIn("claude -p", command)
        self.assertIn("/dev/null", command)
        self.assertIn("timeout", command)

    def test_codex_uses_exec_subcommand_not_the_interactive_default(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")) as run:
            auth.verify_client("codex", "asb-demo-agent")
        command = self._exec_command("codex", run)
        self.assertIn("codex exec", command)
        self.assertIn("/dev/null", command)

    def test_no_verify_command_uses_the_dead_slash_login(self):
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("/login", auth._verify_command(provider))

    def test_no_verify_command_uses_a_version_query(self):
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("--version", auth._verify_command(provider))

    def test_exec_runs_as_uid_1000(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "run",
                                  return_value=_ok(0, "ASB_AUTH_VERIFY_OK")) as run:
            auth.verify_client("claude", "asb-demo-agent")
        exec_call = next(c for c in run.call_args_list if c.args[0] == "exec")
        self.assertIn("1000", exec_call.args)


class TestVerifyCommand(unittest.TestCase):
    """`verify(ws, provider, json_output=...)`: mesmo schema de relatorio de
    `status()`, mas alimentado por `verify_client`."""

    def test_verify_all_calls_verify_client_once_per_provider(self):
        seen = []

        def fake_verify_client(provider, container):
            seen.append(provider)
            return AuthResult(provider, "authenticated", "t", "canned", "")

        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent"}), \
                mock.patch("sys.stdout", io.StringIO()):
            rc = auth.verify("demo", "all", json_output=True)

        self.assertEqual(seen, ["claude", "codex", "agy"])
        self.assertEqual(rc, 0)

    def test_verify_json_report_matches_status_schema(self):
        def fake_verify_client(provider, container):
            return AuthResult(provider, "unreachable", "2026-09-08T00:00:00Z",
                              "canned", "asb-agent doctor")

        out = io.StringIO()
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent"}), \
                mock.patch("sys.stdout", out):
            auth.verify("demo", "claude", json_output=True)

        data = json.loads(out.getvalue())
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["workspace"], "demo")
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["provider"], "claude")
        self.assertEqual(data["results"][0]["state"], "unreachable")

    def test_verify_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            auth.verify("demo", "gemini", json_output=True)

    def test_verify_never_calls_login_or_status_commands(self):
        """`verify` nunca muta estado: nenhuma chamada a login()/operator_lock."""
        with mock.patch("asb.auth.login") as login, \
                mock.patch("asb.auth.operator_lock") as lock, \
                mock.patch("asb.auth.verify_client",
                          return_value=AuthResult("claude", "authenticated",
                                                  "t", "x", "")), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent"}), \
                mock.patch("sys.stdout", io.StringIO()):
            auth.verify("demo", "claude", json_output=True)
        login.assert_not_called()
        lock.assert_not_called()

    def test_verify_secrets_never_reach_the_json_report(self):
        """O teste de log exigido pelo brief: fixtures com token, bearer e
        codigo OAuth nao podem aparecer no JSON persistido. `verify_client` e
        substituido por uma dublagem que devolveria esse texto se a
        implementacao interpolasse saida bruta -- e o relatorio JSON
        completo (nao so `AuthResult.evidence`) e verificado."""
        token = "sk-ant-oat01-TOKEN-DE-TESTE-NUNCA-REAL"
        bearer = "Bearer eyJhbGciOiJIUzI1NiJ9.FIXTURE.NUNCA-REAL"
        oauth_code = "oauth_code=4/0AeaYSHD-FIXTURE-NUNCA-REAL"
        fixture_secrets = f"{token} {bearer} {oauth_code}"

        def leaking_call(provider, returncode, output, network_ok):
            # Simula o que aconteceria SE classify_verification interpolasse
            # a saida bruta capturada -- o proprio guarda deste teste.
            return AuthResult(provider, "unknown", "t",
                              f"saida nao reconhecida (codigo {returncode})", "")

        def fake_verify_client(provider, container):
            # Chama a implementacao REAL de classify_verification para provar
            # que ela, de fato, nunca ecoa o fixture na evidencia.
            return auth.classify_verification(
                provider, 1, fixture_secrets, network_ok=True)

        out = io.StringIO()
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent"}), \
                mock.patch("sys.stdout", out):
            auth.verify("demo", "all", json_output=True)

        rendered = out.getvalue()
        for secret in (token, bearer, oauth_code):
            self.assertNotIn(secret, rendered)
        # Guarda do proprio teste: o relatorio tem de ser JSON valido com os
        # tres resultados, nao um relatorio vazio que passaria por acidente.
        data = json.loads(rendered)
        self.assertEqual(len(data["results"]), 3)


if __name__ == "__main__":
    unittest.main()
