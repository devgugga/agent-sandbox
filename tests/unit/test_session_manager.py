"""Testes de `asb.sessions.manager` (Tarefa 8): a maquina de estados de
recuperacao de sessoes.

Nenhum SSH, tmux, Podman ou provedor real: o terminal, os drivers, o
`remote_run`, o relogio e o `sleep` sao falsos. O `SessionStore` e o REAL,
num diretorio temporario, para que qualquer `replace()` de um registro
desatualizado falhe com `StaleRevisionError` — a prova de que cada passo
persiste o ultimo registro devolvido pelo store.
"""
from __future__ import annotations

import asb_test_isolation  # noqa: F401  (guarda de isolamento da suite: nenhum volume real)

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))

from asb.agents.base import (  # noqa: E402
    AgentAvailability, LaunchCommand, SessionEvidence,
)
from asb.checkouts.model import CheckoutId  # noqa: E402
from asb.sessions.manager import (  # noqa: E402
    AttachResult, ResumeResult, SessionManager, SessionManagerError,
    StartSession, terminal_name,
)
from asb.sessions.model import (  # noqa: E402
    AgentKind, AgentSession, ProviderSessionId, SessionState, TerminalId,
)
from asb.sessions.store import SessionStore, StaleRevisionError  # noqa: E402
from asb.sessions.terminal import Liveness, TerminalError  # noqa: E402

CWD = Path("/srv/sandbox/project")
CHECKOUT = CheckoutId("c-0001")
OTHER_CHECKOUT = CheckoutId("c-0002")
NOW = datetime(2026, 9, 18, 12, 30, 45, 123456, tzinfo=timezone.utc)
NOW_STORED = NOW.replace(microsecond=0)
PROVIDER_ID = "0000-provider-id"

ACTIVE_STATES = (
    SessionState.STARTING, SessionState.RUNNING, SessionState.DETACHED,
    SessionState.SUSPENDED, SessionState.EXITED_RESUMABLE,
    SessionState.RECOVERY_REQUIRED,
)


class FakeTerminal:
    """Terminal falso: `probe` devolve os valores de `probes` em ordem (o
    ultimo se repete); `start`/`stop` levantam o que for configurado."""

    def __init__(self, store: SessionStore, probes=(Liveness.ALIVE,),
                 exit_status: int | None = None,
                 start_error: Exception | None = None,
                 stop_error: Exception | None = None) -> None:
        self._store = store
        self.probes = list(probes)
        self.exit_status = exit_status
        self.start_error = start_error
        self.stop_error = stop_error
        self.calls: list[tuple] = []
        self.on_exit_status = None
        # Estado persistido no instante de cada `start`: prova a ordem
        # "persistir STARTING, depois lancar".
        self.state_at_start: list[SessionState] = []

    def _session_for(self, terminal_id: str) -> AgentSession | None:
        for session in self._store.list():
            if session.terminal_id == terminal_id:
                return session
        return None

    def start(self, terminal_id, cwd, command) -> None:
        TerminalId(terminal_id)
        self.calls.append(("start", terminal_id, Path(cwd), tuple(command)))
        session = self._session_for(terminal_id)
        if session is not None:
            self.state_at_start.append(session.state)
        if self.start_error is not None:
            raise self.start_error

    def probe(self, terminal_id) -> Liveness:
        self.calls.append(("probe", terminal_id))
        if len(self.probes) > 1:
            return self.probes.pop(0)
        return self.probes[0]

    def capture_exit_status(self, terminal_id) -> int | None:
        self.calls.append(("capture_exit_status", terminal_id))
        if self.on_exit_status is not None:
            self.on_exit_status()
        return self.exit_status

    def stop(self, terminal_id) -> None:
        self.calls.append(("stop", terminal_id))
        if self.stop_error is not None:
            raise self.stop_error

    def attach_argv(self, terminal_id) -> list[str]:
        self.calls.append(("attach_argv", terminal_id))
        return ["ssh", "-tt", "tmux", "attach-session", "-t", f"={terminal_id}"]

    def names(self, name: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == name]


