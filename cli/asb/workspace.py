"""cli/asb/workspace.py — identidade do workspace, layout em disco e clone.

Duas regras carregam este modulo inteiro:

1. O nome do workspace e DETERMINISTICO. Com um nome irreproduzivel o destroy
   nao encontra o que criar removeu, e recursos vazam em silencio enquanto o
   Orca reporta sucesso. No v1 isso aconteceu com um nome derivado de $$.
2. O estado do workspace fica FORA do mount gravavel. O squid.conf renderizado
   dentro do mount permitiria ao agente editar a propria allowlist.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

UNSAFE = re.compile(r"[^a-zA-Z0-9._-]")


class WorkspaceError(Exception):
    pass


@dataclass(frozen=True)
class Layout:
    ws: str
    project: str
    mount: Path
    project_root: Path
    state: Path


def _sanitize(value: str) -> str:
    # Colapsar repeticoes: sem isso "uuid::/a/b" vira "uuid---a-b" com um traco
    # por caractere trocado, e nomes como "hexmed-stack--f05b729e" aparecem.
    return re.sub(r"-{2,}", "-", UNSAFE.sub("-", value)).strip("-")


def workspace_id(repo: Path, env: Mapping[str, str]) -> str:
    """Identidade do workspace, sempre reproduzivel a partir das entradas.

    O Orca passa ORCA_VM_INSTANCE_ID, unico POR WORKSPACE. Sem ele a derivacao
    cai no caminho do repositorio — e como o Orca executa os hooks a partir do
    checkout primario, todo workspace do mesmo projeto receberia o mesmo nome e
    o segundo mataria o primeiro.
    """
    given = env.get("ORCA_VM_INSTANCE_ID") or env.get("ORCA_WORKSPACE_ID") or ""
    if given.strip():
        return _sanitize(given)
    # Normalizar ANTES de derivar: uma barra final muda o hash, e create e
    # destroy divergiriam se o caminho chegasse de formas diferentes.
    text = str(Path(repo)).rstrip("/")
    base = _sanitize(Path(text).name)
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"{base}-{digest}"


def layout_for(repo: Path, ws: str, home: Path) -> Layout:
    """Onde tudo mora. `home` e o mesmo caminho no host e no container (D4)."""
    project = _sanitize(Path(str(repo).rstrip("/")).name)
    mount = Path(home) / "asb-agent" / project / ws
    return Layout(
        ws=ws,
        project=project,
        mount=mount,
        project_root=mount / project,
        # XDG_STATE_HOME por padrao. Nunca dentro do mount (o agente editaria a
        # propria allowlist) e nunca em /tmp (tmpfs: some no reboot, e um bind
        # mount apontando para caminho inexistente matou o squid do v1).
        state=Path(home) / ".local" / "state" / "agent-sandbox" / ws,
    )


def _git(*args: str, cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise WorkspaceError(
            f"git {' '.join(args)} falhou em {cwd}: {result.stderr.strip()}")


def prepare_clone(origin: Path, layout: Layout) -> None:
    """Cria o checkout do workspace, se ainda nao existir.

    Clone e nao worktree: uma worktree guarda seus metadados no .git do
    repositorio de ORIGEM, que nao e montado no container, e `git` la dentro
    falharia. Para origem local o git usa hardlinks, entao o clone e rapido e
    barato em disco.

    Idempotente. Um `up` sobre um workspace existente NUNCA reclona: isso
    apagaria commits que o agente ja fez e que ainda nao voltaram para o host.
    """
    origin = Path(origin)
    if not (origin / ".git").exists():
        raise WorkspaceError(f"origem nao e um repositorio git: {origin}")

    layout.mount.mkdir(parents=True, exist_ok=True)
    layout.state.mkdir(parents=True, exist_ok=True)
    layout.state.chmod(0o700)

    if (layout.project_root / ".git").is_dir():
        return
    if layout.project_root.exists():
        raise WorkspaceError(
            f"{layout.project_root} existe e nao e um repositorio git; "
            "remova-o a mao ou use outro workspace")
    _git("clone", str(origin), str(layout.project_root), cwd=layout.mount)


def remove_state(layout: Layout) -> None:
    """Chamado por `down`. NAO toca no mount: la vive o trabalho do agente."""
    shutil.rmtree(layout.state, ignore_errors=True)


def remove_workspace(layout: Layout) -> None:
    """Chamado por `purge`, so apos confirmacao explicita do operador."""
    remove_state(layout)
    shutil.rmtree(layout.mount, ignore_errors=True)
