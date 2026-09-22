"""server/tests/test_static.py — Task 6: static serving and `--fixture`.

Deliberately named to collide with any `tests/unit/test_static.py`-shaped
suite elsewhere: `--import-mode=importlib` (Task 1) is what lets same-named
files coexist under one `pytest` invocation.

`/api/*` NEVER falls back to `index.html` — that is the whole point of
the boundary between the two. `TestApiBoundary` proves that with the
observable response (status AND content type/body — a 404 that happened
to carry HTML would
still fail the property even at the right status code), not by trusting
that `static.router` is mounted after the `/api` routers.

`TestFixtureReader` proves: a real daemon built with
`snapshot.fixture_reader` over the two files in `server/fixtures/`
serves the healthy tree's data verbatim (bypassing
`models.tree_response`/`sanitize`, since a fixture already carries the
wire shape) and drives the registry-failure fixture through the exact
same 503 branch a real registry failure takes;
auth is untouched either way (Section F) — every fixture-backed request
below still needs the real cookie.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from asb.interfaces.snapshot import Snapshot
from asb_server.app import create_app
from asb_server.auth import AuthManager
from asb_server.settings import Settings
from asb_server.snapshot import fixture_reader
from fastapi.testclient import TestClient

DAEMON_PORT = 7420
DAEMON_ORIGIN = f"http://127.0.0.1:{DAEMON_PORT}"

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_HEALTHY_FIXTURE = _FIXTURES_DIR / "healthy-tree.json"
_REGISTRY_FAILURE_FIXTURE = _FIXTURES_DIR / "registry-failure.json"


def _unused_snapshot_reader() -> Snapshot:
    # Static/boundary tests never touch the snapshot reader; a call here
    # is a bug (it would mean a static path reached an /api handler).
    raise AssertionError("snapshot_reader should not be called by these tests")


def _build_dist(tmp: Path) -> Path:
    """A minimal but real `web/dist`: an `index.html` distinguishable from
    a 404 body, and one asset file so the "serve the literal file when it
    exists" branch has something real to hit."""
    dist = tmp / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>asb</title>")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('asb');")
    return dist


class StaticTestCase(unittest.TestCase):
    """Common fixture: a tmp config root and a settable `web_dist_path`.
    Subclasses build `Settings`/the app themselves since some cases need a
    real `dist` and others deliberately omit it."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _settings(self, *, web_dist_path: Path) -> Settings:
        return Settings(
            port=DAEMON_PORT,
            token_path=self.tmp / "server-token",
            session_key_path=self.tmp / "server-session-key",
            web_dist_path=web_dist_path,
        )


class TestSpaFallback(StaticTestCase):
    def setUp(self) -> None:
        super().setUp()
        dist = _build_dist(self.tmp)
        settings = self._settings(web_dist_path=dist)
        app = create_app(settings, snapshot_reader=_unused_snapshot_reader)
        self.client = self.enterContext(TestClient(app))

    def test_root_serves_index(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("<title>asb</title>", response.text)

    def test_unknown_client_route_serves_index(self):
        # A React-Router-owned path the daemon never heard of — the SPA
        # itself resolves it client-side once index.html has loaded.
        response = self.client.get("/anything/deep/path")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>asb</title>", response.text)

    def test_real_asset_is_served_literally_not_index(self):
        response = self.client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("console.log", response.text)


class TestApiBoundary(StaticTestCase):
    """`/api/*` never falls back to `index.html`, status AND body."""

    def setUp(self) -> None:
        super().setUp()
        dist = _build_dist(self.tmp)
        settings = self._settings(web_dist_path=dist)
        app = create_app(settings, snapshot_reader=_unused_snapshot_reader)
        self.client = self.enterContext(TestClient(app))

    def test_unknown_api_path_is_404_not_html(self):
        response = self.client.get("/api/unknown")
        self.assertEqual(response.status_code, 404)
        self.assertIn("application/json", response.headers["content-type"])
        self.assertNotIn("<title>asb</title>", response.text)
        self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_unknown_nested_api_path_is_also_404(self):
        response = self.client.get("/api/tree/nonexistent")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("<title>asb</title>", response.text)


class TestMissingDist(StaticTestCase):
    """`web/dist` missing: `/` is 503 naming the fix; `/api` still works —
    a front end that never got built must not take the API down."""

    def setUp(self) -> None:
        super().setUp()
        settings = self._settings(web_dist_path=self.tmp / "never-built")
        app = create_app(settings, snapshot_reader=_unused_snapshot_reader)
        self.client = self.enterContext(TestClient(app))

    def test_root_is_503_naming_the_fix(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("asb-agent install-server", response.json()["detail"])

    def test_any_non_api_path_is_also_503(self):
        response = self.client.get("/some/route")
        self.assertEqual(response.status_code, 503)

    def test_api_health_still_answers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_api_unknown_is_still_404_not_503(self):
        # A missing dist must not change the /api boundary's own status.
        response = self.client.get("/api/unknown")
        self.assertEqual(response.status_code, 404)


class FixtureTestCase(unittest.TestCase):
    """Common fixture for `--fixture`-reader tests: a real token/session
    (auth is never disabled) and a real `dist` so the daemon this builds
    is exactly what `asb-server serve --fixture` would run."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        dist = _build_dist(tmp)
        self.settings = Settings(
            port=DAEMON_PORT,
            token_path=tmp / "server-token",
            session_key_path=tmp / "server-session-key",
            web_dist_path=dist,
        )
        self.manager = AuthManager.load(self.settings)

    def _client(self, fixture_path: Path) -> TestClient:
        app = create_app(self.settings, snapshot_reader=fixture_reader(fixture_path))
        return self.enterContext(TestClient(app))

    def _login(self, client: TestClient) -> None:
        response = client.post(
            "/api/auth/session", json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN})
        assert response.status_code == 204, response.text


class TestFixtureHealthyTree(FixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = self._client(_HEALTHY_FIXTURE)

    def test_tree_requires_the_real_cookie(self):
        # Section F: --fixture does not disable auth.
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 401)

    def test_tree_serves_the_fixture_verbatim(self):
        self._login(self.client)
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 200)
        expected = json.loads(_HEALTHY_FIXTURE.read_text())
        self.assertEqual(response.json(), expected)

    def test_index_is_still_served_from_the_real_dist(self):
        # --fixture only swaps the reader; static serving is untouched.
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>asb</title>", response.text)


class TestFixtureRegistryFailure(FixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = self._client(_REGISTRY_FAILURE_FIXTURE)
        self._login(self.client)

    def test_tree_is_503_via_the_same_registry_error_branch(self):
        response = self.client.get("/api/tree")
        self.assertEqual(response.status_code, 503)
        expected = json.loads(_REGISTRY_FAILURE_FIXTURE.read_text())
        self.assertEqual(response.json(), {"detail": expected["registry_error"]})


if __name__ == "__main__":
    unittest.main()