class FakeDriver:
    """Driver falso com a mesma superficie que o manager usa. A descoberta
    devolve, por tentativa, o valor de `discoveries` (o ultimo se repete)."""

    def __init__(self, kind: AgentKind = AgentKind.CODEX,
                 discoveries=(None,), resume_supported: bool = True,
                 launch_env=None, resume_env=None,
                 probes=("full",)) -> None:
        # Resultado de cada `probe()`, em ordem (o ultimo se repete):
        # "full" (--version e --help responderam), "help_failed" (--help
        # falhou ao executar) ou "unavailable" (--version falhou).
        self.kind = kind
        self.probes = list(probes)
        self.discoveries = list(discoveries)
        self.resume_supported = resume_supported
        self.launch_env = launch_env or {}
        self.resume_env = resume_env or {}
        self.probe_runs: list[object] = []
        self.baseline = SessionEvidence(scan_root=Path("/vol/codex-sessions"),
                                        known_paths=frozenset({Path("/old")}))
        self.capture_before_cwds: list[Path] = []
        self.capture_after_inputs: list[SessionEvidence] = []
        self.resumed: list[tuple[Path, str]] = []

    def launch(self, cwd: Path) -> LaunchCommand:
        return LaunchCommand(argv=(str(self.kind),), env=self.launch_env)

    def resume(self, cwd: Path, session_id: str) -> LaunchCommand:
        self.resumed.append((cwd, session_id))
        return LaunchCommand(argv=(str(self.kind), "resume", session_id),
                             env=self.resume_env)

    def probe(self, run) -> AgentAvailability:
        self.probe_runs.append(run)
        outcome = self.probes.pop(0) if len(self.probes) > 1 \
            else self.probes[0]
        full = outcome == "full"
        return AgentAvailability(
            available=outcome != "unavailable",
            version=None if outcome == "unavailable" else "1.0",
            resume_supported=full and self.resume_supported,
            reason=f"fake {outcome}", probed_fully=full)

    def capture_before(self, cwd: Path) -> SessionEvidence:
        self.capture_before_cwds.append(cwd)
        return self.baseline

    def capture_after(self, baseline: SessionEvidence) -> SessionEvidence:
        self.capture_after_inputs.append(baseline)
        return SessionEvidence(scan_root=baseline.scan_root,
                               known_paths=baseline.known_paths,
                               new_paths=frozenset())

    def discover_session_id(self, evidence: SessionEvidence) -> str | None:
        if len(self.discoveries) > 1:
            return self.discoveries.pop(0)
        return self.discoveries[0]


class _FakeRemoteRun:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs) -> str:
        self.calls.append((args, kwargs))
        raise AssertionError("o manager nunca chama remote_run diretamente")


class ManagerCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = SessionStore(Path(tmp.name) / "sessions.json")
        self.sleeps: list[float] = []
        self.remote_run = _FakeRemoteRun()

    def make(self, terminal: FakeTerminal, *drivers: FakeDriver) -> SessionManager:
        if not drivers:
            drivers = (FakeDriver(),)
        return SessionManager(
            store=self.store, terminal=terminal,
            drivers={d.kind: d for d in drivers},
            remote_run=self.remote_run,
            clock=lambda: NOW, sleep=self.sleeps.append)

    def terminal(self, **kwargs) -> FakeTerminal:
        return FakeTerminal(self.store, **kwargs)

    def seed(self, state: SessionState, *, provider_id: str | None = PROVIDER_ID,
             agent: AgentKind = AgentKind.CODEX,
             checkout: CheckoutId = CHECKOUT,
             with_terminal: bool = True) -> AgentSession:
        record = self.store.insert(AgentSession.new(checkout, agent, CWD, "t"))
        changes: dict[str, object] = {"provider_session_id": provider_id}
        if with_terminal:
            changes["terminal_id"] = terminal_name(record.id)
        return self.store.replace(record.with_state(state, **changes))


