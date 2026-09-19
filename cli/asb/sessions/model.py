"""cli/asb/sessions/model.py — identidade e registro imutavel de sessao.

Uma sessao de agente e o processo de um assistente (codex, claude,
antigravity) rodando dentro de um checkout, opcionalmente ligado a um
terminal (tmux) e a uma sessao nativa do provedor. Este modulo nao toca
tmux, systemd nem provedor algum; so define a forma dos dados.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from asb.checkouts.model import CheckoutId

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# provider_session_id vem de fora (APIs do Codex, Claude, Antigravity): o
# formato e do provedor, nao nosso, entao so recusamos vazio, espaco em
# branco, metacaracteres de shell e um "-" inicial (que um argv de resume
# leria como flag de linha de comando) — sem exigir minusculas-64.
_SHELL_METACHARACTERS = re.compile(r"[;&|`$()<>{}\[\]\\'\"\n\r]")


class SessionId(str):
    """Identificador estavel de uma sessao (prefixo "s-" + hex aleatorio)."""

    def __new__(cls, value: str) -> "SessionId":
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"invalid session id: {value!r}")
        return super().__new__(cls, value)


class TerminalId(str):
    """Identificador do terminal (tmux) ligado a uma sessao."""

    def __new__(cls, value: str) -> "TerminalId":
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"invalid terminal id: {value!r}")
        return super().__new__(cls, value)


class ProviderSessionId(str):
    """Identificador de sessao nativo do provedor externo."""

    def __new__(cls, value: str) -> "ProviderSessionId":
        if not isinstance(value, str) or not value \
                or re.search(r"\s", value) \
                or _SHELL_METACHARACTERS.search(value) \
                or value.startswith("-"):
            raise ValueError(f"invalid provider session id: {value!r}")
        return super().__new__(cls, value)


class AgentKind(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    ANTIGRAVITY = "antigravity"


class SessionState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    DETACHED = "detached"
    SUSPENDED = "suspended"
    EXITED_RESUMABLE = "exited_resumable"
    COMPLETED = "completed"
    RECOVERY_REQUIRED = "recovery_required"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentSession:
    id: SessionId
    checkout_id: CheckoutId
    agent: AgentKind
    cwd: Path
    title: str
    state: SessionState
    terminal_id: TerminalId | None
    provider_session_id: ProviderSessionId | None
    last_healthy_at: datetime | None
    revision: int = 0
    # Instante do `start`. `None` em registros gravados antes do campo:
    # sem ele nao ha descoberta preguicosa do id do provedor.
    started_at: datetime | None = None
    # Instante (arredondado para cima ao segundo) da primeira escrita num
    # estado final; `None` enquanto viva e em registros antigos.
    ended_at: datetime | None = None

    @classmethod
    def new(cls, checkout_id: CheckoutId, agent: AgentKind, cwd: Path,
            title: str, *,
            started_at: datetime | None = None) -> "AgentSession":
        return cls(
            id=SessionId(f"s-{secrets.token_hex(8)}"),
            checkout_id=checkout_id,
            agent=agent,
            cwd=cwd,
            title=title,
            state=SessionState.STARTING,
            terminal_id=None,
            provider_session_id=None,
            last_healthy_at=None,
            started_at=started_at,
        )

    def with_state(self, state: SessionState, **changes: object) -> "AgentSession":
        terminal_id = changes.get("terminal_id")
        if terminal_id is not None and not isinstance(terminal_id, TerminalId):
            changes["terminal_id"] = TerminalId(terminal_id)
        provider_session_id = changes.get("provider_session_id")
        if provider_session_id is not None \
                and not isinstance(provider_session_id, ProviderSessionId):
            changes["provider_session_id"] = ProviderSessionId(provider_session_id)
        return replace(self, state=state, **changes)
