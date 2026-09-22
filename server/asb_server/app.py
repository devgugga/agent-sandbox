"""server/asb_server/app.py — create_app(settings, *, snapshot_reader) -> FastAPI.

Task 3 builds a valid, routeless FastAPI app: the seam Task 4 (auth.py,
api/auth.py), Task 5 (api/health.py, api/tree.py, snapshot.py) and Task 6
(static.py, `--fixture`) slot into without rewriting `create_app`.

Task 4 adds the `auth` router here but deliberately does not load the
token or session-key files at this point — `create_app` also runs inside
`asb-server openapi`, which must stay a pure, disk-write-free command
(see `asb_server.auth`'s module docstring). Secrets load lazily, on the
first request that needs them.
"""
from __future__ import annotations

from collections.abc import Callable

from asb.interfaces.snapshot import Snapshot
from fastapi import FastAPI

from .api import auth as auth_api
from .settings import Settings

# The seam spec Section 10 names: a real read in production, a fixture or a
# stub in tests. Task 3 stores it for the routes later tasks add; it never
# calls it itself.
SnapshotReader = Callable[[], Snapshot]


def create_app(settings: Settings, *, snapshot_reader: SnapshotReader) -> FastAPI:
    """The daemon's FastAPI app. `settings` and `snapshot_reader` are kept
    on `app.state` so the routers Task 4/5/6 add can read them via the
    request without changing this function's signature."""
    app = FastAPI(title="agent-sandbox daemon")
    app.state.settings = settings
    app.state.snapshot_reader = snapshot_reader
    app.include_router(auth_api.router)
    return app
