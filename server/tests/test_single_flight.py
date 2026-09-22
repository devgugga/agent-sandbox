"""server/tests/test_single_flight.py — Task 5: the three spec Section 7.4
properties `SnapshotService` must have.

Deliberately named to collide with any `tests/unit/test_single_flight.py`-
shaped suite elsewhere: `--import-mode=importlib` (Task 1) is what lets
same-named files coexist under one `pytest` invocation.

`TestClient`, entered as a context manager, keeps ONE `anyio` blocking
portal (`starlette.testclient`'s `_portal_factory` reuses `self.portal`
once it exists) running ONE event loop. Two OS threads calling
`client.get(...)` concurrently on that SAME entered client each submit
their request as an independent task onto that SAME loop
(`anyio.from_thread.BlockingPortal.call` -> `start_task_soon(...).result()`)
— this is what makes the proofs below genuine rather than simulated:
requests really do run concurrently on one event loop, exactly as they
would under `uvicorn`.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from asb.interfaces.snapshot import Snapshot
from asb_server.app import create_app
from asb_server.auth import AuthManager
from asb_server.settings import Settings
from fastapi.testclient import TestClient

DAEMON_PORT = 7420
DAEMON_ORIGIN = f"http://127.0.0.1:{DAEMON_PORT}"


class TestDaemonNeverImportsCurses(unittest.TestCase):
    """Amendment Section C / controller ruling R22: the daemon imports
    `asb.interfaces.snapshot`, never `asb.interfaces.tui` (which does
    `import curses` at module level). This is the direct, runtime version
    of that claim: after importing every module Task 5 added or touched,
    `curses` must never have entered `sys.modules` — a source-text grep
    could miss a re-export or an indirect import; this cannot.

    Runs in a SEPARATE subprocess rather than this test process:
    `tests/unit/test_tui_controller.py` and `tests/unit/test_snapshot.py`
    (in the SAME `pytest tests/unit server/tests` run) import `tui.py`
    themselves and leave `curses` in `sys.modules` for the rest of the
    process — a same-process check would pass or fail depending on test
    ORDER, not on anything this diff did."""

    def test_curses_never_gets_imported(self):
        script = (
            "import sys\n"
            "import asb_server.api.health\n"
            "import asb_server.api.tree\n"
            "import asb_server.app\n"
            "import asb_server.main\n"
            "import asb_server.snapshot\n"
            "assert 'curses' not in sys.modules, "
            "[m for m in sys.modules if 'curses' in m]\n"
        )
        result = subprocess.run([sys.executable, "-c", script], check=False,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


def _empty_snapshot() -> Snapshot:
    return Snapshot(projects=(), checkouts=(), sessions=(), unregistered=(),
                     project_errors={}, registry_error=None)


class TestProductionReaderComposition(unittest.TestCase):
    """Amendment Section C, the other half of `TestDaemonNeverImportsCurses`
    above: not only must `curses` stay out of `sys.modules`, `production_reader`
    must call `asb_server.snapshot`'s OWN `default_checkouts` (Task 2's, on
    `asb.interfaces.snapshot`) rather than building a `tui`-flavoured one by
    hand. Patches the three collaborators `production_reader` composes and
    checks both that each is called and the order data flows between them."""

    def test_composes_session_services_default_checkouts_and_read_snapshot(self):
        from unittest.mock import call, patch

        from asb_server import snapshot as snapshot_module

        sentinel_services = object()
        sentinel_checkouts = object()
        sentinel_snapshot = object()
        root = Path("/some/repo/root")

        with patch.object(snapshot_module, "session_services",
                           return_value=sentinel_services) as mock_services, \
             patch.object(snapshot_module, "default_checkouts",
                           return_value=sentinel_checkouts) as mock_checkouts, \
             patch.object(snapshot_module, "read_snapshot",
                           return_value=sentinel_snapshot) as mock_read:
            result = snapshot_module.production_reader(root=root)

        mock_services.assert_called_once_with(root)
        mock_checkouts.assert_called_once_with(sentinel_services)
        mock_read.assert_called_once_with(
            sentinel_services, sentinel_checkouts, snapshot_module.read_branch)
        self.assertIs(result, sentinel_snapshot)
        # Nothing here reaches for a second, `tui`-specific liveness probe
        # or manager factory — `default_checkouts` is called with just the
        # services, relying on its own default (amendment Section C).
        self.assertEqual(mock_checkouts.call_args, call(sentinel_services))


class TestSnapshotServiceIsConstructedEagerly(unittest.TestCase):
    """Regression coverage for fix round 1, Important 1: `get_snapshot_service`
    (`api/tree.py`) used to build a NEW `SnapshotService` lazily, on first
    use, caching it on `app.state`. FastAPI resolves a plain-`def`
    dependency like that via `run_in_threadpool`
    (`fastapi/dependencies/utils.py`), so two requests arriving
    concurrently — most plausibly right at daemon cold start, spec
    Section 17.6's own scenario — could each run that dependency on a
    DIFFERENT thread-pool thread, each observe `state.snapshot_service is
    None`, and each construct their own instance: two independent
    `_inflight` slots, defeating single-flight.

    The OLD `test_two_concurrent_requests_yield_one_read_and_same_read_at`
    test could not catch this: it synchronizes thread B's start on
    `entered`, a flag the STUB READER sets from inside a call that can
    only happen AFTER thread A's dependency resolution (and its
    `state.snapshot_service` assignment) has already completed. That
    synchronization closes the exact window the bug lived in. These tests
    target the window directly rather than hoping to land inside it under
    thread-scheduling luck."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings(
            port=DAEMON_PORT, token_path=tmp / "server-token",
            session_key_path=tmp / "server-session-key")

    def test_create_app_builds_it_before_any_request_exists(self):
        # Deterministic, not timing-dependent: the fix's actual invariant
        # is that construction happens INSIDE `create_app`, synchronously,
        # before `create_app` even returns — so there is no window left
        # for two requests to race into, regardless of scheduling.
        app = create_app(self.settings, snapshot_reader=_empty_snapshot)
        self.assertIsNotNone(app.state.snapshot_service)

    def test_the_dependency_never_constructs_a_second_instance(self):
        from unittest.mock import patch

        from asb_server import app as app_module

        with patch.object(app_module, "SnapshotService",
                           wraps=app_module.SnapshotService) as mock_cls:
            app = create_app(self.settings, snapshot_reader=_empty_snapshot)
            self.assertEqual(mock_cls.call_count, 1)

            manager = AuthManager.load(self.settings)
            with TestClient(app) as client:
                response = client.post(
                    "/api/auth/session", json={"token": manager.token},
                    headers={"Origin": DAEMON_ORIGIN})
                assert response.status_code == 204, response.text

                # A burst of concurrent requests, all fired essentially at
                # once, with NO synchronization on anything the reader
                # does — the realistic "several requests right after
                # startup" scenario, not an artificially widened window.
                threads = [
                    threading.Thread(target=client.get, args=("/api/tree",))
                    for _ in range(8)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            # `SnapshotService` was constructed exactly ONCE — inside
            # `create_app`, before the app even existed to receive a
            # request — regardless of how many concurrent requests the
            # dependency layer resolved afterward.
            self.assertEqual(mock_cls.call_count, 1)


class SingleFlightTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings(
            port=DAEMON_PORT,
            token_path=tmp / "server-token",
            session_key_path=tmp / "server-session-key",
        )
        self.manager = AuthManager.load(self.settings)

    def _client(self, reader, *, raise_server_exceptions: bool = True) -> TestClient:
        app = create_app(self.settings, snapshot_reader=reader)
        client = self.enterContext(TestClient(
            app, raise_server_exceptions=raise_server_exceptions))
        response = client.post(
            "/api/auth/session", json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN})
        assert response.status_code == 204, response.text
        return client


