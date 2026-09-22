"""server/asb_server/auth.py — token file, cookie session, Origin check.

Two `0600` secret files back the daemon's authentication (spec Section
7.5): `server-token` (32 random bytes, hex) is what `asb-agent ui` posts
once from the URL fragment, and `server-session-key` (same shape) signs
the session id carried in the cookie so a session survives a daemon
restart. Both are created atomically with
`os.O_CREAT | os.O_EXCL | os.O_WRONLY` and the mode passed to `os.open` —
never create-then-`chmod` (`cli/asb/keyring.py`'s pattern), which leaves a
window where the file is briefly observable at the process umask's mode.
These two files are the daemon's only secrets (amendment D).

`AuthManager.load` is called from two places: `main.py::_serve` calls it
once, eagerly, before `create_app`, purely to fail fast — "the daemon
refuses to start" (spec Section 12) has to happen before `uvicorn.run`
binds the port, and it must not happen as a side effect of
`asb-server openapi` (which also calls `create_app`, and must stay a pure,
byte-stable, disk-write-free command). So `create_app` never loads secrets
itself; `get_auth_manager` below loads them lazily, on the first request
that needs them, and caches the result on `app.state`.

Every comparison against a secret goes through `hmac.compare_digest`
(amendment F) — a plain `==` is a timing oracle on the token or on the
session signature.

Task 5 (amendment D) adds the one log call spec Section 12 asks for here:
"token file missing at daemon start: generated with 0600; logged once."
The line names the path, never the secret value.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from .settings import Settings

SESSION_COOKIE_NAME = "asb_session"
TOKEN_BYTES = 32

# Any bit set beyond owner read/write is "looser than 0600" (amendment E).
_ALLOWED_MODE_BITS = 0o600

logger = logging.getLogger("asb_server")


class InsecureModeError(RuntimeError):
    """A secret file's mode is looser than 0600. `str(exc)` names the exact
    `chmod` command to run (spec Section 12); the daemon must not start."""


def _ensure_secret_file(path: Path) -> tuple[str, bool]:
    """Returns `(hex secret at path, was it just created)`, creating it
    (32 random bytes, hex, mode 0600) if it does not exist yet. Creation
    is atomic: the kernel sets the mode at `os.open` time, so the file is
    never observable at any other mode. Raises `InsecureModeError` if an
    existing file's mode is looser than 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _ALLOWED_MODE_BITS)
    except FileExistsError:
        pass
    else:
        secret = secrets.token_hex(TOKEN_BYTES)
        with os.fdopen(fd, "w") as handle:
            handle.write(secret)
        return secret, True

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & ~_ALLOWED_MODE_BITS:
        raise InsecureModeError(
            f"{path} has mode {mode:04o}, which is looser than 0600. "
            f"Run: chmod 600 {path}"
        )
    return path.read_text().strip(), False


@dataclass(frozen=True)
class AuthManager:
    """The daemon's loaded secrets plus the operations that use them.
    Immutable and self-contained: two independently loaded instances built
    from the same `session_key` verify each other's session values, which
    is what lets a session survive a daemon restart (spec Section 7.5)."""

    token: str
    session_key: bytes

    @classmethod
    def load(cls, settings: Settings) -> AuthManager:
        """Reads or creates both secret files. Raises `InsecureModeError`
        if either is looser than 0600 — the token and the session key are
        equally secret (amendment E)."""
        token, token_created = _ensure_secret_file(settings.token_path)
        if token_created:
            # Spec Section 12: "token file missing at daemon start:
            # generated with 0600; logged once." Only the path, never the
            # token itself.
            logger.info("token file created at %s (mode 0600)",
                        settings.token_path)
        session_key_hex, _ = _ensure_secret_file(settings.session_key_path)
        return cls(token=token, session_key=bytes.fromhex(session_key_hex))

    def verify_token(self, candidate: str) -> bool:
        """Constant-time comparison against the token. Never raises: a
        candidate with non-ASCII characters simply fails to match, rather
        than turning into a 500 that could echo something back."""
        try:
            return hmac.compare_digest(self.token, candidate)
        except TypeError:
            return False

    def issue_session_value(self) -> str:
        """A fresh `<session id>.<hmac>` cookie value. The signature lets
        any daemon holding the same `session_key` — including one started
        after a restart — verify it without keeping the id in memory."""
        session_id = secrets.token_hex(16)
        signature = self._sign(session_id)
        return f"{session_id}.{signature}"

    def verify_session_value(self, value: str) -> bool:
        """Constant-time verification of a `<session id>.<hmac>` cookie
        value. Malformed or hostile input (missing separator, non-ASCII
        bytes) fails closed rather than raising, so a 401 body never
        differs based on how a cookie was invalid."""
        session_id, _, signature = value.partition(".")
        if not session_id or not signature:
            return False
        try:
            return hmac.compare_digest(self._sign(session_id), signature)
        except TypeError:
            return False

    def _sign(self, session_id: str) -> str:
        return hmac.new(
            self.session_key, session_id.encode("ascii"), hashlib.sha256
        ).hexdigest()


def get_auth_manager(request: Request) -> AuthManager:
    """FastAPI dependency: the request's `AuthManager`, loaded and cached
    on `app.state` at first use rather than at `create_app` time (see the
    module docstring for why `asb-server openapi` must not trigger this)."""
    state = request.app.state
    manager = getattr(state, "auth_manager", None)
    if manager is None:
        manager = AuthManager.load(state.settings)
        state.auth_manager = manager
    return manager


def allowed_origins(settings: Settings) -> frozenset[str]:
    """The daemon's own origin, plus the Vite dev origin when `--dev` was
    passed (`settings.dev_origins`). Spec Section 7.2."""
    return frozenset({f"http://{settings.host}:{settings.port}", *settings.dev_origins})


def require_origin(request: Request) -> None:
    """Dependency for POST routes (and, later, WebSocket upgrades): the
    `Origin` header must equal the daemon's own origin or the dev origin.
    A missing or foreign origin is 403 — distinct from 401, which is about
    the cookie, never the origin (amendment C)."""
    settings: Settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is None or origin not in allowed_origins(settings):
        raise HTTPException(status_code=403)


def require_session(
    request: Request,
    manager: AuthManager = Depends(get_auth_manager),  # noqa: B008 (FastAPI idiom)
) -> None:
    """Dependency for every route except `health` and `auth/session`
    (spec Section 7.2): the session cookie must be present and valid."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie is None or not manager.verify_session_value(cookie):
        raise HTTPException(status_code=401)
