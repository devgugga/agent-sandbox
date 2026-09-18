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
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.agents.antigravity import AntigravityDriver  # noqa: E402
from asb.agents.base import (  # noqa: E402
    AgentAvailability, LaunchCommand, ResumeUnsupported, SessionEvidence,
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


class TestLaunchAndResumeArgv(unittest.TestCase):
    """Amostras exatas do brief da Tarefa 5."""

    def test_codex_launch_argv(self):
        self.assertEqual(CodexDriver().launch(Path("/repo")).argv, ("codex",))

    def test_codex_resume_argv(self):
        self.assertEqual(
            CodexDriver().resume(Path("/repo"), "abc").argv,
            ("codex", "resume", "abc"))

    def test_claude_resume_argv(self):
        self.assertEqual(
            ClaudeDriver().resume(Path("/repo"), "abc").argv,
            ("claude", "--resume", "abc"))

    def test_antigravity_resume_raises_when_session_id_unprovable(self):
        # session_id_provable=False e um fato ESTATICO da instalacao
        # neste host (nenhum diretorio de estado local encontrado para
        # `agy`): resume() recusa mesmo sem nunca ter sido probado, para
        # nao prometer uma resumption que ninguem provou. O binario da
        # imagem do container e o gate autoritativo real (ver
        # docs/validation/2026-09-17-agent-session-contracts.md).
        with self.assertRaises(ResumeUnsupported):
            AntigravityDriver().resume(Path("/repo"), "abc")

    def test_claude_launch_argv(self):
        self.assertEqual(ClaudeDriver().launch(Path("/repo")).argv, ("claude",))

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
            reason="ok"))

    def test_claude_probe_confirms_resume_when_option_present(self):
        run = _FakeRun({
            "--version": "2.1.275 (Claude Code)",
            "--help": "Options:\n  -r, --resume [value]  Resume a session\n",
        })
        availability = ClaudeDriver().probe(run)
        self.assertTrue(availability.resume_supported)
        self.assertEqual(availability.version, "2.1.275")


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

    def test_multiple_new_files_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            sessions = sessions_root / "2026" / "09" / "17"
            sessions.mkdir(parents=True)
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            (sessions / "rollout-a.jsonl").write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"id": "id-a"}}) + "\n")
            (sessions / "rollout-b.jsonl").write_text(
                json.dumps({"type": "session_meta",
                            "payload": {"id": "id-b"}}) + "\n")
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
                            "payload": {"id": "session-meta-id"}}) + "\n"
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
                json.dumps({"type": "session_meta", "payload": {}}) + "\n")
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
                            "payload": {"id": "session-meta-id"}}) + "\n")
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
                            "payload": {"id": "pre-existing"}}) + "\n")
            driver = self._driver(sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))


class TestClaudeSessionEvidence(unittest.TestCase):
    def test_slug_replaces_slash_and_dot(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = ClaudeDriver(sessions_root=sessions_root)
            cwd = Path("/a/b/.c/d")
            baseline = driver.capture_before(cwd)
            expected_slug = "-a-b--c-d"
            self.assertEqual(baseline.scan_root,
                              sessions_root / expected_slug)

    def test_exactly_one_new_jsonl_returns_its_filename_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            cwd = Path("/repo")
            driver = ClaudeDriver(sessions_root=sessions_root)
            baseline = driver.capture_before(cwd)
            project_dir = baseline.scan_root
            project_dir.mkdir(parents=True)
            new_file = project_dir / "00000000-0000-4000-8000-000000000001.jsonl"
            new_file.write_text(
                json.dumps({"sessionId": new_file.stem,
                            "type": "last-prompt"}) + "\n")
            after = driver.capture_after(baseline)
            self.assertEqual(after.new_paths, frozenset({new_file}))
            self.assertEqual(driver.discover_session_id(after), new_file.stem)

    def test_zero_new_files_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = ClaudeDriver(sessions_root=sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))

    def test_multiple_new_files_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_root = Path(tmp)
            driver = ClaudeDriver(sessions_root=sessions_root)
            baseline = driver.capture_before(Path("/repo"))
            baseline.scan_root.mkdir(parents=True)
            (baseline.scan_root / "aaaa.jsonl").write_text("{}\n")
            (baseline.scan_root / "bbbb.jsonl").write_text("{}\n")
            after = driver.capture_after(baseline)
            self.assertIsNone(driver.discover_session_id(after))



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

    def test_claude_without_sessions_root_ignores_host_claude_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, env = self._fake_home(tmp)
            project_dir = home / ".claude" / "projects" / "-repo"
            project_dir.mkdir(parents=True)
            with env, mock.patch("pathlib.Path.home", return_value=home):
                driver = ClaudeDriver()
                baseline = driver.capture_before(Path("/repo"))
                (project_dir / "00000000-0000-4000-8000-000000000009.jsonl"
                 ).write_text("{}\n")
                after = driver.capture_after(baseline)
            self.assertIsNone(baseline.scan_root)
            self.assertEqual(after.new_paths, frozenset())
            self.assertIsNone(driver.discover_session_id(after))

if __name__ == "__main__":
    unittest.main()
