"""cli/asb/sessions/manager.py — maquina de estados de recuperacao de sessoes.

Um `SessionManager` e ligado a UM workspace: recebe o `TmuxTerminal` daquele
workspace, os drivers construidos com o `sessions_root` do volume de sessao
dele, o `SessionStore` compartilhado e um `remote_run` que executa DENTRO do
sandbox (o binario da imagem e quem decide se ha resume nativo).

Regras que cada ramo abaixo respeita:

- o tmux e a fonte da verdade sobre liveness; um `TerminalId` salvo nao e
  evidencia de processo vivo. ALIVE reanexa ao MESMO terminal; DEAD com um
  `ProviderSessionId` e resume confirmado relanca o resume nativo; DEAD com
  exit status 0 e conclusao voluntaria (`completed`, nunca relancada);
  UNKNOWN e sempre `recovery_required` e nunca lanca nem retoma processo;
- uma mudanca de estado so e gravada depois que o terminal a confirma, e
  cada passo grava o ULTIMO registro devolvido pelo store (revisao correta);
- `TerminalError` de `start()` e ambiguo (a sessao PODE existir): sonda
  antes de concluir, nunca re-tenta as cegas;
- so `TerminalError` e capturado; cancelamento (`KeyboardInterrupt`...)
  sempre chega ao chamador.
"""
from __future__ import annotations

import functools
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from asb.agents.base import (
    AgentAvailability, AgentDriver, LaunchCommand, RunFn, SessionEvidence,
)
from asb.checkouts.model import CheckoutId
from asb.sessions.model import (
    AgentKind, AgentSession, ProviderSessionId, SessionId, SessionState,
    TerminalId,
)
from asb.sessions.store import SessionStore, StaleRevisionError
from asb.sessions.terminal import Liveness, TerminalError, TmuxTerminal

# Descoberta do id do provedor: ate 5 tentativas, 1 s entre elas.
_DISCOVERY_ATTEMPTS = 5
_DISCOVERY_INTERVAL_SECONDS = 1.0

# Estados finais: nunca sondados, nunca relancados.
_FINAL = frozenset({SessionState.COMPLETED, SessionState.FAILED})

# Estados que `reconcile` nao sonda: suspenso de proposito, ou em voo noutro
# processo.
_NOT_RECONCILED = frozenset({SessionState.SUSPENDED, SessionState.STARTING})


class SessionManagerError(RuntimeError):
    """Operacao recusada ou nao confirmada pelo terminal."""


@dataclass(frozen=True)
class StartSession:
    """Pedido de uma nova sessao. `cwd` e o checkout de EXECUCAO do sandbox
    (`ConnectionInfo.project_root`): o mesmo caminho absoluto no host e no
    container, onde o agente roda e de onde o Claude deriva o slug."""

    checkout_id: CheckoutId
    agent: AgentKind
    cwd: Path
    title: str


@dataclass(frozen=True)
class AttachResult:
    """`argv` interativo que anexa ao terminal da sessao, ou `None` quando
    nao ha terminal vivo confirmado para anexar."""

    session: AgentSession
    argv: tuple[str, ...] | None


@dataclass(frozen=True)
class ResumeResult:
    """`launched` diz se um comando de resume nativo foi despachado; o
    estado final esta em `session`."""

    session: AgentSession
    launched: bool


