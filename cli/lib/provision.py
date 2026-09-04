#!/usr/bin/env python3
"""cli/lib/provision.py — prepara a configuracao do host para o sandbox.

Le o manifesto, recusa qualquer caminho negado, aplica os filtros necessarios
e imprime linhas `origem<TAB>destino` para o chamador copiar.

Uso: provision.py <manifesto> <diretorio-de-staging>
"""
import hashlib
import json
import re
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

ALLOWED_SYMLINK_ROOTS = (
    Path.home() / ".agents" / "skills",
    Path("/usr/share/omarchy/default/agents/skills"),
)
ALLOWED_DESTINATION_ROOTS = (
    Path("/home/agent/.claude"),
    Path("/home/agent/.codex"),
    Path("/home/agent/.gemini"),
)


def denied(path: Path) -> str | None:
    for part in path.parts:
        if part in DENY:
            return part
    return None


def scan(root: Path) -> str | None:
    """Procura caminho negado dentro de um diretorio declarado.

    Verifica o nome E o alvo resolvido de cada entrada. Sem resolver, um
    symlink chamado `inocente.json` apontando para `~/.claude/.credentials.json`
    passa pela lista de negacao — o nome nao e negado. Hoje o `podman cp`
    preserva symlinks em vez de segui-los, entao o vazamento nao se concretiza,
    mas depender desse detalhe do podman como fronteira e fragil: qualquer troca
    por `tar --dereference` ou `cp -L` reabriria o buraco.
    """
    source_root = root.resolve()
    allowed_roots = tuple(path.resolve() for path in ALLOWED_SYMLINK_ROOTS)
    seen: set[Path] = set()

    def within(path: Path, parent: Path) -> bool:
        return path == parent or path.is_relative_to(parent)

    def trusted_target(target: Path) -> bool:
        return within(target, source_root) or any(
            within(target, allowed) for allowed in allowed_roots
        )

    def visit(path: Path, *, declared_root: bool = False) -> str | None:
        if (bad := denied(Path(path.name))) is not None:
            return f"{path} ({bad})"
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except FileNotFoundError:
                return None
            if (bad := denied(target)) is not None:
                return f"{path} -> {target} ({bad})"
            # O proprio src nao ganha confianca so por resolver para si mesmo.
            if (declared_root and not any(within(target, a) for a in allowed_roots)) \
                    or (not declared_root and not trusted_target(target)):
                return f"{path} -> {target} (fora das raizes permitidas)"
            return visit(target)
        if path.is_file():
            return denied(path.resolve())
        if not path.is_dir():
            return None
        resolved = path.resolve()
        if resolved in seen:
            return None
        seen.add(resolved)
        try:
            children = path.iterdir()
            for child in children:
                if (bad := visit(child)) is not None:
                    return bad
        except OSError as error:
            return f"{path} nao pode ser inspecionado ({error})"
        return None

    return visit(root, declared_root=root.is_symlink())



def materialize(src: Path, stage: Path) -> Path:
    """Copia um diretorio para o staging com os symlinks RESOLVIDOS.

    `podman cp` preserva symlinks. As skills do host apontam para fora do home
    (`/usr/share/omarchy/...`, `~/.agents/skills/...`), entao sem resolver elas
    chegam ao container como links quebrados: presentes num `ls`, inuteis para
    o agente. Links quebrados na origem sao ignorados em vez de abortar.
    """
    # Chave derivada do caminho de ORIGEM: ~/.claude/plugins e ~/.codex/plugins
    # tem o mesmo basename e colidiriam no staging, com o segundo sobrescrevendo
    # o primeiro em silencio.
    key = hashlib.sha256(str(src).encode()).hexdigest()[:12]
    dest = stage / f"{key}-{src.name}"
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(directory, names):
        skip = []
        for n in names:
            candidate = Path(directory) / n
            if candidate.is_symlink() and not candidate.exists():
                skip.append(n)
        return skip

    shutil.copytree(src, dest, symlinks=False, ignore=ignore)
    return dest


def filter_claude_settings(src: Path, stage: Path) -> Path:
    data = json.loads(src.read_text())
    for key in ("hooks", "statusLine"):
        data.pop(key, None)
    out = stage / "claude-settings.json"
    out.write_text(json.dumps(data, indent=2))
    return out


def filter_antigravity_hooks(src: Path, stage: Path) -> Path:
    """Reescreve somente comandos de hook que apontam para o home do host."""
    data = json.loads(src.read_text())
    hook_path = re.compile(r"/(?:[^/\s'\"]+/)*\.orca/agent-hooks/")

    def normalize(value):
        if isinstance(value, dict):
            return {
                key: hook_path.sub("/home/agent/.orca/agent-hooks/", child)
                if key == "command" and isinstance(child, str)
                else normalize(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [normalize(child) for child in value]
        return value

    out = stage / "antigravity-hooks.json"
    out.write_text(json.dumps(normalize(data), indent=2) + "\n")
    return out


FILTERS = {
    "antigravity-hooks": filter_antigravity_hooks,
    "claude-settings": filter_claude_settings,
}


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: provision.py <manifesto> <staging>", file=sys.stderr)
        return 2
    manifest, stage = Path(sys.argv[1]), Path(sys.argv[2])
    stage.mkdir(parents=True, exist_ok=True)
    entries = tomllib.loads(manifest.read_text()).get("entry", [])

    for e in entries:
        src = Path(e["src"]).expanduser()
        dst = Path(e["dst"])
        if (bad := denied(Path(e["src"]))) is not None:
            print(f"recusado: {e['src']} contem caminho negado ({bad})", file=sys.stderr)
            return 1
        if not src.exists():
            print(f"ausente, ignorado: {src}", file=sys.stderr)
            continue
        if (bad := scan(src)) is not None:
            print(f"recusado: {src} contem caminho negado ({bad})", file=sys.stderr)
            return 1
        if ".." in dst.parts or not dst.is_absolute() or not any(
            dst == root or dst.is_relative_to(root)
            for root in ALLOWED_DESTINATION_ROOTS
        ) or (bad := denied(dst)) is not None:
            print(f"recusado: destino fora das raizes permitidas: {dst}", file=sys.stderr)
            return 1
        if (name := e.get("filter")):
            src = FILTERS[name](src, stage)
        elif src.is_dir():
            src = materialize(src, stage)
        print(f"{src}\t{dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
