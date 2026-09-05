"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from . import podman

IMAGE = "agent-sandbox:latest"


def build(root: Path) -> int:
    """Constroi a imagem base espelhando o usuario do host.

    id -un e $HOME entram como build args. Nunca literais: um nome assado
    quebraria a imagem no primeiro host diferente (spec §16).
    """
    user = getpass.getuser()
    home = os.path.expanduser("~")
    print(f"construindo {IMAGE} para {user} ({home})")
    # Contexto de build e a raiz do repo: o Containerfile copia cli/asb-guard
    # e image/*, e assim o guarda existe uma vez so.
    podman.run("build", "--build-arg", f"ASB_USER={user}",
               "--build-arg", f"ASB_HOME={home}",
               "-t", IMAGE, "-f", str(root / "image" / "Containerfile"),
               str(root))
    return 0


def up(root: Path, workspace: str, repo: Path) -> int:
    raise NotImplementedError("up nao implementado ainda")


def down(workspace: str) -> int:
    raise NotImplementedError("down nao implementado ainda")


def suspend(workspace: str) -> int:
    raise NotImplementedError("suspend nao implementado ainda")


def resume(root: Path, workspace: str) -> int:
    raise NotImplementedError("resume nao implementado ainda")


def pull(workspace: str) -> int:
    raise NotImplementedError("pull nao implementado ainda")


def purge(workspace: str, confirmed: bool = False) -> int:
    raise NotImplementedError("purge nao implementado ainda")


def login(root: Path) -> int:
    raise NotImplementedError("login nao implementado ainda")


def list_workspaces() -> int:
    raise NotImplementedError("list nao implementado ainda")