class TestSingleFlightCollapsesConcurrentReads(SingleFlightTestCase):
    """Property 1 (single-flight) and property 3 (fresh services every
    read, proven by absence of a second call), spec Section 17.6's own
    acceptance wording: "two simultaneous refresh clicks produce one
    snapshot read"."""

    def test_two_concurrent_requests_yield_one_read_and_same_read_at(self):
        call_count = 0
        count_lock = threading.Lock()
        entered = threading.Event()
        release = threading.Event()

        def slow_reader() -> Snapshot:
            nonlocal call_count
            with count_lock:
                call_count += 1
            entered.set()
            # Blocks the WORKER thread the reader runs on, never the
            # event loop — this is also what test_worker_thread.py's
            # sibling test below relies on.
            assert release.wait(timeout=5), "test deadlocked: release never set"
            return _empty_snapshot()

        client = self._client(slow_reader)
        results: list = [None, None]

        def call(index: int) -> None:
            results[index] = client.get("/api/tree")

        # spec Section 17.6's own acceptance wording is about the
        # JOURNAL: "visible in the journal as one log line." `assertLogs`
        # is that proof, not a restatement of it — it captures the SAME
        # `logger.info` calls `app._log_requests` makes on stdout in
        # production, and the assertions below inspect their actual text.
        with self.assertLogs("asb_server", level="INFO") as captured:
            thread_a = threading.Thread(target=call, args=(0,))
            thread_a.start()
            # Thread A must have genuinely entered the reader (i.e. the
            # read is really in progress) before thread B starts, or
            # thread B could win the "is anything in flight?" race and
            # start its own read — which would still be correct
            # behavior, just not what this test is proving.
            self.assertTrue(entered.wait(timeout=5), "read never started")

            thread_b = threading.Thread(target=call, args=(1,))
            thread_b.start()
            # Give thread B a moment to actually reach
            # `SnapshotService.read` and collapse onto the in-flight
            # future before we release it.
            thread_b.join(timeout=0.2)
            self.assertTrue(thread_b.is_alive(),
                             "thread B finished before release")

            release.set()
            thread_a.join(timeout=5)
            thread_b.join(timeout=5)

        self.assertEqual(call_count, 1)
        response_a, response_b = results
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual(response_a.json()["read_at"], response_b.json()["read_at"])

        # The journal proof itself: both per-request log lines for
        # `/api/tree` carry `read_at=<the SAME timestamp>` — an operator
        # reading the journal can see the two requests collapsed onto one
        # physical read without cross-referencing anything else. Compared
        # log-line to log-line (both come from the SAME `.isoformat()`
        # call in `tree.py`, so their text is exactly equal) rather than
        # to the JSON body, whose `Z`-suffixed rendering differs in text
        # from `datetime.isoformat()`'s `+00:00` while naming the same
        # instant.
        tree_lines = [line for line in captured.output if "/api/tree" in line]
        self.assertEqual(len(tree_lines), 2, captured.output)
        logged_read_ats = [line.rsplit("read_at=", 1)[1] for line in tree_lines]
        self.assertEqual(logged_read_ats[0], logged_read_ats[1])

    def test_next_request_after_completion_reads_again(self):
        # No cache: once the in-flight read finishes, the NEXT call is a
        # genuinely new physical read (amendment Section B, property 3).
        calls: list[datetime] = []

        def reader() -> Snapshot:
            calls.append(datetime.now(UTC))
            return _empty_snapshot()

        client = self._client(reader)
        first = client.get("/api/tree")
        second = client.get("/api/tree")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(first.json()["read_at"], second.json()["read_at"])

    def test_a_raising_read_is_delivered_to_every_waiter(self):
        # What happens when the in-progress read raises while another
        # caller waits on it: both receive the SAME exception (surfaced
        # as the daemon's generic 500), not a hang.
        entered = threading.Event()
        release = threading.Event()

        def failing_reader() -> Snapshot:
            entered.set()
            assert release.wait(timeout=5), "test deadlocked: release never set"
            raise RuntimeError("boom")

        client = self._client(failing_reader, raise_server_exceptions=False)
        results: list = [None, None]

        def call(index: int) -> None:
            results[index] = client.get("/api/tree")

        with self.assertLogs("asb_server", level="INFO") as captured:
            thread_a = threading.Thread(target=call, args=(0,))
            thread_a.start()
            self.assertTrue(entered.wait(timeout=5), "read never started")

            thread_b = threading.Thread(target=call, args=(1,))
            thread_b.start()
            thread_b.join(timeout=0.2)
            self.assertTrue(thread_b.is_alive(),
                             "thread B finished before release")

            release.set()
            thread_a.join(timeout=5)
            thread_b.join(timeout=5)

        response_a, response_b = results
        self.assertEqual(response_a.status_code, 500)
        self.assertEqual(response_b.status_code, 500)
        # Generic detail only — the exception's own text never reaches
        # the response body.
        self.assertNotIn("boom", response_a.text)
        self.assertNotIn("boom", response_b.text)

        # The per-request line still fires on this path
        # (`app._log_requests`'s `try`/`finally`) — matched by prefix, not
        # substring, since the traceback lines below also mention
        # `api/tree.py` in their frames. Fix round 1 (Minor): the status
        # logged here is the literal, correct `500` — `_unhandled_exception`
        # always returns 500, so `_log_requests` can state that as fact
        # rather than the earlier placeholder string. The traceback itself
        # goes to the journal, never the response body.
        request_lines = [line for line in captured.output
                         if line.startswith("INFO:asb_server:GET /api/tree")]
        self.assertEqual(len(request_lines), 2, captured.output)
        for line in request_lines:
            self.assertIn("-> 500", line)
        tracebacks = [line for line in captured.output
                     if "unhandled error handling" in line]
        self.assertEqual(len(tracebacks), 2, captured.output)
        for line in tracebacks:
            self.assertIn("RuntimeError: boom", line)


