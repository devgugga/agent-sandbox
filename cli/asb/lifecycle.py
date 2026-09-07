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

from . import podman, readiness, supervisor
from .install import install_runtime
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
CONFIG = (
    Path(os.environ["ASB_CONFIG_ROOT"])
    if "ASB_CONFIG_ROOT" in os.environ
    else Path(os.path.expanduser("~")) / ".config" / "agent-sandbox"
)
SSH_KEY = CONFIG / "id_ed25519"
CREDENTIALS_VOLUME = os.environ.get("ASB_CREDENTIALS_VOLUME", "asb-credentials")
TOOLCACHE_VOLUME = "asb-toolcache"
KEYRING_CONTAINER = "asb-keyring"
KEYRING_RUNTIME_VOLUME = "asb-keyring-runtime"
KEYRING_DATA_VOLUME = "asb-keyring-data"
KEYRING_BUS = "/run/asb-keyring/bus"
KEYRING_PASS = CONFIG / "keyring.pass"
KEYRING_SCHEMA = "2"


def _inspect_keyring_container(container: str) -> tuple[str, dict[str, dict[str, object]]]:
    """Retorna o schema e os mounts reais do singleton, indexados por destino."""
    try:
        raw = podman.out("container", "inspect", container, "--format", "{{json .}}")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("inspect nao retornou um objeto JSON")
        schema = (data.get("Config", {}).get("Labels", {}) or {}).get("asb.keyring.schema", "")
        mounts = {}
        for m in data.get("Mounts", []) or []:
            dest = m.get("Destination") or m.get("destination")
            if dest:
                mounts[dest] = {
                    "type": m.get("Type") or m.get("type") or "",
                    "name": m.get("Name") or m.get("name") or "",
                    "source": m.get("Source") or m.get("source") or "",
                    "rw": bool(m.get("RW", False)),
                }
        return schema, mounts
    except Exception as exc:
        raise podman.PodmanError(
            f"nao foi possivel inspecionar o container de keyring '{container}': {exc}"
        ) from exc


