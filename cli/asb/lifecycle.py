"""cli/asb/lifecycle.py — up, down, suspend, resume, purge, pull, build."""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from . import install, podman, readiness, supervisor
from .install import install_runtime
from .keyring import (
    CONFIG,
    KEYRING_BUS,
    KEYRING_CONTAINER,
    KEYRING_DATA_VOLUME,
    KEYRING_PASS,
    KEYRING_RUNTIME_VOLUME,
    KEYRING_SCHEMA,
    _inspect_keyring_container,
    _keyring_mount_contract_issue,
    check_keyring_service,
    ensure_keyring_data_volume,
    ensure_keyring_pass,
    ensure_keyring_runtime_volume,
    ensure_keyring_service,
)
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

# CONFIG, SSH_KEY e as constantes/funcoes de keyring (KEYRING_*, ensure_keyring_*,
# check_keyring_service, _inspect_keyring_container, _keyring_mount_contract_issue)
# foram extraidas para cli/asb/keyring.py (Tarefa A2).
# Os nomes acima sao reexports temporarios: mantem `lifecycle.X` funcionando para
# quem ja importava daqui, sem duplicar a logica.
IMAGE = "agent-sandbox:latest"
PROXY_IMAGE = "agent-sandbox-proxy:latest"
PROXY_PORT = 3128
SSH_KEY = CONFIG / "id_ed25519"
CREDENTIALS_VOLUME = os.environ.get("ASB_CREDENTIALS_VOLUME", "asb-credentials")
TOOLCACHE_VOLUME = "asb-toolcache"