# -- start ---------------------------------------------------------------------


class TestStart(ManagerCase):
    def request(self, agent: AgentKind = AgentKind.CODEX) -> StartSession:
        return StartSession(checkout_id=CHECKOUT, agent=agent, cwd=CWD,
                            title="Investigate PTY")

    def test_start_persists_unique_discovered_id_after_alive_probe(self):
        terminal = self.terminal(probes=[Liveness.ALIVE])
        driver = FakeDriver(discoveries=[PROVIDER_ID])
        session = self.make(terminal, driver).start(self.request())

        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertEqual(session.provider_session_id, PROVIDER_ID)
        self.assertEqual(session.terminal_id, terminal_name(session.id))
        self.assertEqual(session.last_healthy_at, NOW_STORED)
        self.assertEqual(self.store.get(session.id), session)
        # Metadados capturados no cwd de execucao (a ORDEM antes do
        # lancamento e provada pelo teste com o CodexDriver real).
        self.assertEqual(driver.capture_before_cwds, [CWD])
        self.assertEqual(terminal.names("start"),
                         [("start", session.terminal_id, CWD, ("codex",))])
        self.assertEqual(terminal.state_at_start, [SessionState.STARTING])
        self.assertEqual(self.sleeps, [])

    def test_start_terminal_id_is_a_valid_terminal_id(self):
        session = self.make(self.terminal()).start(self.request())
        self.assertIsInstance(session.terminal_id, TerminalId)
        self.assertEqual(session.terminal_id, f"asb-{session.id}")

    def test_two_sessions_in_one_checkout_get_distinct_ids_and_terminals(self):
        manager = self.make(self.terminal())
        first = manager.start(self.request())
        second = manager.start(self.request())
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.terminal_id, second.terminal_id)
        self.assertEqual({s.id for s in manager.list(CHECKOUT)},
                         {first.id, second.id})

    def test_dead_after_start_becomes_failed_without_discovery(self):
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver(discoveries=[PROVIDER_ID])
        session = self.make(terminal, driver).start(self.request())
        self.assertEqual(session.state, SessionState.FAILED)
        self.assertIsNone(session.provider_session_id)
        self.assertEqual(driver.capture_after_inputs, [])
        self.assertEqual(self.store.get(session.id).state, SessionState.FAILED)

    def test_unknown_after_start_is_recovery_required_never_failed(self):
        terminal = self.terminal(probes=[Liveness.UNKNOWN])
        session = self.make(terminal).start(self.request())
        self.assertEqual(session.state, SessionState.RECOVERY_REQUIRED)
        self.assertEqual(len(terminal.names("start")), 1)

    def test_ambiguous_start_error_then_alive_is_running(self):
        terminal = self.terminal(probes=[Liveness.ALIVE],
                                 start_error=TerminalError("ssh exit 255"))
        session = self.make(terminal, FakeDriver(discoveries=[PROVIDER_ID])
                            ).start(self.request())
        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertEqual(session.provider_session_id, PROVIDER_ID)
        self.assertEqual(len(terminal.names("start")), 1)  # nunca re-tenta

    def test_ambiguous_start_error_then_dead_is_failed(self):
        terminal = self.terminal(probes=[Liveness.DEAD],
                                 start_error=TerminalError("timeout"))
        session = self.make(terminal).start(self.request())
        self.assertEqual(session.state, SessionState.FAILED)
        self.assertEqual(len(terminal.names("start")), 1)

    def test_ambiguous_start_error_then_unknown_is_recovery_required(self):
        terminal = self.terminal(probes=[Liveness.UNKNOWN],
                                 start_error=TerminalError("timeout"))
        session = self.make(terminal).start(self.request())
        self.assertEqual(session.state, SessionState.RECOVERY_REQUIRED)
        self.assertEqual(len(terminal.names("start")), 1)

    def test_non_terminal_error_from_start_propagates(self):
        terminal = self.terminal(start_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.make(terminal).start(self.request())
        self.assertEqual(terminal.names("probe"), [])

    def test_discovery_finds_id_on_a_later_poll_with_original_baseline(self):
        driver = FakeDriver(discoveries=[None, None, PROVIDER_ID])
        session = self.make(self.terminal(), driver).start(self.request())
        self.assertEqual(session.provider_session_id, PROVIDER_ID)
        self.assertEqual(self.sleeps, [1.0, 1.0])
        # Toda tentativa compara contra o instantaneo PRE-lancamento.
        self.assertEqual(driver.capture_after_inputs, [driver.baseline] * 3)

    def test_discovery_zero_or_ambiguous_after_bound_stores_no_id(self):
        # `discover_session_id` devolve None para zero E para ambiguo.
        driver = FakeDriver(discoveries=[None])
        session = self.make(self.terminal(), driver).start(self.request())
        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertIsNone(session.provider_session_id)
        self.assertEqual(len(driver.capture_after_inputs), 5)
        self.assertEqual(self.sleeps, [1.0] * 4)

    def test_ambiguous_discovery_with_two_new_files_stores_no_id(self):
        # Driver real (Codex) sobre uma arvore temporaria: dois arquivos
        # novos sao ambiguos e nenhum id e escolhido.
        import json

        from asb.agents.codex import CodexDriver

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            driver = CodexDriver(sessions_root=root)
            terminal = self.terminal()

            def start_and_write(terminal_id, cwd, command):
                for name in ("a", "b"):
                    (root / f"rollout-{name}.jsonl").write_text(
                        json.dumps({"type": "session_meta",
                                    "payload": {"cwd": str(CWD),
                                                "id": f"id-{name}"}}) + "\n")

            terminal.start = start_and_write
            session = self.make(terminal, driver).start(self.request())
        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertIsNone(session.provider_session_id)
        self.assertEqual(self.sleeps, [1.0] * 4)

    def test_snapshot_is_taken_before_launch_with_real_codex_driver(self):
        # O `start` do terminal escreve o rollout desta sessao: so um
        # instantaneo tirado ANTES do lancamento o ve como arquivo novo.
        import json

        from asb.agents.codex import CodexDriver

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = self.terminal()

            def start_and_write(terminal_id, cwd, command):
                (root / "rollout-mine.jsonl").write_text(
                    json.dumps({"type": "session_meta",
                                "payload": {"cwd": str(CWD),
                                            "id": PROVIDER_ID}}) + "\n")

            terminal.start = start_and_write
            session = self.make(terminal, CodexDriver(sessions_root=root)
                                ).start(self.request())
        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertEqual(session.provider_session_id, PROVIDER_ID)
        self.assertEqual(self.store.get(session.id), session)
        self.assertEqual(self.sleeps, [])

    def test_invalid_discovered_id_is_not_persisted(self):
        driver = FakeDriver(discoveries=["-rm -rf"])
        session = self.make(self.terminal(), driver).start(self.request())
        self.assertEqual(session.state, SessionState.RUNNING)
        self.assertIsNone(session.provider_session_id)

    def test_launch_env_raises_before_any_record_or_launch(self):
        terminal = self.terminal()
        driver = FakeDriver(launch_env={"TOKEN": "x"})
        with self.assertRaises(SessionManagerError):
            self.make(terminal, driver).start(self.request())
        self.assertEqual(self.store.list(), [])
        self.assertEqual(terminal.calls, [])


# -- the recovery matrix (attach / resume / reconcile) --------------------------


class TestAttachMatrix(ManagerCase):
    def test_running_alive_attaches_same_terminal_and_is_detached(self):
        record = self.seed(SessionState.RUNNING)
        terminal = self.terminal(probes=[Liveness.ALIVE])
        driver = FakeDriver()
        result = self.make(terminal, driver).attach(record.id)

        self.assertIsInstance(result, AttachResult)
        self.assertEqual(result.session.state, SessionState.DETACHED)
        self.assertEqual(result.session.terminal_id, record.terminal_id)
        self.assertEqual(result.session.last_healthy_at, NOW_STORED)
        self.assertEqual(result.argv[-1], f"={record.terminal_id}")
        self.assertEqual(terminal.names("attach_argv"),
                         [("attach_argv", record.terminal_id)])
        self.assertEqual(terminal.names("start"), [])
        self.assertEqual(driver.probe_runs, [])
        self.assertEqual(self.store.get(record.id), result.session)

    def test_detached_dead_with_supported_id_resumes_natively(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD, Liveness.ALIVE],
                                 exit_status=137)
        driver = FakeDriver()
        result = self.make(terminal, driver).attach(record.id)

        self.assertEqual(driver.probe_runs, [self.remote_run])
        self.assertEqual(driver.resumed, [(CWD, PROVIDER_ID)])
        # O pane morto e removido antes de relancar com o MESMO nome.
        self.assertEqual(
            [c[0] for c in terminal.calls],
            ["probe", "capture_exit_status", "stop", "start", "probe",
             "attach_argv"])
        self.assertEqual(terminal.names("start"),
                         [("start", record.terminal_id, CWD,
                           ("codex", "resume", PROVIDER_ID))])
        self.assertEqual(terminal.state_at_start, [SessionState.STARTING])
        self.assertEqual(result.session.state, SessionState.RUNNING)
        self.assertEqual(result.session.provider_session_id, PROVIDER_ID)
        self.assertEqual(result.session.last_healthy_at, NOW_STORED)
        self.assertIsNotNone(result.argv)

    def test_detached_dead_without_id_is_recovery_required(self):
        record = self.seed(SessionState.DETACHED, provider_id=None)
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver()
        result = self.make(terminal, driver).attach(record.id)
        self.assertEqual(result.session.state, SessionState.RECOVERY_REQUIRED)
        self.assertIsNone(result.argv)
        self.assertEqual(terminal.names("start"), [])
        self.assertEqual(driver.probe_runs, [])  # sem id, nem probe remoto

    def test_detached_dead_with_unsupported_resume_is_recovery_required(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver(resume_supported=False)
        result = self.make(terminal, driver).attach(record.id)
        self.assertEqual(result.session.state, SessionState.RECOVERY_REQUIRED)
        self.assertIsNone(result.argv)
        self.assertEqual(driver.probe_runs, [self.remote_run])
        self.assertEqual(driver.resumed, [])
        self.assertEqual(terminal.names("start"), [])

    def test_dead_with_exit_status_zero_is_completed_never_relaunched(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD], exit_status=0)
        driver = FakeDriver()
        result = self.make(terminal, driver).attach(record.id)
        self.assertEqual(result.session.state, SessionState.COMPLETED)
        self.assertIsNone(result.argv)
        self.assertEqual(terminal.names("start"), [])
        self.assertEqual(driver.probe_runs, [])

    def test_any_active_state_with_unknown_probe_is_recovery_required(self):
        for state in ACTIVE_STATES:
            with self.subTest(state=state):
                record = self.seed(state)
                terminal = self.terminal(probes=[Liveness.UNKNOWN])
                driver = FakeDriver()
                result = self.make(terminal, driver).attach(record.id)
                self.assertEqual(result.session.state,
                                 SessionState.RECOVERY_REQUIRED)
                self.assertIsNone(result.argv)
                self.assertEqual(terminal.names("start"), [])
                self.assertEqual(terminal.names("stop"), [])
                self.assertEqual(driver.probe_runs, [])
                self.assertEqual(self.remote_run.calls, [])

    def test_completed_and_failed_remain_untouched_without_probe(self):
        for state in (SessionState.COMPLETED, SessionState.FAILED):
            with self.subTest(state=state):
                record = self.seed(state)
                terminal = self.terminal(probes=[Liveness.DEAD])
                result = self.make(terminal).attach(record.id)
                self.assertEqual(result.session, record)
                self.assertIsNone(result.argv)
                self.assertEqual(terminal.calls, [])
                self.assertEqual(self.store.get(record.id), record)

    def test_record_without_terminal_is_recovery_required_without_probe(self):
        record = self.seed(SessionState.STARTING, provider_id=None,
                           with_terminal=False)
        terminal = self.terminal()
        result = self.make(terminal).attach(record.id)
        self.assertEqual(result.session.state, SessionState.RECOVERY_REQUIRED)
        self.assertEqual(terminal.calls, [])


