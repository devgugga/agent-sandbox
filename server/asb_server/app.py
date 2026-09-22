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

Fix round 1: `app.state.snapshot_service` is built HERE, synchronously,
rather than lazily inside `api/tree.py`'s dependency. FastAPI resolves a
plain-`def` dependency via `run_in_threadpool`
(`fastapi/dependencies/utils.py`), so a lazy "build it on first use"
dependency runs on a THREAD POOL thread per request: two concurrent
`/api/tree` requests arriving before the first one has stored anything
each observe `state.snapshot_service is None` and each construct their
OWN `SnapshotService` — two independent `_inflight` slots, defeating
single-flight on exactly a cold-start burst (spec Section 17.6's
scenario). Building it here, before `create_app` returns and before any
request can exist, removes the window entirely. `SnapshotService.__init__`
only stores a reference (no I/O), so this stays compatible with
`asb-server openapi`'s side-effect-free contract.
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
from .models import TreeResponse
from .settings import Settings
from .snapshot import SnapshotService
from .static import router as static_api

# The seam spec Section 10 names: a real read in production, a fixture or a
# stub in tests. Task 3 stores it for the routes later tasks add; it never
# calls it itself. Task 6 broadens this to `Snapshot | TreeResponse`
# (mirrors `snapshot.SnapshotReader` — see that module's docstring): a
# `--fixture` reader yields the wire `TreeResponse` directly for the
# healthy case, never a reconstructed `Snapshot`.
SnapshotReader = Callable[[], Snapshot | TreeResponse]

logger = logging.getLogger("asb_server")


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """`call_next` raises rather than returning when the route raised an
    exception `_unhandled_exception` turns into a 500 — that conversion
    happens in `ServerErrorMiddleware`, which sits OUTSIDE this
    middleware, so by the time control reaches back here the exception
    has already propagated past and the real `Response` object never
    comes back to this frame. The `try`/`finally` is what keeps "one line
    per request" true on that path too, not just the successful one;
    `status_code` defaults to 500 rather than a placeholder because
    `_unhandled_exception` unconditionally returns 500 — that is the one
    fact this frame can still know for certain about a response it never
    sees."""
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        extra = getattr(request.state, "log_extra", None)
        logger.info("%s %s -> %d%s", request.method, request.url.path,
                    status_code, f" {extra}" if extra else "")


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Spec Section 7.6: unexpected exceptions get a generic 500 body; the
    traceback goes to the journal only. `logger.exception` writes the
    traceback to the log, never to `content` below."""
    logger.exception("unhandled error handling %s %s",
                      request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def create_app(settings: Settings, *, snapshot_reader: SnapshotReader) -> FastAPI:
    """The daemon's FastAPI app. `settings`, `snapshot_reader` and the ONE
    `SnapshotService` built from it are kept on `app.state` so the routers
    Task 4/5/6 add can read them via the request without changing this
    function's signature. `snapshot_service` is built here rather than
    lazily (see the module docstring) — it must exist, as a single shared
    instance, before the first request can possibly arrive."""
    app = FastAPI(title="agent-sandbox daemon")
    app.state.settings = settings
    app.state.snapshot_reader = snapshot_reader
    app.state.snapshot_service = SnapshotService(snapshot_reader)
    app.include_router(auth_api.router)
    app.include_router(health_api.router)
    app.include_router(tree_api.router)
    # LAST: `static_api`'s catch-all (`/{full_path:path}`) must never be
    # tried before a concrete `/api/...` route (amendment Section B).
    # Starlette matches routes in registration order, so THIS ordering is
    # what makes every `/api` router above actually answer its own path.
    # `static.py`'s own `full_path.startswith("api")` guard is a narrower,
    # order-independent safeguard against a different failure: an
    # UNMATCHED `/api` path silently serving `index.html`. It does not
    # substitute for correct ordering — see `static.py`'s module
    # docstring for what it does and does not guarantee.
    app.include_router(static_api)
    app.add_middleware(BaseHTTPMiddleware, dispatch=_log_requests)
    app.add_exception_handler(Exception, _unhandled_exception)
    return app
