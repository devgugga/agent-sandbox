"""cli/asb/install.py — o que o sandbox instala no host.

Regra da §16: tudo aqui e idempotente, reexecutavel, e NAO grava o caminho
absoluto deste checkout em arquivo de sistema algum. No v1 o ExecStart da
unidade systemd tinha o caminho assado, e mover a pasta quebrava a restauracao
no boot em silencio.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

BROKER_SCRIPT = Path("/usr/local/lib/asb-docker-broker.py")
BROKER_UNIT = Path("/etc/systemd/system/asb-docker-broker.service")
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
PODMAN_RESTART_UNIT = Path("/usr/lib/systemd/user/podman-restart.service")


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
    if not PODMAN_RESTART_UNIT.is_file():
        print("podman-restart.service nao encontrado; sem restauracao "
              "automatica no boot. Use 'asb-agent resume' apos religar.",
              file=sys.stderr)
        return 1

    podman_bin = shutil.which("podman")
    if not podman_bin:
        print("podman nao encontrado no PATH", file=sys.stderr)
        return 1

    true_bin = shutil.which("true")
    if not true_bin:
        print("true nao encontrado no PATH", file=sys.stderr)
        return 1

    dropin = (
        Path.home()
        / ".config"
        / "systemd"
        / "user"
        / "podman-restart.service.d"
        / "agent-sandbox.conf"
    )
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text(
        f"[Service]\nExecStartPre={podman_bin} unshare --rootless-netns {true_bin}\n"
    )

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "podman-restart.service"],
                   check=True)
    print("restauracao no boot habilitada (podman-restart.service)",
          file=sys.stderr)
    return 0


def _link(link: Path, dest: Path) -> None:
    """Symlink para o checkout, nunca copia: uma copia envelhece em silencio e
    o agente passa a se comportar diferente do que este repositorio diz."""
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(dest)
    print(f"instalado: {link}", file=sys.stderr)


def guards(root: Path) -> int:
    """Instala os nomes que vao no campo Command do Orca, e o proprio CLI."""
    target = Path.home() / ".local" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    for agent in ("claude", "codex", "agy"):
        _link(target / f"asb-{agent}", root / "cli" / "asb-guard")
    # Sem o CLI no PATH o operador so consegue opera-lo de dentro do checkout.
    # O entrypoint ja resolve o proprio caminho com Path(__file__).resolve(),
    # que segue o symlink — o link era a unica peca faltando.
    _link(target / "asb-agent", root / "cli" / "asb-agent")
    print("Em Orca -> Settings -> Agents, troque o campo Command:\n"
          "  claude -> asb-claude | codex -> asb-codex | agy -> asb-agy\n"
          "asb-agent passa a rodar de qualquer diretorio.",
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


def install_runtime(
    root: Path,
    revision: str,
    target_base: Path | None = None,
) -> Path:
    """Instala o runtime versionado em ~/.local/lib/agent-sandbox/runtime/<revisao>/.

    Garante cópia independente (sem symlinks para o checkout), idempotência
    atômica e escrita dos scripts helper (launcher e runtime_check).
    """
    if not revision or not isinstance(revision, str):
        raise ValueError("Revisao nao pode ser vazia")
    if any(c in revision for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
        raise ValueError(f"Revisao invalida ou insegura: {revision!r}")

    base = (
        target_base
        if target_base is not None
        else (Path.home() / ".local" / "lib" / "agent-sandbox" / "runtime")
    )
    dest = base / revision
    base.mkdir(parents=True, exist_ok=True)

    staging = base / f".staging-{revision}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        # Copiar pacote asb do checkout para staging/asb
        src_asb = root / "cli" / "asb"
        if not src_asb.is_dir():
            raise FileNotFoundError(f"Pacote asb nao encontrado em {src_asb}")

        dst_asb = staging / "asb"
        shutil.copytree(
            src_asb,
            dst_asb,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            symlinks=False,
        )

        # Gerar launcher.sh executável
        launcher_path = staging / "launcher.sh"
        launcher_content = (
            "#!/bin/sh\n"
            "set -eu\n"
            "podman_bin=\"$(command -v podman || echo /usr/bin/podman)\"\n"
            "container=\"\"\n"
            "for arg in \"$@\"; do\n"
            "    case \"$arg\" in\n"
            "        --attach|--sig-proxy=false|--sig-proxy=*|start)\n"
            "            ;;\n"
            "        *)\n"
            "            container=\"$arg\"\n"
            "            ;;\n"
            "    esac\n"
            "done\n"
            "if [ -z \"$container\" ]; then\n"
            "    echo \"asb-launcher: missing container name\" >&2\n"
            "    exit 2\n"
            "fi\n"
            "status=$(\"$podman_bin\" inspect \"$container\" --format '{{.State.Status}}' 2>/dev/null || true)\n"
            "if [ \"$status\" = \"running\" ]; then\n"
            "    exec \"$podman_bin\" attach --sig-proxy=false \"$container\"\n"
            "else\n"
            "    exec \"$podman_bin\" start --attach --sig-proxy=false \"$container\"\n"
            "fi\n"
        )
        launcher_path.write_text(launcher_content, encoding="utf-8")
        launcher_path.chmod(0o755)

        # Gerar runtime_check.py executável
        check_path = staging / "runtime_check.py"
        check_content = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "runtime_dir = Path(__file__).resolve().parent\n"
            "if str(runtime_dir) not in sys.path:\n"
            "    sys.path.insert(0, str(runtime_dir))\n"
            "\n"
            "from asb.runtime_check import main\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    sys.exit(main())\n"
        )
        check_path.write_text(check_content, encoding="utf-8")
        check_path.chmod(0o755)

        # Troca atômica de staging para dest
        if dest.exists():
            backup = base / f".old-{revision}-{os.getpid()}"
            dest.rename(backup)
            staging.rename(dest)
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.rename(dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return dest

