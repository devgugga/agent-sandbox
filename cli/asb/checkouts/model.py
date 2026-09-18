"""cli/asb/checkouts/model.py — identidade e registro imutavel de checkout.

Um checkout e um caminho de trabalho git dentro de um projeto: o checkout
primario ou um worktree secundario. Este modulo nao toca disco nem git; so
define a forma dos dados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from asb.projects.model import ProjectId

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class CheckoutId(str):
    """Identificador estavel de um checkout (prefixo "c-" + hex aleatorio)."""

    def __new__(cls, value: str) -> "CheckoutId":
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"invalid checkout id: {value!r}")
        return super().__new__(cls, value)


class CheckoutKind(StrEnum):
    PRIMARY = "primary"
    WORKTREE = "worktree"


class CheckoutState(StrEnum):
    CLEAN = "clean"
    DIRTY = "dirty"
    DETACHED = "detached"


@dataclass(frozen=True)
class Checkout:
    id: CheckoutId
    project_id: ProjectId
    path: Path
    kind: CheckoutKind
    branch: str
    state: CheckoutState
    workspace: str


class FinishState(StrEnum):
    """Resultado de `finish`/`cleanup`. So `CLEANED` removeu recursos; um
    `CLEANUP_PENDING` pode ter removido alguns e diz o que sobrou."""

    MERGED = "merged"
    CONFLICT = "conflict"
    BLOCKED = "blocked"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANED = "cleaned"


@dataclass(frozen=True)
class FinishCheckout:
    """Pedido de integracao de um worktree em `target_branch`. Limpeza e
    remocao do branch local so com escolha explicita."""

    checkout_id: CheckoutId
    target_branch: str
    cleanup_after_merge: bool = False
    delete_merged_branch: bool = False
    # O branch e o commit do sandbox que a confirmacao mostrou; com eles,
    # o export recusa se o sandbox mudou desde entao.
    expected_sandbox_branch: str | None = None
    expected_sandbox_commit: str | None = None


@dataclass(frozen=True)
class FinishResult:
    state: FinishState
    source_commit: str | None
    target_commit: str | None
    message: str

    @classmethod
    def blocked(cls, message: str, source_commit: str | None = None,
                target_commit: str | None = None) -> "FinishResult":
        return cls(FinishState.BLOCKED, source_commit, target_commit, message)

    @classmethod
    def cleanup_pending(cls, source_commit: str | None,
                        target_commit: str | None,
                        message: str) -> "FinishResult":
        return cls(FinishState.CLEANUP_PENDING, source_commit, target_commit,
                   message)
