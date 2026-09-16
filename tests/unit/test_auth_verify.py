"""Testes de cli/asb/auth.py — verificacao real e orcamento explicito (A4).

Diferente de DIAGNOSTICO (status, Tarefa A2) e de LOGIN (Tarefa A3), esta
metade faz UMA chamada real ao fornecedor por `verify()`, sem retry, para
provar que o SERVIDOR aceitou a credencial — nao apenas que o cliente local
acha que esta logado. Nenhum teste aqui alcanca um fornecedor de verdade:
`subprocess.run`, `podman.running`, `podman.out` e
`readiness.probe_proxy` sao todos simulados. O container, a porta SSH e o
proxy do workspace existem apenas como argumentos capturados.

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

import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def _gate_then(result):
    """Resultados do gate SSH observacional e da unica chamada real."""
    return [_ok(0), result]


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
        self.assertEqual(result.state, "unreachable")
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
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")
        self.assertNotEqual(result.state, "unreachable")

    def test_429_substring_in_a_port_number_does_not_false_positive(self):
        """R4 do catalogo de regressoes (docs/domains/sandbox/known-
        regressions.md): `"403" in output` tambem casava a porta 40300.
        Aqui, uma porta ou id que contenha "429" como substring nao pode
        virar `provider_error` por limite de taxa."""
        result = auth.classify_verification(
            "claude", 0, "listening on port 14290, connected", network_ok=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")

    def test_503_substring_in_a_byte_count_does_not_false_positive(self):
        result = auth.classify_verification(
            "codex", 0, "processed 5003 bytes successfully", network_ok=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")

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


class _SSHInfraCase(unittest.TestCase):
    """Contexto local minimo; a chamada ao fornecedor continua sintetica."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="asb-test-auth-key-")
        self.ssh_key = Path(self._tmp.name) / "id_ed25519"
        self.ssh_key.write_text("synthetic-not-a-real-key\n", encoding="utf-8")
        self._port_patch = mock.patch.object(
            auth.podman, "out", return_value="127.0.0.1:41234")
        self._key_patch = mock.patch.object(
            auth.lifecycle, "SSH_KEY", self.ssh_key)
        self._port_patch.start()
        self._key_patch.start()

    def tearDown(self):
        self._key_patch.stop()
        self._port_patch.stop()
        self._tmp.cleanup()


class TestVerifyClientCallBudget(_SSHInfraCase):
    """Uma chamada por fornecedor por `verify_client`, sem retry, e sempre
    observavel via `call_budget()`."""

    def setUp(self):
        super().setUp()
        auth.reset_call_budget()

    def tearDown(self):
        auth.reset_call_budget()
        super().tearDown()

    def test_no_call_is_spent_when_the_container_is_not_running(self):
        with mock.patch.object(auth.podman, "running", return_value=False), \
                mock.patch.object(auth.readiness, "probe_proxy") as probe, \
                mock.patch.object(auth.subprocess, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        probe.assert_not_called()
        run.assert_not_called()
        self.assertEqual(result.state, "unreachable")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)

    def test_no_call_is_spent_when_the_proxy_is_not_reachable(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_unreachable_probe()), \
                mock.patch.object(auth.subprocess, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        run.assert_not_called()
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)

    def test_exactly_one_call_is_spent_on_a_successful_verification(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(
                                      _ok(0, "ASB_AUTH_VERIFY_OK"))) as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")
        self.assertEqual(auth.call_budget()["claude"], 1)
        self.assertEqual(run.call_count, 2,
                         "gate SSH + exatamente uma chamada real")

    def test_call_budget_is_per_provider(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=[_ok(0),
                                               _ok(0, "ASB_AUTH_VERIFY_OK"),
                                               _ok(0),
                                               _ok(0, "ASB_AUTH_VERIFY_OK")]):
            auth.verify_client("claude", "asb-demo-agent")
            auth.verify_client("codex", "asb-demo-agent")

        budget = auth.call_budget()
        self.assertEqual(budget["claude"], 1)
        self.assertEqual(budget["codex"], 1)

    def test_reset_call_budget_clears_the_counter(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(
                                      _ok(0, "ASB_AUTH_VERIFY_OK"))):
            auth.verify_client("claude", "asb-demo-agent")
        self.assertEqual(auth.call_budget()["claude"], 1)
        auth.reset_call_budget()
        self.assertEqual(auth.call_budget(), {})


