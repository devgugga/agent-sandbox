"""cli/asb/projects/model.py — identidade e registro imutavel de projeto.

Um projeto e o repositorio raiz: onde fica o checkout primario e o diretorio
que guarda os worktrees dos checkouts secundarios. Este modulo nao toca disco
nem git; so define a forma dos dados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProjectId(str):
    """Identificador estavel de um projeto (prefixo "p-" + hex aleatorio)."""

    def __new__(cls, value: str) -> "ProjectId":
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError(f"invalid project id: {value!r}")
        return super().__new__(cls, value)


@dataclass(frozen=True)
class Project:
    id: ProjectId
    primary: Path
    integration_branch: str
    worktree_root: Path
    # Canonical `git rev-parse --git-common-dir` for `primary`. Optional so
    # existing positional construction (id, primary, integration_branch,
    # worktree_root) keeps working; the registry always fills it in.
    git_common_dir: Path | None = None
