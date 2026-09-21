"""cli/asb/runtime/workspace.py — preparo de recursos do workspace
(containers, redes, volumes, manifesto, unidades systemd) e a supervisao
que os liga/desliga.

Extraido de `cli/asb/lifecycle.py::prepare_workspace` (Tarefa 4 da
decomposicao de modulos), verbatim: mesmo argv de Podman, mesma ordem, mesmo
texto de erro, mesma politica de posse na transacao. `lifecycle.py` continua
reexportando `prepare_workspace`, `build_proxy`, `start_services` e
`start_forwarder` (mesmo padrao ja usado nas extracoes anteriores) para quem
ja importava daqui.

`IMAGE`, `PROXY_IMAGE`, `PROXY_PORT`, `names()`, `ensure_ssh_key()` e
`ensure_runtime()` continuam em `lifecycle.py` — sao usados tambem por
`up()`/`resume()` fora da preparacao, entao mover-los aqui so trocaria um
acoplamento cruzado por outro. Este modulo os alcanca por import ADIADO de
`lifecycle` (`from .. import lifecycle`, dentro dos metodos — nunca no topo,
que criaria um ciclo: `lifecycle.py` importa `WorkspaceRuntime` daqui no
nivel de modulo). O import adiado tem uma vantagem alem de evitar o ciclo:
como o nome `lifecycle` fica ligado ao MODULO (nao a uma copia da funcao),
`lifecycle.ensure_ssh_key()` chamado por este arquivo continua respeitando
`mock.patch("cli.asb.lifecycle.ensure_ssh_key", ...)` nos testes — a mesma
propriedade que ja tornou a mudanca pura de `WorkspaceTransaction` compativel
com a suite sem editar um teste sequer.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import podman, supervisor
from ..profile import Profile, load_profile
from ..squid import render
from ..staging import build_staging
from ..workspace import Layout, layout_for, prepare_clone
from .storage import RuntimeStorage
from .transaction import WorkspaceTransaction


def build_proxy(root: Path) -> None:
    """Garante a imagem do proxy: constroi so se ainda nao existir."""
    from .. import lifecycle

    if podman.exists("image", lifecycle.PROXY_IMAGE):
        return
    podman.run("build", "-t", lifecycle.PROXY_IMAGE,
               "-f", str(root / "image" / "Containerfile.proxy"), str(root))


def start_services(
    ws: str,
    profile: Profile,
    cmd_action: str = "create",
    restart: str = "no",
    tx: WorkspaceTransaction | None = None,
) -> dict[str, dict[str, str]]:
    from .. import lifecycle

    n = lifecycle.names(ws)
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
    from .. import lifecycle

    if not profile.host_ports:
        return ""
    for port in profile.host_ports:
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            raise ValueError(f"Porta invalida para forwarder: {port!r}")
    n = lifecycle.names(ws)
    forwarder = f"{n['net']}-fwd"
    port_args = [str(port) for port in profile.host_ports]
    cmd_flags = ["-d"] if cmd_action == "run" else []
    podman.run(cmd_action, *cmd_flags, "--name", forwarder,
               "--label", f"asb.workspace={ws}",
               "--restart", restart,
               "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
               "--network", f"{n['net']},{n['out']}", "--user", "900",
               "--entrypoint", "/usr/local/bin/asb-forwarder",
               lifecycle.PROXY_IMAGE, *port_args)
    cid = _get_container_id(forwarder)
    if tx:
        tx.record_container(cid)
    return cid


def _get_container_id(name: str) -> str:
    try:
        cid = podman.out("inspect", name, "--format", "{{.Id}}").strip()
        if cid:
            return cid
    except Exception:
        pass
    return name


@dataclass
class _SetupResult:
    """Valores produzidos pela preparacao inicial (imagem, clone,
    squid.conf, redes) que as secoes seguintes de `prepare()` consomem —
    so estrutura de passagem de valor, nenhuma logica nova."""

    home: Path
    storage: RuntimeStorage
    profile: Profile
    layout: Layout
    conf: Path
    n: dict[str, str]
    cmd_action: str
    cmd_flags: list[str]
    restart_policy: str


@dataclass
class _OptionalContainersResult:
    """Resultado de §2-4: servicos adicionais, forwarder e broker Docker —
    so estrutura de passagem de valor, nenhuma logica nova."""

    services_manifest: dict[str, dict[str, str]]
    fwd_name: str
    fwd_cid: str
    docker_cid: str
    docker_name: str


@dataclass
class _AgentResult:
    """Resultado de §5: staging, chave SSH, diretorio do runtime e o id do
    container do agente — so estrutura de passagem de valor."""

    stage: Path
    key: Path
    runtime_dir: Path
    agent_cid: str


class WorkspaceRuntime:
    """Orquestra o preparo de recursos de um workspace: containers, redes,
    volumes, manifesto e unidades systemd. Extraido de `lifecycle.py`
    (Tarefa 4 da decomposicao de modulos) para deixa-lo uma fachada real."""

    def _prepare_setup_and_network(
        self,
        root: Path,
        ws: str,
        repo: Path,
        tx: WorkspaceTransaction | None,
        storage: RuntimeStorage | None,
    ) -> _SetupResult:
        """Checa a imagem, garante o proxy, prepara o clone, grava o
        squid.conf e cria as duas redes do workspace — a parte NAO numerada
        de `prepare_workspace`, seguida do bloco que fixa `cmd_action`/
        `cmd_flags`/`restart_policy` (Emenda A: todo container nasce
        parado, sem politica de reinicio do Podman)."""
        from .. import lifecycle

        if not podman.exists("image", lifecycle.IMAGE):
            raise podman.PodmanError(
                f"imagem {lifecycle.IMAGE} ausente; execute 'asb-agent build'")

        build_proxy(root)
        home = Path(os.path.expanduser("~"))
        storage = storage if storage is not None else RuntimeStorage(home)
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

        n = lifecycle.names(ws)
        if not podman.exists("network", n["net"]):
            podman.run("network", "create", "--internal", n["net"])
            if tx:
                tx.record_network(n["net"])
        if not podman.exists("network", n["out"]):
            podman.run("network", "create", n["out"])
            if tx:
                tx.record_network(n["out"])

        # Runtime unico (Emenda A): todo container ASB nasce parado e sem
        # politica de reinicio do Podman; quem o inicia e reinicia e sempre
        # o systemd.
        cmd_action = "create"
        cmd_flags: list[str] = []
        restart_policy = "no"

        return _SetupResult(home=home, storage=storage, profile=profile,
                            layout=layout, conf=conf, n=n,
                            cmd_action=cmd_action, cmd_flags=cmd_flags,
                            restart_policy=restart_policy)

    def _create_proxy_container(
        self,
        n: dict[str, str],
        ws: str,
        conf: Path,
        cmd_action: str,
        cmd_flags: list[str],
        restart_policy: str,
        tx: WorkspaceTransaction | None,
    ) -> str:
        """§1 Proxy: cria o container do squid e devolve o id."""
        from .. import lifecycle

        proxy_args = [
            cmd_action,
            *cmd_flags,
            "--name", n["proxy"],
            "--label", f"asb.workspace={ws}",
            "--restart", restart_policy,
            "--network", f"{n['net']},{n['out']}", "--user", "900",
            "-v", f"{conf}:/etc/squid/squid.conf:ro,Z",
            lifecycle.PROXY_IMAGE, "squid", "-N", "-f", "/etc/squid/squid.conf",
        ]
        podman.run(*proxy_args)
        proxy_cid = _get_container_id(n["proxy"])
        if tx:
            tx.record_container(proxy_cid)
        return proxy_cid

    def _create_optional_containers(
        self,
        ws: str,
        n: dict[str, str],
        profile: Profile,
        cmd_action: str,
        cmd_flags: list[str],
        restart_policy: str,
        tx: WorkspaceTransaction | None,
    ) -> "_OptionalContainersResult":
        """§2-4: servicos adicionais, forwarder e broker Docker — os tres
        containers OPCIONAIS que `prepare()` cria entre o proxy e o
        agente."""
        from .. import lifecycle

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
                "--entrypoint", "sh", lifecycle.PROXY_IMAGE, "-c",
                "socat TCP-LISTEN:2375,fork,reuseaddr UNIX-CONNECT:/var/run/docker.sock",
            ]
            podman.run(*docker_args)
            docker_cid = _get_container_id(docker_name)
            if tx:
                tx.record_container(docker_cid)

        return _OptionalContainersResult(
            services_manifest=services_manifest, fwd_name=fwd_name,
            fwd_cid=fwd_cid, docker_cid=docker_cid, docker_name=docker_name)

    def _create_agent_container(
        self,
        root: Path,
        ws: str,
        n: dict[str, str],
        home: Path,
        layout: Layout,
        profile: Profile,
        storage: RuntimeStorage,
        cmd_action: str,
        cmd_flags: list[str],
        restart_policy: str,
        tx: WorkspaceTransaction | None,
    ) -> "_AgentResult":
        """§5: staging, chave SSH, keyring, e o container do agente —
        inclusive a emenda de nested-mode, POSICIONAL (`agent_args[-1:-1]`
        insere logo ANTES da imagem, que precisa continuar sendo o ultimo
        elemento de `agent_args`)."""
        from .. import lifecycle

        stage = layout.state / "staging"
        shutil.rmtree(stage, ignore_errors=True)
        staged = build_staging(root / "profiles" / "provision.toml", stage, home)
        print(f"configuracao: {staged} entrada(s)", file=sys.stderr)

        key = lifecycle.ensure_ssh_key()
        published = []
        for host_p, cont_p in profile.publish_ports:
            published.extend(["-p", f"127.0.0.1:{host_p}:{cont_p}"])

        runtime_dir = lifecycle.ensure_runtime(root)
        lifecycle.ensure_keyring_service(runtime_dir)

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
            "-e", f"HTTPS_PROXY=http://{n['proxy']}:{lifecycle.PROXY_PORT}",
            "-e", f"HTTP_PROXY=http://{n['proxy']}:{lifecycle.PROXY_PORT}",
            "-e", "NO_PROXY=127.0.0.1,localhost",
            "-v", f"{layout.mount}:{layout.mount}:Z",
            "-v", f"{stage}:/run/asb-config:ro,Z",
            "-v", f"{lifecycle.ensure_keyring_runtime_volume()}:/run/asb-keyring:ro,z",
            "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={lifecycle.KEYRING_BUS}",
            "-v", f"{storage.ensure_credentials()}:/run/asb-credentials:z",
            "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,ro,notmpcopyup,tmpfs-mode=000",
            *storage.credential_mounts(),
            # Por cima dos mounts acima: a credencial e compartilhada, a
            # transcricao nao. Sem isto o agente do workspace A LE os
            # projetos, todos e sessoes do workspace B.
            *storage.session_mounts(storage.ensure_sessions(ws, tx)),
            "-v", f"{storage.ensure_toolcache()}:/run/asb-toolcache:Z",
            *(["-e", f"DOCKER_HOST=tcp://{n['net']}-docker:2375"]
              if profile.host_api == "read" else []),
            "-e", "ASB_HOST_PORTS=" + ",".join(str(p) for p in profile.host_ports),
            "-e", f"ASB_WORKSPACE={ws}",
            lifecycle.IMAGE,
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

        return _AgentResult(stage=stage, key=key, runtime_dir=runtime_dir,
                            agent_cid=agent_cid)

    def _write_manifest(
        self,
        ws: str,
        n: dict[str, str],
        layout: Layout,
        profile: Profile,
        proxy_cid: str,
        agent_cid: str,
        fwd_name: str,
        fwd_cid: str,
        docker_name: str,
        docker_cid: str,
        services_manifest: dict[str, dict[str, str]],
        key: Path,
        runtime_dir: Path,
    ) -> None:
        """§6: grava `runtime.json` — a entrada de manifesto do proxy e do
        agente sao sempre gravadas; forwarder/docker/servicos entram so se
        existirem."""
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

    def prepare(
        self,
        root: Path,
        ws: str,
        repo: Path,
        tx: WorkspaceTransaction | None = None,
        storage: RuntimeStorage | None = None,
    ) -> None:
        """Prepara clone, redes, containers e manifesto sem restauracao
        global. Movido verbatim de `lifecycle.prepare_workspace`."""
        setup = self._prepare_setup_and_network(root, ws, repo, tx, storage)
        home, storage, profile, layout, conf, n = (
            setup.home, setup.storage, setup.profile, setup.layout,
            setup.conf, setup.n)
        cmd_action, cmd_flags, restart_policy = (
            setup.cmd_action, setup.cmd_flags, setup.restart_policy)

        # 1. Proxy
        proxy_cid = self._create_proxy_container(
            n, ws, conf, cmd_action, cmd_flags, restart_policy, tx)

        # 2-4. Servicos adicionais, forwarder e broker Docker
        optional = self._create_optional_containers(
            ws, n, profile, cmd_action, cmd_flags, restart_policy, tx)
        services_manifest, fwd_name, fwd_cid, docker_cid, docker_name = (
            optional.services_manifest, optional.fwd_name, optional.fwd_cid,
            optional.docker_cid, optional.docker_name)

        # 5. Staging, SSH, Keyring, container do agente
        agent = self._create_agent_container(
            root, ws, n, home, layout, profile, storage,
            cmd_action, cmd_flags, restart_policy, tx)
        stage, key, runtime_dir, agent_cid = (
            agent.stage, agent.key, agent.runtime_dir, agent.agent_cid)

        # 6. Gravar manifesto runtime.json
        self._write_manifest(
            ws, n, layout, profile, proxy_cid, agent_cid, fwd_name, fwd_cid,
            docker_name, docker_cid, services_manifest, key, runtime_dir)

        # 7. Instalar unidades systemd (runtime unico)
        self._install_units(ws, layout, tx)

    def _install_units(
        self,
        ws: str,
        layout: Layout,
        tx: WorkspaceTransaction | None,
    ) -> None:
        """§7: instala as unidades systemd do workspace, e registra o
        conteudo ANTERIOR do gate de rede compartilhado para restauracao no
        rollback (a espera de rede e compartilhada por todos os
        workspaces)."""
        gate_unit = supervisor.unit_dir() / supervisor.network_unit_name()
        if tx is not None and gate_unit.is_file():
            tx.record_restore(gate_unit, gate_unit.read_text(encoding="utf-8"))
        units = supervisor.install_workspace(ws, state_dir=layout.state)
        if tx and isinstance(units, (list, tuple)):
            for u in units:
                tx.record_unit(u)
