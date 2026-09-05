"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import base64
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
from .workspace import (
    Layout,
    layout_for,
    prepare_clone,
    remove_state,
    remove_workspace,
)

IMAGE = "agent-sandbox:latest"
PROXY_IMAGE = "agent-sandbox-proxy:latest"
PROXY_PORT = 3128
CONFIG = Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
SSH_KEY = CONFIG / "id_ed25519"
CREDENTIALS_VOLUME = "asb-credentials"
KEYRING_PASS = CONFIG / "keyring.pass"


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


def ensure_credentials_volume() -> str:
    if not podman.exists("volume", CREDENTIALS_VOLUME):
        podman.run("volume", "create", CREDENTIALS_VOLUME)
    return CREDENTIALS_VOLUME


def ensure_keyring_pass() -> Path:
    """A passphrase do keyring vive SO no host. Uma copia do volume levada para
    outra maquina carrega um keyring cifrado que nao abre — verificado no v1:
    com a passphrase errada o agy falha enquanto o claude continua respondendo,
    provando que a falha e do keyring e nao geral."""
    if KEYRING_PASS.exists():
        return KEYRING_PASS
    CONFIG.mkdir(parents=True, exist_ok=True)
    CONFIG.chmod(0o700)
    KEYRING_PASS.write_text(
        base64.b64encode(os.urandom(32)).decode().strip())
    KEYRING_PASS.chmod(0o600)
    return KEYRING_PASS


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
    """Remove todo container do workspace pelo LABEL, nunca por prefixo solto:
    casar prefixo sem delimitador casava workspaces irmaos (ex: asb-demo- casava asb-demo-2-)."""
    found: set[str] = set()
    for container in podman.out(
            "ps", "-a", "--filter", f"label=asb.workspace={ws}",
            "--format", "{{.Names}}").splitlines():
        c = container.strip()
        if c:
            found.add(c)
    n = names(ws)
    for c in (n["agent"], n["proxy"], f"{n['net']}-fwd", f"{n['net']}-docker"):
        if podman.exists("container", c):
            found.add(c)
    for container in sorted(found):
        podman.run("rm", "-f", container, check=False)


def start_services(ws: str, profile: Profile) -> None:
    n = names(ws)
    for service in profile.services:
        container = f"asb-{ws}-svc-{service.name}"
        env = []
        for key, value in service.env.items():
            env += ["-e", f"{key}={value}"]
        # --user 0: imagens sem diretiva USER (postgres, por exemplo) sao
        # resolvidas por keep-id para o uid mapeado do host, e o initdb falha
        # em ajustar permissoes dos diretorios da propria imagem.
        podman.run("run", "-d", "--name", container,
                   "--label", f"asb.workspace={ws}",
                   "--restart", "unless-stopped",
                   "--network", n["net"], "--user", "0",
                   *env, service.image)


