#!/usr/bin/env python3
"""cli/lib/provision.py — prepara a configuracao do host para o sandbox.

Le o manifesto, recusa qualquer caminho negado, aplica os filtros necessarios
e imprime linhas `origem<TAB>destino` para o chamador copiar.

Uso: provision.py <manifesto> <diretorio-de-staging>
"""
import json
import shutil
import sys
import tomllib
from pathlib import Path

# Nomes que nunca podem entrar no sandbox, nem como entrada declarada nem
# escondidos dentro de um diretorio declarado. A imagem autenticada ja carrega
# as credenciais dos agentes; as do host nao tem o que fazer la.
DENY = {
    ".credentials.json", "auth.json", "history.jsonl", ".netrc",
    "sessions", "projects", "security", "ide", "conversations",
    "knowledge", "brain", ".ssh", "id_ed25519", "keyring.pass",
}


def denied(path: Path) -> str | None:
    for part in path.parts:
        if part in DENY:
            return part
    return None


def scan(root: Path) -> str | None:
    """Procura caminho negado dentro de um diretorio declarado."""
    if root.is_file():
        return denied(Path(root.name))
    for p in root.rglob("*"):
        if p.name in DENY:
            return str(p)
    return None


def filter_claude_settings(src: Path, stage: Path) -> Path:
    data = json.loads(src.read_text())
    for key in ("hooks", "statusLine"):
        data.pop(key, None)
    out = stage / "claude-settings.json"
    out.write_text(json.dumps(data, indent=2))
    return out


FILTERS = {"claude-settings": filter_claude_settings}


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: provision.py <manifesto> <staging>", file=sys.stderr)
        return 2
    manifest, stage = Path(sys.argv[1]), Path(sys.argv[2])
    stage.mkdir(parents=True, exist_ok=True)
    entries = tomllib.loads(manifest.read_text()).get("entry", [])

    for e in entries:
        src = Path(e["src"]).expanduser()
        if (bad := denied(Path(e["src"]))) is not None:
            print(f"recusado: {e['src']} contem caminho negado ({bad})", file=sys.stderr)
            return 1
        if not src.exists():
            print(f"ausente, ignorado: {src}", file=sys.stderr)
            continue
        if (bad := scan(src)) is not None:
            print(f"recusado: {src} contem caminho negado ({bad})", file=sys.stderr)
            return 1
        if (name := e.get("filter")):
            src = FILTERS[name](src, stage)
        print(f"{src}\t{e['dst']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
