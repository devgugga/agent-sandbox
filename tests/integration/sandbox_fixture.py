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
        if not name.startswith(self._prefix):
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
            "sh",
            "-c",
            "trap 'exit 0' TERM INT; while :; do sleep 0.5 & wait $!; done",
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
                f"echo '{content.strip()}' > /sentinel.txt",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def sentinel_exists(self) -> bool:
        """Checks if the sentinel file exists inside the container."""
        res = subprocess.run(
            [self._podman_bin, "exec", self.container, "test", "-f", "/sentinel.txt"],
            capture_output=True,
            text=True,
        )
        return res.returncode == 0

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

    def assert_no_orphans(self) -> None:
        """Verifies that no running container or orphan processes remain."""
        if self.is_container_running():
            raise AssertionError(f"Container {self.container} ainda está em execução")
        res_pgrep = subprocess.run(
            ["pgrep", "-f", f"podman.*{self.container}"],
            capture_output=True,
            text=True,
        )
        if res_pgrep.stdout.strip():
            raise AssertionError(
                f"Processos órfãos encontrados para {self.container}: {res_pgrep.stdout.strip()}"
            )

    def teardown(self) -> None:
        """Cleans up all registered resources strictly."""
        if self._cleaned_up:
            return
        self._cleaned_up = True

        # 1. Stop and reset all registered units
        for unit in list(self._registered_units):
            subprocess.run(
                ["systemctl", "--user", "stop", unit],
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["systemctl", "--user", "reset-failed", unit],
                capture_output=True,
                text=True,
            )

        # 2. Remove unit file
        if self._unit_file.exists():
            self._validate_path(self._unit_file)
            self._unit_file.unlink(missing_ok=True)
        if self._forwarder_unit_file.exists():
            self._validate_path(self._forwarder_unit_file)
            self._forwarder_unit_file.unlink(missing_ok=True)

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
        )

        # 3. Stop and remove all registered containers
        for container in list(self._registered_containers):
            self._validate_resource_name(container)
            subprocess.run(
                [self._podman_bin, "rm", "-f", container],
                capture_output=True,
                text=True,
            )

        # 4. Remove all registered volumes
        for volume in list(self._registered_volumes):
            self._validate_resource_name(volume)
            subprocess.run(
                [self._podman_bin, "volume", "rm", "-f", volume],
                capture_output=True,
                text=True,
            )

        # 5. Remove all registered networks
        for network in list(self._registered_networks):
            self._validate_resource_name(network)
            subprocess.run(
                [self._podman_bin, "network", "rm", "-f", network],
                capture_output=True,
                text=True,
            )

        # 6. Remove temporary root
        if self.state_root.exists():
            self._validate_path(self.state_root)
            shutil.rmtree(self.state_root, ignore_errors=True)

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
