"""server/asb_server/api/health.py — GET /api/health.

No auth (spec Section 7.2 lists `health` alongside `auth/session` as the
two exceptions to `require_session`): `asb-agent ui` and `doctor` poll
this before a session cookie exists, so it must answer unconditionally.
"""
from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version as _package_version

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["health"])

# Fixed once, at import time — every `/api/health` response in this
# process reports the SAME instant (amendment Section F: "fixed at
# process start, not per request").
_STARTED_AT = datetime.now(UTC)

# The installed `asb_server` distribution's version, exactly as
# `server/pyproject.toml` declares it. Deterministic per install: it is
# package metadata, not a build timestamp or a git SHA, so it never
# differs between two runs of the same checkout — the same property
# `asb-server openapi`'s byte-stability check (spec Section 5) depends on.
_VERSION = _package_version("asb_server")


class HealthResponse(BaseModel):
    version: str
    started_at: datetime


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=_VERSION, started_at=_STARTED_AT)
