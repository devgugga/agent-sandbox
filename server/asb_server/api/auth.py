"""server/asb_server/api/auth.py — POST /api/auth/session, GET /api/auth/me.

The mechanism (token file, session cookie, Origin check) lives in
`asb_server.auth`; this module only wires the two routes spec Section 7.2
lists (amendment B: Task 4 owns both files).
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

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SessionRequest(BaseModel):
    token: str


@router.post("/session", status_code=204, dependencies=[Depends(require_origin)])
async def create_session(
    payload: SessionRequest,
    response: Response,
    manager: AuthManager = Depends(get_auth_manager),  # noqa: B008 (FastAPI idiom)
) -> None:
    """Body `{token}`; on match sets the session cookie and returns 204;
    401 otherwise (spec Section 7.2). The token arrives in the POST body,
    never a query string, so it never reaches a request line or a log
    (spec Section 7.5, amendment G)."""
    if not manager.verify_token(payload.token):
        raise HTTPException(status_code=401)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=manager.issue_session_value(),
        httponly=True,
        samesite="strict",
        path="/",
    )


@router.get("/me", status_code=204, dependencies=[Depends(require_session)])
async def read_me() -> None:
    """204 when the cookie is valid; 401 otherwise — enforced entirely by
    the `require_session` dependency, so a valid request has nothing left
    to do."""
    return
