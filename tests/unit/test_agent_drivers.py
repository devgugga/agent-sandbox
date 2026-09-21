"""Testes dos drivers de provedor de agente (Tarefa 5; auth desde a Tarefa 2).

Um `AgentDriver` apenas RETORNA `LaunchCommand`; nenhum teste aqui inicia um
processo real, envia um prompt ou contata a API de um provedor. `probe()`
recebe sempre um runner falso injetado. Os caminhos de estado de sessao
(Codex/Claude) usam arvores `tempfile`, nunca o estado real do operador.

As regras de autenticacao de cada fornecedor (`parse_auth_status`,
`login_argv`, `verify_argv`, `classify_verification`) migraram de
`cli/asb/auth.py` para os drivers na Tarefa 2 da decomposicao (um
fornecedor por vez: Claude, depois Codex, depois Antigravity). Nenhum teste
aqui inicia um subprocesso, chama podman ou faz SSH real: `classify_verification`
e `parse_auth_status` recebem sempre um `CompletedProcess` sintetico.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.agents.antigravity import AntigravityDriver, _agy_model_row  # noqa: E402
from asb.agents.base import (  # noqa: E402
    AgentAvailability, AuthResult, LaunchCommand, Lifetime, ResumeUnsupported,
    SessionEvidence,
)
from asb.agents.claude import ClaudeDriver  # noqa: E402
from asb.agents.codex import CodexDriver  # noqa: E402


def _completed(returncode: int, stdout: str = "", stderr: str = "") \
        -> subprocess.CompletedProcess:
    """`CompletedProcess` sintetico: nenhum teste de classificacao aqui
    executa um processo real."""
    return subprocess.CompletedProcess((), returncode, stdout, stderr)


class _FakeRun:
    """Runner falso injetado em `probe()`: nunca executa um processo real."""

    def __init__(self, outputs: dict[str, str | Exception]):
        self._outputs = outputs
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(self, argv, timeout=None):
        self.calls.append((tuple(argv), timeout))
        key = argv[-1]  # "--version" ou "--help"
        result = self._outputs[key]
        if isinstance(result, Exception):
            raise result
        return result


CLAUDE_UUID = "0f0e0d0c-0b0a-4000-8000-00000000abcd"
CODEX_BYPASS = "--dangerously-bypass-approvals-and-sandbox"
CODEX_TRUST = 'projects."/repo".trust_level="trusted"'
CLAUDE_BYPASS = "--dangerously-skip-permissions"


class TestLaunchAndResumeArgv(unittest.TestCase):
    """Argv exatos. Claude e Codex rodam sem prompts de permissao, como o
    Orca os lanca (o sandbox e a fronteira de isolamento); Antigravity nao
    recebe flag de bypass."""

    def test_codex_launch_argv(self):
        self.assertEqual(CodexDriver().launch(Path("/repo")).argv,
                         ("codex", CODEX_BYPASS, "-c", CODEX_TRUST))

    def test_codex_resume_argv(self):
        # `codex resume [OPTIONS] [SESSION_ID]`: a flag vem antes do id e o
        # override vem DEPOIS do id (o binario 0.155.0 da imagem aceita
        # `-c` apos o posicional; ver o relatorio desta tarefa).
        self.assertEqual(
            CodexDriver().resume(Path("/repo"), "abc").argv,
            ("codex", "resume", CODEX_BYPASS, "abc", "-c", CODEX_TRUST))

    def test_claude_resume_argv(self):
        # `--resume [value]` tem valor opcional: o id vem logo depois dele.
        self.assertEqual(
            ClaudeDriver().resume(Path("/repo"), CLAUDE_UUID).argv,
            ("claude", "--resume", CLAUDE_UUID, CLAUDE_BYPASS))

    def test_antigravity_resume_raises_when_session_id_unprovable(self):
        # session_id_provable=False e um fato ESTATICO da instalacao
        # neste host (nenhum diretorio de estado local encontrado para
        # `agy`): resume() recusa mesmo sem nunca ter sido probado, para
        # nao prometer uma resumption que ninguem provou. O binario da
        # imagem do container e o gate autoritativo real (ver
        # docs/validation/2026-09-17-agent-session-contracts.md).
        with self.assertRaises(ResumeUnsupported):
            AntigravityDriver().resume(Path("/repo"), "abc")

    def test_claude_launch_argv_carries_the_assigned_session_id(self):
        self.assertEqual(
            ClaudeDriver().launch(Path("/repo"), CLAUDE_UUID).argv,
            ("claude", "--session-id", CLAUDE_UUID, CLAUDE_BYPASS))

    def test_claude_launch_requires_a_canonical_uuid(self):
        for bad in (None, "", "abc", "-rf", CLAUDE_UUID.upper(),
                    "{" + CLAUDE_UUID + "}", CLAUDE_UUID.replace("-", ""),
                    CLAUDE_UUID + " ", "x" + CLAUDE_UUID[1:]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ClaudeDriver().launch(Path("/repo"), bad)

    def test_only_claude_assigns_the_session_id_at_launch(self):
        self.assertTrue(ClaudeDriver.assigns_session_id_at_launch)
        self.assertFalse(CodexDriver.assigns_session_id_at_launch)
        self.assertFalse(AntigravityDriver.assigns_session_id_at_launch)

    def test_drivers_without_launch_ids_refuse_one(self):
        # Um id passado a quem nao o usa seria descartado em silencio.
        for driver in (CodexDriver(), AntigravityDriver()):
            with self.subTest(driver=driver.kind), \
                    self.assertRaises(ValueError):
                driver.launch(Path("/repo"), CLAUDE_UUID)

    def test_antigravity_launch_argv(self):
        self.assertEqual(AntigravityDriver().launch(Path("/repo")).argv, ("agy",))

    def test_launch_returns_launch_command_type(self):
        self.assertIsInstance(CodexDriver().launch(Path("/repo")), LaunchCommand)


class TestCodexTrustOverride(unittest.TestCase):
    """O Codex guarda o trust do diretorio em `~/.codex/config.toml`, que
    no sandbox vive no volume COMPARTILHADO de credenciais e e reescrito
    pelo manifesto do entrypoint a cada start. Por isso o driver passa o
    trust como override POR LANCAMENTO, escopado ao checkout da sessao."""

    def test_launch_trusts_the_session_checkout(self):
        argv = CodexDriver().launch(Path("/work/my repo")).argv
        self.assertEqual(
            argv[-2:],
            ("-c", 'projects."/work/my repo".trust_level="trusted"'))

    def test_resume_trusts_the_session_checkout(self):
        argv = CodexDriver().resume(Path("/work/my repo"), "abc").argv
        self.assertEqual(
            argv[-2:],
            ("-c", 'projects."/work/my repo".trust_level="trusted"'))

    def test_launch_omits_the_override_for_a_path_with_a_quote(self):
        self.assertEqual(CodexDriver().launch(Path('/work/a"b')).argv,
                         ("codex", CODEX_BYPASS))

    def test_launch_omits_the_override_for_a_path_with_a_backslash(self):
        self.assertEqual(CodexDriver().launch(Path("/work/a\\b")).argv,
                         ("codex", CODEX_BYPASS))

    def test_launch_omits_the_override_for_a_path_with_a_newline(self):
        self.assertEqual(CodexDriver().launch(Path("/work/a\nb")).argv,
                         ("codex", CODEX_BYPASS))

    def test_resume_omits_the_override_for_a_path_with_a_quote(self):
        self.assertEqual(CodexDriver().resume(Path('/work/a"b'), "abc").argv,
                         ("codex", "resume", CODEX_BYPASS, "abc"))

    def test_resume_omits_the_override_for_a_path_with_a_backslash(self):
        self.assertEqual(CodexDriver().resume(Path("/work/a\\b"), "abc").argv,
                         ("codex", "resume", CODEX_BYPASS, "abc"))

    def test_resume_omits_the_override_for_a_path_with_a_newline(self):
        self.assertEqual(CodexDriver().resume(Path("/work/a\nb"), "abc").argv,
                         ("codex", "resume", CODEX_BYPASS, "abc"))

    def test_launch_omits_the_override_for_a_path_with_an_equals_sign(self):
        # O `-c` parte em `key=value` no PRIMEIRO `=`: um `=` dentro da
        # chave citada parte a chave ao meio e o Codex recusa a config
        # inteira ("config could not be loaded", medido em 0.155.0) — pior
        # que o prompt de trust, porque a sessao nem comecaria.
        self.assertEqual(CodexDriver().launch(Path("/work/a=b")).argv,
                         ("codex", CODEX_BYPASS))

    def test_resume_omits_the_override_for_a_path_with_an_equals_sign(self):
        self.assertEqual(CodexDriver().resume(Path("/work/a=b"), "abc").argv,
                         ("codex", "resume", CODEX_BYPASS, "abc"))

    def test_launch_still_refuses_a_session_id(self):
        # O override nao pode contornar a checagem da base.
        with self.assertRaises(ValueError):
            CodexDriver().launch(Path("/repo"), "abc")

    def test_resume_still_validates_the_session_id(self):
        with self.assertRaises(ValueError):
            CodexDriver().resume(Path("/repo"), "-rm -rf")

class TestAntigravityResumeArgvOnceProvable(unittest.TestCase):
    """A construcao do argv (`("agy", "--conversation", id)`) continua no
    codigo, alcancavel assim que uma mudanca futura provar a fonte do
    session-id do Antigravity e virar `session_id_provable` para `True`
    (ver docs/validation/2026-09-17-agent-session-contracts.md). Esta
    subclasse de teste e o que evita redescobrir esse argv depois do
    checkpoint humano."""

    def test_resume_argv_once_session_id_is_provable(self):
        class _ProvenAntigravityDriver(AntigravityDriver):
            session_id_provable = True

        self.assertEqual(
            _ProvenAntigravityDriver().resume(Path("/repo"), "abc").argv,
            ("agy", "--conversation", "abc"))


class TestResumeValidatesProviderSessionId(unittest.TestCase):
    """Um provider-session-id invalido nunca vira argv — reusa a validacao
    de `asb.sessions.model.ProviderSessionId` (Tarefa 1)."""

    def test_rejects_whitespace(self):
        with self.assertRaises(ValueError):
            CodexDriver().resume(Path("/repo"), "has space")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            ClaudeDriver().resume(Path("/repo"), "")

    def test_rejects_shell_metacharacters(self):
        # Nao usa AntigravityDriver aqui: seu resume() recusa por
        # ResumeUnsupported antes mesmo de validar o id (ver
        # TestLaunchAndResumeArgv), entao a rama de ProviderSessionId
        # invalido precisa de um driver com session_id_provable=True.
        with self.assertRaises(ValueError):
            ClaudeDriver().resume(Path("/repo"), "abc;rm -rf")

    def test_rejects_leading_dash(self):
        # A provider session id that comes back looking like a CLI flag
        # (e.g. a filename stem an agent wrote as "--dangerously-skip-
        # permissions") must never reach argv unvalidated.
        with self.assertRaises(ValueError):
            ClaudeDriver().resume(Path("/repo"), "--dangerously-skip-permissions")


class TestProbeMissingBinary(unittest.TestCase):
    def test_missing_binary_is_unavailable(self):
        run = _FakeRun({"--version": FileNotFoundError(2, "no such file")})
        availability = CodexDriver().probe(run)
        self.assertFalse(availability.available)
        self.assertIsNone(availability.version)
        self.assertFalse(availability.resume_supported)
        self.assertIn("codex", availability.reason)

    def test_missing_binary_resume_raises(self):
        driver = CodexDriver()
        driver.probe(_FakeRun({"--version": FileNotFoundError(2, "nope")}))
        with self.assertRaises(ResumeUnsupported):
            driver.resume(Path("/repo"), "abc")


class TestProbeVersionTimeout(unittest.TestCase):
    def test_version_timeout_is_unavailable(self):
        run = _FakeRun({
            "--version": subprocess.TimeoutExpired(cmd=["claude", "--version"],
                                                    timeout=5.0),
        })
        availability = ClaudeDriver().probe(run)
        self.assertFalse(availability.available)
        self.assertFalse(availability.resume_supported)
        self.assertIsNone(availability.version)

    def test_probe_passes_five_second_timeout(self):
        run = _FakeRun({
            "--version": "codex-cli 0.154.0",
            "--help": "Usage: codex [OPTIONS]\n\nCommands:\n  resume  ...\n",
        })
        driver = CodexDriver()
        driver.probe(run)
        self.assertEqual(run.calls, [
            (("codex", "--version"), 5.0),
            (("codex", "--help"), 5.0),
        ])


class TestProbeUnknownVersionOutput(unittest.TestCase):
    def test_unrecognized_version_output_is_unavailable(self):
        run = _FakeRun({"--version": "not a version string at all"})
        availability = AntigravityDriver().probe(run)
        self.assertFalse(availability.available)
        self.assertIsNone(availability.version)
        self.assertFalse(availability.resume_supported)

    def test_empty_version_output_is_unavailable(self):
        run = _FakeRun({"--version": ""})
        availability = CodexDriver().probe(run)
        self.assertFalse(availability.available)
        self.assertIsNone(availability.version)
        self.assertFalse(availability.resume_supported)


class TestProbeHelpFails(unittest.TestCase):
    """Rama nao nomeada explicitamente no brief, mas alcancavel: --version
    responde, --help falha. O driver fica disponivel (versao conhecida)
    porem sem resume confirmado."""

    def test_help_failure_keeps_available_but_drops_resume(self):
        run = _FakeRun({
            "--version": "codex-cli 0.154.0",
            "--help": subprocess.TimeoutExpired(cmd=["codex", "--help"],
                                                 timeout=5.0),
        })
        driver = CodexDriver()
        availability = driver.probe(run)
        self.assertTrue(availability.available)
        self.assertEqual(availability.version, "0.154.0")
        self.assertFalse(availability.resume_supported)
        with self.assertRaises(ResumeUnsupported):
            driver.resume(Path("/repo"), "abc")


class TestProbeHelpLacksResumeOption(unittest.TestCase):
    """Rama distinta de session_id_provable: aqui a opcao de resume esta
    literalmente ausente do --help de um provider com fonte de session-id
    comprovada (Codex)."""

    def test_help_without_resume_option_reports_unsupported(self):
        run = _FakeRun({
            "--version": "codex-cli 0.154.0",
            "--help": "Usage: codex [OPTIONS]\n\nCommands:\n  login  ...\n",
        })
        driver = CodexDriver()
        availability = driver.probe(run)
        self.assertTrue(availability.available)
        self.assertEqual(availability.version, "0.154.0")
        self.assertFalse(availability.resume_supported)

    def test_help_without_resume_option_makes_resume_raise(self):
        run = _FakeRun({
            "--version": "2.1.275 (Claude Code)",
            "--help": "Usage: claude [options]\n\nOptions:\n  -p, --print\n",
        })
        driver = ClaudeDriver()
        driver.probe(run)
        with self.assertRaises(ResumeUnsupported):
            driver.resume(Path("/repo"), "abc")


class TestProbeCleanRun(unittest.TestCase):
    def test_codex_probe_confirms_resume_when_option_present(self):
        run = _FakeRun({
            "--version": "codex-cli 0.154.0",
            "--help": "Commands:\n  resume  Resume a previous session\n",
        })
        availability = CodexDriver().probe(run)
        self.assertEqual(availability, AgentAvailability(
            available=True, version="0.154.0", resume_supported=True,
            reason="ok", probed_fully=True))

    def test_claude_probe_confirms_resume_when_option_present(self):
        run = _FakeRun({
            "--version": "2.1.275 (Claude Code)",
            "--help": "Options:\n  -r, --resume [value]  Resume a session\n",
        })
        availability = ClaudeDriver().probe(run)
        self.assertTrue(availability.resume_supported)
        self.assertEqual(availability.version, "2.1.275")


class TestProbedFully(unittest.TestCase):
    """`probed_fully` so e True quando `--version` e `--help` responderam."""

    def test_complete_probes_are_probed_fully(self):
        cases = (
            (CodexDriver(), "codex-cli 0.154.0",
             "Commands:\n  resume  Resume a previous session\n"),
            (CodexDriver(), "codex-cli 0.154.0", "Commands:\n  login\n"),
            (AntigravityDriver(), "1.2.5", "  --conversation   Resume\n"),
        )
        for driver, version, help_text in cases:
            with self.subTest(driver=driver.kind, help_text=help_text):
                availability = driver.probe(
                    _FakeRun({"--version": version, "--help": help_text}))
                self.assertTrue(availability.probed_fully)

    def test_each_failure_branch_is_not_probed_fully(self):
        timeout = subprocess.TimeoutExpired(cmd=["codex"], timeout=5.0)
        cases = {
            "version raises": {"--version": FileNotFoundError(2, "nope")},
            "version unrecognized": {"--version": "not a version"},
            "help raises": {"--version": "codex-cli 0.154.0",
                            "--help": timeout},
        }
        for name, outputs in cases.items():
            with self.subTest(name):
                availability = CodexDriver().probe(_FakeRun(outputs))
                self.assertFalse(availability.probed_fully)


class TestAntigravitySessionIdUnproven(unittest.TestCase):
    """Antigravity: mesmo com --conversation presente no --help do
    binario de HOST, resume_supported nunca e True neste host porque a
    fonte do session-id nao esta comprovada (session_id_provable=False).
    O binario da imagem do container e o gate autoritativo real."""

    def test_probe_never_confirms_resume_even_with_option_present(self):
        run = _FakeRun({
            "--version": "1.2.5",
            "--help": "  --conversation   Resume a previous conversation by ID\n",
        })
        availability = AntigravityDriver().probe(run)
        self.assertTrue(availability.available)
        self.assertEqual(availability.version, "1.2.5")
        self.assertFalse(availability.resume_supported)

    def test_discover_session_id_always_none(self):
        evidence = SessionEvidence(scan_root=None, known_paths=frozenset(),
                                    new_paths=frozenset({Path("/x/y.jsonl")}))
        self.assertIsNone(AntigravityDriver().discover_session_id(evidence))

    def test_capture_before_and_after_are_always_empty(self):
        driver = AntigravityDriver()
        baseline = driver.capture_before(Path("/repo"))
        self.assertIsNone(baseline.scan_root)
        self.assertEqual(baseline.known_paths, frozenset())
        after = driver.capture_after(baseline)
        self.assertEqual(after.new_paths, frozenset())


class TestCodexSessionEvidence(unittest.TestCase):
    def _driver(self, sessions_root: Path) -> CodexDriver:
        return CodexDriver(sessions_root=sessions_root)

    def test_zero_new_files_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_two_matching_new_files_return_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            (sessions / "rollout-a.jsonl").write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "id-a"}}) + "\n")
            (sessions / "rollout-b.jsonl").write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "id-b"}}) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_exactly_one_new_file_with_session_meta_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-2026-09-17T00-00-00-abc.jsonl"
            new_file.write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "session-meta-id"}}) + "\n"
                + json.dumps({"type": "response_item"}) + "\n")
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset({new_file}))
            self.assertEqual(driver.discover_session_id(after),
                              "session-meta-id")

    def test_new_file_without_session_meta_first_line_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-other.jsonl"
            new_file.write_text(json.dumps({"type": "response_item"}) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_new_file_with_session_meta_missing_id_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-no-id.jsonl"
            new_file.write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo"}}) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_new_file_with_invalid_json_first_line_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-not-json.jsonl"
            new_file.write_text("not json at all\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_new_file_with_non_dict_payload_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-non-dict-payload.jsonl"
            new_file.write_text(
                json.dumps({"type": "session_meta", "payload": "oops"}) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_new_file_with_non_object_first_line_returns_none(self):
        # A first line that is valid JSON but not an object (e.g. a JSON
        # array) must not crash discover_session_id() with AttributeError
        # from calling .get() on a non-dict.
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-non-object-line.jsonl"
            new_file.write_text(json.dumps([1]) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_new_file_that_cannot_be_read_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            new_file = sessions / "rollout-unreadable.jsonl"
            new_file.write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "session-meta-id"}}) + "\n")
            after = driver.capture_after(baseline)
            new_file.unlink()  # o candidato existia na varredura, mas sumiu
            self.assertIsNone(driver.discover_session_id(after))

    def test_pre_existing_file_is_not_a_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            (sessions / "rollout-pre-existing.jsonl").write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "pre-existing"}}) + "\n")
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))

    def _write_meta(self, path: Path, payload: object) -> None:
        # Um thread do usuario (`source` string) salvo quando o teste diz
        # outra coisa: a rejeicao testada e a do campo que o teste varia.
        if isinstance(payload, dict):
            payload = {"source": "cli", "thread_source": "user", **payload}
        path.write_text(json.dumps({"type": "session_meta",
                                    "payload": payload}) + "\n")

    def test_capture_records_cwd_in_both_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._driver(Path(tmp))
            baseline = driver.capture_before(Path("/repo"))
            after = driver.capture_after(baseline)
            self.assertEqual(baseline.cwd, Path("/repo"))
            self.assertEqual(after.cwd, Path("/repo"))

    def test_candidate_with_matching_cwd_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            self._write_meta(sessions_root / "rollout-mine.jsonl",
                             {"cwd": "/repo", "id": "mine"})
            after = driver.capture_after(baseline)
            self.assertEqual(driver.discover_session_id(after), "mine")

    def test_only_new_file_from_another_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            self._write_meta(sessions_root / "rollout-other.jsonl",
                             {"cwd": "/other-checkout", "id": "other"})
            after = driver.capture_after(baseline)
            self.assertEqual(len(after.new_paths), 1)
            self.assertIsNone(driver.discover_session_id(after))

    def test_other_checkout_file_does_not_make_own_file_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            self._write_meta(sessions_root / "rollout-other.jsonl",
                             {"cwd": "/other-checkout", "id": "other"})
            self._write_meta(sessions_root / "rollout-mine.jsonl",
                             {"cwd": "/repo", "id": "mine"})
            after = driver.capture_after(baseline)
            self.assertEqual(driver.discover_session_id(after), "mine")

    def test_missing_or_non_string_cwd_is_rejected(self):
        for payload in ({"id": "no-cwd"}, {"cwd": None, "id": "null-cwd"},
                        {"cwd": ["/repo"], "id": "list-cwd"}):
            with self.subTest(payload=payload), \
                    tempfile.TemporaryDirectory() as tmp:
                sessions_root = Path(tmp)
                driver = self._driver(sessions_root)
                baseline = driver.capture_before(Path("/repo"))
                self._write_meta(sessions_root / "rollout-x.jsonl", payload)
                after = driver.capture_after(baseline)
                self.assertIsNone(driver.discover_session_id(after))

    def test_evidence_without_cwd_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_file = Path(tmp) / "rollout-x.jsonl"
            self._write_meta(new_file, {"cwd": "/repo", "id": "x"})
            evidence = SessionEvidence(scan_root=Path(tmp),
                                       new_paths=frozenset({new_file}))
            self.assertIsNone(
                self._driver(Path(tmp)).discover_session_id(evidence))


class TestClaudeNeverDiscovers(unittest.TestCase):
    """O id do Claude e atribuido no lancamento (`--session-id`): o driver
    nao varre nada, nem com um `sessions_root` que ganha um arquivo novo."""

    def test_new_jsonl_in_the_project_dir_is_never_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            project_dir = sessions_root / "-repo"
            project_dir.mkdir()
            driver = ClaudeDriver(sessions_root=sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            (project_dir / f"{CLAUDE_UUID}.jsonl").write_text("{}\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(baseline.scan_root)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))


# Formas reais do `session_meta` observadas no piloto (ids sinteticos): o
# thread do usuario e o subagente que `approvals_reviewer = "auto_review"`
# abre na primeira mensagem, com o MESMO cwd.
STARTED = datetime(2026, 9, 19, 14, 36, 14, tzinfo=timezone.utc)
USER_ID = "11111111-1111-4111-8111-111111111111"
SUBAGENT_ID = "22222222-2222-4222-8222-222222222222"


def _user_meta(session_id: str = USER_ID, cwd: str = "/repo",
               timestamp: object = "2026-09-19T14:36:19.412Z") -> dict:
    return {"id": session_id, "session_id": session_id,
            "timestamp": timestamp, "cwd": cwd, "originator": "codex-tui",
            "cli_version": "0.153.4", "source": "cli",
            "thread_source": "user", "model_provider": "openai"}


def _subagent_meta(session_id: str = SUBAGENT_ID, cwd: str = "/repo",
                   timestamp: str = "2026-09-19T14:36:19.431Z") -> dict:
    return {"id": session_id, "session_id": session_id,
            "timestamp": timestamp, "cwd": cwd, "originator": "codex-tui",
            "cli_version": "0.153.4",
            "source": {"subagent": {"other": "guardian_review"}},
            "thread_source": "guardian_review",
            "parent_thread_id": USER_ID, "multi_agent_version": 1,
            "model_provider": "openai"}


class _CodexCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.driver = CodexDriver(sessions_root=self.root)

    def write(self, name: str, payload: dict) -> Path:
        path = self.root / "2026" / "09" / "19" / f"rollout-{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"timestamp": "2026-09-19T14:36:19Z",
                                    "type": "session_meta",
                                    "payload": payload}) + "\n"
                        + json.dumps({"type": "response_item"}) + "\n")
        return path

    def discover_new(self) -> str | None:
        """Descoberta do start: so arquivos criados depois do baseline."""
        return self.driver.discover_session_id(
            self.driver.capture_after(self._baseline))

    def discover_since(self, not_before=STARTED, claimed=frozenset(),
                       contended=()) -> str | None:
        """Descoberta preguicosa: todo arquivo atual, sem baseline."""
        return self.driver.discover_session_id(self.driver.capture_since(
            Path("/repo"), not_before, claimed, contended))


class TestCodexIgnoresSubagentThreads(_CodexCase):
    def setUp(self) -> None:
        super().setUp()
        self._baseline = self.driver.capture_before(Path("/repo"))

    def test_user_thread_is_accepted_and_the_subagent_rejected(self):
        self.write("user", _user_meta())
        self.write("subagent", _subagent_meta())
        self.assertEqual(self.discover_new(), USER_ID)

    def test_a_subagent_only_candidate_set_yields_nothing(self):
        self.write("subagent", _subagent_meta())
        self.assertIsNone(self.discover_new())

    def test_two_user_threads_yield_nothing(self):
        self.write("a", _user_meta())
        self.write("b", _user_meta("33333333-3333-4333-8333-333333333333"))
        self.write("subagent", _subagent_meta())
        self.assertIsNone(self.discover_new())

    def test_only_a_user_thread_source_counts(self):
        # `codex exec` grava `source: "exec"`; so `thread_source: "user"`
        # (o que os 23 threads nao-subagente do host tem) passa.
        exec_run = {k: v for k, v in _user_meta().items()
                    if k != "thread_source"}
        for payload in ({**exec_run, "source": "exec"}, exec_run,
                        {**_user_meta(), "thread_source": "exec"},
                        {**_user_meta(), "thread_source": None}):
            with self.subTest(payload=payload):
                path = self.write("x", payload)
                self.assertIsNone(self.discover_new())
                path.unlink()

    def test_hostile_first_lines_yield_no_id_and_never_raise(self):
        # Abaixo do teto de 64 KiB: `[` aninhado estoura a recursao do
        # parser (`RecursionError`) e um inteiro de 5000 digitos passa do
        # limite de conversao (`ValueError` que nao e `JSONDecodeError`).
        self.write("user", _user_meta())
        for bomb in ("[" * 60000, '{"a": ' + "1" * 5000 + "}"):
            with self.subTest(bomb=bomb[:8]):
                path = self.root / "bomb.jsonl"
                path.write_text(bomb + "\n")
                self.assertEqual(self.discover_new(), USER_ID)
                path.unlink()

    def test_either_subagent_marker_alone_rejects(self):
        dict_source = {**_user_meta(), "source": {"subagent": "x"}}
        with_parent = {**_user_meta(), "parent_thread_id": SUBAGENT_ID}
        no_source = {k: v for k, v in _user_meta().items() if k != "source"}
        for payload in (dict_source, with_parent, no_source,
                        {**_user_meta(), "source": None},
                        {**_user_meta(), "source": 7}):
            with self.subTest(payload=payload):
                path = self.write("x", payload)
                self.assertIsNone(self.discover_new())
                path.unlink()


class TestCodexLazyDiscovery(_CodexCase):
    """Sem baseline (a sessao comecou ha muito): todo arquivo atual e
    candidato, filtrado por cwd, thread do usuario, `timestamp` do
    `session_meta` >= inicio da sessao e id ainda nao reclamado."""

    def test_capture_since_sees_files_that_existed_before(self):
        self.write("user", _user_meta())
        evidence = self.driver.capture_since(
            Path("/repo"), STARTED, frozenset({"x"}),
            (Lifetime(None, None),))
        self.assertEqual(len(evidence.new_paths), 1)
        self.assertEqual(evidence.cwd, Path("/repo"))
        self.assertEqual(evidence.not_before, STARTED)
        self.assertEqual(evidence.claimed_ids, frozenset({"x"}))
        self.assertEqual(evidence.contended, (Lifetime(None, None),))
        self.assertEqual(self.discover_since(), USER_ID)

    def test_user_thread_at_or_after_the_start_is_accepted(self):
        self.write("user", _user_meta(timestamp="2026-09-19T14:36:14Z"))
        self.write("subagent", _subagent_meta())
        self.assertEqual(self.discover_since(), USER_ID)

    def test_candidate_older_than_the_start_yields_nothing(self):
        self.write("user", _user_meta(timestamp="2026-09-19T14:36:13.999Z"))
        self.assertIsNone(self.discover_since())

    def test_already_claimed_candidate_yields_nothing(self):
        self.write("user", _user_meta())
        self.assertIsNone(self.discover_since(claimed=frozenset({USER_ID})))

    def test_claimed_candidate_does_not_make_the_other_ambiguous(self):
        other = "33333333-3333-4333-8333-333333333333"
        self.write("mine", _user_meta())
        self.write("theirs", _user_meta(other))
        self.assertEqual(self.discover_since(claimed=frozenset({other})),
                         USER_ID)

    def test_unusable_timestamp_yields_nothing(self):
        for timestamp in (None, 7, "", "yesterday", "2026-09-19T14:36:19"):
            with self.subTest(timestamp=timestamp):
                path = self.write("user", _user_meta(timestamp=timestamp))
                self.assertIsNone(self.discover_since())
                path.unlink()

    def test_a_candidate_inside_a_sibling_lifetime_yields_nothing(self):
        self.write("user", _user_meta(timestamp="2026-09-19T14:36:19Z"))
        t = datetime(2026, 9, 19, 14, 36, 19, tzinfo=timezone.utc)
        for window in (Lifetime(STARTED, None), Lifetime(STARTED, t),
                       Lifetime(t, t), Lifetime(None, None)):
            with self.subTest(window=window):
                self.assertIsNone(self.discover_since(contended=(window,)))

    def test_a_candidate_outside_every_sibling_lifetime_is_accepted(self):
        self.write("user", _user_meta(timestamp="2026-09-19T14:36:19Z"))
        before = datetime(2026, 9, 19, 14, 30, tzinfo=timezone.utc)
        after = datetime(2026, 9, 19, 14, 40, tzinfo=timezone.utc)
        self.assertEqual(self.discover_since(contended=(
            Lifetime(before, STARTED), Lifetime(after, None))), USER_ID)

    def test_contended_evidence_requires_a_timestamp(self):
        self.write("user", _user_meta(timestamp=None))
        evidence = SessionEvidence(
            scan_root=self.root, cwd=Path("/repo"),
            new_paths=frozenset(self.root.rglob("*.jsonl")),
            contended=(Lifetime(STARTED, STARTED),))
        self.assertIsNone(self.driver.discover_session_id(evidence))

    def test_other_checkout_is_still_rejected(self):
        self.write("user", _user_meta(cwd="/other"))
        self.assertIsNone(self.discover_since())

    def test_without_sessions_root_capture_since_is_empty(self):
        evidence = CodexDriver().capture_since(Path("/repo"), STARTED,
                                               frozenset())
        self.assertIsNone(evidence.scan_root)
        self.assertEqual(evidence.new_paths, frozenset())


class TestNoHostDefaultScanRoot(unittest.TestCase):
    """Sem `sessions_root`, nenhum driver le o diretorio de estado do HOST,
    mesmo quando ele existe e ganha um arquivo novo durante a captura."""

    def _fake_home(self, tmp: str):
        home = Path(tmp) / "home"
        return home, mock.patch.dict(
            "os.environ", {"HOME": str(home), "CODEX_HOME": str(home / ".codex")})

    def test_codex_without_sessions_root_ignores_host_codex_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, env = self._fake_home(tmp)
            sessions = home / ".codex" / "sessions" / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            with env, mock.patch("pathlib.Path.home", return_value=home):
                driver = CodexDriver()
                baseline = driver.capture_before(Path("/repo"))
                (sessions / "rollout-host.jsonl").write_text(
                    json.dumps({"type": "session_meta",
                                "payload": {"id": "host-session"}}) + "\n")
                after = driver.capture_after(baseline)
            self.assertIsNone(baseline.scan_root)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))


class TestHostileSessionVolume(unittest.TestCase):
    """O volume de sessao e gravavel pelo agente: um symlink, um FIFO ou uma
    primeira linha gigante nunca viram candidato nem id, voltam logo e nao
    levantam. Nenhum teste le `/dev/zero`; o FIFO so e aberto numa thread
    daemon com prazo, destravada pelo proprio teste."""

    META = {"type": "session_meta", "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "evil"}}

    def _codex(self, tmp: str) -> tuple[Path, Path, CodexDriver]:
        root = Path(tmp) / "codex-sessions"
        outside = Path(tmp) / "outside"
        root.mkdir()
        outside.mkdir()
        return root, outside, CodexDriver(sessions_root=root)

    def _bounded(self, fn, unblock: Path | None = None):
        """Roda `fn` numa thread daemon com prazo de 5 s. Se ela ficar presa
        num FIFO, abre o lado de escrita para solta-la e falha o teste."""
        import threading
        box: dict[str, object] = {}

        def target():
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - relatado abaixo
                box["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(5)
        if thread.is_alive():
            if unblock is not None:
                import os
                fd = os.open(unblock, os.O_WRONLY | os.O_NONBLOCK)
                os.close(fd)
            thread.join(5)
            self.fail("discovery blocked on a FIFO in the session volume")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def test_codex_symlink_to_a_file_outside_the_root_is_not_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, outside, driver = self._codex(tmp)
            target = outside / "real.jsonl"
            target.write_text(json.dumps(self.META) + "\n")
            baseline = driver.capture_before(Path("/repo"))
            (root / "evil.jsonl").symlink_to(target)
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))

    def test_codex_symlink_to_endless_content_is_not_read(self):
        # Um arquivo regular grande, sem quebra de linha, FORA da raiz,
        # faz o papel de `/dev/zero` sem nunca le-lo.
        with tempfile.TemporaryDirectory() as tmp:
            root, outside, driver = self._codex(tmp)
            big = outside / "zero"
            with big.open("wb") as handle:
                handle.truncate(64 * 1024 * 1024)
            baseline = driver.capture_before(Path("/repo"))
            (root / "evil.jsonl").symlink_to(big)
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            evidence = SessionEvidence(scan_root=root,
                                       new_paths=frozenset({root / "evil.jsonl"}),
                                       cwd=Path("/repo"))
            # Mesmo entregue direto a descoberta, o symlink nao e seguido.
            self.assertIsNone(driver.discover_session_id(evidence))

    def test_codex_fifo_is_not_a_candidate_and_never_blocks(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root, _outside, driver = self._codex(tmp)
            baseline = driver.capture_before(Path("/repo"))
            fifo = root / "evil.jsonl"
            os.mkfifo(fifo)
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            evidence = SessionEvidence(scan_root=root,
                                       new_paths=frozenset({fifo}),
                                       cwd=Path("/repo"))
            # Mesmo entregue direto a descoberta, o FIFO nao trava.
            self.assertIsNone(self._bounded(
                lambda: driver.discover_session_id(evidence), unblock=fifo))

    def test_codex_oversized_first_line_yields_no_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _outside, driver = self._codex(tmp)
            baseline = driver.capture_before(Path("/repo"))
            record = {"type": "session_meta",
                      "payload": {"cwd": "/repo", "source": "cli", "thread_source": "user", "id": "evil",
                                  "pad": "x" * (128 * 1024)}}
            (root / "big.jsonl").write_text(json.dumps(record) + "\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_codex_scan_root_that_is_a_symlink_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside"
            outside.mkdir()
            root = Path(tmp) / "codex-sessions"
            root.symlink_to(outside)
            driver = CodexDriver(sessions_root=root)
            baseline = driver.capture_before(Path("/repo"))
            (outside / "host.jsonl").write_text(json.dumps(self.META) + "\n")
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))

# ---------------------------------------------------------------------------
# Autenticacao — Claude (Tarefa 2, commit 1). Exemplos verbatim herdados de
# tests/unit/test_auth_status.py::TestParseClaudeStatus e
# tests/unit/test_auth_verify.py::TestClassifyVerification /
# tests/unit/test_login_flow.py::TestLoginCommandTable.
# ---------------------------------------------------------------------------


class TestClaudeParseAuthStatus(unittest.TestCase):
    """Exemplos verbatim do brief da tarefa A2, agora contra o driver."""

    def test_brief_example_unauthenticated(self):
        result = ClaudeDriver().parse_auth_status(_completed(1, '{"loggedIn": false}'))
        self.assertEqual(result.state, "unauthenticated")

    def test_brief_example_unknown_on_timeout(self):
        unexpected = ClaudeDriver().parse_auth_status(_completed(124, ""))
        self.assertEqual(unexpected.state, "unknown")

    def test_authenticated(self):
        result = ClaudeDriver().parse_auth_status(_completed(0, '{"loggedIn": true}'))
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.provider, "claude")
        self.assertEqual(result.remediation, "")

    def test_unauthenticated_stands_on_explicit_negative_even_with_rc_zero(self):
        # A saida explicita (loggedIn:false) prevalece mesmo se o codigo de
        # saida (por algum motivo) fosse 0 -- nunca vira falso positivo.
        result = ClaudeDriver().parse_auth_status(_completed(0, '{"loggedIn": false}'))
        self.assertEqual(result.state, "unauthenticated")

    def test_authenticated_requires_agreement_between_rc_and_payload(self):
        # loggedIn:true com codigo de saida != 0 e contraditorio: fica
        # "unknown", nunca "authenticated" por otimismo.
        result = ClaudeDriver().parse_auth_status(_completed(1, '{"loggedIn": true}'))
        self.assertEqual(result.state, "unknown")

    def test_json_invalido(self):
        result = ClaudeDriver().parse_auth_status(_completed(1, "isto nao e json"))
        self.assertEqual(result.state, "unknown")

    def test_saida_inesperada_com_codigo_zero(self):
        result = ClaudeDriver().parse_auth_status(_completed(0, '{"foo": "bar"}'))
        self.assertEqual(result.state, "unknown")

    def test_unauthenticated_points_at_login(self):
        result = ClaudeDriver().parse_auth_status(_completed(1, '{"loggedIn": false}'))
        self.assertIn("login", result.remediation)

    def test_status_command_never_carries_a_mutating_verb(self):
        self.assertEqual(ClaudeDriver.status_command, "claude auth status --json")
        self.assertNotIn("logout", ClaudeDriver.status_command)
        self.assertNotIn("/login", ClaudeDriver.status_command)

    def test_no_status_command_is_a_version_query(self):
        """Herdado de TestVerificacaoDeLogin: `--version` responde 0 com o
        agente deslogado, e um falso verde e pior que nenhuma checagem."""
        self.assertNotIn("--version", ClaudeDriver.status_command)


class TestClaudeLoginArgv(unittest.TestCase):
    """O contrato exato do comando de login, verbatim do brief da A3."""

    def test_login_argv(self):
        self.assertEqual(ClaudeDriver().login_argv(), ("claude", "auth", "login"))

    def test_login_argv_is_not_the_dead_slash_login(self):
        """`claude /login` sai com 0 SEM logar (A1): um falso verde que
        manda o operador embora achando que a credencial foi gravada."""
        self.assertNotIn("/login", ClaudeDriver().login_argv())

    def test_login_argv_never_selects_api_billing(self):
        """`--console` seleciona faturamento por API em vez da assinatura."""
        self.assertNotIn("--console", ClaudeDriver().login_argv())

    def test_login_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", ClaudeDriver().login_argv())


class TestClaudeVerifyArgv(unittest.TestCase):
    def test_verify_argv_uses_dash_p_and_closes_stdin(self):
        argv = ClaudeDriver().verify_argv()
        self.assertEqual(len(argv), 1)
        command = argv[0]
        self.assertIn("asb-claude -p", command)
        self.assertIn("/dev/null", command)
        self.assertIn("timeout", command)

    def test_verify_argv_uses_the_dead_slash_login(self):
        self.assertNotIn("/login", ClaudeDriver().verify_argv()[0])

    def test_verify_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", ClaudeDriver().verify_argv()[0])

    def test_verify_argv_uses_explicit_synthetic_workdir(self):
        command = ClaudeDriver().verify_argv()[0]
        self.assertIn("mktemp -d", command)
        self.assertIn("cd ", command)


class TestClaudeClassifyVerification(unittest.TestCase):
    """O teste verbatim do brief: rede ruim nunca vira logout. As sete
    formas do brief (autenticado, nao-autenticado, malformado, timeout,
    erro de fornecedor, rede inalcancavel) vivem aqui; "binario ausente" e
    orquestracao de `verify_client` (OSError do subprocess), nao algo que
    `classify_verification` decida — coberto em
    tests/unit/test_auth_verify.py::TestVerifyClientInfrastructureGates."""

    def test_bad_network_never_becomes_unauthenticated(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "connection timed out"), network_state=False)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.remediation, "login")

    def test_rate_limit_is_provider_error_not_unauthenticated(self):
        rate_limited = ClaudeDriver().classify_verification(
            _completed(1, "HTTP 429"), network_state=True)
        self.assertEqual(rate_limited.state, "provider_error")

    def test_rate_limit_never_recommends_removing_the_credential(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "HTTP 429"), network_state=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_service_outage_is_provider_error_not_unauthenticated(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "503 Service Unavailable"), network_state=True)
        self.assertEqual(result.state, "provider_error")
        self.assertNotIn("login", result.remediation.lower())

    def test_timeout_text_is_unreachable_even_when_network_ok_was_true(self):
        """O texto capturado da CHAMADA (nao a pre-checagem) tambem pode
        denunciar timeout -- e tem de cair na mesma categoria nao acusatoria."""
        result = ClaudeDriver().classify_verification(
            _completed(124, "operation timed out"), network_state=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_gnu_timeout_returncode_alone_is_never_unauthenticated(self):
        """Codigo 124 (o `timeout` do coreutils matou o processo) sem texto
        algum: nao ha evidencia de credencial invalida em lugar nenhum."""
        result = ClaudeDriver().classify_verification(
            _completed(124, ""), network_state=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_bare_403_is_never_unauthenticated(self):
        """403 puro tambem e a assinatura de uma negativa de ACL do proxy.
        So a evidencia PROPRIA do fornecedor pode virar `unauthenticated`."""
        result = ClaudeDriver().classify_verification(
            _completed(1, "HTTP/1.1 403 Forbidden"), network_state=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_bare_401_is_never_unauthenticated(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "401 Unauthorized"), network_state=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_provider_own_evidence_of_invalid_credential_is_unauthenticated(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "authentication_error: invalid x-api-key"),
            network_state=True)
        self.assertEqual(result.state, "unauthenticated")
        self.assertEqual(result.remediation, "asb-agent login")

    def test_success_is_returncode_zero_with_no_error_markers(self):
        result = ClaudeDriver().classify_verification(
            _completed(0, "ASB_AUTH_VERIFY_OK"), network_state=True)
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.remediation, "")

    def test_the_word_timeout_alone_does_not_false_positive_on_success(self):
        """Mesmo espirito do R4 (docs/domains/sandbox/known-regressions.md),
        mas em texto: 'timeout' sozinho aparece em nomes de flag e linhas de
        configuracao benignas. So 'timed out' (a frase) e evidencia real de
        falha de rede."""
        result = ClaudeDriver().classify_verification(
            _completed(0, "print-timeout: 5m0s"), network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")
        self.assertNotEqual(result.state, "unreachable")

    def test_429_substring_in_a_port_number_does_not_false_positive(self):
        result = ClaudeDriver().classify_verification(
            _completed(0, "listening on port 14290, connected"),
            network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")

    def test_503_substring_in_a_byte_count_does_not_false_positive(self):
        result = ClaudeDriver().classify_verification(
            _completed(0, "processed 5003 bytes successfully"),
            network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")

    def test_delimited_429_still_matches_as_rate_limit(self):
        for text in ("HTTP 429", "429 Too Many Requests", "status=429,"):
            with self.subTest(text=text):
                result = ClaudeDriver().classify_verification(
                    _completed(1, text), network_state=True)
                self.assertEqual(result.state, "provider_error")

    def test_delimited_503_still_matches_as_service_error(self):
        for text in ("HTTP/1.1 503 Service Unavailable", "(503)"):
            with self.subTest(text=text):
                result = ClaudeDriver().classify_verification(
                    _completed(1, text), network_state=True)
                self.assertEqual(result.state, "provider_error")

    def test_unrecognized_nonzero_output_is_unknown_not_unauthenticated(self):
        result = ClaudeDriver().classify_verification(
            _completed(1, "algo inesperado"), network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_evidence_never_carries_the_raw_output(self):
        """A evidencia e sempre texto enlatado (categoria), nunca o `output`
        interpolado -- e ali que um token ou codigo OAuth apareceria."""
        secret = "sk-ant-oat01-SEGREDO-DE-VERDADE"
        for output, network_state in (
            ("connection timed out", False),
            ("HTTP 429 " + secret, True),
            ("Not logged in " + secret, True),
        ):
            with self.subTest(output=output):
                result = ClaudeDriver().classify_verification(
                    _completed(1, output), network_state=network_state)
                self.assertNotIn(secret, result.evidence)

    def test_exit_zero_with_the_wrong_response_is_not_authenticated(self):
        """Evidencia de sucesso exige resposta no formato solicitado, nao um
        grep de 'ok'. Um exit 0 com resposta errada e um erro de FORMATO,
        registrado separado de erro de credencial."""
        result = ClaudeDriver().classify_verification(
            _completed(0, "claro! aqui esta: ok"), network_state=True)
        self.assertNotEqual(result.state, "authenticated")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_whitespace_is_normalized_before_comparison(self):
        result = ClaudeDriver().classify_verification(
            _completed(0, "  ASB_AUTH_VERIFY_OK  \n"), network_state=True)
        self.assertEqual(result.state, "authenticated")

    def test_a_help_string_never_counts_as_success_evidence(self):
        result = ClaudeDriver().classify_verification(
            _completed(0, "Usage: claude [options] [command] [prompt]"),
            network_state=True)
        self.assertNotEqual(result.state, "authenticated")


# ---------------------------------------------------------------------------
# Autenticacao — Codex (Tarefa 2, commit 2). Exemplos verbatim herdados de
# tests/unit/test_auth_status.py::TestParseCodexStatus e
# tests/unit/test_auth_verify.py::TestClassifyVerification /
# tests/unit/test_login_flow.py::TestLoginCommandTable.
# ---------------------------------------------------------------------------


class TestCodexParseAuthStatus(unittest.TestCase):
    def test_authenticated(self):
        result = CodexDriver().parse_auth_status(
            _completed(0, "Logged in using ChatGPT\n", ""))
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.provider, "codex")
        self.assertEqual(result.remediation, "")

    def test_unauthenticated(self):
        result = CodexDriver().parse_auth_status(
            _completed(1, "Not logged in\n", ""))
        self.assertEqual(result.state, "unauthenticated")

    def test_explicit_negative_prevails_over_positive_substring(self):
        # "Not logged in" CONTEM a substring "logged in" -- a negativa
        # explicita tem que vencer, nunca ser lida como positiva.
        result = CodexDriver().parse_auth_status(
            _completed(1, "Not logged in\n", ""))
        self.assertEqual(result.state, "unauthenticated")

    def test_explicit_negative_on_stderr_also_prevails(self):
        result = CodexDriver().parse_auth_status(_completed(0, "", "Not logged in"))
        self.assertEqual(result.state, "unauthenticated")

    def test_unknown_format_does_not_become_authenticated(self):
        result = CodexDriver().parse_auth_status(_completed(0, "algo inesperado\n", ""))
        self.assertEqual(result.state, "unknown")

    def test_comando_ausente(self):
        result = CodexDriver().parse_auth_status(
            _completed(127, "", "bash: line 1: codex: command not found"))
        self.assertEqual(result.state, "unknown")

    def test_timeout(self):
        result = CodexDriver().parse_auth_status(_completed(124, "", ""))
        self.assertEqual(result.state, "unknown")

    def test_authenticated_requires_returncode_zero(self):
        # Mensagem de sucesso mas codigo != 0 e contraditorio -> unknown.
        result = CodexDriver().parse_auth_status(
            _completed(1, "Logged in using ChatGPT\n", ""))
        self.assertEqual(result.state, "unknown")

    def test_status_command_never_carries_a_mutating_verb(self):
        self.assertEqual(CodexDriver.status_command, "codex login status")
        self.assertNotIn("logout", CodexDriver.status_command)
        self.assertNotIn("/login", CodexDriver.status_command)

    def test_no_status_command_is_a_version_query(self):
        self.assertNotIn("--version", CodexDriver.status_command)


class TestCodexLoginArgv(unittest.TestCase):
    def test_login_argv(self):
        self.assertEqual(CodexDriver().login_argv(),
                         ("codex", "login", "--device-auth"))

    def test_login_argv_is_not_the_dead_slash_login(self):
        self.assertNotIn("/login", CodexDriver().login_argv())

    def test_login_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", CodexDriver().login_argv())


class TestCodexVerifyArgv(unittest.TestCase):
    def test_verify_argv_uses_exec_subcommand_not_interactive_default(self):
        argv = CodexDriver().verify_argv()
        self.assertEqual(len(argv), 1)
        command = argv[0]
        self.assertIn("asb-codex exec", command)
        self.assertIn("/dev/null", command)

    def test_verify_argv_is_not_the_dead_slash_login(self):
        self.assertNotIn("/login", CodexDriver().verify_argv()[0])

    def test_verify_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", CodexDriver().verify_argv()[0])

    def test_verify_argv_uses_explicit_synthetic_workdir(self):
        command = CodexDriver().verify_argv()[0]
        self.assertIn("mktemp -d", command)
        self.assertIn("cd ", command)

    def test_verify_argv_discards_stream_output_and_reads_only_output_file(self):
        command = CodexDriver().verify_argv()[0]
        self.assertIn('-o "$OUT"', command)
        self.assertIn("> /dev/null", command)
        self.assertIn('cat "$OUT"', command)


class TestCodexRemoteScriptBehavior(unittest.TestCase):
    """Executa o script remoto de verdade contra um wrapper falso `asb-codex`
    -- prova o comportamento do script (o que ele imprime/retorna), nao so o
    texto do comando."""

    def _run_with_wrapper(self, wrapper_body: str):
        import os
        with tempfile.TemporaryDirectory(
                prefix="asb-test-codex-driver-wrapper-") as tmp_name:
            wrapper = Path(tmp_name) / "asb-codex"
            wrapper.write_text(
                "#!/usr/bin/env bash\nset -eu\n" + wrapper_body,
                encoding="utf-8")
            wrapper.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp_name}:{env['PATH']}"
            return subprocess.run(
                ["bash", "-c", CodexDriver().verify_argv()[0]],
                capture_output=True, text=True, env=env, timeout=10)

    def test_script_success_emits_only_the_output_file(self):
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

    def test_script_failure_emits_stderr_and_preserves_exit_status(self):
        result = self._run_with_wrapper(
            """while [ "$#" -gt 0 ]; do shift; done
