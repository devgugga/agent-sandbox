"""tests/integration/sandbox_fixture.py — isolated test fixture for systemd supervision.

Enforces strict isolation for automated tests:
- UUID per fixture instance: workspace 'test-<label>-<uuid>'.
- All resources prefixed with 'asb-test-<label>-<uuid>-...'.
- Dedicated temporary state root, SSH keys, credentials volume, toolcache,
  keyring volumes, and passphrase.
- Strict resource registration: rejects any resource name outside the prefix
  and any path outside the temporary root.
- Clean teardown: stops and removes units, runs daemon-reload, stops and
  removes containers, volumes, networks, and temporary directories.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import TracebackType


class IsolationError(Exception):
    """Raised when an operation attempts to access or mutate resources outside isolation."""
    pass


class SandboxFixture:
    """Isolated sandbox fixture context manager for integration tests."""

    def __init__(
        self,
        label: str,
        *,
        port: int = 8080,
        image: str = "docker.io/library/alpine:latest",
        exec_start_post: str | None = None,
        restart: str = "always",
        restart_sec: str = "5s",
        use_launcher: bool = False,
        auto_setup: bool = True,
        extra_create_args: list[str] | None = None,
        forwarder_ports: list[int] | tuple[int, ...] | None = None,
    ) -> None:
        if not label or not label.isalnum():
            raise ValueError(f"Label inválido: {label!r} (deve ser alfanumérico)")

        self.label = label
        self.uid = uuid.uuid4().hex[:8]
        self.workspace = f"test-{label}-{self.uid}"
        self._prefix = f"asb-test-{label}-{self.uid}"

        # Resource names adhering strictly to prefix
        self.container = f"{self._prefix}-pilot"
        self.unit = f"{self._prefix}-pilot.service"
        self.forwarder_container = f"{self._prefix}-fwd"
        self.forwarder_unit = f"{self._prefix}-fwd.service"
        self.credentials_volume = f"{self._prefix}-credentials"
        self.toolcache_volume = f"{self._prefix}-toolcache"
        self.keyring_runtime_volume = f"{self._prefix}-keyring-runtime"
        self.keyring_data_volume = f"{self._prefix}-keyring-data"
        # `lifecycle.ensure_session_volume` cria este volume sob demanda, na
        # primeira subida real do workspace. A fixture nao o cria; registra-o
        # para que o teardown o remova e o `assert_no_orphans` o cubra.
        self.session_volume = f"{self._prefix}-session"
        self.keyring_container = f"{self._prefix}-keyring"
        self.net_internal = f"{self._prefix}-net"
        self.net_out = f"{self._prefix}-out"
        self.forwarder_ports = list(forwarder_ports) if forwarder_ports is not None else []

        self._port = port
        self._image = image
        self._exec_start_post = exec_start_post
        self.restart = restart
        self.restart_sec = restart_sec
        self.use_launcher = use_launcher
        self._auto_setup = auto_setup
        self._extra_create_args = list(extra_create_args) if extra_create_args else []
        # Comando do container sintetico. Um cenario que precisa do entrypoint
        # real da imagem (sshd, para a sonda de prontidao) troca isto por [].
        self._entrypoint_cmd: list[str] = [
            "sh", "-c", "trap 'exit 0' TERM INT; while :; do sleep 0.5 & wait $!; done",
        ]
        # Caminho da sentinela na camada gravavel. Sob o entrypoint real a
        # imagem roda como uid 1000, que nao escreve na raiz.
        self._sentinel_path = "/sentinel.txt"

        # Resolved podman binary
        self._podman_bin = shutil.which("podman")
        if not self._podman_bin:
            raise RuntimeError("podman não encontrado no PATH")
        self._podman_bin = str(Path(self._podman_bin).resolve())

        # Temporary state root directory
        self.state_root = Path(tempfile.mkdtemp(prefix=f"{self._prefix}-")).resolve()
        self.ssh_key = self.state_root / "id_ed25519"
        self.passphrase_file = self.state_root / "keyring.pass"
        self.worktree_dir = self.state_root / "worktree"
        self.config_dir = self.state_root / "config"
        self.launcher_script = self.state_root / "launcher.sh"

        # Unit directory in user systemd runtime or config
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        runtime_user_systemd = (
            Path(xdg_runtime) / "systemd" / "user"
            if xdg_runtime
            else Path(f"/run/user/{os.getuid()}/systemd/user")
        )
        if runtime_user_systemd.is_dir():
            self._unit_dir = runtime_user_systemd
        else:
            self._unit_dir = Path.home() / ".config" / "systemd" / "user"
            self._unit_dir.mkdir(parents=True, exist_ok=True)
        self._unit_file = self._unit_dir / self.unit
        self._forwarder_unit_file = self._unit_dir / self.forwarder_unit

        # Strict registration tracking
        self._registered_containers: set[str] = set()
        self._registered_volumes: set[str] = set()
        self._registered_networks: set[str] = set()
        self._registered_units: set[str] = set()
        self._registered_paths: set[Path] = set([self.state_root])

        # Pre-register all isolated units for this workspace and keyring
        self._registered_units.add(self.unit)
        self._registered_units.add(self.forwarder_unit)
        self._registered_units.add(f"asb-{self.workspace}.target")
        self._registered_units.add(f"asb-{self.workspace}-agent.service")
        self._registered_units.add(f"asb-{self.workspace}-proxy.service")
        self._registered_units.add(f"asb-{self.workspace}-forwarder.service")
        self._registered_units.add(f"asb-{self.workspace}-docker.service")
        self._registered_units.add(f"{self._prefix}-keyring.service")

        # Volume criado por `lifecycle`, nao pela fixture: sem este registro o
        # teardown nao sabia da existencia dele e cada execucao de
        # `test_workspace_supervision.py` deixava um `*-session` para tras —
        # o desvio do criterio "zero recursos residuais asb-test-*" que o gate
        # r13 apontou. Registrar nao cria: `_remove_podman` no-opa se ausente.
        self._registered_volumes.add(self.session_volume)

        self._proxy_broken = False
        self._cleaned_up = False
        # Cliente NAO-fresco por fornecedor (Tarefa A4): `provider_client`
        # reaproveita o mesmo nome enquanto `fresh=False`, simulando o
        # cliente "de login" do piloto real.
        self._provider_clients: dict[str, str] = {}

    def register_container(self, name: str) -> str:
        self._validate_resource_name(name)
        self._registered_containers.add(name)
        return name

    def register_volume(self, name: str) -> str:
        self._validate_resource_name(name)
        self._registered_volumes.add(name)
        return name

    def register_network(self, name: str) -> str:
        self._validate_resource_name(name)
        self._registered_networks.add(name)
        return name

    def register_unit(self, name: str) -> str:
        self._validate_resource_name(name)
        self._registered_units.add(name)
        return name

    def _validate_resource_name(self, name: str) -> str:
        if not name.startswith("asb-test-"):
            raise IsolationError(
                f"Recurso {name!r} recusado: deve iniciar com 'asb-test-'"
            )
        if not (name == self._prefix or name.startswith(f"{self._prefix}-") or name.startswith(f"{self._prefix}.")):
            raise IsolationError(
                f"Recurso {name!r} recusado: fora do escopo desta fixture '{self._prefix}'"
            )
        return name

    def _validate_path(self, path: Path | str) -> Path:
        p = Path(path).resolve()
        is_inside_state = self.state_root in p.parents or p == self.state_root
        is_unit_file = p.parent == self._unit_dir and (p.name == self.unit or p.name == self.forwarder_unit)
        if not (is_inside_state or is_unit_file):
            raise IsolationError(f"Caminho {p} recusado: fora da raiz temporária da fixture")
        return p

    def setup_environment(self) -> None:
        """Sets up dedicated isolated paths, keys, launcher, and volumes."""
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Generate dedicated SSH key
        if not self.ssh_key.exists():
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-f",
                    str(self.ssh_key),
                    "-C",
                    self.workspace,
                ],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Ensure SSH key exists in config_dir as well so CLI uses the exact same key
        config_key = self.config_dir / "id_ed25519"
        if not config_key.exists():
            shutil.copy2(self.ssh_key, config_key)
            shutil.copy2(self.ssh_key.with_suffix(".pub"), config_key.with_suffix(".pub"))

        # Generate dedicated passphrase
        self.passphrase_file.write_text(
            base64.b64encode(os.urandom(32)).decode().strip() + "\n",
            encoding="utf-8",
        )
        self.passphrase_file.chmod(0o600)

        # Setup worktree directory
        self.worktree_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(self.worktree_dir)], check=True)

        # Create launcher script if use_launcher is requested
        self.launcher_script.write_text(
            f"#!/bin/sh\n"
            f"CONTAINER=\"$1\"\n"
            f"STATUS=$({self._podman_bin} inspect \"$CONTAINER\" --format '{{{{.State.Status}}}}' 2>/dev/null)\n"
            f"if [ \"$STATUS\" = \"running\" ]; then\n"
            f"    exec {self._podman_bin} attach --sig-proxy=false \"$CONTAINER\"\n"
            f"else\n"
            f"    exec {self._podman_bin} start --attach --sig-proxy=false \"$CONTAINER\"\n"
            f"fi\n",
            encoding="utf-8",
        )
        self.launcher_script.chmod(0o755)

        # Create isolated volumes
        for vol in (
            self.credentials_volume,
            self.toolcache_volume,
            self.keyring_runtime_volume,
            self.keyring_data_volume,
        ):
            self.register_volume(vol)
            subprocess.run(
                [self._podman_bin, "volume", "create", vol],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def setup_container(self) -> None:
        """Creates the synthetic persistent container."""
        self.register_container(self.container)
        cmd = [
            self._podman_bin,
            "create",
            "--name",
            self.container,
            "--pull=never",
            "-p",
            f"127.0.0.1::{self._port}",
            *self._extra_create_args,
            self._image,
            *self._entrypoint_cmd,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def render_unit(self) -> str:
        """Renders the systemd unit content for the pilot."""
        exec_start_post_line = (
            f"ExecStartPost={self._exec_start_post}\n"
            if self._exec_start_post
            else ""
        )
        if self.use_launcher:
            exec_start_cmd = f"{self.launcher_script} {self.container}"
        else:
            exec_start_cmd = f"{self._podman_bin} start --attach --sig-proxy=false {self.container}"

        return (
            "[Unit]\n"
            f"Description=ASB supervision pilot ({self.workspace})\n"
            "StartLimitIntervalSec=600s\n"
            "StartLimitBurst=3\n"
            "\n"
            "[Service]\n"
            "Type=exec\n"
            f"ExecStart={exec_start_cmd}\n"
            f"{exec_start_post_line}"
            f"ExecStop={self._podman_bin} stop --ignore --time=10 {self.container}\n"
            f"ExecStopPost={self._podman_bin} stop --ignore --time=10 {self.container}\n"
            f"Restart={self.restart}\n"
            f"RestartSec={self.restart_sec}\n"
            "TimeoutStartSec=150s\n"
            "TimeoutStopSec=20s\n"
            "KillMode=process\n"
        )

    def install_unit(self) -> None:
        """Installs and reloads the unit in user systemd."""
        self.register_unit(self.unit)
        self._validate_path(self._unit_file)
        content = self.render_unit()
        self._unit_file.write_text(content, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    def start(self) -> None:
        """Starts the supervised systemd unit."""
        subprocess.run(
            ["systemctl", "--user", "start", self.unit],
            check=True,
            capture_output=True,
            text=True,
        )

    def stop(self) -> None:
        """Stops the supervised systemd unit."""
        subprocess.run(
            ["systemctl", "--user", "stop", self.unit],
            check=False,
            capture_output=True,
            text=True,
        )

    def fail_container(self) -> None:
        """Simulates container failure by sending SIGKILL."""
        subprocess.run(
            [self._podman_bin, "kill", self.container],
            check=True,
            capture_output=True,
            text=True,
        )
        # Ensure systemd observed process exit
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", self.unit],
                capture_output=True,
                text=True,
            )
            if res.stdout.strip() != "active":
                break
            time.sleep(0.1)

    def exit_zero(self) -> None:
        """Stops container cleanly (exit 0) to test unexpected zero-exit."""
        subprocess.run(
            [self._podman_bin, "stop", "-t", "2", self.container],
            check=True,
            capture_output=True,
            text=True,
        )
        # Ensure systemd observed process exit
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", self.unit],
                capture_output=True,
                text=True,
            )
            if res.stdout.strip() != "active":
                break
            time.sleep(0.1)

    def is_container_running(self) -> bool:
        """Checks if container is currently in status 'running'."""
        res = subprocess.run(
            [
                self._podman_bin,
                "ps",
                "--filter",
                f"name=^{self.container}$",
                "--filter",
                "status=running",
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )
        return bool(res.stdout.strip())

    def wait_active(self, timeout: float = 30.0) -> bool:
        """Waits until the unit is active and container is running."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", self.unit],
                capture_output=True,
                text=True,
            )
            if res.stdout.strip() == "active" and self.is_container_running():
                return True
            time.sleep(0.2)
        return False

    def inspect_identity(self) -> tuple[str, int]:
        """Returns the container ID and host port mapping as (cid, port)."""
        res_id = subprocess.run(
            [self._podman_bin, "inspect", self.container, "--format", "{{.Id}}"],
            check=True,
            capture_output=True,
            text=True,
        )
        cid = res_id.stdout.strip()
        res_port = subprocess.run(
            [self._podman_bin, "port", self.container, str(self._port)],
            check=False,
            capture_output=True,
            text=True,
        )
        port_lines = res_port.stdout.strip().splitlines()
        if port_lines:
            mapping = port_lines[0]
            port_num = int(mapping.rsplit(":", 1)[-1])
        else:
            # Fallback for stopped/created container via inspect NetworkSettings
            res_insp = subprocess.run(
                [
                    self._podman_bin,
                    "inspect",
                    self.container,
                    "--format",
                    "{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}}{{end}}{{end}}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            raw = res_insp.stdout.strip()
            port_num = int(raw) if raw else 0
        return cid, port_num

    def write_sentinel(self, content: str = "sentinel-active\n") -> None:
        """Writes a sentinel file inside the container."""
        subprocess.run(
            [
                self._podman_bin,
                "exec",
                self.container,
                "sh",
                "-c",
                f"echo '{content.strip()}' > {self._sentinel_path}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def sentinel_exists(self) -> bool:
        """Checks if the sentinel file exists inside the container."""
        res = subprocess.run(
            [self._podman_bin, "exec", self.container, "test", "-f", self._sentinel_path],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return True
        if res.returncode == 1:
            return False
        raise RuntimeError(
            f"podman exec test -f {self._sentinel_path} falhou com codigo {res.returncode}: {res.stderr.strip()}"
        )

    def exec(
        self,
        *args: str,
        user: str | None = None,
        check: bool = False,
        container: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Runs a command inside a container via podman exec.

        `container` defaults to the fixture's main supervised container
        (`self.container`); pass the name returned by `provider_client()` to
        reach one of those instead.
        """
        cmd = [self._podman_bin, "exec"]
        if user is not None:
            cmd.extend(["-u", user])
        cmd.append(container if container is not None else self.container)
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    # Espelha `cli/asb/lifecycle.py::CREDENTIAL_DIRS` sem importar `asb`: a
    # fixture fala com o CLI real por subprocesso (`self.cli()`), nunca
    # importa o pacote diretamente.
    _CREDENTIAL_DIRS: dict[str, str] = {"claude": ".claude", "codex": ".codex"}

    def _credentials_mountpoint(self) -> Path:
        raw = subprocess.run(
            [self._podman_bin, "volume", "inspect", self.credentials_volume,
             "--format", "{{.Mountpoint}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return Path(raw)

    def provider_client(self, provider: str, fresh: bool) -> str:
        """Sobe (ou reaproveita) um cliente PROPRIO da fixture, montando
        SOMENTE as credenciais SINTETICAS desta fixture (Tarefa A4) — nunca
        `asb-credentials` de producao.

        Espelha o cliente efemero de `cli/asb/auth.py::_client_run_args`
        (mesmos mounts: credenciais em `/run/asb-credentials`, keyring em
        `/run/asb-keyring` somente leitura, `keyrings/` como tmpfs vazio),
        mas usa os volumes ISOLADOS que `setup_environment()` ja criou para
        esta fixture, registrados e limpos pelo `teardown()` normal.

        `fresh=True` sempre cria um container NOVO com sufixo aleatorio,
        simulando o cenario "cliente novo" do piloto (A1/A4: prova que a
        persistencia sobrevive a um container que nunca viu o login).
        `fresh=False` reaproveita um unico cliente por fornecedor durante o
        tempo de vida da fixture — o cenario "cliente de login" — criando-o
        somente na primeira chamada.
        """
        if provider not in ("claude", "codex", "agy"):
            raise ValueError(
                f"fornecedor invalido: {provider!r} "
                "(use 'claude', 'codex' ou 'agy')")

        if not fresh and provider in self._provider_clients:
            return self._provider_clients[provider]

        # Os subdiretorios por fornecedor tem de existir no HOST antes do
        # mount: `volume-subpath` nao cria o caminho, e um subpath ausente
        # aborta o `podman run` (mesma causa documentada em
        # `lifecycle.ensure_credential_dirs`). Feito uma vez por fixture.
        mountpoint = self._credentials_mountpoint()
        for sub in self._CREDENTIAL_DIRS:
            target = mountpoint / sub
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.chmod(0o700)

        suffix = "fresh" if fresh else "login"
        name = self.register_container(
            f"{self._prefix}-{provider}-{suffix}-{uuid.uuid4().hex[:6]}")

        # Mesmo HOME que o `cli/asb/auth.py::_client_run_args` real usa: a
        # imagem e construida espelhando `id -un` do host (lifecycle.build),
        # entao o caminho dentro do container e literalmente o HOME do host.
        home = Path(os.path.expanduser("~"))
        credential_mounts: list[str] = []
        for sub, rel in self._CREDENTIAL_DIRS.items():
            credential_mounts += [
                "--mount",
                f"type=volume,src={self.credentials_volume},dst={home / rel},"
                f"volume-subpath={sub},relabel=shared",
            ]

        # Sem `--cap-drop`/`--security-opt no-new-privileges`: o entrypoint
        # da imagem precisa de CAP_CHOWN para ajustar a posse de `.claude` /
        # `.codex` antes de baixar para uid 1000 (medido: com as capabilities
        # retiradas, `install` falha com "Operation not permitted" e o
        # container sai). Mesmo perfil de `cli/asb/auth.py::_client_run_args`.
        cmd = [
            self._podman_bin, "run", "-d", "--name", name,
            "--userns", "keep-id:uid=1000,gid=1000",
            "-v", f"{self.keyring_runtime_volume}:/run/asb-keyring:ro,z",
            "-e", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/asb-keyring/bus",
            "-v", f"{self.credentials_volume}:/run/asb-credentials:z",
            "--mount", "type=tmpfs,destination=/run/asb-credentials/keyrings,"
                       "ro,notmpcopyup,tmpfs-mode=000",
            *credential_mounts,
            self._image,
            "sleep", "infinity",
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        if not fresh:
            self._provider_clients[provider] = name
        return name

    def setup_forwarder(
        self,
        ports: list[int] | tuple[int, ...] | None = None,
        *,
        use_old_script: bool = False,
    ) -> None:
        """Sets up and starts the forwarder container with the declared ports."""
        if ports is not None:
            self.forwarder_ports = list(ports)
        if not self.forwarder_ports:
            return

        self.register_container(self.forwarder_container)

        port_args = [str(p) for p in self.forwarder_ports]

        if use_old_script:
            script = " ".join(
                f"socat TCP-LISTEN:{port},fork,reuseaddr TCP:host.containers.internal:{port} &"
                for port in self.forwarder_ports
            )
            cmd = [
                self._podman_bin,
                "run",
                "-d",
                "--name",
                self.forwarder_container,
                "--restart",
                "always",
                "--sysctl",
                "net.ipv4.ip_unprivileged_port_start=0",
                "--user",
                "900",
                "agent-sandbox-proxy:latest",
                "sh",
                "-c",
                f"trap 'exit 0' TERM; {script} wait",
            ]
        else:
            cmd = [
                self._podman_bin,
                "run",
                "-d",
                "--name",
                self.forwarder_container,
                "--restart",
                "always",
                "--sysctl",
                "net.ipv4.ip_unprivileged_port_start=0",
                "--user",
                "900",
                "--entrypoint",
                "/usr/local/bin/asb-forwarder",
                "agent-sandbox-proxy:latest",
                *port_args,
            ]

        subprocess.run(cmd, check=True, capture_output=True, text=True)

        for p in self.forwarder_ports:
            if not self.wait_forwarder_listener(p, timeout=15.0):
                raise RuntimeError(f"Forwarder listener não subiu na porta {p}")

    def forwarder_restart_count(self) -> int:
        """Returns the restart count of the forwarder from systemd or podman."""
        restarts = 0
        if self.forwarder_unit in self._registered_units:
            res_unit = subprocess.run(
                ["systemctl", "--user", "show", self.forwarder_unit, "-p", "NRestarts"],
                capture_output=True,
                text=True,
            )
            if res_unit.returncode == 0 and res_unit.stdout.strip().startswith("NRestarts="):
                val = res_unit.stdout.strip().split("=", 1)[1]
                if val.isdigit():
                    restarts = max(restarts, int(val))

        res = subprocess.run(
            [self._podman_bin, "inspect", self.forwarder_container, "--format", "{{.RestartCount}}"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out.isdigit():
                restarts = max(restarts, int(out))

        return restarts

    def fail_forwarder_listener(self, port: int) -> None:
        """Kills the specific socat process listening on port inside the forwarder container.

        Uses PID inside the container only, never pgrep on the host.
        """
        find_cmd = [
            self._podman_bin,
            "exec",
            self.forwarder_container,
            "bash",
            "-c",
            f"ss -tlnp 'sport = :{port}' 2>/dev/null | grep -o 'pid=[0-9]\\+' | head -n1 | cut -d= -f2",
        ]
        res = subprocess.run(find_cmd, capture_output=True, text=True)
        pid = res.stdout.strip()
        if not pid or not pid.isdigit():
            raise RuntimeError(
                f"Listener para a porta {port} não encontrado no container {self.forwarder_container}"
            )

        kill_cmd = [
            self._podman_bin,
            "exec",
            self.forwarder_container,
            "kill",
            "-9",
            pid,
        ]
        subprocess.run(kill_cmd, capture_output=True, text=True)

    def wait_forwarder_listener(self, port: int, timeout: float = 30.0) -> bool:
        """Waits until the forwarder has an active LISTEN socket on port."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = subprocess.run(
                [
                    self._podman_bin,
                    "exec",
                    self.forwarder_container,
                    "ss",
                    "-tln",
                    f"sport = :{port}",
                ],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and "LISTEN" in res.stdout:
                return True
            time.sleep(0.2)
        return False

    def break_proxy(self) -> None:
        """Simulates proxy failure for readiness testing."""
        self._proxy_broken = True
        proxy_name = f"{self._prefix}-proxy"
        if proxy_name in self._registered_containers:
            subprocess.run(
                [self._podman_bin, "stop", "-t", "1", proxy_name],
                check=False,
                capture_output=True,
            )

    def worktree_exists(self) -> bool:
        """Checks if worktree exists."""
        return self.worktree_dir.is_dir()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Executes the ASB CLI within the isolated environment."""
        env = dict(os.environ)
        env["ASB_CREDENTIALS_VOLUME"] = self.credentials_volume
        env["ASB_TOOLCACHE_VOLUME"] = self.toolcache_volume
        env["ASB_KEYRING_CONTAINER"] = self.keyring_container
        env["ASB_KEYRING_RUNTIME_VOLUME"] = self.keyring_runtime_volume
        env["ASB_KEYRING_DATA_VOLUME"] = self.keyring_data_volume
        env["ASB_KEYRING_PASS_FILE"] = str(self.passphrase_file)
        env["ASB_CONFIG_ROOT"] = str(self.config_dir)
        env["ASB_STATE_ROOT"] = str(self.state_root / "state")
        cli_bin = Path(__file__).resolve().parents[2] / "cli" / "asb-agent"
        return subprocess.run(
            [sys.executable, str(cli_bin), *args],
            env=env,
            capture_output=True,
            text=True,
        )

    # Mesma tabela estrita do supervisor (a fixture nao importa `asb`): pares
    # (exit code, stdout) aceitos; qualquer outro par ou stderr falha fechado.
    _UNIT_ENABLED_STATES = frozenset({
        (0, "enabled"), (0, "enabled-runtime"), (0, "static"), (1, "disabled"), (4, "not-found"),
    })
    # (4, "failed"): o arquivo da unit sumiu (ex.: `down`), mas o manager ainda
    # guarda o service como failed ate um reset-failed.
    _UNIT_ACTIVE_STATES = frozenset({
        (0, "active"), (3, "inactive"), (3, "failed"), (4, "inactive"), (4, "failed"),
        (3, "activating"), (3, "deactivating"), (0, "reloading"),
    })

    def _unit_state(self, unit: str) -> tuple[str, str]:
        """(is-enabled, is-active) da unit no manager, independente de arquivo local."""
        states = []
        for verb, table in (("is-enabled", self._UNIT_ENABLED_STATES), ("is-active", self._UNIT_ACTIVE_STATES)):
            res = subprocess.run(["systemctl", "--user", verb, unit], capture_output=True, text=True)
            out, err = res.stdout.strip(), res.stderr.strip()
            if err or (res.returncode, out) not in table:
                raise IsolationError(
                    f"{verb} {unit}: estado nao suportado (rc={res.returncode}, stdout={out!r}, stderr={err!r})")
            states.append(out)
        return states[0], states[1]

    def _systemctl_ok(self, *args: str) -> None:
        res = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
        if res.returncode != 0:
            raise IsolationError(
                f"systemctl --user {' '.join(args)} falhou (rc={res.returncode}): "
                f"{res.stderr.strip() or res.stdout.strip()}")

    def _quiesce_unit(self, unit: str) -> None:
        """Para e desabilita (persistente e runtime) consultando o estado antes de cada comando.

        So se emite o comando que o estado exige; entao qualquer rc != 0 e
        falha — nenhum codigo ou mensagem de "ausente" e tolerado.
        """
        for _ in range(5):
            enabled, active = self._unit_state(unit)
            if active in ("active", "activating", "deactivating", "reloading"):
                self._systemctl_ok("stop", unit)
            elif active == "failed":
                self._systemctl_ok("reset-failed", unit)
            elif enabled == "enabled":
                self._systemctl_ok("disable", unit)
            elif enabled == "enabled-runtime":
                self._systemctl_ok("disable", "--runtime", unit)
            else:
                return
        raise IsolationError(f"unit {unit} nao ficou parada e desabilitada")

    def _podman_exists(self, kind: str, name: str) -> bool:
        res = subprocess.run([self._podman_bin, kind, "exists", name], capture_output=True, text=True)
        if res.returncode == 0:
            return True
        if res.returncode == 1:
            return False
        raise IsolationError(
            f"podman {kind} exists {name} falhou (rc={res.returncode}): {res.stderr.strip()}")

    def _remove_podman(self, kind: str, name: str) -> None:
        self._validate_resource_name(name)
        if not self._podman_exists(kind, name):
            return
        argv = ([self._podman_bin, "rm", "-f", name] if kind == "container"
                else [self._podman_bin, kind, "rm", "-f", name])
        res = subprocess.run(argv, capture_output=True, text=True)
        if res.returncode != 0:
            raise IsolationError(
                f"podman {' '.join(argv[1:])} falhou (rc={res.returncode}): "
                f"{res.stderr.strip() or res.stdout.strip()}")
        if self._podman_exists(kind, name):
            raise IsolationError(f"{kind} {name} ainda existe apos remocao")

    def _unit_roots(self) -> tuple[Path, ...]:
        """Onde units registradas podem morar: runtime do manager e config do usuario."""
        return (self._unit_dir, Path.home() / ".config" / "systemd" / "user")

    def assert_no_orphans(self, *, all_registered: bool = False) -> None:
        """Nenhum processo supervisionado ficou para tras.

        Padrao: o container supervisionado da fixture — e a checagem que as
        suites fazem no meio do teste, com clientes auxiliares ainda de pe.
        Com `all_registered=True` (teardown e cenarios de adocao): todo
        container registrado. Nos dois casos nenhuma unit registrada pode
        estar ativa, e erro de consulta nunca vale como ausencia.
        """
        containers = sorted(self._registered_containers) if all_registered else [self.container]
        problems: list[str] = []
        for name in containers:
            res = subprocess.run(
                [self._podman_bin, "ps", "--filter", f"name=^{name}$", "--filter", "status=running", "--quiet"],
                capture_output=True, text=True)
            if res.returncode != 0:
                problems.append(f"podman ps {name} falhou (rc={res.returncode}): {res.stderr.strip()}")
            elif res.stdout.strip():
                problems.append(f"container {name} ainda em execucao")
        for unit in sorted(self._registered_units):
            try:
                _, active = self._unit_state(unit)
            except IsolationError as exc:
                problems.append(str(exc))
                continue
            if active == "active":
                problems.append(f"unit {unit} ainda ativa")
        pattern = f"podman.*{self._prefix if all_registered else self.container}"
        res = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if res.returncode == 0:
            problems.append(f"processos orfaos para {pattern}: {res.stdout.strip()}")
        elif res.returncode != 1:
            problems.append(f"pgrep falhou (rc={res.returncode}): {res.stderr.strip()}")
        if problems:
            raise AssertionError("; ".join(problems))

    def teardown(self) -> None:
        """Remove todo recurso registrado e PROVA a ausencia; qualquer falha levanta IsolationError."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        errors: list[str] = []

        def attempt(action, *args, **kwargs) -> None:
            try:
                action(*args, **kwargs)
            except (IsolationError, OSError, AssertionError) as exc:
                errors.append(str(exc))

        # 1. Units: parar e desabilitar no manager, em qualquer escopo.
        for unit in sorted(self._registered_units):
            attempt(self._quiesce_unit, unit)

        # 2. Arquivos de unit e links wants dos nomes registrados, nas duas raizes.
        for root in self._unit_roots():
            for unit in sorted(self._registered_units):
                wants = root / "default.target.wants" / unit
                if wants.is_symlink() or wants.exists():
                    errors.append(f"wants link residual {wants}: a unit nao foi desabilitada pelo manager")
                    attempt(wants.unlink)
                unit_file = root / unit
                if unit_file.is_symlink() or unit_file.exists():
                    attempt(unit_file.unlink)
        attempt(self._systemctl_ok, "daemon-reload")

        # 3. Pos-condicao no manager, independente dos arquivos locais.
        for unit in sorted(self._registered_units):
            try:
                state = self._unit_state(unit)
            except IsolationError as exc:
                errors.append(str(exc))
                continue
            if state != ("not-found", "inactive"):
                errors.append(f"unit {unit} ainda conhecida do manager apos teardown "
                              f"(is-enabled={state[0]}, is-active={state[1]})")

        # 4. Podman: containers antes de volumes e redes (que eles usam).
        for kind, names in (("container", self._registered_containers),
                            ("volume", self._registered_volumes),
                            ("network", self._registered_networks)):
            for name in sorted(names):
                attempt(self._remove_podman, kind, name)

        # 5. Raiz temporaria.
        if self.state_root.exists():
            self._validate_path(self.state_root)
            try:
                shutil.rmtree(self.state_root)
            except OSError as exc:
                errors.append(f"Falha ao remover state_root {self.state_root}: {exc}")
        if self.state_root.exists():
            errors.append(f"State root {self.state_root} ainda existe após teardown")

        # 6. Nenhum processo ou unit registrada sobreviveu.
        attempt(self.assert_no_orphans, all_registered=True)

        if errors:
            raise IsolationError(f"Falha de teardown da SandboxFixture: {'; '.join(errors)}")

    def __enter__(self) -> SandboxFixture:
        """Setup guarded: o protocolo de context manager do Python NAO chama
        `__exit__` quando o proprio `__enter__` levanta. `setup_environment`
        cria os quatro volumes ANTES de tudo; sem esta guarda, qualquer
        excecao em `setup_container`, `install_unit` ou `setup_forwarder`
        deixava volumes e containers `asb-test-` na maquina do operador sem
        rastreio nem caminho de limpeza (foi assim que 8 volumes vazaram)."""
        try:
            self.setup_environment()
            if self._auto_setup:
                self.setup_container()
                self.install_unit()
                if self.forwarder_ports:
                    self.setup_forwarder()
        except BaseException:
            self.teardown()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.teardown()
