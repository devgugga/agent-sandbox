"""server/asb_server/api/auth.py — POST /api/auth/session, GET /api/auth/me.

The mechanism (token file, session cookie, Origin check) lives in
`asb_server.auth`; this module only wires the two routes spec Section 7.2
lists (Task 4 owns both files).

Task 5 fix round 1 (controller ruling on Important 2): both routes now
declare their non-2xx `responses=` (`models.ErrorDetail`) so the
generated OpenAPI schema — and the typed client Section 9.1 generates
from it — carries a shape for the 401/403 bodies these routes already
return. Response declarations only; the auth mechanism itself is
untouched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth import (
    SESSION_COOKIE_NAME,
    AuthManager,
    get_auth_manager,
    require_origin,
    require_session,
)
from ..models import ErrorDetail

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SessionRequest(BaseModel):
    token: str


@router.post(
    "/session", status_code=204, dependencies=[Depends(require_origin)],
    responses={
        401: {"model": ErrorDetail, "description": "Token did not match."},
        403: {"model": ErrorDetail,
              "description": "Origin header missing or not the daemon's own "
                              "(or, with --dev, the Vite origin)."},
    },
)
async def create_session(
    payload: SessionRequest,
    response: Response,
    manager: AuthManager = Depends(get_auth_manager),  # noqa: B008 (FastAPI idiom)
) -> None:
    """Body `{token}`; on match sets the session cookie and returns 204;
    401 otherwise (spec Section 7.2). The token arrives in the POST body,
    never a query string, so it never reaches a request line or a log
    (spec Section 7.5)."""
    if not manager.verify_token(payload.token):
        raise HTTPException(status_code=401)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=manager.issue_session_value(),
        httponly=True,
        samesite="strict",
        path="/",
    )


@router.get(
    "/me", status_code=204, dependencies=[Depends(require_session)],
    responses={
        401: {"model": ErrorDetail,
              "description": "Missing or invalid session cookie."},
    },
)
async def read_me() -> None:
    """204 when the cookie is valid; 401 otherwise — enforced entirely by
    the `require_session` dependency, so a valid request has nothing left
    to do."""
    return
