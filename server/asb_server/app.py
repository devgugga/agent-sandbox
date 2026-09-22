"""server/asb_server/app.py — create_app(settings, *, snapshot_reader) -> FastAPI.

Task 3 builds a valid, routeless FastAPI app: the seam Task 4 (auth.py,
api/auth.py), Task 5 (api/health.py, api/tree.py, snapshot.py) and Task 6
(static.py, `--fixture`) slot into without rewriting `create_app`.

Task 4 adds the `auth` router here but deliberately does not load the
token or session-key files at this point — `create_app` also runs inside
`asb-server openapi`, which must stay a pure, disk-write-free command
(see `asb_server.auth`'s module docstring). Secrets load lazily, on the
first request that needs them.

Task 5 adds the daemon's logging convention here (task-5-amendments.md
Section D), for the two sites that are cross-cutting rather than owned by
one route: `_log_requests` is the "one line per request to stdout"
middleware (spec Section 7.6), and `_unhandled_exception` is the
"traceback to the journal only, generic 500 to the caller" handler.
Neither writes the token, the cookie, or provider output — `_log_requests`
logs only the method, the path (never the query string, which is where a
misbehaving client could put a secret) and the status code, plus whatever
a route stashed on `request.state.log_extra` (only `api/tree.py` does,
with a `read_at` timestamp); `_unhandled_exception` logs the traceback via
`logger.exception`, which is exception-object text, never request or
response bodies.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from asb.interfaces.snapshot import Snapshot
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .api import auth as auth_api
from .api import health as health_api
from .api import tree as tree_api
from .settings import Settings

# The seam spec Section 10 names: a real read in production, a fixture or a
# stub in tests. Task 3 stores it for the routes later tasks add; it never
# calls it itself.
SnapshotReader = Callable[[], Snapshot]

logger = logging.getLogger("asb_server")


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """`call_next` raises rather than returning when the route raised an
    exception `_unhandled_exception` turns into a 500 — that conversion
    happens in `ServerErrorMiddleware`, which sits OUTSIDE this
    middleware, so by the time control reaches back here the exception
    has already propagated past. The `try`/`finally` is what keeps "one
    line per request" true on that path too, not just the successful
    one; `status_code` stays `"error"` there because the real response
    object never comes back to this frame."""
    status_code: int | str = "error"
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        extra = getattr(request.state, "log_extra", None)
        logger.info("%s %s -> %s%s", request.method, request.url.path,
                    status_code, f" {extra}" if extra else "")


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Spec Section 7.6: unexpected exceptions get a generic 500 body; the
    traceback goes to the journal only. `logger.exception` writes the
    traceback to the log, never to `content` below."""
    logger.exception("unhandled error handling %s %s",
                      request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def create_app(settings: Settings, *, snapshot_reader: SnapshotReader) -> FastAPI:
    """The daemon's FastAPI app. `settings` and `snapshot_reader` are kept
    on `app.state` so the routers Task 4/5/6 add can read them via the
    request without changing this function's signature."""
    app = FastAPI(title="agent-sandbox daemon")
    app.state.settings = settings
    app.state.snapshot_reader = snapshot_reader
    app.include_router(auth_api.router)
    app.include_router(health_api.router)
    app.include_router(tree_api.router)
    app.add_middleware(BaseHTTPMiddleware, dispatch=_log_requests)
    app.add_exception_handler(Exception, _unhandled_exception)
    return app
