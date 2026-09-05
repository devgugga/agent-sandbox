"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import podman
from .profile import Profile, load_profile
from .squid import render
from .staging import build_staging
from .workspace import Layout, layout_for, prepare_clone, remove_state

IMAGE = "agent-sandbox:latest"
PROXY_IMAGE = "agent-sandbox-proxy:latest"
PROXY_PORT = 3128
CONFIG = Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
SSH_KEY = CONFIG / "id_ed25519"


def names(ws: str) -> dict[str, str]:
    """Nomes derivados do workspace. Um lugar so: no v1 a derivacao duplicada
    entre create e destroy divergiu e vazou um pod a cada divergencia."""
    return {
        "net": f"asb-{ws}",
        "out": f"asb-{ws}-out",
        "agent": f"asb-{ws}-agent",
        "proxy": f"asb-{ws}-proxy",
    }


def ensure_ssh_key() -> Path:
    if SSH_KEY.exists():
        return SSH_KEY
    CONFIG.mkdir(parents=True, exist_ok=True)
    CONFIG.chmod(0o700)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(SSH_KEY),
                    "-C", "agent-sandbox"], check=True,
                   stdout=subprocess.DEVNULL)
    return SSH_KEY


def build_proxy(root: Path) -> None:
    if podman.exists("image", PROXY_IMAGE):
        return
    podman.run("build", "-t", PROXY_IMAGE,
               "-f", str(root / "image" / "Containerfile.proxy"), str(root))


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


def up(root: Path, ws: str, repo: Path) -> int:
    """Cria o workspace. Ou completa, ou nao deixa nada para tras.

    O rollback nao e zelo: um `up` que falha no meio e depois e repetido bate
    em "workspace ja existe" por causa dos proprios restos, e o operador fica
    preso sem entender por que.
    """
    try:
        return _up(root, ws, repo)
    except BaseException:
        # NAO remove ~/asb-agent/<proj>/<ws>: um `up` repetido sobre um
        # workspace existente nao pode apagar commits do agente.
        _sweep_containers(ws)
        for network in (names(ws)["net"], names(ws)["out"]):
            if podman.exists("network", network):
                podman.run("network", "rm", "-f", network, check=False)
        raise


def _sweep_containers(ws: str) -> None:
    """Remove todo container do workspace pelo PREFIXO, nunca por lista: um
    tipo de container acrescentado depois seria esquecido e vazaria."""
    for container in podman.out(
            "ps", "-a", "--filter", f"name=^asb-{ws}-",
            "--format", "{{.Names}}").splitlines():
        if container.strip():
            podman.run("rm", "-f", container.strip(), check=False)


def _up(root: Path, ws: str, repo: Path) -> int:
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    n = names(ws)
    if podman.exists("container", n["agent"]):
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    build_proxy(root)
    home = Path(os.path.expanduser("~"))
    profile = load_profile(repo)
    layout = layout_for(repo, ws, home)
    prepare_clone(repo, layout)

    conf = layout.state / "squid.conf"
    conf.write_text(render(profile,
                           root / "image" / "squid" / "allowlist-base.txt",
                           root / "image" / "squid" / "squid.conf.tmpl"))
    # o squid roda como uid 900 e precisa LER o arquivo montado
    conf.chmod(0o644)
    (layout.state / "origin").write_text(str(repo))

    # A rede interna nao tem rota default nem DNS externo, e o podman a
    # reconstroi em TODA partida do container. E por isso que nao existe mais
    # ordem de subida a respeitar: nao ha regra que possa faltar.
    if not podman.exists("network", n["net"]):
        podman.run("network", "create", "--internal", n["net"])
    if not podman.exists("network", n["out"]):
        podman.run("network", "create", n["out"])

    # O proxy tem perna nas duas redes: e o unico caminho para fora.
    podman.run(
        "run", "-d", "--name", n["proxy"], "--restart", "unless-stopped",
        "--network", f"{n['net']},{n['out']}", "--user", "900",
        "-v", f"{conf}:/etc/squid/squid.conf:ro,Z",
        PROXY_IMAGE, "squid", "-N", "-f", "/etc/squid/squid.conf")

    stage = layout.state / "staging"
    shutil.rmtree(stage, ignore_errors=True)
    staged = build_staging(root / "profiles" / "provision.toml", stage, home)
    print(f"configuracao: {staged} entrada(s)", file=sys.stderr)

    key = ensure_ssh_key()
    agent_args = [
        "run", "-d", "--name", n["agent"], "--restart", "unless-stopped",
        "--network", n["net"],
        "-p", "127.0.0.1::22",
        # Sem keep-id o uid 1000 do host mapeia para 0 aqui dentro, o
        # repositorio montado aparece como root e o agente nao consegue
        # escrever no proprio workspace.
        "--userns", "keep-id:uid=1000,gid=1000",
        "-e", f"ORCA_SSH_PUBLIC_KEY={key.with_suffix('.pub').read_text().strip()}",
        "-e", f"HTTPS_PROXY=http://{n['proxy']}:{PROXY_PORT}",
        "-e", f"HTTP_PROXY=http://{n['proxy']}:{PROXY_PORT}",
        "-e", "NO_PROXY=127.0.0.1,localhost",
        "-v", f"{layout.mount}:{layout.mount}:Z",
        "-v", f"{stage}:/run/asb-config:ro,Z",
        IMAGE,
    ]
    podman.run(*agent_args)
    # Idempotente e barato; chamar aqui evita que o operador precise lembrar.
    from . import install
    install.podman_restart()
    return emit(ws, layout)