class TestReadNeverBlocksTheEventLoop(SingleFlightTestCase):
    """Property 2 (worker thread). This test demonstrates — with a
    wall-clock bound, not just a structural inference — that while a
    snapshot read is blocked (on a `threading.Event` the test controls), a
    CONCURRENT request to an unrelated route (`/api/health`, which touches
    none of `SnapshotService`'s machinery) still gets answered promptly:
    it must return in well under half the time the reader is capable of
    blocking for, AND while `release` is provably still unset (so the
    reader has not finished). If `SnapshotService.read` ran the reader
    synchronously on the loop instead of via `run_in_executor`, the health
    request would queue behind the blocked one and could not complete
    until `release` was set — this test would then time out or fail the
    elapsed-time assertion. It does NOT prove that `read_snapshot`'s own
    internals (Git/Podman/SSH calls) never block anything downstream of
    the reader — only that `SnapshotService` itself hands the reader to a
    worker thread and frees the event loop while it runs, which is the
    property spec Section 7.4 assigns to this module."""

    def test_health_answers_while_a_slow_read_is_in_flight(self):
        entered = threading.Event()
        release = threading.Event()
        # Long enough that a health call blocked behind it is unmistakably
        # slow, short enough the test does not hang.
        block_seconds = 5

        def slow_reader() -> Snapshot:
            entered.set()
            assert release.wait(timeout=block_seconds), \
                "test deadlocked: release never set"
            return _empty_snapshot()

        client = self._client(slow_reader)
        tree_response: list = [None]

        def call_tree() -> None:
            tree_response[0] = client.get("/api/tree")

        thread = threading.Thread(target=call_tree)
        thread.start()
        self.assertTrue(entered.wait(timeout=5), "read never started")

        # The event loop is free right now ONLY if the reader is truly
        # off-loaded to a worker thread. If `SnapshotService.read` ran the
        # reader synchronously on the loop, this call would queue behind
        # the blocked `/api/tree` request and could not complete until the
        # loop thread frees up — which, with `release` still unset, cannot
        # happen before `block_seconds`. The wall-clock bound below is
        # what makes this a timing proof, not a structural inference:
        # `release` is provably still unset (asserted right after) when
        # `/api/health` returns, and it returns in a small fraction of
        # `block_seconds`.
        started = time.monotonic()
        health = client.get("/api/health")
        elapsed = time.monotonic() - started
        self.assertEqual(health.status_code, 200)
        self.assertFalse(release.is_set(),
                          "release was already set — this run proves nothing")
        self.assertLess(elapsed, block_seconds / 2,
                         "GET /api/health took long enough to suggest it "
                         "queued behind the blocked snapshot read")

        release.set()
        thread.join(timeout=5)
        self.assertEqual(tree_response[0].status_code, 200)


if __name__ == "__main__":
    unittest.main()
