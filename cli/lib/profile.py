#!/usr/bin/env python3
"""cli/lib/profile.py — le .agent-sandbox.toml de um repo e emite JSON normalizado.

Uso: profile.py <caminho-do-repo>
Se o repo nao tiver perfil, usa profiles/default.toml.
"""
import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent.parent / "profiles" / "default.toml"


def load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: profile.py <caminho-do-repo>", file=sys.stderr)
        return 2

    repo = Path(sys.argv[1])
    candidate = repo / ".agent-sandbox.toml"
    raw = load(candidate) if candidate.is_file() else load(DEFAULT)
    base = load(DEFAULT)

    out = {
        "mode": raw.get("sandbox", {}).get("mode", base["sandbox"]["mode"]),
        "services": raw.get("services", {}),
        "allow": raw.get("network", {}).get("allow", []),
        "proxy": {**base.get("proxy", {}), **raw.get("proxy", {})},
    }

    if out["mode"] not in ("isolated", "attached"):
        print(f"modo invalido: {out['mode']!r}", file=sys.stderr)
        return 1

    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
