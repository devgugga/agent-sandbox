"""server/tests/test_tree.py — Task 5: GET /api/tree.

Deliberately named to collide with any `tests/unit/test_tree.py`-shaped
suite elsewhere: `--import-mode=importlib` (Task 1) is what lets same-named
files coexist under one `pytest` invocation.

These tests exercise the ROUTE's wiring — auth, the error model, the
converter call — through real HTTP requests against a stub
`snapshot_reader`. `models.tree_response`'s own exhaustive scenarios (every
error field, both merged labels, sanitization) are already covered at the
unit level by `test_models.py` (Task 3); this file does not re-prove those,
only that `/api/tree` reaches the SAME converter and serializes what it
returns.

Concurrency (single-flight, worker-thread offloading) is
`test_single_flight.py`'s job, not this file's.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from asb.checkouts.model import CheckoutId, CheckoutKind
from asb.interfaces.snapshot import Snapshot
from asb.interfaces.tui_model import CheckoutView, UnregisteredView
from asb.projects.model import Project, ProjectId
from asb.runtime.sandbox import WorkspaceStatus
from asb.sessions.model import AgentKind, AgentSession, SessionId, SessionState
from asb_server.app import create_app
from asb_server.auth import AuthManager
from asb_server.models import tree_response
from asb_server.settings import Settings
from fastapi.testclient import TestClient

DAEMON_PORT = 7420
DAEMON_ORIGIN = f"http://127.0.0.1:{DAEMON_PORT}"

PROJECT_ID = ProjectId("p-aaaaaaaa")
PROJECT_ID_2 = ProjectId("p-bbbbbbbb")
CHECKOUT_READY = CheckoutId("c-ready0001")
CHECKOUT_ERROR = CheckoutId("c-error0001")
SESSION_ID = SessionId("s-aaaaaaaa")


def _fixture_snapshot() -> Snapshot:
    """One healthy project (a ready checkout with a session and an
    unregistered worktree) plus a second project that failed discovery —
    every error field the converter has (`ProjectNode.error`,
    `CheckoutNode.reason`, `CheckoutNode.error`) is populated at once."""
    project = Project(id=PROJECT_ID, primary=Path("/repo/p"),
                       integration_branch="main",
                       worktree_root=Path("/repo/worktrees"))
    checkout_ready = CheckoutView(
        checkout_id=CHECKOUT_READY, project_id=PROJECT_ID,
        source_path=Path("/repo/p"), workspace="ws-1",
        kind=CheckoutKind.PRIMARY, status=WorkspaceStatus.READY,
        branch="main")
    checkout_error = CheckoutView(
        checkout_id=CHECKOUT_ERROR, project_id=PROJECT_ID,
        source_path=Path("/repo/p-wt"), workspace="ws-2",
        kind=CheckoutKind.WORKTREE, status=WorkspaceStatus.UNAVAILABLE,
        reason="podman down", branch="feature", error="reconcile failed")
    session = AgentSession(
        id=SESSION_ID, checkout_id=CHECKOUT_READY, agent=AgentKind.CLAUDE,
        cwd=Path("/repo/p"), title="review PR", state=SessionState.RUNNING,
        terminal_id=None, provider_session_id=None, last_healthy_at=None)
    unregistered = UnregisteredView(
        project_id=PROJECT_ID, path=Path("/repo/loose"), branch="wip",
        detached=False, missing=False, prunable=True)
    return Snapshot(
        projects=(project,), checkouts=(checkout_ready, checkout_error),
        sessions=(session,), unregistered=(unregistered,),
        project_errors={PROJECT_ID_2: "discover failed"},
        registry_error=None)


def _registry_failure_snapshot() -> Snapshot:
    return Snapshot(projects=(), checkouts=(), sessions=(), unregistered=(),
                     project_errors={}, registry_error="disk full")


class TreeTestCase(unittest.TestCase):
    """Common fixture: a real token, a logged-in client, and a settable
    `snapshot_reader` (tests assign `self.reader` before the first
    request that needs it)."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings(
            port=DAEMON_PORT,
            token_path=tmp / "server-token",
            session_key_path=tmp / "server-session-key",
        )
        self.manager = AuthManager.load(self.settings)
        self.reader = _fixture_snapshot
        app = create_app(self.settings, snapshot_reader=lambda: self.reader())
        self.client = self.enterContext(TestClient(app))

    def _login(self) -> None:
        response = self.client.post(
            "/api/auth/session", json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN})
        assert response.status_code == 204, response.text


class TestTreeRequiresSession(TreeTestCase):
    def test_without_cookie_is_401(self):
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 401)


class TestTreeSuccess(TreeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._login()

    def test_serializes_exactly_what_the_converter_produces(self):
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # `read_at` is generated by `SnapshotService`, not the fixture, so
        # it is captured off the real response and reused to build the
        # expectation — everything else must match byte for byte.
        read_at = datetime.fromisoformat(body["read_at"])
        expected = tree_response(_fixture_snapshot(), read_at=read_at)
        self.assertEqual(body, expected.model_dump(mode="json"))

    def test_per_project_error_is_data_not_an_http_error(self):
        body = self.client.get("/api/tree").json()
        by_id = {p["id"]: p for p in body["projects"]}
        # Only the healthy project has any checkouts; the failed one
        # never appears among `projects` at all here (the fixture never
        # constructed a `ProjectNode` for it — `project_errors` names a
        # project id `tree_response` was never asked to render). What
        # matters is the response is 200 despite that pending error data
        # existing in the snapshot.
        self.assertEqual(len(body["projects"]), 1)
        self.assertIn(PROJECT_ID, by_id)

    def test_per_checkout_error_and_reason_are_present(self):
        body = self.client.get("/api/tree").json()
        checkouts = {c["id"]: c for c in body["projects"][0]["checkouts"]}
        broken = checkouts[str(CHECKOUT_ERROR)]
        self.assertEqual(broken["error"], "reconcile failed")
        self.assertEqual(broken["reason"], "podman down")
        # The other checkout in the SAME project still renders fine — one
        # broken checkout never hides the others.
        healthy = checkouts[str(CHECKOUT_READY)]
        self.assertIsNone(healthy["error"])
        self.assertEqual(len(healthy["sessions"]), 1)

    def test_unregistered_worktree_is_present(self):
        body = self.client.get("/api/tree").json()
        unregistered = body["projects"][0]["unregistered"]
        self.assertEqual(len(unregistered), 1)
        self.assertTrue(unregistered[0]["prunable"])

    def test_one_reader_invocation_per_request(self):
        calls = []
        self.reader = lambda: (calls.append(1) or _fixture_snapshot())
        self.client.get("/api/tree")
        self.assertEqual(len(calls), 1)


class TestTreeRegistryFailure(TreeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._login()
        self.reader = _registry_failure_snapshot

    def test_registry_error_is_503_with_bare_reason(self):
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "disk full"})

    def test_per_request_log_line_still_carries_read_at_on_503(self):
        # `request.state.log_extra` is set BEFORE the route raises
        # `HTTPException(503)` — this proves it survives into
        # `app._log_requests` on the error path too, not just the 200
        # path `test_tree.py`'s other tests exercise.
        with self.assertLogs("asb_server", level="INFO") as captured:
            response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 503)
        tree_lines = [line for line in captured.output if "/api/tree" in line]
        self.assertEqual(len(tree_lines), 1, captured.output)
        self.assertIn("-> 503 read_at=", tree_lines[0])


if __name__ == "__main__":
    unittest.main()