class TestResume(ManagerCase):
    def test_resume_dead_supported_launches_native_resume(self):
        record = self.seed(SessionState.SUSPENDED)
        terminal = self.terminal(probes=[Liveness.DEAD, Liveness.ALIVE])
        driver = FakeDriver()
        result = self.make(terminal, driver).resume(record.id)
        self.assertIsInstance(result, ResumeResult)
        self.assertTrue(result.launched)
        self.assertEqual(result.session.state, SessionState.RUNNING)
        self.assertEqual(terminal.state_at_start, [SessionState.STARTING])
        self.assertEqual(driver.resumed, [(CWD, PROVIDER_ID)])

    def test_resume_alive_does_not_launch(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.ALIVE])
        result = self.make(terminal).resume(record.id)
        self.assertFalse(result.launched)
        self.assertEqual(result.session.state, SessionState.DETACHED)
        self.assertEqual(terminal.names("start"), [])

    def test_resume_launched_but_not_alive_is_recovery_required(self):
        for after in (Liveness.DEAD, Liveness.UNKNOWN):
            with self.subTest(after=after):
                record = self.seed(SessionState.EXITED_RESUMABLE)
                terminal = self.terminal(probes=[Liveness.DEAD, after])
                result = self.make(terminal).resume(record.id)
                self.assertTrue(result.launched)
                self.assertEqual(result.session.state,
                                 SessionState.RECOVERY_REQUIRED)
                self.assertEqual(len(terminal.names("start")), 1)

    def test_resume_start_error_is_ambiguous_and_probed(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD, Liveness.ALIVE],
                                 start_error=TerminalError("timeout"))
        result = self.make(terminal).resume(record.id)
        self.assertEqual(result.session.state, SessionState.RUNNING)
        self.assertEqual(len(terminal.names("start")), 1)

    def test_resume_env_raises_before_touching_the_terminal(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver(resume_env={"TOKEN": "x"})
        with self.assertRaises(SessionManagerError):
            self.make(terminal, driver).resume(record.id)
        self.assertEqual(terminal.names("stop"), [])
        self.assertEqual(terminal.names("start"), [])
        self.assertEqual(self.store.get(record.id), record)

    def test_failed_clearing_of_dead_pane_propagates_without_launch(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD],
                                 stop_error=TerminalError("exit 255"))
        with self.assertRaises(TerminalError):
            self.make(terminal).resume(record.id)
        self.assertEqual(terminal.names("start"), [])
        # STARTING (despachado, nao confirmado) ja estava gravado; a proxima
        # chamada sonda de novo.
        self.assertEqual(self.store.get(record.id).state,
                         SessionState.STARTING)

    def test_stale_concurrent_resumer_fails_before_touching_the_terminal(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])

        def concurrent_winner():
            # Outro resumidor grava STARTING entre a nossa sonda e a escrita.
            current = self.store.get(record.id)
            self.store.replace(current.with_state(SessionState.STARTING))

        terminal.on_exit_status = concurrent_winner
        with self.assertRaises(StaleRevisionError):
            self.make(terminal).resume(record.id)
        self.assertEqual(terminal.names("stop"), [])
        self.assertEqual(terminal.names("start"), [])

    def test_transient_probe_failure_is_not_cached(self):
        for failure in ("unavailable", "help_failed"):
            with self.subTest(failure=failure):
                record = self.seed(SessionState.DETACHED)
                # 1a chamada: sonda DEAD, probe do driver falha, sem
                # lancamento. 2a: sonda DEAD, probe completo, resume, ALIVE.
                terminal = self.terminal(probes=[Liveness.DEAD, Liveness.DEAD,
                                                 Liveness.ALIVE])
                driver = FakeDriver(probes=[failure, "full"])
                manager = self.make(terminal, driver)
                first = manager.resume(record.id)
                self.assertFalse(first.launched)
                self.assertEqual(first.session.state,
                                 SessionState.RECOVERY_REQUIRED)
                second = manager.resume(record.id)
                self.assertTrue(second.launched)
                self.assertEqual(second.session.state, SessionState.RUNNING)
                self.assertEqual(len(driver.probe_runs), 2)

    def test_availability_is_probed_once_per_agent_kind(self):
        codex = FakeDriver(AgentKind.CODEX)
        claude = FakeDriver(AgentKind.CLAUDE)
        first = self.seed(SessionState.DETACHED)
        second = self.seed(SessionState.DETACHED)
        third = self.seed(SessionState.DETACHED, agent=AgentKind.CLAUDE)
        terminal = self.terminal(probes=[Liveness.DEAD])
        manager = self.make(terminal, codex, claude)
        for record in (first, second, third):
            manager.resume(record.id)
        self.assertEqual(len(codex.probe_runs), 1)
        self.assertEqual(len(claude.probe_runs), 1)