def emit(ws: str, layout: Layout) -> int:
    """A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca
    inventada: o Orca guarda a que o create devolveu e disca nela para sempre."""
    n = names(ws)
    mapping = podman.out("port", n["agent"], "22")
    port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
    if not port:
        raise podman.PodmanError("nao foi possivel determinar a porta SSH")
    print(json.dumps({"workspace": ws, "port": int(port), "user":
                      getpass.getuser(),
                      "project_root": str(layout.project_root)}))
    return 0


def down(ws: str) -> int:
    """Remove containers e redes. NAO remove ~/asb-agent/<proj>/<ws>: ali vive
    o trabalho do agente, e apagar isso por engano seria irreversivel."""
    n = names(ws)
    home = Path(os.path.expanduser("~"))
    for container in (n["agent"], n["proxy"]):
        if podman.exists("container", container):
            podman.run("rm", "-f", container, check=False)
    for network in (n["net"], n["out"]):
        if podman.exists("network", network):
            podman.run("network", "rm", "-f", network, check=False)
    origin = _origin_of(ws, home)
    if origin is not None:
        remove_state(layout_for(origin, ws, home))
    return 0


def _origin_of(ws: str, home: Path) -> Path | None:
    """Le o caminho de origem gravado no estado. `down` precisa dele para achar
    o layout, e um workspace sem estado nao e erro: nao ha o que limpar."""
    marker = home / ".local" / "state" / "agent-sandbox" / ws / "origin"
    return Path(marker.read_text().strip()) if marker.is_file() else None


def _require_workspace(ws: str) -> tuple[dict[str, str], Path, Path]:
    n = names(ws)
    if not podman.exists("container", n["agent"]):
        raise podman.PodmanError(f"workspace inexistente: {ws} (use 'up')")
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(
            f"estado ausente para {ws}; recrie o workspace com 'up'")
    return n, home, origin


def suspend(ws: str) -> int:
    n, _, _ = _require_workspace(ws)
    for container in (n["agent"], n["proxy"]):
        if podman.exists("container", container):
            podman.run("stop", "-t", "5", container, check=False)
    return 0


def resume(root: Path, ws: str) -> int:
    """Religa o workspace.

    E `podman start`, e so. Nao ha ordem a respeitar: a rede interna nao pode
    "nao ter subido", entao o agente nunca ganha egresso indevido por partir
    primeiro. O proxy sobe antes por educacao — para o agente nao passar alguns
    segundos sem saida — nao por seguranca.
    """
    n, home, origin = _require_workspace(ws)
    for container in (n["proxy"], n["agent"]):
        if podman.exists("container", container):
            podman.run("start", container, check=False)
    return emit(ws, layout_for(origin, ws, home))


def pull(workspace: str) -> int:
    raise NotImplementedError("pull nao implementado ainda")


def purge(workspace: str, confirmed: bool = False) -> int:
    raise NotImplementedError("purge nao implementado ainda")


def login(root: Path) -> int:
    raise NotImplementedError("login nao implementado ainda")


def list_workspaces() -> int:
    home = Path(os.path.expanduser("~"))
    root = home / ".local" / "state" / "agent-sandbox"
    found = False
    for state in sorted(root.glob("*/origin")) if root.is_dir() else []:
        ws = state.parent.name
        agent = names(ws)["agent"]
        if not podman.exists("container", agent):
            status = "sem container"
        else:
            status = "rodando" if podman.running(agent) else "parado"
        print(f"{ws}\t{status}\t{state.read_text().strip()}")
        found = True
    if not found:
        print("nenhum workspace", file=sys.stderr)
    return 0