def start_forwarder(ws: str, profile: Profile) -> None:
    """Encaminha SO as portas declaradas para o host.

    Nunca faixas privadas: o host participa de uma rede Tailscale, e liberar
    RFC1918 ou CGNAT entregaria a tailnet inteira ao agente.

    O encaminhador tem perna na rede externa porque so assim alcanca o gateway
    do host. Ele nao e um proxy de uso geral: roda socat com destinos fixos, e
    o agente so alcanca as portas listadas.
    """
    if not profile.host_ports:
        return
    n = names(ws)
    forwarder = f"{n['net']}-fwd"
    script = " ".join(
        f"socat TCP-LISTEN:{port},fork,reuseaddr "
        f"TCP:host.containers.internal:{port} &" for port in profile.host_ports)
    podman.run("run", "-d", "--name", forwarder,
               "--label", f"asb.workspace={ws}",
               "--restart", "unless-stopped",
               "--network", f"{n['net']},{n['out']}", "--user", "900",
               "--entrypoint", "sh", PROXY_IMAGE,
               "-c", f"trap 'exit 0' TERM; {script} wait")


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
        "run", "-d", "--name", n["proxy"],
        "--label", f"asb.workspace={ws}",
        "--restart", "unless-stopped",
        "--network", f"{n['net']},{n['out']}", "--user", "900",
        "-v", f"{conf}:/etc/squid/squid.conf:ro,Z",
        PROXY_IMAGE, "squid", "-N", "-f", "/etc/squid/squid.conf")

    start_services(ws, profile)
    start_forwarder(ws, profile)

    if profile.host_api == "read":
        broker_sock = Path("/run/asb-docker/docker.sock")
        if not broker_sock.exists():
            raise podman.PodmanError(
                'host_api = "read" pede o broker; execute '
                "'asb-agent install-broker' (usa sudo, uma vez)")
        # Container proprio, SEM rede externa: quem fala com o socket do
        # Docker nao ganha egresso de tabela junto.
        podman.run(
            "run", "-d", "--name", f"{n['net']}-docker",
            "--label", f"asb.workspace={ws}",
            "--restart", "unless-stopped",
            "--network", n["net"], "--user", "900",
            "-v", f"{broker_sock}:/var/run/docker.sock:Z",
            "--entrypoint", "sh", PROXY_IMAGE, "-c",
            "socat TCP-LISTEN:2375,fork,reuseaddr "
            "UNIX-CONNECT:/var/run/docker.sock")

    stage = layout.state / "staging"
    shutil.rmtree(stage, ignore_errors=True)
    staged = build_staging(root / "profiles" / "provision.toml", stage, home)
    print(f"configuracao: {staged} entrada(s)", file=sys.stderr)

    key = ensure_ssh_key()
    agent_args = [
        "run", "-d", "--name", n["agent"],
        "--label", f"asb.workspace={ws}",
        "--restart", "unless-stopped",
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
        "-e", f"ASB_KEYRING_PASS={ensure_keyring_pass().read_text().strip()}",
        "-v", f"{ensure_credentials_volume()}:/run/asb-credentials:Z",
        *(["-e", f"DOCKER_HOST=tcp://{n['net']}-docker:2375"]
          if profile.host_api == "read" else []),
        "-e", "ASB_HOST_PORTS=" + ",".join(str(p) for p in profile.host_ports),
        "-e", f"ASB_WORKSPACE={ws}",
        IMAGE,
    ]
    if profile.container_mode == "nested":
        # /dev/fuse para o fuse-overlayfs, /dev/net/tun para o netavark/slirp;
        # label=disable porque o SELinux do host nao rotula o que o podman de dentro cria.
        # unmask=/proc/* permite o mount proc do crun sem expor /sys/firmware.
        volume = f"{n['net']}-containers"
        if not podman.exists("volume", volume):
            podman.run("volume", "create", volume)
        agent_args[-1:-1] = [
            "--device", "/dev/fuse",
            "--device", "/dev/net/tun",
            "--security-opt", "label=disable",
            "--security-opt", "unmask=/proc/*",
            # Armazenamento das imagens aninhadas fora da camada gravavel: um
            # `down` seguido de `up` nao rebaixa tudo de novo.
            "-v", f"{volume}:{home}/.local/share/containers:Z",
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
    _sweep_containers(ws)
    for network in (n["net"], n["out"]):
        if podman.exists("network", network):
            podman.run("network", "rm", "-f", network, check=False)
    volume = f"asb-{ws}-containers"
    if podman.exists("volume", volume):
        podman.run("volume", "rm", "-f", volume, check=False)
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
    containers = podman.out(
        "ps", "--filter", f"label=asb.workspace={ws}",
        "--format", "{{.Names}}").splitlines()
    found = {c.strip() for c in containers if c.strip()}
    found.update({n["agent"], n["proxy"]})
    for container in sorted(found):
        if podman.exists("container", container) and podman.running(container):
            podman.run("stop", "-t", "5", container, check=False)
    return 0


def resume(root: Path, ws: str) -> int:
    """Religa o workspace.

    E `podman start`, e so. Nao ha ordem a respeitar por seguranca: a rede interna
    nao pode "nao ter subido", entao o agente nunca ganha egresso indevido por
    partir primeiro. O proxy sobe antes por educacao — para o agente nao passar alguns
    segundos sem saida. Todos os outros containers do workspace (servicos, forwarder,
    broker) tambem sao religados.
    """
    n, home, origin = _require_workspace(ws)
    if podman.exists("container", n["proxy"]):
        podman.run("start", n["proxy"], check=False)
    containers = podman.out(
        "ps", "-a", "--filter", f"label=asb.workspace={ws}",
        "--format", "{{.Names}}").splitlines()
    found = {c.strip() for c in containers if c.strip()}
    found.update({n["agent"]})
    for container in sorted(found):
        if container != n["proxy"] and podman.exists("container", container):
            podman.run("start", container, check=False)
    return emit(ws, layout_for(origin, ws, home))


def pull(ws: str) -> int:
    """Traz o trabalho do workspace para o checkout primario, SEM merge.

    O operador testa e faz o push. Se precisar de ajuste, o workspace continua
    vivo, o agente commita mais, e um novo pull traz a diferenca — e por isso
    que o merge nao acontece aqui.
    """
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    layout = layout_for(origin, ws, home)
    branch = subprocess.run(
        ["git", "-C", str(layout.project_root), "rev-parse",
         "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-C", str(origin), "fetch",
                    str(layout.project_root), f"{branch}:refs/asb/{ws}/{branch}"],
                   check=True)
    print(f"buscado em {origin}: refs/asb/{ws}/{branch}\n"
          f"  revise:  git -C {origin} log refs/asb/{ws}/{branch}\n"
          f"  integre: git -C {origin} merge refs/asb/{ws}/{branch}",
          file=sys.stderr)
    return 0


def purge(ws: str, confirmed: bool) -> int:
    """Remove tambem os ARQUIVOS do workspace. Irreversivel, logo explicito."""
    home = Path(os.path.expanduser("~"))
    origin = _origin_of(ws, home)
    if origin is None:
        raise podman.PodmanError(f"workspace desconhecido: {ws}")
    layout = layout_for(origin, ws, home)
    if not confirmed:
        raise podman.PodmanError(
            f"purge apaga {layout.mount}, incluindo commits que ainda nao "
            f"voltaram para o host. Rode 'asb-agent pull --workspace {ws}' "
            "antes, e repita com --yes se for isso mesmo.")
    down(ws)
    remove_workspace(layout)
    print(f"removido: {layout.mount}", file=sys.stderr)
    return 0


def login(root: Path) -> int:
    """Autentica os tres agentes UMA VEZ, num container fora da rede interna.

    Fora da rede interna de proposito: o login por device-auth precisa de
    egresso direto, e nao ha proxy algum neste caminho.
    """
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    ensure_credentials_volume()
    passphrase = ensure_keyring_pass().read_text().strip()
    name = "asb-login"
    if podman.exists("container", name):
        podman.run("rm", "-f", name, check=False)

    # Com o ENTRYPOINT REAL, nao --entrypoint sleep: e o entrypoint que sobe o
    # D-Bus, destrava o keyring e popula /etc/profile.d. Com sleep nada disso
    # acontece e o agy guarda a credencial em ARQUIVO TEXTO em silencio.
    podman.run(
        "run", "-d", "--name", name,
        "--userns", "keep-id:uid=1000,gid=1000",
        "-e", f"ASB_KEYRING_PASS={passphrase}",
        "-v", f"{CREDENTIALS_VOLUME}:/run/asb-credentials:Z",
        IMAGE)
    try:
        print("\nEntre em cada agente. Use SEMPRE fluxos de device-auth: o "
              "OAuth padrao abre um servidor de callback numa porta do "
              "container que o navegador do host nao alcanca, e trava.\n",
              file=sys.stderr)
        for label, command in (
                ("Claude Code", "claude /login"),
                ("Codex", "codex login --device-auth"),
                # `agy` nao tem subcomando `login`: o binario nu abre a TUI,
                # que autentica no primeiro uso. `agy login` falha com
                # "unexpected argument".
                ("Antigravity", "agy")):
            print(f"--- {label} ---", file=sys.stderr)
            # `bash -lc` nao e decoracao: sem shell de login o agy nao esta no
            # PATH e DBUS_SESSION_BUS_ADDRESS esta ausente, que e exatamente
            # como a credencial acaba em texto claro em vez do keyring.
            subprocess.run([podman.require_binary(), "exec", "-it",
                            "-u", "1000", name, "bash", "-lc", command])

        # Verificar por CODIGO DE SAIDA, nunca por grep de "logged in": essa
        # string casa tambem com "not logged in".
        checks = (("Codex", "codex login status"),
                  ("Claude Code", "claude -p ping < /dev/null"),
                  ("Antigravity", "asb-agy --version"))
        failed = []
        for label, command in checks:
            result = subprocess.run(
                [podman.require_binary(), "exec", "-u", "1000", name,
                 "timeout", "120", "bash", "-lc", command],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state = "ok" if result.returncode == 0 else "FALHOU"
            print(f"  {label}: {state}", file=sys.stderr)
            if result.returncode != 0:
                failed.append(label)
        if failed:
            raise podman.PodmanError(
                "nao autenticado: " + ", ".join(failed))
        print("credenciais gravadas no volume asb-credentials", file=sys.stderr)
        return 0
    finally:
        podman.run("rm", "-f", name, check=False)


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
