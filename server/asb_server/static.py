"""server/asb_server/static.py — serve `web/dist` with SPA fallback.

Spec Section 9/Section 12, amendment Section B: `/` and any non-`/api`
path serve the built front end's `index.html` (a single-page app owns
further routing client-side once loaded); `/api/*` NEVER falls back — an
unmatched `/api` path must stay a 404 the front end can tell apart from a
real response, never HTML it might try to parse as one. `web/dist`
missing means `/` (and every non-`/api` path) answers 503 naming
`asb-agent install-server` (spec Section 12); `/api` must keep answering
regardless — the front end not being built must not take the daemon's
API down, since `static.py`'s router only ever handles non-`/api` paths.

This router is mounted LAST in `create_app` (`app.py`), after every `/api`
router, so a concrete `/api/...` path is always tried first by Starlette's
route matching (routes are matched in registration order) — that mount
order is what makes a REAL `/api` route (e.g. `/api/tree`) actually
answer. The `full_path == "api" or full_path.startswith("api/")` guard
below is a second, narrower safeguard: it only guarantees that an
UNMATCHED `/api` path (one no `/api` router claims) still 404s here
rather than silently returning `index.html`, and it holds regardless of
mount order. It does NOT make the mount order irrelevant — if this
router were ever registered before the `/api` routers, its catch-all
would intercept every `/api/...` request first and this guard would turn
each of them into a 404 too, which fails loudly rather than silently
serving HTML, but still breaks the API. `server/tests/test_static.py`'s
`/api/unknown` case proves the guard's own property; it does not (and
cannot) prove the mount order is correct — that is asserted by the
`/api/health` and `/api/tree` tests in `test_static.py`/`test_health.py`/
`test_tree.py` still answering as themselves.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)

# Spec Section 12's exact failure row: "`web/dist` missing → `/` answers
# 503 with 'run asb-agent install-server'; `/api` still works."
_INSTALL_HINT = (
    "web/dist is missing; run `asb-agent install-server` to build the "
    "front end."
)


def _asset(dist: Path, full_path: str) -> Path | None:
    """The literal file `full_path` names inside `dist`, or `None` when it
    does not exist, is not a plain file, or — via a `..` segment — would
    resolve outside `dist`. A path-traversal attempt simply falls through
    to `index.html` like any other unmatched SPA route; it never escapes
    `dist`."""
    if not full_path:
        return None
    resolved_dist = dist.resolve()
    candidate = (resolved_dist / full_path).resolve()
    try:
        candidate.relative_to(resolved_dist)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@router.get("/{full_path:path}")
async def spa(request: Request, full_path: str) -> FileResponse:
    if full_path == "api" or full_path.startswith("api/"):
        # Not reached for a real `/api` route while the mount order in
        # `create_app` is correct (see module docstring) — this only
        # guarantees an UNMATCHED `/api` path 404s instead of serving
        # `index.html`.
        raise HTTPException(status_code=404)
    dist: Path = request.app.state.settings.web_dist_path
    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail=_INSTALL_HINT)
    asset = _asset(dist, full_path)
    return FileResponse(asset if asset is not None else index)