class TestVerifyClientTimeoutNeverBecomesLogout(_SSHInfraCase):
    """A protecao mais critica desta tarefa: se a chamada em si expirar (o
    caso mais parecido com o bloqueio de 60s do agy deslogado, A1), o
    resultado nunca pode ser confundido com uma prova de que a conta esta
    deslogada."""

    def test_a_host_side_timeout_on_the_call_itself_is_unreachable(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.subprocess, "run",
                    side_effect=[
                        _ok(0),
                        subprocess.TimeoutExpired(cmd="ssh", timeout=70),
                    ]):
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
                    auth.subprocess, "run",
                    side_effect=[
                        _ok(0),
                        subprocess.TimeoutExpired(cmd="ssh", timeout=70),
                    ]):
            auth.verify_client("agy", "asb-demo-agent")
        self.assertEqual(auth.call_budget()["agy"], 1)
        auth.reset_call_budget()


class TestVerifyClientAgy(_SSHInfraCase):
    """Sem prompt, sem `-p`: `agy models` e a chamada real (A1 confirmou o
    subcomando; A4 nao usa `agy -p`, que bloqueia 60s quando deslogado)."""

    def test_agy_verification_never_sends_a_prompt(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(_ok(
                                      0, "GEMINI_3_PRO\nCLAUDE_4_SONNET"))) as run:
            result = auth.verify_client("agy", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")
        command = run.call_args.args[0][-1]
        self.assertIn("asb-agy models", command)
        self.assertNotIn(" -p ", f" {command} ")
        self.assertNotIn("--print", command)

    def test_agy_verification_closes_stdin(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(_ok(
                                      0, "GEMINI_3_PRO\nCLAUDE_4_SONNET"))) as run:
            auth.verify_client("agy", "asb-demo-agent")

        self.assertIn("/dev/null", run.call_args.args[0][-1])

    def test_agy_verification_failure_uses_provider_evidence(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.subprocess, "run",
                    side_effect=_gate_then(
                        _ok(1, "", "authentication required"))):
            result = auth.verify_client("agy", "asb-demo-agent")

        self.assertEqual(result.state, "unauthenticated")

    def test_agy_exit_zero_requires_a_model_list_not_arbitrary_output(self):
        for output in ("", "command completed"):
            with self.subTest(output=output), \
                    mock.patch.object(auth.podman, "running", return_value=True), \
                    mock.patch.object(auth.readiness, "probe_proxy",
                                      return_value=_healthy_probe()), \
                    mock.patch.object(auth.subprocess, "run",
                                      side_effect=_gate_then(_ok(0, output))):
                result = auth.verify_client("agy", "asb-demo-agent")

            self.assertEqual(result.state, "unknown")

    def test_classify_agy_exit_zero_requires_a_model_list(self):
        result = auth.classify_verification(
            "agy", 0, "command completed", network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_agy_auth_marker_outranks_exit_zero(self):
        result = auth.classify_verification(
            "agy", 0, "authentication required", network_ok=True)
        self.assertEqual(result.state, "unauthenticated")

    def test_agy_prose_with_model_families_is_not_a_model_list(self):
        result = auth.classify_verification(
            "agy", 0,
            "Gemini is temporarily unavailable\n"
            "Claude is temporarily unavailable",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_every_agy_list_line_must_be_a_model_identifier(self):
        result = auth.classify_verification(
            "agy", 0,
            "gemini-2.5-pro\nClaude is temporarily unavailable",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_agy_tokenized_error_names_are_not_model_identifiers(self):
        outputs = (
            "gemini-unavailable\nclaude-unavailable",
            "error:gemini\nerror:claude",
        )
        for output in outputs:
            with self.subTest(output=output):
                result = auth.classify_verification(
                    "agy", 0, output, network_ok=True)
                self.assertEqual(result.state, "unknown")

    def test_versioned_identifiers_without_known_family_are_unknown(self):
        result = auth.classify_verification(
            "agy", 0,
            "modelo-2.5-valido\noutro-modelo-1.0",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_versioned_known_model_identifiers_remain_authenticated(self):
        result = auth.classify_verification(
            "agy", 0,
            "gemini-2.5-pro\nclaude-4-sonnet",
            network_ok=True)
        self.assertEqual(result.state, "authenticated")


# Saida REAL de `asb-agy models` capturada no piloto T2 em 2026-09-16, com o
# binario fixado 1.1.27, dentro do container do workspace. A1 nao preservou a
# saida bruta e a guarda foi escrita contra uma lembranca dela; e por isso que
# a classificacao so podia devolver `unknown`. O formato e
# `identificador<TAB>rotulo humano`, precedido de uma linha de prosa.
# Nomes de modelo nao sao credencial: preservados aqui de proposito, para que
# ninguem precise gastar outra chamada real so para reaprender o formato.
# `verify_client` monta `combined = f"{stdout}\n{stderr}"`, entao a prosa de
# stderr chega DEPOIS das linhas de modelo, nao antes. Medido: stdout traz so
# as linhas `identificador<TAB>rotulo`; stderr traz so
# `Fetching available models...`.
AGY_MODELS_REAL_STDOUT = (
    "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
    "gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"
    "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)\n"
    "gemini-3.1-pro-high\tGemini 3.1 Pro (High)\n"
    "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
    "claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)\n"
    "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
)
AGY_MODELS_REAL_STDERR = "Fetching available models...\n"
AGY_MODELS_REAL_OUTPUT = (
    f"{AGY_MODELS_REAL_STDOUT}\n{AGY_MODELS_REAL_STDERR}")


class TestAgyRealModelListFormat(unittest.TestCase):
    """A saida real tem cabecalho de prosa e duas colunas separadas por TAB.

    A guarda continua fechando: o que a torna valida e a COLUNA DO
    IDENTIFICADOR, nunca o rotulo humano, e qualquer linha nao conforme
    DEPOIS da primeira linha de modelo reprova a lista inteira.
    """

    def test_saida_real_do_agy_e_classificada_como_autenticada(self):
        result = auth.classify_verification(
            "agy", 0, AGY_MODELS_REAL_OUTPUT, network_ok=True)
        self.assertEqual(result.state, "authenticated")

    def test_cabecalho_de_prosa_sozinho_nao_autentica(self):
        result = auth.classify_verification(
            "agy", 0, "Fetching available models...", network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_linha_nao_conforme_depois_das_linhas_de_modelo_reprova(self):
        result = auth.classify_verification(
            "agy", 0,
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6\n"
            "Gemini is temporarily unavailable",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_rotulo_humano_nao_pode_sustentar_familia_nem_versao(self):
        # O identificador nao tem familia conhecida nem numero; so o rotulo
        # tem. Se a guarda olhasse a linha inteira, isto passaria.
        result = auth.classify_verification(
            "agy", 0,
            "modelo-desconhecido\tGemini 3.8 Flash (High)\n"
            "outro-desconhecido\tClaude Sonnet 4.6\n",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_uma_unica_linha_de_modelo_nao_e_lista(self):
        result = auth.classify_verification(
            "agy", 0,
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "Fetching available models...",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_prosa_neutra_de_stderr_depois_das_linhas_e_tolerada(self):
        # Ordem REAL: stdout (linhas de modelo) e so entao stderr (prosa).
        result = auth.classify_verification(
            "agy", 0,
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6\n"
            "\nFetching available models...\n",
            network_ok=True)
        self.assertEqual(result.state, "authenticated")

    def test_linha_nao_conforme_ENTRE_linhas_de_modelo_reprova(self):
        # Prosa no MEIO da lista continua reprovando: e o caso de um erro
        # interrompendo a listagem.
        result = auth.classify_verification(
            "agy", 0,
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "algo deu errado no meio\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6\n",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_identificador_com_sufixo_de_unidade_conta_como_versao(self):
        # `gpt-oss-120b-medium` existe na saida real. O numero vem colado a
        # uma unidade ("120b"), e a guarda original exigia digito sem letra
        # depois — reprovando uma linha de modelo legitima e, por tabela, a
        # lista inteira.
        self.assertTrue(auth._agy_model_row("gpt-oss-120b-medium"))

    def test_identificador_sem_digito_algum_continua_reprovado(self):
        # A razao de ser da regra de numero: nomes de erro tokenizados.
        for line in ("gemini-unavailable", "claude-unavailable",
                     "error:gemini"):
            with self.subTest(line=line):
                self.assertFalse(auth._agy_model_row(line))

    def test_cabecalho_que_cita_familia_de_modelo_reprova_a_lista(self):
        # Um cabecalho tolerado e prosa neutra ("Fetching available
        # models..."). Prosa que cita familia conhecida antes das linhas de
        # modelo e justamente o caso que poderia mascarar um erro.
        result = auth.classify_verification(
            "agy", 0,
            "Gemini is temporarily unavailable\n"
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6\n",
            network_ok=True)
        self.assertEqual(result.state, "unknown")

    def test_marcador_de_credencial_ainda_domina_a_lista_valida(self):
        result = auth.classify_verification(
            "agy", 0,
            AGY_MODELS_REAL_OUTPUT + "authentication required\n",
            network_ok=True)
        self.assertEqual(result.state, "unauthenticated")


class TestVerifyClientFormatEvidence(_SSHInfraCase):
    """Evidencia de sucesso exige resposta no formato solicitado, nao um
    grep de 'ok'. Um exit 0 com resposta errada e um erro de FORMATO,
    registrado separado de erro de credencial."""

    def test_exit_zero_with_the_wrong_response_is_not_authenticated(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.subprocess, "run",
                    side_effect=_gate_then(
                        _ok(0, "claro! aqui esta: ok"))):
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertNotEqual(result.state, "authenticated")
        self.assertNotEqual(result.state, "unauthenticated")


class TestVerifyClientInfrastructureGates(_SSHInfraCase):
    def setUp(self):
        super().setUp()
        auth.reset_call_budget()

    def tearDown(self):
        auth.reset_call_budget()
        super().tearDown()

    def test_missing_ssh_port_is_infrastructure_and_spends_no_call(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "out", return_value=""), \
                mock.patch.object(auth.subprocess, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "provider_error")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)
        run.assert_not_called()

    def test_invalid_ssh_port_is_infrastructure_and_spends_no_call(self):
        for mapping in ("invalid", "127.0.0.1:0", "127.0.0.1:70000"):
            with self.subTest(mapping=mapping), \
                    mock.patch.object(auth.podman, "running", return_value=True), \
                    mock.patch.object(auth.readiness, "probe_proxy",
                                      return_value=_healthy_probe()), \
                    mock.patch.object(auth.podman, "out", return_value=mapping), \
                    mock.patch.object(auth.subprocess, "run") as run:
                result = auth.verify_client("claude", "asb-demo-agent")

            self.assertEqual(result.state, "provider_error")
            self.assertEqual(auth.call_budget().get("claude", 0), 0)
            run.assert_not_called()

    def test_port_lookup_timeout_and_oserror_spend_no_call(self):
        failures = (
            subprocess.TimeoutExpired(cmd="podman port", timeout=10),
            OSError("synthetic preparation secret must not leak"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(auth.podman, "running", return_value=True), \
                    mock.patch.object(auth.readiness, "probe_proxy",
                                      return_value=_healthy_probe()), \
                    mock.patch.object(auth.podman, "out", side_effect=failure), \
                    mock.patch.object(auth.subprocess, "run") as run:
                result = auth.verify_client("claude", "asb-demo-agent")

            self.assertEqual(result.state, "provider_error")
            self.assertNotIn("synthetic preparation secret", result.evidence)
            self.assertEqual(auth.call_budget().get("claude", 0), 0)
            run.assert_not_called()

    def test_missing_ssh_identity_does_not_create_one_or_spend_a_call(self):
        missing = Path(self._tmp.name) / "missing-key"
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.lifecycle, "SSH_KEY", missing), \
                mock.patch.object(auth.lifecycle, "ensure_ssh_key") as ensure, \
                mock.patch.object(auth.subprocess, "run") as run:
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "provider_error")
        self.assertEqual(auth.call_budget().get("claude", 0), 0)
        ensure.assert_not_called()
        run.assert_not_called()

    def test_ssh_gate_failures_are_infrastructure_and_spend_no_call(self):
        gate_results = (
            _ok(255, stderr="Permission denied (publickey)"),
            _ok(255, stderr="Connection timed out"),
        )
        for gate_result in gate_results:
            with self.subTest(stderr=gate_result.stderr), \
                    mock.patch.object(auth.podman, "running", return_value=True), \
                    mock.patch.object(auth.readiness, "probe_proxy",
                                      return_value=_healthy_probe()), \
                    mock.patch.object(auth.subprocess, "run",
                                      return_value=gate_result) as run:
                result = auth.verify_client("claude", "asb-demo-agent")

            self.assertEqual(result.state, "unreachable")
            self.assertNotEqual(result.state, "unauthenticated")
            self.assertEqual(auth.call_budget().get("claude", 0), 0)
            self.assertEqual(run.call_count, 1)

    def test_ssh_gate_timeout_and_oserror_spend_no_call(self):
        failures = (
            (subprocess.TimeoutExpired(cmd="ssh true", timeout=10),
             "unreachable"),
            (OSError("synthetic gate secret must not leak"),
             "provider_error"),
        )
        for failure, expected_state in failures:
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(auth.podman, "running", return_value=True), \
                    mock.patch.object(auth.readiness, "probe_proxy",
                                      return_value=_healthy_probe()), \
                    mock.patch.object(auth.subprocess, "run",
                                      side_effect=failure):
                result = auth.verify_client("claude", "asb-demo-agent")

            self.assertEqual(result.state, expected_state)
            self.assertNotIn("synthetic gate secret", result.evidence)
            self.assertEqual(auth.call_budget().get("claude", 0), 0)

    def test_transport_drop_during_provider_call_is_infrastructure_and_counted(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run", side_effect=[
                    _ok(0),
                    _ok(255, stderr="Permission denied (publickey)"),
                ]):
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertEqual(auth.call_budget()["claude"], 1)

    def test_oserror_during_provider_call_is_categorical_and_counted(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run", side_effect=[
                    _ok(0),
                    OSError("synthetic execution secret must not leak"),
                ]):
            result = auth.verify_client("claude", "asb-demo-agent")

        self.assertEqual(result.state, "provider_error")
        self.assertNotIn("synthetic execution secret", result.evidence)
        self.assertEqual(auth.call_budget()["claude"], 1)

    def test_explicit_non_derivable_proxy_reaches_the_proxy_probe(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_unreachable_probe()) as probe, \
                mock.patch.object(auth.subprocess, "run"):
            auth.verify_client(
                "claude", "agent-name-not-derived-from-workspace",
                proxy_container="proxy-name-not-derived-from-agent")

        probe.assert_called_once_with(
            agent_container="agent-name-not-derived-from-workspace",
            proxy_container="proxy-name-not-derived-from-agent")


class TestVerifyClientFormatNormalization(_SSHInfraCase):

    def test_whitespace_is_normalized_before_comparison(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.subprocess, "run",
                    side_effect=_gate_then(
                        _ok(0, "  ASB_AUTH_VERIFY_OK  \n"))):
            result = auth.verify_client("codex", "asb-demo-agent")

        self.assertEqual(result.state, "authenticated")

    def test_a_help_string_never_counts_as_success_evidence(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(
                    auth.subprocess, "run",
                    side_effect=_gate_then(_ok(
                        0, "Usage: claude [options] [command] [prompt]"))):
            result = auth.verify_client("claude", "asb-demo-agent")
        self.assertNotEqual(result.state, "authenticated")


class TestVerifyClientCommands(_SSHInfraCase):
    """As chamadas usam flags CONFIRMADAS na versao fixada (A1/A4), stdin
    fechado, e nao usam flag alguma inventada."""

    def _exec_command(self, provider, run_mock):
        return run_mock.call_args.args[0][-1]

    def test_claude_uses_dash_p_and_closes_stdin(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(
                                      _ok(0, "ASB_AUTH_VERIFY_OK"))) as run:
            auth.verify_client("claude", "asb-demo-agent")
        command = self._exec_command("claude", run)
        self.assertIn("asb-claude -p", command)
        self.assertIn("/dev/null", command)
        self.assertIn("timeout", command)

    def test_codex_uses_exec_subcommand_not_the_interactive_default(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(
                                      _ok(0, "ASB_AUTH_VERIFY_OK"))) as run:
            auth.verify_client("codex", "asb-demo-agent")
        command = self._exec_command("codex", run)
        self.assertIn("asb-codex exec", command)
        self.assertIn("/dev/null", command)

    def test_no_verify_command_uses_the_dead_slash_login(self):
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("/login", auth._verify_command(provider))

    def test_no_verify_command_uses_a_version_query(self):
        for provider in ("claude", "codex", "agy"):
            with self.subTest(provider=provider):
                self.assertNotIn("--version", auth._verify_command(provider))

    def test_ssh_targets_the_host_user(self):
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.getpass, "getuser", return_value="tester"), \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(
                                      _ok(0, "ASB_AUTH_VERIFY_OK"))) as run:
            auth.verify_client("claude", "asb-demo-agent")
        self.assertIn("tester@127.0.0.1", run.call_args.args[0])

    def test_verify_uses_ssh_wrapper_and_explicit_synthetic_workdir(self):
        ssh_result = _ok(0, "ASB_AUTH_VERIFY_OK")
        with mock.patch.object(auth.podman, "running", return_value=True), \
                mock.patch.object(auth.readiness, "probe_proxy",
                                  return_value=_healthy_probe()), \
                mock.patch.object(auth.podman, "out",
                                  return_value="127.0.0.1:41234"), \
                mock.patch.object(auth.podman, "run",
                                  return_value=ssh_result) as podman_run, \
                mock.patch.object(auth.subprocess, "run",
                                  side_effect=_gate_then(ssh_result)) as ssh_run:
            result = auth.verify_client(
                "claude", "asb-demo-agent",
                proxy_container="asb-demo-proxy")

        self.assertEqual(result.state, "authenticated")
        podman_run.assert_not_called()
        self.assertEqual(ssh_run.call_count, 2)
        gate_args = ssh_run.call_args_list[0].args[0]
        args = ssh_run.call_args.args[0]
        self.assertEqual(gate_args[-1], "true")
        self.assertEqual(gate_args[:-1], args[:-1],
                         "gate e chamada devem usar o mesmo transporte")
        self.assertEqual(args[0], "ssh")
        self.assertIn("41234", args)
        remote_command = args[-1]
        self.assertIn("asb-claude", remote_command)
        self.assertIn("mktemp -d", remote_command)
        self.assertIn("cd ", remote_command)
        self.assertIn("/dev/null", remote_command)
        self.assertIs(ssh_run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(ssh_run.call_args.kwargs["timeout"], 70)

    def test_codex_discards_stream_output_and_reads_only_output_file(self):
        command = auth._verify_command("codex")
        self.assertIn('-o "$OUT"', command)
        self.assertIn("> /dev/null", command)
        self.assertIn('cat "$OUT"', command)


class TestCodexRemoteScript(unittest.TestCase):
    def _run_with_wrapper(self, wrapper_body: str):
        with tempfile.TemporaryDirectory(
                prefix="asb-test-auth-codex-wrapper-") as tmp_name:
            wrapper = Path(tmp_name) / "asb-codex"
            wrapper.write_text(
                "#!/usr/bin/env bash\nset -eu\n" + wrapper_body,
                encoding="utf-8")
            wrapper.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp_name}:{env['PATH']}"
            return subprocess.run(
                ["bash", "-c", auth._verify_command("codex")],
                capture_output=True, text=True, env=env, timeout=10)

    def test_codex_script_success_emits_only_the_output_file(self):
        result = self._run_with_wrapper(
            """out=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift 2; else shift; fi
done
printf '%s\\n' 'stream noise must be discarded'
printf '%s\\n' 'benign stderr must be hidden on success' >&2
printf '%s\\n' 'ASB_AUTH_VERIFY_OK' > "$out"
""")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ASB_AUTH_VERIFY_OK")
        self.assertEqual(result.stderr, "")

    def test_codex_script_failure_emits_stderr_and_preserves_exit_status(self):
        result = self._run_with_wrapper(
            """while [ "$#" -gt 0 ]; do shift; done
printf '%s\\n' 'stream noise must be discarded'
printf '%s\\n' 'authentication required' >&2
exit 23
""")

        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "authentication required")


class TestVerifyCommand(unittest.TestCase):
    """`verify(ws, provider, json_output=...)`: mesmo schema de relatorio de
    `status()`, mas alimentado por `verify_client`."""

    def test_verify_all_calls_verify_client_once_per_provider(self):
        seen = []

        def fake_verify_client(provider, container, *, proxy_container=None):
            seen.append(provider)
            return AuthResult(provider, "authenticated", "t", "canned", "")

        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent",
                                                "proxy": "asb-demo-proxy"}), \
                mock.patch("sys.stdout", io.StringIO()):
            rc = auth.verify("demo", "all", json_output=True)

        self.assertEqual(seen, ["claude", "codex", "agy"])
        self.assertEqual(rc, 0)

    def test_verify_passes_canonical_proxy_name_to_verify_client(self):
        seen = []

        def fake_verify_client(provider, container, *, proxy_container=None):
            seen.append((provider, container, proxy_container))
            return AuthResult(provider, "authenticated", "t", "canned", "")

        canonical = {
            "agent": "agent-name-not-derived-from-workspace",
            "proxy": "proxy-name-not-derived-from-agent",
        }
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names", return_value=canonical), \
                mock.patch("sys.stdout", io.StringIO()):
            auth.verify("demo", "claude", json_output=True)

        self.assertEqual(
            seen,
            [("claude", canonical["agent"], canonical["proxy"])])

    def test_verify_json_reports_per_invocation_call_budget(self):
        auth.reset_call_budget()
        auth._spend_call("claude")

        def fake_verify_client(provider, container, *, proxy_container=None):
            auth._spend_call(provider)
            return AuthResult(provider, "authenticated", "t", "canned", "")

        out = io.StringIO()
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(
                    auth.lifecycle, "names",
                    return_value={"agent": "a", "proxy": "p"}), \
                mock.patch("sys.stdout", out):
            auth.verify("demo", "all", json_output=True)

        self.assertEqual(
            json.loads(out.getvalue())["callBudget"],
            {"claude": 1, "codex": 1, "agy": 1})
        auth.reset_call_budget()

    def test_verify_json_report_matches_status_schema(self):
        def fake_verify_client(provider, container, *, proxy_container=None):
            return AuthResult(provider, "unreachable", "2026-09-08T00:00:00Z",
                              "canned", "asb-agent doctor")

        out = io.StringIO()
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent",
                                                "proxy": "asb-demo-proxy"}), \
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
                                  return_value={"agent": "asb-demo-agent",
                                                "proxy": "asb-demo-proxy"}), \
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

        def fake_verify_client(provider, container, *, proxy_container=None):
            # Chama a implementacao REAL de classify_verification para provar
            # que ela, de fato, nunca ecoa o fixture na evidencia.
            return auth.classify_verification(
                provider, 1, fixture_secrets, network_ok=True)

        out = io.StringIO()
        with mock.patch("asb.auth.verify_client", side_effect=fake_verify_client), \
                mock.patch.object(auth.lifecycle, "names",
                                  return_value={"agent": "asb-demo-agent",
                                                "proxy": "asb-demo-proxy"}), \
                mock.patch("sys.stdout", out):
            auth.verify("demo", "all", json_output=True)

        rendered = out.getvalue()
        for secret in (token, bearer, oauth_code):
            self.assertNotIn(secret, rendered)
        # Guarda do proprio teste: o relatorio tem de ser JSON valido com os
        # tres resultados, nao um relatorio vazio que passaria por acidente.
        data = json.loads(rendered)
        self.assertEqual(len(data["results"]), 3)