def _keyring_mount_contract_issue(mounts: dict[str, dict[str, object]]) -> str:
    """Retorna a primeira divergencia do contrato persistente do singleton."""
    expected_volumes = {
        "/run/asb-credentials": (
            os.environ.get("ASB_CREDENTIALS_VOLUME", CREDENTIALS_VOLUME), False),
        "/run/asb-keyring-data": (
            os.environ.get("ASB_KEYRING_DATA_VOLUME", KEYRING_DATA_VOLUME), True),
        "/run/asb-keyring": (
            os.environ.get("ASB_KEYRING_RUNTIME_VOLUME", KEYRING_RUNTIME_VOLUME), True),
    }
    for destination, (name, rw) in expected_volumes.items():
        mount = mounts.get(destination)
        if mount is None:
            return f"mount {destination} ausente"
        if mount.get("type") != "volume" or mount.get("name") != name:
            return f"mount {destination} aponta para origem inesperada"
        if mount.get("rw") is not rw:
            mode = "leitura/escrita" if rw else "somente leitura"
            return f"mount {destination} deve ser {mode}"

    pass_mount = mounts.get("/run/asb-keyring-pass")
    expected_pass = Path(
        os.environ.get("ASB_KEYRING_PASS_FILE", str(KEYRING_PASS))
    ).resolve()
    if pass_mount is None:
        return "mount /run/asb-keyring-pass ausente"
    try:
        actual_pass = Path(str(pass_mount.get("source", ""))).resolve()
    except (OSError, RuntimeError, ValueError):
        actual_pass = Path("/")
    if pass_mount.get("type") != "bind" or actual_pass != expected_pass:
        return "mount /run/asb-keyring-pass aponta para origem inesperada"
    if pass_mount.get("rw") is not False:
        return "mount /run/asb-keyring-pass deve ser somente leitura"
    return ""


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
    vol = os.environ.get("ASB_TOOLCACHE_VOLUME", TOOLCACHE_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


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


def ensure_keyring_data_volume() -> str:
    vol = os.environ.get("ASB_KEYRING_DATA_VOLUME", KEYRING_DATA_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


def check_keyring_service(container: str | None = None) -> tuple[bool, str, str]:
    """Verifica a saude do servico de keyring singleton sem mutacao.

    Distingue:
      1. container ausente: 'container asb-keyring'
      2. container parado: 'asb-keyring parado'
      3. schema desatualizado: 'schema do Secret Service ... desatualizado'
      4. contrato de mounts violado: 'contrato de mounts do Secret Service violado'
      5. socket ausente: 'socket do Secret Service (asb-keyring)'
      6. Secret Service sem resposta: 'Secret Service sem resposta (asb-keyring)'
      7. saudavel: 'Secret Service (asb-keyring)'
    Toda falha indica a mesma correcao: 'asb-agent login'.
    """
    name = container or os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    if shutil.which("podman") is None:
        return False, f"container {name}", "asb-agent login"

    try:
        if not podman.exists("container", name):
            return False, f"container {name}", "asb-agent login"
        if not podman.running(name):
            return False, f"{name} parado", "asb-agent login"

        schema, mounts = _inspect_keyring_container(name)
        if schema != KEYRING_SCHEMA:
            return False, f"schema do Secret Service ({name}) desatualizado ({schema or 'legado'})", "asb-agent login"

        contract_issue = _keyring_mount_contract_issue(mounts)
        if contract_issue:
            return False, f"contrato de mounts do Secret Service violado ({name}): {contract_issue}", "asb-agent login"

        sock_check = podman.run(
            "exec", "-u", "1000", name,
            "test", "-S", KEYRING_BUS,
            check=False,
        )
        sock_rc = getattr(sock_check, "returncode", 1) if sock_check is not None else 1
        if sock_rc != 0:
            return False, f"socket do Secret Service ({name})", "asb-agent login"

        secrets_check = podman.run(
            "exec", "-u", "1000", name,
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
        if secrets_rc != 0:
            return False, f"Secret Service sem resposta ({name})", "asb-agent login"

        return True, f"Secret Service ({name})", ""
    except Exception as exc:
        return False, f"Secret Service ({name}): {exc}", "asb-agent login"


def _wait_for_keyring_readiness(container: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        ok, _, _ = check_keyring_service(container)
        if ok:
            return True
        time.sleep(0.05)
    return False


def ensure_keyring_service(timeout: float = 5.0) -> str:
    """Garante o servico global de keyring (singleton).

    Cria e/ou inicia o container asb-keyring com rede isolada (--network none),
    reinicializacao automatica (--restart unless-stopped), permissao uid 1000,
    volume de dados exclusivo do keyring e volume de runtime compartilhado.

    Se o container existente for schema 1 ou violar o contrato de mounts
    legado, recria automaticamente apenas o container singleton (upgrade
    transparente), sem remover volumes, passfile ou dados legados.
    """
    container = os.environ.get("ASB_KEYRING_CONTAINER", KEYRING_CONTAINER)
    if podman.exists("container", container):
        schema, mounts = _inspect_keyring_container(container)
        if schema not in ("", "1", KEYRING_SCHEMA):
            raise podman.PodmanError(
                f"container '{container}' possui schema incompativel ({schema}). "
                f"Remova-o com 'podman rm -f {container}' e execute 'asb-agent login'."
            )
        needs_upgrade = schema in ("", "1") or bool(
            _keyring_mount_contract_issue(mounts))
        if needs_upgrade:
            # Upgrade automático: remove somente o container singleton, mantendo volumes e passfile intactos
            podman.run("rm", "-f", container, check=False)
        else:
            if not podman.running(container):
                podman.run("start", container)
            if not _wait_for_keyring_readiness(container, timeout=timeout):
                # Recuperacao idempotente nao-circular: reinicia o servico uma vez e revalida
                podman.run("restart", container)
                if not _wait_for_keyring_readiness(container, timeout=timeout):
                    raise podman.PodmanError(
                        f"servico de keyring '{container}' permanece sem resposta apos reinicio; "
                        f"remova o container com 'podman rm -f {container}' e execute 'asb-agent login'"
                    )
            return container

    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")

    pass_file = ensure_keyring_pass()
    cred_vol = ensure_credentials_volume()
    keyring_data_vol = ensure_keyring_data_volume()
    run_vol = ensure_keyring_runtime_volume()

    podman.run(
        "run", "-d", "--name", container,
        "--label", f"asb.keyring.schema={KEYRING_SCHEMA}",
        "--network", "none",
        "--restart", "unless-stopped",
        "--user", "1000",
        "--userns", "keep-id:uid=1000,gid=1000",
        "-v", f"{pass_file}:/run/asb-keyring-pass:ro,Z",
        "-v", f"{cred_vol}:/run/asb-credentials:ro,z",
        "-v", f"{keyring_data_vol}:/run/asb-keyring-data:z",
        "-v", f"{run_vol}:/run/asb-keyring:z",
        "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={KEYRING_BUS}",
        "--entrypoint", "/usr/local/bin/start-keyring.sh",
        IMAGE,
    )
    if not _wait_for_keyring_readiness(container, timeout=timeout):
        podman.run("restart", container)
        if not _wait_for_keyring_readiness(container, timeout=timeout):
            raise podman.PodmanError(
                f"servico de keyring '{container}' falhou ao inicializar; "
                f"remova o container com 'podman rm -f {container}' e execute 'asb-agent login'"
            )
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


class WorkspaceTransaction:
    """Rastreia recursos criados durante a transacao de up para rollback estrito por ID."""

    def __init__(self, ws: str, is_existing: bool) -> None:
        self.ws = ws
        self.is_existing = is_existing
        self.created_containers: list[str] = []
        self.created_networks: list[str] = []
        self.created_volumes: list[str] = []
        self.created_units: list[Path] = []

    def record_container(self, container_id: str) -> None:
        if container_id and container_id not in self.created_containers:
            self.created_containers.append(container_id)

    def record_network(self, network_name: str) -> None:
        if network_name and network_name not in self.created_networks:
            self.created_networks.append(network_name)

    def record_volume(self, volume_name: str) -> None:
        if volume_name and volume_name not in self.created_volumes:
            self.created_volumes.append(volume_name)

    def record_unit(self, unit_path: Path) -> None:
        if unit_path and unit_path not in self.created_units:
            self.created_units.append(unit_path)

    def rollback(self) -> None:
        # Falha em workspace existente NUNCA executa sweep destrutivo de containers preexistentes
        if self.is_existing:
            return

        # Rollback atinge EXCLUSIVAMENTE os IDs dos recursos criados nesta transacao
        for cid in self.created_containers:
            podman.run("rm", "-f", cid, check=False)

        for net in self.created_networks:
            if podman.exists("network", net):
                podman.run("network", "rm", "-f", net, check=False)

        for vol in self.created_volumes:
            if podman.exists("volume", vol):
                podman.run("volume", "rm", "-f", vol, check=False)

        if self.created_units:
            try:
                supervisor.remove_workspace_units(self.ws)
            except Exception:
                pass


def _get_container_id(name: str) -> str:
    try:
        cid = podman.out("inspect", name, "--format", "{{.Id}}").strip()
        if cid:
            return cid
    except Exception:
        pass
    return name


def _origin_of(ws: str, home: Path) -> Path | None:
    """Le o caminho de origem gravado no estado. `down` precisa dele para achar
    o layout, e um workspace sem estado nao e erro: nao ha o que limpar."""
    marker = home / ".local" / "state" / "agent-sandbox" / ws / "origin"
    return Path(marker.read_text().strip()) if marker.is_file() else None


def _runtime_of(ws: str, home: Path | None = None) -> str:
    """Le o backend de runtime gravado no manifesto do workspace."""
    h = home if home is not None else Path(os.path.expanduser("~"))
    manifest_file = h / ".local" / "state" / "agent-sandbox" / ws / "runtime.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                return str(manifest.get("runtime_type") or manifest.get("runtime_backend") or "legacy")
        except Exception:
            pass
    return "legacy"


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


def start_services(
    ws: str,
    profile: Profile,
    cmd_action: str = "run",
    restart: str = "unless-stopped",
    tx: WorkspaceTransaction | None = None,
) -> dict[str, dict[str, str]]:
    n = names(ws)
    cmd_flags = ["-d"] if cmd_action == "run" else []
    manifests: dict[str, dict[str, str]] = {}
    for service in profile.services:
        container = f"asb-{ws}-svc-{service.name}"
        env = []
        for key, value in service.env.items():
            env += ["-e", f"{key}={value}"]
        podman.run(cmd_action, *cmd_flags, "--name", container,
                   "--label", f"asb.workspace={ws}",
                   "--restart", restart,
                   "--network", n["net"], "--user", "0",
                   *env, service.image)
        cid = _get_container_id(container)
        if tx:
            tx.record_container(cid)
        manifests[f"svc-{service.name}"] = {
            "name": container,
            "id": cid,
            "unit": f"{container}.service",
        }
    return manifests


def start_forwarder(
    ws: str,
    profile: Profile,
    cmd_action: str = "run",
    restart: str = "unless-stopped",
    tx: WorkspaceTransaction | None = None,
) -> str:
    """Encaminha SO as portas declaradas para o host."""
    if not profile.host_ports:
        return ""
    for port in profile.host_ports:
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            raise ValueError(f"Porta invalida para forwarder: {port!r}")
    n = names(ws)
    forwarder = f"{n['net']}-fwd"
    port_args = [str(port) for port in profile.host_ports]
    cmd_flags = ["-d"] if cmd_action == "run" else []
    podman.run(cmd_action, *cmd_flags, "--name", forwarder,
               "--label", f"asb.workspace={ws}",
               "--restart", restart,
               "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
               "--network", f"{n['net']},{n['out']}", "--user", "900",
               "--entrypoint", "/usr/local/bin/asb-forwarder",
               PROXY_IMAGE, *port_args)
    cid = _get_container_id(forwarder)
    if tx:
        tx.record_container(cid)
    return cid


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


def _run_mise_installs(agent_container: str, project_root: Path) -> list[tuple[Path, int, str]]:
    mise_errors: list[tuple[Path, int, str]] = []
    for d in discover_mise_dirs(project_root):
        print(f"  info executando mise install em {d.name}...", file=sys.stderr)
        res = podman.run("exec", "-u", "1000", "-w", str(d),
                         agent_container, "mise", "install", "-y", check=False)
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
    return mise_errors


def _current_revision(root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, check=True
        )
        rev = res.stdout.strip()
        if rev and all(c not in rev for c in ("/", "\\", "..", " ", "\t", "\n", "\r")):
            return rev
    except Exception:
        pass
    return "dev"


def prepare_workspace(
    root: Path,
    ws: str,
    repo: Path,
    runtime: str = "legacy",
    tx: WorkspaceTransaction | None = None,
) -> None:
    """Prepara clone, redes, containers e manifesto sem restauracao global."""
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")

    podman.ensure_rootless_netns()
    build_proxy(root)
    home = Path(os.path.expanduser("~"))
    profile = load_profile(repo)
    layout = layout_for(repo, ws, home)
    prepare_clone(repo, layout)

    layout.state.mkdir(parents=True, exist_ok=True)
    conf = layout.state / "squid.conf"
    conf.write_text(render(profile,
                           root / "image" / "squid" / "allowlist-base.txt",
                           root / "image" / "squid" / "squid.conf.tmpl"))
    # o squid roda como uid 900 e precisa LER o arquivo montado
    conf.chmod(0o644)
    (layout.state / "origin").write_text(str(repo))

    n = names(ws)
    if not podman.exists("network", n["net"]):
        podman.run("network", "create", "--internal", n["net"])
        if tx:
            tx.record_network(n["net"])
    if not podman.exists("network", n["out"]):
        podman.run("network", "create", n["out"])
        if tx:
            tx.record_network(n["out"])

    cmd_action = "create" if runtime == "systemd" else "run"
    cmd_flags = ["-d"] if cmd_action == "run" else []
    restart_policy = "no" if runtime == "systemd" else "unless-stopped"

    # 1. Proxy
    proxy_args = [
        cmd_action,
        *cmd_flags,
        "--name", n["proxy"],
        "--label", f"asb.workspace={ws}",
        "--restart", restart_policy,
        "--network", f"{n['net']},{n['out']}", "--user", "900",
        "-v", f"{conf}:/etc/squid/squid.conf:ro,Z",
        PROXY_IMAGE, "squid", "-N", "-f", "/etc/squid/squid.conf",
    ]
    podman.run(*proxy_args)
    proxy_cid = _get_container_id(n["proxy"])
    if tx:
        tx.record_container(proxy_cid)

    # 2. Servicos adicionais
    services_manifest = start_services(
        ws, profile, cmd_action=cmd_action, restart=restart_policy, tx=tx
    )

    # 3. Forwarder
    fwd_cid = start_forwarder(
        ws, profile, cmd_action=cmd_action, restart=restart_policy, tx=tx
    )

    # 4. Broker Docker
    docker_cid = ""
    docker_name = f"{n['net']}-docker"
    if profile.host_api == "read":
        broker_sock = Path("/run/asb-docker/docker.sock")
        if not broker_sock.exists():
            raise podman.PodmanError(
                'host_api = "read" pede o broker; execute '
                "'asb-agent install-broker' (usa sudo, uma vez)")
        docker_args = [
            cmd_action,
            *cmd_flags,
            "--name", docker_name,
            "--label", f"asb.workspace={ws}",
            "--restart", restart_policy,
            "--network", n["net"], "--user", "900",
            "-v", f"{broker_sock}:/var/run/docker.sock:Z",
            "--entrypoint", "sh", PROXY_IMAGE, "-c",
            "socat TCP-LISTEN:2375,fork,reuseaddr UNIX-CONNECT:/var/run/docker.sock",
        ]
        podman.run(*docker_args)
        docker_cid = _get_container_id(docker_name)
        if tx:
            tx.record_container(docker_cid)

    # 5. Staging, SSH, Keyring
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
        cmd_action,
        *cmd_flags,
        "--name", n["agent"],
        "--label", f"asb.workspace={ws}",
        "--restart", restart_policy,
        "--network", n["net"],
        "-p", "127.0.0.1::22",
        *published,
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
        "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000",
        "-v", f"{ensure_toolcache_volume()}:/run/asb-toolcache:Z",
        *(["-e", f"DOCKER_HOST=tcp://{n['net']}-docker:2375"]
          if profile.host_api == "read" else []),
        "-e", "ASB_HOST_PORTS=" + ",".join(str(p) for p in profile.host_ports),
        "-e", f"ASB_WORKSPACE={ws}",
        IMAGE,
    ]
    if profile.container_mode == "nested":
        volume = f"{n['net']}-containers"
        if not podman.exists("volume", volume):
            podman.run("volume", "create", volume)
            if tx:
                tx.record_volume(volume)
        agent_args[-1:-1] = [
            "--device", "/dev/fuse",
            "--device", "/dev/net/tun",
            "--security-opt", "label=disable",
            "--security-opt", "unmask=/proc/*",
            "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
            "-v", f"{volume}:{home}/.local/share/containers:Z",
        ]
    podman.run(*agent_args)
    agent_cid = _get_container_id(n["agent"])
    if tx:
        tx.record_container(agent_cid)

    # 6. Gravar manifesto runtime.json
    manifest_containers: dict[str, dict[str, str]] = {
        "proxy": {
            "name": n["proxy"],
            "id": proxy_cid,
            "unit": f"{n['proxy']}.service",
        },
        "agent": {
            "name": n["agent"],
            "id": agent_cid,
            "unit": f"{n['agent']}.service",
        },
    }
    if profile.host_ports and fwd_cid:
        manifest_containers["forwarder"] = {
            "name": fwd_name,
            "id": fwd_cid,
            "unit": f"{fwd_name}.service",
        }
    if profile.host_api == "read" and docker_cid:
        manifest_containers["docker"] = {
            "name": docker_name,
            "id": docker_cid,
            "unit": f"{docker_name}.service",
        }
    manifest_containers.update(services_manifest)

    manifest_data = {
        "schemaVersion": 1,
        "workspace": ws,
        "runtime_type": runtime,
        "runtime_backend": runtime,
        "containers": manifest_containers,
    }
    for var in (
        "ASB_CONFIG_ROOT",
        "ASB_KEYRING_CONTAINER",
        "ASB_CREDENTIALS_VOLUME",
        "ASB_TOOLCACHE_VOLUME",
        "ASB_KEYRING_DATA_VOLUME",
        "ASB_KEYRING_RUNTIME_VOLUME",
        "ASB_KEYRING_PASS_FILE",
    ):
        if var in os.environ:
            manifest_data[var] = os.environ[var]
    if "ASB_CONFIG_ROOT" in os.environ:
        manifest_data["config_dir"] = os.environ["ASB_CONFIG_ROOT"]
    if "ASB_KEYRING_CONTAINER" in os.environ:
        manifest_data["keyring_container"] = os.environ["ASB_KEYRING_CONTAINER"]
    manifest_data["ssh_key"] = str(key)

    if runtime == "systemd":
        rev = _current_revision(root)
        if (root / "cli" / "asb").is_dir():
            install_runtime(root, rev)
            manifest_data["revision"] = rev

    manifest_file = layout.state / "runtime.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # 7. Instalar unidades systemd se runtime gerenciado
    if runtime == "systemd":
        units = supervisor.install_workspace(ws, state_dir=layout.state)
        if tx and isinstance(units, (list, tuple)):
            for u in units:
                tx.record_unit(u)


def up(root: Path, ws: str, repo: Path, runtime: str = "legacy") -> int:
    """Cria o workspace. Ou completa, ou nao deixa nada para tras.

    Falha em workspace existente NUNCA executa sweep destrutivo de containers preexistentes.
    Em novo workspace, rollback remove EXCLUSIVAMENTE os recursos criados nesta transacao.
    """
    n = names(ws)
    is_existing = podman.exists("container", n["agent"])
    if is_existing:
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    tx = WorkspaceTransaction(ws, is_existing=False)
    home = Path(os.path.expanduser("~"))
    layout = layout_for(repo, ws, home)
    try:
        prepare_workspace(root, ws, repo, runtime=runtime, tx=tx)

        if runtime == "systemd":
            supervisor.start_workspace(ws, enable=True)

        # 1. Sonda de conectividade do proxy antes de operacoes que exigem rede (ex: mise install)
        proxy_res = readiness.wait_until(
            lambda to: readiness.probe_proxy(n["agent"], n["proxy"], timeout=to),
            timeout=30.0,
        )
        if proxy_res.state != "healthy":
            print(f"erro: proxy nao esta pronto ({proxy_res.code}): {proxy_res.remediation}", file=sys.stderr)
            raise podman.PodmanError(f"proxy nao esta pronto: {proxy_res.code}")

        # 2. Executar mise install
        mise_errors = _run_mise_installs(n["agent"], layout.project_root)
        if mise_errors:
            failed_names = ", ".join(d.name for d, _, _ in mise_errors)
            print(f"\nerro: falha na instalacao de ferramentas mise em: {failed_names}",
                  file=sys.stderr)
            print("workspace mantido no ar; corrija a allowlist ou mise.toml e "
                  "execute 'asb-agent up' novamente.", file=sys.stderr)
            return 1

        # 3. Conferir porta e handshake SSH via probe_ssh antes de emitir JSON
        mapping = podman.out("port", n["agent"], "22")
        port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
        if not port:
            raise podman.PodmanError("nao foi possivel determinar a porta SSH")

        key = ensure_ssh_key()
        ssh_res = readiness.wait_until(
            lambda to: readiness.probe_ssh(int(port), key=key, timeout=to),
            timeout=30.0,
        )
        if ssh_res.state != "healthy":
            print(f"erro: SSH nao esta pronto ({ssh_res.code}): {ssh_res.remediation}", file=sys.stderr)
            raise podman.PodmanError(f"SSH nao esta pronto na porta {port}: {ssh_res.code}")

        return emit(ws, layout)
    except BaseException:
        tx.rollback()
        raise


def _up(root: Path, ws: str, repo: Path, runtime: str = "legacy") -> int:
    return up(root, ws, repo, runtime=runtime)


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
    """Remove unidades do systemd (se gerenciado), containers e redes.

    NAO remove ~/asb-agent/<proj>/<ws>: ali vive o trabalho do agente.
    NUNCA remove auth global nem keyring singleton compartilhado.
    """
    n = names(ws)
    home = Path(os.path.expanduser("~"))

    # Remove unidades systemd se existirem
    supervisor.remove_workspace_units(ws)

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
    """Para o workspace.

    Em runtime gerenciado (systemd):
    Desabilita e para o target systemd, e verifica que todos os containers foram parados.

    Em runtime legado:
    Para todos os containers do workspace com podman stop.
    """
    n, home, origin = _require_workspace(ws)
    runtime = _runtime_of(ws, home)

    if runtime == "systemd":
        target = f"asb-{ws}.target"
        subprocess.run(
            ["systemctl", "--user", "disable", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["systemctl", "--user", "stop", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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

    Em runtime gerenciado (systemd):
    Habilita o target, executa reset-failed nas unidades do workspace,
    inicia o target, e aguarda sondas de prontidão (readiness.probe_workspace).

    Em runtime legado:
    Religa os containers com podman start.
    """
    n, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)
    runtime = _runtime_of(ws, home)

    podman.ensure_rootless_netns()
    ensure_keyring_service()

    if runtime == "systemd":
        target = f"asb-{ws}.target"
        subprocess.run(["systemctl", "--user", "enable", target], check=True)
        reset_units = [target]
        manifest_file = layout.state / "runtime.json"
        if manifest_file.is_file():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                for info in manifest.get("containers", {}).values():
                    if isinstance(info, dict) and "unit" in info:
                        reset_units.append(info["unit"])
            except Exception:
                pass
        subprocess.run(
            ["systemctl", "--user", "reset-failed", *reset_units],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        supervisor.start_workspace(ws)

        def check_ws(to: float) -> readiness.ProbeResult:
            probes = readiness.probe_workspace(ws)
            for p in probes:
                if p.state != "healthy":
                    return p
            return readiness.ProbeResult("workspace", "healthy", "ok", 0, "")

        probe_res = readiness.wait_until(check_ws, timeout=30.0)
        if probe_res.state != "healthy":
            print(f"erro: falha na prontidao do workspace ({probe_res.component}: {probe_res.code}): {probe_res.remediation}", file=sys.stderr)
            return 1
    else:
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

    return emit(ws, layout)


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
        "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000",
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
