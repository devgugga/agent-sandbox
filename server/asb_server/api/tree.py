"""server/asb_server/api/tree.py — GET /api/tree.

Requires the session cookie: reuses `auth.require_session` rather than a
second cookie check (amendment Section A/Section F — Task 4 already owns
that mechanism). The only condition that turns this route into an HTTP
error is a registry failure (`Snapshot.registry_error`); every
per-project or per-checkout failure stays data inside a 200 body via
`models.tree_response`, the one converter Task 3 built (amendment
Section E).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_session
from ..models import TreeResponse, tree_response
from ..snapshot import SnapshotService

router = APIRouter(prefix="/api", tags=["tree"])


def get_snapshot_service(request: Request) -> SnapshotService:
    """Lazily built and cached on `app.state` — the same pattern
    `auth.get_auth_manager` uses, and load-bearing here for a different
    reason: single-flight needs ONE long-lived instance shared by every
    request, not a fresh one per call."""
    state = request.app.state
    service = getattr(state, "snapshot_service", None)
    if service is None:
        service = SnapshotService(state.snapshot_reader)
        state.snapshot_service = service
    return service


@router.get("/tree", response_model=TreeResponse,
            dependencies=[Depends(require_session)])
async def get_tree(
    request: Request,
    service: SnapshotService = Depends(get_snapshot_service),  # noqa: B008 (FastAPI idiom)
) -> TreeResponse:
    snapshot, read_at = await service.read()
    # Surfaced in the per-request log line (`app._log_requests`): two
    # concurrent requests that collapsed onto the same physical read show
    # the SAME `read_at` in the journal — spec Section 17.6's
    # observability requirement, without a second, dedicated log line.
    request.state.log_extra = f"read_at={read_at.isoformat()}"
    if snapshot.registry_error is not None:
        raise HTTPException(status_code=503, detail=snapshot.registry_error)
    return tree_response(snapshot, read_at=read_at)