def names(ws: str) -> dict[str, str]:
    """Nomes derivados do workspace. Um lugar so: no v1 a derivacao duplicada
    entre create e destroy divergiu e vazou um pod a cada divergencia."""
    return {
        "net": f"asb-{ws}",
        "out": f"asb-{ws}-out",
        "agent": f"asb-{ws}-agent",
        "proxy": f"asb-{ws}-proxy",
        # Volume de ESTADO DE SESSAO deste workspace (transcricoes, todos).
        # Nao e container: derivado aqui pelo mesmo motivo dos demais nomes.
        "session": f"asb-{ws}-session",
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


# Um DIRETORIO por fornecedor dentro do volume de credenciais, montado sobre
# o diretorio de configuracao correspondente no home.
#
# A1 provou por que tem de ser diretorio: `rename`/`os.replace` sobre um
# SYMLINK substitui o proprio symlink e corta o vinculo com o volume, e sobre
# um arquivo BIND-MONTADO o mesmo `rename` falha com EBUSY. Só o diretorio
# montado sobrevive ao padrao de escrita real dos fornecedores. O Claude ainda
# soma um segundo motivo: ele abre a credencial com `O_RDONLY | O_NOFOLLOW`, e
# num symlink o Linux devolve ELOOP, que ele trata como credencial AUSENTE.
CREDENTIAL_DIRS: dict[str, str] = {"claude": ".claude", "codex": ".codex"}

# Arquivos que o layout ANTIGO (removido na A3) deixava na RAIZ do volume,
# fora de qualquer subdiretorio de fornecedor. O layout novo nao os enxerga,
# entao eles nao sao lidos nem escritos por ninguem — mas continuam legiveis
# em /run/asb-credentials/<nome> por TODO container de agente, porque o volume
# inteiro e montado rw com apenas `keyrings` mascarado. Detectar e AVISAR: a
# politica de migracao (copiar, mover ou deixar) nao e desta funcao, e apagar
# credencial nunca e recuperacao valida.
LEGACY_ROOT_CREDENTIAL_FILES: tuple[str, ...] = (
    "claude.json", "codex-auth.json", ".credentials.json", "auth.json",
    "agy.json", "gemini.json",
)

# Estado de SESSAO por workspace, sobreposto ao diretorio de credencial
# COMPARTILHADO. A credencial precisa ser compartilhada (um login por
# fornecedor, spec); a transcricao nao — e o isolamento entre workspaces
# continua valendo. Cada entrada vira um mount aninhado: o volume do workspace
# entra POR CIMA do subdiretorio correspondente do volume compartilhado.
#
# Medido no podman 6.1 (nao suposto): o mount pai (`~/.claude`) e aplicado
# antes do filho (`~/.claude/projects`); o diretorio de destino NAO precisa
# existir dentro do volume pai (o runtime o cria); e a ORIGEM, sim, precisa
# existir no volume do workspace — dai o mkdir de `ensure_session_volume`.
#
# LIMITE EXPLICITO: so DIRETORIOS entram aqui. Estado de sessao gravado como
# ARQUIVO solto na raiz do diretorio do fornecedor (`~/.claude/history.jsonl`,
# `~/.codex/history.jsonl`) continua compartilhado: sobrepor arquivo exigiria
# bind de arquivo, e A1 mediu que `rename` sobre arquivo bind-montado falha
# com EBUSY — a mesma armadilha que este redesenho existe para sair.
SESSION_STATE_DIRS: dict[str, str] = {
    "claude-projects": ".claude/projects",
    "claude-todos": ".claude/todos",
    "claude-shell-snapshots": ".claude/shell-snapshots",
    "codex-sessions": ".codex/sessions",
}


def ensure_credentials_volume() -> str:
    """Garante que o volume de credenciais EXISTE, e devolve o nome dele.

    Deliberadamente sem efeito no sistema de arquivos: quem so precisa citar o
    volume num mount (o singleton do keyring, por exemplo) chama isto e nao
    mexe em disco. A forma INTERNA do volume e responsabilidade de
    `ensure_credential_dirs`, que so quem monta os subpaths chama.
    """
    vol = os.environ.get("ASB_CREDENTIALS_VOLUME", CREDENTIALS_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


def ensure_credential_dirs(vol: str) -> None:
    """Cria, no host, um diretorio por fornecedor dentro do volume.

    Pelo host porque `volume-subpath` do podman NAO cria o caminho: um subpath
    ausente aborta o `podman run` com "no such file or directory" (medido).
    Pelo host tambem resolve a posse: com `--userns keep-id:uid=1000,gid=1000`
    o usuario do host mapeia para o uid 1000 do container, entao o diretorio
    criado aqui ja chega gravavel para o agente — o oposto do
    `Permission denied (os error 13)` que o piloto do operador viu num volume
    cujo `_data` pertencia ao uid 0.

    NUNCA cria arquivo de credencial, so diretorio. Era exatamente a criacao
    de arquivo (`: > "$stored"` no entrypoint) que deixava `claude.json` com 0
    bytes: um arquivo que jamais poderia ser lido como JSON e indistinguivel
    de "sem credencial". Tambem nunca remove nem sobrescreve o que ja existe.

    Por ser a unica funcao que enxerga a forma INTERNA do volume, e tambem
    daqui que sai o aviso do layout ANTIGO (credencial na raiz) — avisar, sem
    apagar nem mover.
    """
    mountpoint = _volume_mountpoint(vol)
    _mkdir_private(mountpoint, CREDENTIAL_DIRS, vol)
    warn_about_legacy_credential_layout(mountpoint)


def _volume_mountpoint(vol: str) -> Path:
    raw = podman.out("volume", "inspect", vol, "--format", "{{.Mountpoint}}")
    mountpoint = Path(raw)
    if not mountpoint.is_absolute() or not mountpoint.is_dir():
        # Driver de volume nao-local, ou resposta inesperada do podman. Falhar
        # aqui, com o valor a vista, e melhor que um mkdir num caminho
        # relativo qualquer.
        raise podman.PodmanError(
            f"mountpoint do volume {vol} nao e um diretorio do host: {raw!r}")
    return mountpoint


def _mkdir_private(mountpoint: Path, subs: Iterable[str], vol: str) -> None:
    """`mkdir -m 700` de cada subpath, com erro TRADUZIDO.

    Um volume cujo `_data` pertence ao uid 0 — o estado que o piloto real
    encontrou — fazia `PermissionError` cru subir ate o operador como
    traceback. O rollback do `up` rodava, mas o diagnostico nao existia.
    """
    for sub in subs:
        target = mountpoint / sub
        try:
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.chmod(0o700)
        except OSError as exc:
            raise podman.PodmanError(
                f"nao foi possivel preparar {target} no volume {vol}: {exc}. "
                f"O `_data` do volume precisa pertencer ao SEU usuario; um "
                f"`_data` de outro dono vem de um container que escreveu ali "
                f"como root. Devolva a posse com "
                f"'podman unshare chown -R 0:0 {mountpoint}' — dentro do "
                f"`podman unshare` o uid 0 e o seu proprio usuario. Se isso "
                f"falhar com EPERM, o diretorio pertence ao root do host "
                f"(podman rootful escreveu nele) e a correcao pede sudo."
            ) from exc


def warn_about_legacy_credential_layout(mountpoint: Path) -> None:
    """Avisa, alto, quando o volume ainda guarda credencial na RAIZ.

    Esta e a unica funcao que enxerga a forma INTERNA do volume, entao e a
    unica capaz de detectar o layout antigo. Ela NAO apaga, NAO move e NAO
    copia nada: a politica de migracao e de outra tarefa. O silencio e que era
    o defeito — depois de um re-login o volume passa a guardar as DUAS coisas,
    e a copia orfa da raiz continua legivel por todo container de agente.
    """
    try:
        legacy = sorted(
            name for name in LEGACY_ROOT_CREDENTIAL_FILES
            if (mountpoint / name).is_file())
    except OSError:
        return
    if not legacy:
        return
    print(
        "aviso: o volume de credenciais ainda tem arquivos no layout ANTIGO, "
        "na raiz: " + ", ".join(legacy) + ".\n"
        "  Eles NAO sao usados pelo layout novo (um diretorio por fornecedor), "
        "entao o fornecedor correspondente vai pedir login de novo.\n"
        "  Enquanto existirem, seguem legiveis em /run/asb-credentials/<nome> "
        "por qualquer container de agente: se carregam material de credencial "
        "valido, isso e exposicao.\n"
        "  Nada foi apagado nem movido aqui de proposito — decida a migracao e "
        "remova a copia obsoleta voce mesmo, depois de confirmar o login novo.",
        file=sys.stderr)


def credential_mount_args(home: Path) -> list[str]:
    """Argumentos de mount das credenciais, para o agente e para os clientes
    efemeros de login/verificacao.

    `volume-subpath` monta SOMENTE o diretorio do fornecedor: o resto do
    volume — inclusive o subdiretorio legado `keyrings/` — nao aparece por
    este caminho.
    """
    vol = ensure_credentials_volume()
    ensure_credential_dirs(vol)
    args: list[str] = []
    for sub, rel in CREDENTIAL_DIRS.items():
        args += ["--mount",
                 f"type=volume,src={vol},dst={home / rel},"
                 f"volume-subpath={sub},relabel=shared"]
    return args


def ensure_session_volume(ws: str, tx: "WorkspaceTransaction | None" = None) -> str:
    """Volume de estado de sessao DESTE workspace. Um por workspace, sempre.

    Separado do volume de credenciais de proposito: a credencial e uma so,
    compartilhada; a transcricao e de quem a gerou.
    """
    vol = names(ws)["session"]
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
        if tx is not None:
            tx.record_volume(vol)
    mountpoint = _volume_mountpoint(vol)
    # A ORIGEM do subpath precisa existir: `volume-subpath` nao a cria (A1).
    _mkdir_private(mountpoint, SESSION_STATE_DIRS, vol)
    return vol


def session_mount_args(vol: str, home: Path) -> list[str]:
    """Mounts que sobrepoem o estado de sessao do workspace ao diretorio de
    credencial compartilhado.

    Cada um entra POR CIMA de um subdiretorio de `~/.claude` / `~/.codex`, que
    sao eles mesmos mounts do volume compartilhado. O resultado medido: os dois
    workspaces leem a MESMA credencial e nenhum dos dois enxerga a transcricao
    do outro.
    """
    args: list[str] = []
    for sub, rel in SESSION_STATE_DIRS.items():
        args += ["--mount",
                 f"type=volume,src={vol},dst={home / rel},"
                 f"volume-subpath={sub},relabel=shared"]
    return args


def ensure_toolcache_volume() -> str:
    vol = os.environ.get("ASB_TOOLCACHE_VOLUME", TOOLCACHE_VOLUME)
    if not podman.exists("volume", vol):
        podman.run("volume", "create", vol)
    return vol


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
            except Exception as exc:
                # Nunca silenciar: uma falha aqui deixa unidades systemd
                # orfas apontando para containers que o rollback acabou de
                # remover. O rollback continua (o erro original de `up`
                # segue tendo prioridade), mas o operador precisa saber.
                print(
                    f"aviso: falha ao remover unidades systemd de '{self.ws}' "
                    f"durante rollback: {exc}",
                    file=sys.stderr,
                )


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
    cmd_action: str = "create",
    restart: str = "no",
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
    cmd_action: str = "create",
    restart: str = "no",
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


def ensure_runtime(root: Path) -> Path:
    """Instala o runtime versionado desta revisao e devolve o diretorio.

    Emenda A: todo workspace e o keyring sao unidades systemd, e as unidades
    executam `launcher.sh`, `runtime_check.py` e `network_gate.py` desse
    diretorio, nunca do checkout.
    """
    return install_runtime(root, _current_revision(root))


def prepare_workspace(
    root: Path,
    ws: str,
    repo: Path,
    tx: WorkspaceTransaction | None = None,
) -> None:
    """Prepara clone, redes, containers e manifesto sem restauracao global."""
    if not podman.exists("image", IMAGE):
        raise podman.PodmanError(
            f"imagem {IMAGE} ausente; execute 'asb-agent build'")

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

    # Runtime unico (Emenda A): todo container ASB nasce parado e sem politica
    # de reinicio do Podman; quem o inicia e reinicia e sempre o systemd.
    cmd_action = "create"
    cmd_flags: list[str] = []
    restart_policy = "no"

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
    fwd_name = f"{n['net']}-fwd"
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

    runtime_dir = ensure_runtime(root)
    ensure_keyring_service(runtime_dir)

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
        *credential_mount_args(home),
        # Por cima dos mounts acima: a credencial e compartilhada, a
        # transcricao nao. Sem isto o agente do workspace A LE os projetos,
        # todos e sessoes do workspace B.
        *session_mount_args(ensure_session_volume(ws, tx), home),
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
        "runtime_type": "systemd",
        "runtime_backend": "systemd",
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

    manifest_data["revision"] = runtime_dir.name

    manifest_file = layout.state / "runtime.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # 7. Instalar unidades systemd (runtime unico)
    units = supervisor.install_workspace(ws, state_dir=layout.state)
    if tx and isinstance(units, (list, tuple)):
        for u in units:
            tx.record_unit(u)


def up(root: Path, ws: str, repo: Path) -> int:
    """Cria o workspace. Ou completa, ou nao deixa nada para tras.

    Falha em workspace existente NUNCA executa sweep destrutivo de containers preexistentes.
    Em novo workspace, rollback remove EXCLUSIVAMENTE os recursos criados nesta transacao.
    """
    n = names(ws)
    is_existing = podman.exists("container", n["agent"])
    if is_existing:
        raise podman.PodmanError(
            f"workspace ja existe: {ws} (use 'resume', ou 'down' primeiro)")

    # Emenda A §5: o drop-in legado do podman-restart criava o namespace
    # rootless cedo em todo boot. Remocao idempotente e segura: so sai se o
    # conteudo for exatamente o do projeto; drop-ins alheios ficam intactos.
    if install.remove_project_dropin():
        print("drop-in legado do podman-restart removido", file=sys.stderr)

    # Emenda A §4: a espera de boot e sem limite, mas um `up` interativo sem
    # rede ficaria preso em `systemctl start`. Falha antes de criar qualquer
    # recurso, com sonda so do host: nao cria o namespace rootless.
    host_res = readiness.wait_until(
        lambda to: readiness.probe_host(timeout=to), timeout=30.0)
    if host_res.state != "healthy":
        raise podman.PodmanError(
            f"sem conectividade real ({host_res.code}); conecte a rede e "
            "rode 'asb-agent up' de novo")

    tx = WorkspaceTransaction(ws, is_existing=False)
    home = Path(os.path.expanduser("~"))
    layout = layout_for(repo, ws, home)
    try:
        prepare_workspace(root, ws, repo, tx=tx)
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
            lambda to: readiness.probe_ssh(
                int(port), user=getpass.getuser(), key=key, timeout=to),
            timeout=30.0,
        )
        if ssh_res.state != "healthy":
            print(f"erro: SSH nao esta pronto ({ssh_res.code}): {ssh_res.remediation}", file=sys.stderr)
            raise podman.PodmanError(f"SSH nao esta pronto na porta {port}: {ssh_res.code}")

        return emit(ws, layout, port=port)
    except BaseException:
        tx.rollback()
        raise


def _up(root: Path, ws: str, repo: Path) -> int:
    return up(root, ws, repo)


def emit(ws: str, layout: Layout, port: str | None = None) -> int:
    """A linha que o recipe do Orca consome. A porta e LIDA do podman, nunca
    inventada: o Orca guarda a que o create devolveu e disca nela para sempre.

    Aceita a porta ja resolvida pelo chamador (ex: `up`, que ja a consultou
    para o gate SSH) para evitar uma segunda chamada `podman port` redundante;
    se omitida, resolve por conta propria.
    """
    n = names(ws)
    resolved_port = port
    if not resolved_port:
        mapping = podman.out("port", n["agent"], "22")
        resolved_port = mapping.splitlines()[0].rsplit(":", 1)[-1] if mapping else ""
    if not resolved_port:
        raise podman.PodmanError("nao foi possivel determinar a porta SSH")
    print(json.dumps({"workspace": ws, "port": int(resolved_port), "user":
                      getpass.getuser(),
                      "project_root": str(layout.project_root)}))
    return 0


def down(ws: str) -> int:
    """Remove unidades do systemd, containers e redes.

    NAO remove ~/asb-agent/<proj>/<ws>: ali vive o trabalho do agente.
    NUNCA remove auth global nem keyring singleton compartilhado.
    """
    n = names(ws)
    home = Path(os.path.expanduser("~"))

    # Runtime unico (Emenda A): todo workspace tem unidades. `down` e a saida
    # de emergencia de um workspace quebrado, entao a remocao das unidades e
    # best-effort e nunca aborta a limpeza de containers e redes abaixo —
    # nem com `daemon-reload` falhando, nem sem `systemctl` no PATH, nem com
    # manifesto corrompido.
    try:
        supervisor.remove_workspace_units(
            ws, state_dir=home / ".local" / "state" / "agent-sandbox" / ws)
    except Exception as exc:
        print(f"aviso: falha ao remover unidades systemd de {ws}: {exc}; "
              "seguindo com limpeza local", file=sys.stderr)

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
    """Para o workspace: desabilita e para o target systemd e verifica que todos os containers pararam."""
    n, _, _ = _require_workspace(ws)

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

    # Verificar que os containers do workspace realmente pararam: o brief
    # exige a verificacao, nao apenas o disparo do stop/disable.
    still_running = sorted(
        c for c in found
        if podman.exists("container", c) and podman.running(c)
    )
    if still_running:
        print(
            f"erro: falha ao suspender workspace {ws}: containers ainda em "
            f"execucao: {', '.join(still_running)}",
            file=sys.stderr,
        )
        return 1

    return 0


def resume(root: Path, ws: str) -> int:
    """Religa o workspace pelo systemd.

    Verifica a conectividade do host, garante o keyring, habilita o target,
    executa reset-failed nas unidades do workspace e inicia o target. O JSON
    de conexao so e emitido depois que readiness.probe_workspace reporta tudo
    saudavel.
    """
    _, home, origin = _require_workspace(ws)
    layout = layout_for(origin, ws, home)

    # Emenda A §4: mesmo motivo do `up`. Sem rede, `systemctl start` ficaria
    # preso na espera sem limite; aqui a falha e imediata e nada e tocado.
    host_res = readiness.wait_until(
        lambda to: readiness.probe_host(timeout=to), timeout=30.0)
    if host_res.state != "healthy":
        print(f"erro: sem conectividade real ({host_res.code}); conecte a rede "
              "e rode 'asb-agent resume' de novo", file=sys.stderr)
        return 1

    ensure_keyring_service(ensure_runtime(root))

    target = f"asb-{ws}.target"
    subprocess.run(["systemctl", "--user", "enable", target], check=True)
    reset_units = [target]
    manifest_file = layout.state / "runtime.json"
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise podman.PodmanError(
                f"manifesto de runtime corrompido: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise podman.PodmanError("manifesto de runtime corrompido: raiz deve ser um objeto JSON")
        for info in manifest.get("containers", {}).values():
            if isinstance(info, dict) and "unit" in info:
                reset_units.append(info["unit"])
    subprocess.run(
        ["systemctl", "--user", "reset-failed", *reset_units],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    supervisor.start_workspace(ws)

    # Gate de prontidao: `resume` so publica conexao depois que host, proxy,
    # SSH e keyring respondem. Infraestrutura quebrada impede emitir conexao
    # (spec T1): stdout vazio, diagnostico em stderr, retorno 1 — e NENHUM
    # dado do workspace destruido, os containers ficam de pe para diagnose.
    def check_ws(to: float) -> readiness.ProbeResult:
        probes = readiness.probe_workspace(ws)
        for probe in probes:
            if probe.state != "healthy":
                return probe
        return readiness.ProbeResult("workspace", "healthy", "ok", 0, "")

    probe_res = readiness.wait_until(check_ws, timeout=30.0)
    if probe_res.state != "healthy":
        print(f"erro: falha na prontidao do workspace ({probe_res.component}: {probe_res.code}): {probe_res.remediation}", file=sys.stderr)
        return 1

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
    # O estado de sessao deste workspace some junto com os arquivos dele — e
    # so aqui. `down` preserva o trabalho, entao um `down`/`up` mantem as
    # transcricoes. Este volume nunca guarda credencial: a credencial vive no
    # volume compartilhado, que purge algum jamais toca.
    session = names(ws)["session"]
    if podman.exists("volume", session):
        podman.run("volume", "rm", "-f", session, check=False)
    remove_workspace(layout)
    print(f"removido: {layout.mount}", file=sys.stderr)
    return 0


def login(root: Path, provider: str = "all") -> int:
    """Reexport de `auth.login` (Tarefa A3).

    O fluxo de login inteiro mudou de casa: ele vive agora ao lado do
    diagnostico que o verifica, em `cli/asb/auth.py`, e nao mais no meio do
    ciclo de vida dos workspaces. Este invólucro existe apenas para nao
    quebrar quem ja importava `lifecycle.login`; o import e adiado porque
    `auth` importa `lifecycle`.

    A tabela `LOGIN_CHECKS` que ficava aqui foi REMOVIDA, e nao migrada: as
    checagens `claude -p ping` e `agy -p ping` mandavam um PROMPT ao modelo
    para descobrir se havia sessao, e A1 mediu que a do agy bloqueia 60s
    quando deslogado. A verificacao correta e `auth.verify_fresh_client`, que
    pergunta a um cliente NOVO usando o status nativo do fornecedor.
    """
    from . import auth

    return auth.login(root, provider)


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
