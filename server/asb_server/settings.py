"""server/asb_server/settings.py — the daemon's configuration.

`Settings` is a frozen dataclass; `main.py` is the only place that resolves
CLI flags and environment variables into one and hands it to `create_app`.
`host` has no flag and no environment variable — it is fixed to
`127.0.0.1` (spec Section 11's first security property), never
constructed from outside input.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 7420

# `pnpm dev` runs Vite on its own default port; `asb-server serve --dev`
# allows that origin so the Vite-proxied browser can call the daemon (spec
# Section 9.5). No document in this plan pins the number — it is Vite's
# own default, unconfigured in `web/vite.config.ts`.
DEV_ORIGIN = "http://localhost:5173"

_REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST_PATH = _REPO_ROOT / "web" / "dist"

# Mirrors `asb.keyring.CONFIG`'s ASB_CONFIG_ROOT convention exactly, so the
# daemon's token lives next to the CLI's own config instead of a second,
# invented location.
CONFIG_ROOT = (
    Path(os.environ["ASB_CONFIG_ROOT"])
    if "ASB_CONFIG_ROOT" in os.environ
    else Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
)


def port_from_env(default: int = DEFAULT_PORT) -> int:
    """`--port` (main.py) wins when given; otherwise `ASB_SERVER_PORT`,
    falling back to `DEFAULT_PORT`."""
    raw = os.environ.get("ASB_SERVER_PORT")
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    """The daemon's resolved configuration. Task 4 reads `token_path` and
    `session_key_path` to create and validate the token file and the
    session-signing key file; Task 3 only resolves the paths."""

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    token_path: Path = CONFIG_ROOT / "server-token"
    session_key_path: Path = CONFIG_ROOT / "server-session-key"
    web_dist_path: Path = WEB_DIST_PATH
    dev_origins: tuple[str, ...] = ()
