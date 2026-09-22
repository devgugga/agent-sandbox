"""server/asb_server/main.py — console entry: `asb-server serve` / `openapi`.

`serve` is wired only enough to exist and start; `--fixture` is Task 6's
and the cookie/token auth is Task 4's (amendment A). `openapi` must print
byte-identical JSON across runs — `pnpm check:api` (spec Section 5) depends
on that determinism, and this is where it is designed in: `sort_keys=True`
so no dict's insertion order leaks into the output.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import uvicorn
from asb.interfaces.snapshot import Snapshot

from .app import create_app
from .auth import AuthManager, InsecureModeError
from .settings import DEV_ORIGIN, Settings, port_from_env


def _unwired_snapshot_reader() -> Snapshot:
    """`SnapshotService.read` is Task 5's (amendment A); until it exists,
    `serve` starts and answers `/api/health` (Task 5's route) but any route
    that reads the tree has nothing working to call."""
    raise NotImplementedError(
        "snapshot reading is asb_server.snapshot.SnapshotService (Task 5); "
        "asb-server serve has no working tree reader yet")


def _settings_for(args: argparse.Namespace) -> Settings:
    port = args.port if args.port is not None else port_from_env()
    dev_origins = (DEV_ORIGIN,) if args.dev else ()
    return Settings(port=port, dev_origins=dev_origins)


def _serve(args: argparse.Namespace) -> None:
    settings = _settings_for(args)
    try:
        AuthManager.load(settings)
    except InsecureModeError as exc:
        # Refuses to start before the port ever binds (spec Section 12);
        # `create_app` itself never loads secrets (see auth.py).
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    app = create_app(settings, snapshot_reader=_unwired_snapshot_reader)
    uvicorn.run(app, host=settings.host, port=settings.port)


def _openapi(_args: argparse.Namespace) -> None:
    app = create_app(Settings(), snapshot_reader=_unwired_snapshot_reader)
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
    serve.set_defaults(func=_serve)

    openapi = subparsers.add_parser("openapi", help="print the OpenAPI schema")
    openapi.set_defaults(func=_openapi)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