class TestReconcile(ManagerCase):
    def test_reconcile_classifies_without_ever_launching(self):
        alive = self.seed(SessionState.RUNNING)
        terminal = self.terminal(probes=[Liveness.ALIVE])
        [result] = self.make(terminal).reconcile(CHECKOUT)
        self.assertEqual(result.id, alive.id)
        self.assertEqual(result.state, SessionState.DETACHED)
        self.assertEqual(result.last_healthy_at, NOW_STORED)
        self.assertEqual(terminal.names("attach_argv"), [])

    def test_reconcile_dead_resumable_is_exited_resumable_no_launch(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver()
        [result] = self.make(terminal, driver).reconcile(CHECKOUT)
        self.assertEqual(result.id, record.id)
        self.assertEqual(result.state, SessionState.EXITED_RESUMABLE)
        self.assertEqual(terminal.names("start"), [])
        self.assertEqual(terminal.names("stop"), [])
        self.assertEqual(driver.resumed, [])

    def test_reconcile_dead_not_resumable_or_unknown(self):
        cases = (
            (Liveness.DEAD, None, None, SessionState.RECOVERY_REQUIRED),
            (Liveness.DEAD, PROVIDER_ID, 0, SessionState.COMPLETED),
            (Liveness.UNKNOWN, PROVIDER_ID, None,
             SessionState.RECOVERY_REQUIRED),
        )
        for liveness, provider_id, status, expected in cases:
            with self.subTest(liveness=liveness, provider_id=provider_id):
                record = self.seed(SessionState.RUNNING,
                                   provider_id=provider_id,
                                   checkout=CheckoutId(
                                       f"c-{liveness}-{str(status).lower()}"))
                terminal = self.terminal(probes=[liveness], exit_status=status)
                [result] = self.make(terminal).reconcile(record.checkout_id)
                self.assertEqual(result.state, expected)
                self.assertEqual(terminal.names("start"), [])

    def test_reconcile_skips_final_and_suspended_and_other_checkouts(self):
        completed = self.seed(SessionState.COMPLETED)
        failed = self.seed(SessionState.FAILED)
        suspended = self.seed(SessionState.SUSPENDED)
        other = self.seed(SessionState.RUNNING, checkout=OTHER_CHECKOUT)
        terminal = self.terminal(probes=[Liveness.ALIVE])
        results = self.make(terminal).reconcile(CHECKOUT)
        self.assertEqual({r.id: r for r in results},
                         {completed.id: completed, failed.id: failed,
                          suspended.id: suspended})
        self.assertEqual(terminal.calls, [])
        self.assertEqual(self.store.get(other.id), other)


class TestStopAndSuspend(ManagerCase):
    def test_stop_is_recorded_only_after_a_dead_probe(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])
        stopped = self.make(terminal).stop(record.id)
        self.assertEqual([c[0] for c in terminal.calls], ["stop", "probe"])
        self.assertEqual(stopped.state, SessionState.COMPLETED)
        self.assertEqual(self.store.get(record.id), stopped)

    def test_stop_not_confirmed_dead_raises_and_keeps_state(self):
        for after in (Liveness.ALIVE, Liveness.UNKNOWN):
            with self.subTest(after=after):
                record = self.seed(SessionState.DETACHED)
                terminal = self.terminal(probes=[after])
                with self.assertRaises(SessionManagerError):
                    self.make(terminal).stop(record.id)
                self.assertEqual(self.store.get(record.id), record)

    def test_stop_error_propagates_and_keeps_state(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(stop_error=TerminalError("exit 255"))
        with self.assertRaises(TerminalError):
            self.make(terminal).stop(record.id)
        self.assertEqual(self.store.get(record.id), record)

    def test_stop_of_final_session_is_a_no_op(self):
        record = self.seed(SessionState.COMPLETED)
        terminal = self.terminal()
        self.assertEqual(self.make(terminal).stop(record.id), record)
        self.assertEqual(terminal.calls, [])

    def test_stop_without_terminal_completes_without_touching_tmux(self):
        record = self.seed(SessionState.STARTING, provider_id=None,
                           with_terminal=False)
        terminal = self.terminal()
        stopped = self.make(terminal).stop(record.id)
        self.assertEqual(stopped.state, SessionState.COMPLETED)
        self.assertEqual(terminal.calls, [])

    def test_suspend_kills_and_records_suspended_after_dead_probe(self):
        record = self.seed(SessionState.DETACHED)
        terminal = self.terminal(probes=[Liveness.DEAD])
        driver = FakeDriver()
        suspended = self.make(terminal, driver).suspend(record.id)
        self.assertEqual([c[0] for c in terminal.calls], ["stop", "probe"])
        self.assertEqual(suspended.state, SessionState.SUSPENDED)
        self.assertEqual(suspended.provider_session_id, PROVIDER_ID)
        self.assertEqual(len(driver.probe_runs), 1)

    def test_suspend_refuses_when_the_conversation_is_not_resumable(self):
        cases = ((None, True), (PROVIDER_ID, False))
        for provider_id, supported in cases:
            with self.subTest(provider_id=provider_id, supported=supported):
                record = self.seed(SessionState.DETACHED,
                                   provider_id=provider_id)
                terminal = self.terminal()
                driver = FakeDriver(resume_supported=supported)
                with self.assertRaises(SessionManagerError):
                    self.make(terminal, driver).suspend(record.id)
                self.assertEqual(terminal.calls, [])
                self.assertEqual(self.store.get(record.id), record)

    def test_suspend_of_final_session_raises(self):
        record = self.seed(SessionState.COMPLETED)
        terminal = self.terminal()
        with self.assertRaises(SessionManagerError):
            self.make(terminal).suspend(record.id)
        self.assertEqual(terminal.calls, [])


class TestList(ManagerCase):
    def test_list_filters_by_checkout(self):
        mine = self.seed(SessionState.RUNNING)
        other = self.seed(SessionState.RUNNING, checkout=OTHER_CHECKOUT)
        manager = self.make(self.terminal())
        self.assertEqual(manager.list(CHECKOUT), [mine])
        self.assertEqual({s.id for s in manager.list()}, {mine.id, other.id})


class TestTerminalName(unittest.TestCase):
    def test_terminal_name_is_derived_from_the_session_id(self):
        session = AgentSession.new(CHECKOUT, AgentKind.CODEX, CWD, "t")
        name = terminal_name(session.id)
        self.assertIsInstance(name, TerminalId)
        self.assertEqual(name, f"asb-{session.id}")
        ProviderSessionId(PROVIDER_ID)  # o id de teste e valido


if __name__ == "__main__":
    unittest.main()
