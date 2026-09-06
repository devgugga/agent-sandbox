"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import base64
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
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
CREDENTIALS_VOLUME = os.environ.get("ASB_CREDENTIALS_VOLUME", "asb-credentials")
TOOLCACHE_VOLUME = "asb-toolcache"
KEYRING_CONTAINER = "asb-keyring"
KEYRING_RUNTIME_VOLUME = "asb-keyring-runtime"
KEYRING_BUS = "/run/asb-keyring/bus"
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
    vol = os.environ.get("ASB_CREDENTIALS_VOLUME", CREDENTIALS_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


def ensure_toolcache_volume() -> str:
    if not podman.exists("volume", TOOLCACHE_VOLUME):
        podman.run("volume", "create", TOOLCACHE_VOLUME)
    return TOOLCACHE_VOLUME


def ensure_keyring_pass() -> Path:
    """A passphrase do keyring vive SO no host. Uma copia do volume levada para
    outra maquina carrega um keyring cifrado que nao abre — verificado no v1:
    com a passphrase errada o agy falha enquanto o claude continua respondendo,
    provando que a falha e do keyring e nao geral."""
    pass_file = Path(os.environ["ASB_KEYRING_PASS_FILE"]) if "ASB_KEYRING_PASS_FILE" in os.environ else KEYRING_PASS
    if pass_file.exists():
        return pass_file
    parent_existed = pass_file.parent.exists()
    pass_file.parent.mkdir(parents=True, exist_ok=True)
    if pass_file.parent == CONFIG or not parent_existed:
        pass_file.parent.chmod(0o700)
    pass_file.write_text(
        base64.b64encode(os.urandom(32)).decode().strip())
    pass_file.chmod(0o600)
    return pass_file


def ensure_keyring_runtime_volume() -> str:
    vol = os.environ.get("ASB_KEYRING_RUNTIME_VOLUME", KEYRING_RUNTIME_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


def _wait_for_keyring_readiness(container: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        if podman.running(container):
            sock_check = podman.run(
                "exec", "-u", "1000", container,
                "test", "-S", KEYRING_BUS,
                check=False,
            )
            sock_rc = getattr(sock_check, "returncode", 1) if sock_check is not None else 1
            if sock_rc == 0:
                secrets_check = podman.run(
                    "exec", "-u", "1000", container,
                    "dbus-send", "--session",
                    "--dest=org.freedesktop.DBus",
                    "--type=method_call",
                    "--print-reply",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus.GetNameOwner",
                    "string:org.freedesktop.secrets",
                    check=False,
                )
                secrets_rc = getattr(secrets_check, "returncode", 1) if secrets_check is not None else 1
                if secrets_rc == 0:
                    return
        time.sleep(0.05)
    raise podman.PodmanError(
        f"servico de keyring '{container}' nao respondeu dentro de {timeout}s; "
        "execute 'asb-agent login' para inicializar autenticacao"
    )


def ensure_keyring_service(timeout: float = 5.0) -> str:
    """Garante o servico global de keyring (singleton).

    Cria e/ou inicia o container asb-keyring com rede isolada (--network none),
    reinicializacao automatica (--restart unless-stopped), permissao uid 1000,
    e volumes compartilhados de runtime e credenciais.
    """
    container = os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    if podman.exists("container", container):
        schema = podman.out(
            "container", "inspect", container,
            "--format", '{{index .Config.Labels "asb.keyring.schema"}}',
        ).strip()
        if schema != "1":
            raise podman.PodmanError(
                f"container '{container}' possui schema incompativel ({schema or 'desconhecido'}). "
                f"Remova-o com 'podman rm -f {container}' e recrie workspaces com 'asb-agent down' e 'asb-agent up'."
            )
        if not podman.running(container):
            podman.run("start", container)
        _wait_for_keyring_readiness(container, timeout=timeout)
        return container

    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")

    pass_file = ensure_keyring_pass()
    cred_vol = ensure_credentials_volume()
    run_vol = ensure_keyring_runtime_volume()

    podman.run(
        "run", "-d", "--name", container,
        "--label", "asb.keyring.schema=1",
        "--network", "none",
        "--restart", "unless-stopped",
        "--user", "1000",
        "--userns", "keep-id:uid=1000,gid=1000",
        "-v", f"{pass_file}:/run/asb-keyring-pass:ro,Z",
        "-v", f"{cred_vol}:/run/asb-credentials:z",
        "-v", f"{run_vol}:/run/asb-keyring:z",
        "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={KEYRING_BUS}",
        "--entrypoint", "/usr/local/bin/start-keyring.sh",
        IMAGE,
    )
    _wait_for_keyring_readiness(container, timeout=timeout)
    return container


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


PRUNED_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    ".next",
    "__pycache__",
}


def discover_mise_dirs(root: Path) -> list[Path]:
    """Encontra todos os diretorios que contem mise.toml, podando pastas irrelevantes."""
    if not root.exists():
        return []
    dirs: list[Path] = []
    if (root / "mise.toml").is_file():
        dirs.append(root)
    for item in root.rglob("mise.toml"):
        p = item.parent
        if p == root:
            continue
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(part in PRUNED_DIRS for part in rel_parts):
            continue
        dirs.append(p)
    dirs.sort(key=lambda d: (0 if d == root else 1, len(d.parts), str(d)))
    return dirs


def _up(root: Path, ws: str, repo: Path) -> int:
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    n = names(ws)
    if podman.exists("container", n["agent"]):
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    podman.ensure_rootless_netns()
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
    published = []
    for host_p, cont_p in profile.publish_ports:
        published.extend(["-p", f"127.0.0.1:{host_p}:{cont_p}"])

    ensure_keyring_service()

    agent_args = [
        "run", "-d", "--name", n["agent"],
        "--label", f"asb.workspace={ws}",
        "--restart", "unless-stopped",
        "--network", n["net"],
        "-p", "127.0.0.1::22",
        *published,
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
        "-v", f"{ensure_keyring_runtime_volume()}:/run/asb-keyring:ro,z",
        "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={KEYRING_BUS}",
        "-v", f"{ensure_credentials_volume()}:/run/asb-credentials:z",
        "-v", f"{ensure_toolcache_volume()}:/run/asb-toolcache:Z",
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
        # net.ipv4.ip_unprivileged_port_start=0 permite que containers aninhados
        # (ex: Traefik do BlackICE em 80:80) escutem em portas privilegiadas (< 1024).
        volume = f"{n['net']}-containers"
        if not podman.exists("volume", volume):
            podman.run("volume", "create", volume)
        agent_args[-1:-1] = [
            "--device", "/dev/fuse",
            "--device", "/dev/net/tun",
            "--security-opt", "label=disable",
            "--security-opt", "unmask=/proc/*",
            "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
            # Armazenamento das imagens aninhadas fora da camada gravavel: um
            # `down` seguido de `up` nao rebaixa tudo de novo.
            "-v", f"{volume}:{home}/.local/share/containers:Z",
        ]
    podman.run(*agent_args)
    # Idempotente e barato; chamar aqui evita que o operador precise lembrar.
    from . import install
    install.podman_restart()

    mise_errors: list[tuple[Path, int, str]] = []
    for d in discover_mise_dirs(layout.project_root):
        print(f"  info executando mise install em {d.name}...", file=sys.stderr)
        res = podman.run("exec", "-u", "1000", "-w", str(d),
                         n["agent"], "mise", "install", "-y", check=False)
        rc = getattr(res, "returncode", 0)
        if rc == 0:
            print(f"  ok   ferramentas mise instaladas ({d.name})", file=sys.stderr)
        else:
            stderr = getattr(res, "stderr", "") or ""
            print(f"  erro falha ao executar mise install em {d.name} (código {rc})",
                  file=sys.stderr)
            if stderr:
                print(stderr.strip(), file=sys.stderr)
            mise_errors.append((d, rc, stderr))

    if mise_errors:
        failed_names = ", ".join(d.name for d, _, _ in mise_errors)
        print(f"\nerro: falha na instalacao de ferramentas mise em: {failed_names}",
              file=sys.stderr)
        print("workspace mantido no ar; corrija a allowlist ou mise.toml e "
              "execute 'asb-agent up' novamente.", file=sys.stderr)
        return 1

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
    podman.ensure_rootless_netns()
    ensure_keyring_service()
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


def reload_allowlist(root: Path, ws: str) -> int:
    """Recarrega a allowlist do proxy sem tocar no container do agente.

    Preserva a porta SSH publicada (evita desconexao de sessoes do Orca).
    Regenera squid.conf a partir do .agent-sandbox.toml e reinicia o proxy.
    """
    n, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)
    # SEMPRE o perfil do checkout do operador, NUNCA o do clone. O clone vive
    # dentro do mount gravavel e o agente o edita a vontade; preferi-lo faria
    # do operador o carteiro da politica do agente, que acrescentaria um
    # dominio ao proprio .agent-sandbox.toml e esperaria o proximo reload.
    # E a mesma invariante que poe `state/` fora do mount (workspace.py), e a
    # mesma fonte que o `up` usa — as duas rotas nao podem divergir.
    profile = load_profile(origin)
    conf = layout.state / "squid.conf"
    conf.write_text(render(profile,
                           root / "image" / "squid" / "allowlist-base.txt",
                           root / "image" / "squid" / "squid.conf.tmpl"))
    conf.chmod(0o644)
    if podman.exists("container", n["proxy"]):
        podman.run("restart", n["proxy"])
    print(f"allowlist recarregada para {ws} (proxy reiniciado, agente preservado)")
    return 0


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


# Verificar por CODIGO DE SAIDA de um comando que EXERCITA autenticacao.
# `--version` responde 0 com o agente deslogado: era o que fazia o login
# imprimir "Antigravity: ok" enquanto a CLI dizia "You are currently not
# signed in". Um falso verde aqui e pior que nenhuma checagem, porque manda o
# operador embora achando que a credencial foi gravada.
# Tambem nao vale grepar "logged in": essa string casa "not logged in".
LOGIN_CHECKS = (
    ("Codex", "codex login status"),
    ("Claude Code", "claude -p ping < /dev/null"),
    ("Antigravity", "agy -p ping < /dev/null"),
)


def login(root: Path) -> int:
    """Autentica os tres agentes UMA VEZ, num container fora da rede interna.

    Fora da rede interna de proposito: o login por device-auth precisa de
    egresso direto, e nao ha proxy algum neste caminho.
    """
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")
    ensure_keyring_service()
    name = "asb-login"
    if podman.exists("container", name):
        podman.run("rm", "-f", name, check=False)

    podman.run(
        "run", "-d", "--name", name,
        "--userns", "keep-id:uid=1000,gid=1000",
        "-v", f"{ensure_keyring_runtime_volume()}:/run/asb-keyring:ro,z",
        "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={KEYRING_BUS}",
        "-v", f"{ensure_credentials_volume()}:/run/asb-credentials:z",
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
            if label == "Claude Code":
                print("Aviso: se o Claude Code solicitar 'Quick safety check', use a seta\n"
                      "para baixo e selecione 'Yes, I trust this folder' (o padrao 'No, exit' aborta o login).\n",
                      file=sys.stderr)
            # `bash -lc` nao e decoracao: sem shell de login o agy nao esta no
            # PATH e DBUS_SESSION_BUS_ADDRESS esta ausente, que e exatamente
            # como a credencial acaba em texto claro em vez do keyring.
            # -w garante execucao no HOME do usuario em vez da raiz /.
            subprocess.run([podman.require_binary(), "exec", "-it",
                            "-u", "1000", "-w", str(Path.home()), name,
                            "bash", "-lc", command])

        # Verificar por CODIGO DE SAIDA, nunca por grep de "logged in": essa
        # string casa tambem com "not logged in".
        failed = []
        for label, command in LOGIN_CHECKS:
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
