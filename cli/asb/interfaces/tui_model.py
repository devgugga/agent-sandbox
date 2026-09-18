"""cli/asb/interfaces/tui_model.py — a arvore pura da TUI.

`build_tree` transforma projetos, checkouts ja enriquecidos pelo refresh
(status do workspace, branch, tipo) e sessoes ja reconciliadas em linhas
prontas para desenhar. Sem I/O e sem curses: nada aqui roda Git, Podman,
SSH, tmux ou provedor. Todo texto que entra numa linha passa por `sanitize`
(titulos sao entrada do operador; branches e caminhos vem do Git e do disco).
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..checkouts.model import CheckoutId, CheckoutKind
from ..projects.model import Project, ProjectId
from ..runtime.sandbox import WorkspaceStatus
from ..sessions.model import AgentSession, SessionId, SessionState

PLACEHOLDER = "?"
# C0/C1 e DEL (Cc), formatacao invisivel como override bidi (Cf),
# separadores de linha/paragrafo (Zl/Zp) e surrogates soltos (Cs).
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})


def sanitize(text: object) -> str:
    """Troca cada caractere de controle por um marcador visivel."""
    return "".join(PLACEHOLDER if unicodedata.category(ch) in _UNSAFE_CATEGORIES
                   else ch for ch in str(text))


class RowKind(StrEnum):
    PROJECT = "project"
    CHECKOUT = "checkout"
    SESSION = "session"
    NOTE = "note"


@dataclass(frozen=True)
class CheckoutView:
    """Um checkout como o refresh o viu. `branch=None` e branch
    desconhecido; `host_branch` diz que ele foi lido do checkout do
    operador porque o workspace nao estava pronto; `error` e a falha de
    algum passo do refresh para este checkout."""

    checkout_id: CheckoutId
    project_id: ProjectId
    source_path: Path
    workspace: str
    kind: CheckoutKind
    status: WorkspaceStatus
    branch: str | None
    detached: bool = False
    host_branch: bool = False
    reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class TreeRow:
    """Uma linha desenhavel. `key` e estavel entre refreshes (`p:`, `c:`,
    `s:` + id) e e por ela que a selecao sobrevive a um refresh."""

    key: str
    kind: RowKind
    depth: int
    text: str
    expanded: bool | None = None
    project_id: ProjectId | None = None
    checkout_id: CheckoutId | None = None
    session_id: SessionId | None = None
    session_state: SessionState | None = None

    @property
    def selectable(self) -> bool:
        return self.kind is not RowKind.NOTE


def project_key(project_id: str) -> str:
    return f"p:{project_id}"


def checkout_key(checkout_id: str) -> str:
    return f"c:{checkout_id}"


def session_key(session_id: str) -> str:
    return f"s:{session_id}"


def _fold(expanded: bool) -> str:
    return "[-]" if expanded else "[+]"


def _branch_label(view: CheckoutView) -> str:
    if view.branch is None:
        label = "(branch ?)"
    elif view.detached:
        label = f"(detached {view.branch})"
    else:
        label = view.branch
    return f"{label} (host)" if view.host_branch else label


def _status_label(view: CheckoutView) -> str:
    if view.status is WorkspaceStatus.UNAVAILABLE and view.reason:
        return f"unavailable: {view.reason}"
    return str(view.status)


def _checkout_text(view: CheckoutView, expanded: bool) -> str:
    parts = [_fold(expanded), f"[{view.kind}]", _branch_label(view),
             _status_label(view)]
    if view.kind is CheckoutKind.WORKTREE:
        parts.append(str(view.source_path))
    text = "  ".join(parts)
    return f"{text}  !! {view.error}" if view.error else text


def build_tree(projects: Iterable[Project], checkouts: Iterable[CheckoutView],
               sessions: Iterable[AgentSession], *,
               collapsed: frozenset[str] = frozenset(),
               project_errors: Mapping[ProjectId, str] | None = None
               ) -> tuple[TreeRow, ...]:
    """Projetos por caminho primario; em cada um, o primario e depois os
    worktrees por caminho; em cada checkout, as sessoes por titulo. Uma
    sessao de checkout desconhecido nao aparece. `collapsed` guarda as
    chaves dos nos recolhidos."""
    project_errors = project_errors or {}
    by_project: dict[ProjectId, list[CheckoutView]] = {}
    for view in checkouts:
        by_project.setdefault(view.project_id, []).append(view)
    by_checkout: dict[CheckoutId, list[AgentSession]] = {}
    for session in sessions:
        by_checkout.setdefault(session.checkout_id, []).append(session)

    rows: list[TreeRow] = []
    for project in sorted(projects, key=lambda p: (str(p.primary), p.id)):
        key = project_key(project.id)
        expanded = key not in collapsed
        text = f"{_fold(expanded)} {project.primary.name}  {project.primary}"
        if project.id in project_errors:
            text += f"  !! {project_errors[project.id]}"
        rows.append(TreeRow(key, RowKind.PROJECT, 0, sanitize(text),
                            expanded, project_id=project.id))
        if not expanded:
            continue
        views = sorted(by_project.get(project.id, []),
                       key=lambda v: (v.kind is not CheckoutKind.PRIMARY,
                                      str(v.source_path), v.checkout_id))
        if not views:
            rows.append(TreeRow(f"n:{project.id}", RowKind.NOTE, 1,
                                "(no checkouts)", project_id=project.id))
        for view in views:
            ckey = checkout_key(view.checkout_id)
            cexpanded = ckey not in collapsed
            rows.append(TreeRow(
                ckey, RowKind.CHECKOUT, 1,
                sanitize(_checkout_text(view, cexpanded)), cexpanded,
                project_id=project.id, checkout_id=view.checkout_id))
            if not cexpanded:
                continue
            for session in sorted(by_checkout.get(view.checkout_id, []),
                                  key=lambda s: (s.title, s.id)):
                rows.append(TreeRow(
                    session_key(session.id), RowKind.SESSION, 2,
                    sanitize(f"{session.agent}  {session.state}  "
                             f"{session.title}"),
                    project_id=project.id, checkout_id=view.checkout_id,
                    session_id=session.id, session_state=session.state))
    return tuple(rows)