class TestLiveAuthDoubleOptIn(unittest.TestCase):
    def test_env_alone_does_not_enable_live_tests_during_broad_discovery(self):
        from tests.integration import test_provider_auth

        self.assertFalse(test_provider_auth._live_auth_file_selected(
            ["python3", "-m", "unittest", "discover", "-s", "tests/integration"]))

    def test_exact_discovery_pattern_selects_the_live_file(self):
        from tests.integration import test_provider_auth

        self.assertTrue(test_provider_auth._live_auth_file_selected(
            ["python3", "-m", "unittest", "discover", "-s", "tests/integration",
             "-p", "test_provider_auth.py"]))

    def test_supported_pattern_module_and_qualified_aliases_select_live(self):
        from tests.integration import test_provider_auth

        aliases = (
            ["unittest", "discover", "--pattern=test_provider_auth.py"],
            ["unittest", "tests.integration.test_provider_auth"],
            ["unittest", "tests.integration.test_provider_auth."
             "TestLiveProviderVerification."
             "test_verify_client_makes_exactly_one_call_per_provider"],
        )
        for argv in aliases:
            with self.subTest(argv=argv):
                self.assertTrue(
                    test_provider_auth._live_auth_file_selected(list(argv)))

    def test_explicit_file_path_selects_the_live_file(self):
        from tests.integration import test_provider_auth

        self.assertTrue(test_provider_auth._live_auth_file_selected(
            ["tests/integration/test_provider_auth.py"]))

    def test_live_auth_enabled_requires_environment_and_file_selection(self):
        from tests.integration import test_provider_auth

        selected = ["unittest", "discover", "-p", "test_provider_auth.py"]
        broad = ["unittest", "discover", "-s", "tests/integration"]
        with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "1"}), \
                mock.patch.object(sys, "argv", broad):
            self.assertFalse(test_provider_auth._live_auth_enabled())
        with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "1"}), \
                mock.patch.object(sys, "argv", selected):
            self.assertTrue(test_provider_auth._live_auth_enabled())
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(sys, "argv", selected):
            self.assertFalse(test_provider_auth._live_auth_enabled())

    def test_real_class_decorator_skips_broad_discovery_without_live_call(self):
        from tests.integration import test_provider_auth

        broad = ["unittest", "discover", "-s", "tests/integration"]
        try:
            with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "1"}), \
                    mock.patch.object(sys, "argv", broad):
                module = importlib.reload(test_provider_auth)
                self.assertTrue(
                    module.TestLiveProviderVerification.__unittest_skip__)
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                    module.TestLiveProviderVerification)
                with mock.patch.object(module.auth, "verify_client") as verify:
                    result = unittest.TestResult()
                    suite.run(result)
                self.assertEqual(len(result.skipped), 1)
                verify.assert_not_called()
        finally:
            with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "0"}), \
                    mock.patch.object(sys, "argv", broad):
                importlib.reload(test_provider_auth)

    def test_real_class_decorator_allows_explicit_double_opt_in(self):
        from tests.integration import test_provider_auth

        selected = [
            "unittest", "discover", "-s", "tests/integration",
            "-p", "test_provider_auth.py",
        ]
        blocked = ["unittest", "discover", "-s", "tests/integration"]
        try:
            with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "1"}), \
                    mock.patch.object(sys, "argv", selected):
                module = importlib.reload(test_provider_auth)
                self.assertFalse(
                    getattr(module.TestLiveProviderVerification,
                            "__unittest_skip__", False))
        finally:
            with mock.patch.dict(os.environ, {"ASB_LIVE_AUTH": "0"}), \
                    mock.patch.object(sys, "argv", blocked):
                module = importlib.reload(test_provider_auth)
                self.assertTrue(
                    module.TestLiveProviderVerification.__unittest_skip__)