def terminal_name(session_id: SessionId) -> TerminalId:
    """Nome tmux derivado so de um `SessionId` validado."""
    return TerminalId(f"asb-{SessionId(session_id)}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _argv_only(command: LaunchCommand) -> tuple[str, ...]:
    """`TmuxTerminal.start` recebe so argv; um `env` seria descartado em
    silencio, entao recusamos alto. Um driver que precise de env tem de
    ganhar `new-session -e` com o mesmo escape de `;`/`#` da Tarefa 7."""
    if command.env:
        raise SessionManagerError(
            "o driver devolveu env de lancamento, que o terminal nao "
            f"repassa: {sorted(command.env)}")
    return command.argv


class SessionManager:
    def __init__(self, *, store: SessionStore, terminal: TmuxTerminal,
                 drivers: Mapping[AgentKind, AgentDriver], remote_run: RunFn,
                 clock: Callable[[], datetime] = _utc_now,
                 sleep: Callable[[float], object] = time.sleep) -> None:
        self._store = store
        self._terminal = terminal
        self._drivers = drivers
        self._remote_run = remote_run
        self._clock = clock
        self._sleep = sleep
        self._availability: dict[AgentKind, AgentAvailability] = {}

    # -- leitura -------------------------------------------------------------

    def list(self, checkout_id: CheckoutId | None = None) -> list[AgentSession]:
        return [s for s in self._store.list()
                if checkout_id is None or s.checkout_id == checkout_id]

    # -- inicio ----------------------------------------------------------------

    def start(self, request: StartSession) -> AgentSession:
        driver = self._drivers[request.agent]
        # Um provedor que aceita o id no lancamento (Claude) recebe um UUID
        # novo, gravado na escrita STARTING, ANTES do lancamento, e nunca
        # passa por descoberta.
        assigned = (ProviderSessionId(str(uuid.uuid4()))
                    if driver.assigns_session_id_at_launch else None)
        argv = _argv_only(driver.launch(request.cwd, assigned))
        record = self._store.insert(AgentSession.new(
            request.checkout_id, request.agent, request.cwd, request.title))
        record = self._store.replace(record.with_state(
            SessionState.STARTING, terminal_id=terminal_name(record.id),
            provider_session_id=assigned))
        baseline = (None if assigned is not None
                    else driver.capture_before(request.cwd))
        liveness = self._launch(record, argv)
        if liveness is Liveness.DEAD:
            return self._store.replace(record.with_state(SessionState.FAILED))
        if liveness is Liveness.UNKNOWN:
            return self._store.replace(
                record.with_state(SessionState.RECOVERY_REQUIRED))
        provider_session_id = (assigned if baseline is None
                               else self._discover(driver, baseline))
        return self._store.replace(record.with_state(
            SessionState.RUNNING,
            provider_session_id=provider_session_id,
            last_healthy_at=self._clock(),
        ))

    # -- abrir / retomar / reconciliar -----------------------------------------

    def attach(self, session_id: SessionId) -> AttachResult:
        """Fluxo "abrir sessao": reanexa se vivo, retoma nativamente se
        morto e retomavel, senao nao ha o que anexar."""
        record, _ = self._recover(self._store.get(session_id), launch=True)
        if record.state in (SessionState.RUNNING, SessionState.DETACHED):
            return AttachResult(record, tuple(
                self._terminal.attach_argv(record.terminal_id)))
        return AttachResult(record, None)

    def resume(self, session_id: SessionId) -> ResumeResult:
        record, launched = self._recover(self._store.get(session_id),
                                         launch=True)
        return ResumeResult(record, launched)

    def reconcile(self, checkout_id: CheckoutId) -> list[AgentSession]:
        """Alinha o registro ao tmux para as sessoes de `checkout_id`, sem
        NUNCA lancar processo. `suspended` fica como esta: o terminal morto
        e o esperado ali. `starting` tambem: pertence a um start ou resume
        em voo noutro processo (`attach`/`resume` recuperam um `starting`
        deixado por um processo que caiu). So transicoes reais sao
        gravadas: um refresh repetido nao sobe revisoes."""
        results = []
        for record in self.list(checkout_id):
            if record.state not in _NOT_RECONCILED:
                record, _ = self._recover(record, launch=False)
            results.append(record)
        return results

    # -- encerrar ----------------------------------------------------------------

    def suspend(self, session_id: SessionId) -> AgentSession:
        """Encerra o processo mantendo a conversa para resume nativo; so
        quando essa conversa e de fato retomavel."""
        record = self._store.get(session_id)
        if record.state in _FINAL:
            raise SessionManagerError(
                f"sessao {record.id} ja terminou ({record.state})")
        if not self._can_resume(record):
            raise SessionManagerError(
                f"sessao {record.id} nao tem conversa retomavel; use stop")
        return self._kill(record, SessionState.SUSPENDED)

    def stop(self, session_id: SessionId) -> AgentSession:
        """Encerra a sessao pelo operador: `completed`, nunca relancada."""
        record = self._store.get(session_id)
        if record.state in _FINAL:
            return record
        if record.terminal_id is None:
            # O terminal_id e gravado ANTES de qualquer lancamento: sem ele,
            # nenhum processo chegou a existir.
            return self._store.replace(
                record.with_state(SessionState.COMPLETED))
        try:
            return self._kill(record, SessionState.COMPLETED)
        except StaleRevisionError:
            # O tmux ja confirmou DEAD; um refresh concorrente regravou a
            # classificacao entre o kill e esta escrita. Sem isto o
            # registro ficava `exited_resumable` e o Enter relancava uma
            # sessao que o operador parou.
            return self._complete_after_race(record.id)

    def _complete_after_race(self, session_id: SessionId) -> AgentSession:
        """Regrava COMPLETED sobre o registro atual, com a sonda DEAD de
        `_kill` como evidencia. Um estado final concorrente fica como esta;
        um relancamento concorrente (`starting`/`running`, so gravados por
        start e resume) NUNCA vira `completed`."""
        fresh = self._store.get(session_id)
        if fresh.state in _FINAL:
            return fresh
        if fresh.state in (SessionState.STARTING, SessionState.RUNNING):
            raise SessionManagerError(
                f"sessao {fresh.id} foi relancada durante o stop "
                f"({fresh.state}); rode o stop de novo")
        return self._store.replace(fresh.with_state(SessionState.COMPLETED))

    # -- ramos internos ----------------------------------------------------------

    def _recover(self, record: AgentSession, *,
                 launch: bool) -> tuple[AgentSession, bool]:
        """Classifica a sessao pela evidencia do terminal; com `launch`,
        retoma nativamente um terminal morto e retomavel. Devolve o ultimo
        registro gravado e se um resume foi despachado."""
        if record.state in _FINAL:
            return record, False
        # Sem `launch` (reconcile) um estado que nao muda nao e regravado.
        settle = functools.partial(self._settle, rewrite=launch)
        if record.terminal_id is None:
            return settle(record, SessionState.RECOVERY_REQUIRED), False
        liveness = self._terminal.probe(record.terminal_id)
        if liveness is Liveness.ALIVE:
            return settle(record, SessionState.DETACHED,
                          last_healthy_at=self._clock()), False
        if liveness is Liveness.UNKNOWN:
            return settle(record, SessionState.RECOVERY_REQUIRED), False
        if self._terminal.capture_exit_status(record.terminal_id) == 0:
            return settle(record, SessionState.COMPLETED), False
        if not self._can_resume(record):
            return settle(record, SessionState.RECOVERY_REQUIRED), False
        if not launch:
            return settle(record, SessionState.EXITED_RESUMABLE), False
        return self._native_resume(record), True

    def _settle(self, record: AgentSession, state: SessionState, *,
                rewrite: bool, **changes: object) -> AgentSession:
        """Grava a classificacao de `_recover`. Com `rewrite=False`, um
        registro que ja esta em `state` volta como esta, sem escrita (nem
        `last_healthy_at`): so transicoes reais sobem a revisao. Nunca usado
        pela escrita STARTING de `_native_resume`, que TEM de ser checada
        por revisao."""
        if not rewrite and record.state is state:
            return record
        return self._store.replace(record.with_state(state, **changes))

    def _native_resume(self, record: AgentSession) -> AgentSession:
        driver = self._drivers[record.agent]
        argv = _argv_only(driver.resume(record.cwd, record.provider_session_id))
        # STARTING primeiro (a sonda DEAD e a evidencia): a escrita checada
        # por revisao faz um segundo resumidor concorrente falhar com
        # `StaleRevisionError` ANTES de tocar o terminal do vencedor.
        record = self._store.replace(record.with_state(SessionState.STARTING))
        # O pane morto (remain-on-exit) ainda ocupa o nome: remove-lo antes
        # de relancar com o MESMO TerminalId.
        self._terminal.stop(record.terminal_id)
        if self._launch(record, argv) is not Liveness.ALIVE:
            # A conversa nativa continua existindo: nao e `failed`.
            return self._store.replace(
                record.with_state(SessionState.RECOVERY_REQUIRED))
        return self._store.replace(record.with_state(
            SessionState.RUNNING, last_healthy_at=self._clock()))

    def _launch(self, record: AgentSession, argv: Sequence[str]) -> Liveness:
        try:
            self._terminal.start(record.terminal_id, record.cwd, argv)
        except TerminalError:
            # Ambiguo (timeout, falha do ssh, exit 255): a sessao PODE ter
            # sido criada. A sonda abaixo decide; nunca re-tentamos.
            pass
        return self._terminal.probe(record.terminal_id)

    def _can_resume(self, record: AgentSession) -> bool:
        """Id do provedor presente E resume confirmado pelo binario do
        sandbox. O resultado so fica em cache, por tipo de agente, quando
        o binario respondeu `--version` e `--help`; senao a proxima
        chamada sonda de novo."""
        if record.provider_session_id is None:
            return False
        availability = self._availability.get(record.agent)
        if availability is None:
            availability = self._drivers[record.agent].probe(self._remote_run)
            if availability.probed_fully:
                # Uma falha ao executar --version ou --help pode ser
                # transitoria: vale so para esta chamada.
                self._availability[record.agent] = availability
        return availability.resume_supported

    def _kill(self, record: AgentSession, state: SessionState) -> AgentSession:
        self._terminal.stop(record.terminal_id)
        if self._terminal.probe(record.terminal_id) is not Liveness.DEAD:
            raise SessionManagerError(
                f"terminal {record.terminal_id} nao confirmou o encerramento")
        return self._store.replace(record.with_state(state))

    def _discover(self, driver: AgentDriver,
                  baseline: SessionEvidence) -> ProviderSessionId | None:
        """Descoberta limitada: cada tentativa compara contra o instantaneo
        PRE-lancamento; zero, ambiguo ou invalido apos o limite nao grava
        id — nunca o candidato "mais recente"."""
        for attempt in range(_DISCOVERY_ATTEMPTS):
            if attempt:
                self._sleep(_DISCOVERY_INTERVAL_SECONDS)
            found = driver.discover_session_id(driver.capture_after(baseline))
            try:
                # `None` (zero ou ambiguo) e um id malformado falham aqui.
                return ProviderSessionId(found)
            except ValueError:
                continue
        return None
