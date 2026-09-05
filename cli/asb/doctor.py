"""cli/asb/doctor.py — diagnostica o ambiente e nomeia a correcao.

Regra: toda linha de falha diz o COMANDO exato a executar. "Algo esta errado"
nao ajuda ninguem as 2h da manha, e a §16.1 exige que uma maquina nova seja
recuperavel sem adivinhacao.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import podman
from .lifecycle import CREDENTIALS_VOLUME, IMAGE, names


def _line(ok: bool, label: str, fix: str = "") -> bool:
    mark = "ok  " if ok else "FALTA"
    print(f"  {mark} {label}" + ("" if ok else f"  ->  {fix}"))
    return ok


def doctor(root: Path) -> int:
    print("agent-sandbox doctor")
    healthy = True

    healthy &= _line(shutil.which("podman") is not None, "podman instalado",
                     "instale o podman (>= 4.0)")
    if shutil.which("podman"):
        version = podman.out("--version").split()[-1]
        major = int(version.split(".")[0])
        healthy &= _line(major >= 4, f"podman {version} (>= 4.0)",
                         "atualize: --internal e resolucao por nome exigem 4+")

    healthy &= _line(sys.version_info >= (3, 11),
                     f"python {sys.version.split()[0]} (>= 3.11)",
                     "tomllib e stdlib so a partir do 3.11")
    healthy &= _line(shutil.which("git") is not None, "git instalado",
                     "instale o git")

    healthy &= _line(podman.exists("image", IMAGE), f"imagem {IMAGE}",
                     "asb-agent build")
    healthy &= _line(podman.exists("volume", CREDENTIALS_VOLUME),
                     f"volume {CREDENTIALS_VOLUME}", "asb-agent login")

    enabled = subprocess.run(
        ["systemctl", "--user", "is-enabled", "podman-restart.service"],
        capture_output=True, text=True).stdout.strip()
    healthy &= _line(enabled == "enabled",
                     "podman-restart.service habilitado (restauracao no boot)",
                     "systemctl --user enable podman-restart.service")

    guards = Path.home() / ".local" / "bin"
    for agent in ("claude", "codex", "agy"):
        link = guards / f"asb-{agent}"
        expected = root / "cli" / "asb-guard"
        # Checkout movido: o link aponta para um caminho que nao existe mais.
        # E o modo de falha da §16.1, e aqui ele e visivel em vez de silencioso.
        healthy &= _line(link.is_symlink() and link.resolve() == expected,
                         f"guarda asb-{agent} aponta para este checkout",
                         "asb-agent install-guards")

    broker = Path("/run/asb-docker/docker.sock")
    _line(broker.is_socket(),
          'broker do Docker (opcional; so para host_api = "read")',
          "asb-agent install-broker")

    print("\nworkspaces:")
    for state in sorted((Path.home() / ".local" / "state" /
                         "agent-sandbox").glob("*/origin")):
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            status = "SEM CONTAINER  ->  asb-agent up"
        elif podman.running(agent):
            status = "rodando"
        else:
            status = f"parado  ->  asb-agent resume --workspace {ws}"
        print(f"  {ws}: {status}")

    return 0 if healthy else 1
