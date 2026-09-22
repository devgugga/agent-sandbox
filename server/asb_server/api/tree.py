"""server/asb_server/api/tree.py — GET /api/tree.

Requires the session cookie: reuses `auth.require_session` rather than a
second cookie check (amendment Section A/Section F — Task 4 already owns
that mechanism). The only condition that turns this route into an HTTP
error is a registry failure (`Snapshot.registry_error`); every
per-project or per-checkout failure stays data inside a 200 body via
`models.tree_response`, the one converter Task 3 built (amendment
Section E).

Fix round 1 (Important 2): the route documents its 401 and 503
responses via `responses=`, both shaped `models.ErrorDetail`. Spec
Section 9.1 generates a typed client (`openapi-typescript` /
`openapi-fetch`) from this schema; an undocumented non-2xx response
leaves the front end with no typed shape for the 503 `{detail}` body it
renders as a stale-tree banner, or for the 401 it must treat as
re-authentication.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_session
from ..models import ErrorDetail, TreeResponse, tree_response
from ..snapshot import SnapshotService

router = APIRouter(prefix="/api", tags=["tree"])


def get_snapshot_service(request: Request) -> SnapshotService:
    """A pure accessor — `create_app` (`app.py`) builds the ONE
    `SnapshotService` eagerly, before any request can exist, and this
    just reads it back. It must NOT build one itself: FastAPI resolves a
    plain-`def` dependency like this via `run_in_threadpool`, so a
    "build it lazily on first use" version of this function runs on a
    thread-pool thread per request — two concurrent `/api/tree` requests
    at daemon cold start could each observe nothing cached yet and each
    construct their own `SnapshotService`, defeating single-flight on
    exactly spec Section 17.6's "two simultaneous clicks" scenario."""
    return request.app.state.snapshot_service


@router.get(
    "/tree", response_model=TreeResponse,
    dependencies=[Depends(require_session)],
    responses={
        401: {"model": ErrorDetail,
              "description": "Missing or invalid session cookie."},
        503: {"model": ErrorDetail,
              "description": "Registry read failed; `detail` is the "
                              "sanitized reason, verbatim."},
    },
)
async def get_tree(
    request: Request,
    service: SnapshotService = Depends(get_snapshot_service),  # noqa: B008 (FastAPI idiom)
) -> TreeResponse:
    result, read_at = await service.read()
    # Surfaced in the per-request log line (`app._log_requests`): two
    # concurrent requests that collapsed onto the same physical read show
    # the SAME `read_at` in the journal — spec Section 17.6's
    # observability requirement, without a second, dedicated log line.
    request.state.log_extra = f"read_at={read_at.isoformat()}"
    # Task 6 (task-6-amendments.md Section D): a `--fixture` reader may
    # yield the wire `TreeResponse` directly rather than a `Snapshot` —
    # see `snapshot.py`'s module docstring for why. That shape is already
    # the response; nothing left to convert or sanitize.
    if isinstance(result, TreeResponse):
        return result
    if result.registry_error is not None:
        raise HTTPException(status_code=503, detail=result.registry_error)
    return tree_response(result, read_at=read_at)
