"""server/asb_server/snapshot.py — SnapshotService: single-flight read on a
worker thread.

Spec Section 7.4 / task-5-amendments.md Section B, Section C: a snapshot
runs Git, Podman and SSH per checkout and takes seconds.
`SnapshotService.read()` must never block the event loop and must collapse
concurrent callers onto ONE physical read.

`production_reader` is the daemon's own `Callable[[], Snapshot]`
(matches `asb_server.app.SnapshotReader`): it composes `session_services`,
`asb.interfaces.snapshot.default_checkouts` and `read_snapshot` fresh on
every call — the same three calls `TuiController.refresh` makes, minus
`tui.py`. Amendment Section C: the daemon imports `asb.interfaces.snapshot`,
never `asb.interfaces.tui`, which does `import curses` at module level —
importing it here would undo Task 2 entirely.

`SnapshotService` itself is generic and knows nothing about how a
`Snapshot` is produced: it wraps ANY zero-argument reader — production
above, a fixture (Task 6), or a test stub — and adds exactly three things
none of those readers own: worker-thread execution
(`loop.run_in_executor`), single-flight collapsing of concurrent callers
onto one in-flight read, and a `read_at` timestamp captured once per
physical read and shared by every caller that collapsed onto it. There is
no cache: once the in-flight read completes, the NEXT call starts a
brand-new one — caching and background refresh are item 4's job, not
item 1's (amendment Section B).

Task 6 (task-6-amendments.md Section D) adds `fixture_reader` here, next
to `production_reader`: a `--fixture <path.json>` reader. Spec Section 10
says the fixture file has the `TreeResponse` *wire* shape — the far side
of `models.tree_response`'s conversion — not a `Snapshot`'s. Reconstructing
a real `Snapshot` from that shape would be lossy (`asb.projects.model
.Project` needs `worktree_root`/`git_common_dir`, which `TreeResponse`
never carries, and `ProjectNode.name` is an independent JSON field where
production instead derives the name from `Project.primary`'s last path
segment — a fixture's declared name could silently disagree with what a
reconstructed `Project` would produce). So `fixture_reader` yields the
parsed `TreeResponse` directly for the healthy case, bypassing
`tree_response`/`sanitize` entirely; that conversion already has its own
exhaustive coverage in `server/tests/test_tree.py` and `test_models.py`,
so nothing goes uncovered by this choice. The registry-failure fixture
(`{"registry_error": "<reason>"}`) is the one case that genuinely IS a
`Snapshot` concept — a real registry failure has no tree at all — so that
branch returns an all-empty `Snapshot` with `registry_error` set, driving
the exact same 503 branch `api/tree.py::get_tree` already has.
`SnapshotReader` below is broadened to `Snapshot | TreeResponse` to carry
either result through the same `SnapshotService`/`get_tree` plumbing.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from asb.interfaces.sessions import session_services
from asb.interfaces.snapshot import (
    Snapshot,
    default_checkouts,
    read_branch,
    read_snapshot,
)
from asb.interfaces.tui_model import sanitize

from .models import TreeResponse

SnapshotReader = Callable[[], Snapshot | TreeResponse]

# `cli/asb-agent`'s own `ROOT` is `Path(__file__).resolve().parent.parent`
# from `cli/asb-agent` — the repository root, which `SandboxRuntime` uses
# to locate `cli/asb-agent` when it shells out (spec Section 7.4: "the same
# way the CLI does"). `server/asb_server/snapshot.py` sits two levels
# deeper (`server/asb_server/`), so the same root is `parents[2]` from
# here — mirrors `settings.py`'s own `_REPO_ROOT` without importing a
# private name across modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def production_reader(root: Path = _REPO_ROOT) -> Snapshot:
    """Builds fresh services and a fresh `CheckoutManager` and reads one
    snapshot. Fresh on every call, deliberately: `session_services`'s own
    docstring says construction touches no disk, Podman or SSH, so
    rebuilding it here is cheap and is what lets a registry edited on disk
    between reads be seen (amendment Section B, property 3).
    `default_checkouts` is `asb.interfaces.snapshot`'s own function —
    never `tui.default_checkouts` (amendment Section C). No custom
    liveness probe is passed either: the default (`_default_liveness`,
    this module's own `TmuxTerminal`-based prober) is exactly what a
    caller without a `tui`-flavoured one should use."""
    services = session_services(root)
    checkouts = default_checkouts(services)
    return read_snapshot(services, checkouts, read_branch)


def fixture_reader(path: Path) -> SnapshotReader:
    """Builds a `--fixture <path.json>` reader (spec Section 10). Parsed
    ONCE here, at `serve` startup (`main.py` calls this before
    `uvicorn.run`), not lazily on the first request — a malformed fixture
    fails fast with a clear message rather than as a 500 on the first
    `/api/tree` call.

    `{"registry_error": "<reason>"}` (amendment Section C) drives the
    same 503 branch a real registry failure takes: an all-empty
    `Snapshot` with `registry_error` set, `reason` sanitized the same way
    `cli/asb/interfaces/snapshot.py::_reason` sanitizes a real one. Any
    other file is parsed as the `TreeResponse` wire shape and returned
    as-is — see the module docstring for why this bypasses
    `models.tree_response`/`sanitize` rather than reconstructing a
    `Snapshot`."""
    data = json.loads(path.read_text())
    if "registry_error" in data:
        result: Snapshot | TreeResponse = Snapshot(
            projects=(), checkouts=(), sessions=(), unregistered=(),
            project_errors={}, registry_error=sanitize(data["registry_error"]))
    else:
        result = TreeResponse.model_validate(data)

    def _read() -> Snapshot | TreeResponse:
        return result

    return _read


class SnapshotService:
    """Wraps a `SnapshotReader` with worker-thread execution and
    single-flight collapsing. Built once and cached on `app.state`
    (`api/tree.py::get_snapshot_service`) — the in-flight future IS the
    shared state that makes single-flight work, so one instance must
    outlive any single request."""

    def __init__(self, reader: SnapshotReader) -> None:
        self._reader = reader
        self._inflight: (
            asyncio.Future[tuple[Snapshot | TreeResponse, datetime]] | None
        ) = None

    async def read(self) -> tuple[Snapshot | TreeResponse, datetime]:
        """Runs `self._reader` on the default executor (a worker thread,
        never the event loop) and returns `(snapshot, read_at)`.

        A caller that arrives while a read is already in progress does
        NOT trigger a second physical read: it awaits the SAME future and
        receives the SAME `read_at` (spec Section 17.6). No lock is
        needed — everything between the `is None` check and the
        assignment below runs without an `await`, so no other task can
        interleave on this single-threaded event loop.

        `asyncio.shield` matters here, not just as defensive style: an
        `await` on a bare `Task` propagates the AWAITER's cancellation
        (e.g. a client disconnecting mid-request) into the Task it is
        waiting on. Without `shield`, one caller going away could cancel
        the read out from under every other caller collapsed onto it.

        If the read raises, every waiter collapsed onto it receives that
        SAME exception — `asyncio.Future` replays it to every `await`.
        Either way (success or exception), the done callback below clears
        `_inflight`, so the NEXT call starts a genuinely fresh read rather
        than replaying a cached failure."""
        future = self._inflight
        if future is None:
            future = asyncio.get_running_loop().create_task(self._read_once())
            future.add_done_callback(self._clear)
            self._inflight = future
        return await asyncio.shield(future)

    def _clear(
        self, _future: asyncio.Future[tuple[Snapshot | TreeResponse, datetime]]
    ) -> None:
        self._inflight = None

    async def _read_once(self) -> tuple[Snapshot | TreeResponse, datetime]:
        loop = asyncio.get_running_loop()
        snapshot = await loop.run_in_executor(None, self._reader)
        return snapshot, datetime.now(UTC)