printf '%s\\n' 'stream noise must be discarded'
printf '%s\\n' 'authentication required' >&2
exit 23
""")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "authentication required")


class TestCodexClassifyVerification(unittest.TestCase):
    """Casos verbatim de tests/unit/test_auth_verify.py que usavam "codex"
    como fornecedor: rede, limite de taxa e erro de servico sao pipeline
    COMPARTILHADO (base.py), exercitados aqui via CodexDriver; a evidencia
    propria e o formato de sucesso sao dados do driver."""

    def test_rate_limit_never_recommends_removing_the_credential(self):
        result = CodexDriver().classify_verification(
            _completed(1, "HTTP 429"), network_state=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_service_outage_is_provider_error_not_unauthenticated(self):
        result = CodexDriver().classify_verification(
            _completed(1, "503 Service Unavailable"), network_state=True)
        self.assertEqual(result.state, "provider_error")
        self.assertNotIn("login", result.remediation.lower())

    def test_bare_401_is_never_unauthenticated(self):
        result = CodexDriver().classify_verification(
            _completed(1, "401 Unauthorized"), network_state=True)
        self.assertNotEqual(result.state, "unauthenticated")
        self.assertNotIn("login", result.remediation.lower())

    def test_provider_own_evidence_of_invalid_credential_is_unauthenticated(self):
        result = CodexDriver().classify_verification(
            _completed(1, "Not logged in"), network_state=True)
        self.assertEqual(result.state, "unauthenticated")
        self.assertEqual(result.remediation, "asb-agent login")

    def test_503_substring_in_a_byte_count_does_not_false_positive(self):
        result = CodexDriver().classify_verification(
            _completed(0, "processed 5003 bytes successfully"),
            network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")

    def test_delimited_503_still_matches_as_service_error(self):
        for text in ("HTTP/1.1 503 Service Unavailable", "(503)"):
            with self.subTest(text=text):
                result = CodexDriver().classify_verification(
                    _completed(1, text), network_state=True)
                self.assertEqual(result.state, "provider_error")

    def test_evidence_never_carries_the_raw_output(self):
        secret = "sk-ant-oat01-SEGREDO-DE-VERDADE"
        result = CodexDriver().classify_verification(
            _completed(1, "Not logged in " + secret), network_state=True)
        self.assertNotIn(secret, result.evidence)

    def test_success_with_the_shared_prompt_response(self):
        result = CodexDriver().classify_verification(
            _completed(0, "ASB_AUTH_VERIFY_OK"), network_state=True)
        self.assertEqual(result.state, "authenticated")
        self.assertEqual(result.remediation, "")

    def test_timeout_returncode_is_unreachable_not_unauthenticated(self):
        result = CodexDriver().classify_verification(
            _completed(124, "operation timed out"), network_state=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_bad_network_never_becomes_unauthenticated(self):
        result = CodexDriver().classify_verification(
            _completed(1, "connection timed out"), network_state=False)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.remediation, "login")


# ---------------------------------------------------------------------------
# Autenticacao — Antigravity/agy (Tarefa 2, commit 3). Exemplos verbatim
# herdados de tests/unit/test_auth_verify.py (TestClassifyVerification,
# TestVerifyClientAgy, TestAgyRealModelListFormat) e
# tests/unit/test_login_flow.py (TestLoginCommandTable).
# ---------------------------------------------------------------------------


class TestAntigravityParseAuthStatus(unittest.TestCase):
    """Ao contrario de claude/codex, `agy` nao tem comando de status local
    comprovado (A1: `agy -p ping` bloqueia ate 60s aguardando entrada
    quando deslogado). `status_command` fica `None` e `parse_auth_status`
    sempre devolve o mesmo resultado enlatado `unknown`, ignorando
    `completed` -- nao ha saida de fornecedor alguma para interpretar."""

    def test_status_command_is_none(self):
        # Sinal para o chamador (`auth.check_status`) nunca tocar podman.
        self.assertIsNone(AntigravityDriver.status_command)

    def test_parse_auth_status_is_always_unknown(self):
        result = AntigravityDriver().parse_auth_status()
        self.assertEqual(result.state, "unknown")
        self.assertEqual(result.provider, "agy")

    def test_parse_auth_status_never_touches_podman(self):
        # Documenta a garantia por construcao: nao ha parametro de podman
        # nem de container -- o metodo nao tem como tocar podman.
        result = AntigravityDriver().parse_auth_status(None)
        self.assertIn("verify", result.remediation.lower())
        self.assertEqual(result.remediation,
                         "asb-agent auth verify --workspace <id> --agent agy")

    def test_parse_auth_status_ignores_a_completed_argument(self):
        # `completed` e aceito por simetria com claude/codex, mas ignorado:
        # nao ha saida de fornecedor para interpretar.
        real = AntigravityDriver().parse_auth_status(
            _completed(0, '{"loggedIn": true}'))
        self.assertEqual(real.state, "unknown")


class TestAntigravityLoginArgv(unittest.TestCase):
    def test_login_argv(self):
        self.assertEqual(AntigravityDriver().login_argv(), ("agy",))

    def test_login_argv_is_not_the_dead_slash_login(self):
        """`agy` nao tem subcomando `login`; o binario nu abre a TUI, que
        autentica no primeiro uso."""
        self.assertNotIn("/login", AntigravityDriver().login_argv())

    def test_login_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", AntigravityDriver().login_argv())


class TestAntigravityVerifyArgv(unittest.TestCase):
    def test_verify_argv_never_sends_a_prompt(self):
        argv = AntigravityDriver().verify_argv()
        self.assertEqual(len(argv), 1)
        command = argv[0]
        self.assertIn("asb-agy models", command)
        self.assertNotIn(" -p ", f" {command} ")
        self.assertNotIn("--print", command)

    def test_verify_argv_closes_stdin(self):
        self.assertIn("/dev/null", AntigravityDriver().verify_argv()[0])

    def test_verify_argv_is_not_the_dead_slash_login(self):
        self.assertNotIn("/login", AntigravityDriver().verify_argv()[0])

    def test_verify_argv_is_not_a_version_query(self):
        self.assertNotIn("--version", AntigravityDriver().verify_argv()[0])

    def test_verify_argv_uses_explicit_synthetic_workdir(self):
        command = AntigravityDriver().verify_argv()[0]
        self.assertIn("mktemp -d", command)
        self.assertIn("cd ", command)


class TestAntigravityClassifyVerification(unittest.TestCase):
    """Casos verbatim de tests/unit/test_auth_verify.py que usavam "agy"
    como fornecedor (TestClassifyVerification, TestVerifyClientAgy): rede,
    limite de taxa e erro de servico sao pipeline COMPARTILHADO (base.py);
    a evidencia propria e o formato de sucesso (LISTA de modelos, nao uma
    frase fixa) sao dados/override deste driver."""

    def test_timeout_text_is_unreachable_even_when_network_ok_was_true(self):
        result = AntigravityDriver().classify_verification(
            _completed(124, "operation timed out"), network_state=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_gnu_timeout_returncode_alone_is_never_unauthenticated(self):
        result = AntigravityDriver().classify_verification(
            _completed(124, ""), network_state=True)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.state, "unauthenticated")

    def test_provider_own_evidence_of_invalid_credential_is_unauthenticated(self):
        result = AntigravityDriver().classify_verification(
            _completed(1, "authentication required"), network_state=True)
        self.assertEqual(result.state, "unauthenticated")
        self.assertEqual(result.remediation, "asb-agent login")

    def test_the_word_timeout_alone_does_not_false_positive_on_success(self):
        """Mesmo espirito do R4 (docs/domains/sandbox/known-regressions.md):
        'timeout' sozinho aparece em nomes de flag e linhas de configuracao
        benignas (ex.: uma saida de sucesso do agy que mencione
        '--print-timeout'). So 'timed out' (a frase) e evidencia real de
        falha de rede."""
        result = AntigravityDriver().classify_verification(
            _completed(0, "print-timeout: 5m0s"), network_state=True)
        self.assertEqual(result.state, "unknown")
        self.assertNotEqual(result.state, "provider_error")
        self.assertNotEqual(result.state, "unreachable")

    def test_bad_network_never_becomes_unauthenticated(self):
        result = AntigravityDriver().classify_verification(
            _completed(1, "connection timed out"), network_state=False)
        self.assertEqual(result.state, "unreachable")
        self.assertNotEqual(result.remediation, "login")

    def test_classify_agy_exit_zero_requires_a_model_list(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "command completed"), network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_agy_auth_marker_outranks_exit_zero(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "authentication required"), network_state=True)
        self.assertEqual(result.state, "unauthenticated")

    def test_agy_prose_with_model_families_is_not_a_model_list(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "Gemini is temporarily unavailable\n"
                          "Claude is temporarily unavailable"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_every_agy_list_line_must_be_a_model_identifier(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "gemini-2.5-pro\nClaude is temporarily unavailable"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_agy_tokenized_error_names_are_not_model_identifiers(self):
        outputs = (
            "gemini-unavailable\nclaude-unavailable",
            "error:gemini\nerror:claude",
        )
        for output in outputs:
            with self.subTest(output=output):
                result = AntigravityDriver().classify_verification(
                    _completed(0, output), network_state=True)
                self.assertEqual(result.state, "unknown")

    def test_versioned_identifiers_without_known_family_are_unknown(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "modelo-2.5-valido\noutro-modelo-1.0"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_versioned_known_model_identifiers_remain_authenticated(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "gemini-2.5-pro\nclaude-4-sonnet"),
            network_state=True)
        self.assertEqual(result.state, "authenticated")


# Saida REAL de `asb-agy models` capturada no piloto T2 em 2026-09-16, com o
# binario fixado 1.1.27, dentro do container do workspace. A1 nao preservou a
# saida bruta e a guarda foi escrita contra uma lembranca dela; e por isso que
# a classificacao so podia devolver `unknown`. O formato e
# `identificador<TAB>rotulo humano`, precedido de uma linha de prosa.
# Nomes de modelo nao sao credencial: preservados aqui de proposito, para que
# ninguem precise gastar outra chamada real so para reaprender o formato.
# `classify_verification` monta `combined = f"{stdout}\n{stderr}"`, entao a
# prosa de stderr chega DEPOIS das linhas de modelo, nao antes. Medido:
# stdout traz so as linhas `identificador<TAB>rotulo`; stderr traz so
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


class TestAntigravityRealModelListFormat(unittest.TestCase):
    """A saida real tem cabecalho de prosa e duas colunas separadas por TAB.

    A guarda continua fechando: o que a torna valida e a COLUNA DO
    IDENTIFICADOR, nunca o rotulo humano, e qualquer linha nao conforme
    DEPOIS da primeira linha de modelo reprova a lista inteira.
    """

    def test_saida_real_do_agy_e_classificada_como_autenticada(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, AGY_MODELS_REAL_OUTPUT), network_state=True)
        self.assertEqual(result.state, "authenticated")

    def test_cabecalho_de_prosa_sozinho_nao_autentica(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, "Fetching available models..."), network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_linha_nao_conforme_depois_das_linhas_de_modelo_reprova(self):
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                "claude-sonnet-4-6\tClaude Sonnet 4.6\n"
                "Gemini is temporarily unavailable"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_rotulo_humano_nao_pode_sustentar_familia_nem_versao(self):
        # O identificador nao tem familia conhecida nem numero; so o rotulo
        # tem. Se a guarda olhasse a linha inteira, isto passaria.
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "modelo-desconhecido\tGemini 3.8 Flash (High)\n"
                "outro-desconhecido\tClaude Sonnet 4.6\n"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_uma_unica_linha_de_modelo_nao_e_lista(self):
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                "Fetching available models..."),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_prosa_neutra_de_stderr_depois_das_linhas_e_tolerada(self):
        # Ordem REAL: stdout (linhas de modelo) e so entao stderr (prosa).
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                "claude-sonnet-4-6\tClaude Sonnet 4.6\n"
                "\nFetching available models...\n"),
            network_state=True)
        self.assertEqual(result.state, "authenticated")

    def test_linha_nao_conforme_ENTRE_linhas_de_modelo_reprova(self):
        # Prosa no MEIO da lista continua reprovando: e o caso de um erro
        # interrompendo a listagem.
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                "algo deu errado no meio\n"
                "claude-sonnet-4-6\tClaude Sonnet 4.6\n"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_identificador_com_sufixo_de_unidade_conta_como_versao(self):
        # `gpt-oss-120b-medium` existe na saida real. O numero vem colado a
        # uma unidade ("120b"), e a guarda original exigia digito sem letra
        # depois — reprovando uma linha de modelo legitima e, por tabela, a
        # lista inteira.
        self.assertTrue(_agy_model_row("gpt-oss-120b-medium"))

    def test_identificador_sem_digito_algum_continua_reprovado(self):
        # A razao de ser da regra de numero: nomes de erro tokenizados.
        for line in ("gemini-unavailable", "claude-unavailable",
                     "error:gemini"):
            with self.subTest(line=line):
                self.assertFalse(_agy_model_row(line))

    def test_cabecalho_que_cita_familia_de_modelo_reprova_a_lista(self):
        # Um cabecalho tolerado e prosa neutra ("Fetching available
        # models..."). Prosa que cita familia conhecida antes das linhas de
        # modelo e justamente o caso que poderia mascarar um erro.
        result = AntigravityDriver().classify_verification(
            _completed(0,
                "Gemini is temporarily unavailable\n"
                "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                "claude-sonnet-4-6\tClaude Sonnet 4.6\n"),
            network_state=True)
        self.assertEqual(result.state, "unknown")

    def test_marcador_de_credencial_ainda_domina_a_lista_valida(self):
        result = AntigravityDriver().classify_verification(
            _completed(0, AGY_MODELS_REAL_OUTPUT + "authentication required\n"),
            network_state=True)
        self.assertEqual(result.state, "unauthenticated")


if __name__ == "__main__":
    unittest.main()
