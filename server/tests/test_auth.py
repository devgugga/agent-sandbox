"""server/tests/test_auth.py — Task 4: daemon authentication.

Deliberately named to collide with `tests/unit/test_auth.py`, an unrelated
pre-existing suite. `--import-mode=importlib` (Task 1) is what lets this
file and that one coexist under one `pytest` invocation.

Every assertion here is on observable HTTP behavior — status codes,
headers, cookie attributes read off the raw `set-cookie` header (the
`TestClient` cookie jar drops `HttpOnly`/`SameSite`) — never on mocks.
"""
from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from asb.interfaces.snapshot import Snapshot
from asb_server.app import create_app
from asb_server.auth import AuthManager, InsecureModeError
from asb_server.settings import DEV_ORIGIN, Settings
from fastapi.testclient import TestClient

DAEMON_PORT = 7420
DAEMON_ORIGIN = f"http://127.0.0.1:{DAEMON_PORT}"


def _unused_snapshot_reader() -> Snapshot:
    # Auth routes never touch the snapshot reader; a call here is a bug.
    raise AssertionError("snapshot_reader should not be called by auth tests")


class AuthTestCase(unittest.TestCase):
    """Common fixture: a tmp config root, `Settings` pointing into it, and
    a helper to build a fresh app (and client) from those settings."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = Settings(
            port=DAEMON_PORT,
            token_path=tmp / "server-token",
            session_key_path=tmp / "server-session-key",
        )
        # Loading here (rather than relying on the app's lazy load) gives
        # the test the real token up front, and matches what main.py's
        # `_serve` does before `create_app`.
        self.manager = AuthManager.load(self.settings)
        self.client = self._client(self.settings)

    def _client(self, settings: Settings) -> TestClient:
        app = create_app(settings, snapshot_reader=_unused_snapshot_reader)
        return TestClient(app)

    def _login(self, client: TestClient | None = None) -> str:
        """Posts the real token and returns the issued cookie value."""
        response = (client or self.client).post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN},
        )
        assert response.status_code == 204, response.text
        return response.cookies["asb_session"]


class TestSessionEndpoint(AuthTestCase):
    def test_right_token_sets_cookie_with_the_three_named_attributes(self):
        response = self.client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN},
        )
        self.assertEqual(response.status_code, 204)
        set_cookie = response.headers.get("set-cookie")
        self.assertIsNotNone(set_cookie)
        lowered = set_cookie.lower()
        self.assertIn("httponly", lowered)
        self.assertIn("samesite=strict", lowered)
        self.assertIn("path=/", lowered)

    def test_wrong_token_is_401_and_sets_no_cookie(self):
        response = self.client.post(
            "/api/auth/session",
            json={"token": "not-the-token"},
            headers={"Origin": DAEMON_ORIGIN},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(response.headers.get("set-cookie"))

    def test_token_never_appears_in_a_response_body(self):
        # Success and failure both: the real token must not be echoed
        # back, and neither must anything derived from a wrong guess.
        wrong = self.client.post(
            "/api/auth/session",
            json={"token": "not-the-token"},
            headers={"Origin": DAEMON_ORIGIN},
        )
        self.assertNotIn(self.manager.token, wrong.text)

        right = self.client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": DAEMON_ORIGIN},
        )
        self.assertNotIn(self.manager.token, right.text)

    def test_foreign_origin_is_403_not_401(self):
        response = self.client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_origin_is_403(self):
        response = self.client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
        )
        self.assertEqual(response.status_code, 403)

    def test_dev_origin_accepted_with_dev_flag(self):
        dev_settings = Settings(
            port=self.settings.port,
            token_path=self.settings.token_path,
            session_key_path=self.settings.session_key_path,
            dev_origins=(DEV_ORIGIN,),
        )
        app = create_app(dev_settings, snapshot_reader=_unused_snapshot_reader)
        client = TestClient(app)
        response = client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": DEV_ORIGIN},
        )
        self.assertEqual(response.status_code, 204)

    def test_dev_origin_rejected_without_dev_flag(self):
        # The production app (no dev_origins) must not accept it either.
        response = self.client.post(
            "/api/auth/session",
            json={"token": self.manager.token},
            headers={"Origin": DEV_ORIGIN},
        )
        self.assertEqual(response.status_code, 403)


class TestMeEndpoint(AuthTestCase):
    def test_no_cookie_is_401(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_valid_cookie_is_204(self):
        cookie = self._login()
        self.client.cookies.set("asb_session", cookie)
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 204)

    def test_garbage_cookie_is_401(self):
        self.client.cookies.set("asb_session", "garbage-not-signed")
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)


class TestSessionSurvivesRestart(AuthTestCase):
    def test_cookie_from_one_app_validates_on_a_second_app_same_key_file(self):
        cookie = self._login()

        # A second app built from the SAME settings (same token and
        # session-key files on disk) simulates the daemon restarting: a
        # fresh process, same persisted `server-session-key`.
        restarted_client = self._client(self.settings)
        restarted_client.cookies.set("asb_session", cookie)
        response = restarted_client.get("/api/auth/me")
        self.assertEqual(response.status_code, 204)


class TestTokenFileModeValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _settings(self) -> Settings:
        return Settings(
            port=DAEMON_PORT,
            token_path=self.tmp / "server-token",
            session_key_path=self.tmp / "server-session-key",
        )

    def _make_loose_token_file(self, mode: int) -> Settings:
        settings = self._settings()
        settings.token_path.write_text("a" * 64)
        settings.token_path.chmod(mode)
        return settings

    def test_mode_0640_is_refused_with_chmod_message(self):
        settings = self._make_loose_token_file(0o640)
        with self.assertRaises(InsecureModeError) as ctx:
            AuthManager.load(settings)
        message = str(ctx.exception)
        self.assertIn("chmod 600", message)
        self.assertIn(str(settings.token_path), message)

    def test_mode_0604_is_refused_with_chmod_message(self):
        settings = self._make_loose_token_file(0o604)
        with self.assertRaises(InsecureModeError) as ctx:
            AuthManager.load(settings)
        message = str(ctx.exception)
        self.assertIn("chmod 600", message)
        self.assertIn(str(settings.token_path), message)

    def test_session_key_file_gets_the_same_check(self):
        settings = self._settings()
        # Token file is fine; the session-key file is the loose one.
        settings.session_key_path.write_text("b" * 64)
        settings.session_key_path.parent.mkdir(parents=True, exist_ok=True)
        settings.session_key_path.chmod(0o644)
        with self.assertRaises(InsecureModeError) as ctx:
            AuthManager.load(settings)
        self.assertIn("chmod 600", str(ctx.exception))
        self.assertIn(str(settings.session_key_path), str(ctx.exception))

    def test_mode_0600_is_accepted(self):
        settings = self._settings()
        settings.token_path.write_text("c" * 64)
        settings.token_path.chmod(0o600)
        manager = AuthManager.load(settings)
        self.assertEqual(manager.token, "c" * 64)

    def test_freshly_created_files_are_mode_0600(self):
        settings = self._settings()
        AuthManager.load(settings)
        token_mode = stat.S_IMODE(settings.token_path.stat().st_mode)
        key_mode = stat.S_IMODE(settings.session_key_path.stat().st_mode)
        self.assertEqual(token_mode, 0o600)
        self.assertEqual(key_mode, 0o600)


if __name__ == "__main__":
    unittest.main()
