"""cli/asb/staging.py — prepara a configuracao do host para o sandbox.

A allowlist e EXPLICITA de proposito. ~/.claude contem .credentials.json e
~/.codex contem auth.json: declarar o diretorio inteiro entregaria a credencial
do host ao sandbox, que e exatamente o que o volume de credenciais existe para
evitar.

Saida: uma arvore em `stage` mais um manifest.tsv com linhas
`origem-relativa<TAB>destino-absoluto`, que o entrypoint materializa a partir
de um mount read-only.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

# Nomes que nunca entram no sandbox, nem declarados nem escondidos dentro de um
# diretorio declarado.
DENY = {
    ".credentials.json", "auth.json", "history.jsonl", ".netrc",
    "sessions", "projects", "security", "ide", "conversations",
    "knowledge", "brain", ".ssh", "id_ed25519", "keyring.pass",
}


class StagingError(Exception):
    pass


def _allowed_symlink_roots(home: Path) -> tuple[Path, ...]:
    return (home / ".agents" / "skills",
            Path("/usr/share/omarchy/default/agents/skills"))


def _allowed_destination_roots(home: Path) -> tuple[Path, ...]:
    # Espelham o home do HOST (spec D4). Nunca /home/agent literal.
    return (home / ".claude", home / ".codex", home / ".gemini")


def denied(path: Path) -> str | None:
    for part in path.parts:
        if part in DENY:
            return part
    return None


def scan(root: Path, home: Path) -> str | None:
    """Procura caminho negado dentro de um diretorio declarado.

    Verifica o nome E o alvo resolvido de cada entrada. Sem resolver, um
    symlink chamado `inocente.json` apontando para ~/.claude/.credentials.json
    passaria: o nome nao e negado.
    """
    source_root = root.resolve()
    allowed = tuple(p.resolve() for p in _allowed_symlink_roots(home)
                    if p.exists())
    seen: set[Path] = set()

    def within(path: Path, parent: Path) -> bool:
        return path == parent or path.is_relative_to(parent)

    def trusted(target: Path) -> bool:
        return within(target, source_root) or any(
            within(target, a) for a in allowed)

    def visit(path: Path, *, declared_root: bool = False) -> str | None:
        if (bad := denied(Path(path.name))) is not None:
            return f"{path} ({bad})"
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except (FileNotFoundError, RuntimeError):
                return None
            if (bad := denied(target)) is not None:
                return f"{path} -> {target} ({bad})"
            ok = (any(within(target, a) for a in allowed) if declared_root
                  else trusted(target))
            if not ok:
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
            for child in path.iterdir():
                if (bad := visit(child)) is not None:
                    return bad
        except OSError as error:
            return f"{path} nao pode ser inspecionado ({error})"
        return None

    return visit(root, declared_root=root.is_symlink())


def _key(src: Path, name: str) -> str:
    """Chave derivada da ORIGEM: ~/.claude/plugins e ~/.codex/plugins tem o
    mesmo basename e colidiriam, com o segundo sobrescrevendo o primeiro."""
    return f"{hashlib.sha256(str(src).encode()).hexdigest()[:12]}-{name}"


def materialize(src: Path, stage: Path) -> str:
    """Copia um diretorio para o staging com os symlinks RESOLVIDOS.

    As skills do host apontam para fora do home (/usr/share/omarchy/...,
    ~/.agents/skills/...); sem resolver elas chegam como links quebrados.
    Links quebrados na origem sao ignorados em vez de abortar.
    """
    name = _key(src, src.name)
    dest = stage / name
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(directory, names):
        return [n for n in names
                if (Path(directory) / n).is_symlink()
                and not (Path(directory) / n).exists()]

    shutil.copytree(src, dest, symlinks=False, ignore=ignore)
    return name


def copy_file(src: Path, stage: Path) -> str:
    name = _key(src, src.name)
    shutil.copy2(src, stage / name)
    return name


def filter_claude_settings(src: Path, stage: Path) -> str:
    data = json.loads(src.read_text())
    for key in ("hooks", "statusLine"):
        data.pop(key, None)
    name = _key(src, "settings.json")
    (stage / name).write_text(json.dumps(data, indent=2) + "\n")
    return name


def filter_codex_config(src: Path, stage: Path) -> str:
    """Remove as tabelas [projects."..."], indexadas por caminho do HOST."""
    kept, skipping = [], False
    project_table = re.compile(r'^\s*\[projects\b')
    any_table = re.compile(r"^\s*\[")
    for line in src.read_text().splitlines(keepends=True):
        if project_table.match(line):
            skipping = True
            continue
        if skipping and any_table.match(line):
            skipping = False
        if not skipping:
            kept.append(line)
    name = _key(src, "config.toml")
    (stage / name).write_text("".join(kept))
    return name


FILTERS = {
    "claude-settings": filter_claude_settings,
    "codex-config": filter_codex_config,
}


def build_staging(manifest: Path, stage: Path, home: Path) -> int:
    stage.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    entries = tomllib.loads(Path(manifest).read_text()).get("entry", [])

    for entry in entries:
        raw_src, raw_dst = entry["src"], entry["dst"]
        src = Path(raw_src.replace("~", str(home), 1))
        dst = Path(raw_dst.replace("~", str(home), 1))

        if (bad := denied(Path(raw_src))) is not None:
            raise StagingError(f"{raw_src} contem caminho negado ({bad})")
        if not src.exists():
            continue
        if (bad := scan(src, home)) is not None:
            raise StagingError(f"{src} contem caminho negado ({bad})")
        if ".." in dst.parts or not dst.is_absolute() or denied(dst) or not any(
                dst == root or dst.is_relative_to(root)
                for root in _allowed_destination_roots(home)):
            raise StagingError(f"destino fora das raizes permitidas: {dst}")

        if (name := entry.get("filter")):
            staged = FILTERS[name](src, stage)
        elif src.is_dir():
            staged = materialize(src, stage)
        else:
            staged = copy_file(src, stage)
        lines.append(f"{staged}\t{dst}")

    (stage / "manifest.tsv").write_text("".join(f"{l}\n" for l in lines))
    return len(lines)
