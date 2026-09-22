"""server/tests/test_health.py — Task 5: GET /api/health.

Deliberately named to collide with any `tests/unit/test_health.py`-shaped
suite elsewhere: `--import-mode=importlib` (Task 1) is what lets same-named
files coexist under one `pytest` invocation.

Covers: the route answers WITHOUT a session cookie (spec Section 7.2 —
it and `auth/session` are the only two unauthenticated routes, and this is
what `asb-agent ui`/`doctor` poll before a session exists), and the body
carries both `version` and `started_at`.
"""
from __future__ import annotations

import unittest
from datetime import datetime

from asb.interfaces.snapshot import Snapshot
from asb_server.app import create_app
from asb_server.settings import Settings
from fastapi.testclient import TestClient


def _unused_snapshot_reader() -> Snapshot:
    # /api/health never touches the snapshot reader; a call here is a bug.
    raise AssertionError("snapshot_reader should not be called by health tests")


class TestHealthEndpoint(unittest.TestCase):
    def _client(self) -> TestClient:
        app = create_app(Settings(), snapshot_reader=_unused_snapshot_reader)
        return TestClient(app)

    def test_answers_without_any_cookie(self):
        client = self._client()
        # No login, no Cookie header at all.
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_body_carries_version_and_started_at(self):
        client = self._client()
        body = client.get("/api/health").json()
        self.assertIn("version", body)
        self.assertIsInstance(body["version"], str)
        self.assertGreater(len(body["version"]), 0)
        # A valid ISO-8601 datetime string; raises on anything else.
        datetime.fromisoformat(body["started_at"])

    def test_started_at_is_fixed_across_requests(self):
        # spec/amendment Section F: fixed at process start, not per
        # request — two calls to the SAME app report the SAME instant.
        client = self._client()
        first = client.get("/api/health").json()["started_at"]
        second = client.get("/api/health").json()["started_at"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