class TestAgentsBehindProxyExitStatus(unittest.TestCase):
    def test_assertion_failure_remains_the_shell_suite_exit_status(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(
                prefix="asb-test-auth-shell-") as tmp_name:
            synthetic_root = Path(tmp_name)
            (synthetic_root / "tests").mkdir()
            (synthetic_root / "cli").mkdir()
            bin_dir = synthetic_root / "bin"
            bin_dir.mkdir()
            shutil.copy2(root / "tests/assert.sh",
                         synthetic_root / "tests/assert.sh")
            shutil.copy2(root / "tests/test-agents-behind-proxy.sh",
                         synthetic_root / "tests/test-agents-behind-proxy.sh")

            asb_agent = synthetic_root / "cli/asb-agent"
            asb_agent.write_text(
                """#!/usr/bin/env bash
case "$1" in
  up) printf '%s\\n' '{"port":2222}' ;;
  down) exit 0 ;;
  auth) printf '%s\\n' '{"results":[{"provider":"claude","state":"authenticated","evidence":"synthetic"},{"provider":"codex","state":"authenticated","evidence":"synthetic"},{"provider":"agy","state":"authenticated","evidence":"synthetic"}]}' ;;
esac
""", encoding="utf-8")
            asb_agent.chmod(0o755)

            ssh = bin_dir / "ssh"
            ssh.write_text(
                """#!/usr/bin/env bash
cmd="${!#}"
case "$cmd" in
  true) ;;
  *'echo $HTTPS_PROXY'*) echo 'synthetic-wrong-proxy' ;;
  *CLAUDE_CODE_SUBPROCESS_ENV_SCRUB*) echo '' ;;
  *asb-claude*) echo 0 ;;
  *'agy --version'*) echo '1.1.27' ;;
  *keyrings*) echo 'secrets' ;;
  *'npm ping'*) echo 'PONG' ;;
  *'npm install'*) ;;
  *'test -f'*) echo 'ok' ;;
esac
""", encoding="utf-8")
            ssh.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            result = subprocess.run(
                ["bash", str(synthetic_root / "tests/test-agents-behind-proxy.sh")],
                capture_output=True, text=True, env=env, timeout=30)

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FALHOU", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
