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
