#!/usr/bin/env python3
"""cli/lib/render_squid.py — junta allowlist base + perfil e emite squid.conf.

Uso: render_squid.py <allowlist-base.txt> <perfil.json>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent.parent / "image" / "squid" / "squid.conf.tmpl"


def read_base(path: Path) -> list[str]:
    domains = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(line)
    return domains


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: render_squid.py <allowlist-base> <perfil-json>", file=sys.stderr)
        return 2

    domains = read_base(Path(sys.argv[1]))
    profile = json.loads(Path(sys.argv[2]).read_text())
    domains.extend(profile.get("allow", []))

    # dedup preservando ordem
    seen, ordered = set(), []
    for d in domains:
        if d not in seen:
            seen.add(d)
            ordered.append(d)

    if not ordered:
        print("allowlist vazia: o sandbox ficaria sem egresso algum", file=sys.stderr)
        return 1

    sys.stdout.write(TEMPLATE.read_text().replace("__ALLOWLIST__", " ".join(ordered)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
