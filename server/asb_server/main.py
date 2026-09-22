"""server/asb_server/main.py — console entry: `asb-server serve` / `openapi`.

`serve`'s cookie/token auth is Task 4's; `--fixture` is Task 6's
(`_reader_for` below). `openapi` never touches `--fixture` — it
always uses `production_reader`, and must print byte-identical JSON
across runs: `pnpm check:api` (spec Section 5) depends on that
determinism, and this is where it is designed in: `sort_keys=True` so no
dict's insertion order leaks into the output.

Logging is configured here, in `_serve`, rather than in `create_app`:
`asb-server openapi` calls `create_app` too and must stay a pure,
side-effect-free command, so process-wide logging setup belongs to the
one entry point that actually serves traffic. It runs before
`AuthManager.load` so that call's own "token file created" log line
(spec Section 12, `auth.py`) is not silently dropped.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .app import create_app
from .auth import AuthManager, InsecureModeError
from .settings import DEV_ORIGIN, Settings, port_from_env
from .snapshot import SnapshotReader, fixture_reader, production_reader


def _settings_for(args: argparse.Namespace) -> Settings:
    port = args.port if args.port is not None else port_from_env()
    dev_origins = (DEV_ORIGIN,) if args.dev else ()
    return Settings(port=port, dev_origins=dev_origins)


def _reader_for(args: argparse.Namespace) -> SnapshotReader:
    """`--fixture <path.json>` (spec Section 10) is a testability hook,
    not a bypass: it only swaps WHAT `create_app` reads, never whether
    auth runs (`_serve` still calls `AuthManager.load` first, exactly as
    without it), the bind address (`settings.host` is untouched —
    `_settings_for` never reads `args.fixture`), or
    whether secrets are created at `create_app` time (`create_app` never
    loads them either way; see `auth.py`'s module docstring). The fixture
    file itself is read and validated HERE, once, before `uvicorn.run` —
    a malformed fixture is a startup failure with a clear message, not a
    500 on the first request."""
    if args.fixture is None:
        return production_reader
    try:
        return fixture_reader(args.fixture)
    except (OSError, ValueError) as exc:
        print(f"asb-server: could not load fixture {args.fixture}: {exc}",
              file=sys.stderr)
        sys.exit(1)


def _serve(args: argparse.Namespace) -> None:
    settings = _settings_for(args)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                         format="%(asctime)s %(name)s %(message)s")
    try:
        AuthManager.load(settings)
    except InsecureModeError as exc:
        # Refuses to start before the port ever binds (spec Section 12);
        # `create_app` itself never loads secrets (see auth.py).
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    app = create_app(settings, snapshot_reader=_reader_for(args))
    # `access_log=False`: uvicorn's own access log would double every
    # request line alongside `app.py`'s `_log_requests` middleware, which
    # is the "one line per request" spec Section 7.6 asks for (and what
    # the validation checklist's row 4.2 counts).
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False)


def _openapi(_args: argparse.Namespace) -> None:
    app = create_app(Settings(), snapshot_reader=production_reader)
    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asb-server")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the daemon")
    serve.add_argument("--port", type=int, default=None,
                        help="overrides ASB_SERVER_PORT and the default (7420)")
    serve.add_argument("--dev", action="store_true",
                        help="allow the Vite dev-server origin")
    serve.add_argument("--fixture", type=Path, default=None,
                        help="serve a fixture JSON file instead of a real "
                             "read (spec Section 10); testability hook, "
                             "not a bypass (auth and the bind stay as-is)")
    serve.set_defaults(func=_serve)

    openapi = subparsers.add_parser("openapi", help="print the OpenAPI schema")
    openapi.set_defaults(func=_openapi)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
