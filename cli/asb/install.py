"""cli/asb/install.py — o que o sandbox instala no host.

Regra da §16: tudo aqui e idempotente, reexecutavel, e NAO grava o caminho
absoluto deste checkout em arquivo de sistema algum. No v1 o ExecStart da
unidade systemd tinha o caminho assado, e mover a pasta quebrava a restauracao
no boot em silencio.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BROKER_SCRIPT = Path("/usr/local/lib/asb-docker-broker.py")
BROKER_UNIT = Path("/etc/systemd/system/asb-docker-broker.service")
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")


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
    """Instala os nomes que vao no campo Command do Orca.

    Symlinks para o checkout, nunca copias: uma copia envelhece em silencio e
    o agente passa a se comportar diferente do que este repositorio diz.
    """
    target = Path.home() / ".local" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for agent in ("claude", "codex", "agy"):
        link = target / f"asb-{agent}"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(root / "cli" / "asb-guard")
        print(f"instalado: {link}", file=sys.stderr)
    print("Em Orca -> Settings -> Agents, troque o campo Command:\n"
          "  claude -> asb-claude | codex -> asb-codex | agy -> asb-agy",
          file=sys.stderr)
    return 0


def broker(root: Path) -> int:
    """Instala o broker so-leitura. Requer sudo, uma vez.

    O script e COPIADO para /usr/local/lib: a unidade nao pode apontar para
    este checkout, senao mover a pasta quebraria o servico em silencio — o
    mesmo erro que o v1 cometeu com o ExecStart do restore (spec §16.1).
    """
    source = root / "broker" / "asb-docker-broker.py"
    docker_sock = next((s for s in DOCKER_SOCKETS if Path(s).exists()), None)
    if docker_sock is None:
        print("socket do Docker nao encontrado; nada a instalar. O eixo "
              "host_api fica indisponivel; os outros dois seguem normais.",
              file=sys.stderr)
        return 1

    unit = (root / "broker" / "asb-docker-broker.service.tmpl").read_text()
    unit = (unit.replace("__PYTHON__", sys.executable)
                .replace("__SCRIPT__", str(BROKER_SCRIPT))
                .replace("__DOCKER_SOCK__", docker_sock)
                .replace("__UID__", str(os.getuid())))

    print(f"instalando o broker (socket real: {docker_sock}).", file=sys.stderr)
    print("Isso concede LEITURA de Docker sem senha ao seu usuario: ps, logs, "
          "inspect. Mutacao recebe 403 e nao e configuravel.", file=sys.stderr)
    subprocess.run(["sudo", "install", "-m", "0755", str(source),
                    str(BROKER_SCRIPT)], check=True)
    subprocess.run(["sudo", "tee", str(BROKER_UNIT)], input=unit, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now",
                    "asb-docker-broker.service"], check=True)
    print("broker instalado. Habilite por projeto com [docker] host_api = "
          '"read" no .agent-sandbox.toml.', file=sys.stderr)
    return 0
