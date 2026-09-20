"""Testes dos drivers de provedor de agente (Tarefa 5).

Um `AgentDriver` apenas RETORNA `LaunchCommand`; nenhum teste aqui inicia um
processo real, envia um prompt ou contata a API de um provedor. `probe()`
recebe sempre um runner falso injetado. Os caminhos de estado de sessao
(Codex/Claude) usam arvores `tempfile`, nunca o estado real do operador.
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

from asb.agents.antigravity import AntigravityDriver  # noqa: E402
from asb.agents.base import (  # noqa: E402
    AgentAvailability, LaunchCommand, Lifetime, ResumeUnsupported,
    SessionEvidence,
)
from asb.agents.claude import ClaudeDriver  # noqa: E402
from asb.agents.codex import CodexDriver  # noqa: E402


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

if __name__ == "__main__":
    unittest.main()
