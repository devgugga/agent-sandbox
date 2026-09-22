"""server/asb_server/models.py — the wire contract and its converter.

The Pydantic response models below are the daemon's contract (spec
Section 7.3, `docs/superpowers/specs/2026-09-22-asb-web-foundation-design.md`).
`tree_response` turns an `asb.interfaces.snapshot.Snapshot` (Task 2) into a
`TreeResponse`, grouping the same way `tui_model.build_tree` does: checkouts
and unregistered worktrees by project, sessions by checkout.

Spec Section 7.3: "All operator- or Git-sourced strings ... pass through
`tui_model.sanitize`" — titles, branches, paths, reasons and errors are
that sentence's examples, not the whole of it. Every free-text field this
converter builds, including `workspace` (read verbatim from the
operator-editable registry file — `cli/asb/projects/registry.py`'s loader
does not validate its content), passes through `sanitize` here, even when
the source already scrubbed C0/C1 controls (`sanitize` also catches bidi
overrides and other invisible formatting characters that a narrower
filter, or React's own HTML escaping, does not). Internally generated ids
(`checkout_id`, `project_id`, `session_id`, `terminal_id`) and closed enum
vocabularies (`kind`, `status`, `agent`, `state`) are not operator text and
are left as-is; the enum fields reuse `asb`'s own `StrEnum`s rather than
duplicating their literal values — one definition of each vocabulary, not
two that can drift apart.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from asb.checkouts.model import CheckoutId, CheckoutKind
from asb.interfaces.snapshot import Snapshot
from asb.interfaces.tui_model import CheckoutView, UnregisteredView, sanitize
from asb.projects.model import Project, ProjectId
from asb.runtime.sandbox import WorkspaceStatus
from asb.sessions.model import AgentKind, AgentSession, SessionState
from pydantic import BaseModel


def _sanitized(value: str | None) -> str | None:
    return sanitize(value) if value is not None else None


class ErrorDetail(BaseModel):
    """The shape of every non-2xx JSON body this contract documents:
    FastAPI's own `{"detail": ...}` envelope, `detail` always a plain
    string here — an `HTTPException`'s `detail`, whether explicit
    (`/api/tree`'s 503, `snapshot.registry_error`, already sanitized by
    Task 2) or the default reason phrase FastAPI fills in when a route
    raises without one (`/api/tree`'s 401, `/api/auth/session`'s 401/403,
    `/api/auth/me`'s 401). Fix round 1 (Important 2): documented so
    `openapi-typescript`/`openapi-fetch` (spec Section 9.1) generate a
    typed error shape instead of leaving these routes' non-2xx responses
    undocumented."""

    detail: str


class SessionNode(BaseModel):
    id: str
    agent: AgentKind
    state: SessionState
    title: str
    cwd: str
    terminal_id: str | None
    started_at: datetime | None
    ended_at: datetime | None
    last_healthy_at: datetime | None


class CheckoutNode(BaseModel):
    id: str
    kind: CheckoutKind
    path: str
    workspace: str
    status: WorkspaceStatus
    reason: str | None
    branch: str | None
    detached: bool
    host_branch: bool
    missing: bool
    merged: bool
    error: str | None
    sessions: list[SessionNode]


class UnregisteredNode(BaseModel):
    path: str
    branch: str | None
    detached: bool
    missing: bool
    prunable: bool


class ProjectNode(BaseModel):
    id: str
    name: str
    primary_path: str
    integration_branch: str
    error: str | None
    checkouts: list[CheckoutNode]
    unregistered: list[UnregisteredNode]


class TreeResponse(BaseModel):
    read_at: datetime
    projects: list[ProjectNode]


def _session_node(session: AgentSession) -> SessionNode:
    return SessionNode(
        id=str(session.id),
        agent=session.agent,
        state=session.state,
        title=sanitize(session.title),
        cwd=sanitize(str(session.cwd)),
        terminal_id=str(session.terminal_id) if session.terminal_id else None,
        started_at=session.started_at,
        ended_at=session.ended_at,
        last_healthy_at=session.last_healthy_at,
    )


def _checkout_node(view: CheckoutView, sessions: list[AgentSession]) -> CheckoutNode:
    return CheckoutNode(
        id=str(view.checkout_id),
        kind=view.kind,
        path=sanitize(str(view.source_path)),
        workspace=sanitize(view.workspace),
        status=view.status,
        reason=_sanitized(view.reason),
        branch=_sanitized(view.branch),
        detached=view.detached,
        host_branch=view.host_branch,
        missing=view.missing,
        merged=view.merged,
        error=_sanitized(view.error),
        sessions=[_session_node(session) for session in sessions],
    )


def _unregistered_node(view: UnregisteredView) -> UnregisteredNode:
    return UnregisteredNode(
        path=sanitize(str(view.path)),
        branch=_sanitized(view.branch),
        detached=view.detached,
        missing=view.missing,
        prunable=view.prunable,
    )


def _project_node(project: Project, checkouts: list[CheckoutView],
                   unregistered: list[UnregisteredView],
                   sessions_by_checkout: Mapping[CheckoutId, list[AgentSession]],
                   error: str | None) -> ProjectNode:
    return ProjectNode(
        id=str(project.id),
        name=sanitize(project.primary.name),
        primary_path=sanitize(str(project.primary)),
        integration_branch=sanitize(project.integration_branch),
        error=_sanitized(error),
        checkouts=[_checkout_node(view, sessions_by_checkout.get(view.checkout_id, []))
                   for view in checkouts],
        unregistered=[_unregistered_node(view) for view in unregistered],
    )


def tree_response(snapshot: Snapshot, *, read_at: datetime) -> TreeResponse:
    """`snapshot` never carries `registry_error` here — a registry failure
    is the caller's 503 (spec Section 7.6), not a `TreeResponse`. `read_at`
    comes from the caller: `Snapshot` itself has no timestamp, since it is
    the pure result of one read (Task 2), not the record of when it ran."""
    checkouts_by_project: dict[ProjectId, list[CheckoutView]] = {}
    for view in snapshot.checkouts:
        checkouts_by_project.setdefault(view.project_id, []).append(view)
    sessions_by_checkout: dict[CheckoutId, list[AgentSession]] = {}
    for session in snapshot.sessions:
        sessions_by_checkout.setdefault(session.checkout_id, []).append(session)
    unregistered_by_project: dict[ProjectId, list[UnregisteredView]] = {}
    for view in snapshot.unregistered:
        unregistered_by_project.setdefault(view.project_id, []).append(view)

    projects = [
        _project_node(
            project,
            checkouts_by_project.get(project.id, []),
            unregistered_by_project.get(project.id, []),
            sessions_by_checkout,
            snapshot.project_errors.get(project.id),
        )
        for project in snapshot.projects
    ]
    return TreeResponse(read_at=read_at, projects=projects)
