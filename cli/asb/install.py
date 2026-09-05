"""cli/asb/install.py — o que o sandbox instala no host.

Regra da §16: tudo aqui e idempotente, reexecutavel, e NAO grava o caminho
absoluto deste checkout em arquivo de sistema algum. No v1 o ExecStart da
unidade systemd tinha o caminho assado, e mover a pasta quebrava a restauracao
no boot em silencio.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def podman_restart() -> int:
    """Habilita a unidade que o proprio podman ja instala.

    `podman start --all --filter should-start-on-boot=true`, puxada por
    default.target e ordenada apos network-online.target. Substitui inteiros o
    restore-all do v1, a espera por rota/DNS do host, a unidade customizada e o
    codigo de saida 2 para pods legados — e, por nao ser nossa, nao carrega
    caminho nenhum deste checkout.

    Sem linger de proposito: o Orca so roda apos o login, entao uma unidade que
    parte no login e cedo o bastante.
    """
    unit = Path("/usr/lib/systemd/user/podman-restart.service")
    if not unit.is_file():
        print("podman-restart.service nao encontrado; sem restauracao "
              "automatica no boot. Use 'asb-agent resume' apos religar.",
              file=sys.stderr)
        return 1
    subprocess.run(["systemctl", "--user", "enable", "podman-restart.service"],
                   check=True)
    print("restauracao no boot habilitada (podman-restart.service)",
          file=sys.stderr)
    return 0


def guards(root: Path) -> int:
    raise NotImplementedError("install-guards nao implementado ainda")


def broker(root: Path) -> int:
    raise NotImplementedError("install-broker nao implementado ainda")
